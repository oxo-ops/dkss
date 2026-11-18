"""Registered product routes on an owned private schema. No missing-PG skip."""
import os,re,time,uuid,json,html,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from test_http import HTTP
class PGHTTP(HTTP):
 @classmethod
 def setUpClass(cls):
  from sqlalchemy import create_engine,text
  from sqlalchemy.engine import make_url
  url=os.environ['DEMO_POSTGRES_URL'];u=make_url(url)
  assert u.get_backend_name()=='postgresql' and u.host=='127.0.0.1' and u.port==55439 and u.database=='dkss_demo_cas_ci' and not u.query
  cls.schema='demo_cas_'+uuid.uuid4().hex;assert re.fullmatch('demo_cas_[0-9a-f]{32}',cls.schema)
  cls.admin=create_engine(url,isolation_level='AUTOCOMMIT');cls.addClassCleanup(cls.admin.dispose)
  with cls.admin.connect() as c:
   assert c.scalar(text('SELECT current_database()'))=='dkss_demo_cas_ci';c.execute(text('CREATE SCHEMA "'+cls.schema+'"'))
  def drop():
   with cls.admin.connect() as c:c.execute(text('DROP SCHEMA "'+cls.schema+'" CASCADE'))
  cls.addClassCleanup(drop)
  from dkss_app import create_app,models
  from dkss_app.extensions import db,limiter
  cls.db,cls.models=db,models
  with patch.dict(os.environ,{'SECRET_KEY':'synthetic-demo-cas-ci-only','DATABASE_URL':url,'RENDER':'','RATELIMIT_STORAGE_URI':'memory://','OPENAI_API_KEY':'','SMTP_HOST':'','S3_BUCKET_NAME':'','VAPID_PRIVATE_KEY':'','VAPID_PUBLIC_KEY':''}):
   cls.app=create_app({'TESTING':True,'WTF_CSRF_ENABLED':False,'PUBLIC_DEMO_CANDIDATE':True,'PUBLIC_DEMO_WORKFLOW':True,'PUBLIC_DEMO_SHARED_COMPANY':True,'PUBLIC_DEMO_COMPANY':'AONAGI','PUBLIC_DEMO_USERNAME':'checker','PUBLIC_DEMO_DRIVER':'checker','PUBLIC_DEMO_MANAGER':'admin','PUBLIC_DEMO_EPOCH':'synthetic','PUBLIC_DEMO_UNTIL':int(time.time())+3600,'PUBLIC_DEMO_VEHICLE_ID':1,'PUBLIC_DEMO_CHECKLIST_ID':1,'PUBLIC_DEMO_DAY':'2026-10-23','SQLALCHEMY_ENGINE_OPTIONS':{'pool_size':6,'max_overflow':0,'connect_args':{'options':'-csearch_path='+cls.schema+' -cstatement_timeout=20000 -clock_timeout=10000'}}})
  limiter.enabled=False
 @classmethod
 def tearDownClass(cls):
  with cls.app.app_context():cls.db.session.remove();cls.db.engine.dispose()
 def setUp(self):
  super().setUp()
  from sqlalchemy import text
  # Production logical-key uniqueness, explicitly rebuilt after fixture create_all.
  self.db.session.execute(text('CREATE UNIQUE INDEX demo_cas_result_key ON vehicle_checklist_result (company_code, checklist_id, vehicle_record_id, year, month, day)'));self.db.session.commit()
 def test_parallel_first_creation_and_completion(self):
  from flask import g
  token,csrf=self.setup_page();second=self.app.test_client();self.assertEqual(second.get('/demo').status_code,302)
  g.pop('csrf_token',None);g.pop('csrf_valid',None)
  page=second.get(self.url,query_string=self.params).get_data(as_text=True)
  csrf2=html.unescape(re.search(r'name="csrf_token" value="([^"]+)"',page)[1]);token2=html.unescape(re.search(r'name="demo_snapshot" value="([^"]+)"',page)[1])
  barrier=threading.Barrier(2)
  def save(args):
   client,t,c,value=args;barrier.wait(timeout=10)
   r=client.post(self.url+'/save-one',data={**self.params,'item_no':'0','value':value,'csrf_token':c},headers={'X-DKSS-Validation-Only':'1','X-DKSS-Demo-Snapshot':t})
   assert r.status_code==200;return r.json
  with ThreadPoolExecutor(2) as pool:out=list(pool.map(save,[(self.client,token,csrf,'✓'),(second,token2,csrf2,'×')]))
  self.db.session.expire_all();self.assertEqual(sum(x['saved'] is True for x in out),1);self.assertEqual(sum(x.get('preserved') is True for x in out),1);self.assertEqual(self.models.VehicleChecklistResult.query.count(),1)
  # Fill remaining required fields via acknowledged real routes.
  g.pop('csrf_token',None);g.pop('csrf_valid',None)
  page=self.client.get(self.url,query_string=self.params).get_data(as_text=True);token=html.unescape(re.search(r'name="demo_snapshot" value="([^"]+)"',page)[1]);count=sum(i.get('item_type')=='check' for i in json.loads(self.models.Checklist.query.get(self.cid).items_json))
  for n in range(1,count):
   r=self.client.post(self.url+'/save-one',data={**self.params,'item_no':str(n),'value':'✓','csrf_token':csrf},headers={'X-DKSS-Validation-Only':'1','X-DKSS-Demo-Snapshot':token});self.assertIs(r.json['saved'],True);token=r.headers['X-DKSS-Demo-Snapshot']
  proofpage=self.client.get(self.url,query_string=self.params).get_data(as_text=True);proof=html.unescape(re.search(r'name="person_selection_token"\s+value="([^"]+)"',proofpage)[1])
  proofpage2=second.get(self.url,query_string=self.params).get_data(as_text=True);proof2=html.unescape(re.search(r'name="person_selection_token"\s+value="([^"]+)"',proofpage2)[1]);token2=html.unescape(re.search(r'name="demo_snapshot" value="([^"]+)"',proofpage2)[1])
  before=self.models.Notification.query.count();barrier=threading.Barrier(2)
  def complete(args):
   client,t,c,p=args;barrier.wait(timeout=10);r=client.post(self.url+'/complete',data={**self.params,'csrf_token':c,'person_selection_token':p,'approval_notify_users_0':'admin'},headers={'X-DKSS-Final-Submit':'1','X-DKSS-Demo-Snapshot':t});assert r.status_code==200;return r.json
  with ThreadPoolExecutor(2) as pool:out=list(pool.map(complete,[(self.client,token,csrf,proof),(second,token2,csrf2,proof2)]))
  self.db.session.expire_all();self.assertEqual(sum(x.get('saved') is True for x in out),1);self.assertEqual(sum(x.get('preserved') is True for x in out),1);self.assertEqual(self.models.VehicleChecklistResult.query.one().status,'承認待ち');self.assertEqual(self.models.Notification.query.count()-before,1)
def load_tests(loader,tests,pattern):return unittest.TestSuite([PGHTTP('test_parallel_first_creation_and_completion')])
if __name__=='__main__':unittest.main(verbosity=2)
