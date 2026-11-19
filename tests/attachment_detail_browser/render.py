"""Render actual template with synthetic SQLite records; no outbound or production env."""
import os,sys,socket,unittest,json,hashlib
from pathlib import Path
from io import BytesIO
repo=Path(os.environ['PRODUCT_REPO']);sys.path[:0]=[str(repo),str(repo/'tests')]
import sqlalchemy,sqlalchemy.engine.create
original=sqlalchemy.engine.create.create_engine
def safe(url,*a,**kw):
 if not str(url).startswith('sqlite:'):raise AssertionError('nonSQLite forbidden')
 return original(url,*a,**kw)
sqlalchemy.create_engine=safe;sqlalchemy.engine.create.create_engine=safe
socket.socket.connect=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('outbound forbidden'))
socket.create_connection=socket.socket.connect
from test_q12_attachment_thumbnails import AttachmentThumbnailTests
from PIL import Image,ImageDraw
class Export(AttachmentThumbnailTests):
 def test_export_and_original_authorization(self):
  out=Path(os.environ['HTML_OUT']);out.mkdir(parents=True,exist_ok=True)
  im=Image.new('RGB',(1200,800),'#e6f0fa');d=ImageDraw.Draw(im)
  d.rounded_rectangle((90,150,1110,650),radius=70,fill='#2868ac')
  d.rectangle((190,210,1010,430),fill='#b9d6ef');d.text((300,520),'SYNTHETIC ATTACHMENT - ORIGINAL',fill='white',stroke_width=1)
  buffer=BytesIO();im.save(buffer,format='JPEG',quality=95)
  self.original=buffer.getvalue();self.path.write_bytes(self.original)
  response=self.client.get(f'/pointouts/{self.record.id}')
  self.assertEqual(response.status_code,200)
  html=response.get_data(as_text=True)
  self.assertIn('loading="lazy" decoding="async"',html)
  self.assertIn('aria-label="画像の原本を開く"',html)
  (out/'detail.html').write_text(html,encoding='utf8')
  (out/'original.jpg').write_bytes(self.original)
  for size in (640,1280):
   display=self.client.get('/files/uploads/avatar.jpg?display='+str(size))
   self.assertEqual(display.status_code,200)
   (out/('display-'+str(size)+'.webp')).write_bytes(display.data)
   display.close()
  full=self.client.get('/files/uploads/avatar.jpg',follow_redirects=True)
  self.assertEqual(full.data,self.original);full.close()
  portrait=out/'portrait';portrait.mkdir(exist_ok=True)
  im=Image.new('RGB',(1600,2400),'#e6f0fa');d=ImageDraw.Draw(im)
  d.rectangle((100,100,1500,2300),outline='#2868ac',width=40)
  d.text((400,1200),'PORTRAIT - UNCROPPED',fill='black',stroke_width=2)
  im.save(self.path,format='JPEG',quality=95)
  (portrait/'detail.html').write_text(html,encoding='utf8')
  (portrait/'original.jpg').write_bytes(self.path.read_bytes())
  for size in (640,1280):
   display=self.client.get('/files/uploads/avatar.jpg?display='+str(size))
   self.assertEqual(display.status_code,200)
   with Image.open(BytesIO(display.data)) as picture:
    self.assertEqual(picture.size,(size,size*3//2))
   (portrait/('display-'+str(size)+'.webp')).write_bytes(display.data)
   display.close()
  self.user.role='user';self.m.db.session.commit()
  self.assertEqual(self.client.get('/files/uploads/avatar.jpg').status_code,404)
  (out/'authorization.json').write_text(json.dumps({'synthetic_only':True,'original_sha256':hashlib.sha256(self.original).hexdigest(),'authorized_original_byte_identical':True,'revoked_original_denied':True}))
suite=unittest.defaultTestLoader.loadTestsFromTestCase(AttachmentThumbnailTests)
suite.addTest(Export('test_export_and_original_authorization'))
r=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not r.wasSuccessful())
