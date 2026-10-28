"""Existing maintenance dates must land in the same cost bucket on every view."""
from decimal import Decimal
import unittest

from test_domain_consistency import DomainConsistencyTests as Fixture, today
from dkss_app.vehicle_costs import get_vehicle_maintenance_cost_details


class CostDateConsistencyTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    maintenance = Fixture.maintenance
    trend = Fixture.trend
    total = Fixture.total

    def details(self, rows):
        return get_vehicle_maintenance_cost_details(rows, today().year)

    def test_legacy_dates_match_dashboard_annual_and_monthly_costs(self):
        for value in (today().isoformat(), today().strftime('%Y/%m/%d'),
                      today().strftime('%Y/%m/%d') + ' 12:00:00',
                      today().isoformat() + 'T12:00:00+09:00'):
            with self.subTest(date=value):
                row = self.maintenance(Decimal('500.01'))
                row.entry_date = value
                self.m.db.session.commit()
                details = self.details([row])
                self.assertEqual(details['selected_summary']['total_cost'], Decimal('500.01'))
                self.assertEqual(details['monthly_costs'][today().month - 1]['amount'], Decimal('500.01'))
                annual = next(x for x in details['all_time_summary']['annual_costs']
                              if x['year'] == today().year)
                self.assertEqual(Decimal(annual['amount']), Decimal('500.01'))
                self.assertEqual(details['undated_record_count'], 0)
        rows = self.m.VehicleMaintenanceRecord.query.all()
        self.assertEqual(self.total(self.trend()), Decimal('2000.04'))
        self.assertEqual(self.details(rows)['selected_summary']['total_cost'], self.total(self.trend()))
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/costs?year={today().year}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('2,000.04', response.get_data(as_text=True))

    def test_blank_arrival_uses_same_legacy_completion_date(self):
        row = self.maintenance(500)
        row.entry_date = ''
        row.completion_date = today().strftime('%Y/%m/%d')
        self.m.db.session.commit()
        details = self.details([row])
        self.assertEqual(details['selected_summary']['total_cost'], 500)
        self.assertEqual(self.total(self.trend()), 500)
        self.assertEqual(details['undated_record_count'], 0)

    def test_invalid_arrival_is_not_silently_replaced_with_completion(self):
        row = self.maintenance(500)
        row.entry_date = '2026-02-30'
        row.completion_date = today().isoformat()
        self.m.db.session.commit()
        details = self.details([row])
        self.assertIsNone(details['selected_summary']['total_cost'])
        self.assertEqual(details['all_time_summary']['total_cost'], 500)
        self.assertEqual(details['undated_record_count'], 1)
        self.assertEqual(self.total(self.trend()), 0)
        self.assertEqual(row.entry_date, '2026-02-30')

    def test_zero_and_unknown_amounts_remain_distinct_in_legacy_month(self):
        zero = self.maintenance(0)
        unknown = self.maintenance(None)
        for row in (zero, unknown):
            row.entry_date = today().strftime('%Y/%m/%d')
        self.m.db.session.commit()
        details = self.details([zero, unknown])
        month = details['monthly_costs'][today().month - 1]
        self.assertEqual(month['amount'], 0)
        self.assertEqual(month['record_count'], 2)
        self.assertEqual(month['missing_amount_count'], 1)
        self.assertEqual(details['selected_summary']['total_cost'], 0)
        self.assertEqual(details['missing_amount_count'], 1)


del Fixture

if __name__ == '__main__':
    unittest.main()
