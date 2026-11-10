"""Render existing peer part facts without changing aggregation or saved AI."""
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import test_workflow_regressions as workflow
from test_dashboard_saved_proposals import Document


class PeerPartStatisticsDisplayTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def setUp(self):
        workflow.WorkflowRegressionTests.setUp(self)
        self.vehicle.model_code = 'PEER-MODEL'
        self.vehicle.first_registration_date = '2020-04-01'
        self.m.db.session.commit()

    def peer(self, **values):
        fields = dict(company_code='TEST', model_code='PEER-MODEL',
                      first_registration_date='2020-01-01', deleted=False)
        fields.update(values)
        row = self.m.Vehicle(**fields)
        self.m.db.session.add(row); self.m.db.session.flush()
        return row

    def part(self, vehicle, name='エアフィルタ', number='FILTER-1',
             date='2026-09-15', parent=None, **values):
        if parent is None:
            parent = self.m.VehicleMaintenanceRecord(company_code=vehicle.company_code,
                vehicle_record_id=vehicle.id, entry_date=date, completion_date=date,
                status='完了', total_cost=0)
            self.m.db.session.add(parent); self.m.db.session.flush()
        fields = dict(company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
            maintenance_record_id=parent.id, part_name=name, part_number=number,
            replacement_date=date, quantity=1, created_at='2026-09-15T00:00:00Z')
        fields.update(values)
        part = self.m.VehiclePartReplacement(**fields)
        self.m.db.session.add(part); self.m.db.session.flush()
        return parent

    def path(self, **values):
        query = dict(start_date='2026-09-01', end_date='2026-10-31')
        query.update(values)
        return f'/vehicle/karte/{self.vehicle.id}/analysis?' + urlencode(query)

    def page(self, **query):
        self.m.db.session.commit()
        with patch.object(self.m, 'analyze_vehicle_karte', side_effect=AssertionError('No AI')), \
                patch.object(self.m, 'queue_vehicle_karte_analysis', side_effect=AssertionError('No AI queue')):
            response = self.client.get(self.path(**query))
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        return html, Document(html).root

    def panel(self, **query):
        html, root = self.page(**query)
        panels = root.find(cls='ka-peer-parts')
        self.assertEqual(len(panels), 1)
        return html, panels[0]

    def test_registration_counts_are_events_not_quantity_or_vehicle_count(self):
        a, b = self.peer(), self.peer()
        parent = self.part(a, quantity=20)
        self.part(a, parent=parent, quantity=30)
        self.part(a, date='2026-10-01')
        self.part(b)
        _, panel = self.panel()
        row = panel.find(tag='tbody')[0].find(tag='tr')[0]
        self.assertEqual([c.text for c in row.find(tag='td')], ['3件', '2台'])
        self.assertIn('品番：FILTER-1', row.text)
        self.assertIn('2026-09-01 ～ 2026-10-31 / 比較対象 2台', panel.text)
        self.assertIn('登録内容の真偽・作業完了・故障原因はこの集計では判定しない', panel.text)
        self.assertIn('未登録車両を未交換と扱わない', panel.text)
        self.assertNotIn('open', panel.attrs)

    def test_company_model_year_active_period_and_parent_boundaries(self):
        self.m.db.session.add(self.m.Company(company_code='OTHER', company_name='Other', active=True))
        accepted = self.peer()
        self.part(accepted, name='対象登録')
        for vehicle, name in [(self.vehicle, '自車除外'),
                (self.peer(company_code='OTHER'), '別会社除外'),
                (self.peer(model_code='DIFFERENT'), '別型式除外'),
                (self.peer(first_registration_date='2021-01-01'), '別年除外'),
                (self.peer(deleted=True), '無効除外')]:
            self.part(vehicle, name=name)
        self.part(accepted, name='期間前除外', date='2026-08-31')
        self.part(accepted, name='期間後除外', date='2026-11-01')
        self.part(accepted, name='不正日除外', date='bad')
        parent = self.part(accepted, name='架空資料除外')
        parent.notes = 'テスト用資料・支払不要(発行元・取引内容は架空です)'
        foreign_parent = self.part(self.peer(company_code='OTHER'), name='別親除外')
        self.part(accepted, name='不一致親除外', parent=foreign_parent)
        _, panel = self.panel()
        rows = panel.find(tag='tbody')[0].find(tag='tr')
        self.assertEqual(len(rows), 1)
        self.assertIn('対象登録', rows[0].text)
        self.assertNotIn('除外', panel.text)

    def test_conditions_update_the_display_and_return_to_original(self):
        self.part(self.peer(), name='同年')
        self.part(self.peer(first_registration_date='2021-01-01'), name='別年')
        self.part(self.peer(deleted=True), name='無効車')
        _, initial = self.panel()
        self.assertEqual(len(initial.find(tag='tbody')[0].find(tag='tr')), 1)
        _, all_years = self.panel(peer_registration='all_years', peer_inactive='1')
        self.assertEqual(len(all_years.find(tag='tbody')[0].find(tag='tr')), 3)
        self.assertIn('比較対象 3台', all_years.text)
        _, short = self.panel(start_date='2026-10-01')
        self.assertFalse(short.find(tag='table'))
        self.assertIn('実際に交換がなかったことを示すものではありません', short.text)
        _, back = self.panel()
        self.assertEqual(back.text, initial.text)

    def test_empty_registrations_are_distinct_from_no_peers_or_unknown_year(self):
        _, root = self.page()
        self.assertFalse(root.find(cls='ka-peer-parts'))
        self.peer()
        _, panel = self.panel()
        self.assertFalse(panel.find(tag='table'))
        self.assertIn('集計できる部品交換登録はありません', panel.text)
        self.vehicle.first_registration_date = ''
        _, root = self.page(peer_registration='same_year')
        self.assertFalse(root.find(cls='ka-peer-parts'))
        self.assertIn('初度登録年が未登録', root.text)
        _, panel = self.panel(peer_registration='all_years')
        self.assertIn('比較対象 1台', panel.text)

    def test_all_parts_are_reachable_with_no_five_row_cutoff(self):
        peer = self.peer()
        for i in range(14):
            self.part(peer, name=f'登録部品{i:02}', number=f'PART-{i:02}')
        _, panel = self.panel()
        self.assertIn('（14種類）', panel.find(tag='summary')[0].text)
        self.assertEqual(len(panel.find(tag='tbody')[0].find(tag='tr')), 14)
        viewport = panel.find(cls='ka-peer-parts-scroll')[0]
        self.assertEqual(viewport.attrs['tabindex'], '0')
        self.assertEqual(viewport.attrs['role'], 'region')

    def test_names_numbers_and_recorded_variants_are_escaped(self):
        peer = self.peer()
        self.part(peer, name='<img src=x onerror=alert(1)>', number='<script>bad</script>')
        self.part(peer, name='エアフィルター', number='')
        self.part(peer, name='エアフィルタ', number='')
        html, panel = self.panel()
        self.assertNotIn('<img src=x onerror=alert(1)>', html)
        self.assertNotIn('<script>bad</script>', html)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)
        self.assertIn('品番：未登録', panel.text)
        self.assertIn('登録名：エアフィルタ / エアフィルター', panel.text)

    def test_render_does_not_change_records_or_saved_ai(self):
        self.part(self.peer())
        saved = self.m.VehicleKarteAnalysis(company_code='TEST', vehicle_record_id=self.vehicle.id,
            status='completed', result_json=json.dumps({'analysis': {'recommendations': []}}))
        self.m.db.session.add(saved); self.m.db.session.commit()
        def snapshot():
            return ([(r.id, r.company_code, r.vehicle_record_id, r.part_name, r.quantity, r.replacement_date)
                     for r in self.m.VehiclePartReplacement.query.order_by(self.m.VehiclePartReplacement.id)],
                    [(r.id, r.status, r.result_json) for r in self.m.VehicleKarteAnalysis.query.all()])
        before = snapshot()
        self.panel(); self.panel(peer_registration='all_years')
        self.m.db.session.expire_all()
        self.assertEqual(snapshot(), before)

    def test_existing_reader_authorization_stays_intact(self):
        self.part(self.peer())
        self.m.db.session.commit()
        self.m.db.session.add(self.m.Company(company_code='OTHER', company_name='Other', active=True))
        foreign = self.peer(company_code='OTHER')
        self.m.db.session.commit()
        self.assertEqual(self.client.get(f'/vehicle/karte/{foreign.id}/analysis').status_code, 404)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get(self.path()).status_code, 302)
