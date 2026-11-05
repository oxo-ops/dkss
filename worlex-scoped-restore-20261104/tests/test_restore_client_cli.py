"""CLI transport-envelope tests with a non-network synthetic engine only."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[1]

class ClientCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        spec=importlib.util.spec_from_file_location('pure_cli_under_test',ROOT/'worlex_restore.py')
        self.core=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.core)
        self.source=self.root/'worlex_restore.py';self.source.write_bytes((ROOT/'worlex_restore.py').read_bytes())
        self.core.__file__=str(self.source)
        policy={'postgres_structure_sha256':'a'*64,'postgres_acceptance_passed':True,
                'windows_render_acceptance_passed':True,'source_manifest_sha256':self.core.SOURCE_MANIFEST_SHA256,
                'tested_runner_sha256':hashlib.sha256(self.source.read_bytes()).hexdigest()}
        (self.root/'policy.json').write_text(json.dumps(policy));(self.root/'source-counts.json').write_text('{}')
        self.private=self.root/'private-plan.json';self.report=self.root/'report.json'
        self.runtime={'ssl_runtime':{'hash':'synthetic-current-runtime'},'pure_python_client':True}
        self.plan={'target_sha256':'f'*64,'generated_identifiers':{},'synthetic_exact_database_plan':True}
        self.engine=MagicMock();self.connection=MagicMock()
        self.engine.connect.return_value.__enter__.return_value=self.connection
        self.url=f'postgresql+pg8000://{self.core.EXPECTED_USER}:synthetic-not-real@{self.core.EXPECTED_HOST}:5432/{self.core.EXPECTED_DATABASE}?sslmode=verify-full'
    def invoke(self,action):
        args=['restore',action,'--archive','synthetic','--pg-restore','synthetic','--plan',str(self.private),'--report',str(self.report)]
        if action=='execute':args.append('--writers-stopped')
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ,{'WORLEX_NEW_DATABASE_URL':self.url}))
            stack.enter_context(patch.object(sys,'argv',args))
            stack.enter_context(patch.object(self.core,'enforce_windows_client',return_value=self.runtime))
            import client_connection
            stack.enter_context(patch.object(client_connection,'verify_tls_connection',return_value={'verified':True}))
            engine=stack.enter_context(patch.object(self.core,'create_engine',return_value=self.engine))
            stack.enter_context(patch.object(self.core,'render_archive',return_value='synthetic'))
            stack.enter_context(patch.object(self.core,'copy_digest',return_value=self.core.SOURCE_COPY_SHA256))
            stack.enter_context(patch.object(self.core,'read_copy',return_value=({},{})))
            stack.enter_context(patch.object(self.core,'plan',return_value=dict(self.plan)))
            execute=stack.enter_context(patch.object(self.core,'execute_restore',return_value={'status':'TRANSACTION_VERIFIED'}))
            verify=stack.enter_context(patch.object(self.core,'verify_restore',return_value={'status':'RESTORE_PRESENT_MATCHES_PLAN'}))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.core.cli()
            return engine,execute,verify
    def approved(self,runtime=None):
        self.private.write_text(json.dumps({**self.plan,'client_runtime_sha256':self.core.digest(runtime or self.runtime)}))
    def test_inspect_binds_runtime_and_starts_readonly(self):
        engine,execute,verify=self.invoke('inspect')
        saved=json.loads(self.private.read_text())
        self.assertEqual(saved,{**self.plan,'client_runtime_sha256':self.core.digest(self.runtime)})
        self.assertEqual(engine.call_args.args[0].drivername,'postgresql+pg8000')
        self.assertEqual(engine.call_args.args[0].query,{})
        self.assertEqual(engine.call_args.kwargs['connect_args']['startup_params']['default_transaction_read_only'],'on')
        execute.assert_not_called();verify.assert_not_called()
    def test_execute_uses_exact_database_plan_after_runtime_check(self):
        self.approved();engine,execute,verify=self.invoke('execute')
        self.assertEqual(execute.call_args.args[-1],self.plan)
        self.assertEqual(json.loads(Path(str(self.private)+'.execution.json').read_text())['status'],'COMMITTED')
        self.assertNotIn('default_transaction_read_only',engine.call_args.kwargs['connect_args']['startup_params'])
        verify.assert_not_called()
    def test_verify_uses_original_plan_readonly_no_execute(self):
        self.approved();before=self.private.read_bytes();engine,execute,verify=self.invoke('verify')
        self.assertEqual(verify.call_args.args[-1],self.plan);self.assertEqual(self.private.read_bytes(),before)
        self.assertFalse(Path(str(self.private)+'.execution.json').exists())
        self.assertEqual(engine.call_args.kwargs['connect_args']['startup_params']['default_transaction_read_only'],'on')
        execute.assert_not_called()
    def test_runtime_change_stops_before_connect_or_marker(self):
        self.approved({'changed':'runtime'})
        for action in ('execute','verify'):
            with self.subTest(action=action),self.assertRaisesRegex(self.core.Stop,'CLIENT_RUNTIME_CHANGED'):
                self.invoke(action)
        self.engine.connect.assert_not_called();self.assertFalse(Path(str(self.private)+'.execution.json').exists())
        self.assertFalse(self.report.exists())

if __name__=='__main__':unittest.main(verbosity=2)
