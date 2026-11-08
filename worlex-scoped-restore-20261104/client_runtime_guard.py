"""Check the sealed pure-Python client and observe the existing CPython TLS runtime.

No network connection, installation, DLL replacement, or policy change occurs.
The client sidecar contains no native binaries. Existing CPython native module
hashes are observed, not falsely equated with another Python patch release's CI.
"""
import ctypes
import hashlib
import importlib
import importlib.metadata
import importlib.machinery
import json
import os
import re
import ssl
import sys
import sysconfig
from pathlib import Path, PurePosixPath

CLIENT_PROFILE = 'pg8000-pure-python'
PACKAGE_VERSION = '1.31.6'
APPROVED_DISTRIBUTIONS = {
    'pg8000': '1.31.6', 'scramp': '1.5.0', 'asn1crypto': '1.5.1',
    'python-dateutil': '2.9.0.post0', 'six': '1.17.0', 'certifi': '2026.10.23',
}
APPROVED_WHEELS = {'pg8000-1.31.6-py3-none-any.whl': {'name': 'pg8000', 'version': '1.31.6', 'sha256': '1ffe27af94fa5b37ce6885b98d591dc75562ff076859bf50ca7729af59345a80'}, 'scramp-1.5.0-py3-none-any.whl': {'name': 'scramp', 'version': '1.5.0', 'sha256': '8280608f568e81da9e9c9d69cac1331b836622d9b48bf5c5e400e16129c6d1fa'}, 'asn1crypto-1.5.1-py2.py3-none-any.whl': {'name': 'asn1crypto', 'version': '1.5.1', 'sha256': 'db4e40728b728508912cbb3d44f19ce188f218e9eba635821bb4b68564f8fd67'}, 'python_dateutil-2.9.0.post0-py2.py3-none-any.whl': {'name': 'python-dateutil', 'version': '2.9.0.post0', 'sha256': 'a8b2bc7bffae282281c8140a97d3aa9c14da0b136dfe83f850eea9a5f7470427'}, 'six-1.17.0-py2.py3-none-any.whl': {'name': 'six', 'version': '1.17.0', 'sha256': '4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274'}, 'certifi-2026.10.23-py3-none-any.whl': {'name': 'certifi', 'version': '2026.10.23', 'sha256': 'e9b54de76e530bb6cf0ccd036787103acb58fd42ba930ea8bf948ddbaa2f61d1'}}
MODULES = ('pg8000', 'scramp', 'asn1crypto', 'dateutil', 'six', 'certifi')
NATIVE_SUFFIXES = ('.dll', '.pyd', '.so', '.exe', '.dylib')

class ClientStop(RuntimeError):
    def __init__(self, reason, safe_evidence=None):
        super().__init__(reason)
        self.safe_evidence = safe_evidence

def require(value, code):
    if not value:
        raise ClientStop(code)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def no_alias(path):
    return all(not p.is_symlink() and not (hasattr(p, 'is_junction') and p.is_junction())
               for p in (path, *path.parents))

def inside(root, relative):
    require(isinstance(relative, str) and bool(relative), 'CLIENT_MANIFEST_PATH_INVALID')
    value = PurePosixPath(relative)
    require(not value.is_absolute() and '..' not in value.parts and '\\' not in relative
            and ':' not in relative and str(value) == relative, 'CLIENT_MANIFEST_PATH_INVALID')
    path = root.joinpath(*value.parts)
    require(path.is_file() and no_alias(path) and path.resolve().is_relative_to(root.resolve()),
            'CLIENT_FILE_UNSAFE')
    return path

def validate_manifest(root, profile):
    require(root.is_dir() and no_alias(root), 'CLIENT_SIDECAR_MISSING')
    require(profile.get('client_profile') == CLIENT_PROFILE and
            profile.get('package_version') == PACKAGE_VERSION, 'CLIENT_PACKAGE_VERSION_NOT_APPROVED')
    files = profile.get('wheel_files')
    require(isinstance(files, dict) and files, 'CLIENT_FILE_MANIFEST_REQUIRED')
    require(all(isinstance(n, str) for n in files) and
            len({n.casefold() for n in files}) == len(files), 'CLIENT_FILE_ALIAS_COLLISION')
    require(all(isinstance(v, str) and re.fullmatch('[a-f0-9]{64}', v) for v in files.values()),
            'CLIENT_FILE_HASH_INVALID')
    require(all(not n.lower().endswith(NATIVE_SUFFIXES) for n in files), 'CLIENT_NATIVE_PAYLOAD_BLOCKED')
    entries = list(root.rglob('*'))
    require(all(no_alias(p) for p in entries), 'CLIENT_FILE_UNSAFE')
    actual = {p.relative_to(root).as_posix() for p in entries if p.is_file()}
    require(actual == set(files), 'CLIENT_FILE_SET_CHANGED')
    for name, expected in files.items():
        path = inside(root, name)
        require(sha(path) == expected, 'CLIENT_FILE_HASH_MISMATCH')
        with path.open('rb') as stream:
            magic = stream.read(4)
        require(not (magic.startswith(b'MZ') or magic == b'\x7fELF' or magic in (b'\xfe\xed\xfa\xce', b'\xcf\xfa\xed\xfe')),
                'CLIENT_NATIVE_PAYLOAD_BLOCKED')
    wheels = profile.get('wheels')
    require(isinstance(wheels, dict) and len(wheels) == len(APPROVED_DISTRIBUTIONS),
            'CLIENT_WHEEL_PROVENANCE_REQUIRED')
    merged, versions = {}, {}
    for filename, wheel in wheels.items():
        require(isinstance(filename, str) and PurePosixPath(filename).name == filename and
                filename.endswith('-none-any.whl') and '\\' not in filename,
                'CLIENT_NON_PURE_WHEEL_BLOCKED')
        require(isinstance(wheel, dict) and wheel.get('name') not in versions and
                APPROVED_DISTRIBUTIONS.get(wheel.get('name')) == wheel.get('version'),
                'CLIENT_DISTRIBUTION_NOT_APPROVED')
        require({k: wheel.get(k) for k in ('name','version','sha256')} == APPROVED_WHEELS.get(filename),
                'CLIENT_WHEEL_HASH_INVALID')
        versions[wheel['name']] = wheel['version']
        owned = wheel.get('files')
        require(isinstance(owned, dict) and owned and not (set(owned) & set(merged)),
                'CLIENT_WHEEL_FILE_COLLISION')
        merged.update(owned)
    require(versions == APPROVED_DISTRIBUTIONS and merged == files, 'CLIENT_WHEEL_MANIFEST_MISMATCH')
    return files

def windows_loaded_modules():
    require(sys.platform == 'win32', 'WINDOWS_CLIENT_REQUIRED')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.K32EnumProcessModules.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                            ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
    kernel.K32EnumProcessModules.restype = ctypes.c_int
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint
    modules = (ctypes.c_void_p * 4096)()
    needed = ctypes.c_uint()
    require(bool(kernel.K32EnumProcessModules(kernel.GetCurrentProcess(), modules,
                ctypes.sizeof(modules), ctypes.byref(needed))) and
            needed.value <= ctypes.sizeof(modules), 'CLIENT_MODULE_ENUMERATION_FAILED')
    result = []
    for handle in modules[:needed.value // ctypes.sizeof(ctypes.c_void_p)]:
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetModuleFileNameW(handle, buffer, len(buffer))
        require(0 < length < len(buffer), 'CLIENT_DLL_PATH_UNAVAILABLE')
        result.append(Path(buffer.value))
    return result
def windows_system_directory():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetSystemDirectoryW.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetSystemDirectoryW(buffer, len(buffer))
    require(0 < length < len(buffer), 'CLIENT_SYSTEM_DIRECTORY_UNAVAILABLE')
    return Path(buffer.value).resolve()

def loaded_file_version(path):
 require(sys.platform=='win32','WINDOWS_CLIENT_REQUIRED')
 version=ctypes.WinDLL('version',use_last_error=True)
 version.GetFileVersionInfoSizeW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_uint)];version.GetFileVersionInfoSizeW.restype=ctypes.c_uint
 version.GetFileVersionInfoW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p];version.GetFileVersionInfoW.restype=ctypes.c_int
 version.VerQueryValueW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_uint)];version.VerQueryValueW.restype=ctypes.c_int
 unused=ctypes.c_uint(0);size=version.GetFileVersionInfoSizeW(str(path),ctypes.byref(unused))
 if not size:return None
 buffer=ctypes.create_string_buffer(size)
 require(bool(version.GetFileVersionInfoW(str(path),0,size,buffer)),'CLIENT_DLL_VERSION_READ_FAILED')
 pointer=ctypes.c_void_p();length=ctypes.c_uint()
 require(bool(version.VerQueryValueW(buffer,'\\',ctypes.byref(pointer),ctypes.byref(length))) and length.value>=52,'CLIENT_DLL_VERSION_FORMAT_INVALID')
 data=ctypes.cast(pointer,ctypes.POINTER(ctypes.c_uint*13)).contents
 require(data[0]==0xfeef04bd,'CLIENT_DLL_VERSION_SIGNATURE_INVALID')
 return '.'.join(str(n) for n in (data[2]>>16,data[2]&65535,data[3]>>16,data[3]&65535))

def ssl_provider_shape(module=None):
    module = ssl._ssl if module is None else module
    spec = getattr(module, '__spec__', None)
    origin = getattr(spec, 'origin', None)
    loader = getattr(spec, 'loader', None)
    has_file = isinstance(getattr(module, '__file__', None), str)
    builtin = '_ssl' in sys.builtin_module_names
    is_extension = isinstance(loader, importlib.machinery.ExtensionFileLoader)
    is_builtin = loader is importlib.machinery.BuiltinImporter
    kind = ('extension' if has_file and is_extension and origin != 'built-in' else
            'builtin' if not has_file and is_builtin and builtin and origin == 'built-in' else 'unknown')
    return {'kind': kind, 'has_file': has_file, 'listed_as_builtin': builtin,
            'origin_kind': 'builtin' if origin == 'built-in' else 'file' if isinstance(origin, str) else 'unknown',
            'loader_kind': 'extension' if is_extension else 'builtin' if is_builtin else 'other'}

def runtime_tls_evidence():
    require(sys.platform == 'win32' and sys.version_info[:2] == (3, 12),
            'WINDOWS_PYTHON312_CLIENT_REQUIRED')
    require(ctypes.sizeof(ctypes.c_void_p) == 8 and sys.implementation.name == 'cpython' and
            sysconfig.get_platform() == 'win-amd64', 'WINDOWS_AMD64_CLIENT_REQUIRED')
    raw_base = Path(sys.base_prefix)
    require(raw_base.is_absolute() and raw_base.is_dir() and no_alias(raw_base), 'CLIENT_PYTHON_BASE_UNSAFE')
    base = raw_base.resolve()
    raw_loaded = windows_loaded_modules()
    require(all(p.is_absolute() and no_alias(p) for p in raw_loaded), 'CLIENT_LOADED_PATH_ALIAS_BLOCKED')
    loaded = [p.resolve() for p in raw_loaded]
    raw_paths = {p.resolve(): str(p) for p in raw_loaded}
    require(not any('psycopg' in p.name.lower() or 'libpq' in p.name.lower() for p in loaded),
            'BLOCKED_NATIVE_CLIENT_ALREADY_LOADED')
    support = {'vcruntime140.dll', 'vcruntime140_1.dll', 'ucrtbase.dll'}
    shape = ssl_provider_shape()
    ssl_count = sum(p.name.lower().startswith('libssl') for p in loaded)
    crypto_count = sum(p.name.lower().startswith('libcrypto') for p in loaded)
    linkage = 'dynamic' if ssl_count == crypto_count == 1 else 'not_observed' if ssl_count == crypto_count == 0 else 'ambiguous'
    if shape['kind'] != 'extension' or linkage != 'dynamic':
        raise ClientStop('CLIENT_SSL_PROVIDER_NOT_CI_VERIFIED',
                         {'ssl_provider': shape, 'openssl_linkage': linkage})
    selected = [p for p in loaded if
                (p.is_relative_to(base) and p.suffix.lower() in ('.dll', '.pyd')) or
                p.name.lower() in support or p.name.lower() == '_ssl.pyd' or
                p.name.lower().startswith(('python312', 'python3.', 'libssl', 'libcrypto'))]
    for prefix in ('python312.dll', '_ssl.pyd', 'libssl', 'libcrypto'):
        matches = [p for p in selected if p.name.lower().startswith(prefix)]
        require(len(matches) == 1, 'CLIENT_TLS_MODULE_MISSING_OR_AMBIGUOUS')
    require(Path(ssl._ssl.__file__).resolve() in selected, 'CLIENT_SSL_EXTENSION_NOT_MAPPED')
    modules = []
    system = windows_system_directory()
    for path in selected:
        allowed = path.is_relative_to(base) or (path.name.lower() in support and path.parent == system)
        require(allowed and path.is_file() and no_alias(path),
                'CLIENT_TLS_MODULE_OUTSIDE_PYTHON_BASE')
        modules.append({'name': path.name, 'loaded_path': str(path), 'raw_loaded_path': raw_paths[path], 'sha256': sha(path),
                        'file_version': loaded_file_version(path)})
    require(ssl.OPENSSL_VERSION_INFO >= (3, 0), 'CLIENT_OPENSSL_VERSION_UNSUPPORTED')
    return {'python_version': '.'.join(str(x) for x in sys.version_info[:3]),
            'python_executable': str(Path(sys.executable).resolve()), 'base_prefix': str(base), 'base_prefix_raw': str(raw_base),
            'system_directory': str(system), 'ssl_provider': shape, 'openssl_linkage': linkage,
            'openssl_version': {'text': ssl.OPENSSL_VERSION, 'number': ssl.OPENSSL_VERSION_NUMBER},
            'loaded_modules': sorted(modules, key=lambda x: x['name'].casefold()),
            'no_psycopg_or_libpq_loaded': True}

def validate_loaded_client(root, profile):
    files = validate_manifest(root, profile)
    distributions = {}
    for item in importlib.metadata.distributions(path=[str(root)]):
        name = item.metadata['Name'].lower().replace('_', '-')
        require(name not in distributions, 'CLIENT_DUPLICATE_DISTRIBUTION')
        distributions[name] = item.version
    require(distributions == APPROVED_DISTRIBUTIONS, 'LOADED_CLIENT_DISTRIBUTIONS_MISMATCH')
    imported = {}
    for name in MODULES:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        require(path.is_relative_to(root.resolve()), 'LOADED_CLIENT_MODULE_OUTSIDE_SIDECAR')
        relative = path.relative_to(root.resolve()).as_posix()
        require(relative in files and sha(path) == files[relative], 'LOADED_CLIENT_MODULE_HASH_MISMATCH')
        imported[name] = {'path': str(path), 'sha256': sha(path)}
    from client_connection import tls_context
    context = tls_context()
    require(isinstance(context, ssl.SSLContext) and context.check_hostname and
            context.verify_mode == ssl.CERT_REQUIRED and
            context.minimum_version >= ssl.TLSVersion.TLSv1_2, 'CLIENT_VERIFIED_TLS_REQUIRED')
    runtime = runtime_tls_evidence()
    return {'client_profile': CLIENT_PROFILE, 'package_version': PACKAGE_VERSION,
            'pure_python_client': True, 'imported_modules': imported,
            'ssl_runtime': runtime, 'tls_context_verified': True}

def require_deferred_restore_scope(item, counts):
    # Evidence-only contract; runtime, driver and TLS enforcement is unchanged.
    expected = {'source_rows':4100, 'source_tables':37, 'imported_rows':4099,
                'imported_tables':36, 'deferred_rows':1, 'populated_tables':37}
    require(all(type(item.get(k)) is int and item[k] == v for k,v in expected.items()) and
            item.get('populated_tables_meaning') == 'source' and
            item.get('deferred_source_rows') == {'push_subscription':[1]} and
            type(item['deferred_source_rows']['push_subscription'][0]) is int,
            'WINDOWS_CLIENT_DEFERRED_SCOPE_REQUIRED')
    require(isinstance(counts, dict) and len(counts) == 62 and
            all(type(v) is int and v >= 0 for v in counts.values()) and
            sum(v > 0 for v in counts.values()) == 37 and
            all(type(v) is int for v in counts.values()) and sum(counts.values()) == 4100 and
            counts.get('push_subscription') == 1 and item.get('source_counts') == counts and
            item.get('import_counts') == dict(counts, push_subscription=0) and
            all(type(v) is int for v in item['import_counts'].values()),
            'WINDOWS_CLIENT_DEFERRED_COUNTS_REQUIRED')
    require(all(item.get(k) is True for k in ('deferred_source_fixture_retained',
                'push_subscription_rows_unchanged','push_subscription_sequence_unchanged')),
            'WINDOWS_CLIENT_PUSH_PRESERVATION_REQUIRED')
    require(not any(k in item for k in ('push_subscription_ids_remapped',
                                       'all_source_values_and_blobs_match')),
            'WINDOWS_CLIENT_LEGACY_IMPORT_PROOF_FORBIDDEN')


def policy_profile(root, policy):
    require(policy.get('windows_client_acceptance_passed') is True, 'WINDOWS_CLIENT_CI_SEAL_REQUIRED')
    profile = policy.get('windows_client_acceptance')
    require(isinstance(profile, dict) and profile.get('client_profile') == CLIENT_PROFILE,
            'PURE_PYTHON_CLIENT_PROOF_REQUIRED')
    require(profile.get('actual_windows') is True, 'ACTUAL_WINDOWS_CLIENT_PROOF_REQUIRED')
    require(profile.get('candidate_commit') == policy.get('tested_commit') and
            bool(re.fullmatch('[a-f0-9]{40}', str(profile.get('candidate_commit', '')))),
            'CLIENT_COMMIT_PROOF_MISMATCH')
    for key, filename in (('runner_sha256','worlex_restore.py'),
                          ('guard_sha256','client_runtime_guard.py'),
                          ('bootstrap_sha256','client_bootstrap.py'),
                          ('connection_helper_sha256','client_connection.py'),
                          ('observation_sha256','inspect_observation.py'),
                          ('preservation_sha256','preservation_scope.py'),
                          ('launcher_adapter_sha256','launcher_adapter.py')):
        require(profile.get(key) == sha(root / filename), 'CLIENT_PROOF_CODE_MISMATCH')
    summary = profile.get('acceptance_summary', {})
    require(summary.get('postgres_required') is True and summary.get('run', 0) >= 103 and
            summary.get('run') == summary.get('expected') and
            summary.get('errors') == summary.get('failures') == summary.get('skipped') == 0,
            'FULL_WINDOWS_POSTGRES_ACCEPTANCE_REQUIRED')
    tls = profile.get('tls_acceptance', {})
    require(all(tls.get(k) is True for k in
                ('verify_full_used','wrong_root_rejected','wrong_hostname_rejected','plaintext_server_rejected','tls_read_timeout_rejected')),
            'WINDOWS_CLIENT_TLS_PROOF_REQUIRED')
    timeout_control = tls.get('read_timeout_control', {})
    require(timeout_control.get('socket_timeout_seconds') == 5 and timeout_control.get('connect_attempts') == 1 and
            timeout_control.get('startup_received') is True and timeout_control.get('password_message_sent') is False and
            timeout_control.get('authentication_response_sent') is False and
            timeout_control.get('actual_exception_type') in ('TimeoutError','InterfaceError') and
            isinstance(timeout_control.get('elapsed_seconds'), (int,float)) and
            4.5 <= timeout_control['elapsed_seconds'] <= 15, 'WINDOWS_CLIENT_READ_TIMEOUT_PROOF_REQUIRED')
    full = profile.get('full_table_acceptance', {})
    counts = json.loads((root / 'source-counts.json').read_text())
    require_deferred_restore_scope(full, counts)
    require(full.get('source_rows') == 4100 and full.get('populated_tables') == 37 and
            full.get('synthetic_only') is True, 'WINDOWS_CLIENT_FULL_TABLE_PROOF_REQUIRED')
    require(all(full.get(k) is True for k in
                ('imported_values_and_blobs_match','preserved_rows_match','owner_bindings_quarantined')),
            'WINDOWS_CLIENT_VALUE_PRESERVATION_PROOF_REQUIRED')
    disconnect = profile.get('disconnect_acceptance', {})
    before, after = disconnect.get('before_commit', {}), disconnect.get('after_commit', {})
    for item in (before, after):
        require_deferred_restore_scope(item, counts)
        require(item.get('synthetic_only') is True and item.get('source_rows') == 4100 and
                item.get('populated_tables') == 37, 'WINDOWS_CLIENT_DISCONNECT_SCOPE_REQUIRED')
    require(all(before.get(k) is True for k in ('actual_connection_closed_before_commit',
                'all_imports_absent','preserved_rows_match','sequences_unchanged',
                'fresh_readonly_verification_rejects_absent_restore')) and
            before.get('restore_retried') is False, 'WINDOWS_CLIENT_ROLLBACK_PROOF_REQUIRED')
    require(all(after.get(k) is True for k in ('real_commit_then_client_error',
                'fresh_readonly_verification_matches','preserved_rows_match',
                'replay_guard_rejected_before_insert','sequences_unchanged_by_replay')) and
            after.get('network_packet_loss_reproduced') is False, 'WINDOWS_CLIENT_RECONCILIATION_PROOF_REQUIRED')
    runtime = profile.get('ssl_runtime', {})
    require(runtime.get('no_psycopg_or_libpq_loaded') is True and runtime.get('loaded_modules') and
            runtime.get('ssl_provider', {}).get('kind') == 'extension' and runtime.get('openssl_linkage') == 'dynamic',
            'WINDOWS_STDLIB_TLS_RUNTIME_PROOF_REQUIRED')
    return profile

def enforce(root, policy):
    require(sys.flags.isolated == 1 and sys.dont_write_bytecode, 'ISOLATED_NO_BYTECODE_CLIENT_REQUIRED')
    profile = policy_profile(root, policy)
    return validate_loaded_client(root / 'client-sidecar', profile)
