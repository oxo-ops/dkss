"""A confirmed periodic booking cannot suppress or close an independent car expiry."""
import unittest
from test_m06_confirmed_periodic_notice import ConfirmedPeriodicNoticeTests as _Confirmed


class ExpiryKindReviewTests(unittest.TestCase):
    setUpClass = classmethod(_Confirmed.setUpClass.__func__)
    tearDownClass = classmethod(_Confirmed.tearDownClass.__func__)
    setUp = _Confirmed.setUp
    tearDown = _Confirmed.tearDown
    upload_inspection = _Confirmed.upload_inspection
    inspection_form = _Confirmed.inspection_form
    confirmed_plan = _Confirmed.confirmed_plan
    run_alerts = _Confirmed.run_alerts

    def test_confirmed_legacy_periodic_plan_does_not_suppress_car_expiry(self):
        plan, record, _ = self.confirmed_plan()
        self.assertEqual(self.m.inspection_plans.plan_kind(plan), '12month')
        self.assertEqual(self.m.inspection_plans.record_kind(record), '12month')
        report = self.run_alerts('2026-10-22')
        self.assertEqual(report['expiry_candidates'], 1)
        self.assertEqual(self.m.inspection_alerts.ExpiryDelivery.query.count(), 1)
        self.assertEqual(self.m.inspection_alerts.Delivery.query.count(), 1)

    def test_later_periodic_import_does_not_close_existing_car_expiry_receipt(self):
        self.vehicle.inspection_expiry = '2026-10-30'
        self.m.db.session.commit()
        self.run_alerts('2026-10-22')
        receipt = self.m.inspection_alerts.ExpiryDelivery.query.one()
        notice = self.m.Notification.query.one()
        before = [{c.name: getattr(row, c.name) for c in row.__table__.columns} for row in (receipt, notice)]
        self.confirmed_plan()
        self.run_alerts('2026-10-22')
        for row, snapshot in zip((receipt, notice), before):
            self.m.db.session.refresh(row)
            self.assertEqual({c.name: getattr(row, c.name) for c in row.__table__.columns}, snapshot)
        self.assertTrue(self.m.inspection_alerts.workflow(notice)['requires_action'])


del _Confirmed
