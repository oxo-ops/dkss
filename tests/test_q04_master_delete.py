"""Existing master deletion behavior: isolated SQLite, real Flask routes.

These tests verify current behavior, not a decision to permit deletion in every
business situation. PostgreSQL concurrency and transaction failures are separate.
"""
import json
import unittest
import test_q04_master_rename as rename


class MasterDeleteIntegrityTests(unittest.TestCase):
    setUpClass = classmethod(rename.MasterRenameIntegrityTests.setUpClass.__func__)
    tearDownClass = classmethod(rename.MasterRenameIntegrityTests.tearDownClass.__func__)
    setUp = rename.MasterRenameIntegrityTests.setUp
    tearDown = rename.MasterRenameIntegrityTests.tearDown
    seed = rename.MasterRenameIntegrityTests.seed

    def snapshot(self):
        from dkss_app import models
        self.m.db.session.expire_all()
        kinds = [models.Office, models.VehicleType, models.Vehicle, models.User,
                 models.Driver, models.VehicleTypeImportMapping, models.News,
                 models.PatrolResult, models.ChecklistResult,
                 models.VehicleMaintenanceRecord, models.MasterDisplayOrder]
        return tuple(tuple(tuple(getattr(row, c.name) for c in model.__table__.columns)
                           for row in model.query.order_by(model.id).all()) for model in kinds)

    def delete(self, kind, record_id):
        response = self.client.post(f'/master/{kind}/{record_id}/delete')
        self.addCleanup(response.close)
        self.m.db.session.expire_all()
        return response

    def test_office_delete_clears_only_current_company_assignments(self):
        self.seed()
        record_id = self.office.id
        response = self.delete('offices', record_id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/master/offices')
        self.assertIsNone(self.m.db.session.get(self.m.Office, record_id))
        for row in [self.vehicle, self.admin, self.driver]:
            self.assertEqual(row.office, '')
        self.assertEqual(self.foreign_vehicle.office, 'Office-A')
        self.assertEqual(self.foreign_driver.office, 'Office-A')
        self.assertEqual(self.other_office.name, 'Office-A')

    def test_office_delete_preserves_historical_cost_and_vehicle(self):
        self.seed()
        vehicle_id = self.vehicle.id
        row = self.m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=vehicle_id,
            entry_date='2026-10-01', cost_office='Office-A', total_cost=100)
        self.m.db.session.add(row); self.m.db.session.commit()
        row_id = row.id
        self.assertEqual(self.delete('offices', self.office.id).status_code, 302)
        saved = self.m.db.session.get(self.m.VehicleMaintenanceRecord, row_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.cost_office, 'Office-A')
        self.assertEqual(saved.total_cost, 100)
        self.assertEqual(saved.vehicle_record_id, vehicle_id)
        self.assertIsNotNone(self.m.db.session.get(self.m.Vehicle, vehicle_id))

    def test_news_reference_blocks_office_delete_without_partial_changes(self):
        self.seed()
        self.m.db.session.add(self.m.News(company_code='TEST', title='Synthetic',
            target_type='office', target_value='Office-A'))
        self.m.db.session.commit()
        before = self.snapshot()
        self.assertEqual(self.delete('offices', self.office.id).status_code, 409)
        self.assertEqual(self.snapshot(), before)

    def test_patrol_history_blocks_office_delete_without_partial_changes(self):
        self.seed()
        self.m.db.session.add(self.m.PatrolResult(company_code='TEST', office='Office-A'))
        self.m.db.session.commit()
        before = self.snapshot()
        self.assertEqual(self.delete('offices', self.office.id).status_code, 409)
        self.assertEqual(self.snapshot(), before)

    def test_checklist_history_blocks_office_delete_without_partial_changes(self):
        self.seed()
        checklist = self.m.Checklist(company_code='TEST', name='Synthetic', active=True, items_json='[]')
        self.m.db.session.add(checklist); self.m.db.session.flush()
        self.m.db.session.add(self.m.ChecklistResult(company_code='TEST',
            checklist_id=checklist.id, target_office='Office-A'))
        self.m.db.session.commit()
        before = self.snapshot()
        self.assertEqual(self.delete('offices', self.office.id).status_code, 409)
        self.assertEqual(self.snapshot(), before)

    def test_other_company_history_does_not_block_own_office_delete(self):
        self.seed()
        row = self.m.News(company_code='OTHER', title='Synthetic', target_type='office', target_value='Office-A')
        self.m.db.session.add(row); self.m.db.session.commit()
        row_id = row.id
        self.assertEqual(self.delete('offices', self.office.id).status_code, 302)
        self.assertEqual(self.m.db.session.get(self.m.News, row_id).target_value, 'Office-A')

    def test_type_delete_clears_own_assignment_and_mapping_only(self):
        from dkss_app.models import VehicleTypeImportMapping
        self.seed()
        kind_id, mapping_id = self.kind.id, self.mapping.id
        self.assertEqual(self.delete('vehicle-types', kind_id).status_code, 302)
        self.assertIsNone(self.m.db.session.get(self.m.VehicleType, kind_id))
        self.assertIsNone(self.m.db.session.get(VehicleTypeImportMapping, mapping_id))
        self.assertEqual(self.vehicle.type, '')
        self.assertEqual(self.foreign_vehicle.type, 'Type-A')
        self.assertEqual(self.foreign_mapping.vehicle_type_name, 'Type-A')
        self.assertEqual(self.other_kind.name, 'Type-A')

    def test_foreign_ids_cannot_be_deleted(self):
        self.seed()
        before = self.snapshot()
        for kind, row in [('offices', self.other_office), ('vehicle-types', self.other_kind)]:
            self.assertEqual(self.delete(kind, row.id).status_code, 302)
            self.assertEqual(self.snapshot(), before)

    def test_general_user_cannot_delete_either_master(self):
        self.seed()
        self.admin.role = 'user'; self.m.db.session.commit()
        with self.client.session_transaction() as state:
            state['role'] = 'user'
        before = self.snapshot()
        for kind, row in [('offices', self.office), ('vehicle-types', self.kind)]:
            self.assertEqual(self.delete(kind, row.id).status_code, 302)
            self.assertEqual(self.snapshot(), before)

    def test_csrf_required_for_both_delete_routes(self):
        self.seed()
        before = self.snapshot()
        self.m.app.config['WTF_CSRF_ENABLED'] = True
        try:
            for kind, row in [('offices', self.office), ('vehicle-types', self.kind)]:
                self.assertEqual(self.delete(kind, row.id).status_code, 400)
                self.assertEqual(self.snapshot(), before)
        finally:
            self.m.app.config['WTF_CSRF_ENABLED'] = False

    def test_delete_removes_saved_order_id_and_preserves_foreign_order(self):
        from dkss_app.models import MasterDisplayOrder
        self.seed()
        for kind, model, current, foreign in [
            ('offices', self.m.Office, self.office, self.other_office),
            ('vehicle-types', self.m.VehicleType, self.kind, self.other_kind),
        ]:
            extra = model(company_code='TEST', name='Synthetic-extra')
            self.m.db.session.add(extra); self.m.db.session.flush()
            remaining_id = extra.id
            own_order = MasterDisplayOrder(company_code='TEST', kind=kind,
                ordered_ids_json=json.dumps([current.id, remaining_id]))
            foreign_order = MasterDisplayOrder(company_code='OTHER', kind=kind,
                ordered_ids_json=json.dumps([foreign.id]))
            self.m.db.session.add_all([own_order, foreign_order]); self.m.db.session.commit()
            foreign_json = foreign_order.ordered_ids_json
            self.assertEqual(self.delete(kind, current.id).status_code, 302)
            self.assertEqual(json.loads(own_order.ordered_ids_json), [remaining_id])
            self.assertEqual(foreign_order.ordered_ids_json, foreign_json)

    def test_repeated_deletion_does_not_duplicate_delete_audit(self):
        from dkss_app.models import AuditLog
        self.seed()
        for kind, row, action in [('offices', self.office, 'office_deleted'),
                                   ('vehicle-types', self.kind, 'vehicle_type_deleted')]:
            record_id = row.id
            count = AuditLog.query.filter_by(company_code='TEST', action=action).count()
            self.assertEqual(self.delete(kind, record_id).status_code, 302)
            self.assertEqual(self.delete(kind, record_id).status_code, 302)
            logs = AuditLog.query.filter_by(company_code='TEST', action=action).all()
            self.assertEqual(len(logs), count + 1)
            self.assertEqual(logs[-1].target_id, str(record_id))
            self.assertEqual(logs[-1].username, 'admin')


if __name__ == '__main__':
    unittest.main()
