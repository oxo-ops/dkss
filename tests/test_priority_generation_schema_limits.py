"""Bound generation enums without dropping refs or weakening server validation.

The real generator serializes every request. Only urllib transport is synthetic;
no API connection, DB, cache rebuild or model call is made.
"""
from copy import deepcopy
import io
import json
import os
import unittest
from unittest.mock import patch

import vehicle_karte_analysis_ai as generator
from vehicle_priority_inputs import generation_priority_inputs


def payload_with_refs(refs):
    return {'records': [dict(source_id='inspection:1', date='2026-11-11', type='日常点検',
        priority_inputs=[dict(ref=ref, kind='inspection_defect', source_ids=['inspection:1'],
                             target='ブレーキ', display_target='ブレーキ') for ref in refs])],
        'maintenance_knowledge': []}


def enum_lists(value):
    if isinstance(value, dict):
        if isinstance(value.get('enum'), list):
            yield value['enum']
        for child in value.values():
            yield from enum_lists(child)
    elif isinstance(value, list):
        for child in value:
            yield from enum_lists(child)


def recommendation(offer):
    return dict(priority='中', category='整備・点検', target=offer['display_target'],
        current_state='元記録の指摘', timing='状態を確認後', title='登録内容を確認',
        reason='登録された指摘を確認するため', action='対象の状態を確認', uncertainty='実車の状態は未確認',
        confirmation_steps=['対象の状態を確認'], confirmation_branch='結果は責任者が判断',
        basis_type='記録上の指摘・対応', knowledge_ids=[], source_ids=offer['source_ids'],
        priority_input_ref=offer['ref'], risk_status='unassessed', risk_basis='unknown',
        risk_effect='', risk_condition='', risk_evidence=[])


class PriorityGenerationSchemaLimitsTests(unittest.TestCase):
    def capture(self, payload, items=None, *, once=False):
        self.requests = []
        response = dict(overview='合成試験', recommendations=items or [])
        def fake_transport(request, **kwargs):
            self.requests.append(json.loads(request.data))
            return io.BytesIO(json.dumps({'status': 'completed', 'output': [{'content': [
                {'type': 'output_text', 'text': json.dumps(response, ensure_ascii=False)}]}]}).encode())
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-local-test-only'}), \
                patch.object(generator.urllib.request, 'urlopen', side_effect=fake_transport):
            return (generator._analyze_vehicle_karte_once if once else generator.analyze_vehicle_karte)(payload)

    def schema(self):
        return self.requests[-1]['text']['format']['schema']

    def ref_schema(self):
        return self.schema()['properties']['recommendations']['items']['properties']['priority_input_ref']

    def assert_input_preserved(self, payload):
        wire = json.loads(self.requests[-1]['input'])
        expanded = generator.expand_vehicle_karte_analysis_wire_payload(wire)
        self.assertEqual(expanded, {k: v for k, v in payload.items() if not k.startswith('_')})

    def test_count_boundary_includes_empty_ref_and_does_not_drop_offers(self):
        for count, has_enum in ((199, True), (200, False), (251, False)):
            with self.subTest(count=count):
                payload = payload_with_refs([f'proof:{index}' for index in range(count)])
                before = deepcopy(payload)
                self.capture(payload)
                if has_enum:
                    self.assertEqual(set(self.ref_schema()['enum']), {''} | set(generation_priority_inputs(payload)))
                else:
                    self.assertEqual(self.ref_schema(), {'type': 'string'})
                self.assertEqual(payload, before)
                self.assert_input_preserved(payload)

    def test_character_boundary_is_conservative_even_with_fewer_than_250_refs(self):
        for chars, has_enum in ((12000, True), (12001, False)):
            with self.subTest(chars=chars):
                payload = payload_with_refs(['a' * 6000, 'b' * (chars - 6000)])
                self.capture(payload)
                self.assertEqual('enum' in self.ref_schema(), has_enum)
                self.assert_input_preserved(payload)

    def test_all_dynamic_enums_together_stay_below_total_schema_budget(self):
        payload = payload_with_refs([f'proof:{index}' for index in range(199)])
        payload['maintenance_knowledge'] = [dict(source_id=f'knowledge:{i}') for i in range(199)]
        self.capture(payload)
        enums = list(enum_lists(self.schema()))
        self.assertEqual(len(self.ref_schema()['enum']), 200)
        self.assertEqual(sum(map(len, enums)), 613)  # refs200 + sources200 + knowledge199 + fixed14
        self.assertLessEqual(sum(map(len, enums)), 1000)
        for values in enums:
            self.assertLessEqual(len(values), 200)
            self.assertLessEqual(sum(len(value) for value in values), 12000)
        self.assert_input_preserved(payload)

    def test_twenty_inspections_with_twenty_defects_reach_transport_without_oversized_enum(self):
        payload = {'records': [], 'maintenance_knowledge': []}
        for record_id in range(1, 21):
            sid = f'inspection:{record_id}'
            offers = [dict(ref=f'{sid}:defect:{defect_no}:{record_id * 20 + defect_no:024x}',
                kind='inspection_defect', source_ids=[sid], target=f'点検対象{defect_no}',
                display_target=f'点検対象{defect_no}') for defect_no in range(1, 21)]
            payload['records'].append(dict(source_id=sid, date='2026-11-11', type='日常点検', priority_inputs=offers))
        before = deepcopy(payload)
        refs = generation_priority_inputs(payload)
        self.assertEqual(len(refs), 400)
        self.assertGreater(sum(map(len, refs)), 15000)
        self.assertEqual(len(generator.build_vehicle_karte_analysis_batches(payload)), 1)
        self.assertEqual(self.capture(payload)['recommendations'], [])
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.ref_schema(), {'type': 'string'})
        self.assertLess(sum(len(values) for values in enum_lists(self.schema())), 1000)
        self.assertEqual(payload, before)
        self.assert_input_preserved(payload)

    def test_fallback_still_rejects_invented_ref_wrong_category_target_or_source(self):
        payload = payload_with_refs([f'proof:{index}' for index in range(200)])
        payload['records'].append(dict(source_id='inspection:2', date='2026-11-11', type='日常点検'))
        offer = next(iter(generation_priority_inputs(payload).values()))
        valid = recommendation(offer)
        self.assertEqual(self.capture(payload, [valid])['recommendations'][0]['priority_input_ref'], offer['ref'])
        for changes, error in [
            ({'priority_input_ref': 'invented-proof'}, 'INVALID_PRIORITY_INPUT_REFERENCE'),
            ({'category': '記録確認'}, 'INVALID_PRIORITY_INPUT_CATEGORY'),
            ({'target': '別の部品'}, 'INVALID_PRIORITY_INPUT_TARGET'),
            ({'source_ids': ['inspection:2']}, 'INVALID_PRIORITY_INPUT_REFERENCE'),
        ]:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ValueError, error):
                    self.capture(payload, [{**valid, **changes}])
                self.assertEqual(self.ref_schema(), {'type': 'string'})

    def test_compressed_final_fallback_cannot_select_an_unreviewed_original_ref(self):
        original = payload_with_refs([f'proof:{index}' for index in range(201)])
        offers = list(generation_priority_inputs(original).values())
        payload = dict(records=[{k: v for k, v in original['records'][0].items() if k != 'priority_inputs'}],
            maintenance_knowledge=[], analysis_stage='final', _risk_evidence_payload=original,
            review_candidates=[dict(candidate_id=f'candidate:{i}', proposal=recommendation(offer))
                               for i, offer in enumerate(offers[:200])])
        self.capture(payload, [recommendation(offers[199])], once=True)
        self.assertEqual(self.ref_schema(), {'type': 'string'})
        self.assertEqual(set(generation_priority_inputs(payload)), {o['ref'] for o in offers[:200]})
        self.assert_input_preserved(payload)
        with self.assertRaisesRegex(ValueError, 'INVALID_PRIORITY_INPUT_REFERENCE'):
            self.capture(payload, [recommendation(offers[200])], once=True)


    def test_only_confirmed_server_offers_add_exact_citations_and_minimum_saved_label(self):
        payload = payload_with_refs(['confirmation:42:' + 'a' * 24])
        offer = payload['records'][0]['priority_inputs'][0]
        offer.update(kind='confirmed_priority', minimum_saved_priority='高',
                     source_ids=['inspection:1', 'priority_confirmation:42', 'inspection_observation:original'])
        item = recommendation(offer); item['priority'] = '低'
        result = self.capture(payload, [item])
        self.assertEqual(result['recommendations'][0]['priority'], '高')
        self.assertEqual(result['recommendations'][0]['source_ids'], offer['source_ids'])
        self.assert_input_preserved(payload)
        with self.assertRaisesRegex(ValueError, 'INVALID_ANALYSIS_SOURCES'):
            self.capture(payload, [{**item, 'source_ids': offer['source_ids'] + ['invented:1']}])
        plain = deepcopy(payload); plain['records'][0]['priority_inputs'][0]['kind'] = 'inspection_defect'
        with self.assertRaisesRegex(ValueError, 'INVALID_ANALYSIS_SOURCES'):
            self.capture(plain, [item])
        invalid = deepcopy(payload); invalid['records'][0]['priority_inputs'][0]['minimum_saved_priority'] = 60
        with self.assertRaisesRegex(ValueError, 'INVALID_PRIORITY_INPUT_CONFIRMED_FLOOR'):
            self.capture(invalid, [item])
