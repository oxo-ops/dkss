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
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_scoped_analysis_*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() and result.testsRun >= 16 and not result.skipped else 1)
