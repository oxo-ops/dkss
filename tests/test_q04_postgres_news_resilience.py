"""Uncovered news/office commit order, replacement, rollback and lock retries."""
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from sqlalchemy import event, text

import test_q04_postgres_news_office as original
from q04_pg_helpers import PrivatePostgresCase


class NewsOfficeResilienceTests(PrivatePostgresCase):
    setUp = original.NewsOfficeConcurrencyTests.setUp
    snapshot = original.NewsOfficeConcurrencyTests.snapshot
    related_request = original.NewsOfficeConcurrencyTests.related_request

    def post(self, label, action):
        path, data, company = action
        if path == '__delete_recreate__':
            deleted = self.post(label, self.action(f'/master/offices/{self.ids["offices"]}/delete'))
            return (self.post(label, self.action('/master/offices/new', {'name': 'Office-A'}))
                    if deleted.get('status') == 302 else deleted)
        if path.startswith('/itc/news'):
            client = self.app.test_client()
            with self.app.app_context():
                identity = getattr(self.m.User.query.filter_by(company_code=company,
                    username='news-actor').one(), 'account_identity', None)
            with client.session_transaction() as state:
                state.update(account_identity=identity, company_code=company, username='news-actor', role='itc',
                             password_changed_at=self.stamp)
        else:
            client = self.client(company)
        return original.NewsOfficeConcurrencyTests.submit(self, label, client, path, data)

    def news_action(self, writer='new'):
        path, data = self.related_request(writer)
        return self.action(path, data)

    def check_master_first(self, writer, operation):
        before = self.snapshot(self.company)
        mutation = self.action(f'/master/offices/{self.ids["offices"]}/{operation}',
            {'name': 'Renamed'} if operation == 'edit' else {})
        responses, waited = self.schedule(mutation, self.news_action(writer), 'office', first_table='news')
        self.assertEqual([r.get('status') for r in responses], [302, 403], repr(responses))
        state = self.snapshot(self.company)
        self.assertEqual(state['news'], before['news'])
        self.assertEqual(state['notification'], before['notification'])
        self.assertTrue(waited)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_delete_recreate_and_stale_id_do_not_mutate_replacement_news(self):
        old_id = self.ids['offices']
        self.assertEqual(self.post('A', self.action(f'/master/offices/{old_id}/delete')).get('status'), 302)
        self.assertEqual(self.post('A', self.action('/master/offices/new', {'name': 'Office-A'})).get('status'), 302)
        with self.app.app_context():
            # The new office has a new ID; assign a current recipient explicitly.
            replacement = self.m.Office.query.filter_by(company_code=self.company, name='Office-A').one()
            self.assertNotEqual(replacement.id, old_id)
            self.m.User.query.filter_by(company_code=self.company, username='admin').one().office = 'Office-A'
            self.db.session.commit()
        self.assertEqual(self.post('A', self.news_action()).get('status'), 302)
        before = self.snapshot(self.company)
        for operation in ('edit', 'delete'):
            response = self.post('A', self.action(f'/master/offices/{old_id}/{operation}', {'name': 'Stale'}))
            self.assertEqual(response.get('status'), 302)
            self.assertEqual(self.snapshot(self.company), before)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_news_validation_prevents_concurrent_delete_and_same_name_recreation(self):
        responses, waited = self.schedule(self.news_action(), self.action('__delete_recreate__'), 'office')
        self.assertEqual([r.get('status') for r in responses], [302, 409], repr(responses))
        offices = self.snapshot(self.company)['office']
        self.assertEqual([(r['id'], r['name']) for r in offices], [(self.ids['offices'], 'Office-A')])
        self.assertTrue(waited)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_other_company_mutation_does_not_wait_or_receive_notifications(self):
        foreign_id = self.foreign_before['office'][0]['id']
        responses, waited = self.schedule(self.news_action(),
            self.action(f'/master/offices/{foreign_id}/edit', {'name': 'Other-renamed'}, self.other), 'office')
        self.assertEqual([r.get('status') for r in responses], [302, 302], repr(responses))
        self.assertFalse(waited, 'A different company must not share this office lock')
        own, foreign = self.snapshot(self.company), self.snapshot(self.other)
        self.assertEqual(own['office'][0]['name'], 'Office-A')
        self.assertEqual(foreign['office'][0]['name'], 'Other-renamed')
        self.assertEqual(foreign['news'], self.foreign_before['news'])
        self.assertEqual(foreign['notification'], [])
        self.assertTrue(own['notification'])

    def test_second_recipient_failure_rolls_back_news_audit_and_all_notifications(self):
        from dkss_app import notifications_delivery
        with self.app.app_context():
            self.db.session.add(self.m.User(company_code=self.company, username='second-reader',
                role='user', office='Office-A', last_name='Second', password='unused',
                password_changed_at=self.stamp))
            self.db.session.commit()
        before = self.snapshot(self.company)
        inserts = []
        def fail(connection, cursor, statement, parameters, context, executemany):
            if statement.lower().startswith('insert into notification '):
                inserts.append(True)
                if len(inserts) == 2:
                    raise RuntimeError('Q04_NEWS_SECOND_NOTIFICATION')
        event.listen(self.engine, 'after_cursor_execute', fail)
        try:
            with patch.object(notifications_delivery, 'dispatch_external_notification') as dispatch:
                response = self.post('A', self.news_action())
                self.assertEqual(response.get('status'), 500, repr(response))
                self.assertEqual(self.snapshot(self.company), before)
                dispatch.assert_not_called()
        finally:
            event.remove(self.engine, 'after_cursor_execute', fail)
        self.assertEqual(len(inserts), 2)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)
        with patch.object(notifications_delivery, 'dispatch_external_notification'):
            self.assertEqual(self.post('A', self.news_action()).get('status'), 302)
        state = self.snapshot(self.company)
        self.assertEqual(len(state['news']), len(before['news']) + 1)
        self.assertEqual(len(state['notification']), 2)
        self.assertEqual(sum(r['action'] == 'news_created' for r in state['audit_log']), 1)

    def test_edit_failure_rolls_back_news_and_audit_then_retry_succeeds(self):
        self.assert_failed_save_is_atomic(self.news_action('edit'), 'update news ')

    def test_lock_timeout_returns_retryable_conflict_without_partial_save(self):
        before = self.snapshot(self.company)
        states = []
        def timeout(connection, cursor, statement, parameters, context, executemany):
            if getattr(self.local, 'worker', None) and ' from office ' in (' ' + ' '.join(statement.lower().split()) + ' '):
                cursor.execute("SET LOCAL lock_timeout = '150ms'")
        def error(context):
            states.append(getattr(context.original_exception, 'pgcode', None))
        with self.engine.connect() as blocker:
            transaction = blocker.begin()
            blocker.execute(text('SELECT id FROM office WHERE id=:id FOR UPDATE'), {'id': self.ids['offices']})
            event.listen(self.engine, 'before_cursor_execute', timeout)
            event.listen(self.engine, 'handle_error', error)
            try:
                response = self.post('A', self.news_action())
            finally:
                event.remove(self.engine, 'before_cursor_execute', timeout)
                event.remove(self.engine, 'handle_error', error)
                transaction.rollback()
        self.assertIn('55P03', states, 'PostgreSQL must generate the real lock timeout')
        print('Q04_NEWS_RECOVERY:', {'sqlstates': states, 'response': response}, flush=True)
        self.assertEqual(response.get('status'), 409, repr(response))
        self.assertEqual(self.snapshot(self.company), before)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)
        self.assertEqual(self.post('A', self.news_action()).get('status'), 302)

    def test_real_deadlock_victim_rolls_back_and_can_be_retried(self):
        # Fault injection creates a real server-side cycle, not a mocked error:
        # news holds Office and waits on an advisory lock; blocker holds that
        # advisory lock and requests Office. Only the disposable DB is touched.
        ready = threading.Event()
        states = []
        before = self.snapshot(self.company)
        def cycle(connection, cursor, statement, parameters, context, executemany):
            if getattr(self.local, 'worker', None) == 'A' and ' from office ' in (' ' + ' '.join(statement.lower().split()) + ' '):
                cursor.execute("SET LOCAL deadlock_timeout = '50ms'")
                ready.set()
                cursor.execute('SELECT pg_advisory_xact_lock(704273)')
        def error(context):
            states.append(getattr(context.original_exception, 'pgcode', None))
        with self.engine.connect() as blocker:
            transaction = blocker.begin()
            blocker.execute(text("SET LOCAL deadlock_timeout = '5s'"))
            blocker.execute(text('SELECT pg_advisory_xact_lock(704273)'))
            event.listen(self.engine, 'after_cursor_execute', cycle)
            event.listen(self.engine, 'handle_error', error)
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self.post, 'A', self.news_action())
                    try:
                        self.assertTrue(ready.wait(10))
                        blocker.execute(text('SELECT id FROM office WHERE id=:id FOR UPDATE'),
                                        {'id': self.ids['offices']})
                        response = future.result(timeout=10)
                    finally:
                        transaction.rollback()
            finally:
                event.remove(self.engine, 'after_cursor_execute', cycle)
                event.remove(self.engine, 'handle_error', error)
                if transaction.is_active:
                    transaction.rollback()
        self.assertIn('40P01', states, 'The server must select this request as a real deadlock victim')
        print('Q04_NEWS_RECOVERY:', {'sqlstates': states, 'response': response}, flush=True)
        self.assertEqual(response.get('status'), 409, repr(response))
        self.assertEqual(self.snapshot(self.company), before)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)
        self.assertEqual(self.post('A', self.news_action()).get('status'), 302)

    def test_mentions_and_recipients_commit_before_external_dispatch(self):
        from dkss_app import notifications_delivery
        action = self.news_action()
        action[1]['message'] = 'Synthetic [[news-actor|Synthetic]]'
        observed = []
        def observe(*args, **kwargs):
            # A new connection can only see rows after the single commit.
            with self.engine.connect() as connection:
                observed.append((connection.scalar(text('SELECT count(*) FROM news WHERE company_code=:c AND title=:t'),
                    {'c': self.company, 't': 'Office synthetic news'}),
                    connection.scalar(text('SELECT count(*) FROM notification WHERE company_code=:c'), {'c': self.company})))
        with patch.object(notifications_delivery, 'dispatch_external_notification', side_effect=observe):
            self.assertEqual(self.post('A', action).get('status'), 302)
        self.assertEqual(observed, [(1, 2), (1, 2)])
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_post_commit_delivery_db_failure_is_not_reported_as_retryable_save(self):
        from dkss_app import notifications_delivery
        before = self.snapshot(self.company)
        def fail_delivery(*args, **kwargs):
            with self.engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '100ms'"))
                connection.execute(text('SELECT pg_advisory_xact_lock(704274)'))
        with self.engine.begin() as blocker:
            blocker.execute(text('SELECT pg_advisory_xact_lock(704274)'))
            with patch.object(notifications_delivery, 'dispatch_external_notification', side_effect=fail_delivery):
                response = self.post('A', self.news_action())
        self.assertEqual(response.get('status'), 500, repr(response))
        state = self.snapshot(self.company)
        self.assertEqual(len(state['news']), len(before['news']) + 1)
        self.assertEqual(len(state['notification']), len(before['notification']) + 1)
        self.assertEqual(sum(r['action'] == 'news_created' for r in state['audit_log']), 1)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_q08_replaced_recipient_does_not_inherit_selected_generation_notification(self):
        with self.app.app_context():
            driver = self.m.Driver(company_code=self.company, employee_id='replace-reader',
                name='Old reader', office='Office-A', role='user')
            user = self.m.User(company_code=self.company, username='replace-reader',
                last_name='Old reader', office='Office-A', role='user', password='unused',
                password_changed_at=self.stamp)
            self.db.session.add_all([driver, user])
            self.db.session.commit()
            driver_id, retired_identity = driver.id, user.account_identity
        ready, release = threading.Event(), threading.Event()
        gated = []
        def pause_recipients(connection, cursor, statement, parameters, context, executemany):
            sql = ' '.join(statement.lower().split())
            if (getattr(self.local, 'worker', None) == 'A' and not gated
                    and sql.startswith('select ') and ' from "user" ' in sql and '"user".office =' in sql):
                gated.append(True)
                ready.set()
                if not release.wait(20):
                    raise RuntimeError('Recipient snapshot was not released')
        event.listen(self.engine, 'after_cursor_execute', pause_recipients)
        with self.pid_lock:
            self.pids.clear()
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                news = executor.submit(self.post, 'A', self.news_action())
                try:
                    self.assertTrue(ready.wait(10))
                    deleted = executor.submit(self.post, 'B', self.action(f'/master/drivers/{driver_id}/delete')).result(10)
                    self.assertEqual(deleted.get('status'), 302, repr(deleted))
                    recreated = executor.submit(self.post, 'B', self.action('/master/drivers/new', {
                        'employee_id': 'replace-reader', 'last_name': 'New reader', 'role': 'user',
                        'office': 'Office-A', 'password': 'Q04-Replacement-Only-742!'})).result(10)
                    self.assertEqual(recreated.get('status'), 302, repr(recreated))
                    release.set()
                    self.assertEqual(news.result(10), {'status': 302, 'location': '/itc'})
                finally:
                    release.set()
        finally:
            release.set()
            event.remove(self.engine, 'after_cursor_execute', pause_recipients)
        with self.app.app_context():
            replacement = self.m.User.query.filter_by(company_code=self.company, username='replace-reader').one()
            self.assertNotEqual(replacement.account_identity, retired_identity)
            self.assertEqual(self.m.Notification.query.filter_by(company_code=self.company,
                owner_identity=replacement.account_identity).count(), 0)
            self.assertEqual(self.m.Notification.query.filter_by(company_code=self.company,
                owner_identity=retired_identity).count(), 0)
            self.assertEqual(self.m.News.query.filter_by(company_code=self.company,
                title='Office synthetic news').count(), 1)
            self.assertEqual(self.m.Notification.query.filter_by(company_code=self.company,
                target_username='admin').count(), 1)
        self.assertGreaterEqual(len(self.pids), 2)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_real_serialization_failure_requires_reload_then_retry(self):
        from sqlalchemy.orm import Session
        ready, release = threading.Event(), threading.Event()
        states, gated = [], []
        before = self.snapshot(self.company)
        def serializable(session, transaction, connection):
            if getattr(self.local, 'worker', None) == 'A':
                connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                # Establish a real snapshot before the competing update commits.
                connection.execute(text('SELECT id FROM office WHERE id=:id'), {'id': self.ids['offices']})
        def pause(connection, cursor, statement, parameters, context, executemany):
            if (getattr(self.local, 'worker', None) == 'A' and not gated
                    and ' '.join(statement.lower().split()).startswith('select office.')):
                gated.append(True)
                ready.set()
                if not release.wait(20):
                    raise RuntimeError('Serializable reader was not released')
        def error(context):
            states.append(getattr(context.original_exception, 'pgcode', None))
        event.listen(Session, 'after_begin', serializable)
        event.listen(self.engine, 'before_cursor_execute', pause)
        event.listen(self.engine, 'handle_error', error)
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                future = executor.submit(self.post, 'A', self.news_action())
                try:
                    self.assertTrue(ready.wait(10))
                    mutation = self.action(f'/master/offices/{self.ids["offices"]}/edit', {'name': 'Renamed'})
                    self.assertEqual(executor.submit(self.post, 'B', mutation).result(10).get('status'), 302)
                    release.set()
                    response = future.result(10)
                finally:
                    release.set()
        finally:
            event.remove(Session, 'after_begin', serializable)
            event.remove(self.engine, 'before_cursor_execute', pause)
            event.remove(self.engine, 'handle_error', error)
        self.assertIn('40001', states)
        print('Q04_NEWS_RECOVERY:', {'sqlstates': states, 'response': response}, flush=True)
        self.assertEqual(response.get('status'), 409, repr(response))
        state = self.snapshot(self.company)
        self.assertEqual(state['news'], before['news'])
        self.assertEqual(state['notification'], before['notification'])
        self.assertEqual(self.snapshot(self.other), self.foreign_before)
        retry = self.news_action()
        retry[1]['target_value'] = 'Renamed'
        self.assertEqual(self.post('A', retry), {'status': 302, 'location': '/itc'})


def case(writer, operation):
    def check(self):
        self.check_master_first(writer, operation)
    return check


for _writer in ('new', 'edit'):
    for _operation in ('edit', 'delete'):
        setattr(NewsOfficeResilienceTests, 'test_master_first_' + _writer + '_' + _operation, case(_writer, _operation))
