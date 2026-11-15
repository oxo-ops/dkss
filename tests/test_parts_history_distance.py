"""Part history intervals: synthetic records only, no external services."""
from decimal import Decimal
from types import SimpleNamespace as Row
import unittest
from parts_history_distance import replacement_interval
import test_workflow_regressions as workflow


class IntervalTests(unittest.TestCase):
    def test_valid_distance_and_zero(self):
        for amount, expected in [(1500, Decimal(500)), (1000, Decimal(0))]:
            self.assertEqual(replacement_interval(Row(replacement_date='2026-01-01', mileage=1000),
                Row(replacement_date='2026-02-01', mileage=amount)), (expected, None))

    def test_absent_prior_is_distinct_from_unusable_prior(self):
        current = Row(replacement_date='2026-02-01', mileage=1500)
        self.assertEqual(replacement_interval(None, current), (None, '前回記録なし'))
        for stamp in ('', None, '2026-1-01', '2026-02-30', '2026/01/01'):
            value, note = replacement_interval(Row(replacement_date=stamp, mileage=1000), current)
            self.assertIsNone(value)
            self.assertIn('交換日未確認', note)

    def test_same_day_and_reversed_dates_are_not_ordered_by_row_id(self):
        for stamp in ('2026-02-01', '2026-03-01'):
            value, note = replacement_interval(Row(replacement_date=stamp, mileage=1000),
                Row(replacement_date='2026-02-01', mileage=1500))
            self.assertIsNone(value)
            self.assertIn('交換順序未確認', note)

    def test_missing_nonfinite_negative_and_reversed_meters_are_held(self):
        for prior, current in [(None, 1500), (1000, None), ('NaN', 1500),
                               (1000, 'Infinity'), (-1, 1500), (True, 1500), (1500, 1000)]:
            value, note = replacement_interval(Row(replacement_date='2026-01-01', mileage=prior),
                Row(replacement_date='2026-02-01', mileage=current))
            self.assertIsNone(value)
            self.assertIn('比較不可', note)
            self.assertNotEqual(note, '前回記録なし')


class PartsHistoryRouteTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def part(self, stamp, mileage):
        m = self.m
        parent = m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            entry_date=stamp, completion_date=stamp, status='完了', content='タイヤ交換')
        m.db.session.add(parent); m.db.session.flush()
        part = m.VehiclePartReplacement(company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=parent.id, part_name='タイヤ', replacement_date=stamp,
            mileage=mileage, created_at='2026-02-01', updated_at='2026-02-01')
        m.db.session.add(part); m.db.session.commit()
        return part

    def test_unknown_date_does_not_generate_distance_and_get_preserves_records(self):
        a = self.part('', 1000); b = self.part('2026-02-01', 1500)
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/parts')
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn('交換日未確認のため比較不可', text)
        self.assertNotIn('前回から 500', text)
        self.assertEqual((a.replacement_date, a.mileage, b.replacement_date, b.mileage),
                         ('', Decimal(1000), '2026-02-01', Decimal(1500)))
        self.assertEqual(self.m.VehiclePartReplacement.query.count(), 2)

    def test_reversed_meter_displays_reason_not_missing_history(self):
        self.part('2026-01-01', 1500); self.part('2026-02-01', 1000)
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/parts')
        self.assertEqual(response.status_code, 200)
        self.assertIn('走行距離が逆転しているため比較不可', response.get_data(as_text=True))

    def test_known_zero_interval_is_rendered_as_zero(self):
        self.part('2026-01-01', 1000); self.part('2026-02-01', 1000)
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/parts')
        self.assertEqual(response.status_code, 200)
        self.assertIn('前回から 0 km', response.get_data(as_text=True))

    def test_missing_prior_meter_is_not_missing_prior_history(self):
        self.part('2026-01-01', None); self.part('2026-02-01', 1000)
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/parts')
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn('走行距離未確認のため比較不可', text)
        self.assertEqual(text.count('前回記録なし'), 1)

    def test_conflicting_same_day_prior_meters_do_not_choose_by_row_id(self):
        self.part('2026-01-01', 1000); self.part('2026-01-01', 1200)
        self.part('2026-02-01', 1500)
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/parts')
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn('前回交換時の走行距離が不一致のため比較不可', text)
        self.assertNotIn('前回から 300', text)
        self.assertNotIn('前回から 500', text)

    def test_duplicate_same_event_lines_keep_one_event_and_known_distance(self):
        a = self.part('2026-01-01', 1000)
        m = self.m
        duplicate = m.VehiclePartReplacement(company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=a.maintenance_record_id, part_name='タイヤ',
            replacement_date=a.replacement_date, mileage=a.mileage,
            created_at='2026-02-01', updated_at='2026-02-01')
        m.db.session.add(duplicate); m.db.session.commit()
        self.part('2026-02-01', 1500)
        with m.app.test_request_context('/'):
            data = m.get_vehicle_karte_parts_context(self.vehicle)
        self.assertEqual(data['part_groups'][0]['replacement_count'], 2)
        self.assertEqual(data['part_rows'][0]['distance'], Decimal(500))
        self.assertEqual(m.VehiclePartReplacement.query.count(), 3)

    def test_conflicting_current_event_lines_do_not_reuse_first_line_distance(self):
        self.part('2026-01-01', 1000)
        a = self.part('2026-02-01', 1500)
        m = self.m
        m.db.session.add(m.VehiclePartReplacement(company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=a.maintenance_record_id, part_name='タイヤ',
            replacement_date=a.replacement_date, mileage=1600,
            created_at='2026-02-01', updated_at='2026-02-01'))
        m.db.session.commit()
        with m.app.test_request_context('/'):
            data = m.get_vehicle_karte_parts_context(self.vehicle)
        self.assertEqual(data['part_groups'][0]['replacement_count'], 2)
        for row in data['part_rows'][:2]:
            self.assertIsNone(row['distance'])
            self.assertEqual(row['distance_note'], '交換時の走行距離が不一致のため比較不可')
