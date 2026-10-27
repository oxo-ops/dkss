"""Queued OCR must recheck its owner's current access before external calls."""
import json
import unittest
from unittest.mock import patch
from io import BytesIO
from uuid import uuid4
import test_workflow_regressions as workflow
from test_inspection_document_ai import pdf_bytes, extraction
from dkss_app import document_import_queue as queue, vehicle_imports
from dkss_app.extensions import db
from dkss_app.models import VehicleDocumentImportDraft as Draft


class Q02ImportWorkerAccessTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def enqueue(self):
        response = self.client.post('/vehicle/data-import/jobs', data={
            'document_type': 'inspection', 'upload_key': str(uuid4()),
            'document_files': [(BytesIO(pdf_bytes()), 'synthetic.pdf')]},
            headers={'Accept': 'application/json'})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 202)
        return Draft.query.one().id

    def owner(self):
        return self.m.User.query.filter_by(company_code='TEST', username='admin').one()

    def assert_no_external_call(self, ident):
        with patch.object(queue, 'detect_document_types') as detect, patch.object(
                vehicle_imports, 'vehicle_document_extractor') as factory:
            self.assertTrue(queue.process_one(self.m.app))
            detect.assert_not_called()
            factory.assert_not_called()
        db.session.expire_all()
        row = Draft.query.filter_by(id=ident).one()
        self.assertEqual(row.status, 'read_error')
        self.assertEqual(json.loads(row.preview_json or '{}'), {})
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 0)

    def test_locked_owner_cannot_start_queued_external_processing(self):
        ident = self.enqueue()
        self.owner().login_locked = True
        db.session.commit()
        self.assert_no_external_call(ident)

    def test_deleted_owner_cannot_start_queued_external_processing(self):
        ident = self.enqueue()
        db.session.delete(self.owner())
        db.session.commit()
        self.assert_no_external_call(ident)

    def test_demoted_owner_cannot_start_queued_external_processing(self):
        ident = self.enqueue()
        self.owner().role = 'user'
        db.session.commit()
        self.assert_no_external_call(ident)

    def test_inactive_company_cannot_start_queued_external_processing(self):
        ident = self.enqueue()
        self.m.Company.query.filter_by(company_code='TEST').one().active = False
        db.session.commit()
        self.assert_no_external_call(ident)

    def test_foreign_same_username_cannot_replace_deleted_owner(self):
        ident = self.enqueue()
        owner = self.owner()
        self.m.Company.query.filter_by(company_code='OTHER').delete()
        db.session.add(self.m.Company(company_code='OTHER', company_name='Synthetic', active=True))
        db.session.add(self.m.User(company_code='OTHER', username='admin', role='admin',
            password='unused', last_name='Synthetic', password_changed_at=owner.password_changed_at))
        db.session.delete(owner)
        db.session.commit()
        self.assert_no_external_call(ident)

    def test_current_admin_can_still_process_a_queued_document(self):
        ident = self.enqueue()
        def extract(source, filename=None, progress_callback=None):
            return extraction(source)
        with patch.object(queue, 'detect_document_types', return_value={
            'types': ['inspection'], 'certainty': 'clear', 'supported': True}), patch.object(
                vehicle_imports, 'vehicle_document_extractor', return_value=extract) as factory:
            self.assertTrue(queue.process_one(self.m.app))
            factory.assert_called_once_with('inspection')
        db.session.expire_all()
        row = Draft.query.filter_by(id=ident).one()
        self.assertEqual(row.status, 'preview')
        self.assertTrue(row.preview_json)


if __name__ == '__main__':
    unittest.main(verbosity=2)
