import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from dataclasses import replace
from tools.quality.scoped_analysis.ledger import Ledger
from tools.quality.scoped_analysis.pilot import Policy, Request, Target


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'pilot.sqlite'
        self.target=Target('SYNTHETIC_A',1,'a'*64)
        self.policy=Policy((self.target,),'fixture',2,6000,10000,30000,'1','2','synthetic','2026-11-12')
        self.body=dict(model='fixture',instructions='fixture',input='{}',text={},reasoning={'effort':'low'},
                       max_output_tokens=6000,store=False)
        self.ledger=Ledger.create(self.path,self.policy)

    def request(self, extra=''):
        raw=json.dumps({**self.body,'input':'{}'+extra})
        return Request(self.target,raw,hashlib.sha256(raw.encode()).hexdigest(),1000,'synthetic exact')

    def test_durable_reservation_precedes_callback_and_reopen_refuses_replay(self):
        def fake(body):
            self.assertEqual(Ledger(self.path,self.policy).receipts()[0][3],'reserved')
            return {'fixture':'ok'}
        self.ledger.synthetic_call(self.request(),observed_target=self.target,transport=fake)
        reopened=Ledger(self.path,self.policy)
        self.assertEqual(reopened.receipts()[0][3],'returned')
        with self.assertRaisesRegex(ValueError,'REPLAY'): reopened.reserve(self.request(),observed_target=self.target)

    def test_restart_after_reservation_never_retries_or_refunds(self):
        self.ledger.reserve(self.request(),observed_target=self.target)
        reopened=Ledger(self.path,self.policy)
        with self.assertRaisesRegex(ValueError,'UNRESOLVED'):
            reopened.reserve(self.request('next'),observed_target=self.target)
        self.assertEqual(reopened.receipts()[0][2],13000)

    def test_uncertain_transport_is_persisted_and_stops_whole_trial(self):
        def fail(body):raise TimeoutError('synthetic only')
        with self.assertRaises(TimeoutError):
            self.ledger.synthetic_call(self.request(),observed_target=self.target,transport=fail)
        reopened=Ledger(self.path,self.policy)
        self.assertEqual(reopened.receipts()[0][3],'uncertain')
        with self.assertRaisesRegex(ValueError,'UNRESOLVED'):
            reopened.reserve(self.request('next'),observed_target=self.target)

    def test_two_owners_reserve_at_most_once(self):
        barrier=threading.Barrier(2);results=[]
        def owner():
            ledger=Ledger(self.path,self.policy);barrier.wait(5)
            try:ledger.reserve(self.request(),observed_target=self.target);results.append('reserved')
            except ValueError:results.append('refused')
        threads=[threading.Thread(target=owner) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(10);self.assertFalse(thread.is_alive())
        self.assertCountEqual(results,['reserved','refused'])
        self.assertEqual(len(self.ledger.receipts()),1)

    def test_cumulative_budget_call_bound_and_wrong_policy(self):
        for suffix in ('1','2'):
            self.ledger.synthetic_call(self.request(suffix),observed_target=self.target,transport=lambda body:None)
        with self.assertRaisesRegex(ValueError,'BUDGET_OR_CALL'):
            Ledger(self.path,self.policy).reserve(self.request('3'),observed_target=self.target)
        with self.assertRaisesRegex(ValueError,'POLICY_MISMATCH'):
            Ledger(self.path,replace(self.policy,budget_microusd=999999))
        with self.assertRaises(FileExistsError):Ledger.create(self.path,self.policy)

    def test_money_and_call_limits_each_fail_independently(self):
        for name,policy in [('money',replace(self.policy,max_calls=3,budget_microusd=20000)),
                            ('calls',replace(self.policy,max_calls=1,budget_microusd=50000))]:
            ledger=Ledger.create(Path(self.tmp.name)/(name+'.sqlite'),policy)
            ledger.synthetic_call(self.request('first'),observed_target=self.target,transport=lambda body:None)
            with self.assertRaisesRegex(ValueError,'BUDGET_OR_CALL'):
                ledger.reserve(self.request('second'),observed_target=self.target)
            self.assertEqual(len(ledger.receipts()),1)

    def test_exact_body_and_replaced_file_refused_before_reservation(self):
        with self.assertRaisesRegex(ValueError,'BODY_CHANGED'):
            self.ledger.reserve_exact_body(self.request(),self.request('changed').body_json,observed_target=self.target)
        self.assertEqual(self.ledger.receipts(),[])
        replacement=Path(self.tmp.name)/'replacement.sqlite'
        Ledger.create(replacement,self.policy)
        replacement.replace(self.path)
        with self.assertRaisesRegex(ValueError,'FILE_REPLACED'):
            self.ledger.reserve(self.request(),observed_target=self.target)

    def test_no_implicit_resume_creation_and_real_callback_refused(self):
        with self.assertRaisesRegex(ValueError,'MISSING'):
            Ledger(Path(self.tmp.name)/'absent.sqlite',self.policy)
        real=replace(self.target,company='REAL')
        policy=replace(self.policy,targets=(real,))
        ledger=Ledger.create(Path(self.tmp.name)/'real.sqlite',policy)
        calls=[]
        with self.assertRaisesRegex(ValueError,'SYNTHETIC_ONLY'):
            ledger.synthetic_call(replace(self.request(),target=real),observed_target=real,transport=calls.append)
        self.assertEqual(calls,[]);self.assertEqual(ledger.receipts(),[])
