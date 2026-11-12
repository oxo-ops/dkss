"""Synthetic-only connection rehearsal. No network, scheduler or live port.

Optional POSIX private-file CAS is for fresh synthetic temporary directories.

The in-memory CAS store models a contract; it is NOT durable storage. Proof
handles originate only from the injected fake transport and mean SYNTHETIC
evidence, never real user confirmation. Trusted Python code and store are
assumptions, not an authentication/security sandbox. Original ledger unchanged.
"""
import copy
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import stat
import tempfile
import threading

import log_ledger as ledger

RESOURCE = 'srv-synthetic12345678'
DESTINATION = 'synthetic-owner-dot-conversation'
OWNER = 'synthetic-owner'
MODE = 'synthetic_trial'
FORMAT = 'q09-synthetic-monitor-v1'
MAX_ALERTS = 100
RESOURCE_HASH = ledger.digest(RESOURCE)
DESTINATION_HASH = ledger.digest(DESTINATION)
OWNER_HASH = ledger.digest(OWNER)
STATES = {'unattempted', 'reserved', 'accepted', 'known_not_sent', 'uncertain'}


def reject():
    raise ValueError('INVALID_SYNTHETIC_MONITOR_INPUT')


def keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        reject()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return ledger.digest(encoded(value))


def timestamp(value):
    result = ledger.canonical_time(value)
    if result != value:
        reject()
    return result


def shift(value, seconds):
    value = ledger.canonical_time(value)
    moment = datetime.fromisoformat(value[:19]) + timedelta(seconds=seconds)
    return (f'{moment.year:04d}-{moment.month:02d}-{moment.day:02d}T'
            f'{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}' + value[19:])


def hex_value(value):
    if not isinstance(value, str) or not ledger.HEX.fullmatch(value):
        reject()


@dataclass(frozen=True)
class Policy:
    # Explicit rehearsal numbers, NOT an approved operational cadence.
    cadence_seconds: int
    overlap_seconds: int
    send_enabled: bool = False
    schedule_enabled: bool = False

    def __post_init__(self):
        if (type(self.cadence_seconds) is not int or
                not 1 <= self.cadence_seconds <= 86400 or
                type(self.overlap_seconds) is not int or
                not 1 <= self.overlap_seconds <= 604800 or
                type(self.send_enabled) is not bool or
                type(self.schedule_enabled) is not bool):
            reject()


def alert_id(receipt_id):
    hex_value(receipt_id)
    return digest([FORMAT, RESOURCE_HASH, receipt_id, DESTINATION_HASH])


def attempt_id(identifier):
    return digest([FORMAT, identifier, 'attempt-1'])


def new_bundle():
    state = ledger.new_state(RESOURCE)
    return {'format': FORMAT, 'mode': MODE, 'revision': 0,
            'ledger': state, 'ledger_digest': digest(state),
            'last_collection_at': None, 'outbox': {}}


def payload_for(pending):
    identifier = alert_id(pending['receipt_id'])
    return {'format': 'q09-synthetic-alert-v1', 'mode': MODE,
            'alert_id': identifier, 'receipt_id': pending['receipt_id'],
            'resource_hash': RESOURCE_HASH, 'destination_hash': DESTINATION_HASH,
            'variants': copy.deepcopy(pending['variants']),
            'requires_review': pending['requires_review']}


def validate_payload(payload, state):
    keys(payload, {'format', 'mode', 'alert_id', 'receipt_id', 'resource_hash',
                   'destination_hash', 'variants', 'requires_review'})
    receipt = payload['receipt_id']
    if (payload['format'] != 'q09-synthetic-alert-v1' or payload['mode'] != MODE or
            payload['resource_hash'] != RESOURCE_HASH or
            payload['destination_hash'] != DESTINATION_HASH or
            payload['alert_id'] != alert_id(receipt) or
            receipt not in state['records'] or type(payload['requires_review']) is not bool):
        reject()
    variants = payload['variants']
    if not isinstance(variants, list) or not variants or len(variants) > ledger.MAX_VARIANTS:
        reject()
    if len({encoded(v) for v in variants}) != len(variants):
        reject()
    for variant in variants:
        ledger.validate_variant(variant)
        if variant['kind'] == 'unrelated' or variant not in state['records'][receipt]['variants']:
            reject()
        if (variant['kind'] != 'event' or variant.get('requires_review')) and not payload['requires_review']:
            reject()


def proof_fields(proof, entry, kind):
    keys(proof, {'provenance', 'kind', 'alert_id', 'attempt_id', 'payload_digest',
                 'destination_hash', 'actor_hash', 'recorded_at'})
    if (proof['provenance'] != 'synthetic_fake_transport' or proof['kind'] != kind or
            proof['alert_id'] != entry['payload']['alert_id'] or
            proof['attempt_id'] != entry['attempt_id'] or
            proof['payload_digest'] != entry['payload_digest'] or
            proof['destination_hash'] != DESTINATION_HASH or
            proof['actor_hash'] != (OWNER_HASH if kind == 'human_ack' else None)):
        reject()
    timestamp(proof['recorded_at'])
    if entry['reserved_at'] is None or proof['recorded_at'] < entry['reserved_at']:
        reject()


def validate_bundle(bundle):
    keys(bundle, {'format', 'mode', 'revision', 'ledger', 'ledger_digest',
                  'last_collection_at', 'outbox'})
    if (bundle['format'] != FORMAT or bundle['mode'] != MODE or
            type(bundle['revision']) is not int or not 0 <= bundle['revision'] <= ledger.MAX_COUNT):
        reject()
    ledger.validate_state(bundle['ledger'], RESOURCE)
    if digest(bundle['ledger']) != bundle['ledger_digest']:
        reject()
    last = bundle['last_collection_at']
    if last is not None:
        timestamp(last)
    if (last is None) != (bundle['ledger']['runs'] == 0):
        reject()
    outbox = bundle['outbox']
    if not isinstance(outbox, dict) or len(outbox) > MAX_ALERTS:
        reject()
    eligible = {p['receipt_id'] for p in ledger.pending_notifications(bundle['ledger'], RESOURCE)}
    if {entry.get('receipt_id') for entry in outbox.values() if isinstance(entry, dict)} != eligible:
        reject()
    for identifier, entry in outbox.items():
        keys(entry, {'receipt_id', 'payload', 'payload_digest', 'created_at', 'state',
                     'attempt_id', 'reserved_at', 'outcome_at', 'transport_proof',
                     'arrival_proof', 'human_ack_proof'})
        if identifier != alert_id(entry['receipt_id']):
            reject()
        validate_payload(entry['payload'], bundle['ledger'])
        if (entry['payload']['receipt_id'] != entry['receipt_id'] or
                digest(entry['payload']) != entry['payload_digest'] or entry['state'] not in STATES):
            reject()
        timestamp(entry['created_at'])
        if last is None or entry['created_at'] > last:
            reject()
        if entry['state'] == 'unattempted':
            if bundle['ledger']['records'][entry['receipt_id']]['notification_status'] == 'uncertain':
                reject()
            if any(entry[k] is not None for k in (
                    'attempt_id', 'reserved_at', 'outcome_at', 'transport_proof',
                    'arrival_proof', 'human_ack_proof')):
                reject()
        else:
            if entry['attempt_id'] != attempt_id(identifier):
                reject()
            timestamp(entry['reserved_at'])
            if entry['reserved_at'] < entry['created_at']:
                reject()
            if entry['state'] == 'reserved':
                if entry['outcome_at'] is not None:
                    reject()
            else:
                timestamp(entry['outcome_at'])
                if entry['outcome_at'] < entry['reserved_at']:
                    reject()
            transport = entry['transport_proof']
            if entry['state'] in {'accepted', 'known_not_sent'}:
                proof_fields(transport, entry, entry['state'])
                if transport['recorded_at'] != entry['outcome_at']:
                    reject()
            elif transport is not None:
                reject()
            for field, kind in [('arrival_proof', 'arrival'), ('human_ack_proof', 'human_ack')]:
                if entry[field] is not None:
                    if entry['state'] == 'known_not_sent':
                        reject()
                    proof_fields(entry[field], entry, kind)
    if len(encoded(bundle).encode('utf-8')) > ledger.MAX_STATE:
        raise ValueError('STATE_CAPACITY')


def validate_transition(previous, candidate):
    """No eviction, reset, re-arming, payload rewriting or proof replacement."""
    validate_bundle(previous)
    validate_bundle(candidate)
    if candidate['revision'] != previous['revision'] + 1:
        reject()
    if candidate['ledger']['runs'] < previous['ledger']['runs']:
        reject()
    if previous['last_collection_at'] is not None and (
            candidate['last_collection_at'] is None or
            candidate['last_collection_at'] < previous['last_collection_at']):
        reject()
    for receipt, record in previous['ledger']['records'].items():
        newer = candidate['ledger']['records'].get(receipt)
        if newer is None or any(v not in newer['variants'] for v in record['variants']):
            reject()
    allowed = {'unattempted': {'unattempted', 'reserved'},
               'reserved': {'reserved', 'accepted', 'known_not_sent', 'uncertain'},
               'accepted': {'accepted'}, 'known_not_sent': {'known_not_sent'},
               'uncertain': {'uncertain'}}
    for identifier, old in previous['outbox'].items():
        new = candidate['outbox'].get(identifier)
        if new is None or new['state'] not in allowed[old['state']]:
            reject()
        for field in ('receipt_id', 'payload', 'payload_digest', 'created_at'):
            if new[field] != old[field]:
                reject()
        for field in ('attempt_id', 'reserved_at', 'outcome_at', 'transport_proof',
                      'arrival_proof', 'human_ack_proof'):
            if old[field] is not None and new[field] != old[field]:
                reject()


class StoreConflict(RuntimeError):
    pass


class StoreUncertain(RuntimeError):
    pass


class SyntheticCASStore:
    """Thread-safe process-memory MODEL only; no persistence/ACL guarantee.

    A real future port must atomically compare revision and save this WHOLE
    bundle, acknowledge durable commit, retain all tombstones and fail closed.
    It must not use the original CLI as a second independent state writer.
    """
    def __init__(self, snapshot=None):
        self._lock = threading.Lock()
        self._bundle = copy.deepcopy(new_bundle() if snapshot is None else snapshot)
        validate_bundle(self._bundle)
        self.next_fault = None  # Test injection only: conflict, before, after.

    def read(self):
        with self._lock:
            return copy.deepcopy(self._bundle)

    def compare_and_swap(self, expected_revision, candidate):
        with self._lock:
            fault, self.next_fault = self.next_fault, None
            if fault == 'conflict' or self._bundle['revision'] != expected_revision:
                raise StoreConflict('STORE_CONFLICT')
            if fault == 'before':
                raise StoreUncertain('STORE_OUTCOME_UNCERTAIN')
            validate_transition(self._bundle, candidate)
            self._bundle = copy.deepcopy(candidate)
            if fault == 'after':
                raise StoreUncertain('STORE_OUTCOME_UNCERTAIN')
            return candidate['revision']


class SyntheticFileCASStore:
    """POSIX-only private synthetic bundle, cooperative lock + atomic replace.

    Explicit initialize is required; a missing existing file NEVER resets the
    ledger. No production location, Space/Library port or encryption is set up.
    Same-UID processes and parent-directory ownership are trusted, as in the
    original CLI. A stale lock is never deleted/stolen by a new operation.
    """
    def __init__(self, path):
        self.path = Path(path)
        self._check_parent()

    def _check_parent(self):
        parent = self.path.parent
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
                stat.S_IMODE(info.st_mode) & 0o077 or self.path.name in {'', '.', '..'}):
            reject()
        for component in (parent, *parent.parents):
            if component.is_symlink():
                reject()

    def read(self):
        self._check_parent()
        try:
            bundle = ledger.private_file(self.path, ledger.MAX_STATE)
            validate_bundle(bundle)
            return bundle
        except Exception:
            raise StoreUncertain('STORE_UNREADABLE_OR_UNCERTAIN') from None

    def _write(self, expected_revision, candidate, initialize=False):
        self._check_parent()
        validate_bundle(candidate)
        lock = self.path.with_name(self.path.name + '.lock')
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise StoreConflict('STORE_LOCKED') from None
        os.close(fd)
        temporary = None
        try:
            if initialize:
                if os.path.lexists(self.path):
                    raise StoreConflict('STORE_ALREADY_EXISTS')
                if candidate != new_bundle():
                    reject()
            else:
                previous = self.read()
                if previous['revision'] != expected_revision:
                    raise StoreConflict('STORE_CONFLICT')
                validate_transition(previous, candidate)
            fd, temporary = tempfile.mkstemp(prefix='.synthetic-monitor-', dir=self.path.parent)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded(candidate).encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return candidate['revision']
        except StoreConflict:
            raise
        except Exception:
            raise StoreUncertain('STORE_OUTCOME_UNCERTAIN') from None
        finally:
            if temporary is not None:
                os.unlink(temporary)
            os.unlink(lock)

    def initialize(self):
        return self._write(None, new_bundle(), initialize=True)

    def compare_and_swap(self, expected_revision, candidate):
        return self._write(expected_revision, candidate)


def save(store, previous, candidate):
    candidate['revision'] = previous['revision'] + 1
    validate_transition(previous, candidate)
    try:
        revision = store.compare_and_swap(previous['revision'], candidate)
    except StoreConflict:
        raise
    except Exception:
        raise StoreUncertain('STORE_OUTCOME_UNCERTAIN') from None
    if type(revision) is not int or revision != candidate['revision']:
        raise StoreUncertain('STORE_OUTCOME_UNCERTAIN')
    return copy.deepcopy(candidate)


def due(bundle, now, policy):
    validate_bundle(bundle)
    now = ledger.canonical_time(now)
    last = bundle['last_collection_at']
    if last is not None and now < last:
        reject()
    return policy.schedule_enabled and (
        last is None or now >= shift(last, policy.cadence_seconds))


class SyntheticRecorder:
    """Injected fake trusted recorder: captures the actual query it receives.

    Replies are synthetic fixtures, consumed once. Neither fixtures nor queries
    are persisted. This is not a Render authentication or completeness proof.
    """
    def __init__(self, replies):
        if not isinstance(replies, list) or len(replies) > ledger.MAX_PAGES:
            reject()
        if len(encoded(replies).encode('utf-8')) > ledger.MAX_INPUT:
            reject()
        self._replies = copy.deepcopy(replies)
        self.calls = []

    def record(self, query):
        self.calls.append(copy.deepcopy(query))
        reply = self._replies.pop(0) if self._replies else {'ok': False}
        if not isinstance(reply, dict):
            reject()
        keys(reply, {'ok', 'page'} if reply.get('ok') is True else {'ok'})
        if type(reply['ok']) is not bool:
            reject()
        if reply['ok']:
            page = reply['page']
            if not isinstance(page, dict) or type(page.get('hasMore')) is not bool:
                reject()
            keys(page, {'logs', 'hasMore', 'nextStartTime', 'nextEndTime'}
                 if page['hasMore'] else {'logs', 'hasMore'})
        return {'query': copy.deepcopy(query), 'reply': reply}


def collect_once(store, recorder, now, policy, scheduled=False):
    """One explicit overlapping scan. 'scheduled' is a due gate, not a timer."""
    if type(recorder) is not SyntheticRecorder or type(policy) is not Policy or type(scheduled) is not bool:
        reject()
    previous = store.read()
    validate_bundle(previous)
    now = ledger.canonical_time(now)
    # Check rollback even when this is a manual invocation.
    is_due = due(previous, now, policy)
    if scheduled and not is_due:
        return previous
    window = {'startTime': shift(now, -(policy.cadence_seconds + policy.overlap_seconds)),
              'endTime': now}
    pages, current = [], window
    while len(pages) < ledger.MAX_PAGES:
        query = {'resource': [RESOURCE], 'type': ['app'], 'direction': 'forward',
                 **current, 'limit': 1000}
        pages.append(recorder.record(query))
        transcript = {'resource': RESOURCE, 'window': window,
                      'direction': 'forward', 'pages': pages}
        state, _ = ledger.observe(previous['ledger'], transcript)
        scan = state['last_scan']
        if scan['chain_status'] != 'incomplete' or scan['next_window'] is None:
            break
        current = scan['next_window']
    candidate = copy.deepcopy(previous)
    candidate['ledger'] = state
    candidate['ledger_digest'] = digest(state)
    candidate['last_collection_at'] = now
    for pending in ledger.pending_notifications(state, RESOURCE):
        identifier = alert_id(pending['receipt_id'])
        if identifier in candidate['outbox']:
            continue  # Never re-arm or change the original payload after a conflict.
        if len(candidate['outbox']) >= MAX_ALERTS:
            raise ValueError('STATE_CAPACITY')
        payload = payload_for(pending)
        candidate['outbox'][identifier] = {
            'receipt_id': pending['receipt_id'], 'payload': payload,
            'payload_digest': digest(payload), 'created_at': now,
            'state': 'unattempted', 'attempt_id': None, 'reserved_at': None,
            'outcome_at': None, 'transport_proof': None,
            'arrival_proof': None, 'human_ack_proof': None}
    return save(store, previous, candidate)


class SyntheticTransport:
    """No I/O. In-process opaque handles prevent self-declared JSON evidence.

    Public fixture minting deliberately simulates, rather than authenticates, a
    recipient. No real delivery/owner claim can be represented by this module.
    """
    def __init__(self, outcome='accepted'):
        if outcome not in {'accepted', 'known_not_sent', 'timeout_after_accept'}:
            reject()
        self.outcome = outcome
        self.calls = []
        self._proofs = {}
        self._sent = {}

    def _mint(self, payload, kind, now, destination=DESTINATION, actor=None):
        token = object()
        self._proofs[token] = {
            'provenance': 'synthetic_fake_transport', 'kind': kind,
            'alert_id': payload['alert_id'], 'attempt_id': attempt_id(payload['alert_id']),
            'payload_digest': digest(payload), 'destination_hash': ledger.digest(destination),
            'actor_hash': None if actor is None else ledger.digest(actor),
            'recorded_at': ledger.canonical_time(now)}
        return token

    def resolve(self, token):
        # dict/list/string and handles from other transport instances cannot resolve.
        if type(token) is not object or token not in self._proofs:
            reject()
        return copy.deepcopy(self._proofs[token])

    def send(self, payload, now):
        self.calls.append(copy.deepcopy(payload))
        if self.outcome != 'known_not_sent':
            self._sent[payload['alert_id']] = copy.deepcopy(payload)
        if self.outcome == 'timeout_after_accept':
            raise TimeoutError('SYNTHETIC_OUTCOME_UNKNOWN')
        return self._mint(payload, self.outcome, now)

    def arrival(self, identifier, now, destination=DESTINATION):
        if identifier not in self._sent:
            reject()
        return self._mint(self._sent[identifier], 'arrival', now, destination)

    def human_ack(self, identifier, now, owner=OWNER, destination=DESTINATION, explicit=True):
        if identifier not in self._sent or explicit is not True:
            reject()
        return self._mint(self._sent[identifier], 'human_ack', now, destination, owner)


def send_one(store, transport, identifier, now, policy):
    """Reserve durably in the port contract BEFORE one fake send invocation.

    Any reservation/save conflict or unknown outcome aborts before calling send.
    Reloaded reserved, uncertain and all terminal states are NEVER retried.
    Accepted only means synthetic sender acceptance, not arrival or human ack.
    """
    if type(transport) is not SyntheticTransport or type(policy) is not Policy:
        reject()
    previous = store.read()
    validate_bundle(previous)
    now = ledger.canonical_time(now)
    if identifier not in previous['outbox']:
        reject()
    entry = previous['outbox'][identifier]
    if not policy.send_enabled:
        return 'disabled'
    if entry['state'] != 'unattempted':
        return 'suppressed'
    if now < entry['created_at']:
        reject()
    candidate = copy.deepcopy(previous)
    item = candidate['outbox'][identifier]
    item.update(state='reserved', attempt_id=attempt_id(identifier), reserved_at=now)
    reserved = save(store, previous, candidate)
    proof, outcome = None, 'uncertain'
    try:
        token = transport.send(copy.deepcopy(item['payload']), now)
        proof = transport.resolve(token)
        outcome = proof['kind']
        if outcome not in {'accepted', 'known_not_sent'}:
            reject()
        proof_fields(proof, item, outcome)
        if proof['recorded_at'] != now:
            reject()
    except Exception:
        proof, outcome = None, 'uncertain'
    result = copy.deepcopy(reserved)
    result['outbox'][identifier].update(
        state=outcome, outcome_at=now, transport_proof=proof)
    # Failure here leaves the durable reservation or a terminal result. No retry.
    save(store, reserved, result)
    return outcome


def recover_reserved(store, now):
    """Explicit restart reconciliation: only reserved -> uncertain, never send."""
    previous = store.read()
    validate_bundle(previous)
    now = ledger.canonical_time(now)
    candidate = copy.deepcopy(previous)
    for item in candidate['outbox'].values():
        if item['state'] == 'reserved':
            if now < item['reserved_at']:
                reject()
            item.update(state='uncertain', outcome_at=now)
    if candidate == previous:
        return previous
    return save(store, previous, candidate)


def record_evidence(store, transport, identifier, token, kind):
    """Record independently sourced SYNTHETIC arrival OR explicit owner ack.

    A fake accepted response is not a receipt at the destination. A history
    search, quoted text, generic reaction or caller-supplied evidence dict is
    not an acknowledgment input. No received-at/device timestamp is invented.
    """
    if type(transport) is not SyntheticTransport or kind not in {'arrival', 'human_ack'}:
        reject()
    previous = store.read()
    validate_bundle(previous)
    if identifier not in previous['outbox']:
        reject()
    item = previous['outbox'][identifier]
    if item['state'] in {'unattempted', 'known_not_sent'}:
        reject()
    proof = transport.resolve(token)
    proof_fields(proof, item, kind)
    field = kind + '_proof'
    if item[field] is not None:
        reject()  # No replacement/replay of accepted proof.
    candidate = copy.deepcopy(previous)
    candidate['outbox'][identifier][field] = proof
    return save(store, previous, candidate)
