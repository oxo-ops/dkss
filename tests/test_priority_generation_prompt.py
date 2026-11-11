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
        items = {row['item_code']: row['content'] for row in get_daily_inspection_default()['items']}
        self.assertLessEqual(len(items['daily_02']), 24)
        self.assertLessEqual(len(items['daily_03']), 24)
        self.assertGreater(len(items['daily_18']), 24)
