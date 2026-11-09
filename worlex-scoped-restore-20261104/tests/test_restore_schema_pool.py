"""Offline schema-child pool boundaries. No sockets, database or child launch."""
import contextlib
import copy
import io
import os
import ssl
import sys
import types
import unittest
from unittest.mock import patch

from sqlalchemy.pool import NullPool, QueuePool
import test_restore_postgres as target


class SchemaPoolTests(unittest.TestCase):
    def harness(self, *, fail=None, dispose_error=False, baseline=False, config=None):
        state = types.SimpleNamespace(events=[], configs=[], raw=[], checkouts=[],
                                      disposals=0, creates=0, rollbacks=0, closes=0,
                                      primary=ValueError('synthetic primary'), output=io.StringIO())
        if config is None:
            config = {'SQLALCHEMY_DATABASE_URI': 'synthetic-only',
                      'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': NullPool, 'hide_parameters': True,
                          'connect_args': {'ssl_context': ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                                           'timeout': 130, 'startup_params': {'search_path': 'public'}}}}
        state.source_config = config

        class Raw:
            def rollback(self): state.rollbacks += 1
            def close(self): state.closes += 1

        def creator():
            state.creates += 1
            if fail == 'creator': raise state.primary
            raw = Raw(); state.raw.append(raw)
            return raw

        class Engine:
            def __init__(self, options):
                if baseline:
                    self.pool = NullPool(creator)
                else:
                    self.pool = options['poolclass'](creator, pool_size=options['pool_size'],
                        max_overflow=options['max_overflow'], pre_ping=options['pool_pre_ping'],
                        reset_on_return=options['pool_reset_on_return'])

            @contextlib.contextmanager
            def connect(self):
                connection = self.pool.connect()
                state.checkouts.append(connection.dbapi_connection)
                try: yield connection
                finally: connection.close()

            def dispose(self):
                state.events.append('dispose'); state.disposals += 1
                self.pool.dispose()
                if dispose_error: raise OSError('synthetic dispose failure')

        db = types.SimpleNamespace()

        def initialize(name):
            state.events.append(name)
            if fail == name: raise state.primary
            with db.engine.connect(): pass

        class App:
            @contextlib.contextmanager
            def app_context(self):
                state.events.append('context_enter')
                if fail == 'context_enter': raise state.primary
                try: yield
                finally:
                    state.events.append('session_remove')
                    state.events.append('context_exit')
                    if fail == 'context_exit': raise state.primary

            def test_cli_runner(self):
                def invoke(*, args):
                    state.events.append(('invoke', args))
                    try: initialize('init_db')
                    except BaseException as error:
                        return types.SimpleNamespace(exit_code=1, exception=error)
                    return types.SimpleNamespace(exit_code=0, exception=None)
                return types.SimpleNamespace(invoke=invoke)

        app = App()

        def create_app(received, *, initialize_database):
            state.events.append('create_app')
            state.configs.append((received, initialize_database))
            if fail == 'create_app': raise state.primary
            state.engine = db.engine = Engine(received['SQLALCHEMY_ENGINE_OPTIONS'])
            return app

        modules = {}
        for name in ('dkss_app', 'dkss_app.extensions', 'dkss_app.driving_access', 'dkss_app.vehicle_couplings'):
            modules[name] = types.ModuleType(name)
        modules['dkss_app'].create_app = create_app
        modules['dkss_app.extensions'].db = db
        modules['dkss_app.driving_access'].initialize_driving_access = lambda value: initialize('driving_access')
        modules['dkss_app.vehicle_couplings'].initialize_coupling_schema = lambda value: initialize('coupling_schema')

        def tls(connection):
            state.events.append('tls_precheck')
            self.assertIs(connection.dbapi_connection, state.raw[0])
            if fail == 'tls_precheck': raise state.primary

        with patch.dict(sys.modules, modules), patch.dict(os.environ, {'DATABASE_URL': 'synthetic-only',
                'WORLEX_TEST_CA_FILE': 'synthetic-ca'}), patch.object(target, 'ci_app_config', return_value=config) as factory, \
                patch.object(target, 'assert_pg8000_tls', side_effect=tls) as gate, \
                contextlib.redirect_stdout(state.output), patch.object(target, 'schema_exception_graph',
                    wraps=target.schema_exception_graph) as graph:
            try: target.run_ci_schema_initialization()
            except SystemExit as error: state.exit_code = error.code
            else: state.exit_code = 0
            state.errors = [call.args[0] for call in graph.call_args_list if call.args[0] is not None]
        factory.assert_called_once_with('synthetic-only', 'synthetic-ca')
        state.gate_calls = gate.call_count
        state.diagnostics = target.parse_schema_events(state.output.getvalue())
        return state

    def test_child_only_config_copy_preserves_shared_options_and_ssl_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        source = {'SQLALCHEMY_DATABASE_URI': 'synthetic-only', 'other': ['unchanged'],
                  'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': NullPool, 'hide_parameters': True,
                      'connect_args': {'ssl_context': context, 'timeout': 130,
                                       'startup_params': {'search_path': 'public', 'statement_timeout': '120000'}}}}
        # SSLContext is deliberately retained by identity, not pickled or rebuilt.
        before = copy.deepcopy(source, {id(context): context})
        state = self.harness(config=source)
        child, initialize_database = state.configs[0]
        self.assertEqual(source, before)
        self.assertIsNot(child, source)
        self.assertIsNot(child['SQLALCHEMY_ENGINE_OPTIONS'], source['SQLALCHEMY_ENGINE_OPTIONS'])
        self.assertIs(child['SQLALCHEMY_ENGINE_OPTIONS']['connect_args'], source['SQLALCHEMY_ENGINE_OPTIONS']['connect_args'])
        self.assertIs(child['SQLALCHEMY_ENGINE_OPTIONS']['connect_args']['ssl_context'], context)
        self.assertIs(child['other'], source['other'])
        self.assertFalse(initialize_database)
        self.assertEqual(child['SQLALCHEMY_ENGINE_OPTIONS'], dict(source['SQLALCHEMY_ENGINE_OPTIONS'],
            poolclass=QueuePool, pool_size=5, max_overflow=0, pool_pre_ping=False, pool_reset_on_return='rollback'))
        self.assertEqual(state.exit_code, 0)

    def test_shared_ci_config_remains_nullpool_for_ui_and_keeps_guards(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'oxo-ops/dkss'}
        url = 'postgresql+pg8000://restore_ci:restore-disposable-synthetic-only@127.0.0.1:5432/restore_owned_' + 'a'*32
        args = {'ssl_context': object(), 'timeout': 130, 'startup_params': {'statement_timeout': '120000'}}
        with patch.dict(os.environ, env, clear=True), patch.object(target, 'connection_args', return_value=args):
            first = target.ci_app_config(url, 'synthetic-ca')
            second = target.ci_app_config(url, 'synthetic-ca')
            self.assertIs(first['SQLALCHEMY_ENGINE_OPTIONS']['poolclass'], NullPool)
            self.assertEqual(first, second)
            self.assertNotIn('pool_size', first['SQLALCHEMY_ENGINE_OPTIONS'])
            for invalid in (url.replace('127.0.0.1', 'external.invalid'), url.replace('restore_owned_'+'a'*32, 'production')):
                with self.assertRaises(target.Stop): target.ci_app_config(invalid, 'synthetic-ca')

    def test_tls_precheck_and_initializers_reuse_same_healthy_connection(self):
        state = self.harness()
        self.assertEqual(state.events, ['create_app', 'context_enter', 'tls_precheck', ('invoke', ['init-db']),
                                      'init_db', 'driving_access', 'coupling_schema', 'session_remove', 'context_exit', 'dispose'])
        self.assertEqual((state.creates, state.rollbacks, state.closes, state.disposals), (1, 4, 1, 1))
        self.assertEqual(len(state.checkouts), 4)
        self.assertTrue(all(raw is state.raw[0] for raw in state.checkouts))
        self.assertEqual(state.gate_calls, 1)
        self.assertEqual(state.diagnostics[-1]['status'], 'passed')
        self.assertEqual(state.diagnostics[-1]['phase'], 'complete')

    def test_simulated_initialization_order_and_rollback_semantics_match_nullpool(self):
        pooled = self.harness(); baseline = self.harness(baseline=True)
        self.assertEqual(pooled.events, baseline.events)
        self.assertEqual((pooled.exit_code, pooled.rollbacks, pooled.gate_calls),
                         (baseline.exit_code, baseline.rollbacks, baseline.gate_calls))
        self.assertEqual((pooled.creates, baseline.creates), (1, 4))
        self.assertEqual((pooled.closes, baseline.closes), (1, 4))

    def test_pool_has_distinct_overlapping_checkouts_and_no_overflow(self):
        state = self.harness()
        pool = state.engine.pool
        connections = [pool.connect() for _ in range(5)]
        try:
            self.assertEqual(len({id(c.dbapi_connection) for c in connections}), 5)
            self.assertEqual(pool.size(), 5)
            self.assertEqual(pool.checkedout(), 5)
            self.assertEqual(pool._max_overflow, 0)
            self.assertFalse(pool._pre_ping)
        finally:
            for connection in connections: connection.close()
            pool.dispose()

    def test_create_app_or_context_entry_failure_never_disposes_uncaptured_engine(self):
        for phase in ('create_app', 'context_enter'):
            with self.subTest(phase=phase):
                state = self.harness(fail=phase)
                self.assertEqual(state.exit_code, 1)
                self.assertEqual((state.disposals, state.creates, state.gate_calls), (0, 0, 0))
                self.assertEqual(len(state.configs), 1)
                self.assertIs(state.errors[-1], state.primary)
                self.assertEqual(state.diagnostics[-1]['status'], 'failed')

    def test_creator_failure_has_one_attempt_no_retry_or_fallback(self):
        state = self.harness(fail='creator')
        self.assertEqual((state.exit_code, state.creates, state.disposals, state.gate_calls), (1, 1, 1, 0))
        self.assertEqual(state.events[-3:], ['session_remove', 'context_exit', 'dispose'])
        self.assertIs(state.errors[-1], state.primary)
        self.assertNotIn('init_db', state.events)

    def test_each_initialization_failure_cleans_up_once_without_later_phases(self):
        phases = ['tls_precheck', 'init_db', 'driving_access', 'coupling_schema']
        for index, phase in enumerate(phases):
            with self.subTest(phase=phase):
                state = self.harness(fail=phase)
                self.assertEqual((state.exit_code, state.creates, state.closes, state.disposals), (1, 1, 1, 1))
                self.assertEqual(state.events.count(phase), 1)
                self.assertEqual(state.events[-3:], ['session_remove', 'context_exit', 'dispose'])
                for later in phases[index+1:]: self.assertNotIn(later, state.events)
                error = state.errors[-1]
                self.assertIs(error.__cause__ if phase == 'init_db' else error, state.primary)
                self.assertEqual(state.diagnostics[-1]['status'], 'failed')

    def test_context_teardown_failure_disposes_once_and_remains_primary(self):
        state = self.harness(fail='context_exit')
        self.assertEqual((state.exit_code, state.disposals, state.closes), (1, 1, 1))
        self.assertEqual(state.events[-3:], ['session_remove', 'context_exit', 'dispose'])
        self.assertIs(state.errors[-1], state.primary)

    def test_dispose_failure_never_replaces_primary_failure(self):
        for phase in ('creator', 'tls_precheck', 'init_db', 'driving_access', 'coupling_schema', 'context_exit'):
            with self.subTest(phase=phase):
                state = self.harness(fail=phase, dispose_error=True)
                self.assertEqual((state.exit_code, state.disposals), (1, 1))
                error = state.errors[-1]
                self.assertIs(error.__cause__ if phase == 'init_db' else error, state.primary)
                self.assertFalse(any(event['status'] == 'passed' for event in state.diagnostics))

    def test_dispose_only_failure_cannot_report_success_or_retry(self):
        state = self.harness(dispose_error=True)
        self.assertEqual((state.exit_code, state.disposals, state.closes, state.creates), (1, 1, 1, 1))
        self.assertIsInstance(state.errors[-1], OSError)
        self.assertFalse(any(event['status'] == 'passed' for event in state.diagnostics))
        self.assertEqual(state.diagnostics[-1]['status'], 'failed')


if __name__ == '__main__': unittest.main()
