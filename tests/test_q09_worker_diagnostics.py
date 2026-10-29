"""Queue-loop diagnostics must classify failures without serializing their payload."""
import threading
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from dkss_app.document_import_worker import run_worker
import test_document_import_queue as queue_fixtures


class HeartbeatDiagnosticsTests(unittest.TestCase):
    setUpClass = classmethod(queue_fixtures.DocumentImportQueueTests.setUpClass.__func__)
    tearDownClass = classmethod(queue_fixtures.DocumentImportQueueTests.tearDownClass.__func__)
    setUp = queue_fixtures.DocumentImportQueueTests.setUp
    tearDown = queue_fixtures.DocumentImportQueueTests.tearDown
    send = queue_fixtures.DocumentImportQueueTests.send
    status = queue_fixtures.DocumentImportQueueTests.status

    def test_lease_heartbeat_failure_does_not_log_payload_or_lose_result(self):
        from dkss_app import document_import_queue as queue, vehicle_imports
        from test_inspection_document_ai import extraction
        receipt = self.send().json
        failed = threading.Event()
        original_event = threading.Event

        class FastHeartbeatEvent(original_event):
            def wait(self, timeout=None):
                return super().wait(0.001 if timeout == 15 else timeout)

        def renew(*args):
            failed.set()
            raise RuntimeError('Q09_SYNTHETIC_HEARTBEAT_PRIVATE')

        def extract(source, **kwargs):
            self.assertTrue(failed.wait(5), 'The real heartbeat thread must run')
            return extraction(source)

        with patch('threading.Event', FastHeartbeatEvent), \
                patch.object(queue, 'renew', side_effect=renew), \
                patch.object(vehicle_imports, 'vehicle_document_extractor', return_value=extract), \
                patch.object(queue, 'detect_document_types', return_value={
                    'types': ['inspection'], 'certainty': 'clear', 'supported': True}), \
                self.assertLogs(self.m.app.logger, level='ERROR') as logs:
            self.assertTrue(queue.process_one(self.m.app))
        output = '\n'.join(logs.output)
        self.assertNotIn('Q09_SYNTHETIC_HEARTBEAT_PRIVATE', output)
        self.assertIn('OCR_JOB_HEARTBEAT_FAILED', output)
        self.assertIn('error_type=RuntimeError', output)
        self.assertTrue(all(record.exc_info is None for record in logs.records))
        self.assertEqual(self.status(receipt)['succeeded'], 1)


class WorkerDiagnosticsTests(unittest.TestCase):
    def test_iteration_failure_omits_exception_payload_and_recovers(self):
        app = Flask('q09-isolated-diagnostics')
        stopped = threading.Event()
        synthetic_private_value = 'Q09_SYNTHETIC_PRIVATE_DO_NOT_LOG'
        calls = []

        def process(_app):
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError(synthetic_private_value)
            stopped.set()
            return True

        database = MagicMock()
        database.session.query.return_value.group_by.return_value.all.return_value = []
        wake = MagicMock()
        with patch('dkss_app.document_import_queue.process_one', side_effect=process), \
                patch('dkss_app.document_import_worker.db', database), \
                patch('dkss_app.document_import_worker.memory_mb', return_value=(0, 0)), \
                self.assertLogs(app.logger, level='INFO') as logs:
            run_worker(app, stopped, wake)
        output = '\n'.join(logs.output)
        self.assertNotIn(synthetic_private_value, output)
        self.assertIn('OCR_WORKER_ITERATION_FAILED error_type=RuntimeError', output)
        self.assertIn('OCR_WORKER_HEARTBEAT', output)
        self.assertTrue(all(record.exc_info is None for record in logs.records))
        self.assertEqual(len(calls), 2, 'A failed iteration must not stop later work')
        database.session.rollback.assert_called_once()


if __name__ == '__main__':
    unittest.main()
