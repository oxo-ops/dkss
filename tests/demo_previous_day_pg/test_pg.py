"""Unexecuted real-PG candidate. Dedicated synthetic CI database ONLY.
No browser claim. Ordinary-writer race is tested only by the named HTTP case.
DDL destroys fixture tables.
"""
import os,sys,time,json,unittest,threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from unittest.mock import patch
from urllib.parse import urlsplit
URL='postgresql+psycopg2://seed_fixture:synthetic_only@127.0.0.1:55433/seed_fixture'
if os.environ.get('SEED_ISOLATED_PG')!='1' or os.environ.get('DATABASE_URL')!=URL:
 raise SystemExit('DEDICATED_SYNTHETIC_DATABASE_REQUIRED')
if any(os.environ.get(k) for k in ('RENDER','OPENAI_API_KEY','SMTP_HOST','S3_BUCKET_NAME','VAPID_PRIVATE_KEY','VAPID_PUBLIC_KEY','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY')):
 raise SystemExit('EXTERNAL_CONFIGURATION_NOT_ALLOWED')
from test_public_demo_workflow import DemoWorkflowTests as Base
from service_candidate import prepare_previous,Target
from sqlalchemy import text
class PG(Base):
 @classmethod
 def setUpClass(cls):
  from dkss_app import create_app,models
  from dkss_app.extensions import db,limiter
  cls.db,cls.models=db,models
  cls.app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':URL,'SQLALCHEMY_ENGINE_OPTIONS':{'pool_size':20,'max_overflow':0},'WTF_CSRF_ENABLED':False,
   'PUBLIC_DEMO_CANDIDATE':True,'PUBLIC_DEMO_WORKFLOW':True,'PUBLIC_DEMO_COMPANY':'A','PUBLIC_DEMO_USERNAME':'checker','PUBLIC_DEMO_DRIVER':'checker','PUBLIC_DEMO_MANAGER':'admin',
   'PUBLIC_DEMO_EPOCH':'test','PUBLIC_DEMO_UNTIL':int(time.time())+3600,'PUBLIC_DEMO_FROM':int(time.time())-3600,'PUBLIC_DEMO_VEHICLE_ID':1,'PUBLIC_DEMO_CHECKLIST_ID':1,'PUBLIC_DEMO_DAY':'2026-10-23'})
  limiter.enabled=False
 def setUp(self):
  super().setUp();self.app.config['PUBLIC_DEMO_SHARED_COMPANY']=True
  self.login('checker');self.now=datetime.now(timezone.utc)
  master=self.models.Checklist.query.filter_by(company_code='A').one();v=self.models.Vehicle.query.filter_by(company_code='A').one()
  self.target=Target('A',v.id,master.id,v.chassis_number)
  with self.client.session_transaction() as s:self.state=dict(s)
  self.demo_active=False;self.login('admin')
  with self.client.session_transaction() as s:self.normal_state=dict(s)
  self.demo_active=True
  # Same deployed unique-key definition; creation here proves fixture only.
  self.db.session.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS seed_date_unique ON vehicle_checklist_result (company_code,checklist_id,vehicle_record_id,year,month,day)'))
  self.db.session.commit();self.db.session.remove()
 def tearDown(self):
  self.app.config.pop('PUBLIC_DEMO_SHARED_COMPANY',None);super().tearDown()
 def worker(self,barrier=None,fail=False):
  from flask import session
  with self.app.test_request_context('/demo'):
   session.update(self.state)
   pid=self.db.session.execute(text('SELECT pg_backend_pid()')).scalar()
   if barrier:barrier.wait(timeout=30)
   try:return pid,prepare_previous(self.target,now=self.now,fail_before_commit=fail)
   finally:self.db.session.remove()
 def test_sixteen_distinct_connections_one_created(self):
  barrier=threading.Barrier(16)
  with ThreadPoolExecutor(max_workers=16) as pool:results=list(pool.map(lambda _:self.worker(barrier),range(16)))
  self.assertEqual(len({pid for pid,_ in results}),16)
  self.assertEqual([state for _,state in results].count('created'),1)
  self.assertEqual([state for _,state in results].count('preserved'),15)
  self.assertEqual(self.models.VehicleChecklistResult.query.count(),1)
  row=self.models.VehicleChecklistResult.query.one();self.assertEqual(len(json.loads(row.answers_json)),27)
  self.assertEqual(self.models.Notification.query.count(),0)
  self.assertEqual(self.models.VehicleKarteAnalysis.query.count(),0)
 def test_regular_http_save_races_seed_without_lost_user_answer(self):
  import re,html
  from datetime import timedelta
  from zoneinfo import ZoneInfo
  day=self.now.astimezone(ZoneInfo('Asia/Tokyo')).date()-timedelta(days=1)
  barrier=threading.Barrier(2);self.app.config['WTF_CSRF_ENABLED']=True
  def save():
   with self.app.app_context():
    client=self.app.test_client()
    with client.session_transaction() as s:s.update(self.normal_state)
    params={'vehicle_record_id':self.target.vehicle,'year':str(day.year),'month':f'{day.month:02}','active_day':f'{day.day:02}'}
    page=client.get(f'/vehicle/checklists/{self.target.checklist}',query_string=params)
    self.assertEqual(page.status_code,200)
    token=html.unescape(re.search(r'name="csrf_token" value="([^"]+)"',page.get_data(as_text=True))[1])
    pid=self.db.session.execute(text('SELECT pg_backend_pid()')).scalar();barrier.wait(timeout=30)
    response=client.post(f'/vehicle/checklists/{self.target.checklist}/save-one',data={**params,'day':f'{day.day:02}','item_no':'0','value':'×','csrf_token':token})
    try:self.assertEqual(response.status_code,200);return pid
    finally:self.db.session.remove()
  try:
   with ThreadPoolExecutor(max_workers=2) as pool:
    a=pool.submit(self.worker,barrier);b=pool.submit(save);seed=a.result(timeout=45);writer=b.result(timeout=45)
   self.assertNotEqual(seed[0],writer)
   row=self.models.VehicleChecklistResult.query.one()
   values={str(x['item_no']):x['value'] for x in json.loads(row.answers_json)}
   self.assertEqual(values['0'],'×');self.assertIn(seed[1],{'created','preserved'})
  finally:self.app.config['WTF_CSRF_ENABLED']=False
 def test_rollback_then_clean_separate_connection(self):
  with self.assertRaises(ValueError):self.worker(fail=True)
  self.assertEqual(self.models.VehicleChecklistResult.query.count(),0);self.db.session.remove()
  self.assertEqual(self.worker()[1],'created')
 def test_existing_partial_answer_not_overwritten(self):
  self.worker();row=self.models.VehicleChecklistResult.query.one();row.answers_json='[{"item_no":0,"value":"×"}]';self.db.session.commit();before=row.answers_json;self.db.session.remove()
  self.assertEqual(self.worker()[1],'preserved');self.assertEqual(self.models.VehicleChecklistResult.query.one().answers_json,before)
suite=unittest.TestSuite(PG(x) for x in ['test_sixteen_distinct_connections_one_created','test_rollback_then_clean_separate_connection','test_existing_partial_answer_not_overwritten','test_regular_http_save_races_seed_without_lost_user_answer'])
r=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not r.wasSuccessful())
