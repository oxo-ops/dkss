"""Disposable SQLite model tests; NOT proof of PostgreSQL locking/DDL behavior.
No app import, production DB or network. Private test seam bypasses dialect guard.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from postgres_ledger import PostgresStore, PostgresCountLedger, PostgresGenerationLedger
from tools.quality.scoped_analysis.pilot import Target, Policy, Request, digest, SOL_RATE_SOURCE, SOL_STANDARD_30M
from tools.quality.scoped_analysis.count_material import CountMaterial
from tools.quality.scoped_analysis.count_transport import CountPolicy
from tools.quality.scoped_analysis.final_gate import RESPONSES_URL
from tools.quality.scoped_analysis.http_candidate import COUNT_SOURCE

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.engine=create_engine('sqlite:///'+self.tmp.name+'/test.sqlite')
        ddl=Path(__file__).with_name('002_postgres_pilot_ledger.sql').read_text().replace('public.', '')
        with self.engine.begin() as db:
            for stmt in ddl.split(';'):
                stmt='\n'.join(line for line in stmt.splitlines() if not line.startswith('--')).strip()
                if stmt and not stmt.startswith(('BEGIN','COMMIT','SET LOCAL')):
                    db.execute(text(stmt))
        self.store=object.__new__(PostgresStore)
        self.store.engine=self.engine
        self.store.start(approval_reference='synthetic-approval',pricing_reference='synthetic-price')
        self.target=Target('HARUMICHI',644,'a'*64)
        body=dict(model='gpt-6.1-sol',instructions='synthetic',input='synthetic',text={},reasoning={'effort':'low'},max_output_tokens=6000,store=False,service_tier='default')
        raw=json.dumps(body)
        cnt=json.dumps({k:body[k] for k in ('model','instructions','input','text','reasoning')})
        h=lambda x:hashlib.sha256(x.encode()).hexdigest()
        self.material=CountMaterial(self.target,'gpt-6.1-sol',raw,h(raw),cnt,h(cnt))
        self.cp=CountPolicy(h(raw),h(cnt),digest(asdict(self.target)),'gpt-6.1-sol','synthetic',1,'synthetic')
        self.p=Policy((self.target,),'gpt-6.1-sol',1,6000,500000,250000,'2','10',SOL_RATE_SOURCE,'2026-11-12',SOL_STANDARD_30M,RESPONSES_URL)
        self.request=Request(self.target,raw,h(raw),76000,COUNT_SOURCE)
    def tearDown(self):
        self.engine.dispose();self.tmp.cleanup()
    def test_dialect_rejected(self):
        with self.assertRaises(ValueError):PostgresStore(self.engine)
    def test_no_second_run_or_phase(self):
        with self.assertRaises(IntegrityError):self.store.start(approval_reference='again',pricing_reference='again')
        PostgresCountLedger(self.store,self.cp)
        with self.assertRaises(IntegrityError):PostgresCountLedger(self.store,self.cp)
    def test_count_crash_reserved_blocks_retry_and_records_minimal_evidence(self):
        ledger=PostgresCountLedger(self.store,self.cp);ledger.reserve_count(self.material)
        with self.assertRaises(IntegrityError):ledger.reserve_count(self.material)
        ledger.record_count(dict(response_sha256='b'*64,input_tokens=76000,request_id='req_synthetic',received_at='2026-11-13T00:00:00Z'))
        self.assertEqual(ledger.receipts()[0][3],'returned')
        with self.assertRaises(ValueError):ledger.record_outcome(1,'uncertain')
    def test_generation_committed_before_transport_and_no_retry(self):
        ledger=PostgresGenerationLedger(self.store,self.p)
        ledger.reserve_exact_body(self.request,self.request.body_json,observed_target=self.target)
        # Separate connection observes committed reservation.
        self.assertEqual(ledger.receipts()[0][2:],(250000,'reserved'))
        ledger.record_outcome(1,'uncertain')
        with self.assertRaises(IntegrityError):ledger.reserve(self.request,observed_target=self.target)
    def test_changed_bytes_rejected_before_reservation(self):
        ledger=PostgresGenerationLedger(self.store,self.p)
        with self.assertRaises(ValueError):ledger.reserve_exact_body(self.request,self.request.body_json+' ',observed_target=self.target)
        self.assertEqual(ledger.receipts(),[])
    def test_fixed_target_rejected(self):
        other=Target('OTHER',644,'a'*64)
        p=Policy((other,),'gpt-6.1-sol',1,6000,500000,250000,'2','10',SOL_RATE_SOURCE,'2026-11-12',SOL_STANDARD_30M,RESPONSES_URL)
        with self.assertRaises(ValueError):PostgresGenerationLedger(self.store,p)
    def test_count_policy_change_rejected(self):
        ledger=PostgresCountLedger(self.store,self.cp)
        with self.engine.begin() as db:
            db.execute(text("UPDATE dkss_scoped_pilot_phase SET policy_hash='changed'"))
        with self.assertRaises(ValueError):ledger.reserve_count(self.material)
        self.assertEqual(ledger.receipts(),[])

if __name__=='__main__':unittest.main()
