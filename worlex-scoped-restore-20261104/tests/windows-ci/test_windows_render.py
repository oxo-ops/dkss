"""Actual Windows-only synthetic A/B test. Never accepts a real archive input."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

BASE_COMMIT = 'e838e65949e5fde3eb996979ae08029bc429b8ef'
BASE_SHA = '5b09871233af743c487ba535eb444e768bad813ba1d2e6a759efd4f9ef16d7a4'
PACKAGE = Path('worlex-scoped-restore-20261104')
EVIDENCE = Path('windows-evidence')
FIXTURE = Path('windows-fixture/synthetic.tar.gz')
MARKER = b'WINDOWS_RENDER_SYNTHETIC_ONLY_20261104'
REAL_RUN = subprocess.run


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render(module, label, binary):
    calls = []
    work = EVIDENCE / (label + ' directory with spaces')
    work.mkdir()
    def record(args, **kwargs):
        # Observe the exact production renderer invocation, do not alter it.
        if any(x in args for x in ('--dbname', '-d')):
            raise AssertionError('Database destination prohibited')
        result = REAL_RUN(args, **kwargs)
        calls.append({'argv': args, 'env_keys': sorted(kwargs.get('env', {})),
                      'returncode': result.returncode,
                      'stderr': result.stderr.decode('utf-8', errors='replace')})
        return result
    module.ARCHIVE_SHA256 = sha(FIXTURE)  # Synthetic fixture only, in memory.
    module.subprocess.run = record
    try:
        output = module.render_archive(FIXTURE, binary, work)
        assert MARKER in output.read_bytes(), 'Synthetic marker absent'
        manifest = json.loads(FIXTURE.with_name('fixture-manifest.json').read_text())
        assert module.copy_digest(output) == manifest['copy_sha256'], 'COPY digest mismatch'
        rows, columns = module.read_copy(output)
        assert columns == {'synthetic_render_fixture': ['id', 'company_code', 'marker', 'payload']}
        assert rows == {'synthetic_render_fixture': [{'id': '1', 'company_code': 'WORLEX', 'marker': MARKER.decode(), 'payload': 'line1\nline2\t\\slash'}]}
        outcome = {'ok': True, 'sql_sha256': sha(output), 'copy_sha256': module.copy_digest(output), 'parsed_rows_verified': True}
    except Exception as exc:
        outcome = {'ok': False, 'exception': type(exc).__name__, 'error': str(exc)}
    finally:
        module.subprocess.run = REAL_RUN
    outcome['calls'] = calls
    outcome['runner_sha256'] = sha(module.__file__)
    return outcome


def main():
    if sys.platform != 'win32':
        raise SystemExit('Actual Windows runner required; emulation is not evidence')
    EVIDENCE.mkdir()
    binary = Path(sys.argv[1]).resolve(strict=True)
    manifest = json.loads(FIXTURE.with_name('fixture-manifest.json').read_text())
    assert manifest['kind'] == 'synthetic-only' and manifest['archive_sha256'] == sha(FIXTURE)
    with tarfile.open(FIXTURE) as archive:
        assert {p.name.rsplit('/', 1)[0] for p in archive if p.isfile()} == {'synthetic:2026-11-04'}
    original_bytes = REAL_RUN(['git', 'show', f'{BASE_COMMIT}:{PACKAGE.as_posix()}/worlex_restore.py'],
                             check=True, capture_output=True).stdout
    assert hashlib.sha256(original_bytes).hexdigest() == BASE_SHA
    original_path = EVIDENCE / 'original_runner.py'
    original_path.write_bytes(original_bytes)
    # Hostile inherited libpq values must never reach either renderer subprocess.
    os.environ.update({'PGHOST': 'must-not-connect.invalid', 'PGPORT': '1',
                       'PGDATABASE': 'never_connect', 'PGUSER': 'never_connect',
                       'PGPASSWORD': 'synthetic-poison-only', 'PGSERVICE': 'never_connect',
                       'PGSERVICEFILE': 'does-not-exist', 'PGPASSFILE': 'does-not-exist'})
    version = REAL_RUN([str(binary), '--version'], check=True, capture_output=True).stdout.decode().strip()
    assert '18.6' in version, version
    original = render(load(original_path, 'original'), 'control', binary)
    candidate = render(load(PACKAGE / 'worlex_restore.py', 'candidate'), 'candidate', binary)
    reproduced = (not original['ok'] and original['error'] == 'OFFLINE_RENDER_FAILED'
                  and len(original['calls']) == 1 and original['calls'][0]['returncode'] == 1)
    forbidden = {'PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD', 'PGSERVICE', 'PGSERVICEFILE', 'PGPASSFILE'}
    isolated = len(candidate['calls']) == 1 and not forbidden.intersection(candidate['calls'][0]['env_keys'])
    passed = reproduced and candidate['ok'] and isolated
    summary = {'passed': passed, 'actual_windows': True, 'platform': sys.platform,
               'python_version': sys.version, 'original_commit': BASE_COMMIT,
               'candidate_commit': REAL_RUN(['git', 'rev-parse', 'HEAD'], check=True, capture_output=True).stdout.decode().strip(),
               'pg_restore_version': version, 'pg_restore_sha256': sha(binary),
               'original_failure_reproduced': reproduced, 'candidate_environment_isolated': isolated,
               'fixture': manifest, 'original': original, 'candidate': candidate}
    (EVIDENCE / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))  # All input and stderr are exclusively synthetic.
    if not passed:
        raise SystemExit('Windows A/B gate failed; do not claim reproduction or seal policy')


if __name__ == '__main__':
    main()
