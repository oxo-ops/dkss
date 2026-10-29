"""Independent PostgreSQL checkpoints for an unregistered receipt's owner generation."""
import json
import unittest
from unittest.mock import patch

import test_workflow_regressions as workflow
import test_q02_import_worker_access as worker
from dkss_app import document_import_queue as queue, vehicle_imports
from test_inspection_document_ai import extraction
from q10_postgres_support import PostgresFixture


class PostgresImportGenerationAcceptance(PostgresFixture, unittest.TestCase):
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown
    enqueue = worker.Q02ImportWorkerAccessTests.enqueue
    owner = worker.Q02ImportWorkerAccessTests.owner
    test_same_account_normal_processing = worker.Q02ImportWorkerAccessTests.test_current_admin_can_still_process_a_queued_document

    def replace_with_different_person(self):
        with self.m.app.app_context():
            old = self.owner()
            old_identity = old.account_identity
            self.m.db.session.delete(old)
            self.m.db.session.flush()
            new = self.m.User(company_code='TEST', username='admin', role='admin',
                password='unused', last_name='Different synthetic person',
                password_changed_at='2026-10-27 10:00:00')
            self.m.db.session.add(new)
            self.m.db.session.commit()
            new_identity = new.account_identity
        self.assertNotEqual(old_identity, new_identity)
        with self.client.session_transaction() as state:
            state.update(company_code='TEST', username='admin', role='admin',
                account_identity=new_identity, password_changed_at='2026-10-27 10:00:00')
        self.m.db.session.expire_all()

    def process(self, classify=None):
        detection = {'types': ['inspection'], 'certainty': 'clear', 'supported': True}
        with patch.object(queue, 'detect_document_types', side_effect=classify or (lambda *a: detection)), patch.object(
                vehicle_imports, 'vehicle_document_extractor', return_value=lambda source, **kw: extraction(source)) as factory:
            self.assertTrue(queue.process_one(self.m.app))
        self.m.db.session.expire_all()
        return factory

    def test_replacement_during_classification_cannot_start_extraction_or_publish(self):
        ident = self.enqueue()

        def classify(*args):
            self.replace_with_different_person()
            return {'types': ['inspection'], 'certainty': 'clear', 'supported': True}

        factory = self.process(classify)
        row = self.m.VehicleDocumentImportDraft.query.filter_by(id=ident).one()
        print('Q10_CLASSIFICATION_GENERATION:', json.dumps(dict(
            extractor_calls=factory.call_count, status=row.status)), flush=True)
        self.assertEqual((factory.call_count, row.status), (0, 'read_error'))
        self.assertEqual(json.loads(row.preview_json or '{}'), {})

    def ready_receipt_then_replace(self):
        ident = self.enqueue()
        self.process()
        row = self.m.VehicleDocumentImportDraft.query.filter_by(id=ident).one()
        self.assertEqual(row.status, 'preview')
        batch, original = row.batch_id, bytes(row.source_file)
        self.replace_with_different_person()
        return ident, batch, original

    def test_different_person_cannot_open_previously_published_preview(self):
        _, batch, _ = self.ready_receipt_then_replace()
        response = self.client.get(f'/vehicle/data-import/{batch}/preview')
        self.assertEqual(response.status_code, 404)

    def test_different_person_cannot_download_unregistered_original(self):
        ident, _, original = self.ready_receipt_then_replace()
        response = self.client.get('/vehicle/data-import/files/' + ident)
        print('Q10_ORIGINAL_GENERATION:', json.dumps(dict(status=response.status_code,
            original_bytes_exposed=response.data == original)), flush=True)
        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(response.data, original)
