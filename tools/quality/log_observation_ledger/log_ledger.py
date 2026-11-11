"""Offline, conservative Render log observation ledger. Standard library only.

Input is a TRUSTED recorder's cumulative, ordered query/reply transcript, not a
provider completeness certificate. No network, environment lookup, or delivery.
Timestamp-only pagination NEVER advances the trusted read checkpoint.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone

from log_event_receipts import (
    EVENT_FIELDS, EVENT_PATTERN, ID_PATTERN, LEVELS, labels_of, project_page,
)

FORMAT = 'q09-offline-ledger-v1'
MAX_INPUT = 4 * 1024 * 1024
MAX_STATE = 16 * 1024 * 1024
MAX_IDS = 10000
MAX_VARIANTS = 8
MAX_PAGES = 100
MAX_COUNT = 10 ** 12
HEX = re.compile(r'[0-9a-f]{64}\Z')
RESOURCE = re.compile(r'srv-[a-z0-9]{8,64}\Z')
TIMESTAMP = re.compile(
    r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})\Z')
UNKNOWN_FAILURE = re.compile(r'(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]*_FAILED(?![A-Za-z0-9_])')
DIAGNOSTICS = {
    'api_failure', 'invalid_page', 'invalid_query', 'broken_page_chain',
    'pages_after_terminal', 'cursor_stalled', 'invalid_cursor',
    'nonmonotonic_records', 'rejected_record', 'record_outside_query',
    'replayed_log_id', 'conflicting_log_id', 'unprojectable_known_failure',
    'unknown_failure_marker', 'classification_requires_review',
    'missing_terminal_page', 'timestamp_coverage_unverified',
}
VARIANT_KINDS = {'event', 'unrelated', 'unprojectable_known_failure', 'unknown_failure_marker'}


def fail(code='INVALID_INPUT'):
    raise ValueError(code)


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def canonical_time(value):
    """Normalize RFC3339 without losing nanoseconds or comparing timestamp text."""
    match = TIMESTAMP.fullmatch(value) if isinstance(value, str) else None
    if not match:
        fail()
    base, fraction, offset = match.groups()
    if offset != 'Z' and (int(offset[1:3]) > 23 or int(offset[4:6]) > 59):
        fail()
    # RFC3339 -00:00 means local offset unknown, not known UTC.
    if offset == '-00:00':
        fail()
    try:
        moment = datetime.fromisoformat(base + ('+00:00' if offset == 'Z' else offset))
        moment = moment.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        fail()
    return (f'{moment.year:04d}-{moment.month:02d}-{moment.day:02d}T'
            f'{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}.' +
            (fraction or '').ljust(9, '0') + 'Z')


def exact_keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        fail()


def count(value):
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        fail('INVALID_STATE')
    return value


def window(value):
    exact_keys(value, {'startTime', 'endTime'})
    result = {name: canonical_time(value[name]) for name in ('startTime', 'endTime')}
    if result['startTime'] >= result['endTime']:
        fail()
    return result


def new_state(resource):
    if not isinstance(resource, str) or not RESOURCE.fullmatch(resource):
        fail()
    return {'format': FORMAT, 'resource_hash': digest(resource),
            'read_checkpoint': None, 'records': {}, 'runs': 0,
            'last_scan': None, 'monitoring_status': 'not_scheduled',
            'delivery_status': 'not_attempted_by_ledger'}


def validate_variant(value):
    if not isinstance(value, dict) or value.get('kind') not in VARIANT_KINDS:
        fail('INVALID_STATE')
    kind = value['kind']
    keys = {'kind', 'observed_at'}
    if kind == 'event':
        keys |= {'event', 'level', 'details', 'requires_review', 'unknown_marker_present'}
    elif kind == 'unprojectable_known_failure':
        keys |= {'known_events', 'unknown_marker_present'}
    exact_keys(value, keys)
    if canonical_time(value['observed_at']) != value['observed_at']:
        fail('INVALID_STATE')
    if kind in {'event', 'unprojectable_known_failure'} and type(value['unknown_marker_present']) is not bool:
        fail('INVALID_STATE')
    if kind == 'event':
        event = value['event']
        if not isinstance(event, str) or event not in EVENT_FIELDS:
            fail('INVALID_STATE')
        if value['level'] not in LEVELS | {'unverified'} or type(value['requires_review']) is not bool:
            fail('INVALID_STATE')
        exact_keys(value['details'], set(EVENT_FIELDS[event]))
        for key, item in value['details'].items():
            if not isinstance(item, str) or item not in EVENT_FIELDS[event][key] | {'unverified'}:
                fail('INVALID_STATE')
        if ('unverified' in value['details'].values() or value['unknown_marker_present']) and not value['requires_review']:
            fail('INVALID_STATE')
    elif kind == 'unprojectable_known_failure':
        events = value['known_events']
        if (not isinstance(events, list) or not events or
                any(not isinstance(event, str) or event not in EVENT_FIELDS for event in events) or
                events != sorted(set(events))):
            fail('INVALID_STATE')


def validate_state(value, resource):
    """Reject extras before reserializing, so prior state cannot smuggle raw text."""
    exact_keys(value, {'format', 'resource_hash', 'read_checkpoint', 'records',
                       'runs', 'last_scan', 'monitoring_status', 'delivery_status'})
    if (value['format'] != FORMAT or value['resource_hash'] != digest(resource) or
            value['read_checkpoint'] is not None or
            value['monitoring_status'] != 'not_scheduled' or
            value['delivery_status'] != 'not_attempted_by_ledger'):
        fail('INVALID_STATE')
    count(value['runs'])
    records = value['records']
    if not isinstance(records, dict) or len(records) > MAX_IDS:
        fail('INVALID_STATE')
    for record_id, record in records.items():
        if not isinstance(record_id, str) or not HEX.fullmatch(record_id):
            fail('INVALID_STATE')
        exact_keys(record, {'variants', 'notification_status', 'acknowledgment_status'})
        if (record['notification_status'] not in {'not_sent', 'uncertain'} or
                record['acknowledgment_status'] != 'not_received'):
            fail('INVALID_STATE')
        variants = record['variants']
        if not isinstance(variants, list) or not 1 <= len(variants) <= MAX_VARIANTS:
            fail('INVALID_STATE')
        for variant in variants:
            validate_variant(variant)
        if len({json.dumps(v, sort_keys=True) for v in variants}) != len(variants):
            fail('INVALID_STATE')
    scan = value['last_scan']
    if scan is not None:
        exact_keys(scan, {'window', 'direction', 'pages_received', 'pages_linked',
                         'terminal_seen', 'chain_status', 'coverage_status',
                         'next_window', 'last_query_window', 'last_response_status',
                         'last_response_has_more', 'counts'})
        if window(scan['window']) != scan['window'] or scan['direction'] not in {'forward', 'backward'}:
            fail('INVALID_STATE')
        for key in ('pages_received', 'pages_linked'):
            count(scan[key])
        if type(scan['terminal_seen']) is not bool:
            fail('INVALID_STATE')
        if scan['chain_status'] not in {'linked_terminal', 'incomplete', 'broken'}:
            fail('INVALID_STATE')
        if scan['coverage_status'] != 'incomplete_timestamp_only':
            fail('INVALID_STATE')
        if scan['next_window'] is not None and window(scan['next_window']) != scan['next_window']:
            fail('INVALID_STATE')
        if scan['last_query_window'] is not None and window(scan['last_query_window']) != scan['last_query_window']:
            fail('INVALID_STATE')
        if scan['last_response_status'] not in {'not_observed', 'page', 'api_failure', 'invalid_page'}:
            fail('INVALID_STATE')
        if scan['last_response_has_more'] is not None and type(scan['last_response_has_more']) is not bool:
            fail('INVALID_STATE')
        if not isinstance(scan['counts'], dict) or scan['counts'].keys() - DIAGNOSTICS:
            fail('INVALID_STATE')
        for item in scan['counts'].values():
            count(item)


def query_window(query, resource, direction):
    # Scope must be identical and unfiltered. Extra text/level/instance filters
    # would make the apparent coverage narrower than all five failure events.
    exact_keys(query, {'resource', 'type', 'direction', 'startTime', 'endTime', 'limit'})
    if (query['resource'] != [resource] or query['type'] != ['app'] or
            query['direction'] != direction or type(query['limit']) is not int or
            not 1 <= query['limit'] <= 1000):
        fail()
    return window({key: query[key] for key in ('startTime', 'endTime')})


def observe(state, transcript):
    """Return a NEW state and sanitized report; input objects are never mutated.

    Each call must replay the cumulative transcript starting at its declared
    window. A lone continuation page is not a completed scan. Replays are cheap
    enough for this bounded prototype and keep resumability unambiguous.
    """
    exact_keys(transcript, {'resource', 'window', 'direction', 'pages'})
    resource, direction = transcript['resource'], transcript['direction']
    initial = new_state(resource)
    target = window(transcript['window'])
    if direction not in {'forward', 'backward'}:
        fail()
    pages = transcript['pages']
    if not isinstance(pages, list) or len(pages) > MAX_PAGES:
        fail()
    if state is None:
        state = initial
    validate_state(state, resource)
    output = copy.deepcopy(state)
    counts = {}

    def issue(name, amount=1):
        counts[name] = count(counts.get(name, 0) + amount)

    expected, terminal, broken, linked = target, False, False, 0
    last_window, last_status, last_more = None, 'not_observed', None
    for envelope in pages:
        if terminal:
            issue('pages_after_terminal'); broken = True
            break
        try:
            exact_keys(envelope, {'query', 'reply'})
            actual = query_window(envelope['query'], resource, direction)
        except (ValueError, TypeError, KeyError):
            issue('invalid_query'); broken = True
            break
        if actual != expected:
            issue('broken_page_chain'); broken = True
            break
        last_window = actual
        reply = envelope['reply']
        if not isinstance(reply, dict) or type(reply.get('ok')) is not bool:
            last_status, last_more = 'invalid_page', None
            issue('invalid_page'); broken = True
            break
        if not reply['ok']:
            # Deliberately never retain API exception text or arbitrary error data.
            last_status, last_more = 'api_failure', None
            issue('api_failure'); broken = True
            break
        page = reply.get('page')
        if (not isinstance(page, dict) or type(page.get('hasMore')) is not bool or
                not isinstance(page.get('logs'), list) or len(page['logs']) > envelope['query']['limit']):
            last_status, last_more = 'invalid_page', None
            issue('invalid_page'); broken = True
            break
        last_status, last_more = 'page', page['hasMore']
        linked += 1
        previous = None
        for row in page['logs']:
            labels = labels_of(row) if isinstance(row, dict) else None
            provider_id = row.get('id') if isinstance(row, dict) else None
            try:
                observed = canonical_time(row.get('timestamp')) if isinstance(row, dict) else None
            except (ValueError, TypeError):
                observed = None
            message = row.get('message') if isinstance(row, dict) else None
            if (labels is None or labels.get('resource') != resource or labels.get('type') != 'app' or
                    not isinstance(provider_id, str) or not ID_PATTERN.fullmatch(provider_id) or
                    observed is None or not isinstance(message, str) or len(message) > 65536):
                issue('rejected_record')
                continue
            if not actual['startTime'] <= observed <= actual['endTime']:
                issue('record_outside_query')
                continue
            if previous is not None and ((direction == 'forward' and observed < previous) or
                                         (direction == 'backward' and observed > previous)):
                issue('nonmonotonic_records')
            previous = observed
            projected = project_page({'hasMore': False, 'logs': [row]}, resource)
            events = sorted(set(match.group() for match in EVENT_PATTERN.finditer(message)))
            unknown_marker = any(match.group() not in EVENT_FIELDS for match in UNKNOWN_FAILURE.finditer(message))
            if unknown_marker:
                issue('unknown_failure_marker')
            if projected['receipts']:
                receipt = projected['receipts'][0]
                variant = {key: receipt[key] for key in ('event', 'level', 'details', 'requires_review')}
                variant.update(kind='event', observed_at=observed, unknown_marker_present=unknown_marker)
                variant['requires_review'] |= unknown_marker
                if variant['requires_review']:
                    issue('classification_requires_review')
            elif events:
                variant = {'kind': 'unprojectable_known_failure', 'known_events': events,
                           'observed_at': observed, 'unknown_marker_present': unknown_marker}
                issue('unprojectable_known_failure')
            elif unknown_marker:
                variant = {'kind': 'unknown_failure_marker', 'observed_at': observed}
            else:
                variant = {'kind': 'unrelated', 'observed_at': observed}
            key = digest(resource + '\0' + provider_id)
            existing = output['records'].get(key)
            if existing is None:
                if len(output['records']) >= MAX_IDS:
                    fail('STATE_CAPACITY')
                output['records'][key] = {'variants': [variant], 'notification_status': 'not_sent',
                                           'acknowledgment_status': 'not_received'}
            elif variant in existing['variants']:
                issue('replayed_log_id')
            else:
                if len(existing['variants']) >= MAX_VARIANTS:
                    fail('STATE_CAPACITY')
                existing['variants'].append(variant)
                issue('conflicting_log_id')
        if not page['hasMore']:
            terminal = True
            expected = None
            continue
        try:
            following = window({'startTime': page['nextStartTime'], 'endTime': page['nextEndTime']})
        except (ValueError, TypeError, KeyError):
            issue('invalid_cursor'); broken = True; expected = None
            break
        if following == actual:
            issue('cursor_stalled'); broken = True; expected = None
            break
        if ((direction == 'forward' and not (following['endTime'] == actual['endTime'] and
                actual['startTime'] < following['startTime'] < actual['endTime'])) or
                (direction == 'backward' and not (following['startTime'] == actual['startTime'] and
                actual['startTime'] < following['endTime'] < actual['endTime']))):
            issue('invalid_cursor'); broken = True; expected = None
            break
        expected = following
    if not terminal:
        issue('missing_terminal_page')
    issue('timestamp_coverage_unverified')
    # A correctly linked terminal chain is NOT a complete coverage certificate:
    # tied timestamps, moving snapshots, late arrivals and retention gaps remain.
    scan = {'window': target, 'direction': direction, 'pages_received': len(pages),
            'pages_linked': linked, 'terminal_seen': terminal,
            'chain_status': 'broken' if broken else ('linked_terminal' if terminal else 'incomplete'),
            'coverage_status': 'incomplete_timestamp_only', 'next_window': expected,
            'last_query_window': last_window, 'last_response_status': last_status,
            'last_response_has_more': last_more,
            'counts': counts}
    output['runs'] = count(output['runs'] + 1)
    output['last_scan'] = scan
    validate_state(output, resource)
    event_records = sum(any(v['kind'] != 'unrelated' for v in record['variants'])
                        for record in output['records'].values())
    report = {'format': FORMAT, 'scan': scan, 'total_unique_log_ids': len(output['records']),
              'total_marker_or_review_records': event_records, 'read_checkpoint': None,
              'total_conflicting_ids': sum(len(r['variants']) > 1 for r in output['records'].values()),
              'monitoring_status': 'not_scheduled', 'delivery_status': 'not_attempted_by_ledger',
              'human_acknowledgment': 'not_received'}
    return output, report


def pending_notifications(state, resource):
    """Pure projection for a FUTURE approved delivery adapter. Never sends.

    An uncertain item is NOT permission to retry, and a marker is not a
    confirmed incident. Validate before projecting any persisted state.
    """
    validate_state(state, resource)
    return [{'receipt_id': key, 'variants': copy.deepcopy([v for v in record['variants'] if v['kind'] != 'unrelated']),
             'requires_review': len(record['variants']) > 1 or any(
                 v['kind'] != 'event' or v.get('requires_review', False) for v in record['variants']),
             'notification_status': record['notification_status'],
             'acknowledgment_status': record['acknowledgment_status']}
            for key, record in sorted(state['records'].items())
            if any(v['kind'] != 'unrelated' for v in record['variants'])]


def load_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail()
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: fail())


def private_file(path, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1):
            fail('UNSAFE_STATE_PATH')
        raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            fail('STATE_CAPACITY')
        return load_json(raw)


def save_transaction(path, transcript):
    """Cooperative writer lock + private atomic replace. Never follow symlinks.

    The caller must supply a pre-created private directory. A stale crash lock
    stops subsequent writes; it must not be automatically deleted or stolen.
    """
    path = Path(path)
    parent = path.parent
    info = parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
            stat.S_IMODE(info.st_mode) & 0o077 or path.name in {'', '.', '..'}):
        fail('UNSAFE_STATE_PATH')
    # Refuse symlink components, not merely a symlink final parent.
    for component in (parent, *parent.parents):
        if component.is_symlink():
            fail('UNSAFE_STATE_PATH')
    lock = path.with_name(path.name + '.lock')
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    temporary = None
    try:
        try:
            state = private_file(path, MAX_STATE)
        except FileNotFoundError:
            state = None
        state, report = observe(state, transcript)
        raw = json.dumps(state, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
        if len(raw) > MAX_STATE:
            fail('STATE_CAPACITY')
        fd, temporary = tempfile.mkstemp(prefix='.ledger-', dir=parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        # No notification side effect: an uncertain response after this point can
        # safely replay the transcript and will report duplicate IDs.
        return report
    finally:
        if temporary is not None:
            os.unlink(temporary)
        os.unlink(lock)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 2 or argv[0] != '--state':
            fail()
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            fail('INPUT_TOO_LARGE')
        report = save_transaction(argv[1], load_json(raw))
    except (ValueError, TypeError, KeyError, OSError, UnicodeError, RecursionError):
        # Do not echo attacker-controlled errors, file paths or raw input.
        print(json.dumps({'error': 'LEDGER_NOT_UPDATED_OR_OUTCOME_UNCERTAIN',
                          'action': 'inspect_private_state_before_retry', 'read_checkpoint': None}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
