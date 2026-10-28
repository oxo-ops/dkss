"""Scheduled starts are labels, never elapsed days or ranking candidates."""
import unittest
from unittest.mock import patch

import test_workflow_regressions as fixtures
from test_q05_inspection_dates import clock_at
from dkss_app import common


class ScheduledSafeStartTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = fixtures.WorkflowRegressionTests.setUp
    tearDown = fixtures.WorkflowRegressionTests.tearDown

    def seed(self, start='2027-01-01'):
        self.user = self.m.User.query.filter_by(company_code='TEST', username='admin').one()
        self.user.office = 'Tokyo'
        self.m.db.session.add(self.m.Office(company_code='TEST', name='Tokyo'))
        self.driver = self.m.Driver(company_code='TEST', employee_id='admin', name='架空本人',
            role='admin', office='Tokyo', safe_start_date=start, vehicles_json='[]', licenses_json='[]')
        self.m.db.session.add(self.driver)
        self.m.db.session.commit()

    def capture(self, path):
        context = {}
        original = common.render_template
        def render(template, **values):
            context.update(values)
            return original(template, **values)
        with patch.object(common, 'render_template', side_effect=render):
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return context, response.get_data(as_text=True)

    def test_list_and_mobile_detail_show_exact_scheduled_label_without_rewriting_date(self):
        self.seed('2028-2-29')  # Existing legacy precision is read, never normalized in storage.
        with patch.object(common, 'datetime', clock_at('2028-02-28T14:59:59+00:00')):
            context, html = self.capture('/master/drivers')
        label = '開始予定（2028/02/29）'
        self.assertEqual(context['drivers'][0]['safe_days_display'], label)
        self.assertEqual(html.count(label), 2, 'PC table and mobile detail must agree')
        self.m.db.session.refresh(self.driver)
        self.assertEqual(self.driver.safe_start_date, '2028-2-29')

    def test_personal_card_uses_scheduled_label_for_admin_and_regular_user(self):
        self.seed()
        for role in ('admin', 'user'):
            with self.subTest(role=role):
                self.user.role = role
                self.m.db.session.commit()
                with self.client.session_transaction() as session:
                    session['role'] = role
                with patch.object(common, 'datetime', clock_at('2026-12-31T14:59:59+00:00')):
                    context, html = self.capture('/')
                self.assertEqual(context.get('my_safe_start_label'), '開始予定（2027/01/01）')
                self.assertIsNone(context['my_safe_days'])
                self.assertIn('開始予定（2027/01/01）', html)
                self.assertNotIn('開始予定（2027/01/01）</div>\n                <div class="summary-unit">日', html)

    def test_tokyo_year_month_and_leap_boundaries_use_one_day_on_every_view(self):
        self.seed()
        cases = [
            ('2026-12-31T14:59:59+00:00', '2027-01-01', None),
            ('2026-12-31T15:00:00+00:00', '2027-01-01', 0),
            ('2027-01-01T15:00:00+00:00', '2027-01-01', 1),
            ('2027-04-30T14:59:59+00:00', '2027-05-01', None),
            ('2027-04-30T15:00:00+00:00', '2027-05-01', 0),
            ('2028-02-28T15:00:00+00:00', '2028-03-01', None),
            ('2028-02-29T15:00:00+00:00', '2028-03-01', 0),
        ]
        self.user.timezone = 'Pacific/Honolulu'
        for instant, start, days in cases:
            with self.subTest(instant=instant):
                self.driver.safe_start_date = start
                self.m.db.session.commit()
                with patch.object(common, 'datetime', clock_at(instant)):
                    listing, _ = self.capture('/master/drivers')
                    dashboard, _ = self.capture('/')
                if days is None:
                    label = '開始予定（' + start.replace('-', '/') + '）'
                    self.assertEqual(listing['drivers'][0]['safe_days_display'], label)
                    self.assertEqual(dashboard.get('my_safe_start_label'), label)
                    self.assertIsNone(dashboard['my_safe_days'])
                    self.assertEqual(dashboard['ranking'], [])
                else:
                    self.assertEqual(listing['drivers'][0]['safe_days_display'], f'{days}日継続中')
                    self.assertEqual(dashboard['my_safe_days'], days)
                    self.assertFalse(dashboard.get('my_safe_start_label'))
                    self.assertEqual(dashboard['ranking'][0]['safe_days'], days)

    def test_ranking_omits_future_people_when_fewer_than_ten_have_started(self):
        self.seed('2027-01-01')
        for index in range(8):
            self.m.db.session.add(self.m.Driver(company_code='TEST', employee_id=f'past-{index}',
                name=f'開始済み{index}', office='Tokyo', safe_start_date=f'2026-12-{index+1:02d}'))
        for index in range(4):
            self.m.db.session.add(self.m.Driver(company_code='TEST', employee_id=f'future-{index}',
                name=f'未来対象{index}', office='Tokyo', safe_start_date='2027-02-01'))
        self.m.db.session.commit()
        with patch.object(common, 'datetime', clock_at('2026-12-31T14:59:59+00:00')):
            context, html = self.capture('/')
        self.assertEqual(len(context['ranking']), 8)
        self.assertTrue(all(row['employee_id'].startswith('past-') for row in context['ranking']))
        self.assertNotIn('未来対象', html)

    def test_past_year_display_and_unknown_dates_remain_unchanged(self):
        self.seed('2026-01-01')
        with patch.object(common, 'datetime', clock_at('2026-12-31T15:00:00+00:00')):
            listing, _ = self.capture('/master/drivers')
            dashboard, _ = self.capture('/')
        self.assertEqual(listing['drivers'][0]['safe_days_display'], '1年0日継続中')
        self.assertEqual(dashboard['my_safe_days'], 365)
        for value in (None, '', '2027-01', '2027-02-30'):
            self.driver.safe_start_date = value
            self.m.db.session.commit()
            with patch.object(common, 'datetime', clock_at('2026-12-31T15:00:00+00:00')):
                listing, _ = self.capture('/master/drivers')
                dashboard, _ = self.capture('/')
            self.assertEqual(listing['drivers'][0]['safe_days_display'], '0日継続中')
            self.assertIsNone(dashboard['my_safe_days'])
            self.assertFalse(dashboard.get('my_safe_start_label'))
            self.assertEqual(dashboard['ranking'], [])
            self.m.db.session.refresh(self.driver)
            self.assertEqual(self.driver.safe_start_date, value)


if __name__ == '__main__':
    unittest.main()
