"""Q10 opt-in PostgreSQL fixture: owned schema in a marked loopback test DB."""
import os
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


class PostgresFixture:
    @classmethod
    def setUpClass(cls):
        url = os.environ.get('Q10_POSTGRES_TEST_URL', '')
        if not url:
            if os.environ.get('Q10_REQUIRE_POSTGRES') == '1':
                raise RuntimeError('Q10_POSTGRES_TEST_URL required; no SQLite fallback')
            raise unittest.SkipTest('Dedicated Q10 PostgreSQL fixture required')
        parsed = make_url(url)
        if (parsed.get_backend_name() != 'postgresql' or parsed.host not in ('127.0.0.1', 'localhost', '::1')
                or parsed.database != 'dkss_q10_ci'):
            raise RuntimeError('Only loopback dkss_q10_ci is allowed')
        cls.schema = 'q10_' + uuid4().hex
        cls.admin_engine = create_engine(url, isolation_level='AUTOCOMMIT')
        cls.addClassCleanup(cls.admin_engine.dispose)
        with cls.admin_engine.connect() as connection:
            marker = connection.scalar(text("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()"))
            if marker != 'Q10_SYNTHETIC_ONLY':
                raise RuntimeError('Refusing unmarked database')
            cls.server_version = connection.scalar(text('SHOW server_version'))
            connection.execute(text('CREATE SCHEMA "' + cls.schema + '"'))

        def cleanup_schema():
            with cls.admin_engine.connect() as connection:
                connection.execute(text('DROP SCHEMA "' + cls.schema + '" CASCADE'))
        cls.addClassCleanup(cleanup_schema)
        from dkss_app import create_app, models
        from dkss_app.extensions import db, limiter
        from application_fixture import ApplicationFixture
        cls.temp = tempfile.TemporaryDirectory(prefix='q10-pg-assets-')
        cls.addClassCleanup(cls.temp.cleanup)
        env = dict(RENDER='', DATABASE_URL=url, SECRET_KEY='q10-pg-synthetic-only',
                   MFA_ENABLED='false', AWS_EC2_METADATA_DISABLED='true', OPENAI_API_KEY='',
                   SMTP_HOST='', S3_BUCKET_NAME='', VAPID_PRIVATE_KEY='', VAPID_PUBLIC_KEY='',
                   DOCUMENT_IMPORT_WORKER_ENABLED='0', RATELIMIT_STORAGE_URI='memory://')
        environment = patch.dict(os.environ, env)
        environment.start()
        cls.addClassCleanup(environment.stop)
        cls.app = create_app(dict(TESTING=True, WTF_CSRF_ENABLED=False, MFA_ENABLED=False,
            SQLALCHEMY_ENGINE_OPTIONS={'connect_args': {'options': '-csearch_path=' + cls.schema + ' -cstatement_timeout=15000 -clock_timeout=10000'}}))
        cls.db, cls.models = db, models
        cls.m = ApplicationFixture(cls.app)
        limiter.enabled = False
        with cls.app.app_context():
            cls.engine = db.engine
            assert cls.engine.dialect.name == 'postgresql'
            with cls.engine.connect() as connection:
                assert connection.scalar(text('SELECT current_schema()')) == cls.schema
        cls.addClassCleanup(cls.engine.dispose)
        print('Q10_POSTGRES:', cls.server_version, cls.schema, flush=True)

    @classmethod
    def tearDownClass(cls):
        # addClassCleanup runs even when setup/cases fail, in reverse order.
        pass
