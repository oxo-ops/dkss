from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal
import unittest

from dkss_app.analysis import calculate_adopted_maintenance_rule_timing
from vehicle_priority_assessment import Scope, Evidence, Reference, InvalidInput, Candidate, Fact, assess_priority
from vehicle_priority_timing_sources import TimingBinding, ReferenceBinding, bridge_adopted_timing, timing_snapshot_hash, reference_snapshot_hash


class TimingBridgeTests(unittest.TestCase):
    def case(self, metric='distance_km', value=Decimal('1000'), relation='single', action='replace'):
        rule = {'action': action, 'cycle': 'repeat', 'relation': relation,
            'source_quote': 'Synthetic maintenance interval',
            'vehicle_applicability': {'status': 'conditions_matched'},
            'analysis_adoption': {'status': 'adopted_for_analysis', 'rule_key': 'rule-1',
                'document_id': 1, 'document_checksum': 'checksum-1',
                'knowledge_source_id': 'knowledge:1', 'vehicle_source_id': 'vehicle:1',
                'source_url': 'https://example.com/manual'},
            'criteria': [{'metric': metric, 'value': value}]}
        if relation != 'single':
            rule['criteria'].append({'metric': 'period_days', 'value': 100})
        facts = {'as_of': '2026-03-01', 'part_replacements': [{
            'part_name': 'synthetic part', 'latest_dated_replacement': '2026-01-31',
            'replacement_date_usable': True, 'replacement_mileage': 1000,
            'replacement_mileage_usable': True, 'distance_since_km': 900,
            'source_ids': ['part:1']}], 'inspection_items': []}
        if action == 'inspect':
            item_name = 'synthetic part condition inspection'
            rule['source_quote'] = item_name + ' every 1000 km'
            facts['inspection_items'] = [{
                'item_name': item_name, 'inspection_item_index': 3,
                'inspection_date': '2026-01-31', 'inspection_date_usable': True,
                'inspection_mileage': 1000, 'inspection_mileage_usable': True,
                'distance_since_km': 900, 'source_ids': ['periodic:1']}]
        summary = {'end_date': '2026-03-01', 'current_mileage_date': '2026-02-28',
            'current_mileage': 1900, 'mileage_reference': {'distance_usable': True}}
        timing = calculate_adopted_maintenance_rule_timing(rule, 'synthetic part', facts, summary)
        scope = Scope('TEST', 1, 'synthetic part')
        binding = TimingBinding(scope, 'event-1', date(2026, 3, 1), timing_snapshot_hash(rule, timing),
            'rule-1', 'checksum-1', ('ref-1',), ('event:1',), True, True, date(2026, 3, 1))
        evidence = {'event:1': Evidence('event:1', scope, binding.as_of, 'event-1',
            'Explicit host-reviewed event', verified=True)}
        references = {'ref-1': Reference('ref-1', 'https://example.com/manual', 'Synthetic maker',
            'Synthetic manual', 'version-1', rule['source_quote'], 'manufacturer', True, True)}
        binding = replace(binding, reference_bindings=(ReferenceBinding('ref-1', 'checksum-1',
            reference_snapshot_hash(references['ref-1'])),))
        return rule, timing, binding, evidence, references

    def bridge(self, case, rebind=False):
        rule, timing, binding, evidence, references = case
        if rebind:
            binding = replace(binding, snapshot_hash=timing_snapshot_hash(rule, timing))
        return bridge_adopted_timing(rule, timing, binding, evidence, references)

    def test_authentic_service_distance_and_no_mutation(self):
        case = self.case()
        original = deepcopy(case)
        result = self.bridge(case)
        self.assertEqual(case, original)
        self.assertEqual(result.timings[0].elapsed, 900)
        self.assertEqual(result.timings[0].interval, 1000)
        self.assertEqual(result.timings[0].source_ids, ('event:1',))
        self.assertIn('part:1', result.provenance_source_ids)
        self.assertFalse(result.timings[0].legal_deadline)
        self.assertFalse(result.production_enabled)

    def test_any_fully_calculable_emits_each(self):
        self.assertEqual(len(self.bridge(self.case(relation='any')).timings), 2)

    def test_all_never_flattens_even_if_one_reached(self):
        result = self.bridge(self.case(value=800, relation='all'))
        self.assertEqual(result.timings, ())
        self.assertIn('AND', result.missing_conditions[0])

    def test_incomplete_any_wholly_withheld(self):
        case = self.case(relation='any')
        case[1]['criteria'][1]['calculation_permitted'] = False
        self.assertEqual(self.bridge(case, True).timings, ())

    def test_month_clamp_due_only(self):
        result = self.bridge(self.case('period_months', 1))
        self.assertEqual(result.timings[0].due_on, date(2026, 2, 28))
        self.assertIsNone(result.timings[0].elapsed)
        self.assertIn('90', result.missing_conditions[0])

    def test_calendar_days_ratio_and_date(self):
        result = self.bridge(self.case('period_days', 30))
        self.assertEqual(result.timings[0].due_on, date(2026, 3, 2))
        self.assertEqual(result.timings[0].elapsed, 29)
        self.assertEqual(result.timings[0].interval, 30)

    def test_stale_snapshot_or_reference_rejected(self):
        case = self.case()
        case[0]['source_quote'] = 'Changed'
        with self.assertRaises(InvalidInput): self.bridge(case)
        case = list(self.case())
        case[2] = replace(case[2], reference_checked_on=date(2026, 2, 28))
        with self.assertRaises(InvalidInput): self.bridge(case)

    def test_foreign_or_unreviewed_reference_rejected(self):
        for change in ({'applicable': False}, {'verified': False}, {'quote': 'Other'}, {'version': ''}):
            case = self.case()
            case[4]['ref-1'] = replace(case[4]['ref-1'], **change)
            with self.assertRaises(InvalidInput): self.bridge(case)

    def test_historical_baseline_not_relabelled(self):
        case = self.case()
        case[3]['event:1'] = replace(case[3]['event:1'], event_id='replacement-1', status='past')
        with self.assertRaises(InvalidInput): self.bridge(case)

    def test_result_tampering_withheld_even_with_new_hash(self):
        for key, value in [('elapsed_km', 901), ('threshold', 999), ('status', 'reached'),
                           ('baseline_date', '2026-03-02'), ('remaining_km', 0)]:
            case = self.case()
            case[1]['criteria'][0][key] = value
            self.assertEqual(self.bridge(case, True).timings, (), key)

    def test_calendar_tampering_withheld(self):
        case = self.case('period_months', 1)
        case[1]['criteria'][0]['due_date'] = '2026-03-03'
        self.assertEqual(self.bridge(case, True).timings, ())

    def test_decimal_boundary_and_precision(self):
        from vehicle_priority_timing_sources import _ratio
        self.assertEqual(_ratio(Decimal('0.9'), Decimal('1')), (0.9, 1))
        with self.assertRaises(ValueError): _ratio(Decimal('0.90000000000000000001'), 1)
        # Native arithmetic can put 90% just above the exact value.
        with self.assertRaises(ValueError): _ratio(Decimal('0.09'), Decimal('0.1'))
        for v in (True, float('nan'), float('inf'), -1):
            with self.assertRaises((ValueError, OverflowError)): _ratio(v, 1)

    def test_reference_version_substitution_rejected(self):
        case = self.case()
        case[4]['ref-1'] = replace(case[4]['ref-1'], version='different-edition')
        with self.assertRaises(InvalidInput): self.bridge(case)
        case = list(self.case())
        rb = replace(case[2].reference_bindings[0], document_checksum='other-checksum')
        case[2] = replace(case[2], reference_bindings=(rb,))
        with self.assertRaises(InvalidInput): self.bridge(case)

    def test_typed_hash_no_decimal_tag_collision(self):
        self.assertNotEqual(timing_snapshot_hash({'value': Decimal('1')}, {}),
                            timing_snapshot_hash({'value': {'decimal': '1'}}, {}))
        self.assertNotEqual(timing_snapshot_hash({'value': 1}, {}),
                            timing_snapshot_hash({'value': '1'}, {}))

    def test_malformed_containers_and_excerpts_controlled(self):
        for index in (3, 4):
            case = list(self.case())
            case[index] = None
            with self.assertRaises(InvalidInput): self.bridge(case)
        case = self.case()
        case[3]['event:1'] = replace(case[3]['event:1'], excerpt=None)
        with self.assertRaises(InvalidInput): self.bridge(case)
        for invalid in (None, [], 1, 'bad'):
            case = self.case()
            case[1]['criteria'][0] = invalid
            self.assertEqual(self.bridge(case, True).timings, ())
        for key in ('action', 'cycle', 'relation'):
            case = self.case()
            case[0][key] = []
            with self.assertRaises(InvalidInput): self.bridge(case, True)

    def test_large_decimal_subtraction_cannot_hide_reached_threshold(self):
        case = self.case()
        huge = Decimal('1000000000000000000000000000001')
        case[0]['criteria'][0]['value'] = huge
        row = case[1]['criteria'][0]
        row.update(threshold=huge, replacement_mileage=0, recorded_mileage=huge,
                   elapsed_km=Decimal('1000000000000000000000000000000'),
                   remaining_km=1, excess_km=0, status='not_reached_at_reference')
        self.assertEqual(self.bridge(case, True).timings, ())

    def test_caller_low_decimal_precision_does_not_change_output(self):
        from decimal import localcontext
        case = self.case()
        expected = self.bridge(case)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(self.bridge(case), expected)

    def test_bridge_to_existing_scorer_single_any_and_withheld_all(self):
        for relation, expected in (('single', 35), ('any', 35), ('all', None)):
            with self.subTest(relation=relation):
                case = self.case(value=800, relation=relation)
                bridged = self.bridge(case)
                binding, evidence, references = case[2:]
                candidate = Candidate('proposal-1', binding.scope, binding.event_id,
                    timings=bridged.timings, missing_conditions=bridged.missing_conditions)
                assessment = assess_priority(candidate, evidence, references, as_of=binding.as_of)
                timing = next(f for f in assessment['factors'] if f['axis'] == 'timing')
                self.assertEqual(timing['points'], expected)
                self.assertEqual(assessment['effective_score'], expected or 0)
                self.assertEqual(assessment['label'], '低' if expected is None else '中')
                if relation == 'all':
                    self.assertTrue(any('AND' in m for m in assessment['missing_conditions']))

    def test_all_not_accidentally_promoted_high_by_or_flattening(self):
        # Independent explicit synthetic impact fact, never inferred by the bridge.
        for relation, score, label in (('any', 60, '高'), ('all', 25, '中')):
            case = self.case(value=800, relation=relation)
            bridged = self.bridge(case)
            binding, evidence, references = case[2:]
            candidate = Candidate('proposal-1', binding.scope, binding.event_id,
                facts=(Fact('impact_functional', binding.event_source_ids, verified=True),),
                timings=bridged.timings, missing_conditions=bridged.missing_conditions)
            assessment = assess_priority(candidate, evidence, references, as_of=binding.as_of)
            self.assertEqual(assessment['effective_score'], score)
            self.assertEqual(assessment['label'], label)

    def test_authentic_inspection_procedure_and_mileage_origin(self):
        case = self.case(action='inspect')
        timing = case[1]
        self.assertEqual(timing['status'], 'not_reached_at_reference_dates')
        row = timing['criteria'][0]
        self.assertEqual(row['baseline_kind'], 'inspection')
        self.assertEqual(row['inspection_item_index'], 3)
        self.assertEqual(row['inspection_mileage'], 1000)
        self.assertNotIn('replacement_mileage', row)
        before = deepcopy(case)
        result = self.bridge(case)
        self.assertEqual(case, before)
        self.assertEqual(len(result.timings), 1)
        self.assertEqual(result.timings[0].elapsed, 900)
        self.assertEqual(result.timings[0].interval, 1000)
        self.assertIn('periodic:1', result.provenance_source_ids)
        self.assertNotIn('part:1', result.provenance_source_ids)
        binding, evidence, references = case[2:]
        assessment = assess_priority(Candidate('inspection-proposal', binding.scope,
            binding.event_id, timings=result.timings), evidence, references, as_of=binding.as_of)
        self.assertEqual(assessment['effective_score'], 25)

    def test_inspection_missing_or_invalid_origin_metadata_withheld(self):
        for key, value in (('baseline_kind', None), ('baseline_kind', 'replacement'),
                           ('inspection_item_index', None), ('inspection_item_index', -1),
                           ('inspection_item_index', '3'), ('inspection_item_index', True)):
            with self.subTest(key=key, value=value):
                case = self.case(action='inspect')
                case[1]['criteria'][0][key] = value
                self.assertEqual(self.bridge(case, True).timings, ())
        case = self.case(action='inspect')
        del case[1]['criteria'][0]['inspection_item_index']
        self.assertEqual(self.bridge(case, True).timings, ())
        case = self.case(action='inspect')
        del case[1]['criteria'][0]['baseline_kind']
        self.assertEqual(self.bridge(case, True).timings, ())


if __name__ == '__main__':
    unittest.main()
