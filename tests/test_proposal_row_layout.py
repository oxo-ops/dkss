import unittest
from pathlib import Path
from jinja2 import Environment
R=Path(__file__).resolve().parents[1]
class Tests(unittest.TestCase):
 def render(self,**kw):
  t=(R/'templates/index.html').read_text();a=t.index('{% macro attention_table');b=t.index('{% endmacro %}',a)+len('{% endmacro %}')
  item=dict(priority='中',target='前照灯、方向指示器、車幅灯、非常点滅灯、その他',title='title',action='左前車幅灯の光源・接点・通電状態を確認する。',timing='夜間・薄暮時の使用前',vehicle_number='品川 100 か 101',feedback_status='open',proposal_id='p1',url='/vehicle/karte/647/analysis',priority_assessment={'calculation_status':'legacy_preserved'})
  item.update(kw);return Environment(autoescape=True).from_string(t[a:b]).module.attention_table([item])
 def test_exact_fields(self):
  s=self.render()
  for x in ['対応優先度：中','車幅灯','左前車幅灯','目安：夜間・薄暮時の使用前','未着手','品川 100 か 101','#proposal=p1']:self.assertIn(x,s)
  self.assertNotIn('前回評価',s)
 def test_states(self):
  for value,label in [('open','未着手'),('accepted','採用'),('in_progress','対応中'),('completed','完了'),('dismissed','見送り')]:self.assertIn(label,self.render(feedback_status=value))
 def test_escape(self):
  s=self.render(target='<b>title</b>',action='<img>',timing='<script>')
  self.assertIn('&lt;b&gt;',s);self.assertNotIn('<script>',s)
 def test_unknown(self):
  s=self.render(priority='',timing='',feedback_status='')
  self.assertIn('未評価',s);self.assertIn('時期の判断材料不足',s)
if __name__=='__main__':unittest.main()
