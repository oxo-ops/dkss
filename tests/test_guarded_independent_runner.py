"""Test only the non-export boundary, with a new literal sentinel, no app data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class IndependentRunnerOutputTests(unittest.TestCase):
    def run_child(self, fail, missing_guard=False):
        script = Path(__file__).with_name('run_guarded_independent.py')
        code = '''import runpy,sys,types
scope=runpy.run_path(sys.argv[1])
module=types.ModuleType('guarded_independent_cases')
def generate():
 print('synthetic-output-boundary-sentinel')
 print('synthetic-output-boundary-sentinel',file=sys.stderr)
 if sys.argv[2]=='1':raise ValueError('synthetic-output-boundary-sentinel')
module.generate=generate
module.run_roundtrip=lambda *args:None
sys.modules['guarded_independent_cases']=module
scope['child']('generate')
'''
        value = subprocess.run([sys.executable] + (['-S'] if missing_guard else []) + ['-c', code, str(script), '1' if fail else '0'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertNotIn('synthetic-output-boundary-sentinel', value.stdout + value.stderr)
        self.assertEqual(value.stderr, '')
        payload = json.loads(value.stdout)
        self.assertEqual(set(payload), {'stage', 'passed', 'isolation_verified', 'harness_failed'} if fail or missing_guard else {'stage', 'passed', 'isolation_verified', 'cases', 'pending_reservation_verified'})
        self.assertEqual(payload['passed'], not (fail or missing_guard))
        self.assertEqual(value.returncode, 1 if fail or missing_guard else 0)
        self.assertEqual(payload['isolation_verified'], not missing_guard)

    def test_failed_child_does_not_export_trace_or_values(self):
        self.run_child(True)

    def test_successful_child_discards_application_stdout_and_stderr(self):
        self.run_child(False)

    def test_missing_child_guard_refuses_before_application_generation(self):
        self.run_child(False, missing_guard=True)

    def test_each_child_checks_transport_and_sqlite_pg_audit_boundaries(self):
        from run_guarded_independent import verify_child_isolation
        self.assertTrue(verify_child_isolation())

    def test_roundtrip_bootstraps_without_an_ambient_session_key(self):
        from guarded_independent_cases import roundtrip_app
        from dkss_app.extensions import db
        with patch.dict(os.environ), tempfile.TemporaryDirectory() as root:
            os.environ.pop('SECRET_KEY', None)
            target = Path(root) / 'bootstrap.sqlite'
            app = roundtrip_app(target)
            self.assertTrue(app.testing)
            self.assertTrue(app.secret_key)
            self.assertNotIn('SECRET_KEY', os.environ)
            self.assertEqual(app.config['SQLALCHEMY_DATABASE_URI'], 'sqlite:///' + str(target))
            with app.app_context():
                self.assertEqual(db.engine.dialect.name, 'sqlite')
                db.engine.dispose()
