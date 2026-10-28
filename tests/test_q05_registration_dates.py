"""Registration-based safe start dates use the Tokyo business day."""
import unittest
from unittest.mock import patch

import test_workflow_regressions as fixtures
from test_q05_inspection_dates import clock_at
from dkss_app import auth


class RegistrationDateTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = fixtures.WorkflowRegressionTests.setUp
    tearDown = fixtures.WorkflowRegressionTests.tearDown

    def register(self, ident):
        return self.client.post('/register?company_code=TEST', data=dict(
            last_name='架空', first_name='登録', employee_id=ident,
            password='Q05-Register-Only-742!', office=''))

    def test_new_registration_uses_tokyo_day_at_year_end_and_leap_boundaries(self):
        for index, (instant, day) in enumerate((
            ('2026-12-31T14:59:59+00:00', '2026-12-31'),
            ('2026-12-31T15:00:00+00:00', '2027-01-01'),
            ('2028-02-28T15:00:00+00:00', '2028-02-29'),
            ('2028-02-29T15:00:00+00:00', '2028-03-01'),
        )):
            ident = 'register-' + str(index)
            with self.subTest(instant=instant), patch.object(
                auth._dkss_common, 'datetime', clock_at(instant)
            ):
                self.assertEqual(self.register(ident).status_code, 302)
                self.assertEqual(self.m.Driver.query.filter_by(employee_id=ident).one().safe_start_date, day)

    def test_existing_driver_date_and_unknown_precision_are_never_replaced_on_registration(self):
        for index, day in enumerate((None, '', '2028-02', '2028-02-30', '2026-01-01')):
            ident = 'existing-' + str(index)
            driver = self.m.Driver(company_code='TEST', employee_id=ident,
                                   name='既存架空', safe_start_date=day)
            self.m.db.session.add(driver)
            self.m.db.session.commit()
            with patch.object(auth._dkss_common, 'datetime', clock_at('2026-12-31T15:00:00+00:00')):
                self.assertEqual(self.register(ident).status_code, 302)
            self.m.db.session.refresh(driver)
            self.assertEqual(driver.safe_start_date, day)


if __name__ == '__main__':
    unittest.main()
