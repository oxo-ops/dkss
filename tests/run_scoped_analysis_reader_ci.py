"""Only owned disposable PostgreSQL; require all scoped-reader cases to run."""
import os
import sys
import unittest
from unittest.mock import patch
from analysis_runtime_ci_support import verify_owned_service
assert os.environ.get('ANALYSIS_RUNTIME_CI_GUARD_LOADED') == '1'
verify_owned_service(os.environ['ANALYSIS_RUNTIME_POSTGRES_TEST_URL'], os.environ)
suite = unittest.defaultTestLoader.loadTestsFromNames([
    'test_scoped_analysis_reader_postgres', 'test_scoped_analysis_hold_postgres', 'test_scoped_analysis_normal_preflight_postgres',
    'test_priority_generation_prompt', 'test_priority_generation_schema_limits'])
# All HTTP transports additionally fail, even loopback: this test has no HTTP role.
with patch('urllib.request.urlopen', side_effect=AssertionError('NO_HTTP_IN_READER_TEST')):
    result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() and result.testsRun >= 21 and not result.skipped else 1)
