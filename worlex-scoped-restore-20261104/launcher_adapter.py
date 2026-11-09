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
                  archive_hash, expected_archive_hash, target_hash, expected_target_hash,
                  reconciliation=None):
    """Verify no-execute proof OR explicit full reconciliation; create once only."""
    receipt = None
    if not re.fullmatch(r'[a-f0-9]{32}', attempt_id):
        raise ValueError('INVALID_ATTEMPT_ID')
    if reconciliation is not None:
        _require(type(reconciliation) is dict and set(reconciliation) == {'prior_files',
            'reconciliation_files', 'expected'}, 'RECONCILIATION_ARGUMENTS_INVALID')
        receipt = validate_reconciled_evidence(**reconciliation)
        _require(_equal(prior_result, _strict_evidence(reconciliation['prior_files']['safe-result.json'])),
                 'EXACT_UNCERTAIN_PRIOR_RESULT_REQUIRED')
        _require(attempt_id != receipt['expected_prior']['attempt_id'], 'NEW_DISTINCT_ATTEMPT_REQUIRED')
        _require(archive_hash == receipt['expected_prior']['archive_sha256']
            and target_hash == receipt['expected_prior']['target_sha256'], 'RECONCILED_INPUT_MISMATCH')
    elif (type(prior_result) is not dict or prior_result.get('restore_attempted') is not False
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
    if receipt is not None:
        _persist_reconciled_binding(destination, receipt)
    return destination

# This branch is deliberately separate from a prior no-execute stop. It never
# reclassifies the original uncertain execute as restore_attempted=False.
PRIOR_EVIDENCE_FILES = frozenset(('safe-result.json', 'private-plan.json',
    'inspect-started.json', 'inspect-finished.json', 'execute-started.json',
    'execute-finished.json', 'inspect.json', 'private-plan.json.execution.json',
    'attempt-binding.json', 'client-runtime-result.json'))
RECONCILIATION_FILES = frozenset(('00-evidence-bound.json', '10-source-verified.json',
    '20-connection-requested.json', '30-readonly-checks-complete.json', 'safe-result.json'))
BASELINE_RECONCILIATION = {'approved_plan_equal': True, 'automatic_retry': False,
    'cleanup': [], 'live_login_checked': False,
    'original_outcome_unknown_until_reconciliation': True,
    'preserved_rows_and_all_sequences_unchanged': True, 'read_only': True,
    'read_only_reconciliation_required': False, 'restore_attempted': False,
    'restore_sessions_absent_before_and_after': True,
    'status': 'RESTORE_ABSENT_APPROVED_BASELINE_UNCHANGED', 'web_resumed': False}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def _equal(actual, expected):
    return _canonical(actual) == _canonical(expected)


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _strict_evidence(raw):
    _require(type(raw) is bytes and 0 < len(raw) <= 16 * 1024 * 1024, 'EVIDENCE_BYTES_REQUIRED')
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'DUPLICATE_EVIDENCE_FIELD')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('NONFINITE_EVIDENCE_VALUE')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
    _require(type(value) is dict, 'EVIDENCE_OBJECT_REQUIRED')
    return value


def _validate_reconciliation_evidence(*, prior_files, reconciliation_files, expected, required_result):
    """Validate held byte snapshots. The pinned launcher supplies trusted pins.

    Never reads a DB, imports old executable code, alters old files, or authorizes
    a retry of the old attempt. A fresh inspect remains mandatory afterwards.
    """
    _require(type(prior_files) is dict and set(prior_files) == PRIOR_EVIDENCE_FILES,
             'COMPLETE_PRIOR_EVIDENCE_REQUIRED')
    _require(type(reconciliation_files) is dict and set(reconciliation_files) == RECONCILIATION_FILES,
             'COMPLETE_RECONCILIATION_EVIDENCE_REQUIRED')
    required = {'attempt_id', 'commit', 'policy_sha256', 'runner_sha256', 'launcher_sha256',
        'archive_sha256', 'target_sha256', 'prior_result_canonical_sha256',
        'reconciliation_result_canonical_sha256', 'reconciliation_helper_sha256'}
    _require(type(expected) is dict and set(expected) == required, 'EXACT_PRIOR_PINS_REQUIRED')
    for name, value in expected.items():
        size = 32 if name == 'attempt_id' else 40 if name == 'commit' else 64
        _require(type(value) is str and re.fullmatch('[a-f0-9]{'+str(size)+'}', value),
                 'INVALID_PRIOR_PIN')
    prior = {name: _strict_evidence(raw) for name, raw in prior_files.items()}
    checks = {name: _strict_evidence(raw) for name, raw in reconciliation_files.items()}
    failed = prior['safe-result.json']
    _require(_hash(_canonical(failed)) == expected['prior_result_canonical_sha256'],
             'EXACT_UNCERTAIN_PRIOR_RESULT_REQUIRED')
    _require(failed.get('restore_attempted', 'missing') is None
        and failed.get('automatic_retry') is False and failed.get('active_stage') == 'execute'
        and failed.get('status') == 'STOPPED_NO_RETRY'
        and failed.get('read_only_reconciliation_required') is True
        and failed.get('web_resumed') is False, 'PRIOR_UNCERTAIN_EXECUTE_REQUIRED')
    result = checks['safe-result.json']
    _require(_equal(result, required_result)
        and _hash(_canonical(result)) == expected['reconciliation_result_canonical_sha256'],
        'EXACT_FULL_BASELINE_RECONCILIATION_REQUIRED')
    bound = checks['00-evidence-bound.json']
    base = {k: BASELINE_RECONCILIATION[k] for k in ('read_only', 'restore_attempted',
        'automatic_retry', 'web_resumed', 'live_login_checked',
        'original_outcome_unknown_until_reconciliation')}
    _require(set(bound) == {'utc', 'status', 'commit', 'policy_sha256', 'bindings',
        'client_runtime_sha256', 'outer_launcher_runtime_sha256'} | set(base), 'BINDING_JOURNAL_SHAPE')
    _require(bound.get('status') == 'EXACT_FAILED_ATTEMPT_BOUND'
        and bound.get('commit') == expected['commit']
        and bound.get('policy_sha256') == expected['policy_sha256']
        and all(_equal(bound.get(k), v) for k, v in base.items()), 'BINDING_JOURNAL_MISMATCH')
    actual = {name: {'sha256': _hash(raw), 'bytes': len(raw)} for name, raw in prior_files.items()}
    _require(_equal(bound.get('bindings'), actual), 'PRIOR_EVIDENCE_CHANGED_SINCE_RECONCILIATION')
    stages = failed.get('stages')
    _require(type(stages) is list and len(stages) == 2
        and [stage.get('stage') for stage in stages] == ['inspect', 'execute'], 'EXACT_PRIOR_STAGES_REQUIRED')
    for stage in stages:
        name = stage['stage']
        _require(_equal(prior[name+'-started.json'], {'stage': name,
            'event': 'CHILD_LAUNCH_REQUESTED', 'started_utc': stage.get('started_utc'),
            'connection_attempted': None, 'automatic_retry': False}), 'PRIOR_START_MARKER_MISMATCH')
        _require(_equal(prior[name+'-finished.json'], {'stage': name,
            'exit_code': stage.get('exit_code'), 'automatic_retry': False,
            'safe_output': safe_stage_output(stage), 'execute_eligible': name == 'inspect'}),
            'PRIOR_TERMINAL_MARKER_MISMATCH')
    _require(stages[0].get('status') == 'READ_ONLY_PREFLIGHT_PASSED'
        and type(stages[0].get('exit_code')) is int and stages[0]['exit_code'] == 0
        and stages[1].get('status') == 'FAILED_OR_COMMIT_UNCERTAIN'
        and type(stages[1].get('exit_code')) is int and stages[1]['exit_code'] != 0,
        'PRIOR_STAGE_OUTCOME_MISMATCH')
    plan = prior['private-plan.json']
    _require(type(plan.get('version')) is int and plan['version'] == 4
        and plan.get('tenant') == 'WORLEX'
        and plan.get('runner_sha256') == expected['runner_sha256']
        and plan.get('archive_sha256') == expected['archive_sha256']
        and plan.get('client_runtime_sha256') == bound['client_runtime_sha256'], 'APPROVED_PLAN_BINDING_MISMATCH')
    marker = prior['private-plan.json.execution.json']
    _require(set(marker) == {'status', 'target_sha256'}
        and marker['status'] in ('STARTED_NO_RETRY', 'COMMITTED')
        and marker['target_sha256'] == plan.get('target_sha256'), 'PRIOR_EXECUTION_INTENT_REQUIRED')
    attempt = prior['attempt-binding.json']
    _require(all(_equal(attempt.get(k), v) for k, v in {
        'commit': expected['commit'], 'policy_sha256': expected['policy_sha256'],
        'launcher_sha256': expected['launcher_sha256'], 'archive_sha256': expected['archive_sha256'],
        'target_sha256': expected['target_sha256'], 'automatic_retry': False}.items()),
        'PRIOR_ATTEMPT_BINDING_MISMATCH')
    runtime = prior['client-runtime-result.json']
    _require(runtime.get('status') == 'ACTUAL_LOADED_CLIENT_VERIFIED_NO_CONNECTION'
        and runtime.get('connection_attempted') is False and type(runtime.get('runtime')) is dict
        and _hash(json.dumps(runtime['runtime'], sort_keys=True, separators=(',', ':'),
            ensure_ascii=False, allow_nan=False).encode()) == bound['outer_launcher_runtime_sha256'],
        'PRIOR_CLIENT_RUNTIME_BINDING_MISMATCH')
    journal_shapes = {
        '10-source-verified.json': {'status': 'ORIGINAL_SOURCE_VERIFIED_NO_CONNECTION'},
        '20-connection-requested.json': {'status': 'READONLY_CONNECTION_REQUESTED_ONCE'},
        '30-readonly-checks-complete.json': {'status': 'READONLY_CHECKS_COMPLETE',
            'restore_sessions_absent_before_and_after': True}}
    times = [bound.get('utc')]
    for name, shape in journal_shapes.items():
        record = checks[name]
        _require(set(record) == set(shape) | {'utc'}
            and all(_equal(record.get(k), v) for k, v in shape.items()), 'RECONCILIATION_JOURNAL_MISMATCH')
        times.append(record['utc'])
    from datetime import datetime
    try:
        _require(all(type(t) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z', t)
                     for t in times), 'RECONCILIATION_CHRONOLOGY_INVALID')
        points = [datetime.fromisoformat(t.replace('Z', '+00:00')) for t in times]
        finished = datetime.fromisoformat(stages[1]['finished_utc'].replace('Z', '+00:00'))
        _require(finished <= points[0] and points == sorted(points), 'RECONCILIATION_CHRONOLOGY_INVALID')
    except (TypeError, KeyError):
        raise ValueError('RECONCILIATION_CHRONOLOGY_INVALID') from None
    return {'status': ('PRIOR_UNCERTAIN_EXECUTE_RECONCILED_BASELINE_UNCHANGED'
        if _equal(required_result, BASELINE_RECONCILIATION)
        else 'PRIOR_UNCERTAIN_EXECUTE_RECONCILED_PRESENT_VERIFIED_NO_EXECUTE'),
        'prior_restore_attempted': None, 'prior_result_unchanged': True,
        'reconciliation_read_only': True, 'automatic_retry': False,
        'expected_prior': dict(expected), 'prior_files': actual,
        'reconciliation_files': {name: {'sha256': _hash(raw), 'bytes': len(raw)}
                                 for name, raw in reconciliation_files.items()}}


def _persist_reconciled_binding(destination, receipt):
    path = destination / 'prior-reconciliation-binding.json'
    raw = _canonical(receipt)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        _require(stream.write(raw) == len(raw), 'RECONCILIATION_BINDING_SHORT_WRITE')
        stream.flush()
        os.fsync(stream.fileno())
    _require(path.read_bytes() == raw, 'RECONCILIATION_BINDING_READBACK_MISMATCH')


PRESENT_RECONCILIATION = {'status': 'RESTORE_PRESENT_MATCHES_APPROVED_PLAN',
    'imported_rows': 4099, 'deferred_rows': 1,
    'values_blobs_required_settings_and_sequences_verified': True,
    'restore_sessions_absent_before_and_after': True, 'cleanup': [],
    'read_only': True, 'restore_attempted': False, 'automatic_retry': False,
    'web_resumed': False, 'live_login_checked': False,
    'original_outcome_unknown_until_reconciliation': True,
    'read_only_reconciliation_required': False}


def validate_reconciled_evidence(*, prior_files, reconciliation_files, expected):
    """The existing write-attempt boundary remains strictly absence-only."""
    return _validate_reconciliation_evidence(prior_files=prior_files,
        reconciliation_files=reconciliation_files, expected=expected,
        required_result=BASELINE_RECONCILIATION)


def classify_completed_reconciliation(child_exit_code, result_bytes):
    """Zero is required before reading any positive, potentially stale record.

    The caller must invoke the exact reviewed read-only child once. Its exit 0
    occurs only after durable output, successful SafeFS close and final prints.
    This pure classifier never starts a connection, child, inspect or execute.
    """
    _require(type(child_exit_code) is int and child_exit_code == 0,
        'READONLY_CHILD_NOT_COMPLETED_NO_EXECUTE')
    result = _strict_evidence(result_bytes)
    if _equal(result, BASELINE_RECONCILIATION):
        return 'ABSENT_BASELINE_EXACT_NEW_INSPECT_REQUIRED'
    if _equal(result, PRESENT_RECONCILIATION):
        return 'PRESENT_EXACT_NO_NEW_RESTORE'
    raise ValueError('READONLY_OUTCOME_UNRESOLVED_NO_EXECUTE')


def validate_completed_reconciliation(*, child_exit_code, prior_files,
                                      reconciliation_files, expected):
    """Readonly completion API. Present never satisfies begin_attempt()."""
    _require(type(child_exit_code) is int and child_exit_code == 0,
        'READONLY_CHILD_NOT_COMPLETED_NO_EXECUTE')
    _require(type(reconciliation_files) is dict and set(reconciliation_files) == RECONCILIATION_FILES,
        'COMPLETE_RECONCILIATION_EVIDENCE_REQUIRED')
    classification = classify_completed_reconciliation(child_exit_code, reconciliation_files['safe-result.json'])
    # The launcher pins the two allowed schemas, not a predicted live outcome.
    # Never rewrite result bytes or original restore_attempted:null to fabricate
    # absence. Only the expected schema's canonical digest differs for present.
    _require(type(expected) is dict and expected.get('reconciliation_result_canonical_sha256')
        == _hash(_canonical(BASELINE_RECONCILIATION)), 'PINNED_ABSENCE_SCHEMA_REQUIRED')
    required = (BASELINE_RECONCILIATION if classification == 'ABSENT_BASELINE_EXACT_NEW_INSPECT_REQUIRED'
                else PRESENT_RECONCILIATION)
    selected_expected = dict(expected)
    selected_expected['reconciliation_result_canonical_sha256'] = _hash(_canonical(required))
    receipt = _validate_reconciliation_evidence(prior_files=prior_files,
        reconciliation_files=reconciliation_files, expected=selected_expected, required_result=required)
    return {'classification': classification, 'evidence': receipt}
