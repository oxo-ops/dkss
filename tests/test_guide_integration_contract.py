from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
class GuideIntegrationContract(unittest.TestCase):
 def test_no_original_phone_screenshot_is_shipped(self):
  self.assertFalse((ROOT/'static/guide/inspection-detail.png').exists())
  partial=(ROOT/'templates/partials/first_use_guide.html').read_text()
  self.assertNotIn('guide/inspection-detail.png',partial)
  self.assertIn('guide/inspection-detail-open.png',partial)
  import hashlib
  self.assertEqual(hashlib.sha256((ROOT/'static/guide/inspection-detail-open.png').read_bytes()).hexdigest(),'a27219ca3113e1d78314244cf2dd838624f10c2a1e4e2c8f1200a3fd8e177b01')
 def test_operation_notification_keeps_its_own_semantics(self):
  template=(ROOT/'templates/vehicle_checklist_results.html').read_text()
  operation=template.split('id="operation_notify_user_search"',1)[1].split('>',1)[0]
  self.assertNotIn('data-guide-title',operation)
  self.assertNotIn('data-guide-text',operation)
  self.assertIn('.vehicle-check-complete-form .approval-user-search',(ROOT/'static/js/first_use_guide.js').read_text())
 def test_template_drives_daily_vs_custom_approval(self):
  template=(ROOT/'templates/vehicle_checklist_results.html').read_text()
  self.assertEqual(template.count('data-guide-title='),1)
  self.assertIn("else '承認依頼先を選ぶ'",template)
  self.assertIn("else '名前で検索し、候補から承認を依頼する人を選びます。'",template)
if __name__=='__main__':unittest.main()
