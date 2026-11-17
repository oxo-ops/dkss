"""Requires disposable loopback PG. No skip-as-success; never loads production env."""
import os,sys,unittest
from concurrent.futures import ThreadPoolExecutor
from preflight import validate
os.environ['Q02_POSTGRES_TEST_URL']=validate(os.environ.get('Q02_POSTGRES_TEST_URL',''))
os.environ['Q02_REQUIRE_POSTGRES']='1'
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/tests'];sys.argv=sys.argv[:1]
from test_q02_postgres_mfa_concurrency import Q02PostgresMFAConcurrencyTests as Base
from dkss_app import auth_session_registry as registry

class LogoutPG(Base):
 @classmethod
 def setUpClass(cls):
  super().setUpClass()
  with cls.app.app_context():registry.prepare_schema();registry.activate()
 def authenticated(self):
  c,code=self.pending(self.companies[0]);status,identity=self.submit(c,code)
  self.assertEqual(status,302);self.assertEqual(identity,(self.companies[0],'same'))
  self.assertEqual(c.get('/api/notifications/unread-count').status_code,200)
  return c
 def test_logout_commit_rejects_16_copies_on_distinct_requests(self):
  c=self.authenticated();copies=[self.clone(c) for _ in range(16)]
  self.assertEqual(c.post('/logout').status_code,302)
  with ThreadPoolExecutor(max_workers=8) as pool:
   results=list(pool.map(lambda x:x.get('/api/notifications/unread-count').status_code,copies))
  self.assertEqual(results,[401]*16)
 def test_two_authenticated_sessions_logout_is_not_global(self):
  a=self.authenticated();b=self.authenticated();old=self.clone(a)
  self.assertEqual(a.post('/logout').status_code,302)
  self.assertEqual(old.get('/api/notifications/unread-count').status_code,401)
  self.assertEqual(b.get('/api/notifications/unread-count').status_code,200)
 def test_concurrent_logout_is_idempotent_and_no_new_token(self):
  c=self.authenticated();copies=[self.clone(c) for _ in range(4)]
  with ThreadPoolExecutor(max_workers=4) as pool:
   results=list(pool.map(lambda x:x.post('/logout').status_code,copies))
  self.assertTrue(all(code in (302,401) for code in results),results)
  self.assertEqual(c.get('/api/notifications/unread-count').status_code,401)

suite=unittest.defaultTestLoader.loadTestsFromTestCase(LogoutPG)
r=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not r.wasSuccessful())
