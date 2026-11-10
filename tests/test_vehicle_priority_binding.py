"""Explicit binding contracts using only synthetic snapshots, no database."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import unittest

from vehicle_priority_assessment import InvalidInput
from vehicle_priority_binding import (
    DefectBindingSet, ExplicitDefectBinding, build_bound_defect_projection, projection_snapshot_hash,
)
from vehicle_priority_sources import DefectRecord, DefectSnapshot, assess_registered_defects


class DefectProposalBindingTests(unittest.TestCase):
    day = date(2026, 11, 10)

    def case(self, count=1):
        # Use the existing host's identity algorithm, not new invented IDs.
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        records, items, sources, bindings = [], [], {}, []
        for index in range(1, count + 1):
            source_id = f'defect:{index}'
            record = DefectRecord(index, 'TEST', 7, '2026-11-01', '合成の指摘', '未対応', None)
            proposal = dict(target=f'合成部位{index}', category='点検', source_ids=[source_id],
                            priority='高', risk_status='unassessed', risk='元の記述',
                            action='合成確認', reason='合成の根拠')
            key, revision = vehicle_analysis_proposal_ids(proposal)
            items.append(dict(proposal, proposal_id=key, proposal_revision=revision,
                              feedback={'status':'確認中','comment':'元の回答を保持'}, evaluation={'verdict':'useful'}))
            records.append(record)
            sources[source_id] = {'label':'元のラベルを読んで状態は推測しない', 'url':'/synthetic/source'}
            bindings.append(ExplicitDefectBinding(key, revision, proposal['target'], source_id, True))
        snapshot = DefectSnapshot('TEST', 7, self.day, tuple(records))
        analysis = {'overview':'合成概要','recommendations':items,'feedback_history':[{'keep':'original'}]}
        binding_set = DefectBindingSet('TEST', 7, self.day, projection_snapshot_hash(analysis),
                                      projection_snapshot_hash(sources),
                                      assess_registered_defects(snapshot,as_of=self.day)['snapshot_fingerprint'], tuple(bindings))
        return analysis, sources, snapshot, binding_set

    def run_case(self, case):
        before=deepcopy(case)
        result=build_bound_defect_projection(*case,as_of=self.day)
        self.assertEqual(case,before)
        return result

    def rehash_records(self, case, snapshot):
        a,s,_,b=case
        return a,s,snapshot,replace(b,records_fingerprint=assess_registered_defects(snapshot,as_of=self.day)['snapshot_fingerprint'])

    def test_exact_host_identity_binding_keeps_original_saved_fields(self):
        case=self.case(2)
        output=self.run_case(case)
        self.assertEqual(output['feedback_history'],case[0]['feedback_history'])
        for before,after in zip(case[0]['recommendations'],output['recommendations']):
            self.assertEqual({k:v for k,v in after.items() if k!='priority_preview'},before)
            self.assertEqual(after['priority'],'高')
            self.assertEqual(after['priority_preview']['label'],'低')
            self.assertEqual(after['priority_preview']['base_score'],10)
            self.assertEqual(after['priority_preview']['scope']['target'],before['target'])
            self.assertEqual(after['priority_preview']['source_ids'],before['source_ids'])
            self.assertIn('入力の最新性を確認要。記録の古さだけで指摘や停止指示を解除しません',after['priority_preview']['missing_conditions'])
        self.assertFalse(output['priority_binding']['production_enabled'])
        self.assertEqual([x['proposal_id'] for x in output['recommendations']],
                         [x['proposal_id'] for x in case[0]['recommendations']])

    def test_citations_and_equal_target_do_not_establish_correspondence(self):
        a,s,r,b=self.case()
        for verified in (False,None,1,'true'):
            invalid=replace(b,entries=(replace(b.entries[0],correspondence_verified=verified),))
            with self.assertRaises(InvalidInput):self.run_case((a,s,r,invalid))

    def test_changed_analysis_sources_or_record_reject_stale_binding(self):
        for source in ('analysis','sources','records'):
            a,s,r,b=self.case()
            if source=='analysis':a['recommendations'][0]['action']='changed'
            elif source=='sources':s['defect:1']['label']='changed'
            else:r=replace(r,records=(replace(r.records[0],registered_status='対応中'),))
            with self.assertRaises(InvalidInput):self.run_case((a,s,r,b))

    def test_revision_and_target_must_match_even_when_overall_hash_is_updated(self):
        for field in ('proposal_revision','target','proposal_id'):
            a,s,r,b=self.case()
            a['recommendations'][0][field]='changed'
            b=replace(b,analysis_fingerprint=projection_snapshot_hash(a))
            with self.assertRaises(InvalidInput):self.run_case((a,s,r,b))

    def test_missing_duplicate_and_foreign_proposals_are_not_low_fallbacks(self):
        a,s,r,b=self.case(2)
        for entries in (b.entries[:1], b.entries+b.entries[:1],
                        (replace(b.entries[0],proposal_id='other'),b.entries[1])):
            with self.assertRaises(InvalidInput):self.run_case((a,s,r,replace(b,entries=entries)))

    def test_one_record_cannot_be_silently_bound_to_two_different_targets(self):
        a,s,r,b=self.case(2)
        a['recommendations'][1]['source_ids']=['defect:1']
        b=replace(b,analysis_fingerprint=projection_snapshot_hash(a),
                  entries=(b.entries[0],replace(b.entries[1],source_id='defect:1')))
        with self.assertRaises(InvalidInput):self.run_case((a,s,r,b))

    def test_exact_company_vehicle_and_capture_date_are_required(self):
        a,s,r,b=self.case()
        for change in ({'company_code':'OTHER'},{'vehicle_id':8},{'vehicle_id':True},
                       {'captured_on':self.day-timedelta(days=1)},{'entries':list(b.entries)}):
            with self.assertRaises(InvalidInput):self.run_case((a,s,r,replace(b,**change)))
        with self.assertRaises(InvalidInput):
            build_bound_defect_projection(a,s,r,b,as_of=self.day-timedelta(days=1))

    def test_selected_record_needs_membership_in_both_original_citations_and_source_map(self):
        for location in ('citations','sources','source_type'):
            a,s,r,b=self.case()
            if location=='citations':a['recommendations'][0]['source_ids']=[]
            elif location=='sources':s.clear()
            else:s['defect:1']='not structured'
            b=replace(b,analysis_fingerprint=projection_snapshot_hash(a),sources_fingerprint=projection_snapshot_hash(s))
            with self.assertRaises(InvalidInput):self.run_case((a,s,r,b))

    def test_repaired_record_is_not_resurrected_as_open_proposal(self):
        case=self.case();r=replace(case[2],records=(replace(case[2].records[0],registered_status='修理完了'),))
        with self.assertRaises(InvalidInput):self.run_case(self.rehash_records(case,r))

    def test_conflicting_repair_complete_is_also_blocked_from_proposal_binding(self):
        for changes in ({'repair_date':'2026-11-11'}, {'occurred_date':'2026-11-11'},
                        {'repair_date':'2026-10-31'}):
            case=self.case()
            record=replace(case[2].records[0],registered_status='修理完了',**changes)
            r=replace(case[2],records=(record,))
            with self.assertRaises(InvalidInput):self.run_case(self.rehash_records(case,r))

    def test_unknown_state_does_not_get_invented_facts(self):
        case=self.case();r=replace(case[2],records=(replace(case[2].records[0],registered_status=None),))
        output=self.run_case(self.rehash_records(case,r))
        assessment=output['recommendations'][0]['priority_preview']
        self.assertEqual(assessment['label'],'低')
        self.assertEqual(assessment['base_score'],0)
        self.assertEqual([f['points'] for f in assessment['factors']],[None,None,None])
        self.assertIn('現在の登録状態を確認要',assessment['missing_conditions'])
        self.assertFalse(assessment['safety_cleared'])

    def test_prior_projection_cannot_replace_original_revision_input(self):
        a,s,r,b=self.case();out=self.run_case((a,s,r,b))
        b=replace(b,analysis_fingerprint=projection_snapshot_hash(out))
        with self.assertRaises(InvalidInput):self.run_case((out,s,r,b))

    def test_json_digest_rejects_nonfinite_or_nonjson_data(self):
        for value in ({'x':float('nan')},{'x':float('inf')},{'x':{1:'key'}},{'x':date.today()},{'x':(1,2)}):
            with self.assertRaises(InvalidInput):projection_snapshot_hash(value)
        self.assertNotEqual(projection_snapshot_hash({'x':'1'}),projection_snapshot_hash({'x':1}))

    def test_repeat_is_deterministic_and_empty_is_no_records_not_zero_risk(self):
        case=self.case(2)
        self.assertEqual(self.run_case(case),self.run_case(case))
        output=self.run_case(self.case(0))
        self.assertEqual(output['recommendations'],[])
        self.assertEqual(output['priority_preview_order'],[])
        self.assertNotIn('priority',output)


if __name__=='__main__':unittest.main()
