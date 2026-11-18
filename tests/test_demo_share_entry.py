import unittest,time
from test_demo_inspection_compact import CompactDemoTests as Base
class ShareEntryTests(Base):
 def setUp(self):
  super().setUp();self.path=f'/vehicle/checklists/{self.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}?vehicle_record_id={self.vehicle_id}&__aonagi_entry=1'
 def test_fresh_deep_entry_and_distinct_browser(self):
  a=self.app.test_client();b=self.app.test_client()
  for c in (a,b):
   first=c.get(self.path);self.assertEqual(first.status_code,302);self.assertEqual(first.location,self.path)
   r=c.get(first.location);self.assertEqual(r.status_code,200);self.assertIn('no-store',r.headers['Cache-Control']);self.assertEqual(r.headers['Referrer-Policy'],'same-origin')
  with a.session_transaction() as s:token=s['public_demo_token'];self.assertEqual(s['demo_role'],'driver')
  with b.session_transaction() as s:self.assertNotEqual(s['public_demo_token'],token)
  self.assertEqual(self.models.VehicleChecklistResult.query.count(),0)
 def test_ordinary_session_unchanged(self):
  self.demo_active=False;self.login('checker')
  with self.client.session_transaction() as s:before=dict(s)
  self.assertEqual(self.client.get(self.path).status_code,409)
  with self.client.session_transaction() as s:self.assertEqual(dict(s),before)
 def test_expired_and_revoked_not_reissued(self):
  c=self.app.test_client();c.get(self.path)
  with c.session_transaction() as s:token=s['public_demo_token']
  self.app.extensions['public_demo_active_sessions'].clear()
  self.assertEqual(c.get(self.path).status_code,410)
  self.assertFalse(self.app.extensions['public_demo_active_sessions'])
 def test_existing_manager_kept_and_role_choice_not_reset(self):
  self.login('admin')
  with self.client.session_transaction() as s:s['demo_role_selected']=True;token=s['public_demo_token']
  self.assertEqual(self.client.get(self.path).status_code,200)
  with self.client.session_transaction() as s:self.assertEqual(s['demo_role'],'manager');self.assertTrue(s['demo_role_selected']);self.assertEqual(token,s['public_demo_token'])
 def test_query_method_and_endpoint_rejected(self):
  c=self.app.test_client()
  for path,status in ((self.path+'&role=manager',400),(self.path+'&__aonagi_entry=1',400),('/vehicle/checklists?__aonagi_entry=1',404),('/login?__aonagi_entry=1',404)):
   self.assertEqual(c.get(path).status_code,status)
  self.assertEqual(c.post(self.path).status_code,405)
 def test_disabled_and_wrong_company_rejected(self):
  self.login('checker')
  with self.client.session_transaction() as s:s['company_code']='B'
  self.assertEqual(self.client.get(self.path).status_code,410)
  self.app.config['PUBLIC_DEMO_CANDIDATE']=False;self.addCleanup(self.app.config.update,PUBLIC_DEMO_CANDIDATE=True)
  self.assertEqual(self.app.test_client().get(self.path).status_code,404)
 def test_fresh_driver_cannot_take_anonymous_role_hint(self):
  c=self.app.test_client()
  with c.session_transaction() as s:s['demo_role']='manager'
  self.assertEqual(c.get(self.path).status_code,302)
  with c.session_transaction() as s:self.assertEqual(s['role'],'user');self.assertEqual(s['demo_role'],'driver')
 def test_future_window_and_locked_target_rejected(self):
  self.app.config['PUBLIC_DEMO_FROM']=int(time.time())+60
  self.assertEqual(self.app.test_client().get(self.path).status_code,404)
  self.app.config.pop('PUBLIC_DEMO_FROM')
  user=self.models.User.query.filter_by(company_code='A',username='checker').one();user.login_locked=True;self.db.session.commit()
  self.assertEqual(self.app.test_client().get(self.path).status_code,404)
 def test_wrong_vehicle_has_no_other_company_data(self):
  other=self.models.Vehicle.query.filter_by(company_code='B').one()
  path=self.path.replace('vehicle_record_id='+str(self.vehicle_id),'vehicle_record_id='+str(other.id))
  c=self.app.test_client();first=c.get(path);self.assertEqual(first.status_code,302)
  response=c.get(path);self.assertEqual(response.status_code,400)
  self.assertNotIn(other.chassis_number,response.get_data(as_text=True))
  self.assertEqual(self.models.VehicleChecklistResult.query.count(),0)
 def test_pending_mfa_is_not_replaced(self):
  c=self.app.test_client()
  with c.session_transaction() as s:s['mfa_pending_username']='admin';s['mfa_pending_company_code']='B'
  self.assertEqual(c.get(self.path).status_code,409)
  with c.session_transaction() as s:self.assertEqual(s['mfa_pending_company_code'],'B');self.assertNotIn('public_demo_token',s)
 def test_completed_hint_preserved_but_unknown_feedback_rejected(self):
  c=self.app.test_client();url=self.path+'&vehicle_saved=complete'
  self.assertEqual(c.get(url).location,url);self.assertEqual(c.get(url).status_code,200)
  self.assertEqual(c.get(self.path+'&vehicle_saved=anything').status_code,400)

def load_tests(loader,tests,pattern):
 return unittest.TestSuite(ShareEntryTests(x) for x in ShareEntryTests.__dict__ if x.startswith('test_'))
