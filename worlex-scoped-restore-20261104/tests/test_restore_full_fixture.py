"""Independent full-count synthetic coverage; never reads the original archive.

Offline checks use public policy/counts and an in-memory SQLite database only.
The PostgreSQL checks reuse the existing dedicated CI service gate and do not
claim SQLite can validate PostgreSQL catalog, triggers, sequences or indexes.
"""
import copy
import datetime as dt
import decimal
import hashlib
import json
import pathlib
import tempfile
import unittest
import uuid

from sqlalchemy import Column, String, create_engine, func, inspect, select, text

import test_restore_postgres as postgres
from synthetic_fixture import fixture
from test_restore_unit import policy_metadata
from worlex_restore import LOGICAL_REFS, RETIRED, Stop, apply_push_map, canonical, read_copy, typed_payload

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_SOURCE_TABLES = 62
EXPECTED_POPULATED_TABLES = 37
EXPECTED_ROWS = 4100
GENERATED = {'account_identity', 'master_generation'}
# Planned inspections have no completed record; the FK negative control still runs.
INTENTIONALLY_UNPOPULATED_REFS = {('vehicle_inspection_plan', 'completed_record_id')}
HISTORICAL_UNBOUND = {
    'owner_identity', 'actor_identity', 'actor_name', 'actor_user_id',
    'checked_by_identity', 'checked_by_user_id',
    'approved_by_identity', 'approved_by_user_id',
    'target_identity', 'target_user_id',
    'created_by_identity', 'created_by_user_id',
    'countermeasure_by_identity', 'countermeasure_by_user_id',
}


def read_structural_inputs():
    return (json.loads((ROOT / 'policy.json').read_text()),
            json.loads((ROOT / 'source-counts.json').read_text()))


def reference_value(value, kind):
    """Independent source conversion oracle, not typed_payload's helper."""
    if value is None:
        return None
    if kind in {'INTEGER', 'BIGINT', 'SMALLINT'}:
        return int(value)
    if kind == 'BOOLEAN':
        if value not in {'t', 'f'}:
            raise AssertionError('Synthetic BOOLEAN must use COPY t/f encoding')
        return value == 't'
    if kind == 'FLOAT':
        return float(value)
    if kind == 'NUMERIC':
        return decimal.Decimal(value)
    if kind == 'DATETIME':
        return dt.datetime.fromisoformat(value)
    if kind == 'DATE':
        return dt.date.fromisoformat(value)
    if kind == 'BLOB':
        if not value.startswith('\\x'):
            raise AssertionError('Synthetic BLOB must use COPY hex encoding')
        return bytes.fromhex(value[2:])
    return value


def references(policy, counts):
    refs = {(name, col, target, target_col)
            for name, spec in policy['tables'].items() if counts.get(name, 0)
            for col, target, target_col in spec['fk']}
    refs.update(tuple(ref) for ref in LOGICAL_REFS if counts.get(ref[0], 0))
    return sorted(refs)


class FullSyntheticFixtureCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy, cls.expected = read_structural_inputs()
        cls.data, cls.columns, cls.counts = fixture(cls.policy, cls.expected.keys())
        cls.tables = policy_metadata(cls.policy)
        cls.typed, cls.order = typed_payload(
            cls.data, cls.columns, cls.tables, cls.expected)

    def test_matches_every_approved_source_count_including_empty_tables(self):
        self.assertEqual(len(self.expected), EXPECTED_SOURCE_TABLES)
        self.assertEqual(sum(self.expected.values()), EXPECTED_ROWS)
        self.assertEqual(sum(value > 0 for value in self.expected.values()),
                         EXPECTED_POPULATED_TABLES)
        self.assertEqual(set(self.data), set(self.expected))
        self.assertEqual(self.counts, self.expected)
        self.assertEqual({n: len(rows) for n, rows in self.data.items()}, self.expected)
        self.assertEqual(set(self.order), {n for n, count in self.expected.items() if count})
        for name, rows in self.data.items():
            with self.subTest(table=name):
                self.assertEqual(len(self.columns[name]), len(set(self.columns[name])))
                for row in rows:
                    self.assertEqual(set(row), set(self.columns[name]))
                    self.assertEqual(row['company_code'], 'WORLEX')

    def test_all_37_primary_keys_are_present_and_unique(self):
        checked = 0
        for name in self.order:
            spec = self.policy['tables'][name]
            with self.subTest(table=name):
                self.assertTrue(spec['pk'])
                keys = [tuple(row[col] for col in spec['pk']) for row in self.typed[name]]
                self.assertTrue(all(None not in key for key in keys))
                self.assertEqual(len(keys), len(set(keys)))
                checked += 1
        self.assertEqual(checked, EXPECTED_POPULATED_TABLES)

    def test_all_required_columns_lengths_and_typed_values(self):
        for name in self.order:
            spec = self.policy['tables'][name]
            for row in self.typed[name]:
                with self.subTest(table=name, primary_key=tuple(row[k] for k in spec['pk'])):
                    self.assertTrue(set(spec['columns']).issubset(row))
                    for col, entry in spec['columns'].items():
                        value = row[col]
                        if not entry['nullable']:
                            self.assertIsNotNone(value, col)
                        if value is not None and entry['length'] is not None:
                            self.assertLessEqual(len(value), entry['length'], col)
                        if value is not None:
                            types = {'BOOLEAN': bool, 'INTEGER': int, 'BIGINT': int,
                                     'SMALLINT': int, 'FLOAT': float,
                                     'NUMERIC': decimal.Decimal, 'DATE': dt.date,
                                     'DATETIME': dt.datetime, 'BLOB': bytes,
                                     'VARCHAR': str, 'TEXT': str}
                            self.assertIsInstance(value, types[entry['type']], col)

    def test_every_represented_fk_is_populated_closed_and_ordered(self):
        checked = references(self.policy, self.expected)
        self.assertTrue(checked)
        positions = {name: i for i, name in enumerate(self.order)}
        for name, col, target, target_col in checked:
            with self.subTest(table=name, column=col):
                values = [row.get(col) for row in self.typed[name]]
                if (name, col) in INTENTIONALLY_UNPOPULATED_REFS:
                    self.assertTrue(all(value is None for value in values))
                else:
                    self.assertTrue(any(value is not None for value in values),
                                    'A represented reference must be exercised, not all NULL')
                allowed = {row[target_col] for row in self.typed[target]}
                self.assertTrue(all(value is None or value in allowed for value in values))
                if name != target and any(value is not None for value in values):
                    self.assertLess(positions[target], positions[name])

    def test_count_drift_is_rejected_for_each_declared_source_table(self):
        for name, count in self.expected.items():
            bad_counts = dict(self.expected)
            bad_counts[name] = count + 1
            with self.subTest(table=name), self.assertRaisesRegex(Stop, 'SOURCE_COUNT_CHANGED'):
                typed_payload(self.data, self.columns, self.tables, bad_counts)

    def test_primary_key_corruption_is_rejected_in_every_populated_table(self):
        for name in self.order:
            data = copy.deepcopy(self.data)
            pk = self.policy['tables'][name]['pk']
            # Duplicate a whole key where possible; NULL otherwise. No extra rows.
            if len(data[name]) > 1:
                for col in pk:
                    data[name][1][col] = data[name][0][col]
            else:
                data[name][0][pk[0]] = None
            with self.subTest(table=name), self.assertRaises(Stop):
                typed_payload(data, self.columns, self.tables, self.expected)

    def test_broken_reference_is_rejected_for_each_represented_fk(self):
        for name, col, target, target_col in references(self.policy, self.expected):
            data = copy.deepcopy(self.data)
            target_kind = self.policy['tables'][target]['columns'][target_col]['type']
            missing = '-2147483648' if target_kind in {'INTEGER', 'BIGINT', 'SMALLINT'} else 'synthetic-missing-parent'
            data[name][0][col] = missing
            with self.subTest(table=name, column=col), self.assertRaisesRegex(
                    Stop, 'SOURCE_REFERENCE_NOT_TENANT_CLOSED'):
                typed_payload(data, self.columns, self.tables, self.expected)

    def test_every_source_value_is_preserved_except_documented_transformations(self):
        for name in self.order:
            spec = self.policy['tables'][name]
            for source, typed in zip(self.data[name], self.typed[name]):
                for col, value in source.items():
                    with self.subTest(table=name, column=col):
                        if col in GENERATED:
                            continue
                        if col not in spec['columns']:
                            if name == 'vehicle' and col == 'vehicle_id':
                                self.assertEqual(typed[col], value)
                            else:
                                self.assertIn(col, RETIRED.get(name, set()))
                            continue
                        if col == 'notification_identities_json':
                            self.assertEqual(typed[col], '{}')
                            continue
                        if name == 'vehicle' and col == 'chassis_number' and value == '':
                            self.assertIsNone(typed[col])
                            continue
                        self.assertEqual(typed[col], reference_value(value, spec['columns'][col]['type']))

    def test_historical_accounts_are_not_rebound_and_generated_ids_replay(self):
        generated = {}
        checked = set()
        for name in self.order:
            for raw, row in zip(self.data[name], self.typed[name]):
                for col in HISTORICAL_UNBOUND.intersection(row):
                    self.assertIsNone(row[col], name + '.' + col)
                    checked.add((name, col))
                if 'notification_identities_json' in row:
                    self.assertEqual(row['notification_identities_json'], '{}')
                fields = GENERATED.intersection(row)
                if fields:
                    generated.setdefault(name, {})[str(row['id'])] = {col: row[col] for col in fields}
                    for col in fields:
                        self.assertNotIn(col, raw)
                        self.assertEqual(str(uuid.UUID(row[col])), row[col])
                        self.assertNotEqual(uuid.UUID(row[col]).int, 0)
            for col in GENERATED.intersection(self.policy['tables'][name]['columns']):
                values = [row[col] for row in self.typed[name]]
                self.assertEqual(len(values), len(set(values)))
        self.assertTrue(checked)
        restored, order = typed_payload(self.data, self.columns, self.tables,
                                        self.expected, generated=generated)
        self.assertEqual(restored, self.typed)
        self.assertEqual(order, self.order)
        self.assertEqual(len(generated['user']), 15)

    def test_all_24_source_blobs_are_nonempty_and_hash_verified(self):
        seen = {}
        for name in self.order:
            for col, entry in self.policy['tables'][name]['columns'].items():
                if entry['type'] != 'BLOB':
                    continue
                seen[(name, col)] = len(self.typed[name])
                for source, typed in zip(self.data[name], self.typed[name]):
                    blob = typed[col]
                    self.assertIsInstance(blob, bytes)
                    self.assertGreater(len(blob), 0)
                    self.assertEqual(blob, bytes.fromhex(source[col][2:]))
                    if col == 'source_file' and 'source_sha256' in typed:
                        self.assertEqual(hashlib.sha256(blob).hexdigest(), typed['source_sha256'])
        self.assertEqual(seen, {('vehicle_document_import_draft', 'source_file'): 19,
                                ('vehicle_operation_import_draft', 'source_file'): 5})

    def test_legacy_acceptance_anchors_and_vehicle_state_counts_remain(self):
        self.assertEqual(self.data['user'][0]['id'], '3')
        self.assertEqual(self.data['user'][0]['username'], 'fixture-0')
        self.assertEqual(self.data['vehicle'][0]['id'], '2')
        self.assertEqual({int(row['id']) for row in self.data['audit_log']}, set(range(1001, 1424)))
        self.assertEqual(self.data['push_subscription'][0]['id'], '1')
        self.assertEqual(self.data['push_subscription'][0]['endpoint'], 'https://synthetic-backup.invalid/push')
        self.assertEqual(sum(row['deleted'] for row in self.typed['vehicle']), 276)
        self.assertEqual(sum(not row['deleted'] for row in self.typed['vehicle']), 289)
        self.assertEqual(sum(row['chassis_number'] is None for row in self.typed['vehicle']), 11)
        self.assertEqual(sum(bool(row.get('vehicle_id')) for row in self.typed['vehicle']), 241)

    def test_synthetic_copy_roundtrip_covers_all_62_tables(self):
        def encode(value):
            if value is None:
                return r'\N'
            return str(value).replace('\\', '\\\\').replace('\t', r'\t').replace('\n', r'\n').replace('\r', r'\r')

        with tempfile.TemporaryDirectory(prefix='worlex-full-synthetic-copy-') as directory:
            path = pathlib.Path(directory) / 'synthetic.sql'
            with path.open('w', encoding='utf-8') as stream:
                for name, rows in self.data.items():
                    cols = self.columns[name] or ['company_code']
                    stream.write('COPY public."' + name + '" (' + ', '.join('"' + col + '"' for col in cols) + ') FROM stdin;\n')
                    for row in rows:
                        stream.write('\t'.join(encode(row[col]) for col in cols) + '\n')
                    stream.write('\\.\n')
            data, columns = read_copy(path)
        self.assertEqual(data, self.data)
        typed, order = typed_payload(data, columns, self.tables, self.expected)
        self.assertEqual(order, self.order)
        self.assertEqual({name: len(rows) for name, rows in typed.items()}, self.expected)

    def test_sqlite_all_rows_insert_with_fk_checks_and_preserved_values(self):
        tables = policy_metadata(self.policy)
        if 'vehicle_id' not in tables['vehicle'].c:
            tables['vehicle'].append_column(Column('vehicle_id', String(50)))
        metadata = tables['vehicle'].metadata
        engine = create_engine('sqlite+pysqlite:///:memory:')
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')
            self.assertEqual(connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one(), 1)
            metadata.create_all(connection)
            for name in self.order:
                connection.execute(tables[name].insert(), self.typed[name])
            self.assertEqual(connection.exec_driver_sql('PRAGMA foreign_key_check').all(), [])
            for name in self.expected:
                with self.subTest(table=name):
                    self.assertEqual(connection.scalar(select(func.count()).select_from(tables[name])), self.expected[name])
                    pk = self.policy['tables'][name]['pk']
                    actual = connection.execute(select(tables[name]).order_by(*[tables[name].c[col] for col in pk])).mappings().all()
                    expected = sorted(self.typed[name], key=lambda row: tuple(row[col] for col in pk))
                    self.assertEqual(canonical([dict(row) for row in actual]), canonical(expected))


def assert_full_postgres_coverage(case):
    """Called by exactly one test in the existing guarded PG acceptance class."""
    expected = json.loads((ROOT / 'source-counts.json').read_text())
    case.assertEqual(case.counts, expected)
    case.assertEqual(sum(expected.values()), EXPECTED_ROWS)
    # Also prove the 37-table expansion preserves existing audit/current push rows.
    case.preserved_audit()
    case.preserved_audit(company='ITC', identifier=2)
    preserved_push = case.existing_push()
    case.approve_current()
    with case.engine.connect() as connection:
        case.assertEqual(connection.scalar(select(func.count()).select_from(case.tables['audit_log'])), 2)
    case.assertEqual(case.approved['push_subscription_id_remap'], {'1': 2})
    result = case.restore()
    case.assertEqual(result['status'], 'TRANSACTION_VERIFIED')
    verified = case.verify_current()
    case.assertTrue(verified['all_source_values_and_blobs_match'])
    case.assertTrue(verified['non_worlex_and_global_rows_unchanged'])
    coverage = {
        'synthetic_only': True,
        'source_rows': EXPECTED_ROWS,
        'populated_tables': EXPECTED_POPULATED_TABLES,
        'source_counts': expected,
        'imported_values_and_blobs_match': True,
        'preserved_rows_match': True,
        'owner_bindings_quarantined': True,
        'existing_audit_rows_preserved': 2,
        'preserved_worlex_audit_rows': verified['preserved_worlex_audit_rows'],
        'push_subscription_ids_remapped': verified['push_subscription_ids_remapped'],
        'primary_key_tables_checked': 0,
        'foreign_key_constraints_checked': 0,
        'foreign_key_nonnull_values_checked': 0,
        'unique_constraints_and_indexes_checked': 0,
        'unique_nonnull_keys_checked': 0,
        'owner_fields_checked': 0,
        'blob_rows_checked': 0,
        'source_columns_checked': 0,
        'intentionally_unpopulated_foreign_keys': [list(ref) for ref in sorted(INTENTIONALLY_UNPOPULATED_REFS)],
    }
    with case.engine.connect() as connection:
        tables, _ = postgres.validate_schema(connection, case.policy)
        typed, _ = typed_payload(case.data, case.columns, tables, expected,
                                 generated=case.approved['generated_identifiers'])
        apply_push_map(typed, case.approved['push_subscription_id_remap'])
        inspector = inspect(connection)
        for name, count in expected.items():
            with case.subTest(table=name):
                table = tables[name]
                rows = connection.execute(select(table).where(table.c.company_code == 'WORLEX')).mappings().all()
                case.assertEqual(len(rows), count + (1 if name == 'audit_log' else 0))
                if not count:
                    continue
                pk = inspector.get_pk_constraint(name, schema='public')['constrained_columns']
                case.assertTrue(pk)
                coverage['primary_key_tables_checked'] += 1
                actual = {tuple(row[col] for col in pk): dict(row) for row in rows}
                case.assertEqual(len(actual), len(rows))
                imported = []
                for row in typed[name]:
                    observed = actual[tuple(row[col] for col in pk)]
                    case.assertEqual(canonical(observed), canonical(row))
                    coverage['source_columns_checked'] += len(row)
                    imported.append(observed)
                    for col in HISTORICAL_UNBOUND.intersection(observed):
                        case.assertIsNone(observed[col], name + '.' + col)
                        coverage['owner_fields_checked'] += 1
                    for col, entry in case.policy['tables'][name]['columns'].items():
                        if entry['type'] == 'BLOB':
                            case.assertGreater(len(observed[col]), 0)
                            case.assertEqual(bytes(observed[col]), row[col])
                            if col == 'source_file' and 'source_sha256' in observed:
                                case.assertEqual(hashlib.sha256(bytes(observed[col])).hexdigest(), observed['source_sha256'])
                            coverage['blob_rows_checked'] += 1
                unique = inspector.get_unique_constraints(name, schema='public')
                unique += [index for index in inspector.get_indexes(name, schema='public') if index.get('unique')]
                for constraint in unique:
                    cols = constraint.get('column_names')
                    case.assertTrue(cols)
                    case.assertTrue(all(col in table.c for col in cols))
                    # Match restore's conservative full-key check for partial indexes.
                    keys = [tuple(row[col] for col in cols) for row in imported
                            if all(row[col] is not None for col in cols)]
                    case.assertEqual(len(keys), len(set(keys)), constraint.get('name'))
                    coverage['unique_constraints_and_indexes_checked'] += 1
                    coverage['unique_nonnull_keys_checked'] += len(keys)
                for fk in inspector.get_foreign_keys(name, schema='public'):
                    target = tables[fk['referred_table']]
                    allowed = set(connection.execute(select(*[target.c[col] for col in fk['referred_columns']]).where(target.c.company_code == 'WORLEX')).tuples())
                    keys = [tuple(row[col] for col in fk['constrained_columns']) for row in imported]
                    case.assertTrue(all(any(value is None for value in key) or key in allowed for key in keys))
                    coverage['foreign_key_constraints_checked'] += 1
                    coverage['foreign_key_nonnull_values_checked'] += sum(all(value is not None for value in key) for key in keys)
        push = tables['push_subscription']
        case.assertEqual(dict(connection.execute(select(push).where(push.c.id == 1)).mappings().one()), preserved_push)
    case.assertEqual(coverage['primary_key_tables_checked'], EXPECTED_POPULATED_TABLES)
    case.assertEqual(coverage['blob_rows_checked'], 24)
    case.assertEqual(coverage['preserved_worlex_audit_rows'], 1)
    case.assertEqual(coverage['push_subscription_ids_remapped'], 1)
    case.assertGreater(coverage['unique_constraints_and_indexes_checked'], 0)
    case.assertGreater(coverage['foreign_key_constraints_checked'], 0)
    case.assertGreater(coverage['owner_fields_checked'], 0)
    evidence = pathlib.Path(postgres.os.environ.get('WORLEX_EVIDENCE_DIR', case.temp.name))
    evidence.mkdir(exist_ok=True)
    (evidence / 'full-fixture-coverage.json').write_text(json.dumps(coverage, indent=2, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
