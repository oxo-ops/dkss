"""Isolated local storage diagnostic; no production credentials/data/notifications."""
import json
from io import BytesIO
from unittest.mock import patch
from werkzeug.datastructures import FileStorage
from flask import session
from dkss_app import storage, profile_images
from test_q12_attachment_thumbnails import AttachmentThumbnailTests
from test_q12_profile_images import picture

class PostSaveDiagnostic(AttachmentThumbnailTests):
    def test_completed_upload_immediately_readable_without_sleep(self):
        data=picture('blue',size=(1672,941),format='PNG')
        with self.client.session_transaction() as state: claims=dict(state)
        with self.m.app.test_request_context('/pointouts/new',method='POST'):
            session.update(claims)
            with patch('dkss_app.audit.add_audit_log'):
                name=storage.save_uploaded_file(FileStorage(stream=BytesIO(data),filename='new.png'))
        self.record.files_json=json.dumps([name]);self.m.db.session.commit()
        for query in ('?thumb=480','?display=1280',''):
            r=self.client.get('/files/uploads/'+name+query,follow_redirects=True)
            self.assertEqual(r.status_code,200)
            self.assertTrue(r.mimetype.startswith('image/'))
            if not query:self.assertEqual(r.data,data)
            r.close()
    def test_transient_decode_failure_does_not_poison_next_request(self):
        with patch.object(profile_images,'_encode',side_effect=OSError('synthetic transient')):
            r=self.client.get('/files/uploads/avatar.jpg?display=1280',follow_redirects=True)
            self.assertEqual(r.status_code,200);self.assertEqual(r.data,self.original);r.close()
        r=self.client.get('/files/uploads/avatar.jpg?display=1280')
        self.assertEqual((r.status_code,r.mimetype),(200,'image/webp'));r.close()

    def test_s3_transient_response_matrix(self):
        from botocore.exceptions import ClientError
        original=self.original
        class FakeS3:
            mode='ok'; calls=[]
            def head_object(fake,**kw):
                fake.calls.append('HEAD')
                if fake.mode in ('head500','all404','denied'):
                    code={'head500':'500','all404':'NoSuchKey','denied':'AccessDenied'}[fake.mode]
                    raise ClientError({'Error':{'Code':code}},'HeadObject')
                return {'ETag':'synthetic-etag','ContentLength':len(original)}
            def get_object(fake,**kw):
                fake.calls.append('GET')
                if fake.mode in ('all404','denied') or fake.mode=='get_once' and fake.calls.count('GET')==1:
                    code='AccessDenied' if fake.mode=='denied' else 'NoSuchKey'
                    raise ClientError({'Error':{'Code':code}},'GetObject')
                return {'Body':BytesIO(original),'ContentType':'image/jpeg'}
        fake=FakeS3();old=self.m.app.config['S3_BUCKET_NAME']
        self.m.app.extensions['dkss']['s3_client']=fake;self.m.app.config['S3_BUCKET_NAME']='isolated-fake-only'
        try:
            for mode,expected in [('ok',200),('head500',200),('get_once',200),('all404',404),('denied',404)]:
                with self.subTest(mode=mode):
                    profile_images.forget('TEST','avatar.jpg');fake.mode=mode;fake.calls=[]
                    r=self.client.get('/files/uploads/avatar.jpg?display=1280')
                    self.assertEqual(r.status_code,expected);r.close()
                    fake.mode='ok';fake.calls=[]
                    recovered=self.client.get('/files/uploads/avatar.jpg?display=1280')
                    self.assertEqual((recovered.status_code,recovered.mimetype),(200,'image/webp'));recovered.close()
        finally:
            self.m.app.extensions['dkss']['s3_client']=None;self.m.app.config['S3_BUCKET_NAME']=old
