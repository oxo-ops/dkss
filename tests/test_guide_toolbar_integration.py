"""Structural safeguards; rendered browser acceptance remains separate."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class GuideToolbarTests(unittest.TestCase):
 def test_single_entry_in_account_toolbar(self):
  html=(ROOT/'templates/base.html').read_text()
  include="{% include 'partials/first_use_guide.html' %}"
  self.assertEqual(html.count(include),1)
  self.assertLess(html.index('<div class="top-bar'),html.index(include))
  self.assertLess(html.index(include),html.index('id="notificationMenu"'))
 def test_toolbar_wraps_and_title_no_longer_reserves_fixed_space(self):
  css=(ROOT/'static/css/first_use_guide.css').read_text()
  self.assertIn('.top-bar:has(#firstUseGuide){flex-wrap:wrap}',css)
  self.assertIn('.main-content:has(> .dashboard-page) > .top-bar:has(#firstUseGuide){position:static;margin-bottom:12px}',css)
  self.assertIn('.main-content:has(> .top-bar #firstUseGuide) > .dashboard-page .dashboard-header{padding-right:0}',css)
  self.assertNotIn('text-overflow:ellipsis',css)
 def test_help_is_named_and_approved_plan_scope_present(self):
  html=(ROOT/'templates/partials/first_use_guide.html').read_text()
  self.assertIn('aria-label="この画面の使い方を見る"',html)
  self.assertIn("request.endpoint in ['dashboard', 'vehicle_checklist_results', 'vehicle_inspection_plans', 'driving_reports', 'vehicle_karte_list', 'pointouts']",html)
  self.assertIn('aria-controls="firstGuidePanel"',html)
