"""Non-exporting independent validation. Child output/trace values are discarded.

Only source identifiers, stage names, method names, counts and booleans escape.
Generated result JSON and whole-app SQLite snapshots stay in one private temp
folder, removed on exit. This is not an exporter for any earlier fixture.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

STAGES = {'generate', 'guarded-active', 'guarded-held', 'guarded-pending',
          'new-active', 'new-held', 'new-pending', 'retention', 'postgres', 'runner'}


def tree(root):
    content = b''
    for _, path in sorted((p.name + ('/' if p.is_dir() else ''), p) for p in root.iterdir()
                          if p.name not in {'.git', '__pycache__'}):
        if path.is_dir():
            mode, digest = '40000', tree(path)
        else:
            data = path.read_bytes()
            mode, digest = '100644', hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        content += mode.encode() + b' ' + path.name.encode() + b'\0' + bytes.fromhex(digest)
    return hashlib.sha1(b'tree ' + str(len(content)).encode() + b'\0' + content).hexdigest()


def verify_child_isolation():
    guard = sys.modules.get('sitecustomize')
    expected = Path(__file__).resolve().parent / 'guarded_independent_guard' / 'sitecustomize.py'
    if (guard is None or Path(guard.__file__).resolve() != expected
            or getattr(guard, 'GUARDED_INDEPENDENT_AUDIT', None) != 'private-sqlite-q08-loopback-v1'):
        raise RuntimeError('CHILD_ISOLATION_MISSING')
    root = Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
    def rejected(event, *args):
        try:
            sys.audit(event, *args)
        except RuntimeError:
            return
        raise AssertionError('BOUNDARY_NOT_REJECTED')
    # These emit audit events only. No socket, listener, DNS lookup or DB is opened.
    rejected('socket.connect', None, ('192.0.2.1', 443))
    rejected('socket.getaddrinfo', 'example.invalid', 443)
    rejected('socket.bind', None, ('127.0.0.1', 0))
    rejected('sqlite3.connect', str(root.parent / 'outside-private-root.sqlite'))
    rejected('sqlite3.connect', 'file:' + str(root / 'uri.sqlite'))
    sys.audit('sqlite3.connect', str(root / 'allowed-private.sqlite'))
    rejected('socket.connect', None, ('127.0.0.1', 5433))
    if os.environ.get('Q08_POSTGRES_TEST_URL'):
        sys.audit('socket.connect', None, ('127.0.0.1', 5432))
        sys.audit('socket.getaddrinfo', 'localhost', 5432)
    else:
        rejected('socket.connect', None, ('127.0.0.1', 5432))
    return True


def child(stage):
    # OS descriptor suppression covers libraries, logger handlers and unhandled
    # SQL errors whose messages can contain bound JSON. Do this before app import.
    output = os.dup(1)
    null = os.open(os.devnull, os.O_RDWR)
    os.dup2(null, 1)
    os.dup2(null, 2)
    os.close(null)
    result = {'stage': stage, 'passed': False, 'isolation_verified': False}
    try:
        result['isolation_verified'] = verify_child_isolation()
        script_tests = Path(__file__).resolve().parent
        sys.path[:] = [p for p in sys.path if p and Path(p).resolve() != script_tests] + [str(script_tests)]
        if stage not in STAGES:
            raise RuntimeError('UNKNOWN_STAGE')
        from guarded_independent_cases import generate, run_roundtrip
        if stage == 'generate':
            generate()
            result.update(passed=True, cases=6, pending_reservation_verified=True)
        elif stage.startswith('guarded-') or stage.startswith('new-'):
            run_roundtrip(stage.split('-')[1], stage.startswith('new-'))
            result.update(passed=True, database_unchanged=True, semantics_verified=True)
        else:
            loader = unittest.TestLoader()
            module = 'test_guarded_independent_runner' if stage == 'runner' else 'test_guarded_rollback_' + stage
            suite = loader.loadTestsFromName(module)
            wanted = {'runner':5, 'retention':25, 'postgres':24}[stage]
            count = suite.countTestCases()
            if loader.errors or count != wanted:
                raise RuntimeError('TEST_DISCOVERY_FAILED')
            outcome = unittest.TestResult()
            suite.run(outcome)
            # Never format errors, failures, subtest parameters or object values.
            result.update(tests=count, executed=outcome.testsRun, skipped=len(outcome.skipped),
                failures=len(outcome.failures), errors=len(outcome.errors),
                passed=outcome.wasSuccessful() and outcome.testsRun == wanted and not outcome.skipped and not outcome.expectedFailures,
                failed_methods=[type(case).__name__ + '.' + getattr(case, '_testMethodName', 'class_setup')
                                for case, _ in outcome.failures + outcome.errors])
    except BaseException:
        result['harness_failed'] = True
    os.write(output, (json.dumps(result, sort_keys=True) + '\n').encode())
    os.close(output)
    os._exit(0 if result['passed'] else 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', choices=sorted(STAGES))
    parser.add_argument('--producer', type=Path)
    parser.add_argument('--postgres', action='store_true')
    args = parser.parse_args()
    if args.child:
        child(args.child)
    from guarded_independent_cases import PRODUCER, PRODUCER_TREE
    producer = args.producer.resolve()
    candidate = Path(__file__).resolve().parents[1]
    if producer == candidate or tree(producer) != PRODUCER_TREE:
        raise RuntimeError('IMMUTABLE_PRODUCER_TREE_REQUIRED')
    # New data never lives below either checkout or artifact output directory.
    parent = os.environ.get('DKSS_VALIDATION_TMP')
    if args.postgres and os.environ.get('GUARDED_PG_LOGGING_VERIFIED') != '1':
        raise RuntimeError('DISPOSABLE_POSTGRES_LOGGING_NOT_VERIFIED')
    results = []
    with tempfile.TemporaryDirectory(prefix='guarded-independent-', dir=parent) as temp:
        if Path(temp).resolve().is_relative_to(candidate) or Path(temp).resolve().is_relative_to(producer):
            raise RuntimeError('PRIVATE_TEMP_MUST_BE_OUTSIDE_CHECKOUTS')
        env = dict(os.environ, GUARDED_INDEPENDENT_TMP=temp, TMPDIR=temp)
        env.update(FLASK_SKIP_DOTENV='1', DATABASE_URL='sqlite:///:memory:',
            OPENAI_API_KEY='', SMTP_HOST='', S3_BUCKET_NAME='', VAPID_PRIVATE_KEY='',
            VAPID_PUBLIC_KEY='', RENDER='', DOCUMENT_IMPORT_WORKER_ENABLED='0',
            AWS_EC2_METADATA_DISABLED='true', AWS_CONFIG_FILE=os.devnull,
            AWS_SHARED_CREDENTIALS_FILE=os.devnull, RATELIMIT_STORAGE_URI='memory://')
        env.pop('ROLLBACK_FIXTURE_ROOT', None)
        if not args.postgres:
            env.pop('Q08_POSTGRES_TEST_URL', None)
        # Strip the guarded checkout from producer import paths; retain only the
        # interpreter's installed package overlay and isolation audit guard.
        original_paths = os.environ.get('PYTHONPATH', '').split(os.pathsep)
        extras = [p for p in original_paths if p and not Path(p).resolve().is_relative_to(candidate)]
        stages = ['runner', 'generate', 'retention']
        if args.postgres:
            stages.append('postgres')
        stages += ['guarded-active', 'guarded-held', 'guarded-pending',
                   'new-active', 'new-held', 'new-pending']
        for stage in stages:
            source = producer if stage == 'generate' or stage.startswith('new-') else candidate
            guard = candidate / 'tests' / 'guarded_independent_guard'
            env['PYTHONPATH'] = os.pathsep.join([str(guard)] + extras + [str(source), str(source/'tests')])
            # Running this script by path makes its own test folder importable.
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child', stage],
                cwd=source, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            try:
                data = json.loads(completed.stdout)
                assert data.get('stage') == stage
            except (ValueError, AssertionError):
                data = {'stage': stage, 'passed': False, 'safe_child_output': False}
            results.append(data)
            if completed.returncode or not data.get('passed'):
                break
    summary = {'producer_commit': PRODUCER, 'producer_tree': PRODUCER_TREE,
               'stages': results, 'passed': len(results) == len(stages) and all(r['passed'] for r in results),
               'generated_content_exported': False, 'temporary_databases_removed': True,
               'postgres_requested': args.postgres,
               'postgres_logging_verified': bool(args.postgres and os.environ.get('GUARDED_PG_LOGGING_VERIFIED') == '1')}
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    try:
        code = main()
    except BaseException:
        print(json.dumps({'passed':False, 'controller_failed':True}))
        code = 1
    raise SystemExit(code)
