import unittest
from test_demo_inspection_compact import CompactDemoTests as Base
from dkss_app.bundled_asset_cache import PUBLIC_ASSET_VERSIONS
class CacheRouteTests(Base):
 def test_real_demo_public_logo_reused_without_private_html(self):
  self.login('admin')
  for path,h in PUBLIC_ASSET_VERSIONS.items():
   r=self.client.get('/static/'+path+'?v='+h)
   self.assertEqual(r.status_code,200)
   self.assertEqual(r.headers['Cache-Control'],'private, max-age=86400, immutable')
   self.assertNotIn('Set-Cookie',r.headers)
   r=self.client.get('/static/'+path+'?v=old')
   self.assertIn('no-store',r.headers['Cache-Control'])
  r=self.client.get('/')
  self.assertEqual(r.status_code,200);self.assertIn('no-store',r.headers['Cache-Control'])
 def test_expired_session_not_bypassed_on_asset_fetch(self):
  self.login('admin')
  self.app.extensions['public_demo_active_sessions'].clear()
  path,h=next(iter(PUBLIC_ASSET_VERSIONS.items()))
  r=self.client.get('/static/'+path+'?v='+h)
  self.assertEqual(r.status_code,410);self.assertIn('no-store',r.headers['Cache-Control'])

def load_tests(loader, tests, pattern):
 return unittest.TestSuite(CacheRouteTests(name) for name in ("test_real_demo_public_logo_reused_without_private_html", "test_expired_session_not_bypassed_on_asset_fetch"))
