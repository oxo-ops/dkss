"""Synthetic ordinary observation -> optional confirmation -> common consumer.

Original HTTP repair/recheck records are used. No provider/core/auth mocks; the
clock alone is controlled to distinguish same-day observations precisely.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_priority_common_workflow as common
import test_priority_observation_sources as observation
import test_vehicle_priority_assessment as core
from dkss_app.priority_progression import options, preview, progression_confirmation_inputs
from dkss_app.priority_confirmations import confirmation_statuses
from dkss_app.priority_projection import project_registered_priorities
from vehicle_priority_inputs import display_target, validate_priority_input


class ProgressionCoreOrderTests(unittest.TestCase):
    def test_same_day_order_is_opt_in_and_never_allows_future_or_reverse_dates(self):
        base = core.fact('state_recurrent', baseline_source_ids=('old',), comparison_verified=True)
        self.assertFalse(base.comparison_order_verified)
        sources = {'s1': core.source(), 'old': core.source('old', event_id='old', status='resolved')}
        for enabled, delta, expected in [(False, 0, 0), (True, 0, 25), (True, 1, 0), (False, -1, 25)]:
            with self.subTest(enabled=enabled, delta=delta):
                sources['old'] = replace(sources['old'], observed_on=core.DAY + timedelta(days=delta))
                result = core.evaluate(core.candidate(replace(base, comparison_order_verified=enabled)), sources)
                self.assertEqual(result['base_score'], expected)
        # Both dates may be valid historical dates: the flag still cannot
        # turn a later baseline into an earlier observation.
        reversed_sources = {'s1': core.source(observed_on=core.DAY - timedelta(days=1)),
            'old': core.source('old', event_id='old', status='resolved')}
        self.assertEqual(core.evaluate(core.candidate(replace(base, comparison_order_verified=True)), reversed_sources)['base_score'], 0)
        with self.assertRaises(core.InvalidInput):
            core.evaluate(core.candidate(replace(base, comparison_order_verified='true')), sources)


class ProgressionWorkflowTests(unittest.TestCase):
    setUpClass = classmethod(common.CommonPriorityWorkflowTests.setUpClass.__func__)
    tearDownClass = classmethod(common.CommonPriorityWorkflowTests.tearDownClass.__func__)
    tearDown = common.CommonPriorityWorkflowTests.tearDown
    login = common.CommonPriorityWorkflowTests.login
    request = common.CommonPriorityWorkflowTests.request
    save = common.CommonPriorityWorkflowTests.save
    complete = common.CommonPriorityWorkflowTests.complete
    state = common.CommonPriorityWorkflowTests.state
    decision_data = common.CommonPriorityWorkflowTests.decision_data
    decide = common.CommonPriorityWorkflowTests.decide
    snapshot = common.CommonPriorityWorkflowTests.snapshot
    refs = observation.PriorityObservationSourceTests.refs

    def setUp(self):
        common.CommonPriorityWorkflowTests.setUp(self)
        self.day = datetime.now(ZoneInfo('Asia/Tokyo')).date()
        self.vehicle = self.models.Vehicle.query.filter_by(company_code='A').one()
        self.login('checker'); self.request('GET', '/vehicle/checklists')
        self.checklist = self.models.Checklist.query.filter_by(company_code='A').one()
        self.fields = [v for v in json.loads(self.checklist.items_json) if v['item_type'] == 'check']
        self.url = f'/vehicle/karte/{self.vehicle.id}/priority-confirmations'

    def clock(self, day, hour=12, minute=0):
        return patch('dkss_app.checklist_common.get_user_local_now',
            return_value=datetime.combine(day, datetime.min.time(), ZoneInfo('Asia/Tokyo')).replace(hour=hour, minute=minute))

    def begin(self, day, code='daily_02', hour=9, finalize=True):
        self.login('checker')
        self.form = {'vehicle_record_id': self.vehicle.id, 'year': str(day.year), 'month': str(day.month), 'day': str(day.day)}
        number = next(i for i, v in enumerate(self.fields) if v['item_code'] == code)
        with self.clock(day, hour):
            for no in range(len(self.fields)):
                self.save(no, '×' if no == number else '✓')
            self.row = self.models.VehicleChecklistResult.query.filter_by(company_code='A', day=str(day.day).zfill(2), month=str(day.month).zfill(2), year=str(day.year)).one()
            if finalize:
                self.complete(); self.decide('運行可')
        return self.refs()[0]

    def repair(self, number=1, recheck=None, day=None, hour=10, minute=0, precise=True):
        day = day or self.day
        self.login('reviewer')
        data = {'judgment_version': str(self.state()['version']), 'repair_status': '再確認待ち',
            'repair_note': '合成例：左側同じ位置を整備後に再確認。' if recheck else '合成例：左側同じ部位を整備。'}
        if recheck: data['recheck_result'] = recheck
        data['repair_performed_at' if precise else 'repair_performed_date'] = (
            f'{day.isoformat()}T{hour:02}:{minute:02}' if precise else day.isoformat())
        with self.clock(day, hour, minute):
            response = self.request('POST', f'/vehicle/checklist-results/{self.row.id}/defects/{number}/repair', data=data)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))

    def prepare_pair(self, *, same_day=False, precise=True, relation='recurrent', code='daily_02'):
        old_day = self.day - timedelta(days=1)
        old = self.begin(old_day, code, finalize=not same_day)
        self.repair(day=old_day, precise=precise)
        self.repair(recheck='異常なし', day=old_day, hour=10, minute=30, precise=precise)
        old_row = self.row
        event = self.models.ChecklistEvent.query.filter_by(result_type='vehicle', result_id=old_row.id, event_type='解消').one()
        if same_day:
            self.login('admin')
            no = next(i for i, v in enumerate(self.fields) if v['item_code'] == code)
            with self.clock(old_day, 12):
                response = self.request('POST', f'/vehicle/checklists/{self.checklist.id}/save-detail',
                    data={**self.form, 'item_no': str(no), 'comment': '同じ左側位置の別観測。再度の症状。'})
                self.assertEqual(response.status_code, 302)
                self.complete(); self.decide('運行可')
            current = self.refs()[-1]
        else:
            current = self.begin(self.day, code)
        self.current_ref, self.old_ref, self.old_row = current, old, old_row
        self.selection = {'current_observation': current + '|reported',
            'baseline_observation': old + f'|event:{event.id}', 'relation': relation}
        self.login('admin')
        return self.selection

    def confirm(self):
        response = self.client.post(self.url + '/preview', json={'kind': 'progression', 'selection': self.selection})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        prepared = response.json
        response = self.client.post(self.url, json={'token': prepared['token'],
            'statements': [v['key'] for v in prepared['preview']['statements']]})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.json['event_id'], prepared

    def generate(self):
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        with self.app.test_request_context('/'):
            payload, sources = get_vehicle_karte_analysis_job_data(self.vehicle)
        offers = [v for r in payload['records'] for v in r.get('priority_inputs', []) if v['kind'] == 'confirmed_priority']
        self.assertEqual(len(offers), 1)
        offered = offers[0]
        item = dict(priority='低', category='整備・点検', target=display_target(offered['target']),
            title='確認した元観測に基づく対応', current_state='元記録の比較', action='担当者が確認・対応',
            source_ids=offered['source_ids'], priority_input_ref=offered['ref'], proposal_id='same-id', proposal_revision='revision-one')
        validate_priority_input(item, payload)
        analysis = {'recommendations': [item]}
        return analysis, sources, payload

    def test_distinct_day_real_confirmation_scores_65_and_normal_get_preserves_storage(self):
        self.prepare_pair(); event_id, _ = self.confirm()
        analysis, sources, payload = self.generate()
        self.assertEqual(analysis['recommendations'][0]['priority'], '高')
        bundle = {'analysis': analysis, 'sources': sources, 'fingerprints': payload['_fingerprints']}
        state = self.models.VehicleKarteAnalysis(company_code='A', vehicle_record_id=self.vehicle.id,
            status='completed', result_json=json.dumps(bundle, ensure_ascii=False))
        self.db.session.add(state); self.db.session.commit()
        original, before = state.result_json, self.snapshot()
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/analysis/result')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        value = response.json['analysis']['recommendations'][0]['priority_assessment']
        self.assertEqual((value['label'], value['effective_score']), ('高', 65))
        self.assertEqual([v['points'] for v in value['factors']], [40, None, 25])
        self.assertEqual(value['confirmation_details']['event_id'], event_id)
        self.assertEqual(self.snapshot(), before); self.assertEqual(state.result_json, original)
        self.assertEqual(self.state()['status'], '運行可')
        item = response.json['analysis']['recommendations'][0]
        previous_hash = payload['_fingerprints']['important_hash']
        changed = json.loads(self.row.operation_judgment_json)
        changed['defects'][-1]['reported_at_iso'] = '2001-01-01T00:00:00+09:00'
        self.row.operation_judgment_json = json.dumps(changed); self.db.session.commit()
        result = self.client.get(f'/vehicle/karte/{self.vehicle.id}/analysis/result').json
        self.assertFalse(result['is_current'])
        self.assertEqual(result['analysis']['recommendations'][0]['priority_assessment']['effective_score'], None)
        answer = {'status': 'accepted', 'proposal_id': item['proposal_id'], 'proposal_revision': item['proposal_revision']}
        self.assertEqual(self.client.post(f'/vehicle/karte/{self.vehicle.id}/analysis/feedback', json=answer).status_code, 409)
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        with self.app.test_request_context('/'):
            payload, _ = get_vehicle_karte_analysis_job_data(self.vehicle)
        self.assertNotEqual(previous_hash, payload['_fingerprints']['important_hash'])
        self.assertEqual(state.result_json, original)

    def test_worsening_unknown_impact_is_medium_25_not_fabricated_safety_impact(self):
        old = self.begin(self.day - timedelta(days=1), 'daily_04')
        current = self.begin(self.day, 'daily_04')
        self.selection = {'current_observation': current + '|reported',
            'baseline_observation': old + '|reported', 'relation': 'worsening'}
        self.login('admin'); self.confirm()
        analysis, sources, _ = self.generate()
        value = project_registered_priorities(analysis, self.vehicle, sources, as_of=self.day)['recommendations'][0]['priority_assessment']
        self.assertEqual((value['label'], value['effective_score']), ('中', 25))
        self.assertEqual([v['points'] for v in value['factors']], [None, None, 25])

    def test_reverse_order_different_item_and_forged_order_flag_cannot_supply_relation(self):
        self.prepare_pair(same_day=True)
        original = deepcopy(self.selection)
        self.selection.update(current_observation=original['baseline_observation'], baseline_observation=original['current_observation'])
        with self.assertRaises(ValueError): preview(self.vehicle, self.selection, as_of=self.day)
        self.selection = {**original, 'comparison_order_verified': 'true'}
        with self.assertRaises(ValueError): preview(self.vehicle, self.selection, as_of=self.day)
        self.selection = original
        value = preview(self.vehicle, self.selection, as_of=self.day)
        original_json = self.row.operation_judgment_json
        changed = json.loads(original_json)
        changed['defects'][-1]['reported_at'] = changed['defects'][-1]['reported_at'][:11] + '08:00:00'
        changed['defects'][-1]['reported_at_iso'] = changed['defects'][-1]['reported_at_iso'][:11] + '08:00:00+09:00'
        self.row.operation_judgment_json = json.dumps(changed); self.db.session.commit()
        # The exact original reference no longer identifies the altered report.
        with self.assertRaises(ValueError): preview(self.vehicle, original, as_of=self.day)
        self.row.operation_judgment_json = original_json; self.db.session.commit()
        current = self.begin(self.day, 'daily_04')
        self.selection = {**original, 'current_observation': current + '|reported'}
        with self.assertRaisesRegex(ValueError, '対象項目'):
            preview(self.vehicle, self.selection, as_of=self.day)

    def test_periodic_generation_accepts_only_server_offered_confirmation_citations(self):
        from vehicle_periodic_followups import generate_periodic_proposals
        self.prepare_pair(); self.confirm(); analysis, sources, payload = self.generate()
        with patch('vehicle_karte_analysis_ai.analyze_vehicle_karte', return_value=analysis):
            result = generate_periodic_proposals(payload)
        self.assertEqual(result, analysis)
        forged = deepcopy(analysis)
        forged['recommendations'][0]['source_ids'].append('inspection:foreign:unoffered')
        with patch('vehicle_karte_analysis_ai.analyze_vehicle_karte', return_value=forged):
            with self.assertRaisesRegex(ValueError, 'INVALID_PROPOSAL_EVIDENCE'):
                generate_periodic_proposals(payload)

    def test_same_day_real_original_timestamps_and_fixed_relation_allow_65(self):
        self.prepare_pair(same_day=True)
        value = preview(self.vehicle, self.selection, as_of=self.day)
        self.assertTrue(value['sources']['comparison_order_verified'])
        self.confirm(); analysis, sources, _ = self.generate()
        projected = project_registered_priorities(analysis, self.vehicle, sources, as_of=self.day)
        self.assertEqual(projected['recommendations'][0]['priority_assessment']['effective_score'], 65)

    def test_same_day_date_only_recheck_cannot_supply_order(self):
        self.prepare_pair(same_day=True, precise=False)
        with self.assertRaisesRegex(ValueError, '前後関係'):
            preview(self.vehicle, self.selection, as_of=self.day)

    def test_missing_relation_statement_duplicate_and_source_change_are_not_confirmation(self):
        self.prepare_pair()
        response = self.client.post(self.url + '/preview', json={'kind': 'progression', 'selection': self.selection})
        self.assertEqual(response.status_code, 200)
        prepared = response.json
        response = self.client.post(self.url, json={'token': prepared['token'], 'statements': ['current_open_observation', 'same_symptom_position']})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(confirmation_statuses(self.vehicle, as_of=self.day), [])
        event_id, prepared = self.confirm()
        response = self.client.post(self.url, json={'token': prepared['token'], 'statements': [v['key'] for v in prepared['preview']['statements']]})
        self.assertEqual(response.status_code, 409)
        analysis, sources, _ = self.generate()
        state = json.loads(self.row.operation_judgment_json); state['defects'][-1]['reported_at_iso'] = '2001-01-01T00:00:00+09:00'
        self.row.operation_judgment_json = json.dumps(state); self.db.session.commit()
        self.assertEqual(confirmation_statuses(self.vehicle, as_of=self.day)[0]['status'], 'held')
        value = project_registered_priorities(analysis, self.vehicle, sources, as_of=self.day)['recommendations'][0]['priority_assessment']
        self.assertEqual((value['label'], value['effective_score']), ('高', None))

    def test_explicit_cancel_suppresses_only_confirmation_not_original_open_issue(self):
        self.prepare_pair(); event_id, _ = self.confirm()
        analysis, sources, _ = self.generate()
        original = deepcopy(analysis['recommendations'][0]); original.update(priority_input_ref=self.current_ref,
            source_ids=[f'inspection:{self.row.id}'], priority='中', title='元の未解消指摘', proposal_revision='revision-two')
        analysis['recommendations'].append(original)
        before = self.row.operation_judgment_json
        history = self.client.get(self.url, query_string={'kind': 'progression'}).json['history']
        token = next(v['cancel_token'] for v in history if v['event_id'] == event_id)
        response = self.client.post(self.url, json={'token': token}); self.assertEqual(response.status_code, 200)
        projected = project_registered_priorities(analysis, self.vehicle, sources, as_of=self.day)
        self.assertEqual(len(projected['recommendations']), 1)
        remaining = projected['recommendations'][0]
        self.assertEqual((remaining['proposal_id'], remaining['proposal_revision']), ('same-id', 'revision-two'))
        self.assertEqual(remaining['priority_assessment']['effective_score'], 50)
        self.assertEqual(self.row.operation_judgment_json, before)

    def test_verified_resolution_suppresses_only_confirmed_offer_not_missing_chain(self):
        self.prepare_pair(); self.confirm(); analysis, sources, _ = self.generate()
        self.repair(); self.repair(recheck='異常なし', hour=10, minute=30)
        statuses = confirmation_statuses(self.vehicle, as_of=self.day)
        self.assertEqual(statuses[0]['status'], 'resolved')
        self.assertEqual(project_registered_priorities(analysis, self.vehicle, sources, as_of=self.day)['recommendations'], [])
        self.models.ChecklistEvent.query.filter_by(result_id=self.row.id, result_type='vehicle', event_type='解消').delete(); self.db.session.commit()
        self.assertEqual(confirmation_statuses(self.vehicle, as_of=self.day)[0]['status'], 'held')
        self.assertEqual(len(project_registered_priorities(analysis, self.vehicle, sources, as_of=self.day)['recommendations']), 1)

    def test_no_confirmation_no_backfill_and_exact_scope_target_guards(self):
        self.prepare_pair()
        value = options(self.vehicle, as_of=self.day)
        self.assertGreater(len(value['fields'][0]['options']), 0)
        self.assertEqual(confirmation_statuses(self.vehicle, as_of=self.day), [])
        self.confirm(); analysis, sources, _ = self.generate()
        for changed in ('no-proof', 'target', 'cross-company'):
            with self.subTest(changed=changed):
                items, proof = deepcopy(analysis), deepcopy(sources)
                vehicle = self.vehicle
                if changed == 'no-proof': proof = {}
                elif changed == 'target': items['recommendations'][0]['target'] = 'エアコン'
                else: vehicle = self.models.Vehicle.query.filter_by(company_code='B').one()
                result = project_registered_priorities(items, vehicle, proof, as_of=self.day)
                self.assertIsNone(result['recommendations'][0]['priority_assessment']['effective_score'])

if __name__ == '__main__': unittest.main()
