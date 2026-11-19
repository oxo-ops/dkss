"""All common reflection cards omit the removed disclosure, retaining results/actions."""
import copy,unittest,os
from pathlib import Path
from html.parser import HTMLParser
from flask import render_template
from test_driving_ai_navigation import AiNavigationTests
from dkss_app.models import DrivingReportReflection
class Cards(AiNavigationTests):
 def test_all_cards_scopes_and_modes_preserve_results(self):
  _,context,_=self.generate_for(self.base,'record')
  template=self.m.app.jinja_env.get_template('driving_workspace_reflection.html')
  item=context['reflection']['items'][0]
  variants=[dict(item),dict(item,links=[]),dict(item,display_summary='次の確認 11/26')]
  ref=dict(context['reflection'],items=variants)
  original=copy.deepcopy(ref)
  before=[(x.id,x.cache_key,x.result_json) for x in DrivingReportReflection.query.all()]
  for demo in (False,True):
   for admin in (False,True):
    for snapshot in (False,True):
     state=dict(ref,snapshot=dict(ref,period_label='2026/11/01〜2026/11/18の分析')) if snapshot else ref
     with self.m.app.test_request_context('/'):
      html=render_template('driving_workspace_reflection.html',reflection=state,insights=context['insights'],driving_is_admin=admin,filter_query=context['filter_query'],public_demo_mode=demo)
     self.assertNotIn('根拠・比較条件を見る',html)
     self.assertEqual(html.count('<article '),3)
     self.assertNotIn('<details><summary>',html)
     for row in variants:
      self.assertIn(row['display_title'],html);self.assertIn(row['display_headline'],html);self.assertIn(row['action'],html)
     self.assertIn('次の確認 11/26',html);self.assertIn('対象日報を確認',html)
     self.assertEqual(ref,original)
     if os.environ.get('REFLECTION_CARD_OUT'):
      dest=Path(os.environ['REFLECTION_CARD_OUT']);dest.mkdir(parents=True,exist_ok=True)
      (dest/f'cards-{int(demo)}-{int(admin)}-{int(snapshot)}.html').write_text(html)
  self.assertEqual(before,[(x.id,x.cache_key,x.result_json) for x in DrivingReportReflection.query.all()])
def load_tests(loader,tests,pattern):return unittest.TestSuite([Cards('test_all_cards_scopes_and_modes_preserve_results')])
