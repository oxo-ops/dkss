"""No network. Exact forwarding, bounded schema and cleanup precedence tests."""
import contextlib
import copy
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inspect_observation as m

class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.obs = m.Observation(self.tmp.name)
        self.addCleanup(setattr, m, 'ACTIVE', None)
        self.addCleanup(setattr, m, 'LAST', None)
    def test_private_distinct_attempts(self):
        other = m.Observation(self.tmp.name)
        self.assertNotEqual(other.directory, self.obs.directory)
        self.assertEqual(len(list(Path(self.tmp.name).iterdir())), 2)
        if os.name != 'nt': self.assertEqual(self.obs.directory.stat().st_mode & 0o777, 0o700)
    def test_error_graph_cycle_and_secret_omission(self):
        a = OSError(104, 'secret host password')
        b = type('InterfaceError', (Exception,), {})({'C':'08006','M':'secret','D':'private'})
        a.__cause__ = b; b.__context__ = a; a.orig = b
        graph = m.safe_error(a)
        self.assertEqual(len(graph), 2)
        self.assertEqual(graph[0]['errno'], 104)
        self.assertEqual(graph[1]['sqlstate'], '08006')
        self.assertNotIn('secret', json.dumps(graph))
    def test_unknown_error_and_invalid_codes(self):
        e = type('PasswordIsSecret', (Exception,), {})({'C':'BAD SECRET'})
        e.errno = True; e.winerror = 2**100
        self.assertEqual(m.safe_error(e), [{'type':'OtherError','parent':None,'link':None}])
    def test_graph_bounded(self):
        e = ValueError(); p = e
        for _ in range(20): p.__cause__ = ValueError(); p = p.__cause__
        self.assertEqual(len(m.safe_error(e)), 8)
    def test_primary_frozen_cleanup_separate_and_exception_precedence(self):
        primary = ValueError('secret primary'); cleanup = OSError('secret rollback')
        @contextlib.contextmanager
        def transaction():
            try: yield
            finally: raise cleanup
        with self.assertRaises(OSError) as caught:
            with self.obs.wrap_context(transaction(), 'transaction_end'):
                with self.obs.scope('plan'): raise primary
        self.assertIs(caught.exception, cleanup)
        self.assertEqual(self.obs.value['primary']['errors'][0]['type'], 'ValueError')
        self.assertEqual(self.obs.value['cleanup'][0]['errors'][0]['type'], 'OSError')
        frozen = copy.deepcopy(self.obs.value['primary'])
        primary.args = ('changed',)
        self.assertEqual(self.obs.value['primary'], frozen)
    def test_cleanup_only_not_primary_or_stale_query(self):
        self.obs.ordinal = 33
        with self.assertRaises(OSError):
            with self.obs.scope('close', 'cleanup', cleanup=True, ordinal=0): raise OSError('secret')
        self.assertIsNone(self.obs.value['primary'])
        self.assertEqual(self.obs.value['cleanup'][0]['event']['ordinal'], 0)
    def test_forwarding_execute_fetch_exact_args_results(self):
        calls = []; sentinel = object(); params = {'private':'secret'}
        class Raw:
            def execute(self, *a, **kw): calls.append(('execute',a,kw)); return self
            def fetchmany(self, *a, **kw): calls.append(('fetchmany',a,kw)); return sentinel
            def close(self): calls.append(('close',(),{}))
        raw = Raw(); cursor = m.Cursor(raw, self.obs)
        with self.obs.scope('snapshot'):
            self.assertIs(cursor.execute('unchanged SQL',params), cursor)
            self.assertIs(cursor.fetchmany(7), sentinel)
        cursor.close()
        self.assertEqual(calls, [('execute',('unchanged SQL',params),{}),('fetchmany',(7,),{}),('close',(),{})])
        self.assertNotIn('unchanged SQL', json.dumps(self.obs.value))
        self.assertNotIn('secret', json.dumps(self.obs.value))
    def test_fetch_failure_retains_original_query_category(self):
        class Raw:
            def execute(self,*a): pass
            def fetchone(self): raise OSError('private')
        cursor = m.Cursor(Raw(), self.obs)
        with self.obs.scope('snapshot'):cursor.execute('sql')
        with self.assertRaises(OSError):cursor.fetchone()
        event = self.obs.value['primary']['event']
        self.assertEqual((event['phase'],event['operation'],event['ordinal']),('snapshot','cursor_fetchone',1))
    def test_execute_failure_not_fetch(self):
        class Raw:
            def execute(self,*a): raise ValueError('private')
        with self.assertRaises(ValueError):m.Cursor(Raw(),self.obs).execute('sql')
        self.assertEqual(self.obs.value['primary']['event']['operation'],'cursor_execute')
    def test_connect_start_not_tls_or_startup(self):
        def failed(*a, **kw): raise OSError('secret host')
        engine = SimpleNamespace(dialect=SimpleNamespace(connect=failed, initialize=lambda c:None))
        self.obs.install(engine,{})
        with self.assertRaises(OSError):engine.dialect.connect('opaque', private='secret')
        self.assertFalse(self.obs.value['startup_completed'])
        self.assertFalse(self.obs.value['tls_completed'])
        self.assertIsNone(self.obs.value['backend_pid'])
    def test_dbapi_success_pid_only_no_extra_calls(self):
        calls=[]
        class Raw:
            __module__='pg8000.legacy'
            _backend_key_data=struct.pack('!ii',1234,987654321)
            def cursor(self): calls.append('cursor')
            def rollback(self): calls.append('rollback')
            def commit(self): calls.append('commit')
            def close(self): calls.append('close')
        raw=Raw()
        def connect(*a,**kw):calls.append(('connect',a,kw));return raw
        engine=SimpleNamespace(dialect=SimpleNamespace(connect=connect,initialize=lambda c:calls.append('initialize')))
        self.obs.install(engine,{})
        self.assertIs(engine.dialect.connect('original',port=123),raw)
        self.assertEqual(calls,[('connect',('original',),{'port':123})])
        self.assertTrue(self.obs.value['startup_completed']);self.assertFalse(self.obs.value['tls_completed'])
        self.assertEqual(self.obs.value['backend_pid'],1234)
        self.assertNotIn('987654321',json.dumps(self.obs.value))
    def test_strict_launcher_roundtrip_and_extra_field_rejection(self):
        valid=m.launcher_observation({'observation':self.obs.value})
        self.assertEqual(valid,{'observation':self.obs.value})
        valid['observation']['nonce']='0'*32
        self.assertNotEqual(valid['observation'],self.obs.value)
        for key,value in [('private','secret'),('backend_pid',True),('server_clock','invented')]:
            bad=copy.deepcopy(self.obs.value);bad[key]=value
            with self.assertRaises(ValueError):m.launcher_observation({'observation':bad})
    def test_events_bounded_monotonic_and_durable_before_body(self):
        for _ in range(40):
            with self.obs.scope('snapshot'):
                disk=json.loads((self.obs.directory/'observation.json').read_text())
                self.assertEqual(disk['events'][-1]['state'],'start')
        self.assertEqual(len(self.obs.value['events']),64)
        times=[e['elapsed_ms'] for e in self.obs.value['events']]
        self.assertEqual(times,sorted(times));self.assertEqual(self.obs.value['dropped_events'],16)
    def test_partial_persist_keeps_previous_valid_record(self):
        before=(self.obs.directory/'observation.json').read_bytes()
        with patch.object(m.os,'replace',side_effect=OSError('private path')):
            with self.assertRaises(OSError):
                with self.obs.scope('snapshot'):self.fail('Persistence must fail closed before body')
        self.assertEqual((self.obs.directory/'observation.json').read_bytes(),before)
        m.validate_observation(json.loads(before))
    def test_atomic_snapshot_failure_does_not_reopen_old_attempt(self):
        with patch.object(m.uuid,'uuid4',return_value=SimpleNamespace(hex=self.obs.value['nonce'])):
            with self.assertRaises(FileExistsError):m.Observation(self.tmp.name)

class ObservationEdgeTests(unittest.TestCase):
    setUp = ObservationTests.setUp
    def test_logging_failure_cannot_skip_cleanup_or_mask_primary(self):
        calls=[]
        class Context:
            def __enter__(self):return self
            def __exit__(self,*args):calls.append('exit')
        primary=ValueError('private')
        patcher=patch.object(self.obs,'persist',side_effect=OSError('private path'))
        self.addCleanup(patcher.stop)
        with self.assertRaises(ValueError) as raised:
            with self.obs.wrap_context(Context(),'transaction_end'):
                patcher.start()
                raise primary
        self.assertIs(raised.exception,primary)
        self.assertEqual(calls,['exit'])
    def test_cleanup_runs_despite_persist_failure_without_primary(self):
        calls=[]
        with patch.object(self.obs,'persist',side_effect=OSError('private')):
            with self.assertRaises(OSError):
                with self.obs.scope('close',cleanup=True):calls.append('close')
        self.assertEqual(calls,['close'])
    def test_cli_rejects_unsealed_helpers_before_import(self):
        import ast, hashlib, io
        root=Path(self.tmp.name)
        (root/'policy.json').write_text(json.dumps({'tested_artifacts':{}}))
        source=(Path(__file__).resolve().parents[1]/'worlex_restore.py').read_text()
        guard=next(n for n in ast.parse(source).body if isinstance(n,ast.If))
        output=io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            exec(compile(ast.Module(body=[guard],type_ignores=[]),'<guard>','exec'),
                dict(__name__='__main__',__file__=str(root/'worlex_restore.py'),
                     Path=Path,json=json,hashlib=hashlib,sys=sys))
        self.assertEqual(raised.exception.code,2)
        self.assertEqual(json.loads(output.getvalue()),
            {'status':'STOPPED','reason':'HELPER_DIFFERS_FROM_TESTED_REVISION'})
    def test_hostile_attribute_does_not_replace_error(self):
        class Hostile(Exception):
            @property
            def errno(self):raise RuntimeError('secret')
            @property
            def orig(self):raise RuntimeError('secret')
        error=Hostile('secret')
        self.assertEqual(m.safe_error(error),[{'type':'OtherError','parent':None,'link':None}])
    def test_explicit_capture_survives_persist_failure(self):
        error=ValueError('private')
        with patch.object(self.obs,'persist',side_effect=OSError('private')):
            self.obs.capture(error)
        self.assertEqual(self.obs.value['primary']['errors'][0]['type'],'ValueError')
    def test_cursor_iterator_and_context_manager_contract(self):
        calls=[]
        class Raw:
            def __init__(self):self.rows=iter([(1,),(2,)])
            def __iter__(self):calls.append('iter');return self
            def __next__(self):calls.append('next');return next(self.rows)
            def __enter__(self):calls.append('enter');return self
            def __exit__(self,*args):calls.append(('exit',args));return None
        cursor=m.Cursor(Raw(),self.obs)
        self.assertIs(iter(cursor),cursor)
        with cursor as opened:
            self.assertIs(opened,cursor)
            self.assertEqual(next(cursor),(1,))
            self.assertEqual(list(cursor),[(2,)])
        self.assertIsNone(self.obs.value['primary'])
        self.assertEqual(calls[-1],('exit',(None,None,None)))

if __name__=='__main__':unittest.main()
