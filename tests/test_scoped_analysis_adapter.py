import json
import unittest
from dataclasses import replace
from unittest.mock import patch
from tools.quality.scoped_analysis.pilot import Policy, Target, Trial, digest
from tools.quality.scoped_analysis.adapter import prepare_scoped_request
from vehicle_karte_analysis_ai import _analyze_vehicle_karte_once, prepare_vehicle_karte_analysis_request


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.payload = {'vehicle_source': {'source_id': 'vehicle:1'},
                        'records': [{'source_id':'maintenance:1', 'detail':'synthetic repair'}]}
        self.target = Target('SYNTHETIC_A', 1, digest(self.payload))
        self.policy = Policy((self.target,), 'synthetic-model', 1, 6000, 200000, 100000,
                             '1', '2', 'synthetic rate, not provider price', '2026-11-12')

    def prepare(self, **kw):
        return prepare_scoped_request(self.policy, self.target, kw.pop('payload', self.payload),
            observed_company=kw.pop('company', 'SYNTHETIC_A'), observed_vehicle_id=1,
            count_input_tokens=lambda raw, model: (1000, 'synthetic counter fixture'), **kw)

    def test_actual_request_builder_to_budget_guard(self):
        class NoEnvironment(dict):
            def get(self, *args): raise AssertionError('environment access forbidden')
        with patch('vehicle_karte_analysis_ai.os.environ', NoEnvironment()), patch(
                'urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
            req = self.prepare()
        body, receipt = Trial(self.policy).prepare(req, observed_target=self.target)
        self.assertEqual(receipt['reserved_microusd'], 13000)
        self.assertEqual(req.body_json, json.dumps(body))
        self.assertIn('schema', body['text']['format'])
        self.assertIn('maintenance:1', body['input'])
        self.assertGreater(len(body['instructions']), 1000)

    def test_dry_body_matches_actual_transport_body(self):
        class Captured(BaseException): pass
        sent = []
        def capture(req, **kw):
            sent.append(json.loads(req.data))
            raise Captured()
        expected = prepare_vehicle_karte_analysis_request(self.payload, model='synthetic-model')
        with patch('vehicle_karte_analysis_ai.os.environ',
                   {'OPENAI_API_KEY':'sk-synthetic-not-a-key', 'OPENAI_MODEL':'synthetic-model'}), \
             patch('urllib.request.urlopen', side_effect=capture):
            with self.assertRaises(Captured):
                _analyze_vehicle_karte_once(self.payload)
        self.assertEqual(sent, [expected])

    def test_scope_and_payload_version_fail_before_counter(self):
        for kwargs in ({'company':'OTHER'}, {'payload':{**self.payload, 'extra':'changed'}}):
            with self.assertRaises(ValueError): self.prepare(**kwargs)

    def test_multiple_batches_rejected_without_partial_output(self):
        payload = {'records':[{'source_id':f'maintenance:{i}'} for i in range(81)]}
        with self.assertRaisesRegex(ValueError, 'MULTI_BATCH'):
            prepare_vehicle_karte_analysis_request(payload, model='synthetic-model')

    def test_missing_evidence_and_model_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'NO_EVIDENCE'):
            prepare_vehicle_karte_analysis_request({}, model='synthetic-model')
        with self.assertRaisesRegex(ValueError, 'MODEL_REQUIRED'):
            prepare_vehicle_karte_analysis_request(self.payload, model='')
