"""Synthetic real routes; no external network, notifications or live data."""
import os,sys,json,re,html,socket,unittest
from pathlib import Path
import sqlalchemy
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError("external connection forbidden"))
socket.create_connection=socket.socket.connect
original=sqlalchemy.create_engine
def sqlite_only(url,*a,**kw):
 assert str(url).startswith("sqlite:")
 return original(url,*a,**kw)
sqlalchemy.create_engine=sqlite_only
R=Path(os.environ['PRODUCT_REPO']).resolve()
sys.path[:0]=[str(R/'tests/demo_guide/fixtures'),str(R/'tests'),str(R)]
from test_public_demo_workflow import DemoWorkflowTests
class Pages(DemoWorkflowTests):
 def test_names(self):
  from dkss_app.checklist_notify_identity import initialize_notify_identities
  initialize_notify_identities()
  self.app.config['PUBLIC_DEMO_SHARED_COMPANY']=True
  self.demo_active=False;self.login('admin')
  user=self.models.User.query.filter_by(company_code='AONAGI',username='admin').one()
  user.last_name='通知担当';user.first_name='太郎'
  self.db.session.commit()
  cid=self.app.config['PUBLIC_DEMO_CHECKLIST_ID']
  url=f'/vehicle/checklists/{cid}?vehicle_record_id=1&year=2026&month=10&active_day=24'
  page=self.request('GET',url).get_data(as_text=True)
  match=re.search(r'name="person_selection_token"\s+value="([^"]+)"',page)
  proof={'person_selection_token':html.unescape(match[1])} if match else {}
  endpoint=f'/vehicle/checklists/{cid}/reminder-notify-users'
  self.assertEqual(self.request('POST',endpoint,data={'vehicle_record_id':'1','reminder_notify_users':'admin',**proof}).status_code,200)
  out=Path(os.environ['HTML_OUT']);out.mkdir(parents=True,exist_ok=True);rows=[]
  for demo in [False,True]:
   for role,username in [('driver','checker'),('manager','admin')]:
    self.demo_active=demo;self.login(username)
    with self.client.session_transaction() as sess:sess['demo_role_selected']=True
    response=self.request('GET',url);self.assertEqual(response.status_code,200)
    text=response.get_data(as_text=True)
    block=text.split('data-reminder-readonly',1)[1].split('</div>',1)[0] if role=='driver' else text.split('id="selected_reminder_notify_users"',1)[1].split('</div>',1)[0]
    self.assertIn('通知担当太郎',block)
    if role=='driver':self.assertNotIn('>admin<',block);self.assertNotIn('<button',block)
    else:self.assertIn('data-user-name="admin"',block)
    name=('demo' if demo else 'normal')+'-'+role
    (out/(name+'.html')).write_text(text);rows.append({'endpoint':name,'path':url,'role':role})
  (out/'routes.json').write_text(json.dumps(rows))
if __name__=='__main__':
 r=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Pages('test_names')]));sys.exit(not r.wasSuccessful())
