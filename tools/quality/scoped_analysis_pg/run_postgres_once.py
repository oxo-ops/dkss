"""DRAFT PostgreSQL variant, operator-invoked only. Import/CLI does nothing; never auto-resume.
Reviewed runtime must supply RunConditions and call run_once explicitly.
Requires separately approved/applied ledger migration. No filesystem ledger.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import contextlib
import json
import logging
import os
import time

COMMIT = '1adf2daa07505ec332cec0201d033c2b5336bef4'
COMPANY = 'HARUMICHI'
VEHICLE = 644
ALLOWED = (644, 645, 646)
DB_HOST = 'dpg-dbkk5juc6qcc73am01r0-a.oregon-postgres.render.com'
DB_NAME = 'dkss_db_new_20261103'
MODEL = 'gpt-6.1-sol'
HOLD = hashlib.sha256(b'approved-388/HARUMICHI/644/count1/generation1').hexdigest()

@dataclass(frozen=True)
class RunConditions:
    verified_commit: str
    expected_db_name: str
    expected_db_host: str
    expected_db_user: str
    approval_reference: str
    pricing_evidence_reference: str
    ledger_migration_verified: bool
    all_other_analysis_workers_stopped: bool
    independent_review_passed: bool
    tax_and_region_multiplier_verified: bool


def _require(ok):
    if not ok:
        raise RuntimeError('PILOT_PRECONDITION_FAILED')


def run_once(conditions, *, api_key):
    """Returns safe status only. No CLI, no credential lookup, no retry.

    After verified DB access, start consumes a fixed PostgreSQL trial marker. Never delete it. Earlier preflight failures make no DB changes.
    Conditions are operator attestations, NOT evidence verified by this function.
    """
    _require(isinstance(conditions, RunConditions))
    _require(conditions.verified_commit == COMMIT)
    _require(conditions.expected_db_name == DB_NAME and conditions.expected_db_host == DB_HOST)
    _require(os.environ.get('RENDER_GIT_COMMIT') == COMMIT)
    _require(all((conditions.expected_db_name, conditions.expected_db_host, conditions.expected_db_user, conditions.approval_reference,
        conditions.pricing_evidence_reference, conditions.all_other_analysis_workers_stopped,
        conditions.ledger_migration_verified, conditions.independent_review_passed,
        conditions.tax_and_region_multiplier_verified)))
    _require(os.environ.get('VEHICLE_ANALYSIS_WORKER_ENABLED', '0') != '1')
    _require((os.environ.get('OPENAI_ANALYSIS_MODEL') or os.environ.get('OPENAI_MODEL') or MODEL) == MODEL)
    _require(isinstance(api_key, str) and bool(api_key.strip()))
    # Suppress library/application output, including SQL/exception/raw request logs.
    old_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            result = _run(conditions, api_key)
        return result
    except BaseException:
        # Do not expose traceback, exception text, source payload, response, or key.
        return {'status': 'stopped_no_retry', 'operator_reconciliation_required': True}
    finally:
        api_key = None
        logging.disable(old_disable)


def _run(c, api_key):
    from urllib.parse import urlsplit, parse_qs
    # TLS must already be configured by the authorized operator. No weakening or
    # secret print; inspect only and fail closed before importing the application.
    u = urlsplit(os.environ.get('DATABASE_URL', ''))
    q = parse_qs(u.query, keep_blank_values=True)
    _require(u.hostname == DB_HOST and u.path == '/' + DB_NAME and u.username == c.expected_db_user)
    _require(not (set(q) & {'host', 'hostaddr', 'dbname', 'service'}))
    _require(q.get('sslmode', [os.environ.get('PGSSLMODE')]) == ['verify-full'])
    ca = q.get('sslrootcert', [os.environ.get('PGSSLROOTCERT')])
    _require(len(ca) == 1 and ca[0] and os.path.isfile(ca[0]) and os.access(ca[0], os.R_OK))
    from app import app, db, Vehicle, VehicleKarteAnalysis
    from dkss_app.analysis import (get_vehicle_karte_analysis_job_data,
        queue_vehicle_karte_analysis)
    from tools.quality.scoped_analysis.preflight import NormalReadScope, read_normal_input
    from tools.quality.scoped_analysis.count_material import prepare_count_material
    from tools.quality.scoped_analysis.count_transport import CountPolicy, CountHTTPS
    from tools.quality.scoped_analysis.pilot import Policy, Request, digest, SOL_STANDARD_30M, SOL_RATE_SOURCE
    from postgres_ledger import PostgresStore, PostgresCountLedger, PostgresGenerationLedger
    from tools.quality.scoped_analysis.http_candidate import COUNT_SOURCE
    from tools.quality.scoped_analysis.final_gate import RESPONSES_URL
    from tools.quality.scoped_analysis.job_bridge import ScopedJobBridge
    from tools.quality.scoped_analysis.https_transport import ResponsesHTTPS
    from dkss_app.analysis_worker import leadership
    from vehicle_analysis_repository import VehicleAnalysisJobRepository
    from vehicle_analysis_service import VehicleAnalysisJobService
    from dkss_app.priority_confirmed_projection import prepare_held_confirmed_candidates, reconcile_confirmed_candidates_before_save
    from sqlalchemy import text
    from uuid import uuid4

    class SanitizedRepository(VehicleAnalysisJobRepository):
        def fail(self, state_id, token, code, retry_at, *, claimed_hash, snapshot_hash=None):
            # Never persist service-generated str(error), SQL params or payload.
            return super().fail(state_id, token, 'PILOT_FAILED_NO_RETRY', retry_at,
                claimed_hash=claimed_hash, snapshot_hash=snapshot_hash)

    class SilentLogger:
        def warning(self, *args, **kwargs):
            pass

    with app.app_context(), leadership(app) as owner:
        _require(owner is not None)
        owner.check()
        _require(db.engine.url.host == c.expected_db_host and db.engine.url.username == c.expected_db_user)
        _require(db.engine.dialect.name == 'postgresql' and db.engine.url.database == c.expected_db_name)
        identity = db.session.execute(text("SELECT current_database(), current_user, ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()" )).one()
        _require(identity[0] == c.expected_db_name and identity[1] == c.expected_db_user and identity[2] is True)
        db.session.remove()
        store = PostgresStore(db.engine)
        # Transactional fixed trial marker consumed before queue, count or send.
        store.start(approval_reference=c.approval_reference, pricing_reference=c.pricing_evidence_reference)
        repository = SanitizedRepository(db=db, state_model=VehicleKarteAnalysis, vehicle_model=Vehicle)
        # Canonical queue creation only, no direct state fabrication or due-time edits.
        _require(VehicleKarteAnalysis.query.filter_by(company_code=COMPANY, vehicle_record_id=VEHICLE).first() is None)
        vehicle = Vehicle.query.filter_by(id=VEHICLE, company_code=COMPANY, deleted=False).one()
        with app.test_request_context('/'):
            payload, _ = get_vehicle_karte_analysis_job_data(vehicle)
            state = queue_vehicle_karte_analysis(vehicle, payload)
        db.session.flush()
        state_id, due = state.id, state.next_analysis_at
        _require(state.status == 'pending' and state.pilot_hold is None and due is not None)
        _require(payload.get('_fingerprints', {}).get('has_important_history') is True)
        owner.check()
        # Queue and hold commit atomically; crash cannot expose an unheld pending row.
        repository.install_pilot_hold(state_id, COMPANY, VEHICLE, HOLD, datetime.now(timezone.utc))
        db.session.remove()
        del payload, state, vehicle
        due = due.replace(tzinfo=timezone.utc) if due.tzinfo is None else due
        delay = (due - datetime.now(timezone.utc)).total_seconds()
        _require(delay <= 130)
        if delay > 0:
            time.sleep(delay + 0.1)
        owner.check()
        snapshot = read_normal_input(NormalReadScope(COMPANY, VEHICLE, state_id, ALLOWED, True))
        material = prepare_count_material(snapshot.payload, target=snapshot.target, model=MODEL)
        body = json.loads(material.generation_json)
        _require(body['max_output_tokens'] <= 6000 and len(material.generation_json.encode()) <= 500000)
        count_policy = CountPolicy(material.generation_sha256, material.count_sha256,
            digest(asdict(snapshot.target)), MODEL, c.approval_reference, 1, c.pricing_evidence_reference)
        count_ledger = PostgresCountLedger(store, count_policy)
        owner.check()
        evidence = CountHTTPS(api_key).run(count_ledger, material)
        _require(evidence['transport_received'] is True and evidence['input_tokens'] <= 76000)
        # Conservative reservation: 76k*2.50 + 6k*10 = 250000 microUSD.
        # Count is free per verified provider terms; reserve 1 microUSD anyway.
        # Region 10% and tax 10%: (250000+1)*1.21 < 1000000 microUSD.
        _require((250000 + 1) * 121 <= 1000000 * 100)
        policy = Policy((snapshot.target,), MODEL, 1, 6000, 500000, 250000,
            '2', '10', SOL_RATE_SOURCE, '2026-11-12', SOL_STANDARD_30M, RESPONSES_URL)
        request = Request(snapshot.target, material.generation_json, material.generation_sha256,
            evidence['input_tokens'], COUNT_SOURCE)
        ledger = PostgresGenerationLedger(store, policy)
        bridge = ScopedJobBridge(ledger, request, transport=ResponsesHTTPS(api_key))
        db.session.remove()
        owner.check()
        bridge.validate_state(repository.get(state_id))
        # Same canonical service/callbacks as #388 job wrapper; preserve already-held
        # repository rather than reacquiring/clearing the trial's persistent hold.
        completed = VehicleAnalysisJobService(
            repository=repository, load_input=bridge.load_input, analyze=bridge.analyze,
            ownership_check=owner.check,
            prepare_confirmed=prepare_held_confirmed_candidates,
            reconcile_confirmed=reconcile_confirmed_candidates_before_save,
            utc_now=lambda: datetime.now(timezone.utc), new_token=lambda: str(uuid4()),
            input_context=lambda: app.test_request_context('/'),
            logger=SilentLogger(), read_api_key=lambda: '',
        ).run(state_id)
        db.session.remove()
        state = VehicleKarteAnalysis.query.filter_by(id=state_id, company_code=COMPANY, vehicle_record_id=VEHICLE).one()
        receipts = ledger.receipts()
        _require(completed is True and state.status == 'completed' and state.pilot_hold == HOLD)
        _require(len(receipts) == 1 and receipts[0][3] == 'returned')
        db.session.remove()
        return {'status': 'saved_hold_retained', 'state_id': state_id, 'count_calls': 1,
            'generation_calls': 1, 'generation_sha256': material.generation_sha256,
            'tax_inclusive_reservation_microusd_ceiling': 302502}
