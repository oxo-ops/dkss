"""Opt-in OWNED synthetic PostgreSQL CI only. Never accepts a live database.
Not executed here. Requires existing exact URL+ownership-marker CI fixture.
"""
import os
from pathlib import Path
import threading
import unittest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from postgres_ledger import PostgresStore

class OwnedPostgresLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw=os.environ.get('ANALYSIS_RUNTIME_POSTGRES_TEST_URL','')
        if not raw:
            if os.environ.get('ANALYSIS_RUNTIME_REQUIRE_POSTGRES') == '1':
                raise AssertionError('Owned PostgreSQL fixture required')
            raise unittest.SkipTest('Owned PostgreSQL CI not configured')
        if os.environ.get('ANALYSIS_RUNTIME_CI_GUARD_LOADED') != '1':
            raise AssertionError('Owned CI network guard required')
        from analysis_runtime_ci_support import verify_owned_service, CONNECT_ARGS
        verify_owned_service(raw,os.environ)
        cls.engine=create_engine(raw,connect_args=CONNECT_ARGS)
    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
    def cleanup(self):
        with self.engine.begin() as db:
            for name in ('reservation','phase','trial'):
                db.execute(text('DROP TABLE IF EXISTS public.dkss_scoped_pilot_'+name))
    def setUp(self):
        self.cleanup()
        sql=Path(__file__).with_name('002_postgres_pilot_ledger.sql').read_text()
        with self.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
            db.execute(text(sql))
        self.store=PostgresStore(self.engine)
        self.store.start(approval_reference='synthetic',pricing_reference='synthetic')
        self.store.create_phase('count','a'*64)
    def tearDown(self):
        self.cleanup()
    def test_two_concurrent_reservations_only_one_commits(self):
        barrier=threading.Barrier(2); outcomes=[]
        def reserve():
            try:
                barrier.wait(timeout=5)
                self.store.reserve('count','a'*64,'b'*64,1)
                outcomes.append('committed')
            except IntegrityError:
                outcomes.append('blocked')
        threads=[threading.Thread(target=reserve) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(timeout=10)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(sorted(outcomes),['blocked','committed'])
        self.assertEqual(len(self.store.receipts('count')),1)
    def test_connection_reopen_keeps_reservation_and_blocks_restart(self):
        self.store.reserve('count','a'*64,'b'*64,1)
        self.engine.dispose()
        reopened=PostgresStore(self.engine)
        self.assertEqual(reopened.receipts('count')[0][3],'reserved')
        with self.assertRaises(IntegrityError):
            reopened.start(approval_reference='again',pricing_reference='again')
        with self.assertRaises(IntegrityError):
            reopened.reserve('count','a'*64,'b'*64,1)
    def test_continuation_accepts_only_unstarted_original_marker(self):
        with self.engine.begin() as db:
            db.execute(text('DELETE FROM public.dkss_scoped_pilot_phase'))
        self.store.verify_unstarted(approval_reference='synthetic',pricing_reference='synthetic')
        with self.engine.connect() as db:
            self.assertEqual(db.scalar(text('SELECT count(*) FROM public.dkss_scoped_pilot_trial')),1)
            self.assertEqual(db.scalar(text('SELECT count(*) FROM public.dkss_scoped_pilot_phase')),0)
        with self.assertRaises(ValueError):
            self.store.verify_unstarted(approval_reference='changed',pricing_reference='synthetic')
    def test_continuation_rejects_existing_phase_and_never_recreates_marker(self):
        with self.assertRaises(ValueError):
            self.store.verify_unstarted(approval_reference='synthetic',pricing_reference='synthetic')
        # Existing phase remains untouched; a second trial start also fails.
        with self.assertRaises(IntegrityError):
            self.store.start(approval_reference='synthetic',pricing_reference='synthetic')
    def test_each_write_forces_synchronous_commit(self):
        with self.store.writing() as db:
            self.assertEqual(db.scalar(text('SHOW synchronous_commit')),'on')

if __name__=='__main__':unittest.main()
