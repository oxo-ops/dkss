"""The normal generator preserves exact short inspection targets, not severity guesses."""
from pathlib import Path
import unittest
from daily_inspection_defaults import get_daily_inspection_default


class PriorityGenerationPromptTests(unittest.TestCase):
    def test_strict_source_identity_guidance_preserves_existing_short_target_contract(self):
        source = (Path(__file__).resolve().parents[1] / 'vehicle_karte_analysis_ai.py').read_text()
        self.assertIn('findings.contentの原文が24文字以内なら、その原文をtargetへ保持', source)
        self.assertIn('複数の指摘・別事象を1つの項目へ推測で対応付けない', source)
        self.assertIn('点数やpriority_assessmentは出力せず', source)
        self.assertIn('targetはdisplay_target', source)
        self.assertIn('別部品名や独自の短縮名へ言い換えません', source)
        items = {row['item_code']: row['content'] for row in get_daily_inspection_default()['items']}
        self.assertLessEqual(len(items['daily_02']), 24)
        self.assertLessEqual(len(items['daily_03']), 24)
        self.assertGreater(len(items['daily_18']), 24)

    def test_compressed_full_history_final_schema_keeps_only_reviewed_server_refs(self):
        import io
        import json
        import os
        from unittest.mock import patch
        import vehicle_karte_analysis_ai as generator
        from vehicle_priority_inputs import generation_priority_inputs, validate_priority_input
        records = []
        for index in range(81):
            sid = f'inspection:{index + 1}'
            offer = dict(ref=f'{sid}:defect:1:server-proof', kind='inspection_defect',
                         source_ids=[sid], target=f'対象{index}', display_target=f'対象{index}')
            records.append(dict(source_id=sid, date='2026-11-11', type='日常点検',
                content=f'{index:03}:' + 'x' * 2100, priority_inputs=[offer]))
        payload = {'records': records, 'maintenance_knowledge': []}
        original_once = generator._analyze_vehicle_karte_once
        final_seen, request_seen = {}, {}
        def fake_response(request, **kwargs):
            request_seen.update(json.loads(request.data))
            return io.BytesIO(json.dumps({'status': 'completed', 'output': [{'content': [
                {'type': 'output_text', 'text': json.dumps({'overview': '合成確認', 'recommendations': []})}]}]}).encode())
        def stage(value, on_progress=None):
            if value.get('analysis_stage') == 'partial':
                option = value['records'][0]['priority_inputs'][0]
                return {'recommendations': [dict(priority='中', category='整備・点検',
                    target=option['target'], source_ids=option['source_ids'], priority_input_ref=option['ref'])]}
            if value.get('analysis_stage') == 'review':
                return {'candidate_reviews': [dict(candidate_id=c['candidate_id'], relation='unrelated',
                    source_ids=[], reason='この組では追加根拠なし') for c in value['review_candidates']]}
            final_seen.update(value)
            return original_once(value, on_progress=on_progress)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-local-test-only'}), \
                patch.object(generator, '_analyze_vehicle_karte_once', side_effect=stage), \
                patch.object(generator.urllib.request, 'urlopen', side_effect=fake_response):
            result = generator.analyze_vehicle_karte(payload)
        self.assertEqual(result['recommendations'], [])
        self.assertTrue(final_seen['history_review_scope']['complete'])
        self.assertNotIn('priority_inputs', final_seen['records'][0])
        reviewed = {row['proposal']['priority_input_ref'] for row in final_seen['review_candidates']}
        schema = request_seen['text']['format']['schema']
        allowed = schema['properties']['recommendations']['items']['properties']['priority_input_ref']['enum']
        self.assertEqual(set(allowed), {''} | reviewed)
        self.assertEqual(set(generation_priority_inputs(final_seen)), reviewed)
        self.assertNotIn('_risk_evidence_payload', request_seen['input'])
        # The final validator uses the identical selected-reference contract.
        chosen = dict(final_seen['review_candidates'][0]['proposal'])
        validate_priority_input(chosen, final_seen)
        excluded = next(row['priority_inputs'][0] for row in records if row['priority_inputs'][0]['ref'] not in reviewed)
        chosen.update(priority_input_ref=excluded['ref'], target=excluded['target'], source_ids=excluded['source_ids'])
        with self.assertRaises(ValueError): validate_priority_input(chosen, final_seen)
