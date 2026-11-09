"""Bounded INSERT acceptance on the explicitly gated synthetic PG18 service only.

Importing this module cannot connect. These tests remain skipped unless the
existing dedicated-service gate succeeds. No production input is read.
"""
from collections import Counter
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

import test_restore_postgres as postgres
import worlex_restore as restore
from insert_size_fixture import (
    ENCODED_VALUE_BYTES, RAW_BLOB_BYTES, encoded_bytes, fixture, payload_stats,
)
from test_restore_unit import policy_metadata


class InsertSizeFixtureTests(unittest.TestCase):
    def test_full_size_synthetic_envelope_and_five_large_draft_rows(self):
        policy = json.loads((postgres.PACKAGE / 'policy.json').read_text())
        counts = json.loads((postgres.PACKAGE / 'source-counts.json').read_text())
        data, columns, actual = fixture(policy, counts)
        self.assertEqual(actual, counts)
        self.assertEqual(sum(map(len, data.values())), 4100)
        typed, _ = restore.typed_payload(data, columns, policy_metadata(policy), counts)
        restore.defer_push_subscription(typed, restore.DEFERRED_SOURCE_ROWS)
        self.assertEqual(payload_stats(typed), {
            'source_rows': 4100, 'imported_rows': 4099, 'blob_values': 24,
            'blob_bytes': RAW_BLOB_BYTES, 'encoded_parameter_bytes': ENCODED_VALUE_BYTES})
        large = [(name, sum(encoded_bytes(value) for value in row.values()))
                 for name, rows in typed.items() for row in rows
                 if sum(encoded_bytes(value) for value in row.values()) > 4 * 1024**2]
        self.assertEqual(len(large), 5)
        self.assertTrue(all(name == 'vehicle_operation_import_draft' and size < 8 * 1024**2
                            for name, size in large))


class PostgreSQLBoundedInsertAcceptance(unittest.TestCase):
    # Reuse the exact dedicated CI guards and initialization, but not inherited
    # test methods: this adds six focused tests rather than duplicating a suite.
    setUpClass = classmethod(postgres.PostgreSQLRestoreAcceptance.setUpClass.__func__)
    restore = postgres.PostgreSQLRestoreAcceptance.restore
    approve_current = postgres.PostgreSQLRestoreAcceptance.approve_current
    verify_current = postgres.PostgreSQLRestoreAcceptance.verify_current
    preserved_audit = postgres.PostgreSQLRestoreAcceptance.preserved_audit
    existing_push = postgres.PostgreSQLRestoreAcceptance.existing_push

    def setUp(self):
        with patch.object(postgres, 'fixture', fixture):
            postgres.PostgreSQLRestoreAcceptance.setUp(self)
        self.metrics = []
        event.listen(self.engine, 'after_cursor_execute', self.record_insert)
        self.addCleanup(event.remove, self.engine, 'after_cursor_execute', self.record_insert)

    def record_insert(self, connection, cursor, statement, parameters, context, executemany):
        if not context.isinsert or context.compiled is None:
            return
        command = context.compiled.statement
        if command.table.name not in self.data:
            return
        # Preservation fixture setup INSERTs precede the test's metrics reset.
        batches = getattr(command, '_multi_values', ())
        count = len(batches[0]) if batches else 1
        self.metrics.append({'table': command.table.name, 'rows': count,
                             'binds': len(parameters), 'sql_bytes': len(statement.encode('utf-8')),
                             'parameter_bytes': sum(encoded_bytes(value) for value in parameters),
                             'executemany': bool(executemany),
                             'returning': bool(command._returning),
                             'explicit_multi_values': bool(batches)})

    def prepare_preservation(self):
        self.preserved_audit()
        self.preserved_audit(company='ITC', identifier=2)
        self.existing_push()
        self.approve_current()
        with self.engine.connect() as connection:
            self.preserved = restore.snapshot(connection, self.tables)
            self.sequences = restore.sequence_states(connection, self.tables)
            self.tenant_counts = {name: connection.scalar(
                select(func.count()).select_from(table).where(table.c.company_code == 'WORLEX'))
                for name, table in self.tables.items() if 'company_code' in table.c}
        self.metrics.clear()

    def typed_source(self):
        typed, _ = restore.typed_payload(self.data, self.columns, self.tables, self.counts,
                                         generated=self.approved['generated_identifiers'])
        restore.defer_push_subscription(typed, restore.DEFERRED_SOURCE_ROWS)
        return typed

    def assert_metrics(self, complete=True):
        self.assertTrue(self.metrics)
        for metric in self.metrics:
            self.assertFalse(metric['executemany'])
            self.assertFalse(metric['returning'])
            self.assertTrue(metric['explicit_multi_values'])
            self.assertLessEqual(metric['rows'], 100)
            self.assertLessEqual(metric['binds'], 8000)
            self.assertLessEqual(metric['sql_bytes'], 128 * 1024)
            self.assertLessEqual(metric['parameter_bytes'],
                                 (8 if metric['rows'] == 1 else 4) * 1024**2)
        if complete:
            self.assertEqual(sum(item['rows'] for item in self.metrics), 4099)
            self.assertEqual(sum(item['parameter_bytes'] for item in self.metrics), ENCODED_VALUE_BYTES)
            self.assertEqual(sum(item['parameter_bytes'] > 4 * 1024**2 for item in self.metrics), 5)
            self.assertLess(len(self.metrics), 150)
            self.assertTrue(any(item['rows'] > 1 for item in self.metrics))

    def write_evidence(self, name, **extra):
        directory = Path(os.environ.get('WORLEX_EVIDENCE_DIR', self.temp.name))
        directory.mkdir(exist_ok=True)
        result = {'synthetic_only': True, 'actual_postgres_18': True,
                  'envelope': payload_stats(self.typed_source()),
                  'insert_dispatch': self.metrics, **extra}
        (directory / ('bounded-insert-' + name + '.json')).write_text(json.dumps(result, indent=2, sort_keys=True))

    def assert_exact_epochs(self, connection, typed):
        expected = Counter()
        for name in self.policy['analysis_input_tables']:
            for row in typed.get(name, []):
                identifier = row['id'] if name == 'vehicle' else row.get('vehicle_record_id')
                bucket = 'shared' if identifier is None else 'vehicle:' + str(identifier)
                expected[bucket] += 1
        table = self.tables['analysis_input_epoch']
        actual = {row.bucket: row.revision for row in connection.execute(
            select(table).where(table.c.company_code == 'WORLEX'))}
        self.assertEqual(actual, dict(expected))
        return dict(sorted(expected.items()))

    def test_full_size_values_preservation_epochs_and_bounded_dispatch(self):
        self.prepare_preservation()
        source_digest = restore.digest(self.data)
        result = self.restore()
        self.assertEqual(result['status'], 'TRANSACTION_VERIFIED')
        self.assert_metrics()
        verified = self.verify_current()
        self.assertTrue(verified['imported_values_and_blobs_match'])
        self.assertTrue(verified['required_settings_and_preserved_rows_unchanged'])
        self.assertTrue(verified['push_subscription_rows_unchanged'])
        self.assertTrue(verified['push_subscription_sequence_unchanged'])
        self.assertEqual(restore.digest(self.data), source_digest)
        typed = self.typed_source()
        with self.engine.connect() as connection:
            tables, _ = restore.validate_schema(connection, self.policy)
            for name, expected in typed.items():
                table = tables[name]
                query = select(table).where(table.c.company_code == 'WORLEX')
                if name == 'audit_log':
                    query = query.where(table.c.id.in_([row['id'] for row in expected]))
                actual = [dict(row) for row in connection.execute(query).mappings()]
                keys = [column.name for column in table.primary_key]
                order = lambda row: tuple(row[key] for key in keys)
                self.assertEqual(restore.canonical(sorted(actual, key=order)),
                                 restore.canonical(sorted(expected, key=order)), name)
            epochs = self.assert_exact_epochs(connection, typed)
            self.assertEqual(restore.snapshot(connection, tables,
                exclude_vehicle_compat=self.approved['legacy_vehicle_id_addition'],
                audit_import_ids=[row['id'] for row in typed['audit_log']]), self.preserved)
            self.assertEqual(restore.sequence_states(connection, tables)[('push_subscription', 'id')],
                             self.sequences[('push_subscription', 'id')])
        self.write_evidence('full-size', exact_all_imported_values_and_blobs=True,
            preserved_itc_settings_audit_push=True, exact_epoch_revisions=epochs,
            deferred_source_retained=True, source_rows=4100, imported_rows=4099)

    def assert_rollback(self, injection):
        self.prepare_preservation()
        before = restore.digest(self.data)
        with self.assertRaisesRegex(restore.Stop, 'INJECTED_ROLLBACK_PROBE'):
            self.restore(inject_failure=injection)
        self.assert_metrics(complete=injection == 'after_sequences')
        if injection == 'middle_insert_batch':
            self.assertEqual(sum(item['table'] == 'vehicle_operation_record' for item in self.metrics), 2)
            self.assertGreater(len(self.metrics), 2)
        self.assert_rollback_state(before)
        self.write_evidence(injection, all_imports_absent=True, preserved_rows_match=True,
                            sequences_unchanged=True, compatibility_column_rolled_back=True)

    def assert_rollback_state(self, source_digest):
        with self.engine.connect() as connection:
            tables, _ = restore.validate_schema(connection, self.policy)
            self.assertEqual(list(tables['vehicle'].c.keys()), list(self.tables['vehicle'].c.keys()))
            self.assertEqual(restore.snapshot(connection, tables), self.preserved)
            self.assertEqual(restore.sequence_states(connection, tables), self.sequences)
            for name, table in tables.items():
                if 'company_code' in table.c:
                    self.assertEqual(connection.scalar(select(func.count()).select_from(table).where(
                        table.c.company_code == 'WORLEX')), self.tenant_counts[name], name)
        self.assertEqual(restore.digest(self.data), source_digest)

    def test_middle_insert_batch_rolls_back(self):
        self.assert_rollback('middle_insert_batch')

    def test_after_sequences_rolls_back_full_size_import(self):
        self.assert_rollback('after_sequences')

    def test_actual_third_batch_constraint_error_rolls_back_without_retry(self):
        self.prepare_preservation()
        source_digest = restore.digest(self.data)
        attempts = []
        first_id = int(self.data['vehicle_operation_record'][0]['id'])

        def duplicate_committed_in_transaction_key(connection, cursor, statement,
                                                   parameters, context, executemany):
            if context.isinsert and context.compiled.statement.table.name == 'vehicle_operation_record':
                attempts.append(1)
                if len(attempts) == 3:
                    self.assertFalse(executemany)
                    # Change exactly one explicit PK at the DBAPI boundary in
                    # this disposable DB. PostgreSQL, not the helper, rejects it.
                    positions = context.compiled.positiontup
                    self.assertIn('id_m0', positions)
                    replacement = list(parameters)
                    replacement[positions.index('id_m0')] = first_id
                    parameters = tuple(replacement)
            return statement, parameters

        event.listen(self.engine, 'before_cursor_execute',
                     duplicate_committed_in_transaction_key, retval=True)
        try:
            with self.assertRaises(IntegrityError):
                self.restore()
        finally:
            event.remove(self.engine, 'before_cursor_execute',
                         duplicate_committed_in_transaction_key)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sum(item['table'] == 'vehicle_operation_record'
                             for item in self.metrics), 2)
        self.assert_metrics(complete=False)
        self.assert_rollback_state(source_digest)
        self.write_evidence('actual-third-batch-error', actual_postgres_constraint_error=True,
            target_table='vehicle_operation_record', attempted_target_batches=3,
            successful_target_batches=2, all_imports_absent=True,
            preserved_rows_match=True, sequences_unchanged=True, restore_retried=False)

    def test_full_size_disconnect_before_commit(self):
        # The existing test performs a real close before COMMIT and fresh
        # read-only reconciliation. Redirect its evidence to avoid overwriting
        # the original acceptance test's files.
        with patch.dict(os.environ, {'WORLEX_EVIDENCE_DIR': self.temp.name}):
            postgres.PostgreSQLRestoreAcceptance.test_disconnect_before_commit_rolls_back_all_imported_tables_and_sequences(self)
        self.metrics = [item for item in self.metrics if item['explicit_multi_values']]
        self.assert_metrics()
        evidence = json.loads((Path(self.temp.name) / 'disconnect-before-commit.json').read_text())
        self.write_evidence('disconnect-before-commit', reconciliation=evidence)

    def test_full_size_disconnect_after_commit(self):
        with patch.dict(os.environ, {'WORLEX_EVIDENCE_DIR': self.temp.name}):
            postgres.PostgreSQLRestoreAcceptance.test_disconnect_after_commit_reconciles_without_reinserting(self)
        self.metrics = [item for item in self.metrics if item['explicit_multi_values']]
        self.assert_metrics()
        with self.engine.connect() as connection:
            epochs = self.assert_exact_epochs(connection, self.typed_source())
        evidence = json.loads((Path(self.temp.name) / 'disconnect-after-commit.json').read_text())
        self.write_evidence('disconnect-after-commit', reconciliation=evidence,
                            exact_epoch_revisions=epochs)


if __name__ == '__main__':
    unittest.main()
