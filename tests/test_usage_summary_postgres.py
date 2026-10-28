"""Opt-in real PostgreSQL; only a dedicated loopback DB/private schema is used."""
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_usage_summary as fixtures
from dkss_app import audit


class PostgresUsageSummaryTests(fixtures.UsageSummaryTests):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        url = os.environ.get('Q05_USAGE_POSTGRES_URL', '')
        if not url:
            if os.environ.get('Q05_USAGE_REQUIRE_POSTGRES') == '1':
                raise RuntimeError('Dedicated PostgreSQL URL required')
            raise unittest.SkipTest('Dedicated PostgreSQL job only')
        parsed = make_url(url)
        if (parsed.get_backend_name() != 'postgresql' or parsed.host not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.database != 'dkss_q05_ci'):
            raise RuntimeError('Only loopback disposable dkss_q05_ci is allowed')
        cls.schema = 'q05_usage_' + uuid.uuid4().hex
        cls.admin_engine = create_engine(url, isolation_level='AUTOCOMMIT')
        cls.addClassCleanup(cls.admin_engine.dispose)
        with cls.admin_engine.connect() as conn:
            conn.execute(text('CREATE SCHEMA "' + cls.schema + '"'))
            print('Q05_USAGE_SERVER:', conn.scalar(text('SHOW server_version')))
            if conn.scalar(text('SHOW transaction_isolation')) != 'read committed':
                raise RuntimeError('Acceptance requires the application default READ COMMITTED')
        cls.addClassCleanup(cls.drop_schema)
        from dkss_app import create_app
        from application_fixture import ApplicationFixture
        with patch.dict(os.environ, dict(SECRET_KEY='usage-test-only', DATABASE_URL=url,
                RENDER='', OPENAI_API_KEY='', SMTP_HOST='', S3_BUCKET_NAME='',
                VAPID_PRIVATE_KEY='', VAPID_PUBLIC_KEY='', AWS_EC2_METADATA_DISABLED='true',
                RATELIMIT_STORAGE_URI='memory://')):
            cls.m = ApplicationFixture(create_app(dict(TESTING=True, MFA_ENABLED=False,
                WTF_CSRF_ENABLED=False, SQLALCHEMY_ENGINE_OPTIONS=dict(pool_size=12, max_overflow=0,
                    connect_args={'options': '-csearch_path=' + cls.schema + ' -ctimezone=UTC -cstatement_timeout=20000'}))))
        cls.m.limiter.enabled = False
        with cls.m.app.app_context():
            cls.m.db.create_all()
            cls.addClassCleanup(cls.m.db.engine.dispose)

    @classmethod
    def tearDownClass(cls):
        with cls.m.app.app_context():
            cls.m.db.session.remove()

    @classmethod
    def drop_schema(cls):
        from sqlalchemy import text
        with cls.admin_engine.connect() as conn:
            conn.execute(text('DROP SCHEMA "' + cls.schema + '" CASCADE'))

    def parallel(self, companies, *, existing=False, http=False):
        from sqlalchemy import event
        from identity_fixture import identity_for
        m = self.m
        if 'OTHER' in companies:
            m.db.session.add(m.Company(company_code='OTHER', company_name='Other'))
        if existing:
            m.db.session.add_all([m.CompanyUsageSummary(company_code=c, login_count=42)
                                 for c in set(companies)])
        m.db.session.commit()
        identity = identity_for('TEST', 'admin', m.app)
        stamp = m.User.query.filter_by(company_code='TEST', username='admin').one().password_changed_at
        start = threading.Barrier(len(companies))
        initial_reads = threading.Barrier(len(companies))
        seen, pids, lock = set(), set(), threading.Lock()
        def synchronize(conn, cursor, statement, parameters, context, many):
            with lock:
                pids.add(cursor.connection.get_backend_pid())
            if existing or 'from company_usage_summary' not in statement.lower():
                return
            tid = threading.get_ident()
            with lock:
                first = tid not in seen
                seen.add(tid)
            if first:
                initial_reads.wait(timeout=15)
        engine = m.db.engine
        event.listen(engine, 'after_cursor_execute', synchronize)
        def work(item):
            index, company = item
            try:
                if http:
                    client = m.app.test_client()
                    with client.session_transaction() as state:
                        state.update(account_identity=identity, company_code='TEST', username='admin',
                                     role='admin', password_changed_at=stamp)
                    start.wait(timeout=15)
                    return client.get('/').status_code
                with m.app.app_context():
                    if existing:
                        # Load deliberately stale ORM state before another request commits.
                        stale = m.CompanyUsageSummary.query.filter_by(company_code=company).one()
                        self.assertEqual(stale.login_count, 42)
                    start.wait(timeout=15)
                    self.log(company)
                    audit.update_company_usage_summary(company, increment_login=(not existing or index % 2 == 0))
                    m.db.session.commit()
                    return 200
            except Exception as error:
                return type(error).__name__
        try:
            with ThreadPoolExecutor(max_workers=len(companies)) as pool:
                results = list(pool.map(work, enumerate(companies)))
        finally:
            event.remove(engine, 'after_cursor_execute', synchronize)
        self.assertEqual(results, [200] * len(companies))
        self.assertGreaterEqual(len(pids), 2)
        m.db.session.expire_all()
        for company in set(companies):
            row = self.summary(company)
            expected = (42 + sum(i % 2 == 0 for i,c in enumerate(companies) if c == company)
                        if existing else 0 if http else companies.count(company))
            self.assertEqual(row.login_count, expected)
            self.assertEqual(row.user_count, 1 if company == 'TEST' else 0)
            self.assertEqual(row.vehicle_count, 1 if company == 'TEST' else 0)
            self.assertEqual(m.AuditLog.query.filter_by(company_code=company).count(),
                             0 if http else companies.count(company))
        self.assertEqual(m.CompanyUsageSummary.query.count(), len(set(companies)))
        self.assertEqual(m.AuditLog.query.count(), 0 if http else len(companies))
        print('Q05_USAGE_PARALLEL:', len(companies), 'backends:', len(pids))

    def test_initial_parallel_login_increments_and_audit_are_not_lost(self):
        self.parallel(['TEST'] * 8)

    def test_initial_parallel_dashboard_returns_200(self):
        self.parallel(['TEST'] * 8, http=True)

    def test_existing_parallel_login_and_read_refresh_stale_state(self):
        self.parallel(['TEST'] * 8, existing=True)

    def test_initial_parallel_companies_remain_independent(self):
        self.parallel(['TEST', 'OTHER'] * 4)

    def test_uncommitted_creator_rollback_allows_waiter_to_create_once(self):
        from sqlalchemy import event
        m = self.m
        reads = threading.Barrier(2)
        created, attempted = threading.Event(), threading.Event()
        role = threading.local()
        seen, lock = set(), threading.Lock()
        def after_read(conn, cursor, statement, parameters, context, many):
            if 'from company_usage_summary' not in statement.lower():
                return
            with lock:
                first = role.name not in seen
                seen.add(role.name)
            if first:
                reads.wait(timeout=15)
        def before_insert(conn, cursor, statement, parameters, context, many):
            if statement.lower().startswith('insert into company_usage_summary') and role.name == 'waiter':
                self.assertTrue(created.wait(timeout=15))
                attempted.set()
        engine = m.db.engine
        event.listen(engine, 'after_cursor_execute', after_read)
        event.listen(engine, 'before_cursor_execute', before_insert)
        def request(name):
            role.name = name
            with m.app.app_context():
                self.log()
                audit.update_company_usage_summary('TEST', increment_login=True)
                if name == 'creator':
                    created.set()
                    self.assertTrue(attempted.wait(timeout=15))
                    m.db.session.rollback()
                else:
                    m.db.session.commit()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(request, ['creator', 'waiter']))
        finally:
            event.remove(engine, 'after_cursor_execute', after_read)
            event.remove(engine, 'before_cursor_execute', before_insert)
        m.db.session.expire_all()
        self.assertEqual(m.CompanyUsageSummary.query.count(), 1)
        self.assertEqual(self.summary().login_count, 1)
        self.assertEqual(m.AuditLog.query.count(), 1)
