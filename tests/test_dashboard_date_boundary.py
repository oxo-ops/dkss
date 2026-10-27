"""Q05: dashboard business dates must not depend on the server timezone."""
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import test_workflow_regressions as workflow
from dkss_app import dashboard as module


class DashboardDateBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def test_tokyo_day_controls_expiry_safe_days_and_query_period(self):
        self.vehicle.office = 'Tokyo'
        self.m.User.query.filter_by(company_code='TEST', username='admin').one().office = 'Tokyo'
        driver = self.m.Driver(company_code='TEST', employee_id='admin', name='架空',
                               office='Tokyo', safe_start_date='2026-01-01')
        self.m.db.session.add(driver)
        cutoff = self.m.Vehicle(company_code='TEST', chassis_number='Q05-CUTOFF', office='Tokyo')
        beyond = self.m.Vehicle(company_code='TEST', chassis_number='Q05-BEYOND', office='Tokyo')
        self.m.db.session.add_all([cutoff, beyond])
        for instant, expected in (
            ('2026-10-26T14:59:59+00:00', '2026-10-26'),
            ('2026-10-26T15:00:00+00:00', '2026-10-27'),
            ('2026-12-31T15:00:00+00:00', '2027-01-01'),
            ('2028-02-28T15:00:00+00:00', '2028-02-29'),
            ('2028-02-29T15:00:00+00:00', '2028-03-01'),
        ):
            with self.subTest(instant=instant):
                current = datetime.fromisoformat(instant)
                local_day = date.fromisoformat(expected)
                self.vehicle.inspection_expiry = expected
                cutoff.inspection_expiry = (local_day + timedelta(days=90)).isoformat()
                beyond.inspection_expiry = (local_day + timedelta(days=91)).isoformat()
                driver.safe_start_date = (local_day - timedelta(days=1)).isoformat()
                self.m.db.session.commit()

                class UTCServerClock(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return (current.astimezone(tz) if tz else
                                current.astimezone(timezone.utc).replace(tzinfo=None))

                with self.m.app.test_request_context('/'):
                    self.m.session.update(company_code='TEST', username='admin',
                                          role='admin', name='架空')
                    with patch.object(module._dkss_common, 'datetime', UTCServerClock), \
                         patch.object(module._dkss_common, 'render_template',
                                      side_effect=lambda template, **kw: kw):
                        context = module.dashboard()
                self.assertEqual(context['dashboard_period_end'], expected)
                self.assertEqual(context['dashboard_period_start'],
                                 (local_day - timedelta(days=29)).isoformat())
                self.assertEqual(context['my_safe_days'], 1)
                alerts = context['inspection_alerts']
                self.assertEqual({row['vehicle_record_id']: row['remaining_days'] for row in alerts},
                                 {self.vehicle.id: 0, cutoff.id: 90})
