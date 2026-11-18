import importlib.util,unittest,hashlib
from pathlib import Path
from flask import Flask,request,session,Response
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('asset_cache',ROOT/'dkss_app/bundled_asset_cache.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class CacheTests(unittest.TestCase):
 def setUp(self):
  self.app=Flask(__name__);self.app.secret_key='isolated-only'
 def response(self,path,endpoint='static',filename='images/alseon/wordmark.webp',method='GET',status=200,cookie=False,modified=False,permanent=False):
  with self.app.test_request_context(path,method=method):
   request.url_rule=type('Rule',(),{'endpoint':endpoint})();request.view_args={'filename':filename}
   if permanent:session.permanent=True
   session.modified=modified
   r=Response(status=status);r.headers['Cache-Control']='private, no-store'
   if cookie:r.set_cookie('test','synthetic')
   return m.apply_bundled_asset_cache(r).headers['Cache-Control']
 def test_exact_version_get_head_cache(self):
  for method in ('GET','HEAD'):
   for status in (200,304):
    self.assertIn('max-age=86400',self.response('/static/logo?v='+m.PUBLIC_ASSET_VERSIONS['images/alseon/wordmark.webp'],method=method,status=status))
 def test_errors_cookie_and_mutated_sessions_never_cached(self):
  url='/static/logo?v='+m.PUBLIC_ASSET_VERSIONS['images/alseon/wordmark.webp']
  for kw in ({'status':302},{'status':403},{'status':404},{'status':500},{'cookie':True},{'modified':True},{'permanent':True},{'method':'POST'}):
   self.assertEqual(self.response(url,**kw),'private, no-store')
 def test_unknown_assets_and_dynamic_paths_never_cached(self):
  url='/static/logo?v='+m.PUBLIC_ASSET_VERSIONS['images/alseon/wordmark.webp']
  for filename in ('uploads/a.png','manuals/a.pdf','images/user.png','css/style.css','../images/alseon/wordmark.webp'):
   self.assertEqual(self.response(url,filename=filename),'private, no-store')
  for endpoint in ('uploaded_file','vehicle_karte','api','login',None):
   self.assertEqual(self.response(url,endpoint=endpoint),'private, no-store')
 def test_no_wrong_duplicate_or_extra_query_cached(self):
  h=m.PUBLIC_ASSET_VERSIONS['images/alseon/wordmark.webp']
  for query in ('','?v=old','?v='+h+'&v='+h,'?v='+h+'&token=x','?v='+h+'&__aonagi_entry=1'):
   self.assertEqual(self.response('/static/logo'+query),'private, no-store')
 def test_version_is_exact_bytes(self):
  assets=ROOT/'static'
  for path,version in m.PUBLIC_ASSET_VERSIONS.items():
   self.assertEqual(hashlib.sha256((assets/path).read_bytes()).hexdigest(),version)
if __name__=='__main__':unittest.main()
