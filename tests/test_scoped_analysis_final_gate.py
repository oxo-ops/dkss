import hashlib
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from tools.quality.scoped_analysis.final_gate import Envelope, RESPONSES_URL, synthetic_final_call
from tools.quality.scoped_analysis.ledger import Ledger
from tools.quality.scoped_analysis.pilot import Policy, Request, Target, SOL_STANDARD_30M, SOL_RATE_SOURCE


class FinalGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Target('SYNTHETIC_GATE', 1, 'a'*64)
        self.policy = Policy((self.target,), 'gpt-6.1-sol', 2, 6000, 10000,
                             100000, '2', '10', SOL_RATE_SOURCE, '2026-11-12',
                             SOL_STANDARD_30M, RESPONSES_URL)
        self.ledger = Ledger.create(Path(self.tmp.name)/'gate.sqlite', self.policy)
        body = dict(model='gpt-6.1-sol', instructions='synthetic', input='{}', text={},
                    reasoning={'effort':'low'}, max_output_tokens=6000, store=False,
                    service_tier='default')
        raw = json.dumps(body)
        self.request = Request(self.target, raw, hashlib.sha256(raw.encode()).hexdigest(),
                               1000, 'synthetic-counter-v1')
        self.envelope = Envelope(RESPONSES_URL, raw.encode())

    def call(self, envelope=None, counter=None, transport=None, request=None):
        return synthetic_final_call(self.ledger, request or self.request,
            envelope or self.envelope, observed_target=self.target,
            count_input_tokens=counter or (lambda raw, model: (1000, 'synthetic-counter-v1')),
            transport=transport or (lambda envelope: 'ok'))

    def test_exact_envelope_and_reserved_receipt_before_callback(self):
        def counter(raw, model):
            self.assertIs(raw, self.envelope.body)
            self.assertEqual(model, 'gpt-6.1-sol')
            return 1000, 'synthetic-counter-v1'
        def transport(envelope):
            self.assertIs(envelope, self.envelope)
            receipt = self.ledger.receipts()[0]
            self.assertEqual(receipt[1], self.request.body_sha256)
            self.assertEqual(receipt[2:], (62500, 'reserved'))
            return 'ok'
        self.assertEqual(self.call(counter=counter, transport=transport), 'ok')
        self.assertEqual(self.ledger.receipts()[0][3], 'returned')

    def test_mutable_envelope_impostor_rejected(self):
        from types import SimpleNamespace
        impostor = SimpleNamespace(url=self.envelope.url, body=self.envelope.body)
        def forbidden(*args):
            self.fail('invalid envelope reached callback')
        with self.assertRaisesRegex(ValueError, 'INVALID_FINAL_ENVELOPE'):
            self.call(impostor, counter=forbidden, transport=forbidden)
        self.assertEqual(self.ledger.receipts(), [])

    def test_endpoint_variants_rejected_without_reservation(self):
        for url in (RESPONSES_URL+'?x=1', RESPONSES_URL+'/', 'https://example.com/v1/responses',
                    'http://api.openai.com/v1/responses', 'https://user@api.openai.com/v1/responses'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.call(replace(self.envelope, url=url))
        self.assertEqual(self.ledger.receipts(), [])

    def test_final_body_changes_rejected_without_reservation(self):
        for raw in (self.envelope.body+b' ', bytearray(self.envelope.body),
                    self.envelope.body.replace(b'default', b'priority'),
                    self.envelope.body.replace(b'gpt-6.1-sol', b'other-model')):
            with self.subTest(raw=type(raw)), self.assertRaises(ValueError):
                self.call(replace(self.envelope, body=raw))
        self.assertEqual(self.ledger.receipts(), [])

    def test_rehashed_invalid_model_tier_and_output_still_rejected(self):
        for changes in ({'model': 'other'}, {'service_tier': 'priority'},
                        {'max_output_tokens': 6001}):
            body = {**json.loads(self.request.body_json), **changes}
            raw = json.dumps(body)
            request = replace(self.request, body_json=raw,
                              body_sha256=hashlib.sha256(raw.encode()).hexdigest())
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call(Envelope(RESPONSES_URL, raw.encode()), request=request)
        self.assertEqual(self.ledger.receipts(), [])

    def test_recount_cannot_exceed_approved_bound_or_change_source(self):
        for count, source in ((1001, 'synthetic-counter-v1'), (True, 'synthetic-counter-v1'),
                              (0, 'synthetic-counter-v1'), (1000, 'different'), (1000, '')):
            with self.subTest(count=count, source=source), self.assertRaises(ValueError):
                self.call(counter=lambda raw, model: (count, source))
        self.assertEqual(self.ledger.receipts(), [])

    def test_timeout_persists_uncertain_and_forbids_retry(self):
        def fail(envelope):
            raise TimeoutError('synthetic')
        with self.assertRaises(TimeoutError):
            self.call(transport=fail)
        self.assertEqual(self.ledger.receipts()[0][3], 'uncertain')
        with self.assertRaisesRegex(ValueError, 'UNRESOLVED'):
            self.call()

    def test_real_company_refused_before_counter_or_callback(self):
        target = replace(self.target, company='real-company')
        policy = replace(self.policy, targets=(target,))
        self.ledger = Ledger.create(Path(self.tmp.name)/'real.sqlite', policy)
        def forbidden(*args):
            self.fail('real target reached callback')
        with self.assertRaisesRegex(ValueError, 'SYNTHETIC_ONLY'):
            self.call(counter=forbidden, transport=forbidden)
        self.assertEqual(self.ledger.receipts(), [])
