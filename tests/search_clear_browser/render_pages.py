"""Synthetic real GETs only; external sockets and non-SQLite engines forbidden."""
import os,sys,json,socket,unittest
from html.parser import HTMLParser
class EntryParser(HTMLParser):
 def __init__(self):super().__init__();self.entries=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if "entry-add-icon" in a.get("class","").split():self.entries.append(a)
from pathlib import Path
import sqlalchemy
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external socket forbidden'))
socket.create_connection=socket.socket.connect
_create=sqlalchemy.create_engine
def sqlite_only(url,*a,**kw):
 assert str(url).startswith('sqlite:');return _create(url,*a,**kw)
sqlalchemy.create_engine=sqlite_only
R=Path(os.environ['PRODUCT_REPO']).resolve()
sys.path[:0]=[str(R/'tests/demo_guide/fixtures'),str(R/'tests'),str(R)]
from test_demo_inspection_compact import CompactDemoTests
from flask import url_for
class Pages(CompactDemoTests):
 def test_entries(self):
  self.demo_active=False;self.login('admin','B')
  out=Path(os.environ['HTML_OUT']);out.mkdir(parents=True,exist_ok=True)
  names=['driver_master','vehicle_master']
  m=self.models
  self.db.session.add(m.Driver(company_code="B",employee_id="synthetic-person",name="長い名前の表示確認ドライバー",office="長い営業所名の表示確認営業所"))
  vehicle=m.Vehicle.query.filter_by(company_code="B").first();vehicle.plate_area="品川";vehicle.plate_class="100";vehicle.plate_kana="か";vehicle.plate_number="1234"
  checklist=m.Checklist(company_code='B',name='安全確認',target='安全管理',display_type='日',items_json='[]');self.db.session.add(checklist);self.db.session.commit()
  rows=[]
  for name in names:
   if name=='itc_dashboard':
    u=m.User.query.filter_by(company_code='B',username='admin').one();u.role='itc';self.db.session.commit();self.login('admin','B')
   rule=next(x for x in self.app.url_map.iter_rules() if x.endpoint==name and 'GET' in x.methods)
   with self.app.test_request_context():p=url_for(name,**{k:checklist.id for k in rule.arguments})
   response=self.client.get(p);self.assertEqual(response.status_code,200,(name,response.status_code,response.location))
   self.assertIn('search_field_clear.js',response.text)
   (out/(name+'.html')).write_text(response.text)
   rows.append({'endpoint':name,'path':p})
  self.assertEqual(len(rows),2)
  (out/'routes.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
if __name__=='__main__':
 r=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Pages('test_entries')]));sys.exit(not r.wasSuccessful())
