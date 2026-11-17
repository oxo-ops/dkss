"""Isolated actual-model service candidate, NOT installed into any app hook.
Caller policy must be fixed server configuration, never request parameters.
Uses existing model, snapshot builder, vehicle lock and judgment initialization.
"""
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import json
@dataclass(frozen=True)
class Target:
 company:str
 vehicle:int
 checklist:int
 chassis:str

def prepare_previous(target, *, now=None, fail_before_commit=False):
 from flask import current_app,session,request
 from dkss_app import models
 from dkss_app.extensions import db
 from dkss_app.public_demo_sessions import verify
 from dkss_app.checklist_common import checklist_to_dict
 from dkss_app.checklists import lock_vehicle_inspection_updates,reset_vehicle_operation_judgment
 now=now or datetime.now(timezone.utc)
 cfg=current_app.config
 if now.tzinfo is None:raise ValueError('AWARE_TIME_REQUIRED')
 if (request.path!='/demo' or request.method!='GET' or request.args
     or not cfg.get('PUBLIC_DEMO_CANDIDATE') or not cfg.get('PUBLIC_DEMO_SHARED_COMPANY')
     or cfg.get('PUBLIC_DEMO_COMPANY')!=target.company
     or session.get('aonagi_readonly_demo') is not True
     or session.get('company_code')!=target.company
     or session.get('demo_epoch')!=cfg.get('PUBLIC_DEMO_EPOCH')
     or session.get('demo_until')!=cfg.get('PUBLIC_DEMO_UNTIL')
     or not cfg.get('PUBLIC_DEMO_FROM',0)<=now.timestamp()<cfg.get('PUBLIC_DEMO_UNTIL',0)):
  return 'scope_denied'
 verify()
 role=session.get('demo_role')
 if role not in {'driver','manager'}:return 'scope_denied'
 username=cfg.get('PUBLIC_DEMO_MANAGER' if role=='manager' else 'PUBLIC_DEMO_DRIVER')
 user=models.User.query.filter_by(company_code=target.company,username=username).one_or_none()
 company=models.Company.query.filter_by(company_code=target.company,active=True).one_or_none()
 if (not company or not user or user.login_locked or user.account_identity!=session.get('account_identity')
     or session.get('username')!=username or user.role!=('admin' if role=='manager' else 'user')):return 'scope_denied'
 if cfg.get('PUBLIC_DEMO_RELEASE') and user.account_identity!=cfg.get('PUBLIC_DEMO_'+role.upper()+'_IDENTITY'):return 'scope_denied'
 master=models.Checklist.query.filter_by(id=target.checklist,company_code=target.company,active=True).one_or_none()
 if not master:return 'scope_denied'
 checklist=checklist_to_dict(master)
 if checklist.get('fixed_template_code')!='daily_inspection_truck_trailer':return 'unsupported_master'
 vehicle=models.Vehicle.query.filter_by(id=target.vehicle,company_code=target.company,chassis_number=target.chassis,deleted=False).one_or_none()
 if not vehicle:return 'scope_denied'
 try:
  if lock_vehicle_inspection_updates(target.company,vehicle_record_id=target.vehicle,checklist=checklist) is not None:
   db.session.rollback();return 'conflict'
  today=now.astimezone(ZoneInfo('Asia/Tokyo')).date();day=today-timedelta(days=1)
  rows=models.VehicleChecklistResult.query.filter_by(company_code=target.company,vehicle_record_id=target.vehicle).all()
  for row in rows:
   try:date=datetime(int(row.year),int(row.month),int(row.day)).date()
   except (ValueError,TypeError):db.session.rollback();return 'invalid_existing_date'
   if row.checklist_id==target.checklist and date==day:
    db.session.rollback();return 'preserved'
  # A normal save invalidates current/future driving decisions. Preserve all
  # existing current/future inputs instead of attempting to bypass that behavior.
  if any(datetime(int(r.year),int(r.month),int(r.day)).date()>=today for r in rows):
   db.session.rollback();return 'current_input_preserved'
  from daily_inspection_defaults import get_daily_inspection_default
  expected=get_daily_inspection_default()['items']
  actual=[x for x in checklist['items'] if str(x.get('item_code','')).startswith('daily_')]
  keys=('item_code','item_type','category','content','criteria','input_type','choices','shaded')
  if len(actual)!=len(expected) or any(any(a.get(k)!=e.get(k) for k in keys) for a,e in zip(actual,expected)):
   db.session.rollback();return 'unsupported_master'
  items=[x for x in checklist['items'] if x.get('item_type')=='check'];answers=[]
  for no,item in enumerate(items):
   if not str(item.get('item_code','')).startswith('daily_'):continue
   if item.get('input_type')!='select' or '✓' not in item.get('choices',[]):
    db.session.rollback();return 'unsupported_master'
   answers.append(dict(item_no=no,category=item.get('category',''),content=item.get('content',''),criteria=item.get('criteria',''),value='✓',comment='',files=[]))
  if len(answers)!=27:db.session.rollback();return 'unsupported_master'
  row=models.VehicleChecklistResult(company_code=target.company,vehicle_record_id=target.vehicle,checklist_id=target.checklist,year=str(day.year),month=f'{day.month:02}',day=f'{day.day:02}',checked_by='体験用サンプル',checked_by_username='',checked_date=now.astimezone(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M'),status='入力中',approved_by='',approved_by_username='',approved_date='',reject_reason='',answers_json=json.dumps(answers,ensure_ascii=False),checklist_snapshot_json=json.dumps(checklist,ensure_ascii=False),operation_judgment_json='{}')
  db.session.add(row);db.session.flush()
  reset_vehicle_operation_judgment(row,checklist)
  if getattr(row,'_pending_defect_notifications',[]):raise ValueError('UNEXPECTED_NOTIFICATION')
  db.session.add(models.ChecklistEvent(company_code=target.company,result_type='vehicle',result_id=row.id,event_type='体験用前日値準備',actor_username=session.get('username'),actor_user_id=user.id,actor_identity=user.account_identity,actor_name=session.get('name'),created_at=now.astimezone(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M:%S'),detail_json=json.dumps({'source':'demo_previous_day_sample','sample_day':day.isoformat(),'status':'入力中'},ensure_ascii=False)))
  if fail_before_commit:raise ValueError('INJECTED_BEFORE_COMMIT')
  db.session.commit();return 'created'
 except BaseException:
  db.session.rollback();raise
