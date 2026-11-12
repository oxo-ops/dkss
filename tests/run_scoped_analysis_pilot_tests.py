"""Finite stdlib-only acceptance with all network/process creation denied."""
from pathlib import Path
import sys
import unittest
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def guard(event, args):
    if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.fork', 'os.exec'}:
        raise RuntimeError('SCOPED_ANALYSIS_TEST_EXTERNAL_IO_FORBIDDEN')


sys.addaudithook(guard)
for probe in (lambda: socket.socket(), lambda: subprocess.Popen([sys.executable, '-c', 'pass'])):
    try:
        probe()
    except RuntimeError as error:
        if str(error) != 'SCOPED_ANALYSIS_TEST_EXTERNAL_IO_FORBIDDEN':
            raise
    else:
        raise RuntimeError('EXTERNAL_IO_GUARD_NOT_ACTIVE')
sys.path.insert(0, str(ROOT / 'tests'))
suite = unittest.defaultTestLoader.loadTestsFromNames(['test_scoped_analysis_pilot', 'test_scoped_analysis_adapter', 'test_scoped_analysis_ledger', 'test_scoped_analysis_final_gate'])
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() and result.testsRun >= 35 and not result.skipped else 1)
