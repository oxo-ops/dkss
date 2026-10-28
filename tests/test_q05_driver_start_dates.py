"""Driver start dates must retain the date-input format used by SQL ranking."""
import unittest
from types import SimpleNamespace

import test_workflow_regressions as fixtures
from dkss_app.dashboard_repository import DashboardRepository


class DriverStartDateTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = fixtures.WorkflowRegressionTests.setUp
    tearDown = fixtures.WorkflowRegressionTests.tearDown

    def form(self, ident, day):
        return dict(employee_id=ident, last_name='架空', first_name='乗務者',
                    role='user', office='', safe_start_date=day,
                    password='Q05-Synthetic-Only-742!')

    def test_new_rejects_noncanonical_dates_without_creating_driver_or_account(self):
        for index, day in enumerate(('2026-2-03', '2026-02-3', '2026-2-3')):
            with self.subTest(day=day):
                before = (self.m.Driver.query.count(), self.m.User.query.count())
                response = self.client.post('/master/drivers/new',
                    data=self.form('invalid-' + str(index), day))
                self.assertEqual(response.status_code, 400)
                self.assertEqual((self.m.Driver.query.count(), self.m.User.query.count()), before)

    def test_edit_rejects_noncanonical_dates_and_preserves_driver_and_account(self):
        response = self.client.post('/master/drivers/new', data=self.form('edited', '2026-02-03'))
        self.assertEqual(response.status_code, 302)
        driver = self.m.Driver.query.filter_by(employee_id='edited').one()
        original = (driver.safe_start_date, driver.name)
        for day in ('2026-2-03', '2026-02-3', '2026-2-3'):
            with self.subTest(day=day):
                form = self.form('edited', day)
                form.pop('password')
                form['last_name'] = '更新させない'
                response = self.client.post(f'/master/drivers/{driver.id}/edit', data=form)
                self.assertEqual(response.status_code, 400)
                self.m.db.session.expire_all()
                self.assertEqual((driver.safe_start_date, driver.name), original)
                self.assertEqual(self.m.User.query.filter_by(username='edited').one().last_name, '架空')

    def test_blank_and_canonical_leap_day_remain_accepted_on_new_and_edit(self):
        for index, day in enumerate(('', '2000-02-29', '2028-02-29', '0001-01-01')):
            with self.subTest(day=day):
                ident = 'valid-' + str(index)
                response = self.client.post('/master/drivers/new', data=self.form(ident, day))
                self.assertEqual(response.status_code, 302)
                driver = self.m.Driver.query.filter_by(employee_id=ident).one()
                self.assertEqual(driver.safe_start_date, day)
                form = self.form(ident, day)
                form.pop('password')
                response = self.client.post(f'/master/drivers/{driver.id}/edit', data=form)
                self.assertEqual(response.status_code, 302)
                self.m.db.session.refresh(driver)
                self.assertEqual(driver.safe_start_date, day)

    def test_month_only_invalid_calendar_and_timestamp_are_rejected(self):
        for index, day in enumerate(('2028-02', '1900-02-29', '2028-02-30',
                                     '2028-02-29T00:00:00')):
            with self.subTest(day=day):
                response = self.client.post('/master/drivers/new',
                    data=self.form('calendar-' + str(index), day))
                self.assertEqual(response.status_code, 400)
                self.assertIsNone(self.m.Driver.query.filter_by(employee_id='calendar-' + str(index)).first())

    def test_accepted_dates_have_chronological_sql_ranking(self):
        for ident, day in (('october', '2026-10-01'), ('february', '2026-02-03')):
            self.assertEqual(self.client.post('/master/drivers/new',
                data=self.form(ident, day)).status_code, 302)
        repository = DashboardRepository(SimpleNamespace(company_code='TEST', office='', office_missing=False))
        self.assertEqual([row.employee_id for row in repository.ranking_drivers()],
                         ['february', 'october'])


if __name__ == '__main__':
    unittest.main()
