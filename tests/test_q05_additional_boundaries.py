"""Additional Q05 probes; synthetic evidence and temporary SQLite only."""
from datetime import datetime
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_workflow_regressions as fixtures
import test_maintenance_timing as timing_fixtures
from test_q05_inspection_dates import clock_at
from dkss_app.analysis import calculate_adopted_maintenance_rule_timing as calculate
from dkss_app.notifications import format_notification_datetime
from dkss_app.vehicle_karte import validate_vehicle_maintenance_form


class TimingBoundaryTests(unittest.TestCase):
    case = timing_fixtures.MaintenanceTimingTests.case

    def evaluate(self, action, as_of, baseline='2028-02-28', value=1):
        rule, facts, summary = self.case(action, 'period_days', value)
        facts['as_of'] = summary['end_date'] = as_of
        facts['part_replacements'][0]['latest_dated_replacement'] = baseline
        facts['inspection_items'][0]['inspection_date'] = baseline
        return calculate(rule, 'エアドライヤ', facts, summary)

    def test_due_day_is_reached_but_not_overdue(self):
        with patch('dkss_app.common.datetime', clock_at('2028-03-01T00:00:00+00:00')):
            for action in ('replace', 'inspect'):
                for day, status, remaining, overdue in (
                    ('2028-02-28', 'not_reached_at_reference_dates', 1, 0),
                    ('2028-02-29', 'threshold_reached', 0, 0),
                    ('2028-03-01', 'threshold_reached', 0, 1),
                ):
                    with self.subTest(action=action, day=day):
                        result = self.evaluate(action, day)
                        self.assertEqual(result['status'], status)
                        criterion = result['criteria'][0]
                        self.assertEqual(criterion['due_date'], '2028-02-29')
                        self.assertEqual((criterion['remaining_days'], criterion['overdue_days']),
                                         (remaining, overdue))

    def test_reference_day_becomes_valid_at_tokyo_midnight(self):
        for action in ('replace', 'inspect'):
            for instant, expected in (
                ('2028-02-28T14:59:59+00:00', 'invalid_reference_date'),
                ('2028-02-28T15:00:00+00:00', 'recorded_threshold_reached'),
            ):
                with self.subTest(action=action, instant=instant), patch(
                    'dkss_app.common.datetime', clock_at(instant)
                ):
                    self.assertEqual(self.evaluate(action, '2028-02-29')['reason'], expected)

    def test_unknown_month_only_invalid_and_future_baselines_are_held(self):
        with patch('dkss_app.common.datetime', clock_at('2028-03-01T00:00:00+00:00')):
            for action in ('replace', 'inspect'):
                for value in (None, '', '2028-02', '2028-02-30', '2028-03-02'):
                    with self.subTest(action=action, value=value):
                        result = self.evaluate(action, '2028-03-01', value)
                        self.assertEqual(result['status'], 'held')
                        self.assertFalse(result['calculation_permitted'])
                        self.assertEqual(result['criteria'], [])


class DisplayAndInputBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = fixtures.WorkflowRegressionTests.setUp
    tearDown = fixtures.WorkflowRegressionTests.tearDown

    def notification(self, value, mode, zone='Asia/Tokyo'):
        with self.m.app.test_request_context('/'):
            from flask import request
            request.environ['dkss.notification_local_now'] = datetime(
                2028, 2, 29, 0, 0, tzinfo=ZoneInfo(zone))
            return format_notification_datetime(value, mode)

    def test_utc_midnight_boundary_controls_notification_group(self):
        for value, key, group in (
            ('2028-02-28T14:59:59Z', '2028-02-28', '昨日'),
            ('2028-02-28T15:00:00Z', '2028-02-29', '今日'),
        ):
            self.assertEqual(self.notification(value, 'key'), key)
            self.assertEqual(self.notification(value, 'group'), group)

    def test_equivalent_offsets_preserve_sort_microseconds(self):
        values = ('2028-02-28T15:00:00.123456Z',
                  '2028-02-29T00:00:00.123456+09:00',
                  '2028-02-28T05:00:00.123456-10:00')
        for value in values:
            self.assertEqual(self.notification(value, 'sort'), '2028-02-28 15:00:00.123456')
            self.assertEqual(self.notification(value, 'time'), '00:00')

    def test_user_timezone_keeps_previous_day_and_legacy_naive_meaning(self):
        self.assertEqual(self.notification('2028-02-28T15:00:00Z', 'key', 'Pacific/Honolulu'),
                         '2028-02-28')
        self.assertEqual(self.notification('2028-02-29 00:00:00', 'sort'),
                         '2028-02-28 15:00:00.000000')

    def test_unknown_and_invalid_notification_dates_remain_unknown(self):
        for value in (None, '', '2028-02', '2028-02-30', '2028-02-29T24:00:00'):
            self.assertEqual(self.notification(value, 'key'), 'unknown')
            self.assertEqual(self.notification(value, 'group'), '日時不明')
            self.assertEqual(self.notification(value, 'time'), '')

    def test_maintenance_form_rejects_invalid_dates_on_each_field(self):
        for field in ('entry_date', 'completion_date', 'invoice_date'):
            for value in ('2028-02', '2028-2-29', '2028-02-30', '1900-02-29',
                          '2028-02-29T00:00:00'):
                with self.subTest(field=field, value=value):
                    form = dict(content='架空整備', entry_date='2028-02-28')
                    form[field] = value
                    _, errors = validate_vehicle_maintenance_form(form)
                    self.assertEqual([key for _, key in errors], [field])

    def test_maintenance_form_keeps_blank_dates_and_independent_invoice_date(self):
        form = dict(content='架空整備', entry_date='', completion_date='', invoice_date='')
        values, errors = validate_vehicle_maintenance_form(form, entry_date_required=False)
        self.assertEqual(errors, [])
        for field in ('entry_date', 'completion_date', 'invoice_date'):
            self.assertIsNone(values[field])
        _, errors = validate_vehicle_maintenance_form(form)
        self.assertEqual([key for _, key in errors], ['entry_date'])
        for end in ('2028-02-29', '2028-03-01'):
            values, errors = validate_vehicle_maintenance_form(dict(
                content='架空整備', entry_date='2028-02-29', completion_date=end,
                invoice_date='2027-12-31'))
            self.assertEqual(errors, [])
            self.assertEqual(values['invoice_date'], '2027-12-31')

    def test_maintenance_form_rejects_reversal_at_leap_and_year_boundaries(self):
        for start, end in (('2028-03-01', '2028-02-29'), ('2028-01-01', '2027-12-31')):
            _, errors = validate_vehicle_maintenance_form(dict(
                content='架空整備', entry_date=start, completion_date=end))
            self.assertEqual([key for _, key in errors], ['completion_date'])

    def test_direct_new_post_rejects_invalid_or_reversed_dates_without_records(self):
        for start, end in (('2028-02', ''), ('2028-02-30', ''),
                           ('2028-03-01', '2028-02-29')):
            response = self.client.post(
                f'/vehicle/karte/{self.vehicle.id}/maintenance/new',
                data=dict(content='架空整備', entry_date=start, completion_date=end))
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 0)
            self.assertEqual(self.m.VehiclePartReplacement.query.count(), 0)

    def test_direct_edit_post_preserves_existing_dates_after_rejection(self):
        row, form = fixtures.WorkflowRegressionTests.maintenance(
            self, linked=False, arrival='2026-10-01')
        original = (row.entry_date, row.completion_date, row.content)
        for end in ('2026-09-30', '2026-10', '2026-02-30'):
            form.update(entry_date='2026-10-01', completion_date=end)
            response = self.client.post(
                f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit', data=form)
            self.assertEqual(response.status_code, 400)
            self.m.db.session.expire_all()
            self.assertEqual((row.entry_date, row.completion_date, row.content), original)

    def test_driver_safe_days_changes_at_tokyo_midnight(self):
        from dkss_app import masters

        driver = self.m.Driver(company_code='TEST', employee_id='q05-driver', name='架空乗務者')
        self.m.db.session.add(driver)
        for instant, start, expected in (
            ('2026-12-31T14:59:59+00:00', '2026-12-31', '0日継続中'),
            ('2026-12-31T15:00:00+00:00', '2026-12-31', '1日継続中'),
            ('2028-02-28T15:00:00+00:00', '2028-02-28', '1日継続中'),
            ('2028-02-29T15:00:00+00:00', '2028-02-28', '2日継続中'),
        ):
            clock = clock_at(instant)
            # datetime.today() on a UTC server must use the same fixed instant.
            clock.today = classmethod(lambda cls: cls.now())
            driver.safe_start_date = start
            self.m.db.session.commit()
            captured = {}

            def render(template, **context):
                captured.update(context)
                return 'captured'

            with self.subTest(instant=instant), patch.object(
                masters._dkss_common, 'datetime', clock
            ), patch.object(masters._dkss_common, 'render_template', side_effect=render):
                response = self.client.get('/master/drivers')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(captured['drivers'][0]['safe_days_display'], expected)
            self.m.db.session.refresh(driver)
            self.assertEqual(driver.safe_start_date, start)


if __name__ == '__main__':
    unittest.main()
