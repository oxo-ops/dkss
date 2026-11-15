"""Bounded synthetic PostgreSQL deployment probes, not production sizing."""
import json
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import test_session_authority_candidate as fixtures


@unittest.skipUnless(os.environ.get('SESSION_AUTHORITY_POSTGRES_TEST_URL'), 'isolated PostgreSQL required')
class RegistryCapacity(unittest.TestCase):
    login = fixtures.SessionAuthorityIntegration.login

    def setUp(self):
        from dkss_app import create_app
        def normal_app(config):
            options = dict(config['SQLALCHEMY_ENGINE_OPTIONS'])
            options.update(pool_size=2, max_overflow=0, pool_timeout=0.2)
            return create_app(dict(config, SESSION_AUTHORITY_CANDIDATE=False,
                                   SQLALCHEMY_ENGINE_OPTIONS=options))
        with patch('dkss_app.create_app', side_effect=normal_app):
            fixtures.SessionAuthorityIntegration.setUp(self)
        self.login()
        self.cookie_name = self.app.config['SESSION_COOKIE_NAME']
        self.cookie = self.client.get_cookie(self.cookie_name).value
        self.db.session.remove()

    def request_once(self, path):
        client = self.app.test_client()
        client.set_cookie(self.cookie_name, self.cookie)
        start = time.perf_counter()
        with self.app.app_context():
            response = client.get(path)
            result = (response.status_code, (time.perf_counter()-start)*1000,
                      'Set-Cookie' in response.headers)
            response.close()
        return result

    def test_bounded_workload(self):
        from dkss_app import auth_session_registry as registry
        from contextlib import nullcontext
        records = []
        # Same synthetic actor, two workers, half static/half polling, 40 requests/mode.
        paths = ['/static/js/base.js', '/api/notifications/unread-count'] * 20
        for mode in ('baseline', 'unprepared', 'prepared', 'enforced'):
            if mode == 'prepared': registry.prepare_schema()
            if mode == 'enforced':
                registry.activate()
                self.client = self.app.test_client(); self.login()
                self.cookie = self.client.get_cookie(self.cookie_name).value
                self.db.session.remove()
            bypass = patch.object(registry, 'require_session', return_value=None) if mode == 'baseline' else nullcontext()
            with bypass, ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(self.request_once, paths))
            self.assertTrue(all(row[0] == 200 for row in results))
            timings = sorted(row[1] for row in results)
            records.append(dict(mode=mode, requests=len(results), concurrency=2,
                                p50_ms=round(timings[19],2), p95_ms=round(timings[37],2),
                                max_ms=round(max(timings),2), failures=0))
        print('REGISTRY_SYNTHETIC_LOAD=' + json.dumps(records, sort_keys=True))

    def test_pool_exhaustion_is_bounded_and_recovers(self):
        engine = self.db.engine
        from sqlalchemy.exc import SQLAlchemyError
        holders = [engine.connect(), engine.connect()]
        failures = []
        original = self.db.session.connection
        def observe_checkout(*args, **kwargs):
            try:
                return original(*args, **kwargs)
            except SQLAlchemyError as exc:
                failures.append(type(exc).__name__)
                raise
        try:
            self.assertEqual(engine.pool.checkedout(), 2)
            with patch.object(self.db.session, 'connection', side_effect=observe_checkout):
                code, elapsed, cookie_write = self.request_once('/api/notifications/unread-count')
        finally:
            for conn in holders: conn.close()
        self.assertEqual(code, 503); self.assertFalse(cookie_write)
        self.assertEqual(failures, ['TimeoutError'])
        self.assertLess(elapsed, 3000)  # bounded CI harness, not a production SLA
        self.assertEqual(self.request_once('/api/notifications/unread-count')[0], 200)
        print('REGISTRY_POOL_EXHAUSTION=' + json.dumps(dict(status=code, elapsed_ms=round(elapsed,2), recovery=200)))

    def test_policy_statement_timeout_is_bounded_and_recovers(self):
        from sqlalchemy import text, event
        from dkss_app import auth_session_registry as registry
        registry.prepare_schema()
        engine = self.db.engine
        blocker = engine.connect(); transaction = blocker.begin()
        blocker.execute(text('LOCK TABLE auth_session_policy IN ACCESS EXCLUSIVE MODE'))
        # Apply a short timeout only to this test's newly checked-out connection.
        def set_timeout(dbapi_connection, record, proxy):
            cursor = dbapi_connection.cursor()
            cursor.execute('SET statement_timeout = 200'); cursor.close()
        event.listen(engine, 'checkout', set_timeout)
        try:
            code, elapsed, cookie_write = self.request_once('/api/notifications/unread-count')
        finally:
            event.remove(engine, 'checkout', set_timeout)
            transaction.rollback(); blocker.close()
        self.assertEqual(code, 503); self.assertFalse(cookie_write)
        self.assertGreaterEqual(elapsed, 150); self.assertLess(elapsed, 3000)
        self.assertEqual(self.request_once('/api/notifications/unread-count')[0], 200)
        print('REGISTRY_STATEMENT_TIMEOUT=' + json.dumps(dict(status=code, elapsed_ms=round(elapsed,2), recovery=200)))
