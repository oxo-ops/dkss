"""Identical acceptance cases run before/after the three independent review fixes."""
import unittest
from test_m06_confirmed_periodic_notice import ConfirmedPeriodicNoticeTests as _Confirmed
from test_inspection_plans import InspectionPlanTests as _Plans


class ReviewRegressionTests(unittest.TestCase):
    setUpClass = classmethod(_Confirmed.setUpClass.__func__)
    tearDownClass = classmethod(_Confirmed.tearDownClass.__func__)
    setUp = _Confirmed.setUp
    tearDown = _Confirmed.tearDown
    upload_inspection = _Confirmed.upload_inspection
    inspection_form = _Confirmed.inspection_form
    confirmed_plan = _Confirmed.confirmed_plan
    run_alerts = _Confirmed.run_alerts
    change = _Plans.change
    save = _Plans.save

    def test_confirmed_legacy_kind_survives_month_change(self):
        plan, _, _ = self.confirmed_plan()
        old_kind = plan.kind
        change = self.change(mon='2026-11', kind='12month')
        change.update(id=plan.id, version=plan.version, period_key=plan.period_key,
                      reservation_date='2026-11-12')
        self.save([change])
        self.m.db.session.refresh(plan)
        self.assertEqual(plan.kind, old_kind)
        self.assertEqual(plan.planned_month, '2026-11')
        self.assertEqual(self.m.inspection_plans.plan_kind(plan), '12month')

    def test_completed_legacy_manual_plan_uses_confirmed_completion_record(self):
        _, record, _ = self.confirmed_plan()
        plan = self.m.VehicleInspectionPlan(company_code='TEST', vehicle_record_id=self.vehicle.id,
            kind='12month', period_key='2026-09', planned_month='2026-09', source='manual',
            source_record_id=None, completed_record_id=record.id, status='completed', version=2)
        self.m.db.session.add(plan)
        self.m.db.session.commit()
        before = {c.name: getattr(plan, c.name) for c in plan.__table__.columns}
        self.assertEqual(self.m.inspection_plans.record_kind(record), '12month')
        self.assertEqual(self.m.inspection_plans.plan_kind(plan), '12month')
        self.assertEqual({c.name: getattr(plan, c.name) for c in plan.__table__.columns}, before)

    def test_new_expiry_notice_does_not_close_or_read_old_held_receipt(self):
        self.vehicle.inspection_expiry = '2026-09-30'
        self.m.db.session.commit()
        self.run_alerts('2026-10-22')
        receipt = self.m.inspection_alerts.ExpiryDelivery.query.one()
        notice = self.m.Notification.query.one()
        legacy = self.m.VehicleInspectionPlan(company_code='TEST', vehicle_record_id=self.vehicle.id,
            kind='12month', period_key='2026-09', planned_month='2026-09', status='planned',
            source='manual', version=1)
        self.m.db.session.add(legacy)
        self.vehicle.inspection_expiry = '2027-09-30'
        self.m.db.session.commit()
        self.run_alerts('2026-11-08')
        snapshots = [{c.name: getattr(row, c.name) for c in row.__table__.columns}
                     for row in (receipt, notice)]
        report = self.run_alerts('2027-08-01')
        self.assertEqual(report['expiry_candidates'], 1)
        self.assertEqual(self.m.inspection_alerts.ExpiryDelivery.query.count(), 2)
        for row, snapshot in zip((receipt, notice), snapshots):
            self.m.db.session.refresh(row)
            self.assertEqual({c.name: getattr(row, c.name) for c in row.__table__.columns}, snapshot)


del _Confirmed, _Plans
