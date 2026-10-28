"""Actual read-only snapshots and failed concurrent indexes in owned Q04 schemas."""
import os
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from test_q04_master_preflight import fixture
from tools.q04_master_preflight import diagnose, read_only_connection
import q04_pg_helpers as shared


class ApplicationMasterPreflightTests(shared.PrivatePostgresCase):
    def test_real_application_schema_is_checked_without_bootstrap_or_changes(self):
        with self.app.app_context():
            actor = self.m.User.query.filter_by(company_code=self.company, username='admin').one()
            actor.office = 'Missing-preflight-office'
            self.db.session.commit()
        before = self.snapshot(self.company), self.snapshot(self.other)
        with patch('dkss_app.database.init_db', side_effect=AssertionError('No bootstrap in preflight')):
            result = diagnose(os.environ['Q04_POSTGRES_TEST_URL'], 'dkss_q04_ci', schema=self.schema)
        self.assertTrue(result['complete'], result)
        self.assertEqual(result['status'], 'issues', result)
        self.assertTrue(any(f['code'] == 'missing_reference' and f['table'] == 'user'
                            and any(s['company_code'] == self.company for s in f['samples'])
                            for f in result['findings']), result)
        self.assertEqual((self.snapshot(self.company), self.snapshot(self.other)), before)


class PostgresMasterPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ.get('Q04_POSTGRES_TEST_URL', '')
        if not cls.url:
            if os.environ.get('Q04_REQUIRE_POSTGRES') == '1':
                raise RuntimeError('Dedicated Q04 PostgreSQL URL is required')
            raise unittest.SkipTest('Dedicated Q04 PostgreSQL required')
        url = make_url(cls.url)
        if (url.get_backend_name() != 'postgresql' or url.database != 'dkss_q04_ci'
                or url.host not in {'localhost', '127.0.0.1', '::1'} or url.query):
            raise RuntimeError('Only owned loopback dkss_q04_ci is allowed')

    def setUp(self):
        self.schema = 'q04_preflight_' + uuid.uuid4().hex
        self.engine = create_engine(self.url)
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as c:
            c.execute(text('CREATE SCHEMA "' + self.schema + '"'))
        self.addCleanup(self.drop_schema)
        fixture(self.engine, self.schema)

    def drop_schema(self):
        with self.engine.begin() as c:
            c.execute(text('DROP SCHEMA "' + self.schema + '" CASCADE'))

    def report(self):
        return diagnose(self.url, 'dkss_q04_ci', schema=self.schema)

    def test_server_enforces_readonly_and_snapshot_isolation(self):
        with read_only_connection(self.url, 'dkss_q04_ci') as c:
            self.assertEqual(c.scalar(text('SHOW transaction_read_only')), 'on')
            self.assertEqual(c.scalar(text('SHOW transaction_isolation')), 'repeatable read')
            self.assertEqual(c.scalar(text(f'SELECT count(*) FROM "{self.schema}".office')), 2)
            with self.engine.begin() as writer:
                writer.execute(text(f"INSERT INTO \"{self.schema}\".office(id,company_code,name) VALUES(3,'A','Later')"))
            self.assertEqual(c.scalar(text(f'SELECT count(*) FROM "{self.schema}".office')), 2)
            with self.assertRaises(DBAPIError) as failure:
                c.execute(text(f'DELETE FROM "{self.schema}".office'))
            self.assertEqual(failure.exception.orig.pgcode, '25006')
        self.assertEqual(self.report()['status'], 'ok')

    def test_failed_concurrent_index_and_duplicates_reported_together_without_repair(self):
        prefix = '"' + self.schema + '".'
        with self.engine.begin() as c:
            c.execute(text('DROP INDEX ' + prefix + 'uq_office_company_name'))
            c.execute(text(f"INSERT INTO {prefix}office(id,company_code,name) VALUES(3,'A','Valid')"))
        with self.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
            with self.assertRaises(IntegrityError):
                c.execute(text('CREATE UNIQUE INDEX CONCURRENTLY uq_office_company_name ON '
                               + prefix + 'office(company_code,name)'))
        with self.engine.connect() as c:
            before = c.scalar(text('SELECT to_regclass(:name)::oid'),
                              {'name': prefix + 'uq_office_company_name'})
        result = self.report()
        self.assertTrue(result['complete'])
        codes = {f['code'] for f in result['findings']}
        self.assertIn('duplicate_name', codes)
        self.assertIn('index_invalid', codes)
        invalid = next(f for f in result['findings'] if f['code'] == 'index_invalid')
        self.assertFalse(invalid['actual']['indisvalid'])
        with self.engine.connect() as c:
            self.assertEqual(c.scalar(text('SELECT to_regclass(:name)::oid'),
                             {'name': prefix + 'uq_office_company_name'}), before)
            self.assertEqual(c.scalar(text('SELECT count(*) FROM ' + prefix + 'office')), 3)

    def test_rls_and_wrong_schema_never_claim_complete_coverage(self):
        with self.engine.begin() as c:
            c.execute(text(f'ALTER TABLE "{self.schema}".office ENABLE ROW LEVEL SECURITY'))
        result = self.report()
        self.assertFalse(result['complete'])
        self.assertIn('rls_coverage_unverified', [f['code'] for f in result['findings']])
        empty = diagnose(self.url, 'dkss_q04_ci', schema=self.schema + '_absent')
        self.assertFalse(empty['complete'])
        self.assertEqual(empty['status'], 'incomplete')

    def test_clean_schema_and_foreign_company_reference_are_separate(self):
        self.assertEqual(self.report()['status'], 'ok')
        with self.engine.begin() as c:
            c.execute(text(f"UPDATE \"{self.schema}\".vehicle SET office='Foreign-only' WHERE company_code='A'"))
        result = self.report()
        issue = next(f for f in result['findings'] if f['code'] == 'missing_reference')
        self.assertEqual(issue['master'], 'office')
        self.assertEqual(issue['samples'][0]['company_code'], 'A')
