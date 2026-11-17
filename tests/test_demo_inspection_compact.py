"""Real routes, synthetic SQLite only. No production records or external delivery."""
import html,re,time,unittest
from test_public_demo_workflow import DemoWorkflowTests as Base
class CompactDemoTests(Base):
 def setUp(self):
  super().setUp();self.app.config['PUBLIC_DEMO_SHARED_COMPANY']=True
  self.addCleanup(self.app.config.pop,'PUBLIC_DEMO_SHARED_COMPANY',None)
  v=self.models.Vehicle.query.filter_by(company_code='A').one()
  v.plate_area='品川';v.plate_class='100';v.plate_kana='か';v.plate_number='101';self.db.session.commit()
  self.vehicle_id=v.id;self.client=self.app.test_client()
 def enter(self):
  self.assertEqual(self.client.get('/demo').location,'/')
  text=self.client.get('/').get_data(as_text=True)
  return html.unescape(re.search(r'name="csrf_token" value="([^"]+)"',text)[1]),text
 def test_role_selection_hides_notice_and_reentry_restores_it(self):
  for role in ('driver','manager'):
   token,text=self.enter();self.assertIn('class="alert public-demo-notice"',text)
   self.assertNotIn('体験を終了',text)
   count=self.models.VehicleChecklistResult.query.count()
   reply=self.client.post('/demo/role',data={'role':role,'csrf_token':token})
   self.assertEqual(reply.status_code,302);self.assertEqual(reply.location,'/')
   with self.client.session_transaction() as s:self.assertIs(s['demo_role_selected'],True)
   selected=self.client.get('/').get_data(as_text=True)
   self.assertNotIn('class="alert public-demo-notice"',selected)
   self.assertEqual(count,self.models.VehicleChecklistResult.query.count())
   self.enter()
   with self.client.session_transaction() as s:self.assertNotIn('demo_role_selected',s)
 def test_failures_do_not_set_selection(self):
  token,_=self.enter()
  for data,status in (({'role':'driver'},400),({'role':'invalid','csrf_token':token},400)):
   self.assertEqual(self.client.post('/demo/role',data=data).status_code,status)
   with self.client.session_transaction() as s:self.assertNotIn('demo_role_selected',s)
  user=self.models.User.query.filter_by(company_code='A',username='admin').one();user.login_locked=True;self.db.session.commit()
  self.assertEqual(self.client.post('/demo/role',data={'role':'manager','csrf_token':token}).status_code,404)
  with self.client.session_transaction() as s:self.assertNotIn('demo_role_selected',s)
 def test_point_to_existing_vehicle_and_selected_form(self):
  token,text=self.enter();checklist=self.app.config['PUBLIC_DEMO_CHECKLIST_ID']
  target=f'/vehicle/checklists/{checklist}?vehicle_record_id={self.vehicle_id}'
  self.assertIn(target,text)
  page=self.client.get(target);self.assertEqual(page.status_code,200)
  text=page.get_data(as_text=True)
  self.assertIn('id="vehicle_workspace_date"',text);self.assertIn('エンジンのかかり具合、異音',text)
  self.assertNotIn('<div class="criteria-box" hidden>',text)
  self.assertIn('criteria-line-pre',text);self.assertNotIn('入力日はプルダウン',text)
  self.assertEqual(0,self.models.VehicleChecklistResult.query.count())
 def test_ordinary_login_cannot_be_replaced_by_demo(self):
  self.demo_active=False;self.login('checker')
  self.assertEqual(self.client.get('/demo').status_code,409)
 def test_expired_demo_does_not_accept_role(self):
  token,_=self.enter()
  old=self.app.config['PUBLIC_DEMO_UNTIL']
  self.app.config['PUBLIC_DEMO_UNTIL']=int(time.time())-1
  self.addCleanup(self.app.config.update,PUBLIC_DEMO_UNTIL=old)
  self.assertEqual(self.client.post('/demo/role',data={'role':'driver','csrf_token':token}).status_code,410)
 def test_ordinary_company_keeps_criteria(self):
  self.demo_active=False;self.login('checker')
  target=f'/vehicle/checklists/{self.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}?vehicle_record_id={self.vehicle_id}'
  page=self.client.get(target);self.assertEqual(page.status_code,200)
  self.assertIn('criteria-line-pre',page.get_data(as_text=True))
  self.assertNotIn('<div class="criteria-box" hidden>',page.get_data(as_text=True))

# The inherited fixture also has non-shared workflow tests. Run those in their
# original module/config; this suite covers only the six shared-mode additions.
def load_tests(loader, tests, pattern):
 return unittest.TestSuite(CompactDemoTests(name) for name in (
  'test_role_selection_hides_notice_and_reentry_restores_it',
  'test_failures_do_not_set_selection',
  'test_point_to_existing_vehicle_and_selected_form',
  'test_ordinary_company_keeps_criteria',
  'test_ordinary_login_cannot_be_replaced_by_demo',
  'test_expired_demo_does_not_accept_role'))
