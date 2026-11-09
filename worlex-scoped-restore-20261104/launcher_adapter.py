"""Reviewed local launcher boundary. No database, subprocess, or retry operations.

A release launcher must call persist_stage before allowing the next stage. This
adapter is part of the tested artifact map, not a post-CI source rewrite.
"""
import json
import os
from pathlib import Path
import re
from inspect_observation import launcher_observation, TYPES

SUCCESS_FLAGS = ('imported_values_and_blobs_match', 'deferred_source_not_imported',
    'push_subscription_rows_unchanged', 'push_subscription_sequence_unchanged',
    'required_settings_and_preserved_rows_unchanged')


def safe_stage_output(parsed):
    if type(parsed) is not dict:
        raise ValueError('INVALID_STAGE_OUTPUT')
    safe = launcher_observation(parsed)
    vocabulary = {
        'status': {'READ_ONLY_PREFLIGHT_PASSED', 'FAILED_OR_COMMIT_UNCERTAIN',
                   'STOPPED', 'COMMITTED', 'RESTORE_PRESENT_MATCHES_PLAN'},
        'reason': {'CLIENT_RUNTIME_CHANGED_SINCE_INSPECT', 'PLAN_ALREADY_EXISTS',
                   'REPORT_ALREADY_EXISTS', 'PREFLIGHT_PLAN_CHANGED', 'INSPECT_OPERATION_FAILED'},
        'error_type': TYPES,
    }
    for key, allowed in vocabulary.items():
        value = parsed.get(key)
        if type(value) is str and value in allowed:
            safe[key] = value
    for key in (*SUCCESS_FLAGS, 'live_changes', 'read_only', 'sequence_positions_safe',
                'owner_bindings_quarantined'):
        if type(parsed.get(key)) is bool:
            safe[key] = parsed[key]
    return safe


def persist_stage(directory, parsed, *, stage, exit_code):
    if stage not in ('inspect', 'execute', 'verify') or type(exit_code) is not int:
        raise ValueError('INVALID_STAGE_ENVELOPE')
    safe = safe_stage_output(parsed)
    if stage == 'inspect' and 'observation' not in safe:
        raise ValueError('INSPECT_OBSERVATION_REQUIRED')
    eligible = False
    if stage == 'inspect' and exit_code == 0:
        observed = safe['observation']
        if not (safe.get('status') == 'READ_ONLY_PREFLIGHT_PASSED'
                and safe.get('live_changes') is False
                and observed['inspection_completed'] is True
                and observed['startup_completed'] is True
                and observed['tls_completed'] is True
                and observed['primary'] is None and observed['cleanup'] == []):
            raise ValueError('INSPECT_COMPLETION_REQUIRED')
        eligible = True
    record = {'stage': stage, 'exit_code': exit_code, 'automatic_retry': False,
              'safe_output': safe, 'execute_eligible': eligible}

    # Exclusive creation prevents stale attempt/result reuse. A failed or partial
    # write raises, leaving no successful return that could authorize execution.
    path = Path(directory) / (stage + '-finished.json')
    data = json.dumps(record, sort_keys=True, allow_nan=False).encode()
    if len(data) > 65536:
        raise ValueError('STAGE_RESULT_TOO_LARGE')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    saved = json.loads(path.read_bytes())
    if saved != record:
        raise ValueError('STAGE_PERSISTENCE_MISMATCH')
    return saved


def begin_attempt(root, attempt_id, prior_result, *, active_hashes, expected_hashes,
                  archive_hash, expected_archive_hash, target_hash, expected_target_hash):
    """Verify immediate prior no-execute stop and active inputs, never old trees."""
    if not re.fullmatch(r'[a-f0-9]{32}', attempt_id):
        raise ValueError('INVALID_ATTEMPT_ID')
    if (type(prior_result) is not dict or prior_result.get('restore_attempted') is not False
            or prior_result.get('automatic_retry') is not False
            or prior_result.get('status') != 'STOPPED_NO_RETRY'):
        raise ValueError('PRIOR_NO_EXECUTE_PROOF_REQUIRED')
    if not expected_hashes or active_hashes != expected_hashes:
        raise ValueError('ACTIVE_CODE_MISMATCH')
    for actual, expected in ((archive_hash, expected_archive_hash), (target_hash, expected_target_hash)):
        if type(expected) is not str or not re.fullmatch('[a-f0-9]{64}', expected) or actual != expected:
            raise ValueError('ACTIVE_INPUT_MISMATCH')
    destination = Path(root) / attempt_id
    destination.mkdir(mode=0o700)  # exclusive, contains no inherited plan
    return destination
