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
connect_args = dict(CONNECT_ARGS)
if URL.startswith('postgresql+psycopg2://'):
    connect_args['application_name'] = f'dkss-analysis-ci-{os.getpid()}'
app = create_app({'SQLALCHEMY_DATABASE_URI': URL,
    'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': connect_args}})
case = os.environ['ANALYSIS_RUNTIME_CASE']
assert case.isidentifier()
case_root = ROOT / case
case_root.mkdir(exist_ok=True)


def record(filename, **values):
    descriptor = os.open(case_root / filename, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, (json.dumps({'pid': os.getpid(), 'at': time.time(), **values}) + '\n').encode())
    finally:
        os.close(descriptor)


def wait_for_fixture_release(filename):
    deadline = time.monotonic() + 45
    while not (case_root / filename).exists():
        if time.monotonic() > deadline:
            raise RuntimeError('SYNTHETIC_AI_RELEASE_TIMEOUT')
        time.sleep(0.05)


def synthetic_ai(payload, on_progress=None):
    if on_progress is not None:
        on_progress()
    record('calls.jsonl', important_hash=payload['_fingerprints']['important_hash'])
    if case == 'test_live_leader_db_loss_blocks_second_model_chunk':
        record('chunks.jsonl', stage='chunk1')
        wait_for_fixture_release('release_next_chunk')
        if on_progress is not None:
            on_progress()
        # Independent discriminator: a missing per-chunk ownership fence must
        # expose this attempt, even if the later final-save fence rejects it.
        record('chunks.jsonl', stage='chunk2')
        return {'overview': 'Synthetic CI completed', 'recommendations': []}
    wait_for_fixture_release('release')
    if on_progress is not None:
        on_progress()
    if case == 'test_live_leader_db_loss_blocks_save_with_valid_original_token':
        record('fences.jsonl', stage='last_progress_finished')
    return {'overview': 'Synthetic CI completed', 'recommendations': []}


common.analyze_vehicle_karte = synthetic_ai

if case == 'test_live_leader_db_loss_blocks_save_with_valid_original_token':
    from dkss_app import priority_confirmed_projection
    real_reconcile = priority_confirmed_projection.reconcile_confirmed_candidates_before_save

    def reconcile_then_pause(*args, **kwargs):
        result = real_reconcile(*args, **kwargs)
        record('fences.jsonl', stage='after_reconcile')
        # No callback or token change occurs after this pause: the next product
        # boundary is JobService's final ownership_check, followed by finish.
        wait_for_fixture_release('release_save')
        return result

    priority_confirmed_projection.reconcile_confirmed_candidates_before_save = reconcile_then_pause
