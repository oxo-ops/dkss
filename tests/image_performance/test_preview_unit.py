"""Isolated module/Flask tests: not a substitute for production-route auth tests."""
import importlib.util,sys,types,tempfile,unittest,hashlib
from pathlib import Path
from io import BytesIO
from unittest.mock import patch
from flask import Flask,session
from PIL import Image
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[1]))
from dkss_app import profile_images as p,attachment_images as a
class Tests(unittest.TestCase):
 def setUp(self):
  self.app=Flask(__name__);self.app.secret_key='synthetic-only';self.revision=1
  out=BytesIO();Image.new('RGB',(1200,800),'red').save(out,'PNG');self.raw=out.getvalue();self.reads=0
 def read(self):self.reads+=1;return self.raw
 def get(self,q='480',user='u',company='A',source=True):
  with self.app.test_request_context('/?preview='+q):
   session.update(username=user,company_code=company,account_identity='i')
   with patch.object(p,'source_revision',return_value=((self.revision,),self.read) if source else None):
    r=a.display_preview('sample.png')
    if r:r.direct_passthrough=False;return r.get_data(),r.headers
 def test_uncropped_lossless_and_original(self):
  before=hashlib.sha256(self.raw).digest();data,h=self.get();im=Image.open(BytesIO(data));self.assertEqual(im.size,(480,320));self.assertEqual(im.getpixel((0,0)),(255,0,0));self.assertLess(len(data),len(self.raw));self.assertIn('no-store',h['Cache-Control']);self.assertEqual(hashlib.sha256(self.raw).digest(),before)
 def test_cache_rechecks_source_and_scopes(self):
  self.get();self.get();self.assertEqual(self.reads,1);self.get(user='other');self.assertEqual(self.reads,2);self.get(company='B');self.assertEqual(self.reads,3);self.revision+=1;self.get();self.assertEqual(self.reads,4);self.assertIsNone(self.get(source=False))
 def test_unsupported_missing_and_upscale(self):
  for q in ['bad','0','999','-1']:self.assertIsNone(self.get(q))
  self.assertIsNone(self.get(user=''));self.assertIsNone(self.get(company=''))
  out=BytesIO();Image.new('RGB',(100,50),'red').save(out,'PNG');self.raw=out.getvalue();self.assertIsNone(self.get())
 def test_animation_and_cmyk_preserved(self):
  for mode,fmt in [('CMYK','JPEG'),('L','PNG')]:
   out=BytesIO();Image.new(mode,(1200,800)).save(out,fmt);self.raw=out.getvalue();self.assertIsNone(self.get())
  out=BytesIO();Image.new('RGB',(600,400),'red').save(out,'GIF',save_all=True,append_images=[Image.new('RGB',(600,400),'blue')],duration=100);self.raw=out.getvalue();self.assertIsNone(self.get())
 def test_rotated_full_frame(self):
  out=BytesIO();im=Image.new('RGB',(800,1200),'blue');ex=im.getexif();ex[274]=6;im.save(out,'PNG',exif=ex);self.raw=out.getvalue();data,_=self.get();self.assertEqual(Image.open(BytesIO(data)).size,(480,320))
 def test_oversized_image_bypasses_full_decode(self):
  out=BytesIO();im=Image.new('RGB',(5000,4000),'red');im.save(out,'PNG');im.close();self.raw=out.getvalue()
  with patch.object(p,'_encode',side_effect=AssertionError('oversized decode')):
   self.assertIsNone(self.get())
if __name__=='__main__':unittest.main()
