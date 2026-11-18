"""Synthetic actual GET responses. No sockets or non-SQLite database."""
import os,sys,json,socket,unittest,re
from pathlib import Path
from urllib.parse import urlencode
import sqlalchemy
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external socket forbidden'))
socket.create_connection=socket.socket.connect
_create=sqlalchemy.create_engine
def sqlite_only(url,*a,**kw):
 assert str(url).startswith('sqlite:');return _create(url,*a,**kw)
sqlalchemy.create_engine=sqlite_only
R=Path(os.environ['PRODUCT_REPO']).resolve()
sys.path[:0]=[str(R/'tests/demo_guide/fixtures'),str(R/'tests'),str(R)]
from test_demo_inspection_compact import CompactDemoTests
class Pages(CompactDemoTests):
 def test_entries(self):
  self.demo_active=False;self.login('admin','B')
  out=Path(os.environ['HTML_OUT']);out.mkdir(parents=True,exist_ok=True)
  response=self.client.get('/notifications');self.assertEqual(response.status_code,200)
  def choice(name):
   select=re.search(r'<select[^>]*name="'+name+r'"[^>]*>(.*?)</select>',response.text,re.S).group(1)
   return next(v for v in re.findall(r'<option value="([^"]*)"',select) if v)
  category,kind=choice('category'),choice('type')
  initial=dict(view='unread',category=category,type=kind,q='表示確認')
  variants=[('initial',initial),('clear',dict(initial,q='')),('missing',dict(initial,q='存在しない通知検索')),('reset',dict(view='unread'))]
  routes=[]
  for key,params in variants:
   p='/notifications?'+urlencode(params)
   result=self.client.get(p);self.assertEqual(result.status_code,200)
   self.assertIn('search_field_clear.js',result.text)
   self.assertIn('empty-text',result.text)
   (out/(key+'.html')).write_text(result.text)
   routes.append(dict(key=key,path=p))
  (out/'routes.json').write_text(json.dumps(dict(routes=routes,category=category,type=kind),ensure_ascii=False))
if __name__=='__main__':
 r=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Pages('test_entries')]));sys.exit(not r.wasSuccessful())
