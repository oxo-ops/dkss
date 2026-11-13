"""Owned disposable PostgreSQL only: real migration and row-lock races."""
from datetime import datetime, timezone
from pathlib import Path
import threading
import unittest
from sqlalchemy import event, text
import test_analysis_worker_postgres as fixture


class PilotHoldPostgresTests(unittest.TestCase):
    setUpClass=classmethod(fixture.AnalysisWorkerPostgresTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.AnalysisWorkerPostgresTests.tearDownClass.__func__)
    setUp=fixture.AnalysisWorkerPostgresTests.setUp
    tearDown=fixture.AnalysisWorkerPostgresTests.tearDown
    repository=fixture.AnalysisWorkerPostgresTests.repository
    wait_for_blocked=fixture.AnalysisWorkerPostgresTests.wait_for_blocked

    def test_additive_migration_preserves_existing_rows_and_nullable_hold(self):
        # Temporary table shadows the fixture's table; original migration SQL is
        # executed unchanged. No migration ever points at an external database.
        sql=(Path(__file__).resolve().parents[1]/'tools/quality/scoped_analysis/migrations/001_pilot_hold.sql').read_text()
        with self.db.engine.begin() as connection:
            connection.execute(text('CREATE TEMP TABLE vehicle_karte_analysis (id INTEGER PRIMARY KEY, result_json TEXT) ON COMMIT DROP'))
            connection.execute(text("INSERT INTO vehicle_karte_analysis VALUES (7, 'preserved')"))
            connection.execute(text(sql))
            self.assertEqual(tuple(connection.execute(text('SELECT id,result_json,pilot_hold FROM vehicle_karte_analysis')).one()),(7,'preserved',None))
            connection.execute(text("UPDATE vehicle_karte_analysis SET pilot_hold=:hold WHERE id=7"),{'hold':'a'*64})
            self.assertEqual(connection.scalar(text('SELECT pilot_hold FROM vehicle_karte_analysis')),'a'*64)

    def race(self, hold_first):
        held,release=threading.Event(),threading.Event()
        outcomes,errors={},[]
        now=datetime.now(timezone.utc)
        def run(first):
            with self.app.app_context():
                listener=None
                try:
                    session=self.db.session()
                    name='hold_race_second' if not first else 'hold_race_first'
                    session.execute(text("SELECT set_config('application_name',:name,false)"),{'name':name})
                    if first:
                        def listener(session):
                            held.set()
                            if not release.wait(8):raise RuntimeError('COMMIT_RELEASE_TIMEOUT')
                        event.listen(session,'before_commit',listener)
                    repo=self.repository()
                    operation_hold=(hold_first==first)
                    if operation_hold:
                        try:
                            repo.install_pilot_hold(self.state_id,'TEST',self.vehicle_id,'a'*64,now)
                            outcomes['hold']=True
                        except ValueError as error:
                            self.assertEqual(str(error),'PILOT_HOLD_OR_ACTIVE_LEASE')
                            outcomes['hold']=False
                    else:
                        outcomes['claim']=repo.claim(self.state_id,'old','normal-owner',now)
                except Exception as error:
                    errors.append(type(error).__name__+':'+str(error))
                finally:
                    if listener is not None:event.remove(session,'before_commit',listener)
                    self.db.session.remove()
        a=threading.Thread(target=run,args=(True,));b=threading.Thread(target=run,args=(False,))
        a.start()
        try:
            self.assertTrue(held.wait(5));b.start();self.wait_for_blocked('hold_race_second')
        finally:
            release.set();a.join(10)
            if b.ident is not None:b.join(10)
        self.assertFalse(a.is_alive());self.assertFalse(b.is_alive());self.assertEqual(errors,[])
        self.assertEqual(outcomes,{'hold':hold_first,'claim':not hold_first})
        state=self.db.session.get(self.models.VehicleKarteAnalysis,self.state_id)
        self.assertEqual(state.pilot_hold,'a'*64 if hold_first else None)

    def test_committed_hold_defeats_blocked_normal_claim(self):self.race(True)
    def test_active_normal_claim_prevents_hold_acquisition(self):self.race(False)
