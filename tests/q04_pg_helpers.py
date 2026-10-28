"""Shared Q04 scheduling on real SQL and owned, loopback-only PostgreSQL."""
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event, text

import test_q04_postgres_master_concurrency as existing


class PrivatePostgresCase(unittest.TestCase):
    setUpClass = classmethod(existing.MasterConcurrencyTests.setUpClass.__func__)
    drop_schema = classmethod(existing.MasterConcurrencyTests.drop_schema.__func__)
    client = existing.MasterConcurrencyTests.client
    setUp = existing.MasterConcurrencyTests.setUp

    def snapshot(self, company):
        result = existing.MasterConcurrencyTests.snapshot(self, company)
        with self.app.app_context():
            for model in (self.m.DeliveryPlace, self.m.PatrolContentType, self.m.LicenseType,
                          self.m.PatrolResult, self.m.ChecklistResult,
                          self.m.ChecklistEvent, self.m.Notification):
                result[model.__tablename__] = [
                    {c.name: getattr(row, c.name) for c in model.__table__.columns}
                    for row in model.query.filter_by(company_code=company).order_by(model.id)]
        return result

    def post(self, label, action):
        path, data, company = action
        self.local.worker = label
        try:
            with self.client(company) as client:
                response = client.post(path, data=data,
                    headers={'X-DKSS-Final-Submit': '1'})
                try:
                    return {'status': response.status_code, 'location': response.location}
                finally:
                    response.close()
        except Exception as error:
            return {'error': type(error).__name__, 'message': str(error)[:500]}
        finally:
            self.local.worker = None

    def action(self, path, data=None, company=None):
        return path, data or {}, company or self.company

    def assert_failed_save_is_atomic(self, action, sql_prefix):
        before, foreign = self.snapshot(self.company), self.snapshot(self.other)
        reached = []
        def fail(connection, cursor, statement, parameters, context, executemany):
            if statement.lower().startswith(sql_prefix):
                reached.append(True)
                raise RuntimeError('Q04_RELATED_AFTER_SQL')
        event.listen(self.engine, 'after_cursor_execute', fail)
        try:
            response = self.post('A', action)
        finally:
            event.remove(self.engine, 'after_cursor_execute', fail)
        self.assertEqual(reached, [True])
        self.assertTrue(response.get('error') or response.get('status') == 500, repr(response))
        self.assertEqual(self.snapshot(self.company), before)
        self.assertEqual(self.snapshot(self.other), foreign)
        self.assertEqual(self.post('A', action).get('status'), 302, 'Retry after rollback must succeed')

    def schedule(self, first, second, table, parallel_prefix=None, first_table=None):
        """Hold A after SELECT; observe B finishing or waiting on A's real lock.

        For insert/disjoint-update races, pause both before the matching SQL.
        No SQL text, query results, locks, or commits are substituted.
        """
        ready, release = threading.Event(), threading.Event()
        barrier = threading.Barrier(2, timeout=10)
        reached, pids = set(), {}
        waited = False

        def matches(statement):
            sql = ' '.join(statement.lower().split())
            return (sql.startswith(parallel_prefix) if parallel_prefix else
                    sql.startswith('select ') and (' from ' + table + ' ') in sql)

        def first_matches(statement):
            sql = ' '.join(statement.lower().split())
            return (sql.startswith('select ') and (' from ' + first_table + ' ') in sql
                    if first_table else matches(statement))

        def before(connection, cursor, statement, parameters, context, executemany):
            label = getattr(self.local, 'worker', None)
            if label:
                # Master mutations may UPDATE a source table without SELECTing it.
                # Track that request's connection as well as the paused reader.
                pids.setdefault(label, cursor.connection.get_backend_pid())
            if label and (matches(statement) or label == 'A' and first_matches(statement)):
                pids[label] = cursor.connection.get_backend_pid()
                if parallel_prefix and label not in reached:
                    reached.add(label)
                    barrier.wait()

        def after(connection, cursor, statement, parameters, context, executemany):
            label = getattr(self.local, 'worker', None)
            if not parallel_prefix and label == 'A' and not reached and first_matches(statement):
                reached.add('A')
                ready.set()
                if not release.wait(20):
                    raise RuntimeError('Q04 SQL gate timed out')

        event.listen(self.engine, 'before_cursor_execute', before)
        event.listen(self.engine, 'after_cursor_execute', after)
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                a = executor.submit(self.post, 'A', first)
                try:
                    if not parallel_prefix and not ready.wait(10):
                        raise AssertionError('A did not reach the real SQL gate: ' + repr(a.result(1)))
                    b = executor.submit(self.post, 'B', second)
                    if not parallel_prefix:
                        deadline = time.monotonic() + 8
                        while not b.done():
                            if time.monotonic() > deadline:
                                raise AssertionError('B neither finished nor waited on A')
                            if 'B' in pids:
                                with self.engine.connect() as connection:
                                    blockers = connection.scalar(text('SELECT pg_blocking_pids(:pid)'),
                                                                 {'pid': pids['B']})
                                if pids['A'] in blockers:
                                    waited = True
                                    break
                            time.sleep(.01)
                    release.set()
                    results = a.result(20), b.result(20)
                finally:
                    release.set()
        finally:
            release.set()
            event.remove(self.engine, 'before_cursor_execute', before)
            event.remove(self.engine, 'after_cursor_execute', after)
        print('Q04_GAP_EVIDENCE:', json.dumps({'test': self.id(), 'table': table,
            'parallel_prefix': parallel_prefix, 'responses': results,
            'backend_pids': pids, 'lock_wait_observed': waited}), flush=True)
        self.assertEqual(set(pids), {'A', 'B'})
        self.assertEqual(len(set(pids.values())), 2)
        if parallel_prefix:
            self.assertEqual(reached, {'A', 'B'})
        return results, waited
