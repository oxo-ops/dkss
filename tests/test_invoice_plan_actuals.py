"""Invoice facts are already performed; plan summaries link to the preserved original."""
import hashlib
import json
import unittest
import test_q05_document_dates as fixtures


class InvoicePlanActualTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.DocumentCompletionDateTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.DocumentCompletionDateTests.tearDownClass.__func__)
    setUp = fixtures.DocumentCompletionDateTests.setUp
    tearDown = fixtures.DocumentCompletionDateTests.tearDown
    draft = fixtures.DocumentCompletionDateTests.draft
    form = fixtures.DocumentCompletionDateTests.form

    def imported(self, end='2026-10-28'):
        draft = self.draft('maintenance')
        data = self.form(start='2026-10-28', end=end)
        data.update({'content_q05_0': 'オイル量の確認・補充', 'maintenance_category_q05_0': '整備',
                     'total_cost_q05_0': '3300'})
        response = self.client.post('/vehicle/data-import/q05-batch/confirm', data=data)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        return self.m.VehicleMaintenanceRecord.query.one(), draft

    def actuals(self, **args):
        response = self.client.get('/api/vehicle/inspection-plans', query_string={
            'scope': 'company', 'year': 2026, 'month': '2026-10', **args})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.json['invoice_actuals']

    def test_confirm_import_is_performed_and_links_original_without_plan_writes(self):
        record, draft = self.imported()
        self.assertEqual(record.status, '完了')
        self.assertEqual(record.display_status, '実施済み')
        rows = self.actuals()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['summary'], '2026/10/28 オイル量の確認・補充 実施')
        response = self.client.get(rows[0]['source_url'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, draft.source_file)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)
        self.assertEqual(self.m.VehiclePartReplacement.query.count(), 0)

    def test_legacy_invoice_correction_preserves_state_source_and_record_count(self):
        record, draft = self.imported()
        record.status = None
        self.m.db.session.commit()
        source_hash = hashlib.sha256(draft.source_file).hexdigest()
        url = f'/vehicle/karte/{self.vehicle.id}/maintenance/{record.id}/edit'
        # Resolve the application's actual form URL.
        with self.m.app.test_request_context():
            from flask import url_for
            url = url_for('vehicle_karte_maintenance_form', vehicle_record_id=self.vehicle.id, record_id=record.id)
        html = self.client.get(url).get_data(as_text=True)
        self.assertIn('訂正を保存', html)
        self.assertNotIn('value="complete"', html)
        data = {'content': 'オイル量の確認・補充（読取訂正）', 'entry_date': record.entry_date,
                'completion_date': record.completion_date, 'maintenance_action': 'save',
                'status': '整備中', 'total_cost': '3300',
                'record_version': self.m.vehicle_maintenance_record_version(record)}
        response = self.client.post(url, data=data)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        self.m.db.session.refresh(record)
        self.assertIsNone(record.status)
        self.assertEqual(record.display_status, '実施済み')
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 1)
        self.assertEqual(str(record.total_cost), '3300.00')
        self.assertEqual(hashlib.sha256(draft.source_file).hexdigest(), source_hash)
        self.assertIn('読取訂正', self.actuals()[0]['summary'])

    def test_invoice_completion_request_is_rejected_without_writes(self):
        record, _ = self.imported()
        with self.m.app.test_request_context():
            from flask import url_for
            url = url_for('vehicle_karte_maintenance_form', vehicle_record_id=self.vehicle.id, record_id=record.id)
        count = self.m.VehicleMaintenanceRecordEvent.query.count()
        response = self.client.post(url, data={
            'content': '変更しない', 'entry_date': record.entry_date,
            'completion_date': record.completion_date, 'maintenance_action': 'complete',
            'record_version': self.m.vehicle_maintenance_record_version(record)})
        self.assertEqual(response.status_code, 400)
        self.m.db.session.refresh(record)
        self.assertEqual(record.content, 'オイル量の確認・補充')
        self.assertEqual(self.m.VehicleMaintenanceRecordEvent.query.count(), count)

    def test_unknown_execution_date_is_not_replaced_with_invoice_or_entry_date(self):
        record, _ = self.imported(end='')
        rows = self.actuals()
        self.assertIsNone(rows[0]['performed_date'])
        self.assertEqual(rows[0]['summary'], '実施日不明 オイル量の確認・補充 実施')
        self.assertIsNone(record.completion_date)

    def test_read_replay_does_not_duplicate_or_complete_existing_plan(self):
        self.imported()
        plan = self.m.VehicleInspectionPlan(company_code='TEST', vehicle_record_id=self.vehicle.id,
            kind='3month', planned_month='2026-10', period_key='2026-10',
            status='planned', source='manual', version=1)
        self.m.db.session.add(plan)
        self.m.db.session.commit()
        for _ in range(2):
            self.assertEqual(len(self.actuals()), 1)
        self.m.db.session.refresh(plan)
        self.assertEqual(plan.status, 'planned')
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 1)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 1)

    def test_foreign_draft_and_foreign_vehicle_cannot_supply_source(self):
        record, draft = self.imported()
        good_url = self.actuals()[0]['source_url']
        draft.company_code = 'OTHER'
        self.m.db.session.commit()
        self.assertEqual(self.actuals(), [])
        self.assertEqual(self.client.get(good_url).status_code, 404)
        draft.company_code = 'TEST'
        draft.result_json = json.dumps({'records': [{'vehicle_record_id': self.vehicle.id + 99}]})
        self.m.db.session.commit()
        self.assertEqual(self.actuals(), [])
        self.assertEqual(self.client.get(good_url).status_code, 404)

    def test_noncompleted_source_and_outside_year_are_not_displayed(self):
        record, draft = self.imported()
        self.assertEqual(self.actuals(year=2024), [])
        draft.status = 'preview'
        self.m.db.session.commit()
        self.assertEqual(self.actuals(), [])

    def test_invoice_status_filter_matches_legacy_and_new_records(self):
        record, _ = self.imported()
        record.status = None
        self.m.db.session.commit()
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/maintenance',
                                   query_string={'status': '実施済み'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('オイル量の確認・補充', response.get_data(as_text=True))

    def test_confirmed_later_invoice_uses_existing_manual_record_once(self):
        record, draft = self.imported()
        record.invoice_details_json = '{}'
        record.status = '完了'
        doc = self.m.VehicleMaintenanceDocument(
            company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=record.id, source_draft_id=draft.id,
            source_record_index=0, created_by_username='admin',
            financial_status='pending', parts_status='not_applicable')
        self.m.db.session.add(doc)
        self.m.db.session.commit()
        self.assertEqual(self.actuals(), [])
        doc.financial_status = 'confirmed'
        self.m.db.session.commit()
        for _ in range(2):
            rows = self.actuals()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['maintenance_record_id'], record.id)
            self.assertEqual(self.client.get(rows[0]['source_url']).data, draft.source_file)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 1)

    def test_company_scope_excludes_foreign_record_even_with_own_source(self):
        record, _ = self.imported()
        record.company_code = 'OTHER'
        self.m.db.session.commit()
        self.assertEqual(self.actuals(), [])

    def test_multiple_confirmed_originals_share_one_summary(self):
        record, draft = self.imported()
        second = self.m.VehicleDocumentImportDraft(
            id='second-source', batch_id='second-batch', company_code='TEST',
            created_by_username='admin', document_type='maintenance',
            source_filename='second.pdf', source_file=draft.source_file,
            source_sha256=draft.source_sha256, result_json=draft.result_json, status='completed')
        self.m.db.session.add(second)
        self.m.db.session.flush()
        self.m.db.session.add(self.m.VehicleMaintenanceDocument(
            company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=record.id, source_draft_id=second.id,
            source_record_index=0, created_by_username='admin',
            financial_status='confirmed', parts_status='not_applicable'))
        self.m.db.session.commit()
        rows = self.actuals()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]['sources']), 2)
        for source in rows[0]['sources']:
            self.assertEqual(self.client.get(source['url']).data, draft.source_file)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 1)


if __name__ == '__main__':
    unittest.main()
