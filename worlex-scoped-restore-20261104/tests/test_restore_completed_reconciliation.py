"""Pure completed-readonly transition tests. No DB or subprocess execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import launcher_adapter as A
import test_restore_reconciled_attempt as fixtures
fixture = fixtures.fixture


def completed(present=False):
    value=fixture()
    if present:value['reconciliation_files']['safe-result.json']=A._canonical(A.PRESENT_RECONCILIATION)
    return value


class CompletedReconciliationTests(unittest.TestCase):
    def test_absent_exact_requires_new_inspection_and_preserves_all_bytes(self):
        f=completed();before=copy.deepcopy(f)
        result=A.validate_completed_reconciliation(child_exit_code=0,**f)
        self.assertEqual(result['classification'],'ABSENT_BASELINE_EXACT_NEW_INSPECT_REQUIRED')
        self.assertIsNone(result['evidence']['prior_restore_attempted']);self.assertEqual(before,f)
        with tempfile.TemporaryDirectory() as tmp:
            fixtures.ReconciledAttemptTests().begin(tmp,f)

    def test_present_exact_never_authorizes_existing_begin_attempt(self):
        f=completed(True);before=copy.deepcopy(f)
        result=A.validate_completed_reconciliation(child_exit_code=0,**f)
        self.assertEqual(result['classification'],'PRESENT_EXACT_NO_NEW_RESTORE')
        self.assertEqual(result['evidence']['status'],'PRIOR_UNCERTAIN_EXECUTE_RECONCILED_PRESENT_VERIFIED_NO_EXECUTE')
        self.assertIsNone(result['evidence']['prior_restore_attempted']);self.assertEqual(before,f)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):fixtures.ReconciledAttemptTests().begin(tmp,f)
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_nonzero_unknown_and_wrong_type_exit_refuse_stale_positive_before_parse(self):
        for code in (1,2,3,-1,None,False,True,0.0,'0'):
            for present in (False,True):
                with self.subTest(code=code,present=present),patch.object(A,'_strict_evidence',side_effect=AssertionError('must not parse stale proof')):
                    with self.assertRaisesRegex(ValueError,'READONLY_CHILD_NOT_COMPLETED'):
                        A.validate_completed_reconciliation(child_exit_code=code,**completed(present))

    def test_partial_duplicate_nonfinite_and_missing_result_refuse(self):
        for raw in (b'{',b'{"status":1,"status":2}',b'{"x":NaN}',b'[]',b''):
            f=completed();f['reconciliation_files']['safe-result.json']=raw
            with self.subTest(raw=raw),self.assertRaises(ValueError):A.validate_completed_reconciliation(child_exit_code=0,**f)
        f=completed();del f['reconciliation_files']['safe-result.json']
        with self.assertRaises(ValueError):A.validate_completed_reconciliation(child_exit_code=0,**f)

    def test_mixed_unknown_cleanup_or_incomplete_result_refuses(self):
        for present in (False,True):
            for key,value in [('cleanup',[{'operation':'close'}]),('read_only_reconciliation_required',True),
                ('restore_sessions_absent_before_and_after',False),('restore_attempted',True),('read_only',0),
                ('status','RECONCILIATION_UNRESOLVED_STOP'),('extra',True)]:
                f=completed(present);data=json.loads(f['reconciliation_files']['safe-result.json']);data[key]=value
                f['reconciliation_files']['safe-result.json']=A._canonical(data)
                with self.subTest(present=present,key=key),self.assertRaises(ValueError):A.validate_completed_reconciliation(child_exit_code=0,**f)

    def test_every_present_result_required_field_is_required(self):
        for key in A.PRESENT_RECONCILIATION:
            f=completed(True);result=dict(A.PRESENT_RECONCILIATION);del result[key]
            f['reconciliation_files']['safe-result.json']=A._canonical(result)
            with self.subTest(key=key),self.assertRaises(ValueError):A.validate_completed_reconciliation(child_exit_code=0,**f)

    def test_all_original_and_proof_files_required_for_both_outcomes(self):
        for present in (False,True):
            for group in ('prior_files','reconciliation_files'):
                for name in completed(present)[group]:
                    f=completed(present);del f[group][name]
                    with self.subTest(present=present,group=group,name=name),self.assertRaises(ValueError):
                        A.validate_completed_reconciliation(child_exit_code=0,**f)

    def test_present_branch_rejects_modified_prior_and_journal_bindings(self):
        for name in completed(True)['prior_files']:
            f=completed(True);f['prior_files'][name]+=b' '
            with self.subTest(name=name),self.assertRaises(ValueError):A.validate_completed_reconciliation(child_exit_code=0,**f)
        f=completed(True);f['reconciliation_files']['30-readonly-checks-complete.json']=b'{}'
        with self.assertRaises(ValueError):A.validate_completed_reconciliation(child_exit_code=0,**f)

    def test_unbound_expected_schema_cannot_authorize_transition(self):
        for present in (False,True):
            f=completed(present);f['expected']['reconciliation_result_canonical_sha256']='0'*64
            with self.assertRaises(ValueError):A.validate_completed_reconciliation(child_exit_code=0,**f)

    def test_cannot_inject_present_mode_into_begin_attempt(self):
        f=completed(True);f['required_result']=A.PRESENT_RECONCILIATION
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError):fixtures.ReconciledAttemptTests().begin(tmp,f)
