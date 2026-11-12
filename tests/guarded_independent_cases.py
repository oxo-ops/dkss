"""Independent ephemeral certificate cases. Never export generated content.

Producer: exact GitHub 692298445d7d57c9c611328792ef966d27b4ebe9.
Public scenario: CertificateSourceTests legal_deadline confirmation; completed_at
change from test_http_today_confirmation_becomes_held_tomorrow_or_when_evidence_changes.
Pending reservation uses the published real-reconcile/queue interleaving in
tests/test_analysis_generation_fence.py, with only this certificate input.
This does not load or reconstruct any earlier rollback snapshot or progression recipe.
"""
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PRODUCER = '692298445d7d57c9c611328792ef966d27b4ebe9'
PRODUCER_TREE = '4e1afcd727375d71ce1eb4cffce6dcf594db5dab'


def directory():
    path = Path(os.environ['GUARDED_INDEPENDENT_TMP']).resolve()
    if not path.is_dir():
        raise RuntimeError('INDEPENDENT_TEMP_MISSING')
    return path


def saved(case='held', kind='analysis'):
    with sqlite3.connect(directory() / 'cases.sqlite') as db:
        rows = db.execute('SELECT value FROM generated WHERE case_name=? AND kind=?', (case, kind)).fetchall()
    if len(rows) != 1:
        raise RuntimeError('INDEPENDENT_CASE_MISSING')
    return rows[0][0]


def record(case, key, value):
    with sqlite3.connect(directory() / 'cases.sqlite') as db:
        db.execute('CREATE TABLE IF NOT EXISTS generated (case_name TEXT, kind TEXT, value TEXT, PRIMARY KEY(case_name,kind))')
        db.execute('INSERT OR REPLACE INTO generated VALUES(?,?,?)', (case, key, value))


def backup(source, dest):
    with sqlite3.connect(source) as src, sqlite3.connect(dest) as dst:
        src.backup(dst)


def generate_normal(c):
    from dkss_app.analysis import get_vehicle_karte_analysis_job_data, queue_vehicle_karte_analysis, run_vehicle_karte_analysis_job
    with c.app.test_request_context('/'):
        payload, _ = get_vehicle_karte_analysis_job_data(c.vehicle)
        state = queue_vehicle_karte_analysis(c.vehicle, payload)
    state.status = 'pending'
    state.next_analysis_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    state.lease_token = None
    state.lease_expires_at = None
    c.db.session.commit()
    ident = state.id
    # Empty model output is already an explicit public completion-test scenario.
    # The actual server confirmation projection creates the legal-deadline result.
    with patch('dkss_app.common.analyze_vehicle_karte', return_value={'recommendations': []}):
        if not run_vehicle_karte_analysis_job(ident):
            raise RuntimeError('NORMAL_GENERATION_FAILED')


def generate_periodic(c, record_id):
    service = c.app.extensions['dkss']['periodic_followups']
    api = f'/vehicle/karte/{c.vehicle.id}/periodic/{record_id}/suggestions'
    job = service.Proposal.query.one_or_none()
    if job is not None:
        job.status = 'error'
        job.updated_at = '2000-01-01T00:00:00+09:00'
        c.db.session.commit()
    with patch.object(c.app.extensions['periodic_proposal_executor'], 'submit') as submit:
        response = c.client.post(api, json={'retry': True})
    if response.status_code != 202 or not submit.called:
        raise RuntimeError('PERIODIC_ADMISSION_FAILED')
    function, *args = submit.call_args.args
    with patch('vehicle_karte_analysis_ai.analyze_vehicle_karte', return_value={'recommendations': []}):
        function(*args)
    c.db.session.expire_all()
    if service.Proposal.query.one().status != 'completed':
        raise RuntimeError('PERIODIC_GENERATION_FAILED')


def expected(response, case):
    analysis = response.get('analysis', response.get('result')) or {}
    items = analysis.get('recommendations') or []
    legal = [v for v in items if any(d.get('kind') == 'legal_deadline' for d in
             (v.get('priority_assessment', {}).get('historical_confirmation_details') or
              v.get('priority_assessment', {}).get('confirmation_details_list') or
              [v.get('priority_assessment', {}).get('confirmation_details', {})]))]
    if len(legal) != 1:
        return False
    item = legal[0]
    value = item.get('priority_assessment', {})
    if case == 'active':
        return value.get('effective_score') == 60 and not item.get('priority_candidate_carryover')
    if case == 'pending':
        # The previous active bundle is retained verbatim, not regenerated into a
        # carry bundle. Fresh read projection must withhold its current score.
        return (value.get('effective_score') is None
                and len(value.get('historical_confirmation_details', [])) == 1)
    return (value.get('effective_score') is None and bool(item.get('priority_candidate_carryover'))
            and len(value.get('historical_confirmation_details', [])) == 1)


def generate_pending_reservation(c, document_id):
    """Exercise V7's generation fence through the real V8 worker and queue.

    The deterministic hook represents a newer reservation visible at final save.
    SQLite does not prove concurrent writers can enter V8's locked section.
    Native V8 source-writer/lock-order acceptance remains separate.
    """
    from dkss_app import analysis, common, priority_confirmed_projection as projection
    from vehicle_analysis_repository import VehicleAnalysisJobRepository
    from vehicle_analysis_service import snapshot_hash
    state = c.models.VehicleKarteAnalysis.query.one()
    state_id, vehicle_id = state.id, c.vehicle.id
    retained = (state.result_json, state.last_analyzed_at, state.last_error)
    state.status = 'pending'
    state.next_analysis_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    state.lease_token = None
    state.lease_expires_at = None
    c.db.session.commit()
    claimed_hash = state.input_hash
    reservation = {}
    reached = []
    finished = []
    def audit():
        columns = c.models.ChecklistEvent.__table__.columns.keys()
        return [tuple(getattr(row, column) for column in columns) for row in
                c.models.ChecklistEvent.query.order_by(c.models.ChecklistEvent.id).all()]
    previous_audit = audit()
    real = projection.reconcile_confirmed_candidates_before_save
    def reconcile(*args, **kwargs):
        generated = real(*args, **kwargs)
        # Same independently published certificate-change scenario as held.
        document = c.db.session.get(c.models.VehicleDocumentImportDraft, document_id)
        document.completed_at = datetime(2026, 1, 2)
        c.db.session.commit()
        vehicle = c.db.session.get(c.models.Vehicle, vehicle_id)
        with c.app.test_request_context('/'):
            fresh, _ = analysis.get_vehicle_karte_analysis_job_data(vehicle)
            queued = analysis.queue_vehicle_karte_analysis(vehicle, fresh)
        c.db.session.commit()
        reservation.update(input_hash=queued.input_hash, next_analysis_at=queued.next_analysis_at,
                           request_reason=queued.request_reason)
        if (queued.input_hash in {claimed_hash, snapshot_hash(args[2]['_fingerprints'])}
                or queued.status != 'running' or not queued.lease_token
                or queued.next_analysis_at is None or not queued.request_reason):
            raise RuntimeError('NEW_RESERVATION_NOT_DISTINCT')
        reached.append(True)
        return generated
    real_finish = VehicleAnalysisJobRepository.finish
    real_fail = VehicleAnalysisJobRepository.fail
    def finish(*args, **kwargs):
        result = real_finish(*args, **kwargs)
        finished.append(result)
        return result
    with patch.object(common, 'analyze_vehicle_karte', return_value={'recommendations': []}) as ai, \
            patch.object(projection, 'reconcile_confirmed_candidates_before_save', side_effect=reconcile) as gate, \
            patch.object(VehicleAnalysisJobRepository, 'finish', autospec=True, side_effect=finish) as saver, \
            patch.object(VehicleAnalysisJobRepository, 'fail', autospec=True, side_effect=real_fail) as failure:
        outcome = analysis.run_vehicle_karte_analysis_job(state_id)
    c.db.session.expire_all()
    state = c.db.session.get(c.models.VehicleKarteAnalysis, state_id)
    if (outcome or ai.call_count != 1 or gate.call_count != 1 or not reservation
            or reached != [True] or saver.call_count != 1 or finished != [False] or failure.call_count != 0
            or state.status != 'pending' or state.lease_token is not None or state.lease_expires_at is not None
            or (state.result_json, state.last_analyzed_at, state.last_error) != retained
            or any(getattr(state, key) != value for key, value in reservation.items())
            or audit() != previous_audit):
        raise RuntimeError('NEW_RESERVATION_NOT_PRESERVED')


def save_case(c, case, vehicle_id, record_id):
    c.db.session.expire_all()
    normal = c.models.VehicleKarteAnalysis.query.one()
    proposal = c.app.extensions['dkss']['periodic_followups'].Proposal.query.one()
    record(case, 'analysis', normal.result_json)
    record(case, 'periodic', proposal.result_json)
    record(case, 'vehicle_id', str(vehicle_id))
    record(case, 'record_id', str(record_id))
    record(case, 'state_id', str(normal.id))
    for kind, url in (
            ('analysis', f'/vehicle/karte/{vehicle_id}/analysis/result'),
            ('periodic', f'/vehicle/karte/{vehicle_id}/periodic/{record_id}/suggestions')):
        response = c.client.get(url)
        if response.status_code != 200 or not expected(response.json, case):
            raise RuntimeError('INDEPENDENT_EXPECTATION_FAILED')
        if case == 'pending' and kind == 'analysis' and (
                response.json.get('status') != 'pending' or response.json.get('is_current') is not False):
            raise RuntimeError('PENDING_READ_NOT_STALE')
        record(case, 'baseline_' + kind, json.dumps(response.json, sort_keys=True))
    path = c.db.engine.url.database
    c.db.session.remove()
    backup(path, directory() / (case + '.sqlite'))


def generate():
    from test_priority_certificate_sources import CertificateSourceTests
    from test_workflow_regressions import WorkflowRegressionTests
    from test_inspection_plans import InspectionPlanTests
    from application_fixture import ApplicationFixture
    # These are existing public HTTP import helpers, not copied output documents.
    CertificateSourceTests.upload_inspection = WorkflowRegressionTests.upload_inspection
    CertificateSourceTests.inspection_form = WorkflowRegressionTests.inspection_form
    CertificateSourceTests.import_record = InspectionPlanTests.import_record
    CertificateSourceTests.setUpClass()
    c = CertificateSourceTests()
    c.setUp()
    c.m = ApplicationFixture(c.app)
    try:
        periodic = c.import_record()
        record_id = periodic.id
        c.confirm_http()
        vehicle_id, document_id = c.vehicle.id, c.document.id
        for case in ('active', 'held'):
            c.vehicle = c.db.session.get(c.models.Vehicle, vehicle_id)
            c.document = c.db.session.get(c.models.VehicleDocumentImportDraft, document_id)
            if case == 'held':
                # Exact independent published certificate-change scenario.
                c.document.completed_at = datetime(2026, 1, 2)
                c.db.session.commit()
            generate_normal(c)
            generate_periodic(c, record_id)
            save_case(c, case, vehicle_id, record_id)
            if case == 'active':
                c.vehicle = c.db.session.get(c.models.Vehicle, vehicle_id)
                generate_pending_reservation(c, document_id)
                save_case(c, 'pending', vehicle_id, record_id)
    finally:
        c.tearDown()
        c.doCleanups()
        CertificateSourceTests.tearDownClass()


def roundtrip_app(target):
    from dkss_app import create_app
    # This factory runs in a fresh process after fixture env patches have ended.
    # Never depend on an ambient/local or production session-signing key.
    return create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False,
                       'SECRET_KEY': 'guarded-independent-roundtrip-test-only',
                       'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(target)})


def run_roundtrip(case, newer):
    from dkss_app import models
    from dkss_app.extensions import db, limiter
    from identity_fixture import identity_for
    target = directory() / (case + '.sqlite')
    def snapshot():
        with sqlite3.connect(target) as conn:
            names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {n: sorted(conn.execute('SELECT * FROM "' + n + '"').fetchall(), key=repr) for n in names}
    before = snapshot()
    app = roundtrip_app(target)
    limiter.enabled = False
    with app.app_context():
        client = app.test_client()
        user = models.User.query.filter_by(company_code='A', username='admin').one()
        with client.session_transaction() as session:
            session.update(company_code='A', username='admin', role=user.role,
                account_identity=identity_for('A', 'admin', app=app), name='Test admin',
                password_changed_at=user.password_changed_at)
        vehicle_id = int(saved(case, 'vehicle_id'))
        record_id = int(saved(case, 'record_id'))
        state_id = int(saved(case, 'state_id'))
        api = f'/vehicle/karte/{vehicle_id}/periodic/{record_id}/suggestions'
        for kind, url in [('analysis', f'/vehicle/karte/{vehicle_id}/analysis/result'), ('periodic', api)]:
            response = client.get(url)
            if response.status_code != 200:
                raise RuntimeError('ROUNDTRIP_READ_FAILED')
            data = response.json
            if newer:
                if not expected(data, case) or json.dumps(data, sort_keys=True) != saved(case, 'baseline_' + kind):
                    raise RuntimeError('ROUNDTRIP_RETURN_CHANGED')
            elif data.get('status') != 'held' or data.get('is_current') is not False:
                raise RuntimeError('ROUNDTRIP_WITHHOLD_FAILED')
        if not newer:
            from dkss_app.analysis import get_vehicle_karte_analysis_job_data, queue_vehicle_karte_analysis, run_vehicle_karte_analysis_job
            service = app.extensions['dkss']['periodic_followups']
            with patch('dkss_app.common.analyze_vehicle_karte') as ai, patch('vehicle_periodic_followups.generate_periodic_proposals') as pai, patch.object(app.extensions['periodic_proposal_executor'], 'submit') as submit:
                for retry in (False, True):
                    response = client.post(api, json={'retry': retry})
                    if response.status_code != 409 or response.json.get('status') != 'held':
                        raise RuntimeError('ROUNDTRIP_POST_NOT_REFUSED')
                vehicle = db.session.get(models.Vehicle, vehicle_id)
                with app.test_request_context('/'):
                    payload, _ = get_vehicle_karte_analysis_job_data(vehicle)
                    queue_vehicle_karte_analysis(vehicle, payload)
                    db.session.commit()
                if run_vehicle_karte_analysis_job(state_id):
                    raise RuntimeError('ROUNDTRIP_WORKER_NOT_REFUSED')
                job = service.Proposal.query.one()
                service.worker('A', record_id, job.run_token, {})
                if ai.called or pai.called or submit.called:
                    raise RuntimeError('ROUNDTRIP_EXTERNAL_WORK')
        db.session.remove()
        db.engine.dispose()
    if before != snapshot():
        raise RuntimeError('ROUNDTRIP_DATABASE_MUTATION')
