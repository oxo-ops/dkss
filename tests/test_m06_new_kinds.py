"""Independent new facts through the real scoped preview/save routes."""
import unittest
import json
from datetime import date
from test_inspection_plans import InspectionPlanTests as _Plans


class NewKindTests(unittest.TestCase):
    setUpClass = classmethod(_Plans.setUpClass.__func__)
    tearDownClass = classmethod(_Plans.tearDownClass.__func__)
    setUp = _Plans.setUp
    tearDown = _Plans.tearDown
    change = _Plans.change
    upload_inspection = _Plans.upload_inspection
    inspection_form = _Plans.inspection_form

    def save_plan(self, kind, **extra):
        payload = {'changes': [self.change(kind=kind, **extra)], 'kind_contract': 'independent-v1'}
        preview = self.client.post('/api/vehicle/inspection-plans/preview', json=payload)
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        payload['token'] = preview.json['token']
        response = self.client.post('/api/vehicle/inspection-plans/save', json=payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def complete(self, kind, **extra):
        payload = dict(vehicle_record_id=self.vehicle.id, kind=kind,
                       performed_date='2026-09-12', kind_contract='independent-v1', **extra)
        preview = self.client.post('/api/vehicle/inspection-plans/execution/preview', json=payload)
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        payload['token'] = preview.json['token']
        response = self.client.post('/api/vehicle/inspection-plans/execution/save', json=payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def test_both_new_plans_coexist_in_same_month(self):
        self.save_plan('12month')
        self.save_plan('vehicle_inspection')
        self.assertEqual({p.kind for p in self.m.VehicleInspectionPlan.query.all()},
                         {'periodic_12month', 'vehicle_inspection'})

    def test_same_day_actuals_remain_independent(self):
        self.complete('12month')
        self.complete('vehicle_inspection')
        rows = self.m.inspection_plans.Execution.query.all()
        self.assertEqual({r.kind for r in rows}, {'periodic_12month', 'vehicle_inspection'})
        self.assertEqual(len(rows), 2)
        self.assertIsNone(next(r.next_month for r in rows if r.kind == 'vehicle_inspection'))

    def test_expiry_is_only_a_car_candidate(self):
        self.vehicle.inspection_expiry = '2026-12-01'
        self.m.db.session.commit()
        summary = self.m.inspection_plans.summary('TEST', self.vehicle.id)
        self.assertNotIn('12month', summary)
        self.assertEqual(summary['vehicle_inspection']['source'], 'expiry')

    def test_stale_annual_writer_is_rejected_without_writing(self):
        response = self.client.post('/api/vehicle/inspection-plans/preview',
                                    json={'changes': [self.change(kind='12month')]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)

    def test_periodic_evidence_cannot_change_car_expiry(self):
        self.vehicle.inspection_expiry = '2026-12-01'
        self.m.db.session.commit()
        response = self.client.post('/api/vehicle/inspection-plans/execution/preview', json=dict(
            vehicle_record_id=self.vehicle.id, kind='12month', performed_date='2026-09-12',
            kind_contract='independent-v1', confirmation='原本確認', confirmed=True, new_expiry='2027-12-01'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.vehicle.inspection_expiry, '2026-12-01')
        self.assertEqual(self.m.inspection_plans.Execution.query.count(), 0)

    def legacy_plan(self):
        plan = self.m.VehicleInspectionPlan(company_code='TEST', vehicle_record_id=self.vehicle.id,
            kind='12month', period_key='2026-09', planned_month='2026-09', status='planned',
            source='manual', version=1)
        self.m.db.session.add(plan)
        self.m.db.session.commit()
        return plan

    def test_unknown_overlap_requires_new_basis_and_preserves_old_plan(self):
        old = self.legacy_plan()
        before = {c.name: getattr(old, c.name) for c in old.__table__.columns}
        payload = dict(vehicle_record_id=self.vehicle.id, kind='12month', performed_date='2026-09-12',
                       kind_contract='independent-v1')
        denied = self.client.post('/api/vehicle/inspection-plans/execution/preview', json=payload)
        self.assertEqual(denied.status_code, 409)
        self.complete('12month', confirmed=True, confirmation='新規分の12か月点検を原本で確認')
        self.m.db.session.refresh(old)
        self.assertEqual({c.name: getattr(old, c.name) for c in old.__table__.columns}, before)
        execution = self.m.inspection_plans.Execution.query.one()
        self.assertIsNone(execution.plan_id)
        self.assertEqual(execution.kind, 'periodic_12month')

    def test_plan_overlap_basis_and_candidates_are_audited(self):
        old = self.legacy_plan()
        self.save_plan('vehicle_inspection', mon='2026-09', kind_confirmation='予約原本で車検を確認')
        self.m.db.session.refresh(old)
        self.assertEqual((old.kind, old.status, old.version), ('12month', 'planned', 1))
        event = self.m.VehicleInspectionPlanEvent.query.one()
        detail = json.loads(event.detail_json)
        self.assertEqual(detail['duplicate_candidates'], [old.id])
        self.assertEqual(detail['kind_confirmation'], '予約原本で車検を確認')

    def test_unknown_old_unsent_plan_does_not_generate_notice(self):
        self.legacy_plan()
        self.vehicle.office = '犬塚'
        self.m.User.query.filter_by(username='admin').one().office = '犬塚'
        self.m.db.session.commit()
        self.m.inspection_alerts.run('TEST', today=date(2026, 10, 22), force=True)
        self.assertEqual(self.m.Notification.query.count(), 0)

    def test_unknown_pending_and_ended_receipts_preserve_all_fields(self):
        self.vehicle.office = '犬塚'
        self.m.User.query.filter_by(username='admin').one().office = '犬塚'
        self.m.db.session.commit()
        self.save_plan('12month', mon='2026-09')
        self.m.inspection_alerts.run('TEST', today=date(2026, 10, 22), force=True)
        plan = self.m.VehicleInspectionPlan.query.one()
        receipt = self.m.inspection_alerts.Delivery.query.one()
        notification = self.m.Notification.query.one()
        # Represent an existing old ambiguous fact and its actual historical receipt.
        plan.kind = '12month'
        self.m.db.session.commit()
        for ended in (None, 'closed'):
            receipt.ended_status = ended
            notification.read = False
            self.m.db.session.commit()
            snapshots = [{c.name: getattr(row, c.name) for c in row.__table__.columns}
                         for row in (receipt, notification)]
            self.m.inspection_alerts.run('TEST', today=date(2026, 11, 8), force=True)
            self.assertEqual(self.m.Notification.query.count(), 1)
            for row, snapshot in zip((receipt, notification), snapshots):
                self.m.db.session.refresh(row)
                self.assertEqual({c.name: getattr(row, c.name) for c in row.__table__.columns}, snapshot)

    def test_unknown_expiry_dependency_is_held_even_after_certificate_changes(self):
        self.vehicle.office = '犬塚'
        self.vehicle.inspection_expiry = '2026-09-30'
        self.m.User.query.filter_by(username='admin').one().office = '犬塚'
        self.m.db.session.commit()
        self.m.inspection_alerts.run('TEST', today=date(2026, 10, 22), force=True)
        receipt = self.m.inspection_alerts.ExpiryDelivery.query.one()
        notice = self.m.Notification.query.one()
        self.legacy_plan()
        self.vehicle.inspection_expiry = '2027-09-30'
        self.m.db.session.commit()
        before = {c.name: getattr(receipt, c.name) for c in receipt.__table__.columns}
        self.m.inspection_alerts.run('TEST', today=date(2026, 11, 8), force=True)
        self.m.db.session.refresh(receipt)
        self.m.db.session.refresh(notice)
        self.assertEqual({c.name: getattr(receipt, c.name) for c in receipt.__table__.columns}, before)
        self.assertFalse(notice.read)
        self.assertEqual(self.m.Notification.query.count(), 1)

    def test_new_document_writer_and_karte_keep_distinct_kinds(self):
        from test_inspection_document_ai import extraction, pdf_bytes
        for index, kind in enumerate(('12month', 'vehicle_inspection'), 1):
            source = pdf_bytes(index)
            data = extraction(source)
            data['records'][0].update(inspection_type=kind, inspection_date='2026-09-12',
                inspection_type_raw='12か月点検' if kind == '12month' else '車検',
                next_inspection_date=None, next_inspection_month=None)
            self.upload_inspection(data=data, source=source)
            draft = self.m.VehicleDocumentImportDraft.query.filter_by(status='preview').one()
            response = self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=self.inspection_form(draft))
            self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        records = self.m.VehiclePeriodicInspectionRecord.query.all()
        self.assertEqual({r.inspection_type for r in records}, {'periodic_12month', 'vehicle_inspection'})
        summary = self.m.get_vehicle_periodic_inspection_summary('TEST', self.vehicle.id)
        self.assertEqual(set(summary), {'12month', 'vehicle_inspection'})
        for kind in ('12month', 'vehicle_inspection'):
            page = self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections?inspection_view={kind}')
            self.assertEqual(page.status_code, 200)
            expected = next(r for r in records if self.m.inspection_plans.record_kind(r) == kind)
            other = next(r for r in records if r.id != expected.id)
            self.assertIn(f'id="periodic-record-{expected.id}"', page.get_data(as_text=True))
            self.assertNotIn(f'id="periodic-record-{other.id}"', page.get_data(as_text=True))


del _Plans

if __name__ == '__main__':
    unittest.main()
