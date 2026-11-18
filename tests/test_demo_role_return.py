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
                hidden = target
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

    def test_purpose_entry_selects_driver_and_opens_existing_checklist(self):
        token, page = self.enter()
        self.assertIn('>点検する</button>', page)
        self.assertIn('>結果・管理を見る</button>', page)
        self.assertNotIn('>運転者</button>', page)
        self.assertNotIn('入力・変更は他の利用者にも見えます', page)
        target = (f'/vehicle/checklists/{self.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}'
                  f'?vehicle_record_id={self.vehicle_id}')
        before = self.models.VehicleChecklistResult.query.count()
        for role, destination in [('driver', target), ('manager', '/')]:
            response = self.client.post('/demo/role', data={
                'role':role, 'csrf_token':token, 'demo_entry':'purpose'})
            self.assertEqual(response.location, destination)
            following = self.client.get(destination)
            self.assertEqual(following.status_code, 200)
            self.assertNotIn('class="alert public-demo-notice"', following.text)
            self.assertIn('id="firstUseGuide"', following.text)
            with self.client.session_transaction() as session:
                self.assertTrue(session['demo_role_selected'])
                self.assertEqual(session['demo_role'], role)
            self.assertEqual(before, self.models.VehicleChecklistResult.query.count())
        # Existing re-entry offers the choice again without new business records.
        self.enter()
        with self.client.session_transaction() as session:
            self.assertNotIn('demo_role_selected', session)

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
