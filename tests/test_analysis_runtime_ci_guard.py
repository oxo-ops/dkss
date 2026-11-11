"""Pure checks for the acceptance URL/environment boundary, never connects."""
import unittest
import importlib.util
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from analysis_runtime_ci_support import URL, validate_service_url


class AnalysisRuntimeCIGuardTests(unittest.TestCase):
    def test_exact_owned_job_and_url_are_required(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'oxo-ops/dkss'}
        self.assertEqual(validate_service_url(URL, env).database, 'dkss_analysis_runtime_ci')
        for bad in ({}, {**env, 'GITHUB_REPOSITORY': 'other/repo'}, {**env, 'PGSERVICE': 'production'}):
            with self.assertRaises(RuntimeError): validate_service_url(URL, bad)
        for bad in (URL+'?host=external.invalid', URL+'?hostaddr=192.0.2.1', URL+'?service=production',
                    URL.replace('127.0.0.1', 'external.invalid'), URL.replace('dkss_analysis_runtime_ci', 'production'),
                    URL.replace('analysis-runtime-disposable-ci-only', 'other'), URL.replace(':5432', ':5433')):
            with self.assertRaises(RuntimeError): validate_service_url(bad, env)


    def test_ci_wsgi_app_serves_ordinary_login_without_bypassing_auth(self):
        from dkss_app import common, analysis_worker
        from dkss_app.extensions import db
        with tempfile.TemporaryDirectory(prefix='analysis-ci-wsgi-') as directory:
            env = {'SECRET_KEY': 'synthetic-wsgi-test', 'RENDER': '', 'RATELIMIT_STORAGE_URI': 'memory://',
                'DATABASE_URL': 'sqlite:///:memory:', 'ANALYSIS_RUNTIME_POSTGRES_TEST_URL': 'synthetic-replaced',
                'ANALYSIS_RUNTIME_CASE': 'test_ci_login', 'ANALYSIS_RUNTIME_CI_GUARD_LOADED': '1',
                'OPENAI_API_KEY': '', 'S3_BUCKET_NAME': '', 'SMTP_HOST': '',
                'VAPID_PRIVATE_KEY': '', 'VAPID_PUBLIC_KEY': '', 'VEHICLE_ANALYSIS_WORKER_ENABLED': '0'}
            source = Path(__file__).with_name('analysis_runtime_ci_app.py')
            spec = importlib.util.spec_from_file_location('analysis_ci_app_test_only', source)
            module = importlib.util.module_from_spec(spec)
            with patch.dict(os.environ, env), \
                    patch('analysis_runtime_ci_support.acceptance_root', return_value=Path(directory)), \
                    patch('analysis_runtime_ci_support.verify_owned_service', return_value='sqlite:///:memory:'), \
                    patch('analysis_runtime_ci_support.CONNECT_ARGS', {}), \
                    patch.object(common, 'analyze_vehicle_karte', common.analyze_vehicle_karte), \
                    patch.object(analysis_worker, 'INTERVAL_SECONDS', analysis_worker.INTERVAL_SECONDS):
                spec.loader.exec_module(module)
                client = module.app.test_client()
                response = client.get('/login')
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'<form', response.data)
                protected = client.get('/vehicle/karte/1/analysis/result')
                self.assertEqual(protected.status_code, 302)
                self.assertTrue(protected.headers['Location'].endswith('/login'))
                self.assertEqual(client.get('/__ci_analysis_health').status_code, 404)
                self.assertFalse(list(Path(directory).rglob('calls.jsonl')))
                self.assertNotIn('vehicle_analysis_worker', module.app.extensions)
                with module.app.app_context():
                    db.session.remove(); db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
