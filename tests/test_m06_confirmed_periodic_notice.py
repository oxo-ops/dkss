"""Confirmed twelve-month source must not be retired by a certificate renewal."""
import json
import unittest
from datetime import date
from test_inspection_alerts import InspectionAlertTests as _Alerts
from test_inspection_plans import InspectionPlanTests as _Plans


class ConfirmedPeriodicNoticeTests(unittest.TestCase):
    setUpClass = classmethod(_Plans.setUpClass.__func__)
    tearDownClass = classmethod(_Plans.tearDownClass.__func__)
    setUp = _Alerts.setUp
    tearDown = _Alerts.tearDown
    upload_inspection = _Plans.upload_inspection
    inspection_form = _Plans.inspection_form
    run_alerts = _Alerts.run_alerts
    state = _Alerts.state

    def confirmed_plan(self):
        from test_inspection_document_ai import extraction, pdf_bytes
        source = pdf_bytes()
        data = extraction(source)
        data['records'][0].update(inspection_type='12month', inspection_type_raw='12か月定期点検',
                                  inspection_date='2026-09-12', next_inspection_month='2026-10', next_inspection_date=None)
        self.assertEqual(self.upload_inspection(data=data, source=source).status_code, 302)
        draft = self.m.VehicleDocumentImportDraft.query.one()
        response = self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=self.inspection_form(draft))
        self.assertEqual(response.status_code, 302)
        record = self.m.VehiclePeriodicInspectionRecord.query.one()
        plan = self.m.VehicleInspectionPlan.query.one()
        self.assertEqual((plan.kind, plan.source, plan.source_record_id), ('12month', 'document', record.id))
        self.vehicle.inspection_expiry = '2026-10-30'
        self.m.db.session.commit()
        return plan, record, draft

    def test_certificate_update_does_not_end_confirmed_twelve_month_notice(self):
        plan, record, draft = self.confirmed_plan()
        self.run_alerts()
        notice = self.m.Notification.query.one()
        receipt = self.m.inspection_alerts.Delivery.query.one()
        before = (receipt.id, receipt.revision, receipt.phase, receipt.bucket, receipt.sent_day)
        self.assertTrue(self.state(notice)['requires_action'])
        self.vehicle.inspection_expiry = '2027-10-30'
        self.m.db.session.commit()
        self.assertTrue(self.state(notice)['requires_action'])
        self.assertEqual(self.run_alerts()['notifications'], 0)
        self.m.db.session.refresh(receipt)
        self.m.db.session.refresh(notice)
        self.assertIsNone(receipt.ended_status)
        self.assertFalse(notice.read)
        self.assertEqual(before, (receipt.id, receipt.revision, receipt.phase, receipt.bucket, receipt.sent_day))
        self.assertEqual(self.m.inspection_alerts.Delivery.query.count(), 1)
        self.assertEqual(self.m.Notification.query.count(), 1)
        self.assertEqual(plan.status, 'planned')
        self.assertEqual(self.m.inspection_plans.Execution.query.count(), 0)


    def test_confirmed_source_classification_is_read_only_and_rejects_conflicts(self):
        from vehicle_inspection_alerts import confirmed_twelve_month_source
        plan, record, draft = self.confirmed_plan()
        before = (plan.kind, record.inspection_type, record.details_json, draft.preview_json, draft.result_json)
        self.assertTrue(confirmed_twelve_month_source(plan, record, draft))
        mutations = [
            (record, 'company_code', 'FOREIGN'), (draft, 'company_code', 'FOREIGN'),
            (record, 'vehicle_record_id', self.vehicle.id + 1),
            (record, 'inspection_type', 'vehicle_inspection'),
            (draft, 'status', 'preview'), (draft, 'document_type', 'certificate'),
            (record, 'source_record_index', -1), (plan, 'period_key', '2026-12'),
            (plan, 'source', 'manual'),
            (record, 'details_json', 'not-json'), (draft, 'preview_json', '[]'),
            (draft, 'result_json', json.dumps({'records': []})),
        ]
        for obj, field, value in mutations:
            with self.subTest(field=field, value=value):
                original = getattr(obj, field)
                setattr(obj, field, value)
                self.assertFalse(confirmed_twelve_month_source(plan, record, draft))
                setattr(obj, field, original)
        for raw in ('車検', '12か月点検・車検', '不明', None, [], {}):
            with self.subTest(raw=raw):
                details = json.loads(record.details_json)
                details['inspection_type_raw'] = raw
                record.details_json = json.dumps(details)
                self.assertFalse(confirmed_twelve_month_source(plan, record, draft))
                record.details_json = before[2]
        self.assertEqual(before, (plan.kind, record.inspection_type, record.details_json, draft.preview_json, draft.result_json))

    def test_closed_receipt_is_not_reopened_or_reissued(self):
        self.confirmed_plan()
        self.run_alerts()
        notice = self.m.Notification.query.one()
        receipt = self.m.inspection_alerts.Delivery.query.one()
        receipt.ended_status = 'closed'
        notice.read = True
        self.vehicle.inspection_expiry = '2027-10-30'
        self.m.db.session.commit()
        self.assertEqual(self.run_alerts()['notifications'], 0)
        self.m.db.session.refresh(receipt)
        self.m.db.session.refresh(notice)
        self.assertEqual(receipt.ended_status, 'closed')
        self.assertTrue(notice.read)
        self.assertFalse(self.state(notice)['requires_action'])
        self.assertEqual(self.m.Notification.query.count(), 1)

    def test_real_twelve_month_actual_still_completes_its_notice(self):
        from test_inspection_document_ai import extraction, pdf_bytes
        plan, _, _ = self.confirmed_plan()
        self.run_alerts()
        notice = self.m.Notification.query.one()
        self.vehicle.inspection_expiry = '2027-10-30'
        self.m.db.session.commit()
        source = pdf_bytes(2)
        data = extraction(source)
        data['records'][0].update(inspection_type='12month', inspection_type_raw='12か月定期点検',
                                  inspection_date='2026-10-20', next_inspection_month=None, next_inspection_date=None)
        self.assertEqual(self.upload_inspection(data=data, source=source).status_code, 302)
        draft = self.m.VehicleDocumentImportDraft.query.filter_by(status='preview').one()
        self.assertEqual(self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm',
                                         data=self.inspection_form(draft)).status_code, 302)
        self.run_alerts()
        self.m.db.session.refresh(plan)
        self.assertEqual(plan.status, 'completed')
        self.assertFalse(self.state(notice)['requires_action'])
        self.assertEqual(self.m.inspection_alerts.Delivery.query.one().ended_status, 'completed')



del _Alerts, _Plans
