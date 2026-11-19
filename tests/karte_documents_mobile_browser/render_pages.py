"""Disposable, authenticated route render. No deployed service/data."""
import os,sys,importlib.util,json,re,html,unittest,socket
from pathlib import Path
import sqlalchemy
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external socket forbidden'))
socket.create_connection=socket.socket.connect
engine=sqlalchemy.create_engine
def sqlite_only(url,*a,**k):
 assert str(url).startswith('sqlite:'), 'SQLite fixture only'
 return engine(url,*a,**k)
sqlalchemy.create_engine=sqlite_only
R=Path(os.environ['PRODUCT_REPO']).resolve();D=R/'tests/demo_guide'
sys.path[:0]=[str(D),str(D/'fixtures'),str(R),str(R/'tests')]
spec=importlib.util.spec_from_file_location('document_base',D/'render_pages.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
class Pages(base.Pages):
 def test_documents(self):
  super().test_pages()
  out=Path(os.environ['HTML_OUT'])
  source=(out/'vehicle_karte_documents.html').read_text()
  match=re.search(r'href="([^"]+#document_preview)"\s+class="kd-filename"',source)
  self.assertIsNotNone(match)
  url=html.unescape(match[1]);r=self.client.get(url.split('#')[0])
  self.assertEqual(r.status_code,200)
  self.assertIn('id="document_preview"',r.text)
  (out/'document_selected.html').write_text(r.text)
  (out/'document_selected.json').write_text(json.dumps({'url':url}))
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Pages('test_documents')]))
 sys.exit(not result.wasSuccessful())
