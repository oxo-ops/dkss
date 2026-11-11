"""Bounded automatic runtime, with synthetic input/provider and disposable DB only."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
import threading
from zoneinfo import ZoneInfo
import unittest
from unittest.mock import MagicMock, Mock, patch

from flask import Flask
from dkss_app import analysis_worker as worker
import test_workflow_regressions as workflow
import test_priority_candidate_completion as completion


class WorkerLifecycleTests(unittest.TestCase):
    def test_default_off_invalid_and_testing_never_start(self):
        app = Flask('analysis-default-off')
        with patch('dkss_app.analysis_worker.threading.Thread') as thread:
            for value in ('', '0', 'true', '2'):
                with patch.dict(os.environ, {'VEHICLE_ANALYSIS_WORKER_ENABLED': value}):
                    worker.start_worker(app)
            app.testing = True
            with patch.dict(os.environ, {'VEHICLE_ANALYSIS_WORKER_ENABLED': '1'}):
                worker.start_worker(app)
            thread.assert_not_called()
        self.assertNotIn('vehicle_analysis_worker', app.extensions)

    def test_one_thread_and_cooperative_stop(self):
        app = Flask('analysis-one-thread')
        with patch.dict(os.environ, {'VEHICLE_ANALYSIS_WORKER_ENABLED': '1'}), \
                patch('dkss_app.analysis_worker.threading.Thread') as thread:
            thread.return_value.is_alive.return_value = True
            worker.start_worker(app); worker.start_worker(app)
            thread.assert_called_once()
            self.assertTrue(thread.call_args.kwargs['daemon'])
            worker.stop_worker(app)
            self.assertTrue(app.extensions['vehicle_analysis_worker']['stop'].is_set())

    def test_gunicorn_keeps_existing_hooks_and_starts_stops_analysis(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('analysis_gunicorn_test',
            Path(__file__).resolve().parents[1] / 'gunicorn.conf.py')
        config = importlib.util.module_from_spec(spec); spec.loader.exec_module(config)
        app = Flask('gunicorn-analysis')
        with patch('dkss_app.driving_access.initialize_driving_access') as driving, \
                patch('dkss_app.vehicle_couplings.initialize_coupling_schema') as coupling, \
                patch('dkss_app.document_import_worker.start_worker') as ocr_start, \
                patch('dkss_app.document_import_worker.stop_worker') as ocr_stop, \
                patch.object(worker, 'start_worker') as analysis_start, \
                patch.object(worker, 'stop_worker') as analysis_stop:
            config.post_worker_init(Mock(wsgi=app)); config.worker_exit(None, Mock(wsgi=app))
            for called in (driving, coupling, ocr_start, ocr_stop, analysis_start, analysis_stop):
                called.assert_called_once_with(app)
        self.assertEqual((config.timeout, config.graceful_timeout), (120, 30))

    def test_fail_closed_without_postgres_and_no_schema_creation(self):
        app = Flask('unsupported-analysis-database')
        database = MagicMock(); database.engine.dialect.name = 'sqlite'
        with patch.object(worker, 'db', database):
            with self.assertRaisesRegex(RuntimeError, 'REQUIRES_POSTGRESQL'):
                with worker.leadership(app):
                    self.fail('unsupported database entered')
            with worker.leadership(app, allow_local=True) as owner:
                owner.check()
        database.engine.connect.assert_not_called()
        database.create_all.assert_not_called()

    def test_postgres_busy_and_release_on_failure_contract(self):
        app = Flask('fake-postgres-leadership')
        database = MagicMock(); database.engine.dialect.name = 'postgresql'
        connection = database.engine.connect.return_value.execution_options.return_value
        connection.invalidated = False; connection.closed = False
        connection.execute.return_value.scalar_one.return_value = False
        with patch.object(worker, 'db', database):
            with worker.leadership(app) as owner:
                self.assertIsNone(owner)
        self.assertEqual(connection.execute.call_count, 1)
        connection.close.assert_called_once()
        connection.reset_mock()
        connection.execute.return_value.scalar_one.return_value = 101
        with patch.object(worker, 'db', database):
            with self.assertRaisesRegex(ValueError, 'synthetic'):
                with worker.leadership(app) as owner:
                    owner.check()
                    raise ValueError('synthetic')
        statements = [str(call.args[0]) for call in connection.execute.call_args_list]
        self.assertIn('SELECT pg_advisory_unlock', statements[-1])
        connection.close.assert_called_once()
        self.assertTrue(all('CREATE ' not in sql and 'ALTER ' not in sql for sql in statements))

    def test_reconnected_backend_cannot_keep_leadership(self):
        connection = MagicMock(); connection.invalidated = False; connection.closed = False
        connection.execute.return_value.scalar_one.side_effect = [101, 102]
        owner = worker.Leadership(connection)
        with self.assertRaisesRegex(RuntimeError, 'LEADERSHIP_LOST'):
            owner.check()

    def test_loop_error_is_sanitized_and_retried(self):
        app = Flask('analysis-diagnostics'); stopped = threading.Event()
        waits = []
        def wait(seconds):
            waits.append(seconds)
            if len(waits) == 2:
                stopped.set()
        stopped.wait = Mock(side_effect=wait)
        with patch.object(worker, 'leadership', side_effect=ValueError('PRIVATE_TEST_VALUE')), \
                patch.object(worker, 'db') as database, self.assertLogs(app.logger, 'INFO') as logs:
            worker.run_worker(app, stopped)
        output = '\n'.join(logs.output)
        self.assertNotIn('PRIVATE_TEST_VALUE', output)
        self.assertIn('ANALYSIS_WORKER_ITERATION_FAILED error_type=ValueError', output)
        stopped.wait.assert_called_with(worker.INTERVAL_SECONDS)
        database.session.remove.assert_called()

    def test_shutdown_finishes_current_pass_and_releases_leadership(self):
        app = Flask('analysis-shutdown'); stopped = threading.Event()
        released = []
        @contextmanager
        def owner(*args, **kwargs):
            try:
                yield Mock()
            finally:
                released.append(True)
        def job(*args, **kwargs):
            stopped.set()
            return 1, 0
        with patch.object(worker, 'leadership', owner), patch.object(worker, 'db'), \
                patch.object(worker, 'scan_batch', return_value=(0, 1, 0)) as scan, \
                patch.object(worker, 'run_due_job', side_effect=job) as run:
            worker.run_worker(app, stopped)
        scan.assert_called_once(); run.assert_called_once()
        self.assertEqual(released, [True])

    def test_leadership_loss_before_pass_never_scans_or_calls_ai(self):
        app = Flask('analysis-leadership-loss'); stopped = threading.Event()
        stopped.wait = Mock(side_effect=lambda *_: stopped.set())
        @contextmanager
        def owner(*args, **kwargs):
            yield Mock(check=Mock(side_effect=RuntimeError('ANALYSIS_LEADERSHIP_LOST')))
        with patch.object(worker, 'leadership', owner), patch.object(worker, 'db'), \
                patch.object(worker, 'scan_batch') as scan, patch.object(worker, 'run_due_job') as run:
            worker.run_worker(app, stopped)
        scan.assert_not_called(); run.assert_not_called()

    def test_busy_cli_does_not_scan_or_generate_and_keeps_public_refresh(self):
        from dkss_app import analysis
        app = Flask('analysis-cli-busy')
        @contextmanager
        def busy(*args, **kwargs):
            yield None
        with app.app_context(), patch.object(worker, 'leadership', busy), \
                patch.object(analysis, '_refresh_analysis_public_knowledge') as public, \
                patch.object(analysis, '_vehicle_karte_analysis_tick_unlocked') as tick:
            analysis.vehicle_karte_analysis_tick()
        public.assert_called_once(); tick.assert_not_called()


class BoundedScanTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def test_keyset_cap_fairness_and_company_deleted_filters(self):
        from dkss_app import analysis
        m = self.m
        m.db.session.add_all([m.Vehicle(company_code='TEST', chassis_number=f'BOUND-{n}') for n in range(23)])
        m.db.session.add(m.Company(company_code='OFF', company_name='Off', active=False))
        m.db.session.add(m.Vehicle(company_code='OFF', chassis_number='INACTIVE'))
        m.db.session.add(m.Vehicle(company_code='TEST', chassis_number='DELETED', deleted=True))
        m.db.session.commit()
        payload = {'_fingerprints': {'policy_version': 1, 'important_hash': 'x', 'routine_hash': 'y'}}
        seen = []
        def load(vehicle):
            seen.append(vehicle.id)
            return payload, {}
        with patch.object(analysis, 'get_vehicle_karte_analysis_job_data', side_effect=load):
            cursor, scanned, errors = worker.scan_batch(m.app, 0)
            self.assertEqual((scanned, errors, len(seen)), (20, 0, 20))
            cursor, scanned, errors = worker.scan_batch(m.app, cursor)
            self.assertEqual((cursor, scanned, errors, len(set(seen))), (0, 4, 0, 24))
        self.assertEqual(m.VehicleKarteAnalysis.query.count(), 24)

    def test_due_job_cap_and_active_lease_are_preserved(self):
        from dkss_app import analysis
        now = datetime.now(timezone.utc)
        for n in range(4):
            vehicle = self.m.Vehicle(company_code='TEST', chassis_number=f'DUE-{n}')
            self.m.db.session.add(vehicle); self.m.db.session.flush()
            self.m.db.session.add(self.m.VehicleKarteAnalysis(company_code='TEST', vehicle_record_id=vehicle.id,
                status='running' if n == 0 else 'pending', next_analysis_at=now-timedelta(minutes=1),
                lease_token='other' if n == 0 else None,
                lease_expires_at=now+timedelta(minutes=3) if n == 0 else None))
        self.m.db.session.commit()
        with patch.object(analysis, 'run_vehicle_karte_analysis_job', return_value=True) as run:
            self.assertEqual(worker.run_due_job(self.m.app), (1, 0))
        run.assert_called_once()
        self.assertNotEqual(run.call_args.args[0], self.m.VehicleKarteAnalysis.query.filter_by(lease_token='other').one().id)


class AutomaticAnalysisWorkflowTests(unittest.TestCase):
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

    def test_normal_confirmation_reaches_saved_result_after_two_minutes_without_another_post(self):
        from dkss_app import analysis
        self.prepare_pair(); self.confirm()
        vehicle_id = self.vehicle.id
        self.assertEqual(self.models.VehicleKarteAnalysis.query.count(), 0)
        now = [datetime.combine(self.day, datetime.min.time(), ZoneInfo('Asia/Tokyo')).replace(hour=12).astimezone(timezone.utc)]
        stopped = threading.Event()
        observations = []
        def wait(seconds):
            self.assertEqual(seconds, 60)
            with self.app.app_context():
                state = self.models.VehicleKarteAnalysis.query.filter_by(vehicle_record_id=vehicle_id).one()
                observations.append(state.status)
            now[0] += timedelta(seconds=seconds)
            if len(observations) == 3:
                stopped.set()
        @contextmanager
        def owner(*args, **kwargs):
            yield worker.LocalOwnership()
        with patch.object(worker, 'leadership', owner), patch.object(stopped, 'wait', wait), \
                patch.object(analysis._dkss_common, 'datetime', wraps=datetime) as queue_clock, \
                patch.object(worker, 'datetime', wraps=datetime) as due_clock, \
                patch('dkss_app.common.analyze_vehicle_karte', return_value={'overview': 'Synthetic', 'recommendations': []}) as ai:
            queue_clock.now.side_effect = lambda tz=None: now[0].astimezone(tz) if tz else now[0].replace(tzinfo=None)
            due_clock.now.side_effect = queue_clock.now.side_effect
            worker.run_worker(self.app, stopped)
        self.assertEqual(observations, ['pending', 'pending', 'completed'])
        ai.assert_called_once()
        self.db.session.expire_all()
        response = self.client.get(f'/vehicle/karte/{vehicle_id}/analysis/result')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'completed')
        self.assertTrue(response.json['is_current'])
        self.assertEqual(response.json['analysis']['recommendations'][0]['priority_assessment']['effective_score'], 65)
        self.assertEqual(self.state()['status'], '運行可')
        with patch('dkss_app.common.analyze_vehicle_karte') as ai:
            self.client.get(f'/vehicle/karte/{vehicle_id}/analysis/result')
            self.client.get(f'/vehicle/karte/{vehicle_id}/analysis/result')
            ai.assert_not_called()


if __name__ == '__main__':
    unittest.main()
