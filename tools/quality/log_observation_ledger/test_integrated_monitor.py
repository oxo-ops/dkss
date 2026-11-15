"""Network-blocked synthetic integration acceptance, real temp-file IO only."""
import copy
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
def deny_network(event, args):
    if event.startswith('socket.'):
        raise RuntimeError('NETWORK_FORBIDDEN')
sys.addaudithook(deny_network)
import integrated_monitor as v2
import offline_monitor as old
import collection_history as history
from test_offline_monitor import NOW, LATER, AFTER, policy, reply, collect, only

class Integrated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'v2.json'
        self.store = v2.FileStore(self.path)
        self.store.initialize()
    def tearDown(self): self.tmp.cleanup()
    def scan(self, replies=None, now=NOW):
        return v2.collect_once(self.store, old.SyntheticRecorder([reply()] if replies is None else replies), now, policy())
    def test_pages_once_and_failure_retained(self):
        r=old.SyntheticRecorder([reply([], True, '2026-11-11T11:00:00Z', NOW), {'ok':False}])
        first=v2.collect_once(self.store,r,NOW,policy())
        self.assertEqual(len(r.calls),2)
        self.assertEqual(len(first['history']),1)
        self.assertEqual(first['history'][0]['response'],'api_failure')
        second=self.scan([reply([])],LATER)
        self.assertEqual(second['history'][0],first['history'][0])
        self.assertEqual(second['history'][1]['coverage'],'unverified')
    def test_not_due_no_write(self):
        before=self.scan(); r=old.SyntheticRecorder([])
        after=v2.collect_once(self.store,r,NOW,policy(),scheduled=True)
        self.assertEqual(before,after); self.assertFalse(r.calls)
    def test_mock_send_proofs_and_recovery_never_append(self):
        self.scan(); adapter=v2.Projection(self.store); ident=only(adapter)[0]
        transport=old.SyntheticTransport()
        self.assertEqual(old.send_one(adapter,transport,ident,LATER,policy(send_enabled=True)),'accepted')
        self.assertEqual(len(self.store.read()['history']),1)
        before=copy.deepcopy(self.store.read()['monitor']['outbox'])
        self.scan([reply([])],AFTER)
        self.assertEqual(self.store.read()['monitor']['outbox'],before)
        self.assertEqual(old.send_one(v2.Projection(self.store),transport,ident,AFTER,policy(send_enabled=True)),'suppressed')
        self.assertEqual(len(transport.calls),1)
    def test_stale_collection_vs_reservation_conflicts(self):
        self.scan(); stale=v2.Projection(self.store); other=v2.Projection(self.store)
        ident=only(other)[0]
        old.send_one(other,old.SyntheticTransport(),ident,LATER,policy(send_enabled=True))
        before=self.store.read()
        with self.assertRaises(old.StoreConflict): old.collect_once(stale,old.SyntheticRecorder([reply([])]),AFTER,policy())
        self.assertEqual(self.store.read(),before)
    def test_history_prefix_and_run_tamper_rejected(self):
        self.scan([{'ok':False}]); before=self.store.read()
        for mode in ('delete','edit','prior','runs'):
            c=copy.deepcopy(before); c['monitor']['revision']+=1
            if mode=='delete':c['history']=[]
            if mode=='edit':c['history'][0]['response']='page'
            if mode=='prior':c['prior_runs_without_history']=1
            if mode=='runs':
                c['monitor']['ledger']['runs']+=2
                c['monitor']['ledger_digest']=old.digest(c['monitor']['ledger'])
            with self.assertRaises(ValueError):v2.transition(before,c)
    def test_full_stops_before_fetch(self):
        self.scan(); r=old.SyntheticRecorder([])
        with patch.object(history,'MAX_HISTORY',1):
            with self.assertRaisesRegex(ValueError,'FULL'):v2.collect_once(self.store,r,LATER,policy())
        self.assertFalse(r.calls)
    def test_legacy_monitor_rejects_v2(self):
        with self.assertRaises(ValueError):old.validate_bundle(self.store.read())
    def test_missing_corrupt_and_symlink_fail_closed(self):
        self.path.unlink()
        with self.assertRaises(old.StoreUncertain):self.store.read()
        self.path.write_text('{}');self.path.chmod(0o600)
        with self.assertRaises(old.StoreUncertain):self.store.read()
        self.path.unlink();self.path.symlink_to(Path(self.tmp.name)/'absent')
        with self.assertRaises(old.StoreUncertain):self.store.read()
    def test_no_reinitialize(self):
        with self.assertRaises(old.StoreConflict):self.store.initialize()
    def test_fsync_uncertain_no_retry(self):
        before=self.store.read()
        with patch.object(v2.os,'fsync',side_effect=OSError):
            with self.assertRaises(old.StoreUncertain):self.scan()
        self.assertEqual(self.store.read(),before)
    def test_directory_fsync_failure_reports_uncertain_but_coherent(self):
        real=os.fsync;calls=[]
        def fail_directory(fd):
            calls.append(fd)
            if len(calls)==2:raise OSError('injected')
            return real(fd)
        with patch.object(v2.os,'fsync',side_effect=fail_directory):
            with self.assertRaises(old.StoreUncertain):self.scan()
        result=self.store.read()
        self.assertEqual(result['monitor']['ledger']['runs'],1)
        self.assertEqual(len(result['history']),1)
        self.assertEqual(len(result['monitor']['outbox']),1)
    def test_cleanup_failure_retains_lock_and_stops_retry(self):
        real=os.unlink
        def fail_lock(path,*a,**kw):
            if str(path).endswith('.lock'):raise OSError('injected')
            return real(path,*a,**kw)
        with patch.object(v2.os,'unlink',side_effect=fail_lock):
            with self.assertRaises(old.StoreUncertain):self.scan()
        self.assertEqual(len(self.store.read()['history']),1)
        with self.assertRaises(old.StoreConflict):self.scan(now=LATER)
    def test_migration_preserves_all_legacy_states(self):
        for state in ('unattempted','reserved','accepted','known_not_sent','uncertain'):
            with self.subTest(state=state):
                source=Path(self.tmp.name)/('old-'+state)
                legacy=old.SyntheticFileCASStore(source);legacy.initialize();collect(legacy)
                ident=only(legacy)[0]
                if state=='accepted': old.send_one(legacy,old.SyntheticTransport(),ident,LATER,policy(send_enabled=True))
                elif state=='known_not_sent': old.send_one(legacy,old.SyntheticTransport(outcome='known_not_sent'),ident,LATER,policy(send_enabled=True))
                elif state in ('reserved','uncertain'):
                    c=legacy.read();e=c['outbox'][ident];e.update(state='reserved',attempt_id=old.attempt_id(ident),reserved_at=old.timestamp(old.ledger.canonical_time(LATER)))
                    old.save(legacy,legacy.read(),c)
                    if state=='uncertain':old.recover_reserved(legacy,AFTER)
                raw=source.read_bytes();dest=v2.FileStore(Path(self.tmp.name)/('new-'+state))
                dest.migrate_from(source,writers_stopped=True)
                bundle=dest.read()
                self.assertEqual(bundle['monitor'],legacy.read())
                self.assertEqual(source.read_bytes(),raw)
                self.assertEqual(bundle['prior_runs_without_history'],1)
                self.assertEqual(bundle['history'],[])
                if state!='unattempted':
                    t=old.SyntheticTransport()
                    self.assertEqual(old.send_one(v2.Projection(dest),t,ident,AFTER,policy(send_enabled=True)),'suppressed')
                    self.assertFalse(t.calls)
    def test_migration_is_explicit_no_overwrite(self):
        source=Path(self.tmp.name)/'old'; old.SyntheticFileCASStore(source).initialize()
        with self.assertRaises(ValueError):self.store.migrate_from(source)
        with self.assertRaises(old.StoreConflict):self.store.migrate_from(source,writers_stopped=True)
        with self.assertRaises(ValueError):v2.FileStore(source).migrate_from(source,writers_stopped=True)
    def test_source_busy_no_lock_theft(self):
        source=Path(self.tmp.name)/'old';old.SyntheticFileCASStore(source).initialize()
        lock=Path(str(source)+'.lock');lock.touch(mode=0o600)
        with self.assertRaises(old.StoreConflict):self.store.migrate_from(source,writers_stopped=True)
        self.assertTrue(lock.exists())
    def test_not_due_rejects_wrong_types(self):
        for recorder, pol, scheduled in [(old.SyntheticRecorder([]),policy(),1),(object(),policy(),True),(old.SyntheticRecorder([]),object(),True)]:
            with self.assertRaises(ValueError):v2.collect_once(self.store,recorder,NOW,pol,scheduled)
    def test_process_race_whole_bundle_one_commit(self):
        processes=[]
        try:
            for i in range(2):
                processes.append(subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'race',str(self.path),str(i)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={}))
            deadline=time.monotonic()+10
            while not all(Path(str(self.path)+'.ready'+str(i)).exists() for i in range(2)):
                if time.monotonic()>deadline:self.fail('BARRIER_TIMEOUT')
                time.sleep(.01)
            Path(str(self.path)+'.go').touch()
            codes=[]
            for p in processes:
                out,err=p.communicate(timeout=10);self.assertEqual(err,b'');codes.append(p.returncode)
            self.assertEqual(sorted(codes),[0,23])
            result=self.store.read()
            self.assertEqual(result['monitor']['ledger']['runs'],1)
            self.assertEqual(len(result['history']),1)
            self.assertEqual(len(result['monitor']['outbox']),1)
        finally:
            for p in processes:
                if p.poll() is None:p.kill();p.communicate()
    def test_real_sigkill_before_after_replace(self):
        for stage in ('before','after'):
            with self.subTest(stage=stage):
                p=Path(self.tmp.name)/stage;v2.FileStore(p).initialize()
                proc=subprocess.run([sys.executable,'-I',str(Path(__file__).resolve()),'kill',str(p),stage],capture_output=True,timeout=10,env={})
                self.assertEqual(proc.returncode,-signal.SIGKILL,proc.stderr)
                result=v2.FileStore(p).read()
                expected=0 if stage=='before' else 1
                self.assertEqual(result['monitor']['ledger']['runs'],expected)
                self.assertEqual(len(result['history']),expected)
                self.assertEqual(len(result['monitor']['outbox']),expected)
                with self.assertRaises(old.StoreConflict):v2.collect_once(v2.FileStore(p),old.SyntheticRecorder([reply()]),LATER,policy())
                self.assertTrue(Path(str(p)+'.lock').exists())

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='kill':
        path,stage=sys.argv[2:];real=os.replace
        def kill_replace(a,b):
            if stage=='after':real(a,b)
            os.kill(os.getpid(),signal.SIGKILL)
        v2.os.replace=kill_replace
        v2.collect_once(v2.FileStore(path),old.SyntheticRecorder([reply()]),NOW,policy())
    elif len(sys.argv)>1 and sys.argv[1]=='race':
        path,number=sys.argv[2:];adapter=v2.Projection(v2.FileStore(path))
        Path(path+'.ready'+number).touch();deadline=time.monotonic()+10
        while not Path(path+'.go').exists():
            if time.monotonic()>deadline:raise RuntimeError('BARRIER_TIMEOUT')
            time.sleep(.01)
        try:old.collect_once(adapter,old.SyntheticRecorder([reply()]),NOW,policy())
        except old.StoreConflict:sys.exit(23)
    else:unittest.main(verbosity=2)
