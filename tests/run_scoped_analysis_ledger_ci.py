"""No network/processes; only disposable SQLite, including existing mode=rw files."""
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from urllib.parse import urlsplit, unquote
ROOT=Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
if not ROOT.is_dir() or not ROOT.is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve()):
    raise RuntimeError('OWNED_TEMP_ROOT_REQUIRED')
sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1])]


def guard(event,args):
    if event.startswith('socket.') or event in {'subprocess.Popen','os.system','os.posix_spawn','os.fork','os.exec'}:
        raise RuntimeError('LEDGER_TEST_EXTERNAL_IO_FORBIDDEN')
    if event=='sqlite3.connect':
        value=str(args[0])
        if value==':memory:': return
        if value.startswith('file:'):
            uri=urlsplit(value)
            if uri.netloc or uri.query!='mode=rw' or uri.fragment:
                raise RuntimeError('LEDGER_TEST_BAD_SQLITE_URI')
            path=Path(unquote(uri.path)).resolve()
            if not path.is_file():raise RuntimeError('LEDGER_TEST_EXISTING_FILE_REQUIRED')
        else: path=Path(value).resolve()
        if not path.is_relative_to(ROOT):raise RuntimeError('LEDGER_TEST_OUTSIDE_ROOT')


sys.addaudithook(guard)
# Explicit forbidden URI forms and outside-root paths are tested before any IO.
for path in ('file:/outside?mode=rw','file:/outside?mode=ro','file://host/path?mode=rw',str(ROOT.parent/'outside.sqlite')):
    try:guard('sqlite3.connect',(path,))
    except RuntimeError:pass
    else:raise AssertionError('SQLITE_BOUNDARY_NOT_ACTIVE')
suite=unittest.defaultTestLoader.loadTestsFromNames(['test_scoped_analysis_ledger','test_scoped_analysis_saved_flow', 'test_scoped_analysis_job_bridge_saved'])
result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() and result.testsRun>=11 and not result.skipped else 1)
