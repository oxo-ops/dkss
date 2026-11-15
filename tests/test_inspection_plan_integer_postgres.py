"""Inspection integer route checks on loopback disposable PostgreSQL only."""
import os
import re
import uuid
import unittest
from unittest.mock import patch
from test_inspection_plan_integer_inputs import InspectionIntegerInputs as _Base


class InspectionIntegerPostgres(_Base):
    @classmethod
    def setUpClass(cls):
        url = os.environ.get('INSPECTION_POSTGRES_TEST_URL', '')
        if not url:
            if os.environ.get('INSPECTION_REQUIRE_POSTGRES') == '1':
                raise RuntimeError('Inspection PostgreSQL configuration is required')
            raise unittest.SkipTest('Inspection PostgreSQL runs in its dedicated CI job')
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        parsed = make_url(url)
        if (parsed.get_backend_name() != 'postgresql' or parsed.query
                or parsed.host not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.database != 'dkss_inspection_ci'):
            raise RuntimeError('Only loopback disposable database dkss_inspection_ci is permitted')
        cls.schema = 'inspection_targets_' + uuid.uuid4().hex
        assert re.fullmatch(r'inspection_targets_[0-9a-f]{32}', cls.schema)
        cls.admin_engine = create_engine(url, isolation_level='AUTOCOMMIT')
        cls.addClassCleanup(cls.admin_engine.dispose)
        with cls.admin_engine.connect() as connection:
            if connection.scalar(text('SELECT current_database()')) != 'dkss_inspection_ci':
                raise RuntimeError('Unexpected database')
            connection.execute(text('CREATE SCHEMA "' + cls.schema + '"'))
            print('INSPECTION_POSTGRES_SERVER:', connection.scalar(text('SHOW server_version')))
        cls.addClassCleanup(cls.drop_private_schema)
        from dkss_app import create_app
        from application_fixture import ApplicationFixture
        env = dict(SECRET_KEY='inspection-private-test-only', DATABASE_URL=url, RENDER='',
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

    def test_int32_columns_and_larger_comparison_parameters(self):
        from sqlalchemy import text
        for table, column in (('vehicle', 'id'), ('vehicle_inspection_plan', 'id'),
                              ('vehicle_inspection_plan', 'version')):
            kind = self.m.db.session.execute(text(
                "SELECT data_type FROM information_schema.columns WHERE table_schema=:schema "
                "AND table_name=:table AND column_name=:column"),
                dict(schema=self.schema, table=table, column=column)).scalar_one()
            self.assertEqual(kind, 'integer')
        for value in (2 ** 31, 2 ** 63 - 1):
            with self.subTest(value=value):
                response = self.client.get(f'/api/vehicle/inspection-plans?detail=1&vehicle_id={value}')
                self.assertEqual(response.status_code, 404)
                change = self.change(); change['vehicle_record_id'] = value
                response = self.client.post('/api/vehicle/inspection-plans/preview', json={'changes': [change]})
                self.assertEqual(response.status_code, 404)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)


del _Base
