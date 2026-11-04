"""Offline fail-closed tests. All DLL/client objects are synthetic mocks."""
import hashlib,importlib.util,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent
if ROOT.name=='tests':ROOT=ROOT.parent
spec=importlib.util.spec_from_file_location('client_guard_under_test',ROOT/'client_runtime_guard.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
def digest(value):return hashlib.sha256(value).hexdigest()
class ClientRuntimeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.sidecar=self.root/'client-sidecar';self.sidecar.mkdir()
  files={'psycopg2/_psycopg.cp312-win_amd64.pyd':b'not a real extension','psycopg2.libs/libpq-approved.dll':b'not real pq','psycopg2.libs/libssl-approved.dll':b'not real ssl','psycopg2.libs/libcrypto-approved.dll':b'not real crypto'}
  for name,value in files.items():
   path=self.sidecar/name;path.parent.mkdir(exist_ok=True);path.write_bytes(value)
  self.profile={'package_version':'2.9.12','libpq_compile_version':180006,'libpq_runtime_version':180006,'files':{k:digest(v) for k,v in files.items()},'extension_relative_path':'psycopg2/_psycopg.cp312-win_amd64.pyd','loaded_dlls':{Path(k).name:{'relative_path':k,'sha256':digest(v),'file_version':'18.6.0.0'} for k,v in files.items() if k.endswith('.dll')},'openssl_version':{'number':0x30600020,'text':'OpenSSL synthetic test'}}
 def policy(self):
  (self.root/'worlex_restore.py').write_bytes(b'fixture runner')
  before={k:True for k in ('actual_connection_closed_before_commit','all_imports_absent','preserved_rows_match','sequences_unchanged','fresh_readonly_verification_rejects_absent_restore')};before.update(synthetic_only=True,source_rows=4100,populated_tables=37,restore_retried=False)
  after={k:True for k in ('real_commit_then_client_error','fresh_readonly_verification_matches','preserved_rows_match','replay_guard_rejected_before_insert','sequences_unchanged_by_replay')};after.update(synthetic_only=True,source_rows=4100,populated_tables=37,network_packet_loss_reproduced=False)
  self.profile.update(actual_windows=True,candidate_commit='a'*40,wheel_sha256='b'*64,source_sdist_sha256='1dedb1c7a1d8552c4a6044c6b1c41a52e6a8e2d144af83eccac758076b1b7c15',pg_archive_sha256='e2246ba91d22345bc3d017586c09ede52d9df180b1eeb480f050445f1cad84e2',runner_sha256=digest(b'fixture runner'),guard_sha256=guard.sha(Path(guard.__file__)),acceptance_summary={'postgres_required':True,'run':50,'expected':50,'errors':0,'failures':0,'skipped':0},tls_acceptance={k:True for k in ('verify_full_used','wrong_root_rejected','wrong_hostname_rejected')},full_table_acceptance={'source_rows':4100,'populated_tables':37,'synthetic_only':True,'imported_values_and_blobs_match':True,'preserved_rows_match':True,'owner_bindings_quarantined':True},disconnect_acceptance={'before_commit':before,'after_commit':after})
  return {'windows_client_acceptance_passed':True,'tested_commit':'a'*40,'windows_client_acceptance':self.profile}
 def fake_client(self):
  package=types.ModuleType('psycopg2');package.__version__='2.9.12 (synthetic)';package.__libpq_version__=180006
  package.extensions=types.SimpleNamespace(libpq_version=lambda:180006,get_wait_callback=lambda:None)
  package._psycopg=types.SimpleNamespace(__file__=str(self.sidecar/self.profile['extension_relative_path']))
  return package
 def loaded(self,package=None):
  package=package or self.fake_client()
  def openssl_num():return self.profile['openssl_version']['number']
  def openssl_text(n):return self.profile['openssl_version']['text'].encode('ascii')
  crypto=types.SimpleNamespace(OpenSSL_version_num=openssl_num,OpenSSL_version=openssl_text)
  with patch.object(guard.sys,'platform','win32'),patch.object(guard.sys,'version_info',(3,12,14)),patch.dict(sys.modules,{'psycopg2':package}),patch.object(guard,'loaded_module_path',side_effect=lambda name:self.sidecar/self.profile['loaded_dlls'][name]['relative_path']),patch.object(guard,'loaded_file_version',return_value='18.6.0.0'),patch.object(guard.ctypes,'CDLL',return_value=crypto):
   return guard.validate_loaded_client(self.sidecar,self.profile)
 def test_valid_manifest_and_loaded_client(self):
  guard.validate_manifest(self.sidecar,self.profile);result=self.loaded();self.assertEqual(len(result['loaded_dlls']),3);self.assertTrue(all(Path(x['absolute_path']).is_absolute() for x in result['loaded_dlls']))
 def test_extra_file_and_modified_dll_block(self):
  extra=self.sidecar/'unexpected.txt';extra.write_text('synthetic')
  with self.assertRaisesRegex(guard.ClientStop,'CLIENT_FILE_SET_CHANGED'):guard.validate_manifest(self.sidecar,self.profile)
  extra.unlink();(self.sidecar/'psycopg2.libs/libpq-approved.dll').write_bytes(b'changed')
  with self.assertRaisesRegex(guard.ClientStop,'CLIENT_FILE_HASH_MISMATCH'):guard.validate_manifest(self.sidecar,self.profile)
 def test_path_aliases_and_casefold_collision_block(self):
  for name in ('../outside','C:/outside','a\\b','/absolute','a//b'):
   with self.subTest(name=name),self.assertRaises(guard.ClientStop):guard.inside(self.sidecar,name)
  self.profile['files']['PSYCOPG2/_psycopg.cp312-win_amd64.pyd']='a'*64
  with self.assertRaisesRegex(guard.ClientStop,'CLIENT_FILE_ALIAS_COLLISION'):guard.validate_manifest(self.sidecar,self.profile)
 def test_invalid_source_and_failed_acceptance_block(self):
  policy=self.policy();guard.policy_profile(self.root,policy)
  self.profile['source_sdist_sha256']='c'*64
  with self.assertRaisesRegex(guard.ClientStop,'CLIENT_SUPPLY_CHAIN_PROOF_REQUIRED'):guard.policy_profile(self.root,policy)
  policy=self.policy();self.profile['acceptance_summary']['skipped']=1
  with self.assertRaisesRegex(guard.ClientStop,'FULL_WINDOWS_POSTGRES_ACCEPTANCE_REQUIRED'):guard.policy_profile(self.root,policy)
 def test_full_values_and_disconnect_required(self):
  policy=self.policy();self.profile['full_table_acceptance']['preserved_rows_match']=False
  with self.assertRaisesRegex(guard.ClientStop,'WINDOWS_CLIENT_VALUE_PRESERVATION_PROOF_REQUIRED'):guard.policy_profile(self.root,policy)
  policy=self.policy();self.profile['disconnect_acceptance']['after_commit']['fresh_readonly_verification_matches']=False
  with self.assertRaisesRegex(guard.ClientStop,'WINDOWS_CLIENT_RECONCILIATION_PROOF_REQUIRED'):guard.policy_profile(self.root,policy)
 def test_tls_negative_checks_required(self):
  policy=self.policy();self.profile['tls_acceptance']['wrong_hostname_rejected']=False
  with self.assertRaisesRegex(guard.ClientStop,'WINDOWS_CLIENT_TLS_PROOF_REQUIRED'):guard.policy_profile(self.root,policy)
 def test_runtime180003_and_wait_callback_block(self):
  package=self.fake_client();package.extensions.libpq_version=lambda:180003
  with self.assertRaisesRegex(guard.ClientStop,'LOADED_CLIENT_LIBPQ_MISMATCH'):self.loaded(package)
  package=self.fake_client();package.extensions.get_wait_callback=lambda:object()
  with self.assertRaisesRegex(guard.ClientStop,'CUSTOM_CLIENT_WAIT_CALLBACK_BLOCKED'):self.loaded(package)
 def test_extension_outside_sidecar_block(self):
  package=self.fake_client();package._psycopg.__file__=str(self.root/'outside.pyd')
  with self.assertRaisesRegex(guard.ClientStop,'LOADED_CLIENT_EXTENSION_PATH_MISMATCH'):self.loaded(package)
 def test_wrong_windows_or_old_seal_block(self):
  with patch.object(guard.sys,'platform','linux'),self.assertRaisesRegex(guard.ClientStop,'WINDOWS_PYTHON312_CLIENT_REQUIRED'):guard.validate_loaded_client(self.sidecar,self.profile)
  policy=self.policy();policy['windows_client_acceptance_passed']=False
  with self.assertRaisesRegex(guard.ClientStop,'WINDOWS_CLIENT_CI_SEAL_REQUIRED'):guard.policy_profile(self.root,policy)
if __name__=='__main__':unittest.main(verbosity=2)
