"""Queued-generation row fences on the owned official PostgreSQL service only."""
from datetime import datetime, timedelta, timezone
import threading
import unittest
from sqlalchemy import text
import test_analysis_worker_postgres as fixture


class QueuedGenerationPostgresTests(unittest.TestCase):
    setUpClass = classmethod(fixture.AnalysisWorkerPostgresTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.AnalysisWorkerPostgresTests.tearDownClass.__func__)
    setUp = fixture.AnalysisWorkerPostgresTests.setUp
    tearDown = fixture.AnalysisWorkerPostgresTests.tearDown
    repository = fixture.AnalysisWorkerPostgresTests.repository
    wait_for_blocked = fixture.AnalysisWorkerPostgresTests.wait_for_blocked

    def blocked_generation_change(self, operation):
        now = datetime.now(timezone.utc)
        deadline = now+timedelta(seconds=40)
        previous = '{ "analysis": { "overview": "previous byte exact" } }'
        analyzed_at = now-timedelta(days=1)
        self.models.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
            'status':'running', 'lease_token':'old-owner', 'lease_expires_at':now+timedelta(minutes=3),
            'result_json':previous, 'last_analyzed_at':analyzed_at, 'last_error':'previous error'})
        self.db.session.commit(); self.db.session.remove()
        cached, held, start, release = (threading.Event() for _ in range(4))
        results, errors = [], []
        name = 'analysis_generation_' + operation
        def saver():
            with self.app.app_context():
                try:
                    self.db.session.execute(text("SELECT set_config('application_name', :name, false)"), {'name': name})
                    old = self.db.session.get(self.models.VehicleKarteAnalysis, self.state_id)
                    self.assertEqual(old.input_hash, 'old')
                    cached.set()
                    if not start.wait(5): raise RuntimeError('start-timeout')
                    repo = self.repository()
                    if operation == 'finish':
                        results.append(repo.finish(self.state_id, 'old-owner', claimed_hash='old', snapshot_hash='old',
                            bundle={'analysis':{'overview':'obsolete'}}, finished=now, method='ai'))
                    else:
                        results.append(repo.fail(self.state_id, 'old-owner', 'old failure', now+timedelta(hours=1), claimed_hash='old'))
                except Exception as error:
                    errors.append((type(error).__name__, str(error)))
                finally:
                    self.db.session.rollback(); self.db.session.remove()
        def queue():
            with self.app.app_context():
                try:
                    vehicle = self.db.session.get(self.models.Vehicle, self.vehicle_id)
                    state = self.repository().get_or_create(vehicle)
                    state.input_hash = 'new-generation'
                    state.next_analysis_at = deadline
                    state.request_reason = 'new-generation-reason'
                    self.db.session.flush()
                    held.set()
                    if not release.wait(8): raise RuntimeError('release-timeout')
                    self.db.session.commit()
                except Exception as error:
                    errors.append((type(error).__name__, str(error)))
                finally:
                    self.db.session.rollback(); self.db.session.remove()
        saving = threading.Thread(target=saver); queuing = threading.Thread(target=queue)
        saving.start()
        try:
            self.assertTrue(cached.wait(5))
            queuing.start(); self.assertTrue(held.wait(5)); start.set()
            self.wait_for_blocked(name)
        finally:
            release.set(); start.set()
            saving.join(10)
            if queuing.ident is not None: queuing.join(10)
        self.assertFalse(saving.is_alive()); self.assertFalse(queuing.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [False] if operation == 'finish' else [True])
        state = self.db.session.get(self.models.VehicleKarteAnalysis, self.state_id)
        self.assertEqual((state.status, state.input_hash, state.request_reason),
                         ('pending','new-generation','new-generation-reason'))
        self.assertEqual(state.result_json, previous)
        self.assertEqual(state.last_analyzed_at, analyzed_at)
        self.assertEqual(state.next_analysis_at, deadline)
        self.assertEqual(state.last_error, 'previous error')
        self.assertIsNone(state.lease_token); self.assertIsNone(state.lease_expires_at)

    def test_final_save_waits_for_new_generation_and_refreshes_cached_row(self):
        self.blocked_generation_change('finish')

    def test_old_failure_waits_for_new_generation_and_preserves_new_deadline(self):
        self.blocked_generation_change('fail')
