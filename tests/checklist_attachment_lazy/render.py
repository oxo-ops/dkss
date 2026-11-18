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
  m=self.m
  items=[dict(item_type='check',input_type='select',category='安全',content='合成項目',choices=['○','△','×'])]
  checklist=m.Checklist(company_code='TEST',name='合成点検',target='安全管理',items_json=json.dumps(items,ensure_ascii=False),frequency_unit='month')
  m.db.session.add(checklist);m.db.session.flush()
  result=m.ChecklistResult(company_code='TEST',checklist_id=checklist.id,target_type='user',target_username='admin',target_identity=self.user.account_identity,checked_date='2026-11-19',answers_json=json.dumps([{'value':'○','files':['avatar.jpg']}]),checklist_snapshot_json=json.dumps({'items':items},ensure_ascii=False))
  m.db.session.add(result);m.db.session.commit()
  from flask import url_for
  with self.m.app.test_request_context():
   detail_url=url_for('checklist_result_detail',result_index=result.id)
   edit_url=url_for('edit_checklist_result',result_index=result.id)
  response=self.client.get(detail_url)
  self.assertEqual(response.status_code,200)
  html=response.get_data(as_text=True)
  self.assertIn('loading="lazy" decoding="async"',html)
  self.assertIn('checklist-result-attachment-image',html)
  (out/'detail.html').write_text(html,encoding='utf8')
  edited=self.client.get(edit_url);self.assertEqual(edited.status_code,200)
  self.assertIn('class="saved-file-preview-image" loading="lazy" decoding="async"',edited.get_data(as_text=True))
  (out/'edit.html').write_text(edited.get_data(as_text=True),encoding='utf8')
  (out/'original.jpg').write_bytes(self.original)
  full=self.client.get('/files/uploads/avatar.jpg',follow_redirects=True)
  self.assertEqual(full.data,self.original);full.close()
  self.user.role='user';self.m.db.session.commit()
  self.assertEqual(self.client.get('/files/uploads/avatar.jpg').status_code,404)
  (out/'authorization.json').write_text(json.dumps({'synthetic_only':True,'original_sha256':hashlib.sha256(self.original).hexdigest(),'authorized_original_byte_identical':True,'revoked_original_denied':True}))
suite=unittest.defaultTestLoader.loadTestsFromTestCase(AttachmentThumbnailTests)
suite.addTest(Export('test_export_and_original_authorization'))
r=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not r.wasSuccessful())
