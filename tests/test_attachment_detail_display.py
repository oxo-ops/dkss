"""Detail derivatives preserve uncropped content and all original access checks."""
from io import BytesIO
from PIL import Image
from unittest.mock import patch
import hashlib
from dkss_app import profile_images
from test_q12_attachment_thumbnails import AttachmentThumbnailTests

class AttachmentDetailTests(AttachmentThumbnailTests):
    def get(self,name='avatar.jpg',size=640,**kw):
        r=self.client.get(f'/files/uploads/{name}?display={size}',**kw)
        r.get_data();r.close();return r

    def test_display_crop_original_download_and_no_store(self):
        before=hashlib.sha256(self.original).hexdigest()
        r=self.get()
        self.assertEqual((r.status_code,r.mimetype),(200,'image/webp'))
        with Image.open(BytesIO(r.data)) as im:
            self.assertEqual(im.size,(640,427))
        with patch.object(profile_images,'source_revision',side_effect=AssertionError('original path')):
            original=self.client.get('/files/uploads/avatar.jpg',follow_redirects=True)
            self.assertEqual(original.data,self.original);original.close()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)
        self.assertIn('no-store',r.headers['Cache-Control'])

    def test_source_update_and_sizes_are_separate(self):
        from test_q12_profile_images import picture
        first=self.get().data
        self.path.write_bytes(picture('blue'))
        self.assertNotEqual(self.get().data,first)
        for size in (640,1280):
            with Image.open(BytesIO(self.get(size=size).data)) as im:
                self.assertEqual(im.size,(640,427) if size==640 else (1200,800))

    def test_invalid_size_keeps_original(self):
        self.assertEqual(self.get(size=999,follow_redirects=True).data,self.original)
