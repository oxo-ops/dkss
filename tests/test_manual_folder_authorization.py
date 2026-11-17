import unittest
from pathlib import Path
import test_q12_profile_images as profile_fixture
from botocore.exceptions import ClientError
class ManualTenant(profile_fixture.ProfileImageDisplayTests):
 def setUp(self):
  super().setUp()
  self.m.db.session.add(self.m.Company(company_code='OTHER',company_name='Synthetic',active=True))
  self.m.db.session.add(self.m.User(company_code='OTHER',username='admin',password='unused',role='admin',last_name='Synthetic',password_changed_at=self.user.password_changed_at))
  for company in ('TEST','OTHER'):self.m.db.session.add(self.m.Manual(company_code=company,title='Synthetic manual',filename='shared.pdf'))
  self.m.db.session.commit()
  class Store:
   def __init__(s):s.calls=[];s.keys={'manuals/shared.pdf'}
   def head_object(s,**kw):
    s.calls.append(('HEAD',kw['Key']))
    if kw['Key'] not in s.keys:raise ClientError({'Error':{'Code':'NoSuchKey'}},'HeadObject')
    return {'VersionId':'synthetic-v1','ContentLength':8}
   def get_object(s,**kw):
    from io import BytesIO
    s.calls.append(('GET',kw['Key']))
    if kw['Key'] not in s.keys:raise ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
    return {'Body':BytesIO(b'SYNTHETIC PDF'),'ContentType':'application/pdf'}
   def generate_presigned_url(s,*args,**kw):s.calls.append(('SIGN',kw['Params']['Key'],kw['ExpiresIn']));return 'https://synthetic.invalid/manual.pdf'
  self.store=Store();self.m.app.extensions['dkss']['s3_client']=self.store;self.m.app.config['S3_BUCKET_NAME']='synthetic-only'
 def switch(self,company):
  u=self.m.User.query.filter_by(company_code=company,username='admin').one()
  with self.client.session_transaction() as s:s.update(company_code=company,account_identity=u.account_identity)
 def get_manual(self):
  r=self.client.get('/static/manuals/shared.pdf');r.get_data();r.close();return r
 def test_two_authenticated_companies_share_flat_key_if_both_reference(self):
  self.assertEqual(self.get_manual().status_code,302);self.switch('OTHER');self.assertEqual(self.get_manual().status_code,302)
  self.assertEqual([c for c in self.store.calls if c[0]=='SIGN'],[('SIGN','manuals/shared.pdf',300)]*2)
 def test_other_company_only_reference_is_denied_before_storage(self):
  self.m.Manual.query.filter_by(company_code='TEST').delete();self.m.db.session.commit()
  self.assertEqual(self.get_manual().status_code,404);self.assertEqual(self.store.calls,[])
 def test_reference_revocation_blocks_new_signature(self):
  self.assertEqual(self.get_manual().status_code,302);self.store.calls.clear()
  self.m.Manual.query.filter_by(company_code='TEST').delete();self.m.db.session.commit()
  self.assertEqual(self.get_manual().status_code,404);self.assertEqual(self.store.calls,[])
 def test_company_keys_keep_separate_signing_targets(self):
  self.store.keys.update({'manuals/TEST/shared.pdf','manuals/OTHER/shared.pdf'})
  self.assertEqual(self.get_manual().status_code,302);self.switch('OTHER');self.assertEqual(self.get_manual().status_code,302)
  self.assertEqual([c[1] for c in self.store.calls if c[0]=='SIGN'],['manuals/TEST/shared.pdf','manuals/OTHER/shared.pdf'])
 def test_raw_proxy_same_flat_bytes_and_revoked_reference(self):
  a=self.client.get('/files/manuals/shared.pdf');self.assertEqual(a.status_code,200)
  self.switch('OTHER');b=self.client.get('/files/manuals/shared.pdf');self.assertEqual(b.status_code,200);self.assertEqual(a.data,b.data);a.close();b.close()
  self.store.calls.clear();self.m.Manual.query.filter_by(company_code='OTHER').delete();self.m.db.session.commit()
  denied=self.client.get('/files/manuals/shared.pdf');self.assertEqual(denied.status_code,404);denied.close();self.assertEqual(self.store.calls,[])
 def test_denied_primary_does_not_fall_back(self):
  for path in ('/static/manuals/shared.pdf','/files/manuals/shared.pdf'):
   self.store.calls.clear()
   def denied(**kw):
    self.store.calls.append(('DENY',kw['Key']))
    raise ClientError({'Error':{'Code':'AccessDenied'}},'HeadObject')
   self.store.head_object=denied;self.store.get_object=denied
   response=self.client.get(path);self.assertEqual(response.status_code,404);response.close()
   self.assertEqual(self.store.calls,[('DENY','manuals/TEST/shared.pdf')])
 def test_profile_reference_cannot_authorize_manual_without_manual_row(self):
  self.m.Manual.query.filter_by(company_code='TEST').delete()
  self.user.profile_image='shared.pdf';self.m.db.session.commit()
  self.assertEqual(self.get_manual().status_code,404)
  response=self.client.get('/files/manuals/shared.pdf');self.assertEqual(response.status_code,404);response.close()
  self.assertEqual(self.store.calls,[])
  self.store.keys.add('uploads/TEST/shared.pdf')
  response=self.client.get('/files/uploads/shared.pdf');self.assertEqual(response.status_code,200);response.close()
 def test_local_flat_manual_requires_manual_row_not_profile(self):
  self.m.app.extensions['dkss']['s3_client']=None;self.m.app.config['S3_BUCKET_NAME']=''
  p=Path(self.m.app.static_folder,'manuals','shared.pdf');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'SYNTHETIC LOCAL PDF')
  for path in ('/static/manuals/shared.pdf','/files/manuals/shared.pdf'):
   response=self.client.get(path,follow_redirects=True);self.assertEqual(response.status_code,200);self.assertEqual(response.data,b'SYNTHETIC LOCAL PDF');response.close()
  self.m.Manual.query.filter_by(company_code='TEST').delete();self.user.profile_image='shared.pdf';self.m.db.session.commit()
  for path in ('/static/manuals/shared.pdf','/files/manuals/shared.pdf'):
   response=self.client.get(path,follow_redirects=True);self.assertEqual(response.status_code,404);response.close()
  self.assertEqual(p.read_bytes(),b'SYNTHETIC LOCAL PDF')
 def test_unknown_folder_not_authorized_by_profile(self):
  from flask import session
  from dkss_app.storage import file_belongs_to_current_company
  self.user.profile_image='shared.pdf';self.m.db.session.commit()
  with self.m.app.test_request_context('/'):
   session.update(company_code='TEST',username='admin',account_identity=self.user.account_identity)
   self.assertTrue(file_belongs_to_current_company('shared.pdf','uploads'))
   for folder in ('unknown','',None,'Manuals'):self.assertFalse(file_belongs_to_current_company('shared.pdf',folder))
 def test_regular_user_manual_compatibility(self):
  self.user.role='user';self.m.db.session.commit()
  with self.client.session_transaction() as session:session['role']='user'
  self.assertEqual(self.get_manual().status_code,302)
  self.m.Manual.query.filter_by(company_code='TEST').delete();self.user.profile_image='shared.pdf';self.m.db.session.commit()
  self.assertEqual(self.get_manual().status_code,404)

for n in dir(profile_fixture.ProfileImageDisplayTests):
 if n.startswith('test_') and n not in ManualTenant.__dict__:setattr(ManualTenant,n,None)

if __name__ == "__main__": unittest.main()
