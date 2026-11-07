"""Synthetic PG18 acceptance, restricted to the workflow-owned service container.
Never reads an archive and never accepts a production connection.
"""
import copy, hashlib, json, math, os, pathlib, re, secrets, ssl, subprocess, sys, tempfile, time, unittest, uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch
from sqlalchemy import create_engine, text, select, func, event
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from client_connection import connection_args, verify_tls_connection
from worlex_restore import Stop, validate_schema, typed_payload, snapshot, plan, execute_restore, verify_restore, digest, sequence_states
from synthetic_fixture import fixture, PASSWORD
PACKAGE=pathlib.Path(__file__).resolve().parents[1]
APP=pathlib.Path(os.environ.get('WORLEX_TEST_APP_SOURCE',PACKAGE.parent)).resolve()
MARKER='WORLEX_RESTORE_SYNTHETIC_ONLY'
# Filled only after the two real, isolated PostgreSQL catalog tests pass.
CATALOG_BATCHING_EVIDENCE={}

def validate_service_url(value,environment):
 if environment.get('GITHUB_ACTIONS')!='true' or environment.get('GITHUB_REPOSITORY')!='oxo-ops/dkss':raise Stop('DEDICATED_CI_ONLY')
 u=make_url(value)
 if (u.drivername!='postgresql+pg8000' or u.host!='127.0.0.1' or u.database!='dkss_restore_ci' or u.username!='restore_ci' or u.password!='restore-disposable-synthetic-only' or u.port is None or u.query):raise Stop('REFUSING_NONTEST_CONNECTION')
 return u

def ci_ca_file(environment):
 value=environment.get('WORLEX_TEST_CA_FILE','')
 if not value or not pathlib.Path(value).is_file():raise Stop('EXPLICIT_CI_CA_FILE_REQUIRED')
 return str(pathlib.Path(value).resolve())

def ci_app_config(value,cafile):
 # Only this harness's disposable per-test databases may initialize the app.
 u=make_url(value)
 if not re.fullmatch(r'restore_owned_[0-9a-f]{32}',u.database or ''):raise Stop('CI_OWNED_DATABASE_REQUIRED')
 validate_service_url(u.set(database='dkss_restore_ci'),os.environ)
 args=connection_args(cafile=cafile,application_name='worlex_synthetic_app')
 # App schema initialization creates unqualified tables. Keep their target
 # public; PostgreSQL still searches pg_catalog implicitly before this path.
 args['startup_params']={**args['startup_params'],'search_path':'public'}
 return {'SQLALCHEMY_DATABASE_URI':u.render_as_string(hide_password=False),
         'SQLALCHEMY_ENGINE_OPTIONS':{'poolclass':NullPool,'hide_parameters':True,
                                     'connect_args':args}}

def assert_pg8000_tls(connection):
 # pg8000 1.31.6's documented SQLAlchemy import path uses legacy.Connection;
 # Exercise the exact production post-connect gate before the CI checks/SQL.
 if any(n=='psycopg' or n.startswith('psycopg.') or n=='psycopg2' or n.startswith('psycopg2.') for n in sys.modules):raise Stop('LEGACY_POSTGRES_DRIVER_LOADED')
 try:verify_tls_connection(connection,'127.0.0.1')
 except ValueError:raise Stop('CI_PG8000_TLS_NOT_VERIFIED') from None
 raw=connection.connection.driver_connection
 sock=getattr(raw,'_usock',None)
 if (connection.dialect.driver!='pg8000' or type(raw).__module__!='pg8000.legacy'
     or not isinstance(sock,ssl.SSLSocket) or sock.context.verify_mode!=ssl.CERT_REQUIRED
     or not sock.context.check_hostname or sock.server_hostname!='127.0.0.1'
     or not sock.getpeercert() or sock.version() not in ('TLSv1.2','TLSv1.3')):
  raise Stop('CI_PG8000_TLS_NOT_VERIFIED')

# CI-only diagnostics: fixed labels and numeric facts, never exception messages,
# SQL text/parameters, environment values, stdout/stderr or absolute paths.
SCHEMA_DIAGNOSTIC_PREFIX='WORLEX_CI_SCHEMA_INIT_V1='
SCHEMA_PHASES=('bootstrap_import','imports','create_app','tls_precheck','init_db','driving_access','coupling_schema','complete')
SCHEMA_FRAME_FILES=frozenset(('__init__.py','core.py','base.py','default.py','session.py','schema.py','connection.py','socket.py','ssl.py','subprocess.py','test_restore_postgres.py','client_connection.py','legacy.py','extensions.py','driving_access.py','vehicle_couplings.py','cli.py','commands.py'))
SCHEMA_FRAME_FUNCTIONS=frozenset(('create_app','initialize_database','init_db','init_db_command','initialize_driving_access','initialize_coupling_schema','invoke','main','connect','_connect','execute','_execute','_execute_context','_exec_single_context','_handle_dbapi_exception','cursor','commit','rollback','_read','_read_int','_flush','handle_messages','handle_ERROR_RESPONSE','recv','recv_into','read','do_handshake','wrap_socket','assert_pg8000_tls','verify_tls_connection','run_ci_schema_initialization','emit','other'))
SCHEMA_ERROR_TYPES=frozenset(('OtherException','Exception','SystemExit','AssertionError','ImportError','ModuleNotFoundError','FileNotFoundError','PermissionError','UnicodeEncodeError','UnicodeDecodeError','TimeoutError','OSError','MemoryError','RuntimeError','ValueError','TypeError','KeyError','NotImplementedError','OperationalError','InterfaceError','ProgrammingError','IntegrityError','InternalError','DatabaseError','DataError','InvalidRequestError','StatementError','DisconnectionError','PendingRollbackError','SSLError','SSLCertVerificationError','ConnectionResetError','ConnectionAbortedError','BrokenPipeError','Stop'))

def schema_exception_chain(error):
 from client_connection import sqlstate
 result=[];seen=set()
 while error is not None and id(error) not in seen and len(result)<6:
  seen.add(id(error));name=type(error).__name__;frames=[];tb=error.__traceback__
  while tb is not None:
   code=tb.tb_frame.f_code;filename=code.co_filename.replace('\\','/').rsplit('/',1)[-1]
   filename=filename if filename in SCHEMA_FRAME_FILES else 'other'
   function=code.co_name if code.co_name in SCHEMA_FRAME_FUNCTIONS else 'other'
   frames.append({'file':filename,'function':function,'line':tb.tb_lineno});tb=tb.tb_next
  item={'type':name if name in SCHEMA_ERROR_TYPES else 'OtherException','sqlstate':sqlstate(error),'frames':frames[-8:]}
  for key in ('errno','winerror'):
   value=getattr(error,key,None);item[key]=value if type(value) is int and -(2**31)<=value<2**32 else None
  result.append(item)
  original=getattr(error,'orig',None)
  error=original if isinstance(original,BaseException) and original is not error else error.__cause__ or error.__context__
 return result

def run_ci_schema_initialization():
 start=time.monotonic();cpu_start=time.process_time();phase='imports'
 def emit(status,error=None):
  value={'version':1,'phase':phase,'status':status,'elapsed_seconds':round(time.monotonic()-start,6),'cpu_seconds':round(time.process_time()-cpu_start,6),'exception_chain':schema_exception_chain(error) if error is not None else []}
  print(SCHEMA_DIAGNOSTIC_PREFIX+json.dumps(value,sort_keys=True,allow_nan=False),flush=True)
 try:
  emit('started')
  from dkss_app import create_app
  from dkss_app.extensions import db
  from dkss_app.driving_access import initialize_driving_access
  from dkss_app.vehicle_couplings import initialize_coupling_schema
  phase='create_app';emit('started')
  app=create_app(ci_app_config(os.environ['DATABASE_URL'],os.environ['WORLEX_TEST_CA_FILE']),initialize_database=False)
  with app.app_context():
   phase='tls_precheck';emit('started')
   with db.engine.connect() as connection:assert_pg8000_tls(connection)
   phase='init_db';emit('started')
   result=app.test_cli_runner().invoke(args=['init-db'])
   if result.exit_code:raise RuntimeError('SYNTHETIC_INIT_FAILED') from result.exception
   phase='driving_access';emit('started');initialize_driving_access(app)
   phase='coupling_schema';emit('started');initialize_coupling_schema(app)
  phase='complete';emit('passed')
 except BaseException as error:
  emit('failed',error)
  raise SystemExit(1) from None

def parse_schema_diagnostic(output):
 if isinstance(output,bytes):output=output.decode('utf-8',errors='replace')
 if not isinstance(output,str):return None
 def unique(pairs):
  result={}
  for key,value in pairs:
   if key in result:raise ValueError('DUPLICATE_DIAGNOSTIC_KEY')
   result[key]=value
  return result
 def invalid_constant(_):raise ValueError('NONFINITE_DIAGNOSTIC_VALUE')
 for line in reversed(output[-65536:].splitlines()):
  if not line.startswith(SCHEMA_DIAGNOSTIC_PREFIX) or len(line)>16384:continue
  try:
   value=json.loads(line[len(SCHEMA_DIAGNOSTIC_PREFIX):],object_pairs_hook=unique,parse_constant=invalid_constant)
   if not isinstance(value,dict) or set(value)!={'version','phase','status','elapsed_seconds','cpu_seconds','exception_chain'}:continue
   if type(value['version']) is not int or value['version']!=1 or value['phase'] not in SCHEMA_PHASES or value['status'] not in ('started','failed','passed'):continue
   if any(type(value[k]) not in (int,float) or not math.isfinite(value[k]) or not 0<=value[k]<=600 for k in ('elapsed_seconds','cpu_seconds')):continue
   chain=value['exception_chain']
   if not isinstance(chain,list) or len(chain)>6 or (value['status']=='failed' and not chain):continue
   valid=True
   for item in chain:
    if not isinstance(item,dict) or set(item)!={'type','sqlstate','errno','winerror','frames'} or item['type'] not in SCHEMA_ERROR_TYPES:valid=False;break
    if item['sqlstate'] is not None and (not isinstance(item['sqlstate'],str) or not re.fullmatch('[0-9A-Z]{5}',item['sqlstate'])):valid=False;break
    if any(item[k] is not None and (type(item[k]) is not int or not -(2**31)<=item[k]<2**32) for k in ('errno','winerror')):valid=False;break
    frames=item['frames']
    if not isinstance(frames,list) or len(frames)>8:valid=False;break
    for frame in frames:
     if not isinstance(frame,dict) or set(frame)!={'file','function','line'}:valid=False;break
     if (frame['file'] not in SCHEMA_FRAME_FILES|{'other'} or frame['function'] not in SCHEMA_FRAME_FUNCTIONS or type(frame['line']) is not int or not 1<=frame['line']<=1000000):valid=False;break
   if valid:return value
  except (TypeError,ValueError,KeyError,AttributeError):continue
 return None

def schema_failure_evidence(result,elapsed,error=None):
 output=getattr(result,'stdout',None) if result is not None else getattr(error,'stdout',None)
 status='timed_out' if isinstance(error,subprocess.TimeoutExpired) else 'output_decode_failed' if isinstance(error,UnicodeError) else 'launch_failed' if error is not None else 'child_failed'
 code=getattr(result,'returncode',None)
 return {'synthetic_only':True,'status':status,'returncode':code if type(code) is int else None,'elapsed_seconds':round(elapsed,6),'child':parse_schema_diagnostic(output),'launch_exception_chain':schema_exception_chain(error) if error is not None else [],'raw_output_included':False,'retried':False}

def report_schema_failure(value,test_name):
 if not re.fullmatch('test_[a-z0-9_]{1,120}',test_name):raise Stop('INVALID_SYNTHETIC_TEST_NAME')
 report=dict(value,evidence_saved=False)
 destination=os.environ.get('WORLEX_EVIDENCE_DIR')
 if destination:
  path=pathlib.Path(destination)/('schema-init-failure-'+test_name+'.json')
  saved=dict(value,evidence_saved=True)
  try:
   with path.open('x',encoding='utf-8') as handle:json.dump(saved,handle,indent=2,sort_keys=True,allow_nan=False)
  except OSError:pass  # Preserve the original safe failure; never expose write errors.
  else:report=saved
 return 'Synthetic schema initialization failed: '+json.dumps(report,sort_keys=True,allow_nan=False)


class ServiceGuardTests(unittest.TestCase):
 def test_dedicated_service_and_rejections(self):
  env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'oxo-ops/dkss'}
  value='postgresql+pg8000://restore_ci:restore-disposable-synthetic-only@127.0.0.1:5432/dkss_restore_ci'
  self.assertEqual(validate_service_url(value,env).database,'dkss_restore_ci')
  for invalid in [value.replace('127.0.0.1','external.invalid'),value.replace('dkss_restore_ci','production'),value+'?host=other',value.replace('restore_ci:','real_user:'),value.replace('+pg8000','+psycopg2')]:
   with self.assertRaises(Stop):validate_service_url(invalid,env)
  with self.assertRaises(Stop):validate_service_url(value,{})
 def test_missing_explicit_ca_fails_closed(self):
  with self.assertRaisesRegex(Stop,'EXPLICIT_CI_CA_FILE_REQUIRED'):ci_ca_file({})
  with self.assertRaisesRegex(Stop,'EXPLICIT_CI_CA_FILE_REQUIRED'):ci_ca_file({'WORLEX_TEST_CA_FILE':str(PACKAGE/'nonexistent-ca.pem')})
 def test_app_config_uses_explicit_context_without_libpq_environment(self):
  env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'oxo-ops/dkss','PGSSLMODE':'disable','PGSSLROOTCERT':'not-used'}
  value='postgresql+pg8000://restore_ci:restore-disposable-synthetic-only@127.0.0.1:5432/restore_owned_'+('a'*32)
  context=object();args={'ssl_context':context,'timeout':130,'startup_params':{'search_path':'pg_catalog,public','statement_timeout':'120000'}}
  with patch.dict(os.environ,env,clear=True),patch(__name__+'.connection_args',return_value=args) as factory:
   config=ci_app_config(value,'explicit-ci-ca.pem')
  factory.assert_called_once_with(cafile='explicit-ci-ca.pem',application_name='worlex_synthetic_app')
  self.assertEqual(config['SQLALCHEMY_DATABASE_URI'],value)
  options=config['SQLALCHEMY_ENGINE_OPTIONS']
  self.assertIs(options['poolclass'],NullPool);self.assertTrue(options['hide_parameters'])
  self.assertIs(options['connect_args']['ssl_context'],context)
  self.assertEqual(options['connect_args']['startup_params'],{'search_path':'public','statement_timeout':'120000'})
 def test_app_config_rejects_non_ci_destinations_before_context_creation(self):
  env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'oxo-ops/dkss'}
  value='postgresql+pg8000://restore_ci:restore-disposable-synthetic-only@127.0.0.1:5432/restore_owned_'+('a'*32)
  with patch.dict(os.environ,env,clear=True),patch(__name__+'.connection_args') as factory:
   for invalid in [value.replace('127.0.0.1','external.invalid'),value+'?host=other',value.replace('restore_owned_'+('a'*32),'production'),value.replace('+pg8000','+psycopg2')]:
    with self.subTest(value=invalid),self.assertRaises(Stop):ci_app_config(invalid,'explicit-ci-ca.pem')
   factory.assert_not_called()
 def test_tls_check_requires_verified_pg8000_socket(self):
  def connection():
   sock=Mock(spec=ssl.SSLSocket)
   sock.context=SimpleNamespace(verify_mode=ssl.CERT_REQUIRED,check_hostname=True)
   sock.server_hostname='127.0.0.1';sock.getpeercert.return_value={'subjectAltName':(('IP Address','127.0.0.1'),)};sock.version.return_value='TLSv1.3'
   raw=type('Connection',(),{'__module__':'pg8000.legacy'})();raw._usock=sock
   return SimpleNamespace(dialect=SimpleNamespace(driver='pg8000'),connection=SimpleNamespace(driver_connection=raw))
  valid=connection()
  with patch(__name__+'.verify_tls_connection',wraps=verify_tls_connection) as production_gate:
   assert_pg8000_tls(valid)
   production_gate.assert_called_once_with(valid,'127.0.0.1')
  with patch(__name__+'.verify_tls_connection',side_effect=ValueError('CLIENT_ACTUAL_TLS_NOT_VERIFIED')),self.assertRaisesRegex(Stop,'CI_PG8000_TLS_NOT_VERIFIED'):
   assert_pg8000_tls(connection())
  for change in ('non_tls','wrong_driver','no_ca_check','no_hostname_check','wrong_hostname','no_certificate','old_tls'):
   c=connection();sock=c.connection.driver_connection._usock
   if change=='non_tls':c.connection.driver_connection._usock=object()
   elif change=='wrong_driver':c.dialect.driver='other'
   elif change=='no_ca_check':sock.context.verify_mode=ssl.CERT_NONE
   elif change=='no_hostname_check':sock.context.check_hostname=False
   elif change=='wrong_hostname':sock.server_hostname='external.invalid'
   elif change=='no_certificate':sock.getpeercert.return_value={}
   else:sock.version.return_value='TLSv1.1'
   with self.subTest(change=change),self.assertRaisesRegex(Stop,'CI_PG8000_TLS_NOT_VERIFIED'):assert_pg8000_tls(c)
  with patch.dict(sys.modules,{'psycopg2':object()}),self.assertRaisesRegex(Stop,'LEGACY_POSTGRES_DRIVER_LOADED'):assert_pg8000_tls(connection())

class PostgreSQLRestoreAcceptance(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if os.environ.get('WORLEX_REQUIRE_POSTGRES')!='1':raise unittest.SkipTest('Explicit isolated PostgreSQL service required; no local/live fallback')
  cls.service=validate_service_url(os.environ.get('WORLEX_TEST_POSTGRES_URL',''),os.environ)
  cls.cafile=ci_ca_file(os.environ)
  manifest=json.loads((PACKAGE/'source-manifest.json').read_text())
  if not all((APP/n).is_file() and hashlib.sha256((APP/n).read_bytes()).hexdigest()==v for n,v in manifest['files'].items()):raise Stop('PINNED_APPLICATION_SOURCE_MISMATCH')
  cls.admin=create_engine(cls.service,poolclass=NullPool,isolation_level='AUTOCOMMIT',hide_parameters=True,connect_args=connection_args(cafile=cls.cafile,application_name='worlex_synthetic_admin'))
  cls.addClassCleanup(cls.admin.dispose)
  with cls.admin.connect() as c:
   assert_pg8000_tls(c)
   if c.scalar(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"))!=MARKER:raise Stop('UNMARKED_CI_DATABASE')
   if c.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'"))!=0:raise Stop('CI_MARKER_DATABASE_MUST_REMAIN_EMPTY')
   version=c.scalar(text('SHOW server_version_num'))
   if not 180000<=int(version)<190000:raise Stop('POSTGRES_18_REQUIRED')
  cls.base_policy=json.loads((PACKAGE/'policy.json').read_text());cls.seal_written=False
 def setUp(self):
  self.name='restore_owned_'+uuid.uuid4().hex
  with self.admin.connect() as c:c.exec_driver_sql('CREATE DATABASE "'+self.name+'" TEMPLATE template0')
  self.url=self.service.set(database=self.name)
  self.engine=create_engine(self.url,poolclass=NullPool,hide_parameters=True,connect_args=connection_args(cafile=self.cafile,application_name='worlex_synthetic_restore'))
  self.addCleanup(self.engine.dispose)
  with self.engine.begin() as c:
   assert_pg8000_tls(c)
   self.assertEqual(c.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")),0)
   c.exec_driver_sql("COMMENT ON DATABASE \""+self.name+"\" IS 'WORLEX_RESTORE_SYNTHETIC_ONLY'")
  self.temp=tempfile.TemporaryDirectory(prefix='worlex-synthetic-');self.addCleanup(self.temp.cleanup)
  env={'PATH':os.defpath,'HOME':self.temp.name,'LANG':'C.UTF-8','TZ':'UTC','PYTHONPATH':os.pathsep.join(map(str,(PACKAGE/'tests',PACKAGE,APP))),'PYTHONDONTWRITEBYTECODE':'1','FLASK_SKIP_DOTENV':'1','DATABASE_URL':self.url.render_as_string(hide_password=False),'SECRET_KEY':secrets.token_urlsafe(40),'ITC_INITIAL_PASSWORD':'Synthetic-ITC-Only!','RENDER':'','AWS_EC2_METADATA_DISABLED':'true','AWS_CONFIG_FILE':os.devnull,'AWS_SHARED_CREDENTIALS_FILE':os.devnull,'S3_BUCKET_NAME':'','OPENAI_API_KEY':'','SMTP_HOST':'','VAPID_PRIVATE_KEY':'','VAPID_PUBLIC_KEY':'','DOCUMENT_IMPORT_WORKER_ENABLED':'0','ANALYSIS_READ_CACHE_ENABLED':'0','RATELIMIT_STORAGE_URI':'memory://','WORLEX_TEST_CA_FILE':self.cafile,'WORLEX_TEST_APP_SOURCE':str(APP),'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'oxo-ops/dkss'}
  # Inherit only Windows loader requirements. The CA is explicit and checked;
  # libpq PGSSL environment variables have no authority in this candidate.
  for key in ('SYSTEMROOT','WINDIR','TEMP','TMP'):
   if key in os.environ:env[key]=os.environ[key]
  if os.name=='nt':
   env['PATH']=str(pathlib.Path(sys.executable).parent)+os.pathsep+str(pathlib.Path(env['SYSTEMROOT'])/'System32')
  self.env=env
  bootstrap_event={'version':1,'phase':'bootstrap_import','status':'started','elapsed_seconds':0,'cpu_seconds':0,'exception_chain':[]}
  setup=("import json\nprint("+repr(SCHEMA_DIAGNOSTIC_PREFIX)+"+json.dumps("+repr(bootstrap_event)+"),flush=True)\nfrom test_restore_postgres import run_ci_schema_initialization; run_ci_schema_initialization()")
  started=time.monotonic()
  try:
   result=subprocess.run([sys.executable,'-c',setup],cwd=APP,env=env,capture_output=True,text=True,timeout=180)
  except (OSError,subprocess.TimeoutExpired,UnicodeError) as error:
   evidence=schema_failure_evidence(None,time.monotonic()-started,error)
   self.fail(report_schema_failure(evidence,self._testMethodName))
  if result.returncode:
   evidence=schema_failure_evidence(result,time.monotonic()-started)
   self.fail(report_schema_failure(evidence,self._testMethodName))
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
 def test_catalog_maps_match_original_full_fixture(self):
  from sqlalchemy import inspect
  from sqlalchemy.engine.reflection import ObjectKind, ObjectScope
  from worlex_restore import defer_push_subscription, DEFERRED_SOURCE_ROWS
  typed,_=typed_payload(self.data,self.columns,self.tables,self.counts,self.approved['generated_identifiers'])
  defer_push_subscription(typed,DEFERRED_SOURCE_ROWS)
  names=[name for name,rows in typed.items() if rows]
  self.assertEqual(sum(self.counts.values()),4100)
  self.assertEqual(sum(map(len,typed.values())),4099)
  self.assertEqual(len(names),36)
  with self.engine.begin() as c:
   c.exec_driver_sql('SET TRANSACTION READ ONLY')
   single,bulk=inspect(c),inspect(c)
   uniques=bulk.get_multi_unique_constraints(schema='public',filter_names=names,kind=ObjectKind.ANY,scope=ObjectScope.ANY)
   indexes=bulk.get_multi_indexes(schema='public',filter_names=names,kind=ObjectKind.ANY,scope=ObjectScope.ANY)
   expected={('public',name) for name in names}
   self.assertEqual(set(uniques),expected);self.assertEqual(set(indexes),expected)
   for name in names:
    with self.subTest(table=name):
     original_unique=single.get_unique_constraints(name,schema='public')
     original_indexes=single.get_indexes(name,schema='public')
     self.assertEqual(original_unique,uniques[('public',name)])
     self.assertEqual(original_indexes,indexes[('public',name)])
     self.assertEqual(original_unique+[i for i in original_indexes if i.get('unique')],
                      uniques[('public',name)]+[i for i in indexes[('public',name)] if i.get('unique')])
  self.unchanged()
  CATALOG_BATCHING_EVIDENCE['maps']={'populated_import_tables':len(names),'exact_public_keys':True,
    'unique_maps_equal':True,'index_maps_equal':True,'ordered_combination_equal':True,'preserved_state_unchanged':True}
 def test_catalog_preflight_reduces_real_full_fixture_queries(self):
  import catalog_baseline
  from worlex_restore import check_empty_and_itc, defer_push_subscription, DEFERRED_SOURCE_ROWS
  typed,_=typed_payload(self.data,self.columns,self.tables,self.counts,self.approved['generated_identifiers'])
  defer_push_subscription(typed,DEFERRED_SOURCE_ROWS)
  self.assertEqual(sum(self.counts.values()),4100)
  self.assertEqual(sum(map(len,typed.values())),4099)
  self.assertEqual(sum(bool(rows) for rows in typed.values()),36)
  captured=[]
  def record(connection,cursor,statement,parameters,context,executemany):
   # Kept in memory only for equality. Evidence contains counts, never SQL/binds.
   captured.append(('catalog' if 'pg_catalog.' in statement else 'application',statement,copy.deepcopy(parameters),executemany))
  traces=[]
  with self.engine.begin() as c:
   c.exec_driver_sql('SET TRANSACTION READ ONLY')
   for preflight in (catalog_baseline.check_empty_and_itc,check_empty_and_itc):
    captured.clear();event.listen(c,'before_cursor_execute',record)
    try:preflight(c,self.tables,typed)
    finally:event.remove(c,'before_cursor_execute',record)
    traces.append(list(captured))
  old_catalog=[row for row in traces[0] if row[0]=='catalog']
  new_catalog=[row for row in traces[1] if row[0]=='catalog']
  old_application=[row for row in traces[0] if row[0]=='application']
  new_application=[row for row in traces[1] if row[0]=='application']
  self.assertEqual(len(old_catalog),108);self.assertEqual(len(new_catalog),3)
  self.assertTrue(old_application);self.assertEqual(old_application,new_application)
  self.unchanged()
  CATALOG_BATCHING_EVIDENCE['preflight']={'source_rows':4100,'import_rows':4099,'populated_import_tables':36,
    'old_catalog_execute_calls':len(old_catalog),'new_catalog_execute_calls':len(new_catalog),
    'old_application_execute_calls':len(old_application),'new_application_execute_calls':len(new_application),
    'application_queries_and_binds_equal':True,'preserved_state_unchanged':True,
    'synthetic_only':True,'network_disconnect_fix_proven':False}
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
  self.assertEqual(self.approved['deferred_source_rows'],{'push_subscription':[1]})
  with self.engine.connect() as c:before=dict(c.execute(select(self.tables['audit_log']).where(self.tables['audit_log'].c.id==1)).mappings().one())
  result=self.restore();self.assertEqual(result['preserved_worlex_audit_rows'],1)
  self.assertTrue(result['push_subscription_rows_unchanged'])
  self.assertEqual(self.verify_current()['status'],'RESTORE_PRESENT_MATCHES_PLAN')
  with self.engine.connect() as c:
   audit=self.tables['audit_log']
   self.assertEqual(c.scalar(select(func.count()).select_from(audit).where(audit.c.company_code=='WORLEX')),424)
   self.assertEqual(dict(c.execute(select(audit).where(audit.c.id==1)).mappings().one()),before)
   self.assertEqual(c.scalar(select(audit.c.action).where(audit.c.id==1001)),'synthetic_imported_event')
 def test_audit_ids_are_never_rewritten_to_hide_a_collision(self):
  self.preserved_audit(company='SYNTHETIC_OTHER',identifier=1001)
  with self.assertRaisesRegex(Stop,'PRIMARY_KEY_COLLISION:audit_log'):self.approve_current()
 def existing_push(self,*,endpoint='https://synthetic-backup.invalid/push'):
  with self.engine.begin() as c:
   owner=c.scalar(text("SELECT account_identity FROM public.\"user\" WHERE company_code='ITC' AND username='itc'"))
   row={'id':1,'company_code':'ITC','username':'itc','owner_identity':owner,'endpoint':endpoint,'p256dh':'synthetic-existing-key','auth':'synthetic-existing-auth','created_at':'2026-11-04 00:00:00'}
   c.execute(self.tables['push_subscription'].insert(),row)
   return dict(c.execute(select(self.tables['push_subscription']).where(self.tables['push_subscription'].c.id==1)).mappings().one())
 def test_push_endpoint_and_id_collision_defers_source_and_preserves_all_values(self):
  self.preserved_audit();before=self.existing_push();self.approve_current()
  source=copy.deepcopy(self.data)
  self.assertEqual(self.approved['deferred_source_rows'],{'push_subscription':[1]})
  self.assertNotIn('push_subscription_id_remap',self.approved)
  self.assertEqual(self.approved['version'],3)
  self.assertEqual(self.approved['import_counts'],dict(self.counts,push_subscription=0))
  with self.engine.connect() as c:sequence_before=sequence_states(c,self.tables)[('push_subscription','id')]
  self.assertEqual(set(sequence_before),{'qualified','last','called','next','max','log_cnt','catalog'})
  self.assertEqual(set(sequence_before['catalog']),{'schema','name','oid','owner','acl','type_oid','start','increment','min','max','cache','cycle','ownership','persistence','options','tablespace','filenode'})
  self.assertEqual(sequence_before['next'],sequence_before['last']+1 if sequence_before['called'] else sequence_before['last'])
  statements=[]
  def record_sql(connection,cursor,statement,parameters,context,executemany):statements.append(statement)
  event.listen(self.engine,'before_cursor_execute',record_sql)
  try:
   result=self.restore();verified=self.verify_current()
  finally:event.remove(self.engine,'before_cursor_execute',record_sql)
  forbidden=re.compile(r'\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|ALTER\s+SEQUENCE)\s+(?:"?public"?\.)?"?push_subscription(?:_id_seq)?"?\b|\b(?:nextval|setval)\s*\([^)]*push_subscription',re.IGNORECASE)
  self.assertFalse([statement for statement in statements if forbidden.search(statement)])
  for report in (result,verified):
   for key,value in {'source_rows':4100,'source_tables':37,'imported_rows':4099,'imported_tables':36,'deferred_rows':1,'deferred_source_rows':{'push_subscription':[1]}}.items():self.assertEqual(report[key],value)
   self.assertTrue(report['imported_values_and_blobs_match'])
   self.assertTrue(report['push_subscription_rows_unchanged']);self.assertTrue(report['push_subscription_sequence_unchanged'])
   self.assertNotIn('push_subscription_ids_remapped',report)
   self.assertNotIn('all_source_values_and_blobs_match',report)
  self.assertEqual(self.data,source);self.assertEqual(sum(map(len,self.data.values())),4100)
  with self.engine.connect() as c:
   table=self.tables['push_subscription']
   self.assertEqual([dict(row) for row in c.execute(select(table)).mappings()], [before])
   self.assertEqual(sequence_states(c,self.tables)[('push_subscription','id')],sequence_before)
 def test_raw_deferred_source_mutation_is_rejected_with_unchanged_source_hash(self):
  self.existing_push();self.approve_current()
  original=copy.deepcopy(self.data['push_subscription'])
  self.data['push_subscription'][0]['endpoint']='https://synthetic-mutated.invalid/push'
  with self.assertRaises(Stop):self.restore()
  self.data['push_subscription']=original
  self.restore()
  self.data['push_subscription'][0]['auth']='synthetic-mutated'
  with self.assertRaises(Stop):self.verify_current()

 def test_push_without_collision_is_still_deferred_without_owner_rebinding(self):
  before=self.existing_push(endpoint='https://synthetic-current.invalid/push');self.approve_current();self.restore()
  self.assertTrue(self.verify_current()['push_subscription_rows_unchanged'])
  with self.engine.connect() as c:self.assertEqual([dict(row) for row in c.execute(select(self.tables['push_subscription'])).mappings()],[before])
 def test_verified_restore_detects_preserved_push_value_mutation(self):
  self.existing_push();self.approve_current();self.restore()
  with self.engine.begin() as c:c.exec_driver_sql("UPDATE public.push_subscription SET auth='synthetic-mutated' WHERE id=1")
  with self.assertRaises(Stop):self.verify_current()
 def test_verified_restore_detects_push_sequence_last_value_mutation(self):
  self.existing_push();self.approve_current();self.restore()
  with self.engine.begin() as c:c.exec_driver_sql("SELECT setval('public.push_subscription_id_seq', 99, false)")
  with self.assertRaises(Stop):self.verify_current()
 def test_verified_restore_detects_push_sequence_called_mutation(self):
  self.existing_push();self.approve_current();self.restore()
  with self.engine.begin() as c:
   last,called=c.exec_driver_sql('SELECT last_value,is_called FROM public.push_subscription_id_seq').one()
   c.execute(text("SELECT setval('public.push_subscription_id_seq', :last, :called)"),{'last':last,'called':not called})
  with self.assertRaises(Stop):self.verify_current()
 def test_verified_restore_detects_push_sequence_catalog_mutation(self):
  self.existing_push();self.approve_current();self.restore()
  with self.engine.begin() as c:c.exec_driver_sql('ALTER SEQUENCE public.push_subscription_id_seq START WITH 17')
  with self.assertRaises(Stop):self.verify_current()

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

 def test_disconnect_before_commit_rolls_back_all_imported_tables_and_sequences(self):
  # The connection belongs to this newly created CI-only database. Closing it
  # before COMMIT must leave no imported data or transactional sequence changes.
  from sqlalchemy.exc import InterfaceError
  import pg8000
  self.preserved_audit();self.preserved_audit(company='ITC',identifier=2);self.existing_push();self.approve_current()
  with self.engine.connect() as c:
   before=snapshot(c,self.tables);sequences=sequence_states(c,self.tables)
  source_before=copy.deepcopy(self.data)
  guards=[0];reached=[False]
  with self.assertRaises(InterfaceError):
   with self.engine.begin() as c:
    scalar=c.scalar
    def lose_connection(statement,*args,**kwargs):
     if 'pg_stat_activity' in str(statement):
      guards[0]+=1
      if guards[0]==3:
       reached[0]=True
       c.connection.driver_connection.close()
       c.invalidate()
       raise InterfaceError(None,None,pg8000.InterfaceError('network error: synthetic client connection lost before commit'),connection_invalidated=True)
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
  (evidence/'disconnect-before-commit.json').write_text(json.dumps({'synthetic_only':True,'source_rows':4100,'source_tables':37,'populated_tables':37,'populated_tables_meaning':'source','source_counts':self.counts,'imported_rows':4099,'imported_tables':36,'deferred_rows':1,'deferred_source_rows':{'push_subscription':[1]},'import_counts':dict(self.counts,push_subscription=0),'deferred_source_fixture_retained':self.data==source_before,'push_subscription_rows_unchanged':True,'push_subscription_sequence_unchanged':True,'imported_values_and_blobs_match':False,'actual_connection_closed_before_commit':True,'all_imports_absent':True,'preserved_rows_match':True,'sequences_unchanged':True,'fresh_readonly_verification_rejects_absent_restore':True,'restore_retried':False},indent=2))

 def test_disconnect_after_commit_reconciles_without_reinserting(self):
  # Model a client losing the outcome AFTER a real PostgreSQL commit. This is
  # not a claim to inject or reproduce network-level packet/acknowledgement loss.
  from sqlalchemy.exc import InterfaceError
  import pg8000
  self.preserved_audit();self.preserved_audit(company='ITC',identifier=2);self.existing_push();self.approve_current()
  source_before=copy.deepcopy(self.data)
  real_commit=self.engine.dialect.do_commit;commits=[0]
  def commit_then_lose_outcome(dbapi_connection):
   real_commit(dbapi_connection);commits[0]+=1
   getattr(dbapi_connection,'driver_connection',dbapi_connection).close()
   raise pg8000.InterfaceError('network error: synthetic post-commit outcome loss')
  with patch.object(self.engine.dialect,'do_commit',side_effect=commit_then_lose_outcome):
   with self.assertRaises(InterfaceError):self.restore()
  self.assertEqual(commits[0],1)
  verified=self.verify_current()
  self.assertEqual(verified['source_rows'],4100)
  self.assertTrue(verified['imported_values_and_blobs_match'])
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
  self.assertTrue(replay_verified['imported_values_and_blobs_match'])
  self.assertTrue(replay_verified['non_worlex_and_global_rows_unchanged'])
  with self.engine.connect() as c:
   self.assertEqual(snapshot(c,tables),before)
   self.assertEqual(sequence_states(c,tables),sequences)
  evidence=pathlib.Path(os.environ.get('WORLEX_EVIDENCE_DIR',self.temp.name));evidence.mkdir(exist_ok=True)
  (evidence/'disconnect-after-commit.json').write_text(json.dumps({'synthetic_only':True,'source_rows':4100,'source_tables':37,'populated_tables':37,'populated_tables_meaning':'source','source_counts':self.counts,'imported_rows':4099,'imported_tables':36,'deferred_rows':1,'deferred_source_rows':{'push_subscription':[1]},'import_counts':dict(self.counts,push_subscription=0),'deferred_source_fixture_retained':self.data==source_before,'push_subscription_rows_unchanged':True,'push_subscription_sequence_unchanged':True,'imported_values_and_blobs_match':verified['imported_values_and_blobs_match'],'real_commit_then_client_error':True,'network_packet_loss_reproduced':False,'fresh_readonly_verification_matches':True,'preserved_rows_match':True,'replay_guard_rejected_before_insert':True,'sequences_unchanged_by_replay':True},indent=2))

 def test_real_synthetic_login_and_primary_pages(self):
  self.restore()
  sys.path.insert(0,str(APP))
  with patch.dict(os.environ,self.env,clear=True):
   from dkss_app import create_app
   from dkss_app.extensions import db
   app=create_app({**ci_app_config(self.url,self.cafile),'SECRET_KEY':'synthetic-ui-only','TESTING':True,'MFA_ENABLED':False,'WTF_CSRF_ENABLED':False,'RATELIMIT_ENABLED':False},initialize_database=False)
   with app.app_context():
    with db.engine.connect() as connection:assert_pg8000_tls(connection)
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
