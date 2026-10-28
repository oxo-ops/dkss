"""Explicit disposable localhost PostgreSQL only; never falls back to DATABASE_URL."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from test_q08_account_identity import AccountIdentityTests as _Identity
from test_q08_vehicle_null_capacity import VehicleNullCapacityTests as _Capacity


class DisposablePostgres:
    @classmethod
    def setUpClass(cls):
        raw = os.environ.get('Q08_POSTGRES_TEST_URL')
        if not raw:
            raise unittest.SkipTest('Q08_POSTGRES_TEST_URL must explicitly select a disposable localhost database')
        url = make_url(raw)
        if url.host not in {'127.0.0.1','localhost'} or not (url.database or '').startswith('dkss_q08'):
            raise RuntimeError('Q08 tests require a disposable localhost dkss_q08 database')
        cls.admin = create_engine(url)
        cls.schema = 'q08_' + uuid4().hex
        with cls.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        from dkss_app import create_app
        from application_fixture import ApplicationFixture
        scoped = url.update_query_dict({'options':'-csearch_path='+cls.schema})
        try:
            with patch.dict(os.environ, {'SECRET_KEY':'q08-postgres-only','ITC_INITIAL_PASSWORD':'Synthetic-Only-742!',
                'DATABASE_URL':scoped.render_as_string(hide_password=False),'RENDER':'','MFA_ENABLED':'false',
                'OPENAI_API_KEY':'','SMTP_HOST':'','S3_BUCKET_NAME':'','VAPID_PRIVATE_KEY':'','VAPID_PUBLIC_KEY':'',
                'AWS_EC2_METADATA_DISABLED':'true'}):
                cls.m = ApplicationFixture(create_app(initialize_database=True))
            cls.m.app.config.update(TESTING=True,WTF_CSRF_ENABLED=False)
            cls.m.limiter.enabled = False
        except BaseException:
            cls.drop_schema()
            raise

    @classmethod
    def drop_schema(cls):
        with cls.admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{cls.schema}" CASCADE'))
        cls.admin.dispose()

    @classmethod
    def tearDownClass(cls):
        with cls.m.app.app_context():
            cls.m.db.session.remove()
            cls.m.db.engine.dispose()
        cls.drop_schema()


class PostgresAccountIdentityTests(DisposablePostgres, _Identity):
    def test_notification_writer_overlapping_delete_and_reregistration_keeps_old_owner(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        old = self.user()
        identity = old.account_identity
        ready, release = threading.Event(), threading.Event()
        m = self.m

        def writer():
            with m.app.app_context():
                try:
                    notice = m.Notification(company_code='TEST',target_user='Person A',
                        target_username='retired',owner_identity=identity,title='Q08_RACING_OLD_MESSAGE')
                    m.db.session.add(notice)
                    m.db.session.flush()
                    ready.set()
                    if not release.wait(15): raise RuntimeError('Writer was not released')
                    m.db.session.commit()
                    return notice.id
                finally:
                    m.db.session.remove()

        with ThreadPoolExecutor(max_workers=1) as pool:
            writing = pool.submit(writer)
            try:
                self.assertTrue(ready.wait(15))
                new = self.replace_person(old)
            finally:
                release.set()
            ident = writing.result(timeout=15)
        m.db.session.expire_all()
        row = m.Notification.query.filter_by(id=ident).one()
        self.assertEqual(row.owner_identity, identity)
        self.assertEqual(self.client_for(new).post(f'/api/notifications/{ident}/read').status_code,404)

    def test_postgres_legacy_migration_keeps_notifications_and_audits_unbound(self):
        from dkss_app.account_identity import upgrade_account_identity
        db = self.m.db
        db.session.remove()
        db.drop_all()
        with db.engine.begin() as c:
            for statement in ['CREATE TABLE "user" (id INTEGER PRIMARY KEY, username TEXT)',
                'CREATE TABLE notification (id INTEGER PRIMARY KEY, company_code TEXT, message TEXT)',
                'CREATE TABLE news (id INTEGER PRIMARY KEY)',
                'CREATE TABLE vehicle_maintenance_record_event (id INTEGER PRIMARY KEY)',
                'CREATE TABLE push_subscription (id INTEGER PRIMARY KEY, company_code TEXT)',
                'CREATE TABLE audit_log (id INTEGER PRIMARY KEY, detail TEXT)']:
                c.execute(text(statement))
            c.execute(text('INSERT INTO "user" VALUES (1, \'reused\')'))
            c.execute(text("INSERT INTO notification VALUES (1, 'TEST', 'OLD PRIVATE MESSAGE')"))
            c.execute(text("INSERT INTO audit_log VALUES (1, 'OLD AUDIT')"))
        upgrade_account_identity()
        with db.engine.connect() as c:
            identity = c.scalar(text('SELECT account_identity FROM "user"'))
            self.assertTrue(identity)
            self.assertEqual(c.execute(text('SELECT message,owner_identity FROM notification')).one(),('OLD PRIVATE MESSAGE',None))
            self.assertEqual(c.execute(text('SELECT detail,actor_identity FROM audit_log')).one(),('OLD AUDIT',None))
        upgrade_account_identity()
        with db.engine.connect() as c:
            self.assertEqual(c.scalar(text('SELECT account_identity FROM "user"')),identity)


class PostgresNullCapacityTests(DisposablePostgres, _Capacity):
    pass
