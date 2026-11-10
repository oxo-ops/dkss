"""Verified condition expression, not new AND or calendar-month score policy."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
import unittest

from dkss_app.analysis import calculate_adopted_maintenance_rule_timing
from vehicle_priority_assessment import Candidate, Evidence, Reference, Scope, assess_priority, InvalidInput
from vehicle_priority_timing_sources import (
    ReferenceBinding, TimingBinding, bridge_adopted_timing,
    reference_snapshot_hash, timing_snapshot_hash, timing_condition_payload,
)


class TimingConditionViewTests(unittest.TestCase):
    def case(self, criteria=None, relation='all', baseline='2026-01-31', as_of='2026-03-01',
             mileage_date=None, elapsed=900):
        criteria=criteria or [{'metric':'period_days','value':45},{'metric':'period_months','value':1}]
        rule={'action':'replace','cycle':'repeat','relation':relation,'criteria':criteria,
              'source_quote':'Synthetic rule: preserve all conditions',
              'vehicle_applicability':{'status':'conditions_matched'},
              'analysis_adoption':{'status':'adopted_for_analysis','rule_key':'rule-A',
                  'document_id':1,'document_checksum':'sha-A','knowledge_source_id':'knowledge:1',
                  'vehicle_source_id':'vehicle:1','source_url':'https://example.com/synthetic'}}
        facts={'as_of':as_of,'part_replacements':[{'part_name':'synthetic part',
              'latest_dated_replacement':baseline,'replacement_date_usable':True,
              'replacement_mileage':1000,'replacement_mileage_usable':True,
              'distance_since_km':elapsed,'source_ids':['part:1']}], 'inspection_items':[]}
        summary={'end_date':as_of,'current_mileage_date':mileage_date or as_of,
                 'current_mileage':1000+elapsed,'mileage_reference':{'distance_usable':True}}
        timing=calculate_adopted_maintenance_rule_timing(rule,'synthetic part',facts,summary)
        day=date.fromisoformat(as_of);scope=Scope('TEST',1,'synthetic part')
        evidence={'event:1':Evidence('event:1',scope,day,'event-1','Explicit synthetic event',verified=True)}
        reference=Reference('ref:1',rule['analysis_adoption']['source_url'],'Synthetic maker',
                            'Synthetic rule','v1',rule['source_quote'],'manufacturer',True,True)
        references={'ref:1':reference}
        binding=TimingBinding(scope,'event-1',day,timing_snapshot_hash(rule,timing),'rule-A','sha-A',
            ('ref:1',),('event:1',),True,True,day,(ReferenceBinding('ref:1','sha-A',reference_snapshot_hash(reference)),))
        return rule,timing,binding,evidence,references

    def run_case(self,case):
        before=deepcopy(case)
        result=bridge_adopted_timing(*case)
        self.assertEqual(before,case)
        payload=timing_condition_payload(result)
        json.dumps(payload,allow_nan=False)
        return result,payload

    def test_calendar_and_retains_individual_conditions_and_latest_date(self):
        result,payload=self.run_case(self.case())
        group=result.condition_group
        self.assertEqual(result.timings,())
        self.assertEqual(group.calendar_threshold_on,date(2026,3,17))
        self.assertEqual(group.calendar_threshold_basis,'all_calendar_conditions_latest')
        self.assertFalse(group.threshold_reached)
        self.assertEqual([c.threshold_reached for c in group.conditions],[False,True])
        self.assertEqual([c.due_on for c in group.conditions],[date(2026,3,17),date(2026,2,28)])
        self.assertFalse(payload['scoring_input_emitted'])
        self.assertEqual(payload['relation'],'all')
        self.assertEqual(payload['scope'],{'company_code':'TEST','vehicle_id':1,'target':'synthetic part'})
        self.assertEqual(payload['event_id'],'event-1')
        self.assertEqual(payload['as_of'],'2026-03-01')
        self.assertIn('AND', ' '.join(payload['missing_conditions']))

    def test_calendar_and_before_on_and_after_last_threshold(self):
        for day,reached in [('2026-03-16',False),('2026-03-17',True),('2026-03-18',True)]:
            result,_=self.run_case(self.case(as_of=day))
            self.assertEqual(result.condition_group.threshold_reached,reached)
            self.assertEqual(result.condition_group.calendar_threshold_on,date(2026,3,17))
            self.assertEqual(result.timings,())

    def test_calendar_any_keeps_earliest_without_changing_existing_scored_inputs(self):
        result,payload=self.run_case(self.case(relation='any'))
        self.assertEqual(result.condition_group.calendar_threshold_on,date(2026,2,28))
        self.assertTrue(result.condition_group.threshold_reached)
        self.assertEqual(len(result.timings),2)
        self.assertTrue(payload['scoring_input_emitted'])
        self.assertEqual(result.condition_group.calendar_threshold_basis,'any_calendar_condition_earliest')

    def test_and_has_no_scoring_even_when_calendar_threshold_is_reached(self):
        case=self.case(as_of='2026-03-18');result,_=self.run_case(case)
        binding=case[2]
        candidate=Candidate('proposal:1',binding.scope,binding.event_id,timings=result.timings,
                            missing_conditions=result.missing_conditions)
        assessment=assess_priority(candidate,case[3],case[4],as_of=binding.as_of)
        self.assertIsNone(assessment['factors'][1]['points'])
        self.assertIsNone(assessment['earliest_due_on'])
        self.assertEqual(assessment['applied_floors'],[])

    def test_mixed_and_has_no_invented_calendar_crossing_date(self):
        criteria=[{'metric':'distance_km','value':1000},{'metric':'period_months','value':1}]
        for elapsed,reached in [(900,False),(1000,True)]:
            result,payload=self.run_case(self.case(criteria=criteria,elapsed=elapsed,mileage_date='2026-02-28'))
            group=result.condition_group
            self.assertEqual(group.threshold_reached,reached)
            self.assertIsNone(group.calendar_threshold_on)
            self.assertIsNone(group.calendar_threshold_basis)
            self.assertEqual(group.conditions[0].reference_on,date(2026,2,28))
            self.assertEqual(group.as_of,date(2026,3,1))
            self.assertEqual(result.timings,())
            self.assertEqual(payload['condition_group']['conditions'][0]['quantity_unit'],'km')

    def test_mixed_or_preserves_scoring_without_inventing_group_calendar_date(self):
        criteria=[{'metric':'distance_km','value':1000},{'metric':'period_days','value':100}]
        result,payload=self.run_case(self.case(criteria=criteria,relation='any'))
        self.assertIsNone(result.condition_group.calendar_threshold_on)
        self.assertEqual(len(result.timings),2)
        self.assertEqual(result.missing_conditions,())
        self.assertIn('距離条件',result.condition_group.note)
        self.assertTrue(payload['scoring_input_emitted'])

    def test_factual_and_does_not_require_native_float_scoring_approximation(self):
        criteria=[{'metric':'distance_km','value':Decimal('0.1')},{'metric':'period_days','value':100}]
        result,payload=self.run_case(self.case(criteria=criteria,elapsed=Decimal('0.09')))
        self.assertIsNotNone(result.condition_group)
        condition=result.condition_group.conditions[0]
        self.assertEqual(condition.elapsed_quantity,'0.09')
        self.assertEqual(condition.remaining_quantity,'0.01')
        self.assertFalse(condition.threshold_reached)
        self.assertEqual(result.timings,())
        self.assertIn('AND',result.missing_conditions[0])

    def test_incomplete_and_does_not_present_unverified_rows_as_facts(self):
        case=list(self.case(criteria=[{'metric':'distance_km','value':1000},{'metric':'engine_hours','value':100}]))
        result,payload=self.run_case(case)
        self.assertIsNone(result.condition_group)
        self.assertEqual(payload['status'],'calculation_unavailable')
        self.assertIsNone(payload['condition_group'])
        self.assertFalse(payload['scoring_input_emitted'])
        self.assertEqual(result.timings,())

    def test_tampered_and_criterion_cannot_appear_verified_even_with_rebound_hash(self):
        for changes in ({'due_date':'2026-03-16'},{'elapsed_days':900},{'threshold':999},
                        {'status':'reached'},{'baseline_date':'2026-03-02'}):
            case=list(self.case())
            case[1]['criteria'][0].update(changes)
            case[2]=replace(case[2],snapshot_hash=timing_snapshot_hash(case[0],case[1]))
            result,payload=self.run_case(case)
            self.assertIsNone(result.condition_group)
            self.assertEqual(payload['status'],'calculation_unavailable')

    def test_tampered_and_aggregate_reached_is_rejected(self):
        case=list(self.case())
        case[1]['status']='threshold_reached'
        case[2]=replace(case[2],snapshot_hash=timing_snapshot_hash(case[0],case[1]))
        result,_=self.run_case(case)
        self.assertIsNone(result.condition_group)

    def test_months_are_added_directly_not_iteratively(self):
        result,payload=self.run_case(self.case([{'metric':'period_months','value':2}],relation='single'))
        condition=result.condition_group.conditions[0]
        self.assertEqual(condition.due_on,date(2026,3,31))
        self.assertEqual(condition.calendar_interval_days,59)
        self.assertEqual(condition.threshold,'2')
        self.assertEqual(condition.unit,'calendar_months')
        self.assertIsNone(result.timings[0].elapsed)
        values=payload['condition_group']['conditions'][0]
        self.assertEqual(values['quantity_unit'],'days')
        self.assertEqual(values['unit'],'calendar_months')
        self.assertNotIn('progress_ratio',values)

    def test_leap_month_and_nonleap_month_end(self):
        for baseline,as_of,due,days in [('2024-01-31','2024-02-29','2024-02-29',29),
                                       ('2025-01-31','2025-02-28','2025-02-28',28),
                                       ('2024-02-29','2025-02-28','2025-02-28',365)]:
            amount=12 if baseline.startswith('2024-02') else 1
            result,_=self.run_case(self.case([{'metric':'period_months','value':amount}],relation='single',
                                           baseline=baseline,as_of=as_of))
            condition=result.condition_group.conditions[0]
            self.assertEqual(condition.due_on,date.fromisoformat(due))
            self.assertEqual(condition.calendar_interval_days,days)
            self.assertTrue(condition.threshold_reached)

    def test_months_do_not_invent_ninety_percent_from_elapsed_days(self):
        result,payload=self.run_case(self.case([{'metric':'period_months','value':1}],relation='single',
                                              as_of='2026-02-26'))
        condition=result.condition_group.conditions[0]
        self.assertEqual(condition.elapsed_quantity,'26')
        self.assertEqual(condition.calendar_interval_days,28)
        self.assertIsNone(result.timings[0].elapsed)
        self.assertIsNone(result.timings[0].interval)
        self.assertTrue(any('90' in m for m in result.missing_conditions))
        self.assertNotIn('ratio',json.dumps(payload))

    def test_invalid_calendar_inputs_stay_unavailable(self):
        for metric,value,baseline in [('period_months',Decimal('1.5'),'2026-01-31'),
                                     ('period_months',1,'2026-01'),
                                     ('period_months',1,'2026-04-01'),
                                     ('period_days',-1,'2026-01-31')]:
            case=self.case([{'metric':metric,'value':value}],relation='single',baseline=baseline)
            # Upstream held input may lack provenance; identity/provenance rejects
            # it rather than giving it a verified view or a zero date.
            try:result,payload=self.run_case(case)
            except InvalidInput:continue
            self.assertIsNone(result.condition_group)
            self.assertEqual(payload['status'],'calculation_unavailable')

    def test_payload_retains_quote_as_text_not_generated_markup(self):
        case=list(self.case())
        quote='<script>synthetic</script> AND condition text'
        case[0]['source_quote']=quote
        ref=replace(case[4]['ref:1'],quote=quote)
        case[4]['ref:1']=ref
        case[2]=replace(case[2],snapshot_hash=timing_snapshot_hash(case[0],case[1]),
                        reference_bindings=(ReferenceBinding('ref:1','sha-A',reference_snapshot_hash(ref)),))
        _,payload=self.run_case(case)
        self.assertEqual(payload['condition_group']['source_quote'],quote)
        self.assertNotIn('html',payload)
        self.assertFalse(payload['production_enabled'])

    def test_repeat_and_json_serialization_are_stable(self):
        case=self.case()
        self.assertEqual(self.run_case(case),self.run_case(case))
        with self.assertRaises(InvalidInput):timing_condition_payload({})


if __name__=='__main__':unittest.main()
