"""Offline common-entry boundary tests; no real credentials or database."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

from q04_entry_fixture import MemoryEvidence, approve, fake_snapshot, manifest_for
from tools.migration_entry import ContractError, _approved, _Trace, execute_q04, reconcile_q04


class MigrationEntryContractTests(unittest.TestCase):
    def setUp(self):
        self.evidence = MemoryEvidence()
        self.m = manifest_for(fake_snapshot())
        self.engine = Mock(echo=False, pool=Mock(echo=False))
        self.engine.dialect.name = 'postgresql'
        self.engine.dialect.driver = 'psycopg2'

    def test_exact_manifest_approval_and_references(self):
        raw, approval = approve(self.m, self.evidence)
        self.assertEqual(_approved(raw, approval, self.evidence), self.m)

    def test_manifest_tampering_unknown_keys_and_duplicate_keys_rejected_before_connect(self):
        raw, approval = approve(self.m, self.evidence)
        for bad in (raw+b' ', raw[:-1]+b',"unknown":1}', raw[:-1]+b',"operation":"duplicate"}'):
            with self.subTest(bad=bad[-30:]), self.assertRaises(ContractError):
                execute_q04(engine=Mock(), manifest=bad, approval=approval, evidence=self.evidence)
        self.assertEqual(self.evidence.events, [])

    def test_unapproved_baselines_target_and_version_rejected(self):
        cases = [lambda m: m.update(example_only=True),
                 lambda m: m['ledger'].update(title='請求訂正'),
                 lambda m: m['release'].update(source_commit='18ae141b'),
                 lambda m: m['release'].update(core_sha256='0'*64),
                 lambda m: m['target']['snapshot'].update(schema='public'),
                 lambda m: m['target']['snapshot'].update(database='dkss_baseline_20261029'),
                 lambda m: m['target']['snapshot'].update(isolation='serializable'),
                 lambda m: m['target']['snapshot']['tables'].pop('office'),
                 lambda m: m['target']['snapshot']['tables']['office'].update(privileges=[True,True,False,True])]
        for change in cases:
            with self.subTest(change=cases.index(change)):
                m = copy.deepcopy(self.m); change(m)
                raw, approval = approve(m, self.evidence)
                engine = Mock()
                with self.assertRaises(ContractError):
                    execute_q04(engine=engine, manifest=raw, approval=approval, evidence=self.evidence)
                engine.connect.assert_not_called()

    def test_trusted_approval_and_evidence_must_match(self):
        raw, approval = approve(self.m, self.evidence)
        for ref in (approval['approval_ref'], self.m['evidence']['T02']['ref']):
            saved = self.evidence.records[ref]
            self.evidence.records[ref] = {'tampered': True}
            with self.assertRaises(ContractError):
                _approved(raw, approval, self.evidence)
            self.evidence.records[ref] = saved

    def test_expired_and_not_started_approval(self):
        for key, value in [('window_end_utc','2000-01-01T00:00:00Z'),
                           ('window_start_utc','2099-01-01T00:00:00Z')]:
            self.m['approval'][key] = value
            raw, approval = approve(self.m, self.evidence)
            with self.assertRaises(ContractError): _approved(raw, approval, self.evidence)

    def test_claim_failure_does_not_reach_adapter(self):
        raw, approval = approve(self.m, self.evidence)
        self.evidence.fail_event = 'PENDING'
        engine = self.engine
        with patch('tools.migration_entry.apply') as adapter:
            result = execute_q04(engine=engine, manifest=raw, approval=approval, evidence=self.evidence)
        adapter.assert_not_called()
        self.assertEqual(result['failure_code'], 'ATTEMPT_CLAIM_FAILED')
        self.assertEqual(result['commit_state'], 'NOT_ATTEMPTED')

    def test_unknown_rejects_same_and_new_attempt_without_reexecution(self):
        engine = self.engine
        raw, approval = approve(self.m, self.evidence)
        with patch('tools.migration_entry.apply', side_effect=RuntimeError('secret-do-not-output')) as adapter:
            first = execute_q04(engine=engine, manifest=raw, approval=approval, evidence=self.evidence)
            self.assertEqual(first['status'], 'OUTCOME_UNKNOWN')
            for attempt in ('synthetic-1', 'synthetic-2'):
                self.m['attempt_id'] = attempt
                raw, approval = approve(self.m, self.evidence)
                result = execute_q04(engine=engine, manifest=raw, approval=approval, evidence=self.evidence)
                self.assertEqual(result['failure_code'], 'ATTEMPT_CLAIM_FAILED')
            self.assertEqual(adapter.call_count, 1)
        self.assertNotIn('secret-do-not-output', json.dumps([first, self.evidence.events]))

    def test_commit_entry_or_closed_driver_cannot_prove_rollback(self):
        driver = Mock(closed=0); driver.get_transaction_status.return_value = 0
        trace = _Trace(driver=driver, rollback_entered=True)
        self.assertTrue(trace.rollback_confirmed())
        trace.commit_entered = True
        self.assertFalse(trace.rollback_confirmed())
        trace.commit_entered = False; driver.closed = 1
        self.assertFalse(trace.rollback_confirmed())

    def test_readiness_alone_does_not_prove_commit_or_release_unknown(self):
        attempt = dict(attempt_id='synthetic-1', target_ref='synthetic-target', manifest_sha256='a'*64,
                       status='OUTCOME_UNKNOWN')
        readback = dict(target_ref=attempt['target_ref'], manifest_sha256=attempt['manifest_sha256'],
            target_verified=True, reviewer_ref='synthetic-DBA', storage_state='APPLIED_STATE_MATCH',
            attempt_commit='UNKNOWN')
        self.evidence.records['readback'] = readback
        self.evidence.busy[attempt['target_ref']] = attempt['attempt_id']
        result = reconcile_q04(attempt=attempt, readback_ref='readback', evidence=self.evidence)
        self.assertEqual(result, dict(storage_state='APPLIED_STATE_MATCH', attempt_commit='UNKNOWN', resume_allowed=False))
        self.assertIn(attempt['target_ref'], self.evidence.busy)
        readback['attempt_commit'] = 'CONFIRMED'
        with self.assertRaises(ContractError):
            reconcile_q04(attempt=attempt, readback_ref='readback', evidence=self.evidence)

    def test_sql_logging_refused(self):
        engine = self.engine; engine.echo = True
        raw, approval = approve(self.m, self.evidence)
        with self.assertRaisesRegex(ContractError, 'SQL_LOGGING'):
            execute_q04(engine=engine, manifest=raw, approval=approval, evidence=self.evidence)

    def test_persisted_final_with_lost_ack_still_blocks_next_attempt(self):
        raw, approval = approve(self.m, self.evidence)
        engine = self.engine
        append = self.evidence.append
        def lose_ack(record):
            receipt = append(record)
            if record['event_type'] == 'FINAL': raise OSError('synthetic persisted ACK loss')
            return receipt
        with patch.object(self.evidence, 'append', side_effect=lose_ack), patch(
                'tools.migration_entry.apply', return_value={'office': {'added_column': True, 'assigned': 2}}):
            result = execute_q04(engine=engine, manifest=raw, approval=approval, evidence=self.evidence)
        self.assertEqual(result['status'], 'OUTCOME_UNKNOWN')
        self.assertEqual(self.evidence.events[-1]['status'], 'APPLIED')
        self.m['attempt_id'] = 'another-attempt'
        raw, approval = approve(self.m, self.evidence)
        with patch('tools.migration_entry.apply') as adapter:
            result = execute_q04(engine=engine, manifest=raw, approval=approval, evidence=self.evidence)
            adapter.assert_not_called()
        self.assertEqual(result['failure_code'], 'ATTEMPT_CLAIM_FAILED')

    def test_reconciliation_requires_matching_transaction_proof_and_never_resumes(self):
        attempt = dict(attempt_id='synthetic-1', target_ref='synthetic-target', manifest_sha256='a'*64,
                       status='OUTCOME_UNKNOWN')
        self.evidence.records['readback'] = dict(target_ref=attempt['target_ref'],
            manifest_sha256=attempt['manifest_sha256'], target_verified=True, reviewer_ref='synthetic-DBA',
            storage_state='APPLIED_STATE_MATCH', attempt_commit='CONFIRMED', transaction_evidence_ref='proof')
        self.evidence.records['proof'] = dict(attempt_id='wrong', target_ref=attempt['target_ref'],
            manifest_sha256=attempt['manifest_sha256'], attempt_commit='CONFIRMED')
        with self.assertRaisesRegex(ContractError, 'TRANSACTION_EVIDENCE_MISMATCH'):
            reconcile_q04(attempt=attempt, readback_ref='readback', evidence=self.evidence)
        self.evidence.records['proof']['attempt_id'] = attempt['attempt_id']
        result = reconcile_q04(attempt=attempt, readback_ref='readback', evidence=self.evidence)
        self.assertEqual(result['attempt_commit'], 'CONFIRMED')
        self.assertFalse(result['resume_allowed'])
