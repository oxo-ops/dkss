"""Video dashboard: real scoped follow-ups and every trend's source records."""
from datetime import datetime
import json
from unittest.mock import patch
import unittest

from identity_fixture import identity_for
import test_dashboard_saved_proposals as saved
from dkss_app import dashboard as dashboard_module


class DashboardSafetyAttentionTests(unittest.TestCase):
    setUpClass = classmethod(saved.DashboardSavedProposalTests.setUpClass.__func__)
    tearDownClass = classmethod(saved.DashboardSavedProposalTests.tearDownClass.__func__)
    setUp = saved.DashboardSavedProposalTests.setUp
    tearDown = saved.DashboardSavedProposalTests.tearDown
    configure = saved.DashboardSavedProposalTests.configure
    page = saved.DashboardSavedProposalTests.page
    save = saved.DashboardSavedProposalTests.save
    recommendations = staticmethod(saved.DashboardSavedProposalTests.recommendations)

    def patrol(self, marker, **changes):
        values = dict(company_code='TEST', office='試験営業所', target_type='delivery_place',
                      delivery_place='架空納入先', content=marker, category='指摘',
                      date='2026-01-01', countermeasure='確認する対策', approval_status='承認待ち')
        values.update(changes)
        row = self.m.PatrolResult(**values)
        self.m.db.session.add(row)
        self.m.db.session.commit()
        return row

    def safety_panel(self):
        html, root = self.page()
        panels = root.find(cls='dashboard-safety-attention')
        return html, panels[0] if panels else None

    def user_role(self, role):
        self.m.User.query.filter_by(company_code='TEST', username='admin').one().role = role
        self.m.db.session.commit()
        with self.client.session_transaction() as session:
            session['role'] = role

    def test_safety_and_vehicle_candidates_share_the_top_region(self):
        self.configure()
        row = self.patrol('写真と対策の確認対象', countermeasure_due_date='2026-11-20')
        self.save(self.vehicle, self.recommendations(1))
        html, root = self.page()
        region = root.find(cls='dashboard-attention-list')[0]
        self.assertEqual(len(region.find(cls='dashboard-safety-attention')), 1)
        self.assertEqual(len(region.find(cls='dashboard-attention-panel')), 2)
        self.assertIn('安全管理：次の対応', region.text)
        self.assertIn('車両管理：AIの整備提案', region.text)
        self.assertIn('対策確認待ち', region.text)
        self.assertIn('2026-11-20', region.text)
        self.assertIn('全期間', region.text)  # Old unresolved records must not vanish.
        href = region.find(cls='dashboard-safety-content')[0].find(tag='a')[0].attrs['href']
        self.assertEqual(href, f'/pointouts/{row.id}')
        detail = self.client.get(href)
        self.assertEqual(detail.status_code, 200)
        self.assertIn('写真と対策の確認対象', detail.get_data(as_text=True))

    def test_company_actual_office_and_unknown_office_fail_closed(self):
        user = self.configure()
        self.patrol('表示対象')
        self.patrol('別会社の秘密', company_code='OTHER')
        self.patrol('別営業所の秘密', office='別営業所')
        self.patrol('承認完了', approval_status='承認済み')
        self.patrol('Good記録', category='Good')
        user.dashboard_settings_json = json.dumps({'office': '別営業所'})
        self.m.db.session.commit()
        _, panel = self.safety_panel()
        self.assertIn('表示対象', panel.text)
        for marker in ('別会社の秘密', '別営業所の秘密', '承認完了', 'Good記録'):
            self.assertNotIn(marker, panel.text)
        self.assertEqual(len(panel.find(cls='dashboard-safety-content')), 1)
        user.office = ''
        self.m.db.session.commit()
        _, panel = self.safety_panel()
        self.assertFalse(panel.find(cls='dashboard-safety-content'))
        self.assertIn('所属営業所を確認', panel.text)

    def test_regular_viewer_uses_uuid_permission_before_contents_and_counts(self):
        self.configure()
        self.user_role('user')
        own = identity_for('TEST', 'admin', app=self.m.app)
        self.patrol('納入先公開')
        self.patrol('本人対象', target_type='user', target_username='admin', target_identity=own)
        self.patrol('本人作成', target_type='user', created_by_username='admin', created_by_identity=own)
        legacy = self.patrol('同名だけ秘密', target_type='user', target_username='admin', target_user='検証 管理者')
        legacy.target_identity = None
        legacy.target_user_id = None
        self.m.db.session.commit()
        self.patrol('他人の秘密', target_type='user', target_identity='other-person')
        _, panel = self.safety_panel()
        self.assertEqual(len(panel.find(cls='dashboard-safety-content')), 3)
        self.assertIn('3件', panel.text)
        self.assertNotIn('同名だけ秘密', panel.text)
        self.assertNotIn('他人の秘密', panel.text)
        for a in panel.find(tag='a'):
            self.assertEqual(self.client.get(a.attrs['href']).status_code, 200)

    def test_counts_expansion_states_and_escaping_do_not_invent_priority(self):
        self.configure()
        self.patrol('<img src=x onerror=alert(1)>')
        self.patrol('差し戻された対策', approval_status='差し戻し')
        self.patrol('未登録の対策', countermeasure='', approval_status='未対応')
        for i in range(4):
            self.patrol(f'追加{i}')
        html, panel = self.safety_panel()
        self.assertIn('7件', panel.text)
        self.assertEqual(len(panel.find(cls='dashboard-safety-content')), 7)
        self.assertIn('残り4件', panel.find(cls='dashboard-safety-more')[0].text)
        self.assertIn('差し戻し', panel.text)
        self.assertIn('対策未確認', panel.text)
        self.assertNotIn('<img src=x onerror=alert(1)>', html)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)
        self.assertNotIn('高', ''.join(n.text for n in panel.find(cls='dashboard-safety-state')))

    def test_independent_display_preferences(self):
        user = self.configure()
        self.patrol('安全候補')
        self.save(self.vehicle, self.recommendations(1))
        for safety, analysis in ((True, False), (False, True), (False, False), (True, True)):
            with self.subTest(safety=safety, analysis=analysis):
                user.dashboard_settings_json = json.dumps({'show_pending': safety, 'show_analysis': analysis})
                self.m.db.session.commit()
                _, root = self.page()
                self.assertEqual(bool(root.find(cls='dashboard-safety-attention')), safety)
                self.assertEqual(bool(root.find(cls='dashboard-attention-panel')), analysis)
                self.assertEqual(bool(root.find(cls='dashboard-attention-list')), safety or analysis)

    def test_get_does_not_change_safety_records_or_create_feedback(self):
        self.configure()
        self.patrol('変更しない')
        def snapshot():
            return [tuple(getattr(r, col.name) for col in self.m.PatrolResult.__table__.columns)
                    for r in self.m.PatrolResult.query.order_by(self.m.PatrolResult.id)]
        before = snapshot()
        self.page(); self.page()
        self.m.db.session.expire_all()
        self.assertEqual(before, snapshot())
        self.assertEqual(self.m.VehicleAnalysisFeedback.query.count(), 0)

    def seed_trend(self):
        item = dict(item_type='check', input_type='select', category='安全分野',
                    content='歩行経路を確認', choices=['○', '△', '×'])
        checklist = self.m.Checklist(company_code='TEST', name='架空安全点検', target='安全管理',
                                     items_json=json.dumps([item]), frequency_unit='month')
        self.m.db.session.add(checklist); self.m.db.session.flush()
        own = identity_for('TEST', 'admin', app=self.m.app)
        rows = []
        for name, company, office, identity in (
            ('本人1', 'TEST', '試験営業所', own), ('本人2', 'TEST', '試験営業所', own),
            ('他人だけの秘密項目', 'TEST', '試験営業所', 'other-person'),
            ('他社秘密', 'OTHER', '試験営業所', own), ('他営業所秘密', 'TEST', '別営業所', own)
        ):
            snapshot_item = dict(item, content=item['content'] if name.startswith('本人') else name)
            row = self.m.ChecklistResult(company_code=company, checklist_id=checklist.id,
                target_office=office, target_type='user', target_username='admin' if name.startswith('本人') else 'other', target_identity=identity,
                checked_date='2026-11-11', answers_json='[{"value":"×"}]',
                checklist_snapshot_json=json.dumps({'items': [snapshot_item]}))
            self.m.db.session.add(row); rows.append(row)
        self.m.db.session.commit()
        return rows

    def test_trend_links_every_visible_source_and_excludes_private_counts(self):
        self.configure(); rows = self.seed_trend(); self.user_role('user')
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 11, 12, tzinfo=tz)
        with patch.object(dashboard_module._dkss_common, 'datetime', Clock):
            html, root = self.page()
        trend = root.find(cls='dashboard-trend-records')[0]
        self.assertEqual(len(trend.find(cls='dashboard-trend-issue')), 1)
        self.assertIn('2件', trend.text)
        self.assertNotIn('秘密', trend.text)
        urls = [n.attrs['href'] for n in trend.find(tag='a')]
        self.assertEqual(len(urls), 2)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200)
        for row in rows[:2]:
            self.assertIn(f'/safety/checklist-results/{row.id}', urls)


if __name__ == '__main__':
    unittest.main()
