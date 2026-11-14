"""Offline projection of authorized Render log pages. No network, DB, or delivery.

This is a read-only preparation tool, not a running monitor or an incident system.
Never copy raw log messages, provider IDs, labels, or exception text to its output.
"""
import hashlib
import json
import re
import sys
from datetime import datetime

EVENT_FIELDS = {
    'UPLOAD_DELETE_FAILED': {
        'backend': {'s3', 'local'}, 'error_type': {'ClientError', 'OSError'}},
    'EMAIL_DELIVERY_FAILED': {
        'purpose': {'notification', 'email_change', 'unknown'},
        'stage': {'connect', 'starttls', 'authenticate', 'send', 'close', 'unknown'},
        'error_type': {'authentication', 'recipient_refused', 'sender_refused',
            'data_rejected', 'tls', 'connection', 'smtp', 'unexpected'}},
    'WEB_PUSH_SEND_FAILED': {'error_type': {'provider', 'unexpected'}},
    'DOCUMENT_IMPORT_FAILED': {
        'mode': {'form', 'progress', 'unknown'},
        'stage': {'extract', 'process', 'persist', 'unknown'},
        'error_type': {'input', 'runtime', 'database', 'unexpected'}},
    'INVOICE_REVIEW_FAILED': {
        'action': {'already_recorded', 'initial_cost', 'additional_cost',
            'correction', 'parts_review', 'unknown'},
        'error_type': {'integrity', 'operational', 'data', 'statement',
            'database', 'unexpected'}},
}
EVENT_PATTERN = re.compile(r'(?<![A-Za-z0-9_])(' + '|'.join(EVENT_FIELDS) + r')(?![A-Za-z0-9_])')
ID_PATTERN = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
TIME_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})\Z')
LEVELS = {'debug', 'info', 'warning', 'warn', 'error', 'fatal'}


def labels_of(record):
    labels = record.get('labels')
    if not isinstance(labels, list):
        return None
    result = {}
    for value in labels:
        if not isinstance(value, dict):
            return None
        name, item = value.get('name'), value.get('value')
        if not isinstance(name, str) or not isinstance(item, str) or name in result:
            return None
        result[name] = item
    return result


def valid_timestamp(value):
    if not isinstance(value, str) or not TIME_PATTERN.fullmatch(value):
        return False
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None
    except ValueError:
        return False


def project_page(page, expected_resource):
    """Return bounded, sanitized records; hasMore never becomes success/zero proof.

    IDs identify provider log records, not users, documents, incidents or deliveries.
    Duplicate/conflicting records are surfaced. There is no automatic retry/action.
    """
    if (not isinstance(page, dict) or type(page.get('hasMore')) is not bool
            or not isinstance(page.get('logs'), list) or len(page['logs']) > 1000
            or not isinstance(expected_resource, str)
            or not re.fullmatch(r'srv-[a-z0-9]{8,64}', expected_resource)):
        raise ValueError('INVALID_LOG_PAGE')
    receipts, by_id = [], {}
    counters = dict(unrelated=0, rejected=0, duplicate=0, conflicting=0)
    for record in page['logs']:
        if not isinstance(record, dict):
            counters['rejected'] += 1
            continue
        labels = labels_of(record)
        if labels is None or labels.get('resource') != expected_resource or labels.get('type') != 'app':
            counters['rejected'] += 1
            continue
        message = record.get('message')
        if not isinstance(message, str) or len(message) > 65536:
            counters['rejected'] += 1
            continue
        matches = list(EVENT_PATTERN.finditer(message))
        if not matches:
            counters['unrelated'] += 1
            continue
        provider_id, timestamp = record.get('id'), record.get('timestamp')
        if (len(matches) != 1 or not isinstance(provider_id, str)
                or not ID_PATTERN.fullmatch(provider_id) or not valid_timestamp(timestamp)):
            counters['rejected'] += 1
            continue
        event = matches[0].group(0)
        # Only exact enum values are emitted. Unknown/malformed values do not hide
        # a known failure; they require review without copying the unsafe text.
        tail = message[matches[0].end():]
        details, requires_review = {}, bool(re.search(r'[\x00-\x1f\x7f]', tail))
        for key, allowed in EVENT_FIELDS[event].items():
            values = re.findall(r'(?<!\S)' + re.escape(key) + r'=([^\s]+)', tail)
            if len(values) == 1 and values[0] in allowed and not requires_review:
                details[key] = values[0]
            else:
                details[key] = 'unverified'
                requires_review = True
        receipt_id = hashlib.sha256((expected_resource + '\0' + provider_id).encode()).hexdigest()
        value = {'receipt_id': receipt_id, 'event': event, 'observed_at': timestamp,
            'service': 'dkss-web', 'level': labels.get('level') if labels.get('level') in LEVELS else 'unverified',
            'details': details, 'requires_review': requires_review,
            'notification_status': 'not_sent', 'acknowledgment_status': 'not_received'}
        if receipt_id in by_id:
            if by_id[receipt_id] == value:
                counters['duplicate'] += 1
            else:
                counters['conflicting'] += 1
            continue
        by_id[receipt_id] = value
        receipts.append(value)
    # A terminal page does not prove preceding pages were fetched. This function
    # receives one page only and cannot attest to an entire time window.
    return {'format': 'q09-read-only-receipts-v1', 'page_has_more': page['hasMore'],
        'page_chain_status': 'not_verified', 'coverage_requires_review': True,
        'counts': counters, 'receipts': receipts,
        'monitoring_status': 'not_scheduled', 'delivery_status': 'not_attempted'}


def main():
    try:
        raw = sys.stdin.buffer.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError('INPUT_TOO_LARGE')
        payload = json.loads(raw)
        result = project_page(payload['page'], payload['expected_resource'])
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        print(json.dumps({'error': 'INVALID_INPUT'}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
