"""Normal periodic generation preserves source proof and reuses the priority view.

Only the document extraction/AI answer is stubbed. Human daily input, original
import, proposal job, stored result and GET all use the normal Flask/SQLite path.
"""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_priority_common_workflow as common
import test_priority_stage2_workflow as stage2
import test_inspection_plans as plans
import test_workflow_regressions as workflow
import test_priority_adopted_timing as timing
from dkss_app.priority_consumers import (PERIODIC_PROOF_KEY, capture_periodic_priority_sources,
    bind_periodic_priority_sources, project_periodic_priorities, priority_counts)
from vehicle_priority_inputs import validate_priority_input


class PeriodicPriorityWorkflowTests(unittest.TestCase):
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
    begin_priority = stage2.PriorityStage2WorkflowTests.begin_priority
    repair_priority = stage2.PriorityStage2WorkflowTests.repair_priority
    upload_inspection = workflow.WorkflowRegressionTests.upload_inspection
    inspection_form = workflow.WorkflowRegressionTests.inspection_form
    import_record = plans.InspectionPlanTests.import_record

    def setUp(self):
        common.CommonPriorityWorkflowTests.setUp(self)
        from application_fixture import ApplicationFixture
        self.m = ApplicationFixture(self.app)
        self.service = self.app.extensions['dkss']['periodic_followups']
        self.executor = self.app.extensions['periodic_proposal_executor']

    def prepare(self, decision='運行可', repair=False):
        self.begin_priority(); self.decide(decision)
        if repair:
            self.repair_priority()
        self.login('admin')
        self.periodic = self.import_record()
        self.api = f'/vehicle/karte/{self.vehicle.id}/periodic/{self.periodic.id}/suggestions'

    def input(self):
        with self.app.test_request_context('/'):
            return self.service.proposal_input(self.vehicle, self.periodic)

    def item(self, payload, kind='inspection_defect'):
        record = next(r for r in payload['records'] if r['source_id'] == f'inspection:{self.row.id}')
        offer = next(v for v in record['priority_inputs'] if v['kind'] == kind)
        item = dict(priority='低', category='整備・点検', target=offer['display_target'],
            title='元記録の確認', action='元記録と実車を確認', current_state='元の指摘',
            source_ids=offer['source_ids'], priority_input_ref=offer['ref'])
        validate_priority_input(item, payload)
        return item

    def execute_normal_job(self, kind='inspection_defect'):
        with patch.object(self.executor, 'submit') as submit:
            response = self.client.post(self.api, json={})
        self.assertEqual(response.status_code, 202)
        fn, company, record_id, token, payload, proof = submit.call_args.args
        json.dumps(proof, ensure_ascii=False)
        item = self.item(payload, kind)
        raw = {'recommendations': [item]}
        before = self.snapshot()
        with patch('vehicle_karte_analysis_ai.analyze_vehicle_karte', return_value=raw):
            fn(company, record_id, token, payload, proof)
        self.assertEqual(self.snapshot(), before)
        job = self.service.Proposal.query.one()
        saved = job.result_json
        with patch.object(self.executor, 'submit') as forbidden:
            response = self.client.get(self.api)
        self.assertEqual(response.status_code, 200); forbidden.assert_not_called()
        self.assertEqual(response.json['status'], 'completed')
        self.assertEqual(self.snapshot(), before); self.assertEqual(job.result_json, saved)
        self.assertNotIn(PERIODIC_PROOF_KEY, response.json['result'])
        return response.json, raw, proof, job

    def test_daily_normal_generation_computes_50_and_counts_without_changing_facts(self):
        self.prepare()
        data, raw, proof, job = self.execute_normal_job()
        value = data['result']['recommendations'][0]
        self.assertEqual((value['priority'], value['priority_assessment']['effective_score']), ('中', 50))
        self.assertEqual(data['result']['priority_summary'],
            {'labels': {'高': 0, '中': 1, '低': 0}, 'invalid_count': 0, 'proposal_count': 1})
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        self.assertEqual((value['proposal_id'], value['proposal_revision']), vehicle_analysis_proposal_ids(raw['recommendations'][0]))
        self.assertEqual(json.loads(job.result_json)['recommendations'], raw['recommendations'])
        self.assertEqual(json.loads(job.result_json)[PERIODIC_PROOF_KEY], proof)
        html = self.client.get(self.api.replace('/suggestions', '/followup')).get_data(as_text=True)
        self.assertIn('vehicle_priority_presentation.js', html)
        self.assertLess(html.index('vehicle_priority_presentation.js'), html.index('vehicle_periodic_suggestions.js'))

    def test_recheck_normal_generation_uses_25_with_no_invented_impact_or_state(self):
        self.prepare(repair=True)
        data, _, _, _ = self.execute_normal_job()
        value = data['result']['recommendations'][0]['priority_assessment']
        self.assertEqual(value['effective_score'], 25)
        self.assertEqual([v['points'] for v in value['factors']], [None, None, None])
        self.assertEqual(self.state()['status'], '未判定')

    def test_instruction_normal_generation_uses_existing_human_60_only(self):
        self.prepare(decision='運行不可')
        data, raw, _, _ = self.execute_normal_job('registered_operation_instruction')
        value = data['result']['recommendations'][0]['priority_assessment']
        self.assertEqual(value['effective_score'], 60)
        self.assertEqual(raw['recommendations'][0]['priority'], '高')
        self.assertEqual(value['instruction_details']['recorded_status'], '運行不可')
        self.assertEqual(self.state()['status'], '運行不可')

    def test_missing_original_proof_preserves_saved_class_not_current_rebinding(self):
        self.prepare()
        payload, sources, digest = self.input()
        original = {'recommendations': [self.item(payload)]}
        self.assertEqual(original['recommendations'][0]['priority'], '低')
        job = self.service.Proposal(company_code='A', inspection_record_id=self.periodic.id,
            input_hash=digest, run_token='legacy', status='completed',
            result_json=json.dumps(original), updated_at=self.day.isoformat()+'T12:00:00+09:00')
        self.db.session.add(job); self.db.session.commit()
        before = job.result_json
        response = self.client.get(self.api)
        self.assertEqual(response.json['status'], 'completed')
        value = response.json['result']['recommendations'][0]['priority_assessment']
        self.assertEqual((value['label'], value['effective_score']), ('低', None))
        self.assertEqual(job.result_json, before)
        self.assertTrue(any('生成時' in reason for reason in value['missing_conditions']))
        with patch.object(self.executor, 'submit') as submit:
            self.client.post(self.api, json={})
        submit.assert_not_called()  # No paid migration of completed old results.

    def test_foreign_scope_and_unknown_class_are_not_converted_to_low(self):
        self.prepare()
        payload, sources, _ = self.input()
        item = self.item(payload); item['priority'] = '不正区分'
        proof = capture_periodic_priority_sources('OTHER', self.vehicle.id, sources)
        original = bind_periodic_priority_sources({'recommendations': [item]}, proof)
        projected, _ = project_periodic_priorities(original, self.vehicle, sources, as_of=self.day)
        self.assertIsNone(projected['recommendations'][0]['priority_assessment']['label'])
        self.assertEqual(projected['priority_summary']['invalid_count'], 1)
        self.assertEqual(projected['priority_summary']['labels'], {'高': 0, '中': 0, '低': 0})
        self.assertEqual(original[PERIODIC_PROOF_KEY], proof)

    def test_source_snapshots_are_not_mutated_by_periodic_enrichment(self):
        self.prepare()
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        with self.app.test_request_context('/'):
            original_payload, original_sources = get_vehicle_karte_analysis_job_data(self.vehicle)
        _, sources, _ = self.input()
        sid = f'periodic:{self.periodic.id}'
        self.assertIn('snapshot', sources[sid])
        self.assertEqual(sources[sid]['snapshot'], original_sources[sid]['snapshot'])
        self.assertIn('symbol_legend', next(r for r in self.input()[0]['records'] if r['source_id'] == sid))

    def test_changed_input_uses_normal_new_generation_not_get_backfill(self):
        self.prepare()
        _, _, old_proof, job = self.execute_normal_job()
        original = job.result_json
        self.periodic.content = '原本に追加された記載'; self.db.session.commit()
        with patch.object(self.executor, 'submit') as submit:
            self.assertEqual(self.client.get(self.api).json['status'], 'missing')
            self.assertEqual(job.result_json, original)
            self.assertEqual(self.client.post(self.api, json={}).status_code, 202)
        new_proof = submit.call_args.args[-1]
        sid = f'periodic:{self.periodic.id}'
        self.assertNotEqual(new_proof['sources'][sid]['snapshot'], old_proof['sources'][sid]['snapshot'])


class PeriodicTimingPriorityTests(unittest.TestCase):
    setUpClass = classmethod(timing.AdoptedTimingPriorityTests.setUpClass.__func__)
    tearDownClass = classmethod(timing.AdoptedTimingPriorityTests.tearDownClass.__func__)
    setUp = timing.AdoptedTimingPriorityTests.setUp
    tearDown = timing.AdoptedTimingPriorityTests.tearDown
    setup_rule = timing.AdoptedTimingPriorityTests.setup_rule
    operation = timing.AdoptedTimingPriorityTests.operation
    save_rule = timing.AdoptedTimingPriorityTests.save_rule
    upload_inspection = workflow.WorkflowRegressionTests.upload_inspection
    inspection_form = workflow.WorkflowRegressionTests.inspection_form
    import_record = plans.InspectionPlanTests.import_record

    def check_saved_read(self, record=None):
        record = record or self.import_record()
        self.periodic = record
        service = self.m.app.extensions['dkss']['periodic_followups']
        api = f'/vehicle/karte/{self.vehicle.id}/periodic/{record.id}/suggestions'
        self.api = api
        with patch.object(self.m.app.extensions['periodic_proposal_executor'], 'submit') as submit:
            self.assertEqual(self.client.post(api, json={}).status_code, 202)
        fn, company, record_id, token, payload, proof = submit.call_args.args
        offers = [o for k in payload['maintenance_knowledge'] for o in k.get('priority_inputs', [])]
        self.assertEqual(len(offers), 1, payload['maintenance_knowledge'])
        offer = offers[0]
        item = dict(priority='高', category='整備・点検', target=offer['display_target'],
            title='採用済み交換基準', source_ids=offer['source_ids'], priority_input_ref=offer['ref'])
        validate_priority_input(item, payload)
        with patch('vehicle_karte_analysis_ai.analyze_vehicle_karte', return_value={'recommendations':[item]}):
            fn(company, record_id, token, payload, proof)
        job = service.Proposal.query.one(); saved = job.result_json
        response = self.client.get(api)
        self.assertEqual(response.json['status'], 'completed')
        value = response.json['result']['recommendations'][0]['priority_assessment']
        self.assertEqual((value['label'], value['effective_score']), ('中', 35))
        self.assertEqual([v['points'] for v in value['factors']], [None,35,None])
        self.assertEqual(job.result_json, saved)
        return value

    def test_adopted_replacement_timing_survives_periodic_enrichment_and_normal_saved_read(self):
        self.setup_rule()
        self.check_saved_read()

    def test_adopted_inspection_timing_keeps_original_periodic_snapshot_and_baseline(self):
        self.setup_rule(criteria=[{'metric': 'period_days', 'value': 30}], action='inspect')
        self.rule['source_quote'] = '合成試験部品の排出水量と状態確認'
        self.save_rule()
        from test_inspection_document_ai import extraction, pdf_bytes
        source = pdf_bytes(1)
        data = extraction(source)
        original = data['records'][0]
        original.update(inspection_date='2026-09-12', symbol_legend='○:点検済み')
        original['inspection_items'][0]['item_name'] = self.rule['source_quote']
        self.upload_inspection(data=data, source=source)
        draft = self.m.VehicleDocumentImportDraft.query.one()
        response = self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=self.inspection_form(draft))
        self.assertEqual(response.status_code, 302)
        value = self.check_saved_read(self.m.VehiclePeriodicInspectionRecord.query.one())
        self.assertEqual(value['timing_reference']['action'], 'inspect')
        self.assertTrue(any(sid.startswith('periodic:') for factor in value['factors'] for sid in factor['source_ids']))


class PriorityConsumerPureTests(unittest.TestCase):
    def test_model_proof_is_never_saved_without_server_capture(self):
        result = {'recommendations': [], PERIODIC_PROOF_KEY: {'forged': True}}
        self.assertNotIn(PERIODIC_PROOF_KEY, bind_periodic_priority_sources(result, None))
        self.assertIn(PERIODIC_PROOF_KEY, result)

    def test_counts_are_proposals_not_unknowns_as_low(self):
        items = [{'priority_assessment': {'label': '高'}}, {}, None, {'priority_assessment': {'label': '低'}}]
        self.assertEqual(priority_counts({'recommendations': items}),
            {'labels': {'高':1, '中':0, '低':1}, 'invalid_count':2, 'proposal_count':4})
