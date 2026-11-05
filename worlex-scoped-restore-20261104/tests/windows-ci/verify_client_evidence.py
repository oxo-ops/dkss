"""Fail-closed combined-gate checks for actual Windows pure-client evidence."""
import base64
import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
from email.parser import BytesParser
import re
import stat
import zipfile


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def safe_relative(value):
    require(isinstance(value, str) and value, 'Empty artifact member path')
    relative = PurePosixPath(value)
    require(relative.parts and not relative.is_absolute() and '..' not in relative.parts and
            '\\' not in value and ':' not in value and str(relative) == value,
            'Unsafe artifact member path: ' + value)
    require(not any(ord(char) < 32 or char in '<>\"|?*' for char in value),
            'Windows-invalid artifact member path: ' + value)
    require(all(part not in ('', '.') and not part.endswith((' ', '.')) and
                not re.fullmatch(r'(?i)(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?', part)
                for part in relative.parts), 'Windows-ambiguous artifact member path: ' + value)
    return relative


def artifact_path(directory, filename):
    relative = safe_relative(filename)
    require(len(relative.parts) == 1, 'Artifact filename must be a basename')
    path = directory / filename
    require(path.is_file() and not path.is_symlink() and
            path.resolve().is_relative_to(directory.resolve()), 'Artifact absent or unsafe: ' + filename)
    return path


def wheel_files(path, name, version):
    """Hash the complete exact wheel and reject native/ambiguous sidecar payloads."""
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [entry.filename for entry in members if not entry.is_dir()]
        require(names and len(names) == len(set(names)) == len({n.casefold() for n in names}),
                'Duplicate or Windows-aliased wheel members')
        result = {}
        for entry in members:
            relative = entry.filename.rstrip('/') if entry.is_dir() else entry.filename
            safe_relative(relative)
            mode = entry.external_attr >> 16
            require(not stat.S_ISLNK(mode), 'Wheel symlink forbidden')
            if entry.is_dir():
                continue
            require(not re.search(r'(?i)\.(?:dll|pyd|so|exe|dylib)(?:\.[0-9.]+)?$', relative),
                    'Native binary forbidden in pure client wheel: ' + relative)
            require(not relative.lower().endswith('.pth') and
                    not any(part.endswith('.data') for part in PurePosixPath(relative).parts),
                    'Wheel requires installation transformations outside the sealed sidecar')
            content = archive.read(entry)
            require(not content.startswith((b'MZ', b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf',
                                            b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe')),
                    'Native binary signature forbidden in pure client wheel')
            result[relative] = hashlib.sha256(content).hexdigest()
        wheel_metadata = [n for n in names if n.endswith('.dist-info/WHEEL')]
        package_metadata = [n for n in names if n.endswith('.dist-info/METADATA')]
        records = [n for n in names if n.endswith('.dist-info/RECORD')]
        require(len(wheel_metadata) == len(package_metadata) == len(records) == 1,
                'Exactly one package metadata record required per wheel')
        require(PurePosixPath(wheel_metadata[0]).parent == PurePosixPath(package_metadata[0]).parent,
                'Wheel metadata directories differ')
        require(PurePosixPath(records[0]).parent == PurePosixPath(package_metadata[0]).parent,
                'Wheel RECORD directory differs')
        rows = list(csv.reader(io.StringIO(archive.read(records[0]).decode('utf-8'))))
        require(all(len(row) == 3 for row in rows) and len(rows) == len(names) and
                {row[0] for row in rows} == set(names), 'Wheel RECORD must cover every file exactly once')
        for relative, digest, size in rows:
            if relative == records[0]:
                require(not digest and not size, 'Wheel RECORD self-entry must be unhashed')
                continue
            expected = 'sha256=' + base64.urlsafe_b64encode(bytes.fromhex(result[relative])).decode('ascii').rstrip('=')
            require(digest == expected and size == str(archive.getinfo(relative).file_size),
                    'Wheel RECORD payload hash/size mismatch: ' + relative)
        wheel = BytesParser().parsebytes(archive.read(wheel_metadata[0]))
        package = BytesParser().parsebytes(archive.read(package_metadata[0]))
        normalize = lambda value: re.sub(r'[-_.]+', '-', value).lower()
        require(normalize(package.get('Name', '')) == normalize(name) and
                package.get('Version') == version, 'Wheel package identity differs from lock')
        tags = wheel.get_all('Tag', [])
        require(wheel.get('Root-Is-Purelib', '').lower() == 'true' and tags and
                all(re.fullmatch(r'py[23](?:\.py[23])*-none-any', tag) for tag in tags),
                'Pure universal wheel metadata required')
    return dict(sorted(result.items()))



def validate_pure_wheels(packages, directory):
    """Validate the entire locked wheel directory before install or extraction."""
    directory = Path(directory)
    require(isinstance(packages, list) and packages, 'Pinned pure-client packages required')
    expected = {entry['filename']: entry for entry in packages}
    require(len(expected) == len(packages) == len({entry['name'] for entry in packages}),
            'Duplicate locked pure-client package or filename')
    require(directory.is_dir() and not directory.is_symlink(), 'Pure wheel directory missing or unsafe')
    require({path.name for path in directory.iterdir()} == set(expected),
            'Pure wheel directory must contain only the complete locked artifacts')
    wheels, merged, folded = {}, {}, set()
    for filename, entry in expected.items():
        require(filename.endswith('-none-any.whl') and valid_hash(entry['sha256']),
                'Pure universal locked wheel required')
        require(entry['url'].startswith('https://files.pythonhosted.org/packages/'),
                'Official PyPI wheel origin required')
        path = artifact_path(directory, filename)
        require(sha(path) == entry['sha256'], 'Pinned official wheel hash mismatch: ' + filename)
        files = wheel_files(path, entry['name'], entry['version'])
        require(not folded.intersection(name.casefold() for name in files), 'Cross-wheel file collision')
        folded.update(name.casefold() for name in files)
        merged.update(files)
        wheels[filename] = {'name': entry['name'], 'version': entry['version'],
                            'sha256': entry['sha256'], 'files': files}
    return dict(sorted(wheels.items())), dict(sorted(merged.items()))


def validate_imported_modules(imported, merged):
    module_files = {'pg8000': 'pg8000/__init__.py', 'scramp': 'scramp/__init__.py',
                    'asn1crypto': 'asn1crypto/__init__.py', 'dateutil': 'dateutil/__init__.py',
                    'six': 'six.py', 'certifi': 'certifi/__init__.py'}
    require(isinstance(imported, dict) and set(imported) == set(module_files),
            'Every imported pure dependency must be observed')
    sites = set()
    for module, relative in module_files.items():
        item = imported[module]
        path = PureWindowsPath(item['path'])
        require(path.is_absolute() and '..' not in path.parts and relative in merged and
                item.get('sha256') == merged[relative] and
                path.as_posix().lower().endswith('/' + relative.lower()),
                'Imported pure module path/hash mismatch: ' + module)
        sites.add(str(path.parents[len(PurePosixPath(relative).parts) - 1]).casefold())
    require(len(sites) == 1, 'Imported pure-client dependencies come from different environments')
    return next(iter(sites))


def validate_ssl_runtime(ssl_runtime):
    require(ssl_runtime.get('ssl_provider') == {
                'kind': 'extension', 'has_file': True, 'listed_as_builtin': False,
                'origin_kind': 'file', 'loader_kind': 'extension'} and
            ssl_runtime.get('openssl_linkage') == 'dynamic',
            'Only the CI-verified extension/dynamic SSL provider is accepted')
    require(ssl_runtime.get('no_psycopg_or_libpq_loaded') is True,
            'Native PostgreSQL client absence must be checked in the live process')
    require(isinstance(ssl_runtime.get('python_version'), str) and
            re.match(r'^3\.12\.\d+(?:\s|$)', ssl_runtime['python_version']), 'Observed CPython 3.12 runtime required')
    executable = PureWindowsPath(ssl_runtime['python_executable'])
    base_prefix = PureWindowsPath(ssl_runtime['base_prefix'])
    system_directory = PureWindowsPath(ssl_runtime['system_directory'])
    require(executable.is_absolute() and base_prefix.is_absolute() and system_directory.is_absolute() and
            '..' not in executable.parts and '..' not in base_prefix.parts and
            '..' not in system_directory.parts and system_directory.name.lower() == 'system32' and
            executable.name.lower() == 'python.exe',
            'Actual Windows Python runtime paths required')
    openssl = ssl_runtime['openssl_version']
    require(type(openssl.get('number')) is int and openssl['number'] >= 0x30000000 and
            isinstance(openssl.get('text'), str) and re.match(r'^OpenSSL [0-9]+\.', openssl['text']),
            'Actual Python OpenSSL runtime version required')
    modules = ssl_runtime['loaded_modules']
    require(isinstance(modules, list) and modules, 'Actual mapped Python SSL modules required')
    observed = set()
    support = {'vcruntime140.dll', 'vcruntime140_1.dll', 'ucrtbase.dll'}
    for module in modules:
        path = PureWindowsPath(module['loaded_path'])
        name = module['name']
        require(isinstance(name, str), 'Mapped module name invalid')
        allowed = path.is_relative_to(base_prefix) or (name.casefold() in support and
                                                      path.parent == system_directory)
        require(path.is_absolute() and '..' not in path.parts and allowed and
                path.name == name and path.suffix.lower() in ('.dll', '.pyd') and
                valid_hash(module['sha256']), 'Mapped Python SSL module path/hash invalid')
        if name.casefold() in ('_ssl.pyd', 'python312.dll') or name.lower().startswith(('libssl', 'libcrypto')):
            require(path.is_relative_to(base_prefix), 'Required Python SSL module outside Python base')
        require(name.casefold() not in observed, 'Duplicate mapped Python SSL module')
        observed.add(name.casefold())
        require('file_version' in module and (module['file_version'] is None or
                re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', module['file_version'])),
                'Invalid Windows module version resource')
        require(not any(token in name.lower() for token in ('psycopg', 'libpq')),
                'Native PostgreSQL client module loaded')
    require(observed.issuperset({'_ssl.pyd', 'python312.dll'}) and
            sum(name.startswith('libssl') and name.endswith('.dll') for name in observed) == 1 and
            sum(name.startswith('libcrypto') and name.endswith('.dll') for name in observed) == 1,
            'Actual Python SSL extension/runtime/dependency observations missing')

    return ssl_runtime


def validate_client(client, linux_policy, root, directory, commit):
    lock = json.loads((root / 'tests/windows-ci/client-build-inputs.json').read_text())
    require(client.get('schema_version') == 2 and client.get('passed') is True and
            client.get('actual_windows') is True and client.get('synthetic_only') is True,
            'Actual Windows synthetic pure-client proof required')
    require(client.get('client_profile') == 'pg8000-pure-python' and
            client.get('package_version') == '1.31.6', 'Approved pg8000 client identity required')
    require(not any(key in client for key in ('source_client', 'wheel', 'libpq_compile_version',
                                             'libpq_runtime_version', 'custom_wait_callback')),
            'Legacy native-client proof cannot seal a pure client')
    require(isinstance(commit, str) and re.fullmatch(r'[a-f0-9]{40}', commit) and
            client.get('candidate_commit') == commit, 'Windows client commit mismatch')
    require(client.get('runner_sha256') == sha(root / 'worlex_restore.py'), 'Windows client core mismatch')
    require(client.get('tested_artifacts') == linux_policy['tested_artifacts'], 'Linux/Windows code maps differ')
    require(client.get('workflow_sha256') == linux_policy['workflow_sha256'], 'Linux/Windows workflows differ')
    for relative in ('worlex_restore.py', 'client_runtime_guard.py', 'client_bootstrap.py',
                     'client_connection.py', 'tests/windows-ci/client-build-inputs.json'):
        require(client['tested_artifacts'].get(relative) == sha(root / relative),
                'Required client artifact hash mismatch: ' + relative)
    summary = client['acceptance_summary']
    require(summary == linux_policy['acceptance_summary'], 'Linux/Windows test coverage differs')
    require(summary.get('postgres_required') is True and type(summary.get('expected')) is int and
            summary['expected'] >= 93 and summary.get('run') == summary['expected'] and
            all(type(summary.get(k)) is int and summary[k] == 0 for k in ('failures', 'errors', 'skipped')),
            'Windows acceptance incomplete')
    for key in ('full_table_acceptance', 'disconnect_acceptance'):
        require(client.get(key) == linux_policy.get(key), 'Linux/Windows acceptance evidence differs: ' + key)
    full = client['full_table_acceptance']
    require(full.get('synthetic_only') is True and full.get('source_rows') == 4100 and
            full.get('populated_tables') == 37 and
            full.get('source_counts') == json.loads((root / 'source-counts.json').read_text()) and
            all(full.get(k) is True for k in ('imported_values_and_blobs_match', 'preserved_rows_match',
                                             'owner_bindings_quarantined')),
            'Full-table synthetic value/preservation proof required')
    disconnect = client['disconnect_acceptance']
    for key in ('before_commit', 'after_commit'):
        item = disconnect[key]
        require(item.get('synthetic_only') is True and item.get('source_rows') == 4100 and
                item.get('populated_tables') == 37, 'Full-table disconnect scope required')
    before, after = disconnect['before_commit'], disconnect['after_commit']
    require(all(before.get(k) is True for k in ('actual_connection_closed_before_commit', 'all_imports_absent',
            'preserved_rows_match', 'sequences_unchanged', 'fresh_readonly_verification_rejects_absent_restore')) and
            before.get('restore_retried') is False, 'Pre-commit rollback proof missing')
    require(all(after.get(k) is True for k in ('real_commit_then_client_error', 'fresh_readonly_verification_matches',
            'preserved_rows_match', 'replay_guard_rejected_before_insert', 'sequences_unchanged_by_replay')) and
            after.get('network_packet_loss_reproduced') is False, 'Post-commit reconciliation proof missing')

    tls = client['tls']
    require(tls.get('sslmode') == 'verify-full' and tls.get('verify_mode') == 'CERT_REQUIRED' and
            all(tls.get(k) is True for k in ('in_use', 'check_hostname', 'wrong_root_rejected',
                                           'wrong_hostname_rejected', 'plaintext_server_rejected',
                                           'tls_read_timeout_rejected')),
            'Verifying SSLContext positive/negative/refusal TLS proof missing')
    require(tls.get('protocol') in ('TLSv1.2', 'TLSv1.3') and
            isinstance(tls.get('cipher'), str) and bool(tls['cipher']),
            'Modern TLS evidence required')
    timeout_control = tls['read_timeout_control']
    require(timeout_control.get('actual_exception_type') in ('TimeoutError', 'InterfaceError') and
            type(timeout_control.get('elapsed_seconds')) in (float, int) and
            math.isfinite(timeout_control['elapsed_seconds']) and
            4.5 <= timeout_control['elapsed_seconds'] <= 15 and
            type(timeout_control.get('socket_timeout_seconds')) is int and
            timeout_control['socket_timeout_seconds'] == 5 and
            type(timeout_control.get('connect_attempts')) is int and timeout_control['connect_attempts'] == 1 and
            timeout_control.get('startup_received') is True and
            timeout_control.get('password_message_sent') is False and
            timeout_control.get('authentication_response_sent') is False,
            'Owned TLS read-timeout/no-retry/no-password control missing')
    stability = client['stability']
    require(stability.get('synthetic_only') is True and stability.get('read_only') is True and
            stability.get('client_profile') == 'pg8000-pure-python' and
            type(stability.get('buffer_queries')) is int and stability['buffer_queries'] >= 64 and
            type(stability.get('window_queries')) is int and stability['window_queries'] >= 185 and
            type(stability.get('window_seconds')) in (float, int) and
            math.isfinite(stability['window_seconds']) and stability['window_seconds'] >= 185 and
            type(stability.get('query_count')) is int and
            stability['query_count'] >= stability['buffer_queries'] + stability['window_queries'] and
            stability.get('exact_external_38_queries_replayed') is False and
            stability.get('external_disconnect_cause_proven') is False and
            'libpq_runtime_version' not in stability, 'Synthetic Windows TLS stability proof missing')

    packages = lock['pure_client']['packages']
    require(isinstance(packages, list) and len(packages) == 6,
            'Complete pinned pure-client dependency closure required')
    by_name = {item['name']: item for item in packages}
    require(set(by_name) == {'pg8000', 'scramp', 'asn1crypto', 'python-dateutil', 'six', 'certifi'} and
            by_name['pg8000']['version'] == '1.31.6', 'Unexpected pure-client package closure')
    wheels, merged = validate_pure_wheels(packages, directory / 'pure-wheels')
    require(client.get('wheels') == wheels, 'Exact pinned pure wheel manifests differ')
    require(client.get('wheel_files') == merged, 'Complete merged pure-client file manifest mismatch')
    imported = client['imported_modules']
    validate_imported_modules(imported, merged)

    ssl_runtime = validate_ssl_runtime(client['ssl_runtime'])

    build = client['build_proof']
    require(all(build.get(k) is True for k in ('pure_client_verified', 'no_native_client_payload',
                                             'pip_check_passed')), 'Pure-client integrity proof missing')
    expected_inputs = {x['filename']: x['sha256'] for x in
                       [*lock['build_tools'], *packages, *lock['application_source_wheels']]}
    require(build.get('source_inputs_sha256') == expected_inputs, 'Pinned build input hashes differ')
    require(build.get('pg_config_version') == 'PostgreSQL 18.6' and
            build.get('postgres_archive_sha256') == lock['postgresql']['sha256'],
            'Synthetic fixture server archive provenance mismatch')
    application_wheels = build.get('application_source_wheels', [])
    require(len(application_wheels) == len(lock['application_source_wheels']) == 1,
            'Reviewed application source wheel proof required')
    app = application_wheels[0]
    require(app.get('name') == 'http-ece' and app.get('version') == '1.2.1' and
            app.get('sdist_sha256') == lock['application_source_wheels'][0]['sha256'] and
            app.get('source_unmodified') is True and app.get('pure_python') is True,
            'Application source wheel provenance mismatch')
    require(bool(re.fullmatch(r'http_ece-1\.2\.1-[A-Za-z0-9.]+-none-any\.whl', app['wheel_filename'])),
            'Unexpected application wheel tag')
    app_path = artifact_path(directory / 'application-wheels', app['wheel_filename'])
    require(valid_hash(app['wheel_sha256']) and sha(app_path) == app['wheel_sha256'],
            'Application wheel artifact mismatch')
    require(wheel_files(app_path, app['name'], app['version']) == app['files'],
            'Application pure wheel content mismatch')
    return {'actual_windows': True, 'candidate_commit': commit,
            'client_profile': 'pg8000-pure-python', 'package_version': '1.31.6',
            'runner_sha256': client['runner_sha256'],
            'guard_sha256': sha(root / 'client_runtime_guard.py'),
            'bootstrap_sha256': sha(root / 'client_bootstrap.py'),
            'connection_helper_sha256': sha(root / 'client_connection.py'),
            'wheels': wheels, 'wheel_files': merged, 'imported_modules': imported,
            'ssl_runtime': ssl_runtime, 'acceptance_summary': summary,
            'full_table_acceptance': full, 'disconnect_acceptance': disconnect,
            'tls_acceptance': {'verify_full_used': True, 'wrong_root_rejected': True,
                               'wrong_hostname_rejected': True, 'plaintext_server_rejected': True,
                               'tls_read_timeout_rejected': True, 'read_timeout_control': timeout_control,
                               'check_hostname': True, 'verify_mode': 'CERT_REQUIRED'},
            'stability_acceptance': stability}
