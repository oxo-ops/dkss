import unittest,json,time
from unittest.mock import patch
from test_demo_share_entry import ShareEntryTests as Base
class SeedShare(Base):
 def setUp(self):
  super().setUp()
  from dkss_app.demo_previous_day import Target,prepare_previous
  m=self.models.Checklist.query.filter_by(company_code='A').one();v=self.models.Vehicle.query.filter_by(company_code='A').one()
  self.target=Target('A',v.id,m.id,v.chassis_number)
  self.binding=patch('dkss_app.demo_previous_day.prepare_entry',side_effect=lambda:prepare_previous(self.target,now=getattr(self,"clock",None)));self.called=self.binding.start();self.addCleanup(self.binding.stop)
 def rows(self):return [(r.id,r.answers_json,r.status,r.operation_judgment_json) for r in self.models.VehicleChecklistResult.query.all()]
 def test_issue_then_verify_then_seed_and_second_browser_preserves(self):
  a=self.app.test_client();b=self.app.test_client()
  self.assertEqual(a.get(self.path).status_code,302);self.called.assert_not_called();self.assertEqual(self.rows(),[])
  self.assertEqual(a.get(self.path).status_code,200);self.assertEqual(len(self.rows()),1);before=self.rows()
  self.assertEqual(b.get(self.path).status_code,302);self.assertEqual(b.get(self.path).status_code,200);self.assertEqual(self.rows(),before)
  self.assertEqual(self.models.Notification.query.count(),0)
 def test_revoked_between_issue_and_second_get_never_creates(self):
  c=self.app.test_client();c.get(self.path);self.app.extensions['public_demo_active_sessions'].clear()
  self.assertEqual(c.get(self.path).status_code,410);self.called.assert_not_called();self.assertEqual(self.rows(),[])
 def test_normal_mfa_and_bad_query_never_create(self):
  for key in ('mfa_pending_username','username'):
   c=self.app.test_client()
   with c.session_transaction() as s:s[key]='admin'
   self.assertEqual(c.get(self.path).status_code,409)
  c=self.app.test_client();self.assertEqual(c.get(self.path+'&role=manager').status_code,400)
  self.called.assert_not_called();self.assertEqual(self.rows(),[])
 def test_other_vehicle_or_invalid_date_never_create(self):
  other=self.models.Vehicle.query.filter_by(company_code='B').one()
  from urllib.parse import urlsplit,parse_qsl,urlencode
  u=urlsplit(self.path);q=dict(parse_qsl(u.query));q['month']='13';invalid_month=u.path+'?'+urlencode(q)
  for path in (self.path.replace('vehicle_record_id='+str(self.vehicle_id),'vehicle_record_id='+str(other.id)),invalid_month):
   c=self.app.test_client();self.assertEqual(c.get(path).status_code,302);c.get(path)
   self.assertEqual(self.rows(),[])
 def test_existing_partial_result_preserved(self):
  c=self.app.test_client();c.get(self.path);c.get(self.path)
  row=self.models.VehicleChecklistResult.query.one();row.answers_json='[{"item_no":0,"value":"×"}]';self.db.session.commit();before=self.rows()
  self.assertEqual(c.get(self.path).status_code,200);self.assertEqual(self.rows(),before)
 def test_plain_entry_and_shared_home_do_not_double_create(self):
  c=self.app.test_client();self.assertEqual(c.get('/demo').status_code,302);before=self.rows();self.assertEqual(len(before),1)
  self.assertEqual(c.get('/?__aonagi_entry=1').status_code,200);self.assertEqual(self.rows(),before)
 def test_expired_existing_demo_never_creates(self):
  c=self.app.test_client();c.get(self.path);self.app.config['PUBLIC_DEMO_UNTIL']=int(time.time())-1
  self.addCleanup(self.app.config.update,PUBLIC_DEMO_UNTIL=int(time.time())+3600)
  self.assertEqual(c.get(self.path).status_code,410);self.called.assert_not_called();self.assertEqual(self.rows(),[])
def load_tests(loader,tests,pattern):return unittest.TestSuite(SeedShare(x) for x in SeedShare.__dict__ if x.startswith('test_'))
