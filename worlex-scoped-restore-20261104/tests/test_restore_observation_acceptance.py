"""Formal inspect on owned CI PostgreSQL; synthetic source boundary only."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import client_connection
import inspect_observation
import worlex_restore as core
from launcher_adapter import persist_stage
import test_restore_postgres as baseline

def deterministic_catalog_order(dialect):
    """Test-only identical catalog input, not a normalized trace comparator.

    PostgreSQL makes no ordering promise for SQLAlchemy's _get_table_oids query.
    Its result order becomes the expanding OID binds for constraint/index reads.
    Sort only those returned (OID, table-name) rows on this engine instance, for
    both compared runs. Execute the original method once, with unchanged inputs;
    retain every original row object. Never alter SQL, binds, or other results.
    """
    original = dialect._get_table_oids
    calls = []
    def ordered(*args, **kwargs):
        rows = list(original(*args, **kwargs))
        if any(len(row) != 2 or type(row[0]) is not int or row[0] <= 0
               or type(row[1]) is not str or not row[1] for row in rows):
            raise AssertionError('INVALID_TEST_CATALOG_IDENTITY')
        if len({row[0] for row in rows}) != len(rows) or len({row[1] for row in rows}) != len(rows):
            raise AssertionError('DUPLICATE_TEST_CATALOG_IDENTITY')
        calls.append(tuple(sorted((row[0], row[1]) for row in rows)))
        return sorted(rows, key=lambda row: row[0])
    dialect._get_table_oids = ordered
    return calls


class DeterministicCatalogInputTests(unittest.TestCase):
    def test_wrapper_forwards_once_without_sql_or_row_replacement(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        first, second = (24450, 'synthetic_b'), (24438, 'synthetic_a')
        original = Mock(return_value=[first, second])
        dialect = SimpleNamespace(_get_table_oids=original)
        unrelated = SimpleNamespace(_get_table_oids=original)
        calls = deterministic_catalog_order(dialect)
        connection, cache = object(), {}
        result = dialect._get_table_oids(connection, 'public', ['synthetic_b', 'synthetic_a'],
            scope='synthetic_scope', kind='synthetic_kind', info_cache=cache)
        original.assert_called_once_with(connection, 'public', ['synthetic_b', 'synthetic_a'],
            scope='synthetic_scope', kind='synthetic_kind', info_cache=cache)
        self.assertIs(result[0], second); self.assertIs(result[1], first)
        self.assertEqual(calls, [((24438, 'synthetic_a'), (24450, 'synthetic_b'))])
        self.assertIs(unrelated._get_table_oids, original)

    def test_wrapper_rejects_duplicates_invalid_oids_and_names(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        for rows in ([(1,'a'),(1,'a')], [(1,'a'),(1,'b')], [(1,'a'),(2,'a')],
                     [(True,'a')], [(0,'a')], [(-1,'a')], [('1','a')],
                     [(1,'')], [(1,None)], [(1,'a','extra')]):
            with self.subTest(rows=rows):
                original = Mock(return_value=rows)
                dialect = SimpleNamespace(_get_table_oids=original)
                calls = deterministic_catalog_order(dialect)
                with self.assertRaisesRegex(AssertionError, 'TEST_CATALOG_IDENTITY'):
                    dialect._get_table_oids('synthetic_connection')
                original.assert_called_once_with('synthetic_connection')
                self.assertEqual(calls, [])

    def compiled_trace(self, rows):
        # The actual pinned SQLAlchemy PG/pg8000 queries and positional binds,
        # using an inert connection. No engine, socket, or database is created.
        from sqlalchemy.dialects.postgresql.pg8000 import PGDialect_pg8000
        from sqlalchemy.engine.reflection import ObjectKind, ObjectScope
        dialect = PGDialect_pg8000(); dialect.server_version_info = (18, 0)
        trace = []
        class Result:
            def all(self): return rows
            def mappings(self): return []
        class Connection:
            def execute(self, statement, parameters):
                compiled = statement.params(**parameters).compile(dialect=dialect,
                    compile_kwargs={'render_postcompile': True})
                trace.append((str(compiled), tuple(compiled.params[name]
                    for name in compiled.positiontup), False))
                return Result()
        calls = deterministic_catalog_order(dialect)
        for method in ('get_multi_pk_constraint','get_multi_indexes','get_multi_unique_constraints'):
            list(getattr(dialect,method)(Connection(), 'public', ['synthetic_a','synthetic_b'],
                ObjectScope.ANY, ObjectKind.ANY))
        self.assertEqual(len(trace),6)  # Three original OID SELECTs plus three catalog SELECTs.
        self.assertEqual(len(calls),3)
        return trace, calls

    def test_actual_catalog_sql_and_binds_equal_for_reordered_input(self):
        rows = [(24450,'synthetic_b'),(24438,'synthetic_a')]
        self.assertEqual(self.compiled_trace(rows), self.compiled_trace(rows[::-1]))

    def test_changed_missing_extra_identity_remains_visible(self):
        rows = [(24450,'synthetic_b'),(24438,'synthetic_a')]
        original = self.compiled_trace(rows)
        for changed in ([(24451,'synthetic_b'),rows[1]],
                        [(24450,'changed_name'),rows[1]], rows[:1], rows+[(24469,'extra')]):
            with self.subTest(rows=changed):
                self.assertNotEqual(original, self.compiled_trace(changed))

    def test_exact_trace_comparison_rejects_sql_bind_order_and_count_changes(self):
        import copy
        original = self.compiled_trace([(24450,'synthetic_b'),(24438,'synthetic_a')])[0]
        original.append(('SELECT synthetic_business_value WHERE id = %s', (123,), False))
        changes = []
        changed = copy.deepcopy(original); changed[-1] = (changed[-1][0], (124,), False); changes.append(changed)
        changed = copy.deepcopy(original); changed[-1] = (changed[-1][0]+' ', (123,), False); changes.append(changed)
        changed = copy.deepcopy(original); changed[-1] = (*changed[-1][:2], True); changes.append(changed)
        changed = copy.deepcopy(original); changed[0],changed[1] = changed[1],changed[0]; changes.append(changed)
        changes.extend([original[:-1],original+[original[-1]]])
        # Even permutation of known OID binds is NOT normalized in the trace.
        changed = copy.deepcopy(original)
        sql, binds, many = changed[1]; swapped=list(binds)
        positions=[i for i,value in enumerate(binds) if value in (24438,24450)]
        swapped[positions[0]],swapped[positions[1]]=swapped[positions[1]],swapped[positions[0]]
        changed[1]=(sql,tuple(swapped),many); changes.append(changed)
        for changed in changes:
            with self.subTest(trace=changes.index(changed)):
                with self.assertRaises(AssertionError): self.assertEqual(original,changed)


class PostgreSQLObservationAcceptance(unittest.TestCase):
    setUpClass = classmethod(baseline.PostgreSQLRestoreAcceptance.setUpClass.__func__)
    setUp = baseline.PostgreSQLRestoreAcceptance.setUp
    unchanged = baseline.PostgreSQLRestoreAcceptance.unchanged

    def invoke_inspect(self, fail=False, diagnostic_fault=None, mandatory_fault=None):
        root = Path(tempfile.mkdtemp(prefix='formal-cli-',dir=self.temp.name))
        source = root/'worlex_restore.py'; source.write_bytes(Path(core.__file__).read_bytes())
        (root/'policy.json').write_text(json.dumps(self.policy))
        (root/'source-counts.json').write_bytes((baseline.PACKAGE/'source-counts.json').read_bytes())
        output = io.StringIO(); real_args = client_connection.connection_args
        real_engine = core.create_engine; calls = []
        def engine(url, **kwargs):
            calls.append(kwargs)
            return real_engine(self.url, **kwargs)
        def args(**kwargs): return real_args(cafile=self.cafile, **kwargs)
        approved = root/'plan.json'; report = root/'report.json'
        url = self.url.set(port=5432).render_as_string(hide_password=False)
        original_open, original_replace, original_write_text = os.open, os.replace, Path.write_text
        injected = []
        def denial():
            error = PermissionError(13, 'synthetic observer denial'); error.winerror = 5
            return error
        def open_file(path, *args, **kwargs):
            if diagnostic_fault == 'early_open' and Path(path).name == 'next.json':
                injected.append('early_open'); raise denial()
            return original_open(path,*args,**kwargs)
        def replace_file(src,dst):
            obs=inspect_observation.LAST
            event=obs.value['events'][-1] if obs is not None and obs.value['events'] else {}
            if (diagnostic_fault == 'after_fetch' and obs is not None and Path(src).parent == obs.directory and event.get('phase') == 'validate_schema'
                    and event.get('operation') == 'cursor_fetchone' and event.get('state') == 'ok'):
                injected.append('after_fetch'); raise denial()
            return original_replace(src,dst)
        def write_text(path,*args,**kwargs):
            if mandatory_fault in ('plan','report') and path == (approved if mandatory_fault == 'plan' else report):
                raise denial()
            return original_write_text(path,*args,**kwargs)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(os,'open',side_effect=open_file))
            stack.enter_context(patch.object(os,'replace',side_effect=replace_file))
            stack.enter_context(patch.object(Path,'write_text',write_text))
            for target, value in [('__file__',str(source)), ('EXPECTED_HOST',self.url.host),
                                  ('EXPECTED_DATABASE',self.url.database), ('EXPECTED_USER',self.url.username)]:
                stack.enter_context(patch.object(core,target,value))
            stack.enter_context(patch.object(core,'enforce_windows_client',return_value={'synthetic':True}))
            stack.enter_context(patch.object(core,'render_archive',return_value='synthetic'))
            stack.enter_context(patch.object(core,'copy_digest',return_value=core.SOURCE_COPY_SHA256))
            stack.enter_context(patch.object(core,'read_copy',return_value=(self.data,self.columns)))
            stack.enter_context(patch.object(core,'create_engine',side_effect=engine))
            stack.enter_context(patch.object(client_connection,'connection_args',side_effect=args))
            stack.enter_context(patch.dict(os.environ,{'WORLEX_NEW_DATABASE_URL':url}))
            stack.enter_context(patch.object(sys,'argv',['restore','inspect','--archive','synthetic',
                '--pg-restore','synthetic','--plan',str(approved),'--report',str(report)]))
            stack.enter_context(contextlib.redirect_stdout(output))
            if mandatory_fault in ('plan','report'):
                with self.assertRaises(PermissionError):core.cli()
                self.assertEqual(output.getvalue(),'')
                observed=inspect_observation.output_fields()['observation']
                self.assertFalse(observed['inspection_completed'])
                self.assertFalse((root/'inspect-finished.json').exists())
                self.assertFalse(Path(str(approved)+'.execution.json').exists())
                self.assertEqual(len(calls),1)
                if diagnostic_fault:self.assertEqual(injected,[diagnostic_fault])
                self.unchanged()
                return observed
            if fail:
                # Real server statement failure, captured before rollback; no retry.
                def denied(connection,*a,**kw): connection.exec_driver_sql('SELECT 1/0')
                stack.enter_context(patch.object(core,'plan',side_effect=denied))
                with self.assertRaises(Exception): core.cli()
                parsed = {'status':'FAILED_OR_COMMIT_UNCERTAIN', **inspect_observation.output_fields()}
            else:
                core.cli(); parsed = json.loads(output.getvalue())
            if mandatory_fault == 'execute_marker':
                execute_report=root/'execute-report.json'
                with patch.object(sys,'argv',['restore','execute','--archive','synthetic',
                    '--pg-restore','synthetic','--plan',str(approved),'--report',str(execute_report),'--writers-stopped']):
                    def marker_open(path,*args,**kwargs):
                        if str(path).endswith('.execution.json'):raise denial()
                        return open_file(path,*args,**kwargs)
                    with patch.object(os,'open',side_effect=marker_open),self.assertRaises(PermissionError):core.cli()
                self.assertFalse(execute_report.exists())
                self.assertFalse(Path(str(approved)+'.execution.json').exists())
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['connect_args']['startup_params']['default_transaction_read_only'],'on')
        if diagnostic_fault:self.assertEqual(injected,[diagnostic_fault])
        if mandatory_fault == 'adapter':
            with patch('launcher_adapter.os.fsync',side_effect=denial()),self.assertRaises(PermissionError):
                persist_stage(root,parsed,stage='inspect',exit_code=0)
            self.assertFalse(Path(str(approved)+'.execution.json').exists())
            self.unchanged()
            return parsed['observation']
        saved = persist_stage(root,parsed,stage='inspect',exit_code=3 if fail else 0)
        self.assertEqual(saved['execute_eligible'],not fail)
        observed = saved['safe_output']['observation']
        self.assertTrue(observed['startup_completed']); self.assertTrue(observed['tls_completed'])
        self.assertIs(type(observed['backend_pid']),int)
        self.assertEqual(observed, parsed['observation'])
        if not fail:
            plan = json.loads(approved.read_text()); plan.pop('client_runtime_sha256')
            self.assertNotIn('observation',plan)
            # Generated UUIDs are pinned to compare the canonical plan only.
            with self.engine.connect() as connection:
                expected = core.plan(connection,self.data,self.columns,self.policy,self.counts,
                    self.source_hash,generated=plan['generated_identifiers'])
            self.assertEqual(plan,expected)
        else:
            self.assertFalse(approved.exists()); self.assertFalse(report.exists())
        self.unchanged()
        return observed

    def test_formal_cli_observation_roundtrip_and_canonical_plan(self):
        observed = self.invoke_inspect()
        self.assertIsNone(observed['primary'])
        self.assertEqual(observed['cleanup'],[])

    def test_formal_cli_server_error_preserved_before_cleanup_no_reconnect(self):
        observed = self.invoke_inspect(fail=True)
        self.assertIsNotNone(observed['primary'])
        self.assertIn('22012', json.dumps(observed['primary']))
        self.assertEqual(observed['cleanup'],[])

    def test_formal_cli_degraded_diagnostics_same_read_only_plan_and_terminal(self):
        observed=self.invoke_inspect(diagnostic_fault='after_fetch')
        self.assertTrue(observed['inspection_completed'])
        self.assertFalse(observed['diagnostic_persistence']['complete'])
        self.assertEqual(observed['diagnostic_persistence']['warning']['operation'],'replace_snapshot')
        self.assertIsNone(observed['primary']);self.assertEqual(observed['cleanup'],[])

    def test_formal_cli_server_error_after_degradation_stays_primary(self):
        observed=self.invoke_inspect(fail=True,diagnostic_fault='early_open')
        self.assertFalse(observed['inspection_completed'])
        self.assertFalse(observed['diagnostic_persistence']['complete'])
        self.assertIn('22012',json.dumps(observed['primary']))
        self.assertEqual(observed['cleanup'],[])

    def test_formal_cli_required_plan_report_adapter_and_execute_marker_still_block(self):
        for target in ('plan','report','adapter','execute_marker'):
            with self.subTest(target=target):
                self.invoke_inspect(diagnostic_fault='after_fetch',mandatory_fault=target)

    def test_instrumentation_preserves_exact_sql_binds_and_connection_count(self):
        from sqlalchemy import event
        from sqlalchemy.pool import NullPool
        traces = []; plans = []; connections = []; catalogs = []
        for mode in ('disabled','healthy','degraded'):
            enabled = mode != 'disabled'
            args = client_connection.connection_args(cafile=self.cafile, read_only=True,
                application_name='worlex_synthetic_restore')
            engine = core.create_engine(self.url, poolclass=NullPool, hide_parameters=True, connect_args=args)
            # Make only the unordered catalog input deterministic on BOTH engines.
            catalog_calls = deterministic_catalog_order(engine.dialect)
            trace = []; opened = []
            event.listen(engine, 'before_cursor_execute', lambda c, cursor, statement, parameters, context, many:
                trace.append((statement, parameters, many)))
            event.listen(engine, 'connect', lambda dbapi, record: opened.append(True))
            observer = inspect_observation.Observation(Path(self.temp.name)) if enabled else None
            if observer:
                observer.install(engine,args)
                if mode == 'degraded':
                    with patch('inspect_observation.os.replace',side_effect=PermissionError(13,'synthetic')):
                        observer.persist()
                    self.assertFalse(observer.value['diagnostic_persistence']['complete'])
            inspect_observation.ACTIVE = observer
            try:
                with engine.connect() as connection, connection.begin():
                    connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                    plans.append(core.plan(connection,self.data,self.columns,self.policy,self.counts,
                        self.source_hash,generated=self.approved['generated_identifiers']))
            finally:
                engine.dispose(); inspect_observation.ACTIVE = None
            traces.append(trace); connections.append(len(opened)); catalogs.append(catalog_calls)
        self.assertTrue(catalogs[0])
        for index in (1,2):
            self.assertEqual(catalogs[0],catalogs[index])
            self.assertEqual(plans[0],plans[index]);self.assertEqual(traces[0],traces[index])
        self.assertIn(('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY',(),False),traces[0])
        self.assertEqual(connections,[1,1,1]); self.unchanged()

    def test_locked_context_rejects_other_connection_and_stale_transaction(self):
        original = core.plan
        with self.engine.connect() as other:
            stale_transaction = other.begin(); stale_transaction.rollback()
        for field, replacement in (('connection',other), ('transaction',stale_transaction)):
            def substituted(*args, **kwargs):
                result = original(*args, **kwargs)
                kwargs['_context'][field] = replacement
                return result
            with self.subTest(field=field), self.engine.begin() as connection:
                with patch.object(core,'plan',side_effect=substituted):
                    with self.assertRaisesRegex(core.Stop,'LOCKED_PLAN_CONTEXT_CHANGED'):
                        core.execute_restore(connection,self.data,self.columns,self.policy,
                            self.counts,self.source_hash,self.approved)
            self.unchanged()
