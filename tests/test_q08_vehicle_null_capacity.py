"""Unknown vehicle states consume a reservation without being reclassified."""
import json
import unittest
from test_workflow_regressions import WorkflowRegressionTests as Fixture


class VehicleNullCapacityTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown

    def unknown(self):
        # A raw/legacy INSERT omitting deleted has no server default. Normal ORM
        # creation supplies False; no production route is claimed to create NULL.
        self.m.db.session.execute(self.m.db.text(
            "INSERT INTO vehicle (company_code,chassis_number) VALUES ('TEST','Q08-UNKNOWN')"))
        self.m.Company.query.filter_by(company_code='TEST').one().vehicle_limit = 2
        self.m.db.session.commit()
        return self.m.Vehicle.query.filter_by(chassis_number='Q08-UNKNOWN').one()

    def assert_unknown_preserved(self, row):
        self.m.db.session.expire_all()
        self.assertIsNone(row.deleted)

    def test_legacy_omitted_boolean_is_null_and_new_orm_vehicle_is_false(self):
        row = self.unknown()
        self.assertIsNone(row.deleted)
        self.assertFalse(self.vehicle.deleted)

    def test_null_reservation_blocks_new_registration_at_capacity(self):
        row = self.unknown()
        response = self.client.post('/master/vehicles/new',data={
            'chassis_number':'Q08-NEW', 'vehicle_form_action':'save'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.m.Vehicle.query.count(),2)
        self.assert_unknown_preserved(row)

    def test_null_reservation_allows_new_registration_when_capacity_remains(self):
        row = self.unknown()
        self.m.Company.query.filter_by(company_code='TEST').one().vehicle_limit = 3
        self.m.db.session.commit()
        response = self.client.post('/master/vehicles/new',data={
            'chassis_number':'Q08-NEW', 'vehicle_form_action':'save'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.m.Vehicle.query.count(),3)
        self.assert_unknown_preserved(row)

    def test_unknown_cannot_be_implicitly_activated_or_deactivated(self):
        row = self.unknown()
        for inactive in ['0','1']:
            response = self.client.post(f'/master/vehicles/{row.id}/inactive',data={'inactive':inactive})
            self.assertEqual(response.status_code,409)
            self.assert_unknown_preserved(row)

    def test_bulk_activation_of_unknown_is_rejected_atomically(self):
        row = self.unknown()
        self.vehicle.deleted = True
        self.m.db.session.commit()
        response = self.client.post('/master/vehicles/bulk-active',data={'vehicle_ids':[str(row.id),str(self.vehicle.id)]})
        self.assertEqual(response.status_code,409)
        self.assert_unknown_preserved(row)
        self.assertTrue(self.vehicle.deleted)

    def test_pending_csv_creation_respects_null_reservation_without_writes(self):
        from dkss_app.vehicle_pending import create_vehicle_from_pending_operations
        row = self.unknown()
        pending = self.m.VehicleImportPending(company_code='TEST',status='pending',
            identity_json=json.dumps({'source_vehicle_number':'品川100あ1234','chassis_number':'Q08-CSV'}))
        with self.assertRaises(self.m.UploadValidationError):
            create_vehicle_from_pending_operations(pending,'TEST')
        self.assertEqual(self.m.Vehicle.query.count(),2)
        self.assert_unknown_preserved(row)

    def test_other_company_unknown_does_not_consume_own_capacity(self):
        from dkss_app.vehicle_capacity import reserved_vehicle_count
        self.m.db.session.execute(self.m.db.text(
            "INSERT INTO vehicle (company_code,chassis_number) VALUES ('OTHER','Q08-OTHER')"))
        self.m.db.session.commit()
        self.assertEqual(reserved_vehicle_count('TEST'),1)
