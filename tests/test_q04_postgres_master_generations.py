"""Generation-aware real master HTTP routes and legacy migration on private PostgreSQL."""
import os
import unittest
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from dkss_app.master_generations import upgrade_storage

import q04_pg_helpers as shared
from test_q04_master_generations import GenerationCases
from test_q04_master_generation_storage import StorageCases, legacy_fixture


class PostgresMasterGenerationTests(GenerationCases, shared.PrivatePostgresCase):
    force_id_reuse = True

    def setUp(self):
        super().setUp()
        self.models = self.m
        self.foreign_controls()


class PostgresMasterGenerationStorageTests(StorageCases, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ.get('Q04_POSTGRES_TEST_URL', '')
        if not cls.url:
            if os.environ.get('Q04_REQUIRE_POSTGRES') == '1':
                raise RuntimeError('Dedicated Q04 PostgreSQL required')
            raise unittest.SkipTest('Dedicated Q04 PostgreSQL required')
        parsed = make_url(cls.url)
        if (parsed.host not in {'127.0.0.1', 'localhost', '::1'} or parsed.database != 'dkss_q04_ci'
                or parsed.get_backend_name() != 'postgresql' or parsed.query):
            raise RuntimeError('Only disposable loopback dkss_q04_ci is allowed')

    def setUp(self):
        self.engine = create_engine(self.url)
        self.addCleanup(self.engine.dispose)
        self.schema = 'q04_generations_' + uuid.uuid4().hex
        with self.engine.begin() as c: c.execute(text('CREATE SCHEMA "' + self.schema + '"'))
        self.addCleanup(self.drop_schema)
        legacy_fixture(self.engine, self.schema)

    def drop_schema(self):
        with self.engine.begin() as c: c.execute(text('DROP SCHEMA "' + self.schema + '" CASCADE'))

    def test_existing_reader_times_out_migration_lock_without_partial_changes(self):
        columns, before = self.columns(), self.rows()
        with self.engine.begin() as reader:
            reader.execute(text(f'LOCK TABLE "{self.schema}".office IN ACCESS SHARE MODE'))
            with self.assertRaises(OperationalError) as failure:
                upgrade_storage(self.engine, self.schema)
            self.assertEqual(failure.exception.orig.pgcode, '55P03')
        self.assertEqual(self.columns(), columns)
        self.assertEqual(self.rows(), before)
