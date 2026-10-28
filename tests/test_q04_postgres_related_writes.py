"""Actual related-record writes racing master renames/deletes, private PG only.

Start a related writer, hold it after reading its selected master, then attempt
the master mutation on another backend. A protected reader may block the master
writer; otherwise let the master finish before resuming the related writer.
No SQL, locks, validation results, or commit behavior are mocked.
"""
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event, text

import test_q04_postgres_master_concurrency as concurrency


class RelatedMasterWriteTests(unittest.TestCase):
    setUpClass = classmethod(concurrency.MasterConcurrencyTests.setUpClass.__func__)
    drop_schema = classmethod(concurrency.MasterConcurrencyTests.drop_schema.__func__)
    client = concurrency.MasterConcurrencyTests.client
    snapshot = concurrency.MasterConcurrencyTests.snapshot

    def setUp(self):
        concurrency.MasterConcurrencyTests.setUp(self)
        m = self.m
        with self.app.app_context():
            m.Company.query.filter(m.Company.company_code.in_([self.company, self.other])).update(
                {'vehicle_limit': 100}, synchronize_session=False)
            vehicle = m.Vehicle(company_code=self.company, chassis_number='REL-EDIT-' + self.company,
                                office='', type='')
            driver = m.Driver(company_code=self.company, employee_id='rel-edit',
                              name='Synthetic', office='', role='user')
            user = m.User(company_code=self.company, username='rel-edit', password='unused',
                          last_name='Synthetic', role='user', office='', password_changed_at=self.stamp)
            self.db.session.add_all([vehicle, driver, user])
            self.db.session.commit()
            self.vehicle_id, self.driver_id = vehicle.id, driver.id
        self.foreign_before = self.snapshot(self.other)

    def related_request(self, writer, kind=None):
        office = 'Office-A' if kind in (None, 'offices') else ''
        vehicle_type = 'Type-A' if kind in (None, 'vehicle-types') else ''
        if writer.startswith('vehicle_'):
            chassis = ('REL-NEW-' if writer.endswith('new') else 'REL-EDIT-') + self.company
            data = {'chassis_number': chassis, 'office': office, 'type': vehicle_type,
                    'vehicle_form_action': 'save', 'gross_vehicle_weight': '1000', 'max_payload': '500'}
            path = '/master/vehicles/new' if writer.endswith('new') else (
                '/master/vehicles/' + str(self.vehicle_id) + '/edit')
        else:
            data = {'employee_id': 'rel-new' if writer.endswith('new') else 'rel-edit',
                    'last_name': 'Synthetic', 'first_name': '', 'role': 'user', 'office': office}
            if writer.endswith('new'):
                data['password'] = 'Q04-Related-Only-742!'
            path = '/master/drivers/new' if writer.endswith('new') else (
                '/master/drivers/' + str(self.driver_id) + '/edit')
        return path, data

    def submit(self, label, client, path, data):
        self.local.worker = label
        try:
            try:
                response = client.post(path, data=data)
                try:
                    return {'status': response.status_code, 'location': response.location}
                finally:
                    response.close()
            except Exception as error:
                return {'error': type(error).__name__, 'message': str(error)[:1000]}
        finally:
            self.local.worker = None

    def target_rows(self, writer):
        with self.app.app_context():
            if writer.startswith('vehicle_'):
                models = [(self.m.Vehicle, {'chassis_number': (
                    'REL-NEW-' if writer.endswith('new') else 'REL-EDIT-') + self.company})]
            else:
                employee = 'rel-new' if writer.endswith('new') else 'rel-edit'
                models = [(self.m.Driver, {'employee_id': employee}),
                          (self.m.User, {'username': employee})]
            return {model.__tablename__: [
                {c.name: getattr(row, c.name) for c in model.__table__.columns}
                for row in model.query.filter_by(company_code=self.company, **filters).order_by(model.id)]
                for model, filters in models}

    def orphans(self):
        state = self.snapshot(self.company)
        offices = {r['name'] for r in state['office']}
        types = {r['name'] for r in state['vehicle_type']}
        failures = []
        for table, column, valid in [('vehicle', 'office', offices), ('vehicle', 'type', types),
                                     ('user', 'office', offices), ('driver', 'office', offices),
                                     ('vehicle_type_import_mapping', 'vehicle_type_name', types)]:
            for row in state[table]:
                if row[column] and row[column] not in valid:
                    failures.append({'table': table, 'id': row['id'], 'field': column, 'value': row[column]})
        return failures

    def assert_writer_result(self, writer, response, before):
        destination = '/master/vehicles' if writer.startswith('vehicle_') else '/master/drivers'
        self.assertIn(response.get('status'), (302, 400, 409), repr(response))
        if response['status'] == 302:
            self.assertEqual(response.get('location'), destination)
            self.assertTrue(all(len(rows) == 1 for rows in self.target_rows(writer).values()))
        else:
            self.assertEqual(self.target_rows(writer), before, 'Rejected writer left partial target changes')

    def control(self, writer):
        before = self.target_rows(writer)
        path, data = self.related_request(writer)
        response = self.submit('B', self.client(), path, data)
        self.assertEqual(response.get('status'), 302, repr(response))
        self.assert_writer_result(writer, response, before)
        self.assertEqual(self.orphans(), [])
        self.assertEqual(self.snapshot(self.other), self.foreign_before)
        print('Q04_RELATED_CONTROL:', writer, response, flush=True)

    def race(self, writer, kind, operation):
        table = 'office' if kind == 'offices' else 'vehicle_type'
        ready, release = threading.Event(), threading.Event()
        pids, gated = {}, set()
        lock_wait = False

        def is_master_read(statement):
            sql = ' '.join(statement.lower().split())
            return sql.startswith('select ') and (' from ' + table + ' ') in sql

        def before_read(connection, cursor, statement, parameters, context, executemany):
            label = getattr(self.local, 'worker', None)
            if label and is_master_read(statement):
                pids.setdefault(label, cursor.connection.get_backend_pid())

        def hold_related_reader(connection, cursor, statement, parameters, context, executemany):
            if getattr(self.local, 'worker', None) == 'B' and not gated and is_master_read(statement):
                gated.add('B')
                ready.set()
                if not release.wait(20):
                    raise RuntimeError('Related reader was not released')

        path, data = self.related_request(writer, kind)
        before = self.target_rows(writer)
        master_path = '/master/' + kind + '/' + str(self.ids[kind]) + '/' + operation
        master_data = {'name': 'Renamed-Master'} if operation == 'edit' else {}
        master_client, related_client = self.client(), self.client()
        event.listen(self.engine, 'before_cursor_execute', before_read)
        event.listen(self.engine, 'after_cursor_execute', hold_related_reader)
        with self.pid_lock:
            self.pids.clear()
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                related = executor.submit(self.submit, 'B', related_client, path, data)
                try:
                    if not ready.wait(10):
                        result = related.result(timeout=1) if related.done() else 'still running'
                        raise RuntimeError('Writer never reached master validation: ' + repr(result))
                    master = executor.submit(self.submit, 'A', master_client, master_path, master_data)
                    deadline = time.monotonic() + 8
                    while not master.done():
                        if time.monotonic() > deadline:
                            raise RuntimeError('Master neither completed nor waited on the related writer')
                        if pids.get('A') and pids.get('B'):
                            with self.engine.connect() as connection:
                                blockers = connection.scalar(text('SELECT pg_blocking_pids(:pid)'),
                                                             {'pid': pids['A']})
                            if pids['B'] in blockers:
                                lock_wait = True
                                break
                        time.sleep(.01)
                    # Either B holds the master lock (let B commit first), or
                    # A has already finished (B must not persist a stale name).
                    release.set()
                    master_result = master.result(timeout=20)
                    related_result = related.result(timeout=20)
                finally:
                    release.set()
        finally:
            release.set()
            event.remove(self.engine, 'before_cursor_execute', before_read)
            event.remove(self.engine, 'after_cursor_execute', hold_related_reader)
        orphaned = self.orphans()
        evidence = {'test': self.id(), 'writer': writer, 'master': kind, 'operation': operation,
                    'responses': {'master': master_result, 'related': related_result},
                    'postgres_backends': sorted(self.pids), 'master_waited_for_related': lock_wait,
                    'orphaned_current_references': orphaned}
        print('Q04_RELATED_EVIDENCE:', json.dumps(evidence, ensure_ascii=True), flush=True)
        self.assertEqual(set(pids), {'A', 'B'}, 'Both requests must reach real master SQL')
        self.assertGreaterEqual(len(self.pids), 2, 'Two real PostgreSQL backends are required')
        self.assertEqual(master_result, {'status': 302, 'location': '/master/' + kind})
        self.assert_writer_result(writer, related_result, before)
        with self.app.app_context():
            model = self.m.Office if kind == 'offices' else self.m.VehicleType
            master_row = model.query.filter_by(id=self.ids[kind], company_code=self.company).first()
            if operation == 'edit':
                self.assertIsNotNone(master_row)
                self.assertEqual(master_row.name, 'Renamed-Master')
            else:
                self.assertIsNone(master_row)
            expected = master_row.name if master_row else ''
        if related_result.get('status') == 302:
            column = 'office' if kind == 'offices' else 'type'
            for rows in self.target_rows(writer).values():
                self.assertEqual(rows[0][column], expected,
                                 'Successful related writer did not retain the effective assignment')
        self.assertEqual(self.snapshot(self.other), self.foreign_before)
        self.assertEqual(orphaned, [], 'A writer saved a name absent from its company master')


def control_case(writer):
    def check(self):
        self.control(writer)
    return check


def race_case(writer, kind, operation):
    def check(self):
        self.race(writer, kind, operation)
    return check


for _writer in ('vehicle_new', 'vehicle_edit', 'driver_new', 'driver_edit'):
    setattr(RelatedMasterWriteTests, 'test_control_' + _writer, control_case(_writer))
    for _kind in (('offices', 'vehicle-types') if _writer.startswith('vehicle_') else ('offices',)):
        for _operation in ('edit', 'delete'):
            setattr(RelatedMasterWriteTests,
                    'test_race_' + _writer + '_' + _kind.replace('-', '_') + '_' + _operation,
                    race_case(_writer, _kind, _operation))


if __name__ == '__main__':
    unittest.main(verbosity=2)
