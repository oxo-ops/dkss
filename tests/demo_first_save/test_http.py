import os,sys,re,html,json,unittest
from pathlib import Path
D=Path(__file__).resolve().parent
REPO=Path(os.environ['DEMO_CANDIDATE_REPO']).resolve()
sys.path[:0]=[str(D/'fixtures'),str(REPO),str(REPO/'tests')]
from test_demo_inspection_compact import CompactDemoTests
class HTTP(CompactDemoTests):
 def setUp(self):
  super().setUp()
  from flask.testing import FlaskClient
  original=self.app.test_client_class
  class FreshRequestClient(FlaskClient):
   def open(client,*args,**kwargs):
    with client.application.app_context():
     response=super(FreshRequestClient,client).open(*args,**kwargs)
    from dkss_app.extensions import db
    from flask import has_app_context
    if has_app_context():db.session.expire_all()
    return response
  self.app.test_client_class=FreshRequestClient
  self.addCleanup(setattr,self.app,'test_client_class',original)
  self.client=self.app.test_client()
 def setup_page(self):
  self.enter();self.app.config['WTF_CSRF_ENABLED']=True;self.addCleanup(self.app.config.update,WTF_CSRF_ENABLED=False)
  self.cid=self.app.config['PUBLIC_DEMO_CHECKLIST_ID'];self.url=f'/vehicle/checklists/{self.cid}';self.params={'vehicle_record_id':self.vehicle_id,'year':'2026','month':'10','day':'23','active_day':'23'}
  page=self.client.get(self.url,query_string=self.params);self.assertEqual(page.status_code,200);text=page.get_data(as_text=True)
  def field(n):return html.unescape(re.search('name="'+n+'" value="([^"]+)"',text)[1])
  return field('demo_snapshot'),field('csrf_token')
 def test_stale_inline_and_detail_preserve(self):
  t,csrf=self.setup_page();headers={'X-DKSS-Validation-Only':'1','X-DKSS-Demo-Snapshot':t}
  data={**self.params,'item_no':'0','value':'×','csrf_token':csrf}
  first=self.client.post(self.url+'/save-one',data=data,headers=headers);self.assertEqual(first.status_code,200);self.assertIs(first.json['saved'],True)
  row=self.models.VehicleChecklistResult.query.one();before=row.answers_json;counts=(self.models.Notification.query.count(),self.models.ChecklistEvent.query.count())
  later=self.client.post(self.url+'/save-one',data={**data,'value':'✓'},headers=headers);self.assertEqual(later.status_code,200);self.assertIs(later.json['saved'],False);self.assertIs(later.json['preserved'],True)
  detail=self.client.post(self.url+'/save-detail',data={**data,'comment':'stale comment'},headers=headers);self.assertEqual(detail.status_code,200);self.assertIs(detail.json['preserved'],True)
  self.db.session.refresh(row);self.assertEqual(row.answers_json,before);self.assertEqual(counts,(self.models.Notification.query.count(),self.models.ChecklistEvent.query.count()))
  self.assertEqual(self.client.get(later.json['redirect_url']).status_code,200)
  ack=first.headers['X-DKSS-Demo-Snapshot'];own=self.client.post(self.url+'/save-one',data={**data,'value':'✓'},headers={**headers,'X-DKSS-Demo-Snapshot':ack});self.assertIs(own.json['saved'],True)
 def test_complete_once_and_stale_complete(self):
  token,csrf=self.setup_page();items=json.loads(self.models.Checklist.query.get(self.cid).items_json);count=sum(i.get('item_type')=='check' for i in items)
  old=token
  for n in range(count):
   r=self.client.post(self.url+'/save-one',data={**self.params,'item_no':str(n),'value':'✓','csrf_token':csrf},headers={'X-DKSS-Validation-Only':'1','X-DKSS-Demo-Snapshot':token});self.assertEqual(r.status_code,200);self.assertIs(r.json['saved'],True);token=r.headers['X-DKSS-Demo-Snapshot']
  page=self.client.get(self.url,query_string=self.params).get_data(as_text=True);proof=html.unescape(re.search(r'name="person_selection_token"\s+value="([^"]+)"',page)[1]);body={**self.params,'csrf_token':csrf,'person_selection_token':proof,'approval_notify_users_0':'admin'}
  stale=self.client.post(self.url+'/complete',data=body,headers={'X-DKSS-Final-Submit':'1','X-DKSS-Demo-Snapshot':old});self.assertIs(stale.json['preserved'],True);self.assertEqual(self.models.VehicleChecklistResult.query.one().status,'入力中');self.assertEqual(self.models.Notification.query.count(),0)
  result=self.client.post(self.url+'/complete',data=body,headers={'X-DKSS-Final-Submit':'1','X-DKSS-Demo-Snapshot':token});self.assertEqual(result.status_code,200);self.assertIs(result.json['success'],True)
  row=self.models.VehicleChecklistResult.query.one();self.db.session.refresh(row);self.assertEqual(row.status,'承認待ち')
  def snapshot():return tuple(tuple(tuple(getattr(r,c.name) for c in m.__table__.columns) for r in m.query.order_by(m.id)) for m in (self.models.VehicleChecklistResult,self.models.Notification,self.models.ChecklistEvent))
  before=snapshot();again=self.client.post(self.url+'/complete',data=body,headers={'X-DKSS-Final-Submit':'1','X-DKSS-Demo-Snapshot':token});self.assertIs(again.json['preserved'],True);self.assertEqual(snapshot(),before);self.assertEqual(self.client.get(again.json['redirect_url']).status_code,200)
 def test_two_cookie_clients_and_no_late_upload(self):
  from flask import g
  from unittest.mock import patch
  import io
  first_token,first_csrf=self.setup_page();second=self.app.test_client();self.assertEqual(second.get('/demo').status_code,302)
  g.pop('csrf_token',None);g.pop('csrf_valid',None)
  page=second.get(self.url,query_string=self.params).get_data(as_text=True)
  second_token=html.unescape(re.search(r'name="demo_snapshot" value="([^"]+)"',page)[1]);second_csrf=html.unescape(re.search(r'name="csrf_token" value="([^"]+)"',page)[1])
  with self.client.session_transaction() as a: atoken=a['public_demo_token']
  with second.session_transaction() as b:self.assertNotEqual(atoken,b['public_demo_token'])
  g.pop('csrf_token',None);g.pop('csrf_valid',None)
  first=self.client.post(self.url+'/save-one',data={**self.params,'item_no':'0','value':'×','csrf_token':first_csrf},headers={'X-DKSS-Validation-Only':'1','X-DKSS-Demo-Snapshot':first_token});self.assertIs(first.json['saved'],True)
  before=self.models.VehicleChecklistResult.query.one().answers_json
  g.pop('csrf_token',None);g.pop('csrf_valid',None)
  with patch('dkss_app.storage.save_uploaded_file',side_effect=AssertionError('stale upload must not start')) as upload:
   later=second.post(self.url+'/save-detail',data={**self.params,'item_no':'0','comment':'other browser','csrf_token':second_csrf,'files':(io.BytesIO(b'synthetic'),'late.png')},headers={'X-DKSS-Validation-Only':'1','X-DKSS-Demo-Snapshot':second_token});self.assertEqual(later.status_code,200);self.assertIs(later.json['preserved'],True);upload.assert_not_called()
  self.assertEqual(self.models.VehicleChecklistResult.query.one().answers_json,before)
  g.pop('csrf_token',None);g.pop('csrf_valid',None)
  invalid=second.post(self.url+'/save-one',data={**self.params,'item_no':'0','value':'✓','csrf_token':'bad'},headers={'X-DKSS-Validation-Only':'1','X-DKSS-Demo-Snapshot':second_token});self.assertEqual(invalid.status_code,400);self.assertEqual(self.models.VehicleChecklistResult.query.one().answers_json,before)
 def test_ack_does_not_adopt_post_commit_writer(self):
  from unittest.mock import patch
  token,csrf=self.setup_page()
  def later_writer(record):
   answers=json.loads(record.answers_json);answers[0]['comment']='separate committed writer';record.answers_json=json.dumps(answers,ensure_ascii=False);self.db.session.commit()
  body={**self.params,'item_no':'0','value':'✓','csrf_token':csrf}
  with patch('dkss_app.checklists.dispatch_vehicle_defect_notifications',side_effect=later_writer):
   first=self.client.post(self.url+'/save-one',data=body,headers={'X-DKSS-Validation-Only':'1','X-DKSS-Demo-Snapshot':token});self.assertIs(first.json['saved'],True)
  ack=first.headers['X-DKSS-Demo-Snapshot'];before=self.models.VehicleChecklistResult.query.one().answers_json
  second=self.client.post(self.url+'/save-one',data={**body,'value':'×'},headers={'X-DKSS-Validation-Only':'1','X-DKSS-Demo-Snapshot':ack});self.assertIs(second.json['preserved'],True);self.assertEqual(self.models.VehicleChecklistResult.query.one().answers_json,before)
 def test_ordinary_unchanged(self):
  self.demo_active=False;self.login('checker');cid=self.app.config['PUBLIC_DEMO_CHECKLIST_ID'];r=self.client.post(f'/vehicle/checklists/{cid}/save-one',data={'vehicle_record_id':self.vehicle_id,'year':'2026','month':'10','day':'23','item_no':'0','value':'✓'});self.assertEqual(r.status_code,302)
def load_tests(loader,tests,pattern):return unittest.TestSuite(HTTP(n) for n in ['test_stale_inline_and_detail_preserve','test_complete_once_and_stale_complete','test_two_cookie_clients_and_no_late_upload','test_ack_does_not_adopt_post_commit_writer','test_ordinary_unchanged'])
if __name__=='__main__':unittest.main(verbosity=2)
