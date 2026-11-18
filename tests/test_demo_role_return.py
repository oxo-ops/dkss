import html
import re
import unittest
from test_demo_inspection_compact import CompactDemoTests

class RoleReturnTests(CompactDemoTests):
    def test_opened_checklist_survives_either_role(self):
        for role in ('driver', 'manager'):
            with self.subTest(role=role):
                token, _ = self.enter()
                target = (f'/vehicle/checklists/{self.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}'
                          f'?vehicle_record_id={self.vehicle_id}&year=2026&month=10&active_day=23')
                page = self.client.get(target + '&__aonagi_entry=1')
                self.assertEqual(page.status_code, 200)
                hidden = html.unescape(re.search(r'name="checklist_return" value="([^"]+)"', page.text)[1])
                before = self.models.VehicleChecklistResult.query.count()
                reply = self.client.post('/demo/role', data={
                    'role': role, 'csrf_token': token, 'checklist_return': hidden})
                self.assertEqual(reply.location, target)
                following = self.client.get(reply.location)
                self.assertEqual(following.status_code, 200)
                self.assertNotIn('class="alert public-demo-notice"', following.text)
                self.assertEqual(before, self.models.VehicleChecklistResult.query.count())
                with self.client.session_transaction() as session:
                    self.assertEqual(session['demo_role'], role)

    def test_home_entry_has_no_return_target(self):
        token, page = self.enter()
        self.assertNotIn('name="checklist_return"', page)
        self.assertEqual(self.client.post('/demo/role', data={
            'role':'driver', 'csrf_token':token}).location, '/')

    def test_untrusted_destinations_cannot_redirect(self):
        token, _ = self.enter()
        for target in ('https://evil.example/vehicle/checklists/1', '//evil.example/x',
                       '/logout', '/demo', '/vehicle/checklists/1/delete',
                       'https://[bad', '/vehicle/checklists/1#x', '\n/vehicle/checklists/1'):
            with self.subTest(target=target):
                self.assertEqual(self.client.post('/demo/role', data={
                    'role':'driver', 'csrf_token':token, 'checklist_return':target}).location, '/')

    def test_extra_parameters_are_not_forwarded(self):
        token, _ = self.enter()
        response = self.client.post('/demo/role', data={'role':'driver', 'csrf_token':token,
            'checklist_return':'/vehicle/checklists/1?vehicle_record_id=1&__aonagi_entry=1&next=https://evil.example&year=bad'})
        self.assertEqual(response.location, '/vehicle/checklists/1?vehicle_record_id=1')

    def test_repeated_selection_preserves_same_target(self):
        token, _ = self.enter()
        target=f'/vehicle/checklists/{self.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}?vehicle_record_id={self.vehicle_id}'
        for _ in range(2):
            self.assertEqual(self.client.post('/demo/role', data={
                'role':'driver', 'csrf_token':token, 'checklist_return':target}).location, target)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(RoleReturnTests(name) for name in RoleReturnTests.__dict__ if name.startswith('test_'))
