"""Presentation-only conflict response; no ordinary identity replacement."""
import unittest
from test_demo_session_recovery import RecoveryTests
class EntryMessageTests(RecoveryTests):
 def test_normal_identity_conflict_is_japanese_and_unchanged(self):
  self.demo_active=False;self.login('checker',company='B')
  for path in ('/demo','/?__aonagi_entry=1'):
   with self.client.session_transaction() as s:before=dict(s)
   r=self.client.get(path);self.assertEqual(r.status_code,409)
   self.assertIn('通常利用を継続しています',r.get_data(as_text=True))
   self.assertIn('プライベートウィンドウ',r.get_data(as_text=True))
   with self.client.session_transaction() as s:self.assertEqual(before,dict(s))
 def test_pending_mfa_marker_remains_conflict_without_disclosure(self):
  c=self.app.test_client()
  with c.session_transaction() as s:s['mfa_pending_username']='synthetic-private-name'
  r=c.get('/?__aonagi_entry=1');self.assertEqual(r.status_code,409)
  self.assertIn('ログイン手続き中',r.get_data(as_text=True))
  self.assertNotIn('synthetic-private-name',r.get_data(as_text=True))
  with c.session_transaction() as s:self.assertEqual(s['mfa_pending_username'],'synthetic-private-name')
 def test_login_heading_scope(self):
  r=self.app.test_client().get('/login');self.assertEqual(r.status_code,200)
  self.assertIn('class="ordinary-login-heading"',r.get_data(as_text=True))

def load_tests(loader,tests,pattern):
 return unittest.TestSuite(EntryMessageTests(n) for n in EntryMessageTests.__dict__ if n.startswith('test_'))
