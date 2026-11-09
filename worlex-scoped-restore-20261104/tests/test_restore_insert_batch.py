"""Synthetic exact-pg8000 compilation/dispatch; no sockets or production source."""
import copy
import datetime as dt
import decimal
import inspect
import unittest
from unittest import mock

import pg8000
from pg8000.converters import PY_TYPES, make_params
from sqlalchemy import (MetaData, Table, Column, Integer, String, Text, Boolean,
                        Numeric, Date, DateTime, Float, LargeBinary, literal, create_engine)
from sqlalchemy.dialects.postgresql.pg8000 import PGDialect_pg8000
from sqlalchemy.engine import Engine, URL
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.elements import quoted_name
import worlex_restore as wr


class FakeCursor:
    rowcount = -1
    description = None

    def __init__(self, db):
        self.db = db

    def execute(self, statement, parameters=()):
        self.db.calls.append((statement, tuple(parameters)))
        if self.db.fail_at == len(self.db.calls):
            raise RuntimeError('synthetic batch failure')
        self.rowcount = 1

    def executemany(self, *args):
        raise AssertionError('executemany is forbidden')

    def close(self):
        pass

    def setinputsizes(self, *args):
        pass


class FakeDB:
    _client_encoding = 'utf8'

    def __init__(self):
        self.calls = []
        self.py_types = PY_TYPES.copy()
        self.fail_at = None

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        pass

    def close(self):
        pass


def fake_engine():
    db = FakeDB()
    dialect = PGDialect_pg8000(dbapi=pg8000)
    dialect.server_version_info = (18, 6)
    dialect.default_schema_name = 'public'
    # Direct Engine construction bypasses create_engine's connection hook.
    # Invoke the pinned dialect's actual hook, as a real connection does.
    dialect.on_connect()(db)
    return Engine(StaticPool(creator=lambda: db), dialect, URL.create('postgresql+pg8000')), db


def payload_table():
    return Table('synthetic', MetaData(), Column('id', Integer, primary_key=True),
                 Column('payload', Text))


class InsertBatchTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.db = fake_engine()
        self.connection = self.engine.connect()
        self.table = payload_table()

    def tearDown(self):
        self.connection.close()
        self.engine.dispose()

    def statements(self, rows, table=None):
        return list(wr.iter_insert_batches(self.connection, table if table is not None else self.table, rows))

    def sizes(self, statement, rows, columns=2):
        return wr.insert_batch_metrics(self.connection, statement, rows, columns)

    def test_fixed_limits_and_existing_300s_transaction_budget(self):
        self.assertEqual((wr.INSERT_MAX_ROWS, wr.INSERT_MAX_BINDS,
                          wr.INSERT_MAX_SQL_BYTES, wr.INSERT_MAX_PARAMETER_BYTES,
                          wr.INSERT_MAX_SINGLETON_BYTES), (100, 8000, 131072, 4194304, 8388608))
        self.assertIn("transaction_timeout='300s'", inspect.getsource(wr.execute_restore))
        self.assertIn('connection.execute(statement)', inspect.getsource(wr.execute_restore))

    def test_zero_one_100_101_rows_use_single_execute_without_returning(self):
        for count, expected in [(0, 0), (1, 1), (100, 1), (101, 2)]:
            with self.subTest(count=count):
                self.db.calls.clear()
                rows = [dict(id=i, payload='synthetic') for i in range(count)]
                before = copy.deepcopy(rows)
                for statement in self.statements(rows):
                    self.connection.execute(statement)
                self.assertEqual(len(self.db.calls), expected)
                self.assertEqual(rows, before)
                for sql, params in self.db.calls:
                    self.assertNotIn('RETURNING', sql)
                    self.assertNotIn('ON CONFLICT', sql)
                    self.assertNotIn('COPY', sql)
                    self.assertLessEqual(len(params), 200)
                if count >= 100:
                    self.assertIn('), (', self.db.calls[0][0])

    def test_all_typed_values_and_explicit_ids_match_original_dbapi_order(self):
        table = Table('typed', MetaData(), Column('id', Integer, primary_key=True),
                      Column('s', String), Column('b', Boolean), Column('n', Numeric),
                      Column('d', Date), Column('at', DateTime), Column('f', Float),
                      Column('blob', LargeBinary), Column('null', Text))
        rows = [dict(id=i, s='한글 雪 %\\x\n', b=i % 2 == 0, n=decimal.Decimal('12.3400'),
                     d=dt.date(2026, 11, 9), at=dt.datetime(2026, 11, 9, 3, 4, 5),
                     f=1.25, blob=b'\x00\xff\x80', null=None) for i in range(101)]
        rows[1] = dict(reversed(list(rows[1].items())))
        expected = []
        for row in rows:
            compiled = table.insert().values(row).compile(dialect=self.connection.dialect)
            params = compiled.construct_params()
            expected.extend(compiled._bind_processors[k](params[k]) if k in compiled._bind_processors
                            else params[k] for k in compiled.positiontup)
        for statement in self.statements(rows, table):
            self.connection.execute(statement)
        self.assertEqual([value for _, params in self.db.calls for value in params], expected)

    def test_wire_size_matches_actual_driver_bind_bytes_and_processors(self):
        rows = [dict(id=1, payload='雪🙂'), dict(id=2, payload=None)]
        statement = self.statements(rows)[0]
        self.connection.execute(statement)
        sql, params = self.db.calls[0]
        encoded = make_params(self.db.py_types, params)
        expected = sum(4 + (0 if value is None else len(value.encode('utf8'))) for value in encoded)
        sizes = self.sizes(statement, 2)
        self.assertEqual(sizes, dict(rows=2, binds=4, sql_bytes=len(sql.encode()), parameter_bytes=25))
        self.assertEqual(sizes['parameter_bytes'], expected)

    def test_exact_four_mib_singleton_and_oversized_row_are_isolated(self):
        for size in [wr.INSERT_MAX_PARAMETER_BYTES, wr.INSERT_MAX_PARAMETER_BYTES + 1]:
            rows = [dict(id=1, payload='x' * (size - 9)), dict(id=2, payload='small')]
            statements = self.statements(rows)
            self.assertEqual(len(statements), 2)
            self.assertEqual(self.sizes(statements[0], 1)['parameter_bytes'], size)
            self.assertEqual(self.sizes(statements[1], 1)['parameter_bytes'], 14)

    def test_exact_four_mib_multirow_and_next_byte_split(self):
        size = wr.INSERT_MAX_PARAMETER_BYTES
        rows = [dict(id=1, payload='x' * (size // 2 - 9)),
                dict(id=2, payload='x' * (size // 2 - 9))]
        statements = self.statements(rows)
        self.assertEqual(len(statements), 1)
        self.assertEqual(self.sizes(statements[0], 2)['parameter_bytes'], size)
        rows[1]['payload'] += 'x'
        self.assertEqual(len(self.statements(rows)), 2)

    def test_eight_mib_singleton_boundary_is_enforced(self):
        row = dict(id=1, payload='x' * (wr.INSERT_MAX_SINGLETON_BYTES - 9))
        statement = self.statements([row])[0]
        self.assertEqual(self.sizes(statement, 1)['parameter_bytes'], wr.INSERT_MAX_SINGLETON_BYTES)
        row['payload'] += 'x'
        with self.assertRaisesRegex(wr.Stop, 'INSERT_SINGLETON_BUDGET_EXCEEDED'):
            self.statements([row])
        self.assertEqual(self.db.calls, [])

    def test_bytea_hex_expansion_and_utf8_are_measured_not_python_lengths(self):
        table = Table('binary', MetaData(), Column('id', Integer, primary_key=True),
                      Column('payload', LargeBinary))
        statement = self.statements([dict(id=1, payload=b'\x00\xff' * 500)], table)[0]
        self.assertEqual(self.sizes(statement, 1)['parameter_bytes'], 2011)
        statement = self.statements([dict(id=1, payload='雪' * 1000)])[0]
        self.assertEqual(self.sizes(statement, 1)['parameter_bytes'], 3009)

    def test_bind_budget_exact_boundary_and_wider_rows(self):
        for columns, row_count, expected in [(80, 100, 1), (81, 100, 2)]:
            table = Table('wide', MetaData(), Column('id', Integer, primary_key=True),
                          *(Column('c' + str(i), Text) for i in range(columns - 1)))
            rows = [dict(id=i, **{'c' + str(j): None for j in range(columns - 1)}) for i in range(row_count)]
            statements = self.statements(rows, table)
            self.assertEqual(len(statements), expected)
            for statement in statements:
                compiled = statement.compile(dialect=self.connection.dialect)
                self.assertLessEqual(len(compiled.params), 8000)
            if columns == 80:
                self.assertEqual(len(statements[0].compile(dialect=self.connection.dialect).params), 8000)

    def test_compiled_sql_budget_splits_and_rejects_oversized_singleton(self):
        rows = [dict(id=i, payload='x') for i in range(4)]
        single = self.sizes(self.statements(rows[:1])[0], 1)['sql_bytes']
        with mock.patch.object(wr, 'INSERT_MAX_SQL_BYTES', single):
            self.assertEqual(len(self.statements(rows)), 4)
        with mock.patch.object(wr, 'INSERT_MAX_SQL_BYTES', single - 1):
            with self.assertRaisesRegex(wr.Stop, 'INSERT_SINGLETON_BUDGET_EXCEEDED'):
                self.statements(rows[:1])

    def test_missing_extra_or_mixed_columns_rejected_without_dispatch(self):
        for rows in [[dict(id=1)], [dict(id=1, payload='x', extra='no')],
                     [dict(id=1, payload='x'), dict(id=2)]]:
            with self.subTest(rows=rows), self.assertRaisesRegex(wr.Stop, 'INSERT_ROW_COLUMNS_CHANGED'):
                self.statements(rows)
        self.assertEqual(self.db.calls, [])

    def test_missing_primary_key_and_nonprimitive_values_fail_closed(self):
        with self.assertRaisesRegex(wr.Stop, 'INSERT_EXPLICIT_PRIMARY_KEY_REQUIRED'):
            self.statements([dict(id=None, payload='x')])
        for value in [literal('sql-expression'), [], {}, object(), memoryview(b'x')]:
            with self.assertRaisesRegex(wr.Stop, 'INSERT_PARAMETER_TYPE_UNSUPPORTED'):
                self.statements([dict(id=1, payload=value)])
        table = Table('no_primary', MetaData(), Column('payload', Text))
        with self.assertRaisesRegex(wr.Stop, 'INSERT_TABLE_SHAPE_UNSUPPORTED'):
            list(wr.iter_insert_batches(self.connection, table, [dict(payload='x')]))
        self.assertEqual(self.db.calls, [])

    def test_real_on_connect_initialization_is_required_and_exact_map_accepted(self):
        expected = PY_TYPES.copy()
        expected[quoted_name] = PY_TYPES[str]
        self.assertEqual(self.db.py_types, expected)
        self.assertIs(self.db.py_types[quoted_name], PY_TYPES[str])
        self.assertNotIn(quoted_name, PY_TYPES)
        self.db.py_types = PY_TYPES.copy()
        with self.assertRaisesRegex(wr.Stop, 'INSERT_ENCODING_OR_ADAPTER_UNSUPPORTED'):
            self.statements([dict(id=1, payload='synthetic')])
        self.connection.dialect.on_connect()(self.db)
        statement = self.statements([dict(id=1, payload='synthetic')])[0]
        self.connection.execute(statement)
        self.assertEqual(self.db.calls[0][1], (1, 'synthetic'))
        self.assertEqual(self.sizes(statement, 1)['parameter_bytes'], 18)
        # Exercise create_engine's real pool hook registration too. Only
        # server introspection is mocked; creator prevents socket creation.
        db = FakeDB()
        engine = create_engine('postgresql+pg8000://', creator=lambda: db, poolclass=StaticPool)
        try:
            with mock.patch.object(engine.dialect, 'initialize') as initialize:
                with engine.connect() as connection:
                    self.assertEqual(db.py_types.keys(), expected.keys())
                    self.assertTrue(all(db.py_types[key] is value for key, value in expected.items()))
                    for batch in wr.iter_insert_batches(connection, self.table, [dict(id=1, payload='synthetic')]):
                        connection.execute(batch)
                initialize.assert_called_once()
            self.assertEqual(db.calls[0][1], (1, 'synthetic'))
        finally:
            engine.dispose()

    def test_missing_unknown_and_replaced_adapter_entries_are_rejected(self):
        initialized = self.db.py_types.copy()
        class DeceptiveConverter:
            def __call__(self, value):
                return str(value) + '-changed'
            def __eq__(self, other):
                return True
        cases = [
            ('missing_quoted_name', lambda adapters: adapters.pop(quoted_name)),
            ('missing_builtin', lambda adapters: adapters.pop(int)),
            ('replaced_quoted_name', lambda adapters: adapters.update({quoted_name: lambda value: str(value)})),
            ('replaced_str', lambda adapters: adapters.update({str: lambda value: str(value)})),
            ('replaced_builtin', lambda adapters: adapters.update({int: lambda value: str(value)})),
            ('unknown_adapter', lambda adapters: adapters.update({object: lambda value: str(value)})),
            ('deceptive_equality', lambda adapters: adapters.update({str: DeceptiveConverter()})),
        ]
        for name, mutate in cases:
            with self.subTest(adapter=name):
                self.db.py_types = initialized.copy()
                mutate(self.db.py_types)
                with self.assertRaisesRegex(wr.Stop, 'INSERT_ENCODING_OR_ADAPTER_UNSUPPORTED'):
                    self.statements([dict(id=1, payload='synthetic')])
        self.assertEqual(self.db.calls, [])
        class AdapterMap(dict):
            pass
        self.db.py_types = AdapterMap(initialized)
        with self.assertRaisesRegex(wr.Stop, 'INSERT_ENCODING_OR_ADAPTER_UNSUPPORTED'):
            self.statements([dict(id=1, payload='synthetic')])
        self.db.py_types = initialized
        self.assertEqual(len(self.statements([dict(id=1, payload='synthetic')])), 1)

    def test_unknown_encoding_client_and_custom_adapter_fail_closed(self):
        rows = [dict(id=1, payload='x')]
        self.db._client_encoding = 'latin1'
        with self.assertRaisesRegex(wr.Stop, 'INSERT_ENCODING_OR_ADAPTER_UNSUPPORTED'):
            self.statements(rows)
        self.db._client_encoding = 'utf8'
        self.db.py_types[str] = lambda value: value + 'changed'
        with self.assertRaisesRegex(wr.Stop, 'INSERT_ENCODING_OR_ADAPTER_UNSUPPORTED'):
            self.statements(rows)
        self.db.py_types = PY_TYPES.copy()
        self.connection.dialect.on_connect()(self.db)
        with mock.patch.object(self.connection.dialect, 'driver', 'other'):
            with self.assertRaisesRegex(wr.Stop, 'INSERT_CLIENT_UNSUPPORTED'):
                self.statements(rows)

    def test_compiler_shape_drift_fails_closed(self):
        statement = self.table.insert().values([dict(id=1, payload='x')])
        compiled = statement.compile(dialect=self.connection.dialect)
        for attribute, value in [('post_compile_params', {'unexpected'}),
                                 ('positiontup', ['id_m0', 'id_m0'])]:
            with mock.patch.object(statement, 'compile', return_value=compiled), mock.patch.object(compiled, attribute, value):
                with self.assertRaises(wr.Stop):
                    self.sizes(statement, 1)
        with self.assertRaises(wr.Stop):
            self.sizes(self.table.insert().values([dict(id=1, payload='x')]).returning(self.table.c.id), 1)

    def test_middle_batch_error_propagates_once_without_retry(self):
        self.db.fail_at = 2
        with self.assertRaisesRegex(RuntimeError, 'synthetic batch failure'):
            for statement in self.statements([dict(id=i, payload='x') for i in range(301)]):
                self.connection.execute(statement)
        self.assertEqual(len(self.db.calls), 2)
        self.assertEqual(self.db.calls[0][1][::2], tuple(range(100)))
        self.assertEqual(self.db.calls[1][1][::2], tuple(range(100, 200)))

    def test_full_synthetic_source_dispatch_preserves_table_and_row_order(self):
        import json
        from pathlib import Path
        from synthetic_fixture import fixture
        from test_restore_unit import policy_metadata
        root = Path(wr.__file__).parent
        policy = json.loads((root / 'policy.json').read_text())
        counts = json.loads((root / 'source-counts.json').read_text())
        data, columns, _ = fixture(policy, counts)
        tables = policy_metadata(policy)
        typed, order = wr.typed_payload(data, columns, tables, counts)
        wr.defer_push_subscription(typed, wr.DEFERRED_SOURCE_ROWS)
        if 'vehicle_id' not in tables['vehicle'].c:
            tables['vehicle'].append_column(Column('vehicle_id', String(50)))
        total = 0
        for name in order:
            before = len(self.db.calls)
            for statement in wr.iter_insert_batches(self.connection, tables[name], typed[name]):
                self.connection.execute(statement)
            observed = [value for _, params in self.db.calls[before:] for value in params]
            wanted = []
            for row in typed[name]:
                compiled = tables[name].insert().values(row).compile(dialect=self.connection.dialect)
                params = compiled.construct_params()
                wanted.extend(compiled._bind_processors[k](params[k]) if k in compiled._bind_processors
                              else params[k] for k in compiled.positiontup)
            self.assertEqual(observed, wanted, name)
            total += len(typed[name])
        self.assertEqual(total, 4099)
        self.assertLess(len(self.db.calls), 100)
        self.assertTrue(all('RETURNING' not in sql for sql, _ in self.db.calls))
