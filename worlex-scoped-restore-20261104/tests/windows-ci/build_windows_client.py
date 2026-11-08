"""Build and exercise one pure-Python client candidate in a fresh Windows CI directory.

No service install, existing database, real backup, user venv, or fallback client.
The only database server this script can launch lives below RUNNER_TEMP/OWNER.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import uuid
import zipfile

from verify_client_evidence import validate_acceptance

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
sys.path.insert(0, str(PACKAGE / 'tests'))
from ci_server_diagnostics import PREFIX, owned_server_lifecycle
REPO = PACKAGE.parent
EVIDENCE = REPO / 'windows-client-evidence'
PASSWORD = 'restore-disposable-synthetic-only'  # Disposable CI identity only.


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True), encoding='utf-8')


def run(args, *, env=None, cwd=None, timeout=600, capture=False):
    return subprocess.run([str(x) for x in args], env=env, cwd=cwd or REPO,
                          timeout=timeout, check=True, text=True,
                          capture_output=capture)


def clean_environment():
    allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'PROGRAMFILES',
               'PROGRAMFILES(X86)', 'PROGRAMDATA', 'PROCESSOR_ARCHITECTURE',
               'NUMBER_OF_PROCESSORS', 'GITHUB_ACTIONS', 'GITHUB_REPOSITORY',
               'GITHUB_SHA', 'RUNNER_TEMP'}
    env = {key.upper(): value for key, value in os.environ.items() if key.upper() in allowed}
    require('SYSTEMROOT' in env, 'WINDOWS_SYSTEMROOT_REQUIRED')
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
               PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_CONFIG_FILE=os.devnull,
               PIP_NO_INPUT='1', PIP_INDEX_URL='https://pypi.org/simple',
               AWS_EC2_METADATA_DISABLED='true', S3_BUCKET_NAME='', OPENAI_API_KEY='',
               SMTP_HOST='', VAPID_PRIVATE_KEY='', DOCUMENT_IMPORT_WORKER_ENABLED='0')
    env['PATH'] = os.pathsep.join([str(Path(sys.executable).parent),
                                 str(Path(env['SYSTEMROOT']) / 'System32')])
    return env


def fetch(item, destination):
    require(item['url'].startswith(('https://files.pythonhosted.org/',
                                    'https://get.enterprisedb.com/postgresql/')),
            'UNAPPROVED_BUILD_DOWNLOAD_SOURCE')
    require(re.fullmatch(r'[0-9a-f]{64}', item['sha256']), 'BUILD_HASH_REQUIRED')
    with urllib.request.urlopen(item['url'], timeout=120) as response, destination.open('xb') as output:
        shutil.copyfileobj(response, output)
    require(sha(destination) == item['sha256'], 'BUILD_DOWNLOAD_HASH_MISMATCH:' + destination.name)


def extract_zip(archive, destination):
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            require(not Path(name).is_absolute() and '..' not in Path(name).parts,
                    'UNSAFE_ARCHIVE_MEMBER')
        source.extractall(destination)


def vc_environment(base):
    vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    require(vswhere.is_file(), 'BUILT_IN_MSVC_DISCOVERY_MISSING')
    installation = run([vswhere, '-latest', '-products', '*', '-requires',
                        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
                        '-property', 'installationPath'], env=base, capture=True).stdout.strip()
    require(bool(installation) and '\n' not in installation, 'ONE_MSVC_INSTALLATION_REQUIRED')
    vcvars = Path(installation) / 'VC/Auxiliary/Build/vcvars64.bat'
    require(vcvars.is_file(), 'BUILT_IN_MSVC_X64_MISSING')
    command = f'call "{vcvars}" >nul && set'
    # cmd parses quotes itself, not using CommandLineToArgvW/CRT escaping.
    raw_command = '"' + base['COMSPEC'] + '" /d /s /c "' + command + '"'
    values = subprocess.run(raw_command, executable=base['COMSPEC'], env=base,
                            cwd=REPO, timeout=120, check=True, text=True,
                            capture_output=True).stdout
    result = dict(base)
    for line in values.splitlines():
        if '=' in line and not line.startswith('='):
            key, value = line.split('=', 1)
            result[key.upper()] = value
    result['DISTUTILS_USE_SDK'] = '1'
    result['MSSdk'] = '1'
    result['WORLEX_MSVC_INSTALLATION'] = installation
    return result


def msvc_runtime_directory(compiler):
    """Use the x64 CRT supplied by the already selected official VS install."""
    installation = Path(compiler['WORLEX_MSVC_INSTALLATION']).resolve(strict=True)
    redist_parent = (installation / 'VC/Redist/MSVC').resolve(strict=True)
    declared = compiler.get('VCTOOLSREDISTDIR')
    if declared:
        redist = Path(declared).resolve(strict=True)
        require(redist.is_relative_to(redist_parent), 'MSVC_REDIST_OUTSIDE_SELECTED_INSTALLATION')
        versions = [redist]
    else:
        # Same verified Visual Studio installation only, never an inherited PATH
        # or arbitrary system search. Sort numeric toolset versions explicitly.
        versions = [path for path in redist_parent.iterdir()
                    if path.is_dir() and re.fullmatch(r'\d+(?:\.\d+)+', path.name)]
        versions.sort(key=lambda path: tuple(map(int, path.name.split('.'))), reverse=True)
    required = ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
    for version in versions:
        matches = [path for path in (version / 'x64').glob('Microsoft.VC*.CRT')
                   if path.is_dir() and all((path / name).is_file() for name in required)]
        require(len(matches) <= 1, 'AMBIGUOUS_MSVC_X64_CRT_DIRECTORY')
        if matches:
            result = matches[0].resolve(strict=True)
            require(result.is_relative_to(redist_parent), 'MSVC_CRT_OUTSIDE_SELECTED_INSTALLATION')
            return result
    raise RuntimeError('SELECTED_MSVC_X64_CRT_MISSING')


def native_loader_preflight(pg_bin, baseline, corrected, runtime_dir, evidence):
    """Measure executable loading without starting or touching a database."""
    result = {'postgres_archive_sha256': 'e2246ba91d22345bc3d017586c09ede52d9df180b1eeb480f050445f1cad84e2',
              'runtime_directory': str(runtime_dir), 'process_path_only': True,
              'dlls_copied': False, 'tools': {}, 'baseline_runtime_candidates': {}}
    runtime_names = ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
    for name in runtime_names:
        result['baseline_runtime_candidates'][name] = [
            {'path': str(path), 'sha256': sha(path)}
            for directory in (pg_bin, Path(baseline['SYSTEMROOT']) / 'System32', Path(sys.executable).parent)
            if (path := directory / name).is_file()]
    result['selected_runtime_files'] = {path.name: sha(path) for path in sorted(runtime_dir.glob('*.dll'))}
    for name in ('initdb.exe', 'postgres.exe', 'pg_ctl.exe'):
        binary = pg_bin / name
        observations = {'binary_sha256': sha(binary)}
        for label, environment in (('baseline', baseline), ('corrected', corrected)):
            process = subprocess.run([str(binary), '--version'], env=environment,
                                     cwd=REPO, timeout=30, capture_output=True, text=True)
            observations[label] = {'returncode': process.returncode,
                                   'ntstatus_hex': hex(process.returncode & 0xffffffff),
                                   'stdout': process.stdout.strip(), 'stderr': process.stderr.strip()}
        result['tools'][name] = observations
    existing = json.loads(evidence.read_text(encoding='utf-8'))
    existing['server_loader_preflight'] = result
    json_write(evidence, existing)
    json_write(evidence.with_name('build-proof.json'), {'status': 'SERVER_LOADER_PREFLIGHT',
                                                       'dependency_proof': existing})
    for name, observations in result['tools'].items():
        corrected_result = observations['corrected']
        require(corrected_result['returncode'] == 0 and
                corrected_result['stdout'] == f'{Path(name).stem} (PostgreSQL) 18.6',
                'OFFICIAL_SERVER_TOOL_LOADER_PREFLIGHT_FAILED:' + name)
    return result


def restricted_initdb_preflight(build_python, work, pg_archive, pg_bin, pg_env, runtime_dir):
    """Exercise PostgreSQL's own restricted-token path without creating a DB."""
    control = Path(tempfile.mkdtemp(prefix='worlex-private-acl-control-',
                                    dir=os.environ['RUNNER_TEMP'])).resolve(strict=True)
    require(control.is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve()), 'CONTROL_OUTSIDE_RUNNER_TEMP')
    (control / 'OWNER').write_text('WORLEX_WINDOWS_CLIENT_SYNTHETIC_ONLY')
    extract_zip(pg_archive, control / 'postgresql')
    control_bin = control / 'postgresql/pgsql/bin'
    # Both arms use byte-identical complete official distributions, no DLL graft.
    original = {path.relative_to(pg_bin.parent).as_posix(): sha(path)
                for path in pg_bin.parent.rglob('*') if path.is_file()}
    copied = {path.relative_to(control_bin.parent).as_posix(): sha(path)
              for path in control_bin.parent.rglob('*') if path.is_file()}
    require(original == copied, 'RESTRICTED_CONTROL_OFFICIAL_BUNDLE_MISMATCH')
    output = EVIDENCE / 'dependency-proof.json'
    run([build_python, HERE / 'windows_client_probe.py', 'acl-snapshot', work,
         control, runtime_dir, output], env=pg_env)
    password_file = work / 'show-probe-password.txt'
    password_file.write_text(PASSWORD, encoding='ascii')
    result = {'scope': 'native_initdb_restricted_self_reexec_show_only',
              'official_bundle_bytes_identical': True, 'existing_acls_changed': False,
              'restricted_token_bypassed': False,
              'environment_without_path_sha256': hashlib.sha256(json.dumps(
                  {key: value for key, value in pg_env.items() if key != 'PATH'},
                  sort_keys=True).encode()).hexdigest(), 'arms': {}}
    try:
        for label, directory, binary_dir in (('private_0700_control', control, control_bin),
                                             ('inherited_acl_candidate', work, pg_bin)):
            data = directory / 'show-only-absent-data'
            require(not data.exists(), 'SHOW_PROBE_DATA_ALREADY_EXISTS')
            environment = dict(pg_env)
            require(sum(Path(part) == pg_bin for part in pg_env['PATH'].split(os.pathsep)) == 1,
                    'EXACTLY_ONE_SERVER_BIN_IN_PATH_REQUIRED')
            environment['PATH'] = os.pathsep.join(
                str(binary_dir) if Path(part) == pg_bin else part
                for part in pg_env['PATH'].split(os.pathsep))
            require('PG_RESTRICT_EXEC' not in environment, 'RESTRICTED_TOKEN_BYPASS_BLOCKED')
            args = [str(binary_dir / 'initdb.exe'), '--debug', '--show', '-D', str(data), '-U', 'restore_ci',
                    '--encoding=UTF8', '--locale=C', '--auth-local=scram-sha-256',
                    '--auth-host=scram-sha-256', '--pwfile', str(password_file)]
            observation = {'argv': args, 'path': environment['PATH'], 'cwd': str(REPO)}
            try:
                process = subprocess.run(args, env=environment, cwd=REPO, timeout=60,
                                         capture_output=True, text=True)
                observation.update(returncode=process.returncode,
                                   ntstatus_hex=hex(process.returncode & 0xffffffff),
                                   stdout=process.stdout.strip(), stderr=process.stderr.strip())
            except (OSError, subprocess.TimeoutExpired) as error:
                observation.update(returncode=None, ntstatus_hex=None, stdout='', stderr='',
                                   invocation_error_type=type(error).__name__, invocation_error=str(error))
            absent = not data.exists()
            observation['data_directory_remains_absent'] = absent
            result['arms'][label] = observation
            existing = json.loads(output.read_text(encoding='utf-8'))
            existing['restricted_initdb_preflight'] = result
            json_write(output, existing)
            json_write(EVIDENCE / 'build-proof.json', {'status': 'RESTRICTED_INITDB_PREFLIGHT',
                                                       'dependency_proof': existing})
            require(absent, 'SHOW_PROBE_UNEXPECTED_DATA_CREATION')
        candidate = result['arms']['inherited_acl_candidate']
        require(candidate['returncode'] == 0 and 'VERSION=18.6' in candidate['stderr'],
                'RESTRICTED_INITDB_SHOW_PREFLIGHT_FAILED')
        result['same_run_private_vs_inherited_failure_reproduced'] = (
            result['arms']['private_0700_control']['ntstatus_hex'] == '0xc0000135')
        existing = json.loads(output.read_text(encoding='utf-8'))
        existing['restricted_initdb_preflight'] = result
        json_write(output, existing)
        json_write(EVIDENCE / 'build-proof.json', {'status': 'RESTRICTED_INITDB_PREFLIGHT_PASSED',
                                                   'dependency_proof': existing})
    finally:
        password_file.unlink(missing_ok=True)


def wheel_files(wheel):
    with zipfile.ZipFile(wheel) as source:
        names = [n for n in source.namelist() if not n.endswith('/')]
        require(len(names) == len(set(names)), 'DUPLICATE_WHEEL_ENTRIES')
        return {name: hashlib.sha256(source.read(name)).hexdigest() for name in sorted(names)}


def filtered_requirements(source):
    """No alternate psycopg distribution can enter the fresh application venv."""
    output = []
    excluded = []
    for raw in source.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        require(re.fullmatch(r'[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+', line),
                'ONLY_EXACT_SIMPLE_APPLICATION_REQUIREMENTS_ALLOWED')
        name = re.sub(r'[-_.]+', '-', line.split('==')[0]).lower()
        if name in {'psycopg2', 'psycopg2-binary'}:
            excluded.append(line)
        else:
            output.append(line)
    require(excluded == ['psycopg2-binary==2.9.12'], 'UNEXPECTED_APPLICATION_PSYCOPG_REQUIREMENT')
    return '\n'.join(output) + '\n'


def acceptance_valid(summary):
    try:
        validate_acceptance(summary)
    except (ValueError, KeyError, TypeError):
        return False
    return True


def main():
    require(sys.platform == 'win32', 'ACTUAL_WINDOWS_REQUIRED')
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and
            os.environ.get('GITHUB_REPOSITORY') == 'oxo-ops/dkss', 'DEDICATED_CI_ONLY')
    require(sys.version_info[:2] == (3, 12), 'CPYTHON_3_12_REQUIRED')
    lock = json.loads((HERE / 'client-build-inputs.json').read_text())
    require(not EVIDENCE.exists(), 'NEW_EVIDENCE_DIRECTORY_REQUIRED')
    EVIDENCE.mkdir()
    # Python's Windows mkdir(0700), used by tempfile.mkdtemp, installs a
    # protected Owner/Admin DACL. PostgreSQL deliberately re-executes initdb
    # with Administrators disabled. Use a new ordinary inherited-ACL directory
    # in this disposable CI runner, without changing any existing permissions.
    runner_temp = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    work = runner_temp / ('worlex-pure-client-' + uuid.uuid4().hex)
    work.mkdir()  # Atomic create; never reuse or relax an existing directory.
    work = work.resolve(strict=True)
    require(work.is_relative_to(runner_temp), 'RUNNER_TEMP_ONLY')
    (work / 'OWNER').write_text('WORLEX_WINDOWS_CLIENT_SYNTHETIC_ONLY')
    base = clean_environment()
    base['HOME'] = str(work)
    downloads = work / 'downloads'
    downloads.mkdir()
    pg_archive = downloads / 'postgresql-18.6-binaries.zip'
    fetch(lock['postgresql'], pg_archive)
    extract_zip(pg_archive, work / 'postgresql')
    pg = work / 'postgresql/pgsql'
    pg_bin = pg / 'bin'
    pg_config = pg_bin / 'pg_config.exe'
    require(pg_config.is_file() and (pg / 'include/libpq-fe.h').is_file(), 'OFFICIAL_POSTGRES_BUILD_FILES_REQUIRED')
    require(any((pg / relative).is_file() for relative in ('lib/libpq.lib', 'lib/ms/libpq.lib')),
            'OFFICIAL_POSTGRES_IMPORT_LIBRARY_REQUIRED')
    pg_env = dict(base, PATH=str(pg_bin) + os.pathsep + base['PATH'])
    official_binaries_before = {path.name: sha(path) for path in sorted(pg_bin.iterdir())
                               if path.is_file() and path.suffix.lower() in ('.exe', '.dll')}
    pg_version = run([pg_config, '--version'], env=pg_env, capture=True).stdout.strip()
    require(pg_version == 'PostgreSQL 18.6', 'OFFICIAL_PG_CONFIG_VERSION_MISMATCH')
    inputs = {}
    for entry in [*lock['build_tools'], *lock['pure_client']['packages'], *lock['application_source_wheels']]:
        destination = downloads / entry['filename']
        fetch(entry, destination)
        inputs[entry['filename']] = sha(destination)
    build = work / 'build-venv'
    app = work / 'acceptance-venv'
    run([sys.executable, '-m', 'venv', build], env=base)
    run([sys.executable, '-m', 'venv', app], env=base)
    build_python = build / 'Scripts/python.exe'
    app_python = app / 'Scripts/python.exe'
    run([build_python, '-m', 'pip', 'install', '--no-index', '--no-deps',
         *[downloads / entry['filename'] for entry in lock['build_tools']]], env=base)
    run([build_python, '-m', 'pip', 'check'], env=base)
    # pywebpush's sole sdist-only dependency is handled explicitly. No broad
    # source fallback is enabled for either the app or client.
    require(len(lock['application_source_wheels']) == 1 and
            lock['application_source_wheels'][0]['name'] == 'http-ece' and
            lock['application_source_wheels'][0]['version'] == '1.2.1',
            'ONLY_REVIEWED_HTTP_ECE_SOURCE_BUILD_ALLOWED')
    http_source = work / 'http-ece-source'
    http_source.mkdir()
    http_input = lock['application_source_wheels'][0]
    with tarfile.open(downloads / http_input['filename']) as archive:
        archive.extractall(http_source, filter='data')
    http_source = http_source / 'http_ece-1.2.1'
    require(http_source.is_dir(), 'EXPECTED_HTTP_ECE_SOURCE_DIRECTORY_MISSING')
    http_before = {p.relative_to(http_source).as_posix(): sha(p) for p in http_source.rglob('*')
                   if p.is_file() and p.suffix in {'.py', '.cfg', '.toml'}}
    app_wheels = work / 'application-wheels'
    app_wheels.mkdir()
    run([build_python, '-m', 'pip', 'wheel', '--no-index', '--no-build-isolation',
         '--no-deps', '--wheel-dir', app_wheels, http_source], env=base)
    for relative, expected in http_before.items():
        require(sha(http_source / relative) == expected, 'HTTP_ECE_SOURCE_WAS_MODIFIED')
    http_wheels = list(app_wheels.glob('http_ece-1.2.1-*-none-any.whl'))
    require(len(http_wheels) == 1, 'HTTP_ECE_PURE_PYTHON_WHEEL_REQUIRED')
    http_wheel = http_wheels[0]
    http_files = wheel_files(http_wheel)
    require(not any(name.lower().endswith(('.dll', '.pyd', '.so', '.exe')) for name in http_files),
            'HTTP_ECE_UNEXPECTED_NATIVE_BINARY')
    with zipfile.ZipFile(http_wheel) as archive:
        metadata = [name for name in archive.namelist() if name.endswith('.dist-info/WHEEL')]
        require(len(metadata) == 1 and b'Root-Is-Purelib: true' in archive.read(metadata[0]),
                'HTTP_ECE_PURELIB_METADATA_REQUIRED')
    http_proof = {'name': 'http-ece', 'version': '1.2.1', 'sdist_sha256': http_input['sha256'],
                  'source_unmodified': True, 'pure_python': True,
                  'wheel_filename': http_wheel.name, 'wheel_sha256': sha(http_wheel), 'files': http_files}
    compiler = vc_environment(base)
    runtime_dir = msvc_runtime_directory(compiler)
    # ICU in initdb/postgres needs the Microsoft C++ CRT, which the official PG
    # archive does not ship. Keep its complete installed x64 CRT directory on the
    # fixture server's child PATH only. Never copy/graft DLLs into PostgreSQL or
    # the client wheel, and never expand the application client's isolated PATH.
    original_pg_env = dict(pg_env)
    pg_env['PATH'] = os.pathsep.join([str(pg_bin), str(runtime_dir), base['PATH']])
    pure_wheels = work / 'pure-wheels'
    pure_wheels.mkdir()
    for entry in lock['pure_client']['packages']:
        shutil.copyfile(downloads / entry['filename'], pure_wheels / entry['filename'])
    from verify_client_evidence import validate_pure_wheels
    validate_pure_wheels(lock['pure_client']['packages'], pure_wheels)
    json_write(EVIDENCE / 'dependency-proof.json', {'pure_python_client': True})
    require(official_binaries_before == {path.name: sha(path) for path in sorted(pg_bin.iterdir())
                                        if path.is_file() and path.suffix.lower() in ('.exe', '.dll')},
            'OFFICIAL_POSTGRES_SERVER_BINARIES_CHANGED')
    run([build_python, HERE / 'windows_client_probe.py', 'server-dependencies', work,
         runtime_dir, EVIDENCE / 'dependency-proof.json'], env=base)
    native_loader_preflight(pg_bin, original_pg_env, pg_env, runtime_dir,
                            EVIDENCE / 'dependency-proof.json')
    restricted_initdb_preflight(build_python, work, pg_archive, pg_bin, pg_env, runtime_dir)
    requirements = work / 'requirements-application.txt'
    requirements.write_text(filtered_requirements(REPO / 'requirements.txt'), encoding='utf-8')
    run([app_python, '-m', 'pip', 'install', '--only-binary=:all:', '--find-links', app_wheels,
         '-r', requirements, 'http-ece==1.2.1'], env=base)
    run([app_python, '-m', 'pip', 'install', '--no-index', '--no-deps', *sorted(pure_wheels.glob('*.whl'))], env=base)
    run([app_python, '-m', 'pip', 'check'], env=base)
    test_env = dict(base)
    test_env['PATH'] = str(app_python.parent) + os.pathsep + str(Path(base['SYSTEMROOT']) / 'System32')
    test_env['PYTHONPATH'] = os.pathsep.join([str(PACKAGE), str(PACKAGE / 'tests')])
    test_env['WORLEX_TEST_CA_FILE'] = str(work / 'server.crt')
    test_env['WORLEX_REQUIRE_POSTGRES'] = '1'
    test_env['WORLEX_EVIDENCE_DIR'] = str(EVIDENCE)
    run([app_python, HERE / 'windows_client_probe.py', 'certificates', work], env=test_env)
    password_file = work / 'initdb-password.txt'
    password_file.write_text(PASSWORD, encoding='ascii')
    data = work / 'data'
    require(not data.exists(), 'INITDB_REQUIRES_NEW_DIRECTORY')
    run([pg_bin / 'initdb.exe', '-D', data, '-U', 'restore_ci', '--encoding=UTF8',
         '--locale=C', '--auth-local=scram-sha-256', '--auth-host=scram-sha-256',
         '--pwfile', password_file], env=pg_env)
    password_file.unlink()
    with socket.socket() as free_port:
        free_port.bind(('127.0.0.1', 0))
        port = free_port.getsockname()[1]
    config = ("\nlisten_addresses = '127.0.0.1'\nport = %d\nssl = on\n"
              "ssl_cert_file = '%s'\nssl_key_file = '%s'\n"
              "password_encryption = 'scram-sha-256'\n" %
              (port, (work / 'server.crt').as_posix(), (work / 'server.key').as_posix()))
    # Diagnostics apply only to this newly initialized owned CI cluster.
    config += "log_timezone = 'UTC'\nlog_connections = on\nlog_disconnections = on\n" + PREFIX
    with (data / 'postgresql.conf').open('a', encoding='utf-8') as output:
        output.write(config)
    (data / 'pg_hba.conf').write_text('hostssl all all 127.0.0.1/32 scram-sha-256\nhostnossl all all 127.0.0.1/32 reject\n', encoding='ascii')
    def start_owned_server():
        run([pg_bin / 'pg_ctl.exe', '-D', data, '-l', work / 'server.log', '-w', '-t', '60', 'start'], env=pg_env)

    def cleanup_owned_server():
        # A failed start can still leave this exact owned server alive.
        require((work / 'OWNER').read_text() == 'WORLEX_WINDOWS_CLIENT_SYNTHETIC_ONLY', 'OWNERSHIP_LOST')
        status = subprocess.run([str(pg_bin / 'pg_ctl.exe'), '-D', str(data), 'status'],
                                env=pg_env, cwd=REPO, timeout=30, capture_output=True)
        require(status.returncode in (0, 3), 'OWNED_SERVER_STATUS_UNCERTAIN')
        if status.returncode == 0:
            run([pg_bin / 'pg_ctl.exe', '-D', data, '-m', 'fast', '-w', 'stop'], env=pg_env)

    def cleanup_owned_secrets():
        for path in (work / 'server.key', password_file):
            if path.exists():
                path.unlink()

    with owned_server_lifecycle(work, os.environ['RUNNER_TEMP'], EVIDENCE,
                                start=start_owned_server, cleanup=cleanup_owned_server,
                                secrets_cleanup=cleanup_owned_secrets):
        run([app_python, HERE / 'windows_client_probe.py', 'probe', work, str(port), pure_wheels, EVIDENCE], env=test_env)
        test_env['WORLEX_TEST_POSTGRES_URL'] = (
            f'postgresql+pg8000://restore_ci:{PASSWORD}@127.0.0.1:{port}/dkss_restore_ci')
        run([app_python, PACKAGE / 'tests/run_acceptance.py'], env=test_env, timeout=1800)
        run([app_python, HERE / 'windows_client_probe.py', 'stability', work, str(port), pure_wheels, EVIDENCE], env=test_env, timeout=360)
        runtime = json.loads((EVIDENCE / 'runtime-proof.json').read_text())
        policy = json.loads((EVIDENCE / 'provisional-policy.json').read_text())
        require(acceptance_valid(policy['acceptance_summary']), 'FULL_WINDOWS_ACCEPTANCE_REQUIRED')
        commit = run(['git', 'rev-parse', 'HEAD'], capture=True).stdout.strip()
        require(commit == os.environ['GITHUB_SHA'], 'CHECKOUT_COMMIT_MISMATCH')
        (EVIDENCE / 'commit.txt').write_text(commit + '\n', encoding='ascii')
        build_proof = {'source_inputs_sha256': inputs,
                       'postgres_archive_sha256': sha(pg_archive),
                       'pg_config_version': pg_version,
                       'pure_client_verified': True, 'no_native_client_payload': True,
                       'pip_check_passed': True,
                       'application_source_wheels': [http_proof],
                       'dependency_proof': json.loads((EVIDENCE / 'dependency-proof.json').read_text())}
        json_write(EVIDENCE / 'build-proof.json', build_proof)
        proof = {'schema_version': 2, 'passed': True, 'actual_windows': True,
                 'synthetic_only': True, 'candidate_commit': commit,
                 'runner_sha256': sha(PACKAGE / 'worlex_restore.py'),
                 'client_profile': 'pg8000-pure-python', 'package_version': '1.31.6',
                 'wheels': runtime['wheels'], 'wheel_files': runtime['wheel_files'],
                 'imported_modules': runtime['imported_modules'],
                 'ssl_runtime': runtime['ssl_runtime'], 'tls': runtime['tls'],
                 'build_proof': build_proof,
                 'acceptance_summary': policy['acceptance_summary'],
                 'full_table_acceptance': policy['full_table_acceptance'],
                 'disconnect_acceptance': policy['disconnect_acceptance'],
                 'tested_artifacts': policy['tested_artifacts'],
                 'workflow_sha256': policy['workflow_sha256'],
                 'stability': json.loads((EVIDENCE / 'stability-proof.json').read_text())}
        shutil.copytree(pure_wheels, EVIDENCE / 'pure-wheels')
        app_artifacts = EVIDENCE / 'application-wheels'
        app_artifacts.mkdir()
        shutil.copyfile(http_wheel, app_artifacts / http_wheel.name)
        from verify_client_evidence import validate_client
        profile = validate_client(proof, policy, PACKAGE, EVIDENCE, commit)
        operational = work / 'operational-smoke'
        operational.mkdir()
        for name in ('worlex_restore.py', 'client_runtime_guard.py', 'client_bootstrap.py', 'client_connection.py', 'inspect_observation.py', 'preservation_scope.py', 'launcher_adapter.py', 'source-counts.json'):
            shutil.copyfile(PACKAGE / name, operational / name)
        # Synthetic-only guard fixture, never published as a usable policy.
        smoke_policy = dict(policy, windows_client_acceptance_passed=True,
                            windows_client_acceptance=profile, tested_commit=commit)
        json_write(operational / 'policy.json', smoke_policy)
        for wheel in sorted(pure_wheels.glob('*.whl')):
            extract_zip(wheel, operational / 'client-sidecar')
        run([app_python, '-I', '-B', HERE / 'windows_client_probe.py', 'sidecar', work,
             operational, operational / 'policy.json', EVIDENCE / 'sidecar-proof.json'], env=test_env)
        bootstrap = run([app_python, '-I', '-B', operational / 'client_bootstrap.py',
                         'worlex_restore.py', '--help'], env=test_env, capture=True)
        require('usage:' in bootstrap.stdout.lower(), 'ISOLATED_BOOTSTRAP_HELP_SMOKE_FAILED')
        sidecar = json.loads((EVIDENCE / 'sidecar-proof.json').read_text())
        sidecar['isolated_bootstrap_passed'] = True
        json_write(EVIDENCE / 'sidecar-proof.json', sidecar)
        proof['sidecar'] = sidecar
        json_write(EVIDENCE / 'client-proof.json', proof)


if __name__ == '__main__':
    main()
