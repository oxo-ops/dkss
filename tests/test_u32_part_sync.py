"""U32: real invoice confirmation and maintenance HTTP correction, isolated DB."""
import hashlib
import json
import unittest
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError
import test_document_connections as documents
import test_q07_invoice_reimports as invoices


class PartSyncTests(unittest.TestCase):
    setUpClass = classmethod(documents.DocumentConnectionTests.setUpClass.__func__)
    tearDownClass = classmethod(documents.DocumentConnectionTests.tearDownClass.__func__)
    setUp = documents.DocumentConnectionTests.setUp
    tearDown = documents.DocumentConnectionTests.tearDown
    invoice = documents.DocumentConnectionTests.invoice
    edit_form = invoices.InvoiceReimportTests.edit_form
    edit = invoices.InvoiceReimportTests.edit

    def imported(self, completion='2026-10-22'):
        draft, key, form = self.invoice()
        form.update({'mileage_' + key: '10000', 'completion_date_' + key: completion})
        response = self.client.post('/vehicle/data-import/' + draft.batch_id + '/confirm', data=form)
        self.assertEqual(response.status_code, 302)
        row = self.m.VehicleMaintenanceRecord.query.one()
        part = self.m.VehiclePartReplacement.query.one()
        source = self.m.VehiclePartReplacementSource.query.one()
        self.assertEqual((part.maintenance_record_id, source.replacement_id), (row.id, part.id))
        self.assertEqual(part.mileage, 10000)
        self.assertEqual(part.replacement_date, completion or '2026-10-21')
        return row, part, source, draft

    def values(self, part):
        self.m.db.session.refresh(part)
        return part.replacement_date, part.mileage

    def events(self, row):
        model = self.m.VehicleMaintenanceRecordEvent
        return model.query.filter_by(maintenance_record_id=row.id).order_by(model.id).all()

    def test_imported_correction_syncs_and_audits_without_modifying_original(self):
        row, part, source, draft = self.imported()
        original = (draft.source_file, draft.preview_json, row.line_items_json, source.source_line_version)
        count = len(self.events(row))
        self.assertEqual(self.edit(row, mileage='12000', completion_date='2026-10-23').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-23', 12000))
        self.assertEqual(part.updated_by_username, 'admin')
        events = self.events(row)
        self.assertEqual(len(events), count + 1)
        changes = {c['field']: c for c in json.loads(events[-1].changes_json)}
        for field in ('mileage', 'completion_date', f'part_replacement:{part.id}:mileage',
                      f'part_replacement:{part.id}:replacement_date'):
            self.assertIn(field, changes)
        change = changes[f'part_replacement:{part.id}:replacement_date']
        self.assertEqual((change['before'], change['after']), ('2026-10-22', '2026-10-23'))
        for item in (draft, row, source):
            self.m.db.session.refresh(item)
        self.assertEqual((draft.source_file, draft.preview_json, row.line_items_json, source.source_line_version), original)
        response = self.client.get('/vehicle/data-import/files/' + draft.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(hashlib.sha256(response.data).hexdigest(), draft.source_sha256)

    def test_entry_date_fallback_and_completion_date_precedence(self):
        row, part, _, _ = self.imported(completion='')
        self.assertEqual(self.edit(row, entry_date='2026-10-20').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-20', 10000))
        self.assertEqual(self.edit(row, completion_date='2026-10-23').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-23', 10000))
        self.assertEqual(self.edit(row, entry_date='2026-10-19').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-23', 10000))
        self.assertEqual(self.edit(row, completion_date='').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-19', 10000))

    def test_independent_measurements_preserved_per_field(self):
        row, part, _, _ = self.imported()
        part.mileage = 10500
        self.m.db.session.commit()
        self.assertEqual(self.edit(row, mileage='12000', completion_date='2026-10-23').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-23', 10500))
        part.replacement_date = '2026-10-24'
        part.mileage = row.mileage
        self.m.db.session.commit()
        self.assertEqual(self.edit(row, mileage='13000', completion_date='2026-10-25').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-24', 13000))

    def test_missing_source_preserves_part_even_when_old_values_match(self):
        row, part, source, _ = self.imported()
        self.m.db.session.delete(source)
        self.m.db.session.commit()
        self.assertEqual(self.edit(row, mileage='12000', completion_date='2026-10-23').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-22', 10000))

    def test_manual_maintenance_correction_does_not_invent_parts_or_sources(self):
        response = self.client.post(f'/vehicle/karte/{self.vehicle.id}/maintenance/new', data={
            'content': 'Manual service', 'entry_date': '2026-10-21',
            'completion_date': '2026-10-22', 'mileage': '10000', 'maintenance_action': 'save'})
        self.assertEqual(response.status_code, 302)
        row = self.m.VehicleMaintenanceRecord.query.one()
        self.assertEqual(self.edit(row, mileage='12000', completion_date='2026-10-23').status_code, 302)
        self.m.db.session.refresh(row)
        self.assertEqual((row.mileage, row.completion_date), (12000, '2026-10-23'))
        self.assertEqual(self.m.VehiclePartReplacement.query.count(), 0)
        self.assertEqual(self.m.VehiclePartReplacementSource.query.count(), 0)

    def test_cleared_mileage_remains_unknown_and_can_be_corrected_again(self):
        row, part, _, _ = self.imported()
        self.assertEqual(self.edit(row, mileage='').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-22', None))
        self.assertEqual(self.edit(row, mileage='12000').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-22', 12000))

    def test_source_version_mismatch_preserves_part(self):
        row, part, source, _ = self.imported()
        source.source_line_version = '0' * 64
        self.m.db.session.commit()
        self.assertEqual(self.edit(row, mileage='12000').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-22', 10000))

    def test_invalid_source_index_preserves_part(self):
        row, part, source, _ = self.imported()
        source.source_line_index = 99
        self.m.db.session.commit()
        self.assertEqual(self.edit(row, mileage='12000').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-22', 10000))

    def test_nonreplacement_line_with_matching_version_preserves_part(self):
        row, part, source, _ = self.imported()
        lines = json.loads(row.line_items_json)
        lines[0]['replacement_action'] = 'inspect'
        row.line_items_json = json.dumps(lines)
        source.source_line_version = hashlib.sha256(json.dumps(
            lines[0], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        self.m.db.session.commit()
        self.assertEqual(self.edit(row, mileage='12000').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-22', 10000))

    def test_foreign_source_and_foreign_part_are_not_updated(self):
        row, part, source, _ = self.imported()
        source.company_code = 'OTHER'
        self.m.db.session.commit()
        self.assertEqual(self.edit(row, mileage='12000').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-22', 10000))
        source.company_code = 'TEST'
        part.company_code = 'OTHER'
        part.mileage = 12000
        self.m.db.session.commit()
        self.assertEqual(self.edit(row, mileage='13000').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-22', 12000))

    def test_stale_form_is_rejected_without_second_part_update(self):
        row, part, _, _ = self.imported()
        stale = self.edit_form(row, mileage='14000')
        self.assertEqual(self.edit(row, mileage='12000').status_code, 302)
        count = len(self.events(row))
        response = self.client.post(f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit', data=stale)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.values(part), ('2026-10-22', 12000))
        self.assertEqual(len(self.events(row)), count)

    def test_commit_failure_rolls_back_parent_part_and_audit_then_retries(self):
        row, part, _, _ = self.imported()
        count = len(self.events(row))
        with patch.object(self.m.db.session, 'commit', side_effect=SQLAlchemyError('U32 isolated failure')):
            response = self.edit(row, mileage='12000', completion_date='2026-10-23')
        self.assertEqual(response.status_code, 500)
        self.m.db.session.refresh(row)
        self.assertEqual((row.mileage, row.completion_date), (10000, '2026-10-22'))
        self.assertEqual(self.values(part), ('2026-10-22', 10000))
        self.assertEqual(len(self.events(row)), count)
        self.assertEqual(self.edit(row, mileage='12000', completion_date='2026-10-23').status_code, 302)
        self.assertEqual(self.values(part), ('2026-10-23', 12000))


if __name__ == '__main__':
    unittest.main()
