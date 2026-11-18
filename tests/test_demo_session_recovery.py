import time,unittest
from unittest.mock import patch
from test_demo_inspection_compact import CompactDemoTests as Base
class RecoveryTests(Base):
 def enter_cookies(self):
  t=int(time.time());c=self.app.test_client()
  with patch('itsdangerous.timed.time.time',return_value=t):r=c.get('/demo')
  self.assertEqual(r.status_code,302)
  hint=c.get_cookie('dkss_demo_return');self.assertTrue(hint.secure);self.assertTrue(hint.http_only)
  return t,c.get_cookie(self.app.config['SESSION_COOKIE_NAME']).value,hint.value
 def client_with(self,cookie,hint):
  c=self.app.test_client();c.set_cookie(self.app.config['SESSION_COOKIE_NAME'],cookie);c.set_cookie('dkss_demo_return',hint);return c
 def test_expired_get_returns_entry_not_login(self):
  t,cookie,hint=self.enter_cookies()
  for path in ('/vehicle/checklists',f'/vehicle/karte/{self.vehicle_id}','/','/safety/driving-reports','/vehicle/inspection-plans','/safety'):
   c=self.client_with(cookie,hint)
   with patch('itsdangerous.timed.time.time',return_value=t+1801):
    r=c.get(path);self.assertEqual(r.location,'/demo');self.assertIn('no-store',r.headers['Cache-Control'])
    r=c.get('/demo');self.assertEqual(r.location,'/')
    with c.session_transaction() as s:self.assertTrue(s['aonagi_readonly_demo']);self.assertEqual(s['demo_role'],'driver')
 def test_valid_session_and_role_unchanged(self):
  self.login('admin');c=self.client
  with c.session_transaction() as s:before=dict(s)
  self.assertEqual(c.get('/vehicle/checklists',follow_redirects=True).status_code,200)
  with c.session_transaction() as s:self.assertEqual(s['demo_role'],'manager');self.assertEqual(s['public_demo_token'],before['public_demo_token'])
 def test_no_hint_or_bad_hint_cannot_recover(self):
  for hint in ('', 'tampered'):
   c=self.client_with('',hint);self.assertEqual(c.get('/vehicle/checklists').location,'/login')
 def test_no_post_or_api_replay(self):
  t,cookie,hint=self.enter_cookies()
  with patch('itsdangerous.timed.time.time',return_value=t+1801):
   for method,path in (('POST','/vehicle/checklists'),('GET','/api/unknown')):
    r=self.client_with(cookie,hint).open(path,method=method)
    self.assertNotEqual(r.location,'/demo')
 def test_normal_login_stays_normal_and_clears_hint(self):
  _,cookie,hint=self.enter_cookies();c=self.client_with('',hint)
  r=c.get('/login');self.assertEqual(r.status_code,200);self.assertIsNone(c.get_cookie('dkss_demo_return'))
  self.demo_active=False;self.login('checker')
  self.client.set_cookie('dkss_demo_return',hint)
  self.assertEqual(self.client.get('/vehicle/checklists',follow_redirects=True).status_code,200)
  with self.client.session_transaction() as s:self.assertNotIn('aonagi_readonly_demo',s)
  self.assertIsNone(self.client.get_cookie('dkss_demo_return'))
 def test_epoch_expiry_partial_mfa_are_not_reissued(self):
  t,cookie,hint=self.enter_cookies()
  c=self.client_with('',hint)
  with c.session_transaction() as s:s['mfa_pending_username']='admin'
  self.assertNotEqual(c.get('/vehicle/checklists').location,'/demo')
  old=self.app.config['PUBLIC_DEMO_EPOCH'];self.app.config['PUBLIC_DEMO_EPOCH']='changed'
  self.assertEqual(self.client_with('',hint).get('/vehicle/checklists').location,'/login')
  self.app.config['PUBLIC_DEMO_EPOCH']=old
  with patch('itsdangerous.timed.time.time',return_value=t+4000):
   self.assertEqual(self.client_with(cookie,hint).get('/vehicle/checklists').location,'/login')
 def test_revoked_demo_not_reissued(self):
  _,cookie,hint=self.enter_cookies();self.app.extensions['public_demo_active_sessions'].clear()
  c=self.client_with(cookie,hint);r=c.get('/vehicle/checklists')
  self.assertEqual(r.status_code,410);self.assertIsNone(c.get_cookie('dkss_demo_return'))
 def test_other_company_and_arbitrary_session_do_not_recover(self):
  _,_,hint=self.enter_cookies()
  for state in ({'company_code':'B','username':'other'}, {'unrelated':'value'}, {'aonagi_readonly_demo':False}):
   c=self.client_with('',hint)
   with c.session_transaction() as session:session.update(state)
   self.assertNotEqual(c.get('/vehicle/checklists').location,'/demo')
 def test_disabled_future_locked_and_inactive_fail_closed(self):
  _,_,hint=self.enter_cookies()
  for key,value in (('PUBLIC_DEMO_CANDIDATE',False),('PUBLIC_DEMO_FROM',int(time.time())+100)):
   previous=self.app.config.get(key);self.app.config[key]=value
   try:self.assertNotEqual(self.client_with('',hint).get('/vehicle/checklists').location,'/demo')
   finally:
    if previous is None:self.app.config.pop(key,None)
    else:self.app.config[key]=previous
  user=self.models.User.query.filter_by(company_code='A',username='checker').one()
  user.login_locked=True;self.db.session.commit()
  c=self.client_with('',hint);self.assertEqual(c.get('/vehicle/checklists').location,'/demo');self.assertEqual(c.get('/demo').status_code,404)
  with c.session_transaction() as session:self.assertNotIn('username',session)
  user.login_locked=False;company=self.models.Company.query.filter_by(company_code='A').one();company.active=False;self.db.session.commit()
  self.assertEqual(self.client_with('',hint).get('/demo').status_code,404)
 def test_every_allowlisted_endpoint_only_redirects_to_fixed_entry(self):
  from dkss_app.public_demo import RECOVERY_ENDPOINTS
  from flask import url_for
  _,_,hint=self.enter_cookies();checked=set()
  for rule in self.app.url_map.iter_rules():
   if rule.endpoint not in RECOVERY_ENDPOINTS:continue
   with self.app.test_request_context():path=url_for(rule.endpoint,**{key:1 for key in rule.arguments})
   response=self.client_with('',hint).get(path+'?unexpected_redirect=https://example.invalid')
   self.assertEqual(response.status_code,302);self.assertEqual(response.location,'/demo');checked.add(rule.endpoint)
  self.assertEqual(checked,RECOVERY_ENDPOINTS)

def load_tests(loader,tests,pattern):
 return unittest.TestSuite(RecoveryTests(n) for n in RecoveryTests.__dict__ if n.startswith('test_'))
