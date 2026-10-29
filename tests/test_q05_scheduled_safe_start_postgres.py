"""Q05 routes and parallel readers on an explicitly disposable PostgreSQL DB."""
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from unittest.mock import patch
import unittest

import test_q05_scheduled_safe_start as fixtures
from test_q05_inspection_dates import clock_at


class TextInside(HTMLParser):
    def __init__(self, predicate):
        super().__init__()
        self.predicate, self.depth, self.parts = predicate, 0, []

    def handle_starttag(self, tag, attrs):
        if self.depth or self.predicate(dict(attrs)):
            if tag not in {'br', 'img', 'input', 'hr', 'meta', 'link'}:
                self.depth += 1

    def handle_endtag(self, tag):
        if self.depth and tag not in {'br', 'img', 'input', 'hr', 'meta', 'link'}:
            self.depth -= 1

    def handle_data(self, value):
        if self.depth:
            self.parts.append(value)

    @classmethod
    def text(cls, html, predicate):
        parser = cls(predicate)
        parser.feed(html)
        return ' '.join(' '.join(parser.parts).split())


class PostgresScheduledSafeStartTests(fixtures.ScheduledSafeStartTests):
    @classmethod
    def setUpClass(cls):
        url = os.environ.get('Q05_POSTGRES_TEST_URL', '')
        if not url:
            if os.environ.get('Q05_REQUIRE_POSTGRES') == '1':
                raise RuntimeError('Q05 PostgreSQL configuration is required')
            raise unittest.SkipTest('Q05 PostgreSQL runs in its dedicated CI job')
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        parsed = make_url(url)
        if (parsed.get_backend_name() != 'postgresql'
                or parsed.host not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.database != 'dkss_q05_ci'):
            raise RuntimeError('Only loopback disposable database dkss_q05_ci is permitted')
        cls.schema = 'q05_scheduled_' + uuid.uuid4().hex
        assert re.fullmatch(r'q05_scheduled_[0-9a-f]{32}', cls.schema)
        cls.admin_engine = create_engine(url, isolation_level='AUTOCOMMIT')
        cls.addClassCleanup(cls.admin_engine.dispose)
        with cls.admin_engine.connect() as connection:
            if connection.scalar(text('SELECT current_database()')) != 'dkss_q05_ci':
                raise RuntimeError('Unexpected database')
            connection.execute(text('CREATE SCHEMA "' + cls.schema + '"'))
            print('Q05_POSTGRES_SERVER:', connection.scalar(text('SHOW server_version')))
        cls.addClassCleanup(cls.drop_private_schema)
        from dkss_app import create_app
        from application_fixture import ApplicationFixture
        env = dict(SECRET_KEY='q05-private-test-only', DATABASE_URL=url, RENDER='',
            OPENAI_API_KEY='', SMTP_HOST='', S3_BUCKET_NAME='', VAPID_PRIVATE_KEY='',
            VAPID_PUBLIC_KEY='', AWS_EC2_METADATA_DISABLED='true', RATELIMIT_STORAGE_URI='memory://')
        with patch.dict(os.environ, env):
            app = create_app(dict(TESTING=True, MFA_ENABLED=False, WTF_CSRF_ENABLED=False,
                SQLALCHEMY_ENGINE_OPTIONS=dict(pool_size=12, max_overflow=0, pool_timeout=20,
                    connect_args={'options': '-csearch_path=' + cls.schema
                                  + ' -ctimezone=UTC -cstatement_timeout=30000'})))
        cls.m = ApplicationFixture(app)
        cls.m.limiter.enabled = False
        with app.app_context():
            cls.m.db.create_all()
            cls.addClassCleanup(cls.m.db.engine.dispose)

    @classmethod
    def tearDownClass(cls):
        with cls.m.app.app_context():
            cls.m.db.session.remove()

    @classmethod
    def drop_private_schema(cls):
        from sqlalchemy import text
        with cls.admin_engine.connect() as connection:
            connection.execute(text('DROP SCHEMA "' + cls.schema + '" CASCADE'))

    def test_parallel_profiles_keep_labels_rankings_and_saved_values_isolated(self):
        self.parallel_profiles(initialize_usage=False)

    def test_parallel_profiles_with_initialized_usage_keep_the_same_display(self):
        self.parallel_profiles(initialize_usage=True)

    def parallel_profiles(self, *, initialize_usage):
        from dkss_app import common
        from identity_fixture import identity_for
        from sqlalchemy import event
        self.seed('2027-01-01')
        self.m.db.session.add(self.m.Company(company_code='OTHER', company_name='架空他社', active=True))
        self.m.db.session.add(self.m.Office(company_code='OTHER', name='Tokyo'))
        stamp = self.user.password_changed_at
        actors = [('TEST', 'admin', 'admin'), ('TEST', 'started', 'user'),
                  ('TEST', 'unset', 'user'), ('OTHER', 'admin', 'admin')]
        for company, username, role in actors[1:]:
            self.m.db.session.add(self.m.User(company_code=company, username=username,
                role=role, password='unused', password_changed_at=stamp,
                last_name='他社専用' if company == 'OTHER' else username, office='Tokyo'))
            start = ('2027-01-02' if company == 'OTHER' else
                     '2026-12-31' if username == 'started' else None)
            self.m.db.session.add(self.m.Driver(company_code=company, employee_id=username,
                role=role, name='他社専用' if company == 'OTHER' else username,
                office='Tokyo', safe_start_date=start, vehicles_json='[]'))
        self.m.db.session.commit()
        if initialize_usage:
            self.m.db.session.add_all([
                self.m.CompanyUsageSummary(company_code='TEST'),
                self.m.CompanyUsageSummary(company_code='OTHER'),
            ])
            self.m.db.session.commit()
        self.assertEqual(self.m.CompanyUsageSummary.query.count(), 2 if initialize_usage else 0)
        identities = {(company, name): identity_for(company, name, self.m.app)
                      for company, name, _ in actors}
        def snapshot():
            return [(r.id, r.safe_start_date) for r in self.m.Driver.query.order_by(self.m.Driver.id)]
        before = snapshot()
        pids, pid_lock = set(), threading.Lock()
        first_reads, first_read_barrier = set(), threading.Barrier(8)
        synchronize_first_wave = True
        def observe(conn, cursor, statement, parameters, context, many):
            with pid_lock:
                pids.add(cursor.connection.get_backend_pid())
        def synchronize_initial_summary_read(conn, cursor, statement, parameters, context, many):
            if initialize_usage or not synchronize_first_wave or 'from company_usage_summary' not in statement.lower():
                return
            thread_id = threading.get_ident()
            with pid_lock:
                first = thread_id not in first_reads
                first_reads.add(thread_id)
            if first:
                # The real SELECT has completed. Preserve the observed cold-start race.
                first_read_barrier.wait(timeout=20)
        engine = self.m.db.engine
        event.listen(engine, 'before_cursor_execute', observe)
        event.listen(engine, 'after_cursor_execute', synchronize_initial_summary_read)
        try:
            for instant, begun in [('2026-12-31T14:59:59+00:00', False),
                                    ('2026-12-31T15:00:00+00:00', True)]:
                # Only the cold wave may wait after SELECT. On the second wave,
                # FOR UPDATE intentionally serializes existing rows; waiting at
                # a SQL barrier while holding that lock would deadlock the test.
                synchronize_first_wave = not begun
                barrier = threading.Barrier(8)
                def read(actor):
                    company, username, role = actor
                    client = self.m.app.test_client()
                    with client.session_transaction() as session:
                        session.update(account_identity=identities[company, username],
                            company_code=company, username=username, role=role,
                            password_changed_at=stamp, name=username)
                    barrier.wait(timeout=20)
                    response = client.get('/')
                    return actor, response.status_code, response.get_data(as_text=True)
                with patch.object(common, 'datetime', clock_at(instant)):
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        results = list(pool.map(read, actors * 2))
                for (company, username, _), status, html in results:
                    self.assertEqual(status, 200)
                    card = TextInside.text(html, lambda a: {'summary-card', 'main'} <= set(a.get('class', '').split()))
                    self.assertIn('<h3 id="dashboard-reference-ranking">', html)
                    ranking = html.split('<h3 id="dashboard-reference-ranking">', 1)[1]
                    ranking = ranking.split('<h3 id="dashboard-reference-inspection">', 1)[0]
                    label = ('開始予定（2027/01/02）' if company == 'OTHER' else
                             '開始予定（2027/01/01）' if username == 'admin' and not begun else None)
                    if label:
                        self.assertIn(label, card)
                        self.assertNotIn('日', card)
                    elif username != 'unset':
                        self.assertIn(('1' if username == 'started' and begun else '0') + ' 日', card)
                    if company == 'TEST':
                        self.assertNotIn('他社専用', ranking)
                        if not begun:
                            self.assertNotIn('架空本人', ranking)
                    else:
                        self.assertIn('ランキング対象のドライバーがありません', ranking)
        finally:
            event.remove(engine, 'before_cursor_execute', observe)
            event.remove(engine, 'after_cursor_execute', synchronize_initial_summary_read)
        self.assertGreaterEqual(len(pids), 2, 'Parallel requests must use real independent DB connections')
        self.m.db.session.expire_all()
        self.assertEqual(snapshot(), before)
        self.assertEqual(self.m.CompanyUsageSummary.query.count(), 2)
        for company, users, vehicles in [('TEST', 3, 1), ('OTHER', 1, 0)]:
            row = self.m.CompanyUsageSummary.query.filter_by(company_code=company).one()
            self.assertEqual((row.user_count, row.vehicle_count, row.login_count,
                              row.checklist_result_count), (users, vehicles, 0, 0))
        print('Q05_PARALLEL_REQUESTS: 16; PostgreSQL backends:', len(pids))
