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
  from datetime import datetime,timezone
  from identity_fixture import identity_for
  today=datetime.now(timezone.utc).strftime('%Y-%m-%d')
  vehicle.office='test';vehicle.type='大型トラクター・長い車両名称の表示確認';vehicle.plate_area='品川';vehicle.plate_class='100';vehicle.plate_kana='か';vehicle.plate_number='101'
  self.db.session.add(m.Office(company_code='A',name='test'))
  self.db.session.add(m.PatrolResult(company_code='A',office='test',target_type='delivery_place',delivery_place='営業所構内',content='歩行経路の荷物を確認',category='指摘',date=today,countermeasure='通路を整理する',approval_status='承認待ち',countermeasure_due_date=today))
  titles=['タイヤの状態確認','灯火の確認','前照灯、方向指示器、車幅灯、非常点滅灯、その他','駐車ブレーキ・レバーの引きしろ（踏みしろ）','ファン・ベルトの張り具合、損傷','エンジンのかかり具合、異音・低速、加速の状態']
  def saved(v, count):
   recs=[dict(title=t,target=t,category='整備・点検',priority='中',action='左前車輪付近の異常がないか、整備担当者と一緒に確認する。',reason='日常点検記録を確認',timing='次回運行前に担当者が確認') for t in titles[:count]]
   self.db.session.add(m.VehicleKarteAnalysis(company_code='A',vehicle_record_id=v.id,status='completed',result_json=json.dumps({'analysis':{'recommendations':recs},'generated_at':today+'T00:00:00Z'},ensure_ascii=False)))
  saved(vehicle,5)
  office_vehicle=m.Vehicle(company_code='A',office='test',plate_area='尾張小牧',plate_class='100',plate_kana='か',plate_number='1234',type='大型トラクター・連結車両（長い名称）')
  self.db.session.add(office_vehicle);self.db.session.flush();saved(office_vehicle,6)
  items=[dict(item_type='check',input_type='select',category='安全分野',content=c,choices=['○','△','×']) for c in ['歩行経路を確認','整理整頓を確認','保護具を確認']]
  checklist=m.Checklist(company_code='A',name='営業所安全確認',target='安全管理',items_json=json.dumps(items,ensure_ascii=False),frequency_unit='month');self.db.session.add(checklist);self.db.session.flush()
  for username in ('admin','checker'):
   self.db.session.add(m.ChecklistResult(company_code='A',checklist_id=checklist.id,target_office='test',target_type='user',target_username=username,target_identity=m.User.query.filter_by(company_code='A',username=username).one().account_identity,checked_date=today,answers_json=json.dumps([{'value':'×'},{'value':'△'},{'value':'×'}]),checklist_snapshot_json=json.dumps({'items':items},ensure_ascii=False)))
  self.db.session.commit();rows=[]
  for shared in (False,True):
   self.app.config['PUBLIC_DEMO_SHARED_COMPANY']=shared;self.demo_active=shared
   for username in ('admin','checker'):
    self.login(username)
    if shared:
     with self.client.session_transaction() as s:s['demo_role_selected']=True
    response=self.client.get('/?__aonagi_entry=1' if shared else '/');self.assertEqual(response.status_code,200)
    body=response.get_data(as_text=True)
    self.assertIn('タイヤの状態確認',body);self.assertIn('灯火の確認',body);self.assertIn('歩行経路を確認',body);self.assertIn('dashboard-video-proposal',body);self.assertIn('office-trend-row',body);self.assertIn('歩行経路の荷物を確認',body);self.assertIn('dashboard_mobile_priority.js',body);self.assertIn('id="firstUseGuide"',body)
    file=('demo' if shared else 'normal')+'-'+username+'.html';(out/file).write_text(body)
    rows.append({'file':file,'role':username,'shared':shared,'status':200})
  (out/'report.json').write_text(json.dumps(rows));print(rows)
if __name__=='__main__':
 r=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([FullHome('test_home')]));sys.exit(not r.wasSuccessful())
