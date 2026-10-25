"""Application lifecycle, registration parity, and isolation contracts."""
import ast
import builtins
import json
import os
from pathlib import Path
import subprocess
import symtable
import sys
import unittest
from unittest.mock import patch

from sqlalchemy.engine import Engine
from dkss_app import create_app
from dkss_app.contracts import application_contract
from dkss_app.extensions import db
from dkss_app.models import Vehicle, VehiclePeriodicInspectionRecord

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {'SECRET_KEY': 'isolated-only', 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
          'TESTING': True, 'WTF_CSRF_ENABLED': False, 'S3_BUCKET_NAME': '',
          'RATELIMIT_ENABLED': False}


class ApplicationFoundationTests(unittest.TestCase):
    def factory(self, **values):
        with patch.dict(os.environ, {'RENDER': '', 'AWS_EC2_METADATA_DISABLED': 'true'}):
            return create_app(CONFIG | values)

    def test_package_and_wsgi_import_do_not_connect_or_initialize_database(self):
        script = '''
from unittest.mock import patch
from sqlalchemy.engine import Engine
with patch.object(Engine, 'connect', side_effect=AssertionError('unexpected DB connection')):
    import dkss_app
    import app
    assert len(list(app.app.url_map.iter_rules())) > 100
'''
        env = dict(os.environ, SECRET_KEY='isolated', DATABASE_URL='sqlite:///:memory:',
                   S3_BUCKET_NAME='', RENDER='', AWS_EC2_METADATA_DISABLED='true')
        env.pop('ITC_INITIAL_PASSWORD', None)
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_factory_does_not_connect_database(self):
        with patch.object(Engine, 'connect', side_effect=AssertionError('unexpected DB connection')):
            self.factory()

    def test_all_routes_schema_indexes_hooks_and_filters_match_original(self):
        expected = json.loads((ROOT / 'tests/fixtures/application_contract.json').read_text(encoding='utf-8'))
        self.assertEqual(application_contract(self.factory(RATELIMIT_ENABLED=True), db), expected)

    def test_factories_have_separate_config_extensions_and_engines(self):
        first = self.factory(SECRET_KEY='first', VAPID_PUBLIC_KEY='first-key')
        second = self.factory(SECRET_KEY='second', VAPID_PUBLIC_KEY='second-key')
        self.assertIsNot(first.extensions['dkss'], second.extensions['dkss'])
        with first.app_context():
            first_engine = db.engine
            self.assertEqual(first.config['VAPID_PUBLIC_KEY'], 'first-key')
        with second.app_context():
            self.assertIsNot(db.engine, first_engine)
            self.assertEqual(second.config['VAPID_PUBLIC_KEY'], 'second-key')

    def test_schema_initialization_is_an_explicit_cli_command(self):
        app = self.factory()
        with patch.dict(os.environ, {'ITC_INITIAL_PASSWORD': 'Isolated-Only-742!'}):
            result = app.test_cli_runner().invoke(args=['init-db'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('DATABASE_INITIALIZED', result.output)
        with app.app_context():
            self.assertIn('vehicle', db.inspect(db.engine).get_table_names())
            db.session.remove()
            db.engine.dispose()

    def test_inspection_sync_dispatches_once_in_each_application(self):
        first, second = self.factory(), self.factory()
        for index, app in enumerate([first, second, first]):
            with app.app_context():
                db.create_all()
                service = app.extensions['inspection_plan_sync']
                with patch.object(service, 'sync_pending', wraps=service.sync_pending) as sync:
                    row = Vehicle(company_code='TEST', chassis_number='TEST-' + str(index))
                    db.session.add(row)
                    db.session.flush()
                    record = VehiclePeriodicInspectionRecord(company_code='TEST', vehicle_record_id=row.id,
                        inspection_type='3month', inspection_date='2026-09-01',
                        source_draft_id='isolated', source_record_index=row.id, created_by_username='test')
                    db.session.add(record)
                    db.session.commit()
                    self.assertEqual(sync.call_count, 1)
                db.session.remove()
        for app in [first, second]:
            with app.app_context():
                db.engine.dispose()

    def test_implementation_does_not_depend_on_compatibility_entrypoint_or_globals(self):
        for path in (ROOT / 'dkss_app').glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertNotIn('app', [a.name for a in node.names], str(path))
                if isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, 'app', str(path))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotEqual(node.func.id, 'globals', str(path))

    def test_no_undefined_global_dependencies_in_package(self):
        for path in (ROOT / 'dkss_app').glob('*.py'):
            table = symtable.symtable(path.read_text(encoding='utf-8'), str(path), 'exec')
            defined = {s.get_name() for s in table.get_symbols()
                       if s.is_assigned() or s.is_imported() or s.is_namespace()}
            defined |= set(dir(builtins)) | {'__name__', '__file__'}
            def check(scope):
                for child in scope.get_children():
                    for symbol in child.get_symbols():
                        if symbol.is_global() and symbol.is_referenced():
                            self.assertIn(symbol.get_name(), defined,
                                          f'{path.name}:{child.get_lineno()} {symbol.get_name()}')
                    check(child)
            check(table)
