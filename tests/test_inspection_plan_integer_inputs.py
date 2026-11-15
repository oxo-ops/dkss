"""Reject ambiguous inspection target IDs; synthetic Flask/SQLite only."""
import unittest
from test_inspection_plans import InspectionPlanTests as _Fixture


class InspectionIntegerInputs(unittest.TestCase):
    setUpClass = classmethod(_Fixture.setUpClass.__func__)
    tearDownClass = classmethod(_Fixture.tearDownClass.__func__)
    setUp = _Fixture.setUp
    tearDown = _Fixture.tearDown
    change = _Fixture.change
    save = _Fixture.save

    def test_fractional_and_boolean_vehicle_ids_do_not_select_real_vehicle(self):
        for value in (True, self.vehicle.id + 0.9, float(self.vehicle.id), 10 ** 30):
            with self.subTest(value=value):
                change = self.change(); change['vehicle_record_id'] = value
                response = self.client.post('/api/vehicle/inspection-plans/preview', json={'changes': [change]})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)

    def test_invalid_plan_id_and_version_do_not_update_existing_plan(self):
        self.save([self.change()])
        plan = self.m.VehicleInspectionPlan.query.one()
        for field in ('id', 'version'):
            for value in (True, 1.9, 1.0, [], {}, 10 ** 30):
                with self.subTest(field=field, value=value):
                    change = self.change(); change.update(id=plan.id, version=plan.version, note='must not save')
                    change[field] = value
                    response = self.client.post('/api/vehicle/inspection-plans/save', json={'changes': [change], 'token': 'invalid'})
                    self.assertEqual(response.status_code, 400)
        self.m.db.session.refresh(plan)
        self.assertEqual(plan.note, '')
        self.assertEqual(plan.version, 1)

    def test_fractional_save_cannot_use_valid_integer_preview_token(self):
        change = self.change()
        preview = self.client.post('/api/vehicle/inspection-plans/preview', json={'changes': [change]})
        self.assertEqual(preview.status_code, 200)
        change['vehicle_record_id'] = self.vehicle.id + 0.9
        response = self.client.post('/api/vehicle/inspection-plans/save',
            json={'changes': [change], 'token': preview.json['token']})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)
        self.assertEqual(self.m.VehicleInspectionPlanEvent.query.count(), 0)

    def test_execution_preview_rejects_ambiguous_ids(self):
        base = dict(vehicle_record_id=self.vehicle.id, kind='3month', performed_date='2026-01-01')
        for field in ('vehicle_record_id', 'plan_id', 'version'):
            for value in (True, 1.9, [], 10 ** 30):
                with self.subTest(field=field, value=value):
                    response = self.client.post('/api/vehicle/inspection-plans/execution/preview', json={**base, field: value})
                    self.assertEqual(response.status_code, 400)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(), 0)

    def test_huge_read_target_is_validation_error_not_database_overflow(self):
        for query in ('detail=1&', 'scope=vehicle&'):
            response = self.client.get('/api/vehicle/inspection-plans?' + query + 'vehicle_id=' + '9' * 30)
            self.assertEqual(response.status_code, 400)

    def test_huge_source_path_id_is_rejected_before_database(self):
        response = self.client.get('/vehicle/inspection-plans/executions/' + '9' * 30 + '/source')
        self.assertEqual(response.status_code, 400)

    def test_integer_strings_remain_supported(self):
        change = self.change(); change.update(vehicle_record_id=str(self.vehicle.id), version='0', id='0')
        self.save([change])
        response = self.client.get(f'/api/vehicle/inspection-plans?detail=1&vehicle_id={self.vehicle.id}')
        self.assertEqual(response.status_code, 200)


del _Fixture


class InspectionIntegerBoundaries(unittest.TestCase):
    def test_exact_bind_bounds_and_optional_absence(self):
        from vehicle_inspection_plans import request_integer
        from werkzeug.exceptions import BadRequest
        for value in (2 ** 63 - 1, str(2 ** 63 - 1), 1, '1'):
            self.assertEqual(request_integer(value), int(value))
        for value in (None, '', 0, '0'):
            self.assertEqual(request_integer(value, optional=True), 0)
        for value in (False, True, -1, '-1', 2 ** 63, str(2 ** 63), 1.0, [], {}):
            for optional in (False, True):
                with self.subTest(value=value, optional=optional):
                    with self.assertRaises(BadRequest):
                        request_integer(value, optional=optional)
        for value in (None, '', 0, '0'):
            with self.assertRaises(BadRequest):
                request_integer(value)
