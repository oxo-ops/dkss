"""Run original-recovery fault tests in isolated Python processes.

The helper uses current checkout source/models and only in-memory SQLite;
process isolation prevents temporary module/socket fixtures affecting the suite.
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tests' / 'source_recovery_fault_probe.py'

class SourceRecoveryFaultTests(unittest.TestCase):
    def probe(self, case):
        env = {key: os.environ[key] for key in (
            'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL'
        ) if key in os.environ}
        result = subprocess.run(
            [sys.executable, '-I', '-B', str(PROBE), 'RecoveryFaults.' + case],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Ran 1 test', result.stderr)
        self.assertIn('OK', result.stderr)

    def test_corrupt_first_source_rejects_without_row_mutation(self):
        self.probe('test_corrupt_first_source_rejects_without_row_mutation')

    def test_missing_first_source_rejects_without_row_mutation(self):
        self.probe('test_missing_first_source_rejects_without_row_mutation')

    def test_later_corruption_preserves_committed_prefix_then_resumes(self):
        self.probe('test_later_corruption_preserves_committed_prefix_then_resumes')

    def test_other_company_source_cannot_rescue_missing_original(self):
        self.probe('test_other_company_source_cannot_rescue_missing_original')

    def test_deleted_corrupt_source_does_not_block_remaining_recovery(self):
        self.probe('test_deleted_corrupt_source_does_not_block_remaining_recovery')

    def test_commit_interruption_does_not_falsely_restore_current_row(self):
        self.probe('test_commit_interruption_does_not_falsely_restore_current_row')
