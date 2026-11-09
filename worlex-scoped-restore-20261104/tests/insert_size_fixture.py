"""Generated public-size envelope, never a reproduction of private source data.

Only aggregate sizes are retained: 4,100 source rows, 24 bytea values totaling
15,189,518 bytes, and 60,968,018 pg8000 encoded parameter bytes (including four-byte lengths) after push deferral.
The distribution is deliberately synthetic; it is not production row content.
"""
import hashlib

from pg8000.converters import PY_TYPES, make_param
from synthetic_fixture import fixture as small_fixture
from test_restore_unit import policy_metadata
from worlex_restore import DEFERRED_SOURCE_ROWS, defer_push_subscription, typed_payload

RAW_BLOB_BYTES = 15_189_518
ENCODED_VALUE_BYTES = 60_968_018
OPERATION_BLOB_BYTES = 2_864_812


def encoded_bytes(value):
    encoded = make_param(PY_TYPES, value)
    return 4 if encoded is None else 4 + len(encoded.encode('utf-8'))


def payload_stats(typed):
    blobs = [value for rows in typed.values() for row in rows
             for value in row.values() if isinstance(value, bytes)]
    return {'source_rows': 4100, 'imported_rows': sum(map(len, typed.values())),
            'blob_values': len(blobs), 'blob_bytes': sum(map(len, blobs)),
            'encoded_parameter_bytes': sum(encoded_bytes(value)
                for rows in typed.values() for row in rows for value in row.values())}


def fixture(policy, table_names):
    data, columns, counts = small_fixture(policy, table_names)
    remaining = RAW_BLOB_BYTES - 5 * OPERATION_BLOB_BYTES
    quotient, remainder = divmod(remaining, 19)
    for name in ('vehicle_operation_import_draft', 'vehicle_document_import_draft'):
        for i, row in enumerate(data[name]):
            size = OPERATION_BLOB_BYTES if name == 'vehicle_operation_import_draft' else quotient + (i < remainder)
            marker = ('SYNTHETIC-NONPRIVATE-' + name + '-' + str(i) + '\n').encode()
            blob = (marker * ((size + len(marker) - 1) // len(marker)))[:size]
            row['source_file'] = '\\x' + blob.hex()
            if 'source_sha256' in row:
                row['source_sha256'] = hashlib.sha256(blob).hexdigest()
    # Determine padding independently through the pinned driver's public value
    # conversion; generated UUID content varies, but its byte length does not.
    typed, _ = typed_payload(data, columns, policy_metadata(policy), counts)
    defer_push_subscription(typed, DEFERRED_SOURCE_ROWS)
    padding = ENCODED_VALUE_BYTES - payload_stats(typed)['encoded_parameter_bytes']
    rows = data['vehicle_operation_record']
    quotient, remainder = divmod(padding, len(rows))
    if quotient < 2:
        raise AssertionError('Synthetic envelope has insufficient padding budget')
    for i, row in enumerate(rows):
        # JSON whitespace is valid and changes no synthetic record semantics.
        row['source_row_json'] += ' ' * (quotient + (i < remainder))
    return data, columns, counts
