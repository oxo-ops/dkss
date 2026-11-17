"""Shared demo keeps ordinary reminder role boundaries after phone UI changes."""
import html
import re
import unittest
from test_public_demo_workflow import DemoWorkflowTests as Fixture

class DemoReminderReadonlyTests(Fixture):
    def test_shared_demo_role_switch_preserves_reminder_readonly_boundary(self):
        self.app.config['PUBLIC_DEMO_SHARED_COMPANY'] = True
        self.addCleanup(self.app.config.pop, 'PUBLIC_DEMO_SHARED_COMPANY', None)
        self.client = self.app.test_client()
        self.assertEqual(self.request('GET', '/demo').status_code, 302)
        index = self.app.config['PUBLIC_DEMO_CHECKLIST_ID']
        path = f'/vehicle/checklists/{index}'
        params = {'vehicle_record_id': 1, 'year': 2026, 'month': 10, 'day': 24, 'active_day': 24}
        driver = self.request('GET', path, query_string=params)
        self.assertEqual(driver.status_code, 200)
        body = driver.get_data(as_text=True)
        self.assertIn('data-reminder-readonly', body)
        self.assertNotIn('id="reminder_notify_user_search"', body)
        self.assertIn('20261117-role-entry-flow-1', body)
        self.assertIn('20261117-row-criteria-1', body)
        endpoint = f'/vehicle/checklists/{index}/reminder-notify-users'
        self.assertEqual(self.request('POST', endpoint, data={'vehicle_record_id': 1}).status_code, 403)
        token = html.unescape(re.search(r'name="csrf_token" value="([^"]+)"', body)[1])
        self.assertEqual(self.request('POST', '/demo/role', data={'role':'manager','csrf_token':token}).status_code,302)
        manager = self.request('GET', path, query_string=params)
        self.assertEqual(manager.status_code, 200)
        self.assertIn('id="reminder_notify_user_search"', manager.get_data(as_text=True))
        self.assertNotIn('data-reminder-readonly', manager.get_data(as_text=True))

for name in dir(Fixture):
    if name.startswith('test_') and name not in DemoReminderReadonlyTests.__dict__:
        setattr(DemoReminderReadonlyTests, name, None)
del Fixture
