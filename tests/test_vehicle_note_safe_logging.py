"""Vehicle note failure confidentiality and rollback on disposable SQLite."""
import unittest
from unittest.mock import patch
from sqlalchemy.exc import OperationalError, IntegrityError
import test_workflow_regressions as workflow
from test_invoice_review_safe_logging import captured_errors


class VehicleNoteSafeLoggingTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def post_note(self, content, version):
        return self.client.post(f'/vehicle/karte/{self.vehicle.id}/note',
                                data={'content': content, 'version': version})

    def exercise_failure(self, existing=False, conflict=False):
        if existing:
            self.assertEqual(self.post_note('Original note', 0).status_code, 302)
        version = 1 if existing else 0
        canaries = ('SYNTHETIC_PRIVATE_NOTE', 'SYNTHETIC_SQL', 'SYNTHETIC_DRIVER_SECRET')
        error_type = IntegrityError if conflict else OperationalError
        def fail_after_flush():
            self.m.db.session.flush()
            raise error_type(canaries[1], {'content': canaries[0]}, RuntimeError(canaries[2]))
        with captured_errors(self.m.app.logger) as (records, rendered), \
                patch.object(self.m.db.session, 'commit', side_effect=fail_after_flush), \
                patch.object(self.m.db.session, 'rollback', wraps=self.m.db.session.rollback) as rollback:
            response = self.post_note(canaries[0], version)
        self.assertEqual(response.status_code, 409 if conflict else 500)
        self.assertEqual(rollback.call_count, 1)
        rows = self.m.VehicleKarteNote.query.all()
        self.assertEqual(len(rows), 1 if existing else 0)
        if existing:
            self.assertEqual((rows[0].content, rows[0].version), ('Original note', 1))
        for canary in canaries:
            self.assertNotIn(canary, '\n'.join(rendered) + response.get_data(as_text=True))
        self.assertEqual(len(records), 0 if conflict else 1)
        if not conflict:
            self.assertEqual(records[0].getMessage(), 'VEHICLE_NOTE_SAVE_FAILED error_type=database')
            self.assertIsNone(records[0].exc_info)
            self.assertIsNone(records[0].stack_info)
        self.assertEqual(self.post_note('Retry note', version).status_code, 302)
        row = self.m.VehicleKarteNote.query.one()
        self.assertEqual((row.content, row.version), ('Retry note', version + 1))

    def test_new_note_failure_is_private_and_retryable(self):
        self.exercise_failure()

    def test_existing_note_failure_preserves_content_and_version(self):
        self.exercise_failure(existing=True)

    def test_integrity_conflict_remains_private(self):
        self.exercise_failure(conflict=True)
