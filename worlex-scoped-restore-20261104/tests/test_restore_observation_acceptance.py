"""Formal inspect on owned CI PostgreSQL; synthetic source boundary only."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import client_connection
import inspect_observation
import worlex_restore as core
from launcher_adapter import persist_stage
import test_restore_postgres as baseline

class PostgreSQLObservationAcceptance(unittest.TestCase):
    setUpClass = classmethod(baseline.PostgreSQLRestoreAcceptance.setUpClass.__func__)
    setUp = baseline.PostgreSQLRestoreAcceptance.setUp
    unchanged = baseline.PostgreSQLRestoreAcceptance.unchanged

    def invoke_inspect(self, fail=False):
        root = Path(self.temp.name)/'formal-cli'; root.mkdir()
        source = root/'worlex_restore.py'; source.write_bytes(Path(core.__file__).read_bytes())
        (root/'policy.json').write_text(json.dumps(self.policy))
        (root/'source-counts.json').write_bytes((baseline.PACKAGE/'source-counts.json').read_bytes())
        output = io.StringIO(); real_args = client_connection.connection_args
        real_engine = core.create_engine; calls = []
        def engine(url, **kwargs):
            calls.append(kwargs)
            return real_engine(self.url, **kwargs)
        def args(**kwargs): return real_args(cafile=self.cafile, **kwargs)
        approved = root/'plan.json'; report = root/'report.json'
        url = self.url.set(port=5432).render_as_string(hide_password=False)
        with contextlib.ExitStack() as stack:
            for target, value in [('__file__',str(source)), ('EXPECTED_HOST',self.url.host),
                                  ('EXPECTED_DATABASE',self.url.database), ('EXPECTED_USER',self.url.username)]:
                stack.enter_context(patch.object(core,target,value))
            stack.enter_context(patch.object(core,'enforce_windows_client',return_value={'synthetic':True}))
            stack.enter_context(patch.object(core,'render_archive',return_value='synthetic'))
            stack.enter_context(patch.object(core,'copy_digest',return_value=core.SOURCE_COPY_SHA256))
            stack.enter_context(patch.object(core,'read_copy',return_value=(self.data,self.columns)))
            stack.enter_context(patch.object(core,'create_engine',side_effect=engine))
            stack.enter_context(patch.object(client_connection,'connection_args',side_effect=args))
            stack.enter_context(patch.dict(os.environ,{'WORLEX_NEW_DATABASE_URL':url}))
            stack.enter_context(patch.object(sys,'argv',['restore','inspect','--archive','synthetic',
                '--pg-restore','synthetic','--plan',str(approved),'--report',str(report)]))
            stack.enter_context(contextlib.redirect_stdout(output))
            if fail:
                # Real server statement failure, captured before rollback; no retry.
                def denied(connection,*a,**kw): connection.exec_driver_sql('SELECT 1/0')
                stack.enter_context(patch.object(core,'plan',side_effect=denied))
                with self.assertRaises(Exception): core.cli()
                parsed = {'status':'FAILED_OR_COMMIT_UNCERTAIN', **inspect_observation.output_fields()}
            else:
                core.cli(); parsed = json.loads(output.getvalue())
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['connect_args']['startup_params']['default_transaction_read_only'],'on')
        saved = persist_stage(root,parsed,stage='inspect',exit_code=3 if fail else 0)
        observed = saved['safe_output']['observation']
        self.assertTrue(observed['startup_completed']); self.assertTrue(observed['tls_completed'])
        self.assertIs(type(observed['backend_pid']),int)
        self.assertEqual(observed, parsed['observation'])
        if not fail:
            plan = json.loads(approved.read_text()); plan.pop('client_runtime_sha256')
            self.assertNotIn('observation',plan)
            # Generated UUIDs are pinned to compare the canonical plan only.
            with self.engine.connect() as connection:
                expected = core.plan(connection,self.data,self.columns,self.policy,self.counts,
                    self.source_hash,generated=plan['generated_identifiers'])
            self.assertEqual(plan,expected)
        else:
            self.assertFalse(approved.exists()); self.assertFalse(report.exists())
        self.unchanged()
        return observed

    def test_formal_cli_observation_roundtrip_and_canonical_plan(self):
        observed = self.invoke_inspect()
        self.assertIsNone(observed['primary'])
        self.assertEqual(observed['cleanup'],[])

    def test_formal_cli_server_error_preserved_before_cleanup_no_reconnect(self):
        observed = self.invoke_inspect(fail=True)
        self.assertIsNotNone(observed['primary'])
        self.assertIn('22012', json.dumps(observed['primary']))
        self.assertEqual(observed['cleanup'],[])

    def test_instrumentation_preserves_exact_sql_binds_and_connection_count(self):
        from sqlalchemy import event
        from sqlalchemy.pool import NullPool
        traces = []; plans = []; connections = []
        for enabled in (False, True):
            args = client_connection.connection_args(cafile=self.cafile, read_only=True,
                application_name='worlex_synthetic_restore')
            engine = core.create_engine(self.url, poolclass=NullPool, hide_parameters=True, connect_args=args)
            trace = []; opened = []
            event.listen(engine, 'before_cursor_execute', lambda c, cursor, statement, parameters, context, many:
                trace.append((statement, parameters, many)))
            event.listen(engine, 'connect', lambda dbapi, record: opened.append(True))
            observer = inspect_observation.Observation(Path(self.temp.name)) if enabled else None
            if observer: observer.install(engine,args)
            inspect_observation.ACTIVE = observer
            try:
                with engine.connect() as connection, connection.begin():
                    connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                    plans.append(core.plan(connection,self.data,self.columns,self.policy,self.counts,
                        self.source_hash,generated=self.approved['generated_identifiers']))
            finally:
                engine.dispose(); inspect_observation.ACTIVE = None
            traces.append(trace); connections.append(len(opened))
        self.assertEqual(plans[0], plans[1]); self.assertEqual(traces[0],traces[1])
        self.assertEqual(connections,[1,1]); self.unchanged()

    def test_locked_context_rejects_other_connection_and_stale_transaction(self):
        original = core.plan
        with self.engine.connect() as other:
            stale_transaction = other.begin(); stale_transaction.rollback()
        for field, replacement in (('connection',other), ('transaction',stale_transaction)):
            def substituted(*args, **kwargs):
                result = original(*args, **kwargs)
                kwargs['_context'][field] = replacement
                return result
            with self.subTest(field=field), self.engine.begin() as connection:
                with patch.object(core,'plan',side_effect=substituted):
                    with self.assertRaisesRegex(core.Stop,'LOCKED_PLAN_CONTEXT_CHANGED'):
                        core.execute_restore(connection,self.data,self.columns,self.policy,
                            self.counts,self.source_hash,self.approved)
            self.unchanged()
