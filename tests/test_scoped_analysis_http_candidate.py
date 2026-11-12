import json
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch
import test_scoped_analysis_final_gate as gate_tests
from tools.quality.scoped_analysis.http_candidate import SyntheticHTTPTrial, COUNT_SOURCE, COUNT_PATH
from tools.quality.scoped_analysis.ledger import Ledger


class HTTPTests(unittest.TestCase):
    def setUp(self):
        gate_tests.FinalGateTests.setUp(self)
        self.policy = replace(self.policy, max_calls=1)
        self.ledger = Ledger.create(Path(self.tmp.name)/'http.sqlite', self.policy)
        self.request = replace(self.request, token_count_source=COUNT_SOURCE)
        self.calls=[]
        self.status=200
        self.count=1000
        self.fail_generation=False
        self.generation_status=200
        owner=self
        class Connection:
            def __init__(self, host, timeout, context):
                owner.assertEqual(host,'api.openai.com')
                owner.assertEqual(timeout,120)
                owner.assertTrue(context.check_hostname)
            def request(self, method, path, body, headers):
                owner.calls.append((method,path,body,headers))
                self.path=path
                if path == '/v1/responses':
                    owner.assertEqual(owner.ledger.receipts()[0][3],'reserved')
                    if owner.fail_generation: raise TimeoutError('synthetic')
            def getresponse(self):
                self.status=owner.status if self.path==COUNT_PATH else owner.generation_status
                return self
            def read(self, limit):
                return json.dumps({'object':'response.input_tokens','input_tokens':owner.count}
                    if self.path == COUNT_PATH else {'status':'completed','output':[]}).encode()
            def close(self): pass
        self.connection_factory=Connection

    def trial(self):
        return SyntheticHTTPTrial(self.ledger,self.request,observed_target=self.target,connection_factory=self.connection_factory)

    def test_http_count_then_exact_generation_no_replay(self):
        trial=self.trial()
        self.assertEqual(trial.run()['status'],'completed')
        self.assertEqual([x[1] for x in self.calls],[COUNT_PATH,'/v1/responses'])
        count_body=json.loads(self.calls[0][2]);body=json.loads(self.request.body_json)
        self.assertEqual(count_body,{k:body[k] for k in ('model','instructions','input','text','reasoning')})
        self.assertEqual(self.calls[1][2],self.request.body_json.encode())
        with self.assertRaisesRegex(ValueError,'NO_RETRY'): trial.run()
        with self.assertRaisesRegex(ValueError,'NO_RETRY'): self.trial().run()
        self.assertEqual(len(self.calls),2)

    def test_redirect_and_rate_limit_not_followed_or_retried(self):
        for status in (301,302,307,308,429,500):
            self.status=status;trial=self.trial();before=len(self.calls)
            with self.assertRaisesRegex(RuntimeError,str(status)):trial.run()
            with self.assertRaisesRegex(ValueError,'NO_RETRY'):trial.run()
            self.assertEqual(len(self.calls),before+1)
        self.assertEqual(self.ledger.receipts(),[])

    def test_count_over_bound_stops_generation(self):
        self.count=1001
        with self.assertRaisesRegex(ValueError,'TOKEN_BOUND'):self.trial().run()
        self.assertEqual(len(self.calls),1);self.assertEqual(self.ledger.receipts(),[])

    def test_budget_rejected_before_any_http(self):
        self.policy=replace(self.policy,budget_microusd=1)
        self.ledger=Ledger.create(Path(self.tmp.name)/'small.sqlite',self.policy)
        with self.assertRaisesRegex(ValueError,'BUDGET'):self.trial()
        self.assertEqual(self.calls,[])

    def test_generation_timeout_is_uncertain_and_never_retried(self):
        self.fail_generation=True
        with self.assertRaises(TimeoutError):self.trial().run()
        self.assertEqual(self.ledger.receipts()[0][3],'uncertain')
        with self.assertRaisesRegex(ValueError,'NO_RETRY'):self.trial().run()
        self.assertEqual(len(self.calls),2)

    def test_bad_count_is_not_a_token_estimate(self):
        for count in (True,0,-1,'1000'):
            self.count=count
            with self.assertRaisesRegex(ValueError,'INVALID_PROVIDER_COUNT'):self.trial().run()
        self.assertEqual(len(self.calls),4);self.assertEqual(self.ledger.receipts(),[])

    def test_reassigned_request_revalidated_before_count(self):
        trial=self.trial()
        trial.request=replace(self.request,body_json=self.request.body_json+' ')
        with self.assertRaisesRegex(ValueError,'REQUEST_CHANGED'):trial.run()
        self.assertEqual(self.calls,[])

    def test_no_implicit_live_connection(self):
        from tools.quality.scoped_analysis.http_candidate import post_json_synthetic
        with self.assertRaisesRegex(ValueError,'MOCK_CONNECTION'):
            post_json_synthetic(COUNT_PATH,b'{}',connection_factory=None)

    def test_generation_redirect_and_429_stay_uncertain(self):
        for status in (302,429):
            self.ledger=Ledger.create(Path(self.tmp.name)/('status'+str(status)+'.sqlite'),self.policy)
            self.generation_status=status;before=len(self.calls)
            with self.assertRaisesRegex(RuntimeError,str(status)):self.trial().run()
            self.assertEqual(len(self.calls),before+2)
            self.assertEqual(self.ledger.receipts()[0][3],'uncertain')
            with self.assertRaisesRegex(ValueError,'NO_RETRY'):self.trial().run()
            self.assertEqual(len(self.calls),before+2)
