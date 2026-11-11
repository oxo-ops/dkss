"""CI-only WSGI app: real Gunicorn hooks, real queue/DB, synthetic model transport."""
import json
import os
from pathlib import Path
import time

from analysis_runtime_ci_support import verify_owned_service, acceptance_root, CONNECT_ARGS

ROOT = acceptance_root()
assert os.environ.get('ANALYSIS_RUNTIME_CI_GUARD_LOADED') == '1'
assert os.environ.get('OPENAI_API_KEY') == ''
URL = verify_owned_service(os.environ['ANALYSIS_RUNTIME_POSTGRES_TEST_URL'], os.environ)

from dkss_app import create_app
from dkss_app import common, analysis_worker

# Accelerate only the idle wait for process tests. The real queue and lease
# deadlines remain untouched; expired recovery is induced explicitly in the
# disposable fixture by the test, not by production clock/lease modifications.
analysis_worker.INTERVAL_SECONDS = 0.2
app = create_app({'SQLALCHEMY_DATABASE_URI': URL,
    'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': CONNECT_ARGS}})
case = os.environ['ANALYSIS_RUNTIME_CASE']
assert case.isidentifier()
case_root = ROOT / case
case_root.mkdir(exist_ok=True)


def synthetic_ai(payload, on_progress=None):
    if on_progress is not None:
        on_progress()
    row = {'pid': os.getpid(), 'at': time.time(), 'important_hash': payload['_fingerprints']['important_hash']}
    descriptor = os.open(case_root / 'calls.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, (json.dumps(row) + '\n').encode())
    finally:
        os.close(descriptor)
    deadline = time.monotonic() + 45
    while not (case_root / 'release').exists():
        if time.monotonic() > deadline:
            raise RuntimeError('SYNTHETIC_AI_RELEASE_TIMEOUT')
        time.sleep(0.05)
    if on_progress is not None:
        on_progress()
    return {'overview': 'Synthetic CI completed', 'recommendations': []}


common.analyze_vehicle_karte = synthetic_ai
