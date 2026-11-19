import argparse,json,sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--preflight-only',action='store_true');p.add_argument('--port',type=int,default=51235);a=p.parse_args()
sys.path[:0]=[str(a.repo),str(a.repo/'tests')]
from test_workflow_regressions import WorkflowRegressionTests as Fixture
from dkss_app.vehicle_inspection_plans_models import get_models
Fixture.setUpClass();case=Fixture();case.setUp();m=case.m;app=m.app
case.vehicle.office='試験営業所';case.vehicle.plate_area='試験';case.vehicle.plate_number='101'
user=m.User.query.filter_by(company_code='TEST',username='admin').one();user.office='試験営業所'
Plan=get_models(m.db)[0]
current=datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m')
for mon,day in dict([(current,'18'),('2024-02','29'),('2026-02','28')]).items():
 m.db.session.add(Plan(company_code='TEST',vehicle_record_id=case.vehicle.id,kind='3month',period_key=mon,planned_month=mon,reservation_date=mon+'-'+day,status='planned',factory='試験整備',note='カレンダー試験'))
m.db.session.commit()
for mon,count in [('2026-02',1),('2026-11',12)]:
 for i in range(count):
  v=m.Vehicle(company_code='TEST',chassis_number=f'PENDING-{mon}-{i}',office='試験営業所',plate_area='品川',plate_number=str(200+i))
  m.db.session.add(v);m.db.session.flush()
  m.db.session.add(Plan(company_code='TEST',vehicle_record_id=v.id,kind='3month',period_key=mon,planned_month=mon,reservation_date=None,status='planned',factory='試験整備',note='未予約の合成試験'))
m.db.session.commit()
# Synthetic long description, without source/private data or production access.
from flask import request
synthetic_vehicle_id=case.vehicle.id
@app.after_request
def long_invoice_fixture(response):
 if request.path=='/api/vehicle/inspection-plans' and response.status_code==200:
  value=response.get_json();value.setdefault('invoice_actuals',[]).append({'vehicle_record_id':synthetic_vehicle_id,'performed_date':'2026-11-10','summary':'2026/11/10 保証対応によるワイパーゴム交換（無償）','sources':[]})
  response.set_data(json.dumps(value,ensure_ascii=False));response.content_type='application/json'
 return response
app.config['WTF_CSRF_ENABLED']=True
cookie=app.session_interface.get_signing_serializer(app).dumps(dict(company_code='TEST',username='admin',role='admin',account_identity=user.account_identity,password_changed_at=user.password_changed_at,name='試験管理者'))
a.out.mkdir(parents=True,exist_ok=True)
(a.out/'fixture.json').write_text(json.dumps({'port':a.port,'cookie':cookie}))
for mon in [current,'2024-02','2026-02']:
 response=case.client.get('/api/vehicle/inspection-plans?month='+mon)
 assert response.status_code==200,response.status_code
 assert response.json['can_edit'] and response.json['vehicles']
page=case.client.get('/vehicle/inspection-plans');assert page.status_code==200
assert b'inspection_calendar_views.css' in page.data
print('PREFLIGHT_OK',flush=True)
if a.preflight_only:
 case.tearDown();Fixture.tearDownClass();sys.exit(0)
case.ctx.pop()
from werkzeug.serving import make_server
server=make_server('127.0.0.1',a.port,app,threaded=True)
(a.out/'ready').write_text('ready')
try:server.serve_forever()
finally:server.server_close();Fixture.tearDownClass()
