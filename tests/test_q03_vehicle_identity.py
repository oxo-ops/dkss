"""Fixed inspection actor IDs must not follow a reused login name."""
import unittest
import test_q02_vehicle_workflow_boundaries as workflow


class Q03VehicleIdentityTests(unittest.TestCase):
    setUpClass = classmethod(workflow.Q02VehicleWorkflowBoundaryTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.Q02VehicleWorkflowBoundaryTests.tearDownClass.__func__)
    setUp = workflow.Q02VehicleWorkflowBoundaryTests.setUp
    tearDown = workflow.Q02VehicleWorkflowBoundaryTests.tearDown
    login = workflow.Q02VehicleWorkflowBoundaryTests.login
    request = workflow.Q02VehicleWorkflowBoundaryTests.request
    record = workflow.Q02VehicleWorkflowBoundaryTests.record
    url = workflow.Q02VehicleWorkflowBoundaryTests.url
    judge = workflow.Q02VehicleWorkflowBoundaryTests.judge
    judge_data = workflow.Q02VehicleWorkflowBoundaryTests.judge_data
    snapshot = workflow.Q02VehicleWorkflowBoundaryTests.snapshot

    def reuse(self, username):
        a = self.models.User.query.filter_by(company_code='A', username=username).one()
        original_id = a.id
        a.username = 'retained-' + username
        b = self.models.User(company_code='A', username=username, role=a.role,
            password='unused', last_name='Replacement', password_changed_at='new')
        self.db.session.add(b)
        self.db.session.commit()
        self.assertNotEqual(b.id, original_id)
        return original_id

    def test_reused_checker_cannot_assign_operation_manager_via_post(self):
        row = self.record(fixed=True)
        old_id = self.reuse('checker')
        self.assertEqual(row.checked_by_user_id, old_id)
        self.login('checker')
        before = self.snapshot()
        response = self.request('POST', self.url(row, '/operation-judgment'),
            data=self.judge_data(row, action='assign_operation_manager', manager_username='admin'),
            headers={'X-DKSS-Final-Submit': '1', 'Accept': 'application/json'})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.is_json)
        self.assertTrue(response.json['errors'])
        self.assertEqual(self.snapshot(), before)
        self.login('retained-checker')
        self.assertEqual(self.judge(row, action='assign_operation_manager', manager_username='admin').status_code, 302)

    def test_reused_selected_admin_cannot_inherit_manager_judgment(self):
        row = self.record(fixed=True, requested=['admin'])
        self.reuse('admin')
        self.login('admin')
        before = self.snapshot()
        self.assertEqual(self.judge(row).status_code, 403)
        self.assertEqual(self.snapshot(), before)
        self.login('retained-admin')
        self.assertEqual(self.judge(row).status_code, 302)


if __name__ == '__main__':
    unittest.main(verbosity=2)
