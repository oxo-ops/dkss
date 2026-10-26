"""Saved AI results, current records and display filters must remain distinguishable."""
import json
import os
import unittest
from unittest.mock import patch
from test_workflow_regressions import WorkflowRegressionTests as _Base


class AnalysisResultConsistencyTests(unittest.TestCase):
    setUpClass = classmethod(_Base.setUpClass.__func__)
    tearDownClass = classmethod(_Base.tearDownClass.__func__)
    setUp = _Base.setUp
    tearDown = _Base.tearDown

    def payload(self):
        with self.m.app.test_request_context('/'):
            return self.m.get_vehicle_karte_analysis_job_data(self.vehicle)

    def result(self):
        return self.client.get(f'/vehicle/karte/{self.vehicle.id}/analysis/result')

    def saved_result(self):
        m = self.m
        record = m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            content='ブレーキ調整', entry_date='2026-10-21')
        m.db.session.add(record); m.db.session.commit()
        payload, sources = self.payload()
        proposal = dict(priority='中', category='整備・点検', target='ブレーキ',
            current_state='作業後の状態は未確認', title='ブレーキの確認', timing='次回運行前',
            action='実車の状態を確認', reason='調整後の確認結果が未登録',
            confirmation_steps=['担当者が記録と実車を確認'], confirmation_branch='異常があれば担当者へ連絡',
            uncertainty='実車は未確認', basis_type='記録上の指摘・対応', knowledge_ids=[],
            source_ids=[f'maintenance:{record.id}'])
        state = m.VehicleKarteAnalysis(company_code='TEST', vehicle_record_id=self.vehicle.id, status='completed',
            result_json=json.dumps(dict(analysis=dict(overview='保存された概要', recommendations=[proposal]),
                fingerprints=payload['_fingerprints'], sources=sources, comparison=payload['comparison'],
                generated_at='2026/10/25 09:00'), ensure_ascii=False, default=str))
        m.db.session.add(state); m.db.session.commit()
        key, revision = m.vehicle_analysis_proposal_ids(proposal)
        return record, state, dict(proposal_id=key, proposal_revision=revision, status='in_progress', comment='確認予定')

    def test_first_analysis_counts_do_not_require_a_saved_result_or_ai_call(self):
        m = self.m
        m.db.session.add(m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            content='整備', entry_date='2026-10-21'))
        m.db.session.add(m.VehicleMaintenanceRecord(company_code='OTHER', vehicle_record_id=self.vehicle.id,
            content='他社', entry_date='2026-10-21'))
        m.db.session.commit()
        with patch.object(m, 'analyze_vehicle_karte') as ai:
            response = self.result()
        data = response.json
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data['has_result'])
        self.assertIsNone(data['is_current'])
        self.assertEqual(data['input_summary'], dict(daily_inspections=0, periodic_inspections=0, maintenance=1, parts=0))
        self.assertIsNotNone(data['scheduled_comparison'])
        ai.assert_not_called()
        self.assertEqual(m.VehicleKarteAnalysis.query.count(), 0)

    def test_empty_vehicle_reports_zero_counts(self):
        self.assertEqual(set(self.result().json['input_summary'].values()), {0})

    def test_stale_result_keeps_overview_evidence_and_previous_scope(self):
        record, state, body = self.saved_result()
        self.assertTrue(self.result().json['is_current'])
        record.content = '修正後の整備'; self.m.db.session.commit()
        for status in ('completed', 'pending', 'running', 'error'):
            state.status = status; self.m.db.session.commit()
            data = self.result().json
            self.assertFalse(data['is_current'])
            self.assertEqual(data['analysis']['overview'], '保存された概要')
            self.assertIn(f'maintenance:{record.id}', data['sources'])
            self.assertEqual(data['comparison'], json.loads(state.result_json)['comparison'])

    def test_feedback_rejects_changed_input_and_pending_result_without_writes(self):
        record, state, body = self.saved_result()
        url = f'/vehicle/karte/{self.vehicle.id}/analysis/feedback'
        record.content = '更新済み'; self.m.db.session.commit()
        self.assertEqual(self.client.post(url, json=body).status_code, 409)
        record.content = 'ブレーキ調整'; state.status = 'pending'; self.m.db.session.commit()
        self.assertEqual(self.client.post(url, json=body).status_code, 409)
        self.assertEqual(self.m.VehicleAnalysisFeedback.query.count(), 0)

    def test_feedback_accepts_current_completed_result(self):
        record, state, body = self.saved_result()
        self.assertEqual(self.client.post(f'/vehicle/karte/{self.vehicle.id}/analysis/feedback', json=body).status_code, 200)
        self.assertEqual(self.m.VehicleAnalysisFeedback.query.count(), 1)

    def test_display_filters_do_not_relabel_saved_ai_scope(self):
        record, state, body = self.saved_result()
        before = json.loads(state.result_json)['comparison']
        with patch.dict(os.environ, {'VEHICLE_KARTE_AI_PEER_REGISTRATION': 'all_years', 'VEHICLE_KARTE_AI_PEER_INCLUDE_INACTIVE': '1'}):
            data = self.result().json
        self.assertEqual(data['comparison'], before)
        self.assertEqual(data['scheduled_comparison']['registration_scope'], 'all_years')
        self.assertTrue(data['scheduled_comparison']['include_inactive'])
        self.assertFalse(data['is_current'])
        page = self.client.get(f'/vehicle/karte/{self.vehicle.id}/analysis?start_date=2026-01-01&end_date=2026-10-21&peer_registration=all_years&peer_inactive=1')
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn('type="hidden" name="peer_registration" value="all_years"', text)
        self.assertIn('type="hidden" name="peer_inactive" value="1"', text)
        self.assertEqual(self.result().json['comparison'], before)

    def test_foreign_vehicle_cannot_read_counts_or_conditions(self):
        foreign = self.m.Vehicle(company_code='OTHER', chassis_number='OTHER-001')
        self.m.db.session.add(foreign); self.m.db.session.commit()
        self.assertEqual(self.client.get(f'/vehicle/karte/{foreign.id}/analysis/result').status_code, 404)


del _Base
