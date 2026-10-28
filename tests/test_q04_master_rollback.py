"""Master-write atomicity on disposable SQLite; no production connections.

Faults occur after real SQL or after flush but before commit. Each request owns
its app context, so Flask-SQLAlchemy teardown, rather than a test rollback,
must discard the failed transaction. PostgreSQL/concurrency are separate checks.
"""
import json
import re
import unittest

from sqlalchemy import event
from sqlalchemy.orm import Session

import test_q04_master_rename as rename


class InjectedMasterFailure(RuntimeError):
    pass


class MasterRollbackIntegrityTests(unittest.TestCase):
    setUpClass = classmethod(rename.MasterRenameIntegrityTests.setUpClass.__func__)
    tearDownClass = classmethod(rename.MasterRenameIntegrityTests.tearDownClass.__func__)
    setUp = rename.MasterRenameIntegrityTests.setUp
    tearDown = rename.MasterRenameIntegrityTests.tearDown
    seed = rename.MasterRenameIntegrityTests.seed

    def snapshot(self):
        from dkss_app.models import AuditLog, MasterDisplayOrder, VehicleTypeImportMapping
        m = self.m
        m.db.session.expire_all()
        models = [m.Office, m.VehicleType, m.Vehicle, m.User, m.Driver,
                  VehicleTypeImportMapping, m.VehicleMaintenanceRecord,
                  MasterDisplayOrder, AuditLog]
        rows = []
        for model in models:
            query = model.query
            if model is AuditLog:
                # Separate operational failure logs from successful delete logs.
                query = query.filter(model.action.in_([
                    'office_deleted', 'vehicle_type_deleted']))
            rows.append(tuple(tuple(getattr(row, c.name)
                                    for c in model.__table__.columns)
                              for row in query.order_by(model.id).all()))
        return tuple(rows)

    def request_with_own_context(self, url, data=None):
        # The shared fixture holds an app context for seeding/assertions. Pop it
        # so this request gets the same session teardown as a real HTTP request.
        self.ctx.pop()
        try:
            response = self.client.post(url, data=data or {})
            try:
                return response.status_code
            finally:
                response.close()
        finally:
            self.ctx = self.m.app.app_context()
            self.ctx.push()

    def check_failure(self, kind, operation, checkpoint):
        from dkss_app.models import AuditLog, MasterDisplayOrder, VehicleTypeImportMapping
        m = self.m
        self.seed()
        model = m.Office if kind == 'offices' else m.VehicleType
        record = self.office if kind == 'offices' else self.kind
        ident = record.id
        vehicle_id = self.vehicle.id
        mapping_id = self.mapping.id
        m.db.session.add(m.VehicleMaintenanceRecord(
            company_code='TEST', vehicle_record_id=vehicle_id,
            entry_date='2026-10-01', cost_office='Office-A', total_cost=100))
        m.db.session.add(MasterDisplayOrder(
            company_code='TEST', kind=kind, ordered_ids_json=json.dumps([ident])))
        m.db.session.commit()
        before = self.snapshot()
        engine = m.db.engine
        hits = []

        def fail_after_sql(conn, cursor, statement, parameters, context, executemany):
            normalized = re.sub(r'["`\[\]]', '', statement).strip().lower()
            if operation == 'delete':
                verb, table = 'delete from', model.__table__.name
            elif kind == 'offices':
                verb, table = 'update', m.User.__table__.name
            else:
                verb, table = 'update', VehicleTypeImportMapping.__table__.name
            if re.match(r'^' + verb + r'\s+' + re.escape(table.lower()) + r'\b', normalized):
                hits.append('after-sql')
                raise InjectedMasterFailure('Q04_AFTER_SQL')

        def fail_before_commit(session):
            if session.get_bind() is not engine:
                return
            pending = list(session.dirty) + list(session.deleted)
            if not any(isinstance(row, model) and row.id == ident for row in pending):
                return
            # Execute all pending UPDATE/INSERT/DELETE statements first. Raising
            # before flush would not prove rollback of the master/order/audit.
            session.flush()
            hits.append('before-commit-after-flush')
            raise InjectedMasterFailure('Q04_BEFORE_COMMIT')

        if checkpoint == 'sql':
            target, event_name, hook = engine, 'after_cursor_execute', fail_after_sql
        else:
            target, event_name, hook = Session, 'before_commit', fail_before_commit

        url = f'/master/{kind}/{ident}/{operation}'
        data = {'name': 'Renamed'} if operation == 'edit' else {}
        event.listen(target, event_name, hook)
        try:
            try:
                status = self.request_with_own_context(url, data)
            except InjectedMasterFailure:
                pass
            else:
                self.assertGreaterEqual(status, 500)
                self.assertLess(status, 600)
        finally:
            event.remove(target, event_name, hook)

        self.assertEqual(len(hits), 1, 'The intended failure point was not reached exactly once')
        # No rollback() or remove() is called here by the test. This is a fresh
        # app context after normal request teardown, reading the persisted DB.
        self.assertEqual(self.snapshot(), before, 'Failed request left partial writes')

        # A second normal request must still work and must not inherit stale state.
        self.assertEqual(self.request_with_own_context(url, data), 302)
        if operation == 'edit':
            self.assertEqual(m.db.session.get(model, ident).name, 'Renamed')
            vehicle = m.db.session.get(m.Vehicle, vehicle_id)
            if kind == 'offices':
                self.assertEqual(vehicle.office, 'Renamed')
                self.assertEqual(m.User.query.filter_by(company_code='TEST', username='admin').one().office, 'Renamed')
                self.assertEqual(m.Driver.query.filter_by(company_code='TEST', employee_id='TEST-DRIVER').one().office, 'Renamed')
            else:
                self.assertEqual(vehicle.type, 'Renamed')
                self.assertEqual(m.db.session.get(VehicleTypeImportMapping, mapping_id).vehicle_type_name, 'Renamed')
        else:
            self.assertIsNone(m.db.session.get(model, ident))
            order = MasterDisplayOrder.query.filter_by(company_code='TEST', kind=kind).one()
            self.assertEqual(json.loads(order.ordered_ids_json), [])
            action = 'office_deleted' if kind == 'offices' else 'vehicle_type_deleted'
            self.assertEqual(AuditLog.query.filter_by(company_code='TEST', action=action,
                                                     target_id=str(ident)).count(), 1)
            vehicle = m.db.session.get(m.Vehicle, vehicle_id)
            if kind == 'offices':
                self.assertEqual(vehicle.office, '')
                self.assertEqual(m.User.query.filter_by(company_code='TEST', username='admin').one().office, '')
                self.assertEqual(m.Driver.query.filter_by(company_code='TEST', employee_id='TEST-DRIVER').one().office, '')
            else:
                self.assertEqual(vehicle.type, '')
                self.assertIsNone(m.db.session.get(VehicleTypeImportMapping, mapping_id))

    def test_office_rename_rolls_back_after_related_sql(self):
        self.check_failure('offices', 'edit', 'sql')

    def test_office_rename_rolls_back_after_flush_before_commit(self):
        self.check_failure('offices', 'edit', 'commit')

    def test_vehicle_type_rename_rolls_back_after_mapping_sql(self):
        self.check_failure('vehicle-types', 'edit', 'sql')

    def test_vehicle_type_rename_rolls_back_after_flush_before_commit(self):
        self.check_failure('vehicle-types', 'edit', 'commit')

    def test_office_delete_rolls_back_after_master_delete_sql(self):
        self.check_failure('offices', 'delete', 'sql')

    def test_office_delete_rolls_back_order_and_audit_before_commit(self):
        self.check_failure('offices', 'delete', 'commit')

    def test_vehicle_type_delete_rolls_back_after_master_delete_sql(self):
        self.check_failure('vehicle-types', 'delete', 'sql')

    def test_vehicle_type_delete_rolls_back_mapping_order_and_audit_before_commit(self):
        self.check_failure('vehicle-types', 'delete', 'commit')


if __name__ == '__main__':
    unittest.main()
