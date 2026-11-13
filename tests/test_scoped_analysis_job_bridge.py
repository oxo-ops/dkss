"""No HTTP. Exact-byte bridge, durable boundary, and secret-safe failure tests."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace
from tools.quality.scoped_analysis.pilot import Policy, Request, Target, digest, SOL_STANDARD_30M, SOL_RATE_SOURCE
from tools.quality.scoped_analysis.ledger import Ledger
from tools.quality.scoped_analysis.final_gate import RESPONSES_URL
from tools.quality.scoped_analysis.http_candidate import COUNT_SOURCE
from tools.quality.scoped_analysis.job_bridge import ScopedJobBridge
from vehicle_karte_analysis_ai import prepare_vehicle_karte_analysis_request, _analyze_vehicle_karte_once


class JobBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.payload = {'vehicle_source': {'source_id':'vehicle:1'},
            'records':[{'source_id':'maintenance:1','detail':'synthetic repair'}]}
        self.target = Target('SYNTHETIC_BRIDGE',1,digest(self.payload))
        self.policy = Policy((self.target,), 'gpt-6.1-sol',1,6000,500000,250000,
            '2','10',SOL_RATE_SOURCE,'2026-11-12',SOL_STANDARD_30M,RESPONSES_URL)
        self.body = prepare_vehicle_karte_analysis_request(self.payload,model=self.policy.model)
        self.body['service_tier']='default'
        raw=json.dumps(self.body)
        self.request=Request(self.target,raw,hashlib.sha256(raw.encode()).hexdigest(),10000,COUNT_SOURCE)
        self.ledger=Ledger.create(Path(self.tmp.name)/'ledger.sqlite',self.policy)
        self.calls=[]
        def transport(url,raw):
            self.assertEqual(url,RESPONSES_URL);self.assertEqual(raw,self.request.body_json.encode())
            self.assertEqual(self.ledger.receipts()[0][3],'reserved')
            self.calls.append(raw)
            return {'status':'completed','output':[{'content':[{'type':'output_text',
                'text':json.dumps({'overview':'synthetic','recommendations':[]})}]}]}
        self.bridge=ScopedJobBridge(self.ledger,self.request,transport=transport)

    def test_wrong_state_rejected_before_claim_or_transport(self):
        for state in (None,SimpleNamespace(company_code='OTHER',vehicle_record_id=1),
                      SimpleNamespace(company_code=self.target.company,vehicle_record_id=2)):
            with self.assertRaisesRegex(ValueError,'STATE_SCOPE'):
                self.bridge.validate_state(state)
        self.assertEqual(self.ledger.receipts(),[])

    def test_exact_builder_callback_without_credentials_or_global_http(self):
        class NoEnvironment(dict):
            def get(self,*args):raise AssertionError('credential lookup forbidden')
        with patch('vehicle_karte_analysis_ai.os.environ',NoEnvironment()),patch(
            'urllib.request.urlopen',side_effect=AssertionError('unbounded transport forbidden')):
            result=_analyze_vehicle_karte_once(self.payload,_model=self.policy.model,
                _request_transport=self.bridge._send)
        self.assertEqual(result['overview'],'synthetic')
        self.assertEqual(len(self.calls),1)
        with self.assertRaises(ValueError):self.bridge._send(self.body)
        self.assertEqual(len(self.calls),1)

    def test_byte_tampering_refused_before_transport(self):
        with self.assertRaisesRegex(ValueError,'BODY_CHANGED'):
            self.bridge._send({**self.body,'input':'different'})
        self.assertEqual(self.calls,[]);self.assertEqual(self.ledger.receipts(),[])

    def test_exception_detail_not_propagated_and_reservation_retained(self):
        def bad(*args):raise RuntimeError('secret-provider-body')
        self.bridge.transport=bad
        with self.assertRaisesRegex(RuntimeError,'^PILOT_TRANSPORT_UNCERTAIN$'):
            self.bridge._send(self.body)
        self.assertEqual(self.ledger.receipts()[0][3],'uncertain')
        with self.assertRaises(ValueError):self.bridge._send(self.body)

    def test_unloaded_analyzer_cannot_send(self):
        # This fail-closed check must not import the application.
        with patch.dict('sys.modules',{'dkss_app.priority_confirmed_projection':SimpleNamespace()}):
            with self.assertRaisesRegex(ValueError,'NOT_LOADED'):
                self.bridge.analyze(self.payload)
        self.assertEqual(self.calls,[])

    def test_unverified_count_source_refused(self):
        with self.assertRaisesRegex(ValueError,'SINGLE_APPROVED'):
            ScopedJobBridge(self.ledger,replace(self.request,token_count_source='guess'),transport=lambda *a:None)

    def test_changed_or_limited_input_refused_before_generation(self):
        vehicle=SimpleNamespace(company_code=self.target.company,id=1)
        for payload in ({**self.payload,'extra':'changed'},
                        {**self.payload,'comparison':{'comparison_scope':{'acceptance_limited':True}}}):
            module=SimpleNamespace(get_vehicle_karte_analysis_job_data=lambda v:(payload,{}))
            with patch.dict('sys.modules',{'dkss_app.analysis':module}):
                with self.assertRaisesRegex(ValueError,'NORMAL_INPUT_CHANGED'):
                    self.bridge.load_input(vehicle)
        self.assertFalse(self.bridge.loaded);self.assertEqual(self.calls,[])


class HTTPBridgeTests(unittest.TestCase):
    def test_fixed_tls_endpoint_one_attempt_no_redirect_retry_or_body_leak(self):
        from tools.quality.scoped_analysis.https_transport import ResponsesHTTPS
        calls=[]
        class Fake:
            def __init__(self,host,timeout,context):
                assert host=='api.openai.com' and timeout==120 and context.check_hostname
            def request(self,method,path,body,headers):calls.append((method,path,body))
            def getresponse(self):self.status=302;return self
            def read(self,n):raise AssertionError('error body must not be read')
            def close(self):pass
        client=ResponsesHTTPS('synthetic-only',connection_factory=Fake)
        with self.assertRaisesRegex(ValueError,'ENDPOINT'):
            client('https://other.example',b'{}')
        with self.assertRaisesRegex(RuntimeError,'^PILOT_HTTP_UNCERTAIN$'):
            client(RESPONSES_URL,b'{}')
        with self.assertRaisesRegex(ValueError,'NO_TRANSPORT_RETRY'):
            client(RESPONSES_URL,b'{}')
        self.assertEqual(calls,[('POST','/v1/responses',b'{}')])
        self.assertIsNone(client._key)
