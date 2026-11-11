"""Saved dashboard recommendations: bounded preview, labels and source links."""
import json
from html.parser import HTMLParser
from unittest.mock import patch
import unittest

import test_workflow_regressions as workflow
from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids


class Element:
    def __init__(self, tag, attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def find(self, *, tag=None, cls=None):
        result = []
        for child in self.children:
            if not isinstance(child, Element):
                continue
            if (tag is None or child.tag == tag) and (
                cls is None or cls in child.attrs.get('class', '').split()
            ):
                result.append(child)
            result.extend(child.find(tag=tag, cls=cls))
        return result

    @property
    def text(self):
        return ''.join(c.text if isinstance(c, Element) else c for c in self.children)


class Document(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Element('root')
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


class DashboardSavedProposalTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    @staticmethod
    def recommendations(count):
        return [dict(title=f'保存済み候補{i:02}', target=f'部品{i:02}',
                     category='整備・点検', priority=['高', '中', '低'][i % 3],
                     action=f'確認する{i:02}', reason=f'根拠{i:02}', timing='次回点検時')
                for i in range(count)]

    def save(self, vehicle, items, *, status='completed'):
        state = self.m.VehicleKarteAnalysis(
            company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
            status=status, result_json=json.dumps({
                'analysis': {'recommendations': items},
                'generated_at': '2026-11-10T00:00:00Z',
            }, ensure_ascii=False))
        self.m.db.session.add(state)
        self.m.db.session.commit()
        return state

    def configure(self):
        self.vehicle.office = '試験営業所'
        user = self.m.User.query.filter_by(company_code='TEST', username='admin').one()
        user.office = '試験営業所'
        self.m.db.session.add(self.m.Office(company_code='TEST', name='試験営業所'))
        self.m.db.session.add(self.m.Driver(company_code='TEST', employee_id='admin',
            name='検証 管理者', office='試験営業所', vehicles_json=json.dumps([str(self.vehicle.id)])))
        self.m.db.session.commit()
        return user

    def page(self):
        with patch.object(self.m, 'analyze_vehicle_karte', side_effect=AssertionError('No AI')), \
                patch.object(self.m, 'queue_vehicle_karte_analysis', side_effect=AssertionError('No AI queue')):
            response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        return html, Document(html).root

    def test_preview_has_at_most_five_and_remaining_count_is_exact(self):
        self.configure()
        state = self.save(self.vehicle, [])
        for count in (0, 1, 3, 5, 6, 9):
            with self.subTest(count=count):
                items = self.recommendations(count)
                state.result_json = json.dumps({'analysis': {'recommendations': items}})
                self.m.db.session.commit()
                before = state.result_json
                html, root = self.page()
                panel = root.find(cls='dashboard-attention-panel')[0]
                previews = panel.find(cls='dashboard-attention-preview')
                self.assertEqual(len(previews), int(count > 0))
                preview_rows = previews[0].find(tag='tbody')[0].find(tag='tr') if previews else []
                self.assertEqual(len(preview_rows), min(count, 5))
                more = panel.find(cls='dashboard-attention-more')
                self.assertEqual(len(more), int(count > 5))
                if more:
                    self.assertNotIn('open', more[0].attrs)
                    self.assertIn(f'残り{count - 5}件', more[0].find(tag='summary')[0].text)
                    self.assertEqual(len(more[0].find(tag='tbody')[0].find(tag='tr')), count - 5)
                self.assertEqual(len(panel.find(cls='dashboard-attention-view-all')), int(count > 5))
                # Shared response-priority order uses the stable proposal ID, not title.
                expected = sorted(items, key=lambda i: ({'高': 0, '中': 1, '低': 2}[i['priority']], vehicle_analysis_proposal_ids(i)[0]))
                all_rows = [row for tbody in panel.find(tag='tbody') for row in tbody.find(tag='tr')]
                self.assertEqual(len(all_rows), count)
                for row, item in zip(all_rows, expected):
                    self.assertIn(item['target'], row.text)
                    key, _ = vehicle_analysis_proposal_ids(item)
                    self.assertTrue(any(a.attrs.get('href', '').endswith('#proposal=' + key)
                                        for a in row.find(tag='a')))
                self.m.db.session.expire_all()
                self.assertEqual(state.result_json, before)

    def test_known_priority_labels_only_and_untrusted_content_is_escaped(self):
        self.configure()
        items = self.recommendations(6)
        for item, priority in zip(items, ('高', '中', '低', '未評価', '', '<script>bad</script>')):
            item['priority'] = priority
        items[-1]['target'] = '<img src=x onerror=alert(1)>'
        self.save(self.vehicle, items)
        html, root = self.page()
        badges = root.find(cls='dashboard-attention-priority')
        self.assertEqual([b.text for b in badges], ['高', '中', '低'])
        self.assertEqual([b.attrs['aria-label'] for b in badges],
                         ['対応優先度：高', '対応優先度：中', '対応優先度：低'])
        self.assertNotIn('<img src=x onerror=alert(1)>', html)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)
        self.assertNotIn('<script>bad</script>', html)

    def test_both_groups_have_independent_preview_limits_and_company_boundaries(self):
        self.configure()
        self.save(self.vehicle, self.recommendations(7))
        for company, office, deleted, marker in (
            ('TEST', '試験営業所', False, '所属内'), ('OTHER', '試験営業所', False, '他社秘密'),
            ('TEST', '別営業所', False, '別営業所候補'), ('TEST', '試験営業所', True, '削除車両候補')
        ):
            vehicle = self.m.Vehicle(company_code=company, chassis_number=marker,
                                     office=office, deleted=deleted)
            self.m.db.session.add(vehicle)
            self.m.db.session.flush()
            items = self.recommendations(8)
            for item in items:
                item['target'] = marker + item['target']
            self.save(vehicle, items)
        html, root = self.page()
        panels = root.find(cls='dashboard-attention-panel')
        self.assertEqual(len(panels), 2)
        for panel, remaining in zip(panels, (2, 3)):
            self.assertEqual(len(panel.find(cls='dashboard-attention-preview')[0].find(tag='tbody')[0].find(tag='tr')), 5)
            self.assertIn(f'残り{remaining}件', panel.find(cls='dashboard-attention-more')[0].text)
        for marker in ('他社秘密', '別営業所候補', '削除車両候補'):
            self.assertNotIn(marker, html)

    def test_finished_current_proposals_stay_excluded_without_padding(self):
        self.configure()
        items = self.recommendations(7)
        self.save(self.vehicle, items)
        for item, status in zip(items, ('completed', 'dismissed', 'completed')):
            key, revision = vehicle_analysis_proposal_ids(item)
            self.m.db.session.add(self.m.VehicleAnalysisFeedback(
                company_code='TEST', vehicle_record_id=self.vehicle.id,
                proposal_key=key, proposal_revision=revision, status=status,
                snapshot_json=json.dumps(item), created_by='admin', created_at='2026-11-10 09:00:00'))
        self.m.db.session.commit()
        _, root = self.page()
        panel = root.find(cls='dashboard-attention-panel')[0]
        self.assertEqual(len(panel.find(tag='tbody')[0].find(tag='tr')), 4)
        self.assertEqual(panel.find(cls='dashboard-attention-more'), [])
        self.assertEqual(self.m.VehicleAnalysisFeedback.query.count(), 3)

    def test_record_checks_and_saved_error_or_pending_results_remain_separate(self):
        self.configure()
        items = self.recommendations(6)
        items[-1]['category'] = '記録確認'
        items[-1]['title'] = '読取内容の確認'
        state = self.save(self.vehicle, items)
        for status, message in (('error', '更新に失敗'), ('running', '更新待ち')):
            state.status = status
            self.m.db.session.commit()
            html, root = self.page()
            panel = root.find(cls='dashboard-attention-panel')[0]
            self.assertIn(message, panel.text)
            self.assertEqual(len(panel.find(cls='dashboard-attention-preview')[0].find(tag='tbody')[0].find(tag='tr')), 5)
            self.assertIn('読取内容の確認', panel.find(cls='dashboard-attention-records')[0].text)
            self.assertFalse(panel.find(cls='dashboard-attention-more'))

    def test_hidden_analysis_preference_remains_respected(self):
        user = self.configure()
        self.save(self.vehicle, self.recommendations(7))
        user.dashboard_settings_json = json.dumps({'show_analysis': False})
        self.m.db.session.commit()
        _, root = self.page()
        self.assertFalse(root.find(cls='dashboard-attention-panel'))


if __name__ == '__main__':
    unittest.main()
