"""Signed registered expenses must not become a positive-only composition."""
import unittest
import re
from test_q07_cost_display_consistency import CostDisplayConsistencyTests as Fixture


class CostSignedCompositionTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    maintenance = Fixture.maintenance
    page = Fixture.page
    analysis = Fixture.analysis

    def panel(self):
        context, html = self.analysis()
        found = re.search(r'<section class="ka7-panel ka8-cost-panel">(.*?)</section>', html, re.S)
        return context, found.group(1) if found else ''

    def test_mixed_signed_categories_do_not_draw_positive_only_percentages(self):
        self.maintenance(100, labor_cost=100)
        self.maintenance(-50, parts_cost=-50)
        context, panel = self.panel()
        self.assertEqual(context['analysis_cost_breakdown']['total'], 50)
        self.assertIn('-50', panel)
        self.assertIn('100', panel)
        self.assertNotIn('ka10-cost-composition', panel)
        self.assertNotIn('ka10-cost-percentage', panel)
        self.assertIn('負の金額を含むため構成比は表示していません', panel)

    def test_all_negative_amounts_remain_visible_without_percentages(self):
        self.maintenance(-50, parts_cost=-50)
        _, panel = self.panel()
        self.assertIn('-50', panel)
        self.assertNotIn('ka10-cost-composition', panel)
        self.assertIn('負の金額を含むため構成比は表示していません', panel)

    def test_excluded_negative_amounts_do_not_suppress_valid_composition(self):
        from datetime import timedelta
        from test_domain_consistency import today
        self.maintenance(100, labor_cost=100)
        foreign = self.maintenance(-50, parts_cost=-50)
        foreign.company_code = 'OTHER'
        other_vehicle = self.m.Vehicle(company_code='TEST', chassis_number='SIGNED-OTHER')
        self.m.db.session.add(other_vehicle)
        self.m.db.session.flush()
        other = self.maintenance(-50, parts_cost=-50)
        other.vehicle_record_id = other_vehicle.id
        old = self.maintenance(-50, parts_cost=-50)
        old.entry_date = (today().replace(day=1) - timedelta(days=1)).isoformat()
        self.maintenance(-50, parts_cost=-50, notes='テスト用資料・支払不要(発行元・取引内容は架空です)')
        self.m.db.session.commit()
        context, panel = self.panel()
        self.assertEqual(context['analysis_cost_breakdown']['total'], 100)
        self.assertIn('ka10-cost-composition', panel)
        self.assertIn('100.0%', panel)
        self.assertNotIn('負の金額を含むため', panel)

    def test_nonnegative_composition_unchanged(self):
        self.maintenance(100, labor_cost=75, parts_cost=25)
        _, panel = self.panel()
        self.assertIn('ka10-cost-composition', panel)
        self.assertIn('75.0%', panel)
        self.assertIn('25.0%', panel)
        self.assertNotIn('負の金額を含むため', panel)


del Fixture
