"""Require every official acceptance case to execute, without implicit skips."""
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import sys
import unittest

from analysis_runtime_ci_support import acceptance_root, verify_owned_service

ROOT = acceptance_root()
assert os.environ.get('ANALYSIS_RUNTIME_CI_GUARD_LOADED') == '1'
verify_owned_service(os.environ['ANALYSIS_RUNTIME_POSTGRES_TEST_URL'], os.environ)
repo = Path(__file__).resolve().parents[1]
pins = [line.strip().split('==') for line in (repo/'requirements.txt').read_text().splitlines() if '==' in line]
assert all(metadata.version(name) == version for name, version in pins)
modules = ['test_analysis_runtime_ci_guard', 'test_analysis_worker_postgres', 'test_analysis_runtime_gunicorn']
suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
expected = 14  # 2 guard/WSGI checks + 7 PostgreSQL + 5 real Gunicorn cases.
assert suite.countTestCases() == expected, suite.countTestCases()
result = unittest.TextTestRunner(verbosity=2).run(suite)
report = {'expected': expected, 'run': result.testsRun, 'skipped': len(result.skipped),
    'failures': len(result.failures), 'errors': len(result.errors), 'pins_verified': len(pins),
    'real_ai': False, 'disposable_postgres': True}
(ROOT/'acceptance.json').write_text(json.dumps(report, indent=2)+'\n')
print('ANALYSIS_RUNTIME_ACCEPTANCE', json.dumps(report), flush=True)
sys.exit(0 if result.wasSuccessful() and result.testsRun == expected and not result.skipped else 1)
