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

    def test_safety_then_vehicle_stable_groups(self):
        safety = {'items': [dict(office='A', content='s1', url='/s1'),
                            dict(office='B', content='private', url='/hidden'),
                            dict(office='A', content='s2', url='/s2')]}
        vehicles = {'mine': {'items': [dict(office='A', title='v1', url='/v1', priority='低')]},
                    'office': {'items': [dict(office='A', title='v2', url='/v2', priority='高')]}}
        before = copy.deepcopy((safety, vehicles))
        rows = office_actions('A', safety, vehicles)
        self.assertEqual([r['url'] for r in rows], ['/s1','/s2','/v1','/v2'])
        self.assertEqual([r['kind'] for r in rows], ['安全','安全','車両','車両'])
        self.assertEqual((safety, vehicles), before)
        self.assertEqual(len(rows), 4)
        self.assertEqual(office_actions('A', {}, {}), [])

    def test_five_previews_all_original_links_and_escape(self):
        env = Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parents[1] / 'templates')), autoescape=select_autoescape())
        env.globals['url_for'] = lambda endpoint, **values: '/static/' + values['filename']
        issues = [dict(content=f'<script>項目{i}</script>', count=10-i, category='区分',
                       records=[dict(url=f'/source/{i}', date='2026-11-18', checklist='点検')]) for i in range(8)]
        actions = [dict(kind='安全', title=f'対応{i}', state='対策未確認', url=f'/action/{i}') for i in range(7)]
        html = env.get_template('partials/dashboard_office_trends.html').render(
            dashboard_office_check_trend={'answer_count': 8, 'issues': issues},
            dashboard_office_actions=actions, dashboard_scope_office='A')
        self.assertIn('残り3項目', html)
        self.assertNotIn('残り2件', html)
        self.assertIn('data-action-kind="安全"', html)
        self.assertIn('data-action-next', html)
        self.assertIn('js/dashboard_office_actions.js', html)
        self.assertEqual(html.count('class="office-trend-row"'), 8)
        self.assertEqual(html.count('class="office-action-link"'), 7)
        self.assertEqual(html.split('残り3項目')[0].count('class="office-trend-row"'), 5)
        self.assertNotIn('<script>', html)
        for i in range(8): self.assertIn(f'/source/{i}', html)
        for i in range(7): self.assertIn(f'/action/{i}', html)
        self.assertNotIn('data-priority=', html)


if __name__ == '__main__': unittest.main()
