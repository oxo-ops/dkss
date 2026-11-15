"""Cost cards disclose missing amounts in their own aggregation scope."""
from decimal import Decimal
import unittest
from test_q07_cost_display_consistency import CostDisplayConsistencyTests as Fixture
from test_domain_consistency import today


class CostCompletenessNotesTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    maintenance = Fixture.maintenance
    page = Fixture.page

    def previous(self, amount):
        row = self.maintenance(amount)
        row.entry_date = f'{today().year - 1}-01-01'
        self.m.db.session.commit()
        return row

    def test_previous_missing_amount_is_disclosed_beside_comparison(self):
        self.maintenance(200)
        self.previous(100)
        missing = self.previous(None)
        context, html = self.page('costs', year=today().year)
        details = context['cost_details']
        self.assertEqual(details['previous_missing_amount_count'], 1)
        self.assertEqual(details['all_time_missing_amount_count'], 1)
        self.assertEqual(details['change_percentage'], Decimal('100'))
        self.assertIn('前年の金額未入力 1件を除いた集計との比較です。', html)
        self.assertIn('全期間の金額未入力 1件を除いた集計です。', html)
        self.assertIsNone(missing.total_cost)

    def test_undated_missing_is_only_in_cumulative_scope(self):
        self.maintenance(0)
        missing = self.maintenance(None)
        missing.entry_date = 'unknown'
        self.m.db.session.commit()
        context, html = self.page('costs', year=today().year)
        details = context['cost_details']
        self.assertEqual(details['all_time_missing_amount_count'], 1)
        self.assertEqual(details['previous_missing_amount_count'], 0)
        self.assertEqual(details['missing_amount_count'], 0)
        self.assertEqual(details['all_time_summary']['total_cost'], 0)
        self.assertIn('全期間の金額未入力 1件を除いた集計です。', html)
        self.assertNotIn('前年の金額未入力', html)

    def test_zero_and_synthetic_or_foreign_records_are_not_missing(self):
        self.maintenance(0)
        self.previous(0)
        self.previous(None).notes = 'テスト用資料・支払不要(発行元・取引内容は架空です)'
        foreign = self.previous(None)
        foreign.company_code = 'OTHER'
        self.m.db.session.commit()
        context, html = self.page('costs', year=today().year)
        details = context['cost_details']
        self.assertEqual(details['all_time_missing_amount_count'], 0)
        self.assertEqual(details['previous_missing_amount_count'], 0)
        self.assertEqual(details['previous_total'], 0)
        self.assertNotIn('全期間の金額未入力', html)
        self.assertNotIn('前年の金額未入力', html)


# Imported fixture is not an additional test suite.
del Fixture
