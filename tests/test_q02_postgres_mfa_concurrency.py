"""Opt-in MFA concurrency checks against an isolated local PostgreSQL service.

Normal discovery skips these checks without Q02_POSTGRES_TEST_URL. CI sets
Q02_REQUIRE_POSTGRES=1 so missing configuration cannot become a green skip.
Only loopback dkss_q02_ci is accepted; each run owns a random private schema.
"""
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import unittest
from unittest.mock import patch


class Q02PostgresMFAConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ.get('Q02_POSTGRES_TEST_URL', '')
        if not url:
            if os.environ.get('Q02_REQUIRE_POSTGRES') == '1':
                raise RuntimeError('Q02 PostgreSQL configuration is required')
            raise unittest.SkipTest('PostgreSQL concurrency runs in the dedicated CI job')
        from sqlalchemy import create_engine, event, text
        from sqlalchemy.engine import make_url
        parsed = make_url(url)
        if (parsed.get_backend_name() != 'postgresql'
                or parsed.host not in ('127.0.0.1', 'localhost', '::1')
                or parsed.database != 'dkss_q02_ci'):
            raise RuntimeError('Only loopback PostgreSQL database dkss_q02_ci is permitted')
        from dkss_app import create_app, models, auth
        from dkss_app.extensions import db, limiter
        from werkzeug.security import generate_password_hash
        cls.db, cls.models, cls.auth = db, models, auth
        cls.schema = 'q02_mfa_' + uuid.uuid4().hex
        assert re.fullmatch(r'q02_mfa_[0-9a-f]{32}', cls.schema)
        cls.admin_engine = create_engine(url, isolation_level='AUTOCOMMIT')
        cls.addClassCleanup(cls.admin_engine.dispose)
        with cls.admin_engine.connect() as connection:
            if connection.scalar(text('SELECT current_database()')) != 'dkss_q02_ci':
                raise RuntimeError('Unexpected database')
            cls.server_version = connection.scalar(text('SHOW server_version'))
            connection.execute(text('CREATE SCHEMA "' + cls.schema + '"'))
        cls.addClassCleanup(cls.drop_private_schema)
        env = {'SECRET_KEY': 'q02-postgres-test-only', 'DATABASE_URL': url, 'RENDER': '',
               'OPENAI_API_KEY': '', 'SMTP_HOST': '', 'S3_BUCKET_NAME': '',
               'VAPID_PRIVATE_KEY': '', 'VAPID_PUBLIC_KEY': '',
               'AWS_EC2_METADATA_DISABLED': 'true', 'RATELIMIT_STORAGE_URI': 'memory://'}
        with patch.dict(os.environ, env):
            cls.app = create_app({'TESTING': True, 'MFA_ENABLED': True, 'WTF_CSRF_ENABLED': False,
                'SQLALCHEMY_ENGINE_OPTIONS': {
                    'pool_size': 12, 'max_overflow': 0, 'pool_timeout': 15,
                    'connect_args': {'options': '-csearch_path=' + cls.schema
                                     + ' -cstatement_timeout=30000 -clock_timeout=20000'}}})
        limiter.enabled = False
        with cls.app.app_context():
            cls.db.create_all()
            cls.engine = cls.db.engine
        cls.addClassCleanup(cls.engine.dispose)
        cls.password = 'Q02-Postgres-Only-742!'
        cls.password_hash = generate_password_hash(cls.password)
        cls.pid_lock = threading.Lock()
        cls.backend_pids = set()

        def observe_user_read(connection, cursor, statement, parameters, context, executemany):
            # Observe real concurrent request connections without changing SQL or locks.
            if 'FROM "user"' in statement:
                with cls.pid_lock:
                    cls.backend_pids.add(cursor.connection.get_backend_pid())
        event.listen(cls.engine, 'before_cursor_execute', observe_user_read)
        cls.addClassCleanup(event.remove, cls.engine, 'before_cursor_execute', observe_user_read)
        print('Q02_POSTGRES_SERVER:', cls.server_version)

    @classmethod
    def drop_private_schema(cls):
        from sqlalchemy import text
        # Name generated above, never taken from user input or a configured schema.
        with cls.admin_engine.connect() as connection:
            connection.execute(text('DROP SCHEMA "' + cls.schema + '" CASCADE'))

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        self.addCleanup(self.db.session.remove)
        self.companies = ['A_' + uuid.uuid4().hex[:12], 'B_' + uuid.uuid4().hex[:12]]
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        m = self.models
        for company in self.companies:
            self.db.session.add(m.Company(company_code=company, company_name=company, active=True))
            self.db.session.add(m.User(company_code=company, username='same', role='user',
                password=self.password_hash, last_name='Synthetic', first_name='User',
                password_changed_at=stamp, email_address='q02@example.invalid'))
        self.db.session.commit()
        self.codes = {}
        def deliver(user, code):
            self.codes[user.company_code] = code
            return True
        mocked = patch.object(self.auth, 'send_mfa_code_email', side_effect=deliver)
        mocked.start()
        self.addCleanup(mocked.stop)

    def pending(self, company):
        client = self.app.test_client()
        response = client.post('/login', data={'company_code': company, 'username': 'same',
                                               'password': self.password})
        try:
            self.assertEqual((response.status_code, response.location), (302, '/mfa'))
        finally:
            response.close()
        return client, self.codes[company]

    def clone(self, client):
        copied = self.app.test_client()
        cookie_name = self.app.config['SESSION_COOKIE_NAME']
        copied.set_cookie(cookie_name, client.get_cookie(cookie_name).value)
        return copied

    def submit(self, client, code):
        response = client.post('/mfa', data={'code': code})
        try:
            status = response.status_code
        finally:
            response.close()
        with client.session_transaction() as session:
            authenticated = (session.get('company_code'), session.get('username'))
        return status, authenticated

    def together(self, pairs):
        barrier = threading.Barrier(len(pairs), timeout=20)
        with self.pid_lock:
            self.backend_pids.clear()
        def run(pair):
            barrier.wait()
            return self.submit(*pair)
        with ThreadPoolExecutor(max_workers=len(pairs)) as executor:
            results = list(executor.map(run, pairs))
        self.assertGreaterEqual(len(self.backend_pids), 2,
            'Concurrency evidence requires at least two real PostgreSQL backend connections')
        self.assertTrue(all(status in (200, 302) for status, _ in results))
        self.db.session.expire_all()
        print('Q02_POSTGRES_PARALLEL:', len(pairs), 'requests;', len(self.backend_pids), 'backends')
        return [authenticated for _, authenticated in results]

    def user(self, company):
        self.db.session.expire_all()
        return self.models.User.query.filter_by(company_code=company, username='same').one()

    def logs(self, company, action):
        self.db.session.expire_all()
        return self.models.AuditLog.query.filter_by(company_code=company, username='same',
                                                    action=action).order_by(self.models.AuditLog.id).all()

    def test_same_code_authenticates_exactly_one_of_eight_parallel_clients(self):
        company = self.companies[0]
        pending, code = self.pending(company)
        clients = [self.clone(pending) for _ in range(8)]
        results = self.together([(client, code) for client in clients])
        self.assertEqual(results.count((company, 'same')), 1)
        self.assertEqual(sum(username is not None for _, username in results), 1)
        self.assertIsNone(self.user(company).mfa_code_hash)
        self.assertEqual(len(self.logs(company, 'login_success')), 1)

    def test_eight_parallel_failures_record_only_five_and_invalidate_once(self):
        company = self.companies[0]
        pending, code = self.pending(company)
        wrong = '000000' if code != '000000' else '111111'
        clients = [self.clone(pending) for _ in range(8)]
        results = self.together([(client, wrong) for client in clients])
        self.assertTrue(all(username is None for _, username in results))
        failures = self.logs(company, 'mfa_failed')
        self.assertEqual(len(failures), 5)
        self.assertEqual([int(re.search(r'MFA認証失敗 (\d+)回目', row.detail).group(1))
                          for row in failures], [1, 2, 3, 4, 5])
        self.assertEqual(len(self.logs(company, 'mfa_code_invalidated')), 1)
        self.assertIsNone(self.user(company).mfa_code_hash)
        _, authenticated = self.submit(self.clone(pending), code)
        self.assertIsNone(authenticated[1])

    def test_two_parallel_failures_after_four_failures_stop_at_five(self):
        company = self.companies[0]
        pending, code = self.pending(company)
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(4):
            self.submit(self.clone(pending), wrong)
        self.assertEqual(len(self.logs(company, 'mfa_failed')), 4)
        results = self.together([(self.clone(pending), wrong) for _ in range(2)])
        self.assertTrue(all(username is None for _, username in results))
        self.assertEqual(len(self.logs(company, 'mfa_failed')), 5)
        self.assertEqual(len(self.logs(company, 'mfa_code_invalidated')), 1)
        self.assertIsNone(self.user(company).mfa_code_hash)

    def test_same_username_in_two_companies_consumes_each_code_once(self):
        pairs = []
        for company in self.companies:
            pending, code = self.pending(company)
            pairs.extend((self.clone(pending), code) for _ in range(4))
        results = self.together(pairs)
        for company in self.companies:
            self.assertEqual(results.count((company, 'same')), 1)
            self.assertEqual(len(self.logs(company, 'login_success')), 1)
            self.assertIsNone(self.user(company).mfa_code_hash)


if __name__ == '__main__':
    unittest.main(verbosity=2)
