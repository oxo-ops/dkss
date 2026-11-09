"""Offline exact evidence tests. Synthetic data only, no database or subprocess."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import launcher_adapter as A
from inspect_observation import Observation


def fixture():
    expected = {name: 'a'*64 for name in ('policy_sha256', 'runner_sha256', 'launcher_sha256',
        'archive_sha256', 'target_sha256', 'prior_result_canonical_sha256',
        'reconciliation_result_canonical_sha256', 'reconciliation_helper_sha256')}
    expected.update(attempt_id='b'*32, commit='c'*40)
    with tempfile.TemporaryDirectory() as obsdir:
        obs = Observation(obsdir).value
    obs.update(inspection_completed=True, startup_completed=True, tls_completed=True)
    stages = [{'stage': 'inspect', 'status': 'READ_ONLY_PREFLIGHT_PASSED', 'exit_code': 0,
        'observation': obs, 'live_changes': False, 'started_utc': '2026-11-09T01:00:00.000Z',
        'finished_utc': '2026-11-09T01:01:00.000Z'},
        {'stage': 'execute', 'status': 'FAILED_OR_COMMIT_UNCERTAIN', 'exit_code': 3,
        'started_utc': '2026-11-09T01:02:00.000Z', 'finished_utc': '2026-11-09T01:03:00.000Z'}]
    failed = {'status': 'STOPPED_NO_RETRY', 'restore_attempted': None, 'automatic_retry': False,
        'active_stage': 'execute', 'web_resumed': False, 'read_only_reconciliation_required': True,
        'stages': stages}
    plan = {'version': 4, 'tenant': 'WORLEX', 'runner_sha256': expected['runner_sha256'],
        'archive_sha256': expected['archive_sha256'], 'client_runtime_sha256': 'd'*64,
        'target_sha256': 'e'*64}
    runtime = {'pinned': True}
    prior = {'safe-result.json': failed, 'private-plan.json': plan,
        'inspect.json': {'target_sha256': plan['target_sha256']},
        'private-plan.json.execution.json': {'status': 'STARTED_NO_RETRY', 'target_sha256': plan['target_sha256']},
        'attempt-binding.json': {k: expected[k] for k in ('commit', 'policy_sha256', 'launcher_sha256', 'archive_sha256', 'target_sha256')},
        'client-runtime-result.json': {'status': 'ACTUAL_LOADED_CLIENT_VERIFIED_NO_CONNECTION',
            'connection_attempted': False, 'runtime': runtime}}
    prior['attempt-binding.json']['automatic_retry'] = False
    for stage in stages:
        name = stage['stage']
        prior[name+'-started.json'] = {'stage': name, 'event': 'CHILD_LAUNCH_REQUESTED',
            'started_utc': stage['started_utc'], 'connection_attempted': None, 'automatic_retry': False}
        prior[name+'-finished.json'] = {'stage': name, 'exit_code': stage['exit_code'],
            'automatic_retry': False, 'safe_output': A.safe_stage_output(stage), 'execute_eligible': name == 'inspect'}
    p = {k: A._canonical(v) for k, v in prior.items()}
    r = {'safe-result.json': copy.deepcopy(A.BASELINE_RECONCILIATION),
        '00-evidence-bound.json': {'utc': '2026-11-09T02:00:00.000Z',
            'status': 'EXACT_FAILED_ATTEMPT_BOUND', 'commit': expected['commit'],
            'policy_sha256': expected['policy_sha256'], 'bindings': {
                k: {'sha256': A._hash(v), 'bytes': len(v)} for k, v in p.items()},
            'client_runtime_sha256': 'd'*64, 'outer_launcher_runtime_sha256': A._hash(A._canonical(runtime)),
            **{k: A.BASELINE_RECONCILIATION[k] for k in ('read_only', 'restore_attempted',
                'automatic_retry', 'web_resumed', 'live_login_checked', 'original_outcome_unknown_until_reconciliation')}},
        '10-source-verified.json': {'utc': '2026-11-09T02:01:00.000Z', 'status': 'ORIGINAL_SOURCE_VERIFIED_NO_CONNECTION'},
        '20-connection-requested.json': {'utc': '2026-11-09T02:02:00.000Z', 'status': 'READONLY_CONNECTION_REQUESTED_ONCE'},
        '30-readonly-checks-complete.json': {'utc': '2026-11-09T02:03:00.000Z', 'status': 'READONLY_CHECKS_COMPLETE', 'restore_sessions_absent_before_and_after': True}}
    expected['prior_result_canonical_sha256'] = A._hash(A._canonical(failed))
    expected['reconciliation_result_canonical_sha256'] = A._hash(A._canonical(r['safe-result.json']))
    return {'prior_files': p, 'reconciliation_files': {k: A._canonical(v) for k, v in r.items()}, 'expected': expected}


def mutate(f, group, name, key, value):
    data = json.loads(f[group][name]); data[key] = value
    f[group][name] = A._canonical(data)


class ReconciledAttemptTests(unittest.TestCase):
    def begin(self, root, f, **changes):
        args = dict(attempt_id='f'*32, prior_result=json.loads(f['prior_files'].get('safe-result.json', b'{}')),
            active_hashes={'core': '1'*64}, expected_hashes={'core': '1'*64},
            archive_hash='a'*64, expected_archive_hash='a'*64,
            target_hash='a'*64, expected_target_hash='a'*64, reconciliation=f)
        return A.begin_attempt(root, **{**args, **changes})

    def test_exact_evidence_preserves_original_uncertainty(self):
        f = fixture(); before = copy.deepcopy(f)
        receipt = A.validate_reconciled_evidence(**f)
        self.assertIsNone(receipt['prior_restore_attempted']); self.assertEqual(f, before)
        with tempfile.TemporaryDirectory() as tmp:
            path = self.begin(tmp, f)
            self.assertEqual(json.loads((path/'prior-reconciliation-binding.json').read_bytes()), receipt)

    def test_missing_or_extra_evidence_fails_before_attempt(self):
        for group in ('prior_files', 'reconciliation_files'):
            for name in fixture()[group]:
                f = fixture(); del f[group][name]
                with self.subTest(group=group, name=name), tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(ValueError): self.begin(tmp, f)
                    self.assertEqual(list(Path(tmp).iterdir()), [])
            f = fixture(); f[group]['extra.json'] = b'{}'
            with self.assertRaises(ValueError): A.validate_reconciled_evidence(**f)

    def test_duplicate_json_fields_and_partial_json_rejected(self):
        for group in ('prior_files', 'reconciliation_files'):
            for name in fixture()[group]:
                for raw in (b'{"status":null,"status":true}', b'{', b'{} trailing', b'{"x":NaN}', b'[]'):
                    f = fixture(); f[group][name] = raw
                    with self.subTest(group=group, name=name, raw=raw), self.assertRaises(ValueError):
                        A.validate_reconciled_evidence(**f)

    def test_any_prior_bytes_mutation_breaks_reconciliation_binding(self):
        for name in fixture()['prior_files']:
            f = fixture(); f['prior_files'][name] += b' '
            with self.subTest(name=name), self.assertRaises(ValueError): A.validate_reconciled_evidence(**f)

    def test_baseline_flags_missing_false_wrong_type_or_extra_rejected(self):
        for key, value in A.BASELINE_RECONCILIATION.items():
            for change in (None, 0, 'true', False if value is True else True):
                f = fixture(); mutate(f, 'reconciliation_files', 'safe-result.json', key, change)
                with self.subTest(key=key, change=change), self.assertRaises(ValueError): A.validate_reconciled_evidence(**f)
        f = fixture(); mutate(f, 'reconciliation_files', 'safe-result.json', 'extra', True)
        with self.assertRaises(ValueError): A.validate_reconciled_evidence(**f)

    def test_prior_false_cannot_replace_historical_null(self):
        f = fixture(); mutate(f, 'prior_files', 'safe-result.json', 'restore_attempted', False)
        with self.assertRaises(ValueError): A.validate_reconciled_evidence(**f)
        f = fixture()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            self.begin(tmp, f, prior_result={'restore_attempted': False, 'automatic_retry': False, 'status': 'STOPPED_NO_RETRY'})

    def test_changed_expected_hashes_rejected(self):
        for key in ('prior_result_canonical_sha256', 'reconciliation_result_canonical_sha256',
                    'commit', 'policy_sha256', 'runner_sha256', 'launcher_sha256', 'archive_sha256', 'target_sha256'):
            f = fixture(); f['expected'][key] = '0' * len(f['expected'][key])
            with self.subTest(key=key), self.assertRaises(ValueError): A.validate_reconciled_evidence(**f)

    def test_journal_incomplete_cleanup_and_wrong_order_rejected(self):
        for name in ('00-evidence-bound.json', '10-source-verified.json', '20-connection-requested.json', '30-readonly-checks-complete.json'):
            for key, value in (('utc', '2025-01-01T00:00:00.000Z'), ('cleanup', []), ('status', 'PARTIAL')):
                f = fixture(); mutate(f, 'reconciliation_files', name, key, value)
                with self.subTest(name=name, key=key), self.assertRaises(ValueError): A.validate_reconciled_evidence(**f)

    def test_new_distinct_attempt_and_duplicate_invocation(self):
        f = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): self.begin(tmp, f, attempt_id=f['expected']['attempt_id'])
            self.begin(tmp, f)
            with self.assertRaises(FileExistsError): self.begin(tmp, f)

    def test_active_source_archive_and_target_changes_rejected(self):
        for change in ({'active_hashes': {}}, {'archive_hash': '2'*64}, {'target_hash': '2'*64}, {'attempt_id': '../escape'}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError): self.begin(tmp, fixture(), **change)

    def test_partial_binding_persistence_poisoned_attempt_not_retried(self):
        f = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            with patch('launcher_adapter.os.fsync', side_effect=OSError('injected')):
                with self.assertRaises(OSError): self.begin(tmp, f)
            self.assertTrue((Path(tmp)/('f'*32)).is_dir())
            with self.assertRaises(FileExistsError): self.begin(tmp, f)

    def test_old_begin_attempt_does_not_accept_uncertain_without_reconciliation(self):
        f = fixture()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError): self.begin(tmp, f, reconciliation=None)

    def test_nonascii_outer_runtime_uses_exact_core_digest(self):
        f = fixture()
        data = json.loads(f['prior_files']['client-runtime-result.json'])
        data['runtime']['fixture_path'] = 'C:/Users/試験'
        f['prior_files']['client-runtime-result.json'] = A._canonical(data)
        journal = json.loads(f['reconciliation_files']['00-evidence-bound.json'])
        raw = f['prior_files']['client-runtime-result.json']
        journal['bindings']['client-runtime-result.json'] = {'sha256': A._hash(raw), 'bytes': len(raw)}
        journal['outer_launcher_runtime_sha256'] = A._hash(json.dumps(data['runtime'], sort_keys=True,
            separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode())
        f['reconciliation_files']['00-evidence-bound.json'] = A._canonical(journal)
        A.validate_reconciled_evidence(**f)
