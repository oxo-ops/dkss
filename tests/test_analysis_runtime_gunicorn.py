"""Finite real-process acceptance, only in marked official CI with synthetic AI."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, text


class AnalysisRuntimeGunicornTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('ANALYSIS_RUNTIME_GUNICORN_TEST') != '1':
            raise unittest.SkipTest('Official isolated Gunicorn acceptance not enabled')
        from analysis_runtime_ci_support import verify_owned_service, acceptance_root, CONNECT_ARGS
        cls.root = acceptance_root()
        cls.url = verify_owned_service(os.environ['ANALYSIS_RUNTIME_POSTGRES_TEST_URL'], os.environ)
        if os.environ.get('ANALYSIS_RUNTIME_CI_GUARD_LOADED') != '1':
            raise AssertionError('The socket/SQLite guard must be loaded before process tests')
        try:
            socket.getaddrinfo('external.invalid', 443)
        except RuntimeError:
            pass
        else:
            raise AssertionError('External DNS was not blocked by the audit guard')
        from dkss_app import create_app, models
        from dkss_app.extensions import db
        cls.db, cls.models = db, models
        cls.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': cls.url,
            'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': CONNECT_ARGS}})
        cls.repo = Path(__file__).resolve().parents[1]

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            cls.db.session.remove(); cls.db.engine.dispose()

    def setUp(self):
        self.case = self._testMethodName
        self.case_root = self.root / self.case
        self.case_root.mkdir(exist_ok=False)
        self.processes = []
        with self.app.app_context():
            self.db.drop_all(); self.db.create_all()
            self.db.session.add(self.models.Company(company_code='TEST', company_name='Synthetic CI', active=True))
            vehicle = self.models.Vehicle(company_code='TEST', chassis_number='SYNTHETIC-ONLY')
            self.db.session.add(vehicle); self.db.session.flush()
            self.vehicle_id = vehicle.id
            day = datetime.now(ZoneInfo('Asia/Tokyo')).date().isoformat()
            self.db.session.add(self.models.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=vehicle.id,
                entry_date=day, completion_date=day, content='Synthetic CI maintenance only', status='完了'))
            self.db.session.commit()
            from dkss_app.analysis import get_vehicle_karte_analysis_job_data, queue_vehicle_karte_analysis
            with self.app.test_request_context('/'):
                payload, _ = get_vehicle_karte_analysis_job_data(vehicle)
            self.assertTrue(payload['_fingerprints']['has_important_history'])
            state = queue_vehicle_karte_analysis(vehicle, payload)
            state.next_analysis_at = datetime.now(timezone.utc)-timedelta(minutes=1)
            self.previous = json.dumps({'analysis': {'overview': 'Synthetic previous result', 'recommendations': []}})
            state.result_json = self.previous
            self.db.session.commit(); self.state_id = state.id
            self.db.session.remove()

    def tearDown(self):
        for process, stream in reversed(self.processes):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=35)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(timeout=5)
            stream.close()
        with self.app.app_context(): self.db.session.remove()

    def environment(self, enabled='1'):
        env = dict(os.environ)
        env.update(ANALYSIS_RUNTIME_CASE=self.case, VEHICLE_ANALYSIS_WORKER_ENABLED=enabled,
            DOCUMENT_IMPORT_WORKER_ENABLED='0', PUBLIC_KNOWLEDGE_ENABLED='0', WEB_CONCURRENCY='2', WEB_THREADS='2',
            OPENAI_API_KEY='', S3_BUCKET_NAME='', SMTP_HOST='', VAPID_PRIVATE_KEY='', VAPID_PUBLIC_KEY='')
        return env

    def start(self):
        log = self.case_root / f'gunicorn-{len(self.processes)}.log'
        stream = log.open('w')
        process = subprocess.Popen([sys.executable, '-m', 'gunicorn', '-c', 'gunicorn.conf.py',
            '--bind', '127.0.0.1:5019', 'analysis_runtime_ci_app:app'], cwd=self.repo,
            env=self.environment(), stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        self.processes.append((process, stream))
        self.await_condition(lambda: self.health() is not None, 'Gunicorn did not serve the ordinary login page', 25,
            process=process)
        return process

    def health(self):
        try:
            with urlopen('http://127.0.0.1:5019/login', timeout=1) as response:
                body = response.read(1024 * 1024)
                ok = response.status == 200 and b'<form' in body
            return {'ordinary_login': True} if ok else None
        except (OSError, ValueError):
            return None

    def await_condition(self, condition, message, timeout=12, process=None):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                self.fail(f'{message}: master exited with {process.returncode}')
            value = condition()
            if value: return value
            time.sleep(0.05)
        self.fail(message)

    def calls(self):
        path = self.case_root / 'calls.jsonl'
        if not path.exists(): return []
        data = path.read_text()
        # A concurrent append is not complete until its terminating newline.
        return [json.loads(line) for line in data[:data.rfind('\n')+1].splitlines()]

    def state(self):
        with self.app.app_context():
            state = self.db.session.get(self.models.VehicleKarteAnalysis, self.state_id)
            value = {'status': state.status, 'token': state.lease_token, 'result': state.result_json,
                'lease_expires_at': state.lease_expires_at, 'retry_at': state.next_analysis_at,
                'last_error': state.last_error}
            self.db.session.remove()
            return value

    def expire_fixture_lease(self):
        # This is explicit synthetic-fixture manipulation, never production logic.
        with self.app.app_context():
            self.models.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
                'lease_expires_at': datetime.now(timezone.utc)-timedelta(seconds=1)}, synchronize_session=False)
            self.db.session.commit(); self.db.session.remove()

    def release_ai(self):
        (self.case_root / 'release').write_text('synthetic transport may finish\n')

    def stop(self, process):
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=35)
        self.assertEqual(process.returncode, 0)
        from dkss_app.analysis_worker import leadership
        with leadership(self.app) as owner:
            self.assertIsNotNone(owner, 'normal Gunicorn exit must release the DB leader')

    def assert_completed(self):
        self.await_condition(lambda: self.state()['status'] == 'completed', 'Synthetic analysis did not complete')
        self.assertEqual(json.loads(self.state()['result'])['analysis']['overview'], 'Synthetic CI completed')

    def test_two_workers_one_call_cli_busy_http_responsive_and_exit_release(self):
        process = self.start()
        self.await_condition(lambda: len(self.calls()) == 1, 'Synthetic AI did not start')
        logs = lambda: ''.join(p.read_text() for p in self.case_root.glob('gunicorn-*.log'))
        self.await_condition(lambda: 'ANALYSIS_WORKER_STANDBY' in logs(), 'Second web process did not become standby')
        cli = subprocess.run([sys.executable, '-m', 'flask', '--app', 'analysis_runtime_ci_app',
            'vehicle-karte-analysis-tick'], cwd=self.repo, env=self.environment('0'),
            text=True, capture_output=True, timeout=15)
        (self.case_root/'cli.log').write_text(cli.stdout+cli.stderr)
        self.assertEqual(cli.returncode, 0); self.assertIn('ANALYSIS_WORKER_BUSY', cli.stdout)
        for _ in range(3): self.assertIsNotNone(self.health())
        self.assertEqual(len(self.calls()), 1)
        self.release_ai(); self.assert_completed(); self.stop(process)
        self.assertEqual(len(self.calls()), 1)

    def test_sigterm_inflight_preserves_previous_then_recovers_after_lease(self):
        process = self.start()
        self.await_condition(lambda: len(self.calls()) == 1, 'Synthetic AI did not start')
        old_pid, old_token = self.calls()[0]['pid'], self.state()['token']
        self.stop(process)
        self.assertEqual(self.state()['status'], 'running')
        self.assertEqual(self.state()['result'], self.previous)
        replacement = self.start()
        time.sleep(0.6)
        self.assertEqual(len(self.calls()), 1, 'Unexpired job must not be called again')
        self.release_ai(); self.expire_fixture_lease(); self.assert_completed()
        self.assertEqual(len(self.calls()), 2); self.assertNotEqual(self.calls()[1]['pid'], old_pid)
        self.assertIsNotNone(old_token); self.stop(replacement)

    def test_sigkill_worker_respawns_without_reclaim_before_lease_expiry(self):
        process = self.start()
        self.await_condition(lambda: len(self.calls()) == 1, 'Synthetic AI did not start')
        first_pid = self.calls()[0]['pid']
        os.kill(first_pid, signal.SIGKILL)
        self.await_condition(lambda: self.health() is not None, 'Other/replacement web worker did not respond')
        time.sleep(0.6)
        self.assertEqual(len(self.calls()), 1); self.assertEqual(self.state()['result'], self.previous)
        self.release_ai(); self.expire_fixture_lease(); self.assert_completed()
        self.assertEqual(len(self.calls()), 2); self.assertNotEqual(self.calls()[1]['pid'], first_pid)
        self.stop(process)

    def test_hup_reload_releases_old_leader_without_duplicate_unexpired_job(self):
        process = self.start()
        self.await_condition(lambda: len(self.calls()) == 1, 'Synthetic AI did not start')
        first_pid = self.calls()[0]['pid']
        process.send_signal(signal.SIGHUP)
        def old_exited():
            try: os.kill(first_pid, 0)
            except ProcessLookupError: return True
            return False
        self.await_condition(old_exited, 'Reload did not retire the old leader', 35, process=process)
        self.assertEqual(len(self.calls()), 1); self.assertEqual(self.state()['result'], self.previous)
        self.release_ai(); self.expire_fixture_lease(); self.assert_completed()
        self.assertEqual(len(self.calls()), 2); self.assertNotEqual(self.calls()[1]['pid'], first_pid)
        self.stop(process)

    def events(self, filename):
        path = self.case_root / filename
        if not path.exists(): return []
        data = path.read_text()
        return [json.loads(line) for line in data[:data.rfind('\n')+1].splitlines()]

    def assert_process_alive(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            self.fail('The original OS worker must remain alive during DB-session loss')

    def leader_backend(self):
        # Only the session owning this exact two-int advisory tag in this
        # already-verified synthetic database can qualify as the leader.
        with self.app.app_context(), self.db.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT activity.pid, activity.application_name
                FROM pg_locks locks JOIN pg_stat_activity activity ON activity.pid=locks.pid
                WHERE locks.locktype='advisory' AND locks.granted
                  AND locks.classid=CAST(1145787219 AS oid) AND locks.objid=CAST(1 AS oid)
                  AND locks.objsubid=2
                  AND locks.database=(SELECT oid FROM pg_database WHERE datname=current_database())
                  AND activity.datname=current_database() AND activity.usename=current_user
                  AND activity.backend_type='client backend'
                  AND activity.pid<>pg_backend_pid()
            """)).mappings().all()
        self.assertLessEqual(len(rows), 1, 'Only one dedicated leader backend may exist')
        return dict(rows[0]) if rows else None

    def terminate_owned_leader_once(self, original_os_pid):
        from analysis_runtime_ci_support import verify_owned_service
        verify_owned_service(self.url, os.environ)
        old = self.leader_backend()
        self.assertIsNotNone(old)
        expected_name = f'dkss-analysis-ci-{original_os_pid}'
        self.assertEqual(old['application_name'], expected_name)
        self.assert_process_alive(original_os_pid)
        # Recheck the complete ownership/tag predicate in the terminating SQL.
        # Issue exactly once. Any exception/uncertain outcome fails the case;
        # subsequent polling is read-only and never resends termination.
        with self.app.app_context(), self.db.engine.connect() as connection:
            terminated = connection.execute(text("""
                SELECT pg_terminate_backend(activity.pid)
                FROM pg_locks locks JOIN pg_stat_activity activity ON activity.pid=locks.pid
                WHERE locks.locktype='advisory' AND locks.granted
                  AND locks.classid=CAST(1145787219 AS oid) AND locks.objid=CAST(1 AS oid)
                  AND locks.objsubid=2
                  AND locks.database=(SELECT oid FROM pg_database WHERE datname=current_database())
                  AND activity.datname=current_database() AND activity.usename=current_user
                  AND activity.backend_type='client backend' AND activity.pid<>pg_backend_pid()
                  AND activity.pid=:pid AND activity.application_name=:name
            """), {'pid': old['pid'], 'name': expected_name}).scalar_one_or_none()
        self.assertIs(terminated, True)
        (self.case_root/'terminated-leader.json').write_text(json.dumps({
            'database_backend_pid': old['pid'], 'os_worker_pid': original_os_pid,
            'advisory_namespace': 1145787219, 'advisory_key': 1, 'termination_requests': 1})+'\n')
        def successor():
            current = self.leader_backend()
            return current if current and current['pid'] != old['pid'] else None
        replacement = self.await_condition(successor, 'Standby did not acquire leadership after DB loss')
        self.assertNotEqual(replacement['application_name'], expected_name)
        self.assertTrue(replacement['application_name'].startswith('dkss-analysis-ci-'))
        self.assert_process_alive(original_os_pid)
        return replacement

    def assert_original_token_still_valid(self, original_token):
        value = self.state()
        self.assertEqual((value['status'], value['token']), ('running', original_token))
        self.assertIsNotNone(value['lease_expires_at'])
        self.assertGreater(value['lease_expires_at'], datetime.now(timezone.utc))
        self.assertEqual(value['result'], self.previous)
        self.assertEqual(len(self.calls()), 1)

    def assert_leadership_error_retains_previous_and_schedules_retry(self):
        self.await_condition(lambda: self.state()['status'] == 'error', 'Lost ownership was not handled as an error')
        value = self.state()
        self.assertEqual(value['result'], self.previous)
        self.assertIsNone(value['token']); self.assertIsNone(value['lease_expires_at'])
        self.assertTrue(value['last_error'].startswith(('OperationalError:', 'RuntimeError:')))
        now = datetime.now(timezone.utc)
        self.assertGreater(value['retry_at'], now+timedelta(minutes=55))
        self.assertLess(value['retry_at'], now+timedelta(minutes=65))
        self.assertEqual(len(self.calls()), 1, 'Handled leadership loss must not trigger an immediate model retry')

    def test_live_leader_db_loss_blocks_second_model_chunk(self):
        process = self.start()
        self.await_condition(lambda: len(self.events('chunks.jsonl')) == 1, 'First synthetic model chunk did not finish')
        original_os_pid = self.calls()[0]['pid']
        token = self.state()['token']; self.assertIsNotNone(token)
        self.terminate_owned_leader_once(original_os_pid)
        self.assert_original_token_still_valid(token)
        (self.case_root/'release_next_chunk').write_text('release synthetic next-chunk boundary\n')
        self.assert_leadership_error_retains_previous_and_schedules_retry()
        self.assertEqual([row['stage'] for row in self.events('chunks.jsonl')], ['chunk1'])
        self.assert_process_alive(original_os_pid)
        self.stop(process)

    def test_live_leader_db_loss_blocks_save_with_valid_original_token(self):
        self.release_ai()
        process = self.start()
        self.await_condition(lambda: any(row['stage'] == 'after_reconcile' for row in self.events('fences.jsonl')),
            'Real reconciliation did not finish before the final-save pause')
        self.assertEqual([row['stage'] for row in self.events('fences.jsonl')],
            ['last_progress_finished', 'after_reconcile'])
        original_os_pid = self.calls()[0]['pid']
        token = self.state()['token']; self.assertIsNotNone(token)
        self.terminate_owned_leader_once(original_os_pid)
        self.assert_original_token_still_valid(token)
        (self.case_root/'release_save').write_text('release synthetic final-save boundary\n')
        self.assert_leadership_error_retains_previous_and_schedules_retry()
        self.assertEqual([row['stage'] for row in self.events('fences.jsonl')],
            ['last_progress_finished', 'after_reconcile'])
        self.assert_process_alive(original_os_pid)
        self.stop(process)

    def test_missing_analysis_schema_refuses_work_without_creating_table(self):
        with self.app.app_context():
            self.models.VehicleKarteAnalysis.__table__.drop(self.db.engine)
        process = self.start()
        logs = lambda: ''.join(p.read_text() for p in self.case_root.glob('gunicorn-*.log'))
        self.await_condition(lambda: 'ANALYSIS_WORKER_ITERATION_FAILED error_type=ProgrammingError' in logs(),
            'Missing schema was not refused')
        self.assertEqual(self.calls(), [])
        with self.app.app_context():
            self.assertFalse(inspect(self.db.engine).has_table('vehicle_karte_analysis'))
        process.send_signal(signal.SIGTERM); process.wait(timeout=35)
        self.assertEqual(process.returncode, 0)


if __name__ == '__main__':
    unittest.main()
