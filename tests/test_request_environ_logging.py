"""Request caches must preserve string-only WSGI environ keys and access logs."""
from datetime import timedelta
import io
import logging
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask, request, session

from dkss_app import driving_vehicle_links, safety_identity
import driving_identity_resolution


class RequestEnvironCacheTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'isolated-request-cache-test'

    def assert_string_keys(self):
        self.assertTrue(all(isinstance(key, str) for key in request.environ))

    def correction_mocks(self, *, ready=True, columns=None):
        inspector = Mock()
        inspector.has_table.return_value = ready
        inspector.get_columns.return_value = [
            {'name': name} for name in (
                driving_vehicle_links.CORRECTION_IDENTITIES if columns is None else columns)]
        model = Mock(__tablename__='synthetic_corrections')
        model.query.filter_by.return_value.order_by.return_value.all.side_effect = [
            ['company-a'], ['company-b'], ['new-request']]
        return inspector, model

    def test_identity_outside_request_does_not_query(self):
        with patch.object(safety_identity, 'user_id') as lookup:
            self.assertIsNone(safety_identity.current_user_id())
        lookup.assert_not_called()

    def test_identity_cache_keeps_company_username_and_missing_result_separate(self):
        with patch.object(safety_identity, 'user_id', side_effect=[11, 22, None]) as lookup:
            with self.app.test_request_context('/'):
                session.update(company_code='A', username='one')
                self.assertEqual(safety_identity.current_user_id(), 11)
                self.assertEqual(safety_identity.current_user_id(), 11)
                session['company_code'] = 'B'
                self.assertEqual(safety_identity.current_user_id(), 22)
                session['username'] = 'missing'
                self.assertIsNone(safety_identity.current_user_id())
                self.assertIsNone(safety_identity.current_user_id())
                session.update(company_code='A', username='one')
                self.assertEqual(safety_identity.current_user_id(), 11)
                self.assertEqual(lookup.call_count, 3)
                self.assert_string_keys()
            self.assertEqual([call.args for call in lookup.call_args_list],
                             [('A', 'one'), ('B', 'one'), ('B', 'missing')])

    def test_identity_cache_is_not_reused_by_next_request(self):
        with patch.object(safety_identity, 'user_id', side_effect=[11, 22]) as lookup:
            for expected in (11, 22):
                with self.app.test_request_context('/'):
                    session.update(company_code='A', username='one')
                    self.assertEqual(safety_identity.current_user_id(), expected)
                    self.assertEqual(safety_identity.current_user_id(), expected)
                    self.assert_string_keys()
            self.assertEqual(lookup.call_count, 2)

    def test_correction_cache_is_company_scoped_and_request_local(self):
        inspector, model = self.correction_mocks()
        with patch.object(driving_vehicle_links, 'db', SimpleNamespace(engine=object())), \
                patch.object(driving_vehicle_links, 'inspect', return_value=inspector), \
                patch.object(driving_vehicle_links, 'DrivingVehicleCorrection', model):
            with self.app.test_request_context('/'):
                session['company_code'] = 'A'
                first = driving_vehicle_links.correction_state()
                self.assertEqual(first, (True, ['company-a']))
                self.assertIs(driving_vehicle_links.correction_state(), first)
                session['company_code'] = 'B'
                self.assertEqual(driving_vehicle_links.correction_state(), (True, ['company-b']))
                session['company_code'] = 'A'
                self.assertIs(driving_vehicle_links.correction_state(), first)
                self.assert_string_keys()
            with self.app.test_request_context('/'):
                session['company_code'] = 'A'
                self.assertEqual(driving_vehicle_links.correction_state(), (True, ['new-request']))
                self.assert_string_keys()
        self.assertEqual(inspector.has_table.call_count, 3)
        self.assertEqual([call.kwargs for call in model.query.filter_by.call_args_list],
                         [{'company_code': 'A'}, {'company_code': 'B'}, {'company_code': 'A'}])

    def test_correction_unready_states_remain_cached_without_querying(self):
        for ready, columns in ((False, None), (True, [])):
            with self.subTest(table_exists=ready):
                inspector, model = self.correction_mocks(ready=ready, columns=columns)
                with patch.object(driving_vehicle_links, 'db', SimpleNamespace(engine=object())), \
                        patch.object(driving_vehicle_links, 'inspect', return_value=inspector), \
                        patch.object(driving_vehicle_links, 'DrivingVehicleCorrection', model), \
                        self.app.test_request_context('/'):
                    session['company_code'] = 'A'
                    self.assertEqual(driving_vehicle_links.correction_state(), (False, []))
                    self.assertEqual(driving_vehicle_links.correction_state(), (False, []))
                    self.assert_string_keys()
                inspector.has_table.assert_called_once()
                model.query.filter_by.assert_not_called()

    def test_resolver_cache_preserves_company_scope_and_explicit_refresh(self):
        first, other, refreshed = object(), object(), object()
        with patch.object(driving_identity_resolution, 'Resolver',
                          side_effect=[first, other, refreshed]) as create:
            with self.app.test_request_context('/'):
                session['company_code'] = 'A'
                self.assertIs(driving_identity_resolution.resolver(), first)
                self.assertIs(driving_identity_resolution.resolver(), first)
                session['company_code'] = 'B'
                self.assertIs(driving_identity_resolution.resolver(), other)
                session['company_code'] = 'A'
                self.assertIs(driving_identity_resolution.resolver(), first)
                self.assertIs(driving_identity_resolution.resolver(fresh=True), refreshed)
                self.assertIs(driving_identity_resolution.resolver(), refreshed)
                session['company_code'] = 'B'
                self.assertIs(driving_identity_resolution.resolver(), other)
                self.assert_string_keys()
        self.assertEqual([call.args for call in create.call_args_list], [('A',), ('B',), ('A',)])

    def test_resolver_cache_is_not_reused_by_next_request(self):
        values = [object(), object()]
        with patch.object(driving_identity_resolution, 'Resolver', side_effect=values) as create:
            for expected in values:
                with self.app.test_request_context('/'):
                    session['company_code'] = 'A'
                    self.assertIs(driving_identity_resolution.resolver(), expected)
                    self.assertIs(driving_identity_resolution.resolver(), expected)
                    self.assert_string_keys()
        self.assertEqual(create.call_count, 2)

    @unittest.skipUnless(os.name == 'posix', 'Gunicorn requires POSIX')
    def test_real_gunicorn_access_logger_handles_all_populated_caches(self):
        from gunicorn.config import Config
        from gunicorn.glogging import Logger

        # Keep the real atoms/access implementation, but isolate log handlers
        # from global gunicorn loggers used by other tests or running services.
        logger = object.__new__(Logger)
        logger.cfg = Config()
        logger.cfg.set('accesslog', '-')
        logger.access_log = logging.Logger('isolated-access', logging.INFO)
        output = io.StringIO()
        logger.access_log.addHandler(logging.StreamHandler(output))
        logger.error_log = Mock()
        inspector, model = self.correction_mocks()
        with patch.object(safety_identity, 'user_id', return_value=11), \
                patch.object(driving_identity_resolution, 'Resolver', return_value='synthetic-resolver'), \
                patch.object(driving_vehicle_links, 'db', SimpleNamespace(engine=object())), \
                patch.object(driving_vehicle_links, 'inspect', return_value=inspector), \
                patch.object(driving_vehicle_links, 'DrivingVehicleCorrection', model), \
                self.app.test_request_context('/cache-check', headers={'User-Agent': 'synthetic-probe'}):
            session.update(company_code='A', username='one')
            self.assertEqual(safety_identity.current_user_id(), 11)
            self.assertEqual(driving_vehicle_links.correction_state(), (True, ['company-a']))
            self.assertEqual(driving_identity_resolution.resolver(), 'synthetic-resolver')
            response = SimpleNamespace(status='200 OK', headers=[('Content-Type', 'text/plain')], sent=2)
            req = SimpleNamespace(headers=[('User-Agent', 'synthetic-probe')])
            logger.access(response, req, request.environ, timedelta(microseconds=1234))
            self.assert_string_keys()
        self.assertIn('"GET /cache-check HTTP/1.1" 200 2', output.getvalue())
        self.assertIn('synthetic-probe', output.getvalue())
        logger.error_log.error.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'Gunicorn requires POSIX')
    def test_gthread_repeated_requests_log_and_keep_connection_reusable(self):
        from gunicorn.config import Config
        from gunicorn.glogging import Logger
        from gunicorn.http.message import Request
        from gunicorn.http.unreader import IterUnreader
        from gunicorn.workers.gthread import ThreadWorker

        logger = object.__new__(Logger)
        logger.cfg = Config()
        logger.cfg.set('accesslog', '-')
        logger.access_log = logging.Logger('isolated-gthread-access', logging.INFO)
        output = io.StringIO()
        logger.access_log.addHandler(logging.StreamHandler(output))
        logger.error_log = Mock()
        seen = []

        @self.app.get('/cache-check')
        def cache_check():
            session.update(company_code='A', username='one')
            self.assertEqual(safety_identity.current_user_id(), 11)
            self.assertEqual(driving_vehicle_links.correction_state(), (False, []))
            self.assertEqual(driving_identity_resolution.resolver(), 'synthetic-resolver')
            seen.append(request.environ)
            return 'ok'

        # Exercise the actual parser, WSGI response and gthread request handler.
        # Only socket I/O is captured in memory; no server/DB/network is started.
        worker = object.__new__(ThreadWorker)
        worker.cfg = logger.cfg
        worker.log = logger
        worker.wsgi = self.app
        worker.nr = 0
        worker.max_requests = 100
        worker.alive = True
        worker.keepalived_conns = []
        worker.max_keepalived = 10
        inspector, model = self.correction_mocks(ready=False)
        with patch.object(safety_identity, 'user_id', return_value=11) as lookup, \
                patch.object(driving_identity_resolution, 'Resolver', return_value='synthetic-resolver') as resolve, \
                patch.object(driving_vehicle_links, 'db', SimpleNamespace(engine=object())), \
                patch.object(driving_vehicle_links, 'inspect', return_value=inspector), \
                patch.object(driving_vehicle_links, 'DrivingVehicleCorrection', model):
            for _ in range(5):
                req = Request(worker.cfg, IterUnreader([
                    b'GET /cache-check HTTP/1.1\r\nHost: localhost\r\n\r\n']),
                    ('127.0.0.1', 12345))
                sock = Mock()
                sock.recv.return_value = b''
                conn = SimpleNamespace(sock=sock, client=('127.0.0.1', 12345),
                                       server=('127.0.0.1', 8000))
                self.assertTrue(worker.handle_request(req, conn))
                sent = b''.join(call.args[0] for call in sock.sendall.call_args_list)
                self.assertIn(b'HTTP/1.1 200 OK\r\n', sent)
                self.assertTrue(sent.endswith(b'\r\n\r\nok'))
                sock.close.assert_not_called()
        self.assertEqual(lookup.call_count, 5)
        self.assertEqual(inspector.has_table.call_count, 5)
        self.assertEqual(resolve.call_count, 5)
        self.assertEqual(len({id(env) for env in seen}), 5)
        self.assertTrue(all(isinstance(key, str) for env in seen for key in env))
        self.assertEqual(output.getvalue().count('"GET /cache-check HTTP/1.1" 200 2'), 5)
        logger.error_log.error.assert_not_called()
        logger.error_log.exception.assert_not_called()


if __name__ == '__main__':
    unittest.main()
