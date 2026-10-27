"""Q05 inspection calendar and Tokyo-midnight behavior with synthetic records."""
from datetime import date, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_inspection_plans as fixtures
from vehicle_inspection_plans import iso_date, month, add_months
from vehicle_inspection_alerts import reminder_phase, expiry_phase, local_today


def clock_at(value):
    instant = datetime.fromisoformat(value)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    return Clock


class InspectionCalendarTests(unittest.TestCase):
    def test_days_accept_only_exact_calendar_dates(self):
        for value in (None, '', ' ', '2028-02', '2028-2-29', '2028/02/29',
                      '2026-02-29', '1900-02-29', '2028-02-30', '2028-02-29T00:00:00'):
            with self.subTest(value=value):
                self.assertIsNone(iso_date(value))
        self.assertEqual(iso_date('2000-02-29'), date(2000, 2, 29))
        self.assertEqual(iso_date('2028-02-29'), date(2028, 2, 29))

    def test_month_precision_does_not_create_a_performed_day(self):
        self.assertEqual(month('2028-02'), '2028-02')
        self.assertIsNone(iso_date('2028-02'))
        for value in (None, '', '2028-2', '2028-00', '2028-13', '2028-02-29'):
            self.assertIsNone(month(value))

    def test_month_arithmetic_clamps_to_calendar_month_end(self):
        for start, count, end in [('2028-01-31', 1, '2028-02-29'),
            ('2027-01-31', 1, '2027-02-28'), ('2028-02-29', 12, '2029-02-28'),
            ('2026-12-31', 3, '2027-03-31'), ('2028-03-31', -1, '2028-02-29'),
            ('2000-02-29', 1200, '2100-02-28')]:
            with self.subTest(start=start, count=count):
                self.assertEqual(add_months(date.fromisoformat(start), count).isoformat(), end)

    def test_unreserved_plan_changes_phase_at_month_boundaries(self):
        plan = SimpleNamespace(status='planned', planned_month='2027-01', reservation_date=None)
        for day, expected in [('2026-11-30', None), ('2026-12-01', 'prior_booking'),
                              ('2027-01-01', 'month_booking'), ('2027-02-01', 'month_elapsed')]:
            result = reminder_phase(plan, date.fromisoformat(day))
            self.assertEqual(result[0] if result else None, expected)

    def test_booking_thresholds_include_leap_day_and_exact_booking_day(self):
        plan = SimpleNamespace(status='planned', planned_month='2028-03', reservation_date='2028-03-01')
        for day, expected in [('2028-02-22', None), ('2028-02-23', 'booking_7days'),
                              ('2028-02-29', 'booking_1day'), ('2028-03-01', 'booking_1day'),
                              ('2028-03-02', 'execution_check')]:
            result = reminder_phase(plan, date.fromisoformat(day))
            self.assertEqual(result[0] if result else None, expected)

    def test_expiry_thresholds_never_mark_expired_on_expiry_day(self):
        for expiry in (date(2028, 2, 29), date(2027, 1, 1)):
            from datetime import timedelta
            for delta, expected in [(-7, 'expiry_7days'), (-1, 'expiry_1day'),
                                    (0, 'expiry_today'), (1, 'expiry_elapsed')]:
                result = expiry_phase(expiry, expiry + timedelta(days=delta))
                self.assertEqual(result[0], expected)

    def test_missing_invalid_or_cancelled_plans_have_no_reminder(self):
        for value in (None, '', '2028-13', '2028-2'):
            plan = SimpleNamespace(status='planned', planned_month=value, reservation_date=None)
            self.assertIsNone(reminder_phase(plan, date(2028, 3, 1)))
        plan = SimpleNamespace(status='cancelled', planned_month='2028-02', reservation_date=None)
        self.assertIsNone(reminder_phase(plan, date(2028, 3, 1)))

    def test_notification_today_uses_tokyo_not_server_day(self):
        for instant, expected in [('2027-12-31T14:59:59+00:00', '2027-12-31'),
                                  ('2027-12-31T15:00:00+00:00', '2028-01-01'),
                                  ('2028-02-28T15:00:00+00:00', '2028-02-29')]:
            with patch('vehicle_inspection_alerts.datetime', clock_at(instant)):
                self.assertEqual(local_today().isoformat(), expected)


class InspectionDateRouteTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.InspectionPlanTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.InspectionPlanTests.tearDownClass.__func__)
    setUp = fixtures.InspectionPlanTests.setUp
    tearDown = fixtures.InspectionPlanTests.tearDown
    change = fixtures.InspectionPlanTests.change
    save = fixtures.InspectionPlanTests.save
    complete = fixtures.InspectionPlanTests.complete

    def test_invalid_and_wrong_month_reservation_preview_does_not_write(self):
        for value in ('2028-02-30', '2028-2-29', '2028-03-01'):
            row = self.change(mon='2028-02')
            row['reservation_date'] = value
            result = self.client.post('/api/vehicle/inspection-plans/preview', json={'changes': [row]})
            self.assertEqual(result.status_code, 400)
            self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)
            self.assertEqual(self.m.VehicleInspectionPlanEvent.query.count(), 0)

    def test_leap_day_booking_and_month_only_plan_keep_their_precision(self):
        row = self.change(mon='2028-02')
        row['reservation_date'] = '2028-02-29'
        self.save([row, self.change(mon='2028-03')])
        rows = self.m.VehicleInspectionPlan.query.order_by(self.m.VehicleInspectionPlan.planned_month).all()
        self.assertEqual((rows[0].planned_month, rows[0].reservation_date), ('2028-02', '2028-02-29'))
        self.assertEqual(rows[1].planned_month, '2028-03')
        self.assertIsNone(rows[1].reservation_date)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(), 0)

    def test_future_execution_becomes_today_at_tokyo_midnight(self):
        payload = dict(vehicle_record_id=self.vehicle.id, kind='3month', performed_date='2028-02-29')
        with patch('vehicle_inspection_plans.datetime', clock_at('2028-02-28T14:59:59+00:00')):
            self.assertEqual(self.client.post('/api/vehicle/inspection-plans/execution/preview', json=payload).status_code, 400)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(), 0)
        with patch('vehicle_inspection_plans.datetime', clock_at('2028-02-28T15:00:00+00:00')):
            self.complete(performed='2028-02-29')
        execution = self.m.inspection_plans.Execution.query.one()
        self.assertEqual((execution.performed_date, execution.next_month), ('2028-02-29', '2028-05'))

    def test_unknown_certificate_expiry_does_not_invent_candidate(self):
        for value in (None, '', '2028-02', '2028-02-30'):
            self.vehicle.inspection_expiry = value
            self.m.db.session.commit()
            response = self.client.get(f'/api/vehicle/inspection-plans?detail=1&vehicle_id={self.vehicle.id}')
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('12month', response.json['plans'])
            self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)
            self.assertEqual(self.m.inspection_plans.Execution.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
