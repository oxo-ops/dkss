import unittest
from dataclasses import replace
from unittest.mock import patch
from tools.quality.scoped_analysis.count_material import prepare_count_material, bind_supplied_count
from tools.quality.scoped_analysis.pilot import Target, digest
import json


class CountMaterialTests(unittest.TestCase):
    def setUp(self):
        self.payload = {'vehicle_source': {'source_id': 'vehicle:1'},
                        'records': [{'source_id': 'maintenance:1', 'detail': 'synthetic-only'}]}
        self.target = Target('SYNTHETIC_COUNT', 1, digest(self.payload))
        self.material = prepare_count_material(self.payload, target=self.target, model='gpt-6.1-sol')

    def bind(self, material=None, response=None, **kw):
        m = material or self.material
        args = dict(observed_generation_sha256=m.generation_sha256, observed_count_sha256=m.count_sha256)
        args.update(kw)
        return bind_supplied_count(m, response or {'object': 'response.input_tokens', 'input_tokens': 123}, **args)

    def test_count_includes_all_input_affecting_fields_and_not_output_controls(self):
        body = json.loads(self.material.generation_json)
        self.assertEqual(json.loads(self.material.count_json), {k: body[k] for k in ('model','instructions','input','text','reasoning')})
        self.assertEqual(body['service_tier'], 'default')
        self.assertEqual(body['max_output_tokens'], 6000)
        self.assertNotIn('synthetic-only', repr(self.material))
        evidence = self.bind()
        self.assertFalse(evidence['provider_provenance_verified'])
        self.assertFalse(evidence['generation_authorized'])

    def test_changed_generation_bytes_count_or_observed_hash_rejected(self):
        for m in (replace(self.material,generation_json=self.material.generation_json+' '),
                  replace(self.material,count_json=self.material.count_json+' ')):
            with self.assertRaisesRegex(ValueError,'BINDING'): self.bind(m)
        with self.assertRaisesRegex(ValueError,'BINDING'):
            self.bind(observed_generation_sha256='0'*64)
        with self.assertRaisesRegex(ValueError,'BINDING'):
            self.bind(observed_count_sha256='0'*64)

    def test_no_assumed_zero_or_boolean_count(self):
        for value in (None,0,-1,True,'123'):
            with self.assertRaisesRegex(ValueError,'INVALID'):
                self.bind(response={'object':'response.input_tokens','input_tokens':value})

    def test_changed_input_or_limited_cohort_rejected(self):
        for payload in ({**self.payload,'extra':'changed'},
                        {**self.payload,'comparison':{'comparison_scope':{'acceptance_limited':True}}}):
            with self.assertRaisesRegex(ValueError,'SCOPE_OR_REVISION'):
                prepare_count_material(payload,target=self.target,model='gpt-6.1-sol')

    def test_model_requires_explicit_supported_value(self):
        for model in ('',None,'other'):
            with self.assertRaisesRegex(ValueError,'MODEL'):
                prepare_count_material(self.payload,target=self.target,model=model)

    def test_builder_does_not_lookup_credentials_or_transmit(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')), patch(
                'vehicle_karte_analysis_ai.os.environ', {}):
            self.assertEqual(prepare_count_material(self.payload,target=self.target,model='gpt-6.1-sol'),self.material)
