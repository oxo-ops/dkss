"""Fixed inspection actor IDs must not follow a reused login name."""
import unittest
import json
import os
from unittest.mock import patch
import test_q02_vehicle_workflow_boundaries as workflow
import test_q03_postgres_person_identity as postgres


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

    def _retired_checker(self):
        row = self.record(fixed=True)
        a = self.models.User.query.filter_by(company_code='A', username='checker').one()
        old_id, old_uuid = a.id, a.account_identity
        self.db.session.delete(a)
        self.db.session.commit()
        b = self.models.User(id=old_id, company_code='A', username='checker', role='user',
            password='unused', last_name='Replacement B', password_changed_at='same-stamp')
        self.db.session.add(b)
        self.db.session.commit()
        self.assertEqual(b.id, old_id)
        self.assertNotEqual(b.account_identity, old_uuid)
        self.assertEqual(row.checked_by_identity, old_uuid)
        return row, b

    def test_independent_reminder_probe_excludes_recreated_checker(self):
        from dkss_app import checklist_notifications as notices
        row, b = self._retired_checker()
        checklist = self.db.session.get(self.models.Checklist, row.checklist_id)
        checklist.reminder_enabled, checklist.reminder_time = True, '00:00'
        self.db.session.commit()
        self.assertEqual(notices.get_vehicle_checklist_notify_users('A', row.checklist_id, row.vehicle_record_id), [])
        with patch.object(notices._dkss_notifications_delivery, 'add_notification') as sender:
            notices.send_vehicle_checklist_reminders('A')
            sender.assert_not_called()
        self.assertEqual(self.models.Notification.query.filter_by(owner_identity=b.account_identity).count(), 0)

    def _default_notification_probe(self, legacy_setting=False):
        row, b = self._retired_checker()
        checklist = self.db.session.get(self.models.Checklist, row.checklist_id)
        checklist.items_json = json.dumps([{'item_type':'check', 'content':'synthetic check',
            'input_type':'text', 'answer_required':False}])
        if legacy_setting:
            # An old username-only setting is not a new explicit attestation.
            self.db.session.add(self.models.VehicleChecklistNotifySetting(company_code='A',
                checklist_id=checklist.id, vehicle_record_id=row.vehicle_record_id,
                notify_users_json=json.dumps(['checker'])))
        self.db.session.commit()
        for suffix, day in (('new', '24'), ('complete', '25')):
            response = self.request('POST', f'/vehicle/checklists/{checklist.id}/{suffix}', data={
                'vehicle_record_id':row.vehicle_record_id, 'year':'2026', 'month':'10', 'day':day,
                'answer_0':'synthetic answer'})
            self.assertEqual(response.status_code, 302)
            created = self.models.VehicleChecklistResult.query.filter_by(checklist_id=checklist.id, day=day).one()
            self.assertNotIn('checker', json.loads(created.notify_users_json or '[]'))
            self.assertNotIn(b.account_identity, (created.notification_identities_json or '{}'))
            self.assertEqual(self.models.Notification.query.filter_by(owner_identity=b.account_identity).count(), 0)
        self.db.session.refresh(row)
        self.assertNotEqual(row.checked_by_identity, b.account_identity)
        # A deliberate administrator re-selection is a new assignment to B,
        # not evidence that B owns A's past records.
        response = self.request('POST', f'/vehicle/checklists/{checklist.id}/reminder-notify-users', data={
            'vehicle_record_id':row.vehicle_record_id, 'reminder_notify_users':['checker']})
        self.assertEqual(response.status_code, 200)
        response = self.request('POST', f'/vehicle/checklists/{checklist.id}/new', data={
            'vehicle_record_id':row.vehicle_record_id, 'year':'2026', 'month':'10', 'day':'26',
            'answer_0':'new explicit assignment'})
        self.assertEqual(response.status_code, 302)
        created = self.models.VehicleChecklistResult.query.filter_by(checklist_id=checklist.id, day='26').one()
        self.assertEqual(json.loads(created.notify_users_json), ['checker'])
        self.assertEqual(json.loads(created.notification_identities_json), {'checker': b.account_identity})
        self.assertGreater(self.models.Notification.query.filter_by(owner_identity=b.account_identity).count(), 0)
        self.assertNotEqual(row.checked_by_identity, b.account_identity)

    def test_independent_new_inspection_default_probe_uses_retained_uuid(self):
        self._default_notification_probe()

    def test_independent_new_inspection_default_probe_holds_legacy_setting(self):
        self._default_notification_probe(legacy_setting=True)


@unittest.skipUnless(os.environ.get('Q03_POSTGRES_TEST_URL'), 'explicit local PostgreSQL URL required')
class Q03PostgresVehicleIdentityTests(Q03VehicleIdentityTests):
    setUpClass = classmethod(postgres.Q03PostgresPersonIdentityTests.setUpClass.__func__)
    tearDownClass = classmethod(postgres.Q03PostgresPersonIdentityTests.tearDownClass.__func__)


if __name__ == '__main__':
    unittest.main(verbosity=2)
