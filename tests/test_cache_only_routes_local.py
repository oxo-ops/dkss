"""Local synthetic QA only, not a published product candidate."""
import unittest,hashlib,json
from unittest.mock import patch
from flask import session
from test_q12_document_images import DocumentImageTests
import test_q12_document_display as display
class CacheOnlyRoutes(DocumentImageTests):
 def seed(self,*a,**kw):
  draft=super().seed(*a,**kw)
  from dkss_app.profile_images import cache,_encode
  user=self.m.User.query.filter_by(company_code='TEST',username='admin').one()
  key=('TEST','document:q12-doc','admin',user.account_identity,(self.vehicle.id,hashlib.sha256(draft.source_file).hexdigest()),480,'lossless-width')
  cache().put(key,_encode(lambda:draft.source_file,480,False,lossless=True,width_only=True))
  return draft
 def test_cold_no_encoder_and_original_response(self):
  draft=self.seed();self.m.app.extensions.pop('profile_display_images',None)
  import dkss_app.document_images as images
  with patch.object(images,'_encode',side_effect=AssertionError('decode prohibited')):
   html=self.page('document:q12-doc');response=self.client.get(self.url+'?preview=480')
  self.assertEqual(response.data,draft.source_file);self.assertEqual(response.mimetype,'image/jpeg');self.assertIn('no-store',response.headers['Cache-Control']);self.assertNotIn('?preview=480',html)
 def test_warm_bytes_survive_and_original_download(self):
  draft=self.seed();response=self.client.get(self.url+'?preview=480');self.assertEqual(response.mimetype,'image/webp');self.assertEqual(self.client.get(self.url+'?download=1').data,draft.source_file)
 def test_html_selection_pdf_close_and_write_functions_unchanged(self):
  draft=self.seed();self.m.app.extensions.pop('profile_display_images',None)
  self.assertIn('kd-image-preview',self.page('document:q12-doc'));self.assertNotIn('kd-image-preview',self.page('closed'))
  response=self.client.post(f'/vehicle/karte/{self.vehicle.id}/note',data={'version':0,'content':'synthetic note'})
  self.assertEqual(response.status_code,302)
  self.assertIn('synthetic note',self.client.get(f'/vehicle/karte/{self.vehicle.id}').get_data(as_text=True))
selected=['test_cold_no_encoder_and_original_response','test_warm_bytes_survive_and_original_download','test_html_selection_pdf_close_and_write_functions_unchanged','test_removed_association_status_and_deleted_document_reject_cached_body','test_other_company_cannot_reuse_cached_document','test_password_revocation_and_logout_reject_cached_body','test_cache_hits_still_authorize_and_http_is_never_304','test_download_overrides_variant_and_damaged_images_fall_back']
def load_tests(loader,tests,pattern):return unittest.TestSuite(CacheOnlyRoutes(n) for n in selected)
