import json
from datetime import datetime
from unittest.mock import patch
from flask import session
from werkzeug.datastructures import MultiDict
from test_driving_reflection_identity import ReflectionIdentityTests as Base
from driving_report_reflection import validate_result
from driving_report_insights import digest
from dkss_app.models import DrivingReportReflection

class SavedPeriodTests(Base):
 def setUp(self):
  super().setUp()
  self.m.app.config.update(PUBLIC_DEMO_SHARED_COMPANY=True,PUBLIC_DEMO_COMPANY='TEST')
  self.a.operation_date='2026-11-10';self.m.db.session.commit()
  self.args=dict(scope='office',office=digest(['office','安城']),period='month',category='safety')
 def call(self,day,args=None,seed=False,demo=True,html=False,month=11):
  class Clock(datetime):
   @classmethod
   def now(cls,tz=None):
    from zoneinfo import ZoneInfo
    d=datetime(2026,month,day,12,tzinfo=ZoneInfo('Asia/Tokyo'))
    return d.astimezone(tz) if tz else d.replace(tzinfo=None)
  with self.m.app.test_request_context('/safety/driving-reports'),patch('driving_report_management.datetime',Clock),patch('driving_report_reflection.datetime',Clock),patch('driving_report_reflection.generate',side_effect=AssertionError('NO_AI')),patch.object(self.executor,'submit',side_effect=AssertionError('NO_QUEUE')):
   session.update(self.claims());session['aonagi_readonly_demo']=demo
   rows,prev,_,_,f,b,facts=self.prepare(MultiDict(args or self.args))
   if seed:
    key,doc=self.reflection_service['context'](rows,prev,f,b,facts)
    e=doc['evidence'][0];res=validate_result({'items':[{'evidence_id':e['id'],'action':e['allowed_actions'][0]}]},doc)
    self.m.db.session.add(DrivingReportReflection(company_code='TEST',cache_key=key,status='completed',result_json=json.dumps(res),created_at='2026-11-18T03:00:00+00:00',updated_at='2026-11-18T03:00:00+00:00'));self.m.db.session.commit()
   state=self.reflection_service['view'](rows,prev,f,b,facts)
   if html:
    from flask import render_template
    return render_template('driving_workspace_reflection.html',reflection=state,insights=b,driving_is_admin=True,filter_query=f)
   return state
 def test_19_and_20_keep_exact_18_snapshot_without_generation(self):
  old=self.call(18,seed=True);before=self.snapshot()
  for day in (19,20):
   state=self.call(day);self.assertEqual(state['status'],'new');self.assertNotEqual(state['key'],old['key'])
   self.assertEqual(state['snapshot']['key'],old['key']);self.assertIn('2026/11/18',state['snapshot']['period_label']);self.assertFalse(state['auto_refresh'])
   self.assertIn('period=custom',state['snapshot']['items'][0]['links'][0]['url'])
  self.assertEqual(before,self.snapshot())
 def test_regular_company_or_non_demo_cannot_use_snapshot(self):
  self.call(18,seed=True)
  self.assertNotIn('snapshot',self.call(19,demo=False))
  self.m.app.config['PUBLIC_DEMO_COMPANY']='OTHER';self.assertNotIn('snapshot',self.call(19))
 def test_new_data_or_other_office_rejects_old_result(self):
  self.call(18,seed=True)
  self.assertNotIn('snapshot',self.call(19,dict(self.args,office=digest(['office','小山']))))
  payload=json.loads(self.a.details_json);payload['distance']='999';self.a.details_json=json.dumps(payload);self.m.db.session.commit()
  self.assertNotIn('snapshot',self.call(19))
 def test_filter_and_personal_views_not_broadened(self):
  self.call(18,seed=True)
  for extra in ({'state':'followup'},{'vehicle':'1'},{'scope':'self'},{'compare':'month'},{'breakdown':'vehicles'}):
   self.assertNotIn('snapshot',self.call(19,dict(self.args,**extra)))
 def test_presentation_page_does_not_hide_saved_period(self):
  self.call(18,seed=True)
  state=self.call(20,dict(self.args,page='1',listing='people',breakdown='people'))
  self.assertIn('snapshot',state)
 def test_render_labels_actual_period_without_claiming_today_completed(self):
  self.call(18,seed=True)
  html=self.call(20,html=True)
  self.assertIn('2026/11/01〜2026/11/18の分析',html)
  self.assertIn('data-status="new"',html)
  self.assertIn('data-auto-refresh="false"',html)
  self.assertIn('この期間で作成',html)
  self.assertIn('11/18 12:00 更新',html)
  self.assertNotIn('この期間のAI分析はまだ作成されていません',html)
  self.assertIn('急加速',html)
  # Existing JS overwrites only the live status node on pending/error. The
  # period must remain attached to the still-visible saved items until reload.
  from html.parser import HTMLParser
  class Nodes(HTMLParser):
   def __init__(self):super().__init__();self.kind=None;self.text={};self.attrs={}
   def handle_starttag(self,tag,attrs):
    a=dict(attrs)
    if tag=='p':
     self.kind=next((k for k in ('data-reflection-status','data-reflection-snapshot-period') if k in a),None)
     if self.kind:self.attrs[self.kind]=a;self.text[self.kind]=''
   def handle_data(self,data):
    if self.kind:self.text[self.kind]+=data
   def handle_endtag(self,tag):
    if tag=='p':self.kind=None
  nodes=Nodes();nodes.feed(html)
  self.assertEqual(nodes.text['data-reflection-status'],'')
  self.assertIn('hidden',nodes.attrs['data-reflection-status'])
  self.assertEqual(nodes.text['data-reflection-snapshot-period'],'2026/11/01〜2026/11/18の分析')
  self.assertNotIn('hidden',nodes.attrs['data-reflection-snapshot-period'])


 def bind_personal(self):
  from dkss_app import driving_access
  from identity_fixture import identity_for
  with self.m.app.test_request_context():
   session.update(account_identity=identity_for('TEST','admin'),company_code='TEST',username='admin',role='admin')
   driving_access.assign([self.a],'admin','admin');self.m.db.session.commit()
  self.args=dict(scope='self',period='month',category='safety')
 def test_personal_saved_period_keeps_self_and_no_writes(self):
  self.bind_personal();old=self.call(18,seed=True);before=self.snapshot()
  for day in (19,20):
   state=self.call(day)
   self.assertEqual(state['snapshot']['key'],old['key'])
   self.assertIn('2026/11/18',state['snapshot']['period_label'])
   self.assertFalse(state['auto_refresh'])
   for link in state['snapshot']['items'][0]['links']:
    self.assertIn('scope=self',link['url'])
    self.assertIn('period=custom',link['url'])
  self.assertEqual(before,self.snapshot())
 def test_personal_not_reused_for_office_filter_or_new_identity(self):
  self.bind_personal();self.call(18,seed=True)
  for extra in ({'scope':'office','office':digest(['office','安城'])},
                {'vehicle':'1'},{'compare':'month'},{'period':'all'}):
   self.assertNotIn('snapshot',self.call(19,dict(self.args,**extra)))
  self.recreate_account()
  self.assertNotIn('snapshot',self.call(19))
 def test_personal_source_change_rejects_saved_period(self):
  self.bind_personal();self.call(18,seed=True)
  self.change_report()
  self.assertNotIn('snapshot',self.call(19))
 def test_personal_demo_only_and_seven_day_bound(self):
  self.bind_personal();self.call(18,seed=True)
  self.assertNotIn('snapshot',self.call(19,demo=False))
  self.assertNotIn('snapshot',self.call(26))
  self.m.app.config['PUBLIC_DEMO_COMPANY']='OTHER'
  self.assertNotIn('snapshot',self.call(19))

 def test_personal_month_boundary_never_reuses_prior_month(self):
  self.bind_personal();self.call(18,seed=True);before=self.snapshot()
  self.assertNotIn('snapshot',self.call(1,month=12))
  self.assertEqual(before,self.snapshot())
 def test_personal_role_change_does_not_reuse_admin_result(self):
  self.bind_personal();self.call(18,seed=True)
  self.m.User.query.filter_by(username='admin').one().role='user'
  self.m.db.session.commit()
  with self.client.session_transaction() as state:state['role']='user'
  self.assertNotIn('snapshot',self.call(19))
 def test_personal_revoked_assignment_cannot_reuse_saved_result(self):
  from dkss_app import driving_access
  self.bind_personal();self.call(18,seed=True)
  with self.m.app.test_request_context():
   session.update(self.claims())
   driving_access.assign([self.a],None,'admin');self.m.db.session.commit()
  before=self.snapshot()
  state=self.call(19)
  self.assertNotIn('snapshot',state)
  self.assertEqual(state['items'],[])
  self.assertEqual(before,self.snapshot())
 def test_personal_html_explicitly_labels_old_period(self):
  self.bind_personal();self.call(18,seed=True)
  html=self.call(20,html=True)
  self.assertIn('2026/11/01〜2026/11/18の分析',html)
  self.assertIn('data-status="new"',html)
  self.assertIn('data-auto-refresh="false"',html)


def load_tests(loader,tests,pattern):
 return __import__('unittest').TestSuite(SavedPeriodTests(x) for x in SavedPeriodTests.__dict__ if x.startswith('test_'))
