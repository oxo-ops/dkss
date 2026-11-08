"""Offline-only owned server diagnostics: no database or subprocess calls."""
import contextlib
import io
import json
import os
import stat
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import ci_server_diagnostics as diagnostics


class OwnedServerDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / 'owned'
        self.work.mkdir()
        (self.work / 'OWNER').write_text(diagnostics.OWNER)
        self.log = self.work / 'server.log'
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()

    def record(self, message='database system is ready to accept connections', database='dkss_restore_ci'):
        return f'WORLEX_CI|2026-11-09 01:02:03.123 UTC|123abc.123|4321|{database}|00000|LOG:  {message}\n'

    def collect(self):
        return diagnostics.collect_owned_events(self.work, self.root)

    def lifecycle(self, **overrides):
        args = dict(start=Mock(), cleanup=Mock(), secrets_cleanup=Mock())
        args.update(overrides)
        return diagnostics.owned_server_lifecycle(self.work, self.root, self.evidence, **args)

    def metadata(self):
        return json.loads((self.evidence / 'owned-server-lifecycle.json').read_text())

    def test_allowlisted_events_have_synthetic_correlation(self):
        self.log.write_text(self.record())
        event = self.collect()['events'][0]
        self.assertEqual(event, dict(timestamp='2026-11-09 01:02:03.123 UTC', session='123abc.123', pid=4321, severity='LOG', sqlstate='00000', database='dkss_restore_ci', category='ready'))

    def test_secrets_sql_urls_cancel_keys_and_data_never_copied(self):
        secret = 'password=secret postgresql://u:p@host/db cancel_key=123 SELECT private_data'
        self.log.write_text(self.record('connection received: ' + secret) + self.record(secret) + self.record('disconnection: ' + secret, 'production_private'))
        rendered = json.dumps(self.collect())
        for value in ('password', 'secret', 'postgresql://', 'cancel_key', 'SELECT', 'private_data', 'production_private'):
            self.assertNotIn(value, rendered)
        self.assertEqual(len(self.collect()['events']), 2)

    def test_missing_log_explicit_status(self):
        self.assertEqual(self.collect()['status'], 'missing')

    def test_wrong_marker_and_outside_root_rejected(self):
        (self.work / 'OWNER').write_text('NOT_OWNED')
        with self.assertRaises(ValueError):
            self.collect()
        with self.assertRaises(ValueError):
            diagnostics.collect_owned_events(self.work, self.evidence)

    def test_symlink_log_rejected(self):
        target = self.root / 'unowned.log'
        target.write_text(self.record())
        try:
            self.log.symlink_to(target)
        except OSError:
            # Windows runners may deny creating symlinks. Model the metadata
            # directly rather than skip or require privilege changes.
            self.log.write_text(self.record())
            original = Path.lstat
            with patch.object(Path, 'lstat', lambda path: SimpleNamespace(st_mode=stat.S_IFLNK) if path == self.log else original(path)):
                with self.assertRaises(ValueError):
                    self.collect()
        else:
            with self.assertRaises(ValueError):
                self.collect()

    def test_oversize_input_and_output_are_bounded(self):
        self.log.write_text('x' * (diagnostics.MAX_BYTES + 1) + '\n' + self.record() * 4000)
        result = self.collect()
        self.assertTrue(result['truncated'])
        self.assertGreater(result['bytes_omitted'], 0)
        self.assertLessEqual(len(result['events']), diagnostics.MAX_EVENTS)
        self.assertLess(len(json.dumps(result)), diagnostics.MAX_OUTPUT)

    def test_partial_write_discarded(self):
        self.log.write_text(self.record() + self.record().rstrip('\n'))
        result = self.collect()
        self.assertTrue(result['partial_tail_discarded'])
        self.assertEqual(len(result['events']), 1)

    def test_invalid_timestamp_and_session_rejected(self):
        self.log.write_text(self.record().replace('2026-11-09', '2026-99-99') + self.record().replace('123abc.123', 'sensitive_session'))
        self.assertEqual(self.collect()['events'], [])

    def test_collector_failure_never_masks_primary(self):
        primary = RuntimeError('SECRET PRIMARY')
        collector = Mock(side_effect=ValueError('SECRET COLLECTOR'))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(RuntimeError) as caught:
            with self.lifecycle(collector=collector):
                raise primary
        self.assertIs(caught.exception, primary)
        self.assertEqual(collector.call_count, 2)
        self.assertTrue(self.metadata()['collection_incomplete'])
        self.assertNotIn('SECRET', ''.join(p.read_text() for p in self.evidence.iterdir()))

    def test_primary_cleanup_and_secrets_failure_recorded_separately(self):
        self.log.write_text(self.record())
        primary = ValueError('original')
        with self.assertRaises(ValueError) as caught:
            with self.lifecycle(cleanup=Mock(side_effect=RuntimeError('cleanup')), secrets_cleanup=Mock(side_effect=OSError('secrets'))):
                raise primary
        self.assertIs(caught.exception, primary)
        meta = self.metadata()
        self.assertEqual(meta['primary_exception_class'], 'ValueError')
        self.assertEqual(meta['cleanup_exception_class'], 'RuntimeError')
        self.assertEqual(meta['secrets_cleanup_exception_class'], 'OSError')

    def test_start_failure_still_collects_and_cleans_once(self):
        self.log.write_text(self.record('could not bind IPv4 address private-data'))
        failure = RuntimeError('start failure')
        start, cleanup, secrets = Mock(side_effect=failure), Mock(), Mock()
        with self.assertRaises(RuntimeError) as caught:
            with self.lifecycle(start=start, cleanup=cleanup, secrets_cleanup=secrets):
                self.fail('body must not run')
        self.assertIs(caught.exception, failure)
        for callback in (start, cleanup, secrets):
            callback.assert_called_once_with()
        for stage in ('before', 'after'):
            self.assertTrue((self.evidence / f'owned-server-{stage}-teardown.json').exists())

    def test_cleanup_only_failure_propagates(self):
        self.log.write_text(self.record())
        failure = RuntimeError('cleanup')
        with self.assertRaises(RuntimeError) as caught:
            with self.lifecycle(cleanup=Mock(side_effect=failure)):
                pass
        self.assertIs(caught.exception, failure)
        self.assertIsNone(self.metadata()['primary_exception_class'])

    def test_partial_evidence_write_falls_back_without_masking_primary(self):
        self.log.write_text(self.record())
        def writer(evidence, name, value):
            (evidence / (name + '.tmp')).write_text('{')
            raise OSError('SECRET WRITE FAILURE')
        output = io.StringIO()
        primary = RuntimeError('primary')
        with contextlib.redirect_stderr(output), self.assertRaises(RuntimeError) as caught:
            with self.lifecycle(writer=writer):
                raise primary
        self.assertIs(caught.exception, primary)
        self.assertIn('OWNED_SERVER_DIAGNOSTICS_INCOMPLETE', output.getvalue())
        self.assertNotIn('SECRET', output.getvalue())

    def test_diagnostics_failure_does_not_change_acceptance_gates(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            with self.lifecycle():
                pass
        self.assertTrue(self.metadata()['collection_incomplete'])
        self.assertIn('OWNED_SERVER_DIAGNOSTICS_INCOMPLETE', output.getvalue())

    def test_unrecognized_records_have_counts_not_inferred_causes(self):
        self.log.write_text(self.record('unrecognized private failure') + 'private unparsed line\n')
        result = self.collect()
        self.assertEqual(result['unknown_event_count'], 1)
        self.assertEqual(result['unparsed_line_count'], 1)
        self.assertEqual(result['events'], [])

    def test_rare_failure_survives_later_connection_chatter(self):
        database = 'restore_owned_' + 'a' * 32
        failure = self.record('unrecognized private error', database).replace('|LOG:', '|FATAL:')
        self.log.write_text(failure + self.record('connection received: private') * 1000)
        result = self.collect()
        self.assertEqual(result['events'][0]['category'], 'unknown_error')
        self.assertEqual(result['events'][0]['database'], database)
        self.assertEqual(result['unknown_event_count'], 1)
        self.assertEqual(result['events_omitted'], 1001 - diagnostics.MAX_EVENTS)

    @contextlib.contextmanager
    def link_or_model(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError:
            # Windows CI can deny symlink creation. Model only lstat metadata,
            # exercising the same rejection rather than skipping the test.
            original = Path.lstat
            original_exists = os.path.lexists
            with patch.object(Path, 'lstat', lambda path: SimpleNamespace(st_mode=stat.S_IFLNK) if path == link else original(path)), patch.object(os.path, 'lexists', lambda path: True if Path(path) == link else original_exists(path)):
                yield
        else:
            try:
                yield
            finally:
                link.unlink()

    def test_predictable_temp_symlink_is_never_opened(self):
        unrelated = self.root / 'unrelated'
        unrelated.write_text('UNCHANGED')
        name = 'owned-server-lifecycle.json'
        with self.link_or_model(self.evidence / (name + '.tmp'), unrelated):
            diagnostics._persist(self.evidence, name, {'complete': True})
            self.assertEqual(unrelated.read_text(), 'UNCHANGED')
            self.assertFalse((self.evidence / name).is_symlink())
            self.assertEqual(json.loads((self.evidence / name).read_text()), {'complete': True})

    def test_evidence_target_symlink_is_rejected(self):
        unrelated = self.root / 'unrelated'
        unrelated.write_text('UNCHANGED')
        name = 'owned-server-lifecycle.json'
        with self.link_or_model(self.evidence / name, unrelated):
            # lexists is based on lstat, including the Windows model.
            with self.assertRaises(ValueError):
                diagnostics._persist(self.evidence, name, {'complete': True})
            self.assertEqual(unrelated.read_text(), 'UNCHANGED')

    def test_evidence_ancestor_symlink_is_rejected(self):
        alias = self.root / 'alias'
        with self.link_or_model(alias, self.evidence, directory=True):
            with self.assertRaises(ValueError):
                diagnostics._persist(alias, 'owned-server-lifecycle.json', {})
        self.assertEqual(list(self.evidence.iterdir()), [])

    def test_owned_ancestor_symlink_is_rejected(self):
        alias = self.root / 'alias'
        with self.link_or_model(alias, self.root, directory=True):
            with self.assertRaises(ValueError):
                diagnostics.collect_owned_events(alias / 'owned', self.root)

    def test_owned_marker_and_log_hardlinks_are_rejected(self):
        self.log.write_text(self.record())
        for path in (self.log, self.work / 'OWNER'):
            with self.subTest(path=path.name):
                link = self.root / 'hardlink'
                os.link(path, link)
                try:
                    with self.assertRaises(ValueError):
                        self.collect()
                finally:
                    link.unlink()

    def test_windows_reparse_ancestor_metadata_is_rejected(self):
        original = Path.lstat
        def reparse(path):
            if path == self.work:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return original(path)
        with patch.object(Path, 'lstat', reparse):
            with self.assertRaises(ValueError):
                self.collect()

    def test_truncated_partial_and_omitted_snapshots_mark_incomplete(self):
        for field in ('truncated', 'partial_tail_discarded', 'bytes_omitted', 'lines_omitted', 'events_omitted'):
            with self.subTest(field=field), contextlib.redirect_stderr(io.StringIO()):
                collector = Mock(return_value={'status': 'collected', 'events': [], field: 1})
                with self.lifecycle(collector=collector):
                    pass
                self.assertTrue(self.metadata()['collection_incomplete'])

    def test_atomic_publish_failure_keeps_complete_old_file_and_removes_temp(self):
        name = 'owned-server-lifecycle.json'
        diagnostics._persist(self.evidence, name, {'old': True})
        with patch.object(Path, 'replace', side_effect=OSError('private failure')):
            with self.assertRaises(OSError):
                diagnostics._persist(self.evidence, name, {'new': True})
        self.assertEqual(json.loads((self.evidence / name).read_text()), {'old': True})
        self.assertEqual([path.name for path in self.evidence.iterdir()], [name])

    def test_unknown_exception_class_never_leaks_name(self):
        private_exception = type('CustomerPrivateValue', (Exception,), {})
        self.assertEqual(diagnostics.exception_label(private_exception('secret')), 'OtherError')

    def test_callbacks_run_once_without_retries_or_extra_processes(self):
        self.log.write_text(self.record())
        order = []
        with self.lifecycle(start=lambda: order.append('start'), cleanup=lambda: order.append('cleanup'), secrets_cleanup=lambda: order.append('secrets')):
            order.append('body')
        self.assertEqual(order, ['start', 'body', 'cleanup', 'secrets'])
        self.assertFalse(self.metadata()['collection_incomplete'])


if __name__ == '__main__':
    unittest.main()
