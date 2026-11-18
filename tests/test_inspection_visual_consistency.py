"""Prevent the reported narrow day heading and divergent control style."""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
class InspectionVisualConsistency(unittest.TestCase):
 def test_mobile_day_label_has_room_and_table_is_symmetric(self):
  css=(ROOT/'static/css/vehicle_checklist_compact.css').read_text()
  self.assertIn('width: 36px !important; min-width: 36px !important; max-width: 36px !important;',css)
  self.assertIn('margin-left: 0; margin-right: 0;',css)
  self.assertNotIn('width: calc(100% + 16px)',css)
 def test_control_palette_matches_existing_standard_buttons(self):
  css=(ROOT/'static/css/vehicle_checklist_compact.css').read_text()
  shared=(ROOT/'static/css/style.css').read_text()
  for token in ('#d4dcf3','#f5f5ff','#405589','#bdb4f3','#eeebff'):
   self.assertIn(token,css);self.assertIn(token,shared)
  self.assertNotIn('background: var(--dkss-action-blue)',css)
 def test_item_stays_a_plain_text_button_with_guide_discovery(self):
  css=(ROOT/'static/css/vehicle_checklist_compact.css').read_text().split('/* Native button:',1)[1]
  self.assertIn('color: inherit;',css);self.assertIn('text-decoration: none;',css)
  template=(ROOT/'templates/vehicle_checklist_results.html').read_text()
  self.assertIn('aria-controls="detailModal"',template)
  guide=(ROOT/'static/js/first_use_guide.js').read_text()
  self.assertIn('項目名を押すと、評価基準や詳細が開きます。',guide)
