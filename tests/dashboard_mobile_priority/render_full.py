"""Disposable real-route full-home fixture; no delivery or external DB."""
import os,sys,socket,unittest,json
from pathlib import Path
from unittest.mock import patch
P=Path(os.environ['PRODUCT_REPO']).resolve(); sys.path[:0]=[str(P),str(P/'tests')]
import sqlalchemy,sqlalchemy.engine.create
original=sqlalchemy.engine.create.create_engine
def safe(url,*a,**k):
 if not str(url).startswith('sqlite:'):raise AssertionError('non-SQLite blocked')
 return original(url,*a,**k)
sqlalchemy.create_engine=safe;sqlalchemy.engine.create.create_engine=safe
socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(AssertionError('network blocked'))
socket.create_connection=socket.socket.connect
from test_public_demo_workflow import DemoWorkflowTests
class FullHome(DemoWorkflowTests):
 def test_home(self):
  from flask.testing import FlaskClient
  class Fresh(FlaskClient):
   def open(c,*a,**kw):
    with c.application.app_context():r=super().open(*a,**kw)
    self.db.session.expire_all();return r
  self.app.test_client_class=Fresh;self.client=self.app.test_client()
  out=Path(os.environ['HTML_OUT']);out.mkdir(parents=True,exist_ok=True)
  m=self.models
  vehicle=m.Vehicle.query.filter_by(company_code='A').one()
  for username in ('admin','checker'):
   u=m.User.query.filter_by(company_code='A',username=username).one();u.office='test'
   self.db.session.add(m.Driver(company_code='A',employee_id=username,name='Test '+username,office='test',vehicles_json=json.dumps([str(vehicle.id)])))
  self.db.session.commit();rows=[]
  for shared in (False,True):
   self.app.config['PUBLIC_DEMO_SHARED_COMPANY']=shared;self.demo_active=shared
   for username in ('admin','checker'):
    self.login(username)
    if shared:
     with self.client.session_transaction() as s:s['demo_role_selected']=True
    response=self.client.get('/');self.assertEqual(response.status_code,200)
    body=response.get_data(as_text=True)
    self.assertIn('dashboard_mobile_priority.js',body);self.assertIn('id="firstUseGuide"',body)
    file=('demo' if shared else 'normal')+'-'+username+'.html';(out/file).write_text(body)
    rows.append({'file':file,'role':username,'shared':shared,'status':200})
  (out/'report.json').write_text(json.dumps(rows));print(rows)
if __name__=='__main__':
 r=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([FullHome('test_home')]));sys.exit(not r.wasSuccessful())
