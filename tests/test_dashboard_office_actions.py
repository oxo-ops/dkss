import copy
from pathlib import Path
import unittest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from dkss_app.dashboard_office_actions import office_actions


class OfficeActionsTests(unittest.TestCase):
    def test_scope_no_fabricated_safety_priority_no_mutation(self):
        safety = {'items': [dict(office='A', content='状態だけ', state='対策未確認', url='/safe'),
                            dict(office='B', content='他営業所', state='差し戻し', url='/secret')]}
        vehicles = {'mine': {'items': [dict(office='B', title='他所属の使用車両', url='/other'),
                                      dict(office='A', title='使用車両', url='/mine', priority='中')]},
                    'office': {'items': [dict(office='A', title='所属車両', url='/office', priority='高')]}}
        original = copy.deepcopy((safety, vehicles))
        rows = office_actions('A', safety, vehicles)
        self.assertEqual([r['url'] for r in rows], ['/safe', '/mine', '/office'])
        self.assertNotIn('priority', rows[0])
        self.assertEqual(rows[1]['priority'], '中')
        self.assertEqual((safety, vehicles), original)
        self.assertEqual(office_actions('', safety, vehicles), [])

    def test_five_previews_all_original_links_and_escape(self):
        env = Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parents[1] / 'templates')), autoescape=select_autoescape())
        issues = [dict(content=f'<script>項目{i}</script>', count=10-i, category='区分',
                       records=[dict(url=f'/source/{i}', date='2026-11-18', checklist='点検')]) for i in range(8)]
        actions = [dict(kind='安全', title=f'対応{i}', state='対策未確認', url=f'/action/{i}') for i in range(7)]
        html = env.get_template('partials/dashboard_office_trends.html').render(
            dashboard_office_check_trend={'answer_count': 8, 'issues': issues},
            dashboard_office_actions=actions, dashboard_scope_office='A')
        self.assertIn('残り3項目', html)
        self.assertIn('残り2件', html)
        self.assertEqual(html.count('class="office-trend-row"'), 8)
        self.assertEqual(html.count('class="office-action-link"'), 7)
        self.assertEqual(html.split('残り3項目')[0].count('class="office-trend-row"'), 5)
        self.assertNotIn('<script>', html)
        for i in range(8): self.assertIn(f'/source/{i}', html)
        for i in range(7): self.assertIn(f'/action/{i}', html)
        self.assertNotIn('data-priority=', html)


if __name__ == '__main__': unittest.main()
