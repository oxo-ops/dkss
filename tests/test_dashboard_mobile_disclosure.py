"""Compact home keeps action/expiry and an existing accessible detail link."""
import unittest
from test_dashboard_safety_attention import DashboardSafetyAttentionTests as Base
class DashboardMobileDisclosureTests(unittest.TestCase):
 setUpClass=classmethod(Base.setUpClass.__func__)
 tearDownClass=classmethod(Base.tearDownClass.__func__)
 setUp=Base.setUp;tearDown=Base.tearDown;configure=Base.configure;page=Base.page;patrol=Base.patrol
 def test_long_record_is_clipped_only_visually_with_original_detail_url(self):
  self.configure();text='【体験用・架空】'+('路面と歩行者動線の確認。'*50)+'接触・負傷なし。'
  row=self.patrol(text,countermeasure_due_date='2026-11-19');html,root=self.page();card=root.find(cls='dashboard-safety-content')[0];link=card.find(cls='dashboard-safety-opening')[0]
  self.assertIn(text.removeprefix('【体験用・架空】'),link.text);self.assertEqual(link.attrs['href'],f'/pointouts/{row.id}')
  self.assertFalse(card.find(cls='dashboard-safety-story'));self.assertNotIn('冒頭の文を表示',card.text)
  self.assertIn('2026-11-19',card.text);self.assertIn('写真と対策内容を確認',card.text)
 def test_custom_content_is_escaped_and_distinct(self):
  self.configure()
  for text in ['<img src=x onerror=alert(1)> 負傷なし。','異常とは判断していない確認中の記録'*20,'「引用文。まだ引用内の文」'+'続き'*40]:self.patrol(text)
  html,root=self.page();self.assertNotIn('<img src=x onerror=alert(1)>',html)
  titles=[x.text for x in root.find(cls='dashboard-safety-story-title')];self.assertEqual(len(set(titles)),3)
  self.assertTrue(all(x.attrs['href'].startswith('/pointouts/') for x in root.find(cls='dashboard-safety-opening')))
del Base
