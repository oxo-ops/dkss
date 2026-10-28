"""Invoice financial review routes against an isolated DB; no real data or OCR calls."""
from decimal import Decimal
import hashlib
import json
import re
import unittest
from unittest.mock import patch
from uuid import uuid4

from test_workflow_regressions import WorkflowRegressionTests as Fixture
from test_domain_consistency import today


class InvoiceLifecycleTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown

    def target(self, total=None, **costs):
        row = self.m.VehicleMaintenanceRecord(company_code='TEST',
            vehicle_record_id=self.vehicle.id, entry_date=today().isoformat(),
            content='既存整備', status='整備中', invoice_number='EXISTING',
            cost_office='A', total_cost=total, **costs)
        self.m.db.session.add(row)
        self.m.db.session.commit()
        return row

    def invoice(self, target, total='100', **costs):
        from test_inspection_document_ai import pdf_bytes
        ident = str(uuid4())
        source = pdf_bytes() + ('\n% ' + ident).encode()
        payload = {'record_date': target.entry_date, 'content': '追加資料',
                   'source_pages': [1], 'line_items': [], 'fees': []}
        draft = self.m.VehicleDocumentImportDraft(id=ident, batch_id=ident,
            company_code='TEST', created_by_username='admin', document_type='maintenance',
            source_filename=ident + '.pdf', source_file=source,
            source_sha256=hashlib.sha256(source).hexdigest(),
            preview_json=json.dumps({'records': [payload]}), status='preview')
        self.m.db.session.add(draft)
        self.m.db.session.commit()
        key = ident + '_0'
        form = {'include': key, 'vehicle_' + key: str(self.vehicle.id),
                'date_' + key: target.entry_date, 'content_' + key: '追加資料',
                'total_cost_' + key: total if total is not None else ''}
        form.update({field + '_' + key: value for field, value in costs.items()})
        choices = self.client.get(
            f'/vehicle/document-import/{ident}/{ident}/0/maintenance-candidates',
            query_string={'vehicle_id': self.vehicle.id, 'record_date': target.entry_date}).json['candidates']
        form['service_match_' + key] = next(x['token'] for x in choices
            if x['kind'] == 'maintenance' and x['record_id'] == target.id)
        response = self.client.post(f'/vehicle/data-import/{ident}/confirm', data=form)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        return self.m.VehicleMaintenanceDocument.query.filter_by(source_draft_id=ident).one(), draft, form

    def review(self, doc, mode, *, expected=None, replacement=None, probe=False):
        data = {'confirm_' + mode: '1'}
        if expected is not None:
            data['expected_total'] = str(expected)
        if replacement is not None:
            data['replaces_document_id'] = replacement.id
        return self.client.post('/master/vehicles/invoice-reviews/' + doc.id + '/' + mode.replace('_', '-'),
            data=data, headers={'X-DKSS-Validation-Only': '1'} if probe else {})

    def assert_total(self, target, expected):
        from dkss_app.vehicle_costs import get_vehicle_maintenance_cost_details, get_vehicle_overview_cost_summary
        from dkss_app.analysis import build_vehicle_karte_analysis_summary
        from dkss_app.dashboard import get_dashboard_office_maintenance_trend
        self.m.db.session.refresh(target)
        amount = Decimal(str(expected)) if expected is not None else None
        self.assertEqual(target.total_cost, amount)
        rows = self.m.VehicleMaintenanceRecord.query.all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(get_vehicle_overview_cost_summary(rows)['total_cost'], amount)
        details = get_vehicle_maintenance_cost_details(rows, today().year)
        self.assertEqual(details['selected_summary']['total_cost'], amount)
        self.assertEqual(details['monthly_costs'][today().month - 1]['amount'], amount)
        summary = build_vehicle_karte_analysis_summary(rows, [], [], [],
            today().replace(day=1).isoformat(), today().isoformat())
        self.assertEqual(summary['total_cost'], amount)
        trend = get_dashboard_office_maintenance_trend('TEST', 'A')
        self.assertEqual(sum(m['amount'] for m in trend['months']), amount or Decimal('0'))
        self.assertEqual(target.status, '整備中')
        self.assertEqual(self.m.VehiclePartReplacement.query.count(), 0)

    def assert_originals(self, *drafts):
        for draft in drafts:
            self.m.db.session.refresh(draft)
            self.assertEqual(draft.status, 'completed')
            response = self.client.get('/vehicle/data-import/files/' + draft.id)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(hashlib.sha256(response.data).hexdigest(), draft.source_sha256)

    def test_initial_addition_correction_chain_and_replay(self):
        row = self.target()
        first, d1, _ = self.invoice(row, '100')
        self.assertEqual(self.review(first, 'initial_cost').status_code, 302)
        self.assert_total(row, 100)
        extra, d2, _ = self.invoice(row, '30')
        self.assertEqual(self.review(extra, 'additional_cost', expected=100).status_code, 302)
        self.assert_total(row, 130)
        corrected, d3, _ = self.invoice(row, '20')
        self.assertEqual(self.review(corrected, 'correction', expected=130, replacement=extra).status_code, 302)
        self.assert_total(row, 120)
        self.assertEqual(extra.financial_status, 'superseded')
        corrected_again, d4, _ = self.invoice(row, '25')
        self.assertEqual(self.review(corrected_again, 'correction', expected=120, replacement=corrected).status_code, 302)
        self.assert_total(row, 125)
        self.assertEqual(corrected_again.related_document_id, corrected.id)
        for doc, mode, expected, old in ((first, 'initial_cost', None, None),
                (extra, 'additional_cost', 125, None),
                (corrected_again, 'correction', 125, corrected)):
            self.assertEqual(self.review(doc, mode, expected=expected, replacement=old).status_code, 400)
            self.assert_total(row, 125)
        self.assert_originals(d1, d2, d3, d4)

    def test_replacing_initial_invoice_preserves_other_additions_and_components(self):
        row = self.target()
        first, d1, _ = self.invoice(row, '100', labor_cost='70', parts_cost='20', other_cost='0', tax_amount='10')
        self.assertEqual(self.review(first, 'initial_cost').status_code, 302)
        extra, d2, _ = self.invoice(row, '30', labor_cost='10', parts_cost='17', other_cost='0', tax_amount='3')
        self.assertEqual(self.review(extra, 'additional_cost', expected=100).status_code, 302)
        fixed, d3, _ = self.invoice(row, '50', labor_cost='30', parts_cost='15', other_cost='0', tax_amount='5')
        self.assertEqual(self.review(fixed, 'correction', expected=130, replacement=first).status_code, 302)
        self.assert_total(row, 80)
        self.assertEqual((row.labor_cost, row.parts_cost, row.other_cost, row.tax_amount), (40, 32, 0, 8))
        self.assertEqual(first.financial_status, 'superseded')
        self.assertEqual(extra.financial_status, 'confirmed')
        self.assert_originals(d1, d2, d3)

    def test_correction_can_recover_previously_unknown_components(self):
        row = self.target()
        first, _, _ = self.invoice(row, '100')
        self.assertEqual(self.review(first, 'initial_cost').status_code, 302)
        self.assertIsNone(row.labor_cost)
        fixed, _, _ = self.invoice(row, '100', labor_cost='70', parts_cost='20', other_cost='0', tax_amount='10')
        self.assertEqual(self.review(fixed, 'correction', expected=100, replacement=first).status_code, 302)
        self.assert_total(row, 100)
        self.assertEqual((row.labor_cost, row.parts_cost, row.other_cost, row.tax_amount), (70, 20, 0, 10))

    def test_failed_correction_rolls_back_both_documents_and_history(self):
        from sqlalchemy.exc import SQLAlchemyError
        row = self.target()
        first, d1, _ = self.invoice(row, '100')
        self.assertEqual(self.review(first, 'initial_cost').status_code, 302)
        fixed, d2, _ = self.invoice(row, '60')
        previous_decision = first.decision_json
        events = self.m.VehicleMaintenanceRecordEvent.query.count()
        with patch.object(self.m.db.session, 'commit', side_effect=SQLAlchemyError('forced Q07 correction rollback')):
            self.assertEqual(self.review(fixed, 'correction', expected=100, replacement=first).status_code, 500)
        self.assert_total(row, 100)
        self.assertEqual((first.financial_status, fixed.financial_status), ('confirmed', 'pending'))
        self.assertEqual(first.decision_json, previous_decision)
        self.assertIsNone(fixed.related_document_id)
        self.assertEqual(self.m.VehicleMaintenanceRecordEvent.query.count(), events)
        self.assertEqual(self.review(fixed, 'correction', expected=100, replacement=first).status_code, 302)
        self.assert_total(row, 60)
        self.assert_originals(d1, d2)

    def test_legacy_baseline_and_unknown_components_survive_correction(self):
        row = self.target('500', labor_cost=100)
        extra, d1, _ = self.invoice(row, '30', labor_cost='10')
        self.assertEqual(self.review(extra, 'additional_cost', expected=500).status_code, 302)
        fixed, d2, _ = self.invoice(row, '20', labor_cost='5')
        self.assertEqual(self.review(fixed, 'correction', expected=530, replacement=extra).status_code, 302)
        self.assert_total(row, 520)
        self.assertEqual(row.labor_cost, 105)
        self.assertIsNone(row.parts_cost)
        self.assert_originals(d1, d2)

    def test_zero_invoice_and_corrected_zero_are_known(self):
        row = self.target()
        first, _, _ = self.invoice(row, '0')
        self.assertEqual(self.review(first, 'initial_cost').status_code, 302)
        self.assert_total(row, 0)
        extra, _, _ = self.invoice(row, '50')
        self.assertEqual(self.review(extra, 'additional_cost', expected=0).status_code, 302)
        fixed, _, _ = self.invoice(row, '0')
        self.assertEqual(self.review(fixed, 'correction', expected=50, replacement=extra).status_code, 302)
        self.assert_total(row, 0)

    def test_validation_probe_rolls_back_entire_correction(self):
        row = self.target()
        first, d1, _ = self.invoice(row)
        self.assertEqual(self.review(first, 'initial_cost', probe=True).status_code, 200)
        self.assert_total(row, None)
        self.assertEqual(first.financial_status, 'pending')
        self.assertEqual(self.review(first, 'initial_cost').status_code, 302)
        fixed, d2, _ = self.invoice(row, '60')
        events = self.m.VehicleMaintenanceRecordEvent.query.count()
        self.assertEqual(self.review(fixed, 'correction', expected=100, replacement=first, probe=True).status_code, 200)
        self.assert_total(row, 100)
        self.assertEqual(first.financial_status, 'confirmed')
        self.assertEqual(fixed.financial_status, 'pending')
        self.assertEqual(self.m.VehicleMaintenanceRecordEvent.query.count(), events)
        self.assertEqual(self.review(fixed, 'correction', expected=100, replacement=first).status_code, 302)
        self.assert_total(row, 60)
        self.assert_originals(d1, d2)

    def test_stale_total_and_superseded_selection_cannot_write(self):
        row = self.target()
        first, _, _ = self.invoice(row)
        self.assertEqual(self.review(first, 'initial_cost').status_code, 302)
        extra, _, _ = self.invoice(row, '30')
        self.assertEqual(self.review(extra, 'additional_cost', expected=99).status_code, 400)
        self.assert_total(row, 100)
        fixed, _, _ = self.invoice(row, '60')
        self.assertEqual(self.review(fixed, 'correction', expected=100, replacement=first).status_code, 302)
        self.assertEqual(self.review(extra, 'correction', expected=60, replacement=first).status_code, 400)
        self.assert_total(row, 60)
        self.assertEqual(extra.financial_status, 'pending')

    def test_tampered_original_or_payload_cannot_apply_costs(self):
        row = self.target('500')
        doc, draft, _ = self.invoice(row)
        original = draft.source_file
        draft.source_file = b'changed'
        self.m.db.session.commit()
        self.assertEqual(self.review(doc, 'additional_cost', expected=500).status_code, 400)
        draft.source_file = original
        doc.payload_json = json.dumps({**json.loads(doc.payload_json), 'total_cost': '999'})
        self.m.db.session.commit()
        self.assertEqual(self.review(doc, 'additional_cost', expected=500).status_code, 400)
        self.assert_total(row, 500)
        self.assertEqual(doc.financial_status, 'pending')

    def test_changed_ledger_or_target_blocks_correction(self):
        row = self.target()
        first, _, _ = self.invoice(row)
        self.assertEqual(self.review(first, 'initial_cost').status_code, 302)
        fixed, _, _ = self.invoice(row, '60')
        row.total_cost = 101
        self.m.db.session.commit()
        self.assertEqual(self.review(fixed, 'correction', expected=101, replacement=first).status_code, 400)
        self.assert_total(row, 101)
        row.total_cost = 100
        decision = json.loads(first.decision_json)
        decision['confirmed_costs']['total_cost'] = '999'
        first.decision_json = json.dumps(decision)
        self.m.db.session.commit()
        self.assertEqual(self.review(fixed, 'correction', expected=100, replacement=first).status_code, 400)
        self.assert_total(row, 100)

    def test_inconsistent_components_and_missing_total_cannot_be_confirmed(self):
        row = self.target('500')
        for total, costs in ((None, {}), ('100', dict(labor_cost='10', parts_cost='20', other_cost='0', tax_amount='0'))):
            with self.subTest(total=total):
                doc, draft, _ = self.invoice(row, total, **costs)
                self.assertEqual(self.review(doc, 'additional_cost', expected=500).status_code, 400)
                self.assert_total(row, 500)
                self.assert_originals(draft)

    def test_addition_overflow_is_atomic(self):
        row = self.target('999999999999.99')
        doc, draft, _ = self.invoice(row, '0.01')
        self.assertEqual(self.review(doc, 'additional_cost', expected=row.total_cost).status_code, 400)
        self.assert_total(row, '999999999999.99')
        self.assertEqual(doc.financial_status, 'pending')
        self.assert_originals(draft)

    def test_database_failure_keeps_review_retryable(self):
        from sqlalchemy.exc import SQLAlchemyError
        row = self.target('500')
        doc, draft, _ = self.invoice(row)
        events = self.m.VehicleMaintenanceRecordEvent.query.count()
        with patch.object(self.m.db.session, 'commit', side_effect=SQLAlchemyError('forced Q07 rollback')):
            self.assertEqual(self.review(doc, 'additional_cost', expected=500).status_code, 500)
        self.assert_total(row, 500)
        self.assertEqual(doc.financial_status, 'pending')
        self.assertEqual(self.m.VehicleMaintenanceRecordEvent.query.count(), events)
        self.assertEqual(self.review(doc, 'additional_cost', expected=500).status_code, 302)
        self.assert_total(row, 600)
        self.assert_originals(draft)

    def test_import_resubmit_and_already_recorded_do_not_double_count(self):
        row = self.target('500')
        doc, draft, form = self.invoice(row)
        self.assertEqual(self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=form).status_code, 409)
        url = '/master/vehicles/invoice-reviews/' + doc.id + '/duplicate'
        for _ in range(2):
            self.assertEqual(self.client.post(url, data={'already_recorded': '1'}).status_code, 302)
            self.assert_total(row, 500)
        self.assertEqual(doc.financial_status, 'duplicate')
        self.assert_originals(draft)

    def test_pending_cancel_preserves_existing_costs_and_confirmed_cancel_is_blocked(self):
        row = self.target('500')
        pending, draft, _ = self.invoice(row)
        url = f'/vehicle/karte/{self.vehicle.id}/documents/{draft.id}/delete'
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        token = re.search(r'name="delete_token" value="([^"]+)"', page.get_data(as_text=True))[1]
        response = self.client.post(url, data={'delete_token': token, 'confirm_delete': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assert_total(row, 500)
        self.assertEqual(self.m.VehicleMaintenanceDocument.query.count(), 0)
        self.m.db.session.refresh(draft)
        self.assertEqual(draft.status, 'deleted')
        applied, original, _ = self.invoice(row)
        self.assertEqual(self.review(applied, 'additional_cost', expected=500).status_code, 302)
        url = f'/vehicle/karte/{self.vehicle.id}/documents/{original.id}/delete'
        self.assertEqual(self.client.post(url, data={'confirm_delete': 'yes'}).status_code, 409)
        self.assert_total(row, 600)
        self.assert_originals(original)


del Fixture

if __name__ == '__main__':
    unittest.main()
