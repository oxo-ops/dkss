"""Verified source-only completion, exact display dedupe and retained history."""
from copy import deepcopy
from datetime import timedelta
import json
import unittest

import test_priority_progression_workflow as progression
from dkss_app.priority_confirmed_projection import (
    finalize_confirmed_priority_candidates as finish,
    prepare_held_confirmed_candidates as prepare,
    reconcile_confirmed_candidates_before_save as reconcile,
    DETERMINISTIC_KEY,
)
from dkss_app.priority_consumers import identify_priority_proposals, priority_counts
from dkss_app.priority_projection import project_registered_priorities
from vehicle_priority_inputs import display_target


class CandidateCompletionTests(unittest.TestCase):
    setUpClass = classmethod(progression.ProgressionWorkflowTests.setUpClass.__func__)
    tearDownClass = classmethod(progression.ProgressionWorkflowTests.tearDownClass.__func__)
    setUp = progression.ProgressionWorkflowTests.setUp
    tearDown = progression.ProgressionWorkflowTests.tearDown
    login = progression.ProgressionWorkflowTests.login
    request = progression.ProgressionWorkflowTests.request
    save = progression.ProgressionWorkflowTests.save
    complete = progression.ProgressionWorkflowTests.complete
    state = progression.ProgressionWorkflowTests.state
    decision_data = progression.ProgressionWorkflowTests.decision_data
    decide = progression.ProgressionWorkflowTests.decide
    snapshot = progression.ProgressionWorkflowTests.snapshot
    refs = progression.ProgressionWorkflowTests.refs
    clock = progression.ProgressionWorkflowTests.clock
    begin = progression.ProgressionWorkflowTests.begin
    repair = progression.ProgressionWorkflowTests.repair
    prepare_pair = progression.ProgressionWorkflowTests.prepare_pair
    confirm = progression.ProgressionWorkflowTests.confirm

    def load(self):
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        with self.app.test_request_context('/'):
            return get_vehicle_karte_analysis_job_data(self.vehicle)

    def view(self, result, sources):
        return project_registered_priorities(identify_priority_proposals(result), self.vehicle, sources, as_of=self.day)

    def cancel(self, event_id):
        self.login('admin')
        history = self.client.get(self.url, query_string={'kind': 'progression'}).json['history']
        token = next(value['cancel_token'] for value in history if value['event_id'] == event_id)
        response = self.client.post(self.url, json={'token': token})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def ordinary(self, payload):
        offer = next(value for row in payload['records'] for value in row.get('priority_inputs', []) if value['ref'] == self.current_ref)
        return dict(priority='中', category='整備・点検', target=display_target(offer['target']), title='元の指摘を確認',
            action='実車の状態を担当者が確認', current_state='登録された未解消指摘',
            priority_input_ref=offer['ref'], source_ids=offer['source_ids'])

    def change_original(self):
        value = self.state()
        value['defects'][-1]['reported_at_iso'] = '2001-01-01T00:00:00+09:00'
        self.row.operation_judgment_json = json.dumps(value); self.db.session.commit()

    def test_ai_empty_and_unrelated_output_never_hide_verified_fact_and_are_idempotent(self):
        self.prepare_pair(); self.confirm(); payload, sources = self.load()
        for items in ([], [dict(priority='低', category='記録確認', target='別の記録', title='別の照合', action='照合', source_ids=['vehicle:1'])]):
            original = {'overview': '合成AI結果', 'recommendations': deepcopy(items), 'priority_summary': {'proposal_count': 999}}
            before, input_before = deepcopy(original), deepcopy(payload)
            result = finish(original, payload)
            self.assertEqual(original, before); self.assertEqual(payload, input_before)
            self.assertEqual(len(result['recommendations']), len(items) + 1)
            self.assertNotIn('priority_summary', result)
            self.assertEqual(finish(result, payload), result)
            item = self.view(result, sources)['recommendations'][-1]
            self.assertEqual(item['priority_assessment']['effective_score'], 65)

    def test_same_observation_dedupe_preserves_saved_original_other_action_and_cancel_restore(self):
        self.prepare_pair(); event_id, _ = self.confirm(); payload, sources = self.load()
        original = self.ordinary(payload)
        other_action = {**original, 'action': '別の具体的な検査を行う', 'title': '別の対処'}
        result = finish({'recommendations': [original, other_action]}, payload)
        self.assertEqual(result['recommendations'][:2], [original, other_action])
        self.assertEqual(len(result['recommendations']), 3)
        identified = identify_priority_proposals(result)
        self.assertNotEqual(identified['recommendations'][0]['proposal_id'], identified['recommendations'][2]['proposal_id'])
        rendered = self.view(result, sources)
        self.assertEqual(len(rendered['recommendations']), 2)
        self.assertEqual(priority_counts(rendered)['proposal_count'], 2)
        self.assertEqual(len(rendered['priority_order_indices']), 2)
        self.assertEqual(len(rendered['priority_deduplicated_proposals']), 1)
        self.assertIn('別の具体的な検査を行う', [item['action'] for item in rendered['recommendations']])
        before = self.row.operation_judgment_json
        self.cancel(event_id)
        rendered = self.view(result, sources)
        self.assertEqual(len(rendered['recommendations']), 2)
        self.assertEqual([v['priority_assessment']['effective_score'] for v in rendered['recommendations']], [50, 50])
        self.assertEqual(self.row.operation_judgment_json, before)
        self.assertEqual(result['recommendations'][:2], [original, other_action])

    def test_repeated_confirmation_one_group_partial_and_all_cancel(self):
        self.prepare_pair(); first, _ = self.confirm(); second, _ = self.confirm(); payload, sources = self.load()
        result = finish({'recommendations': []}, payload)
        self.assertEqual(len(result['recommendations']), 1)
        self.assertEqual(len(result['recommendations'][0]['priority_confirmation_refs']), 2)
        value = self.view(result, sources)['recommendations'][0]['priority_assessment']
        self.assertEqual(value['effective_score'], 65)
        self.assertEqual(len(value['confirmation_details_list']), 2)
        self.cancel(first)
        value = self.view(result, sources)['recommendations'][0]['priority_assessment']
        self.assertEqual(value['effective_score'], 65)
        self.assertEqual(value['confirmation_details']['event_id'], second)
        self.cancel(second)
        self.assertEqual(self.view(result, sources)['recommendations'], [])
        self.assertEqual(self.state()['defects'][-1]['status'], '対応待ち')

    def test_more_than_five_distinct_verified_events_remain_present(self):
        old_day = self.day - timedelta(days=7)
        old = self.begin(old_day)
        self.repair(day=old_day); self.repair(day=old_day, recheck='異常なし', hour=10, minute=30)
        event = self.models.ChecklistEvent.query.filter_by(result_type='vehicle', result_id=self.row.id, event_type='解消').one()
        for offset in range(6):
            ref = self.begin(self.day - timedelta(days=5-offset))
            self.selection = {'current_observation': ref + '|reported', 'baseline_observation': old + f'|event:{event.id}', 'relation': 'recurrent'}
            self.login('admin'); self.confirm()
        payload, sources = self.load()
        result = finish({'recommendations': []}, payload)
        self.assertEqual(len(result['recommendations']), 6)
        rendered = self.view(result, sources)
        self.assertEqual(priority_counts(rendered)['labels'], {'高': 6, '中': 0, '低': 0})
        self.assertEqual(len(rendered['priority_order_indices']), 6)
        self.assertEqual(len({v['proposal_id'] for v in rendered['recommendations']}), 6)

    def test_source_hold_carries_only_actual_previous_saved_class_and_is_stable(self):
        self.prepare_pair(); self.confirm(); old_payload, old_sources = self.load()
        old = finish({'recommendations': []}, old_payload)
        previous = {'analysis': old, 'sources': old_sources, 'generated_at': '2026/11/11 09:00'}
        before = deepcopy(previous)
        self.change_original()
        payload, sources = self.load()
        self.assertNotIn(DETERMINISTIC_KEY, payload)
        self.assertEqual(finish({'recommendations': []}, payload)['recommendations'], [])
        prepare(self.vehicle, payload, sources, previous, as_of=self.day)
        result = reconcile(self.vehicle, {'recommendations': []}, payload, sources, as_of=self.day)
        item = self.view(result, sources)['recommendations'][0]
        self.assertEqual((item['priority_assessment']['label'], item['priority_assessment']['effective_score']), ('高', None))
        self.assertEqual(item['priority_assessment']['previous_result']['confirmed_at'], [old_sources[next(k for k in old_sources if k.startswith('priority_confirmation:'))]['priority_confirmation_proof']['confirmed_at']])
        self.assertEqual(previous, before)
        second_payload, second_sources = self.load()
        prepare(self.vehicle, second_payload, second_sources, {'analysis': result, 'sources': sources, 'generated_at': 'later'}, as_of=self.day)
        second = reconcile(self.vehicle, {'recommendations': []}, second_payload, second_sources, as_of=self.day)
        self.assertEqual(second['recommendations'], result['recommendations'])
        value = self.view(second, second_sources)['recommendations'][0]['priority_assessment']
        self.assertGreater(len(value['historical_confirmation_details'][0]['display_sources']), 1)
        audit = self.models.ChecklistEvent.query.filter_by(result_type='vehicle_priority', event_type='優先度根拠確認').one()
        audit.actor_identity = None; self.db.session.commit()
        value = self.view(second, second_sources)['recommendations'][0]['priority_assessment']
        self.assertEqual((value['label'], value['effective_score']), ('高', None))
        self.assertEqual(value['historical_confirmation_details'][0]['actor_name'], second['recommendations'][0]['priority_historical_confirmations'][0]['actor_name'])

    def test_generation_race_cancel_or_new_source_hold_does_not_invent_saved_result(self):
        self.prepare_pair(); event_id, _ = self.confirm(); payload, sources = self.load()
        result = finish({'recommendations': []}, payload)
        self.cancel(event_id)
        self.assertEqual(reconcile(self.vehicle, result, payload, sources, as_of=self.day)['recommendations'], [])
        self.confirm(); payload, sources = self.load()
        result = finish({'recommendations': []}, payload)
        self.change_original()
        updated = reconcile(self.vehicle, result, payload, sources, as_of=self.day)
        self.assertEqual(updated['recommendations'], [])
        self.assertIn('priority_generation_notice', updated)

    def test_foreign_previous_scope_and_unknown_sources_never_supply_carry(self):
        self.prepare_pair(); self.confirm(); payload, sources = self.load()
        result = finish({'recommendations': []}, payload)
        previous = {'analysis': result, 'sources': sources}
        foreign = self.models.Vehicle.query.filter_by(company_code='B').one()
        new_payload, new_sources = {}, {}
        prepare(foreign, new_payload, new_sources, previous, as_of=self.day)
        self.assertEqual(new_payload['_held_confirmed_priority_candidates'], [])
        self.assertEqual(new_sources, {})

import test_priority_manufacturer_evidence as maker
import test_priority_manufacturer_workflow as maker_workflow


class MixedConfirmationTests(unittest.TestCase):
    setUpClass = classmethod(maker.ManufacturerEvidenceTests.setUpClass.__func__)
    tearDownClass = classmethod(maker.ManufacturerEvidenceTests.tearDownClass.__func__)
    for _name in ('tearDown', 'login', 'request', 'save', 'complete', 'state', 'decision_data',
                  'decide', 'snapshot', 'refs', 'clock', 'begin', 'repair', 'confirm', 'load', 'view', 'cancel'):
        locals()[_name] = getattr(CandidateCompletionTests, _name)
    begin_priority = maker.ManufacturerEvidenceTests.begin_priority
    repair_priority = maker.ManufacturerEvidenceTests.repair_priority
    recheck = maker.ManufacturerEvidenceTests.recheck
    use_original_instruction_only = maker.ManufacturerEvidenceTests.use_original_instruction_only

    def setUp(self):
        maker.ManufacturerEvidenceTests.setUp(self)
        self.url = f'/vehicle/karte/{self.vehicle.id}/priority-confirmations'
        self.fields = [v for v in json.loads(self.checklist.items_json) if v['item_type'] == 'check']

    def test_same_observation_manufacturer_and_progression_keep_both_facts_and_partial_cancel(self):
        current_row, maker_selection = self.row, deepcopy(self.selection)
        self.login('admin')
        prepared = maker_workflow.ManufacturerConfirmationWorkflowTests.prepare(self)
        maker_id, _ = maker_workflow.ManufacturerConfirmationWorkflowTests.confirm(self, prepared)
        old_day = self.day - timedelta(days=1)
        old = self.begin(old_day)
        self.repair(day=old_day); self.repair(day=old_day, recheck='異常なし', hour=10, minute=30)
        event = self.models.ChecklistEvent.query.filter_by(result_type='vehicle', result_id=self.row.id, event_type='解消').one()
        self.row = current_row
        self.selection = {'current_observation': maker_selection['observation_input_ref'] + '|reported',
            'baseline_observation': old + f'|event:{event.id}', 'relation': 'recurrent'}
        self.login('admin'); progression_id, _ = self.confirm()
        payload, sources = self.load()
        result = finish({'recommendations': []}, payload)
        self.assertEqual(len(result['recommendations']), 1)
        value = self.view(result, sources)['recommendations'][0]['priority_assessment']
        self.assertEqual(value['effective_score'], 65)
        self.assertEqual([v['points'] for v in value['factors']], [40, None, 25])
        self.assertIn('manufacturer_immediate_condition', [v['code'] for v in value['applied_floors']])
        self.assertEqual({v['event_id'] for v in value['confirmation_details_list']}, {maker_id, progression_id})
        previous = {'analysis': deepcopy(result), 'sources': deepcopy(sources), 'generated_at': '2026/11/11 09:00'}
        self.public.available = False; self.db.session.commit()
        new_payload, new_sources = self.load()
        prepare(self.vehicle, new_payload, new_sources, previous, as_of=self.day)
        carried = reconcile(self.vehicle, {'recommendations': []}, new_payload, new_sources, as_of=self.day)
        self.assertEqual(len(carried['recommendations']), 1)
        held = self.view(carried, new_sources)['recommendations'][0]['priority_assessment']
        self.assertEqual((held['label'], held['effective_score']), ('高', None))
        self.assertEqual(len(held['historical_confirmation_details']), 2)
        self.public.available = True; self.db.session.commit()
        self.cancel(progression_id)
        value = self.view(result, sources)['recommendations'][0]['priority_assessment']
        self.assertEqual(value['effective_score'], 60)
        self.assertEqual(value['confirmation_details']['event_id'], maker_id)
        self.cancel(maker_id)
        self.assertEqual(self.view(result, sources)['recommendations'], [])
        self.assertEqual(self.state()['defects'][0]['status'], '対応待ち')

if __name__ == '__main__': unittest.main()

