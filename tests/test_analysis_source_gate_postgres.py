"""Three source-gate acceptance cases, on the owned official PostgreSQL only.

The real inspection/confirmation/repair HTTP flow, job, reconciliation, and
repository run unchanged. Test-side wrappers only mark/pause real boundaries;
the model is synthetic. This proves the ordinary repair writer's Vehicle gate,
not serialization of every possible source writer. A third low-level case checks
the legacy analysis-row-then-evaluation-FK lock order, not the rollback HTTP app.
Local discovery skips before creating an app, opening PostgreSQL, or invoking
the SQLite fixture lifecycle.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
import threading
import time
import traceback
import unittest
from unittest.mock import patch

from sqlalchemy import event, text

import test_priority_candidate_completion as fixture


class AnalysisSourceGatePostgresTests(unittest.TestCase):
    # Reuse only normal-route fixture helpers, never its SQLite setUpClass or
    # inherited test methods. This module contributes exactly three test cases.
    login = fixture.CandidateCompletionTests.login
    request = fixture.CandidateCompletionTests.request
    save = fixture.CandidateCompletionTests.save
    complete = fixture.CandidateCompletionTests.complete
    state = fixture.CandidateCompletionTests.state
    decision_data = fixture.CandidateCompletionTests.decision_data
    decide = fixture.CandidateCompletionTests.decide
    refs = fixture.CandidateCompletionTests.refs
    clock = fixture.CandidateCompletionTests.clock
    begin = fixture.CandidateCompletionTests.begin
    repair = fixture.CandidateCompletionTests.repair
    prepare_pair = fixture.CandidateCompletionTests.prepare_pair
    confirm = fixture.CandidateCompletionTests.confirm
    load = fixture.CandidateCompletionTests.load

    @classmethod
    def setUpClass(cls):
        raw = os.environ.get('ANALYSIS_RUNTIME_POSTGRES_TEST_URL', '')
        if not raw:
            if os.environ.get('ANALYSIS_RUNTIME_REQUIRE_POSTGRES') == '1':
                raise AssertionError('Explicit disposable analysis PostgreSQL URL required')
            raise unittest.SkipTest('Disposable analysis PostgreSQL not configured')
        from analysis_runtime_ci_support import verify_owned_service, CONNECT_ARGS
        # Exact URL, GitHub repository/job, absence of ambient PG overrides,
        # ownership marker, and finite connection/lock/statement timeouts.
        verify_owned_service(raw, os.environ)
        from dkss_app import create_app, models
        from dkss_app.extensions import db, limiter
        cls.db, cls.models = db, models
        cls.limiter, cls.old_limiter_enabled = limiter, limiter.enabled
        with patch.dict(os.environ, {
                'SECRET_KEY': 'synthetic-analysis-ci', 'S3_BUCKET_NAME': '',
                'RENDER': '', 'RATELIMIT_STORAGE_URI': 'memory://',
                'OPENAI_API_KEY': '', 'SMTP_HOST': '', 'VAPID_PRIVATE_KEY': '',
                'VAPID_PUBLIC_KEY': '', 'AWS_EC2_METADATA_DISABLED': 'true',
                'DOCUMENT_IMPORT_WORKER_ENABLED': '0',
                'VEHICLE_ANALYSIS_WORKER_ENABLED': '0', 'PUBLIC_KNOWLEDGE_ENABLED': '0'}):
            cls.app = create_app({
                'SQLALCHEMY_DATABASE_URI': raw, 'TESTING': True,
                'WTF_CSRF_ENABLED': False,
                'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': CONNECT_ARGS},
            })
        limiter.enabled = False

    @classmethod
    def tearDownClass(cls):
        try:
            with cls.app.app_context():
                cls.db.session.remove()
                cls.db.engine.dispose()
        finally:
            cls.limiter.enabled = cls.old_limiter_enabled

    def setUp(self):
        # This method uses this class's verified PG app; it does not construct
        # an app or overwrite its URI with the fixture's SQLite URI.
        fixture.CandidateCompletionTests.setUp(self)
        self.addCleanup(fixture.CandidateCompletionTests.tearDown, self)
        self.assertEqual(self.db.engine.dialect.name, 'postgresql')
        from dkss_app.analysis_read_cache import upgrade_read_cache
        from vehicle_analysis_service import snapshot_hash
        upgrade_read_cache()
        self.prepare_pair()
        self.confirmation_id, _ = self.confirm()
        payload, _ = self.load()
        self.assertTrue(payload['_fingerprints']['has_important_history'])
        self.vehicle_id, self.row_id = self.vehicle.id, self.row.id
        self.previous = {
            'analysis': {'overview': 'NO-PRIOR-CONFIRMED-CANDIDATE', 'recommendations': []},
            'sources': {}, 'fingerprints': {}, 'generated_at': 'PRIOR-EMPTY',
        }
        self.previous_json = json.dumps(self.previous, ensure_ascii=False)
        self.original_hash = snapshot_hash(payload['_fingerprints'])
        state = self.models.VehicleKarteAnalysis(
            company_code='A', vehicle_record_id=self.vehicle_id, status='pending',
            input_hash=self.original_hash, result_json=self.previous_json,
            next_analysis_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        foreign_vehicle = self.models.Vehicle.query.filter_by(company_code='B').one()
        self.foreign_vehicle_id = foreign_vehicle.id
        self.db.session.add_all([state, self.models.VehicleKarteAnalysis(
            company_code='B', vehicle_record_id=foreign_vehicle.id, status='completed',
            input_hash='foreign-unchanged', result_json='{"foreign":"unchanged"}')])
        self.db.session.commit()
        self.state_id = state.id
        self.repair_data = {
            'judgment_version': str(self.state()['version']),
            'repair_status': '再確認待ち',
            'repair_note': '合成例：左側同じ部位を整備。',
            'repair_performed_at': f'{self.day.isoformat()}T10:00',
        }
        self.assertNotIn('recheck_result', self.repair_data)
        self.login('reviewer')
        with self.client.session_transaction() as browser_session:
            self.reviewer_session = dict(browser_session)
        self.login('admin')
        self.db.session.remove()
        self.before = self.read_committed()
        self.assertEqual(self.before['status'], 'active')
        self.assertEqual(self.before['result_json'], self.previous_json)
        self.foreign_before = self.foreign_snapshot()

    @staticmethod
    def row_values(row):
        return tuple(getattr(row, column.name) for column in row.__table__.columns)

    def scoped_sources(self):
        """Exact business rows for A/this vehicle, excluding analysis/cache rows."""
        m = self.models
        inspection = m.VehicleChecklistResult.query.filter_by(
            company_code='A', vehicle_record_id=self.vehicle_id).order_by(m.VehicleChecklistResult.id).all()
        ids = [row.id for row in inspection]
        events = m.ChecklistEvent.query.filter(
            m.ChecklistEvent.company_code == 'A',
            self.db.or_(
                self.db.and_(m.ChecklistEvent.result_type == 'vehicle', m.ChecklistEvent.result_id.in_(ids)),
                self.db.and_(m.ChecklistEvent.result_type == 'vehicle_priority',
                             m.ChecklistEvent.result_id == self.vehicle_id)),
        ).order_by(m.ChecklistEvent.id).all()
        maintenance = m.VehicleMaintenanceRecord.query.filter_by(
            company_code='A', vehicle_record_id=self.vehicle_id).order_by(m.VehicleMaintenanceRecord.id).all()
        maintenance_events = m.VehicleMaintenanceRecordEvent.query.filter_by(
            company_code='A', vehicle_record_id=self.vehicle_id).order_by(m.VehicleMaintenanceRecordEvent.id).all()
        return {
            'inspection': tuple(self.row_values(row) for row in inspection),
            'audit': tuple(self.row_values(row) for row in events),
            'maintenance': tuple(self.row_values(row) for row in maintenance),
            'maintenance_audit': tuple(self.row_values(row) for row in maintenance_events),
        }

    def sample(self):
        """Read the current session, including a writer's uncommitted changes."""
        from dkss_app.priority_confirmations import confirmation_statuses
        self.db.session.expire_all()
        vehicle = self.models.Vehicle.query.filter_by(company_code='A', id=self.vehicle_id).one()
        state = self.models.VehicleKarteAnalysis.query.filter_by(
            company_code='A', vehicle_record_id=self.vehicle_id, id=self.state_id).one()
        row = self.models.VehicleChecklistResult.query.filter_by(
            company_code='A', vehicle_record_id=self.vehicle_id, id=self.row_id).one()
        statuses = confirmation_statuses(vehicle, as_of=self.day)
        self.assertEqual(len(statuses), 1)
        confirmation = statuses[0]
        self.assertEqual((confirmation['company_code'], confirmation['vehicle_id'], confirmation['event_id']),
                         ('A', self.vehicle_id, self.confirmation_id))
        epoch = self.models.AnalysisInputEpoch.query.filter_by(
            company_code='A', bucket=f'vehicle:{self.vehicle_id}').one()
        return {
            'status': confirmation['status'], 'result_json': state.result_json,
            'input_hash': state.input_hash, 'job_status': state.status,
            'lease_token': state.lease_token, 'lease_expires_at': state.lease_expires_at,
            'epoch': epoch.revision, 'source_json': row.operation_judgment_json,
            'answers_json': row.answers_json, 'checklist_snapshot_json': row.checklist_snapshot_json,
            'sources': self.scoped_sources(),
        }

    def read_committed(self):
        with self.app.app_context():
            try:
                return self.sample()
            finally:
                self.db.session.remove()

    def foreign_snapshot(self):
        # Nonempty foreign Vehicle/analysis rows and all foreign business rows
        # must remain byte/field identical, including epochs and notifications.
        with self.app.app_context():
            models = (self.models.Vehicle, self.models.VehicleKarteAnalysis,
                      self.models.VehicleChecklistResult, self.models.ChecklistEvent,
                      self.models.VehicleMaintenanceRecord, self.models.VehicleMaintenanceRecordEvent,
                      self.models.AnalysisInputEpoch, self.models.Notification,
                      self.models.VehicleAnalysisEvaluation)
            try:
                return tuple(tuple(self.row_values(row) for row in model.query.filter_by(
                    company_code='B').order_by(*model.__table__.primary_key.columns).all()) for model in models)
            finally:
                self.db.session.remove()

    def mark_backend(self, name):
        # LOCAL prevents pooled connections retaining another case's label.
        self.db.session.execute(text("SELECT set_config('application_name', :name, true)"), {'name': name})
        return self.db.session.execute(text('SELECT pg_backend_pid(), txid_current()')).one()

    def wait_for_blocked(self, waiter, blocker, name, sql_fragment, *, executed_sql=None):
        deadline = time.monotonic() + 3
        last = None
        while time.monotonic() < deadline:
            with self.db.engine.connect() as connection:
                last = connection.execute(text("""
                    SELECT wait_event_type, query, pg_blocking_pids(pid) AS blockers
                    FROM pg_stat_activity
                    WHERE datname=current_database() AND pid=:pid AND application_name=:name
                """), {'pid': waiter, 'name': name}).mappings().first()
            if last and last['wait_event_type'] == 'Lock' and blocker in last['blockers']:
                sql = (executed_sql() if executed_sql is not None else last['query']).lower()
                self.assertIn(sql_fragment, sql)
                self.assertIn('vehicle', sql)
                self.assertIn('company_code', sql)
                return dict(last)
            time.sleep(0.02)
        self.fail(f'Expected database row lock wait was not observed: {last!r}')

    def run_interleaving(self, *, writer_first):
        from dkss_app import analysis, checklists, common, vehicle_karte
        from dkss_app import priority_confirmed_projection as projection
        from vehicle_analysis_repository import VehicleAnalysisJobRepository

        # Events are only scheduling instruments. No fake lock, fake source
        # transition, fake reconciliation, or fake result persistence is used.
        events = {name: threading.Event() for name in (
            'model_ready', 'model_return', 'saver_entered', 'saver_acquired',
            'reconciled', 'save_release', 'writer_entered', 'writer_acquired',
            'writer_continue', 'writer_persisted', 'writer_commit', 'writer_done')}
        if not writer_first:
            events['model_return'].set()
            events['writer_commit'].set()
        else:
            events['save_release'].set()
            events['writer_continue'].set()
        evidence, errors, jobs, responses, model_calls = {}, [], [], [], []
        real_gate = VehicleAnalysisJobRepository.lock_vehicle_for_finish
        real_writer_gate = checklists.lock_vehicle_inspection_updates
        real_persist = vehicle_karte.persist_vehicle_inspection_repair
        real_reconcile = projection.reconcile_confirmed_candidates_before_save
        real_finish = VehicleAnalysisJobRepository.finish

        def wait(name):
            if not events[name].wait(8):
                raise RuntimeError(f'source-gate-test-timeout:{name}')

        def synthetic_model(payload, on_progress=None):
            model_calls.append(deepcopy(payload))
            # The actual renewal commits before either final gate is taken.
            self.assertIsNotNone(on_progress)
            on_progress()
            events['model_ready'].set()
            wait('model_return')
            return {'overview': 'FIRST-GENERATION', 'recommendations': []}

        def saver_gate(repository, company, vehicle_id):
            self.assertEqual((company, vehicle_id), ('A', self.vehicle_id))
            evidence['saver_pid'], evidence['saver_tx'] = self.mark_backend('analysis_source_saver')
            events['saver_entered'].set()
            value = real_gate(repository, company, vehicle_id)
            self.assertIsNotNone(value)
            events['saver_acquired'].set()
            return value

        def writer_gate(company, *args, **kwargs):
            self.assertEqual(company, 'A')
            self.assertEqual(kwargs.get('result_index'), self.row_id)
            evidence['writer_pid'], evidence['writer_tx'] = self.mark_backend('analysis_source_writer')
            events['writer_entered'].set()
            result = real_writer_gate(company, *args, **kwargs)
            self.assertIsNone(result)
            events['writer_acquired'].set()
            # In saver-first, hold after the real blocked UPDATE succeeds but
            # before any source mutation, to inspect the committed save.
            wait('writer_continue')
            return result

        def persist(*args, **kwargs):
            result = real_persist(*args, **kwargs)
            self.db.session.flush()
            evidence['writer_uncommitted'] = self.sample()
            self.assertEqual(evidence['writer_uncommitted']['status'], 'held')
            self.assertEqual(evidence['writer_uncommitted']['input_hash'], self.original_hash)
            self.assertGreater(evidence['writer_uncommitted']['epoch'], self.before['epoch'])
            self.assertEqual(self.db.session.scalar(text('SELECT txid_current()')), evidence['writer_tx'])
            events['writer_persisted'].set()
            wait('writer_commit')
            return result

        def reconcile(*args, **kwargs):
            self.assertTrue(events['saver_acquired'].is_set())
            self.assertEqual(self.db.session.scalar(text('SELECT txid_current()')), evidence['saver_tx'])
            before = self.sample()
            self.assertEqual(before['result_json'], self.previous_json)
            self.assertEqual(before['status'], 'held' if writer_first else 'active')
            result = real_reconcile(*args, **kwargs)
            evidence['reconciled'] = deepcopy(result)
            self.assertEqual(len(result['recommendations']), 0 if writer_first else 1)
            self.assertEqual(self.sample()['sources'], before['sources'])
            events['reconciled'].set()
            wait('save_release')
            return result

        def finish(repository, *args, **kwargs):
            # This transaction ID spans real Vehicle lock -> real reconcile ->
            # the repository's conditional row fence and result commit.
            self.assertEqual(self.db.session.scalar(text('SELECT txid_current()')), evidence['saver_tx'])
            evidence['before_finish'] = self.sample()
            self.assertEqual(evidence['before_finish']['result_json'], self.previous_json)
            self.assertEqual(evidence['before_finish']['status'], 'held' if writer_first else 'active')
            return real_finish(repository, *args, **kwargs)

        def job():
            with self.app.app_context():
                try:
                    jobs.append(analysis.run_vehicle_karte_analysis_job(self.state_id))
                except Exception:
                    errors.append(traceback.format_exc())
                finally:
                    self.db.session.rollback()
                    self.db.session.remove()

        def repair_post():
            with self.app.app_context():
                try:
                    client = self.app.test_client()
                    with client.session_transaction() as browser_session:
                        browser_session.update(self.reviewer_session)
                    with self.clock(self.day, 10):
                        response = client.post(
                            f'/vehicle/checklist-results/{self.row_id}/defects/1/repair',
                            data=self.repair_data)
                    responses.append((response.status_code, response.get_data(as_text=True)))
                    response.close()
                except Exception:
                    errors.append(traceback.format_exc())
                finally:
                    self.db.session.rollback()
                    self.db.session.remove()
                    events['writer_done'].set()

        saver = threading.Thread(target=job, name='source-gate-saver', daemon=True)
        writer = threading.Thread(target=repair_post, name='source-gate-writer', daemon=True)
        with patch.object(common, 'analyze_vehicle_karte', side_effect=synthetic_model), \
                patch.object(VehicleAnalysisJobRepository, 'lock_vehicle_for_finish', new=saver_gate), \
                patch.object(checklists, 'lock_vehicle_inspection_updates', side_effect=writer_gate), \
                patch.object(vehicle_karte, 'persist_vehicle_inspection_repair', side_effect=persist), \
                patch.object(projection, 'reconcile_confirmed_candidates_before_save', side_effect=reconcile), \
                patch.object(VehicleAnalysisJobRepository, 'finish', new=finish):
            try:
                saver.start()
                self.assertTrue(events['model_ready'].wait(5), errors)
                if writer_first:
                    writer.start()
                    self.assertTrue(events['writer_persisted'].wait(5), errors)
                    # The real writer obtained its gate while the model was
                    # paused, proving the model did not already hold it.
                    visible = self.read_committed()
                    self.assertEqual(visible['status'], 'active')
                    self.assertEqual(visible['result_json'], self.previous_json)
                    self.assertEqual(visible['sources'], self.before['sources'])
                    self.assertEqual(visible['input_hash'], self.original_hash)
                    events['model_return'].set()
                    self.assertTrue(events['saver_entered'].wait(3), errors)
                    evidence['lock_wait'] = self.wait_for_blocked(
                        evidence['saver_pid'], evidence['writer_pid'], 'analysis_source_saver', 'for no key update')
                    self.assertFalse(events['saver_acquired'].is_set())
                    self.assertFalse(events['reconciled'].is_set())
                    events['writer_commit'].set()
                else:
                    self.assertTrue(events['reconciled'].wait(5), errors)
                    visible = self.read_committed()
                    self.assertEqual(visible['result_json'], self.previous_json)
                    self.assertEqual(visible['sources'], self.before['sources'])
                    writer.start()
                    self.assertTrue(events['writer_entered'].wait(3), errors)
                    evidence['lock_wait'] = self.wait_for_blocked(
                        evidence['writer_pid'], evidence['saver_pid'], 'analysis_source_writer', 'update vehicle')
                    self.assertFalse(events['writer_acquired'].is_set())
                    self.assertFalse(events['writer_persisted'].is_set())
                    events['save_release'].set()
                    saver.join(10)
                    self.assertFalse(saver.is_alive(), errors)
                    self.assertEqual(jobs, [True], errors)
                    self.assertTrue(events['writer_acquired'].wait(3), errors)
                    evidence['committed_before_repair'] = self.read_committed()
                    saved = evidence['committed_before_repair']
                    self.assertEqual(saved['status'], 'active')
                    self.assertEqual(saved['sources'], self.before['sources'])
                    candidates = json.loads(saved['result_json'])['analysis']['recommendations']
                    self.assertEqual(len(candidates), 1)
                    self.assertEqual(candidates[0]['priority'], '高')
                    self.assertNotIn('priority_candidate_carryover', candidates[0])
                    self.assertFalse(events['writer_persisted'].is_set())
                    events['writer_continue'].set()
            finally:
                # Always release every test pause, even on failed observation.
                for name in ('model_return', 'save_release', 'writer_continue', 'writer_commit'):
                    events[name].set()
                for thread in (saver, writer):
                    if thread.ident is not None:
                        thread.join(12)
            self.assertFalse(saver.is_alive(), 'Saver did not terminate within finite cleanup')
            self.assertFalse(writer.is_alive(), 'Repair writer did not terminate within finite cleanup')
        self.assertEqual(errors, [])
        self.assertEqual(jobs, [True])
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0][0], 302, responses[0][1])
        self.assertEqual(len(model_calls), 1)
        self.assertEqual(json.loads(self.previous_json), self.previous)
        self.assertEqual(self.previous['analysis']['recommendations'], [])
        self.assertIn('lock_wait', evidence)
        self.assertEqual(self.foreign_snapshot(), self.foreign_before)
        return evidence

    def assert_result_and_regenerate(self, evidence, expected):
        from dkss_app import analysis, common
        first = self.read_committed()
        self.assertEqual((first['job_status'], first['status']), ('completed', 'held'))
        self.assertIsNone(first['lease_token'])
        self.assertIsNone(first['lease_expires_at'])
        self.assertEqual(first['input_hash'], self.original_hash)
        self.assertEqual(first['sources'], evidence['writer_uncommitted']['sources'])
        self.assertNotEqual(first['source_json'], self.before['source_json'])
        self.assertEqual(first['answers_json'], self.before['answers_json'])
        self.assertEqual(first['checklist_snapshot_json'], self.before['checklist_snapshot_json'])
        old_audit = {row[0]: row for row in self.before['sources']['audit']}
        final_audit = {row[0]: row for row in first['sources']['audit']}
        self.assertEqual({key: final_audit[key] for key in old_audit}, old_audit)
        judgment = json.loads(first['source_json'])
        self.assertEqual(judgment['defects'][-1]['status'], '再確認待ち')
        self.assertNotIn('recheck', judgment['defects'][-1])
        self.assertEqual(len(json.loads(first['result_json'])['analysis']['recommendations']), expected)
        if expected:
            self.assertEqual(first['result_json'], evidence['committed_before_repair']['result_json'])
        else:
            self.assertEqual(evidence['writer_uncommitted']['result_json'], self.previous_json)
            self.assertIn('priority_generation_notice', json.loads(first['result_json'])['analysis'])

        def get_result():
            response = self.client.get(f'/vehicle/karte/{self.vehicle_id}/analysis/result')
            try:
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                values = response.json['analysis']['recommendations']
                self.assertEqual(len(values), expected)
                if expected:
                    assessment = values[0]['priority_assessment']
                    self.assertEqual((assessment['label'], assessment['effective_score']), ('高', None))
                    self.assertTrue(assessment.get('historical_confirmation_details'))
            finally:
                response.close()

        get_result()
        self.assertEqual(self.read_committed()['result_json'], first['result_json'])
        self.assertEqual(self.read_committed()['sources'], first['sources'])
        # The next generation uses the real queue and job. Move only the queue
        # clock, never override a lease/claim, force a hash, or call AI twice.
        with self.app.app_context():
            vehicle = self.models.Vehicle.query.filter_by(company_code='A', id=self.vehicle_id).one()
            with self.app.test_request_context('/'):
                payload, _ = analysis.get_vehicle_karte_analysis_job_data(vehicle)
            analysis.queue_vehicle_karte_analysis(vehicle, payload)
            self.db.session.commit()
            self.db.session.remove()

        class DueClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(minutes=3)

        def synthetic_model(payload, on_progress=None):
            if on_progress:
                on_progress()
            return {'overview': 'NEXT-GENERATION', 'recommendations': []}

        with self.app.app_context(), patch.object(common, 'datetime', DueClock), \
                patch.object(common, 'analyze_vehicle_karte', side_effect=synthetic_model) as model:
            self.assertTrue(analysis.run_vehicle_karte_analysis_job(self.state_id))
            model.assert_called_once()
            self.db.session.remove()
        second = self.read_committed()
        recommendations = json.loads(second['result_json'])['analysis']['recommendations']
        self.assertEqual(len(recommendations), expected)
        if expected:
            self.assertTrue(recommendations[0].get('priority_candidate_carryover'))
            proof = json.loads(second['result_json'])['sources'][f'priority_confirmation:{self.confirmation_id}']['priority_confirmation_proof']
            self.assertEqual((proof['company_code'], proof['vehicle_id']), ('A', self.vehicle_id))
        get_result()
        self.assertEqual(self.read_committed()['sources'], first['sources'])
        self.assertEqual(self.read_committed()['result_json'], second['result_json'])
        self.assertEqual(self.foreign_snapshot(), self.foreign_before)
        print('ANALYSIS_SOURCE_GATE_ACCEPTANCE', json.dumps({
            'order': 'save-before-repair' if expected else 'repair-before-save',
            'observed_wait_event_type': evidence['lock_wait']['wait_event_type'],
            'observed_blocker_pids': evidence['lock_wait']['blockers'],
            'saver_pid': evidence['saver_pid'], 'writer_pid': evidence['writer_pid'],
            'previous_candidates': 0, 'first_candidates': expected,
            'next_candidates': len(recommendations), 'status_after_repair': second['status'],
            'synthetic_model_calls_per_generation': 1, 'source_audit_guards': True,
        }), flush=True)

    def test_repair_commits_first_final_gate_waits_and_rejects_first_held_candidate(self):
        evidence = self.run_interleaving(writer_first=True)
        self.assert_result_and_regenerate(evidence, expected=0)

    def test_save_commits_first_real_repair_waits_then_saved_history_can_carry(self):
        evidence = self.run_interleaving(writer_first=False)
        self.assert_result_and_regenerate(evidence, expected=1)

    def test_final_gate_allows_legacy_analysis_first_evaluation_foreign_key(self):
        """Exact old lock order, not execution of the historical app or POST.

        Legacy transaction: analysis FOR UPDATE -> evaluation INSERT/FK.
        New saver: real Vehicle NO KEY UPDATE -> real finish/analysis FOR UPDATE.
        The FK KEY SHARE must remain compatible with the saver's Vehicle gate.
        """
        from dkss_app import analysis, common
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        from dkss_app.priority_confirmed_projection import finalize_confirmed_priority_candidates
        from vehicle_analysis_repository import VehicleAnalysisJobRepository

        def repository():
            return VehicleAnalysisJobRepository(
                db=self.db, state_model=self.models.VehicleKarteAnalysis,
                vehicle_model=self.models.Vehicle)

        # Seed a genuinely source-backed current proposal, so the synthetic
        # legacy writer inserts a complete, valid evaluation of a saved item.
        vehicle = self.models.Vehicle.query.filter_by(company_code='A', id=self.vehicle_id).one()
        with self.app.test_request_context('/'):
            payload, sources = analysis.get_vehicle_karte_analysis_job_data(vehicle)
        generated = finalize_confirmed_priority_candidates(
            {'overview': 'LEGACY-EVALUATION-BASELINE', 'recommendations': []}, payload)
        self.assertEqual(len(generated['recommendations']), 1)
        selected = generated['recommendations'][0]
        key, revision = vehicle_analysis_proposal_ids(selected)
        prior_bundle = {
            'analysis': generated, 'sources': sources, 'fingerprints': payload['_fingerprints'],
            'analysis_method': 'ai', 'generated_at': 'SYNTHETIC-LEGACY-BASELINE',
        }
        prior_json = json.dumps(prior_bundle, ensure_ascii=False, default=str)
        state = self.models.VehicleKarteAnalysis.query.filter_by(
            company_code='A', vehicle_record_id=self.vehicle_id, id=self.state_id).one()
        state.result_json = prior_json
        self.db.session.commit()
        token = 'source-gate-fk-owner'
        now = datetime.now(timezone.utc)
        self.assertTrue(repository().claim(self.state_id, self.original_hash, token, now))
        self.db.session.remove()
        final_bundle = deepcopy(prior_bundle)
        final_bundle['analysis']['overview'] = 'SYNTHETIC-FINAL-SAVE'

        state_locked, gate_acquired, insert_allowed, inserted, commit_allowed = (
            threading.Event() for _ in range(5))
        saver_done = threading.Event()
        evidence, errors, results = {}, [], []

        def bounded_wait(signal, name):
            if not signal.wait(8):
                raise RuntimeError(f'legacy-fk-test-timeout:{name}')

        def legacy_order_writer():
            with self.app.app_context():
                try:
                    evidence['legacy_pid'], evidence['legacy_tx'] = self.mark_backend('analysis_legacy_fk_writer')
                    locked = self.models.VehicleKarteAnalysis.query.filter_by(
                        company_code='A', vehicle_record_id=self.vehicle_id,
                        id=self.state_id).with_for_update().one()
                    self.assertEqual((locked.result_json, locked.lease_token), (prior_json, token))
                    state_locked.set()
                    bounded_wait(insert_allowed, 'insert-allowed')
                    evaluation = self.models.VehicleAnalysisEvaluation(
                        company_code='A', vehicle_record_id=self.vehicle_id,
                        proposal_key=key, proposal_revision=revision,
                        verdict='appropriate', comment='Synthetic legacy lock-order compatibility',
                        created_by='admin', created_at=now.strftime('%Y/%m/%d %H:%M'),
                        snapshot_json=json.dumps({
                            'proposal': selected, 'generated_at': prior_bundle['generated_at'],
                            'analysis_method': 'ai', 'fingerprints': payload['_fingerprints'],
                            'sources': {source_id: source for source_id, source in sources.items()
                                        if source_id in selected['source_ids']},
                        }, ensure_ascii=False))
                    self.db.session.add(evaluation)
                    # Flush performs the real Vehicle FK check while the saver
                    # retains its gate and still waits on our analysis row.
                    self.db.session.flush()
                    evidence['evaluation_id'] = evaluation.id
                    self.assertEqual(self.db.session.scalar(text('SELECT txid_current()')),
                                     evidence['legacy_tx'])
                    self.assertFalse(saver_done.is_set())
                    inserted.set()
                    bounded_wait(commit_allowed, 'legacy-commit')
                    self.db.session.commit()
                    evidence['legacy_committed'] = True
                except Exception:
                    errors.append(traceback.format_exc())
                finally:
                    self.db.session.rollback()
                    self.db.session.remove()

        def saver():
            with self.app.app_context():
                try:
                    repo = repository()
                    evidence['saver_pid'], evidence['saver_tx'] = self.mark_backend('analysis_legacy_fk_saver')
                    locked_vehicle = repo.lock_vehicle_for_finish('A', self.vehicle_id)
                    self.assertIsNotNone(locked_vehicle)
                    self.assertEqual((locked_vehicle.company_code, locked_vehicle.id), ('A', self.vehicle_id))
                    self.assertEqual(self.db.session.scalar(text('SELECT txid_current()')),
                                     evidence['saver_tx'])
                    gate_acquired.set()
                    # Real finish takes the analysis row and commits the same
                    # transaction that owns the real final Vehicle gate.
                    finish_connection = self.db.session.connection()
                    gate_transaction = finish_connection.get_transaction()
                    def capture_finish_sql(connection, cursor, statement, parameters, context, executemany):
                        normalized = ' '.join(statement.lower().split())
                        if normalized.startswith('select ') and 'from vehicle_karte_analysis ' in normalized:
                            self.assertIs(connection, finish_connection)
                            self.assertIs(connection.get_transaction(), gate_transaction)
                            evidence['finish_sql'] = statement
                    # pg_stat_activity.query may truncate before FOR UPDATE.
                    # Capture the actual execute on this connection, without
                    # issuing SQL or changing the statement/parameters.
                    event.listen(finish_connection, 'before_cursor_execute', capture_finish_sql)
                    try:
                        results.append(repo.finish(
                            self.state_id, token, claimed_hash=self.original_hash,
                            snapshot_hash=self.original_hash, bundle=final_bundle,
                            finished=now, method='ai'))
                    finally:
                        event.remove(finish_connection, 'before_cursor_execute', capture_finish_sql)
                except Exception:
                    errors.append(traceback.format_exc())
                finally:
                    saver_done.set()
                    self.db.session.rollback()
                    self.db.session.remove()

        legacy = threading.Thread(target=legacy_order_writer, name='legacy-evaluation-writer', daemon=True)
        saving = threading.Thread(target=saver, name='legacy-compatible-saver', daemon=True)
        with patch.object(common, 'analyze_vehicle_karte') as model:
            try:
                legacy.start()
                self.assertTrue(state_locked.wait(5), errors)
                saving.start()
                self.assertTrue(gate_acquired.wait(3), errors)
                evidence['lock_wait'] = self.wait_for_blocked(
                    evidence['saver_pid'], evidence['legacy_pid'], 'analysis_legacy_fk_saver',
                    'from vehicle_karte_analysis', executed_sql=lambda: evidence['finish_sql'])
                self.assertIn('for update', evidence['finish_sql'].lower())
                self.assertIn('lease_token', evidence['finish_sql'].lower())
                insert_allowed.set()
                self.assertTrue(inserted.wait(2), errors)
                # The actual INSERT completed before either transaction was
                # released; the saver must still be blocked by this writer.
                evidence['wait_after_insert'] = self.wait_for_blocked(
                    evidence['saver_pid'], evidence['legacy_pid'], 'analysis_legacy_fk_saver',
                    'from vehicle_karte_analysis', executed_sql=lambda: evidence['finish_sql'])
                self.assertFalse(saver_done.is_set())
                with self.db.engine.connect() as connection:
                    writer_wait = connection.execute(text("""
                        SELECT wait_event_type FROM pg_stat_activity
                        WHERE datname=current_database() AND pid=:pid
                          AND application_name='analysis_legacy_fk_writer'
                    """), {'pid': evidence['legacy_pid']}).scalar_one()
                self.assertNotEqual(writer_wait, 'Lock')
                commit_allowed.set()
            finally:
                insert_allowed.set()
                commit_allowed.set()
                for thread in (legacy, saving):
                    if thread.ident is not None:
                        thread.join(12)
            self.assertFalse(legacy.is_alive(), 'Legacy writer exceeded finite cleanup')
            self.assertFalse(saving.is_alive(), 'Saver exceeded finite cleanup')
            model.assert_not_called()
        self.assertEqual(errors, [])
        self.assertTrue(evidence.get('legacy_committed'))
        self.assertEqual(results, [True])
        after = self.read_committed()
        self.assertEqual(after['job_status'], 'completed')
        self.assertIsNone(after['lease_token'])
        self.assertEqual(after['result_json'], json.dumps(final_bundle, ensure_ascii=False, default=str))
        self.assertEqual(after['sources'], self.before['sources'])
        with self.app.app_context():
            evaluation = self.models.VehicleAnalysisEvaluation.query.filter_by(
                company_code='A', vehicle_record_id=self.vehicle_id,
                id=evidence['evaluation_id']).one()
            self.assertEqual((evaluation.proposal_key, evaluation.proposal_revision, evaluation.verdict),
                             (key, revision, 'appropriate'))
            self.assertEqual(json.loads(evaluation.snapshot_json)['proposal'], selected)
            self.db.session.remove()
        self.assertEqual(self.foreign_snapshot(), self.foreign_before)
        print('ANALYSIS_SOURCE_GATE_LEGACY_FK_ACCEPTANCE', json.dumps({
            'scope': 'low-level-legacy-lock-order-only-not-rollback-http',
            'saver_pid': evidence['saver_pid'], 'legacy_pid': evidence['legacy_pid'],
            'observed_wait_event_type': evidence['lock_wait']['wait_event_type'],
            'evaluation_flushed_while_saver_waited': True,
            'legacy_committed': True, 'final_save_committed': True, 'model_calls': 0,
        }), flush=True)


if __name__ == '__main__':
    unittest.main()
