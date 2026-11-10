"""Pure real-schema adapter contracts; only synthetic values are used."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import unittest

from vehicle_priority_assessment import InvalidInput
from vehicle_priority_sources import DefectRecord, DefectSnapshot, assess_registered_defects


class RegisteredDefectAdapterTests(unittest.TestCase):
    day = date(2026, 11, 10)

    def row(self, status='未対応', **changes):
        row = DefectRecord(1, 'TEST', 2, '2020-01-01', '合成の指摘内容', status, None)
        return replace(row, **changes)

    def run_snapshot(self, *rows):
        snapshot = DefectSnapshot('TEST', 2, self.day, tuple(rows))
        before = deepcopy(snapshot)
        output = assess_registered_defects(snapshot, as_of=self.day)
        self.assertEqual(snapshot, before)
        return output

    def test_registered_open_states_only_supply_state_axis(self):
        for status in ('未対応', '対応中'):
            with self.subTest(status=status):
                output = self.run_snapshot(self.row(status))
                item = output['items'][0]
                self.assertEqual(item['assessment']['base_score'], 10)
                self.assertEqual(item['assessment']['label'], '低')
                self.assertEqual([f['points'] for f in item['assessment']['factors']], [None, None, 10])
                self.assertEqual(item['record']['occurred_date'], '2020-01-01')
                self.assertEqual(item['assessment']['observed_on'], self.day.isoformat())
                self.assertEqual(item['assessment']['event_id'], 'defect:1')
                self.assertFalse(item['assessment']['safety_cleared'])
                self.assertFalse(output['production_enabled'])

    def test_component_name_and_dramatic_prose_never_infer_severity(self):
        first = self.run_snapshot(self.row(content='ブレーキ危険・高・再発・今すぐ交換・運行不可'))
        result = first['items'][0]['assessment']
        self.assertEqual(result['effective_score'], 10)
        self.assertEqual(result['applied_floors'], [])
        self.assertEqual(result['factors'][0]['fact_codes'], [])
        self.assertEqual(result['factors'][2]['fact_codes'], ['state_open'])

    def test_repair_complete_does_not_recreate_open_task(self):
        output = self.run_snapshot(self.row('修理完了', repair_date='2026-11-01'))
        self.assertEqual(output['items'], [])
        self.assertEqual(output['excluded_records'][0]['reason'], 'registered_repair_complete')
        self.assertEqual(output['excluded_records'][0]['registered_status'], '修理完了')

    def test_unknown_state_never_becomes_a_fourth_priority_or_inferred_open_state(self):
        for status in (None, '', '未評価', '完了', ' 未対応', 'unknown'):
            result = self.run_snapshot(self.row(status))['items'][0]['assessment']
            self.assertEqual(result['label'], '低')
            self.assertEqual(result['base_score'], 0)
            self.assertEqual([f['points'] for f in result['factors']], [None, None, None])
            self.assertIn('現在の登録状態を確認要', result['missing_conditions'])

    def test_missing_dates_are_not_invented_or_used_as_deadlines(self):
        result = self.run_snapshot(self.row(occurred_date=None))['items'][0]
        self.assertIsNone(result['record']['occurred_date'])
        self.assertIsNone(result['assessment']['earliest_due_on'])
        self.assertIn('発生日の記録を確認要', result['assessment']['missing_conditions'])
        self.assertEqual(result['assessment']['base_score'], 10)

    def test_conflicting_dates_withhold_current_state_fact(self):
        for changes in ({'occurred_date':'2026-11-11'}, {'repair_date':'2026-11-11'},
                        {'occurred_date':'2026-11-01','repair_date':'2026-10-31'}):
            result = self.run_snapshot(self.row(**changes))['items'][0]['assessment']
            self.assertEqual(result['base_score'], 0)
            self.assertIn('発生日・修理日と取得日の関係を確認要', result['missing_conditions'])
        output = self.run_snapshot(self.row('修理完了', repair_date='2026-11-11'))
        self.assertEqual(len(output['items']), 1)
        self.assertEqual(output['excluded_records'], [])

    def test_different_as_of_cannot_reconstruct_historical_status(self):
        snapshot = DefectSnapshot('TEST', 2, self.day, (self.row(),))
        for other in (self.day-timedelta(days=1), self.day+timedelta(days=1), '2026-11-10'):
            with self.assertRaises(InvalidInput):
                assess_registered_defects(snapshot, as_of=other)

    def test_foreign_duplicate_invalid_ids_and_wrong_types_are_rejected(self):
        for rows in ((self.row(company_code='OTHER'),), (self.row(vehicle_id=3),),
                     (self.row(), self.row()), (self.row(record_id=True),),
                     (self.row(content={}),), (self.row(registered_status=['未対応']),)):
            with self.assertRaises(InvalidInput):
                self.run_snapshot(*rows)
        for change in ({'company_code':''}, {'vehicle_id':True}, {'records':[]}, {'captured_on':None}):
            snapshot = replace(DefectSnapshot('TEST', 2, self.day, ()), **change)
            with self.assertRaises(InvalidInput):
                assess_registered_defects(snapshot, as_of=self.day)

    def test_repeat_fingerprint_and_scope_separate_records_without_merging_targets(self):
        rows = (self.row(record_id=2), self.row(record_id=1))
        first, second = self.run_snapshot(*rows), self.run_snapshot(*rows)
        self.assertEqual(first, second)
        self.assertEqual([i['assessment']['candidate_id'] for i in first['items']], ['defect:1','defect:2'])
        changed = self.run_snapshot(self.row(record_id=2, registered_status='対応中'), self.row())
        self.assertNotEqual(first['snapshot_fingerprint'], changed['snapshot_fingerprint'])

    def test_empty_collection_is_no_records_not_zero_risk(self):
        output = self.run_snapshot()
        self.assertEqual(output['items'], [])
        self.assertEqual(output['excluded_records'], [])
        self.assertNotIn('priority', output)


if __name__ == '__main__':
    unittest.main()
