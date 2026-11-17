import unittest
from pathlib import Path
from jinja2 import Environment,FileSystemLoader
R=Path(__file__).resolve().parents[1]
class HomeTests(unittest.TestCase):
 def setUp(self):self.env=Environment(loader=FileSystemLoader(R/'templates'),autoescape=True)
 def test_safety_action_deadline_and_record_link(self):
  item=dict(content='雨天の構内で滑りやすいことを確認した。'*10,url='/pointouts/9',state='対策確認待ち',action='写真と対策内容を確認',due_date='2026-11-19',location='青凪体験運転者',office='中央',date='2026-10-28')
  s=self.env.get_template('partials/dashboard_safety_attention.html').render(dashboard_safety_attention={'items':[item],'available':True})
  for text in [item['content'],item['url'],item['state'],item['action'],item['due_date'],item['location']]:self.assertIn(text,s)
  for text in ['冒頭の文を表示','全文をこの画面で読む','上の文章から','記録日']:self.assertNotIn(text,s)
 def test_safety_escape_and_remaining(self):
  rows=[dict(content='<script>alert(1)</script>',url='/pointouts/9',state='差し戻し',action='確認',due_date='',location='A')]*4
  s=self.env.get_template('partials/dashboard_safety_attention.html').render(dashboard_safety_attention={'items':rows,'available':True})
  self.assertIn('&lt;script&gt;',s);self.assertNotIn('<script>',s);self.assertIn('残り1件',s)
 def test_ai_keeps_existing_evidence_link_state_timing_and_priority(self):
  t=(R/'templates/index.html').read_text();start=t.index('{% macro attention_table');end=t.index('{% endmacro %}',start)+len('{% endmacro %}');fn=self.env.from_string(t[start:end]).module.attention_table
  row=dict(vehicle_number='101',url='/vehicle/karte/647/analysis',priority='中',priority_assessment={'calculation_status':'legacy_preserved'},target='タイヤ',title='記録',action='空気圧を確認',reason='長い根拠'*50,timing='次の運行前',feedback_status='in_progress',proposal_id='p1')
  s=fn([row],True)
  for x in ['101','タイヤ','空気圧を確認','次の運行前','対応中','前回評価','/vehicle/karte/647/analysis#proposal=p1']:self.assertIn(x,s)
  self.assertNotIn('長い根拠',s);self.assertNotIn('保存版・算定根拠を確認',s)
 def test_full_template_parse(self):self.env.get_template('index.html')
if __name__=='__main__':unittest.main()
