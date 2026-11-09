"""Execute-only cumulative budget; unchanged statement/socket/read-only limits."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import client_connection
import worlex_restore as core
import test_restore_client_cli as cli_fixture
import test_restore_postgres as postgres_fixture

LOCAL_SETTINGS = [
    "SET LOCAL lock_timeout='10s'",
    "SET LOCAL statement_timeout='120s'",
    "SET LOCAL idle_in_transaction_session_timeout='180s'",
    "SET LOCAL transaction_timeout='900s'",
    "SET LOCAL search_path=pg_catalog,public",
]
OTHER_STARTUP = {'search_path':'pg_catalog,public', 'statement_timeout':'120000',
                 'lock_timeout':'10000', 'idle_in_transaction_session_timeout':'180000'}


class ExecuteBudgetTests(unittest.TestCase):
    def test_generic_and_readonly_connection_defaults_remain_300s(self):
        for read_only in (False, True):
            with self.subTest(read_only=read_only):
                args = client_connection.connection_args(read_only=read_only)
                expected = {**OTHER_STARTUP, 'transaction_timeout':'300000'}
                if read_only: expected['default_transaction_read_only'] = 'on'
                self.assertEqual(args['startup_params'], expected)
                self.assertEqual(args['timeout'], 130)
        # Caller-local execute overrides cannot leak into the next default call.
        args['startup_params']['transaction_timeout'] = '900000'
        self.assertEqual(client_connection.connection_args()['startup_params']['transaction_timeout'], '300000')
        for value in (None, 0, 1, 'execute', 'False'):
            with self.subTest(invalid=value), self.assertRaisesRegex(ValueError, 'READ_ONLY_FLAG_INVALID'):
                client_connection.connection_args(read_only=value)
        with self.assertRaises(TypeError): client_connection.connection_args(transaction_timeout=900)

    def test_execute_local_limits_precede_lock_and_no_work_when_lock_refused(self):
        connection = Mock(); connection.in_transaction.return_value = True
        connection.scalar.return_value = False
        with self.assertRaisesRegex(core.Stop, 'RESTORE_ALREADY_RUNNING'):
            core.execute_restore(connection, {}, {}, {}, {}, 'synthetic', {})
        self.assertEqual([call.args[0] for call in connection.exec_driver_sql.call_args_list], LOCAL_SETTINGS)
        self.assertEqual(str(connection.scalar.call_args.args[0]), 'SELECT pg_try_advisory_xact_lock(873624100,20261104)')
        self.assertEqual(connection.scalar.call_count, 1)
        connection.execute.assert_not_called(); connection.commit.assert_not_called()

    def test_missing_transaction_fails_before_settings_or_lock(self):
        connection = Mock(); connection.in_transaction.return_value = False
        with self.assertRaisesRegex(core.Stop, 'TRANSACTION_REQUIRED'):
            core.execute_restore(connection, {}, {}, {}, {}, 'synthetic', {})
        connection.exec_driver_sql.assert_not_called(); connection.scalar.assert_not_called()
        connection.execute.assert_not_called(); connection.commit.assert_not_called()

    def test_any_local_setting_failure_stops_once_without_lock_or_retry(self):
        for index, statement in enumerate(LOCAL_SETTINGS):
            with self.subTest(statement=statement):
                connection = Mock(); connection.in_transaction.return_value = True
                error = RuntimeError('synthetic SET LOCAL failure')
                connection.exec_driver_sql.side_effect = [None] * index + [error]
                with self.assertRaises(RuntimeError) as caught:
                    core.execute_restore(connection, {}, {}, {}, {}, 'synthetic', {})
                self.assertIs(caught.exception, error)
                self.assertEqual([call.args[0] for call in connection.exec_driver_sql.call_args_list], LOCAL_SETTINGS[:index+1])
                connection.scalar.assert_not_called(); connection.execute.assert_not_called()
                connection.commit.assert_not_called()


    def test_effective_search_path_formatting_keeps_exact_schema_order_and_limits(self):
        checker = PostgreSQLExecuteBudgetAcceptance('test_actual_cli_execute_startup_and_local_budget_are_900s')
        values = {'transaction_timeout':'15min', 'statement_timeout':'2min',
            'lock_timeout':'10s', 'idle_in_transaction_session_timeout':'3min',
            'transaction_read_only':'off', 'search_path':'pg_catalog,public'}
        def connection(overrides=None, socket_timeout=130):
            settings = {**values, **(overrides or {})}
            result = Mock()
            result.exec_driver_sql.side_effect = lambda sql: Mock(scalar=Mock(return_value=settings[sql.removeprefix('SHOW ')]))
            result.connection.driver_connection._usock.gettimeout.return_value = socket_timeout
            return result
        with patch.object(postgres_fixture, 'assert_pg8000_tls') as tls:
            for value in ('pg_catalog,public', 'pg_catalog, public', ' pg_catalog , public '):
                with self.subTest(valid=value):
                    actual = checker.assert_effective(connection({'search_path':value}), 900, False)
                    self.assertEqual(actual['search_path'], ['pg_catalog','public'])
            for value in ('public,pg_catalog', 'pg_catalog,public,extra', 'pg_catalog,pg_catalog',
                          'pg_catalog', 'public', '', 'pg_catalog,', 'pg_catalogue,public',
                          'pg_ catalog,public', '$user,public', 'pg_catalog,public,'):
                with self.subTest(invalid=value), self.assertRaises(AssertionError):
                    checker.assert_effective(connection({'search_path':value}), 900, False)
            for key, value in (('transaction_timeout','5min'), ('statement_timeout','3min'),
                               ('lock_timeout','11s'), ('idle_in_transaction_session_timeout','4min'),
                               ('transaction_read_only','on')):
                with self.subTest(unchanged_limit=key), self.assertRaises(AssertionError):
                    checker.assert_effective(connection({key:value}), 900, False)
            with self.assertRaises(AssertionError):
                checker.assert_effective(connection(socket_timeout=129), 900, False)
            self.assertEqual(tls.call_count, 20)


class PostgreSQLExecuteBudgetAcceptance(unittest.TestCase):
    # Same marked workflow-owned service, exact source and TLS gates as the
    # existing suite. No new database is needed: only SHOW/SET LOCAL are issued.
    setUpClass = classmethod(postgres_fixture.PostgreSQLRestoreAcceptance.setUpClass.__func__)
    setUp = cli_fixture.ClientCLITests.setUp

    def assert_effective(self, connection, seconds, read_only):
        postgres_fixture.assert_pg8000_tls(connection)
        actual = {name: connection.exec_driver_sql('SHOW '+name).scalar() for name in (
            'transaction_timeout', 'statement_timeout', 'lock_timeout',
            'idle_in_transaction_session_timeout', 'transaction_read_only', 'search_path')}
        # SHOW preserves startup formatting but SET LOCAL may insert a space.
        # Only surrounding token whitespace is immaterial; names/order are exact.
        actual['search_path'] = [name.strip() for name in actual['search_path'].split(',')]
        self.assertEqual(actual, {'transaction_timeout':str(seconds//60)+'min',
            'statement_timeout':'2min', 'lock_timeout':'10s',
            'idle_in_transaction_session_timeout':'3min',
            'transaction_read_only':'on' if read_only else 'off', 'search_path':['pg_catalog','public']})
        self.assertEqual(connection.connection.driver_connection._usock.gettimeout(), 130)
        return actual

    def invoke_actual_cli(self, action, callback):
        real_args = client_connection.connection_args
        real_engine = self.core.create_engine
        calls = []
        def args(**kwargs): return real_args(cafile=self.cafile, **kwargs)
        def engine(url, **kwargs):
            calls.append(kwargs['connect_args'])
            return real_engine(self.service, **kwargs)
        if action != 'inspect': cli_fixture.ClientCLITests.approved(self)
        argv = ['restore', action, '--archive', 'synthetic', '--pg-restore', 'synthetic',
                '--plan', str(self.private), '--report', str(self.report)]
        if action == 'execute': argv.append('--writers-stopped')
        url = self.service.set(port=5432).render_as_string(hide_password=False)
        operation = {'inspect':'plan', 'verify':'verify_restore', 'execute':'execute_restore'}[action]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {'WORLEX_NEW_DATABASE_URL':url}))
            stack.enter_context(patch.object(sys, 'argv', argv))
            stack.enter_context(patch.object(self.core, 'EXPECTED_HOST', self.service.host))
            stack.enter_context(patch.object(self.core, 'EXPECTED_USER', self.service.username))
            stack.enter_context(patch.object(self.core, 'EXPECTED_DATABASE', self.service.database))
            stack.enter_context(patch.object(self.core, 'enforce_windows_client', return_value=self.runtime))
            stack.enter_context(patch.object(client_connection, 'connection_args', side_effect=args))
            stack.enter_context(patch.object(self.core, 'create_engine', side_effect=engine))
            stack.enter_context(patch.object(self.core, 'render_archive', return_value='synthetic'))
            stack.enter_context(patch.object(self.core, 'copy_digest', return_value=self.core.SOURCE_COPY_SHA256))
            stack.enter_context(patch.object(self.core, 'read_copy', return_value=({}, {})))
            stack.enter_context(patch.object(self.core, operation, side_effect=callback))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.core.cli()
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_actual_cli_execute_startup_and_local_budget_are_900s(self):
        observed = []
        def probe(connection, *unused):
            observed.append(self.assert_effective(connection, 900, False))
            # A lower inherited/local setting must not defeat the execute budget.
            connection.exec_driver_sql("SET LOCAL transaction_timeout='300s'")
            self.assertEqual(connection.exec_driver_sql('SHOW transaction_timeout').scalar(), '5min')
            owner = self
            class BeforeLock:
                def __getattr__(self, name): return getattr(connection, name)
                def scalar(self, statement):
                    owner.assertEqual(str(statement), 'SELECT pg_try_advisory_xact_lock(873624100,20261104)')
                    observed.append(owner.assert_effective(connection, 900, False))
                    return False  # Real SET LOCAL, no advisory lock or restore write.
            core.execute_restore(BeforeLock(), {}, {}, {}, {}, 'synthetic', {})
        with self.assertRaisesRegex(core.Stop, 'RESTORE_ALREADY_RUNNING'):
            self.invoke_actual_cli('execute', probe)
        self.assertEqual(len(observed), 2)
        self.assertEqual(json.loads(Path(str(self.private)+'.execution.json').read_text())['status'], 'STARTED_NO_RETRY')
        self.assertFalse(self.report.exists())

    def test_actual_cli_inspect_verify_and_reconciliation_default_remain_300s(self):
        for action in ('inspect', 'verify'):
            with self.subTest(action=action):
                observed = []
                def probe(connection, *unused):
                    observed.append(self.assert_effective(connection, 300, True))
                    return dict(self.plan) if action == 'inspect' else {'status':'RESTORE_PRESENT_MATCHES_PLAN'}
                # Separate output files; prior inspect still supplies the same plan.
                self.report = self.root/(action+'-report.json')
                args = self.invoke_actual_cli(action, probe)
                self.assertEqual(len(observed), 1)
                self.assertEqual(args['startup_params'], {**OTHER_STARTUP,
                    'transaction_timeout':'300000', 'default_transaction_read_only':'on'})
                self.assertFalse(Path(str(self.private)+'.execution.json').exists())
        # Reconciliation calls the unchanged generic factory with read_only=True.
        engine = self.core.create_engine(self.service, poolclass=postgres_fixture.NullPool,
            hide_parameters=True, connect_args=client_connection.connection_args(cafile=self.cafile,
                application_name='worlex_synthetic_reconcile', read_only=True))
        try:
            with engine.connect() as connection, connection.begin():
                self.assert_effective(connection, 300, True)
        finally: engine.dispose()


if __name__ == '__main__': unittest.main(verbosity=2)
