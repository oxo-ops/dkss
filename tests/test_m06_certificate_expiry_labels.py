"""M06 partial acceptance: certificate wording without reclassifying legacy facts."""
import unittest
from datetime import date
from test_inspection_alerts import InspectionAlertTests as _Alerts
from test_workflow_regressions import WorkflowRegressionTests as _Workflow


class CertificateExpiryLabelTests(unittest.TestCase):
    setUpClass = classmethod(_Workflow.setUpClass.__func__)
    tearDownClass = classmethod(_Workflow.tearDownClass.__func__)
    setUp = _Alerts.setUp
    tearDown = _Alerts.tearDown
    expiry = _Alerts.expiry
    run_alerts = _Alerts.run_alerts
    state = _Alerts.state

    def test_new_expiry_notice_identifies_certificate_without_creating_facts(self):
        self.expiry()
        report = self.run_alerts()
        notice = self.m.Notification.query.one()
        self.assertEqual(report['notifications'], 1)
        self.assertIn('車検証満了日', notice.title)
        self.assertIn('車検証満了日 2026-10-22', notice.message)
        self.assertNotIn('12か月点検期限', notice.title + notice.message)
        self.assertTrue(self.state(notice)['requires_action'])
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(), 0)

    def test_old_notice_text_receipt_and_read_state_survive_repeated_poll(self):
        self.expiry()
        self.run_alerts()
        notice = self.m.Notification.query.one()
        notice.title = '点検予定の確認：12か月点検期限・予定未登録 1件'
        notice.message = '旧版で保存済みの12か月点検期限通知'
        notice.read = True
        self.m.db.session.commit()
        receipt = self.m.inspection_alerts.ExpiryDelivery.query.one()
        before = (notice.id, notice.title, notice.message, notice.read, receipt.id,
                  receipt.phase, receipt.bucket, receipt.sent_day, receipt.ended_status)
        for _ in range(2):
            self.assertEqual(self.run_alerts()['notifications'], 0)
        self.m.db.session.refresh(notice)
        self.m.db.session.refresh(receipt)
        self.assertEqual(before, (notice.id, notice.title, notice.message, notice.read, receipt.id,
                                 receipt.phase, receipt.bucket, receipt.sent_day, receipt.ended_status))
        self.assertEqual(self.m.Notification.query.count(), 1)
        self.assertEqual(self.m.inspection_alerts.ExpiryDelivery.query.count(), 1)

    def test_certificate_section_names_master_expiry_without_changing_plan_state(self):
        self.expiry()
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<dt>車検証満了日</dt><dd>2026-10-22</dd>', response.get_data(as_text=True))
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(), 0)

    def test_phase_keys_and_trigger_dates_survive_wording_change(self):
        from vehicle_inspection_alerts import expiry_phase
        for day, key in [('2026-09-30', None), ('2026-10-01', 'expiry_prior'),
                         ('2026-11-01', 'expiry_month'), ('2026-11-23', 'expiry_7days'),
                         ('2026-11-29', 'expiry_1day'), ('2026-11-30', 'expiry_today'),
                         ('2026-12-01', 'expiry_elapsed')]:
            with self.subTest(day=day):
                phase = expiry_phase(date(2026, 11, 30), date.fromisoformat(day))
                self.assertEqual(phase[0] if phase else None, key)
                if phase:
                    self.assertIn('車検証満了日', phase[2])
                    self.assertNotIn('12か月点検', phase[2])


del _Alerts, _Workflow
