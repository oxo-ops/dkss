"""Document completion dates must follow their explicitly entered start dates."""
import hashlib
import json
from types import SimpleNamespace
import unittest

import test_workflow_regressions as fixtures
from dkss_app.vehicle_imports import validate_vehicle_document_record


class DocumentCompletionDateTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = fixtures.WorkflowRegressionTests.setUp
    tearDown = fixtures.WorkflowRegressionTests.tearDown

    def form(self, ident='q05', start='2028-02-29', end='2028-03-01', vehicle=True):
        key = ident + '_0'
        return {'include': key, 'vehicle_' + key: str(self.vehicle.id) if vehicle else '',
                'date_' + key: start, 'completion_date_' + key: end,
                'inspection_type_' + key: '3month', 'content_' + key: '架空の整備・点検',
                'invoice_date_' + key: '2028-02-01'}

    def draft(self, kind):
        from test_inspection_document_ai import pdf_bytes
        source = pdf_bytes()
        row = {'record_date': '2028-02-29', 'content': '架空の整備・点検',
               'inspection_type': '3month', 'completion_date': '2028-03-01',
               'source_pages': [1], 'line_items': [], 'fees': []}
        draft = self.m.VehicleDocumentImportDraft(id='q05', batch_id='q05-batch',
            company_code='TEST', created_by_username='admin', document_type=kind,
            source_filename=kind + '.pdf', source_file=source,
            source_sha256=hashlib.sha256(source).hexdigest(),
            preview_json=json.dumps({'records': [row]}), status='preview')
        self.m.db.session.add(draft)
        self.m.db.session.commit()
        return draft

    def assert_no_records(self):
        for model in (self.m.VehicleMaintenanceRecord, self.m.VehiclePeriodicInspectionRecord,
                      self.m.VehiclePartReplacement, self.m.VehicleImportPendingRecord):
            self.assertEqual(model.query.count(), 0, model.__name__)

    def test_validator_rejects_reversed_maintenance_and_inspection_dates(self):
        for kind in ('maintenance', 'inspection'):
            draft = SimpleNamespace(id='q05', company_code='TEST', document_type=kind)
            values, errors = validate_vehicle_document_record(draft, 0, {}, self.form(end='2028-02-28'))
            self.assertTrue(any(field == 'completion_date_q05_0' for _, field in errors), errors)
            self.assertEqual(values['completion_date'], '2028-02-28')
            self.assert_no_records()

    def test_equal_day_overnight_and_unknown_completion_remain_allowed(self):
        for kind in ('maintenance', 'inspection'):
            draft = SimpleNamespace(id='q05', company_code='TEST', document_type=kind)
            for start, end in [('2028-02-29', '2028-02-29'), ('2028-02-29', '2028-03-01'),
                               ('2026-12-31', '2027-01-01'), ('2028-02-29', '')]:
                with self.subTest(kind=kind, start=start, end=end):
                    values, errors = validate_vehicle_document_record(draft, 0, {}, self.form(start=start, end=end))
                    self.assertEqual(errors, [])
                    self.assertEqual(values['completion_date'], end or None)
                    if kind == 'maintenance':
                        self.assertEqual(values['invoice_date'], '2028-02-01')

    def test_invalid_calendar_and_noncanonical_dates_keep_field_errors(self):
        for kind in ('maintenance', 'inspection'):
            draft = SimpleNamespace(id='q05', company_code='TEST', document_type=kind)
            for start, end, field in [('2028-02-30', '2028-03-01', 'date_q05_0'),
                                      ('2028-02-29', '2028-02-30', 'completion_date_q05_0'),
                                      ('2028-02-29', '2028-2-28', 'completion_date_q05_0')]:
                with self.subTest(kind=kind, start=start, end=end):
                    _, errors = validate_vehicle_document_record(draft, 0, {}, self.form(start=start, end=end))
                    self.assertEqual([key for _, key in errors], [field])

    def test_maintenance_final_confirmation_rejects_reverse_without_business_writes(self):
        draft = self.draft('maintenance')
        original_source = draft.source_file
        response = self.client.post('/vehicle/data-import/q05-batch/confirm', data=self.form(end='2028-02-28'),
                                    headers={'X-DKSS-Final-Submit': '1'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('completion_date_q05_0', [e['field'] for e in response.json['errors']])
        self.assert_no_records()
        self.m.db.session.refresh(draft)
        self.assertEqual(draft.status, 'preview')
        self.assertEqual(draft.source_file, original_source)

    def test_inspection_final_confirmation_rejects_reverse_without_execution_or_plan(self):
        draft = self.draft('inspection')
        response = self.client.post('/vehicle/data-import/q05-batch/confirm', data=self.form(end='2028-02-28'))
        self.assertEqual(response.status_code, 400)
        self.assert_no_records()
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(), 0)
        self.m.db.session.refresh(draft)
        self.assertEqual(draft.status, 'preview')

    def test_validation_only_rejects_reverse_without_changing_draft(self):
        draft = self.draft('maintenance')
        before = draft.preview_json
        response = self.client.post('/vehicle/data-import/q05-batch/confirm',
            data=self.form(end='2028-02-28'), headers={'X-DKSS-Validation-Only': '1'})
        self.assertEqual(response.status_code, 400)
        self.m.db.session.refresh(draft)
        self.assertEqual(draft.preview_json, before)
        self.assert_no_records()

    def test_unassigned_vehicle_does_not_turn_reversed_dates_into_pending_record(self):
        self.draft('maintenance')
        response = self.client.post('/vehicle/data-import/q05-batch/confirm',
            data=self.form(end='2028-02-28', vehicle=False))
        self.assertEqual(response.status_code, 400)
        self.assert_no_records()

    def test_valid_leap_day_import_keeps_completion_and_independent_invoice_date(self):
        self.draft('maintenance')
        response = self.client.post('/vehicle/data-import/q05-batch/confirm', data=self.form())
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        row = self.m.VehicleMaintenanceRecord.query.one()
        self.assertEqual((row.entry_date, row.completion_date, row.invoice_date),
                         ('2028-02-29', '2028-03-01', '2028-02-01'))


if __name__ == '__main__':
    unittest.main()
