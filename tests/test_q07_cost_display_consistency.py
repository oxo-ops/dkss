"""Actual rendered monetary views must retain legacy dates and stored precision."""
from decimal import Decimal
from datetime import timedelta
import unittest
import re
from flask import template_rendered

from test_domain_consistency import DomainConsistencyTests as Fixture, today


class CostDisplayConsistencyTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    maintenance = Fixture.maintenance
    trend = Fixture.trend

    def page(self, suffix, **query):
        captured = []
        def collect(sender, template, context, **extra):
            captured.append(context)
        with template_rendered.connected_to(collect, self.m.app):
            response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/{suffix}', query_string=query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(captured), 1)
        return captured[0], response.get_data(as_text=True)

    def analysis(self):
        return self.page('analysis', start_date=today().replace(day=1).isoformat(), end_date=today().isoformat())

    def test_legacy_dates_reach_analysis_kpi_month_and_component_display(self):
        row = self.maintenance(Decimal('500.01'), labor_cost=200, parts_cost=300, tax_amount=Decimal('.01'))
        for value in (today().isoformat(), today().strftime('%Y/%m/%d'),
                      today().strftime('%Y/%m/%d') + ' 12:00:00',
                      '  ' + today().isoformat() + 'T12:00:00+09:00'):
            with self.subTest(date=value):
                row.entry_date = value
                self.m.db.session.commit()
                context, html = self.analysis()
                summary = context['analysis_summary']
                breakdown = context['analysis_cost_breakdown']
                self.assertEqual(summary['total_cost'], Decimal('500.01'))
                self.assertEqual(summary['monthly'][-1]['cost'], Decimal('500.01'))
                self.assertEqual(summary['undated_maintenance_count'], 0)
                self.assertEqual(breakdown['total'], summary['total_cost'])
                self.assertEqual(sum(x['amount'] for x in breakdown['rows']), summary['total_cost'])
                self.assertIn('整備費の内訳', html)
                self.assertIn('500.01', html)
                costs, _ = self.page('costs', year=today().year)
                self.assertEqual(costs['cost_details']['selected_summary']['total_cost'], summary['total_cost'])

    def test_blank_arrival_uses_completion_consistently_without_changing_data(self):
        row = self.maintenance(500)
        row.completion_date = today().strftime('%Y/%m/%d') + ' 12:00:00'
        for blank in (None, '', '   '):
            with self.subTest(arrival=blank):
                row.entry_date = blank
                self.m.db.session.commit()
                context, _ = self.analysis()
                self.assertEqual(context['analysis_summary']['total_cost'], 500)
                self.assertEqual(context['analysis_summary']['monthly'][-1]['cost'], 500)
                self.assertEqual(context['analysis_cost_breakdown']['total'], 500)
                self.assertEqual(row.entry_date, blank)

    def test_invalid_nonblank_arrival_is_not_replaced_by_valid_completion(self):
        row = self.maintenance(500)
        row.entry_date = '2026-02-30'
        row.completion_date = today().isoformat()
        self.m.db.session.commit()
        context, _ = self.analysis()
        self.assertIsNone(context['analysis_summary']['total_cost'])
        self.assertIsNone(context['analysis_cost_breakdown']['total'])
        self.assertEqual(context['analysis_summary']['all_time_cost'], 500)
        self.assertEqual(context['analysis_summary']['undated_maintenance_count'], 1)
        self.assertEqual(row.entry_date, '2026-02-30')

    def test_dashboard_tooltip_preserves_decimal_amount_like_cost_page(self):
        row = self.maintenance(Decimal('500.01'))
        self.m.User.query.filter_by(company_code='TEST', username='admin').one().office = 'A'
        self.m.db.session.commit()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        titles = re.findall(r'<title>(.*?)</title>', response.get_data(as_text=True), re.S)
        self.assertIn(f'{today().month}月：500.01円', titles)
        for value, label in (('0.01', '0.01'), ('0.50', '0.5'), ('0', '0'),
                             ('-50.01', '-50.01'), ('1000.10', '1,000.1')):
            with self.subTest(amount=value):
                row.total_cost = Decimal(value)
                self.m.db.session.commit()
                bucket = self.trend()['months'][-1]
                self.assertEqual(bucket['formatted'], label)
                self.assertEqual(bucket['amount'], Decimal(value))

    def test_dashboard_formatting_does_not_cap_aggregate_at_one_record_limit(self):
        # A valid aggregate may be larger than the per-record amount limit.
        self.maintenance(Decimal('999999999999.99'))
        self.maintenance(Decimal('999999999999.99'))
        bucket = self.trend()['months'][-1]
        self.assertEqual(bucket['amount'], Decimal('1999999999999.98'))
        self.assertEqual(bucket['formatted'], '1,999,999,999,999.98')

    def test_unknown_zero_and_negative_adjustment_keep_distinct_totals(self):
        row = self.maintenance(0)
        self.maintenance(None)
        context, _ = self.analysis()
        self.assertEqual(context['analysis_summary']['total_cost'], 0)
        self.assertEqual(context['analysis_summary']['missing_cost_count'], 1)
        self.assertEqual(context['analysis_cost_breakdown']['total'], 0)
        self.assertEqual(context['analysis_cost_breakdown']['record_count'], 1)
        row.total_cost = Decimal('-50.01')
        self.m.db.session.commit()
        context, html = self.analysis()
        self.assertEqual(context['analysis_summary']['total_cost'], Decimal('-50.01'))
        self.assertEqual(context['analysis_cost_breakdown']['total'], Decimal('-50.01'))
        self.assertIn('-50.01', html)

    def test_period_company_vehicle_and_synthetic_exclusions_still_agree(self):
        row = self.maintenance(125, labor_cost=100, tax_amount=25)
        row.entry_date = today().strftime('%Y/%m/%d')
        outside = self.maintenance(700)
        outside.entry_date = (today().replace(day=1) - timedelta(days=1)).isoformat()
        self.maintenance(800, notes='テスト用資料・支払不要(発行元・取引内容は架空です)')
        foreign = self.maintenance(900)
        foreign.company_code = 'OTHER'
        other = self.m.Vehicle(company_code='TEST', chassis_number='SECOND')
        self.m.db.session.add(other)
        self.m.db.session.flush()
        other_row = self.maintenance(1000)
        other_row.vehicle_record_id = other.id
        self.m.db.session.commit()
        context, _ = self.analysis()
        self.assertEqual(context['analysis_summary']['total_cost'], 125)
        self.assertEqual(context['analysis_cost_breakdown']['total'], 125)
        self.assertEqual(context['analysis_cost_breakdown']['record_count'], 1)
        self.assertEqual(context['analysis_summary']['all_time_cost'], 825)


del Fixture

if __name__ == '__main__':
    unittest.main()
