"""Real confirmed sources -> scheduled generation with an empty model response.

Only the urllib transport is synthetic. Original readers, confirmation POST,
input builder, queue/job persistence, projection, and stale feedback are real.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
import unittest
from unittest.mock import patch

import vehicle_karte_analysis_ai as generator


@contextmanager
def actual_confirmation(kind):
    if kind == 'manufacturer_immediate':
        from test_priority_manufacturer_workflow import ManufacturerConfirmationWorkflowTests
        case = ManufacturerConfirmationWorkflowTests()
    elif kind == 'legal_deadline':
        from test_priority_certificate_sources import CertificateSourceTests
        case = CertificateSourceTests()
    else:
        from test_priority_progression_workflow import ProgressionWorkflowTests
        case = ProgressionWorkflowTests()
    case.setUpClass()
    try:
        case.setUp()
        try:
            if kind == 'manufacturer_immediate':
                case.use_original_instruction_only()
            elif kind == 'progression':
                case.prepare_pair(same_day=True)
            case.login('admin')
            confirm = case.confirm_http if kind == 'legal_deadline' else case.confirm
            event_id, _ = confirm()
            yield case, event_id, confirm
        finally:
            case.tearDown(); case.doCleanups()
    finally:
        case.tearDownClass()


class DeterministicNormalGenerationTests(unittest.TestCase):
    def exercise(self, kind, score):
        from dkss_app import analysis as service
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        with actual_confirmation(kind) as (case, event_id, confirm):
            with case.app.test_request_context('/'):
                payload, sources = service.get_vehicle_karte_analysis_job_data(case.vehicle)
                state = service.queue_vehicle_karte_analysis(case.vehicle, payload)
            before_payload = deepcopy(payload)
            self.assertTrue(payload['_fingerprints']['has_important_history'])
            state.next_analysis_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            case.db.session.commit()
            original_business = {name: [tuple(getattr(r, c.name) for c in getattr(case.models, name).__table__.columns)
                for r in getattr(case.models, name).query.order_by(getattr(case.models, name).id)]
                for name in ('VehicleChecklistResult', 'Notification', 'VehicleMaintenanceRecord')}
            calls = []
            def empty_model(request, **kwargs):
                wire = generator.expand_vehicle_karte_analysis_wire_payload(json.loads(json.loads(request.data)['input']))
                calls.append(wire)
                self.assertNotIn('_confirmed_priority_candidates', wire)
                result = {'overview': '合成応答。AI候補は空配列。', 'recommendations': []}
                return BytesIO(json.dumps({'status': 'completed', 'output': [{'content': [
                    {'type': 'output_text', 'text': json.dumps(result)}]}]}).encode())
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-local-test-only'}), \
                    patch.object(generator.urllib.request, 'urlopen', side_effect=empty_model):
                self.assertTrue(service.run_vehicle_karte_analysis_job(state.id))
                regenerated = generator.analyze_vehicle_karte(payload)
            self.assertEqual(len(calls), 2)
            self.assertEqual(payload, before_payload)
            case.db.session.refresh(state)
            self.assertEqual(state.status, 'completed')
            original_json = state.result_json
            bundle = json.loads(original_json)
            item, = bundle['analysis']['recommendations']
            self.assertIn(f'confirmation:{event_id}:', item['priority_input_ref'])
            self.assertEqual(vehicle_analysis_proposal_ids(item), vehicle_analysis_proposal_ids(regenerated['recommendations'][0]))
            self.assertEqual(bundle['sources'], json.loads(json.dumps(sources, ensure_ascii=False, default=str)))
            api = f'/vehicle/karte/{case.vehicle.id}/analysis/result'
            shown = case.request('GET', api).json
            self.assertTrue(shown['is_current'])
            value, = shown['analysis']['recommendations']
            self.assertEqual(value['priority_assessment']['effective_score'], score)
            self.assertEqual(value['priority_assessment']['confirmation_details']['kind'], kind)
            self.assertEqual(value['priority'], '高')
            self.assertEqual(state.result_json, original_json)
            old_answer = dict(proposal_id=value['proposal_id'], proposal_revision=value['proposal_revision'], status='accepted')
            self.assertEqual(case.request('POST', api.replace('/result', '/feedback'), json=old_answer).status_code, 200)
            # A later original confirmation is a real important-input change.
            # Failed generation must not replace a previously saved result with
            # a fabricated successful result or with an empty proposal list.
            confirm()
            with case.app.test_request_context('/'):
                changed, _ = service.get_vehicle_karte_analysis_job_data(case.vehicle)
                state = service.queue_vehicle_karte_analysis(case.vehicle, changed)
            self.assertNotEqual(payload['_fingerprints']['important_hash'], changed['_fingerprints']['important_hash'])
            state.next_analysis_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            case.db.session.commit()
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-local-test-only'}), \
                    patch.object(generator.urllib.request, 'urlopen', side_effect=OSError('synthetic transport failure')):
                self.assertFalse(service.run_vehicle_karte_analysis_job(state.id))
            case.db.session.refresh(state)
            self.assertEqual(state.status, 'error')
            self.assertEqual(state.result_json, original_json)
            shown = case.request('GET', api).json
            self.assertTrue(shown['has_result']); self.assertFalse(shown['is_current'])
            self.assertEqual(case.request('POST', api.replace('/result', '/feedback'), json=old_answer).status_code, 409)
            self.assertEqual(original_business, {name: [tuple(getattr(r, c.name) for c in getattr(case.models, name).__table__.columns)
                for r in getattr(case.models, name).query.order_by(getattr(case.models, name).id)] for name in original_business})
            # A successful empty response after source evidence becomes held
            # must retain the actual previous evaluation, not silently erase it.
            if kind == 'manufacturer_immediate':
                case.public.available = False
            elif kind == 'legal_deadline':
                case.document.source_sha256 = 'a' * 64
            else:
                answers = json.loads(case.row.answers_json)
                next(answer for answer in answers if answer.get('value') == '×')['comment'] = '原確認とは異なる現在回答'
                case.row.answers_json = json.dumps(answers, ensure_ascii=False)
            case.db.session.commit()
            with case.app.test_request_context('/'):
                held_payload, _ = service.get_vehicle_karte_analysis_job_data(case.vehicle)
                state = service.queue_vehicle_karte_analysis(case.vehicle, held_payload)
            state.next_analysis_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            case.db.session.commit()
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-local-test-only'}), \
                    patch.object(generator.urllib.request, 'urlopen', side_effect=empty_model):
                self.assertTrue(service.run_vehicle_karte_analysis_job(state.id))
            case.db.session.refresh(state)
            held_raw = json.loads(state.result_json)['analysis']['recommendations']
            self.assertEqual(len(held_raw), 1)
            self.assertIn('priority_candidate_carryover', held_raw[0])
            held_response = case.request('GET', api).json
            self.assertTrue(held_response['is_current'])
            held_value, = held_response['analysis']['recommendations']
            self.assertEqual(held_value['priority'], '高')
            self.assertEqual(held_value['proposal_id'], old_answer['proposal_id'])
            self.assertIsNone(held_value['priority_assessment']['effective_score'])
            self.assertTrue(held_value['priority_assessment']['previous_result']['reason'])
            self.assertEqual(case.request('POST', api.replace('/result', '/feedback'), json=old_answer).status_code, 409)
            current_answer = dict(old_answer, proposal_revision=held_value['proposal_revision'])
            self.assertEqual(case.request('POST', api.replace('/result', '/feedback'), json=current_answer).status_code, 409)
            self.assertEqual(case.request('POST', api.replace('/result', '/evaluation'), json=dict(
                proposal_id=held_value['proposal_id'], proposal_revision=held_value['proposal_revision'],
                verdict='appropriate', comment='')).status_code, 409)

    def test_manufacturer_empty_model_still_saves_60_and_failed_update_preserves_previous_result(self):
        self.exercise('manufacturer_immediate', 60)

    def test_legal_empty_model_still_saves_60_and_failed_update_preserves_previous_result(self):
        self.exercise('legal_deadline', 60)

    def test_recurrence_empty_model_still_saves_65_and_failed_update_preserves_previous_result(self):
        self.exercise('progression', 65)

    def test_cancellation_during_model_transport_cannot_publish_a_current_confirmed_candidate(self):
        from dkss_app import analysis as service
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        with actual_confirmation('legal_deadline') as (case, _event_id, _confirm):
            with case.app.test_request_context('/'):
                payload, _ = service.get_vehicle_karte_analysis_job_data(case.vehicle)
                state = service.queue_vehicle_karte_analysis(case.vehicle, payload)
            state.next_analysis_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            case.db.session.commit()
            from dkss_app.priority_confirmed_projection import finalize_confirmed_priority_candidates
            proposed = finalize_confirmed_priority_candidates({'recommendations': []}, payload)['recommendations'][0]
            key, revision = vehicle_analysis_proposal_ids(proposed)
            calls = []
            def cancel_before_response(request, **kwargs):
                prefix = f'/vehicle/karte/{case.vehicle.id}/priority-confirmations'
                history = case.request('GET', prefix, query_string={'kind': 'legal_deadline'}).json['history']
                response = case.request('POST', prefix, json={'token': history[0]['cancel_token']})
                self.assertEqual(response.status_code, 200)
                calls.append('cancelled')
                return BytesIO(json.dumps({'status': 'completed', 'output': [{'content': [
                    {'type': 'output_text', 'text': json.dumps({'overview': '合成空応答', 'recommendations': []})}]}]}).encode())
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-local-test-only'}), \
                    patch.object(generator.urllib.request, 'urlopen', side_effect=cancel_before_response):
                self.assertTrue(service.run_vehicle_karte_analysis_job(state.id))
            self.assertEqual(calls, ['cancelled'])
            case.db.session.refresh(state)
            raw = state.result_json
            self.assertEqual(json.loads(raw)['analysis']['recommendations'], [])
            api = f'/vehicle/karte/{case.vehicle.id}/analysis/result'
            shown = case.request('GET', api).json
            self.assertFalse(shown['is_current'])
            self.assertEqual(shown['analysis']['recommendations'], [])
            self.assertEqual(case.request('POST', api.replace('/result', '/feedback'),
                json=dict(proposal_id=key, proposal_revision=revision, status='accepted')).status_code, 409)
            self.assertEqual(state.result_json, raw)

    def test_periodic_empty_generation_preserves_held_confirmation_until_explicit_cancellation(self):
        from application_fixture import ApplicationFixture
        from types import MethodType
        import test_inspection_plans as plans
        import test_workflow_regressions as workflows
        with actual_confirmation('manufacturer_immediate') as (case, _event_id, _confirm):
            case.m = ApplicationFixture(case.app)
            case.upload_inspection = MethodType(workflows.WorkflowRegressionTests.upload_inspection, case)
            case.inspection_form = MethodType(workflows.WorkflowRegressionTests.inspection_form, case)
            record = plans.InspectionPlanTests.import_record(case)
            service = case.app.extensions['dkss']['periodic_followups']
            executor = case.app.extensions['periodic_proposal_executor']
            api = f'/vehicle/karte/{case.vehicle.id}/periodic/{record.id}/suggestions'
            def run(empty=True):
                with patch.object(executor, 'submit') as submit:
                    self.assertEqual(case.client.post(api, json={'retry': True}).status_code, 202)
                fn, *args = submit.call_args.args
                response = {'overview': '合成空応答', 'recommendations': []}
                def transport(request, **kwargs):
                    if not empty: raise OSError('synthetic periodic transport failure')
                    return BytesIO(json.dumps({'status': 'completed', 'output': [{'content': [
                        {'type': 'output_text', 'text': json.dumps(response)}]}]}).encode())
                with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-local-test-only'}), \
                        patch.object(generator.urllib.request, 'urlopen', side_effect=transport):
                    fn(*args)
                case.db.session.expire_all()
                return case.client.get(api).json, service.Proposal.query.one()
            shown, job = run()
            self.assertEqual(shown['result']['recommendations'][0]['priority_assessment']['effective_score'], 60)
            original = job.result_json
            first = shown['result']['recommendations'][0]
            case.public.available = False; case.db.session.commit()
            held, job = run()
            value, = held['result']['recommendations']
            self.assertTrue(held['is_current'])
            self.assertEqual(value['proposal_id'], first['proposal_id'])
            self.assertEqual(value['priority'], '高'); self.assertIsNone(value['priority_assessment']['effective_score'])
            self.assertTrue(value['priority_assessment']['previous_result']['reason'])
            self.assertNotEqual(job.result_json, original)
            held_json = job.result_json
            record.content += ' 更新失敗を確認する合成原文訂正'; case.db.session.commit()
            failed, job = run(empty=False)
            self.assertEqual(failed['status'], 'error'); self.assertFalse(failed['is_current'])
            self.assertEqual(job.result_json, held_json)
            self.assertEqual(failed['result']['recommendations'][0]['proposal_id'], first['proposal_id'])
            prefix = f'/vehicle/karte/{case.vehicle.id}/priority-confirmations'
            history = case.client.get(prefix, query_string={'kind': 'manufacturer_immediate'}).json['history']
            self.assertEqual(case.client.post(prefix, json={'token': history[0]['cancel_token']}).status_code, 200)
            completed, job = run()
            self.assertEqual(completed['status'], 'completed')
            self.assertEqual(completed['result']['recommendations'], [])
            self.assertEqual(json.loads(job.result_json)['recommendations'], [])
