"""Current parts card uses the same evidence gate as the analysis panel."""
from datetime import timedelta
import json
import unittest
import test_workflow_regressions as workflow


class CurrentPartDistanceTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def prepare(self, *, status='完了', invoice=False, mileage=1000, completion=None):
        m = self.m
        today = m.datetime.now(m.ZoneInfo('Asia/Tokyo')).date()
        stamp = (today - timedelta(days=5)).isoformat()
        parent = m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            entry_date=stamp, completion_date=completion, status=status, content='タイヤ交換',
            invoice_details_json=json.dumps({'source': {'draft_id': 'synthetic'}}) if invoice else '{}')
        m.db.session.add(parent); m.db.session.flush()
        part = m.VehiclePartReplacement(company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=parent.id, part_name='タイヤ', replacement_date=stamp,
            mileage=mileage, created_at=stamp, updated_at=stamp)
        m.db.session.add(part)
        m.db.session.add(m.VehicleOperationRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            report_number='synthetic-current', operation_date=today.isoformat(), arrival_meter=1500))
        m.db.session.commit()
        return parent, part

    def card(self):
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/parts')
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        return text.split('class="kp-current-list', 1)[1].split('class="kp-interval-label', 1)[0]

    def test_completed_replacement_and_known_zero_are_displayed(self):
        parent, part = self.prepare()
        self.assertIn('交換後 <b>500</b> km', self.card())
        part.mileage = 1500; self.m.db.session.commit()
        self.assertIn('交換後 <b>0</b> km', self.card())

    def test_unconfirmed_work_is_not_presented_as_completed_replacement(self):
        parent, part = self.prepare(status='入庫中')
        before = (parent.status, parent.completion_date, part.mileage)
        text = self.card()
        self.assertIn('交換の実施未確認', text)
        self.assertNotIn('交換後 <b>', text)
        self.assertEqual((parent.status, parent.completion_date, part.mileage), before)

    def test_actual_invoice_does_not_require_manual_completion_status(self):
        self.prepare(status='入庫中', invoice=True)
        self.assertIn('交換後 <b>500</b> km', self.card())

    def test_future_completion_is_held(self):
        m = self.m
        tomorrow = (m.datetime.now(m.ZoneInfo('Asia/Tokyo')).date() + timedelta(days=1)).isoformat()
        self.prepare(completion=tomorrow)
        self.assertIn('基準日までの交換を確認できません', self.card())

    def test_conflicting_same_day_replacement_meters_are_held(self):
        parent, part = self.prepare()
        m = self.m
        m.db.session.add(m.VehiclePartReplacement(company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=parent.id, part_name='タイヤ', replacement_date=part.replacement_date,
            mileage=1200, created_at=part.created_at))
        m.db.session.commit()
        text = self.card()
        self.assertIn('同日の交換時距離が不一致', text)
        self.assertNotIn('交換後 <b>', text)

    def test_negative_replacement_meter_is_not_a_larger_elapsed_distance(self):
        self.prepare(mileage=-100)
        text = self.card()
        self.assertIn('交換時距離が未取得・不正', text)
        self.assertNotIn('交換後 <b>', text)
