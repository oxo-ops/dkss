import hashlib
import json
import unittest
from dataclasses import replace
from tools.quality.scoped_analysis.pilot import Policy, Request, Target, Trial, estimate_microusd


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.target = Target('SYNTHETIC_A', 1, 'a' * 64)
        self.policy = Policy((self.target,), 'synthetic-model', 2, 6000, 10000, 15000,
                             '1', '2', 'synthetic fixture, not provider prices', '2026-11-12')
        self.body = dict(model='synthetic-model', instructions='fixture', input='{}',
                         text={}, reasoning={'effort':'low'}, max_output_tokens=6000, store=False)
        self.calls = []

    def request(self, body=None, **changes):
        raw = json.dumps(body or self.body)
        return replace(Request(self.target, raw, hashlib.sha256(raw.encode()).hexdigest(),
                               1000, 'synthetic exact-token fixture'), **changes)

    def invoke(self, trial, request=None, target=None):
        return trial.synthetic_call(request or self.request(), observed_target=target or self.target,
                                    transport=lambda body: self.calls.append(body) or {'fixture':'ok'})

    def denied(self, request=None, target=None, policy=None):
        trial = Trial(policy or self.policy)
        with self.assertRaises(ValueError): self.invoke(trial, request, target)
        self.assertEqual(self.calls, [])
        self.assertEqual(trial.receipts, [])

    def test_success_reserves_before_transport(self):
        t = Trial(self.policy)
        def fake(body):
            self.assertEqual(t.receipts[0]['status'], 'reserved')
            self.assertEqual(t.used, 13000)
            return True
        self.assertTrue(t.synthetic_call(self.request(), observed_target=self.target, transport=fake))
        self.assertEqual(t.receipts[0]['status'], 'returned')

    def test_company_vehicle_and_revision_boundary(self):
        for target in (Target('SYNTHETIC_B', 1, 'a'*64), Target('SYNTHETIC_A', 2, 'a'*64),
                       replace(self.target, input_revision='b'*64)):
            self.denied(target=target)
            self.denied(request=self.request(target=target), target=target)

    def test_model_and_transport_shape(self):
        for changes in ({'model':'other'}, {'store':True}, {'tools':[{'type':'web_search'}]},
                        {'input':[{'image_url':'https://invalid'}]}, {'reasoning':{'effort':'high'}}):
            self.denied(request=self.request({**self.body, **changes}))

    def test_tamper_and_size(self):
        self.denied(request=self.request(body_sha256='b'*64))
        self.denied(policy=replace(self.policy, max_request_bytes=1))

    def test_unknown_tokens_not_estimated_from_chars(self):
        for n in (0, -1, None, True, 1.2):
            self.denied(request=self.request(input_token_upper_bound=n))
        self.denied(request=self.request(token_count_source=''))

    def test_output_and_money_ceiling(self):
        for n in (6001, 0, True):
            self.denied(request=self.request({**self.body, 'max_output_tokens':n}))
        self.denied(policy=replace(self.policy, budget_microusd=12999))
        self.assertEqual(estimate_microusd(replace(self.policy,
            input_usd_per_million='0.0001', output_usd_per_million='0.0001'), 1, 1), 1)

    def test_replay_and_second_call_budget(self):
        t = Trial(self.policy); self.invoke(t)
        with self.assertRaises(ValueError): self.invoke(t)
        with self.assertRaises(ValueError): self.invoke(t, self.request({**self.body, 'input':'new fixture'}))
        self.assertEqual(len(self.calls), 1)

    def test_call_limit(self):
        t=Trial(replace(self.policy, max_calls=1, budget_microusd=999999))
        self.invoke(t)
        with self.assertRaises(ValueError): self.invoke(t, self.request({**self.body, 'input':'new fixture'}))
        self.assertEqual(len(self.calls), 1)

    def test_uncertain_not_retried_or_refunded(self):
        t = Trial(self.policy)
        def failure(body): raise TimeoutError('synthetic')
        with self.assertRaises(TimeoutError):
            t.synthetic_call(self.request(), observed_target=self.target, transport=failure)
        self.assertEqual(t.used, 13000)
        self.assertEqual(t.receipts[0]['status'], 'uncertain')
        with self.assertRaises(ValueError): self.invoke(t)
        self.assertEqual(self.calls, [])

    def test_real_scope_cannot_invoke(self):
        real=Target('REAL', 1, 'a'*64)
        self.denied(policy=replace(self.policy, targets=(real,)), request=self.request(target=real), target=real)

    def test_policy_rejects_unbounded_or_duplicate_targets(self):
        for targets in ((), [self.target], (self.target,self.target), tuple(Target('SYNTHETIC_A', i, 'a'*64) for i in range(1,7))):
            with self.assertRaises(ValueError): replace(self.policy, targets=targets)
        for n in (0, True, -1):
            with self.assertRaises(ValueError): replace(self.policy, max_calls=n)
        for rate in ('NaN', 'Infinity', '-1', '0'):
            with self.assertRaises(ValueError): replace(self.policy, input_usd_per_million=rate)


if __name__ == '__main__': unittest.main()
