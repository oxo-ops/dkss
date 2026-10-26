"""Recorded evidence and calendar boundaries for the shared timing policy."""
from copy import deepcopy
import unittest

from dkss_app.analysis import calculate_adopted_maintenance_rule_timing as calculate


class MaintenanceTimingTests(unittest.TestCase):
    def case(self, action='replace', metric='period_months', value=1):
        rule = {'action': action, 'cycle': 'repeat', 'relation': 'single',
                'source_quote': 'エアドライヤ排出水量・状態の確認',
                'analysis_adoption': {'status': 'adopted_for_analysis',
                                     'knowledge_source_id': 'knowledge:1',
                                     'vehicle_source_id': 'vehicle:1'},
                'criteria': [{'metric': metric, 'value': value}]}
        summary = {'end_date': '2026-03-31', 'current_mileage_date': '2026-03-30',
                   'current_mileage': 15000, 'mileage_reference': {'distance_usable': True}}
        facts = {'as_of': summary['end_date'], 'part_replacements': [{
            'part_name': 'エアドライヤ', 'latest_dated_replacement': '2026-01-31',
            'replacement_date_usable': True, 'replacement_mileage': 10000,
            'replacement_mileage_usable': True, 'distance_since_km': 5000,
            'source_ids': ['part:1']}], 'inspection_items': [{
                'item_name': rule['source_quote'], 'inspection_item_index': 3,
                'inspection_date': '2026-01-31', 'inspection_date_usable': True,
                'inspection_mileage': 10000, 'inspection_mileage_usable': True,
                'distance_since_km': 5000, 'source_ids': ['periodic:1']}]}
        return rule, facts, summary

    def run_case(self, case):
        rule, facts, summary = case
        before = deepcopy(case)
        result = calculate(rule, 'エアドライヤ', facts, summary)
        self.assertEqual(case, before, 'Policy must not mutate recorded evidence')
        return result

    def test_month_end_clamps_to_last_calendar_day_for_both_actions(self):
        for action in ('replace', 'inspect'):
            with self.subTest(action=action):
                result = self.run_case(self.case(action))
                self.assertEqual(result['status'], 'threshold_reached')
                self.assertEqual(result['criteria'][0]['due_date'], '2026-02-28')
                self.assertEqual(result['criteria'][0]['overdue_days'], 31)
                self.assertEqual(result['source_ids'][0], 'part:1' if action == 'replace' else 'periodic:1')

    def test_inspection_retains_its_own_baseline_and_output_fields(self):
        result = self.run_case(self.case('inspect'))
        self.assertEqual(result['scope'], 'registered_inspection_and_reading_dates')
        self.assertEqual(result['criteria'][0]['baseline_kind'], 'inspection')
        self.assertEqual(result['criteria'][0]['inspection_item_index'], 3)
        self.assertNotIn('baseline_kind', self.run_case(self.case())['criteria'][0])

    def test_distance_uses_confirmed_meter_readings(self):
        for action, key in [('replace', 'replacement'), ('inspect', 'inspection')]:
            case = self.case(action, 'distance_km', 6000)
            result = self.run_case(case)
            self.assertEqual(result['status'], 'not_reached_at_reference_dates')
            self.assertEqual(result['criteria'][0]['remaining_km'], 1000)
            self.assertEqual(result['criteria'][0][key + '_mileage'], 10000)
            collection = 'part_replacements' if action == 'replace' else 'inspection_items'
            case[1][collection][0]['distance_since_km'] = 9999
            result = self.run_case(case)
            self.assertEqual(result['status'], 'unknown')
            self.assertFalse(result['calculation_permitted'])

    def test_invalid_thresholds_are_held_for_both_actions(self):
        for action in ('replace', 'inspect'):
            for value in (True, -1, 0, '1', float('inf')):
                with self.subTest(action=action, value=value):
                    result = self.run_case(self.case(action, value=value))
                    self.assertEqual(result['reason'], 'invalid_criterion')
                    self.assertEqual(result['criteria'], [])

    def test_unconfirmed_dates_and_missing_evidence_never_authorize_calculation(self):
        for action, collection, key, prefix in [
            ('replace', 'part_replacements', 'replacement', 'replacement'),
            ('inspect', 'inspection_items', 'inspection', 'inspection'),
        ]:
            case = self.case(action)
            case[1][collection][0][key + '_date_usable'] = False
            self.assertEqual(self.run_case(case)['reason'], prefix + '_date_not_confirmed')
            case = self.case(action)
            case[1][collection][0]['source_ids'] = []
            self.assertEqual(self.run_case(case)['reason'], prefix + '_evidence_missing')

    def test_inspection_record_does_not_establish_component_replacement(self):
        case = self.case()
        case[1]['part_replacements'] = []
        result = self.run_case(case)
        self.assertEqual(result['status'], 'held')
        self.assertFalse(result['calculation_permitted'])
        self.assertEqual(result['criteria'], [])

    def test_any_and_all_relations_keep_their_distinct_meaning(self):
        for action in ('replace', 'inspect'):
            case = self.case(action)
            case[0]['criteria'].append({'metric': 'distance_km', 'value': 6000})
            case[0]['relation'] = 'any'
            self.assertEqual(self.run_case(case)['status'], 'threshold_reached')
            case[0]['relation'] = 'all'
            self.assertEqual(self.run_case(case)['status'], 'not_reached_at_reference_dates')


if __name__ == '__main__':
    unittest.main()
