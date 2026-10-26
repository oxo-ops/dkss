"""Aggregation contracts using plain records, with no application import."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace as Row
import unittest

from vehicle_analysis_summary import VehicleAnalysisSummaryService


class AnalysisSummaryTests(unittest.TestCase):
    def setUp(self):
        def factual(rows, parts=()):
            kept = [r for r in rows if not getattr(r, 'synthetic', False)]
            keys = {(r.company_code, r.vehicle_record_id, r.id) for r in kept}
            return kept, [p for p in parts if (p.company_code, p.vehicle_record_id, p.maintenance_record_id) in keys], [r.id for r in rows if getattr(r, 'synthetic', False)]
        self.service = VehicleAnalysisSummaryService(
            filter_factual_history=factual,
            periodic_synthetic_evidence=lambda r: r.id if getattr(r, 'synthetic', False) else None,
            today=lambda: date(2026, 10, 25))

    def maintenance(self, **kw):
        values = dict(id=1, company_code='A', vehicle_record_id=1, entry_date='2026-09-01',
                      completion_date='', mileage=None, total_cost=Decimal('100'), category='整備')
        values.update(kw)
        return Row(**values)

    def operation(self, **kw):
        values = dict(id=1, operation_date='2026-09-01', distance=Decimal('20'), arrival_meter=1000,
                      arrival_at='2026-09-01T18:00:00+09:00')
        values.update(kw)
        return Row(**values)

    def summary(self, maintenance=(), operations=(), parts=(), defects=(), periodic=()):
        return self.service.summarize(maintenance, operations, parts, defects,
                                      '2026-09-01', '2026-10-25', periodic_records=periodic)

    def test_empty_months_stay_unknown(self):
        got = self.summary()
        self.assertIsNone(got['total_cost'])
        self.assertIsNone(got['distance'])
        self.assertEqual([m['cost'] for m in got['monthly']], [None, None])

    def test_zero_cost_is_known_and_ratio_uses_decimal(self):
        got = self.summary([self.maintenance(total_cost=0)], [self.operation()])
        self.assertEqual(got['cost_per_km'], Decimal('0'))
        self.assertEqual(got['cost_per_km_status'], 'matched_record_months')

    def test_missing_cost_prevents_ratio(self):
        got = self.summary([self.maintenance(), self.maintenance(id=2, total_cost=None)], [self.operation()])
        self.assertIsNone(got['cost_per_km'])
        self.assertEqual(got['missing_cost_count'], 1)

    def test_different_record_months_prevent_ratio(self):
        got = self.summary([self.maintenance()], [self.operation(operation_date='2026-10-01')])
        self.assertEqual(got['cost_per_km_status'], 'record_months_do_not_match')
        self.assertIsNone(got['cost_per_km'])

    def test_synthetic_parent_and_foreign_child_excluded(self):
        parts = [Row(company_code=c, vehicle_record_id=1, maintenance_record_id=i,
                     replacement_date='2026-09-01', part_name='部品', part_number='')
                 for c, i in [('A', 1), ('A', 2), ('B', 1)]]
        got = self.summary([self.maintenance(), self.maintenance(id=2, synthetic=True)], parts=parts)
        self.assertEqual(got['total_cost'], Decimal('100'))
        self.assertEqual(got['part_replacement_count'], 1)
        self.assertEqual(got['source_exclusions'], [2])

    def test_completion_fallback_and_undated_count(self):
        got = self.summary([self.maintenance(entry_date='', completion_date='2026-09-02'),
                            self.maintenance(id=2, entry_date='bad')])
        self.assertEqual(got['maintenance_count'], 1)
        self.assertEqual(got['undated_maintenance_count'], 1)
        self.assertEqual(got['all_time_cost'], Decimal('200'))

    def test_only_failure_category_counts(self):
        got = self.summary(defects=[Row(category=c, occurred_date='2026-09-01', content='異音')
                                   for c in ['故障', '故障', 'その他']])
        self.assertEqual(got['failure_count'], 2)
        self.assertEqual(got['repeated_failure_contents'], [('異音', 2)])

    def test_conflict_and_decrease_make_distance_unusable(self):
        for rows, key in [([self.operation(), self.operation(id=2, arrival_meter=1100)], 'conflict_dates'),
                          ([self.operation(), self.operation(id=2, operation_date='2026-09-02', arrival_at='', arrival_meter=900)], 'decrease_dates')]:
            with self.subTest(key=key):
                got = self.service.mileage_reference([], rows, '2026-10-25', include_points=True)
                self.assertTrue(got[key])
                self.assertFalse(got['distance_usable'])

    def test_later_operation_same_day_is_selected(self):
        got = self.service.mileage_reference([], [self.operation(), self.operation(id=2, arrival_meter=1100,
                    arrival_at='2026-09-01T19:00:00+09:00')], '2026-10-25')
        self.assertEqual(got['value'], Decimal('1100'))
        self.assertTrue(got['distance_usable'])

    def test_future_and_after_as_of_are_separate(self):
        got = self.service.mileage_reference([], [self.operation(operation_date='2026-10-26'),
                         self.operation(operation_date='2026-10-20')], '2026-10-10')
        self.assertEqual(got['excluded']['future_date'], 1)
        self.assertEqual(got['excluded']['after_as_of'], 1)

    def test_invalid_mileage_values_are_excluded(self):
        got = self.service.mileage_reference([], [self.operation(arrival_meter=v) for v in [True, -1, 'NaN', 'Infinity']], '2026-10-25')
        self.assertEqual(got['excluded']['invalid_value'], 4)
        self.assertEqual(got['status'], 'unknown')

    def test_maintenance_distance_is_not_operation_distance(self):
        got = self.summary([self.maintenance(mileage=1000)])
        self.assertEqual(got['mileage_reference']['value'], Decimal('1000'))
        self.assertIsNone(got['current_mileage'])

    def test_invalid_period_and_reference_date_rejected(self):
        with self.assertRaises(ValueError):
            self.service.summarize([], [], [], [], '2026-10-25', '2026-09-01')
        with self.assertRaises(ValueError):
            self.service.mileage_reference([], [], 'invalid')
