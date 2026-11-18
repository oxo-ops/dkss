import json
import unittest
from flask import template_rendered
from identity_fixture import identity_for
import test_driving_admin_self as fixture

class OfficeSummaryTests(unittest.TestCase):
 setUpClass=classmethod(fixture.AdminSelfTests.setUpClass.__func__)
 tearDownClass=classmethod(fixture.AdminSelfTests.tearDownClass.__func__)
 tearDown=fixture.AdminSelfTests.tearDown
 save=fixture.AdminSelfTests.save
 bind=fixture.AdminSelfTests.bind
 render=fixture.AdminSelfTests.render
 def setUp(self):
  fixture.AdminSelfTests.setUp(self);self.other.office='安城';self.m.db.session.commit()
  with self.client.session_transaction() as state:state.update(account_identity=identity_for('TEST','two',app=self.m.app),username='two',role='user',password_changed_at='stamp')
 def office(self,path='/safety/driving-reports/office-summary'):
  got=[]
  def capture(sender,template,context,**kw):got.append(context)
  template_rendered.connect(capture,self.m.app)
  try:r=self.client.get(path)
  finally:template_rendered.disconnect(capture,self.m.app)
  return r,got[-1] if got else {}
 def test_office_totals_no_personal_sources(self):
  before=[(x.id,x.details_json) for x in self.m.VehicleDrivingReportRecord.query.all()]
  r,c=self.office();self.assertEqual(r.status_code,200)
  summary=c['summary'];self.assertTrue(summary['available']);self.assertEqual(sum(x['count'] for x in summary['months']),3)
  text=r.get_data(as_text=True)
  for forbidden in ['他人の運行秘密','管理者本人の運行','兼務者の運行','reader_username','data-reflection-form','export.csv','export.pdf'] :self.assertNotIn(forbidden,text)
  self.assertEqual(before,[(x.id,x.details_json) for x in self.m.VehicleDrivingReportRecord.query.all()])
  self.assertEqual(set(summary),{'available','months','metrics'})
 def test_office_boundary_and_empty_office(self):
  data=json.loads(self.support.details_json);data['driver_office']='別営業所';self.support.details_json=json.dumps(data);self.m.db.session.commit()
  r,c=self.office();self.assertEqual(sum(x['count'] for x in c['summary']['months']),2)
  self.m.db.session.add(self.m.Company(company_code='OTHER',company_name='Isolated other',vehicle_limit=10,active=True));self.m.db.session.commit()
  data['driver_office']='安城';self.support.details_json=json.dumps(data);self.support.company_code='OTHER';self.m.db.session.commit();r,c=self.office();self.assertEqual(sum(x['count'] for x in c['summary']['months']),2)
  self.other.office='';self.m.db.session.commit();r,c=self.office();self.assertEqual(r.status_code,200);self.assertFalse(c['summary']['available']);self.assertEqual(c['summary']['months'],[])
 def test_query_post_and_direct_detail_denied(self):
  for query in ['office=別営業所','company=OTHER','driver=admin','start=2026-10-01','vehicle=1','format=json']:
   self.assertEqual(self.office('/safety/driving-reports/office-summary?'+query)[0].status_code,400)
  self.assertIn(self.client.post('/safety/driving-reports/office-summary').status_code,[400,405])
  self.assertEqual(self.client.get('/safety/driving-reports/'+str(self.own.id)).status_code,404)
  r=self.client.get('/safety/driving-reports/export.csv?scope=office&period=all');self.assertEqual(r.status_code,200);self.assertNotIn('管理者本人の運行',r.get_data(as_text=True));self.assertIn('他人の運行秘密',r.get_data(as_text=True))

 def test_compatible_rate_only_and_no_source_strings(self):
  from datetime import datetime
  from zoneinfo import ZoneInfo
  for row in [self.own,self.theirs,self.support]:row.operation_date=datetime.now(ZoneInfo('Asia/Tokyo')).date().isoformat()
  self.m.db.session.commit();r,c=self.office();metrics=c['summary']['metrics'];self.assertEqual(len(metrics),1);self.assertEqual(metrics[0]['name'],'急加速');self.assertEqual(metrics[0]['unit'],'回/100km')
  self.assertEqual(set(metrics[0]),{'name','value','unit'})
  data=json.loads(self.support.details_json);data['report_items'][0]['definition']='別の判定定義';self.support.details_json=json.dumps(data);self.m.db.session.commit()
  r,c=self.office();self.assertEqual(c['summary']['metrics'],[])
 def test_direct_ai_office_scope_stays_personal(self):
  from unittest.mock import patch
  response,context=self.render('/safety/driving-reports?scope=office&period=all')
  self.assertEqual(context['filters']['scope'],'self')
  executor=self.m.app.extensions['driving_reflection_executor']
  form=dict(context['filters'],scope='office',input_key=context['reflection']['key'])
  with patch.dict('os.environ',{'OPENAI_API_KEY':'isolated-only'}),patch.object(executor,'submit') as submit:
   response=self.client.post('/safety/driving-reports/reflection',data=form)
   self.assertEqual(response.status_code,202)
   document=submit.call_args.args[-1]
   self.assertEqual(document['role'],'self')
   self.assertNotIn('管理者本人の運行',json.dumps(document,ensure_ascii=False))
   self.assertNotIn('兼務者の運行',json.dumps(document,ensure_ascii=False))
