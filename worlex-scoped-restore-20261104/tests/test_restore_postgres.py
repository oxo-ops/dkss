"""Synthetic PG18 acceptance, restricted to the workflow-owned service container.
Never reads an archive and never accepts a production connection.
"""
import copy, hashlib, json, os, pathlib, secrets, subprocess, sys, tempfile, unittest, uuid
from unittest.mock import patch
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from worlex_restore import Stop, validate_schema, typed_payload, snapshot, plan, execute_restore, verify_restore, digest, sequence_states
from synthetic_fixture import fixture, PASSWORD
PACKAGE=pathlib.Path(__file__).resolve().parents[1]
APP=pathlib.Path(os.environ.get('WORLEX_TEST_APP_SOURCE',PACKAGE.parent)).resolve()
MARKER='WORLEX_RESTORE_SYNTHETIC_ONLY'

def validate_service_url(value,environment):
 if environment.get('GITHUB_ACTIONS')!='true' or environment.get('GITHUB_REPOSITORY')!='oxo-ops/dkss':raise Stop('DEDICATED_CI_ONLY')
 u=make_url(value)
 if (u.drivername!='postgresql+psycopg2' or u.host!='127.0.0.1' or u.database!='dkss_restore_ci' or u.username!='restore_ci' or u.password!='restore-disposable-synthetic-only' or u.port is None or u.query):raise Stop('REFUSING_NONTEST_CONNECTION')
 return u

class ServiceGuardTests(unittest.TestCase):
 def test_dedicated_service_and_rejections(self):
  env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'oxo-ops/dkss'}
  value='postgresql+psycopg2://restore_ci:restore-disposable-synthetic-only@127.0.0.1:5432/dkss_restore_ci'
  self.assertEqual(validate_service_url(value,env).database,'dkss_restore_ci')
  for invalid in [value.replace('127.0.0.1','external.invalid'),value.replace('dkss_restore_ci','production'),value+'?host=other',value.replace('restore_ci:','real_user:')]:
   with self.assertRaises(Stop):validate_service_url(invalid,env)
  with self.assertRaises(Stop):validate_service_url(value,{})

class PostgreSQLRestoreAcceptance(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if os.environ.get('WORLEX_REQUIRE_POSTGRES')!='1':raise unittest.SkipTest('Explicit isolated PostgreSQL service required; no local/live fallback')
  cls.service=validate_service_url(os.environ.get('WORLEX_TEST_POSTGRES_URL',''),os.environ)
  manifest=json.loads((PACKAGE/'source-manifest.json').read_text())
  if not all((APP/n).is_file() and hashlib.sha256((APP/n).read_bytes()).hexdigest()==v for n,v in manifest['files'].items()):raise Stop('PINNED_APPLICATION_SOURCE_MISMATCH')
  cls.admin=create_engine(cls.service,poolclass=NullPool,isolation_level='AUTOCOMMIT',hide_parameters=True,connect_args={'hostaddr':'127.0.0.1','connect_timeout':5})
  cls.addClassCleanup(cls.admin.dispose)
  with cls.admin.connect() as c:
   if os.name=='nt':
    raw=c.connection.driver_connection
    if not raw.info.ssl_in_use or raw.get_dsn_parameters().get('sslmode')!='verify-full':raise Stop('WINDOWS_ADMIN_TLS_NOT_VERIFIED')
   if c.scalar(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"))!=MARKER:raise Stop('UNMARKED_CI_DATABASE')
   if c.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'"))!=0:raise Stop('CI_MARKER_DATABASE_MUST_REMAIN_EMPTY')
   version=c.scalar(text('SHOW server_version_num'))
   if not 180000<=int(version)<190000:raise Stop('POSTGRES_18_REQUIRED')
  cls.base_policy=json.loads((PACKAGE/'policy.json').read_text());cls.seal_written=False
 def setUp(self):
  self.name='restore_owned_'+uuid.uuid4().hex
  with self.admin.connect() as c:c.exec_driver_sql('CREATE DATABASE "'+self.name+'" TEMPLATE template0')
  self.url=self.service.set(database=self.name)
  self.engine=create_engine(self.url,poolclass=NullPool,hide_parameters=True,connect_args={'hostaddr':'127.0.0.1','connect_timeout':5})
  self.addCleanup(self.engine.dispose)
  with self.engine.begin() as c:
   self.assertEqual(c.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")),0)
   c.exec_driver_sql("COMMENT ON DATABASE \""+self.name+"\" IS 'WORLEX_RESTORE_SYNTHETIC_ONLY'")
  self.temp=tempfile.TemporaryDirectory(prefix='worlex-synthetic-');self.addCleanup(self.temp.cleanup)
  env={'PATH':os.defpath,'HOME':self.temp.name,'LANG':'C.UTF-8','TZ':'UTC','PYTHONPATH':str(APP),'PYTHONDONTWRITEBYTECODE':'1','FLASK_SKIP_DOTENV':'1','DATABASE_URL':self.url.render_as_string(hide_password=False),'SECRET_KEY':secrets.token_urlsafe(40),'ITC_INITIAL_PASSWORD':'Synthetic-ITC-Only!','RENDER':'','AWS_EC2_METADATA_DISABLED':'true','AWS_CONFIG_FILE':os.devnull,'AWS_SHARED_CREDENTIALS_FILE':os.devnull,'S3_BUCKET_NAME':'','OPENAI_API_KEY':'','SMTP_HOST':'','VAPID_PRIVATE_KEY':'','VAPID_PUBLIC_KEY':'','DOCUMENT_IMPORT_WORKER_ENABLED':'0','ANALYSIS_READ_CACHE_ENABLED':'0','RATELIMIT_STORAGE_URI':'memory://'}
  # Windows loader requirements and the CI-owned TLS trust are the only
  # inherited values allowed into the otherwise isolated application child.
  for key in ('SYSTEMROOT','WINDIR','TEMP','TMP','PGSSLMODE','PGSSLROOTCERT'):
   if key in os.environ:env[key]=os.environ[key]
  if os.name=='nt':
   if env.get('PGSSLMODE')!='verify-full' or not pathlib.Path(env.get('PGSSLROOTCERT','')).is_file():raise Stop('WINDOWS_CI_TLS_REQUIRED')
   env['PATH']=str(pathlib.Path(sys.executable).parent)+os.pathsep+str(pathlib.Path(env['SYSTEMROOT'])/'System32')
  self.env=env
  setup="""import os
from dkss_app import create_app
from dkss_app.extensions import db
from dkss_app.driving_access import initialize_driving_access
from dkss_app.vehicle_couplings import initialize_coupling_schema
app=create_app(initialize_database=False)
with app.app_context():
 if os.name=='nt':
  with db.engine.connect() as connection:
   raw=connection.connection.driver_connection
   if not raw.info.ssl_in_use or raw.get_dsn_parameters().get('sslmode')!='verify-full':raise RuntimeError('WINDOWS_APP_TLS_NOT_VERIFIED')
 result=app.test_cli_runner().invoke(args=['init-db'])
 if result.exit_code: raise RuntimeError('SYNTHETIC_INIT_FAILED') from result.exception
 initialize_driving_access(app)
 initialize_coupling_schema(app)
"""
  result=subprocess.run([sys.executable,'-c',setup],cwd=APP,env=env,capture_output=True,text=True,timeout=180)
  self.assertEqual(result.returncode,0,'Synthetic schema initialization failed; output intentionally not logged')
  self.policy=copy.deepcopy(self.base_policy)
  with self.engine.begin() as c:
   tables,signature=validate_schema(c,self.policy,building_ci_seal=True)
   self.policy['postgres_structure_sha256']=signature
   self.policy['postgres_acceptance_passed']=True
   self.policy['windows_render_acceptance_passed']=True
   self.policy['tested_runner_sha256']=hashlib.sha256((PACKAGE/'worlex_restore.py').read_bytes()).hexdigest()
   # Distinct unrelated tenant and very high sequence state prove no rewind.
   c.execute(tables['company'].insert(),{'id':900000,'company_code':'SYNTHETIC_OTHER','company_name':'Synthetic Other','active':True,'vehicle_limit':5})
   c.execute(tables['vehicle'].insert(),{'id':900000,'company_code':'SYNTHETIC_OTHER','chassis_number':'SYNTHETIC-OTHER-CHASSIS','deleted':False})
   c.exec_driver_sql('ALTER SEQUENCE public.company_id_seq RESTART WITH 950000')
  self.data,self.columns,self.counts=fixture(self.policy,json.loads((PACKAGE/'source-counts.json').read_text()).keys())
  self.source_hash=digest({'columns':self.columns,'data':self.data})
  with self.engine.connect() as c:
   self.approved=plan(c,self.data,self.columns,self.policy,self.counts,self.source_hash)
   self.tables,_=validate_schema(c,self.policy)
   self.before=snapshot(c,self.tables);self.seq_before=sequence_states(c,self.tables)
 def restore(self,**kw):
  with self.engine.begin() as c:return execute_restore(c,self.data,self.columns,self.policy,self.counts,self.source_hash,self.approved,**kw)
 def unchanged(self):
  with self.engine.connect() as c:
   tables,_=validate_schema(c,self.policy)
   self.assertEqual(snapshot(c,tables),self.before)
   self.assertEqual(sequence_states(c,tables),self.seq_before)
   for t in tables.values():
    if 'company_code' in t.c:self.assertEqual(c.scalar(select(func.count()).select_from(t).where(t.c.company_code=='WORLEX')),0)
 def test_full_count_fixture_all_tables_constraints_and_preservation(self):
  from test_restore_full_fixture import assert_full_postgres_coverage
  assert_full_postgres_coverage(self)
 def test_commit_preserves_rows_blobs_ownership_and_sequence_next_insert(self):
  result=self.restore();self.assertEqual(result['status'],'TRANSACTION_VERIFIED')
  with self.engine.begin() as c:
   c.exec_driver_sql('SET TRANSACTION READ ONLY')
   verified=verify_restore(c,self.data,self.columns,self.policy,self.counts,self.source_hash,self.approved)
   self.assertEqual(verified['status'],'RESTORE_PRESENT_MATCHES_PLAN')
  self.assertTrue(result['non_worlex_and_global_rows_unchanged']);self.assertGreater(result['derived_rows']['analysis_input_epoch'],0)
  with self.engine.begin() as c:
   self.assertEqual(c.scalar(text("SELECT count(*) FROM public.\"user\" WHERE company_code='WORLEX'")),15)
   self.assertEqual(c.scalar(text("SELECT count(*) FROM public.vehicle WHERE company_code='WORLEX' AND NOT deleted")),289)
   self.assertEqual(c.scalar(text("SELECT count(*) FROM public.vehicle WHERE company_code='WORLEX' AND deleted")),276)
   self.assertEqual(c.scalar(text("SELECT count(*) FROM public.notification WHERE company_code='WORLEX' AND owner_identity IS NOT NULL")),0)
   self.assertEqual(c.scalar(text("SELECT count(*) FROM public.vehicle_document_import_draft WHERE company_code='WORLEX' AND owner_identity IS NOT NULL")),0)
   self.assertEqual(c.scalar(text('SELECT last_value FROM public.company_id_seq')),950000)
   # Disposable fixture only: prove the very next generated ID cannot collide.
   new_id=c.scalar(text("INSERT INTO public.vehicle(company_code,chassis_number,deleted) VALUES ('SYNTHETIC_OTHER','SYNTHETIC-NEXT',false) RETURNING id"))
   self.assertGreater(new_id,900000)
  evidence=pathlib.Path(os.environ.get('WORLEX_EVIDENCE_DIR',self.temp.name));evidence.mkdir(exist_ok=True)
  candidate=copy.deepcopy(self.policy);candidate.pop('postgres_acceptance_passed',None);candidate.pop('windows_render_acceptance_passed',None)
  (evidence/'candidate-policy.json').write_text(json.dumps(candidate,indent=2,sort_keys=True))
 def test_read_only_reconciliation_and_modified_payload_rejected(self):
  self.restore()
  with self.engine.begin() as c:
   c.exec_driver_sql('SET TRANSACTION READ ONLY')
   result=verify_restore(c,self.data,self.columns,self.policy,self.counts,self.source_hash,self.approved)
   self.assertEqual(result['status'],'RESTORE_PRESENT_MATCHES_PLAN')
  # Synthetic negative control only; no production route exposes an UPDATE.
  with self.engine.begin() as c:
   c.exec_driver_sql("UPDATE public.vehicle SET type='TAMPERED_SYNTHETIC' WHERE company_code='WORLEX' AND id=2")
  with self.engine.begin() as c:
   c.exec_driver_sql('SET TRANSACTION READ ONLY')
   with self.assertRaisesRegex(Stop,'VERIFY_SOURCE_VALUE_MISMATCH'):verify_restore(c,self.data,self.columns,self.policy,self.counts,self.source_hash,self.approved)
 def test_rollback_after_sequences_restores_rows_column_triggers_and_sequences(self):
  with self.assertRaisesRegex(Stop,'INJECTED_ROLLBACK_PROBE'):self.restore(inject_failure='after_sequences')
  self.unchanged()
 def test_replay_is_rejected(self):
  self.restore()
  with self.assertRaises(Stop):self.restore()
 def test_case_alias_is_rejected(self):
  with self.engine.begin() as c:c.exec_driver_sql("INSERT INTO public.company(id,company_code,company_name) VALUES (800000,'worlex','Synthetic alias')")
  with self.assertRaisesRegex(Stop,'CASE_ALIAS'):self.restore()
 def test_pk_conflict_is_rejected_before_insert(self):
  with self.engine.begin() as c:c.exec_driver_sql("INSERT INTO public.vehicle(id,company_code,chassis_number) VALUES (2,'SYNTHETIC_OTHER','SYNTHETIC-CONFLICT')")
  with self.assertRaisesRegex(Stop,'PRIMARY_KEY_COLLISION'):self.restore()
 def test_second_connection_is_rejected(self):
  with self.engine.connect() as other:
   other.exec_driver_sql('SELECT 1')
   with self.assertRaisesRegex(Stop,'OTHER_DATABASE_SESSIONS_PRESENT'):self.restore()
 def test_changed_schema_is_rejected(self):
  with self.engine.begin() as c:c.exec_driver_sql('DROP INDEX public.uq_office_company_name')
  with self.assertRaisesRegex(Stop,'CATALOG_DIFFERS'):self.restore()
 def test_unsealed_policy_is_rejected(self):
  for key in ('postgres_structure_sha256','windows_render_acceptance_passed'):
   previous=self.policy.pop(key)
   with self.subTest(key=key),self.assertRaisesRegex(Stop,'CI_SEAL_REQUIRED'):self.restore()
   self.policy[key]=previous
 def preserved_audit(self,*,company='WORLEX',identifier=1,created='2026-11-04 07:55:08'):
  row={'id':identifier,'company_code':company,'username':'synthetic-current-user','action':'login_failed','target_type':'user','detail':'synthetic existing immutable log','created_at':created}
  with self.engine.begin() as c:c.execute(self.tables['audit_log'].insert(),row)
  return row
 def approve_current(self):
  with self.engine.connect() as c:
   self.approved=plan(c,self.data,self.columns,self.policy,self.counts,self.source_hash)
 def verify_current(self):
  with self.engine.begin() as c:
   c.exec_driver_sql('SET TRANSACTION READ ONLY')
   return verify_restore(c,self.data,self.columns,self.policy,self.counts,self.source_hash,self.approved)
 def test_existing_one_audit_and_all_423_source_audits_survive(self):
  self.preserved_audit();self.approve_current()
  self.assertEqual(self.approved['push_subscription_id_remap'],{})
  with self.engine.connect() as c:before=dict(c.execute(select(self.tables['audit_log']).where(self.tables['audit_log'].c.id==1)).mappings().one())
  result=self.restore();self.assertEqual(result['preserved_worlex_audit_rows'],1)
  self.assertEqual(result['push_subscription_ids_remapped'],0)
  self.assertEqual(self.verify_current()['status'],'RESTORE_PRESENT_MATCHES_PLAN')
  with self.engine.connect() as c:
   audit=self.tables['audit_log']
   self.assertEqual(c.scalar(select(func.count()).select_from(audit).where(audit.c.company_code=='WORLEX')),424)
   self.assertEqual(dict(c.execute(select(audit).where(audit.c.id==1)).mappings().one()),before)
   self.assertEqual(c.scalar(select(audit.c.action).where(audit.c.id==1001)),'synthetic_imported_event')
 def test_audit_ids_are_never_rewritten_to_hide_a_collision(self):
  self.preserved_audit(company='SYNTHETIC_OTHER',identifier=1001)
  with self.assertRaisesRegex(Stop,'PRIMARY_KEY_COLLISION:audit_log'):self.approve_current()
 def existing_push(self,*,endpoint='https://synthetic-current.invalid/push'):
  with self.engine.begin() as c:
   owner=c.scalar(text("SELECT account_identity FROM public.\"user\" WHERE company_code='ITC' AND username='itc'"))
   row={'id':1,'company_code':'ITC','username':'itc','owner_identity':owner,'endpoint':endpoint,'p256dh':'synthetic-existing-key','auth':'synthetic-existing-auth','created_at':'2026-11-04 00:00:00'}
   c.execute(self.tables['push_subscription'].insert(),row)
   return dict(c.execute(select(self.tables['push_subscription']).where(self.tables['push_subscription'].c.id==1)).mappings().one())
 def test_push_pk_collision_keeps_current_subscription_and_old_owner_unbound(self):
  self.preserved_audit();before=self.existing_push();self.approve_current()
  self.assertEqual(self.approved['push_subscription_id_remap'],{'1':2})
  result=self.restore();self.assertEqual(result['push_subscription_ids_remapped'],1)
  self.verify_current()
  with self.engine.connect() as c:
   table=self.tables['push_subscription']
   self.assertEqual(dict(c.execute(select(table).where(table.c.id==1)).mappings().one()),before)
   restored=c.execute(select(table).where(table.c.id==2)).mappings().one()
   self.assertEqual(restored['company_code'],'WORLEX');self.assertIsNone(restored['owner_identity'])
   self.assertEqual(restored['endpoint'],'https://synthetic-backup.invalid/push')
 def test_push_endpoint_collision_is_rejected_instead_of_rebinding(self):
  self.existing_push(endpoint='https://synthetic-backup.invalid/push')
  with self.assertRaisesRegex(Stop,'TARGET_UNIQUE_KEY_COLLISION:push_subscription'):self.approve_current()

 def test_audit_baseline_change_between_inspection_and_execution_stops(self):
  self.preserved_audit();self.approve_current()
  with self.engine.begin() as c:c.exec_driver_sql("UPDATE public.audit_log SET detail='synthetic changed' WHERE id=1")
  with self.assertRaisesRegex(Stop,'PREFLIGHT_PLAN_CHANGED'):self.restore()
  with self.engine.connect() as c:self.assertEqual(c.scalar(text("SELECT count(*) FROM public.vehicle WHERE company_code='WORLEX'")),0)
 def test_rollback_keeps_existing_audit_and_original_sequence(self):
  self.preserved_audit();self.existing_push();self.approve_current()
  with self.engine.connect() as c:before=snapshot(c,self.tables);seq=sequence_states(c,self.tables)
  with self.assertRaisesRegex(Stop,'INJECTED_ROLLBACK_PROBE'):self.restore(inject_failure='after_sequences')
  with self.engine.connect() as c:
   self.assertEqual(snapshot(c,self.tables),before);self.assertEqual(sequence_states(c,self.tables),seq)
   self.assertEqual(c.scalar(text("SELECT count(*) FROM public.audit_log WHERE company_code='WORLEX'")),1)
   self.assertEqual(c.scalar(text("SELECT count(*) FROM public.vehicle WHERE company_code='WORLEX'")),0)
 def test_unapproved_existing_audit_is_not_allowed(self):
  for identifier,created,company in [(2,'2026-11-04 07:55:08','WORLEX'),(1,'2026-11-04 07:55:09','WORLEX'),(1,'2026-11-04 07:55:08','worlex')]:
   self.preserved_audit(company=company,identifier=identifier,created=created)
   with self.subTest(identifier=identifier,created=created,company=company),self.assertRaisesRegex(Stop,'EXISTING_WORLEX_AUDIT_NOT_APPROVED'):self.approve_current()
   with self.engine.begin() as c:c.exec_driver_sql('DELETE FROM public.audit_log')
 def test_more_than_one_existing_worlex_audit_is_rejected(self):
  self.preserved_audit();self.preserved_audit(identifier=2)
  with self.assertRaisesRegex(Stop,'EXISTING_WORLEX_AUDIT_NOT_APPROVED'):self.approve_current()
 def test_verified_restore_detects_changes_to_preserved_audit(self):
  self.preserved_audit();self.approve_current();self.restore()
  with self.engine.begin() as c:c.exec_driver_sql("UPDATE public.audit_log SET detail='synthetic changed' WHERE id=1")
  with self.assertRaisesRegex(Stop,'VERIFY_PRESERVED_ROWS_CHANGED'):self.verify_current()
 def test_verified_restore_detects_additional_unplanned_audit(self):
  self.preserved_audit();self.approve_current();self.restore();self.preserved_audit(identifier=990001)
  with self.assertRaisesRegex(Stop,'VERIFY_PRESERVED_ROWS_CHANGED'):self.verify_current()

 def test_disconnect_before_commit_rolls_back_all_37_tables_and_sequences(self):
  # The connection belongs to this newly created CI-only database. Closing it
  # before COMMIT must leave no imported data or transactional sequence changes.
  from sqlalchemy.exc import OperationalError
  import psycopg2
  self.preserved_audit();self.preserved_audit(company='ITC',identifier=2);self.existing_push();self.approve_current()
  with self.engine.connect() as c:
   before=snapshot(c,self.tables);sequences=sequence_states(c,self.tables)
  guards=[0];reached=[False]
  with self.assertRaises(OperationalError):
   with self.engine.begin() as c:
    scalar=c.scalar
    def lose_connection(statement,*args,**kwargs):
     if 'pg_stat_activity' in str(statement):
      guards[0]+=1
      if guards[0]==3:
       reached[0]=True
       c.connection.driver_connection.close()
       c.invalidate()
       raise OperationalError(None,None,psycopg2.OperationalError('synthetic client connection lost before commit'),connection_invalidated=True)
     return scalar(statement,*args,**kwargs)
    with patch.object(c,'scalar',side_effect=lose_connection):
     execute_restore(c,self.data,self.columns,self.policy,self.counts,self.source_hash,self.approved)
  self.assertTrue(reached[0]);self.assertEqual(guards[0],3)
  with self.engine.begin() as c:
   c.exec_driver_sql('SET TRANSACTION READ ONLY')
   tables,_=validate_schema(c,self.policy)
   self.assertEqual(list(tables['vehicle'].c.keys()),list(self.tables['vehicle'].c.keys()))
   self.assertEqual(snapshot(c,tables),before)
   self.assertEqual(sequence_states(c,tables),sequences)
   for name,table in tables.items():
    if 'company_code' in table.c:
     expected=1 if name=='audit_log' else 0
     self.assertEqual(c.scalar(select(func.count()).select_from(table).where(table.c.company_code=='WORLEX')),expected,name)
   with self.assertRaisesRegex(Stop,'VERIFY_SOURCE_COUNT_MISMATCH'):
    verify_restore(c,self.data,self.columns,self.policy,self.counts,self.source_hash,self.approved)
  evidence=pathlib.Path(os.environ.get('WORLEX_EVIDENCE_DIR',self.temp.name));evidence.mkdir(exist_ok=True)
  (evidence/'disconnect-before-commit.json').write_text(json.dumps({'synthetic_only':True,'source_rows':4100,'populated_tables':37,'actual_connection_closed_before_commit':True,'all_imports_absent':True,'preserved_rows_match':True,'sequences_unchanged':True,'fresh_readonly_verification_rejects_absent_restore':True,'restore_retried':False},indent=2))

 def test_disconnect_after_commit_reconciles_without_reinserting(self):
  # Model a client losing the outcome AFTER a real PostgreSQL commit. This is
  # not a claim to inject or reproduce network-level packet/acknowledgement loss.
  from sqlalchemy.exc import OperationalError
  import psycopg2
  self.preserved_audit();self.preserved_audit(company='ITC',identifier=2);self.existing_push();self.approve_current()
  real_commit=self.engine.dialect.do_commit;commits=[0]
  def commit_then_lose_outcome(dbapi_connection):
   real_commit(dbapi_connection);commits[0]+=1
   getattr(dbapi_connection,'driver_connection',dbapi_connection).close()
   raise psycopg2.OperationalError('server closed the connection unexpectedly: synthetic post-commit outcome loss')
  with patch.object(self.engine.dialect,'do_commit',side_effect=commit_then_lose_outcome):
   with self.assertRaises(OperationalError):self.restore()
  self.assertEqual(commits[0],1)
  verified=self.verify_current()
  self.assertEqual(verified['source_rows'],4100)
  self.assertTrue(verified['all_source_values_and_blobs_match'])
  self.assertTrue(verified['non_worlex_and_global_rows_unchanged'])
  with self.engine.connect() as c:
   tables,_=validate_schema(c,self.policy)
   before=snapshot(c,tables);sequences=sequence_states(c,tables)
  # Negative control only inside the disposable CI DB: the guard must refuse
  # replay before any INSERT; the operational launcher never retries a write.
  with self.assertRaisesRegex(Stop,'EXISTING_WORLEX_AUDIT_NOT_APPROVED'):self.restore()
  # snapshot intentionally omits imported non-audit WORLEX rows, so repeat the
  # exact-value/row/blob reconciliation as well as checking preserved rows.
  replay_verified=self.verify_current()
  self.assertEqual(replay_verified['source_rows'],4100)
  self.assertTrue(replay_verified['all_source_values_and_blobs_match'])
  self.assertTrue(replay_verified['non_worlex_and_global_rows_unchanged'])
  with self.engine.connect() as c:
   self.assertEqual(snapshot(c,tables),before)
   self.assertEqual(sequence_states(c,tables),sequences)
  evidence=pathlib.Path(os.environ.get('WORLEX_EVIDENCE_DIR',self.temp.name));evidence.mkdir(exist_ok=True)
  (evidence/'disconnect-after-commit.json').write_text(json.dumps({'synthetic_only':True,'source_rows':4100,'populated_tables':37,'real_commit_then_client_error':True,'network_packet_loss_reproduced':False,'fresh_readonly_verification_matches':True,'preserved_rows_match':True,'replay_guard_rejected_before_insert':True,'sequences_unchanged_by_replay':True},indent=2))

 def test_real_synthetic_login_and_primary_pages(self):
  self.restore()
  sys.path.insert(0,str(APP))
  with patch.dict(os.environ,self.env,clear=True):
   from dkss_app import create_app
   from dkss_app.extensions import db
   app=create_app({'SQLALCHEMY_DATABASE_URI':self.url.render_as_string(hide_password=False),'SECRET_KEY':'synthetic-ui-only','TESTING':True,'MFA_ENABLED':False,'WTF_CSRF_ENABLED':False,'RATELIMIT_ENABLED':False},initialize_database=False)
   with app.app_context():
    with app.test_client() as client:
     response=client.post('/login',data={'company_code':'WORLEX','username':'fixture-0','password':PASSWORD},follow_redirects=False)
     self.assertIn(response.status_code,(302,303))
     with client.session_transaction() as session:
      self.assertEqual(session.get('company_code'),'WORLEX');self.assertEqual(session.get('username'),'fixture-0')
     for path in ['/','/master/vehicles','/master/drivers','/master/offices','/master/checklists','/vehicle/checklists','/vehicle/daily-inspections','/safety/checklists','/safety/driving-reports','/vehicle/karte/2']:
      response=client.get(path,follow_redirects=True)
      self.assertEqual(response.status_code,200,path);self.assertNotEqual(response.request.path,'/login',path)
     self.assertIn(client.get('/vehicle/karte/900000').status_code,(403,404))
    db.session.remove();db.engine.dispose()

if __name__=='__main__':unittest.main()
