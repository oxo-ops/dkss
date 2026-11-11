"""Opt-in disposable PostgreSQL checks. Never accept an arbitrary database URL."""
from datetime import datetime, timedelta, timezone
import json
import os
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import text
import time


class AnalysisWorkerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = os.environ.get('ANALYSIS_RUNTIME_POSTGRES_TEST_URL', '')
        if not raw:
            if os.environ.get('ANALYSIS_RUNTIME_REQUIRE_POSTGRES') == '1':
                raise AssertionError('Explicit disposable analysis PostgreSQL URL required')
            raise unittest.SkipTest('Disposable analysis PostgreSQL not configured')
        from analysis_runtime_ci_support import verify_owned_service, CONNECT_ARGS
        verify_owned_service(raw, os.environ)
        from dkss_app import create_app
        from dkss_app.extensions import db
        from dkss_app import models
        cls.db, cls.models = db, models
        with patch.dict(os.environ, {'SECRET_KEY': 'synthetic-analysis-ci', 'S3_BUCKET_NAME': '',
                'RENDER': '', 'RATELIMIT_STORAGE_URI': 'memory://', 'OPENAI_API_KEY': '',
                'DOCUMENT_IMPORT_WORKER_ENABLED': '0', 'VEHICLE_ANALYSIS_WORKER_ENABLED': '0'}):
            cls.app = create_app({'SQLALCHEMY_DATABASE_URI': raw, 'TESTING': True,
                'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': CONNECT_ARGS}})

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            cls.db.session.remove(); cls.db.engine.dispose()

    def setUp(self):
        self.context = self.app.app_context(); self.context.push()
        self.db.drop_all(); self.db.create_all()
        self.db.session.add(self.models.Company(company_code='TEST', company_name='Synthetic', active=True))
        self.vehicle = self.models.Vehicle(company_code='TEST', chassis_number='ANALYSIS-CI')
        self.db.session.add(self.vehicle); self.db.session.flush()
        self.state = self.models.VehicleKarteAnalysis(company_code='TEST', vehicle_record_id=self.vehicle.id,
            status='pending', input_hash='old', next_analysis_at=datetime.now(timezone.utc)-timedelta(minutes=1))
        self.db.session.add(self.state); self.db.session.commit()
        self.state_id, self.vehicle_id = self.state.id, self.vehicle.id
        self.db.session.remove()

    def tearDown(self):
        self.db.session.remove(); self.context.pop()

    def repository(self):
        from vehicle_analysis_repository import VehicleAnalysisJobRepository
        return VehicleAnalysisJobRepository(db=self.db, state_model=self.models.VehicleKarteAnalysis,
            vehicle_model=self.models.Vehicle)

    def test_two_database_sessions_have_one_leader_and_release_on_exit(self):
        from dkss_app.analysis_worker import leadership
        with leadership(self.app) as first:
            self.assertIsNotNone(first); first.check()
            with leadership(self.app) as second:
                self.assertIsNone(second)
        with leadership(self.app) as next_owner:
            self.assertIsNotNone(next_owner)

    def test_disconnected_leader_fails_closed_and_can_be_replaced(self):
        from dkss_app.analysis_worker import leadership
        with leadership(self.app) as first:
            first.connection.invalidate()
            with self.assertRaisesRegex(RuntimeError, 'LEADERSHIP_LOST'):
                first.check()
            with leadership(self.app) as second:
                self.assertIsNotNone(second)

    def test_exception_releases_leadership(self):
        from dkss_app.analysis_worker import leadership
        with self.assertRaisesRegex(ValueError, 'synthetic'):
            with leadership(self.app):
                raise ValueError('synthetic')
        with leadership(self.app) as owner:
            self.assertIsNotNone(owner)

    def test_simultaneous_claims_only_one_wins(self):
        barrier = threading.Barrier(2)
        results, errors = [], []
        def run(token):
            with self.app.app_context():
                try:
                    barrier.wait(timeout=5)
                    results.append(self.repository().claim(self.state_id, 'old', token, datetime.now(timezone.utc)))
                except Exception as error:
                    errors.append(type(error).__name__)
                finally:
                    self.db.session.remove()
        threads = [threading.Thread(target=run, args=(token,)) for token in ('first', 'second')]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, []); self.assertEqual(sorted(results), [False, True])

    def wait_for_blocked(self, name):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.db.engine.connect() as connection:
                blocked = connection.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE application_name=:name AND wait_event_type='Lock'"), {'name': name})
            if blocked:
                return
            time.sleep(0.02)
        self.fail('Expected PostgreSQL lock wait was never observed')

    def test_queue_lock_serializes_a_competing_claim_without_clobbering_token(self):
        locked, claim_started, release = threading.Event(), threading.Event(), threading.Event()
        results, errors = [], []
        def queue():
            with self.app.app_context():
                try:
                    vehicle = self.db.session.get(self.models.Vehicle, self.vehicle_id)
                    state = self.repository().get_or_create(vehicle)
                    locked.set()
                    if not release.wait(5): raise RuntimeError('test-release-timeout')
                    state.input_hash = 'new'
                    self.db.session.commit()
                except Exception as error:
                    errors.append(type(error).__name__)
                finally:
                    self.db.session.remove()
        def claim():
            with self.app.app_context():
                try:
                    self.db.session.execute(text("SET application_name='analysis_claim_waiter'"))
                    claim_started.set()
                    results.append(self.repository().claim(self.state_id, 'old', 'claimant', datetime.now(timezone.utc)))
                except Exception as error:
                    errors.append(type(error).__name__)
                finally:
                    self.db.session.remove()
        first = threading.Thread(target=queue); first.start()
        self.assertTrue(locked.wait(5))
        second = threading.Thread(target=claim); second.start()
        self.assertTrue(claim_started.wait(5))
        try:
            self.wait_for_blocked('analysis_claim_waiter')
        finally:
            release.set()
        first.join(10); second.join(10)
        self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive())
        self.assertEqual(errors, []); self.assertEqual(results, [False])
        state = self.db.session.get(self.models.VehicleKarteAnalysis, self.state_id)
        self.assertEqual(state.input_hash, 'new'); self.assertIsNone(state.lease_token)

    def test_queue_waits_for_claim_then_preserves_fresh_running_token(self):
        from vehicle_analysis_service import snapshot_hash
        from dkss_app.analysis import queue_vehicle_karte_analysis
        held, release = threading.Event(), threading.Event()
        errors = []
        now = datetime.now(timezone.utc)
        payload = {'_fingerprints': {'policy_version': 1, 'important_hash': 'new', 'routine_hash': 'new'}}
        # An expired running owner makes stale queue writes genuinely dangerous:
        # without FOR UPDATE they would dirty status/token and clear the new claim.
        self.models.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
            'status': 'running', 'lease_token': 'expired-owner',
            'lease_expires_at': now-timedelta(minutes=1)}, synchronize_session=False)
        self.db.session.commit(); self.db.session.remove()
        def claim():
            with self.app.app_context():
                try:
                    self.models.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
                        'status': 'running', 'lease_token': 'claim-owner',
                        'lease_expires_at': now+timedelta(minutes=3)}, synchronize_session=False)
                    held.set()
                    if not release.wait(8): raise RuntimeError('test-release-timeout')
                    self.db.session.commit()
                except Exception as error:
                    errors.append(type(error).__name__)
                finally:
                    self.db.session.remove()
        def queue():
            with self.app.app_context():
                try:
                    self.db.session.execute(text("SET application_name='analysis_queue_waiter'"))
                    vehicle = self.db.session.get(self.models.Vehicle, self.vehicle_id)
                    queue_vehicle_karte_analysis(vehicle, payload)
                    self.db.session.commit()
                except Exception as error:
                    errors.append(type(error).__name__)
                finally:
                    self.db.session.remove()
        first = threading.Thread(target=claim); first.start()
        self.assertTrue(held.wait(5))
        second = threading.Thread(target=queue); second.start()
        try:
            self.wait_for_blocked('analysis_queue_waiter')
        finally:
            release.set()
        first.join(10); second.join(10)
        self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        state = self.db.session.get(self.models.VehicleKarteAnalysis, self.state_id)
        self.assertEqual(state.input_hash, snapshot_hash(payload['_fingerprints']))
        self.assertEqual((state.status, state.lease_token), ('running', 'claim-owner'))

    def test_expired_owner_cannot_save_or_fail_new_owner(self):
        now = datetime.now(timezone.utc)
        repo = self.repository()
        self.models.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
            'next_analysis_at': now-timedelta(minutes=10)}, synchronize_session=False)
        self.db.session.commit()
        self.assertTrue(repo.claim(self.state_id, 'old', 'old-owner', now-timedelta(minutes=5)))
        self.assertTrue(repo.claim(self.state_id, 'old', 'new-owner', now))
        self.assertFalse(repo.finish(self.state_id, 'old-owner', claimed_hash='old', snapshot_hash='old',
            bundle={'analysis': {'overview': 'stale'}}, finished=now, method='ai'))
        repo.fail(self.state_id, 'old-owner', 'stale-error', now+timedelta(hours=1), claimed_hash='old')
        state = self.db.session.get(self.models.VehicleKarteAnalysis, self.state_id)
        self.assertEqual(state.lease_token, 'new-owner'); self.assertEqual(state.status, 'running')
        self.assertEqual(json.loads(state.result_json), {})


if __name__ == '__main__':
    unittest.main()
