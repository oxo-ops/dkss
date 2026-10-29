"""M07: real source-scoped read corrections, without changing stored originals."""
import html
import json
import re
import unittest
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError
import test_q07_invoice_reimports as imports
import test_q07_invoice_lifecycle as lifecycle
KEY = 'invoice_cost_reads'
FIELDS = ('labor_cost', 'parts_cost', 'other_cost', 'tax_amount', 'total_cost')


class InvoiceReadCorrectionTests(unittest.TestCase):
    setUpClass = classmethod(imports.InvoiceReimportTests.setUpClass.__func__)
    tearDownClass = classmethod(imports.InvoiceReimportTests.tearDownClass.__func__)
    setUp = imports.InvoiceReimportTests.setUp
    tearDown = imports.InvoiceReimportTests.tearDown
    source = imports.InvoiceReimportTests.source
    upload = imports.InvoiceReimportTests.upload
    extract = imports.InvoiceReimportTests.extract
    worker = imports.InvoiceReimportTests.worker
    draft = imports.InvoiceReimportTests.draft
    form = imports.InvoiceReimportTests.form
    confirm = imports.InvoiceReimportTests.confirm
    imported = imports.InvoiceReimportTests.imported
    additional = imports.InvoiceReimportTests.additional
    review = imports.InvoiceReimportTests.review
    edit_form = imports.InvoiceReimportTests.edit_form
    edit = imports.InvoiceReimportTests.edit
    assert_cost = imports.InvoiceReimportTests.assert_cost
    assert_source = imports.InvoiceReimportTests.assert_source
    target = lifecycle.InvoiceLifecycleTests.target
    invoice = lifecycle.InvoiceLifecycleTests.invoice

    def context(self, row):
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit')
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        found = re.search(r"data-context='([^']+)'", text)
        self.assertIsNotNone(found, text)
        return json.loads(html.unescape(found[1]))

    def read_form(self, row, selected, amount):
        view = self.context(row)
        source = next(s for s in view['sources'] if s['key'] == selected or s['key'].startswith(selected))
        data = self.edit_form(row, **{f: source['values'][f] or '' for f in FIELDS})
        data.update(invoice_source=source['key'], invoice_read_version=view['version'], total_cost=amount)
        return data

    def read(self, row, selected, amount, evidence=False):
        data = self.read_form(row, selected, amount)
        if evidence:
            data['invoice_evidence_confirmed'] = '1'
        return self.client.post(f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit', data=data)

    def legacy_total(self, row, total='140'):
        before = str(row.total_cost)
        row.total_cost = total
        self.m.db.session.add(self.m.VehicleMaintenanceRecordEvent(
            company_code='TEST', vehicle_record_id=self.vehicle.id, maintenance_record_id=row.id,
            action='updated', changes_json=json.dumps([dict(field='total_cost', before=before, after=total)]),
            created_by_username='admin', created_at='2026-10-28T12:00:00+09:00'))
        self.m.db.session.commit()

    def test_primary_read_then_addition_replacement_preserves_source_and_history(self):
        row, original, raw = self.imported()
        extra, extra_draft = self.additional(row)
        self.assertEqual(self.review(extra).status_code, 302)
        old_decision = extra.decision_json
        old_preview = original.preview_json
        self.assertEqual(self.read(row, 'primary:', '110').status_code, 302)
        self.assert_cost(row, 140)
        self.assertEqual(extra.decision_json, old_decision)
        self.assertEqual(original.preview_json, old_preview)
        revisions = json.loads(row.invoice_details_json)[KEY]['sources']
        self.assertEqual(len(revisions), 1)
        change = next(iter(revisions.values()))['revisions'][0]
        self.assertEqual((change['before']['total_cost'], change['after']['total_cost']), ('100.00', '110'))
        replacement, _ = self.additional(row, '20')
        self.assertEqual(self.review(replacement, 'correction', extra).status_code, 302)
        self.assert_cost(row, 130)
        self.assertEqual(extra.financial_status, 'superseded')
        self.assert_source(original, raw)
        self.assertEqual(extra_draft.status, 'completed')

    def test_additional_invoice_read_is_not_assigned_to_primary(self):
        row, original, raw = self.imported()
        extra, draft = self.additional(row)
        self.assertEqual(self.review(extra).status_code, 302)
        payload, preview = extra.payload_json, draft.preview_json
        self.assertEqual(self.read(row, 'document:' + extra.id, '40').status_code, 302)
        self.assert_cost(row, 140)
        self.assertEqual(extra.payload_json, payload)
        self.assertEqual(draft.preview_json, preview)
        self.assertEqual(json.loads(extra.decision_json)['confirmed_costs']['total_cost'], '30.00')
        replacement, _ = self.additional(row, '20')
        self.assertEqual(self.review(replacement, 'correction', extra).status_code, 302)
        self.assert_cost(row, 120)
        self.assert_source(original, raw)

    def test_mixed_aggregate_cannot_be_overwritten_without_source(self):
        row, _, _ = self.imported()
        extra, _ = self.additional(row)
        self.assertEqual(self.review(extra).status_code, 302)
        self.assertEqual(self.edit(row, total_cost='140').status_code, 409)
        self.assert_cost(row, 130)
        self.assertNotIn(KEY, json.loads(row.invoice_details_json))

    def test_legacy_140_requires_explicit_source_and_evidence(self):
        row, original, raw = self.imported()
        extra, _ = self.additional(row)
        self.assertEqual(self.review(extra).status_code, 302)
        self.legacy_total(row)
        self.assertTrue(self.context(row)['unresolved'])
        self.assertEqual(self.read(row, 'primary:', '110').status_code, 409)
        self.assert_cost(row, 140)
        self.assertNotIn(KEY, json.loads(row.invoice_details_json))
        self.assertEqual(self.read(row, 'primary:', '110', evidence=True).status_code, 302)
        self.assert_cost(row, 140)
        change = next(iter(json.loads(row.invoice_details_json)[KEY]['sources'].values()))['revisions'][0]
        self.assertTrue(change['reconciled_legacy'])
        self.assertEqual(change['record_before']['total_cost'], '140.00')
        replacement, _ = self.additional(row, '20')
        self.assertEqual(self.review(replacement, 'correction', extra).status_code, 302)
        self.assert_cost(row, 130)
        self.assert_source(original, raw)

    def test_stale_invoice_context_and_foreign_source_are_rejected(self):
        row, _, _ = self.imported()
        data = self.read_form(row, 'primary:', '110')
        extra, _ = self.additional(row)
        self.assertEqual(self.review(extra).status_code, 302)
        self.assertEqual(self.client.post(
            f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit', data=data).status_code, 409)
        data = self.read_form(row, 'primary:', '110')
        data['invoice_source'] = 'document:foreign'
        self.assertEqual(self.client.post(
            f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit', data=data).status_code, 409)
        self.assert_cost(row, 130)

    def test_read_correction_failure_rolls_back_revision_and_total_then_retries(self):
        row, original, raw = self.imported()
        extra, _ = self.additional(row)
        self.assertEqual(self.review(extra).status_code, 302)
        data = self.read_form(row, 'primary:', '110')
        decision = extra.decision_json
        with patch.object(self.m.db.session, 'commit', side_effect=SQLAlchemyError('synthetic M07 commit failure')):
            response = self.client.post(f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit', data=data)
        self.assertEqual(response.status_code, 500)
        self.assert_cost(row, 130)
        self.assertEqual(extra.decision_json, decision)
        self.assertNotIn(KEY, json.loads(row.invoice_details_json))
        self.assertEqual(self.read(row, 'primary:', '110').status_code, 302)
        self.assert_cost(row, 140)
        self.assert_source(original, raw)

    def test_manual_costs_stay_editable_and_separate_from_added_invoice(self):
        row = self.target('500')
        self.assertEqual(self.edit(row, total_cost='510').status_code, 302)
        extra, _ = self.additional(row)
        self.assertEqual(self.review(extra).status_code, 302)
        self.assertEqual(self.read(row, 'manual', '550').status_code, 302)
        self.m.db.session.refresh(row)
        self.assertEqual(str(row.total_cost), '580.00')
        fixed, _ = self.additional(row, '20')
        self.assertEqual(self.review(fixed, 'correction', extra).status_code, 302)
        self.m.db.session.refresh(row)
        self.assertEqual(str(row.total_cost), '570.00')

    def test_same_amount_replay_does_not_append_another_revision(self):
        row, _, _ = self.imported()
        data = self.read_form(row, 'primary:', '110')
        path = f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit'
        self.assertEqual(self.client.post(path, data=data).status_code, 302)
        self.assertEqual(self.client.post(path, data=data).status_code, 409)
        self.assertEqual(self.read(row, 'primary:', '110').status_code, 302)
        changes = next(iter(json.loads(row.invoice_details_json)[KEY]['sources'].values()))['revisions']
        self.assertEqual(len(changes), 1)
        self.assert_cost(row, 110)

    def test_manual_negative_and_unknown_values_keep_existing_edit_semantics(self):
        row = self.target('500')
        extra, _ = self.additional(row)
        self.assertEqual(self.review(extra).status_code, 302)
        data = self.read_form(row, 'manual', '-5')
        data.update(labor_cost='-1', parts_cost='2', other_cost='3', tax_amount='4')
        path = f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit'
        self.assertEqual(self.client.post(path, data=data).status_code, 302)
        self.m.db.session.refresh(row)
        self.assertEqual(str(row.total_cost), '25.00')
        self.assertEqual(row.status, '整備中')
        manual = next(s for s in self.context(row)['sources'] if s['key'] == 'manual')
        self.assertEqual(manual['values']['labor_cost'], '-1')
        self.assertEqual(self.read(row, 'manual', '').status_code, 302)
        self.m.db.session.refresh(row)
        self.assertIsNone(row.total_cost)
        self.assertEqual(self.read(row, 'manual', '500').status_code, 302)
        self.m.db.session.refresh(row)
        self.assertEqual(str(row.total_cost), '530.00')
        replacement, _ = self.additional(row, '20')
        self.assertEqual(self.review(replacement, 'correction', extra).status_code, 302)
        self.m.db.session.refresh(row)
        self.assertEqual(str(row.total_cost), '520.00')
        self.assertEqual(row.status, '整備中')

    def test_initial_cost_document_read_and_later_replacement(self):
        row = self.target()
        first, original, _ = self.invoice(row)
        self.assertEqual(self.review(first, 'initial_cost').status_code, 302)
        extra, _ = self.additional(row)
        self.assertEqual(self.review(extra).status_code, 302)
        self.assertEqual(self.read(row, 'document:' + first.id, '110').status_code, 302)
        lifecycle.InvoiceLifecycleTests.assert_total(self, row, 140)
        fixed, _ = self.additional(row, '20')
        self.assertEqual(self.review(fixed, 'correction', extra).status_code, 302)
        lifecycle.InvoiceLifecycleTests.assert_total(self, row, 130)
        self.assertEqual(json.loads(first.decision_json)['confirmed_costs']['total_cost'], '100.00')
        self.assertEqual(original.status, 'completed')

    def test_missing_original_keeps_legacy_amount_unresolved(self):
        row, original, _ = self.imported()
        extra, _ = self.additional(row)
        self.assertEqual(self.review(extra).status_code, 302)
        self.legacy_total(row)
        original.status = 'deleted'  # Deliberate missing-evidence fixture, never a real original.
        self.m.db.session.commit()
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit')
        self.assertIn('保留', response.get_data(as_text=True))
        self.assertEqual(self.edit(row, total_cost='150').status_code, 409)
        self.assert_cost(row, 140)
        self.assertNotIn(KEY, json.loads(row.invoice_details_json))

    def test_original_tampering_blocks_source_correction(self):
        row, original, _ = self.imported()
        data = self.read_form(row, 'primary:', '110')
        original.source_file = b'synthetic altered bytes'
        self.m.db.session.commit()
        response = self.client.post(f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit', data=data)
        self.assertEqual(response.status_code, 409)
        self.assert_cost(row, 100)
        self.assertNotIn(KEY, json.loads(row.invoice_details_json))

    def test_zero_is_known_and_unknown_components_stay_unknown(self):
        row, original, raw = self.imported()
        self.assertEqual(self.read(row, 'primary:', '0').status_code, 302)
        self.assert_cost(row, 0)
        self.assertIsNone(row.parts_cost)
        self.assertIsNone(row.labor_cost)
        self.assert_source(original, raw)

    def test_html_validation_preserves_source_and_submitted_amount(self):
        row, _, _ = self.imported()
        extra, _ = self.additional(row)
        self.assertEqual(self.review(extra).status_code, 302)
        data = self.read_form(row, 'document:' + extra.id, '-1')
        response = self.client.post(f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit',
                                    data=data, headers={'Accept': 'text/html'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.headers['X-DKSS-Import-Recovery'], '1')
        found = re.search(r"data-context='([^']+)'", response.get_data(as_text=True))
        view = json.loads(html.unescape(found[1]))
        self.assertEqual(view['selection'], 'document:' + extra.id)
        self.assertEqual(view['submitted']['total_cost'], '-1')
        self.assert_cost(row, 130)
