"""Common priority contracts using exact structured standard inspection facts."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import json
import unittest

from daily_inspection_defaults import get_daily_inspection_default
from vehicle_priority_projection import InspectionSnapshot, project_priority, VERSION, inspection_provenance

DAY = date(2026, 11, 11)


def fixture(code='daily_02', *, day=DAY, label='低', decision=None):
    template = get_daily_inspection_default()
    items = template['items']
    items[0].update(fixed_template_code=template['template_code'], fixed_template_version=1)
    number = next(i for i, row in enumerate(items) if row['item_code'] == code)
    target = items[number]['content']
    answer = dict(item_no=number, content=target, value='×', comment='', files=[])
    defect = dict(defect_no=1, item_no=str(number), status='対応待ち',
                  reported_at=day.isoformat() + ' 08:00:00', reported_answer=answer)
    judgment = dict(status='未判定', version=1, defects=[defect])
    if decision:
        judgment.update(status=decision, authority_confirmed=True, authority_role='整備管理者',
            judged_by_identity='synthetic-person-identity', judged_by_user_id=1,
            judged_at=day.isoformat() + ' 09:00:00')
    row = InspectionSnapshot('TEST', 1, 1, day.isoformat(), '点検完了',
        json.dumps({'items': items}, ensure_ascii=False), json.dumps([answer], ensure_ascii=False),
        json.dumps(judgment, ensure_ascii=False), day, 10000, True, False)
    item = dict(proposal_id='proposal', proposal_revision='original-revision', target=target,
        title='合成点検の対応確認', category='整備・点検', priority=label, source_ids=['inspection:1'],
        action='既存指摘への対応を確認', risk_status='unassessed', risk='機能への影響は未判定です。',
        feedback={'status': 'accepted', 'revision': 'original-revision'})
    return {'recommendations': [item], 'overview': 'synthetic'}, {'inspection:1': {
        'label': '合成点検', 'url': '/source', 'priority_provenance': inspection_provenance(row)}}, row


class CommonPriorityProjectionTests(unittest.TestCase):
    def project(self, analysis=None, sources=None, rows=None, *, day=DAY, **kwargs):
        if analysis is None:
            analysis, sources, row = fixture(day=day)
            rows = [row]
        return project_priority(analysis, sources, rows, company_code='TEST', vehicle_id=1,
            as_of=day, is_current=True, **kwargs)

    def value(self, *args, **kwargs):
        return self.project(*args, **kwargs)['recommendations'][0]['priority_assessment']

    def test_normal_structured_brake_failure_is_medium_50_not_risk_unassessed(self):
        result = self.project()
        item = result['recommendations'][0]
        value = item['priority_assessment']
        self.assertEqual((item['priority'], value['label'], value['base_score'], value['effective_score']), ('中', '中', 50, 50))
        self.assertEqual([f['points'] for f in value['factors']], [40, None, 10])
        self.assertEqual(value['calculation_status'], 'computed')
        self.assertEqual(value['missing_axes'], ['timing'])
        self.assertFalse(value['safety_cleared'])
        self.assertEqual(value['operation_decision'], 'human_only')
        self.assertEqual(item['risk_status'], 'unassessed')
        self.assertEqual(result['priority_order'], ['proposal'])

    def test_stop_related_proposal_preserves_saved_class_without_new_floor(self):
        for label in ('高','中','低'):
            analysis,sources,row=fixture(decision='運行不可',label=label)
            value=self.value(analysis,sources,[row])
            self.assertEqual(value['label'],label)
            self.assertIsNone(value['effective_score'])
            self.assertEqual(value['calculation_status'],'legacy_preserved')
            self.assertTrue(any('停止指示' in x for x in value['missing_conditions']))

    def test_hold_or_released_decision_is_not_instruction(self):
        for decision in ('判定保留', '運行可'):
            a, s, row = fixture(decision=decision)
            self.assertEqual(self.value(a, s, [row])['effective_score'], 50)

    def test_old_or_conflicting_stop_does_not_downgrade_saved_high(self):
        a,s,row=fixture(day=DAY-timedelta(days=5),decision='運行不可',label='高')
        row=replace(row,captured_on=DAY)
        _,_,second=fixture(decision='運行可');second=replace(second,record_id=2)
        for rows in ([row],[row,second]):
            value=self.value(a,s,rows)
            self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])

    def test_whole_inspection_stop_is_never_assigned_to_an_individual_event(self):
        a,s,row=fixture(decision='運行不可',label='高')
        judgment=json.loads(row.judgment_json)
        judgment['defects'].append(dict(judgment['defects'][0],defect_no=2,item_no='2'))
        row=replace(row,judgment_json=json.dumps(judgment))
        s['inspection:1']['priority_provenance']=inspection_provenance(row)
        value=self.value(a,s,[row])
        self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])
        self.assertEqual(value['applied_floors'],[])

    def test_recorded_prior_stop_or_unread_history_withholds_new_score(self):
        a,s,row=fixture(label='高')
        for changed in (replace(row,has_stop_history=True),replace(row,stop_history_reviewed=False)):
            value=self.value(a,s,[changed])
            self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])

    def test_additional_unscoped_inspection_citation_is_not_merged_into_bound_event(self):
        a,s,row=fixture(label='高')
        a['recommendations'][0]['source_ids'].append('inspection:999')
        s['inspection:999']={'label':'other cited record','url':'/source'}
        value=self.value(a,s,[row])
        self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])

    def test_repair_or_recheck_never_implicitly_releases_stop_or_computes_25(self):
        for key in ('repair','recheck'):
            a,s,row=fixture(label='高');judgment=json.loads(row.judgment_json)
            judgment['defects'][0][key]={'result':'異常なし'}
            row=replace(row,judgment_json=json.dumps(judgment))
            value=self.value(a,s,[row])
            self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])
            self.assertEqual(value['applied_floors'],[])

    def test_non_safety_s10_only_keeps_saved_class_without_inventing_score(self):
        for label in ('高','中','低'):
            a,s,row=fixture('daily_01',label=label)
            value=self.value(a,s,[row])
            self.assertEqual(value['label'],label)
            self.assertEqual(value['calculation_status'],'legacy_preserved')
            self.assertIsNone(value['effective_score'])

    def test_wheel_applicability_is_not_inferred(self):
        a,s,row=fixture('daily_18',label='高')
        self.assertIsNone(self.value(a,s,[row])['effective_score'])
        for weight in (None,7999, 'NaN', 'Infinity', 'unknown'):
            value=self.value(a,s,[replace(row,gross_vehicle_weight=weight)])
            self.assertEqual(value['label'],'高')
            self.assertIsNone(value['effective_score'])

    def test_component_name_generic_warning_and_ai_supported_are_not_bindings(self):
        for target in ('ブレーキ', '重大事故の危険', 'daily_02'):
            a,s,row=fixture(label='高')
            a['recommendations'][0].update(target=target,risk_status='supported',priority='高')
            self.assertEqual(self.value(a,s,[row])['calculation_status'],'legacy_preserved')

    def test_modified_standard_wording_version_choice_or_legend_is_withheld(self):
        for change in ('wording','version','choices','criteria'):
            a,s,row=fixture(label='高'); snapshot=json.loads(row.checklist_json)
            if change=='wording': snapshot['items'][1]['content']='ブレーキ'
            elif change=='version': snapshot['items'][0]['fixed_template_version']=2
            else: snapshot['items'][1][change]=[] if change=='choices' else '× means repaired'
            value=self.value(a,s,[replace(row,checklist_json=json.dumps(snapshot))])
            self.assertEqual(value['label'],'高'); self.assertIsNone(value['effective_score'])

    def test_duplicate_event_resolved_state_future_date_and_wrong_scope_are_withheld(self):
        for case in ('duplicate','resolved','future','other_company','other_vehicle'):
            a,s,row=fixture(label='高'); judgment=json.loads(row.judgment_json)
            if case=='duplicate': judgment['defects'].append(dict(judgment['defects'][0],defect_no=2))
            if case=='resolved': judgment['defects'][0]['status']='解消'
            if case in {'duplicate','resolved'}: row=replace(row,judgment_json=json.dumps(judgment))
            if case=='future': row=replace(row,inspection_on='2099-01-01')
            if case=='other_company': row=replace(row,company_code='OTHER')
            if case=='other_vehicle': row=replace(row,vehicle_id=2)
            value=self.value(a,s,[row]); self.assertEqual(value['label'],'高'); self.assertIsNone(value['effective_score'])

    def test_no_facts_stale_or_unavailable_does_not_turn_previous_high_into_low(self):
        a,s,row=fixture(label='高')
        for rows,extra in (([],{}),([row],{'unavailable_reason':'Synthetic read failure'})):
            value=self.value(a,s,rows,**extra)
            self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])

    def test_old_invalid_priority_has_no_fabricated_class_or_score(self):
        a,s,row=fixture(); a['recommendations'][0]['priority']='未評価'
        value=self.value(a,s,[])
        self.assertEqual(value['calculation_status'],'invalid_legacy')
        self.assertIsNone(value['label']);self.assertIsNone(value['effective_score'])

    def test_malformed_source_ids_fail_closed_without_exception(self):
        for ids in (None, 42, {}, ['inspection:1', {}], ['missing:1']):
            a,s,row=fixture(label='高');a['recommendations'][0]['source_ids']=ids
            value=self.value(a,s,[row]);self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])

    def test_invalid_report_datetime_suffix_is_not_a_recorded_observation(self):
        a,s,row=fixture(label='高');judgment=json.loads(row.judgment_json)
        judgment['defects'][0]['reported_at']=DAY.isoformat()+'garbage'
        row=replace(row,judgment_json=json.dumps(judgment))
        s['inspection:1']['priority_provenance']=inspection_provenance(row)
        value=self.value(a,s,[row])
        self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])

    def test_projection_preserves_original_identity_feedback_sources_and_risk(self):
        a,s,row=fixture();before=deepcopy((a,s,row))
        result=self.project(a,s,[row]);item=result['recommendations'][0]
        self.assertEqual((a,s,row),before)
        for key,value in a['recommendations'][0].items():
            if key!='priority':self.assertEqual(item[key],value)
        value=item['priority_assessment'];self.assertEqual(value['candidate_id'],item['proposal_id'])
        self.assertEqual(value['proposal_revision'],item['proposal_revision'])
        self.assertEqual(result,self.project(a,s,[row]))

    def test_record_discrepancy_category_is_not_a_safety_finding(self):
        a,s,row=fixture();a['recommendations'][0]['category']='記録確認'
        value=self.value(a,s,[row]);self.assertEqual(value['label'],'低');self.assertIsNone(value['effective_score'])

    def test_empty_recommendations_stay_empty(self):
        out=self.project({'recommendations':[]},{},[])
        self.assertEqual(out['recommendations'],[]);self.assertEqual(out['priority_order'],[])

    def test_old_source_without_server_provenance_preserves_label_and_has_no_new_score(self):
        a,s,row=fixture(label='高');s['inspection:1'].pop('priority_provenance')
        value=self.value(a,s,[row])
        self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])

    def test_same_source_and_target_cannot_rebind_to_new_event_answer_or_judgment(self):
        for field in ('defect_no','reported_at','answer'):
            a,s,row=fixture(label='高');judgment=json.loads(row.judgment_json)
            if field=='defect_no':judgment['defects'][0]['defect_no']=2
            elif field=='reported_at':judgment['defects'][0]['reported_at']=DAY.isoformat()+' 11:30:00'
            elif field=='answer':judgment['defects'][0]['reported_answer']['comment']='different event'
            value=self.value(a,s,[replace(row,judgment_json=json.dumps(judgment))])
            self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])

    def test_unrelated_row_or_event_changes_do_not_break_selected_event_binding(self):
        a,s,row=fixture()
        judgment=json.loads(row.judgment_json)
        judgment.update(version=31,status='運行可',reason='unrelated registration update')
        judgment['defects'].append(dict(judgment['defects'][0],defect_no=2,item_no='2'))
        row=replace(row,judgment_json=json.dumps(judgment),gross_vehicle_weight=15000)
        value=self.value(a,s,[row])
        self.assertEqual(value['effective_score'],50)

    def test_duplicate_proposal_ids_keep_original_indices_and_stable_sort(self):
        a,s,row=fixture()
        item=a['recommendations'][0]
        a['recommendations']=[dict(item,target='Legacy',priority=label,proposal_revision=str(i))
                               for i,label in enumerate(('低','高','中','高'))]
        out=self.project(a,s,[row])
        self.assertEqual(out['priority_order_format'],'source_indices_v1')
        self.assertEqual(out['priority_order_indices'],[1,3,2,0])
        self.assertEqual(out['priority_order'],['proposal']*4)
        self.assertEqual([v['proposal_revision'] for v in out['recommendations']],['0','1','2','3'])

    def test_capture_day_does_not_rewrite_actual_observation_day(self):
        before=DAY-timedelta(days=10);a,s,row=fixture(day=before)
        value=self.value(a,s,[replace(row,captured_on=DAY)])
        self.assertEqual(value['observed_at'],before.isoformat())
        self.assertEqual(value['as_of'],DAY.isoformat());self.assertEqual(value['captured_on'],DAY.isoformat())
        self.assertEqual(value['effective_score'],50)

    def test_sort_preserves_three_classes_with_known_score_before_unknown_and_stable_id(self):
        a,s,row=fixture(label='低')
        original=a['recommendations'][0]
        a['recommendations'] += [dict(original,proposal_id='a',target='Legacy',priority='中'),
                                 dict(original,proposal_id='z',target='Legacy',priority='高')]
        self.assertEqual(self.project(a,s,[row])['priority_order'],['z','proposal','a'])

    def test_shadow_core_production_guard_remains_unchanged(self):
        from vehicle_priority_assessment import Candidate,Scope,assess_priority,ProductionUseBlocked
        with self.assertRaises(ProductionUseBlocked):
            assess_priority(Candidate('x',Scope('TEST',1,'target')),{}, {},as_of=DAY,mode='production')

if __name__=='__main__':unittest.main()
