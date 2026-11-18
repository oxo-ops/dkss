"""Synthetic private-file fixture only; forbid outbound network and non-SQLite."""
import os,sys,socket,unittest,json,time
from pathlib import Path
repo=Path(os.environ['PRODUCT_REPO']);sys.path[:0]=[str(repo),str(repo/'tests')]
import sqlalchemy,sqlalchemy.engine.create
original=sqlalchemy.engine.create.create_engine
def safe(url,*a,**kw):
 if not str(url).startswith('sqlite:'):raise AssertionError('nonSQLite forbidden')
 return original(url,*a,**kw)
sqlalchemy.create_engine=safe;sqlalchemy.engine.create.create_engine=safe
socket.socket.connect=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('outbound forbidden'))
socket.create_connection=socket.socket.connect
from test_attachment_preview_route import AttachmentPreviewTests
class Export(AttachmentPreviewTests):
 def test_export(self):
  out=Path(os.environ['HTML_OUT']);out.mkdir(parents=True,exist_ok=True)
  response=self.client.get(f'/pointouts/{self.record.id}');self.assertEqual(response.status_code,200)
  (out/'detail.html').write_text(response.get_data(as_text=True))
  (out/'original.jpg').write_bytes(self.original)
  rows=[]
  for width in (480,960):
   start=time.perf_counter();r=self.get(size=width);cold=time.perf_counter()-start
   start=time.perf_counter();warm=self.get(size=width);warm_s=time.perf_counter()-start
   self.assertEqual(r.mimetype,'image/webp');self.assertEqual(r.data,warm.data)
   (out/f'preview-{width}.webp').write_bytes(r.data)
   rows.append(dict(width=width,original=len(self.original),preview=len(r.data),cold=cold,warm=warm_s))
  (out/'measurements.json').write_text(json.dumps(rows))
suite=unittest.defaultTestLoader.loadTestsFromTestCase(AttachmentPreviewTests);suite.addTest(Export('test_export'))
r=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not r.wasSuccessful())
