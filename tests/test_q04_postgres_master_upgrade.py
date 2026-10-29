"""Legacy master index upgrades on an owned disposable PostgreSQL schema.

No production URLs are accepted. The shared fixture enforces a loopback-only
dkss_q04_ci database and creates a random private schema. Failed upgrades are
observed from a new app context; the test never rolls their transaction back.
"""
import json
import os
import unittest
from uuid import uuid4
from unittest.mock import patch

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

import test_q04_postgres_master_concurrency as concurrency


class MasterPostgresUpgradeTests(unittest.TestCase):
    setUpClass = classmethod(concurrency.MasterConcurrencyTests.setUpClass.__func__)
    drop_schema = classmethod(concurrency.MasterConcurrencyTests.drop_schema.__func__)

    def upgrade(self):
        from dkss_app.database import init_db
        with patch.dict(os.environ, {'ITC_INITIAL_PASSWORD': 'Q04-Test-Only-742!'}):
            with self.app.app_context():
                init_db()

    def setUp(self):
        with self.app.app_context():
            self.assertEqual(self.db.session.scalar(text('SELECT current_schema()')), self.schema)
            self.assertEqual(self.db.session.scalar(text('SELECT current_database()')), 'dkss_q04_ci')
            # Each case starts clean inside this class's random private schema.
            self.db.drop_all()
            self.db.create_all()
        self.upgrade()
        concurrency.MasterConcurrencyTests.setUp(self)
        with self.app.app_context():
            for code in (self.company, self.other):
                vehicle = self.m.Vehicle.query.filter_by(company_code=code).one()
                self.db.session.add(self.m.VehicleMaintenanceRecord(company_code=code,
                    vehicle_record_id=vehicle.id, entry_date='2026-10-01',
                    cost_office='Office-A', total_cost=100))
            self.db.session.commit()

    def snapshot(self, company):
        result = concurrency.MasterConcurrencyTests.snapshot(self, company)
        with self.app.app_context():
            model = self.m.VehicleMaintenanceRecord
            result[model.__tablename__] = [
                {c.name: getattr(row, c.name) for c in model.__table__.columns}
                for row in model.query.filter_by(company_code=company).order_by(model.id)]
        return result

    def both_snapshots(self):
        return self.snapshot(self.company), self.snapshot(self.other)

    def indexes(self):
        result = {}
        with self.app.app_context():
            inspector = inspect(self.db.engine)
            for table in ('office', 'vehicle_type'):
                result[table] = sorted((i['name'], bool(i['unique']), tuple(i['column_names']))
                                       for i in inspector.get_indexes(table))
        return result

    def remove_indexes(self):
        with self.app.app_context():
            self.db.session.execute(text('DROP INDEX uq_office_company_name'))
            self.db.session.execute(text('DROP INDEX uq_vehicle_type_company_name'))
            self.db.session.commit()
        self.assertEqual(self.indexes(), {'office': [], 'vehicle_type': []})

    def assert_indexes(self):
        actual = self.indexes()
        self.assertIn(('uq_office_company_name', True, ('company_code', 'name')), actual['office'])
        self.assertIn(('uq_vehicle_type_company_name', True, ('company_code', 'name')), actual['vehicle_type'])

    def evidence(self, scenario):
        # All values come from synthetic seed data in this private schema.
        print('Q04_UPGRADE_EVIDENCE:', json.dumps({'test': self.id(), 'scenario': scenario,
            'server_version': self.server_version, 'indexes': self.indexes(),
            'companies': [self.company, self.other]}, ensure_ascii=True), flush=True)

    def test_legacy_upgrade_adds_indexes_and_preserves_related_and_historical_rows(self):
        self.remove_indexes()
        before = self.both_snapshots()
        self.upgrade()
        self.assert_indexes()
        self.assertEqual(self.both_snapshots(), before)
        # Existing identical names in two companies must survive the upgrade.
        # Verify the PostgreSQL indexes themselves reject duplicates afterwards.
        for table, name in (('office', 'Office-A'), ('vehicle_type', 'Type-A')):
            with self.subTest(table=table):
                with self.assertRaises(IntegrityError) as raised:
                    with self.engine.begin() as connection:
                        connection.execute(text('INSERT INTO ' + table
                            + ' (company_code, name, master_generation) VALUES (:company, :name, :generation)'),
                            {'company': self.company, 'name': name, 'generation': str(uuid4())})
                self.assertEqual(raised.exception.orig.diag.constraint_name,
                                 'uq_' + table + '_company_name')
        self.assertEqual(self.both_snapshots(), before)
        self.evidence('legacy-upgrade-preserves-data-and-enforces-company-names')

    def test_repeated_upgrade_preserves_index_identity_and_all_seeded_rows(self):
        self.remove_indexes()
        self.upgrade()
        before = self.both_snapshots()
        with self.engine.connect() as connection:
            query = text("SELECT oid, relname FROM pg_class WHERE relnamespace = "
                "(SELECT oid FROM pg_namespace WHERE nspname = :schema) "
                "AND relname IN ('uq_office_company_name', 'uq_vehicle_type_company_name') ORDER BY relname")
            first = list(connection.execute(query, {'schema': self.schema}))
        self.upgrade()
        self.upgrade()
        with self.engine.connect() as connection:
            self.assertEqual(list(connection.execute(query, {'schema': self.schema})), first)
        self.assert_indexes()
        self.assertEqual(self.both_snapshots(), before)
        self.evidence('repeated-upgrade-keeps-indexes-and-data')

    def check_duplicate(self, table, model, name, message):
        self.remove_indexes()
        with self.app.app_context():
            self.db.session.add(model(company_code=self.company, name=name))
            self.db.session.commit()
        before = self.both_snapshots()
        with self.assertRaisesRegex(RuntimeError, message):
            self.upgrade()
        # No test-side rollback/remove before reading the persisted result.
        # For duplicate vehicle types, the new office index was created earlier
        # in init_db; PostgreSQL must roll that DDL back on context teardown too.
        self.assertEqual(self.indexes(), {'office': [], 'vehicle_type': []})
        self.assertEqual(self.both_snapshots(), before)
        with self.app.app_context():
            self.assertEqual(model.query.filter_by(company_code=self.company, name=name).count(), 2)
            self.assertEqual(model.query.filter_by(company_code=self.other, name=name).count(), 1)
        self.evidence('duplicate-' + table + '-stops-without-rewriting-data')

    def test_duplicate_offices_stop_upgrade_without_merging_or_deleting_data(self):
        self.check_duplicate('office', self.m.Office, 'Office-A', '\u55b6\u696d\u6240')

    def test_duplicate_vehicle_types_roll_back_the_new_office_index_and_preserve_data(self):
        self.check_duplicate('vehicle_type', self.m.VehicleType, 'Type-A', '\u8eca\u7a2e')


if __name__ == '__main__':
    unittest.main(verbosity=2)
