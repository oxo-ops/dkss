"""Focused readonly-only differential and observation guards; no live fallback."""
import contextlib
import copy
import hashlib
import json
import logging
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from sqlalchemy import Integer, event
import readonly_reconciliation as R
import readonly_legacy_core as legacy
import test_restore_sequence_batch as old_fixture
import test_restore_postgres as postgres

MODULE_SHA = lambda: hashlib.sha256(Path(R.__file__).read_bytes()).hexdigest()
READONLY_BATCH_EVIDENCE = {}

class Observer:
    application = 'worlex_reconcile_0123456789ab'
    batches = 0; sequences = 0
    def scope(self, phase): return contextlib.nullcontext()

class Conn(old_fixture.Conn):
    def __init__(self, items, mutate=None):
        super().__init__(items)
        self.transaction = SimpleNamespace(is_active=True); self.mutate = mutate
    def get_transaction(self): return self.transaction
    def in_transaction(self): return True
    def execute(self, sql, params):
        result = super().execute(str(sql), params)
        if self.mutate: self.mutate('metadata' if 'table_name,column_name' in str(sql) else 'ownership', result.x)
        return result
    def exec_driver_sql(self, sql):
        if sql.startswith("SELECT current_setting"):
            self.calls.append(sql); return old_fixture.Result([('on','repeatable read','worlex_reconcile_0123456789ab')])
        if ' AS sequence_ordinal' in sql:
            self.calls.append(sql); self.value_calls.append(sql)
            rows = []
            for branch in sql.split(' UNION ALL '):
                i = int(re.search(r'SELECT (\d+)::integer', branch)[1])
                item = next(v for v in self.items.values() if '"'+v['meta'][1]+'"' in branch)
                rows.append([i, *item['value']])
            if self.mutate: self.mutate('values', rows)
            return old_fixture.Result(rows)
        return super().exec_driver_sql(sql)

def setup(n=36):
    items, tables = old_fixture.setup(n)
    for table in tables.values(): table.primary_key[0].type = Integer()
    return items, tables

def run_new(connection, tables):
    return R.sequence_states(connection, tables, connection.get_transaction(), Observer(), legacy.q)

def journal_store():
    files = {}
    def journal(name, value):
        if name+'.json' in files: raise ValueError('duplicate')
        files[name+'.json'] = (json.dumps(value, sort_keys=True)+'\n').encode()
    return files, journal

def clean_bundle():
    files, journal = journal_store(); obs = R.Observation(journal, 'worlex_reconcile_0123456789ab')
    with obs.scope('connect'):
        obs.pid = 123; obs.checkpoint('bound')
    for phase in ('session_before','data','session_after'):
        with obs.scope(phase):
            if phase=='data':
                with obs.scope('reader_mode'): pass
                with obs.scope('plan'):
                    with obs.scope('sequence_metadata'): pass
                    with obs.scope('sequence_ownership'): pass
                    with obs.scope('sequence_values'):
                        obs.batches=1; obs.sequences=8; obs.attempted=3; obs.succeeded=3
        with obs.scope('rollback', cleanup=True): pass
    with obs.scope('close', cleanup=True): pass
    with obs.scope('dispose', cleanup=True): pass
    obs.finish()
    return files

class ReadOnlySequenceTests(unittest.TestCase):
    def test_legacy_source_pin_and_no_production_changes(self):
        self.assertEqual(hashlib.sha256(Path(legacy.__file__).read_bytes()).hexdigest(), R.LEGACY_CORE_SHA256)
        root=Path(R.__file__).parent
        self.assertEqual(hashlib.sha256((root/'worlex_restore.py').read_bytes()).hexdigest(), 'b43ba710a6dd48a831d5236293df7a59655ae637f3d9a62071aba23a086df118')
        self.assertEqual(hashlib.sha256((root/'launcher_adapter.py').read_bytes()).hexdigest(), '083eedc180ea773790a3672ef5a344933642073366553e96cf9d8587a3ce07ba')

    def test_complete_state_shape_and_bounded_16_value_reads(self):
        for count in (0,1,16,17,36,256):
            items,tables=setup(count) if count else ({},{})
            old,new=Conn(items),Conn(items)
            before=legacy.sequence_states(old,tables); after=run_new(new,tables)
            self.assertEqual(before,after)
            self.assertEqual(len(new.value_calls),(count+15)//16)
            self.assertTrue(all(len(sql.encode())<=R.MAX_SQL_BYTES and sql.count('SELECT ')<=16 for sql in new.value_calls))
            if count:self.assertEqual(before[('push_subscription','id')],after[('push_subscription','id')])

    def test_value_results_are_order_independent_and_exact_typed(self):
        items,tables=setup()
        c=Conn(items,lambda phase, rows: rows.reverse() if phase=='values' else None)
        self.assertEqual(run_new(c,tables),legacy.sequence_states(Conn(items),tables))
        for change in (lambda rows: rows.pop(),lambda rows: rows.append(rows[0]),
                       lambda rows: rows[0].__setitem__(0,True),lambda rows: rows[0].__setitem__(0,999),
                       lambda rows: rows[1].__setitem__(0,rows[0][0]),lambda rows: rows[0].__setitem__(1,True),
                       lambda rows: rows[0].__setitem__(1,None),lambda rows: rows[0].__setitem__(2,1),
                       lambda rows: rows[0].__setitem__(3,False),lambda rows: rows[0].__setitem__(3,-1)):
            def mutate(phase,rows):
                if phase=='values':change(rows)
            with self.subTest(change=change),self.assertRaises(R.ReadOnlyStop):run_new(Conn(items,mutate),tables)

    def test_unknown_metadata_and_ownership_fail_before_values(self):
        cases=[('metadata',lambda r:r.pop()),('metadata',lambda r:r.append(r[0])),
               ('metadata',lambda r:r.__setitem__(0,(True,*r[0][1:]))),
               ('metadata',lambda r:r.__setitem__(0,(*r[0][:2],'private',*r[0][3:]))),
               ('metadata',lambda r:r.__setitem__(0,(*r[0][:11],999,*r[0][12:]))),
               ('ownership',lambda r:r.clear()),('ownership',lambda r:r.append(r[0])),
               ('ownership',lambda r:r.__setitem__(0,(999,*r[0][1:]))),
               ('ownership',lambda r:r.__setitem__(0,(*r[0][:3],'n')))]
        for phase,change in cases:
            items,tables=setup()
            c=Conn(items,lambda p,r:change(r) if p==phase else None)
            with self.subTest(phase=phase,change=change),self.assertRaises(R.ReadOnlyStop):run_new(c,tables)
            self.assertEqual(c.value_calls,[])

    def test_original_sequence_guards_and_nonserial_keys_remain(self):
        for index,value in ((0,'other'),(11,2),(12,2),(14,2),(15,True)):
            items,tables=setup();items['push_subscription']['meta'][index]=value
            with self.assertRaises(R.ReadOnlyStop):run_new(Conn(items),tables)
        items,tables=setup();items['push_subscription']['seq']=None
        with self.assertRaises(R.ReadOnlyStop):run_new(Conn(items),tables)
        tables['push_subscription'].primary_key[0].name='code';tables['push_subscription'].primary_key[0].type=object()
        self.assertEqual(run_new(Conn(items),tables),legacy.sequence_states(Conn(items),tables))

    def test_transaction_swap_fails_after_every_read_no_retry(self):
        for target in ('metadata','ownership','values'):
            items,tables=setup();c=Conn(items)
            def mutate(phase, rows):
                if phase==target:c.transaction=SimpleNamespace(is_active=True)
            c.mutate=mutate
            with self.subTest(target=target),self.assertRaisesRegex(R.ReadOnlyStop,'TRANSACTION_CHANGED'):run_new(c,tables)
            self.assertLessEqual(len(c.value_calls),1)

    def test_batch_failure_propagates_once_no_partial_result(self):
        items,tables=setup();error=RuntimeError('synthetic secret')
        calls=[]
        def mutate(phase,rows):
            if phase=='values':
                calls.append(1)
                if len(calls)==2:raise error
        with self.assertRaises(RuntimeError) as caught:run_new(Conn(items,mutate),tables)
        self.assertIs(caught.exception,error);self.assertEqual(len(calls),2)

    def test_context_binds_original_and_restores_on_success_and_failure(self):
        items,tables=setup();original=legacy.sequence_states;c=Conn(items)
        for fail in (False,True):
            try:
                with R.reader(legacy,c,expected_core_sha256=R.LEGACY_CORE_SHA256,expected_module_sha256=MODULE_SHA(),observer=Observer()):
                    self.assertIsNot(legacy.sequence_states,original)
                    self.assertEqual(legacy.sequence_states(c,tables),original(Conn(items),tables))
                    if fail:raise RuntimeError('failure')
            except RuntimeError:
                if not fail:raise
            self.assertIs(legacy.sequence_states,original);self.assertFalse(R._ACTIVE)

    def test_context_rejects_lock_other_connection_nested_changed_function_and_hash(self):
        items,tables=setup();c=Conn(items);original=legacy.sequence_states
        kwargs=dict(expected_core_sha256=R.LEGACY_CORE_SHA256,expected_module_sha256=MODULE_SHA(),observer=Observer())
        with R.reader(legacy,c,**kwargs):
            count=len(c.calls)
            for lock in (True,None,0,1):
                with self.assertRaises(R.ReadOnlyStop):legacy.sequence_states(c,tables,lock)
            self.assertEqual(len(c.calls),count)
            with self.assertRaises(R.ReadOnlyStop):legacy.sequence_states(Conn(items),tables)
            with self.assertRaises(R.ReadOnlyStop):
                with R.reader(legacy,c,**kwargs):pass
        for change in ({'expected_core_sha256':'0'*64},{'expected_module_sha256':'0'*64}):
            with self.assertRaises(R.ReadOnlyStop):
                with R.reader(legacy,c,**{**kwargs,**change}):pass
        with patch.object(legacy,'sequence_states',lambda *args:None),self.assertRaises(R.ReadOnlyStop):
            with R.reader(legacy,c,**kwargs):pass
        with self.assertRaises(R.ReadOnlyStop):
            with R.reader(legacy,c,**kwargs):legacy.sequence_states=lambda *args:None
        self.assertIs(legacy.sequence_states,original)

    def test_readonly_repeatable_read_is_required_and_request_limit_is_bounded(self):
        items,tables=setup();c=Conn(items)
        for modes in (('off','repeatable read',Observer.application),('on','read committed',Observer.application),('ON','repeatable read',Observer.application),('on','repeatable read','wrong_app')):
            with patch.object(c,'exec_driver_sql',return_value=old_fixture.Result([modes])),self.assertRaises(R.ReadOnlyStop):
                with R.reader(legacy,c,expected_core_sha256=R.LEGACY_CORE_SHA256,expected_module_sha256=MODULE_SHA(),observer=Observer()):pass
        items,tables=setup(257);c=Conn(items)
        with self.assertRaises(R.ReadOnlyStop):run_new(c,tables)
        self.assertEqual(c.calls,[])

class ReadOnlyObservationTests(unittest.TestCase):
    def test_clean_bundle_exact_files_and_nested_phase_order(self):
        files=clean_bundle()
        result=R.validate_observation_bundle(files,expected_application='worlex_reconcile_0123456789ab')
        self.assertIs(result['clean'],True)
        for name in list(files):
            changed=dict(files);del changed[name]
            with self.assertRaises(R.ReadOnlyStop):R.validate_observation_bundle(changed,expected_application='worlex_reconcile_0123456789ab')
        changed=dict(files);changed['extra.json']=b'{}'
        with self.assertRaises(R.ReadOnlyStop):R.validate_observation_bundle(changed,expected_application='worlex_reconcile_0123456789ab')

    def test_bundle_rejects_malformed_incomplete_secret_and_counter_mutations(self):
        for key,value in (('clean',False),('backend_pid',True),('primary',{'secret':'x'}),('cleanup',[{}]),('journal_failed',True),('extra','secret')):
            files=clean_bundle();final=json.loads(files['readonly-observation.json']);final[key]=value
            files['readonly-observation.json']=json.dumps(final).encode()
            with self.subTest(key=key),self.assertRaises(R.ReadOnlyStop):R.validate_observation_bundle(files,expected_application='worlex_reconcile_0123456789ab')
        for key,value in (('queries_attempted',True),('queries_succeeded',99999),('sequence_batches',-1),('backend_pid',999),('phase','secret'),('event','failed'),('index',True),('utc','2000-01-01T00:00:00.000Z'),('extra','secret')):
            files=clean_bundle();final=json.loads(files['readonly-observation.json']);final['events'][4][key]=value
            files['observation-0005.json']=json.dumps(final['events'][4]).encode();files['readonly-observation.json']=json.dumps(final).encode()
            with self.subTest(key=key),self.assertRaises(R.ReadOnlyStop):R.validate_observation_bundle(files,expected_application='worlex_reconcile_0123456789ab')
        for raw in (b'{',b'{"a":1,"a":2}',b'{"a":NaN}'):
            files=clean_bundle();files['readonly-observation.json']=raw
            with self.assertRaises((ValueError,R.ReadOnlyStop)):R.validate_observation_bundle(files,expected_application='worlex_reconcile_0123456789ab')

    def test_primary_and_swallowed_pool_cleanup_are_separate_secret_free(self):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool
        engine=create_engine('sqlite://',poolclass=NullPool,echo=False)
        files,journal=journal_store();obs=R.Observation(journal,'worlex_reconcile_0123456789ab')
        error=RuntimeError('postgres://credential SECRET SQL value');error.__cause__=Exception({'C':'57014','M':'secret'})
        logger=logging.getLogger('sqlalchemy.pool.impl.NullPool');before=(logger.handlers[:],logger.level,logger.propagate)
        with obs.install(engine):
            try:
                with obs.scope('data'):raise error
            except RuntimeError:pass
            with obs.scope('close',cleanup=True):
                try:raise OSError('secret cleanup')
                except OSError:logger.error('secret termination %s',object(),exc_info=True)
        self.assertEqual((logger.handlers,logger.level,logger.propagate),before)
        self.assertEqual(obs.primary,{'phase':'data','error_type':'RuntimeError','sqlstate':'57014'})
        self.assertEqual(obs.cleanup[0]['operation'],'pool_termination')
        with self.assertRaises(R.ReadOnlyStop):obs.require_clean()
        final=obs.finish();serialized=json.dumps(final)
        self.assertNotIn('secret',serialized.lower());self.assertNotIn('postgres://',serialized)
        self.assertEqual(obs.primary['phase'],'data');self.assertFalse(final['clean']);engine.dispose()

    def test_cleanup_only_pool_failure_never_allows_success(self):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool
        engine=create_engine('sqlite://',poolclass=NullPool,echo=False)
        files,journal=journal_store();obs=R.Observation(journal,'worlex_reconcile_0123456789ab')
        with obs.install(engine):
            with obs.scope('close',cleanup=True):logging.getLogger('sqlalchemy.pool.impl.NullPool').error('ignored private value')
        self.assertIsNone(obs.primary);self.assertEqual(len(obs.cleanup),1)
        with self.assertRaises(R.ReadOnlyStop):obs.require_clean()
        engine.dispose()

    def test_mandatory_journal_failure_preserves_primary_and_still_runs_cleanup(self):
        seen=[];writes=[]
        def failing(name,value):
            writes.append(name);raise PermissionError('private path')
        obs=R.Observation(failing,'worlex_reconcile_0123456789ab');obs.capture(RuntimeError('primary'))
        with self.assertRaises(PermissionError):
            with obs.scope('close',cleanup=True):seen.append('closed')
        self.assertEqual(seen,['closed']);self.assertEqual(obs.primary['error_type'],'RuntimeError')
        self.assertEqual(obs.cleanup[0]['operation'],'journal')
        with self.assertRaises(R.ReadOnlyStop):obs.require_clean()
        with self.assertRaises(R.ReadOnlyStop):obs.finish()
        self.assertFalse(obs.finished);self.assertEqual(writes,['observation-0001'])
        final_writes=[]
        def final_failure(name,value):
            final_writes.append(name)
            if name=='readonly-observation':raise OSError('private final path')
        obs=R.Observation(final_failure,'worlex_reconcile_0123456789ab')
        with self.assertRaises(OSError):obs.finish()
        before=list(final_writes)
        with self.assertRaises(R.ReadOnlyStop):obs.finish()
        with self.assertRaises(R.ReadOnlyStop):obs.checkpoint('complete')
        self.assertEqual(final_writes,before);self.assertEqual(before,['observation-0001','readonly-observation'])
        self.assertTrue(obs.failed_io);self.assertFalse(obs.finished)

    def test_observer_removal_errors_restore_logger_and_keep_original_primary(self):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool
        engine=create_engine('sqlite://',poolclass=NullPool,echo=False)
        files,journal=journal_store();obs=R.Observation(journal,'worlex_reconcile_0123456789ab')
        logger=logging.getLogger('sqlalchemy.pool.impl.NullPool');before=(logger.handlers[:],logger.level,logger.propagate)
        calls=[];original=RuntimeError('primary')
        real_remove=event.remove
        def remove(*args):
            calls.append(args[1]);real_remove(*args)
            if len(calls)==1:raise PermissionError('private file')
        with patch.object(event,'remove',side_effect=remove),self.assertRaises(RuntimeError) as caught:
            with obs.install(engine):
                obs.capture(original);raise original
        self.assertIs(caught.exception,original);self.assertEqual(len(calls),3)
        self.assertEqual((logger.handlers,logger.level,logger.propagate),before)
        self.assertEqual(obs.cleanup[0]['operation'],'observer_remove');self.assertFalse(obs.installed)
        with self.assertRaises(R.ReadOnlyStop):obs.require_clean()
        engine.dispose()

    def test_actual_sqlalchemy_absorbed_terminate_error_is_captured(self):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool
        engine=create_engine('sqlite://',poolclass=NullPool,echo=False)
        files,journal=journal_store();obs=R.Observation(journal,'worlex_reconcile_0123456789ab')
        with obs.install(engine):
            c=engine.connect()
            with patch.object(engine.dialect,'do_terminate',side_effect=OSError('secret terminate')):
                with obs.scope('close',cleanup=True):c.invalidate()
            c.close()
        self.assertTrue(any(item['operation']=='pool_termination' for item in obs.cleanup))
        with self.assertRaises(R.ReadOnlyStop):obs.require_clean()
        engine.dispose()

    def test_bundle_rejects_reordered_phases_and_unfinished_query(self):
        for mode in ('reorder','incomplete','inner','bound'):
            files=clean_bundle();final=json.loads(files['readonly-observation.json'])
            for item in final['events']:
                if mode=='reorder':
                    item['phase']={'session_before':'session_after','session_after':'session_before'}.get(item['phase'],item['phase'])
                elif mode=='inner':
                    item['phase']={'sequence_metadata':'sequence_values','sequence_values':'sequence_metadata'}.get(item['phase'],item['phase'])
                elif mode=='bound':
                    if item['event']=='bound':item['phase']='outside'
                else:item['queries_attempted']+=1
                files['observation-%04d.json'%item['index']]=json.dumps(item).encode()
            files['readonly-observation.json']=json.dumps(final).encode()
            with self.subTest(mode=mode),self.assertRaises(R.ReadOnlyStop):R.validate_observation_bundle(files,expected_application='worlex_reconcile_0123456789ab')

    def test_pid_never_retains_cancel_key_and_sqlstate_is_whitelisted(self):
        files,journal=journal_store();obs=R.Observation(journal,'worlex_reconcile_0123456789ab')
        Raw=type('Connection',(),{'__module__':'pg8000.legacy'})
        raw=Raw();raw._backend_key_data=__import__('struct').pack('!ii',123,987654321)
        obs.bind_connection(SimpleNamespace(connection=SimpleNamespace(driver_connection=raw)))
        self.assertEqual(obs.pid,123);self.assertNotIn('987654321',str(files))
        for value in ('ABCDE','XXXXX','secret',None,12345):self.assertIsNone(R.safe_error(Exception({'C':value}))['sqlstate'])

class PostgreSQLReadOnlyReconciliationAcceptance(unittest.TestCase):
    setUpClass=classmethod(postgres.PostgreSQLRestoreAcceptance.setUpClass.__func__)
    setUp=postgres.PostgreSQLRestoreAcceptance.setUp
    preserved_audit=postgres.PostgreSQLRestoreAcceptance.preserved_audit
    existing_push=postgres.PostgreSQLRestoreAcceptance.existing_push

    def prepare(self):
        self.preserved_audit();self.preserved_audit(company='ITC',identifier=2);self.existing_push()
        with self.engine.connect() as c:
            self.oldplan=legacy.plan(c,self.data,self.columns,self.policy,self.counts,self.source_hash)
        self.assertEqual(self.oldplan['runner_sha256'],R.LEGACY_CORE_SHA256)

    def compare_readonly(self, present):
        original=legacy.sequence_states; trace=[];files,journal=journal_store()
        obs=R.Observation(journal,'worlex_reconcile_0123456789ab')
        engine=postgres.create_engine(self.url,poolclass=postgres.NullPool,hide_parameters=True,echo=False,
            connect_args=postgres.connection_args(cafile=self.cafile,application_name=obs.application,read_only=True))
        with obs.install(engine):
            with obs.scope('connect'):
                c=engine.connect();postgres.assert_pg8000_tls(c);obs.bind_connection(c)
            try:
                for phase in ('session_before','data','session_after'):
                    tx=c.begin()
                    try:
                        with obs.scope(phase):
                            c.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                            if phase!='data':
                                self.assertEqual(c.exec_driver_sql('SELECT 1').scalar_one(),1)
                                continue
                            tables,_=legacy.validate_schema(c,self.policy)
                            audits=[int(row['id']) for row in self.data['audit_log']] if present else ()
                            before=legacy.snapshot(c,tables,audit_import_ids=audits)
                            serial=original(c,tables)
                            operation=legacy.verify_restore if present else legacy.plan
                            args=(c,self.data,self.columns,self.policy,self.counts,self.source_hash)
                            kwargs={} if present else {'generated':self.oldplan['generated_identifiers']}
                            old=operation(*args,self.oldplan) if present else operation(*args,**kwargs)
                            if not present:self.assertEqual(old,self.oldplan)
                            def record(conn,cursor,statement,parameters,context,executemany):trace.append(statement)
                            event.listen(c,'before_cursor_execute',record)
                            try:batched=R.sequence_states(c,tables,tx,Observer(),legacy.q)
                            finally:event.remove(c,'before_cursor_execute',record)
                            with R.reader(legacy,c,expected_core_sha256=R.LEGACY_CORE_SHA256,expected_module_sha256=MODULE_SHA(),observer=obs):
                                with obs.scope('verify_restore' if present else 'plan'):
                                    new=operation(*args,self.oldplan) if present else operation(*args,**kwargs)
                                self.assertEqual(new,old);self.assertEqual(batched,serial)
                            self.assertIs(legacy.sequence_states,original)
                            self.assertEqual(before,legacy.snapshot(c,tables,audit_import_ids=audits))
                            self.assertEqual(serial,original(c,tables))
                    finally:
                        with obs.scope('rollback',cleanup=True):tx.rollback()
            finally:
                try:
                    with obs.scope('close',cleanup=True):c.close()
                finally:
                    with obs.scope('dispose',cleanup=True):engine.dispose()
        obs.require_clean();obs.finish()
        verified=R.validate_observation_bundle(files,expected_application='worlex_reconcile_0123456789ab')
        self.assertTrue(verified['clean']);self.assertGreater(verified['backend_pid'],0)
        self.assertGreater(len(serial),30)
        self.assertEqual(len(trace),2+(len(serial)+15)//16)
        self.assertTrue(all(sql.startswith(('WITH','SELECT')) for sql in trace))
        self.assertEqual(serial[('push_subscription','id')],batched[('push_subscription','id')])
        return {'synthetic_only':True,'actual_postgres_18':True,'legacy_core_sha256':R.LEGACY_CORE_SHA256,
            'complete_plan_or_verify_equal':True,'complete_sequence_dict_equal':True,
            'preserved_itc_audit_settings_push_equal':True,'same_readonly_transaction':True,
            'actual_observer_pid_and_clean_bundle':True,
            'sequences':len(serial),'old_sequence_queries':len(serial)+2,'new_sequence_queries':len(trace),
            'max_branches':16,'max_sql_bytes':32768,'restore_retried':False}

    def test_before_commit_disconnect_keeps_full_legacy_plan_and_sequences_equal(self):
        self.prepare();conn=self.engine.connect();tx=conn.begin()
        try:
            legacy.execute_restore(conn,self.data,self.columns,self.policy,self.counts,self.source_hash,self.oldplan)
            conn.connection.driver_connection.close();conn.invalidate()
        finally:
            with contextlib.suppress(Exception):tx.rollback()
            conn.close()
        result=self.compare_readonly(False);result['classification']='absent';result['actual_close_before_commit']=True
        READONLY_BATCH_EVIDENCE['before_commit']=result

    def test_after_commit_outcome_loss_keeps_full_legacy_verify_and_sequences_equal(self):
        self.prepare()
        with self.engine.begin() as conn:legacy.execute_restore(conn,self.data,self.columns,self.policy,self.counts,self.source_hash,self.oldplan)
        # The commit happened; a client outcome-loss exception is modeled after it.
        # This is not a network-packet-loss experiment and is never a retry.
        try:raise RuntimeError('synthetic outcome loss after real commit')
        except RuntimeError:pass
        result=self.compare_readonly(True);result['classification']='present';result['real_commit_before_outcome_loss']=True
        READONLY_BATCH_EVIDENCE['after_commit']=result
