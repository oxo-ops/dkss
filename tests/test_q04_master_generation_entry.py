"""Only the new entry/guard boundaries; never run against an existing migration DB."""
import copy
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg2
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url

from dkss_app.master_generations import FIELD, upgrade_storage, validate_storage
from q04_entry_fixture import MemoryEvidence, approve, legacy_fixture, manifest_for
from tools import migration_entry as entry
from tools.migration_adapters.q04_master_generations import apply


class MasterGenerationHookTests(unittest.TestCase):
    def test_adapter_requires_guard_and_delegates_once(self):
        engine, guard = object(), lambda c, p: None
        with patch('dkss_app.master_generations.upgrade_storage', return_value={'synthetic': 1}) as core:
            self.assertEqual(apply(engine=engine, schema='explicit', target_guard=guard), {'synthetic': 1})
            core.assert_called_once_with(engine, 'explicit', target_guard=guard)
        for schema, callback in [('', guard), ('explicit', None)]:
            with self.assertRaises(ValueError): apply(engine=engine, schema=schema, target_guard=callback)

    def test_sqlite_hook_same_connection_and_optional_keyword_compatibility(self):
        engine = create_engine('sqlite://'); self.addCleanup(engine.dispose)
        legacy_fixture(engine, 'main')
        calls = []
        def guard(connection, phase):
            calls.append((connection, phase))
            connection.execute(text('SELECT 1'))
        upgrade_storage(engine, 'main', target_guard=guard)
        self.assertEqual([p for _, p in calls], ['CONNECTED', 'LOCKED'])
        self.assertIs(calls[0][0], calls[1][0])
        self.assertTrue(all(r == {'added_column': False, 'assigned': 0}
                            for r in upgrade_storage(engine, 'main').values()))

    def test_old_cli_still_rejects_nonproduction_guard_bypass(self):
        from tools.upgrade_master_generations import migration_engine
        for url, name in [('postgresql://example.invalid/db', 'db'),
                          ('postgresql://127.0.0.1/protected', 'protected'),
                          ('postgresql://127.0.0.1/q04_copy?host=other', 'q04_copy')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                migration_engine(url, name)


class PostgresMasterEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = os.environ.get('Q04_ENTRY_POSTGRES_URL', '')
        if not raw:
            if os.environ.get('Q04_ENTRY_REQUIRE_POSTGRES') == '1':
                raise RuntimeError('New isolated entry PostgreSQL is required')
            raise unittest.SkipTest('New isolated entry PostgreSQL not provided')
        u = make_url(raw)
        if (u.drivername not in {'postgresql', 'postgresql+psycopg2'}
                or u.host not in {'127.0.0.1', 'localhost', '::1'} or u.database != 'q04_entry_ci'
                or not u.port or u.query):
            raise RuntimeError('Only explicit loopback q04_entry_ci without URL overrides is allowed')
        cls.url = raw

    def setUp(self):
        self.engine = create_engine(self.url, isolation_level='READ COMMITTED',
            connect_args={'connect_timeout': 5, 'options': '-csearch_path=pg_catalog -cstatement_timeout=15000'})
        self.addCleanup(self.engine.dispose)
        self.schema = 'q04_entry_' + uuid4().hex
        self.other = self.schema + '_other'
        with self.engine.begin() as c:
            c.exec_driver_sql(f'CREATE SCHEMA "{self.schema}"')
            c.exec_driver_sql(f'CREATE SCHEMA "{self.other}"')
            c.exec_driver_sql(f'CREATE TABLE "{self.other}".sentinel (value integer)')
            c.exec_driver_sql(f'INSERT INTO "{self.other}".sentinel VALUES (42)')
        self.addCleanup(self.drop_own_schemas)
        legacy_fixture(self.engine, self.schema)
        self.evidence = MemoryEvidence()
        with self.engine.connect() as c:
            self.m = manifest_for(entry.snapshot_target(c, self.schema))

    def drop_own_schemas(self):
        with self.engine.begin() as c:
            c.exec_driver_sql(f'DROP SCHEMA "{self.schema}" CASCADE')
            c.exec_driver_sql(f'DROP SCHEMA "{self.other}" CASCADE')

    def execute(self, attempt=None):
        if attempt: self.m['attempt_id'] = attempt
        raw, approval = approve(self.m, self.evidence)
        return entry.execute_q04(engine=self.engine, manifest=raw, approval=approval, evidence=self.evidence)

    def assert_legacy(self):
        with self.engine.connect() as c:
            for table in entry.TABLES:
                self.assertNotIn(FIELD, {col['name'] for col in inspect(c).get_columns(table, schema=self.schema)})

    def assert_controls(self):
        with self.engine.connect() as c:
            self.assertEqual(c.scalar(text(f'SELECT value FROM "{self.other}".sentinel')), 42)
            self.assertEqual(c.execute(text(f'SELECT id,owner_identity FROM "{self.schema}".csv_owner_control ORDER BY id')).all(),
                [(1,None),(2,'11111111-1111-4111-8111-111111111111')])
            for name in entry.TABLES:
                self.assertEqual(c.execute(text(f'SELECT id,company_code,name,owner_identity FROM "{self.schema}"."{name}" ORDER BY id')).all(),
                    [(1,'A','A',None),(2,'B','B','11111111-1111-4111-8111-111111111111')])

    def before_lock(self, callback):
        done = []
        def listener(c, cursor, statement, parameters, context, many):
            if statement.startswith('LOCK TABLE ') and not done:
                done.append(True); callback(c)
        event.listen(self.engine, 'before_cursor_execute', listener)
        self.addCleanup(event.remove, self.engine, 'before_cursor_execute', listener)

    def test_same_connection_two_guards_and_already_applied_new_approval(self):
        calls = []
        original = entry.snapshot_target
        def capture(c, schema):
            calls.append(c)
            return original(c, schema)
        with patch.object(entry, 'snapshot_target', side_effect=capture): result = self.execute()
        self.assertEqual(result['status'], 'APPLIED', result)
        self.assertEqual(len(calls), 2); self.assertIs(calls[0], calls[1])
        self.assertTrue(all(r == {'added_column': True, 'assigned': 2} for r in result['report'].values()))
        with self.engine.connect() as c:
            validate_storage(c, self.schema)
            self.m['target']['snapshot'] = entry.snapshot_target(c, self.schema)
        # Model explicit operator review/new approval, not an entry auto-resume.
        self.evidence.busy.pop(self.m['target']['ref'])
        repeated = self.execute('synthetic-reviewed-second-attempt')
        self.assertEqual(repeated['status'], 'ALREADY_APPLIED', repeated)
        self.assert_controls()

    def test_wrong_schema_oid_rejected_before_update(self):
        self.m['target']['snapshot']['schema_oid'] += 1
        result = self.execute()
        self.assertEqual(result['status'], 'REJECTED', result)
        self.assertEqual(result['commit_state'], 'NOT_COMMITTED')
        self.assertIn('schema_oid', result['rejected_fields'])
        self.assert_legacy(); self.assert_controls()

    def test_locked_guard_detects_replaced_table_oid(self):
        def replace(c):
            with self.engine.begin() as other:
                other.exec_driver_sql(f'ALTER TABLE "{self.schema}".office RENAME TO old_office')
                other.exec_driver_sql(f'CREATE TABLE "{self.schema}".office (LIKE "{self.schema}".old_office INCLUDING ALL)')
                other.exec_driver_sql(f'INSERT INTO "{self.schema}".office SELECT * FROM "{self.schema}".old_office')
        self.before_lock(replace)
        result = self.execute()
        self.assertEqual(result['status'], 'REJECTED', result)
        self.assertEqual(result['last_guard_phase'], 'CONNECTED')
        self.assert_legacy(); self.assert_controls()

    def test_locked_guard_detects_schema_definition_change(self):
        def change(c):
            with self.engine.begin() as other:
                other.exec_driver_sql(f'ALTER TABLE "{self.schema}".office ADD COLUMN synthetic_external integer')
        self.before_lock(change)
        self.assertEqual(self.execute()['status'], 'REJECTED')
        self.assert_legacy(); self.assert_controls()

    def test_locked_guard_rejects_changed_original_search_path(self):
        self.before_lock(lambda c: c.exec_driver_sql('SET LOCAL search_path=public'))
        self.assertEqual(self.execute()['status'], 'REJECTED')
        self.assert_legacy(); self.assert_controls()

    def test_locked_guard_rechecks_approval_after_wait(self):
        def revoke(c):
            for key in self.evidence.records:
                if key.startswith('synthetic-P1-'):
                    self.evidence.records[key]['decision'] = 'REVOKED'
        self.before_lock(revoke)
        self.assertEqual(self.execute()['status'], 'REJECTED')
        self.assert_legacy(); self.assert_controls()

    def test_reader_timeout_is_confirmed_precommit_rollback(self):
        with self.engine.begin() as reader:
            reader.exec_driver_sql(f'LOCK TABLE "{self.schema}".office IN ACCESS SHARE MODE')
            result = self.execute()
        self.assertEqual(result['status'], 'ABORTED_CONFIRMED', result)
        self.assertEqual(result['sqlstate'], '55P03')
        self.assertEqual(result['commit_state'], 'NOT_COMMITTED')
        self.assert_legacy(); self.assert_controls()

    def test_partial_ddl_failure_before_commit_is_confirmed_and_atomic(self):
        def fail(c, cursor, statement, parameters, context, many):
            if statement.startswith('ALTER TABLE ') and 'vehicle_type' in statement:
                raise RuntimeError('synthetic-before-commit-secret-do-not-log')
        event.listen(self.engine, 'before_cursor_execute', fail)
        self.addCleanup(event.remove, self.engine, 'before_cursor_execute', fail)
        result = self.execute()
        self.assertEqual(result['status'], 'ABORTED_CONFIRMED', result)
        self.assertNotIn('secret-do-not-log', json.dumps([result, self.evidence.events]))
        self.assert_legacy(); self.assert_controls()

    def test_lost_commit_response_stays_unknown_and_blocks_new_attempt(self):
        commit = self.engine.dialect.do_commit
        def lost(driver):
            commit(driver)
            raise psycopg2.OperationalError('synthetic-lost-ACK-secret-do-not-log')
        with patch.object(self.engine.dialect, 'do_commit', side_effect=lost): result = self.execute()
        self.assertEqual(result['status'], 'OUTCOME_UNKNOWN', result)
        self.assertEqual(result['commit_state'], 'UNKNOWN')
        with self.engine.connect() as c: validate_storage(c, self.schema)
        with patch('tools.migration_entry.apply') as adapter:
            self.assertEqual(self.execute('new-attempt-cannot-bypass-unknown')['failure_code'], 'ATTEMPT_CLAIM_FAILED')
            adapter.assert_not_called()
        self.assertNotIn('secret-do-not-log', json.dumps([result, self.evidence.events]))
        self.assert_controls()

    def test_commit_entry_without_ack_cannot_claim_not_committed(self):
        with patch.object(self.engine.dialect, 'do_commit', side_effect=psycopg2.OperationalError('synthetic-before-wire')):
            result = self.execute()
        self.assertEqual(result['status'], 'OUTCOME_UNKNOWN', result)
        self.assertEqual(result['commit_state'], 'UNKNOWN')
        self.assert_legacy(); self.assert_controls()

    def test_commit_acknowledged_but_final_record_failed_is_distinct_unknown(self):
        self.evidence.fail_event = 'FINAL'
        result = self.execute()
        self.assertEqual(result['status'], 'OUTCOME_UNKNOWN', result)
        self.assertEqual(result['commit_state'], 'ACKNOWLEDGED')
        self.assertEqual(result['failure_code'], 'FINAL_RECORD_FAILED')
        with self.engine.connect() as c: validate_storage(c, self.schema)
        self.assertIn(self.m['target']['ref'], self.evidence.busy)
        self.assert_controls()

    def test_guard_record_failure_stops_before_ddl(self):
        self.evidence.fail_event = 'LOCKED_OK'
        result = self.execute()
        self.assertEqual(result['commit_state'], 'NOT_COMMITTED', result)
        self.assert_legacy(); self.assert_controls()

    def test_competing_attempt_advisory_lock_is_nonblocking(self):
        import hashlib
        key = int.from_bytes(hashlib.sha256(('synthetic-target:' + entry.OPERATION).encode()).digest()[:8], 'big', signed=True)
        with self.engine.begin() as holder:
            holder.execute(text('SELECT pg_catalog.pg_advisory_xact_lock(:key)'), {'key': key})
            self.assertEqual(self.execute()['status'], 'REJECTED')
        self.assert_legacy(); self.assert_controls()

    def test_limited_role_cannot_reach_ddl(self):
        original = entry.snapshot_target
        def limited(c, schema):
            c.exec_driver_sql('SET LOCAL ROLE pg_read_all_data')
            return original(c, schema)
        with patch.object(entry, 'snapshot_target', side_effect=limited):
            result = self.execute()
        self.assertEqual(result['status'], 'REJECTED', result)
        self.assert_legacy(); self.assert_controls()

    def test_autocommit_connection_cannot_reach_ddl(self):
        raw, approval = approve(self.m, self.evidence)
        result = entry.execute_q04(engine=self.engine.execution_options(isolation_level='AUTOCOMMIT'),
            manifest=raw, approval=approval, evidence=self.evidence)
        self.assertEqual(result['status'], 'REJECTED', result)
        self.assert_legacy(); self.assert_controls()
