"""Explicit additive generation migration; business/person/history data is immutable."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError

from dkss_app.master_generations import FIELD, KINDS, upgrade_storage, validate_storage


def legacy_fixture(engine, schema=None):
    metadata = MetaData(schema=schema)
    for name in list(KINDS.values()) + ['person_history_control']:
        Table(name, metadata, Column('id', Integer, primary_key=True),
              Column('company_code', String(50)), Column('name', String(100)),
              Column('person_uuid', String(36)), Column('history_json', String))
    metadata.create_all(engine)
    with engine.begin() as c:
        for table in metadata.tables.values():
            c.execute(table.insert(), [dict(id=10, company_code='A', name='Same name',
                person_uuid='f4edddc7-f906-466e-9d50-6fd70d870597', history_json='{"preserve":1}'),
                dict(id=20, company_code='B', name='Same name', person_uuid=None, history_json='{}')])


class StorageCases:
    schema = None

    def rows(self, generations=False):
        with self.engine.connect() as c:
            result = {}
            for name in list(KINDS.values()) + ['person_history_control']:
                table = Table(name, MetaData(), schema=self.schema, autoload_with=c)
                columns = [v for v in table.c if generations or v.name != FIELD]
                result[name] = [tuple(row) for row in c.execute(table.select().with_only_columns(*columns).order_by(table.c.id))]
            return result

    def columns(self):
        return {name: [c['name'] for c in inspect(self.engine).get_columns(name, schema=self.schema)]
                for name in KINDS.values()}

    def test_additive_idempotent_upgrade_preserves_ids_names_people_and_history(self):
        before = self.rows()
        report = upgrade_storage(self.engine, self.schema)
        self.assertTrue(all(r == {'added_column': True, 'assigned': 2} for r in report.values()))
        self.assertEqual(self.rows(), before)
        generations = self.rows(generations=True)
        repeat = upgrade_storage(self.engine, self.schema)
        self.assertTrue(all(r == {'added_column': False, 'assigned': 0} for r in repeat.values()))
        self.assertEqual(self.rows(generations=True), generations)
        with self.engine.connect() as c: validate_storage(c, self.schema)

    def test_readiness_check_rejects_legacy_storage_without_migrating(self):
        before, columns = self.rows(), self.columns()
        with self.engine.connect() as c, self.assertRaisesRegex(RuntimeError, 'migration'):
            validate_storage(c, self.schema)
        self.assertEqual(self.columns(), columns)
        self.assertEqual(self.rows(), before)

    def test_failure_after_first_table_rolls_back_columns_and_metadata_together(self):
        before, columns = self.rows(), self.columns()
        def fail(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith('ALTER TABLE') and 'vehicle_type' in statement:
                raise RuntimeError('Synthetic failure after first master migration')
        event.listen(self.engine, 'before_cursor_execute', fail)
        try:
            with self.assertRaisesRegex(RuntimeError, 'Synthetic failure'):
                upgrade_storage(self.engine, self.schema)
        finally:
            event.remove(self.engine, 'before_cursor_execute', fail)
        self.assertEqual(self.columns(), columns)
        self.assertEqual(self.rows(), before)

    def test_invalid_existing_generation_is_not_silently_regenerated(self):
        upgrade_storage(self.engine, self.schema)
        with self.engine.begin() as c:
            table = Table('vehicle_type', MetaData(), schema=self.schema, autoload_with=c)
            c.execute(table.update().where(table.c.id == 10).values({FIELD: 'invalid-generation'}))
        before = self.rows(generations=True)
        with self.assertRaisesRegex(RuntimeError, 'Invalid existing master generation'):
            upgrade_storage(self.engine, self.schema)
        self.assertEqual(self.rows(generations=True), before)

    def test_unknown_legacy_metadata_is_rejected_until_explicit_upgrade(self):
        upgrade_storage(self.engine, self.schema)
        with self.engine.begin() as c:
            table = Table('office', MetaData(), schema=self.schema, autoload_with=c)
            c.execute(table.update().where(table.c.id == 10).values({FIELD: None}))
        before = self.rows(generations=True)
        with self.engine.connect() as c, self.assertRaisesRegex(RuntimeError, 'missing'):
            validate_storage(c, self.schema)
        self.assertEqual(self.rows(generations=True), before)
        result = upgrade_storage(self.engine, self.schema)
        self.assertEqual(result['office']['assigned'], 1)
        self.assertTrue(all(v['assigned'] == 0 for k, v in result.items() if k != 'office'))

    def test_custom_trigger_is_rejected_before_any_metadata_or_business_update(self):
        with self.engine.begin() as c:
            if self.engine.dialect.name == 'sqlite':
                c.exec_driver_sql("CREATE TRIGGER unexpected_master_trigger AFTER UPDATE ON office "
                    "BEGIN UPDATE office SET name='Unexpected rewrite' WHERE id=NEW.id; END")
            else:
                c.exec_driver_sql(f'CREATE TRIGGER unexpected_master_trigger BEFORE UPDATE ON "{self.schema}".office '
                    'FOR EACH ROW EXECUTE FUNCTION pg_catalog.suppress_redundant_updates_trigger()')
        before, columns = self.rows(), self.columns()
        with self.assertRaisesRegex(RuntimeError, 'DBA review'):
            upgrade_storage(self.engine, self.schema)
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.columns(), columns)


class SQLiteMasterGenerationStorageTests(StorageCases, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'q04_generations.sqlite'
        self.url = 'sqlite:///' + self.path.as_posix()
        self.engine = create_engine(self.url, connect_args={'timeout': 0.05})
        self.addCleanup(self.engine.dispose)
        legacy_fixture(self.engine)

    def test_existing_writer_blocks_migration_without_partial_changes(self):
        columns, before = self.columns(), self.rows()
        with self.engine.connect() as writer:
            writer.exec_driver_sql('BEGIN IMMEDIATE')
            with self.assertRaises(OperationalError) as failure:
                upgrade_storage(self.engine)
            self.assertEqual(failure.exception.orig.sqlite_errorcode & 255, 5)
            writer.rollback()
        self.assertEqual(self.columns(), columns)
        self.assertEqual(self.rows(), before)

    def test_explicit_cli_and_readonly_check_do_not_fall_back_or_create_db(self):
        command = [sys.executable, 'tools/upgrade_master_generations.py',
                   '--expected-database', self.path.name, '--confirm-nonproduction']
        env = dict(os.environ, DATABASE_URL=self.url)
        env.pop('Q04_MASTER_GENERATION_DATABASE_URL', None)
        missing = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)
        env['Q04_MASTER_GENERATION_DATABASE_URL'] = self.url
        upgraded = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
        self.assertEqual(json.loads(upgraded.stdout)['office']['assigned'], 2)
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        checked = subprocess.run(command + ['--check'], env=env, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        from tools.upgrade_master_generations import migration_engine
        absent = Path(self.temp.name) / 'absent.sqlite'
        with self.assertRaises(ValueError): migration_engine('sqlite:///' + absent.as_posix(), absent.name)
        self.assertFalse(absent.exists())
