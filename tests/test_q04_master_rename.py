"""Master rename integrity on real Flask endpoints with disposable SQLite only."""
import unittest
from test_workflow_regressions import WorkflowRegressionTests as Base


class MasterRenameIntegrityTests(unittest.TestCase):
    setUpClass = classmethod(Base.setUpClass.__func__)
    tearDownClass = classmethod(Base.tearDownClass.__func__)
    setUp = Base.setUp
    tearDown = Base.tearDown

    def seed(self):
        m = self.m
        m.db.session.add(m.Company(company_code='OTHER', company_name='Other', active=True))
        self.office = m.Office(company_code='TEST', name='Office-A')
        self.other_office = m.Office(company_code='OTHER', name='Office-A')
        self.kind = m.VehicleType(company_code='TEST', name='Type-A')
        self.other_kind = m.VehicleType(company_code='OTHER', name='Type-A')
        self.vehicle.office = 'Office-A'
        self.vehicle.type = 'Type-A'
        self.foreign_vehicle = m.Vehicle(company_code='OTHER', chassis_number='OTHER-SYNTHETIC', office='Office-A', type='Type-A')
        self.admin = m.User.query.filter_by(company_code='TEST', username='admin').one()
        self.admin.office = 'Office-A'
        self.driver = m.Driver(company_code='TEST', employee_id='TEST-DRIVER', name='Sample', office='Office-A')
        self.foreign_driver = m.Driver(company_code='OTHER', employee_id='OTHER-DRIVER', name='Sample', office='Office-A')
        from dkss_app.models import VehicleTypeImportMapping
        self.mapping = VehicleTypeImportMapping(company_code='TEST', excel_value='IMPORT-A', vehicle_type_name='Type-A')
        self.foreign_mapping = VehicleTypeImportMapping(company_code='OTHER', excel_value='IMPORT-A', vehicle_type_name='Type-A')
        m.db.session.add_all([self.office, self.other_office, self.kind, self.other_kind,
            self.foreign_vehicle, self.driver, self.foreign_driver, self.mapping, self.foreign_mapping])
        m.db.session.commit()

    def snapshot(self):
        from dkss_app.models import VehicleTypeImportMapping
        self.m.db.session.expire_all()
        models = [self.m.Office, self.m.VehicleType, self.m.Vehicle,
                  self.m.User, self.m.Driver, VehicleTypeImportMapping]
        return tuple(tuple(tuple(getattr(row, c.name) for c in model.__table__.columns)
                           for row in model.query.order_by(model.id).all()) for model in models)

    def post(self, kind, record_id, name):
        response = self.client.post(f'/master/{kind}/{record_id}/edit', data={'name': name})
        self.addCleanup(response.close)
        self.m.db.session.expire_all()
        return response

    def test_office_rename_updates_current_vehicle_user_and_driver(self):
        self.seed()
        response = self.post('offices', self.office.id, 'Office-Renamed')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/master/offices')
        self.assertEqual(self.office.name, 'Office-Renamed')
        for row in [self.vehicle, self.admin, self.driver]:
            self.assertEqual(row.office, 'Office-Renamed')

    def test_office_rename_leaves_other_company_unchanged(self):
        self.seed()
        self.assertEqual(self.post('offices', self.office.id, 'Office-Renamed').status_code, 302)
        self.assertEqual(self.other_office.name, 'Office-A')
        self.assertEqual(self.foreign_vehicle.office, 'Office-A')
        self.assertEqual(self.foreign_driver.office, 'Office-A')

    def test_office_rename_does_not_rewrite_historical_cost_office(self):
        self.seed()
        record = self.m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            entry_date='2026-10-01', cost_office='Office-A', total_cost=100)
        self.m.db.session.add(record); self.m.db.session.commit()
        self.assertEqual(self.post('offices', self.office.id, 'Office-Renamed').status_code, 302)
        self.assertEqual(self.vehicle.office, 'Office-Renamed')
        self.assertEqual(record.cost_office, 'Office-A')
        self.assertEqual(record.total_cost, 100)

    def test_office_used_by_news_rejects_rename_without_partial_updates(self):
        self.seed()
        self.m.db.session.add(self.m.News(company_code='TEST', title='Synthetic',
            target_type='office', target_value='Office-A'))
        self.m.db.session.commit()
        before = self.snapshot()
        self.assertEqual(self.post('offices', self.office.id, 'Office-Renamed').status_code, 409)
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_office_rename_rejects_without_partial_updates(self):
        self.seed()
        self.m.db.session.add(self.m.Office(company_code='TEST', name='Office-Taken'))
        self.m.db.session.commit()
        before = self.snapshot()
        self.assertEqual(self.post('offices', self.office.id, 'Office-Taken').status_code, 409)
        self.assertEqual(self.snapshot(), before)

    def test_vehicle_type_rename_updates_vehicle_and_import_mapping(self):
        self.seed()
        self.assertEqual(self.post('vehicle-types', self.kind.id, 'Type-Renamed').status_code, 302)
        self.assertEqual(self.kind.name, 'Type-Renamed')
        self.assertEqual(self.vehicle.type, 'Type-Renamed')
        self.assertEqual(self.mapping.vehicle_type_name, 'Type-Renamed')
        self.assertEqual(self.other_kind.name, 'Type-A')
        self.assertEqual(self.foreign_vehicle.type, 'Type-A')
        self.assertEqual(self.foreign_mapping.vehicle_type_name, 'Type-A')

    def test_duplicate_vehicle_type_rejects_without_partial_updates(self):
        self.seed()
        self.m.db.session.add(self.m.VehicleType(company_code='TEST', name='Type-Taken'))
        self.m.db.session.commit()
        before = self.snapshot()
        self.assertEqual(self.post('vehicle-types', self.kind.id, 'Type-Taken').status_code, 409)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_names_reject_without_updates(self):
        self.seed()
        before = self.snapshot()
        for kind, row in [('offices', self.office), ('vehicle-types', self.kind)]:
            for name in ['', '   ', 'x' * 101]:
                with self.subTest(kind=kind, name_length=len(name)):
                    self.assertEqual(self.post(kind, row.id, name).status_code, 400)
                    self.assertEqual(self.snapshot(), before)

    def test_foreign_master_ids_cannot_be_renamed(self):
        self.seed()
        before = self.snapshot()
        for kind, row in [('offices', self.other_office), ('vehicle-types', self.other_kind)]:
            self.assertEqual(self.post(kind, row.id, 'Rejected').status_code, 302)
            self.assertEqual(self.snapshot(), before)

    def test_general_user_cannot_rename_either_master(self):
        self.seed()
        self.admin.role = 'user'; self.m.db.session.commit()
        with self.client.session_transaction() as state:
            state['role'] = 'user'
        before = self.snapshot()
        for kind, row in [('offices', self.office), ('vehicle-types', self.kind)]:
            self.assertEqual(self.post(kind, row.id, 'Rejected').status_code, 302)
            self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
