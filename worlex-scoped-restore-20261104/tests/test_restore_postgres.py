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
  self.env=env
  setup="""from dkss_app import create_app
from dkss_app.driving_access import initialize_driving_access
from dkss_app.vehicle_couplings import initialize_coupling_schema
app=create_app(initialize_database=False)
with app.app_context():
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
  candidate=copy.deepcopy(self.policy);candidate.pop('postgres_acceptance_passed',None)
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
  del self.policy['postgres_structure_sha256']
  with self.assertRaisesRegex(Stop,'POSTGRES_CI_SEAL_REQUIRED'):self.restore()
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
