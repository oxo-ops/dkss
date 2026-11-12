"""Synthetic-only new suite. No existing suite rerun, network or live evidence."""
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

import log_ledger as ledger
import offline_monitor as monitor

NOW = '2026-11-11T12:00:00Z'
LATER = '2026-11-11T13:00:00Z'
AFTER = '2026-11-11T13:01:00Z'
CANARY = 'DO_NOT_EXPORT_private@example.test_SECRET'
RAW_ID = 'synthetic-provider-id-1'
MESSAGES = [
    'UPLOAD_DELETE_FAILED backend=local error_type=OSError',
    'EMAIL_DELIVERY_FAILED purpose=notification stage=send error_type=smtp',
    'WEB_PUSH_SEND_FAILED error_type=provider',
    'DOCUMENT_IMPORT_FAILED mode=form stage=persist error_type=database',
    'INVOICE_REVIEW_FAILED action=correction error_type=database',
]


def policy(**kwargs):
    return monitor.Policy(3600, 3600, **kwargs)


def row(message=MESSAGES[0], identifier=RAW_ID, observed='2026-11-11T11:30:00Z'):
    return {'id': identifier, 'timestamp': observed,
            'message': message + ' ' + CANARY,
            'labels': [{'name': 'resource', 'value': monitor.RESOURCE},
                       {'name': 'type', 'value': 'app'},
                       {'name': 'level', 'value': 'warning'},
                       {'name': 'instance', 'value': CANARY}]}


def reply(rows=None, more=False, start=None, end=None):
    page = {'hasMore': more, 'logs': [row()] if rows is None else rows}
    if more:
        page.update(nextStartTime=start, nextEndTime=end)
    return {'ok': True, 'page': page}


def collect(store=None, rows=None, now=NOW):
    store = monitor.SyntheticCASStore() if store is None else store
    monitor.collect_once(store, monitor.SyntheticRecorder([reply(rows)]), now, policy())
    return store


def only(store):
    bundle = store.read()
    identifier = next(iter(bundle['outbox']))
    return identifier, bundle['outbox'][identifier]


def send(store, transport=None, now=NOW):
    transport = monitor.SyntheticTransport() if transport is None else transport
    identifier, _ = only(store)
    outcome = monitor.send_one(store, transport, identifier, now, policy(send_enabled=True))
    return transport, identifier, outcome


class PolicyAndCollectionTests(unittest.TestCase):
    def test_default_off_and_explicit_due_gate(self):
        store = monitor.SyntheticCASStore()
        self.assertFalse(monitor.due(store.read(), NOW, policy()))
        recorder = monitor.SyntheticRecorder([reply()])
        before = store.read()
        self.assertEqual(monitor.collect_once(store, recorder, NOW, policy(), scheduled=True), before)
        self.assertEqual(recorder.calls, [])
        collect(store)
        transport, identifier = monitor.SyntheticTransport(), only(store)[0]
        self.assertEqual(monitor.send_one(store, transport, identifier, NOW, policy()), 'disabled')
        self.assertEqual(transport.calls, [])

    def test_due_boundary_and_manual_does_not_activate_scheduler(self):
        store = collect()
        enabled = policy(schedule_enabled=True)
        self.assertFalse(monitor.due(store.read(), '2026-11-11T12:59:59.999999999Z', enabled))
        self.assertTrue(monitor.due(store.read(), LATER, enabled))
        self.assertEqual(store.read()['ledger']['monitoring_status'], 'not_scheduled')

    def test_invalid_policy_and_clock_rollback(self):
        for arguments in [(True, 1), (1, False), (0, 1), (1, 0), (86401, 1), (1, 604801)]:
            with self.assertRaises(ValueError):
                monitor.Policy(*arguments)
        with self.assertRaises(ValueError):
            monitor.Policy(1, 1, send_enabled=1)
        with self.assertRaises(TypeError):
            monitor.Policy(1, 1, recipient=CANARY)
        with self.assertRaises(ValueError):
            monitor.due(collect().read(), '2026-11-11T11:59:59Z', policy())

    def test_explicit_overlap_and_nanoseconds(self):
        store, recorder = monitor.SyntheticCASStore(), monitor.SyntheticRecorder([reply([])])
        monitor.collect_once(store, recorder, '2026-11-11T12:00:00.123456789Z', monitor.Policy(60, 120))
        self.assertEqual(recorder.calls, [{
            'resource': [monitor.RESOURCE], 'type': ['app'], 'direction': 'forward',
            'startTime': '2026-11-11T11:57:00.123456789Z',
            'endTime': '2026-11-11T12:00:00.123456789Z', 'limit': 1000}])
        self.assertIsNone(store.read()['ledger']['read_checkpoint'])
        self.assertEqual(store.read()['ledger']['last_scan']['coverage_status'], 'incomplete_timestamp_only')

    def test_actual_continuation_query_and_terminal_not_coverage(self):
        recorder = monitor.SyntheticRecorder([
            reply([row(observed='2026-11-11T10:30:00Z')], True,
                  '2026-11-11T11:00:00Z', NOW),
            reply([row(identifier='synthetic-second-id')])])
        store = monitor.SyntheticCASStore()
        monitor.collect_once(store, recorder, NOW, policy())
        self.assertEqual(len(recorder.calls), 2)
        self.assertEqual(recorder.calls[1]['startTime'], '2026-11-11T11:00:00.000000000Z')
        self.assertEqual(store.read()['ledger']['last_scan']['chain_status'], 'linked_terminal')
        self.assertIsNone(store.read()['ledger']['read_checkpoint'])

    def test_api_failure_and_page_cap_never_all_clear(self):
        for recorder in [
                monitor.SyntheticRecorder([{'ok': False}]),
                monitor.SyntheticRecorder([reply([], True, '2026-11-11T11:00:00Z', NOW)])]:
            store = monitor.SyntheticCASStore()
            with patch.object(ledger, 'MAX_PAGES', 1):
                monitor.collect_once(store, recorder, NOW, policy())
            self.assertNotEqual(store.read()['ledger']['last_scan']['chain_status'], 'linked_terminal')
            self.assertIsNone(store.read()['ledger']['read_checkpoint'])

    def test_recorder_unknown_fields_and_non_fake_ports_rejected(self):
        bad = reply()
        bad['recipient'] = CANARY
        store = monitor.SyntheticCASStore()
        with self.assertRaises(ValueError):
            monitor.collect_once(store, monitor.SyntheticRecorder([bad]), NOW, policy())
        self.assertEqual(store.read(), monitor.new_bundle())
        with self.assertRaises(ValueError):
            monitor.collect_once(store, lambda query: reply(), NOW, policy())

    def test_five_markers_complete_synthetic_chain_separate_proofs(self):
        for message in MESSAGES:
            with self.subTest(marker=message.split()[0]):
                store = collect(rows=[row(message)])
                transport, identifier, outcome = send(store)
                self.assertEqual(outcome, 'accepted')
                _, item = only(store)
                self.assertIsNone(item['arrival_proof'])
                self.assertIsNone(item['human_ack_proof'])
                arrival = transport.arrival(identifier, LATER)
                monitor.record_evidence(store, transport, identifier, arrival, 'arrival')
                self.assertIsNone(only(store)[1]['human_ack_proof'])
                ack = transport.human_ack(identifier, AFTER)
                monitor.record_evidence(store, transport, identifier, ack, 'human_ack')
                item = only(store)[1]
                self.assertEqual(item['state'], 'accepted')
                self.assertEqual(item['payload']['variants'][0]['event'], message.split()[0])
                self.assertEqual(item['arrival_proof']['kind'], 'arrival')
                self.assertEqual(item['human_ack_proof']['actor_hash'], monitor.OWNER_HASH)
                self.assertEqual(item['human_ack_proof']['provenance'], 'synthetic_fake_transport')
                self.assertEqual(store.read()['mode'], 'synthetic_trial')
                self.assertEqual(len(transport.calls), 1)

    def test_no_raw_identifiers_pii_or_secret_in_bundle(self):
        store = collect()
        send(store)
        raw = monitor.encoded(store.read())
        for forbidden in [CANARY, RAW_ID, monitor.RESOURCE, monitor.DESTINATION, monitor.OWNER + '"']:
            self.assertNotIn(forbidden, raw)
        monitor.validate_bundle(ledger.load_json(raw))

    def test_unknown_bundle_payload_and_self_declared_state_rejected(self):
        bundle = collect().read()
        for index in range(3):
            mutated = copy.deepcopy(bundle)
            if index == 0:
                mutated['raw_log'] = CANARY
            elif index == 1:
                entry = next(iter(mutated['outbox'].values()))
                entry['payload']['recipient'] = CANARY
                entry['payload_digest'] = monitor.digest(entry['payload'])
            else:
                mutated['mode'] = 'live'
            with self.assertRaises(ValueError):
                monitor.validate_bundle(mutated)

    def test_ledger_digest_and_receipt_binding_rejected(self):
        bundle = collect().read()
        bad = copy.deepcopy(bundle)
        bad['ledger_digest'] = '0' * 64
        with self.assertRaises(ValueError):
            monitor.validate_bundle(bad)
        bad = copy.deepcopy(bundle)
        entry = next(iter(bad['outbox'].values()))
        entry['receipt_id'] = '0' * 64
        with self.assertRaises(ValueError):
            monitor.validate_bundle(bad)

    def test_duplicate_json_and_oversized_input_rejected(self):
        with self.assertRaises(ValueError):
            ledger.load_json('{"mode":"synthetic_trial","mode":"live"}')
        with patch.object(ledger, 'MAX_INPUT', 1):
            with self.assertRaises(ValueError):
                monitor.SyntheticRecorder([reply()])


class OutboxSafetyTests(unittest.TestCase):
    def test_replay_overlap_and_late_classification_do_not_rearm(self):
        store = collect()
        transport, identifier, _ = send(store)
        original = copy.deepcopy(only(store)[1]['payload'])
        collect(store, now=LATER)
        collect(store, rows=[row(MESSAGES[2])], now=LATER)
        self.assertEqual(list(store.read()['outbox']), [identifier])
        self.assertEqual(only(store)[1]['payload'], original)
        self.assertEqual(len(store.read()['ledger']['records'][only(store)[1]['receipt_id']]['variants']), 2)
        self.assertEqual(monitor.send_one(store, transport, identifier, LATER, policy(send_enabled=True)), 'suppressed')
        self.assertEqual(len(transport.calls), 1)

    def test_known_not_sent_not_automatically_retried(self):
        store = collect()
        transport, identifier, outcome = send(store, monitor.SyntheticTransport('known_not_sent'))
        self.assertEqual(outcome, 'known_not_sent')
        self.assertEqual(monitor.send_one(store, transport, identifier, LATER, policy(send_enabled=True)), 'suppressed')
        with self.assertRaises(ValueError):
            transport.arrival(identifier, LATER)
        self.assertEqual(len(transport.calls), 1)

    def test_uncertain_no_retry_and_separate_evidence_allowed(self):
        store = collect()
        transport, identifier, outcome = send(store, monitor.SyntheticTransport('timeout_after_accept'))
        self.assertEqual(outcome, 'uncertain')
        self.assertIsNone(only(store)[1]['transport_proof'])
        monitor.record_evidence(store, transport, identifier, transport.arrival(identifier, LATER), 'arrival')
        monitor.record_evidence(store, transport, identifier, transport.human_ack(identifier, AFTER), 'human_ack')
        self.assertEqual(only(store)[1]['state'], 'uncertain')
        self.assertEqual(monitor.send_one(store, transport, identifier, AFTER, policy(send_enabled=True)), 'suppressed')
        self.assertEqual(len(transport.calls), 1)

    def test_reservation_save_failure_or_conflict_has_zero_sends(self):
        for fault in ['before', 'conflict', 'after']:
            with self.subTest(fault=fault):
                store = collect()
                transport = monitor.SyntheticTransport()
                store.next_fault = fault
                with self.assertRaises((monitor.StoreConflict, monitor.StoreUncertain)):
                    send(store, transport)
                self.assertEqual(transport.calls, [])
                if fault == 'after':
                    self.assertEqual(only(store)[1]['state'], 'reserved')
                    self.assertEqual(monitor.send_one(store, transport, only(store)[0], LATER,
                                                     policy(send_enabled=True)), 'suppressed')

    def test_save_confirmation_wrong_revision_never_sends(self):
        store, transport = collect(), monitor.SyntheticTransport()
        original = store.compare_and_swap
        def wrong(expected, candidate):
            original(expected, candidate)
            return None
        with patch.object(store, 'compare_and_swap', side_effect=wrong):
            with self.assertRaises(monitor.StoreUncertain):
                send(store, transport)
        self.assertEqual(transport.calls, [])
        self.assertEqual(only(store)[1]['state'], 'reserved')

    def test_result_save_failure_preserves_reservation_and_no_retry(self):
        for fault in ['before', 'after', 'conflict']:
            with self.subTest(fault=fault):
                store, transport = collect(), monitor.SyntheticTransport()
                original = transport.send
                def send_then_fault(payload, now):
                    result = original(payload, now)
                    store.next_fault = fault
                    return result
                with patch.object(transport, 'send', side_effect=send_then_fault):
                    with self.assertRaises((monitor.StoreUncertain, monitor.StoreConflict)):
                        send(store, transport)
                snapshot = store.read()
                restarted = monitor.SyntheticCASStore(snapshot)
                identifier = only(restarted)[0]
                monitor.recover_reserved(restarted, LATER)
                self.assertEqual(monitor.send_one(restarted, transport, identifier, LATER,
                                                 policy(send_enabled=True)), 'suppressed')
                self.assertEqual(len(transport.calls), 1)

    def test_crash_after_reservation_no_automatic_send_on_restart(self):
        store, transport = collect(), monitor.SyntheticTransport()
        with patch.object(transport, 'send', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                send(store, transport)
        restarted = monitor.SyntheticCASStore(store.read())
        self.assertEqual(only(restarted)[1]['state'], 'reserved')
        self.assertEqual(monitor.send_one(restarted, transport, only(restarted)[0], LATER,
                                         policy(send_enabled=True)), 'suppressed')
        monitor.recover_reserved(restarted, LATER)
        self.assertEqual(only(restarted)[1]['state'], 'uncertain')
        self.assertEqual(transport.calls, [])

    def test_competing_senders_only_cas_winner_invokes(self):
        store, transport = collect(), monitor.SyntheticTransport()
        barrier, errors, outcomes = threading.Barrier(2), [], []
        original = store.compare_and_swap
        def racing(expected, candidate):
            if expected == 1:
                barrier.wait(timeout=5)
            return original(expected, candidate)
        def worker():
            try:
                outcomes.append(send(store, transport)[2])
            except monitor.StoreConflict:
                outcomes.append('conflict')
            except BaseException as error:
                errors.append(type(error).__name__)
        with patch.object(store, 'compare_and_swap', side_effect=racing):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertCountEqual(outcomes, ['accepted', 'conflict'])
        self.assertEqual(len(transport.calls), 1)

    def test_capacity_keeps_terminal_tombstone_and_all_state(self):
        store = collect()
        send(store)
        before = store.read()
        with patch.object(monitor, 'MAX_ALERTS', 1):
            with self.assertRaisesRegex(ValueError, 'STATE_CAPACITY'):
                collect(store, rows=[row(identifier='synthetic-second-id')], now=LATER)
        self.assertEqual(store.read(), before)

    def test_tombstone_removal_and_rearm_transition_rejected(self):
        store = collect()
        send(store)
        before = store.read()
        empty = monitor.new_bundle()
        empty['revision'] = before['revision'] + 1
        with self.assertRaises(ValueError):
            store.compare_and_swap(before['revision'], empty)
        bad = copy.deepcopy(before)
        item = next(iter(bad['outbox'].values()))
        item.update(state='unattempted', attempt_id=None, reserved_at=None,
                    outcome_at=None, transport_proof=None)
        bad['revision'] += 1
        with self.assertRaises(ValueError):
            store.compare_and_swap(before['revision'], bad)
        self.assertEqual(store.read(), before)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.store = collect()
        self.transport, self.identifier, _ = send(self.store)

    def test_caller_json_and_foreign_handle_never_proof(self):
        for token in [
                {'provenance': 'synthetic_fake_transport', 'kind': 'human_ack'},
                {'delivered': True}, {'human_ack': True}, object(), 'accepted', None]:
            with self.assertRaises(ValueError):
                monitor.record_evidence(self.store, self.transport, self.identifier, token, 'human_ack')
        other = monitor.SyntheticTransport()
        token = other.send(only(self.store)[1]['payload'], NOW)
        with self.assertRaises(ValueError):
            monitor.record_evidence(self.store, self.transport, self.identifier, token, 'human_ack')

    def test_wrong_recipient_receipt_and_owner_rejected(self):
        tokens = [
            (self.transport.arrival(self.identifier, LATER, destination='synthetic-other-room'), 'arrival'),
            (self.transport.human_ack(self.identifier, LATER, owner='synthetic-other-person'), 'human_ack'),
            (self.transport.human_ack(self.identifier, LATER, destination='synthetic-other-room'), 'human_ack')]
        for token, kind in tokens:
            with self.assertRaises(ValueError):
                monitor.record_evidence(self.store, self.transport, self.identifier, token, kind)
        self.assertIsNone(only(self.store)[1]['arrival_proof'])
        self.assertIsNone(only(self.store)[1]['human_ack_proof'])

    def test_transport_acceptance_not_arrival_or_ack(self):
        item = only(self.store)[1]
        self.assertEqual(item['state'], 'accepted')
        self.assertIsNone(item['arrival_proof'])
        self.assertIsNone(item['human_ack_proof'])
        token = next(iter(self.transport._proofs))
        for kind in ['arrival', 'human_ack']:
            with self.assertRaises(ValueError):
                monitor.record_evidence(self.store, self.transport, self.identifier, token, kind)

    def test_history_presence_or_absence_never_receipt(self):
        for value in [{'history_visible': True}, {'history_visible': False},
                      {'message_id': 'synthetic-id'}, {'reaction': 'thumbs_up'}]:
            with self.assertRaises(ValueError):
                monitor.record_evidence(self.store, self.transport, self.identifier, value, 'arrival')
        self.assertEqual(only(self.store)[1]['state'], 'accepted')
        self.assertIsNone(only(self.store)[1]['arrival_proof'])

    def test_nonexplicit_reply_and_ack_replay_rejected(self):
        for explicit in [False, None, 'yes', 1]:
            with self.assertRaises(ValueError):
                self.transport.human_ack(self.identifier, LATER, explicit=explicit)
        token = self.transport.human_ack(self.identifier, LATER)
        monitor.record_evidence(self.store, self.transport, self.identifier, token, 'human_ack')
        with self.assertRaises(ValueError):
            monitor.record_evidence(self.store, self.transport, self.identifier, token, 'human_ack')
        self.assertIsNone(only(self.store)[1]['arrival_proof'])

    def test_wrong_alert_or_payload_binding_rejected(self):
        other = collect(rows=[row(identifier='synthetic-second-id')])
        _, other_id, _ = send(other, self.transport)
        token = self.transport.human_ack(other_id, LATER)
        with self.assertRaises(ValueError):
            monitor.record_evidence(self.store, self.transport, self.identifier, token, 'human_ack')
        token = self.transport.human_ack(self.identifier, LATER)
        self.transport._proofs[token]['payload_digest'] = '0' * 64
        with self.assertRaises(ValueError):
            monitor.record_evidence(self.store, self.transport, self.identifier, token, 'human_ack')

    def test_proof_before_reservation_rejected(self):
        token = self.transport.human_ack(self.identifier, '2026-11-11T11:59:59Z')
        with self.assertRaises(ValueError):
            monitor.record_evidence(self.store, self.transport, self.identifier, token, 'human_ack')

    def test_evidence_cas_conflict_does_not_appear_saved(self):
        before = self.store.read()
        token = self.transport.human_ack(self.identifier, LATER)
        self.store.next_fault = 'conflict'
        with self.assertRaises(monitor.StoreConflict):
            monitor.record_evidence(self.store, self.transport, self.identifier, token, 'human_ack')
        self.assertEqual(self.store.read(), before)


class PrivateFileCASTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='synthetic-monitor-')
        self.directory = Path(self.temporary.name)
        self.directory.chmod(0o700)
        self.path = self.directory / 'bundle.json'
        self.store = monitor.SyntheticFileCASStore(self.path)
        self.store.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def test_private_file_reload_contains_only_sanitized_bundle(self):
        collect(self.store)
        transport, identifier, _ = send(self.store)
        reloaded = monitor.SyntheticFileCASStore(self.path)
        self.assertEqual(reloaded.read(), self.store.read())
        self.assertEqual(monitor.send_one(reloaded, transport, identifier, LATER,
                                         policy(send_enabled=True)), 'suppressed')
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        for forbidden in [CANARY, RAW_ID, monitor.RESOURCE]:
            self.assertNotIn(forbidden, self.path.read_text())

    def test_missing_store_never_auto_initializes(self):
        self.path.unlink()
        with self.assertRaises(monitor.StoreUncertain):
            collect(self.store)
        self.assertFalse(self.path.exists())

    def test_initialize_never_overwrites_existing(self):
        before = self.path.read_bytes()
        with self.assertRaises(monitor.StoreConflict):
            self.store.initialize()
        self.assertEqual(self.path.read_bytes(), before)

    def test_stale_generation_fails_without_overwrite(self):
        stale = self.store.read()
        collect(self.store)
        candidate = copy.deepcopy(stale)
        candidate['revision'] += 1
        before = self.path.read_bytes()
        with self.assertRaises(monitor.StoreConflict):
            self.store.compare_and_swap(stale['revision'], candidate)
        self.assertEqual(self.path.read_bytes(), before)

    def test_existing_lock_stops_send_and_is_not_stolen(self):
        collect(self.store)
        lock = self.path.with_name(self.path.name + '.lock')
        lock.touch(mode=0o600)
        transport = monitor.SyntheticTransport()
        with self.assertRaises(monitor.StoreConflict):
            send(self.store, transport)
        self.assertTrue(lock.exists())
        self.assertEqual(transport.calls, [])

    def test_reserved_reload_recovery_never_resends(self):
        collect(self.store)
        transport = monitor.SyntheticTransport()
        with patch.object(transport, 'send', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                send(self.store, transport)
        reloaded = monitor.SyntheticFileCASStore(self.path)
        identifier = only(reloaded)[0]
        self.assertEqual(monitor.send_one(reloaded, transport, identifier, LATER,
                                         policy(send_enabled=True)), 'suppressed')
        monitor.recover_reserved(reloaded, LATER)
        self.assertEqual(only(reloaded)[1]['state'], 'uncertain')
        self.assertEqual(transport.calls, [])

    def test_replace_failure_before_reservation_has_zero_sends(self):
        collect(self.store)
        before, transport = self.path.read_bytes(), monitor.SyntheticTransport()
        with patch.object(monitor.os, 'replace', side_effect=OSError(CANARY)):
            with self.assertRaises(monitor.StoreUncertain):
                send(self.store, transport)
        self.assertEqual(transport.calls, [])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ['bundle.json'])

    def test_directory_fsync_unknown_reservation_zero_sends_then_no_retry(self):
        collect(self.store)
        transport, real_fsync, calls = monitor.SyntheticTransport(), monitor.os.fsync, []
        def fsync(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError(CANARY)
            return real_fsync(fd)
        with patch.object(monitor.os, 'fsync', side_effect=fsync):
            with self.assertRaises(monitor.StoreUncertain):
                send(self.store, transport)
        self.assertEqual(transport.calls, [])
        reloaded = monitor.SyntheticFileCASStore(self.path)
        self.assertEqual(only(reloaded)[1]['state'], 'reserved')
        self.assertEqual(monitor.send_one(reloaded, transport, only(reloaded)[0], LATER,
                                         policy(send_enabled=True)), 'suppressed')

    def test_result_file_save_failure_blocks_resend_after_reload(self):
        collect(self.store)
        transport, real_replace = monitor.SyntheticTransport(), monitor.os.replace
        calls = []
        def replace(source, target):
            calls.append(source)
            if len(calls) == 2:
                raise OSError(CANARY)
            return real_replace(source, target)
        with patch.object(monitor.os, 'replace', side_effect=replace):
            with self.assertRaises(monitor.StoreUncertain):
                send(self.store, transport)
        reloaded = monitor.SyntheticFileCASStore(self.path)
        self.assertEqual(only(reloaded)[1]['state'], 'reserved')
        self.assertEqual(monitor.send_one(reloaded, transport, only(reloaded)[0], LATER,
                                         policy(send_enabled=True)), 'suppressed')
        self.assertEqual(len(transport.calls), 1)

    def test_nonprivate_state_symlink_hardlink_and_fifo_rejected(self):
        self.path.chmod(0o644)
        with self.assertRaises(monitor.StoreUncertain):
            self.store.read()
        self.path.chmod(0o600)
        other = self.directory / 'other'
        os.link(self.path, other)
        with self.assertRaises(monitor.StoreUncertain):
            self.store.read()
        other.unlink()
        self.path.unlink()
        other.write_text(CANARY)
        other.chmod(0o600)
        self.path.symlink_to(other)
        with self.assertRaises(monitor.StoreUncertain):
            self.store.read()
        self.path.unlink()
        os.mkfifo(self.path, mode=0o600)
        with self.assertRaises(monitor.StoreUncertain):
            self.store.read()
        self.assertEqual(other.read_text(), CANARY)

    def test_parent_permission_symlink_and_bad_state_rejected(self):
        self.directory.chmod(0o755)
        with self.assertRaises(ValueError):
            monitor.SyntheticFileCASStore(self.path)
        self.directory.chmod(0o700)
        alias = self.directory / 'alias'
        alias.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(ValueError):
            monitor.SyntheticFileCASStore(alias / 'bundle.json')
        self.path.write_text('{"raw":"' + CANARY + '"}')
        self.path.chmod(0o600)
        before = self.path.read_bytes()
        with self.assertRaises(monitor.StoreUncertain):
            self.store.read()
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
