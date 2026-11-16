"""Registered zero and unknown costs must not look like absent records."""
from decimal import Decimal
import unittest
from test_q07_cost_display_consistency import CostDisplayConsistencyTests as Fixture


class CostBreakdownEmptyStatesTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    maintenance = Fixture.maintenance
    page = Fixture.page
    analysis = Fixture.analysis

    def panel(self):
        context, html = self.analysis()
        import re
        found = re.search(r'<section class="ka7-panel ka8-cost-panel">(.*?)</section>', html, re.S)
        return context, found.group(1) if found else ''

    def test_known_zero_remains_visible(self):
        row = self.maintenance(0)
        _, panel = self.panel()
        self.assertIn('登録済み費用の合計は 0<small> 円</small>', panel)
        self.assertNotIn('費用記録はありません', panel)
        self.assertEqual(row.total_cost, 0)

    def test_offsetting_adjustments_are_not_absent(self):
        self.maintenance(100, labor_cost=100)
        self.maintenance(-100, labor_cost=-100)
        _, panel = self.panel()
        self.assertIn('差引額が0円以外となる内訳はありません', panel)
        self.assertNotIn('費用記録はありません', panel)
        self.assertNotIn('ka10-cost-composition', panel)

    def test_all_missing_is_not_zero_or_absent(self):
        row = self.maintenance(None)
        _, panel = self.panel()
        self.assertIn('整備記録はありますが、金額は未入力', panel)
        self.assertIn('金額未入力 1件', panel)
        self.assertNotIn('合計は 0円', panel)
        self.assertNotIn('費用記録はありません', panel)
        self.assertIsNone(row.total_cost)

    def test_partial_amount_discloses_incomplete_composition(self):
        self.maintenance(Decimal('120.5'), labor_cost=Decimal('120.5'))
        self.maintenance(None)
        _, panel = self.panel()
        self.assertIn('120.5', panel)
        self.assertIn('金額未入力 1件', panel)
        self.assertIn('0円として集計していません', panel)

    def test_missing_counts_exclude_foreign_vehicle_period_and_synthetic(self):
        from datetime import timedelta
        from test_domain_consistency import today
        self.maintenance(0)
        foreign = self.maintenance(None)
        foreign.company_code = 'OTHER'
        other_vehicle = self.m.Vehicle(company_code='TEST', chassis_number='COST-OTHER')
        self.m.db.session.add(other_vehicle)
        self.m.db.session.flush()
        other = self.maintenance(None)
        other.vehicle_record_id = other_vehicle.id
        old = self.maintenance(None)
        old.entry_date = (today().replace(day=1) - timedelta(days=1)).isoformat()
        self.maintenance(None, notes='テスト用資料・支払不要(発行元・取引内容は架空です)')
        self.m.db.session.commit()
        _, panel = self.panel()
        self.assertIn('登録済み費用の合計は 0<small> 円</small>', panel)
        self.assertNotIn('金額未入力', panel)

    def test_zero_with_unknown_is_visible_and_keeps_unknown(self):
        self.maintenance(0)
        self.maintenance(None)
        _, panel = self.panel()
        self.assertIn('登録済み費用の合計は 0<small> 円</small>', panel)
        self.assertIn('金額未入力 1件', panel)
        self.assertNotIn('費用記録はありません', panel)

    def test_no_records_remains_without_cost_panel(self):
        _, panel = self.panel()
        self.assertEqual(panel, '')


del Fixture
