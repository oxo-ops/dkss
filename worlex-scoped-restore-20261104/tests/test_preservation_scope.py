"""Offline SQLite checks. No live service, sockets, credentials or source data."""
import json
import datetime as dt
import unittest
from sqlalchemy import Column, Integer, LargeBinary, MetaData, String, Table, create_engine, event
from preservation_scope import PRESERVATION_CONTRACT, PreservationScopeError, snapshot
from worlex_restore import digest


class PreservationScopeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.connection = self.engine.connect()
        metadata = MetaData()
        for name in ('company', 'user', 'audit_log', 'push_subscription', 'vehicle'):
            Table(name, metadata, Column('id', Integer, primary_key=True),
                  Column('company_code', String), Column('value', String),
                  Column('extra_settings', LargeBinary))
        for name in ('document_queue_schedule', 'domain_schema_revision'):
            Table(name, metadata, Column('value', String), Column('extra_settings', LargeBinary))
        metadata.create_all(self.connection)
        self.tables = metadata.tables
        for name, table in self.tables.items():
            rows = [{'value': 'before', 'extra_settings': b'\x00\xff'}]
            if 'company_code' in table.c:
                rows = [dict(rows[0], id=i, company_code=company)
                        for i, company in enumerate(('ITC', 'WORLEX', 'OTHER', 'itc', None), 1)]
            self.connection.execute(table.insert(), rows)
        self.statements = []
        event.listen(self.connection, 'before_cursor_execute', self.record)

    def tearDown(self):
        self.connection.close()
        self.engine.dispose()

    def record(self, connection, cursor, statement, parameters, context, many):
        self.statements.append(statement)

    def snap(self, **kwargs):
        return snapshot(self.connection, self.tables, digest, **kwargs)

    def test_contract_is_explicit_serializable_six_table_scope(self):
        contract = json.loads(json.dumps(PRESERVATION_CONTRACT))
        self.assertEqual(contract['version'], 1)
        self.assertEqual(set(contract['tables']), set(self.snap()))
        self.assertEqual(contract['columns'], 'all_reflected_columns')
        self.assertEqual(contract['push_subscription_sequence'], 'exact_unchanged_checked_separately')

    def test_exact_six_queries_and_exact_itc_selection(self):
        baseline = self.snap()
        self.assertEqual(len(self.statements), 6)
        self.assertTrue(all(s.startswith('SELECT ') for s in self.statements))
        self.assertEqual(baseline['company']['count'], 1)
        self.assertEqual(baseline['user']['count'], 1)
        self.assertEqual(baseline['audit_log']['count'], 5)
        self.assertEqual(baseline['push_subscription']['count'], 5)
        self.assertFalse(any('vehicle' in statement for statement in self.statements))

    def test_every_protected_column_change_is_detected(self):
        for name in PRESERVATION_CONTRACT['tables']:
            table = self.tables[name]
            for column in table.c:
                with self.subTest(table=name, column=column.name):
                    baseline = self.snap()
                    transaction = self.connection.begin_nested()
                    value = 900 if column.name == 'id' else b'new' if column.name == 'extra_settings' else 'changed'
                    statement = table.update().values({column.name: value})
                    if 'id' in table.c:
                        statement = statement.where(table.c.id == 1)
                    self.connection.execute(statement)
                    self.assertNotEqual(baseline, self.snap())
                    transaction.rollback()

    def test_unrelated_business_and_non_itc_rows_are_out_of_scope(self):
        baseline = self.snap()
        self.connection.execute(self.tables['vehicle'].update().values(value='changed'))
        for name in ('company', 'user'):
            self.connection.execute(self.tables[name].update().where(self.tables[name].c.id != 1).values(value='changed'))
        self.assertEqual(baseline, self.snap())

    def test_all_global_and_push_rows_are_protected(self):
        for name in ('document_queue_schedule', 'domain_schema_revision', 'push_subscription', 'audit_log'):
            with self.subTest(table=name):
                baseline = self.snap()
                transaction = self.connection.begin_nested()
                statement = self.tables[name].delete()
                if 'id' in self.tables[name].c:
                    statement = statement.where(self.tables[name].c.id == 5)  # NULL company included
                self.connection.execute(statement)
                self.assertNotEqual(baseline, self.snap())
                transaction.rollback()

    def test_audit_import_exclusion_preserves_existing_worlex_audit(self):
        baseline = self.snap()
        audit = self.tables['audit_log']
        self.connection.execute(audit.insert(), dict(id=100, company_code='WORLEX', value='imported', extra_settings=b'new'))
        self.assertNotEqual(baseline, self.snap())
        self.assertEqual(baseline, self.snap(audit_import_ids=[100]))
        self.connection.execute(audit.update().where(audit.c.id == 2).values(value='changed existing WORLEX audit'))
        self.assertNotEqual(baseline, self.snap(audit_import_ids=[100]))

    def test_keyless_duplicate_rows_are_not_collapsed(self):
        baseline = self.snap()
        table = self.tables['document_queue_schedule']
        self.connection.execute(table.insert(), dict(value='before', extra_settings=b'\x00\xff'))
        after = self.snap()
        self.assertEqual(after['document_queue_schedule']['count'], 2)
        self.assertNotEqual(baseline, after)

    def test_invalid_audit_ids_fail_before_any_query(self):
        for ids in (None, '1', {1}, [True], ['1'], [0], [-1], [1, 1]):
            with self.subTest(ids=ids):
                self.statements.clear()
                with self.assertRaises(PreservationScopeError):
                    self.snap(audit_import_ids=ids)
                self.assertEqual(self.statements, [])

    def test_missing_table_or_selector_fails_before_any_query(self):
        for name in PRESERVATION_CONTRACT['tables']:
            tables = dict(self.tables)
            del tables[name]
            with self.assertRaises(PreservationScopeError):
                snapshot(self.connection, tables, digest)
            self.assertEqual(self.statements, [])
        for name in ('company', 'user', 'audit_log'):
            tables = dict(self.tables)
            tables[name] = Table(name, MetaData(), Column('wrong', String))
            with self.assertRaises(PreservationScopeError):
                snapshot(self.connection, tables, digest)
            self.assertEqual(self.statements, [])

    def test_null_changes_in_nonselector_columns_are_protected(self):
        baseline = self.snap()
        self.connection.execute(self.tables['user'].update().where(self.tables['user'].c.id == 1).values(extra_settings=None))
        self.assertNotEqual(baseline, self.snap())
        # extra_settings is deliberately outside the module's known selectors:
        # its earlier per-column test proves no hard-coded value-column list.


# Reuse only the CI-only setup gates, not its existing test methods. This class
# cannot connect unless the pinned isolated PG18 acceptance service is enabled.
import test_restore_postgres as postgres
from worlex_restore import Stop, execute_restore, plan, snapshot as core_snapshot


class PostgreSQLPreservationScopeTests(unittest.TestCase):
    setUpClass = classmethod(postgres.PostgreSQLRestoreAcceptance.setUpClass.__func__)
    setUp = postgres.PostgreSQLRestoreAcceptance.setUp
    existing_push = postgres.PostgreSQLRestoreAcceptance.existing_push
    preserved_audit = postgres.PostgreSQLRestoreAcceptance.preserved_audit

    def test_pg_each_required_projection_mutation_is_rejected(self):
        self.existing_push()
        self.preserved_audit()
        with self.engine.begin() as connection:
            schedule = self.tables['document_queue_schedule']
            revision = self.tables['domain_schema_revision']
            connection.execute(schedule.insert(), {'id': 900000, 'last_company': 'ITC', 'version': 1})
            connection.execute(revision.insert(), {'revision': 'synthetic_preservation_probe', 'applied_at': dt.datetime(2026, 1, 1)})
        changes = {
            'company': ('company_name', 'changed synthetic name'),
            'user': ('password', 'changed synthetic hash'),
            'document_queue_schedule': ('last_company', 'changed'),
            'domain_schema_revision': ('applied_at', dt.datetime(2026, 1, 2)),
            'audit_log': ('detail', 'changed synthetic audit'),
            'push_subscription': ('auth', 'changed synthetic push'),
        }
        with self.engine.connect() as connection:
            for name, (column, value) in changes.items():
                with self.subTest(table=name):
                    baseline = core_snapshot(connection, self.tables)
                    approved = plan(connection, self.data, self.columns, self.policy,
                                    self.counts, self.source_hash, self.approved['generated_identifiers'])
                    transaction = connection.begin_nested()
                    table = self.tables[name]
                    statement = table.update().values({column: value})
                    if name in ('company', 'user'):
                        statement = statement.where(table.c.company_code == 'ITC')
                    changed = connection.execute(statement)
                    self.assertGreater(changed.rowcount, 0)
                    self.assertNotEqual(core_snapshot(connection, self.tables), baseline)
                    with self.assertRaisesRegex(Stop, 'PREFLIGHT_PLAN_CHANGED'):
                        execute_restore(connection, self.data, self.columns, self.policy,
                                        self.counts, self.source_hash, approved)
                    transaction.rollback()

    def test_pg_unrelated_business_change_preserves_plan(self):
        with self.engine.begin() as connection:
            vehicle = self.tables['vehicle']
            connection.execute(vehicle.update().where(vehicle.c.id == 900000).values(chassis_number='CHANGED-SYNTHETIC-UNRELATED'))
        with self.engine.connect() as connection:
            current = plan(connection, self.data, self.columns, self.policy,
                           self.counts, self.source_hash, self.approved['generated_identifiers'])
            self.assertEqual(current, self.approved)
            self.assertEqual(core_snapshot(connection, self.tables), self.before)

    def test_pg_unrelated_primary_key_collision_still_rejected(self):
        imported_id = int(self.data['vehicle'][0]['id'])
        with self.engine.begin() as connection:
            vehicle = self.tables['vehicle']
            connection.execute(vehicle.update().where(vehicle.c.id == 900000).values(id=imported_id))
        with self.engine.connect() as connection:
            self.assertEqual(core_snapshot(connection, self.tables), self.before)
            with self.assertRaisesRegex(Stop, 'PRIMARY_KEY_COLLISION:vehicle'):
                plan(connection, self.data, self.columns, self.policy,
                     self.counts, self.source_hash, self.approved['generated_identifiers'])


if __name__ == '__main__':
    unittest.main()
