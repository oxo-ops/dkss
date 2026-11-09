"""Offline, observer-owned filesystem faults only. No sockets or subprocesses."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import inspect_observation as m
import launcher_adapter as adapter


def denied():
    value = PermissionError(13, 'SECRET path URL SQL')
    value.winerror = 5
    return value


def success(observed):
    observed.value.update(inspection_completed=True, startup_completed=True, tls_completed=True)
    return {'status':'READ_ONLY_PREFLIGHT_PASSED', 'live_changes':False,
            'observation':m.validate_observation(observed.value)}


class DiagnosticIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.obs = m.Observation(self.tmp.name)
        self.addCleanup(setattr, m, 'ACTIVE', None)
        self.addCleanup(setattr, m, 'LAST', None)

    def assert_degraded(self, operation, *, observation=None):
        value = m.validate_observation((observation or self.obs).value)
        warning = value['diagnostic_persistence']['warning']
        self.assertIs(value['diagnostic_persistence']['complete'],False)
        self.assertEqual(warning['operation'],operation)
        self.assertEqual(warning['target'],m.DIAGNOSTIC_OPERATIONS[operation])
        self.assertNotIn('SECRET',json.dumps(value))
        return warning

    def test_early_open_error_continues_body_once_without_future_file_access(self):
        calls=[]
        with patch.object(m.os,'open',side_effect=denied()) as opened:
            with self.obs.scope('validate_schema'): calls.append('body')
            warning=copy.deepcopy(self.assert_degraded('open_snapshot'))
            for _ in range(100):
                with self.obs.scope('snapshot'): calls.append('later')
            opened.assert_called_once()
        self.assertEqual(calls.count('body'),1)
        self.assertEqual(self.obs.value['diagnostic_persistence']['warning'],warning)
        self.assertEqual(len(self.obs.value['events']),64)
        self.assertGreater(self.obs.value['dropped_events'],0)
        self.assertIsNone(self.obs.value['primary'])

    def test_after_fetch_replace_error_retains_success_and_residue(self):
        calls=[]
        class Raw:
            def execute(self):calls.append('execute')
            def fetchone(self):calls.append('fetch');return (1,)
            def close(self):calls.append('close')
        cursor=m.Cursor(Raw(),self.obs); cursor.execute()
        original=m.os.replace; last_durable=[]
        def replace(src,dst):
            event=self.obs.value['events'][-1]
            if event['operation']=='cursor_fetchone' and event['state']=='ok':
                last_durable.append((self.obs.directory/'observation.json').read_bytes())
                raise denied()
            return original(src,dst)
        with patch.object(m.os,'replace',side_effect=replace) as replaced:
            self.assertEqual(cursor.fetchone(),(1,)); count=replaced.call_count
            cursor.close()
            with self.obs.scope('close','cleanup',cleanup=True):calls.append('cleanup')
            self.assertEqual(replaced.call_count,count)
        warning=self.assert_degraded('replace_snapshot')
        self.assertEqual(warning['event']['operation'],'cursor_fetchone')
        self.assertEqual(warning['event']['state'],'ok')
        self.assertEqual(calls,['execute','fetch','close','cleanup'])
        self.assertEqual((self.obs.directory/'observation.json').read_bytes(),last_durable[0])
        self.assertTrue((self.obs.directory/'next.json').is_file())
        self.assertIsNone(self.obs.value['primary']);self.assertEqual(self.obs.value['cleanup'],[])

    def test_create_directory_error_degrades_but_collision_still_aborts(self):
        with patch.object(Path,'mkdir',side_effect=denied()) as mkdir, patch.object(m.os,'open') as opened:
            other=m.Observation(self.tmp.name)
            mkdir.assert_called_once();opened.assert_not_called()
            self.assert_degraded('create_directory',observation=other)
        with patch.object(m.uuid,'uuid4',return_value=SimpleNamespace(hex=self.obs.value['nonce'])):
            with self.assertRaises(FileExistsError):m.Observation(self.tmp.name)

    def test_write_and_fsync_errors_close_once_and_latch(self):
        for function,operation in (('write','write_snapshot'),('fsync','fsync_snapshot')):
            with self.subTest(function=function):
                obs=m.Observation(self.tmp.name)
                original_close=m.os.close
                with patch.object(m.os,function,side_effect=denied()) as fault, \
                     patch.object(m.os,'close',wraps=original_close) as closed, \
                     patch.object(m.os,'replace') as replaced:
                    obs.persist();obs.persist()
                    fault.assert_called_once();closed.assert_called_once();replaced.assert_not_called()
                self.assert_degraded(operation,observation=obs)
                self.assertTrue((obs.directory/'next.json').exists())

    def test_close_error_is_not_retried_and_never_replaces(self):
        original=m.os.close
        def close(fd):
            original(fd)  # Simulate post-close failure without leaking a test FD.
            raise denied()
        with patch.object(m.os,'close',side_effect=close) as closed,patch.object(m.os,'replace') as replaced:
            self.obs.persist();self.obs.persist()
            closed.assert_called_once();replaced.assert_not_called()
        self.assert_degraded('close_snapshot')
        self.assertTrue((self.obs.directory/'next.json').exists())

    def test_first_write_error_wins_over_close_error(self):
        original=m.os.close
        def close(fd):original(fd);raise OSError(9,'SECRET cleanup')
        with patch.object(m.os,'write',side_effect=denied()),patch.object(m.os,'close',side_effect=close) as closed:
            self.obs.persist();self.obs.persist();closed.assert_called_once()
        warning=self.assert_degraded('write_snapshot')
        self.assertEqual((warning['errno'],warning['winerror']),(13,5))

    def test_short_write_disables_without_retry_or_fabricated_errno(self):
        original=m.os.write
        with patch.object(m.os,'write',side_effect=lambda fd,data:original(fd,data[:1])) as written, \
             patch.object(m.os,'fsync') as sync,patch.object(m.os,'replace') as replaced:
            self.obs.persist();self.obs.persist()
            written.assert_called_once();sync.assert_not_called();replaced.assert_not_called()
        warning=self.assert_degraded('write_snapshot')
        self.assertEqual(warning['code'],'DIAGNOSTIC_SHORT_WRITE')
        self.assertNotIn('errno',warning)
        self.assertEqual((self.obs.directory/'next.json').stat().st_size,1)

    def test_no_target_reopen_delete_or_write_after_disable(self):
        with patch.object(m.os,'replace',side_effect=denied()):self.obs.persist()
        with contextlib.ExitStack() as stack:
            guards=[stack.enter_context(patch.object(m.os,name,side_effect=AssertionError(name)))
                    for name in ('open','write','fsync','close','replace','unlink','remove')]
            for _ in range(5):
                with self.obs.scope('close','cleanup',cleanup=True):pass
                self.obs.persist()
            for guard in guards:guard.assert_not_called()
        self.assertTrue((self.obs.directory/'next.json').exists())

    def test_actual_oserror_body_is_primary_after_diagnostic_denial(self):
        primary=OSError(104,'SECRET database')
        with patch.object(m.os,'open',side_effect=denied()):
            with self.assertRaises(OSError) as raised:
                with self.obs.scope('validate_schema'):raise primary
        self.assertIs(raised.exception,primary)
        self.assertEqual(self.obs.value['primary']['errors'][0]['errno'],104)
        self.assert_degraded('open_snapshot')

    def test_primary_error_and_cleanup_body_error_remain_separate(self):
        primary=ValueError('SECRET primary'); cleanup=OSError(9,'SECRET cleanup')
        with patch.object(m.os,'replace',side_effect=denied()):
            with self.assertRaises(ValueError) as raised:
                try:
                    with self.obs.scope('validate_schema'):raise primary
                finally:
                    try:
                        with self.obs.scope('close','cleanup',cleanup=True):raise cleanup
                    except OSError:pass
        self.assertIs(raised.exception,primary)
        self.assertEqual(self.obs.value['primary']['errors'][0]['type'],'ValueError')
        self.assertEqual(self.obs.value['cleanup'][0]['errors'][0]['errno'],9)
        self.assert_degraded('replace_snapshot')

    def test_cleanup_only_diagnostic_failure_does_not_become_operational(self):
        calls=[]
        with patch.object(m.os,'open',side_effect=denied()):
            with self.obs.scope('close','cleanup',cleanup=True):calls.append('close')
        self.assertEqual(calls,['close']);self.assertIsNone(self.obs.value['primary'])
        self.assertEqual(self.obs.value['cleanup'],[]);self.assert_degraded('open_snapshot')

    def test_programming_and_schema_errors_are_not_degraded(self):
        with patch.object(m.os,'open',side_effect=TypeError('programming')):
            with self.assertRaises(TypeError):self.obs.persist()
        self.assertTrue(self.obs.value['diagnostic_persistence']['complete'])
        with patch.object(m.os,'open',side_effect=denied()):self.obs.persist()
        self.obs.value['extra']='SECRET'
        with self.assertRaisesRegex(ValueError,'OBSERVATION_SCHEMA_INVALID'):self.obs.persist()

    def test_warning_schema_rejects_secrets_wrong_types_and_v1(self):
        with patch.object(m.os,'open',side_effect=denied()):self.obs.persist()
        good=m.validate_observation(self.obs.value)
        mutations=[lambda v:v.update(version=1),lambda v:v.update(inspection_completed=1),
                   lambda v:v['diagnostic_persistence'].update(complete=True),
                   lambda v:v['diagnostic_persistence']['warning'].update(path='SECRET'),
                   lambda v:v['diagnostic_persistence']['warning'].update(errno=True),
                   lambda v:v['diagnostic_persistence']['warning'].update(winerror=2**32),
                   lambda v:v['diagnostic_persistence']['warning'].update(operation='SECRET'),
                   lambda v:v['diagnostic_persistence']['warning'].update(target='SECRET'),
                   lambda v:v['diagnostic_persistence']['warning'].update(code='SECRET'),
                   lambda v:v['diagnostic_persistence']['warning']['event'].update(sql='SECRET')]
        for change in mutations:
            bad=copy.deepcopy(good);change(bad)
            with self.subTest(value=bad),self.assertRaises(ValueError):m.validate_observation(bad)

    def test_successful_degraded_terminal_record_is_explicit_and_durable(self):
        with patch.object(m.os,'replace',side_effect=denied()):self.obs.persist()
        parsed=success(self.obs)
        saved=adapter.persist_stage(self.tmp.name,parsed,stage='inspect',exit_code=0)
        self.assertIs(saved['execute_eligible'],True)
        self.assertEqual(saved,json.loads((Path(self.tmp.name)/'inspect-finished.json').read_bytes()))
        self.assertEqual(saved['safe_output']['observation'],parsed['observation'])
        self.assertFalse(saved['safe_output']['observation']['diagnostic_persistence']['complete'])

    def test_incomplete_or_failed_inspection_never_authorizes_execute(self):
        good=success(self.obs)
        mutations=[lambda v:v.update(status='FAILED_OR_COMMIT_UNCERTAIN'),lambda v:v.pop('live_changes'),
                   lambda v:v.update(live_changes=True),lambda v:v['observation'].update(inspection_completed=False),
                   lambda v:v['observation'].update(startup_completed=None),lambda v:v['observation'].update(tls_completed=None)]
        for change in mutations:
            bad=copy.deepcopy(good);change(bad)
            with self.subTest(value=bad),self.assertRaisesRegex(ValueError,'INSPECT_COMPLETION_REQUIRED'):
                adapter.persist_stage(self.tmp.name,bad,stage='inspect',exit_code=0)
        for cleanup in (False,True):
            obs=m.Observation(self.tmp.name);obs.capture(ValueError(),cleanup=cleanup)
            with self.assertRaisesRegex(ValueError,'INSPECT_COMPLETION_REQUIRED'):
                adapter.persist_stage(self.tmp.name,success(obs),stage='inspect',exit_code=0)
        saved=adapter.persist_stage(self.tmp.name,good,stage='inspect',exit_code=3)
        self.assertFalse(saved['execute_eligible'])

    def test_mandatory_terminal_open_write_flush_fsync_close_and_read_fail_closed(self):
        # Stream operations belong to the required control record, not observer.
        for operation in ('open','write','flush','fsync','close','read'):
            with self.subTest(operation=operation),tempfile.TemporaryDirectory() as root:
                parsed=success(m.Observation(root));stream=None
                with contextlib.ExitStack() as stack:
                    if operation in ('open','fsync'):
                        stack.enter_context(patch.object(adapter.os,operation,side_effect=denied()))
                    elif operation=='read':stack.enter_context(patch.object(Path,'read_bytes',side_effect=denied()))
                    else:
                        real_fdopen=os.fdopen
                        class FaultStream:
                            def __init__(self,fd):self.raw=real_fdopen(fd,'wb')
                            def __enter__(self):return self
                            def write(self,data):
                                if operation=='write':raise denied()
                                return self.raw.write(data)
                            def flush(self):
                                if operation=='flush':raise denied()
                                return self.raw.flush()
                            def fileno(self):return self.raw.fileno()
                            def __exit__(self,*args):
                                self.raw.close()
                                if operation=='close':raise denied()
                        stack.enter_context(patch.object(adapter.os,'fdopen',side_effect=lambda fd,*a:FaultStream(fd)))
                    with self.assertRaises(OSError):adapter.persist_stage(root,parsed,stage='inspect',exit_code=0)


class DiagnosticCLIEnvelopeTests(unittest.TestCase):
    def run_cli(self, *, fault_phase=None, operational_fault=None):
        # Inert engine/plan fixture, explicit no database or connection library I/O.
        import sys
        import worlex_restore as core
        import client_connection
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'worlex_restore.py';source.write_bytes(Path(core.__file__).read_bytes())
            policy=dict(postgres_structure_sha256='a'*64,postgres_acceptance_passed=True,
                        windows_render_acceptance_passed=True,source_manifest_sha256=core.SOURCE_MANIFEST_SHA256,
                        tested_runner_sha256=core.sha(source.read_bytes()))
            (root/'policy.json').write_text(json.dumps(policy));(root/'source-counts.json').write_text('{}')
            plan=root/'plan.json';report=root/'report.json';output=io.StringIO();observers=[];calls=[]
            original_observation=m.Observation; original_replace=os.replace;original_write_text=Path.write_text
            class Connection:
                def __enter__(self):return self
                def __exit__(self,*args):calls.append('connection_close')
                def begin(self):return contextlib.nullcontext()
                def exec_driver_sql(self,sql):calls.append(sql)
            def connect():observers[0].value['startup_completed']=True;return Connection()
            def dispose():
                calls.append('dispose')
                if operational_fault=='dispose':raise RuntimeError('SECRET dispose')
                if operational_fault=='absorbed_cleanup':
                    observers[0].capture(OSError(9,'SECRET swallowed cleanup'),cleanup=True)
            engine=SimpleNamespace(dialect=SimpleNamespace(connect=lambda:None,initialize=lambda:None),connect=connect,dispose=dispose)
            def observation(directory):
                value=original_observation(directory);observers.append(value);return value
            def replace(src,dst):
                event=observers[0].value['events'][-1] if observers and observers[0].value['events'] else {}
                if ((event.get('phase')==fault_phase and event.get('state')=='ok') or
                    (fault_phase=='terminal' and observers and observers[0].value['inspection_completed'])):raise denied()
                return original_replace(src,dst)
            def write_text(path,*args,**kwargs):
                if (operational_fault=='report' and path==report) or (operational_fault=='plan' and path==plan):raise denied()
                return original_write_text(path,*args,**kwargs)
            with contextlib.ExitStack() as stack:
                for name,value in [('__file__',str(source)),('EXPECTED_HOST','synthetic.invalid'),('EXPECTED_DATABASE','synthetic'),
                                   ('EXPECTED_USER','synthetic'),('enforce_windows_client',lambda *a:{}),
                                   ('render_archive',lambda *a:'synthetic'),('copy_digest',lambda *a:core.SOURCE_COPY_SHA256),
                                   ('read_copy',lambda *a:({},{})),('import_scope',lambda *a:{}),
                                   ('create_engine',lambda *a,**k:engine),
                                   ('plan',lambda *a,**k:dict(target_sha256='a'*64,deferred_source_rows={}))]:
                    stack.enter_context(patch.object(core,name,value))
                stack.enter_context(patch.object(client_connection,'verify_tls_connection',lambda *a:None))
                stack.enter_context(patch.object(client_connection,'connection_args',lambda **k:{}))
                stack.enter_context(patch.object(m,'Observation',side_effect=observation))
                stack.enter_context(patch.object(os,'replace',side_effect=replace))
                stack.enter_context(patch.object(Path,'write_text',write_text))
                stack.enter_context(patch.dict(os.environ,{'WORLEX_NEW_DATABASE_URL':'postgresql+pg8000://synthetic:synthetic@synthetic.invalid/synthetic'}))
                stack.enter_context(patch.object(sys,'argv',['restore','inspect','--archive','synthetic','--pg-restore','synthetic','--plan',str(plan),'--report',str(report)]))
                stack.enter_context(contextlib.redirect_stdout(output))
                if operational_fault:
                    with self.assertRaises((OSError,RuntimeError,core.Stop)):core.cli()
                else:core.cli()
            self.assertIn('dispose',calls)
            if operational_fault:
                self.assertEqual(output.getvalue(),'')
                self.assertFalse(observers[0].value['inspection_completed'])
                return
            parsed=json.loads(output.getvalue());self.assertTrue(parsed['observation']['inspection_completed'])
            self.assertFalse(json.loads(report.read_bytes())['observation']['inspection_completed'])
            saved=adapter.persist_stage(root,parsed,stage='inspect',exit_code=0)
            self.assertTrue(saved['execute_eligible'])
            self.assertEqual(saved['safe_output']['observation'],observers[0].value)
            return parsed

    def test_late_output_write_diagnostic_error_is_in_final_terminal_record(self):
        parsed=self.run_cli(fault_phase='output_write')
        self.assertFalse(parsed['observation']['diagnostic_persistence']['complete'])
        self.assertEqual(parsed['observation']['diagnostic_persistence']['warning']['event']['phase'],'output_write')

    def test_late_dispose_diagnostic_error_is_in_final_terminal_record(self):
        parsed=self.run_cli(fault_phase='engine_dispose')
        self.assertFalse(parsed['observation']['diagnostic_persistence']['complete'])
        self.assertEqual(parsed['observation']['diagnostic_persistence']['warning']['event']['phase'],'engine_dispose')

    def test_final_persist_error_after_completion_is_refreshed_before_stdout(self):
        parsed=self.run_cli(fault_phase='terminal')
        self.assertTrue(parsed['observation']['inspection_completed'])
        self.assertFalse(parsed['observation']['diagnostic_persistence']['complete'])

    def test_absorbed_operational_cleanup_error_never_marks_completion(self):
        self.run_cli(operational_fault='absorbed_cleanup')

    def test_genuine_plan_report_and_dispose_failure_never_print_completion(self):
        for operation in ('plan','report','dispose'):
            with self.subTest(operation=operation):self.run_cli(operational_fault=operation)
