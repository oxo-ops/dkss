"""Recovery Web isolates OCR while retaining required application startup hooks."""
import os
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class RecoveryProfileTests(unittest.TestCase):
    def test_profile_disables_web_wakeups_even_with_old_enabled_setting(self):
        with patch.dict(os.environ, {'DOCUMENT_IMPORT_WORKER_ENABLED': '1'}):
            config = runpy.run_path(str(Path(__file__).resolve().parents[1]/'gunicorn.conf.py'))
            self.assertEqual(os.environ['DOCUMENT_IMPORT_WORKER_ENABLED'], '0')
            from dkss_app.document_import_worker import start_worker
            with patch('dkss_app.document_import_worker.threading.Thread') as thread:
                start_worker(SimpleNamespace(testing=False, extensions={}))
                thread.assert_not_called()
            self.assertEqual(config['graceful_timeout'], 30)

    def test_web_keeps_existing_initializers_but_does_not_start_ocr(self):
        app = object()
        with patch.dict(os.environ), patch('dkss_app.driving_access.initialize_driving_access') as driving, \
                patch('dkss_app.vehicle_couplings.initialize_coupling_schema') as coupling, \
                patch('dkss_app.document_import_worker.start_worker') as start:
            config = runpy.run_path(str(Path(__file__).resolve().parents[1]/'gunicorn.conf.py'))
            os.environ['DOCUMENT_IMPORT_WORKER_ENABLED'] = '1'  # Gunicorn cfg.env reapplied
            config['post_worker_init'](SimpleNamespace(wsgi=app))
            self.assertEqual(os.environ['DOCUMENT_IMPORT_WORKER_ENABLED'], '0')
            driving.assert_called_once_with(app)
            coupling.assert_called_once_with(app)
            start.assert_not_called()


class RecoveryCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_workflow_regressions import WorkflowRegressionTests
        cls.fixture = WorkflowRegressionTests
        cls.fixture.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def test_explicit_cli_uses_same_app_even_when_web_worker_is_disabled(self):
        app = self.fixture.m.app
        with patch.dict(os.environ, {'DOCUMENT_IMPORT_WORKER_ENABLED': '0'}), \
                patch('signal.signal'), patch('dkss_app.document_import_worker.run_worker') as run:
            result = app.test_cli_runner().invoke(args=['document-import-worker'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(run.call_count, 1)
            self.assertIs(run.call_args.args[0], app)
            self.assertFalse(run.call_args.args[1].is_set())

