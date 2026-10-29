"""Master deletes/order saves sharing one order row, disposable PostgreSQL only.

Pause A after its order SELECT, start B, observe B reading the same revision or
waiting on A's real lock, then finish A before resuming B. Verify the committed
state before retries, without rolling back a failed request from the test.
"""
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event, text

import test_q04_postgres_master_concurrency as concurrency


class MasterOrderConcurrencyTests(unittest.TestCase):
    setUpClass = classmethod(concurrency.MasterConcurrencyTests.setUpClass.__func__)
    drop_schema = classmethod(concurrency.MasterConcurrencyTests.drop_schema.__func__)
    client = concurrency.MasterConcurrencyTests.client
    snapshot = concurrency.MasterConcurrencyTests.snapshot

    def setUp(self):
        concurrency.MasterConcurrencyTests.setUp(self)
        m = self.m
        with self.app.app_context():
            self.master_ids = {}
            for kind, model in (('offices', m.Office), ('vehicle-types', m.VehicleType)):
                prefix = 'Office-' if kind == 'offices' else 'Type-'
                rows = [model(company_code=self.company, name=prefix + suffix) for suffix in ('B', 'C')]
                self.db.session.add_all(rows)
                self.db.session.flush()
                self.master_ids[kind] = [self.ids[kind]] + [row.id for row in rows]
                saved = m.MasterDisplayOrder.query.filter_by(company_code=self.company, kind=kind).one()
                saved.ordered_ids_json = json.dumps(self.master_ids[kind])
                foreign_id = model.query.filter_by(company_code=self.other).one().id
                self.db.session.add(m.MasterDisplayOrder(company_code=self.other, kind=kind,
                    ordered_ids_json=json.dumps([foreign_id])))
            for suffix in ('B', 'C'):
                self.db.session.add(m.Vehicle(company_code=self.company,
                    chassis_number=self.company + '-' + suffix, office='Office-' + suffix, type='Type-' + suffix))
                self.db.session.add(m.Driver(company_code=self.company, employee_id='driver-' + suffix,
                    name='Synthetic', office='Office-' + suffix))
                self.db.session.add(m.User(company_code=self.company, username='user-' + suffix,
                    role='user', password='unused', last_name='Synthetic', office='Office-' + suffix,
                    password_changed_at=self.stamp))
                self.db.session.add(m.VehicleTypeImportMapping(company_code=self.company,
                    excel_value='IMPORT-' + suffix, vehicle_type_name='Type-' + suffix))
            self.db.session.flush()
            for vehicle in m.Vehicle.query.filter_by(company_code=self.company).all():
                self.db.session.add(m.VehicleMaintenanceRecord(company_code=self.company,
                    vehicle_record_id=vehicle.id, entry_date='2026-10-01', cost_office=vehicle.office, total_cost=100))
            self.db.session.commit()
        self.foreign_before = self.snapshot(self.other)
        self.history_before = self.history()
        self.vehicle_ids_before = self.vehicle_ids()

    def history(self):
        with self.app.app_context():
            model = self.m.VehicleMaintenanceRecord
            return [{c.name: getattr(row, c.name) for c in model.__table__.columns}
                    for row in model.query.filter_by(company_code=self.company).order_by(model.id)]

    def vehicle_ids(self):
        with self.app.app_context():
            return [row.id for row in self.m.Vehicle.query.filter_by(company_code=self.company).order_by(self.m.Vehicle.id)]

    def related(self, kind, index):
        name = ('Office-' if kind == 'offices' else 'Type-') + 'ABC'[index]
        if kind == 'offices':
            models = [(self.m.Office, 'name'), (self.m.Vehicle, 'office'),
                      (self.m.User, 'office'), (self.m.Driver, 'office')]
        else:
            models = [(self.m.VehicleType, 'name'), (self.m.Vehicle, 'type'),
                      (self.m.VehicleTypeImportMapping, 'vehicle_type_name')]
        with self.app.app_context():
            return {model.__tablename__: [
                {c.name: getattr(row, c.name) for c in model.__table__.columns}
                for row in model.query.filter_by(company_code=self.company, **{column: name}).order_by(model.id)]
                for model, column in models}

    def order_state(self, kind):
        from dkss_app.master_readers import ordered_master_query
        with self.app.app_context():
            saved = self.m.MasterDisplayOrder.query.filter_by(company_code=self.company, kind=kind).one()
            model = self.m.Office if kind == 'offices' else self.m.VehicleType
            return {'stored': json.loads(saved.ordered_ids_json), 'version': saved.version,
                    'visible': [row.id for row in ordered_master_query(model, self.company)]}

    def deletion(self, kind, index):
        return {'path': '/master/' + kind + '/' + str(self.master_ids[kind][index]) + '/delete'}

    def reorder(self, kind, wanted, previous):
        return {'path': '/master/' + kind + '/order', 'json': {'ids': wanted, 'previous_ids': previous}}

    def send(self, label, client, spec):
        from master_form_fixture import fresh_master_data
        arguments = ({'json': spec['json']} if 'json' in spec else
                     {'data': fresh_master_data(client, spec['path'], {})})
        self.local.worker = label
        try:
            try:
                response = client.post(spec['path'], **arguments)
                try:
                    return {'status': response.status_code, 'location': response.location,
                            'json': response.get_json(silent=True)}
                finally:
                    response.close()
            except Exception as error:
                return {'error': type(error).__name__, 'message': str(error)[:1000]}
        finally:
            self.local.worker = None

    def pair(self, first, second):
        a_read, b_read = threading.Event(), threading.Event()
        release_a, release_b = threading.Event(), threading.Event()
        pids, read = {}, set()
        lock_wait = False

        def selected(statement):
            sql = ' '.join(statement.lower().split())
            return sql.startswith('select ') and ' from master_display_order ' in sql

        def before(connection, cursor, statement, parameters, context, executemany):
            label = getattr(self.local, 'worker', None)
            if label and selected(statement):
                pids.setdefault(label, cursor.connection.get_backend_pid())

        def after(connection, cursor, statement, parameters, context, executemany):
            label = getattr(self.local, 'worker', None)
            if label and label not in read and selected(statement):
                read.add(label)
                (a_read if label == 'A' else b_read).set()
                if not (release_a if label == 'A' else release_b).wait(20):
                    raise RuntimeError('Order reader was not released')

        event.listen(self.engine, 'before_cursor_execute', before)
        event.listen(self.engine, 'after_cursor_execute', after)
        with self.pid_lock:
            self.pids.clear()
        client_a, client_b = self.client(), self.client()
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                fa = executor.submit(self.send, 'A', client_a, first)
                try:
                    if not a_read.wait(10):
                        raise RuntimeError('A did not read the shared order row')
                    fb = executor.submit(self.send, 'B', client_b, second)
                    deadline = time.monotonic() + 8
                    while not b_read.is_set():
                        if time.monotonic() > deadline:
                            raise RuntimeError('B neither read the order nor waited on A')
                        if pids.get('B'):
                            with self.engine.connect() as connection:
                                blockers = connection.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': pids['B']})
                            if pids['A'] in blockers:
                                lock_wait = True
                                break
                        time.sleep(.01)
                    release_a.set()
                    ra = fa.result(timeout=20)
                finally:
                    release_a.set()
                    release_b.set()
                rb = fb.result(timeout=20)
        finally:
            release_a.set()
            release_b.set()
            event.remove(self.engine, 'before_cursor_execute', before)
            event.remove(self.engine, 'after_cursor_execute', after)
        evidence = {'postgres_backends': sorted(self.pids), 'order_lock_wait_observed': lock_wait}
        self.assertEqual(read, {'A', 'B'}, 'Both requests must execute the shared order SELECT')
        self.assertGreaterEqual(len(self.pids), 2, 'Two PostgreSQL backends are required')
        return ra, rb, evidence

    def audits(self, action):
        with self.app.app_context():
            return [row.target_id for row in self.m.AuditLog.query.filter_by(
                company_code=self.company, action=action).order_by(self.m.AuditLog.id)]

    def check(self, kind, scenario):
        ids = self.master_ids[kind]
        wanted_a, wanted_b = [ids[2], ids[0], ids[1]], [ids[1], ids[2], ids[0]]
        deleted = [0, 1] if scenario == 'separate_deletes' else ([] if scenario == 'two_reorders' else [0])
        first = self.deletion(kind, 0) if scenario in ('separate_deletes', 'delete_then_reorder') else self.reorder(kind, wanted_a, ids)
        second = self.deletion(kind, 1 if scenario == 'separate_deletes' else 0) if scenario in (
            'separate_deletes', 'reorder_then_delete') else self.reorder(kind, wanted_b, ids)
        second_index = 1 if scenario == 'separate_deletes' else 0
        before_related = self.related(kind, second_index)
        ra, rb, evidence = self.pair(first, second)
        action = 'office_deleted' if kind == 'offices' else 'vehicle_type_deleted'
        evidence.update(test=self.id(), scenario=scenario, master=kind,
                        parallel_responses=[ra, rb], after_parallel=self.order_state(kind))
        print('Q04_ORDER_PARALLEL:', json.dumps(evidence, ensure_ascii=True), flush=True)
        self.assertEqual(ra.get('status'), 200 if 'json' in first else 302, repr(ra))
        self.assertIn(rb.get('status'), (302, 409) if 'json' not in second else (409,), repr(rb))
        after_first = ids[1:] if 'json' not in first else wanted_a
        retry = None
        if rb['status'] == 409:
            # Read committed state before retry; no test rollback/remove occurs.
            self.assertEqual(self.order_state(kind)['stored'], after_first)
            self.assertEqual(self.order_state(kind)['visible'], after_first)
            if 'json' not in second:
                self.assertEqual(self.related(kind, second_index), before_related,
                                 'Failed delete left partial master/related writes')
                retry = second
            else:
                self.assertEqual(len(self.audits('master_order_changed')), 0 if 'json' not in first else 1)
                fresh = self.order_state(kind)['visible']
                retry = self.reorder(kind, list(reversed(fresh)) if scenario == 'delete_then_reorder' else wanted_b, fresh)
            expected_deleted = [] if 'json' in first else [str(ids[0])]
            self.assertCountEqual(self.audits(action), expected_deleted,
                                  'Rejected request committed a deletion audit')
            retry_response = self.send('R', self.client(), retry)
            self.assertEqual(retry_response.get('status'), 200 if 'json' in retry else 302, repr(retry_response))
            evidence['retry_response'] = retry_response
        expected_order = ([ids[2]] if scenario == 'separate_deletes' else
                          [ids[2], ids[1]] if scenario in ('delete_then_reorder', 'reorder_then_delete') else wanted_b)
        final = self.order_state(kind)
        self.assertEqual(final['stored'], expected_order, 'Stored order retained a deleted ID or lost a reorder')
        self.assertEqual(final['visible'], expected_order)
        with self.app.app_context():
            model = self.m.Office if kind == 'offices' else self.m.VehicleType
            self.assertEqual({row.id for row in model.query.filter_by(company_code=self.company)}, set(expected_order))
        self.assertCountEqual(self.audits(action), [str(ids[index]) for index in deleted])
        expected_reorders = 0 if scenario == 'separate_deletes' else 2 if scenario == 'two_reorders' else 1
        self.assertEqual(len(self.audits('master_order_changed')), expected_reorders)
        for index in deleted:
            self.assertTrue(all(not rows for rows in self.related(kind, index).values()),
                            'Deleted master still has a current name reference')
        self.assertEqual(self.vehicle_ids(), self.vehicle_ids_before, 'Deleting a master removed vehicle data')
        self.assertEqual(self.history(), self.history_before, 'Historical cost data changed')
        self.assertEqual(self.snapshot(self.other), self.foreign_before)
        evidence['final_order'] = final
        evidence['deletion_audits'] = self.audits(action)
        evidence['order_audits'] = len(self.audits('master_order_changed'))
        print('Q04_ORDER_EVIDENCE:', json.dumps(evidence, ensure_ascii=True), flush=True)


def case(kind, scenario):
    def test(self):
        self.check(kind, scenario)
    return test


for _kind in ('offices', 'vehicle-types'):
    for _scenario in ('separate_deletes', 'delete_then_reorder', 'reorder_then_delete', 'two_reorders'):
        setattr(MasterOrderConcurrencyTests, 'test_' + _kind.replace('-', '_') + '_' + _scenario,
                case(_kind, _scenario))


if __name__ == '__main__':
    unittest.main(verbosity=2)
