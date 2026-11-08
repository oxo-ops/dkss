#!/usr/bin/env python3
"""Offline tests: real SQLAlchemy Inspector/PG compilation, inert catalog/results.

No Engine, DBAPI connection, socket, subprocess, or database is created. Private
Inspector construction is test-only, to provide an inert connection. Production
uses only the public reflection APIs. All fixture values are synthetic.
"""
from __future__ import annotations
import ast
import sys
sys.dont_write_bytecode = True
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import sqlalchemy
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine.reflection import Inspector, ObjectKind, ObjectScope
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BindParameter, BooleanClauseList, Grouping, Null, Tuple
from sqlalchemy.sql.functions import Function
from sqlalchemy.sql.selectable import CompoundSelect, Select

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
import catalog_baseline as old
import worlex_restore as new


def source_function_and_remainder(path):
    # UTF-8 and line endings are explicit so Linux and Windows compare the
    # same Git source bytes, independently of Python AST version details.
    source = path.read_bytes().decode('utf-8')
    if path.name == 'worlex_restore.py':
        # Restore the independently pinned old sequence function before the original scope check.
        import sequence_baseline
        baseline = (HERE / 'sequence_baseline.py').read_text()
        bn = next(n for n in ast.parse(baseline).body if isinstance(n, ast.FunctionDef) and n.name == 'sequence_states')
        bf = ''.join(baseline.splitlines(keepends=True)[bn.lineno-1:bn.end_lineno])
        sn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'sequence_states')
        sl = source.splitlines(keepends=True)
        source = ''.join(sl[:sn.lineno-1]) + bf + ''.join(sl[sn.end_lineno:])
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == 'check_empty_and_itc')
    lines = source.splitlines(keepends=True)
    return (node, ''.join(lines[node.lineno-1:node.end_lineno]),
            ''.join(lines[:node.lineno-1] + lines[node.end_lineno:]))


class Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def mappings(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


def evaluate(node, row):
    if isinstance(node, BindParameter):
        return node.value
    if isinstance(node, Null):
        return None
    if isinstance(node, Grouping):
        return evaluate(node.element, row)
    if isinstance(node, Tuple):
        return tuple(evaluate(x, row) for x in node.clauses)
    if isinstance(node, BooleanClauseList):
        values = [evaluate(x, row) for x in node.clauses]
        return all(values) if node.operator is operators.and_ else any(values)
    if isinstance(node, Function):
        if node.name != 'lower':
            raise RuntimeError('UNEXPECTED_FIXTURE_FUNCTION')
        value = evaluate(list(node.clauses)[0], row)
        return None if value is None else value.lower()
    if hasattr(node, 'left') and hasattr(node, 'right'):
        left, right = evaluate(node.left, row), evaluate(node.right, row)
        if node.operator is operators.in_op:
            return left in right
        if node.operator is operators.eq:
            return left == right
        raise RuntimeError('UNEXPECTED_FIXTURE_OPERATOR')
    if hasattr(node, 'name'):
        return row.get(node.name)
    raise RuntimeError('UNEXPECTED_FIXTURE_NODE')


class InertConnection:
    def __init__(self, fixture, version=(17, 0)):
        self.fixture = fixture
        self.dialect = PGDialect()
        self.dialect.server_version_info = version
        self.engine = SimpleNamespace(dialect=self.dialect)
        self.catalog_calls = []
        self.application_calls = []
        self.inspectors = []
        self.reflection_requests = []
        self.mutation = None
        self.fail_kind = None
        self.transaction = object()
        self.expanded_unique_calls = []
        self.collision_batches = []

    def get_transaction(self):
        return self.transaction

    def in_transaction(self):
        return self.transaction is not None

    def inspector(self):
        inspector = Inspector._construct(Inspector._init_connection, self)
        self.inspectors.append(inspector)
        # Spy on public bulk calls without substituting their SQLAlchemy logic.
        for method in ('get_multi_unique_constraints', 'get_multi_indexes'):
            original = getattr(inspector, method)
            def observe(*args, _method=method, _original=original, **kwargs):
                self.reflection_requests.append((_method, copy.deepcopy(kwargs)))
                result = _original(*args, **kwargs)
                return self.mutation(_method, result) if self.mutation else result
            setattr(inspector, method, observe)
        return inspector

    def compile(self, statement, parameters=None):
        bound = statement.params(**(parameters or {}))
        compiled = bound.compile(dialect=self.dialect, compile_kwargs={'render_postcompile': True})
        return str(compiled), compiled.params

    def execute(self, statement, parameters=None):
        sql, params = self.compile(statement, parameters)
        branches = list(statement.selects) if isinstance(statement, CompoundSelect) else [statement]
        if all(isinstance(branch, Select) and list(branch.selected_columns.keys()) == ['probe_ordinal', 'has_collision'] for branch in branches):
            self.application_calls.append((sql, params))
            result = []
            for branch in branches:
                columns = list(branch.selected_columns)
                ordinal = columns[0].element.value
                inner = columns[1].element.element.element
                self.expanded_unique_calls.append(self.compile(inner))
                table = inner.get_final_froms()[0]
                matched = any(all(evaluate(c, row) for c in inner._where_criteria)
                              for row in self.fixture['target'].get(table.name, []))
                result.append((ordinal, matched))
            self.collision_batches.append({'branches': len(branches), 'binds': len(params), 'sql_bytes': len(sql.encode())})
            return Result(result)
        parameters = parameters or {}
        if statement is self.dialect._constraint_query:
            kind = 'unique_constraints'
            records = [copy.deepcopy(row) for entry in self.fixture['catalog'].values()
                       if entry['oid'] in parameters['oids'] for row in entry['constraints']]
        elif statement is self.dialect._index_query:
            kind = 'indexes'
            records = [copy.deepcopy(row) for entry in self.fixture['catalog'].values()
                       if entry['oid'] in parameters['oids'] for row in entry['indexes']]
        elif 'pg_catalog.pg_class' in sql:
            kind = 'table_oids'
            names = parameters.get('filter_names')
            records = [(entry['oid'], name) for name, entry in self.fixture['catalog'].items()
                       if not names or name in names]
        else:
            self.application_calls.append((sql, params))
            table = statement.get_final_froms()[0]
            rows = [r for r in self.fixture['target'].get(table.name, [])
                    if all(evaluate(c, r) for c in statement._where_criteria)]
            result = [tuple(evaluate(c, r) for c in statement.selected_columns) for r in rows]
            if statement._limit_clause is not None:
                result = result[:evaluate(statement._limit_clause, {})]
            return Result(result)
        self.catalog_calls.append({'kind': kind, 'sql': sql, 'parameters': params})
        if kind == self.fail_kind:
            raise sqlalchemy.exc.InterfaceError(None, None, RuntimeError('SYNTHETIC_OFFLINE_FAILURE'))
        return Result(records)

    def scalar(self, statement):
        sql, params = self.compile(statement)
        self.application_calls.append((sql, params))
        table = statement.get_final_froms()[0]
        return sum(all(evaluate(c, r) for c in statement._where_criteria)
                   for r in self.fixture['target'].get(table.name, []))

    def scalars(self, statement):
        return [row[0] for row in self.execute(statement).all()]


def fixture(count=1, identity=False):
    metadata = MetaData(schema='public')
    tables = {
        'company': Table('company', metadata, Column('company_code', String)),
        'user': Table('user', metadata, Column('id', Integer, primary_key=True),
                      Column('company_code', String), Column('username', String), Column('role', String)),
    }
    typed, target, catalog = {}, {'company': [{'company_code': 'ITC'}],
                                 'user': [{'id': 1, 'company_code': 'ITC', 'username': 'itc', 'role': 'itc'}]}, {}
    for i in range(count):
        name = 'thing' if count == 1 else 'thing_%03d' % i
        columns = [Column('id', Integer, primary_key=True), Column('company_code', String),
                   Column('key_a', String), Column('key_b', String)]
        if identity:
            columns += [Column('account_identity', String), Column('master_generation', String)]
        tables[name] = Table(name, metadata, *columns)
        typed[name] = [{'id': 10, 'company_code': 'WORLEX', 'key_a': 'new', 'key_b': 'b'}]
        target[name] = [{'id': 99, 'company_code': 'ITC', 'key_a': 'existing', 'key_b': 'b'}]
        if identity:
            typed[name][0].update(account_identity='00000000-0000-0000-0000-000000000010',
                                 master_generation='00000000-0000-0000-0000-000000000020')
            target[name][0].update(account_identity='00000000-0000-0000-0000-000000000099',
                                  master_generation='00000000-0000-0000-0000-000000000098')
        catalog[name] = {'oid': 1000 + i, 'constraints': [], 'indexes': []}
    return {'tables': tables, 'typed': typed, 'target': target, 'catalog': catalog}


def constraint(f, name='thing', columns=None, nnd=False):
    row = {'conrelid': f['catalog'][name]['oid'], 'cols': columns if columns is not None else ['key_a'],
           'conname': 'uq_' + name, 'description': None, 'indnkeyatts': len(columns) if columns is not None else 1,
           'indnullsnotdistinct': nnd}
    f['catalog'][name]['constraints'].append(row)
    return row


def index(f, name='thing', columns=None, unique=True, nnd=False, partial=None, expression=False, duplicate=False):
    columns = columns if columns is not None else ['key_a']
    row = {'indrelid': f['catalog'][name]['oid'], 'relname': 'ix_' + name,
           'elements': columns, 'elements_is_expr': [expression] * len(columns),
           'elements_opclass': ['text_ops'] * len(columns), 'elements_opdefault': [True] * len(columns),
           'indnkeyatts': len(columns), 'indisunique': unique, 'indoption': [0] * len(columns),
           'has_constraint': duplicate, 'reloptions': None, 'amname': 'btree',
           'filter_definition': partial, 'indnullsnotdistinct': nnd}
    f['catalog'][name]['indexes'].append(row)
    return row


def run(core, f, *, version=(17, 0), mutation=None, connection=None):
    conn = connection or InertConnection(f, version)
    conn.mutation = mutation
    try:
        with patch.object(core, 'inspect', side_effect=lambda actual: conn.inspector() if actual is conn else None):
            core.check_empty_and_itc(conn, f['tables'], f['typed'])
    except core.Stop as exc:
        outcome = str(exc)
    except sqlalchemy.exc.ArgumentError:
        # Inherited expression-column None behavior; production CLI emits type only.
        outcome = 'ERROR:ArgumentError'
    else:
        outcome = 'PASS'
    return outcome, conn


class EquivalenceTests(unittest.TestCase):
    def equivalent(self, f, expected='PASS', version=(17, 0)):
        a, ca = run(old, f, version=version)
        b, cb = run(new, f, version=version)
        self.assertEqual(a, expected)
        self.assertEqual(b, expected)
        if expected == 'PASS':
            original_unique = [query for query in ca.application_calls if 'IN ((' in query[0]]
            distinct = []
            for query in original_unique:
                if query not in distinct:
                    distinct.append(query)
            self.assertEqual(distinct, cb.expanded_unique_calls)
            self.assertEqual([query for query in ca.application_calls if 'IN ((' not in query[0]],
                             [query for query in cb.application_calls if 'probe_ordinal' not in query[0]])
        return ca, cb

    def test_exact_source_and_change_scope(self):
        self.assertEqual(sqlalchemy.__version__, '2.0.50')
        old_node, old_source, _ = source_function_and_remainder(HERE / 'catalog_baseline.py')
        node, _, remainder = source_function_and_remainder(ROOT / 'worlex_restore.py')
        self.assertEqual(hashlib.sha256(old_source.encode()).hexdigest(), old.BASELINE_FUNCTION_SHA256)
        from integrated_change_scope import assert_unchanged_business_functions
        assert_unchanged_business_functions(self, (ROOT / 'worlex_restore.py').read_text())
        self.assertFalse(any(isinstance(n, ast.Assert) for n in ast.walk(node)))
        # Index/source guard prefix and PK/tenant/UUID checks stay identical;
        # only the target probe delivery is batched.
        old_loop = next(n for n in old_node.body if isinstance(n, ast.For) and any(isinstance(x, ast.For) and isinstance(x.target, ast.Name) and x.target.id == 'index' for x in n.body))
        new_loop = next(n for n in node.body if isinstance(n, ast.For) and any(isinstance(x, ast.For) and isinstance(x.target, ast.Name) and x.target.id == 'index' for x in n.body))
        self.assertEqual([ast.dump(n) for n in old_loop.body[-1].body[:6]],
                         [ast.dump(n) for n in new_loop.body[-1].body[0].body[:6]])
        self.assertEqual([ast.dump(n) for n in old_node.body[:3]], [ast.dump(n) for n in node.body[:3]])
        self.assertEqual([ast.dump(n) for n in old_node.body[-3:]], [ast.dump(n) for n in node.body[-3:]])

    def test_no_unique_constraints(self):
        self.equivalent(fixture())

    def test_constraint_and_unique_index(self):
        f = fixture(); constraint(f); index(f, columns=['key_b', 'key_a'])
        self.equivalent(f)

    def test_source_natural_key_collision(self):
        f = fixture(); constraint(f)
        f['typed']['thing'].append(dict(f['typed']['thing'][0], id=11))
        self.equivalent(f, 'SOURCE_UNIQUE_KEY_COLLISION:thing')

    def test_target_natural_key_collision(self):
        f = fixture(); constraint(f); f['target']['thing'][0]['key_a'] = 'new'
        self.equivalent(f, 'TARGET_UNIQUE_KEY_COLLISION:thing')

    def test_unique_index_target_collision(self):
        f = fixture(); index(f); f['target']['thing'][0]['key_a'] = 'new'
        self.equivalent(f, 'TARGET_UNIQUE_KEY_COLLISION:thing')

    def test_composite_key_noncollision(self):
        f = fixture(); constraint(f, columns=['key_a', 'key_b'])
        f['typed']['thing'].append(dict(f['typed']['thing'][0], id=11, key_b='c'))
        self.equivalent(f)

    def test_null_keys_skipped(self):
        for columns in [['key_a'], ['key_a', 'key_b']]:
            with self.subTest(columns=columns):
                f = fixture(); constraint(f, columns=columns)
                f['typed']['thing'] = [dict(f['typed']['thing'][0], id=i, key_a=None) for i in [10, 11]]
                f['target']['thing'][0]['key_a'] = None
                self.equivalent(f)

    def test_partial_index_keeps_conservative_full_key_check(self):
        f = fixture(); index(f, partial='key_b IS NOT NULL')
        f['target']['thing'][0].update(key_a='new', key_b=None)
        self.equivalent(f, 'TARGET_UNIQUE_KEY_COLLISION:thing')

    def test_partial_index_noncollision(self):
        f = fixture(); index(f, partial='key_b IS NOT NULL')
        self.equivalent(f)

    def test_expression_index_blocked(self):
        f = fixture(); index(f, columns=['lower(key_a)'], expression=True)
        self.equivalent(f, 'ERROR:ArgumentError')

    def test_unknown_and_empty_columns_blocked(self):
        for columns in [[], ['unknown'], [None]]:
            with self.subTest(columns=columns):
                f = fixture(); constraint(f, columns=columns)
                self.equivalent(f, 'ERROR:ArgumentError' if columns == [None] else 'EXPRESSION_UNIQUE_INDEX_BLOCKED:thing')

    def test_nulls_not_distinct_constraint_and_index_blocked(self):
        for factory in [constraint, index]:
            with self.subTest(factory=factory.__name__):
                f = fixture(); factory(f, nnd=True); f['typed']['thing'][0]['key_a'] = None
                self.equivalent(f, 'NULLS_NOT_DISTINCT_INDEX_BLOCKED:thing')

    def test_nonunique_expression_index_ignored(self):
        f = fixture(); index(f, columns=['lower(key_a)'], expression=True, unique=False)
        self.equivalent(f)

    def test_duplicate_constraint_backing_index_retained(self):
        f = fixture(); constraint(f); index(f, duplicate=True)
        ca, cb = self.equivalent(f)
        self.assertEqual(len([sql for sql, _ in ca.application_calls if 'IN ((' in sql]), 2)
        self.assertEqual(len(cb.expanded_unique_calls), 1)
        self.assertEqual(len(cb.collision_batches), 1)

    def test_seen_dedup_null_and_500_row_chunk_semantics(self):
        f = fixture(); constraint(f)
        f['typed']['thing'] = [{'id': 1000+i, 'company_code': 'WORLEX', 'key_a': 'k%04d' % i, 'key_b': 'b'} for i in range(1001)]
        _, cb = self.equivalent(f)
        unique_calls = [params for sql, params in cb.expanded_unique_calls]
        self.assertEqual(len(unique_calls), 3)
        self.assertEqual([len([k for k in params if k.startswith('param_1_')]) for params in unique_calls], [500, 500, 1])

    def test_pk_collision_before_catalog(self):
        f = fixture(); f['target']['thing'][0]['id'] = 10
        _, cb = self.equivalent(f, 'PRIMARY_KEY_COLLISION:thing')
        self.assertEqual(cb.catalog_calls, [])

    def test_tenant_case_alias_before_catalog(self):
        f = fixture(); f['target']['thing'][0]['company_code'] = 'wOrLeX'
        _, cb = self.equivalent(f, 'TARGET_WORLEX_OR_CASE_ALIAS_EXISTS:thing')
        self.assertEqual(cb.catalog_calls, [])

    def test_uuid_and_generation_checks_unchanged(self):
        f = fixture(identity=True); self.equivalent(f)
        for field in ['account_identity', 'master_generation']:
            for value, expected in [('invalid', 'INVALID_EXISTING_GENERATION:thing'),
                                    (f['typed']['thing'][0][field], 'GENERATED_IDENTIFIER_COLLISION:thing')]:
                with self.subTest(field=field, expected=expected):
                    changed = dict(f, target=copy.deepcopy(f['target']))
                    changed['target']['thing'][0][field] = value
                    _, cb = self.equivalent(changed, expected)
                    self.assertEqual(cb.catalog_calls, [])

    def test_existing_uuid_duplicate_rejected(self):
        f = fixture(identity=True)
        f['target']['thing'].append(dict(f['target']['thing'][0], id=100))
        self.equivalent(f, 'INVALID_EXISTING_GENERATION:thing')

    def test_itc_guards_unchanged(self):
        for table, expected in [('company', 'ITC_COMPANY_MISSING'), ('user', 'ITC_ADMIN_MISSING')]:
            with self.subTest(table=table):
                f = fixture(); f['target'][table] = []
                self.equivalent(f, expected)

    def test_empty_typed_never_queries_all_catalog(self):
        f = fixture(); f['typed']['thing'] = []
        ca, cb = self.equivalent(f)
        self.assertEqual(ca.catalog_calls, [])
        self.assertEqual(cb.catalog_calls, [])
        self.assertEqual(cb.reflection_requests, [])

    def test_only_exact_populated_names_any_kind_any_scope(self):
        f = fixture(3); f['typed']['thing_001'] = []
        _, cb = self.equivalent(f)
        self.assertEqual(len(cb.reflection_requests), 2)
        for _, kwargs in cb.reflection_requests:
            self.assertEqual(kwargs, {'schema': 'public', 'filter_names': ['thing_000', 'thing_002'],
                                      'kind': ObjectKind.ANY, 'scope': ObjectScope.ANY})
        oid_query = next(c for c in cb.catalog_calls if c['kind'] == 'table_oids')
        self.assertNotIn('relpersistence', oid_query['sql'])
        self.assertEqual(oid_query['parameters']['nspname_1'], 'public')
        self.assertEqual({v for k, v in oid_query['parameters'].items() if k.startswith('param_')}, {'r', 'p', 'f', 'v', 'm'})

    def test_missing_foreign_extra_keys_fail_closed(self):
        for method, code in [('get_multi_unique_constraints', 'UNIQUE_CATALOG_SCOPE_MISMATCH'),
                             ('get_multi_indexes', 'INDEX_CATALOG_SCOPE_MISMATCH')]:
            for mode in ['missing', 'extra', 'foreign_schema', 'none_schema']:
                with self.subTest(method=method, mode=mode):
                    def mutate(called, result):
                        if called != method:
                            return result
                        result = dict(result)
                        if mode == 'missing':
                            result.pop(('public', 'thing'))
                        elif mode == 'extra':
                            result[('public', 'extra')] = []
                        elif mode == 'foreign_schema':
                            result[('other', 'thing')] = result.pop(('public', 'thing'))
                        else:
                            result[(None, 'thing')] = result.pop(('public', 'thing'))
                        return result
                    outcome, conn = run(new, fixture(), mutation=mutate)
                    self.assertEqual(outcome, code)
                    self.assertFalse(any('IN ((' in sql for sql, _ in conn.application_calls))

    def test_missing_actual_oid_fails_closed(self):
        f = fixture(); f['catalog'].clear()
        outcome, _ = run(new, f)
        self.assertEqual(outcome, 'UNIQUE_CATALOG_SCOPE_MISMATCH')

    def test_fresh_inspector_each_preflight(self):
        f = fixture(); conn = InertConnection(f)
        for _ in range(2):
            self.assertEqual(run(new, f, connection=conn)[0], 'PASS')
        self.assertEqual(len(conn.catalog_calls), 6)
        self.assertEqual(len(conn.inspectors), 2)
        self.assertIsNot(conn.inspectors[0].info_cache, conn.inspectors[1].info_cache)
        other = InertConnection(f)
        self.assertEqual(run(new, f, connection=other)[0], 'PASS')
        self.assertEqual(len(other.catalog_calls), 3)

    def test_real_dialect_maps_and_ordered_combination_equal(self):
        f = fixture(3)
        for name in ['thing_000', 'thing_002']:
            constraint(f, name, columns=['key_a', 'key_b'])
            index(f, name, duplicate=True, partial='key_b IS NOT NULL')
            index(f, name, columns=['key_b'], unique=False)
        old_conn, new_conn = InertConnection(f), InertConnection(f)
        single, bulk = old_conn.inspector(), new_conn.inspector()
        names = list(f['typed'])
        uniques = bulk.get_multi_unique_constraints(schema='public', filter_names=names,
                                                    kind=ObjectKind.ANY, scope=ObjectScope.ANY)
        indexes = bulk.get_multi_indexes(schema='public', filter_names=names,
                                        kind=ObjectKind.ANY, scope=ObjectScope.ANY)
        self.assertEqual(set(uniques), {('public', n) for n in names})
        self.assertEqual(set(indexes), set(uniques))
        self.assertEqual(uniques[('public', 'thing_001')], [])
        self.assertEqual(indexes[('public', 'thing_001')], [])
        for name in names:
            u = single.get_unique_constraints(name, schema='public')
            i = single.get_indexes(name, schema='public')
            self.assertEqual(u, uniques[('public', name)])
            self.assertEqual(i, indexes[('public', name)])
            self.assertEqual(u + [x for x in i if x.get('unique')],
                             uniques[('public', name)] + [x for x in indexes[('public', name)] if x.get('unique')])

    def test_included_columns_are_not_added_to_unique_key(self):
        f = fixture()
        c = constraint(f, columns=['key_a', 'key_b']); c['indnkeyatts'] = 1
        i = index(f, columns=['key_a', 'key_b']); i['indnkeyatts'] = 1
        f['target']['thing'][0].update(key_a='new', key_b='different')
        self.equivalent(f, 'TARGET_UNIQUE_KEY_COLLISION:thing')

    def test_bulk_query_failure_propagates_without_retry_or_fallback(self):
        for kind, expected_calls in [('table_oids', 1), ('unique_constraints', 2), ('indexes', 3)]:
            with self.subTest(kind=kind):
                f = fixture(); conn = InertConnection(f); conn.fail_kind = kind
                with patch.object(Inspector, 'get_unique_constraints', side_effect=AssertionError('FALLBACK_FORBIDDEN')), \
                     patch.object(Inspector, 'get_indexes', side_effect=AssertionError('FALLBACK_FORBIDDEN')):
                    with self.assertRaises(sqlalchemy.exc.InterfaceError):
                        run(new, f, connection=conn)
                self.assertEqual(len(conn.catalog_calls), expected_calls)
                self.assertFalse(any('IN ((' in sql for sql, _ in conn.application_calls))
                self.assertEqual(len(conn.inspectors), 1)

    def test_real_compiled_catalog_calls_36_tables_108_to_3(self):
        f = fixture(36)
        for name in f['typed']:
            constraint(f, name); index(f, name, duplicate=True)
        ca, cb = self.equivalent(f)
        self.assertEqual(len(ca.catalog_calls), 108)
        self.assertEqual(len(cb.catalog_calls), 3)
        self.assertEqual([c['kind'] for c in cb.catalog_calls], ['table_oids', 'unique_constraints', 'indexes'])
        self.assertLess(len(cb.application_calls), len(ca.application_calls))
        # No generated evidence is written into the tested source tree.

    def test_compilation_across_postgres_dialect_versions(self):
        for version in [(14, 0), (15, 0), (16, 0), (17, 0), (18, 0)]:
            with self.subTest(version=version):
                f = fixture(2)
                for name in f['typed']:
                    constraint(f, name); index(f, name)
                ca, cb = self.equivalent(f, version=version)
                self.assertEqual(len(ca.catalog_calls), 6)
                self.assertEqual(len(cb.catalog_calls), 3)


if __name__ == '__main__':
    if sqlalchemy.__version__ != '2.0.50':
        raise SystemExit('SQLALCHEMY_VERSION_MISMATCH')
    unittest.main(verbosity=2)
