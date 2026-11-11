"""Queued input generations: real job/service/reconcile/repository, synthetic AI."""
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

import test_vehicle_analysis_service as fixture
from vehicle_analysis_service import snapshot_hash


class QueuedGenerationFenceTests(unittest.TestCase):
    setUpClass = classmethod(fixture.AnalysisServiceDatabaseTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.AnalysisServiceDatabaseTests.tearDownClass.__func__)
    tearDown = fixture.AnalysisServiceDatabaseTests.tearDown
    state = fixture.AnalysisServiceDatabaseTests.state
    run_job = fixture.AnalysisServiceDatabaseTests.run_job

    def setUp(self):
        fixture.AnalysisServiceDatabaseTests.setUp(self)
        self.previous = '{ "analysis": {"overview": "previous byte exact", "recommendations": []}, "private_proof": "synthetic" }'
        self.previous_at = fixture.NOW-timedelta(days=1)
        state = self.state()
        state.result_json = self.previous
        state.last_analyzed_at = self.previous_at
        state.last_error = 'previous error'
        self.m.db.session.commit()

    def newer_generation(self):
        self.m.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
            'input_hash': 'new-generation', 'next_analysis_at': fixture.NOW+timedelta(seconds=45),
            'request_reason': 'new-generation-reason'})
        self.m.db.session.commit()

    def assert_preserved_new_generation(self):
        state = self.state()
        self.assertEqual(state.result_json, self.previous)
        self.assertEqual(fixture.aware(state.last_analyzed_at), self.previous_at)
        self.assertEqual(state.last_error, 'previous error')
        self.assertEqual((state.status, state.input_hash, state.request_reason),
                         ('pending', 'new-generation', 'new-generation-reason'))
        self.assertEqual(fixture.aware(state.next_analysis_at), fixture.NOW+timedelta(seconds=45))
        self.assertIsNone(state.lease_token); self.assertIsNone(state.lease_expires_at)

    def test_new_generation_immediately_after_real_reconcile_rejects_save(self):
        from dkss_app import priority_confirmed_projection as projection
        real = projection.reconcile_confirmed_candidates_before_save
        calls = []
        def reconcile(*args, **kwargs):
            result = real(*args, **kwargs)
            calls.append('real-reconcile-finished')
            self.newer_generation()
            return result
        with patch.object(projection, 'reconcile_confirmed_candidates_before_save', side_effect=reconcile):
            self.assertFalse(self.run_job()[0])
        self.assertEqual(calls, ['real-reconcile-finished'])
        self.assert_preserved_new_generation()

    def test_new_generation_then_exception_after_real_reconcile_keeps_new_deadline(self):
        from dkss_app import priority_confirmed_projection as projection
        real = projection.reconcile_confirmed_candidates_before_save
        def reconcile(*args, **kwargs):
            real(*args, **kwargs)
            self.newer_generation()
            raise ValueError('old-generation-error-must-not-be-stored')
        with patch.object(projection, 'reconcile_confirmed_candidates_before_save', side_effect=reconcile), \
                self.assertLogs(self.m.app.logger, 'WARNING'):
            self.assertFalse(self.run_job()[0])
        self.assert_preserved_new_generation()

    def test_input_load_error_before_signature_uses_original_claim_hash(self):
        def load(vehicle):
            self.newer_generation()
            raise ValueError('synthetic-load-failure')
        with patch.object(self.m, 'datetime') as clock, \
                patch.object(self.m, 'get_vehicle_karte_analysis_job_data', side_effect=load), \
                patch.object(self.m, 'analyze_vehicle_karte') as ai, self.assertLogs(self.m.app.logger, 'WARNING'):
            clock.now.return_value = fixture.NOW
            self.assertFalse(self.m.run_vehicle_karte_analysis_job(self.state_id))
        ai.assert_not_called(); self.assert_preserved_new_generation()

    def test_snapshot_newer_than_claim_can_save_when_queue_matches_generated_snapshot(self):
        payload = dict(self.payload, _fingerprints=fixture.fingerprints(important='new-before-load'))
        def load(vehicle):
            self.m.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
                'input_hash': snapshot_hash(payload['_fingerprints'])})
            self.m.db.session.commit()
            return payload, {}
        with patch.object(self.m, 'datetime') as clock, \
                patch.object(self.m, 'get_vehicle_karte_analysis_job_data', side_effect=load), \
                patch.object(self.m, 'analyze_vehicle_karte', return_value={'overview':'current snapshot', 'recommendations':[]}):
            clock.now.return_value = fixture.NOW
            self.assertTrue(self.m.run_vehicle_karte_analysis_job(self.state_id))
        self.assertEqual(self.state().status, 'completed')
        self.assertEqual(json.loads(self.state().result_json)['analysis']['overview'], 'current snapshot')
        self.assertEqual(self.state().input_hash, snapshot_hash(payload['_fingerprints']))

    def test_same_snapshot_failure_retains_previous_result_and_one_hour_retry(self):
        def ai(payload, on_progress):
            raise ValueError('same-generation-failure')
        with self.assertLogs(self.m.app.logger, 'WARNING'):
            self.assertFalse(self.run_job(ai)[0])
        state = self.state()
        self.assertEqual(state.result_json, self.previous)
        self.assertEqual(fixture.aware(state.last_analyzed_at), self.previous_at)
        self.assertEqual(state.status, 'error')
        self.assertEqual(fixture.aware(state.next_analysis_at), fixture.NOW+timedelta(hours=1))
        self.assertIn('same-generation-failure', state.last_error)

    def test_newer_lease_owner_is_untouched_on_success_and_failure(self):
        def replace_owner():
            self.m.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
                'lease_token':'replacement', 'input_hash':'replacement-input',
                'next_analysis_at':fixture.NOW+timedelta(seconds=10), 'result_json':'{"replacement":true}'})
            self.m.db.session.commit()
        def ai(payload, on_progress):
            replace_owner()
            return {'overview':'old', 'recommendations':[]}
        self.assertFalse(self.run_job(ai)[0])
        state = self.state()
        self.assertEqual((state.lease_token, state.input_hash, state.result_json),
                         ('replacement','replacement-input','{"replacement":true}'))
        from vehicle_analysis_repository import VehicleAnalysisJobRepository
        repository = VehicleAnalysisJobRepository(db=self.m.db, state_model=self.m.VehicleKarteAnalysis, vehicle_model=self.m.Vehicle)
        self.assertFalse(repository.fail(self.state_id, 'obsolete', 'old-error', fixture.NOW+timedelta(hours=1), claimed_hash='old'))
        self.assertEqual(self.state().lease_token, 'replacement')
        self.assertEqual(fixture.aware(self.state().next_analysis_at), fixture.NOW+timedelta(seconds=10))

    def test_generated_snapshot_failure_is_not_mistaken_for_newer_queued_work(self):
        payload = dict(self.payload, _fingerprints=fixture.fingerprints(important='new-before-load'))
        def ai(value, on_progress):
            self.m.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
                'input_hash':snapshot_hash(payload['_fingerprints'])})
            self.m.db.session.commit()
            raise ValueError('failed-generated-snapshot')
        with self.assertLogs(self.m.app.logger, 'WARNING'):
            self.assertFalse(self.run_job(ai, payload=payload)[0])
        self.assertEqual(self.state().status, 'error')
        self.assertEqual(fixture.aware(self.state().next_analysis_at), fixture.NOW+timedelta(hours=1))
        self.assertEqual(self.state().result_json, self.previous)


import test_priority_candidate_completion as completion


class RealConfirmationGenerationFenceTests(unittest.TestCase):
    setUpClass = classmethod(completion.CandidateCompletionTests.setUpClass.__func__)
    tearDownClass = classmethod(completion.CandidateCompletionTests.tearDownClass.__func__)
    setUp = completion.CandidateCompletionTests.setUp
    tearDown = completion.CandidateCompletionTests.tearDown
    login = completion.CandidateCompletionTests.login
    request = completion.CandidateCompletionTests.request
    save = completion.CandidateCompletionTests.save
    complete = completion.CandidateCompletionTests.complete
    state = completion.CandidateCompletionTests.state
    decision_data = completion.CandidateCompletionTests.decision_data
    decide = completion.CandidateCompletionTests.decide
    snapshot = completion.CandidateCompletionTests.snapshot
    refs = completion.CandidateCompletionTests.refs
    clock = completion.CandidateCompletionTests.clock
    begin = completion.CandidateCompletionTests.begin
    repair = completion.CandidateCompletionTests.repair
    prepare_pair = completion.CandidateCompletionTests.prepare_pair
    confirm = completion.CandidateCompletionTests.confirm
    load = completion.CandidateCompletionTests.load
    cancel = completion.CandidateCompletionTests.cancel

    def test_real_cancel_then_real_queue_after_reconcile_preserves_previous_bundle_and_audit(self):
        from datetime import datetime, timezone
        from dkss_app import analysis, common, priority_confirmed_projection as projection
        self.prepare_pair(); event_id, _ = self.confirm()
        payload, sources = self.load()
        previous = {'analysis':completion.finish({'overview':'previous saved', 'recommendations':[]}, payload),
            'sources':sources, 'fingerprints':payload['_fingerprints'], 'comparison':payload['comparison'],
            'coverage':payload['coverage'], 'generated_at':'previous time', 'analysis_method':'ai'}
        previous_json = json.dumps(previous, ensure_ascii=False)
        state = self.models.VehicleKarteAnalysis(company_code='A', vehicle_record_id=self.vehicle.id,
            status='pending', input_hash=snapshot_hash(payload['_fingerprints']), result_json=previous_json,
            next_analysis_at=datetime.now(timezone.utc)-timedelta(seconds=1))
        self.db.session.add(state); self.db.session.commit()
        state_id, vehicle_id = state.id, self.vehicle.id
        expected = {}
        def audit_rows():
            return [(r.id, r.detail_json) for r in self.models.ChecklistEvent.query.order_by(self.models.ChecklistEvent.id).all()]
        real = projection.reconcile_confirmed_candidates_before_save
        def reconcile(*args, **kwargs):
            generated = real(*args, **kwargs)
            self.assertEqual(len(generated['recommendations']), 1)
            with self.app.app_context():
                self.cancel(event_id)
                vehicle = self.db.session.get(self.models.Vehicle, vehicle_id)
                with self.app.test_request_context('/'):
                    fresh, _ = analysis.get_vehicle_karte_analysis_job_data(vehicle)
                analysis.queue_vehicle_karte_analysis(vehicle, fresh)
                self.db.session.commit()
                queued = self.db.session.get(self.models.VehicleKarteAnalysis, state_id)
                expected.update(hash=queued.input_hash, due=queued.next_analysis_at, reason=queued.request_reason,
                    audit=audit_rows(), original=self.db.session.get(type(self.row), self.row.id).operation_judgment_json)
                self.assertNotEqual(queued.input_hash, snapshot_hash(payload['_fingerprints']))
            return generated
        def synthetic_model(payload, on_progress=None):
            if on_progress: on_progress()
            return {'overview':'obsolete generated text', 'recommendations':[]}
        with patch.object(common, 'analyze_vehicle_karte', side_effect=synthetic_model) as ai, \
                patch.object(projection, 'reconcile_confirmed_candidates_before_save', side_effect=reconcile):
            self.assertFalse(analysis.run_vehicle_karte_analysis_job(state_id))
        ai.assert_called_once()
        self.db.session.expire_all()
        saved = self.db.session.get(self.models.VehicleKarteAnalysis, state_id)
        self.assertEqual(saved.result_json, previous_json)
        self.assertEqual((saved.status, saved.input_hash, saved.next_analysis_at, saved.request_reason),
                         ('pending', expected['hash'], expected['due'], expected['reason']))
        self.assertEqual(audit_rows(), expected['audit'])
        self.assertEqual(self.db.session.get(type(self.row), self.row.id).operation_judgment_json, expected['original'])
        response = self.client.get(f'/vehicle/karte/{vehicle_id}/analysis/result')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['is_current'])
        self.assertEqual(response.json['analysis']['recommendations'], [])
        self.assertEqual(response.json['analysis']['overview'], 'previous saved')
