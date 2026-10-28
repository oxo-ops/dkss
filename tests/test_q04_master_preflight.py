"""Preflight on synthetic SQLite; no application bootstrap or data repair."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, text
from sqlalchemy.exc import DBAPIError

from tools.q04_master_preflight import diagnose, read_only_connection


MASTERS = ('office', 'vehicle_type', 'delivery_place', 'license_type', 'patrol_content_type')
REFERENCES = {
    'vehicle': ('office', 'type'), 'user': ('office',),
    'driver': ('office', 'licenses_json'),
    'vehicle_type_import_mapping': ('vehicle_type_name',),
    'patrol_result': ('office', 'delivery_place', 'content_type'),
    'checklist_result': ('target_office',), 'news': ('target_type', 'target_value'),
    'master_display_order': ('kind', 'ordered_ids_json'),
    'vehicle_maintenance_record': ('invoice_details_json',),
}


def fixture(engine, schema=None):
    metadata = MetaData(schema=schema)
    company = Table('company', metadata, Column('company_code', String, primary_key=True))
    tables = {}
    for name in MASTERS + tuple(REFERENCES):
        columns = ('name',) if name in MASTERS else REFERENCES[name]
        tables[name] = Table(name, metadata, Column('id', Integer, primary_key=True),
                             Column('company_code', String),
                             *(Column(c, String) for c in columns))
    metadata.create_all(engine)
    prefix = '"' + schema + '".' if schema else ''
    with engine.begin() as c:
        c.execute(company.insert(), [{'company_code': 'A'}, {'company_code': 'B'}])
        for name in MASTERS:
            c.execute(tables[name].insert(), [dict(id=1, company_code='A', name='Valid'),
                                             dict(id=2, company_code='B', name='Foreign-only')])
            c.execute(text(f'CREATE UNIQUE INDEX uq_{name}_company_name ON {prefix}"{name}" (company_code, name)'))
        for name, columns in REFERENCES.items():
            row = dict(id=1, company_code='A', **{col: 'Valid' for col in columns})
            if name == 'driver': row['licenses_json'] = '[{"type":"Valid"}]'
            if name == 'news': row.update(target_type='office', target_value='Valid')
            if name == 'master_display_order': row.update(kind='offices', ordered_ids_json='[1]')
            if name == 'vehicle_maintenance_record': row['invoice_details_json'] = '{}'
            c.execute(tables[name].insert(), row)


class MasterPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'q04_snapshot.sqlite'
        self.url = 'sqlite:///' + self.path.as_posix()
        self.engine = create_engine(self.url)
        self.addCleanup(self.engine.dispose)
        fixture(self.engine)

    def sql(self, statement):
        with self.engine.begin() as c: c.execute(text(statement))

    def report(self, limit=3):
        return diagnose(self.url, self.path.name, sample_limit=limit)

    def test_clean_snapshot_and_empty_optional_assignments(self):
        self.sql("UPDATE vehicle SET office='', type=NULL")
        self.assertEqual(self.report()['status'], 'ok')

    def test_all_five_duplicates_and_bad_indexes_reported_without_file_changes(self):
        for table in MASTERS:
            self.sql(f'DROP INDEX uq_{table}_company_name')
            self.sql(f'CREATE INDEX uq_{table}_company_name ON {table} (company_code, name)')
            self.sql(f"INSERT INTO {table}(id,company_code,name) VALUES(3,'A','Valid')")
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        result = self.report(limit=1)
        self.assertTrue(result['complete'])
        self.assertEqual(result['status'], 'issues')
        self.assertEqual({f['table'] for f in result['findings'] if f['code'] == 'duplicate_name'}, set(MASTERS))
        self.assertEqual({f['table'] for f in result['findings'] if f['code'] == 'index_definition'}, set(MASTERS))
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertTrue(all(len(f.get('samples', [])) <= 1 for f in result['findings']))

    def test_foreign_company_names_do_not_satisfy_all_five_master_references(self):
        self.sql("UPDATE vehicle SET office='Foreign-only', type='Foreign-only'")
        self.sql("UPDATE patrol_result SET delivery_place='Foreign-only',content_type='Foreign-only'")
        self.sql("UPDATE driver SET licenses_json='[{\"type\":\"Foreign-only\"}]'")
        errors = [f for f in self.report()['findings'] if f['code'] == 'missing_reference']
        self.assertEqual({f['master'] for f in errors}, set(MASTERS))
        self.assertTrue(all(f['samples'][0]['company_code'] == 'A' for f in errors))

    def test_historical_cost_office_is_observation_not_current_reference_error(self):
        self.sql('UPDATE vehicle_maintenance_record SET invoice_details_json=\'{"cost_attribution":{"office":"Historical-only"}}\'')
        result = self.report()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([f['severity'] for f in result['findings']], ['info'])
        self.assertEqual(result['findings'][0]['code'], 'historical_name')

    def test_office_news_requires_target_but_other_news_does_not(self):
        self.sql("UPDATE news SET target_value='' WHERE target_type='office'")
        self.assertIn('missing_reference', [f['code'] for f in self.report()['findings']])
        self.sql("UPDATE news SET target_type='all'")
        self.assertEqual(self.report()['status'], 'ok')

    def test_malformed_license_and_order_json_are_not_silently_ignored(self):
        for raw in ('not-json', '{}', '[3]', '[{"type":3}]'):
            with self.subTest(raw=raw), self.engine.begin() as c:
                c.execute(text('UPDATE driver SET licenses_json=:raw'), {'raw': raw})
            self.assertIn('invalid_json', [f['code'] for f in self.report()['findings']])
        self.sql("UPDATE master_display_order SET ordered_ids_json='[2,2]'")
        self.assertIn('invalid_order', [f['code'] for f in self.report()['findings']])

    def test_missing_schema_and_columns_are_incomplete_not_clean(self):
        self.sql('DROP TABLE patrol_result')
        self.sql('ALTER TABLE driver RENAME COLUMN licenses_json TO old_licenses')
        result = self.report()
        self.assertFalse(result['complete'])
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('schema_missing', [f['code'] for f in result['findings']])

    def test_partial_wrong_column_and_missing_index_details(self):
        for suffix in ('(company_code, id)', "(company_code, name) WHERE name <> 'Hidden'"):
            self.sql('DROP INDEX uq_office_company_name')
            self.sql('CREATE UNIQUE INDEX uq_office_company_name ON office ' + suffix)
            finding = next(f for f in self.report()['findings'] if f['code'] == 'index_definition')
            self.assertEqual(finding['index'], 'uq_office_company_name')
            self.assertIn('actual', finding)
            self.assertIn('expected', finding)
        self.sql('DROP INDEX uq_office_company_name')
        self.assertIn('index_missing', [f['code'] for f in self.report()['findings']])

    def test_read_only_connection_rejects_write(self):
        with read_only_connection(self.url, self.path.name) as c:
            self.assertEqual(c.scalar(text('PRAGMA query_only')), 1)
            with self.assertRaises(DBAPIError): c.execute(text("DELETE FROM office"))
        self.assertEqual(self.report()['status'], 'ok')

    def test_target_guards_do_not_create_database_or_fall_back_to_app_url(self):
        missing = Path(self.temp.name) / 'missing.sqlite'
        with self.assertRaises(ValueError): diagnose('sqlite:///' + missing.as_posix(), missing.name)
        self.assertFalse(missing.exists())
        for url in ('postgresql://q04@example.com/q04_copy',
                    'postgresql://q04@127.0.0.1/production',
                    'postgresql://q04@127.0.0.1/q04_copy?host=example.com'):
            with self.subTest(url=url), self.assertRaises(ValueError): diagnose(url, 'q04_copy')
        env = dict(os.environ, DATABASE_URL=self.url)
        env.pop('Q04_PREFLIGHT_DATABASE_URL', None)
        run = subprocess.run([sys.executable, 'tools/q04_master_preflight.py',
            '--expected-database', self.path.name, '--confirm-nonproduction'],
            capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 2)
        self.assertNotIn(str(self.path), run.stderr)

    def test_cli_json_exit_status_for_clean_and_invalid_data(self):
        env = dict(os.environ, Q04_PREFLIGHT_DATABASE_URL=self.url)
        run = subprocess.run([sys.executable, 'tools/q04_master_preflight.py',
            '--expected-database', self.path.name, '--confirm-nonproduction'],
            capture_output=True, text=True, encoding='utf-8', env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)['status'], 'ok')
        self.sql("UPDATE vehicle SET office='Missing'")
        run = subprocess.run([sys.executable, 'tools/q04_master_preflight.py',
            '--expected-database', self.path.name, '--confirm-nonproduction'],
            capture_output=True, text=True, encoding='utf-8', env=env)
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(json.loads(run.stdout)['status'], 'issues')
