"""Office-targeted news saves racing office mutation, private PostgreSQL only.

Hold the news writer after its real office validation SELECT. Let the competing
master request commit, or observe its real lock wait, before resuming the news
writer. Synthetic rows only; no attachments, mentions or push subscriptions.
"""
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event, text

import test_q04_postgres_master_concurrency as concurrency
import test_q04_postgres_related_writes as related


class NewsOfficeConcurrencyTests(unittest.TestCase):
    setUpClass = classmethod(concurrency.MasterConcurrencyTests.setUpClass.__func__)
    drop_schema = classmethod(concurrency.MasterConcurrencyTests.drop_schema.__func__)
    client = concurrency.MasterConcurrencyTests.client
    submit = related.RelatedMasterWriteTests.submit

    def snapshot(self, company):
        state = concurrency.MasterConcurrencyTests.snapshot(self, company)
        with self.app.app_context():
            for model in (self.m.News, self.m.Notification):
                state[model.__tablename__] = [
                    {c.name: getattr(row, c.name) for c in model.__table__.columns}
                    for row in model.query.filter_by(company_code=company).order_by(model.id)]
        return state

    def setUp(self):
        concurrency.MasterConcurrencyTests.setUp(self)
        with self.app.app_context():
            for company in (self.company, self.other):
                self.db.session.add(self.m.User(company_code=company, username='news-actor',
                    role='itc', password='unused', last_name='Synthetic', office='',
                    password_changed_at=self.stamp))
                news = self.m.News(company_code=company, title='Existing synthetic news',
                    message='Synthetic', target_type='all', target_value='', files_json='[]')
                self.db.session.add(news)
                self.db.session.flush()
                if company == self.company:
                    self.news_id = news.id
            self.db.session.commit()
        self.foreign_before = self.snapshot(self.other)

    def news_client(self):
        client = self.app.test_client()
        with self.app.app_context():
            identity = getattr(self.m.User.query.filter_by(company_code=self.company,
                username='news-actor').one(), 'account_identity', None)
        with client.session_transaction() as state:
            state.update(account_identity=identity, company_code=self.company, username='news-actor', role='itc',
                         password_changed_at=self.stamp)
        return client

    def related_request(self, writer, kind=None):
        path = '/itc/news/new' if writer == 'new' else '/itc/news/' + str(self.news_id) + '/edit'
        return path, {'title': 'Office synthetic news', 'message': 'Synthetic text',
                      'target_type': 'office', 'target_value': 'Office-A'}

    def target_rows(self, writer):
        with self.app.app_context():
            query = self.m.News.query.filter_by(company_code=self.company)
            query = query.filter_by(title='Office synthetic news') if writer == 'new' else query.filter_by(id=self.news_id)
            return [{c.name: getattr(row, c.name) for c in self.m.News.__table__.columns}
                    for row in query.order_by(self.m.News.id)]

    def orphan_news(self):
        state = self.snapshot(self.company)
        offices = {row['name'] for row in state['office']}
        return [row for row in state['news'] if row['target_type'] == 'office'
                and row['target_value'] not in offices]

    def control(self, writer):
        path, data = self.related_request(writer)
        result = self.submit('B', self.news_client(), path, data)
        self.assertEqual(result, {'status': 302, 'location': '/itc'})
        rows = self.target_rows(writer)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['target_type'], rows[0]['target_value']), ('office', 'Office-A'))
        self.assertEqual(self.orphan_news(), [])
        self.assertEqual(self.snapshot(self.other), self.foreign_before)
        print('Q04_NEWS_CONTROL:', writer, result, flush=True)

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
        state_before = self.snapshot(self.company)
        master_path = '/master/' + kind + '/' + str(self.ids[kind]) + '/' + operation
        master_data = {'name': 'Renamed-Master'} if operation == 'edit' else {}
        master_client, related_client = self.client(), self.news_client()
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
        orphaned = self.orphan_news()
        evidence = {'test': self.id(), 'writer': writer, 'operation': operation,
                    'postgres_backends': sorted(self.pids), 'master_waited_for_news': lock_wait,
                    'responses': {'master': master_result, 'news': related_result},
                    'orphaned_office_news': orphaned}
        print('Q04_NEWS_EVIDENCE:', json.dumps(evidence, ensure_ascii=True), flush=True)
        self.assertEqual(set(pids), {'A', 'B'}, 'Both requests must reach real office SQL')
        self.assertGreaterEqual(len(self.pids), 2, 'Two PostgreSQL backends are required')
        self.assertIn(master_result.get('status'), (302, 409), repr(master_result))
        self.assertIn(related_result.get('status'), (302, 400, 403, 409), repr(related_result))
        if related_result['status'] == 302:
            self.assertEqual(related_result['location'], '/itc')
            rows = self.target_rows(writer)
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]['target_type'], rows[0]['target_value']), ('office', 'Office-A'))
            self.assertEqual(master_result['status'], 409,
                             'Master changed after office-targeted news was validated')
        else:
            self.assertEqual(self.target_rows(writer), before, 'Rejected news save changed its row')
            self.assertEqual(master_result['status'], 302)
        state_after = self.snapshot(self.company)
        if master_result['status'] == 409:
            for table in ('office', 'vehicle', 'user', 'driver', 'master_display_order'):
                self.assertEqual(state_after[table], state_before[table],
                                 'Rejected master request left partial changes: ' + table)
            new_deletions = [row for row in state_after['audit_log']
                            if row['action'] == 'office_deleted']
            self.assertEqual(new_deletions, [])
        else:
            with self.app.app_context():
                office = self.m.Office.query.filter_by(id=self.ids['offices']).first()
                if operation == 'edit':
                    self.assertIsNotNone(office)
                    self.assertEqual(office.name, 'Renamed-Master')
                else:
                    self.assertIsNone(office)
        self.assertEqual(orphaned, [], 'News points to an office absent from its company')
        self.assertEqual(self.snapshot(self.other), self.foreign_before)


def control_case(writer):
    def check(self):
        self.control(writer)
    return check


def race_case(writer, operation):
    def check(self):
        self.race(writer, 'offices', operation)
    return check


for writer in ('new', 'edit'):
    setattr(NewsOfficeConcurrencyTests, 'test_control_news_' + writer, control_case(writer))
    for operation in ('edit', 'delete'):
        setattr(NewsOfficeConcurrencyTests, 'test_news_' + writer + '_office_' + operation,
                race_case(writer, operation))
