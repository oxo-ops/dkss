"""Clock-controlled in-app reminder integration tests; isolated SQLite only."""
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from test_inspection_plans import InspectionPlanTests as _Base
from vehicle_inspection_alerts import reminder_phase


class InspectionAlertTests(unittest.TestCase):
    setUpClass = classmethod(_Base.setUpClass.__func__)
    tearDownClass = classmethod(_Base.tearDownClass.__func__)
    tearDown = _Base.tearDown
    save = _Base.save
    change = _Base.change
    upload_inspection = _Base.upload_inspection
    inspection_form = _Base.inspection_form
    import_record = _Base.import_record
    complete = _Base.complete

    def setUp(self):
        _base_setup(self)
        self.vehicle.office='犬塚'
        self.m.User.query.filter_by(username='admin').one().office='犬塚'
        self.m.db.session.commit()

    def run_alerts(self, day='2026-10-22', force=True):
        return self.m.inspection_alerts.run('TEST',today=date.fromisoformat(day),force=force)['TEST']

    def users(self):
        m=self.m
        m.db.session.add_all([
            m.User(company_code='TEST',username='same',last_name='同営業所',password='unused',role='admin',office='犬塚'),
            m.User(company_code='TEST',username='other',last_name='別営業所',password='unused',role='admin',office='安城'),
            m.User(company_code='TEST',username='ordinary',last_name='一般',password='unused',role='user',office='犬塚'),
            m.User(company_code='FOREIGN',username='foreign',last_name='他社',password='unused',role='admin',office='犬塚'),
        ]);m.db.session.commit()

    def state(self, notification, day='2026-10-22'):
        return self.m.inspection_alerts.workflow(notification,date.fromisoformat(day))

    def test_month_and_booking_thresholds(self):
        p=SimpleNamespace(status='planned',planned_month='2026-12',reservation_date=None)
        expected=[('2026-10-31',None),('2026-11-01','prior_booking'),('2026-12-01','month_booking'),('2027-01-01','month_elapsed')]
        for day,phase in expected:
            result=reminder_phase(p,date.fromisoformat(day))
            self.assertEqual(result[0] if result else None,phase)
        p.reservation_date='2026-12-10'
        for day,phase in [('2026-12-02',None),('2026-12-03','booking_7days'),('2026-12-09','booking_1day'),('2026-12-10','booking_1day'),('2026-12-11','execution_check')]:
            result=reminder_phase(p,date.fromisoformat(day));self.assertEqual(result[0] if result else None,phase)

    def test_only_same_office_admins_receive_in_app_notifications(self):
        self.users();self.save([self.change(mon='2026-11')])
        with patch.object(self.m,'dispatch_external_notification') as external:
            result=self.run_alerts();external.assert_not_called()
        self.assertEqual(result['notifications'],2)
        self.assertEqual({n.target_username for n in self.m.Notification.query.all()},{'admin','same'})
        self.assertTrue(all(n.company_code=='TEST' for n in self.m.Notification.query.all()))

    def test_retry_and_repeated_poll_are_idempotent(self):
        self.save([self.change(mon='2026-11')]);self.assertEqual(self.run_alerts()['notifications'],1)
        self.assertEqual(self.run_alerts()['notifications'],0)
        self.assertEqual(self.m.Notification.query.count(),1)
        self.assertTrue(self.run_alerts(force=False)['skipped'])

    def test_multiple_vehicles_are_grouped_in_one_notification(self):
        m=self.m;v=m.Vehicle(company_code='TEST',chassis_number='SECOND',office='犬塚');m.db.session.add(v);m.db.session.commit()
        self.save([self.change(mon='2026-11'),self.change(vehicle=v,mon='2026-11')])
        result=self.run_alerts();self.assertEqual((result['notifications'],result['plans']),(1,2))
        self.assertIn('2件',m.Notification.query.one().title)
        self.assertEqual(m.inspection_alerts.Delivery.query.count(),2)

    def test_repeat_is_at_least_seven_days_after_actual_delivery(self):
        self.save([self.change(mon='2026-12')])
        self.assertEqual(self.run_alerts('2026-11-07')['notifications'],1)
        self.assertEqual(self.run_alerts('2026-11-08')['notifications'],0)
        self.assertEqual(self.run_alerts('2026-11-13')['notifications'],0)
        self.assertEqual(self.run_alerts('2026-11-14')['notifications'],1)
        old,new=self.m.Notification.query.order_by(self.m.Notification.id).all()
        self.assertFalse(self.state(old,'2026-11-14')['requires_action']);self.assertTrue(old.read)
        self.assertTrue(self.state(new,'2026-11-14')['requires_action'])

    def test_phase_change_ends_previous_notice_and_prompts_new_action(self):
        self.save([self.change(mon='2026-11')]);self.run_alerts('2026-10-22');old=self.m.Notification.query.one()
        self.run_alerts('2026-11-01');self.assertFalse(self.state(old,'2026-11-01')['requires_action'])
        self.assertEqual(self.m.Notification.query.count(),2)

    def test_booking_change_ends_old_notification_immediately(self):
        self.save([self.change(mon='2026-10')]);self.run_alerts();old=self.m.Notification.query.one()
        p=self.m.VehicleInspectionPlan.query.one();change=self.change(mon=p.planned_month)
        change.update(id=p.id,version=p.version,reservation_date='2026-10-23');self.save([change])
        self.assertFalse(self.state(old)['requires_action'])
        self.run_alerts(force=False);self.m.db.session.refresh(old);self.assertTrue(old.read)
        self.assertEqual(self.m.Notification.query.count(),2)

    def test_note_change_does_not_resend_reminder(self):
        self.save([self.change(mon='2026-11')]);self.run_alerts()
        p=self.m.VehicleInspectionPlan.query.one();change=self.change(mon=p.planned_month);change.update(id=p.id,version=p.version,note='メモを修正')
        self.save([change]);self.assertEqual(self.run_alerts(force=False)['notifications'],0)
        self.assertEqual(self.m.Notification.query.count(),1)

    def test_execution_stops_overdue_plan_alert_without_clearing_other_alerts(self):
        self.save([self.change(mon='2026-09')]);self.run_alerts();old=self.m.Notification.query.one()
        self.m.db.session.add(self.m.Notification(company_code='TEST',target_user='管理者',target_username='admin',title='別の不具合警告',message='継続',read=False));self.m.db.session.commit()
        plan=self.m.VehicleInspectionPlan.query.one();self.complete(plan=plan)
        self.assertEqual(self.state(old)['workflow_status'],'completed')
        self.assertEqual(self.run_alerts(force=False)['notifications'],0)
        self.m.db.session.refresh(old);self.assertTrue(old.read)
        self.assertFalse(self.m.Notification.query.filter_by(title='別の不具合警告').one().read)

    def test_cancellation_closes_alert_and_no_weekly_repeat(self):
        self.save([self.change(mon='2026-11')]);self.run_alerts();old=self.m.Notification.query.one()
        p=self.m.VehicleInspectionPlan.query.one();change=self.change(mon=p.planned_month);change.update(id=p.id,version=p.version,status='cancelled');self.save([change])
        self.assertFalse(self.state(old)['requires_action'])
        self.assertEqual(self.run_alerts('2026-11-15')['notifications'],0)

    def test_existing_actual_suppresses_plan_created_later(self):
        self.import_record();self.save([self.change(mon='2026-09')])
        self.assertEqual(self.run_alerts()['notifications'],0)

    def test_missing_office_or_missing_recipient_is_reported(self):
        self.vehicle.office='管理者不在';self.m.db.session.commit();self.save([self.change(mon='2026-11')])
        result=self.run_alerts();self.assertEqual(result['no_recipient'],1);self.assertEqual(result['notifications'],0)
        status=self.client.get('/api/vehicle/inspection-plans/alerts/status')
        self.assertEqual(status.status_code,200);self.assertEqual(status.json['report']['no_recipient'],1)

    def test_inactive_company_and_vehicle_are_excluded(self):
        self.save([self.change(mon='2026-11')]);self.vehicle.deleted=True;self.m.db.session.commit()
        self.assertEqual(self.run_alerts()['notifications'],0)
        self.vehicle.deleted=False;self.m.Company.query.filter_by(company_code='TEST').one().active=False;self.m.db.session.commit()
        self.assertEqual(self.run_alerts()['notifications'],0)

    def test_office_transfer_ends_old_notice_and_notifies_new_office(self):
        self.users();self.save([self.change(mon='2026-11')]);self.run_alerts()
        old=self.m.Notification.query.filter_by(target_username='admin').one()
        self.vehicle.office='安城';self.m.db.session.commit()
        self.assertFalse(self.state(old)['requires_action'])
        self.assertEqual(self.run_alerts(force=False)['notifications'],1)
        self.assertEqual(self.m.Notification.query.order_by(self.m.Notification.id.desc()).first().target_username,'other')

    def test_recipient_role_removal_ends_action(self):
        self.save([self.change(mon='2026-11')]);self.run_alerts();old=self.m.Notification.query.one()
        self.m.User.query.filter_by(username='admin').one().role='user';self.m.db.session.commit()
        self.assertFalse(self.state(old)['requires_action']);self.assertEqual(self.run_alerts()['notifications'],0)

    def test_notification_ui_and_action_filter_use_inspection_workflow(self):
        self.save([self.change(mon='2026-11')]);self.run_alerts()
        page=self.client.get('/notifications?view=action');self.assertEqual(page.status_code,200)
        self.assertIn('点検予定の確認',page.get_data(as_text=True))
        n=self.m.Notification.query.one()
        self.assertEqual(self.m.get_notification_workflow_state(n)['workflow_status'],'pending')
        self.assertEqual(self.m.get_notification_display_info(n)['notification_type'],'inspection_plan')

    def test_poll_creates_notifications_and_user_cannot_read_admin_policy_status(self):
        self.save([self.change(mon='2026-11')]);self.assertEqual(self.m.Notification.query.count(),0)
        self.assertEqual(self.client.get('/api/notifications/unread-count').status_code,200)
        self.assertEqual(self.m.Notification.query.count(),1)
        self.m.User.query.filter_by(username='admin').one().role='user';self.m.db.session.commit()
        self.assertEqual(self.client.get('/api/vehicle/inspection-plans/alerts/status').status_code,403)

    def test_fiscal_year_link_points_to_the_overdue_period(self):
        self.save([self.change(mon='2026-03')]);self.run_alerts()
        self.assertIn('year=2025',self.m.Notification.query.one().link)

    def test_certificate_renewal_closes_only_the_vehicle_inspection_notice(self):
        self.vehicle.inspection_expiry='2026-11-30';self.m.db.session.commit()
        self.save([self.change(mon='2026-11',kind='vehicle_inspection'),self.change(mon='2026-11',kind='12month')])
        self.run_alerts();notification=self.m.Notification.query.one()
        self.vehicle.inspection_expiry='2027-11-30';self.m.db.session.commit();self.run_alerts(force=False)
        states=[self.m.inspection_alerts.workflow(notification,date(2026,10,22))]
        self.assertTrue(states[0]['requires_action']);self.assertIn('1件',states[0]['workflow_label'])
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),0)

    def test_partial_completion_keeps_only_remaining_digest_items_actionable(self):
        self.save([self.change(mon='2026-09'),self.change(mon='2026-09',kind='12month')]);self.run_alerts()
        notification=self.m.Notification.query.one();plan=self.m.VehicleInspectionPlan.query.filter_by(kind='3month').one()
        self.complete(plan=plan);self.run_alerts(force=False)
        state=self.state(notification);self.assertTrue(state['requires_action']);self.assertIn('1件',state['workflow_label'])

    def test_deleted_notice_is_not_recreated_on_same_day(self):
        self.save([self.change(mon='2026-11')]);self.run_alerts();n=self.m.Notification.query.one()
        from datetime import datetime
        n.deleted_at=datetime.now();self.m.db.session.commit()
        self.assertEqual(self.run_alerts()['notifications'],0)

    def test_two_workers_do_not_create_duplicate_notifications(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.save([self.change(mon='2026-11')]);self.m.db.session.commit()
        barrier=Barrier(2)
        def worker():
            with self.m.app.app_context():
                barrier.wait(timeout=5)
                try:
                    return self.m.inspection_alerts.run('TEST',today=date(2026,10,22),force=True)
                finally:
                    self.m.db.session.remove()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:worker(),range(2)))
        self.m.db.session.expire_all()
        self.assertEqual(self.m.Notification.query.count(),1)
        self.assertEqual(self.m.inspection_alerts.Delivery.query.count(),1)

    def test_failed_commit_rolls_back_notification_and_delivery_together(self):
        self.save([self.change(mon='2026-11')])
        with patch.object(self.m.db.session,'commit',side_effect=RuntimeError('commit failed')):
            with self.assertRaises(RuntimeError):self.run_alerts()
        self.assertEqual(self.m.Notification.query.count(),0)
        self.assertEqual(self.m.inspection_alerts.Delivery.query.count(),0)
        self.assertEqual(self.m.inspection_alerts.Run.query.count(),0)
        self.assertEqual(self.run_alerts()['notifications'],1)

    def test_cli_tick_is_available_and_duplicate_safe(self):
        self.save([self.change(mon='2026-11')])
        result=self.m.app.test_cli_runner().invoke(args=['inspection-plan-alerts'])
        self.assertEqual(result.exit_code,0,result.output);self.assertEqual(self.m.Notification.query.count(),1)
        result=self.m.app.test_cli_runner().invoke(args=['inspection-plan-alerts'])
        self.assertEqual(result.exit_code,0,result.output);self.assertEqual(self.m.Notification.query.count(),1)


_base_setup=_Base.setUp
del _Base
if __name__=='__main__':unittest.main()
