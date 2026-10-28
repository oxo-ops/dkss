"""Reminder ownership never comes from a past username or personal name."""
import json
import unittest
from unittest.mock import patch

import test_workflow_regressions as fixture
import test_q08_account_identity as identity_tests
from dkss_app import checklist_notifications as notifications


class ReminderGenerationTests(unittest.TestCase):
    setUpClass = classmethod(fixture.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.WorkflowRegressionTests.tearDownClass.__func__)
    tearDown = fixture.WorkflowRegressionTests.tearDown
    user = identity_tests.AccountIdentityTests.user

    def setUp(self):
        fixture.WorkflowRegressionTests.setUp(self)
        self.checklist = self.m.Checklist(company_code='TEST', name='架空通知点検', target='車両管理',
            frequency_unit='day', frequency_value='1', reminder_enabled=True, reminder_time='00:00')
        self.m.db.session.add(self.checklist)
        self.m.db.session.commit()
        self.checklist_id, self.vehicle_id = self.checklist.id, self.vehicle.id
        self.person = self.user(username='reused', name='架空旧利用者')

    def past(self, **fields):
        values = dict(company_code='TEST', checklist_id=self.checklist.id, vehicle_record_id=self.vehicle.id,
            year='2020', month='01', day='01', status='点検完了', checked_by='架空旧利用者',
            checked_by_username='reused')
        values.update(fields)
        result = self.m.VehicleChecklistResult(**values)
        self.m.db.session.add(result)
        self.m.db.session.commit()
        # Q03 may be present in the combined-tree compatibility run. This row is
        # deliberately legacy data, not a new confirmed Q03 assignment.
        old = {name: None for name in ('checked_by_identity', 'approved_by_identity')
               if hasattr(type(result), name)}
        if 'approvals_json' in fields:
            # Seed persisted historical JSON after Q03's new-record listener;
            # that listener correctly replaces identities on new submissions.
            old['approvals_json'] = fields['approvals_json']
        if old:
            self.m.db.session.execute(type(result).__table__.update().where(type(result).id == result.id).values(**old))
            self.m.db.session.commit()
            self.m.db.session.refresh(result)
        return result

    def recipients(self):
        return notifications.get_vehicle_checklist_notify_users('TEST', self.checklist_id, self.vehicle_id)

    def save_setting(self, names=None):
        return self.client.post(f'/vehicle/checklists/{self.checklist.id}/reminder-notify-users',
            data={'vehicle_record_id':self.vehicle.id, 'reminder_notify_users':names if names is not None else ['reused']})

    def replace(self):
        old_uuid = self.person.account_identity
        self.m.db.session.delete(self.person)
        self.m.db.session.commit()
        self.person = self.user(username='reused', name='架空旧利用者')
        self.assertNotEqual(self.person.account_identity, old_uuid)
        return old_uuid

    def test_legacy_username_does_not_send_to_recreated_person(self):
        self.past()
        self.replace()
        self.assertEqual(self.recipients(), [])
        with patch.object(notifications._dkss_notifications_delivery, 'add_notification') as send:
            notifications.send_vehicle_checklist_reminders('TEST')
        send.assert_not_called()

    def test_legacy_name_and_approval_do_not_select_current_same_name(self):
        self.past(checked_by_username=None, approvals_json=json.dumps([{'approved_by':'架空旧利用者'}]))
        self.replace()
        self.assertEqual(self.recipients(), [])

    def test_explicit_save_sends_with_the_selected_generation(self):
        self.assertEqual(self.save_setting().status_code, 200)
        self.assertEqual(self.recipients(), ['reused'])
        with patch.object(notifications._dkss_notifications_delivery, 'add_notification') as send:
            notifications.send_vehicle_checklist_reminders('TEST')
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs['target_identity'], self.person.account_identity)

    def test_explicit_setting_does_not_follow_reused_username(self):
        self.assertEqual(self.save_setting().status_code, 200)
        self.replace()
        self.assertEqual(self.recipients(), [])

    def test_reused_setting_id_cannot_transfer_evidence_to_another_vehicle(self):
        self.assertEqual(self.save_setting().status_code, 200)
        setting = self.m.VehicleChecklistNotifySetting.query.one()
        setting_id = setting.id
        self.m.db.session.delete(setting)
        other = self.m.Vehicle(company_code='TEST', chassis_number='SYNTHETIC-SECOND')
        self.m.db.session.add(other)
        self.m.db.session.commit()
        self.m.db.session.add(self.m.VehicleChecklistNotifySetting(id=setting_id, company_code='TEST',
            checklist_id=self.checklist_id, vehicle_record_id=other.id, notify_users_json='["reused"]'))
        self.m.db.session.commit()
        self.assertEqual(notifications.get_vehicle_checklist_notify_users('TEST', self.checklist_id, other.id), [])

    def test_explicit_same_value_reconfirmation_records_new_generation(self):
        from dkss_app.checklist_notify_identity import VehicleChecklistNotifyAccount
        self.assertEqual(self.save_setting().status_code, 200)
        old_uuid = self.replace()
        self.assertEqual(self.save_setting().status_code, 200)
        rows = VehicleChecklistNotifyAccount.query.order_by(VehicleChecklistNotifyAccount.id).all()
        self.assertEqual([json.loads(r.identities_json)['reused'] for r in rows],
                         [old_uuid, self.person.account_identity])
        self.assertTrue(all(r.actor_identity and r.actor_name for r in rows))
        self.assertEqual(self.recipients(), ['reused'])

    def test_old_plain_setting_requires_explicit_reconfirmation(self):
        self.m.db.session.add(self.m.VehicleChecklistNotifySetting(company_code='TEST', checklist_id=self.checklist.id,
            vehicle_record_id=self.vehicle.id, notify_users_json='["reused"]'))
        self.m.db.session.commit()
        self.assertEqual(self.recipients(), [])
        self.assertEqual(self.save_setting().status_code, 200)
        self.assertEqual(self.recipients(), ['reused'])

    def test_q03_uuid_evidence_is_company_scoped_and_not_rebound(self):
        self.past(checked_by_username=None, checked_by=None, approvals_json=json.dumps([
            {'approved_by_identity':self.person.account_identity},
            {'approved_by_identity':self.user(company='OTHER', username='outsider').account_identity}]))
        self.assertEqual(self.recipients(), ['reused'])
        self.replace()
        self.assertEqual(self.recipients(), [])

    def test_missing_table_is_read_only_and_initializer_does_not_backfill(self):
        from dkss_app.checklist_notify_identity import VehicleChecklistNotifyAccount, initialize_notify_identities
        self.assertEqual(self.save_setting().status_code, 200)
        self.m.db.session.remove()
        with self.m.db.engine.begin() as connection:
            VehicleChecklistNotifyAccount.__table__.drop(connection)
        self.assertEqual(self.recipients(), [])
        for _ in range(2):
            initialize_notify_identities()
        self.assertEqual(VehicleChecklistNotifyAccount.query.count(), 0)
        self.assertEqual(self.recipients(), [])

    def test_recreation_between_resolution_and_send_keeps_original_uuid(self):
        from datetime import datetime
        self.assertEqual(self.save_setting().status_code, 200)
        old_uuid = self.person.account_identity
        def during_send(*args):
            self.replace()
            return datetime(2026, 10, 28, 12)
        with patch.object(notifications._dkss_checklist_common, 'get_user_local_now', side_effect=during_send):
            notifications.send_vehicle_checklist_reminders('TEST')
        self.assertEqual(self.m.Notification.query.filter_by(owner_identity=self.person.account_identity).count(), 0)
        self.assertNotEqual(old_uuid, self.person.account_identity)


if __name__ == '__main__':
    unittest.main()
