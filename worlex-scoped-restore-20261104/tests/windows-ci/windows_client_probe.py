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


def pure_wheels(directory):
    from verify_client_evidence import validate_pure_wheels
    lock = json.loads((Path(__file__).with_name('client-build-inputs.json')).read_text())
    return validate_pure_wheels(lock['pure_client']['packages'], Path(directory))


def runtime(directory):
    import importlib
    import ssl
    import _ssl
    wheels, files = pure_wheels(directory)
    imports = {}
    site = Path(importlib.import_module('pg8000').__file__).resolve().parent.parent
    require(site.is_relative_to(Path(sys.prefix).resolve()), 'CLIENT_OUTSIDE_FRESH_VENV')
    for name in ('pg8000', 'scramp', 'asn1crypto', 'dateutil', 'six', 'certifi'):
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve(strict=True)
        relative = path.relative_to(site).as_posix()
        require(relative in files and sha(path) == files[relative], 'IMPORTED_PURE_FILE_MISMATCH')
        imports[name] = {'path': str(path), 'sha256': sha(path)}
    for item in wheels.values():
        require(importlib.metadata.version(item['name']) == item['version'], 'PINNED_CLIENT_VERSION_REQUIRED')
    for relative, expected in files.items():
        if relative.endswith('.dist-info/RECORD'):
            continue  # pip rewrites only installation metadata; sidecar checks every file.
        require((site / relative).is_file() and sha(site / relative) == expected, 'INSTALLED_WHEEL_FILE_MISMATCH')
    require(not any(name == 'psycopg2' or name.startswith('psycopg2.') or
                    name == 'psycopg' or name.startswith('psycopg.') for name in sys.modules),
            'UNEXPECTED_PSYCOPG_IMPORT')
    from client_runtime_guard import runtime_tls_evidence
    return {'wheels': wheels, 'wheel_files': files, 'imported_modules': imports,
            'ssl_runtime': runtime_tls_evidence()}


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
    from client_connection import connection_args
    require(1024 <= int(port) <= 65535, 'INVALID_PORT')
    return {'host': '127.0.0.1', 'port': int(port), 'database': database,
            'user': 'restore_ci', 'password': 'restore-disposable-synthetic-only',
            **connection_args(cafile=work / 'server.crt')}


def socket_tls(connection):
    import ssl
    from types import SimpleNamespace
    from client_connection import verify_tls_connection
    # The probe uses DBAPI directly. Adapt only the SQLAlchemy envelope; the
    # production function checks this real pg8000 connection and TLS socket.
    envelope = SimpleNamespace(dialect=SimpleNamespace(driver='pg8000'),
                               connection=SimpleNamespace(driver_connection=connection))
    verify_tls_connection(envelope, '127.0.0.1')
    sock = connection._usock  # Exact pinned pg8000 implementation, observed in CI.
    require(isinstance(sock, ssl.SSLSocket) and bool(sock.getpeercert()), 'VERIFIED_TLS_SOCKET_REQUIRED')
    require(sock.context.check_hostname is True and sock.context.verify_mode == ssl.CERT_REQUIRED,
            'VERIFY_FULL_CONTEXT_REQUIRED')
    require(sock.version() in ('TLSv1.2', 'TLSv1.3'), 'MODERN_TLS_REQUIRED')
    return {'sslmode': 'verify-full', 'in_use': True, 'protocol': sock.version(),
            'cipher': sock.cipher()[0], 'check_hostname': True, 'verify_mode': 'CERT_REQUIRED'}


def refusal_control(options):
    """A CI-owned loopback SSL-refusal peer, never a database or remote address."""
    import socket
    import threading
    import pg8000
    received = []
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(10)
        def peer():
            try:
                sock, _ = listener.accept()
                with sock:
                    sock.settimeout(5)
                    data = b''
                    while len(data) < 8:
                        part = sock.recv(8-len(data))
                        if not part: break
                        data += part
                    received.append(data)
                    sock.sendall(b'N')
                    received.append(sock.recv(1))
            except Exception:
                received.append('PEER_ERROR')
        thread = threading.Thread(target=peer, daemon=True); thread.start()
        try:
            connection = pg8000.connect(**(options | {'port': listener.getsockname()[1], 'timeout': 5}))
        except pg8000.InterfaceError as error:
            require(error.args == ('Server refuses SSL',), 'REFUSAL_FAILED_FOR_OTHER_REASON')
        else:
            connection.close(); raise RuntimeError('PLAINTEXT_FALLBACK_OCCURRED')
        thread.join(10)
    require(not thread.is_alive() and received == [bytes.fromhex('0000000804d2162f'), b''],
            'SSL_REFUSAL_SENT_STARTUP_OR_OTHER_DATA')
    return True


def read_timeout_control(work, options):
    """Real TLS/read-timeout boundary against an owned non-database peer."""
    import socket
    import ssl
    import struct
    import threading
    import pg8000
    from unittest.mock import patch
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.minimum_version = ssl.TLSVersion.TLSv1_2
    server.load_cert_chain(work / 'server.crt', work / 'server.key')
    completed = threading.Event()
    observation = {'startup_received': False, 'password_message_sent': False,
                   'authentication_response_sent': False, 'termination_message_sent': False, 'connect_attempts': 0,
                   'socket_timeout_seconds': 5}
    errors = []
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(10)
        port = listener.getsockname()[1]
        def receive_exact(sock, size):
            output = b''
            while len(output) < size:
                part = sock.recv(size - len(output))
                require(bool(part), 'SYNTHETIC_TLS_PEER_EARLY_EOF')
                output += part
            return output
        def peer():
            try:
                raw, _ = listener.accept()
                with raw:
                    raw.settimeout(5)
                    require(receive_exact(raw, 8) == bytes.fromhex('0000000804d2162f'), 'EXPECTED_SSL_REQUEST')
                    raw.sendall(b'S')
                    with server.wrap_socket(raw, server_side=True) as secured:
                        length = struct.unpack('!I', receive_exact(secured, 4))[0]
                        require(8 < length <= 4096, 'BOUNDED_STARTUP_REQUIRED')
                        startup = receive_exact(secured, length - 4)
                        require(startup[:4] == bytes.fromhex('00030000') and startup.endswith(b'\0\0'),
                                'POSTGRES_PROTOCOL_STARTUP_REQUIRED')
                        fields = startup[4:-1].split(b'\0')[:-1]
                        require(len(fields) % 2 == 0, 'STARTUP_KEY_VALUES_REQUIRED')
                        pairs = dict(zip(fields[::2], fields[1::2]))
                        require(pairs.get(b'user') == b'restore_ci' and pairs.get(b'database') == b'postgres'
                                and b'password' not in pairs, 'FIXED_SYNTHETIC_STARTUP_REQUIRED')
                        observation['startup_received'] = True
                        secured.settimeout(0.2)
                        # No authentication response is sent. Observe only that
                        # no password or other payload follows while client waits.
                        while True:
                            try:
                                extra = secured.recv(1)
                            except socket.timeout:
                                if completed.is_set(): break
                                continue
                            if not extra: break
                            if extra == b'X':
                                require(receive_exact(secured, 4) == bytes.fromhex('00000004'),
                                        'MALFORMED_TERMINATE_MESSAGE')
                                observation['termination_message_sent'] = True
                                continue  # Observe EOF after the valid Terminate frame.
                            observation['password_message_sent'] = extra == b'p'
                            raise RuntimeError('UNEXPECTED_PAYLOAD_WITHOUT_AUTHENTICATION_REQUEST')
            except Exception as error:
                errors.append(str(error) if isinstance(error, RuntimeError) else type(error).__name__)
        thread = threading.Thread(target=peer, daemon=True); thread.start()
        original_create = socket.create_connection
        def counted(address, *args, **kwargs):
            require(address == ('127.0.0.1', port), 'ONLY_OWNED_TIMEOUT_PEER_ALLOWED')
            observation['connect_attempts'] += 1
            return original_create(address, *args, **kwargs)
        start = time.monotonic()
        try:
            with patch('socket.create_connection', side_effect=counted):
                connection = pg8000.connect(**(options | {'port': port, 'timeout': 5}))
        except Exception as error:
            cause = error.__cause__
            require(isinstance(error, TimeoutError) or
                    (isinstance(error, pg8000.InterfaceError) and isinstance(cause, TimeoutError)),
                    'EXPECTED_ACTUAL_READ_TIMEOUT')
            observation['actual_exception_type'] = type(error).__name__
            observation['elapsed_seconds'] = time.monotonic() - start
        else:
            connection.close(); raise RuntimeError('AUTHENTICATION_SILENCE_CONNECTED')
        finally:
            completed.set(); thread.join(5)
    require(not thread.is_alive() and not errors, 'TIMEOUT_PEER_FAILED:' + ','.join(errors))
    require(observation['startup_received'] and observation['connect_attempts'] == 1
            and not observation['password_message_sent']
            and 4.5 <= observation['elapsed_seconds'] <= 15, 'READ_TIMEOUT_CONTROL_NOT_PROVEN')
    return observation


def tls_and_marker(work, port, directory, evidence):
    import pg8000
    import ssl
    import socket
    from unittest.mock import patch
    from client_connection import tls_context
    options = connection_options(work, port)
    connection = pg8000.connect(**options)
    try:
        tls = socket_tls(connection)
        cursor = connection.cursor()
        cursor.execute('SHOW data_directory')
        require(Path(cursor.fetchone()[0]).resolve() == (work / 'data').resolve(), 'WRONG_SERVER_DATA_DIRECTORY')
        cursor.execute('SHOW server_version_num')
        require(cursor.fetchone()[0] == '180006', 'POSTGRES_18_6_REQUIRED')
    finally:
        connection.close()
    original_getaddrinfo = socket.getaddrinfo
    def local_wrong_name(host, *args, **kwargs):
        require(host == 'wrong-host.invalid', 'NEGATIVE_TLS_HOST_NOT_FIXED')
        return original_getaddrinfo('127.0.0.1', *args, **kwargs)
    for label, changes in (
        ('wrong_hostname_rejected', {'host': 'wrong-host.invalid'}),
        ('wrong_root_rejected', {'ssl_context': tls_context(work / 'wrong-root.crt')})):
        try:
            if label == 'wrong_hostname_rejected':
                with patch('socket.getaddrinfo', side_effect=local_wrong_name):
                    connection = pg8000.connect(**(options | changes))
            else:
                connection = pg8000.connect(**(options | changes))
        except ssl.SSLCertVerificationError as error:
            require(error.verify_code in (62, 64) if label == 'wrong_hostname_rejected'
                    else error.verify_code not in (0, 62, 64), 'WRONG_CERTIFICATE_FAILURE_REASON')
            tls[label] = True
        else:
            connection.close(); raise RuntimeError('NEGATIVE_TLS_CONTROL_CONNECTED:' + label)
    tls['plaintext_server_rejected'] = refusal_control(options)
    tls['read_timeout_control'] = read_timeout_control(work, options)
    tls['tls_read_timeout_rejected'] = True
    proof = runtime(directory)
    # The owned data-directory assertion precedes the first synthetic mutation.
    connection = pg8000.connect(**options)
    try:
        socket_tls(connection)
        connection.autocommit = True
        cursor = connection.cursor()
        cursor.execute('CREATE DATABASE dkss_restore_ci TEMPLATE template0')
        cursor.execute("COMMENT ON DATABASE dkss_restore_ci IS 'WORLEX_RESTORE_SYNTHETIC_ONLY'")
    finally:
        connection.close()
    proof['tls'] = tls
    proof['owned_server_directory_verified'] = True
    write_json(evidence / 'runtime-proof.json', proof)


def stability(work, port, directory, evidence):
    import pg8000
    count = 0
    connection = pg8000.connect(**connection_options(work, port, 'dkss_restore_ci'))
    try:
        socket_tls(connection)
        cursor = connection.cursor()
        cursor.execute('SET TRANSACTION READ ONLY')
        cursor.execute('SHOW transaction_read_only'); require(cursor.fetchone()[0] == 'on', 'READ_ONLY_REQUIRED')
        for _ in range(64):
            cursor.execute("SELECT repeat('synthetic-buffer-only-',4096), n FROM generate_series(1,8) n")
            rows = [tuple(row) for row in cursor.fetchall()]
            require(rows == [('synthetic-buffer-only-' * 4096, n) for n in range(1, 9)], 'BUFFER_READ_MISMATCH')
            count += 1
        start = time.monotonic()
        for _ in range(185):
            cursor.execute('SELECT 1 FROM pg_sleep(1)')
            require(tuple(cursor.fetchone()) == (1,), 'STABILITY_PING_FAILED'); count += 1
        elapsed = time.monotonic() - start
        require(elapsed >= 185, 'STABILITY_WINDOW_TOO_SHORT')
        connection.rollback()
    finally:
        connection.close()
    runtime(directory)
    write_json(evidence / 'stability-proof.json', {
        'synthetic_only': True, 'query_count': count, 'buffer_queries': 64,
        'window_queries': 185, 'window_seconds': elapsed,
        'read_only': True, 'client_profile': 'pg8000-pure-python',
        'exact_external_38_queries_replayed': False, 'external_disconnect_cause_proven': False})


def sidecar_guard(work, package, policy_file, output):
    require(package.resolve().is_relative_to(work), 'SMOKE_PACKAGE_MUST_BE_CI_OWNED')
    sidecar = package / 'client-sidecar'
    require(sidecar.is_dir() and not sidecar.is_symlink(), 'SIDECAR_SMOKE_DIRECTORY_REQUIRED')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(sidecar)); sys.path.insert(1, str(package))
    spec = importlib.util.spec_from_file_location('tested_client_guard', package / 'client_runtime_guard.py')
    guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
    policy = json.loads(policy_file.read_text()); profile = policy['windows_client_acceptance']
    result = guard.validate_loaded_client(sidecar, profile)
    require(result['pure_python_client'] is True and result['tls_context_verified'] is True,
            'ACTUAL_SIDECAR_GUARD_FAILED')
    spec = importlib.util.spec_from_file_location('tested_core', package / 'worlex_restore.py')
    core = importlib.util.module_from_spec(spec); spec.loader.exec_module(core)
    core.enforce_windows_client(package, policy)
    write_json(output, {'actual_windows': True, 'production_guard_passed': True,
                        'core_preconnection_guard_passed': True,
                        'sidecar_wheels_sha256': {name: value['sha256'] for name, value in profile['wheels'].items()},
                        'result': result})


if __name__ == '__main__':
    mode, location = sys.argv[1:3]
    work = require_owned(location)
    if mode == 'certificates': certificates(work)
    elif mode == 'server-dependencies': server_dependencies(work, *map(Path, sys.argv[3:5]))
    elif mode == 'acl-snapshot': acl_snapshot(work, *map(Path, sys.argv[3:6]))
    elif mode == 'sidecar': sidecar_guard(work, *map(Path, sys.argv[3:6]))
    elif mode in ('probe', 'stability'):
        port, directory, evidence = sys.argv[3:6]
        function = tls_and_marker if mode == 'probe' else stability
        function(work, int(port), Path(directory).resolve(strict=True), Path(evidence).resolve(strict=True))
    else: raise SystemExit('UNKNOWN_PROBE_MODE')
