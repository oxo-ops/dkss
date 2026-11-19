import unittest
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, DictLoader
import re
ROOT=Path(__file__).resolve().parents[1]
class Contract(unittest.TestCase):
 def render(self, manage, title="営業所安全確認", count=1):
  env=Environment(loader=DictLoader({'base.html':'{% block page_styles %}{% endblock %}<main class="main-content">{% block content %}{% endblock %}</main>', 'results.html':(ROOT/'templates/safety_checklist_results.html').read_text()}))
  result=dict(index=17,checked_by='試験運転者',checked_date='2026-11-19',target_type='office',target_office='試験営業所',status='承認待ち',approved_date=None,can_manage=manage)
  return env.get_template('results.html').render(checklist={},checklist_navigation={},checklist_result_heading=lambda *x:'<h2>'+title+'</h2>',checklist_index=13,checklist_periods=[dict(start_date=datetime(2026,11,18),end_date=datetime(2026,11,18),results=[dict(result,index=17+i) for i in range(count)])],csrf_token=lambda:'synthetic-token',url_for=lambda endpoint,filename,**kw:'/static/'+filename)
 def test_manager_controls_keep_contracts(self):
  s=self.render(True)
  self.assertEqual(s.count('href="/safety/checklist-results/17"'),2)
  self.assertEqual(s.count('href="/safety/checklist-results/17/edit"'),2)
  self.assertEqual(s.count('method="post"'),2)
  self.assertEqual(s.count('action="/safety/checklist-results/17/delete"'),2)
  self.assertEqual(s.count('name="csrf_token" value="synthetic-token"'),2)
  self.assertIn('<span>詳細</span>',s)
  self.assertNotIn('詳細を見る',s)
 def test_readonly_stays_readonly(self):
  s=self.render(False)
  for c in ['btn-edit','btn-delete','<form']:
   self.assertNotIn(c,s)
  self.assertEqual(s.count('href="/safety/checklist-results/17"'),2)
 def test_delete_confirmation_untouched(self):
  js=(ROOT/'static/js/safety_checklist_results.js').read_text()
  self.assertIn('window.confirm("この結果を削除しますか？")',js)
  self.assertIn('event.preventDefault()',js)
if __name__=='__main__':unittest.main()
