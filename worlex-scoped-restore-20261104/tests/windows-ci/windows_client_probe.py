"""CI-owned Windows client/TLS proof. This file never accepts a remote target."""
from __future__ import annotations

import ctypes
import datetime
import hashlib
import importlib.metadata
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import sys
import time
import zipfile


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True), encoding='utf-8')


def require_owned(work):
    require(sys.platform == 'win32', 'ACTUAL_WINDOWS_REQUIRED')
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and
            os.environ.get('GITHUB_REPOSITORY') == 'oxo-ops/dkss', 'DEDICATED_CI_ONLY')
    work = Path(work).resolve(strict=True)
    require(work.is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve()), 'RUNNER_TEMP_ONLY')
    require((work / 'OWNER').read_text() == 'WORLEX_WINDOWS_CLIENT_SYNTHETIC_ONLY', 'OWNERSHIP_REQUIRED')
    return work


def certificates(work):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    now = datetime.datetime.now(datetime.timezone.utc)
    for label in ('server', 'wrong-root'):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=5))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.SubjectAlternativeName([
                    x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(key, hashes.SHA256()))
        (work / (label + '.crt')).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        if label == 'server':
            (work / 'server.key').write_bytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))


def loaded_paths():
    """Enumerate actual mapped modules, not DLL guesses or PATH search results."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.K32EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE),
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.K32EnumProcessModules.restype = wintypes.BOOL
    kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetModuleFileNameW.restype = wintypes.DWORD
    modules = (wintypes.HMODULE * 4096)()
    needed = wintypes.DWORD()
    require(kernel.K32EnumProcessModules(kernel.GetCurrentProcess(), modules,
                                        ctypes.sizeof(modules), ctypes.byref(needed)), 'ENUM_MODULES_FAILED')
    require(needed.value <= ctypes.sizeof(modules), 'MODULE_LIST_TRUNCATED')
    result = []
    for module in modules[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
        buffer = ctypes.create_unicode_buffer(32768)
        n = kernel.GetModuleFileNameW(module, buffer, len(buffer))
        require(0 < n < len(buffer), 'MODULE_PATH_FAILED')
        result.append(Path(buffer.value).resolve(strict=True))
    return result


def file_version(path):
    from ctypes import wintypes
    version = ctypes.WinDLL('version', use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    version.VerQueryValueW.restype = wintypes.BOOL
    unused = wintypes.DWORD()
    length = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(unused))
    if not length:
        return None
    data = ctypes.create_string_buffer(length)
    require(version.GetFileVersionInfoW(str(path), 0, length, data), 'DLL_VERSION_READ_FAILED')
    pointer = ctypes.c_void_p()
    size = wintypes.UINT()
    require(version.VerQueryValueW(data, '\\', ctypes.byref(pointer), ctypes.byref(size)), 'DLL_VERSION_QUERY_FAILED')
    require(size.value >= 13 * ctypes.sizeof(wintypes.DWORD), 'DLL_VERSION_RESOURCE_TOO_SHORT')
    fixed = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    require(fixed[0] == 0xFEEF04BD, 'DLL_VERSION_RESOURCE_INVALID')
    return '.'.join(str(value) for value in (fixed[2] >> 16, fixed[2] & 65535, fixed[3] >> 16, fixed[3] & 65535))


def wheel_manifest(wheel):
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if not n.endswith('/')]
        require(len(names) == len(set(names)), 'DUPLICATE_WHEEL_MEMBERS')
        require(all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in names), 'UNSAFE_WHEEL_MEMBER')
        return {n: hashlib.sha256(archive.read(n)).hexdigest() for n in sorted(names)}


def runtime(wheel):
    import psycopg2
    from psycopg2 import extensions
    require(importlib.metadata.version('psycopg2') == '2.9.12', 'WRONG_PSYCOPG_VERSION')
    try:
        importlib.metadata.version('psycopg2-binary')
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise RuntimeError('BINARY_DISTRIBUTION_PRESENT')
    require(psycopg2.__libpq_version__ == extensions.libpq_version() == 180006,
            'LIBPQ_MUST_COMPILE_AND_RUN_18_6')
    require(extensions.get_wait_callback() is None, 'UNEXPECTED_PSYCOPG_WAIT_CALLBACK')
    site = Path(psycopg2.__file__).resolve().parent.parent
    require(site.is_relative_to(Path(sys.prefix).resolve()), 'CLIENT_OUTSIDE_FRESH_VENV')
    files = wheel_manifest(wheel)
    # pip rewrites RECORD and creates new metadata/pyc files; original installed
    # payload files, especially all DLLs and the extension, must be byte-identical.
    for relative, expected in files.items():
        if relative.endswith('.dist-info/RECORD'):
            continue
        target = site / relative
        require(target.is_file() and sha(target) == expected, 'INSTALLED_WHEEL_FILE_MISMATCH:' + relative)
    relevant = []
    matched = set()
    for path in loaded_paths():
        name = path.name.lower()
        if name.startswith(('libpq', 'libssl', 'libcrypto', '_psycopg')):
            if not path.is_relative_to(site):
                require(not name.startswith(('libpq', '_psycopg')), 'CLIENT_MODULE_OUTSIDE_TESTED_WHEEL:' + name)
                # CPython may load its own OpenSSL for hashlib/ssl. Delvewheel's
                # distinct mangled DLLs below are the only proven client DLLs.
                continue
            relative = path.relative_to(site).as_posix()
            require(relative in files and sha(path) == files[relative], 'CLIENT_DLL_HASH_MISMATCH:' + name)
            matched.add(relative)
            relevant.append({'name': path.name, 'path_relative_to_site_packages': relative,
                             'loaded_path': str(path), 'file_version': file_version(path), 'sha256': sha(path)})
    for prefix in ('libpq', 'libssl', 'libcrypto', '_psycopg'):
        require(sum(x['name'].lower().startswith(prefix) for x in relevant) == 1,
                'EXPECTED_EXACTLY_ONE_LOADED_MODULE:' + prefix)
    # Include every other loaded vendored dependency as well.
    for path in loaded_paths():
        if path.is_relative_to(site):
            relative = path.relative_to(site).as_posix()
            if relative in files and relative not in matched and path.suffix.lower() in ('.dll', '.pyd'):
                require(sha(path) == files[relative], 'VENDORED_MODULE_HASH_MISMATCH')
                relevant.append({'name': path.name, 'path_relative_to_site_packages': relative,
                                 'loaded_path': str(path), 'file_version': file_version(path), 'sha256': sha(path)})
    crypto = next(item for item in relevant if item['name'].lower().startswith('libcrypto'))
    openssl = ctypes.WinDLL(crypto['loaded_path'])
    openssl.OpenSSL_version_num.argtypes = []
    openssl.OpenSSL_version_num.restype = ctypes.c_ulong
    openssl.OpenSSL_version.argtypes = [ctypes.c_int]
    openssl.OpenSSL_version.restype = ctypes.c_char_p
    openssl_version = {'number': int(openssl.OpenSSL_version_num()),
                       'text': openssl.OpenSSL_version(0).decode('ascii')}
    return {'libpq_compile_version': psycopg2.__libpq_version__,
            'libpq_runtime_version': extensions.libpq_version(),
            'psycopg2_version': importlib.metadata.version('psycopg2'),
            'python_version': sys.version, 'python_executable': str(Path(sys.executable)),
            'openssl_version': openssl_version, 'custom_wait_callback': False,
            'loaded_modules': sorted(relevant, key=lambda x: x['name']),
            'wheel': {'filename': Path(wheel).name, 'sha256': sha(wheel), 'files': files}}


def dependencies(raw_wheel, repaired_wheel, output):
    """Verify the actual PE import edges; no DLL-version inference by filename."""
    import pefile
    def graph(path):
        result = {}
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith(('.pyd', '.dll')):
                    pe = pefile.PE(data=archive.read(name))
                    try:
                        require(pe.FILE_HEADER.Machine == 0x8664, 'X64_PE_REQUIRED')
                        imports = [x.dll.decode('ascii').lower() for x in
                                   getattr(pe, 'DIRECTORY_ENTRY_IMPORT', [])]
                        imports += [x.dll.decode('ascii').lower() for x in
                                    getattr(pe, 'DIRECTORY_ENTRY_DELAY_IMPORT', [])]
                        result[name] = sorted(set(imports))
                    finally:
                        pe.close()
        return result
    raw = graph(raw_wheel)
    repaired = graph(repaired_wheel)
    extensions = [name for name in repaired if Path(name).name.startswith('_psycopg') and name.endswith('.pyd')]
    require(len(extensions) == 1, 'ONE_PSYCOPG_EXTENSION_REQUIRED')
    extension = extensions[0]
    require('libpq.dll' in raw[extension], 'DYNAMIC_OFFICIAL_LIBPQ_LINK_REQUIRED')
    found = {}
    for prefix in ('libpq', 'libssl', 'libcrypto'):
        matches = [name for name in repaired if Path(name).name.lower().startswith(prefix)]
        require(len(matches) == 1, 'ONE_VENDORED_DEPENDENCY_REQUIRED:' + prefix)
        found[prefix] = matches[0]
    require(Path(found['libpq']).name.lower() in repaired[extension], 'EXTENSION_NOT_LINKED_TO_VENDORED_LIBPQ')
    for prefix in ('libssl', 'libcrypto'):
        require(Path(found[prefix]).name.lower() in repaired[found['libpq']],
                'LIBPQ_NOT_LINKED_TO_VENDORED_OPENSSL:' + prefix)
    require(Path(found['libcrypto']).name.lower() in repaired[found['libssl']],
            'LIBSSL_NOT_LINKED_TO_VENDORED_LIBCRYPTO')
    write_json(output, {'raw_import_graph': raw, 'repaired_import_graph': repaired,
                        'extension_relative_path': extension, 'bundled_client_modules': found,
                        'coherent_import_edges_verified': True})


def server_dependencies(work, runtime_dir, output):
    """Resolve native server imports only against the approved bundle/OS/CRT."""
    import pefile
    pg_bin = work / 'postgresql/pgsql/bin'
    system = Path(os.environ['SYSTEMROOT']) / 'System32'
    # System directories precede PATH in normal Windows executable DLL search.
    directories = [pg_bin, system, Path(os.environ['SYSTEMROOT']), runtime_dir, Path(sys.base_prefix)]
    pending = [pg_bin / name for name in ('initdb.exe', 'postgres.exe', 'pg_ctl.exe')]
    nodes, missing = {}, []
    while pending:
        path = pending.pop().resolve(strict=True)
        key = str(path)
        if key in nodes:
            continue
        pe = pefile.PE(str(path))
        try:
            require(pe.FILE_HEADER.Machine == 0x8664, 'SERVER_DEPENDENCY_MUST_BE_X64')
            imports = sorted({entry.dll.decode('ascii').lower() for entry in
                              getattr(pe, 'DIRECTORY_ENTRY_IMPORT', [])})
        finally:
            pe.close()
        node = {'sha256': sha(path), 'file_version': file_version(path), 'imports': {}}
        nodes[key] = node
        for name in imports:
            require(Path(name).name == name, 'INVALID_PE_DEPENDENCY_NAME')
            if name.startswith(('api-ms-win-', 'ext-ms-win-')):
                node['imports'][name] = {'kind': 'windows_api_set'}
                continue
            resolved = next((directory / name for directory in directories if (directory / name).is_file()), None)
            if resolved is None:
                missing.append({'importer': key, 'name': name})
                node['imports'][name] = {'kind': 'unresolved'}
            else:
                resolved = resolved.resolve(strict=True)
                node['imports'][name] = {'kind': 'file', 'path': str(resolved)}
                pending.append(resolved)
    result = {'scope': 'eager_loader_import_closure',
              'search_directories': list(map(str, directories)), 'nodes': nodes,
              'unresolved_imports': missing, 'selected_crt_files': {
                  str(path): {'sha256': sha(path), 'file_version': file_version(path)}
                  for path in sorted(runtime_dir.glob('*.dll'))}}
    existing = json.loads(output.read_text(encoding='utf-8'))
    existing['server_dependency_closure'] = result
    write_json(output, existing)
    write_json(output.with_name('build-proof.json'), {'status': 'SERVER_DEPENDENCY_PREFLIGHT',
                                                    'dependency_proof': existing})
    require(not missing, 'SERVER_DEPENDENCY_CLOSURE_UNRESOLVED')


def acl_snapshot(work, control, runtime_dir, output):
    """Read token identities and owner/DACLs; never change permissions or tokens."""
    from ctypes import wintypes
    control = require_owned(control)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    pointer = ctypes.c_void_p
    pp = ctypes.POINTER(pointer)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.OpenProcessToken.restype = wintypes.BOOL
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, pointer,
                                              wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    security.GetTokenInformation.restype = wintypes.BOOL
    security.ConvertSidToStringSidW.argtypes = [pointer, pp]
    security.ConvertSidToStringSidW.restype = wintypes.BOOL
    security.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
                                               pp, pp, pp, pp, pp]
    security.GetNamedSecurityInfoW.restype = wintypes.DWORD
    security.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        pointer, wintypes.DWORD, wintypes.DWORD, pp, ctypes.POINTER(wintypes.DWORD)]
    security.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    security.GetSecurityDescriptorControl.argtypes = [pointer, ctypes.POINTER(wintypes.USHORT),
                                                       ctypes.POINTER(wintypes.DWORD)]
    security.GetSecurityDescriptorControl.restype = wintypes.BOOL

    def sid_string(sid):
        text = pointer()
        require(security.ConvertSidToStringSidW(sid, ctypes.byref(text)), 'SID_CONVERSION_FAILED')
        try:
            return ctypes.wstring_at(text)
        finally:
            kernel.LocalFree(text)

    token = wintypes.HANDLE()
    require(security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)),
            'TOKEN_QUERY_OPEN_FAILED')
    identities = {}
    try:
        for name, info_class in (('token_user', 1), ('token_owner', 4)):
            size = wintypes.DWORD()
            ok = security.GetTokenInformation(token, info_class, None, 0, ctypes.byref(size))
            require(not ok and ctypes.get_last_error() == 122 and size.value > 0, 'TOKEN_SIZE_QUERY_FAILED')
            data = ctypes.create_string_buffer(size.value)
            require(security.GetTokenInformation(token, info_class, data, size, ctypes.byref(size)),
                    'TOKEN_IDENTITY_QUERY_FAILED')
            identities[name] = sid_string(pointer.from_buffer(data))
    finally:
        kernel.CloseHandle(token)

    existing = json.loads(output.read_text(encoding='utf-8'))
    paths = {work, control, runtime_dir, Path.cwd().resolve(strict=True)}
    paths.add(Path(os.environ.get('COMSPEC', str(Path(os.environ['SYSTEMROOT']) / 'System32/cmd.exe'))))
    for raw in existing['server_dependency_closure']['nodes']:
        path = Path(raw)
        paths.add(path)
        if path.is_relative_to(work):
            paths.add(control / path.relative_to(work))
    paths.update(runtime_dir.glob('*.dll'))
    for path in list(paths):
        paths.update(path.parents)
    records = []
    for path in sorted(paths):
        owner, group, dacl, descriptor = (pointer() for _ in range(4))
        # SE_FILE_OBJECT=1, OWNER|GROUP|DACL_SECURITY_INFORMATION=7. Read only.
        error = security.GetNamedSecurityInfoW(str(path), 1, 7, ctypes.byref(owner),
                    ctypes.byref(group), ctypes.byref(dacl), None, ctypes.byref(descriptor))
        if error:
            records.append({'path': str(path), 'read_error_win32': error})
            continue
        text = pointer()
        try:
            length = wintypes.DWORD()
            require(security.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, 1, 7, ctypes.byref(text), ctypes.byref(length)), 'DACL_SDDL_READ_FAILED')
            flags, revision = wintypes.USHORT(), wintypes.DWORD()
            require(security.GetSecurityDescriptorControl(descriptor, ctypes.byref(flags),
                                                          ctypes.byref(revision)), 'DACL_CONTROL_READ_FAILED')
            records.append({'path': str(path), 'owner_sid': sid_string(owner),
                            'group_sid': sid_string(group),
                            'sddl_owner_group_dacl': ctypes.wstring_at(text),
                            'dacl_protected': bool(flags.value & 0x1000),
                            'security_descriptor_control': flags.value})
        finally:
            if text:
                kernel.LocalFree(text)
            kernel.LocalFree(descriptor)
    result = {'scope': 'current_process_token_and_file_security_read_only',
              'observes_restricted_child_token': False, 'token': identities, 'paths': records}
    existing['server_acl_snapshot'] = result
    write_json(output, existing)
    write_json(output.with_name('build-proof.json'), {'status': 'SERVER_ACL_OBSERVED',
                                                     'dependency_proof': existing})
    by_path = {entry['path']: entry for entry in records}
    require(all('owner_sid' in by_path[str(path)] for path in (work, control)), 'WORK_ROOT_ACL_UNAVAILABLE')


def connection_options(work, port, database='postgres'):
    require(1024 <= int(port) <= 65535, 'INVALID_PORT')
    return {'host': '127.0.0.1', 'hostaddr': '127.0.0.1', 'port': int(port),
            'dbname': database, 'user': 'restore_ci',
            'password': 'restore-disposable-synthetic-only', 'sslmode': 'verify-full',
            'sslrootcert': str(work / 'server.crt'), 'connect_timeout': 5}


def tls_and_marker(work, port, wheel, evidence):
    import psycopg2
    options = connection_options(work, port)
    with psycopg2.connect(**options) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SHOW data_directory')
            require(Path(cursor.fetchone()[0]).resolve() == (work / 'data').resolve(), 'WRONG_SERVER_DATA_DIRECTORY')
            cursor.execute('SHOW server_version_num')
            require(cursor.fetchone()[0] == '180006', 'POSTGRES_18_6_REQUIRED')
        require(connection.info.ssl_in_use, 'TLS_NOT_IN_USE')
        tls = {'sslmode': 'verify-full', 'in_use': True,
               'protocol': connection.info.ssl_attribute('protocol'),
               'cipher': connection.info.ssl_attribute('cipher')}
    # Connecting to the correct address while naming a different host isolates
    # hostname verification; an independent root isolates chain verification.
    for label, changes, expected_fragment in (
        ('wrong_hostname_rejected', {'host': 'wrong-host.invalid'}, 'does not match host name'),
        ('wrong_root_rejected', {'sslrootcert': str(work / 'wrong-root.crt')}, 'certificate verify failed')):
        try:
            connection = psycopg2.connect(**(options | changes))
        except psycopg2.OperationalError as error:
            require(expected_fragment in str(error).lower(), 'NEGATIVE_TLS_CONTROL_FAILED_FOR_OTHER_REASON:' + label)
            tls[label] = True
        else:
            connection.close()
            raise RuntimeError('NEGATIVE_TLS_CONTROL_CONNECTED:' + label)
    proof = runtime(wheel)
    # Deliberately create a new database. Never DROP/TRUNCATE or reuse an existing
    # database. The owned data-directory check above precedes this first mutation.
    connection = psycopg2.connect(**options)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute('CREATE DATABASE dkss_restore_ci TEMPLATE template0')
            cursor.execute("COMMENT ON DATABASE dkss_restore_ci IS 'WORLEX_RESTORE_SYNTHETIC_ONLY'")
    finally:
        connection.close()
    proof['tls'] = tls
    proof['owned_server_directory_verified'] = True
    write_json(evidence / 'runtime-proof.json', proof)


def stability(work, port, wheel, evidence):
    """Separate synthetic TLS result-buffer stress and the previous 185s window."""
    import psycopg2
    count = 0
    with psycopg2.connect(**connection_options(work, port, 'dkss_restore_ci')) as connection:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            # Synthetic text exceeds one TLS record, exercising repeated drains.
            for _ in range(64):
                cursor.execute("SELECT repeat('synthetic-buffer-only-',4096), n FROM generate_series(1,8) n")
                rows = cursor.fetchall()
                require(rows == [('synthetic-buffer-only-' * 4096, n) for n in range(1, 9)], 'BUFFER_READ_MISMATCH')
                count += 1
            start = time.monotonic()
            for _ in range(185):
                cursor.execute('SELECT 1 FROM pg_sleep(1)')
                require(cursor.fetchone() == (1,), 'STABILITY_PING_FAILED')
                count += 1
            elapsed = time.monotonic() - start
            require(elapsed >= 185, 'STABILITY_WINDOW_TOO_SHORT')
    proof = runtime(wheel)
    write_json(evidence / 'stability-proof.json', {
        'synthetic_only': True, 'query_count': count, 'buffer_queries': 64,
        'window_queries': 185, 'window_seconds': elapsed,
        'read_only': True, 'libpq_runtime_version': proof['libpq_runtime_version'],
        'exact_external_38_queries_replayed': False,
        'external_disconnect_cause_proven': False})


def sidecar_guard(work, package, policy_file, output):
    """Run the production guard in a fresh child with the exact extracted wheel."""
    require(package.resolve().is_relative_to(work), 'SMOKE_PACKAGE_MUST_BE_CI_OWNED')
    sidecar = package / 'client-sidecar'
    require(sidecar.is_dir() and not sidecar.is_symlink(), 'SIDECAR_SMOKE_DIRECTORY_REQUIRED')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(sidecar))
    spec = importlib.util.spec_from_file_location('tested_client_guard', package / 'client_runtime_guard.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    policy = json.loads(policy_file.read_text())
    profile = policy['windows_client_acceptance']
    result = guard.validate_loaded_client(sidecar, profile)
    require(result['loaded_extension_and_dll_hashes_match'] is True, 'ACTUAL_SIDECAR_GUARD_FAILED')
    spec = importlib.util.spec_from_file_location('tested_core', package / 'worlex_restore.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    core.enforce_windows_client(package, policy)
    write_json(output, {'actual_windows': True, 'production_guard_passed': True,
                        'core_preconnection_guard_passed': True,
                        'sidecar_wheel_sha256': profile['wheel_sha256'],
                        'result': result})


if __name__ == '__main__':
    mode, location = sys.argv[1:3]
    work = require_owned(location)
    if mode == 'certificates':
        certificates(work)
    elif mode == 'dependencies':
        dependencies(*map(Path, sys.argv[3:6]))
    elif mode == 'server-dependencies':
        server_dependencies(work, *map(Path, sys.argv[3:5]))
    elif mode == 'acl-snapshot':
        acl_snapshot(work, *map(Path, sys.argv[3:6]))
    elif mode == 'sidecar':
        sidecar_guard(work, *map(Path, sys.argv[3:6]))
    elif mode in ('probe', 'stability'):
        port, wheel, evidence = sys.argv[3:6]
        function = tls_and_marker if mode == 'probe' else stability
        function(work, int(port), Path(wheel).resolve(strict=True), Path(evidence).resolve(strict=True))
    else:
        raise SystemExit('UNKNOWN_PROBE_MODE')
