"""Periodic regeneration keeps previous proof/results until successful replacement."""
import json
import unittest
from unittest.mock import patch
import test_priority_periodic_consumers as periodic


class PeriodicPreservedRetryTests(unittest.TestCase):
    setUpClass = classmethod(periodic.PeriodicPriorityWorkflowTests.setUpClass.__func__)
    tearDownClass = classmethod(periodic.PeriodicPriorityWorkflowTests.tearDownClass.__func__)

    def setUp(self):
        self.case = periodic.PeriodicPriorityWorkflowTests()
        self.case.app, self.case.db, self.case.models = self.app, self.db, self.models
        self.case.setUp()

    def tearDown(self):
        self.case.tearDown(); self.case.doCleanups()

    def test_started_failed_and_stale_token_preserve_json_identity_until_success(self):
        c = self.case; c.prepare(decision='運行不可')
        first, raw, _proof, job = c.execute_normal_job('registered_operation_instruction')
        original = job.result_json
        first_item = first['result']['recommendations'][0]
        identity = first_item['proposal_id'], first_item['proposal_revision']
        self.assertEqual(first_item['priority_assessment']['effective_score'], 60)
        business = c.snapshot()
        c.periodic.content += ' 訂正された点検原文'; c.db.session.commit()
        pending = c.client.get(c.api).json
        self.assertEqual(pending['status'], 'missing')
        self.assertFalse(pending['is_current'])
        self.assertIsNone(pending['result']['recommendations'][0]['priority_assessment']['effective_score'])
        with patch.object(c.executor, 'submit') as submit:
            self.assertEqual(c.client.post(c.api, json={}).status_code, 202)
        args = submit.call_args.args; fn, company, record_id, token, payload, proof = args
        self.assertEqual(job.result_json, original)
        running = c.client.get(c.api).json
        self.assertEqual(running['status'], 'running'); self.assertFalse(running['is_current'])
        with patch('vehicle_periodic_followups.generate_periodic_proposals', side_effect=ValueError('API_KEY_NOT_SET')):
            fn(company, record_id, token, payload, proof)
        c.db.session.expire_all()
        self.assertEqual(job.result_json, original)
        failed = c.client.get(c.api).json
        self.assertEqual((failed['status'], failed['error'], failed['is_current']), ('error', 'not_configured', False))
        shown, = failed['result']['recommendations']
        self.assertEqual((shown['proposal_id'], shown['proposal_revision']), identity)
        self.assertEqual(shown['priority'], '高'); self.assertIsNone(shown['priority_assessment']['effective_score'])
        with patch.object(c.executor, 'submit') as submit:
            self.assertEqual(c.client.post(c.api, json={'retry': True}).status_code, 202)
        new_args = submit.call_args.args
        self.assertNotEqual(new_args[3], token)
        self.assertEqual(job.result_json, original)
        replacement = {**raw, 'recommendations': [{**raw['recommendations'][0], 'title': '更新後の原指示確認'}]}
        with patch('vehicle_periodic_followups.generate_periodic_proposals', return_value=replacement):
            fn(company, record_id, token, payload, proof)  # Old worker cannot overwrite a newer retry.
            c.db.session.expire_all(); self.assertEqual(job.result_json, original)
            new_args[0](*new_args[1:])
        c.db.session.expire_all()
        self.assertNotEqual(job.result_json, original)
        updated = c.client.get(c.api).json
        self.assertEqual((updated['status'], updated['is_current']), ('completed', True))
        self.assertEqual(updated['result']['recommendations'][0]['priority_assessment']['effective_score'], 60)
        self.assertEqual(json.loads(job.result_json)['recommendations'], replacement['recommendations'])
        self.assertEqual(c.snapshot(), business)

    def test_confirmation_limit_returns_specific_error_and_keeps_saved_result(self):
        c = self.case; c.prepare(decision='運行不可')
        _, _, _, job = c.execute_normal_job('registered_operation_instruction')
        original = job.result_json
        with patch('dkss_app.priority_confirmed_projection.attach_confirmed_priority_inputs',
                side_effect=ValueError('CONFIRMED_PRIORITY_CANDIDATE_LIMIT')):
            response = c.client.get(c.api)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['error'], 'confirmation_limit')
        self.assertFalse(response.json['is_current'])
        self.assertEqual(job.result_json, original)
        self.assertEqual(response.json['result']['recommendations'][0]['priority'], '高')
        self.assertIsNone(response.json['result']['recommendations'][0]['priority_assessment']['effective_score'])
        with patch('dkss_app.analysis.get_vehicle_analysis_read_projection',
                side_effect=ValueError('CONFIRMED_PRIORITY_CANDIDATE_LIMIT')):
            normal = c.client.get(f'/vehicle/karte/{c.vehicle.id}/analysis/result')
        self.assertEqual(normal.status_code, 200)
        self.assertIn('一部だけに絞らず', normal.json['input_warning'])
