"""Header elapsed distance must not turn an invalid meter into valid mileage."""
from datetime import timedelta
from decimal import Decimal
import unittest
from flask import template_rendered
import test_workflow_regressions as workflow


class MaintenanceHeaderDistanceTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def prepare(self, mileage):
        m = self.m
        today = m.datetime.now(m.ZoneInfo('Asia/Tokyo')).date()
        stamp = (today - timedelta(days=5)).isoformat()
        record = m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            entry_date=stamp, completion_date=stamp, status='完了', mileage=mileage)
        m.db.session.add(record)
        m.db.session.add(m.VehicleOperationRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            report_number='header-meter', operation_date=today.isoformat(), arrival_meter=1500))
        m.db.session.commit()
        return record

    def summary(self):
        contexts = []
        def capture(sender, template, context, **kwargs):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.m.app):
            response = self.client.get(f'/vehicle/karte/{self.vehicle.id}')
        self.assertEqual(response.status_code, 200)
        return contexts[-1]['karte_maintenance_summary']

    def test_negative_maintenance_meter_is_not_inflated_distance(self):
        record = self.prepare(-100)
        self.assertIsNone(self.summary()['distance_since'])
        self.assertEqual(record.mileage, -100)  # Do not rewrite legacy source data.

    def test_known_zero_maintenance_meter_is_valid(self):
        self.prepare(0)
        self.assertEqual(self.summary()['distance_since'], Decimal('1500'))

    def test_valid_positive_distance_is_preserved(self):
        self.prepare(1000)
        self.assertEqual(self.summary()['distance_since'], Decimal('500'))

    def test_same_meter_is_known_zero_elapsed_distance(self):
        self.prepare(1500)
        self.assertEqual(self.summary()['distance_since'], Decimal('0'))

    def test_missing_or_reversed_maintenance_meter_is_held(self):
        record = self.prepare(None)
        self.assertIsNone(self.summary()['distance_since'])
        record.mileage = 2000
        self.m.db.session.commit()
        self.assertIsNone(self.summary()['distance_since'])
