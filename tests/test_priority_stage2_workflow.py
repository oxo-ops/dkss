"""Existing human HTTP input -> explicit normal generation ref -> ordinary GET.

No extra input UI, no live DB/AI, and no operation decision by the assessment.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_priority_common_workflow as common_workflow
from vehicle_priority_inputs import inspection_inputs, validate_priority_input, display_target


class PriorityStage2WorkflowTests(common_workflow.CommonPriorityWorkflowTests):
    # Reuse fixture helpers, not the already collected first-stage test.
    test_http_standard_answers_complete_and_review_drive_normal_score_50 = None
    def begin_priority(self, code='daily_02'):
        self.login('checker')
        self.request('GET', '/vehicle/checklists')
        self.checklist = self.models.Checklist.query.filter_by(company_code='A').one()
        fields = json.loads(self.checklist.items_json)
        checks = [v for v in fields if v['item_type'] == 'check']
        number = next(i for i, value in enumerate(checks) if value.get('item_code') == code)
        self.check_count = len(checks)
        self.day = datetime.now(ZoneInfo('Asia/Tokyo')).date()
        self.vehicle = self.models.Vehicle.query.filter_by(company_code='A').one()
        self.form = {'vehicle_record_id': self.vehicle.id, 'year': str(self.day.year),
                     'month': str(self.day.month), 'day': str(self.day.day)}
        for no in range(self.check_count):
            self.save(no, '×' if no == number else '✓')
        self.row = self.models.VehicleChecklistResult.query.one()
        self.complete()

    def generate(self, kind='inspection_defect', label='低'):
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        with self.app.test_request_context('/'):
            payload, sources = get_vehicle_karte_analysis_job_data(self.vehicle)
        record = next(v for v in payload['records'] if v['source_id'] == f'inspection:{self.row.id}')
        offered = next(v for v in record['priority_inputs'] if v['kind'] == kind)
        proposal = dict(priority=label, category='整備・点検', target=display_target(offered['target']),
            title='登録された確認・対応', current_state='登録された指摘', action='実車と記録を確認',
            source_ids=offered['source_ids'], priority_input_ref=offered['ref'])
        validate_priority_input(proposal, payload)
        bundle = dict(analysis={'recommendations': [proposal]}, sources=sources,
                      fingerprints=payload['_fingerprints'])
        state = self.models.VehicleKarteAnalysis(company_code='A', vehicle_record_id=self.vehicle.id,
            status='completed', result_json=json.dumps(bundle, ensure_ascii=False))
        self.db.session.add(state); self.db.session.commit()
        return bundle, state

    def get_priority(self, bundle):
        before = self.snapshot()
        with patch('dkss_app.analysis.get_vehicle_analysis_read_projection', return_value=(
                {'fingerprints': bundle['fingerprints'], 'input_summary': {}, 'comparison': None}, True)):
            response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/analysis/result')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.snapshot(), before)
        return response.json['analysis']['recommendations'][0]['priority_assessment']

    def repair_priority(self):
        self.login('reviewer')
        response = self.request('POST', f'/vehicle/checklist-results/{self.row.id}/defects/1/repair', data={
            'judgment_version': str(self.state()['version']), 'repair_status': '再確認待ち',
            'repair_note': '合成試験。制動装置を整備し、再確認待ちとして登録',
            'repair_performed_date': self.day.isoformat()})
        self.assertEqual(response.status_code, 302)

    def test_exact_explicit_reference_works_with_short_display_target(self):
        self.begin_priority()
        self.decide('運行可')
        bundle, state = self.generate()
        value = self.get_priority(bundle)
        self.assertEqual((value['label'], value['effective_score']), ('中', 50))
        original = state.result_json
        self.get_priority(bundle)
        self.assertEqual(state.result_json, original)

    def test_existing_repair_http_produces_medium_25_with_all_axes_unknown(self):
        self.begin_priority()
        self.decide('運行可')
        self.repair_priority()
        bundle, _ = self.generate()
        value = self.get_priority(bundle)
        self.assertEqual((value['label'], value['base_score'], value['effective_score']), ('中', 0, 25))
        self.assertEqual([v['points'] for v in value['factors']], [None, None, None])
        self.assertEqual(value['applied_floors'][0]['code'], 'required_safety_check_not_done')
        self.assertTrue(any('登録上' in v for v in value['missing_conditions']))
        self.assertEqual(self.state()['status'], '未判定')

    def test_prior_stop_then_repair_does_not_turn_into_medium_25(self):
        self.begin_priority()
        self.decide('運行不可')
        self.repair_priority()
        bundle, _ = self.generate(label='高')
        value = self.get_priority(bundle)
        self.assertEqual(value['label'], '高')
        self.assertIsNone(value['effective_score'])

    def test_existing_whole_vehicle_instruction_computes_60_and_preserves_it_when_unknown(self):
        self.begin_priority()
        self.decide('運行不可')
        original_judgment = self.row.operation_judgment_json
        bundle, state = self.generate('registered_operation_instruction', label='低')
        self.assertEqual(bundle['analysis']['recommendations'][0]['priority'], '高')
        value = self.get_priority(bundle)
        self.assertEqual((value['label'], value['base_score'], value['effective_score']), ('高', 0, 60))
        self.assertEqual(value['instruction_details']['scope'], 'whole_vehicle')
        self.assertEqual(value['instruction_details']['recorded_status'], '運行不可')
        self.assertEqual(self.row.operation_judgment_json, original_judgment)
        # Other current vehicle evidence changed: never fall back to AI low.
        other = self.models.VehicleChecklistResult(company_code='A', vehicle_record_id=self.vehicle.id,
            checklist_id=self.checklist.id, year=str(self.day.year), month=str(self.day.month),
            day=str(self.day.day), status='入力中', checklist_snapshot_json='{}', answers_json='[]',
            operation_judgment_json='{}')
        self.db.session.add(other); self.db.session.commit()
        value = self.get_priority(bundle)
        self.assertEqual(value['label'], '高'); self.assertIsNone(value['effective_score'])
        self.assertEqual(json.loads(state.result_json)['analysis']['recommendations'][0]['priority'], '高')

    def test_instruction_ref_cannot_be_rebound_to_component_or_unknown_source(self):
        self.begin_priority(); self.decide('運行不可')
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        with self.app.test_request_context('/'):
            payload, sources = get_vehicle_karte_analysis_job_data(self.vehicle)
        option = next(v for v in payload['records'][0]['priority_inputs'] if v['kind'] == 'registered_operation_instruction')
        item = dict(priority='低', target='ブレーキ', source_ids=option['source_ids'], priority_input_ref=option['ref'])
        with self.assertRaises(ValueError): validate_priority_input(item, payload)
        item.update(target=option['target'], source_ids=['inspection:999'])
        with self.assertRaises(ValueError): validate_priority_input(item, payload)

    def test_old_or_past_instruction_has_no_new_instruction_offer(self):
        self.begin_priority(); self.decide('運行不可')
        from dkss_app.priority_projection import registered_inspection_provenance
        judgment = self.state()
        judgment.pop('priority_instruction_context')
        self.row.operation_judgment_json = json.dumps(judgment); self.db.session.commit()
        proof = registered_inspection_provenance(self.vehicle, self.row)
        self.assertFalse(any(v['kind'] == 'registered_operation_instruction' for v in inspection_inputs(proof)))

    def test_forged_followup_event_or_missing_event_does_not_compute_25(self):
        self.begin_priority(); self.decide('運行可'); self.repair_priority()
        bundle, _ = self.generate(label='高')
        event = self.models.ChecklistEvent.query.filter_by(result_id=self.row.id, event_type='再確認待ち').one()
        detail = json.loads(event.detail_json)
        detail['previous_defect']['defect_no'] = 999
        event.detail_json = json.dumps(detail); self.db.session.commit()
        value = self.get_priority(bundle)
        self.assertEqual(value['label'], '高'); self.assertIsNone(value['effective_score'])

    def test_explicit_same_instruction_replacement_suppresses_only_response_and_preserves_ids(self):
        self.begin_priority(); self.decide('運行不可')
        bundle, state = self.generate('registered_operation_instruction')
        original = state.result_json
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        expected_id, expected_revision = vehicle_analysis_proposal_ids(bundle['analysis']['recommendations'][0])
        self.decide('運行可')
        before = self.snapshot()
        with patch('dkss_app.analysis.get_vehicle_analysis_read_projection', return_value=(
                {'fingerprints': bundle['fingerprints'], 'input_summary': {}, 'comparison': None}, True)):
            response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/analysis/result')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['analysis']['recommendations'], [])
        resolved = response.json['analysis']['priority_resolved_proposals'][0]
        self.assertEqual((resolved['proposal_id'], resolved['proposal_revision']), (expected_id, expected_revision))
        self.assertEqual(self.snapshot(), before); self.assertEqual(state.result_json, original)
        self.assertEqual(self.state()['status'], '運行可')

    def test_next_day_keeps_saved_high_without_new_score_or_releasing_instruction(self):
        self.begin_priority(); self.decide('運行不可')
        bundle, state = self.generate('registered_operation_instruction')
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        from dkss_app.priority_projection import project_registered_priorities
        raw = deepcopy(bundle['analysis'])
        item = raw['recommendations'][0]
        item['proposal_id'], item['proposal_revision'] = vehicle_analysis_proposal_ids(item)
        before = self.snapshot(); saved = state.result_json
        result = project_registered_priorities(raw, self.vehicle, bundle['sources'],
            as_of=self.day + timedelta(days=1), is_current=False)
        value = result['recommendations'][0]['priority_assessment']
        self.assertEqual((value['label'], value['effective_score']), ('高', None))
        self.assertEqual(self.snapshot(), before); self.assertEqual(state.result_json, saved)
        self.assertEqual(self.state()['status'], '運行不可')

    def test_suppression_preserves_duplicate_other_items_feedback_and_output_indices(self):
        self.begin_priority(); self.decide('運行不可')
        bundle, state = self.generate('registered_operation_instruction')
        instruction = deepcopy(bundle['analysis']['recommendations'][0])
        untouched = dict(priority='中', category='記録確認', target='保存した別の記録',
            title='別の記録', source_ids=instruction['source_ids'], action='元記録を照合')
        # Duplicates intentionally retain the same original feedback identity.
        bundle['analysis']['recommendations'] = [instruction, untouched, deepcopy(instruction), deepcopy(untouched)]
        state.result_json = json.dumps(bundle, ensure_ascii=False); self.db.session.commit()
        original = state.result_json
        self.decide('運行可')
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        with patch('dkss_app.analysis.get_vehicle_analysis_read_projection', return_value=(
                {'fingerprints': bundle['fingerprints'], 'input_summary': {}, 'comparison': None}, True)):
            response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/analysis/result')
        projected = response.json['analysis']
        self.assertEqual(len(projected['recommendations']), 2)
        self.assertEqual(projected['priority_order_indices'], [0, 1])
        self.assertEqual(projected['priority_order_format'], 'source_indices_v1')
        expected_id, expected_revision = vehicle_analysis_proposal_ids(untouched)
        for item in projected['recommendations']:
            self.assertEqual((item['proposal_id'], item['proposal_revision']), (expected_id, expected_revision))
            self.assertEqual(item['feedback'], {})
            self.assertEqual(item['target'], untouched['target'])
            self.assertEqual(item['priority'], '中')
        self.assertEqual(len(projected['priority_resolved_proposals']), 2)
        self.assertEqual(state.result_json, original)

    def test_intermediate_repair_reset_is_not_an_explicit_release_of_original_instruction(self):
        self.begin_priority(); self.decide('運行不可')
        bundle, _ = self.generate('registered_operation_instruction')
        self.repair_priority()
        self.decide('運行可')
        value = self.get_priority(bundle)
        self.assertEqual(value['label'], '高'); self.assertIsNone(value['effective_score'])

    def test_unrelated_other_vehicle_does_not_remove_instruction_score(self):
        self.begin_priority(); self.decide('運行不可')
        bundle, _ = self.generate('registered_operation_instruction')
        other = self.models.Vehicle.query.filter_by(company_code='B').one()
        self.db.session.add(self.models.VehicleChecklistResult(company_code='B', vehicle_record_id=other.id,
            checklist_id=self.checklist.id, year=str(self.day.year), month=str(self.day.month),
            day=str(self.day.day), status='承認済み', checklist_snapshot_json='{}', answers_json='[]',
            operation_judgment_json='{}'))
        self.db.session.commit()
        self.assertEqual(self.get_priority(bundle)['effective_score'], 60)

    def test_long_item_has_server_ref_but_no_inferred_wheel_applicability_or_score(self):
        self.begin_priority('daily_18'); self.decide('運行可')
        bundle, _ = self.generate(label='高')
        self.assertLessEqual(len(bundle['analysis']['recommendations'][0]['target']), 24)
        self.assertTrue(bundle['analysis']['recommendations'][0]['priority_input_ref'])
        value = self.get_priority(bundle)
        self.assertEqual(value['label'], '高'); self.assertIsNone(value['effective_score'])


    def test_malformed_current_judgment_and_malformed_saved_proof_keep_legacy(self):
        self.begin_priority(); self.decide('運行可')
        bundle, state = self.generate(label='高')
        original = self.row.operation_judgment_json
        for bad in ('null', '[]', '42', '"invalid"'):
            with self.subTest(bad=bad):
                self.row.operation_judgment_json = bad; self.db.session.commit()
                value = self.get_priority(bundle)
                self.assertEqual(value['label'], '高'); self.assertIsNone(value['effective_score'])
        self.row.operation_judgment_json = original
        bundle['sources'][f'inspection:{self.row.id}']['priority_provenance']['events'] = None
        state.result_json = json.dumps(bundle, ensure_ascii=False); self.db.session.commit()
        value = self.get_priority(bundle)
        self.assertEqual(value['label'], '高'); self.assertIsNone(value['effective_score'])

    def test_instruction_basis_bound_does_not_reject_human_decision_or_invent_currentness(self):
        self.begin_priority()
        # The bounded helper itself is exercised with exact 1000/1001 rows in
        # read-only mock DB result; no large database or live data is required.
        from dkss_app.priority_projection import _other_operation_input_fingerprint
        from types import SimpleNamespace
        subject = SimpleNamespace(company_code='A', vehicle_record_id=self.vehicle.id, id=self.row.id)
        with patch.object(self.db.session, 'query') as query:
            chain = query.return_value.filter.return_value.order_by.return_value.limit
            chain.return_value.all.return_value = [(i,) for i in range(1001)]
            cache = {}
            self.assertIsNone(_other_operation_input_fingerprint(subject, cache=cache))
            self.assertIsNone(_other_operation_input_fingerprint(subject, cache=cache))
            self.assertEqual(query.call_count, 1)
            chain.assert_called_once_with(1001)
        self.decide('運行不可')
        bundle, _ = self.generate('registered_operation_instruction')
        self.assertEqual(self.get_priority(bundle)['effective_score'], 60)


    def test_valid_brake_ref_cannot_score_an_unrelated_display_target(self):
        self.begin_priority(); self.decide('運行可')
        bundle, state = self.generate(label='高')
        item = bundle['analysis']['recommendations'][0]
        item.update(target='エアコン', title='エアコン確認', action='温度調整')
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        with self.app.test_request_context('/'):
            payload, _ = get_vehicle_karte_analysis_job_data(self.vehicle)
        with self.assertRaises(ValueError): validate_priority_input(item, payload)
        state.result_json = json.dumps(bundle, ensure_ascii=False); self.db.session.commit()
        value = self.get_priority(bundle)
        self.assertEqual(value['label'], '高'); self.assertIsNone(value['effective_score'])


    def test_verified_replacement_does_not_resurrect_after_midnight_or_other_records(self):
        self.begin_priority(); self.decide('運行不可')
        bundle, state = self.generate('registered_operation_instruction')
        self.decide('運行可')
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        from dkss_app.priority_projection import project_registered_priorities
        raw = deepcopy(bundle['analysis'])
        item = raw['recommendations'][0]
        item['proposal_id'], item['proposal_revision'] = vehicle_analysis_proposal_ids(item)
        for as_of in (self.day, self.day + timedelta(days=1)):
            projected = project_registered_priorities(raw, self.vehicle, bundle['sources'], as_of=as_of)
            self.assertEqual(projected['recommendations'], [])
        self.db.session.add(self.models.VehicleChecklistResult(company_code='A', vehicle_record_id=self.vehicle.id,
            checklist_id=self.checklist.id, year=str(self.day.year), month=str(self.day.month),
            day=str(self.day.day), status='入力中', checklist_snapshot_json='{}', answers_json='[]',
            operation_judgment_json='{}'))
        self.db.session.commit()
        projected = project_registered_priorities(raw, self.vehicle, bundle['sources'], as_of=self.day)
        self.assertEqual(projected['recommendations'], [])
        self.assertEqual(len(projected['priority_resolved_proposals']), 1)

    def test_instruction_uses_recorded_business_timezone_not_current_user_preference(self):
        from datetime import timezone
        from dkss_app.priority_projection import project_registered_priorities
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        self.begin_priority()
        # The human decision is late on the stored business day; its JST
        # reference date is the next day. We do not relabel the local timestamp.
        local = datetime.combine(self.day, datetime.min.time()).replace(hour=23,
            tzinfo=ZoneInfo('Pacific/Honolulu'))
        as_of = local.astimezone(ZoneInfo('Asia/Tokyo')).date()
        with patch('dkss_app.checklist_common.get_user_local_now', return_value=local):
            self.decide('運行不可')
        from dkss_app.priority_projection import registered_inspection_provenance
        with patch('dkss_app.priority_projection.datetime', wraps=datetime) as clock:
            clock.now.side_effect = lambda zone: local.astimezone(zone)
            proof = registered_inspection_provenance(self.vehicle, self.row)
            offered = next(v for v in inspection_inputs(proof) if v['kind'] == 'registered_operation_instruction')
            item = dict(priority='高', category='整備・点検', target=offered['target'],
                title='既存判断', action='責任者へ確認', source_ids=offered['source_ids'], priority_input_ref=offered['ref'])
            item['proposal_id'], item['proposal_revision'] = vehicle_analysis_proposal_ids(item)
            result = project_registered_priorities({'recommendations': [item]}, self.vehicle,
                {f'inspection:{self.row.id}': {'priority_provenance': proof}}, as_of=as_of)
        value = result['recommendations'][0]['priority_assessment']
        self.assertEqual(value['effective_score'], 60)
        self.assertEqual(value['observed_at'], as_of.isoformat())
        self.assertTrue(value['instruction_details']['recorded_at'].endswith('-10:00'))


    @unittest.skipUnless(shutil.which('node'), 'Node required for shared UI contract')
    def test_blank_person_name_uses_recorded_username_consistently_across_views(self):
        self.begin_priority()
        admin = self.models.User.query.filter_by(company_code='A', username='admin').one()
        admin.last_name = ''; admin.first_name = ''
        admin.office = self.vehicle.office = '試験営業所'
        self.db.session.add(self.models.Office(company_code='A', name='試験営業所'))
        self.db.session.add(self.models.Driver(company_code='A', employee_id='admin',
            name='合成試験の運転者', office='試験営業所', vehicles_json=json.dumps([str(self.vehicle.id)])))
        self.db.session.commit()
        self.decide('運行不可')
        self.assertEqual(self.state()['judged_by'], '')
        self.assertEqual(self.state()['judged_by_username'], 'admin')
        bundle, state = self.generate('registered_operation_instruction')
        before = self.snapshot(); saved = state.result_json
        with patch('dkss_app.analysis.get_vehicle_analysis_read_projection', return_value=(
                {'fingerprints': bundle['fingerprints'], 'input_summary': {}, 'comparison': None}, True)):
            response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/analysis/result')
        self.assertEqual(response.status_code, 200)
        item = response.json['analysis']['recommendations'][0]
        self.assertEqual(item['priority_assessment']['instruction_details']['actor_name'], 'admin')
        with self.app.test_request_context('/'):
            from dkss_app.dashboard import get_dashboard_vehicle_attention
            dashboard = get_dashboard_vehicle_attention('A', None, [self.vehicle.id])['mine']['items'][0]
        self.assertEqual(dashboard['priority_assessment']['effective_score'], 60)
        self.assertEqual(dashboard['priority_assessment']['instruction_details']['actor_name'], 'admin')
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('対応優先度：高、60点', page.get_data(as_text=True))
        script = """const p=require('./static/js/vehicle_priority_presentation.js');
        const items=JSON.parse(require('fs').readFileSync(0,'utf8'));
        for (const item of items) { const v=p.read(item);
          if (!v.valid || v.label!=='高' || v.score!==60) process.exit(1);
        }"""
        subprocess.run([shutil.which('node'), '-e', script], input=json.dumps([item, dashboard]),
            text=True, check=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(state.result_json, saved)
        self.assertEqual(self.state()['judged_by'], '')
