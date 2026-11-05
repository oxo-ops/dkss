"""Fail-closed pure-client manifest, policy, and native-runtime guards; no DB."""
import copy
import hashlib
import importlib.util
import json
import ssl
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('client_guard_under_test', ROOT/'client_runtime_guard.py')
guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
def digest(value): return hashlib.sha256(value).hexdigest()

class ClientRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.sidecar = self.root/'client-sidecar'; self.sidecar.mkdir()
        self.files, self.wheels = {}, {}
        mapping = dict(zip(guard.APPROVED_DISTRIBUTIONS, ('pg8000','scramp','asn1crypto','dateutil','six','certifi')))
        self.modules = {}
        for name, version in guard.APPROVED_DISTRIBUTIONS.items():
            module = mapping[name]
            relative = f'{module}/__init__.py'
            value = f'# synthetic {module}\n'.encode()
            path = self.sidecar/relative; path.parent.mkdir(); path.write_bytes(value)
            self.files[relative] = digest(value)
            filename = next(n for n, item in guard.APPROVED_WHEELS.items() if item['name'] == name)
            self.wheels[filename] = {**guard.APPROVED_WHEELS[filename], 'files':{relative:digest(value)}}
            self.modules[module] = types.SimpleNamespace(__file__=str(path))
        self.profile = {'client_profile':guard.CLIENT_PROFILE, 'package_version':guard.PACKAGE_VERSION,
                        'wheel_files':dict(self.files), 'wheels':copy.deepcopy(self.wheels)}
        self.runtime = {'python_version':'3.12.14','python_executable':'synthetic', 'base_prefix':'synthetic',
                        'openssl_version':{'text':'synthetic','number':1},
                        'loaded_modules':[{'name':'synthetic'}], 'no_psycopg_or_libpq_loaded':True,'ssl_provider':{'kind':'extension'},'openssl_linkage':'dynamic'}
    def policy(self):
        for name in ('worlex_restore.py','client_runtime_guard.py','client_bootstrap.py','client_connection.py'):
            (self.root/name).write_bytes(('fixture '+name).encode())
        before = {k:True for k in ('actual_connection_closed_before_commit','all_imports_absent',
            'preserved_rows_match','sequences_unchanged','fresh_readonly_verification_rejects_absent_restore')}
        before.update(synthetic_only=True,source_rows=4100,populated_tables=37,restore_retried=False)
        after = {k:True for k in ('real_commit_then_client_error','fresh_readonly_verification_matches',
            'preserved_rows_match','replay_guard_rejected_before_insert','sequences_unchanged_by_replay')}
        after.update(synthetic_only=True,source_rows=4100,populated_tables=37,network_packet_loss_reproduced=False)
        self.profile.update(actual_windows=True,candidate_commit='a'*40,
            runner_sha256=guard.sha(self.root/'worlex_restore.py'),
            guard_sha256=guard.sha(self.root/'client_runtime_guard.py'),
            bootstrap_sha256=guard.sha(self.root/'client_bootstrap.py'),
            connection_helper_sha256=guard.sha(self.root/'client_connection.py'),
            acceptance_summary={'postgres_required':True,'run':93,'expected':93,'errors':0,'failures':0,'skipped':0},
            tls_acceptance={k:True for k in ('verify_full_used','wrong_root_rejected','wrong_hostname_rejected','plaintext_server_rejected','tls_read_timeout_rejected')},
            full_table_acceptance={'source_rows':4100,'populated_tables':37,'synthetic_only':True,
                                  'imported_values_and_blobs_match':True,'preserved_rows_match':True,'owner_bindings_quarantined':True},
            disconnect_acceptance={'before_commit':before,'after_commit':after},ssl_runtime=self.runtime)
        self.profile['tls_acceptance']['read_timeout_control']={'socket_timeout_seconds':5,'connect_attempts':1,'startup_received':True,'password_message_sent':False,'authentication_response_sent':False,'actual_exception_type':'TimeoutError','elapsed_seconds':5.1}
        return {'windows_client_acceptance_passed':True,'tested_commit':'a'*40,'windows_client_acceptance':self.profile}
    def loaded(self, modules=None, distributions=None):
        modules = modules or self.modules
        distributions = distributions or [types.SimpleNamespace(metadata={'Name':n},version=v) for n,v in guard.APPROVED_DISTRIBUTIONS.items()]
        import client_connection
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with patch.object(guard.importlib.metadata,'distributions',return_value=distributions), \
             patch.object(guard.importlib,'import_module',side_effect=lambda n:modules[n]), \
             patch.object(guard,'runtime_tls_evidence',return_value=self.runtime), \
             patch.object(client_connection,'tls_context',return_value=context):
            return guard.validate_loaded_client(self.sidecar,self.profile)
    def test_valid_pure_manifest_and_imported_modules(self):
        guard.validate_manifest(self.sidecar,self.profile)
        result=self.loaded(); self.assertTrue(result['pure_python_client']);self.assertEqual(set(result['imported_modules']),set(guard.MODULES))
    def test_extra_modified_and_native_payload_rejected(self):
        extra=self.sidecar/'extra';extra.write_text('extra')
        with self.assertRaisesRegex(guard.ClientStop,'FILE_SET_CHANGED'):guard.validate_manifest(self.sidecar,self.profile)
        extra.unlink();first=self.sidecar/next(iter(self.files));first.write_text('modified')
        with self.assertRaisesRegex(guard.ClientStop,'FILE_HASH_MISMATCH'):guard.validate_manifest(self.sidecar,self.profile)
        self.profile['wheel_files']['hidden.dll']='a'*64
        with self.assertRaisesRegex(guard.ClientStop,'NATIVE_PAYLOAD'):guard.validate_manifest(self.sidecar,self.profile)
    def test_path_aliases_and_casefold_collision_rejected(self):
        for name in ('../outside','C:/outside','a\\b','/absolute','a//b'):
            with self.subTest(name=name),self.assertRaises(guard.ClientStop):guard.inside(self.sidecar,name)
        first=next(iter(self.files));self.profile['wheel_files'][first.upper()]='a'*64
        with self.assertRaisesRegex(guard.ClientStop,'ALIAS_COLLISION'):guard.validate_manifest(self.sidecar,self.profile)
    def test_wheel_provenance_and_distribution_version_rejected(self):
        wheel=next(iter(self.profile['wheels'].values()));wheel['version']='0'
        with self.assertRaisesRegex(guard.ClientStop,'DISTRIBUTION_NOT_APPROVED'):guard.validate_manifest(self.sidecar,self.profile)
        self.profile['wheels']=copy.deepcopy(self.wheels)
        bad=[types.SimpleNamespace(metadata={'Name':'pg8000'},version='0')]
        with self.assertRaisesRegex(guard.ClientStop,'DISTRIBUTIONS_MISMATCH'):self.loaded(distributions=bad)
    def test_code_hash_and_old_native_seal_rejected(self):
        policy=self.policy();guard.policy_profile(self.root,policy)
        self.profile['connection_helper_sha256']='0'*64
        with self.assertRaisesRegex(guard.ClientStop,'CODE_MISMATCH'):guard.policy_profile(self.root,policy)
        self.profile['client_profile']='psycopg2'
        with self.assertRaisesRegex(guard.ClientStop,'PURE_PYTHON_CLIENT_PROOF'):guard.policy_profile(self.root,policy)
    def test_full_values_and_disconnect_proof_required(self):
        policy=self.policy();self.profile['full_table_acceptance']['preserved_rows_match']=False
        with self.assertRaisesRegex(guard.ClientStop,'VALUE_PRESERVATION'):guard.policy_profile(self.root,policy)
        policy=self.policy();self.profile['disconnect_acceptance']['after_commit']['fresh_readonly_verification_matches']=False
        with self.assertRaisesRegex(guard.ClientStop,'RECONCILIATION_PROOF'):guard.policy_profile(self.root,policy)
    def test_all_tls_negatives_and_runtime_proof_required(self):
        for key in ('wrong_root_rejected','wrong_hostname_rejected','plaintext_server_rejected','tls_read_timeout_rejected'):
            policy=self.policy();self.profile['tls_acceptance'][key]=False
            with self.subTest(key=key),self.assertRaisesRegex(guard.ClientStop,'TLS_PROOF'):guard.policy_profile(self.root,policy)
        policy=self.policy();self.profile['tls_acceptance']['read_timeout_control']['connect_attempts']=2
        with self.assertRaisesRegex(guard.ClientStop,'READ_TIMEOUT_PROOF'):guard.policy_profile(self.root,policy)
        policy=self.policy();self.profile['ssl_runtime']={}
        with self.assertRaisesRegex(guard.ClientStop,'STDLIB_TLS_RUNTIME'):guard.policy_profile(self.root,policy)
    def test_outside_imported_module_rejected(self):
        modules=dict(self.modules);modules['pg8000']=types.SimpleNamespace(__file__=str(self.root/'outside.py'))
        with self.assertRaisesRegex(guard.ClientStop,'OUTSIDE_SIDECAR'):self.loaded(modules=modules)
    def test_provider_shape_distinguishes_builtin_extension_unknown(self):
        extension=types.SimpleNamespace(__file__='/synthetic/_ssl.pyd',__spec__=types.SimpleNamespace(origin='/synthetic/_ssl.pyd',loader=guard.importlib.machinery.ExtensionFileLoader('_ssl','/synthetic/_ssl.pyd')))
        self.assertEqual(guard.ssl_provider_shape(extension)['kind'],'extension')
        builtin=types.SimpleNamespace(__spec__=types.SimpleNamespace(origin='built-in',loader=guard.importlib.machinery.BuiltinImporter))
        with patch.object(guard.sys,'builtin_module_names',('_ssl',)):
            self.assertEqual(guard.ssl_provider_shape(builtin)['kind'],'builtin')
        self.assertEqual(guard.ssl_provider_shape(types.SimpleNamespace())['kind'],'unknown')
    def test_wrong_platform_and_unsealed_policy_rejected(self):
        with patch.object(guard.sys,'platform','linux'),self.assertRaisesRegex(guard.ClientStop,'WINDOWS_PYTHON312'):guard.runtime_tls_evidence()
        with self.assertRaisesRegex(guard.ClientStop,'WINDOWS_CLIENT_CI_SEAL'):guard.policy_profile(self.root,{})

    def runtime_probe(self, mutate=None):
        base=self.root/'python-base';base.mkdir(exist_ok=True)
        modules=[]
        for name in ('python312.dll','_ssl.pyd','libssl-3.dll','libcrypto-3.dll','_hashlib.pyd'):
            path=base/name;path.write_text('synthetic native module');modules.append(path.resolve())
        if mutate:modules=mutate(base,modules)
        with patch.object(guard.sys,'platform','win32'),patch.object(guard.sys,'version_info',(3,12,14)), \
             patch.object(guard.sysconfig,'get_platform',return_value='win-amd64'), \
             patch.object(guard.sys,'base_prefix',str(base)),patch.object(guard.ssl._ssl,'__file__',str(base/'_ssl.pyd'),create=True), \
             patch.object(guard,'windows_loaded_modules',return_value=modules), \
             patch.object(guard,'ssl_provider_shape',return_value={'kind':'extension'}), \
             patch.object(guard,'windows_system_directory',return_value=(self.root/'system32').resolve()), \
             patch.object(guard,'loaded_file_version',return_value='synthetic'):
            return guard.runtime_tls_evidence()
    def test_actual_runtime_module_observation_contract(self):
        result=self.runtime_probe()
        self.assertEqual(len(result['loaded_modules']),5)
        self.assertTrue(result['no_psycopg_or_libpq_loaded'])
        self.assertTrue(all(Path(x['loaded_path']).is_absolute() and len(x['sha256'])==64 for x in result['loaded_modules']))
    def test_runtime_forbids_native_postgres_driver(self):
        with self.assertRaisesRegex(guard.ClientStop,'BLOCKED_NATIVE_CLIENT'):
            self.runtime_probe(lambda b,m:m+[b/'libpq.dll'])
    def test_runtime_requires_each_tls_module(self):
        with self.assertRaisesRegex(guard.ClientStop,'PROVIDER_NOT_CI_VERIFIED'):
            self.runtime_probe(lambda b,m:[p for p in m if p.name!='libssl-3.dll'])
    def test_runtime_rejects_duplicate_tls_module(self):
        with self.assertRaisesRegex(guard.ClientStop,'PROVIDER_NOT_CI_VERIFIED'):
            self.runtime_probe(lambda b,m:m+[b/'libcrypto-other.dll'])
    def test_runtime_rejects_external_tls_module(self):
        def outside(b,m):
            path=self.root/'libssl-3.dll';path.write_text('outside')
            return [path if p.name==path.name else p for p in m]
        with self.assertRaisesRegex(guard.ClientStop,'OUTSIDE_PYTHON_BASE'):self.runtime_probe(outside)
    def test_runtime_support_dll_allowed_only_in_base_or_real_system(self):
        def support(b,m):
            system=self.root/'system32';system.mkdir(exist_ok=True)
            path=system/'ucrtbase.dll';path.write_text('synthetic support');return m+[path]
        self.assertEqual(len(self.runtime_probe(support)['loaded_modules']),6)
        def wrong(b,m):
            path=self.root/'ucrtbase.dll';path.write_text('outside');return m+[path]
        with self.assertRaisesRegex(guard.ClientStop,'OUTSIDE_PYTHON_BASE'):self.runtime_probe(wrong)
    def test_native_magic_hidden_under_text_extension_rejected(self):
        first=next(iter(self.files));path=self.sidecar/first;path.write_bytes(b'MZ00')
        self.profile['wheel_files'][first]=digest(b'MZ00')
        with self.assertRaisesRegex(guard.ClientStop,'NATIVE_PAYLOAD'):guard.validate_manifest(self.sidecar,self.profile)

if __name__=='__main__':unittest.main(verbosity=2)
