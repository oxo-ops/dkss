"""Real authenticated/CSRF routes and immutable audit; source provider only mocked.

Provider-specific tests separately run original-data readers. These tests target
transaction/replay/ownership boundaries without introducing AI or production IO.
"""
from copy import deepcopy
from datetime import datetime
import json
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_video_connected_flows as flows
from dkss_app import priority_confirmations as confirmations
from vehicle_priority_inputs import fingerprint


class PriorityConfirmationWorkflowTests(unittest.TestCase):
    setUpClass = classmethod(flows.ConnectedInspectionFlowTests.setUpClass.__func__)
    tearDownClass = classmethod(flows.ConnectedInspectionFlowTests.tearDownClass.__func__)
    tearDown = flows.ConnectedInspectionFlowTests.tearDown
    login = flows.ConnectedInspectionFlowTests.login
    request = flows.ConnectedInspectionFlowTests.request
    begin_priority = flows.ConnectedInspectionFlowTests.begin_priority
    save = flows.ConnectedInspectionFlowTests.save
    complete = flows.ConnectedInspectionFlowTests.complete
    decision_data = flows.ConnectedInspectionFlowTests.decision_data
    decide = flows.ConnectedInspectionFlowTests.decide
    state = flows.ConnectedInspectionFlowTests.state
    configure_dashboard = flows.ConnectedInspectionFlowTests.configure_dashboard

    def setUp(self):
        flows.ConnectedInspectionFlowTests.setUp(self)
        self.begin_priority(); self.decide('運行可'); self.login('admin')
        self.api = f'/vehicle/karte/{self.vehicle.id}/priority-confirmations'
        self.selection = {'current_observation': 'synthetic-explicit-selection'}
        self.provider = patch.object(confirmations, '_provider', return_value=(self.options, self.preview))
        self.provider.start(); self.addCleanup(self.provider.stop)

    def options(self, vehicle, *, as_of):
        return {'fields': [{'key': 'current_observation', 'label': '元観測', 'type': 'select',
                           'options': [{'value': self.selection['current_observation'], 'label': '合成観測'}]}],
                'missing_conditions': []}

    def preview(self, vehicle, selection, *, as_of):
        if selection != self.selection:
            raise ValueError('元記録を選んでください')
        source = {'vehicle_id': vehicle.id, 'company_code': vehicle.company_code,
                  'result_id': self.row.id, 'original': self.db.session.get(self.models.VehicleChecklistResult, self.row.id).operation_judgment_json}
        value = dict(kind='progression', selection=dict(selection), subject='元記録の比較',
            source_ids=[f'inspection:{self.row.id}'], sources=source,
            statements=[{'key': 'same', 'label': '同じ対象を確認しました'}, {'key': 'actual', 'label': '実際の現車を確認しました'}])
        value['fingerprint'] = fingerprint(value)
        return value

    def prepare_token(self, **extra):
        response = self.client.post(self.api + '/preview', json=dict(kind='progression', selection=self.selection, **extra))
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.json['token']

    def save_confirmation(self, token=None):
        return self.client.post(self.api, json={'token': token or self.prepare_token(), 'statements': ['same', 'actual']})

    def events(self):
        return self.models.ChecklistEvent.query.filter_by(result_type=confirmations.RESULT_TYPE).order_by(self.models.ChecklistEvent.id).all()

    def business(self):
        return {name: [tuple(getattr(row, c.name) for c in getattr(self.models, name).__table__.columns)
                       for row in getattr(self.models, name).query.order_by(getattr(self.models, name).id)]
                for name in ('VehicleChecklistResult', 'Notification', 'VehicleMaintenanceRecord', 'VehicleKarteAnalysis', 'VehicleAnalysisFeedback')}

    def test_optional_preview_saves_nothing_and_confirmation_changes_audit_only(self):
        before = self.business(); old_events = self.models.ChecklistEvent.query.filter_by(result_type='vehicle').count()
        self.assertEqual(self.client.get(self.api).status_code, 200)
        token = self.prepare_token()
        self.assertEqual(self.events(), [])
        self.assertEqual(self.business(), before)
        response = self.save_confirmation(token)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIn('次回の通常分析の入力', response.json['message'])
        self.assertIn('分析が正常に完了すると', response.json['message'])
        self.assertIn('AIの採否にかかわらず対応候補へ補完', response.json['message'])
        event = self.events()[0]; detail = json.loads(event.detail_json)
        self.assertEqual(event.event_type, confirmations.CONFIRM)
        self.assertEqual(event.result_id, self.vehicle.id)
        self.assertEqual(event.actor_identity, detail['actor']['identity'])
        self.assertEqual(event.actor_user_id, detail['actor']['user_id'])
        self.assertEqual(detail['statements'], ['same', 'actual'])
        self.assertEqual(len(confirmations.active_priority_confirmations(self.vehicle)), 1)
        self.assertEqual(self.models.ChecklistEvent.query.filter_by(result_type='vehicle').count(), old_events)
        self.assertEqual(self.business(), before)
        self.assertEqual(self.state()['status'], '運行可')

    def test_replay_parallel_preview_and_changed_source_are_conflicts(self):
        first, second = self.prepare_token(), self.prepare_token()
        self.assertEqual(self.save_confirmation(first).status_code, 200)
        self.assertEqual(self.save_confirmation(first).status_code, 409)
        self.assertEqual(self.save_confirmation(second).status_code, 409)
        fresh = self.prepare_token()
        self.row.operation_judgment_json = json.dumps({**self.state(), 'reason': '元記録が変わった'})
        self.db.session.commit()
        self.assertEqual(self.save_confirmation(fresh).status_code, 409)
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(confirmations.confirmation_statuses(self.vehicle)[0]['status'], 'held')

    def test_unchecked_or_forged_token_never_registers_a_fact(self):
        token = self.prepare_token()
        for keys in ([], ['same'], ['same', 'same'], ['same', 'actual', 'forged']):
            self.assertEqual(self.client.post(self.api, json={'token': token, 'statements': keys}).status_code, 409)
        self.assertEqual(self.save_confirmation(token + 'x').status_code, 409)
        self.assertEqual(self.events(), [])

    def test_owner_company_permission_and_revoked_identity_cannot_reuse_token(self):
        token = self.prepare_token()
        for username, company in [('checker', 'A'), ('checker', 'B')]:
            self.login(username, company)
            self.assertIn(self.save_confirmation(token).status_code, (403, 404))
        self.login('admin')
        with self.client.session_transaction() as stored:
            stored['account_identity'] = 'replaced-account'
        self.assertIn(self.save_confirmation(token).status_code, (302, 401))
        self.assertEqual(self.events(), [])

    def test_cancel_preserves_audit_and_never_resolves_original_inspection(self):
        before = self.business()
        self.assertEqual(self.save_confirmation().status_code, 200)
        original = self.events()[0].detail_json
        state = self.client.get(self.api).json
        token = state['history'][0]['cancel_token']
        self.assertEqual(self.client.post(self.api, json={'token': token}).status_code, 200)
        self.assertEqual(self.events()[0].detail_json, original)
        self.assertEqual([r.event_type for r in self.events()], [confirmations.CONFIRM, confirmations.WITHDRAW])
        self.assertEqual(confirmations.confirmation_statuses(self.vehicle)[0]['status'], 'withdrawn')
        self.assertEqual(confirmations.active_priority_confirmations(self.vehicle), [])
        self.assertEqual(self.client.post(self.api, json={'token': token}).status_code, 409)
        self.assertEqual(self.business(), before)

    def test_correction_withdraws_and_reconfirms_in_one_transaction(self):
        self.assertEqual(self.save_confirmation().status_code, 200)
        first = self.events()[0]; before = first.detail_json
        token = self.prepare_token(replace_event_id=first.id)
        self.assertEqual(self.save_confirmation(token).status_code, 200)
        self.assertEqual(self.events()[0].detail_json, before)
        self.assertEqual([r.event_type for r in self.events()], [confirmations.CONFIRM, confirmations.WITHDRAW, confirmations.CONFIRM])
        self.assertEqual([v['status'] for v in confirmations.confirmation_statuses(self.vehicle)], ['withdrawn', 'active'])

    def test_missing_historical_identity_is_not_backfilled_from_current_account(self):
        self.assertEqual(self.save_confirmation().status_code, 200)
        event = self.events()[0]
        event.actor_identity = None; self.db.session.commit()
        self.assertEqual(confirmations.active_priority_confirmations(self.vehicle), [])
        self.assertIsNone(self.db.session.get(self.models.ChecklistEvent, event.id).actor_identity)

    def test_dedicated_audit_is_excluded_from_existing_dashboard_and_check_counts(self):
        from flask import template_rendered
        self.configure_dashboard()
        def context():
            captured = {}
            def receive(sender, template, context, **extra):
                if template.name == 'index.html':
                    for key in ('my_safe_days', 'my_good_count', 'my_pending_pointouts', 'checklist_score_summaries',
                                'my_checklist_summaries', 'dashboard_safety_attention', 'dashboard_request_counts',
                                'dashboard_office_check_trend'):
                        captured[key] = deepcopy(context[key])
            template_rendered.connect(receive, self.app)
            try:
                self.assertEqual(self.client.get('/').status_code, 200)
            finally:
                template_rendered.disconnect(receive, self.app)
            return captured
        before = context()
        self.assertEqual(self.save_confirmation().status_code, 200)
        self.assertEqual(context(), before)
        token = self.client.get(self.api).json['history'][0]['cancel_token']
        self.assertEqual(self.client.post(self.api, json={'token': token}).status_code, 200)
        self.assertEqual(context(), before)

    def test_new_observation_retains_offset_without_backfilling_old_records(self):
        defect = self.state()['defects'][0]
        value = datetime.fromisoformat(defect['reported_at_iso'])
        self.assertIsNotNone(value.utcoffset())
        self.assertEqual(value.strftime('%Y-%m-%d %H:%M:%S'), defect['reported_at'])
        original = deepcopy(self.state())
        del original['defects'][0]['reported_at_iso']
        self.row.operation_judgment_json = json.dumps(original); self.db.session.commit()
        self.client.get(self.api)
        self.assertNotIn('reported_at_iso', self.state()['defects'][0])

    def test_confirmation_and_cancellation_invalidate_normal_analysis_and_old_feedback(self):
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        bundle, saved = flows.priority.PriorityStage2WorkflowTests.generate(self)
        api = f'/vehicle/karte/{self.vehicle.id}/analysis/result'
        response = self.client.get(api).json
        self.assertTrue(response['is_current'])
        item = response['analysis']['recommendations'][0]
        original = saved.result_json
        self.assertEqual(self.save_confirmation().status_code, 200)
        changed = self.client.get(api).json
        self.assertFalse(changed['is_current'])
        self.assertEqual(saved.result_json, original)
        answer = dict(status='accepted', proposal_id=item['proposal_id'], proposal_revision=item['proposal_revision'])
        self.assertEqual(self.client.post(api.replace('/result', '/feedback'), json=answer).status_code, 409)
        with self.app.test_request_context('/'):
            after_confirmation, _ = get_vehicle_karte_analysis_job_data(self.vehicle)
        self.assertNotEqual(bundle['fingerprints']['important_hash'], after_confirmation['_fingerprints']['important_hash'])
        cancel = self.client.get(self.api).json['history'][0]['cancel_token']
        self.assertEqual(self.client.post(self.api, json={'token': cancel}).status_code, 200)
        with self.app.test_request_context('/'):
            after_cancellation, _ = get_vehicle_karte_analysis_job_data(self.vehicle)
        self.assertNotEqual(after_confirmation['_fingerprints']['important_hash'], after_cancellation['_fingerprints']['important_hash'])
        self.assertEqual(saved.result_json, original)
        self.assertEqual(self.client.post(api.replace('/result', '/feedback'), json=answer).status_code, 409)

    def test_two_concurrent_submissions_create_only_one_confirmation(self):
        from concurrent.futures import ThreadPoolExecutor
        token = self.prepare_token()
        with self.client.session_transaction() as stored:
            identity = dict(stored)
        def submit(_):
            client = self.app.test_client()
            with client.session_transaction() as stored:
                stored.update(identity)
            return client.post(self.api, json={'token': token, 'statements': ['same', 'actual']}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(submit, range(2)))
        self.assertEqual(sorted(statuses), [200, 409])
        self.db.session.expire_all()
        self.assertEqual(len(self.events()), 1)

    def test_existing_csrf_guard_rejects_missing_token_before_mutation(self):
        original = self.app.config['WTF_CSRF_ENABLED']
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.addCleanup(lambda: self.app.config.update(WTF_CSRF_ENABLED=original))
        response = self.client.post(self.api + '/preview', json={'kind': 'progression', 'selection': self.selection})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.events(), [])


    def test_provider_internal_errors_do_not_reach_data_or_preview_response(self):
        private = 'SYNTHETIC_PRIVATE /internal/config.py database-password'
        for kind in (ValueError, TypeError):
            with self.subTest(kind=kind.__name__, route='data'):
                with patch.object(confirmations, '_rows', side_effect=kind(private)):
                    response = self.client.get(self.api)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json['message'], '選択した元記録を表示できません。')
                self.assertNotIn(private, response.get_data(as_text=True))
        for kind in (ValueError, TypeError, KeyError):
            with self.subTest(kind=kind.__name__, route='preview'):
                with patch.object(confirmations, '_checked_preview', side_effect=kind(private)):
                    response = self.client.post(self.api + '/preview', json=dict(kind='progression', selection=self.selection))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json['message'], '元記録の選択を確認してください。')
                self.assertNotIn(private, response.get_data(as_text=True))
        self.assertEqual(self.events(), [])

    def test_internal_save_error_is_private_and_rolls_back(self):
        private = 'SYNTHETIC_PRIVATE database-password SELECT internal'
        before = self.business()
        for kind in (ValueError, TypeError, KeyError):
            token = self.prepare_token()
            with self.subTest(kind=kind.__name__):
                with patch.object(confirmations, '_checked_preview', side_effect=kind(private)):
                    response = self.save_confirmation(token)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json['message'], '確認画面の有効期限が切れました。開き直してください。')
                self.assertNotIn(private, response.get_data(as_text=True))
                self.assertEqual(self.events(), [])
                self.assertEqual(self.business(), before)

    def test_authored_validation_reason_remains_actionable(self):
        message = '元記録の選択を確認してください。'
        with patch.object(confirmations, '_checked_preview', side_effect=ValueError(message)):
            response = self.client.post(self.api + '/preview', json=dict(kind='progression', selection=self.selection))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json['message'], message)
        token = self.prepare_token()
        response = self.client.post(self.api, json={'token': token, 'statements': []})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['message'], '表示された事実確認をすべて確認してから登録してください。')
        self.assertEqual(self.events(), [])
