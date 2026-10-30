"""Both independent facts can refer to one verified case/original without cloning it."""
import unittest
from test_invoice_plan_actuals import InvoicePlanActualTests as _Invoice
from test_m06_new_kinds import NewKindTests as _Kinds


class SharedOriginalTests(unittest.TestCase):
    setUpClass = classmethod(_Invoice.setUpClass.__func__)
    tearDownClass = classmethod(_Invoice.tearDownClass.__func__)
    setUp = _Invoice.setUp
    tearDown = _Invoice.tearDown
    draft = _Invoice.draft
    form = _Invoice.form
    imported = _Invoice.imported
    complete = _Kinds.complete

    def original(self):
        record, draft = self.imported(end='2026-10-28')
        doc = self.m.VehicleMaintenanceDocument(company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=record.id, source_draft_id=draft.id, source_record_index=0,
            created_by_username='admin', financial_status='confirmed', parts_status='not_applicable')
        self.m.db.session.add(doc)
        self.m.db.session.commit()
        return record, draft, doc

    def test_two_facts_share_verified_original_and_case_without_completing_each_other(self):
        case, draft, document = self.original()
        for kind in ('12month', 'vehicle_inspection'):
            self.complete(kind, document_id=draft.id, confirmed=True, confirmation='点検原本と実施日・種別を確認')
        evidence = self.m.inspection_plans.Evidence.query.all()
        self.assertEqual(len(evidence), 2)
        self.assertEqual({e.document_id for e in evidence}, {draft.id})
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 1)
        self.assertEqual(self.m.VehicleMaintenanceDocument.query.count(), 1)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 0)
        latest = self.m.inspection_plans.latest('TEST', self.vehicle.id)
        for kind in ('12month', 'vehicle_inspection'):
            self.assertEqual(latest[kind]['maintenance_record_id'], case.id)
            response = self.client.get(latest[kind]['record_url'])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, draft.source_file)

    def test_wrong_vehicle_or_mismatched_source_index_is_not_accepted(self):
        _, draft, document = self.original()
        document.source_record_index = 99
        self.m.db.session.commit()
        payload = dict(vehicle_record_id=self.vehicle.id, kind='vehicle_inspection',
            kind_contract='independent-v1', performed_date='2026-09-12',
            document_id=draft.id, confirmed=True, confirmation='確認')
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/execution/preview', json=payload).status_code, 400)
        document.source_record_index = 0
        other = self.m.Vehicle(company_code='TEST', chassis_number='OTHER-M06')
        self.m.db.session.add(other)
        self.m.db.session.commit()
        payload['vehicle_record_id'] = other.id
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/execution/preview', json=payload).status_code, 400)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(), 0)

    def test_confirmed_legacy_invoice_source_json_can_link_without_new_document_row(self):
        case, draft = self.imported()
        self.assertEqual(self.m.VehicleMaintenanceDocument.query.count(), 0)
        self.complete('12month', document_id=draft.id, confirmed=True, confirmation='既存原本の種別を確認')
        latest = self.m.inspection_plans.latest('TEST', self.vehicle.id)
        self.assertEqual(latest['12month']['maintenance_record_id'], case.id)
        self.assertEqual(self.m.VehicleMaintenanceDocument.query.count(), 0)

    def test_ambiguous_case_reference_is_not_guessed(self):
        _, draft, _ = self.original()
        case = self.m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            category='整備', status='完了', entry_date='2026-09-12', completion_date='2026-09-12',
            content='別案件', created_by_username='admin')
        self.m.db.session.add(case)
        self.m.db.session.flush()
        document = self.m.VehicleMaintenanceDocument(company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=case.id, source_draft_id=draft.id, source_record_index=1,
            created_by_username='admin', financial_status='confirmed', parts_status='not_applicable')
        self.m.db.session.add(document)
        self.m.db.session.commit()
        response = self.client.post('/api/vehicle/inspection-plans/execution/preview', json=dict(
            vehicle_record_id=self.vehicle.id, kind='12month', kind_contract='independent-v1',
            performed_date='2026-09-12', document_id=draft.id, confirmed=True, confirmation='原本確認'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(), 0)


del _Invoice, _Kinds
