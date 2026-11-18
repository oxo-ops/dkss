"""Read-only HTTP rendering over disposable SQLite, extends existing guide fixture.
No deployed service, SMTP, OpenAI, or storage is involved.
"""
import os,sys,importlib.util,json,unittest,socket
from pathlib import Path
import sqlalchemy
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external socket forbidden'))
socket.create_connection=socket.socket.connect
engine=sqlalchemy.create_engine
def sqlite_only(url,*a,**k):
 assert str(url).startswith('sqlite:'), 'SQLite fixture only'
 return engine(url,*a,**k)
sqlalchemy.create_engine=sqlite_only
R=Path(os.environ['PRODUCT_REPO']).resolve();D=R/'tests/demo_guide'
sys.path[:0]=[str(D),str(D/'fixtures'),str(R),str(R/'tests')]
spec=importlib.util.spec_from_file_location('action_guide_pages',D/'render_pages.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
class ActionPages(base.Pages):
 def test_action_pages(self):
  super().test_pages()
  self.demo_active=False;self.login('admin','B')
  m=self.models
  for model in [m.VehicleType,m.LicenseType,m.Office,m.DeliveryPlace,m.PatrolContentType]:self.db.session.add(model(company_code='B',name='確認用項目'))
  self.db.session.add(m.Driver(company_code='B',employee_id='sample',name='確認用運転者',office='test'))
  self.db.session.commit()
  self.db.session.add(m.Checklist(company_code='B',name='確認用の安全点検表',target='安全管理',items_json='[]'));self.db.session.commit()
  out=Path(os.environ['HTML_OUT']);rows=json.loads((out/'routes.json').read_text())
  names=['checklist_master','vehicle_master','vehicle_type_master','license_type_master','office_master','delivery_place_master','patrol_content_type_master','driver_master','manual_master','new_vehicle_type','new_license_type','new_office','new_delivery_place','new_patrol_content_type','new_driver','new_manual']
  from flask import url_for
  for name in names:
   rule=next(r for r in self.app.url_map.iter_rules() if r.endpoint==name and 'GET' in r.methods);self.assertFalse(rule.arguments)
   with self.app.test_request_context():path=url_for(name)
   response=self.client.get(path);self.assertEqual(response.status_code,200,(name,response.status_code,response.headers.get('Location')))
   key='normal_'+name;(out/(key+'.html')).write_text(response.text)
   rows.append(dict(endpoint=key,path=path,status=200,synthetic_company='B',role='admin'))
  # Real settings page via existing verified demo/ordinary session fixtures, read-only.
  for demo in [True,False]:
   for role,username in [('manager','admin'),('driver','checker')]:
    self.demo_active=demo;self.login(username)
    with self.client.session_transaction() as sess:sess['demo_role_selected']=True
    response=self.client.get('/settings');self.assertEqual(response.status_code,200)
    key=('demo_' if demo else 'normal_')+'settings_'+role
    text=response.text
    self.assertIn('settings-user-card',text)
    for marker in ['settings-notification-card','settings-password-card','action="/logout"']:
     self.assertEqual(marker in text,not demo,(key,marker))
    (out/(key+'.html')).write_text(text)
    rows.append(dict(endpoint=key,path='/settings',status=200,role=role,demo=demo))
  self.demo_active=False;self.login('admin','B')
  # Existing real role/state fixtures: separate from initial unselected inspection page.
  for state in json.loads((out/'inspection-states/states.json').read_text()):
   key='inspection_'+state['role']+'_'+state['code']
   (out/(key+'.html')).write_bytes((out/'inspection-states'/state['file']).read_bytes())
   rows.append(dict(endpoint=key,path=state['path'],status=200,role=state['role'],inspection_state=state['code']))
  for name,model in [('edit_vehicle_type',m.VehicleType),('edit_license_type',m.LicenseType),('edit_office',m.Office),('edit_delivery_place',m.DeliveryPlace),('edit_patrol_content_type',m.PatrolContentType),('edit_driver',m.Driver)]:
   item=model.query.filter_by(company_code='B').order_by(model.id).first();self.assertIsNotNone(item)
   with self.app.test_request_context():path=url_for(name,index=item.id)
   response=self.client.get(path);self.assertEqual(response.status_code,200,(name,response.status_code))
   key='normal_'+name;(out/(key+'.html')).write_text(response.text)
   rows.append(dict(endpoint=key,path=path,status=200,synthetic_company='B',role='admin'))
  (out/'routes.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
  (out/'coverage.json').write_text(json.dumps({'real_html_pages':len(list(out.glob('*.html'))),'added_normal_master_pages':len(names)+6,'inspection_role_states':12,'business_posts':0,'real_login':False,'live':False,'csrf_fixture':False},indent=2))
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([ActionPages('test_action_pages')]))
 sys.exit(not result.wasSuccessful())
