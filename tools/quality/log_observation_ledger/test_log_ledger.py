"""Synthetic tests only. No app imports, external calls, inherited environment."""
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import log_ledger as ledger

SERVICE = 'srv-synthetic12345678'
CANARY = 'DO_NOT_EXPORT_private@example.test_SECRET'
A = '2026-11-11T10:00:00Z'
B = '2026-11-11T11:00:00Z'
C = '2026-11-11T12:00:00Z'
SCRIPT = Path(__file__).with_name('log_ledger.py')


def row(identifier='opaque-provider-log-1', time=B, message=None):
    return {'id': identifier, 'timestamp': time,
            'labels': [{'name': 'resource', 'value': SERVICE}, {'name': 'type', 'value': 'app'},
                       {'name': 'level', 'value': 'error'}, {'name': 'instance', 'value': CANARY}],
            'message': message if message is not None else
                'INVOICE_REVIEW_FAILED action=correction error_type=database ' + CANARY}


def envelope(rows=(), start=A, end=C, more=False, next_start=None, next_end=None, direction='forward'):
    query = {'resource': [SERVICE], 'type': ['app'], 'direction': direction,
             'startTime': start, 'endTime': end, 'limit': 1000}
    page = {'hasMore': more, 'logs': list(rows)}
    if next_start is not None:
        page['nextStartTime'] = next_start
    if next_end is not None:
        page['nextEndTime'] = next_end
    return {'query': query, 'reply': {'ok': True, 'page': page}}


def transcript(*pages, direction='forward'):
    return {'resource': SERVICE, 'window': {'startTime': A, 'endTime': C},
            'direction': direction, 'pages': list(pages)}


def observe(*pages, state=None, direction='forward'):
    return ledger.observe(state, transcript(*pages, direction=direction))


class LedgerTests(unittest.TestCase):
    def test_terminal_window_is_observed_but_not_coverage(self):
        state, report = observe(envelope([row()]))
        self.assertEqual(report['scan']['chain_status'], 'linked_terminal')
        self.assertEqual(report['scan']['coverage_status'], 'incomplete_timestamp_only')
        self.assertEqual(report['scan']['last_response_status'], 'page')
        self.assertFalse(report['scan']['last_response_has_more'])
        self.assertIsNone(state['read_checkpoint'])

    def test_arbitrary_terminal_continuation_is_not_root(self):
        state, report = observe(envelope([row()], start=B))
        self.assertEqual(report['scan']['chain_status'], 'broken')
        self.assertEqual(report['scan']['counts']['broken_page_chain'], 1)
        self.assertEqual(len(state['records']), 0)

    def test_forward_chain_retains_observation(self):
        state, report = observe(envelope([row()], more=True, next_start=B, next_end=C),
                                envelope([row('opaque-provider-log-2')], start=B))
        self.assertEqual(report['scan']['pages_linked'], 2)
        self.assertEqual(report['scan']['chain_status'], 'linked_terminal')
        self.assertEqual(report['scan']['last_query_window']['startTime'], ledger.canonical_time(B))
        self.assertIsNone(state['read_checkpoint'])

    def test_backward_chain_retains_observation(self):
        state, report = observe(
            envelope([row()], direction='backward', more=True, next_start=A, next_end=B),
            envelope([row('opaque-provider-log-2')], end=B, direction='backward'), direction='backward')
        self.assertEqual(report['scan']['chain_status'], 'linked_terminal')
        self.assertEqual(len(state['records']), 2)

    def test_duplicate_across_pages_and_runs_is_visible(self):
        pages = [envelope([row()], more=True, next_start=B, next_end=C), envelope([row()], start=B)]
        state, report = observe(*pages)
        self.assertEqual(report['scan']['counts']['replayed_log_id'], 1)
        next_state, report = observe(*pages, state=state)
        self.assertEqual(report['scan']['counts']['replayed_log_id'], 2)
        self.assertEqual(len(next_state['records']), 1)
        self.assertEqual(len(ledger.pending_notifications(next_state, SERVICE)), 1)

    def test_distinct_ids_with_equal_nanosecond_timestamp_survive(self):
        state, report = observe(envelope([row('log-1', B), row('log-2', B)]))
        self.assertEqual(len(state['records']), 2)
        self.assertNotIn('conflicting_log_id', report['scan']['counts'])

    def test_conflicting_id_retains_both_safe_variants(self):
        state, _ = observe(envelope([row()]))
        other = row(message='EMAIL_DELIVERY_FAILED purpose=notification stage=send error_type=smtp')
        state, report = observe(envelope([other]), state=state)
        self.assertEqual(report['scan']['counts']['conflicting_log_id'], 1)
        self.assertEqual(len(next(iter(state['records'].values()))['variants']), 2)
        self.assertEqual(len(ledger.pending_notifications(state, SERVICE)[0]['variants']), 2)

    def test_unrelated_then_known_same_id_is_conflict_not_silent_drop(self):
        state, _ = observe(envelope([row(message='routine ' + CANARY)]))
        self.assertEqual(ledger.pending_notifications(state, SERVICE), [])
        state, report = observe(envelope([row()]), state=state)
        self.assertEqual(report['scan']['counts']['conflicting_log_id'], 1)
        self.assertEqual(len(ledger.pending_notifications(state, SERVICE)), 1)

    def test_unknown_known_event_enum_is_retained_unverified(self):
        state, report = observe(envelope([row(message='INVOICE_REVIEW_FAILED action=' + CANARY + ' error_type=database')]))
        variant = ledger.pending_notifications(state, SERVICE)[0]['variants'][0]
        self.assertEqual(variant['details']['action'], 'unverified')
        self.assertTrue(variant['requires_review'])
        self.assertEqual(report['scan']['counts']['classification_requires_review'], 1)
        self.assertNotIn(CANARY, json.dumps(state))

    def test_multiple_known_markers_retained_for_review(self):
        state, report = observe(envelope([row(message='EMAIL_DELIVERY_FAILED INVOICE_REVIEW_FAILED ' + CANARY)]))
        variant = ledger.pending_notifications(state, SERVICE)[0]['variants'][0]
        self.assertEqual(variant['kind'], 'unprojectable_known_failure')
        self.assertEqual(variant['known_events'], ['EMAIL_DELIVERY_FAILED', 'INVOICE_REVIEW_FAILED'])
        self.assertEqual(report['scan']['counts']['unprojectable_known_failure'], 1)

    def test_unknown_failure_marker_retained_without_unsafe_name(self):
        state, report = observe(envelope([row(message='PRIVATE_EMPLOYEE_123_FAILED ' + CANARY)]))
        self.assertEqual(ledger.pending_notifications(state, SERVICE)[0]['variants'][0]['kind'], 'unknown_failure_marker')
        self.assertEqual(report['scan']['counts']['unknown_failure_marker'], 1)
        self.assertNotIn('PRIVATE_EMPLOYEE', json.dumps(state))

    def test_mixed_known_and_unknown_marker_preserves_both_review_signals(self):
        mixed = row(message='INVOICE_REVIEW_FAILED action=correction error_type=database PRIVATE_EMPLOYEE_123_FAILED')
        state, report = observe(envelope([mixed]))
        variant = ledger.pending_notifications(state, SERVICE)[0]['variants'][0]
        self.assertEqual(variant['event'], 'INVOICE_REVIEW_FAILED')
        self.assertTrue(variant['unknown_marker_present'])
        self.assertTrue(variant['requires_review'])
        self.assertEqual(report['scan']['counts']['unknown_failure_marker'], 1)
        self.assertNotIn('PRIVATE_EMPLOYEE', json.dumps(state))

    def test_new_unknown_marker_in_existing_id_is_retained_as_conflict(self):
        state, _ = observe(envelope([row()]))
        mixed = row(message='INVOICE_REVIEW_FAILED action=correction error_type=database NEW_PROVIDER_FAILED')
        state, report = observe(envelope([mixed]), state=state)
        item = ledger.pending_notifications(state, SERVICE)[0]
        self.assertTrue(item['requires_review'])
        self.assertEqual(len(item['variants']), 2)
        self.assertEqual(report['scan']['counts']['conflicting_log_id'], 1)

    def test_multiple_known_plus_unknown_marker_all_survive_safely(self):
        mixed = row(message='INVOICE_REVIEW_FAILED EMAIL_DELIVERY_FAILED PRIVATE_EMPLOYEE_FAILED')
        state, report = observe(envelope([mixed]))
        variant = ledger.pending_notifications(state, SERVICE)[0]['variants'][0]
        self.assertEqual(variant['known_events'], ['EMAIL_DELIVERY_FAILED', 'INVOICE_REVIEW_FAILED'])
        self.assertTrue(variant['unknown_marker_present'])
        self.assertEqual(report['scan']['counts']['unknown_failure_marker'], 1)
        self.assertNotIn('PRIVATE_EMPLOYEE', json.dumps(state))

    def test_no_raw_message_id_service_instance_or_error_in_output(self):
        event = row()
        state, report = observe(envelope([event]))
        serialized = json.dumps([state, report, ledger.pending_notifications(state, SERVICE)])
        for secret in (CANARY, SERVICE, event['id'], event['message']):
            self.assertNotIn(secret, serialized)

    def test_api_failure_has_no_exception_text_and_preserves_prior_observations(self):
        first = envelope([row()], more=True, next_start=B, next_end=C)
        failed = envelope(start=B)
        failed['reply'] = {'ok': False, 'error': CANARY, 'rawResponse': CANARY}
        state, report = observe(first, failed)
        self.assertEqual(report['scan']['last_response_status'], 'api_failure')
        self.assertEqual(report['scan']['counts']['api_failure'], 1)
        self.assertEqual(len(state['records']), 1)
        self.assertNotIn(CANARY, json.dumps([state, report]))

    def test_empty_transcript_is_incomplete(self):
        state, report = observe()
        self.assertEqual(report['scan']['chain_status'], 'incomplete')
        self.assertEqual(report['scan']['last_response_status'], 'not_observed')
        self.assertIsNone(state['read_checkpoint'])

    def test_missing_terminal_returns_expected_continuation_without_progress_claim(self):
        state, report = observe(envelope([row()], more=True, next_start=B, next_end=C))
        self.assertEqual(report['scan']['chain_status'], 'incomplete')
        self.assertEqual(report['scan']['next_window']['startTime'], ledger.canonical_time(B))
        self.assertEqual(report['scan']['counts']['missing_terminal_page'], 1)

    def test_cumulative_retry_completes_links_without_new_notifications(self):
        first = envelope([row()], more=True, next_start=B, next_end=C)
        state, _ = observe(first)
        state, report = observe(first, envelope([row()], start=B), state=state)
        self.assertEqual(report['scan']['chain_status'], 'linked_terminal')
        self.assertEqual(len(ledger.pending_notifications(state, SERVICE)), 1)

    def test_provider_cursor_gap_cannot_be_claimed_as_complete(self):
        # Matching a provider-supplied timestamp cursor does not prove the
        # skipped timestamp interval or tied records were exhaustively returned.
        state, report = observe(envelope([row(time=A)], more=True, next_start=B, next_end=C), envelope(start=B))
        self.assertEqual(report['scan']['chain_status'], 'linked_terminal')
        self.assertEqual(report['scan']['counts']['timestamp_coverage_unverified'], 1)
        self.assertIsNone(state['read_checkpoint'])

    def test_mismatched_continuation_window_is_broken(self):
        _, report = observe(envelope([row()], more=True, next_start=B, next_end=C), envelope())
        self.assertEqual(report['scan']['counts']['broken_page_chain'], 1)

    def test_invalid_stalled_reversed_and_missing_cursors_are_visible(self):
        for next_start, next_end, code in [(A, C, 'cursor_stalled'), (A, B, 'invalid_cursor'),
                (C, B, 'invalid_cursor'), (B, None, 'invalid_cursor'), (None, None, 'invalid_cursor')]:
            with self.subTest(next_start=next_start, next_end=next_end):
                _, report = observe(envelope([row()], more=True, next_start=next_start, next_end=next_end))
                self.assertEqual(report['scan']['counts'][code], 1)
                self.assertEqual(report['scan']['chain_status'], 'broken')

    def test_terminal_followed_by_page_is_not_valid_chain(self):
        state, report = observe(envelope([row()]), envelope([row('log-2')]))
        self.assertEqual(report['scan']['counts']['pages_after_terminal'], 1)
        self.assertEqual(report['scan']['chain_status'], 'broken')
        self.assertEqual(len(state['records']), 1)

    def test_filtered_wrong_scope_or_direction_queries_rejected(self):
        for key, value in [('text', ['INVOICE_REVIEW_FAILED']), ('level', ['error']),
                ('resource', ['srv-different1234']), ('type', ['request']),
                ('direction', 'backward'), ('limit', True)]:
            page = envelope([row()]); page['query'][key] = value
            _, report = observe(page)
            self.assertEqual(report['scan']['counts']['invalid_query'], 1)

    def test_invalid_rows_count_including_unrelated_rows(self):
        rows = [None, row(), row(), row(), row()]
        rows[1]['timestamp'] = 'invalid'
        rows[2]['id'] = CANARY
        rows[3]['labels'][1]['value'] = 'build'
        rows[4]['message'] = CANARY
        rows[4]['timestamp'] = 'invalid'
        state, report = observe(envelope(rows))
        self.assertEqual(report['scan']['counts']['rejected_record'], 5)
        self.assertFalse(state['records'])

    def test_outside_query_record_is_not_admitted(self):
        state, report = observe(envelope([row(time='2026-11-11T12:00:00.000000001Z')]))
        self.assertFalse(state['records'])
        self.assertEqual(report['scan']['counts']['record_outside_query'], 1)

    def test_record_order_problem_is_reported(self):
        _, report = observe(envelope([row(time=B), row('log-2', A)]))
        self.assertEqual(report['scan']['counts']['nonmonotonic_records'], 1)

    def test_invalid_response_bool_and_limit_are_visible(self):
        for change in ('bool', 'too_many', 'shape'):
            page = envelope([row()])
            if change == 'bool':
                page['reply']['page']['hasMore'] = 'false'
            elif change == 'too_many':
                page['query']['limit'] = 1
                page['reply']['page']['logs'].append(row('log-2'))
            else:
                page['reply'] = {'ok': 1}
            _, report = observe(page)
            self.assertEqual(report['scan']['counts']['invalid_page'], 1)

    def test_nanosecond_and_offset_normalization(self):
        self.assertEqual(ledger.canonical_time('2026-11-11T19:00:00.123456789+09:00'),
                         '2026-11-11T10:00:00.123456789Z')
        self.assertLess(ledger.canonical_time('2026-11-11T10:00:00.123456788Z'),
                        ledger.canonical_time('2026-11-11T10:00:00.123456789Z'))
        self.assertEqual(ledger.canonical_time('0001-01-01T00:00:00Z'), '0001-01-01T00:00:00.000000000Z')

    def test_invalid_times_rejected(self):
        for value in [None, CANARY, '2026-02-30T00:00:00Z', '2026-11-11T00:00:00',
                '2026-11-11T00:00:00-00:00', '2026-11-11T00:00:00+24:00',
                '2026-11-11T00:00:00.1234567890Z']:
            with self.assertRaises(ValueError):
                ledger.canonical_time(value)

    def test_equivalent_timestamp_not_a_conflict(self):
        state, _ = observe(envelope([row(time='2026-11-11T20:00:00+09:00')]))
        state, report = observe(envelope([row(time=B)]), state=state)
        self.assertEqual(report['scan']['counts']['replayed_log_id'], 1)

    def test_uncertain_notification_does_not_become_sent_or_acknowledged(self):
        state, _ = observe(envelope([row()]))
        next(iter(state['records'].values()))['notification_status'] = 'uncertain'
        state, report = observe(envelope([row()]), state=state)
        item = ledger.pending_notifications(state, SERVICE)[0]
        self.assertEqual(item['notification_status'], 'uncertain')
        self.assertEqual(item['acknowledgment_status'], 'not_received')
        self.assertIsNone(state['read_checkpoint'])
        self.assertEqual(report['delivery_status'], 'not_attempted_by_ledger')

    def test_uncertain_notification_preserved_on_new_conflicting_variant(self):
        state, _ = observe(envelope([row()]))
        next(iter(state['records'].values()))['notification_status'] = 'uncertain'
        state, report = observe(envelope([row(message='WEB_PUSH_SEND_FAILED error_type=provider')]), state=state)
        item = ledger.pending_notifications(state, SERVICE)[0]
        self.assertEqual(item['notification_status'], 'uncertain')
        self.assertTrue(item['requires_review'])
        self.assertEqual(report['total_conflicting_ids'], 1)

    def test_no_input_mutation(self):
        original = transcript(envelope([row()]))
        before = copy.deepcopy(original)
        state, _ = ledger.observe(None, original)
        state_before = copy.deepcopy(state)
        ledger.observe(state, original)
        self.assertEqual(before, original)
        self.assertEqual(state_before, state)

    def test_fake_completeness_assertion_not_accepted(self):
        data = transcript(envelope([row()])); data['complete'] = True
        with self.assertRaises(ValueError):
            ledger.observe(None, data)

    def test_raw_state_extra_rejected_before_projection(self):
        state, _ = observe(envelope([row()]))
        next(iter(state['records'].values()))['raw'] = CANARY
        with self.assertRaises(ValueError):
            ledger.pending_notifications(state, SERVICE)

    def test_bound_resource_and_checkpoint_cannot_be_forged(self):
        for key, value in [('resource_hash', '0' * 64), ('read_checkpoint', B),
                           ('delivery_status', 'sent'), ('monitoring_status', 'scheduled')]:
            state, _ = observe(envelope([row()])); state[key] = value
            with self.assertRaises(ValueError):
                observe(envelope(), state=state)

    def test_variant_unknown_values_rejected_in_state(self):
        state, _ = observe(envelope([row()]))
        next(iter(state['records'].values()))['variants'][0]['details']['action'] = CANARY
        with self.assertRaises(ValueError):
            observe(envelope(), state=state)

    def test_malformed_nested_state_never_reaches_pending_projection(self):
        for malformed in [[], None, CANARY, {'kind': 'event', 'observed_at': []}]:
            state, _ = observe(envelope([row()]))
            next(iter(state['records'].values()))['variants'] = [malformed]
            with self.assertRaises((ValueError, TypeError)):
                ledger.pending_notifications(state, SERVICE)

    def test_capacity_fails_without_mutating_or_silent_eviction(self):
        state, _ = observe(envelope([row()]))
        before = copy.deepcopy(state)
        with patch.object(ledger, 'MAX_IDS', 1):
            with self.assertRaisesRegex(ValueError, '^STATE_CAPACITY$'):
                observe(envelope([row('log-2')]), state=state)
        self.assertEqual(state, before)

    def test_variant_capacity_fails_without_losing_classification(self):
        state, _ = observe(envelope([row()]))
        before = copy.deepcopy(state)
        with patch.object(ledger, 'MAX_VARIANTS', 1):
            with self.assertRaisesRegex(ValueError, '^STATE_CAPACITY$'):
                observe(envelope([row(message='WEB_PUSH_SEND_FAILED error_type=provider')]), state=state)
        self.assertEqual(state, before)

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        for value in ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}']:
            with self.assertRaises(ValueError):
                ledger.load_json(value)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='synthetic-ledger-')
        self.directory = Path(self.temporary.name)
        self.state = self.directory / 'state.json'

    def tearDown(self):
        self.temporary.cleanup()

    def cli(self, payload, path=None):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), '--state', str(path or self.state)],
                              input=payload if isinstance(payload, str) else json.dumps(payload),
                              text=True, capture_output=True, timeout=10,
                              env={'PATH': '/usr/bin:/bin', 'HOME': str(self.directory)})

    def test_cli_persists_private_sanitized_state_and_replays(self):
        data = transcript(envelope([row()]))
        first = self.cli(data)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)
        second = self.cli(data)
        self.assertEqual(second.returncode, 0, second.stderr)
        report = json.loads(second.stdout)
        self.assertEqual(report['scan']['counts']['replayed_log_id'], 1)
        for secret in [CANARY, SERVICE, row()['id']]:
            self.assertNotIn(secret, self.state.read_text() + first.stdout + second.stdout + second.stderr)
        self.assertFalse(self.state.with_name('state.json.lock').exists())

    def test_busy_lock_prevents_write(self):
        lock = self.state.with_name('state.json.lock'); lock.touch(mode=0o600)
        result = self.cli(transcript(envelope([row()])))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.state.exists())
        self.assertTrue(lock.exists())

    def test_bad_state_is_not_overwritten_or_printed(self):
        self.state.write_text('{"private":"' + CANARY + '"}')
        self.state.chmod(0o600)
        before = self.state.read_bytes()
        result = self.cli(transcript(envelope([row()])))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertNotIn(CANARY, result.stdout + result.stderr)

    def test_symlink_state_is_not_followed(self):
        target = self.directory / 'private-target'; target.write_text(CANARY); target.chmod(0o600)
        self.state.symlink_to(target)
        result = self.cli(transcript(envelope([row()])))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(target.read_text(), CANARY)
        self.assertNotIn(CANARY, result.stdout + result.stderr)

    def test_symlink_parent_is_not_followed(self):
        private = self.directory / 'private'; private.mkdir(mode=0o700)
        link = self.directory / 'link'; link.symlink_to(private, target_is_directory=True)
        result = self.cli(transcript(envelope([row()])), link / 'state.json')
        self.assertEqual(result.returncode, 2)
        self.assertFalse((private / 'state.json').exists())

    def test_nonprivate_parent_and_state_are_rejected(self):
        self.directory.chmod(0o755)
        self.assertEqual(self.cli(transcript(envelope())).returncode, 2)
        self.directory.chmod(0o700)
        self.state.write_text('{}'); self.state.chmod(0o644)
        self.assertEqual(self.cli(transcript(envelope())).returncode, 2)

    def test_cli_large_input_fails_without_persisting(self):
        result = self.cli('x' * (ledger.MAX_INPUT + 1))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.state.exists())

    def test_invalid_json_fails_sanitized(self):
        result = self.cli(CANARY)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(CANARY, result.stdout + result.stderr)
        self.assertFalse(self.state.exists())

    def test_replace_failure_leaves_old_state_and_no_temp_or_lock(self):
        data = transcript(envelope([row()]))
        ledger.save_transaction(self.state, data)
        before = self.state.read_bytes()
        with patch.object(ledger.os, 'replace', side_effect=OSError(CANARY)):
            with self.assertRaises(OSError):
                ledger.save_transaction(self.state, data)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ['state.json'])

    def test_hardlinked_state_rejected(self):
        ledger.save_transaction(self.state, transcript(envelope()))
        other = self.directory / 'hardlink'; os.link(self.state, other)
        before = self.state.read_bytes()
        self.assertEqual(self.cli(transcript(envelope([row()]))).returncode, 2)
        self.assertEqual(self.state.read_bytes(), before)

    def test_fifo_state_rejected_without_blocking_and_lock_is_cleaned(self):
        os.mkfifo(self.state, mode=0o600)
        result = self.cli(transcript(envelope()))
        self.assertEqual(result.returncode, 2)
        self.assertTrue(stat.S_ISFIFO(self.state.lstat().st_mode))
        self.assertFalse(self.state.with_name('state.json.lock').exists())

    def test_directory_fsync_failure_has_uncertain_commit_and_cleans_lock(self):
        data = transcript(envelope([row()]))
        ledger.save_transaction(self.state, data)
        real_fsync = ledger.os.fsync
        calls = []
        def fsync(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError(CANARY)
            return real_fsync(fd)
        with patch.object(ledger.os, 'fsync', side_effect=fsync):
            with self.assertRaises(OSError):
                ledger.save_transaction(self.state, data)
        self.assertEqual(json.loads(self.state.read_text())['runs'], 2)
        self.assertFalse(self.state.with_name('state.json.lock').exists())
        report = ledger.save_transaction(self.state, data)
        self.assertEqual(report['scan']['counts']['replayed_log_id'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
