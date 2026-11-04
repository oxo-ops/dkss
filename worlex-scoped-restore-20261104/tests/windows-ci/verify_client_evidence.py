"""Fail-closed combined-gate checks for actual Windows source-client evidence."""
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import zipfile


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_client(client, linux_policy, root, directory, commit):
    lock = json.loads((root / 'tests/windows-ci/client-build-inputs.json').read_text())
    require(client.get('schema_version') == 1 and client.get('passed') is True and
            client.get('actual_windows') is True and client.get('synthetic_only') is True,
            'Actual Windows synthetic client proof required')
    require(client.get('candidate_commit') == commit, 'Windows client commit mismatch')
    require(client.get('runner_sha256') == sha(root / 'worlex_restore.py'), 'Windows client core mismatch')
    require(client.get('tested_artifacts') == linux_policy['tested_artifacts'], 'Linux/Windows code maps differ')
    require(client.get('workflow_sha256') == linux_policy['workflow_sha256'], 'Linux/Windows workflows differ')
    expected_source = {'name': 'psycopg2', 'version': '2.9.12',
                       'sdist_sha256': lock['psycopg2_sdist']['sha256'],
                       'pg_archive_sha256': lock['postgresql']['sha256'],
                       'libpq_compile_version': 180006, 'libpq_runtime_version': 180006}
    require(client.get('source_client') == expected_source, 'Source client provenance/version mismatch')
    summary = client['acceptance_summary']
    require(summary == linux_policy['acceptance_summary'], 'Linux/Windows test coverage differs')
    require(summary.get('postgres_required') is True and summary.get('expected', 0) >= 71 and
            summary.get('run') == summary.get('expected') and
            all(summary.get(k) == 0 for k in ('failures', 'errors', 'skipped')), 'Windows acceptance incomplete')
    for key in ('full_table_acceptance', 'disconnect_acceptance'):
        require(client.get(key) == linux_policy.get(key), 'Linux/Windows acceptance evidence differs: ' + key)
    tls = client['tls']
    require(tls.get('sslmode') == 'verify-full' and all(tls.get(k) is True for k in
            ('in_use', 'wrong_root_rejected', 'wrong_hostname_rejected')), 'Verify-full positive/negative TLS proof missing')
    require(tls.get('protocol') in ('TLSv1.2', 'TLSv1.3') and bool(tls.get('cipher')), 'Modern TLS evidence required')
    require(client.get('custom_wait_callback') is False, 'Unexpected client wait callback')
    openssl = client['openssl_version']
    require(isinstance(openssl.get('number'), int) and openssl['number'] > 0 and
            bool(re.match(r'^OpenSSL [0-9]+\.', openssl.get('text', ''))), 'Actual OpenSSL runtime version required')
    stability = client['stability']
    require(stability.get('synthetic_only') is True and stability.get('read_only') is True and
            stability.get('buffer_queries', 0) >= 64 and stability.get('window_queries', 0) >= 185 and
            stability.get('window_seconds', 0) >= 185 and stability.get('query_count', 0) >= 249 and
            stability.get('libpq_runtime_version') == 180006 and
            stability.get('exact_external_38_queries_replayed') is False and
            stability.get('external_disconnect_cause_proven') is False, 'Synthetic Windows TLS stability proof missing')
    build = client['build_proof']
    require(all(build.get(k) is True for k in ('unmodified_source_verified', 'no_binary_fallback',
            'delvewheel_repair_reproduced', 'pip_check_passed')), 'Source-build integrity proof missing')
    require(build.get('built_wheel_tags') == 'cp312-cp312-win_amd64' and
            build.get('pg_config_version') == 'PostgreSQL 18.6' and
            build.get('postgres_archive_sha256') == lock['postgresql']['sha256'], 'Windows build identity mismatch')
    expected_inputs = {x['filename']: x['sha256'] for x in
                       [*lock['build_tools'], lock['psycopg2_sdist'], *lock['application_source_wheels']]}
    require(build.get('source_inputs_sha256') == expected_inputs, 'Pinned build input hashes differ')
    application_wheels = build.get('application_source_wheels', [])
    require(len(application_wheels) == 1, 'Reviewed application source wheel proof required')
    app = application_wheels[0]
    require(app.get('name') == 'http-ece' and app.get('version') == '1.2.1' and
            app.get('sdist_sha256') == lock['application_source_wheels'][0]['sha256'] and
            app.get('source_unmodified') is True and app.get('pure_python') is True,
            'Application source wheel provenance mismatch')
    require(bool(re.fullmatch(r'http_ece-1\.2\.1-[A-Za-z0-9.]+-none-any\.whl', app['wheel_filename'])),
            'Unexpected application wheel tag')
    app_path = directory / 'application-wheels' / app['wheel_filename']
    require(app_path.is_file() and sha(app_path) == app['wheel_sha256'], 'Application wheel artifact mismatch')
    with zipfile.ZipFile(app_path) as archive:
        app_files = {name: hashlib.sha256(archive.read(name)).hexdigest()
                     for name in archive.namelist() if not name.endswith('/')}
    require(app_files == app['files'] and not any(name.lower().endswith(('.dll', '.pyd', '.so', '.exe')) for name in app_files),
            'Application pure wheel content mismatch')
    require(build.get('official_notice_files'), 'Official dependency notices missing')
    wheel = client['wheel']
    require(wheel['filename'] == 'psycopg2-2.9.12-cp312-cp312-win_amd64.whl', 'Unexpected wheel filename')
    path = directory / wheel['filename']
    require(path.is_file() and sha(path) == wheel['sha256'], 'Tested wheel artifact hash mismatch')
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if not n.endswith('/')]
        require(len(names) == len(set(names)), 'Duplicate wheel members')
        require(all(not Path(name).is_absolute() and '..' not in Path(name).parts and '\\' not in name for name in names),
                'Unsafe wheel members')
        files = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in sorted(names)}
    require(files == wheel['files'], 'Tested wheel file manifest mismatch')
    require(any(name.endswith('/official-postgresql-18.6-docs.zip') for name in files), 'Bundled notices absent')
    dependency = build['dependency_proof']
    require(dependency.get('coherent_import_edges_verified') is True, 'Coherent PE import proof missing')
    extension = dependency['extension_relative_path']
    require(extension in files and extension.endswith('.pyd'), 'Extension payload missing')
    graph = dependency['repaired_import_graph']
    bundled = dependency['bundled_client_modules']
    require(set(bundled) == {'libpq', 'libssl', 'libcrypto'}, 'Bundled client dependency set differs')
    for key, relative in bundled.items():
        require(relative in files and Path(relative).name.lower().startswith(key), 'Invalid bundled dependency')
    require('libpq.dll' in dependency['raw_import_graph'][extension], 'Raw dynamic libpq link missing')
    require(Path(bundled['libpq']).name.lower() in graph[extension], 'Vendored libpq PE edge missing')
    require(all(Path(bundled[key]).name.lower() in graph[bundled['libpq']] for key in ('libssl', 'libcrypto')),
            'Vendored OpenSSL PE edges missing')
    require(Path(bundled['libcrypto']).name.lower() in graph[bundled['libssl']], 'Vendored crypto PE edge missing')
    loaded = {}
    observed = set()
    for module in client['loaded_modules']:
        relative = module['path_relative_to_site_packages']
        require(relative in files and files[relative] == module['sha256'], 'Loaded module hash mismatch')
        require(Path(relative).name == module['name'], 'Loaded module name mismatch')
        require(PureWindowsPath(module['loaded_path']).is_absolute(), 'Actual mapped module path required')
        require(PureWindowsPath(module['loaded_path']).as_posix().lower().endswith('/' + relative.lower()),
                'Actual mapped path differs from installed wheel')
        require(module.get('file_version') is None or bool(re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', module['file_version'])),
                'Invalid Windows DLL version resource')
        require(relative not in observed, 'Duplicate loaded module')
        observed.add(relative)
        if relative.endswith('.dll'):
            loaded[module['name']] = {'relative_path': relative, 'sha256': module['sha256'],
                                      'file_version': module['file_version']}
    require({extension, *bundled.values()}.issubset(observed), 'Actual loaded client dependency proof missing')
    require(set(graph) == {name for name in files if name.lower().endswith(('.dll', '.pyd'))}, 'PE graph coverage mismatch')
    return {'actual_windows': True, 'candidate_commit': commit,
            'runner_sha256': client['runner_sha256'],
            'guard_sha256': sha(root / 'client_runtime_guard.py'),
            'bootstrap_sha256': sha(root / 'client_bootstrap.py'),
            'wheel_sha256': wheel['sha256'], 'wheel_filename': wheel['filename'],
            'source_sdist_sha256': expected_source['sdist_sha256'],
            'pg_archive_sha256': expected_source['pg_archive_sha256'],
            'package_version': '2.9.12', 'libpq_compile_version': 180006,
            'libpq_runtime_version': 180006, 'files': files,
            'extension_relative_path': extension, 'loaded_dlls': loaded,
            'acceptance_summary': summary, 'full_table_acceptance': client['full_table_acceptance'],
            'disconnect_acceptance': client['disconnect_acceptance'],
            'tls_acceptance': {'verify_full_used': True, 'wrong_root_rejected': True,
                               'wrong_hostname_rejected': True},
            'stability_acceptance': stability, 'openssl_version': openssl}
