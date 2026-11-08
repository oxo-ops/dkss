"""Offline-only, synthetic CI diagnostics; no engines, sockets or child runs."""
import copy
import json
import os
import pathlib
import ssl
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_restore_postgres as target


class SchemaDiagnosticsTests(unittest.TestCase):
    def event(self, error=None, phase='init_db'):
        graph = target.schema_exception_graph(error)
        return dict(version=1, phase=phase, status='failed' if error else 'started',
                    elapsed_seconds=1.25, cpu_seconds=0.05, exception_chain=graph['nodes'],
                    exception_graph=graph, utc='2026-11-09T00:01:02.123Z')

    def line(self, event):
        return target.SCHEMA_DIAGNOSTIC_PREFIX + json.dumps(event) + '\n'

    def test_ssl_subclasses_and_primary_cleanup_edges_survive(self):
        for cls in (ssl.SSLEOFError, ssl.SSLZeroReturnError, ssl.SSLWantReadError,
                    ssl.SSLWantWriteError, ssl.SSLSyscallError, ssl.SSLCertVerificationError):
            self.assertEqual(target.schema_exception_chain(cls('secret'))[0]['type'], cls.__name__)
        namespace = {'ssl': ssl}
        exec(compile('def _read():\n raise ssl.SSLEOFError("secret first read")\n'
                     'def close():\n raise ssl.SSLError("secret cleanup flush")\n'
                     'def connect():\n try:_read()\n except ssl.SSLError:close()\n',
                     '/secret/path/core.py', 'exec'), namespace)
        try:
            namespace['connect']()
        except ssl.SSLError as cleanup:
            wrapper = RuntimeError('secret wrapper')
            wrapper.orig = cleanup
            wrapper.__cause__ = cleanup
            graph = target.schema_exception_graph(wrapper)
        self.assertEqual([x['type'] for x in graph['nodes']], ['RuntimeError', 'SSLError', 'SSLEOFError'])
        self.assertTrue(graph['nodes'][0]['suppress_context'])
        self.assertFalse(graph['nodes'][1]['suppress_context'])
        self.assertIn(dict(source=0, target=1, relation='orig'), graph['edges'])
        self.assertIn(dict(source=0, target=1, relation='__cause__'), graph['edges'])
        self.assertIn(dict(source=1, target=2, relation='__context__'), graph['edges'])
        self.assertEqual(graph['nodes'][1]['frames'][-1]['function'], 'close')
        self.assertEqual(graph['nodes'][2]['frames'][-1]['function'], '_read')
        self.assertNotIn('secret', json.dumps(graph))

    def test_graph_cycles_and_truncation_are_bounded(self):
        errors = [RuntimeError(str(n)) for n in range(10)]
        for first, second in zip(errors, errors[1:]): first.__context__ = second
        errors[1].orig = errors[0]
        graph = target.schema_exception_graph(errors[0])
        self.assertEqual(len(graph['nodes']), 6)
        self.assertTrue(graph['truncated'])
        self.assertIn(dict(source=1, target=0, relation='orig'), graph['edges'])
        self.assertLessEqual(len(graph['edges']), 18)
        self.assertEqual(target.parse_schema_diagnostic(self.line(self.event(errors[0])))['exception_graph'], graph)

    def test_strict_redaction_never_includes_messages_args_sql_or_paths(self):
        error = ssl.SSLEOFError('password=secret', 'postgresql://secret', 'SELECT secret')
        error.errno = 'secret'
        error.winerror = 2**80
        error.orig = ValueError({'C': '08006', 'M': 'secret'})
        graph = target.schema_exception_graph(error)
        encoded = json.dumps(graph)
        for forbidden in ('secret', 'password', 'postgresql://', 'SELECT', 'args', 'message'):
            self.assertNotIn(forbidden, encoded)
        self.assertIsNone(graph['nodes'][0]['errno'])
        self.assertIsNone(graph['nodes'][0]['winerror'])
        self.assertEqual(graph['nodes'][1]['sqlstate'], '08006')
        class Hostile(Exception):
            @property
            def orig(self): raise RuntimeError('secret')
        self.assertEqual(target.schema_exception_chain(Hostile())[0]['type'], 'OtherException')

    def test_timeline_partial_timeout_bytes_and_final_event_are_retained(self):
        first = self.event(phase='imports')
        last = self.event(ssl.SSLEOFError('secret'))
        output = self.line(first) + 'secret raw log\n' + self.line(last) + target.SCHEMA_DIAGNOSTIC_PREFIX + '{'
        failure = subprocess.TimeoutExpired(['secret'], 180, output=output.encode(), stderr=b'secret')
        result = target.schema_failure_evidence(None, 180, failure, database='restore_owned_'+'a'*32)
        self.assertEqual(result['child_events'], [first, last])
        self.assertEqual(result['child'], last)
        self.assertEqual(result['status'], 'timed_out')
        self.assertFalse(result['retried'])
        self.assertFalse(result['raw_output_included'])
        self.assertNotIn('secret', json.dumps(result))
        self.assertIsNone(target.schema_failure_evidence(None, 1, database='secret')['synthetic_database'])

    def test_parser_rejects_malformed_oversize_nonfinite_and_unknown_fields(self):
        good = self.event(ssl.SSLEOFError('secret'))
        mutations = []
        for key, value in [('message', 'secret'), ('utc', '2026-99-99T00:01:02.123Z'),
                           ('elapsed_seconds', float('nan')), ('elapsed_seconds', 10**400),
                           ('version', True), ('phase', 'secret')]:
            bad = copy.deepcopy(good); bad[key] = value; mutations.append(self.line(bad))
        for edit in ('edge_index', 'edge_field', 'node_field', 'graph_extra', 'graph_mismatch', 'frame_path'):
            bad = copy.deepcopy(good)
            if edit == 'edge_index': bad['exception_graph']['edges'] = [dict(source=0, target=6, relation='orig')]
            if edit == 'edge_field': bad['exception_graph']['edges'] = [dict(source=0, target=0, relation='secret')]
            if edit == 'node_field': bad['exception_chain'][0]['args'] = 'secret'
            if edit == 'graph_extra': bad['exception_graph']['secret'] = 'secret'
            if edit == 'graph_mismatch': bad['exception_graph']['nodes'] = []
            if edit == 'frame_path': bad['exception_chain'][0]['frames'] = [dict(file='/secret/core.py', function='close', line=1)]
            mutations.append(self.line(bad))
        mutations += [target.SCHEMA_DIAGNOSTIC_PREFIX+'{"version":1,"version":1}',
                      target.SCHEMA_DIAGNOSTIC_PREFIX+'['*2000+']'*2000,
                      target.SCHEMA_DIAGNOSTIC_PREFIX+' '*17000, b'\xff', None]
        for raw in mutations:
            with self.subTest(raw=str(raw)[:60]): self.assertIsNone(target.parse_schema_diagnostic(raw))

    def test_timeline_bound_and_legacy_v1_are_supported(self):
        legacy = self.event(); del legacy['exception_graph']; del legacy['utc']
        self.assertEqual(target.parse_schema_diagnostic(self.line(legacy)), legacy)
        self.assertEqual(len(target.parse_schema_events(self.line(legacy)*30)), 16)

    def test_reporting_failures_do_not_mask_original_or_retry(self):
        value = target.schema_failure_evidence(SimpleNamespace(stdout=self.line(self.event(ssl.SSLEOFError('secret'))), returncode=1), 1)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'WORLEX_EVIDENCE_DIR': directory}):
            rendered = target.report_schema_failure(value, 'test_synthetic')
            saved = json.loads((pathlib.Path(directory)/'schema-init-failure-test_synthetic.json').read_text())
            self.assertEqual(saved['test_name'], 'test_synthetic')
            self.assertTrue(saved['evidence_saved'])
            self.assertNotIn('secret', rendered)
            with patch.object(target.os, 'link', side_effect=PermissionError('secret')):
                self.assertIn('Synthetic schema initialization failed', target.report_schema_failure(value, 'test_synthetic'))
            with patch.object(target.json, 'dumps', side_effect=ValueError('secret')):
                self.assertIn('no retry', target.report_schema_failure(value, '../secret'))
        self.assertFalse(saved['retried'])
        # Parent-side parser/graph/clock failures also preserve the original
        # failure classification without raising diagnostic exceptions.
        for collector in ('parse_schema_events', 'schema_exception_graph', 'schema_utc_now'):
            for error, status in ((subprocess.TimeoutExpired(['secret'], 180), 'timed_out'),
                                  (OSError('secret'), 'launch_failed'), (None, 'child_failed')):
                with self.subTest(collector=collector, status=status), patch.object(
                        target, collector, side_effect=ValueError('secret collector')):
                    fallback = target.schema_failure_evidence(None, 1, error)
                self.assertEqual(fallback, dict(synthetic_only=True, status=status,
                                 diagnostic_unavailable=True, raw_output_included=False, retried=False))
                self.assertNotIn('secret', json.dumps(fallback))

    def test_partial_write_never_publishes_saved_evidence(self):
        value = target.schema_failure_evidence(None, 1)
        def broken_dump(value, handle, **kwargs):
            handle.write('{"evidence_saved": true,')
            raise OSError('secret')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'WORLEX_EVIDENCE_DIR': directory}):
            with patch.object(target.json, 'dump', side_effect=broken_dump):
                rendered = target.report_schema_failure(value, 'test_partial')
            self.assertIn('"evidence_saved": false', rendered)
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [])

    def test_child_reporting_failure_preserves_exit_and_does_not_retry(self):
        # The import fails once. Printing failures cannot escape instead of the
        # original child failure; this exercises no app, subprocess or database.
        import builtins
        original = builtins.__import__
        attempts = []
        def importing(name, *args, **kwargs):
            if name == 'dkss_app':
                attempts.append(name)
                raise ImportError('secret')
            return original(name, *args, **kwargs)
        for fault in (patch('builtins.print', side_effect=OSError('secret')),
                      patch.object(target, 'schema_exception_graph', side_effect=ValueError('secret'))):
            attempts.clear()
            with patch('builtins.__import__', side_effect=importing), fault:
                with self.assertRaises(SystemExit) as stopped: target.run_ci_schema_initialization()
            self.assertEqual(stopped.exception.code, 1)
            self.assertEqual(attempts, ['dkss_app'])


if __name__ == '__main__': unittest.main()
