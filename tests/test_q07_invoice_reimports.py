"""Real upload/confirm/edit paths; only external classification and OCR are mocked."""
from identity_fixture import identity_for
from decimal import Decimal
import hashlib
from io import BytesIO
import json
import re
import unittest
from unittest.mock import patch
from uuid import uuid4

from test_workflow_regressions import WorkflowRegressionTests as Fixture
from test_domain_consistency import today
from dkss_app import document_import_queue as queue, vehicle_imports
from dkss_app.vehicle_karte import vehicle_maintenance_record_version


class InvoiceReimportTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown

    def source(self):
        from test_inspection_document_ai import pdf_bytes
        return pdf_bytes() + ('\n% ' + str(uuid4())).encode()

    def upload(self, source, filename='invoice.pdf'):
        return self.client.post('/vehicle/data-import/jobs', data={
            'document_type': 'maintenance', 'upload_key': str(uuid4()),
            'document_files': (BytesIO(source), filename)}, headers={'Accept': 'application/json'})

    def extract(self, source, amount='100'):
        import maintenance_invoice_ai as ai
        row = {key: None for key in ai.record_properties}
        row.update(source_pages=[1], line_items=[], fees=[], warnings=[],
            entry_date=today().isoformat(), completion_date=today().isoformat(),
            content='費用経路確認', total_cost=amount)
        return dict(schema_version=1, source_sha256=hashlib.sha256(source).hexdigest(), records=[row], warnings=[])

    def worker(self, amount='100'):
        with patch.object(queue, 'detect_document_types', return_value={
                'types': ['maintenance'], 'certainty': 'clear', 'supported': True}), patch.object(
                vehicle_imports, 'vehicle_document_extractor', return_value=lambda source, **kw: self.extract(source, amount)) as factory:
            self.assertTrue(queue.process_one(self.m.app))
        return factory

    def draft(self, receipt):
        return self.m.VehicleDocumentImportDraft.query.filter_by(batch_id=receipt['batch_id']).one()

    def form(self, draft, target=None):
        key = draft.id + '_0'
        form = {'include': key, 'vehicle_' + key: str(self.vehicle.id),
            'date_' + key: today().isoformat(), 'completion_date_' + key: today().isoformat(),
            'cost_office_' + key: 'A', 'content_' + key: '費用経路確認'}
        if target is not None:
            choices = self.client.get(f'/vehicle/document-import/{draft.batch_id}/{draft.id}/0/maintenance-candidates',
                query_string={'vehicle_id': self.vehicle.id, 'record_date': today().isoformat()}).json['candidates']
            form['service_match_' + key] = next(x['token'] for x in choices if x['kind'] == 'maintenance' and x['record_id'] == target.id)
        return form

    def confirm(self, draft, target=None):
        response = self.client.post('/vehicle/data-import/' + draft.batch_id + '/confirm', data=self.form(draft, target))
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        return self.m.VehicleMaintenanceRecord.query.one()

    def imported(self, amount='100'):
        source = self.source()
        receipt = self.upload(source)
        self.assertEqual(receipt.status_code, 202)
        self.worker(amount)
        draft = self.draft(receipt.json)
        return self.confirm(draft), draft, source

    def additional(self, target, amount='30'):
        receipt = self.upload(self.source())
        self.assertEqual(receipt.status_code, 202)
        self.worker(amount)
        draft = self.draft(receipt.json)
        self.confirm(draft, target)
        return self.m.VehicleMaintenanceDocument.query.filter_by(source_draft_id=draft.id).one(), draft

    def review(self, doc, mode='additional_cost', replacement=None):
        target = self.m.db.session.get(self.m.VehicleMaintenanceRecord, doc.maintenance_record_id)
        data = {'confirm_' + mode: '1', 'expected_total': str(target.total_cost)}
        if replacement is not None:
            data['replaces_document_id'] = replacement.id
        return self.client.post('/master/vehicles/invoice-reviews/' + doc.id + '/' + mode.replace('_', '-'), data=data, headers={'X-DKSS-Final-Submit': '1'})

    def edit_form(self, row, **changes):
        fields = ('content', 'category', 'status', 'entry_date', 'completion_date', 'mileage',
            'symptom', 'cause', 'temporary_action', 'repair_content', 'maintenance_company',
            'maintenance_person', 'repair_hours', 'invoice_number', 'invoice_date', 'cost_office',
            'parts_cost', 'labor_cost', 'other_cost', 'tax_amount', 'total_cost', 'notes')
        data = {field: str(getattr(row, field)) if getattr(row, field) is not None else '' for field in fields}
        data.update(record_version=vehicle_maintenance_record_version(row), maintenance_action='save', **changes)
        return data

    def edit(self, row, **changes):
        return self.client.post(f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit', data=self.edit_form(row, **changes))

    def assert_source(self, draft, source):
        self.m.db.session.refresh(draft)
        self.assertEqual(draft.source_file, source)
        response = self.client.get('/vehicle/data-import/files/' + draft.id)
        self.assertEqual((response.status_code, response.data), (200, source))

    def assert_cost(self, row, amount):
        from dkss_app.vehicle_costs import get_vehicle_maintenance_cost_details
        from dkss_app.analysis import build_vehicle_karte_analysis_summary
        from dkss_app.dashboard import get_dashboard_office_maintenance_trend
        self.m.db.session.refresh(row)
        amount = Decimal(str(amount))
        self.assertEqual(row.total_cost, amount)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 1)
        self.assertEqual(get_vehicle_maintenance_cost_details([row], today().year)['selected_summary']['total_cost'], amount)
        self.assertEqual(build_vehicle_karte_analysis_summary([row], [], [], [], today().replace(day=1).isoformat(), today().isoformat())['total_cost'], amount)
        self.assertEqual(sum(x['amount'] for x in get_dashboard_office_maintenance_trend('TEST', 'A')['months']), amount)
        self.assertEqual(row.display_status, '実施済み')

    def test_new_upload_of_same_bytes_after_amount_read_correction_is_rejected(self):
        row, draft, source = self.imported()
        self.assertEqual(self.edit(row, total_cost='125', content='金額の読取訂正').status_code, 302)
        self.assert_cost(row, 125)
        with patch.object(vehicle_imports, 'vehicle_document_extractor', side_effect=AssertionError('duplicate OCR')):
            response = self.upload(source, 'renamed.pdf')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.m.VehicleDocumentImportDraft.query.count(), 1)
        self.assert_cost(row, 125)
        self.assert_source(draft, source)

    def test_other_admin_same_company_reupload_is_still_duplicate(self):
        row, draft, source = self.imported()
        user = self.m.User.query.filter_by(company_code='TEST', username='admin').one()
        self.m.db.session.add(self.m.User(company_code='TEST', username='other-admin', last_name='架空管理者', role='admin',
            password='unused', password_changed_at=user.password_changed_at))
        self.m.db.session.commit()
        with self.client.session_transaction() as state:
            state['username'] = 'other-admin'; state['account_identity'] = identity_for(state.get('company_code'), state.get('username'))
        self.assertEqual(self.upload(source, 'other-name.pdf').status_code, 409)
        self.assert_cost(row, 100)
        with self.client.session_transaction() as state:
            state['username'] = 'admin'; state['account_identity'] = identity_for(state.get('company_code'), state.get('username'))
        self.assert_source(draft, source)

    def test_two_receipts_before_confirm_skip_second_before_ocr(self):
        source = self.source()
        first = self.upload(source).json
        second = self.upload(source, 'copy.pdf').json
        self.worker()
        d1 = self.draft(first)
        self.assertEqual(d1.status, 'preview')
        row = self.confirm(d1)
        self.worker().assert_not_called()
        self.assertEqual(self.draft(second).status, 'skipped')
        self.assert_cost(row, 100)
        self.assert_source(d1, source)

    def test_two_previews_before_confirm_cannot_register_same_source_twice(self):
        source = self.source()
        first = self.upload(source).json
        second = self.upload(source, 'copy.pdf').json
        self.worker()
        self.worker()
        row = self.confirm(self.draft(first))
        d2 = self.draft(second)
        response = self.client.post('/vehicle/data-import/' + d2.batch_id + '/confirm', data=self.form(d2, row), headers={'X-DKSS-Final-Submit': '1'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('同じ原本', str(response.json))
        self.assert_cost(row, 100)
        self.assertEqual(self.m.VehicleMaintenanceDocument.query.count(), 0)

    def test_content_read_correction_after_addition_keeps_later_correction_valid(self):
        row, original, source = self.imported('500')
        added, added_source = self.additional(row)
        self.assertEqual(self.review(added).status_code, 302)
        self.assertEqual(self.edit(row, content='内容の読取訂正').status_code, 302)
        self.assert_cost(row, 530)
        fixed, _ = self.additional(row, '20')
        self.assertEqual(self.review(fixed, 'correction', added).status_code, 302)
        self.assert_cost(row, 520)
        self.assert_source(original, source)
        self.assertEqual(added.financial_status, 'superseded')
        self.assertEqual(added_source.status, 'completed')

    def test_amount_read_correction_before_addition_is_the_recorded_baseline(self):
        row, original, source = self.imported()
        self.assertEqual(self.edit(row, total_cost='120').status_code, 302)
        added, _ = self.additional(row)
        self.assertEqual(self.review(added).status_code, 302)
        self.assertEqual(json.loads(added.decision_json)['costs_before']['total_cost'], '120.00')
        fixed, _ = self.additional(row, '20')
        self.assertEqual(self.review(fixed, 'correction', added).status_code, 302)
        self.assert_cost(row, 140)
        self.assert_source(original, source)

    def test_amount_read_correction_after_addition_blocks_ambiguous_ledger_replacement(self):
        row, original, source = self.imported()
        added, _ = self.additional(row)
        self.assertEqual(self.review(added).status_code, 302)
        self.assertEqual(self.edit(row, total_cost='140').status_code, 409)
        self.assert_cost(row, 130)
        # Existing deployments can already contain the old, unscoped 140 edit.
        # Keep the protective refusal test against that historical state.
        row.total_cost = Decimal('140')
        self.m.db.session.add(self.m.VehicleMaintenanceRecordEvent(
            company_code='TEST', vehicle_record_id=self.vehicle.id, maintenance_record_id=row.id,
            action='updated', changes_json=json.dumps([{'field': 'total_cost', 'before': '130.00', 'after': '140'}]),
            created_by_username='admin', created_at='2026-10-28T12:00:00+09:00'))
        self.m.db.session.commit()
        fixed, _ = self.additional(row, '20')
        response = self.review(fixed, 'correction', added)
        self.assertEqual(response.status_code, 400)
        self.assertIn('登録済み費用と請求書の履歴が一致しません', str(response.json))
        self.assert_cost(row, 140)
        self.assertEqual((added.financial_status, fixed.financial_status), ('confirmed', 'pending'))
        self.assert_source(original, source)

    def test_stale_read_edit_cannot_overwrite_added_cost(self):
        row, original, source = self.imported()
        stale = self.edit_form(row, content='古い画面からの訂正')
        added, _ = self.additional(row)
        self.assertEqual(self.review(added).status_code, 302)
        response = self.client.post(f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit', data=stale)
        self.assertEqual(response.status_code, 409)
        self.assert_cost(row, 130)
        self.assert_source(original, source)

    def test_read_edit_database_failure_preserves_original_and_cost(self):
        from sqlalchemy.exc import SQLAlchemyError
        row, draft, source = self.imported()
        count = self.m.VehicleMaintenanceRecordEvent.query.count()
        with patch.object(self.m.db.session, 'commit', side_effect=SQLAlchemyError('forced Q07 read rollback')):
            self.assertEqual(self.edit(row, total_cost='125').status_code, 500)
        self.assert_cost(row, 100)
        self.assertEqual(self.m.VehicleMaintenanceRecordEvent.query.count(), count)
        self.assert_source(draft, source)

    def test_pending_attachment_cancel_allows_one_fresh_import_of_same_source(self):
        row, original, source = self.imported()
        pending, cancelled = self.additional(row)
        cancelled_source = cancelled.source_file
        url = f'/vehicle/karte/{self.vehicle.id}/documents/{cancelled.id}/delete'
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        token = re.search(r'name="delete_token" value="([^"]+)"', page.get_data(as_text=True))[1]
        self.assertEqual(self.client.post(url, data={'delete_token': token, 'confirm_delete': 'yes'}).status_code, 302)
        self.assert_cost(row, 100)
        receipt = self.upload(cancelled_source)
        self.assertEqual(receipt.status_code, 202)
        self.worker('30')
        restored = self.draft(receipt.json)
        self.confirm(restored, row)
        doc = self.m.VehicleMaintenanceDocument.query.one()
        self.assertEqual(doc.financial_status, 'pending')
        self.assertEqual(self.review(doc).status_code, 302)
        self.assert_cost(row, 130)
        self.assert_source(original, source)
        self.assert_source(restored, cancelled_source)
        self.assertEqual(self.upload(cancelled_source).status_code, 409)

    def test_read_corrected_primary_source_cannot_be_cancelled_and_discard_edits(self):
        row, draft, source = self.imported()
        self.assertEqual(self.edit(row, total_cost='125').status_code, 302)
        url = f'/vehicle/karte/{self.vehicle.id}/documents/{draft.id}/delete'
        self.assertEqual(self.client.post(url, data={'confirm_delete': 'yes'}).status_code, 409)
        self.assert_cost(row, 125)
        self.assert_source(draft, source)

    def test_legacy_upload_confirm_also_rejects_same_source(self):
        row, original, source = self.imported()
        with patch.object(self.m, 'extract_maintenance_invoices', return_value=self.extract(source)):
            response = self.client.post('/vehicle/data-import', data={'document_type': 'maintenance',
                'document_files': (BytesIO(source), 'legacy-copy.pdf')})
        self.assertEqual(response.status_code, 302)
        copied = self.m.VehicleDocumentImportDraft.query.filter(self.m.VehicleDocumentImportDraft.id != original.id).one()
        response = self.client.post('/vehicle/data-import/' + copied.batch_id + '/confirm', data=self.form(copied, row), headers={'X-DKSS-Final-Submit': '1'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('同じ原本', str(response.json))
        self.assert_cost(row, 100)
        self.assert_source(original, source)


del Fixture

if __name__ == '__main__':
    unittest.main()
