"""Q05: protect date precision and reject dates unsafe for ISO comparisons."""
import unittest

import test_workflow_regressions as workflow
from dkss_app.vehicle_master import get_vehicle_date_error


class VehicleDateInputTests(unittest.TestCase):
    def test_exact_dates_accept_leap_days_and_century_rules(self):
        for value in ('2000-02-29', '2028-02-29', '2026-12-31'):
            with self.subTest(value=value):
                self.assertIsNone(get_vehicle_date_error(value, '車検満了日'))
        for value in ('1900-02-29', '2026-02-29', '2026-04-31', '0000-01-01'):
            with self.subTest(value=value):
                self.assertIsNotNone(get_vehicle_date_error(value, '車検満了日'))

    def test_reject_noncanonical_dates_before_string_comparisons(self):
        for value in ('2026-2-03', '2026-02-3', '2026-2-3', '2026-01-1',
                      '20260203', '2026/02/03', '2026-02-03T00:00:00',
                      '2026-02-03\n', '２０２６-０２-０３'):
            with self.subTest(value=value):
                self.assertIsNotNone(get_vehicle_date_error(value, '車検満了日'))

    def test_month_precision_only_for_first_registration(self):
        self.assertIsNone(get_vehicle_date_error('2026-02', '初年度登録日'))
        for value in ('2026-00', '2026-13', '2026-2', '0000-01'):
            with self.subTest(value=value):
                self.assertIsNotNone(get_vehicle_date_error(value, '初年度登録日'))
        self.assertIsNotNone(get_vehicle_date_error('2026-02', '車検満了日'))

    def test_unknown_dates_remain_unknown(self):
        for field in ('初年度登録日', '車検満了日'):
            for value in ('', None):
                self.assertIsNone(get_vehicle_date_error(value, field))


class VehicleDateRouteTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def test_new_vehicle_rejects_noncanonical_expiry_without_writing(self):
        response = self.client.post('/master/vehicles/new', data={
            'chassis_number': 'Q05-NEW', 'vehicle_form_action': 'save',
            'inspection_expiry': '2026-2-3',
        }, headers={'Accept': 'application/json'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.m.Vehicle.query.count(), 1)
        self.assertIsNone(self.m.Vehicle.query.filter_by(chassis_number='Q05-NEW').first())

    def test_edit_rejects_noncanonical_expiry_preserving_original(self):
        self.vehicle.inspection_expiry = '2026-02-03'
        self.m.db.session.commit()
        response = self.client.post(f'/master/vehicles/{self.vehicle.id}/edit', data={
            'chassis_number': self.vehicle.chassis_number, 'vehicle_form_action': 'save',
            'inspection_expiry': '2026-2-3',
        }, headers={'Accept': 'application/json'})
        self.assertEqual(response.status_code, 400)
        self.m.db.session.refresh(self.vehicle)
        self.assertEqual(self.vehicle.inspection_expiry, '2026-02-03')

    def test_registration_month_and_unknown_expiry_are_preserved(self):
        response = self.client.post('/master/vehicles/new', data={
            'chassis_number': 'Q05-MONTH', 'vehicle_form_action': 'save',
            'first_registration_date': '2026-02', 'inspection_expiry': '',
        })
        self.assertEqual(response.status_code, 302)
        vehicle = self.m.Vehicle.query.filter_by(chassis_number='Q05-MONTH').one()
        self.assertEqual(vehicle.first_registration_date, '2026-02')
        self.assertFalse(vehicle.inspection_expiry)

    def test_excel_confirmation_rejects_unpadded_date_without_writing(self):
        form = {name: '' for name in (
            'vehicle_type_code', 'vehicle_type', 'plate_area', 'plate_class',
            'plate_kana', 'plate_number', 'gross_vehicle_weight', 'chassis_number',
            'model_code', 'first_registration_date', 'inspection_expiry',
            'vehicle_name', 'body_type', 'max_payload', 'office', 'active_status',
        )}
        form.update(chassis_number='Q05-EXCEL', inspection_expiry='2026-2-3',
                    active_status='有効')
        response = self.client.post('/master/vehicles/import/confirm', data=form,
                                    headers={'Accept': 'application/json'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json['errors'], [{
            'field': 'inspection_expiry', 'message': '1行目の車検満了日が不正です。',
        }])
        self.assertEqual(self.m.Vehicle.query.count(), 1)
