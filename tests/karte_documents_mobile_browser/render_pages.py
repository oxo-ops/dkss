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
  # More than one page, synthetic originals only; retain original fixture checks above.
  from datetime import datetime,timezone
  for n in range(12):
   row=self.models.VehicleDocumentImportDraft(id=f'closed-sample-{n}',batch_id=f'closed-batch-{n}',company_code='AONAGI',created_by_username='admin',document_type='driving_report',source_filename=f'sample-{n}.pdf',source_file=b'%PDF-1.4\nsynthetic',source_sha256=str(n)*64 if n<10 else 'a'*64,status='completed',completed_at=datetime.now(timezone.utc),result_json=json.dumps({'records':[{'vehicle_record_id':self.vehicle_id}]}))
   self.db.session.add(row)
  self.db.session.commit()
  from urllib.parse import urlsplit,parse_qs,urlencode
  root=f'/vehicle/karte/{self.vehicle_id}/documents'
  pages={}
  def capture(path):
   response=self.client.get(path);self.assertEqual(response.status_code,200)
   key=f'closed-state-{len(pages)}.html';(out/key).write_text(response.text);pages[path]=key
   return response.text
  first=capture(root+'?document=closed')
  paths=[root+'?document=closed&page=2',root+'?document=closed&kind=driving_report',root+'?document=closed&q=sample',root+'?document=closed&per_page=20']
  for path in paths:
   body=capture(path);self.assertNotIn('id="document_preview"',body)
  reopened=html.unescape(re.search(r'href="([^"]+#document_preview)"\s+class="kd-filename"',first)[1]).split('#')[0]
  self.assertIn('id="document_preview"',capture(reopened))
  # Capture all generated page/category links so browser follows real rendered URLs.
  for raw in re.findall(r'href="([^"]+)"',first):
   target=html.unescape(raw).split('#')[0]
   if target.startswith(root+'?') and 'document=closed' in target and target not in pages:
    self.assertNotIn('id="document_preview"',capture(target))
  (out/'closed_states.json').write_text(json.dumps({'root':root,'pages':pages,'reopened':reopened}))

if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Pages('test_documents')]))
 sys.exit(not result.wasSuccessful())
