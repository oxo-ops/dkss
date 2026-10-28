"""Q04 investigation: actual routes, PostgreSQL, disposable private schema only.

These are desired integrity assertions, not expected failures. Failures are
evidence to investigate. A holds a real transaction while B either reads stale
data or waits on A's PostgreSQL row lock. SQL and lock semantics are unchanged.
"""
import json
import os
import re
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch


class MasterConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine, event, text
        from sqlalchemy.engine import make_url
        url = os.environ.get('Q04_POSTGRES_TEST_URL', '')
        if not url:
            if os.environ.get('Q04_REQUIRE_POSTGRES') == '1':
                raise RuntimeError('Q04_POSTGRES_TEST_URL is required; no SQLite fallback')
            raise unittest.SkipTest('Dedicated disposable PostgreSQL is required')
        parsed = make_url(url)
        if (parsed.get_backend_name() != 'postgresql'
                or parsed.host not in ('localhost', '127.0.0.1', '::1')
                or parsed.database != 'dkss_q04_ci'):
            raise RuntimeError('Only loopback database dkss_q04_ci is allowed')
        cls.schema = 'q04_master_' + uuid.uuid4().hex
        assert re.fullmatch(r'q04_master_[0-9a-f]{32}', cls.schema)
        cls.admin_engine = create_engine(url, isolation_level='AUTOCOMMIT')
        cls.addClassCleanup(cls.admin_engine.dispose)
        with cls.admin_engine.connect() as connection:
            if connection.scalar(text('SELECT current_database()')) != 'dkss_q04_ci':
                raise RuntimeError('Unexpected database')
            cls.server_version = connection.scalar(text('SHOW server_version'))
            connection.execute(text('CREATE SCHEMA "' + cls.schema + '"'))
        cls.addClassCleanup(cls.drop_schema)
        from dkss_app import create_app, models
        from dkss_app.extensions import db, limiter
        cls.db, cls.m = db, models
        env = {'SECRET_KEY': 'q04-disposable-only', 'DATABASE_URL': url,
               'ITC_INITIAL_PASSWORD': 'Q04-Disposable-Only-742!',
               'RENDER': '', 'MFA_ENABLED': 'false', 'OPENAI_API_KEY': '',
               'SMTP_HOST': '', 'S3_BUCKET_NAME': '', 'VAPID_PRIVATE_KEY': '',
               'VAPID_PUBLIC_KEY': '', 'AWS_EC2_METADATA_DISABLED': 'true',
               'RATELIMIT_STORAGE_URI': 'memory://'}
        with patch.dict(os.environ, env):
            cls.app = create_app({'TESTING': True, 'MFA_ENABLED': False,
                'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_ENGINE_OPTIONS': {
                    'pool_size': 8, 'max_overflow': 0, 'pool_timeout': 10,
                    'connect_args': {'options': '-csearch_path=' + cls.schema
                        + ' -cstatement_timeout=15000 -clock_timeout=10000'}}})
            with cls.app.app_context():
                cls.engine = db.engine
                cls.addClassCleanup(cls.engine.dispose)
                from dkss_app.database import initialize_database
                initialize_database()
                with cls.engine.connect() as connection:
                    assert connection.scalar(text('SELECT current_schema()')) == cls.schema
                    cls.isolation = connection.scalar(text('SHOW transaction_isolation'))
        limiter.enabled = False
        cls.local = threading.local()
        cls.pid_lock = threading.Lock()
        cls.pids = set()
        def observe(connection, cursor, statement, parameters, context, executemany):
            if getattr(cls.local, 'worker', None):
                with cls.pid_lock:
                    cls.pids.add(cursor.connection.get_backend_pid())
        event.listen(cls.engine, 'before_cursor_execute', observe)
        cls.addClassCleanup(event.remove, cls.engine, 'before_cursor_execute', observe)
        print('Q04_POSTGRES_SERVER:', cls.server_version, 'isolation:', cls.isolation, flush=True)

    @classmethod
    def drop_schema(cls):
        from sqlalchemy import text
        with cls.admin_engine.connect() as connection:
            connection.execute(text('DROP SCHEMA "' + cls.schema + '" CASCADE'))

    def setUp(self):
        # No retained app context: every request owns and tears down its session.
        self.company = 'A_' + uuid.uuid4().hex[:16]
        self.other = 'B_' + uuid.uuid4().hex[:16]
        self.stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        m = self.m
        with self.app.app_context():
            for code in (self.company, self.other):
                self.db.session.add(m.Company(company_code=code, company_name=code, active=True))
                self.db.session.add(m.User(company_code=code, username='admin', role='admin',
                    password='unused', last_name='Synthetic', password_changed_at=self.stamp,
                    office='Office-A'))
                self.db.session.add(m.Office(company_code=code, name='Office-A'))
                self.db.session.add(m.VehicleType(company_code=code, name='Type-A'))
                self.db.session.add(m.Vehicle(company_code=code, chassis_number=code,
                    office='Office-A', type='Type-A'))
                self.db.session.add(m.Driver(company_code=code, employee_id='driver',
                    name='Synthetic', office='Office-A'))
                self.db.session.add(m.VehicleTypeImportMapping(company_code=code,
                    excel_value='Synthetic', vehicle_type_name='Type-A'))
            self.db.session.flush()
            self.ids = {}
            for kind, model in (('offices', m.Office), ('vehicle-types', m.VehicleType)):
                row = model.query.filter_by(company_code=self.company).one()
                self.ids[kind] = row.id
                self.db.session.add(m.MasterDisplayOrder(company_code=self.company,
                    kind=kind, ordered_ids_json=json.dumps([row.id])))
            self.db.session.commit()
        self.foreign_before = self.snapshot(self.other)

    def client(self, company=None):
        client = self.app.test_client()
        with client.session_transaction() as state:
            state.update(company_code=company or self.company, username='admin',
                         role='admin', password_changed_at=self.stamp)
        return client

    def submit(self, label, client, path, name=None):
        self.local.worker = label
        try:
            try:
                response = client.post(path, data={} if name is None else {'name': name})
                try:
                    return {'status': response.status_code, 'location': response.location}
                finally:
                    response.close()
            except Exception as error:
                # Return errors as evidence, never confuse them with a 409 response.
                return {'error': type(error).__name__, 'message': str(error)[:1000]}
        finally:
            self.local.worker = None

    def snapshot(self, company):
        with self.app.app_context():
            m = self.m
            rows = {}
            for model in (m.Office, m.VehicleType, m.Vehicle, m.User, m.Driver,
                          m.VehicleTypeImportMapping, m.MasterDisplayOrder, m.AuditLog):
                rows[model.__tablename__] = [
                    {c.name: getattr(row, c.name) for c in model.__table__.columns}
                    for row in model.query.filter_by(company_code=company).order_by(model.id)]
            return rows

    def race(self, kind, first, second, gate, check_foreign=True):
        from sqlalchemy import event, text
        table = 'office' if kind == 'offices' else 'vehicle_type'
        a_read, b_read = threading.Event(), threading.Event()
        release_a, release_b = threading.Event(), threading.Event()
        selected = threading.Barrier(2, timeout=10)
        fired = set()
        read_pids = {}
        lock_wait = False
        def master_select(statement):
            sql = ' '.join(statement.lower().split())
            return sql.startswith('select ') and (' from ' + table + ' ') in sql

        def before_read(connection, cursor, statement, parameters, context, executemany):
            label = getattr(self.local, 'worker', None)
            if label and master_select(statement):
                read_pids.setdefault(label, cursor.connection.get_backend_pid())

        def hook(connection, cursor, statement, parameters, context, executemany):
            label = getattr(self.local, 'worker', None)
            if not label or label in fired:
                return
            sql = ' '.join(statement.lower().split())
            if gate == 'insert':
                match = sql.startswith('insert into ' + table + ' ')
            elif gate == 'update':
                # Related data writes start after duplicate-name prechecks.
                match = sql.startswith('update driver ' if kind == 'offices' else 'update vehicle ')
            else:
                match = sql.startswith('select ') and (' from ' + table + ' ') in sql
            if not match:
                return
            fired.add(label)
            if gate in ('insert', 'update'):
                selected.wait()
            else:
                # A holds its transaction open while B either reads the old
                # value (unprotected code) or waits on A's real PostgreSQL lock.
                (a_read if label == 'A' else b_read).set()
                if not (release_a if label == 'A' else release_b).wait(20):
                    raise RuntimeError('Schedule timeout: reader was not released')
        event_name = 'after_cursor_execute' if gate == 'read' else 'before_cursor_execute'
        event.listen(self.engine, event_name, hook)
        if gate == 'read':
            event.listen(self.engine, 'before_cursor_execute', before_read)
        with self.pid_lock:
            self.pids.clear()
        a, b = self.client(first.get('company')), self.client(second.get('company'))
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                if gate == 'read':
                    fa = executor.submit(self.submit, 'A', a, first['path'], first.get('name'))
                    try:
                        if not a_read.wait(10):
                            raise RuntimeError('Schedule timeout: A never read the master')
                        fb = executor.submit(self.submit, 'B', b, second['path'], second.get('name'))
                        deadline = time.monotonic() + 10
                        while not b_read.is_set():
                            if time.monotonic() > deadline:
                                raise RuntimeError('B neither read nor waited on A')
                            pid = read_pids.get('B')
                            if pid:
                                with self.engine.connect() as connection:
                                    blockers = connection.scalar(text('SELECT pg_blocking_pids(:pid)'),
                                                                 {'pid': pid})
                                if read_pids['A'] in blockers:
                                    lock_wait = True
                                    break
                            time.sleep(0.01)
                        release_a.set()
                        ra = fa.result(timeout=20)
                    finally:
                        release_a.set()
                        release_b.set()
                    rb = fb.result(timeout=20)
                else:
                    fa = executor.submit(self.submit, 'A', a, first['path'], first.get('name'))
                    fb = executor.submit(self.submit, 'B', b, second['path'], second.get('name'))
                    ra, rb = fa.result(timeout=20), fb.result(timeout=20)
        finally:
            release_a.set()
            release_b.set()
            event.remove(self.engine, event_name, hook)
            if gate == 'read':
                event.remove(self.engine, 'before_cursor_execute', before_read)
        state = self.snapshot(self.company)
        evidence = {'test': self.id(), 'schedule': gate, 'responses': [ra, rb],
                    'postgres_backends': sorted(self.pids), 'lock_wait_observed': lock_wait,
                    'state': state}
        print('Q04_EVIDENCE:', json.dumps(evidence, ensure_ascii=True, default=str), flush=True)
        self.assertEqual(fired, {'A', 'B'}, 'Both requests must reach the intended SQL gate')
        self.assertGreaterEqual(len(self.pids), 2, 'Two PostgreSQL backends are required')
        if check_foreign:
            self.assertEqual(self.snapshot(self.other), self.foreign_before)
        return ra, rb, state

    def run_case(self, kind, scenario):
        model = self.m.Office if kind == 'offices' else self.m.VehicleType
        table, column = model.__tablename__, 'office' if kind == 'offices' else 'type'
        base = '/master/' + kind
        edit = base + '/' + str(self.ids[kind]) + '/edit'
        delete = base + '/' + str(self.ids[kind]) + '/delete'
        if scenario == 'schema':
            from sqlalchemy import inspect
            with self.app.app_context():
                inspector = inspect(self.engine)
                indexes = inspector.get_indexes(table)
                uniques = inspector.get_unique_constraints(table)
            found = any(set(x.get('column_names', [])) == {'company_code', 'name'}
                        and x.get('unique', True) for x in indexes + uniques)
            self.assertTrue(found, table + ': missing company/name uniqueness: ' + repr(indexes + uniques))
            return
        if scenario in ('create', 'companies'):
            a = {'path': base + '/new', 'name': 'Concurrent-New'}
            b = dict(a)
            if scenario == 'companies':
                b['company'] = self.other
                ra, rb, state = self.race(kind, a, b, 'insert', check_foreign=False)
                foreign = self.snapshot(self.other)
                self.assertEqual([ra.get('status'), rb.get('status')], [302, 302])
                self.assertEqual(sum(r['name'] == 'Concurrent-New' for r in state[table]), 1)
                self.assertEqual(sum(r['name'] == 'Concurrent-New' for r in foreign[table]), 1)
                foreign[table] = [r for r in foreign[table] if r['name'] != 'Concurrent-New']
                self.assertEqual(foreign, self.foreign_before)
                return
            ra, rb, state = self.race(kind, a, b, 'insert')
            self.assertEqual(sum(r['name'] == 'Concurrent-New' for r in state[table]), 1)
            self.assertCountEqual([ra.get('status'), rb.get('status')], [302, 409])
            return
        if scenario == 'target':
            with self.app.app_context():
                second = model(company_code=self.company, name='Second')
                self.db.session.add(second)
                self.db.session.flush()
                second_id = second.id
                self.db.session.add(self.m.Vehicle(company_code=self.company,
                    chassis_number=self.company + '-2', **{column: 'Second'}))
                self.db.session.commit()
            ra, rb, state = self.race(kind,
                {'path': edit, 'name': 'Same-Target'},
                {'path': base + '/' + str(second_id) + '/edit', 'name': 'Same-Target'}, 'update')
            self.assertEqual(sum(r['name'] == 'Same-Target' for r in state[table]), 1)
            self.assertCountEqual([ra.get('status'), rb.get('status')], [302, 409])
            by_id = {r['id']: r['name'] for r in state[table]}
            expected = [by_id[self.ids[kind]], by_id[second_id]]
            self.assertEqual([r[column] for r in state['vehicle']], expected)
            self.assert_related(state, kind, by_id[self.ids[kind]])
            return
        if scenario == 'rename':
            first, second = {'path': edit, 'name': 'Renamed-A'}, {'path': edit, 'name': 'Renamed-B'}
        elif scenario == 'rename_delete':
            first, second = {'path': edit, 'name': 'Renamed-A'}, {'path': delete}
        elif scenario == 'delete_rename':
            first, second = {'path': delete}, {'path': edit, 'name': 'Renamed-B'}
        else:
            first, second = {'path': delete}, {'path': delete}
        ra, rb, state = self.race(kind, first, second, 'read')
        self.assertTrue(all(r.get('status') in (302, 409) for r in (ra, rb)), repr([ra, rb]))
        if scenario == 'rename':
            self.assertEqual(len(state[table]), 1)
            self.assert_related(state, kind, state[table][0]['name'])
        else:
            self.assertEqual(state[table], [])
            self.assert_related(state, kind, '')
            saved = next(r for r in state['master_display_order'] if r['kind'] == kind)
            self.assertNotIn(self.ids[kind], json.loads(saved['ordered_ids_json']))
            action = 'office_deleted' if kind == 'offices' else 'vehicle_type_deleted'
            self.assertEqual(sum(r['action'] == action for r in state['audit_log']), 1)

    def assert_related(self, state, kind, expected):
        if kind == 'offices':
            for table in ('driver', 'user', 'vehicle'):
                self.assertEqual(state[table][0]['office'], expected, table)
        else:
            self.assertEqual(state['vehicle'][0]['type'], expected)
            mappings = state['vehicle_type_import_mapping']
            if expected:
                self.assertEqual([r['vehicle_type_name'] for r in mappings], [expected])
            else:
                self.assertEqual(mappings, [])


def case(kind, scenario):
    def check(self):
        self.run_case(kind, scenario)
    return check


for _kind in ('offices', 'vehicle-types'):
    for _scenario in ('schema', 'create', 'companies', 'target', 'rename',
                      'rename_delete', 'delete_rename', 'delete_delete'):
        setattr(MasterConcurrencyTests, 'test_' + _kind.replace('-', '_') + '_' + _scenario,
                case(_kind, _scenario))


if __name__ == '__main__':
    unittest.main(verbosity=2)
