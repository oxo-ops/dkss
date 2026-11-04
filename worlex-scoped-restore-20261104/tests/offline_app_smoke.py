"""Synthetic SQLite app rehearsal. Not PostgreSQL acceptance or live login."""
import os,sys,json,pathlib
root=pathlib.Path(__file__).resolve().parents[1];src=pathlib.Path(sys.argv[1]).resolve()
for key in list(os.environ):
 if key.startswith(('PG','AWS_')) or key in {'DATABASE_URL','RENDER','SECRET_KEY','S3_BUCKET_NAME','ITC_INITIAL_PASSWORD'}:os.environ.pop(key,None)
os.environ.update(ANALYSIS_READ_CACHE_ENABLED='0',AWS_EC2_METADATA_DISABLED='true',S3_BUCKET_NAME='',OPENAI_API_KEY='',SMTP_HOST='',VAPID_PRIVATE_KEY='',DOCUMENT_IMPORT_WORKER_ENABLED='0',ITC_INITIAL_PASSWORD='Synthetic-ITC-Only!')
sys.path.insert(0,str(root));sys.path.insert(0,str(src))
from dkss_app import create_app
from dkss_app.extensions import db
from dkss_app.driving_access import initialize_driving_access
from dkss_app.vehicle_couplings import initialize_coupling_schema
from sqlalchemy import MetaData,Column,String
from worlex_restore import typed_payload
from synthetic_fixture import fixture,PASSWORD
policy=json.loads((root/'policy.json').read_text());names=json.loads((root/'source-counts.json').read_text())
app=create_app({'SQLALCHEMY_DATABASE_URI':'sqlite:///:memory:','SECRET_KEY':'synthetic-ui-only','TESTING':True,'MFA_ENABLED':False,'WTF_CSRF_ENABLED':False,'RATELIMIT_ENABLED':False},initialize_database=False)
with app.app_context():
 r=app.test_cli_runner().invoke(args=['init-db'])
 if r.exit_code:raise RuntimeError('SYNTHETIC_INIT_FAILED') from r.exception
 initialize_driving_access(app);initialize_coupling_schema(app)
 with db.engine.begin() as c:c.exec_driver_sql('ALTER TABLE vehicle ADD COLUMN vehicle_id VARCHAR(50)')
 md=MetaData();md.reflect(db.engine)
 data,cols,counts=fixture(policy,names);typed,order=typed_payload(data,cols,md.tables,counts)
 with db.engine.begin() as c:
  for n in order:c.execute(md.tables[n].insert(),typed[n])
 result={'scope':'SYNTHETIC_SQLITE_ONLY','source_rows':sum(counts.values()),'pages':{}}
 with app.test_client() as client:
  r=client.post('/login',data={'company_code':'WORLEX','username':'fixture-0','password':PASSWORD},follow_redirects=False)
  if r.status_code not in (302,303):raise RuntimeError('SYNTHETIC_LOGIN_FAILED')
  with client.session_transaction() as session:
   if session.get('username')!='fixture-0' or session.get('company_code')!='WORLEX':raise RuntimeError('SYNTHETIC_SESSION_FAILED')
  for path in ['/','/master/vehicles','/master/drivers','/master/offices','/master/checklists','/vehicle/checklists','/vehicle/daily-inspections','/safety/checklists','/safety/driving-reports','/vehicle/karte/2']:
   r=client.get(path,follow_redirects=True)
   result['pages'][path]={'status':r.status_code,'reached_login':r.request.path=='/login'}
   if r.status_code!=200 or r.request.path=='/login':raise RuntimeError('SYNTHETIC_PAGE_FAILED:'+path)
 result['synthetic_password_login_passed']=True
 print(json.dumps(result,indent=2))
