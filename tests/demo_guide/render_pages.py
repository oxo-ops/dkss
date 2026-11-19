"""Synthetic SQLite real-route guide fixture. Never connect to deployed resources."""
import os,sys,json,unittest
from pathlib import Path
D=Path(__file__).resolve().parent
REPO=Path(os.environ['PRODUCT_REPO']).resolve()
sys.path[:0]=[str(D/'fixtures'),str(REPO),str(REPO/'tests')]
from test_demo_inspection_compact import CompactDemoTests
from flask import url_for
from jinja2 import ChoiceLoader,FileSystemLoader
class Pages(CompactDemoTests):
 def test_pages(self):
  from flask.testing import FlaskClient
  class Fresh(FlaskClient):
   def open(c,*a,**kw):
    with c.application.app_context():r=super().open(*a,**kw)
    self.db.session.expire_all();return r
  self.app.test_client_class=Fresh;self.client=self.app.test_client();self.enter()
  overlay=os.environ.get('GUIDE_PRODUCT')
  if overlay:self.app.jinja_loader=ChoiceLoader([FileSystemLoader(Path(overlay)/'templates'),self.app.jinja_loader]);self.app.jinja_env.cache.clear()
  m=self.models;db=self.db
  user=m.User.query.filter_by(company_code='AONAGI',username='admin').one()
  driver=m.Driver(company_code='AONAGI',employee_id='admin',name='Test admin',vehicles_json=json.dumps([str(self.vehicle_id)]),office='test');db.session.add(driver)
  point=m.PatrolResult(company_code='AONAGI',created_by_username='admin',created_by_user_id=user.id,created_by_identity=user.account_identity,created_by_name='Test admin',date='2026-10-23',office='test',category='安全',target_type='user',target_user='Test admin',target_username='admin',target_user_id=user.id,target_identity=user.account_identity,content='通路の荷物を確認する',approval_status='承認待ち',countermeasure='通路の荷物を整理する');db.session.add(point)
  notice=m.Notification(company_code='AONAGI',target_user='Test admin',target_username='admin',owner_identity=user.account_identity,read=True,title='確認する記録',message='通路の状況を確認してください',created_at='2026-10-23 10:00:00');db.session.add(notice)
  safety=m.Checklist(company_code='AONAGI',name='営業所安全確認',target='安全管理',display_type='日',items_json=json.dumps([{'name':'通路の状況','item_type':'check'}],ensure_ascii=False));db.session.add(safety)
  draft=m.VehicleDocumentImportDraft(id='synthetic-guide-draft',batch_id='synthetic-guide-batch',company_code='AONAGI',created_by_username='admin',owner_identity=user.account_identity,document_type='driving_report',source_filename='sample.pdf',source_file=b'%PDF-1.4\nsynthetic',source_sha256='0'*64,preview_json='{}');db.session.add(draft);db.session.flush()
  report=m.VehicleDrivingReportRecord(company_code='AONAGI',vehicle_record_id=self.vehicle_id,operation_date='2026-10-23',content='運行の確認記録',details_json='{}',source_draft_id=draft.id,source_record_index=0,created_by_username='admin');db.session.add(report);db.session.commit()
  ids={'pointout_detail':point.id,'edit_pointout':point.id,'notification_detail':notice.id,'safety_checklist_results':safety.id,'driving_report_detail':report.id}
  db.session.add(m.Checklist(company_code='AONAGI',name='防災確認',target='安全管理',display_type='日',items_json='[]'))
  user.office='test'
  from dkss_app.vehicle_inspection_plans_models import get_models
  db.session.add(get_models(db)[2](company_code='AONAGI',vehicle_record_id=self.vehicle_id,kind='3month',performed_date='2026-10-23',created_by='admin',created_at='2026-10-23T10:00:00'))
  db.session.add(m.VehicleMaintenanceRecord(company_code='AONAGI',vehicle_record_id=self.vehicle_id,category='整備',status='実施済み',entry_date='2026-11-18',completion_date='2026-11-18',content='タイヤの状態確認',total_cost=1000,created_by_username='admin'))
  db.session.add(m.VehicleKarteAnalysis(company_code='AONAGI',vehicle_record_id=self.vehicle_id,status='completed',result_json=json.dumps({'analysis':{'recommendations':[{'proposal_id':'synthetic-1','title':'タイヤの状態確認','target':'タイヤ','category':'整備・点検','priority':'中','action':'次の運行前に確認する','reason':'点検記録に確認待ちがある','timing':'次の運行前'}]},'generated_at':'2026-11-18T00:00:00Z'},ensure_ascii=False)))
  from datetime import datetime,timezone
  db.session.add(m.VehicleDocumentImportDraft(id='synthetic-completed',batch_id='synthetic-completed-batch',company_code='AONAGI',created_by_username='admin',owner_identity=user.account_identity,document_type='driving_report',source_filename='completed.pdf',source_file=b'%PDF-1.4\nsynthetic',source_sha256='1'*64,preview_json='{}',status='completed',completed_at=datetime.now(timezone.utc),result_json=json.dumps({'records':[{'vehicle_record_id':self.vehicle_id,'record_id':report.id}]})))
  db.session.commit()
  self.login('admin')
  with self.client.session_transaction() as s:s['demo_role_selected']=True
  out=Path(os.environ.get('HTML_OUT',D/'html'));out.mkdir(parents=True,exist_ok=True)
  for previous in out.glob('*.html'):previous.unlink()
  endpoints=['dashboard','pointouts','new_pointout','edit_pointout','pointout_detail','driving_reports','driving_report_detail','vehicle_karte','vehicle_karte_history','vehicle_karte_inspections','vehicle_karte_maintenance','vehicle_karte_parts','vehicle_karte_costs','vehicle_karte_documents','vehicle_karte_analysis','vehicle_inspection_plans','notifications','notification_detail','safety_checklists','safety_checklist_results','vehicle_checklist_results','vehicle_data_import','document_import_job','document_import_kind','vehicle_document_import_preview']
  rows=[]
  for name in endpoints:
   rule=next(r for r in self.app.url_map.iter_rules() if r.endpoint==name and 'GET' in r.methods)
   args={k:({'vehicle_record_id':self.vehicle_id,'batch_id':draft.batch_id,'draft_id':draft.id}.get(k,ids.get(name,self.app.config['PUBLIC_DEMO_CHECKLIST_ID']))) for k in rule.arguments if k not in (rule.defaults or {})}
   with self.app.test_request_context():p=url_for(name,**args)
   if name=='dashboard':p+='?__aonagi_entry=1'
   r=self.client.get(p);body=r.get_data(as_text=True)
   rows.append({'endpoint':name,'path':p,'status':r.status_code,'guide':'id="firstUseGuide"' in body,'location':r.headers.get('Location')})
   if name=='notification_detail':
    self.assertEqual(r.status_code,302)
    panel=self.client.get(p+'?panel=1');self.assertEqual(panel.status_code,200);self.assertIn('html',panel.json);(out/'notification-panel.json').write_text(json.dumps(panel.json,ensure_ascii=False))
   elif name=='safety_checklists' and r.status_code==302:
    followed=self.client.get(r.location);self.assertEqual(followed.status_code,200);self.assertIn('id="firstUseGuide"',followed.get_data(as_text=True))
   elif r.status_code==200:
    self.assertIn('id="firstUseGuide"',body);(out/(name+'.html')).write_text(body)
   else:self.fail((name,r.status_code))
  # State-specific real HTML; no business writes or deliveries. Seed is disposable SQLite.
  state_dir=out/'inspection-states';state_dir.mkdir(exist_ok=True)
  state_row=m.VehicleChecklistResult(company_code='AONAGI',checklist_id=self.app.config['PUBLIC_DEMO_CHECKLIST_ID'],vehicle_record_id=self.vehicle_id,year='2026',month='10',day='23',status='入力中',answers_json='[]',checked_by='Test checker',checked_by_username='checker',checked_date='2026-10-23 10:00:00',checklist_snapshot_json='{}');db.session.add(state_row);db.session.commit()
  state_rows=[]
  for role,username in [('driver','checker'),('manager','admin')]:
   self.login(username)
   with self.client.session_transaction() as sess:sess['demo_role_selected']=True
   approval=self.client.get('/api/approval-candidates');self.assertEqual(approval.status_code,200);self.assertIsInstance(approval.json,dict)
   (state_dir/f'{role}-approval-candidates.json').write_text(json.dumps(approval.json,ensure_ascii=False))
   unselected_path=f'/vehicle/checklists/{self.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}'
   unselected=self.client.get(unselected_path);self.assertEqual(unselected.status_code,200)
   from html.parser import HTMLParser
   class Inputs(HTMLParser):
    def handle_starttag(parser,tag,attrs):
     attrs=dict(attrs)
     if attrs.get('id')=='vehicle_record_id':parser.selected=attrs.get('value','')
   parser=Inputs();parser.selected=None;parser.feed(unselected.text);self.assertIn(parser.selected,('', 'None'))
   self.assertIn('id="vehicle_search"',unselected.text)
   filename=f'{role}-unselected.html';(state_dir/filename).write_text(unselected.text)
   state_rows.append({'role':role,'status':'未選択','code':'unselected','file':filename,'path':unselected_path,'editable':False})
   for status,code in [('入力中','input'),('差し戻し','returned'),('承認待ち','waiting'),('承認済み','approved'),('点検完了','complete')]:
    state_row.status=status;db.session.commit()
    path=f'/vehicle/checklists/{self.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}?vehicle_record_id={self.vehicle_id}&year=2026&month=10&day=23&active_day=23'
    response=self.client.get(path);self.assertEqual(response.status_code,200)
    filename=f'{role}-{code}.html';(state_dir/filename).write_text(response.text)
    state_rows.append({'role':role,'status':status,'code':code,'file':filename,'path':path,'editable':code in ('input','returned')})
  (state_dir/'states.json').write_text(json.dumps(state_rows,ensure_ascii=False,indent=2))
  (out/'routes.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows,ensure_ascii=False))
if __name__=='__main__':
 r=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Pages('test_pages')]));sys.exit(not r.wasSuccessful())
