"""Synthetic-only fidelity, original preservation and authorization regression."""
from io import BytesIO
import hashlib
import json
import random
import unittest
from unittest.mock import patch

from PIL import Image, ImageFilter, ImageOps, ImageCms
import test_q12_document_display as documents
import test_workflow_regressions as workflow


class DocumentImageTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    tearDown = workflow.WorkflowRegressionTests.tearDown
    page = documents.DocumentDisplayTests.page

    def setUp(self):
        workflow.WorkflowRegressionTests.setUp(self)
        self.m.app.extensions.pop('profile_display_images', None)

    def seed(self, source=None, extension='jpg'):
        documents.DocumentDisplayTests.seed(self, extension)
        draft = self.m.db.session.get(self.m.VehicleDocumentImportDraft, 'q12-doc')
        if source is None:
            image = Image.frombytes('RGB', (1600,1000), random.Random(12).randbytes(4800000))
            out = BytesIO()
            image.filter(ImageFilter.GaussianBlur(.55)).save(out, format='JPEG', quality=88)
            source = out.getvalue()
        draft.source_file = source
        draft.source_sha256 = hashlib.sha256(source).hexdigest()
        self.m.db.session.commit()
        self.url = f'/vehicle/karte/{self.vehicle.id}/documents/q12-doc/source'
        return draft

    def expected(self, source, size):
        with Image.open(BytesIO(source)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((size, image.height), Image.Resampling.LANCZOS)
            return image.convert('RGBA')

    def test_responsive_candidates_reserve_ratio_and_retain_original(self):
        draft = self.seed()
        html = self.page('document:q12-doc')
        for text in ['width="1600" height="1000"', '?preview=384 384w', 
                     self.url+' 1600w', 'sizes="auto, 100vw"', 'loading="lazy"']:
            self.assertIn(text, html)
        self.assertNotIn('?preview=768 768w', html)
        self.assertEqual(self.client.get(self.url+'?preview=768').data, draft.source_file)
        response = self.client.get(self.url+'?download=1')
        self.assertEqual(response.data, draft.source_file)

    def test_uncropped_derivatives_are_lossless_at_their_display_dimensions(self):
        draft = self.seed()
        for size in [384]:
            response = self.client.get(self.url+f'?preview={size}')
            self.assertEqual(response.mimetype, 'image/webp')
            self.assertLess(len(response.data), len(draft.source_file))
            with Image.open(BytesIO(response.data)) as actual:
                expected = self.expected(draft.source_file, size)
                self.assertEqual(actual.size, expected.size)
                self.assertEqual(actual.convert('RGBA').tobytes(), expected.tobytes())

    def test_cache_hits_still_authorize_and_http_is_never_304(self):
        self.seed()
        import dkss_app.document_images as images
        with patch.object(images, '_encode', wraps=images._encode) as encode:
            first = self.client.get(self.url+'?preview=384')
            count = encode.call_count
            repeated = self.client.get(self.url+'?preview=384', headers={'If-None-Match':'*'})
            self.assertEqual(encode.call_count, count)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(first.data, repeated.data)
        self.assertIn('no-store', repeated.headers['Cache-Control'])
        self.assertNotIn('ETag', repeated.headers)
        self.assertEqual(repeated.headers['X-Content-Type-Options'], 'nosniff')

    def test_replacement_uses_actual_bytes_even_with_stale_stored_sha(self):
        draft = self.seed()
        first = self.client.get(self.url+'?preview=384').data
        old_sha = draft.source_sha256
        out = BytesIO(); Image.new('RGB',(1600,1000),'#d03040').save(out,format='JPEG')
        draft.source_file = out.getvalue()
        self.m.db.session.commit()
        self.assertEqual(draft.source_sha256, old_sha)
        response = self.client.get(self.url+'?preview=384')
        self.assertNotEqual(first,response.data)
        with Image.open(BytesIO(response.data)) as actual:
            self.assertEqual(actual.convert('RGBA').tobytes(),self.expected(draft.source_file,384).tobytes())

    def test_removed_association_status_and_deleted_document_reject_cached_body(self):
        draft = self.seed()
        self.assertEqual(self.client.get(self.url+'?preview=384').status_code,200)
        other=self.m.Vehicle(company_code='TEST',chassis_number='Q12-OTHER')
        self.m.db.session.add(other); self.m.db.session.commit()
        self.assertEqual(self.client.get(f'/vehicle/karte/{other.id}/documents/q12-doc/source?preview=384').status_code,404)
        original = draft.result_json
        draft.result_json=json.dumps({'records':[]}); self.m.db.session.commit()
        self.assertEqual(self.client.get(self.url+'?preview=384').status_code,404)
        draft.result_json=original; draft.status='cancelled'; self.m.db.session.commit()
        self.assertEqual(self.client.get(self.url+'?preview=384').status_code,404)
        draft.status='completed'; self.m.db.session.commit()
        self.m.db.session.delete(draft); self.m.db.session.commit()
        self.assertEqual(self.client.get(self.url+'?preview=384').status_code,404)

    def test_other_company_cannot_reuse_cached_document(self):
        self.seed(); self.client.get(self.url+'?preview=384')
        self.m.db.session.add(self.m.Company(company_code='OTHER',company_name='Synthetic other',active=True))
        user=self.m.User(company_code='OTHER',username='admin',last_name='Other',password='unused',role='admin')
        self.m.db.session.add(user); self.m.db.session.commit()
        with self.client.session_transaction() as state:
            state.update(company_code='OTHER',username='admin',account_identity=user.account_identity,
                         password_changed_at=user.password_changed_at,role='admin')
        self.assertEqual(self.client.get(self.url+'?preview=384').status_code,404)

    def test_cached_derivative_is_partitioned_for_another_authorized_person(self):
        self.seed(); self.client.get(self.url+'?preview=384')
        user=self.m.User(company_code='TEST',username='peer',last_name='Peer',password='unused',role='user')
        self.m.db.session.add(user); self.m.db.session.commit()
        with self.client.session_transaction() as state:
            state.update(username=user.username,role=user.role,account_identity=user.account_identity,
                         password_changed_at=user.password_changed_at)
        import dkss_app.document_images as images
        with patch.object(images,'_encode',wraps=images._encode) as encode:
            self.assertEqual(self.client.get(self.url+'?preview=384').status_code,200)
            self.assertGreater(encode.call_count,0)

    def test_password_revocation_and_logout_reject_cached_body(self):
        self.seed(); self.client.get(self.url+'?preview=384')
        user=self.m.User.query.filter_by(company_code='TEST',username='admin').one()
        old=user.password_changed_at; user.password_changed_at='2000-01-01 00:00:00'; self.m.db.session.commit()
        self.assertEqual(self.client.get(self.url+'?preview=384').status_code,302)
        with self.client.session_transaction() as state:
            state.update(company_code='TEST',username='admin',role='admin',account_identity=user.account_identity,
                         password_changed_at=user.password_changed_at)
        self.client.post('/logout')
        self.assertEqual(self.client.get(self.url+'?preview=384').status_code,302)

    def test_download_overrides_variant_and_damaged_images_fall_back(self):
        draft=self.seed()
        self.assertEqual(self.client.get(self.url+'?preview=123').status_code,404)
        self.assertEqual(self.client.get(self.url+'?preview=384&download=1').data,draft.source_file)
        draft.source_file=b'Synthetic damaged image'; self.m.db.session.commit()
        self.assertEqual(self.client.get(self.url+'?preview=384').data,draft.source_file)
        self.assertNotIn('srcset=',self.page('document:q12-doc').split('class="kd-image-preview"')[1].split('</div>')[0])

    def test_alpha_icc_and_exif_rotation_are_preserved_without_crop(self):
        for mode,extension in [('RGBA','png'),('RGB','jpg')]:
            with self.subTest(mode=mode):
                self.m.VehicleDocumentImportDraft.query.delete(); self.m.db.session.commit()
                image=Image.new(mode,(800,1200),(20,80,130,90) if mode=='RGBA' else (20,80,130))
                out=BytesIO();exif=Image.Exif();exif[274]=6
                icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
                image.save(out,format='PNG' if extension=='png' else 'JPEG',icc_profile=icc,exif=exif)
                draft=self.seed(out.getvalue(),extension)
                html=self.page('document:q12-doc')
                self.assertIn('width="1200" height="800"',html)
                response=self.client.get(self.url+'?preview=384')
                with Image.open(BytesIO(response.data)) as actual:
                    self.assertEqual(actual.info['icc_profile'],icc)
                    expected=self.expected(draft.source_file,384)
                    self.assertEqual(actual.size,expected.size)
                    self.assertEqual(actual.convert('RGBA').tobytes(),expected.tobytes())
