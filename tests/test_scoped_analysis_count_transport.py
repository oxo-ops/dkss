import hashlib
import json
from pathlib import Path
from dataclasses import asdict, replace
import tempfile
import unittest
from tools.quality.scoped_analysis.count_material import prepare_count_material
from tools.quality.scoped_analysis.count_transport import CountHTTPS, CountLedger, CountPolicy
from tools.quality.scoped_analysis.pilot import Target,digest


class CountTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        payload={'vehicle_source':{'source_id':'vehicle:1'},'records':[{'source_id':'maintenance:1','detail':'synthetic'}]}
        target=Target('SYNTHETIC_COUNT',1,digest(payload))
        self.material=prepare_count_material(payload,target=target,model='gpt-6.1-sol')
        self.policy=CountPolicy(self.material.generation_sha256,self.material.count_sha256,digest(asdict(target)),
                                'gpt-6.1-sol','synthetic-approval',1000,'synthetic-price')
        self.path=Path(self.tmp.name)/'count.sqlite'
        self.ledger=CountLedger.create(self.path,self.policy)
        self.calls=[];self.status=200;self.raw=b'{"object":"response.input_tokens","input_tokens":123}'
        self.request_id='req_synthetic';self.fail=None

    def factory(self,host,timeout,context):
        self.assertEqual(host,'api.openai.com');self.assertTrue(context.check_hostname);self.assertEqual(timeout,120)
        self.assertEqual(self.ledger.receipts()[0][3],'reserved')
        outer=self
        class Connection:
            def request(self,method,path,body,headers):
                outer.calls.append((method,path,body))
                if outer.fail: raise outer.fail
            def getresponse(self):self.status=outer.status;return self
            def read(self,n):
                if self.status!=200:raise AssertionError('do not read provider error body')
                return outer.raw
            def getheader(self,name):return outer.request_id
            def close(self):pass
        return Connection()

    def run_count(self,ledger=None):
        client=CountHTTPS('synthetic-only',connection_factory=self.factory)
        try:return client.run(ledger or self.ledger,self.material)
        finally:self.assertIsNone(client._key)

    def test_success_records_both_request_hashes_and_full_response_hash(self):
        evidence=self.run_count()
        self.assertEqual(evidence['response_sha256'],hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(evidence['count_sha256'],self.material.count_sha256)
        self.assertEqual(evidence['generation_sha256'],self.material.generation_sha256)
        self.assertFalse(evidence['generation_authorized']);self.assertEqual(evidence['input_tokens'],123)
        self.assertEqual(self.calls,[('POST','/v1/responses/input_tokens',self.material.count_json.encode())])
        with self.ledger._connect() as db:self.assertEqual(db.execute('SELECT input_tokens FROM count_evidence').fetchone(),(123,))
        with self.assertRaisesRegex(RuntimeError,'NO_RETRY'):
            self.run_count(CountLedger(self.path,self.policy))
        self.assertEqual(len(self.calls),1)

    def test_reserved_crash_blocks_fresh_owner(self):
        self.ledger.reserve_count(self.material)
        with self.assertRaisesRegex(RuntimeError,'NO_RETRY'):self.run_count(CountLedger(self.path,self.policy))
        self.assertEqual(self.calls,[])

    def test_uncertain_is_durable_and_error_is_sanitized(self):
        self.fail=RuntimeError('secret-key-and-private-body')
        with self.assertRaisesRegex(RuntimeError,'^COUNT_ATTEMPT_FAILED_NO_RETRY$'):self.run_count()
        self.assertEqual(self.ledger.receipts()[0][3],'uncertain')
        with self.assertRaisesRegex(RuntimeError,'NO_RETRY'):self.run_count(CountLedger(self.path,self.policy))
        self.assertEqual(len(self.calls),1)

    def test_redirect_has_no_retry_and_no_error_body_read(self):
        self.status=302
        with self.assertRaisesRegex(RuntimeError,'NO_RETRY'):self.run_count()
        self.assertEqual(len(self.calls),1)

    def test_tampered_material_refused_before_connect(self):
        self.material=replace(self.material,count_json=self.material.count_json+' ')
        with self.assertRaisesRegex(RuntimeError,'NO_RETRY'):self.run_count()
        self.assertEqual(self.calls,[]);self.assertEqual(self.ledger.receipts(),[])

    def test_invalid_count_or_missing_request_id_stops_and_records_no_evidence(self):
        self.raw=b'{"object":"response.input_tokens","input_tokens":true}'
        with self.assertRaisesRegex(RuntimeError,'NO_RETRY'):self.run_count()
        with self.ledger._connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM count_evidence').fetchone(),(0,))

    def test_oversized_response_refused(self):
        self.raw=b' '*65537
        with self.assertRaisesRegex(RuntimeError,'NO_RETRY'):self.run_count()
        self.assertEqual(self.ledger.receipts()[0][3],'uncertain')

    def test_missing_ledger_never_created_on_resume(self):
        with self.assertRaisesRegex(ValueError,'MISSING'):
            CountLedger(Path(self.tmp.name)/'missing.sqlite',self.policy)

    def test_same_ledger_two_owners_reserve_only_once(self):
        other=CountLedger(self.path,self.policy)
        self.ledger.reserve_count(self.material)
        with self.assertRaisesRegex(ValueError,'ALREADY'):other.reserve_count(self.material)
        self.assertEqual(len(other.receipts()),1)

    def test_missing_request_id_consumes_attempt_without_evidence(self):
        self.request_id=None
        with self.assertRaisesRegex(RuntimeError,'NO_RETRY'):self.run_count()
        self.assertEqual(self.ledger.receipts()[0][3],'uncertain')
        with self.ledger._connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM count_evidence').fetchone(),(0,))

    def test_concurrent_owners_only_one_reservation(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier=Barrier(2)
        def reserve():
            ledger=CountLedger(self.path,self.policy)
            barrier.wait(timeout=5)
            try:ledger.reserve_count(self.material);return 'reserved'
            except ValueError as error:return str(error)
        with ThreadPoolExecutor(max_workers=2) as workers:
            first=workers.submit(reserve);second=workers.submit(reserve)
            results=[first.result(timeout=10),second.result(timeout=10)]
        self.assertEqual(sorted(results),['COUNT_ALREADY_ATTEMPTED_NO_RETRY','reserved'])
        self.assertEqual(len(self.ledger.receipts()),1)
