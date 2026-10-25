"""Analysis scheduling and token ownership contracts, without external APIs."""
from datetime import date, datetime, timedelta
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import test_workflow_regressions as workflow
from vehicle_analysis_service import (
    AnalysisComparisonSettings, VehicleAnalysisInputService,
    VehicleAnalysisQueueService, snapshot_hash,
)

UTC = ZoneInfo("UTC")
NOW = datetime(2026, 10, 25, 1, 0, tzinfo=UTC)


def fingerprints(important="important-1", routine="routine-1", history=True):
    return {"policy_version": 12, "important_hash": important,
            "routine_hash": routine, "has_important_history": history}


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class AnalysisServiceUnitTests(unittest.TestCase):
    def queue_state(self, *, previous=None, status="completed", input_hash=None,
                    due=None, token=None, lease=None):
        state = SimpleNamespace(result_json=json.dumps({"fingerprints": previous} if previous else {}),
            status=status, input_hash=input_hash, next_analysis_at=due, lease_token=token,
            lease_expires_at=lease, request_reason="previous reason", last_error="old error")
        repository = Mock()
        repository.get_or_create.return_value = state
        service = VehicleAnalysisQueueService(repository=repository, utc_now=lambda: NOW,
                                              parse_result=json.loads)
        return state, service

    def test_first_analysis_is_due_in_two_minutes(self):
        state, service = self.queue_state(status="pending")
        self.assertIs(service.queue(object(), {"_fingerprints": fingerprints()}), state)
        self.assertEqual(state.status, "pending")
        self.assertEqual(state.next_analysis_at, NOW + timedelta(minutes=2))
        self.assertEqual(state.request_reason, "初回分析")

    def test_routine_changes_use_next_three_am_in_japan(self):
        previous = fingerprints()
        state, service = self.queue_state(previous=previous)
        service.queue(object(), {"_fingerprints": fingerprints(routine="changed")})
        self.assertEqual(state.next_analysis_at, datetime(2026, 10, 25, 18, 0, tzinfo=UTC))
        self.assertEqual(state.request_reason, "走行距離・期限などの日次確認")

    def test_earlier_pending_due_is_preserved(self):
        due = NOW + timedelta(seconds=20)
        state, service = self.queue_state(previous=fingerprints(), status="pending", due=due)
        service.queue(object(), {"_fingerprints": fingerprints(important="changed")})
        self.assertEqual(state.next_analysis_at, due)

    def test_same_input_error_keeps_retry_and_reason(self):
        current = fingerprints()
        due = NOW + timedelta(hours=1)
        state, service = self.queue_state(status="error", input_hash=snapshot_hash(current), due=due)
        service.queue(object(), {"_fingerprints": current})
        self.assertEqual((state.status, state.next_analysis_at, state.request_reason),
                         ("error", due, "previous reason"))

    def test_same_input_active_lease_is_not_cleared(self):
        current = fingerprints()
        lease = NOW + timedelta(minutes=1)
        state, service = self.queue_state(status="running", input_hash=snapshot_hash(current),
                                         token="owned", lease=lease)
        service.queue(object(), {"_fingerprints": current})
        self.assertEqual((state.status, state.lease_token, state.lease_expires_at),
                         ("running", "owned", lease))

    def test_changed_input_keeps_active_worker_token(self):
        lease = NOW + timedelta(minutes=1)
        state, service = self.queue_state(previous=fingerprints(), status="running",
                                         token="owned", lease=lease)
        current = fingerprints(important="changed")
        service.queue(object(), {"_fingerprints": current})
        self.assertEqual(state.input_hash, snapshot_hash(current))
        self.assertEqual((state.status, state.lease_token, state.lease_expires_at),
                         ("running", "owned", lease))
        self.assertEqual(state.next_analysis_at, NOW + timedelta(minutes=2))

    def test_unchanged_saved_result_marks_completed_and_clears_stale_lease(self):
        current = fingerprints()
        state, service = self.queue_state(previous=current, status="running",
                                         token="expired", lease=NOW - timedelta(seconds=1))
        service.queue(object(), {"_fingerprints": current})
        self.assertEqual(state.status, "completed")
        self.assertIsNone(state.lease_token)
        self.assertIsNone(state.next_analysis_at)
        self.assertIsNone(state.last_error)

    def test_invalid_settings_are_rejected_and_supported_values_are_preserved(self):
        settings = AnalysisComparisonSettings.from_environ({
            "VEHICLE_KARTE_AI_PEER_REGISTRATION": " all_years ",
            "VEHICLE_KARTE_AI_PEER_INCLUDE_INACTIVE": " 1 ",
        })
        self.assertEqual(settings, AnalysisComparisonSettings("all_years", True))
        for env in ({"VEHICLE_KARTE_AI_PEER_REGISTRATION": "wrong"},
                    {"VEHICLE_KARTE_AI_PEER_INCLUDE_INACTIVE": "true"}):
            with self.assertRaises(ValueError):
                AnalysisComparisonSettings.from_environ(env)

    def test_leap_day_analysis_window_and_comparison_settings(self):
        repository = Mock()
        rows = SimpleNamespace(maintenance=[], operations=[], parts=[], defects=[], periodic=[])
        repository.load.return_value = rows
        summary = Mock(return_value={"summary": True})
        comparison = Mock(return_value={"comparison_scope": {}})
        output = Mock(return_value=({"payload": True}, {"sources": True}))
        vehicle = object()
        result = VehicleAnalysisInputService(
            repository=repository, build_summary=summary, read_comparison=comparison,
            build_payload=output, today=lambda: date(2024, 2, 29),
            read_settings=lambda: AnalysisComparisonSettings("same_year", False),
        ).build(vehicle)
        self.assertEqual(result, ({"payload": True}, {"sources": True}))
        self.assertEqual(summary.call_args.args[-2:], ("2022-02-28", "2024-02-29"))
        self.assertEqual(comparison.call_args.kwargs,
                         {"registration_scope": "same_year", "include_inactive": False})
        self.assertEqual(comparison.return_value["comparison_scope"]["condition_source"],
                         "automatic_analysis_configuration")


class AnalysisServiceDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)

    def setUp(self):
        workflow.WorkflowRegressionTests.setUp(self)
        self.payload = {"_fingerprints": fingerprints(), "coverage": {"records": 1},
                        "comparison": {"vehicle_count": 0}}
        state = self.m.VehicleKarteAnalysis(company_code="TEST", vehicle_record_id=self.vehicle.id,
            status="pending", input_hash=snapshot_hash(self.payload["_fingerprints"]),
            next_analysis_at=NOW - timedelta(seconds=1))
        self.m.db.session.add(state)
        self.m.db.session.commit()
        self.state_id = state.id

    tearDown = workflow.WorkflowRegressionTests.tearDown

    def state(self):
        self.m.db.session.expire_all()
        return self.m.db.session.get(self.m.VehicleKarteAnalysis, self.state_id)

    def run_job(self, ai=None, payload=None):
        with patch.object(self.m, "datetime") as clock, \
             patch.object(self.m, "get_vehicle_karte_analysis_job_data",
                          return_value=(payload or self.payload, {"source": "record"})) as loader, \
             patch.object(self.m, "analyze_vehicle_karte",
                          side_effect=ai or (lambda payload, on_progress: {"overview": "result", "recommendations": []})) as api:
            clock.now.return_value = NOW
            result = self.m.run_vehicle_karte_analysis_job(self.state_id)
        return result, loader, api

    def test_ai_completion_renews_lease_and_saves_expected_bundle(self):
        def ai(payload, on_progress):
            on_progress()
            self.assertEqual(aware(self.state().lease_expires_at), NOW + timedelta(minutes=3))
            return {"overview": "result", "recommendations": []}
        result, _, api = self.run_job(ai)
        self.assertTrue(result)
        api.assert_called_once()
        state = self.state()
        self.assertEqual(state.status, "completed")
        self.assertIsNone(state.lease_token)
        self.assertIsNone(state.next_analysis_at)
        self.assertEqual(aware(state.last_analyzed_at), NOW)
        bundle = json.loads(state.result_json)
        self.assertEqual(bundle["generated_at"], "2026/10/25 10:00")
        self.assertEqual(bundle["fingerprints"], self.payload["_fingerprints"])
        self.assertEqual(bundle["analysis_method"], "ai")

    def test_no_important_history_uses_record_check_without_api(self):
        payload = dict(self.payload, _fingerprints=fingerprints(history=False))
        result, _, api = self.run_job(payload=payload)
        self.assertTrue(result)
        api.assert_not_called()
        state = self.state()
        self.assertIsNone(state.last_analyzed_at)
        self.assertEqual(json.loads(state.result_json)["analysis_method"], "record_check")

    def test_not_due_or_active_lease_does_not_build_input_or_call_api(self):
        for fields in ({"next_analysis_at": NOW + timedelta(minutes=1)},
                       {"next_analysis_at": NOW - timedelta(minutes=1), "status": "running",
                        "lease_token": "another", "lease_expires_at": NOW + timedelta(minutes=2)}):
            with self.subTest(fields=fields):
                self.m.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update(fields)
                self.m.db.session.commit()
                result, loader, api = self.run_job()
                self.assertFalse(result)
                loader.assert_not_called()
                api.assert_not_called()

    def test_expired_running_job_can_be_reclaimed(self):
        state = self.state()
        state.status, state.lease_token = "running", "expired"
        state.lease_expires_at = NOW - timedelta(seconds=1)
        self.m.db.session.commit()
        self.assertTrue(self.run_job()[0])
        self.assertEqual(self.state().status, "completed")

    def test_missing_state_does_not_build_input(self):
        self.state_id = 99999
        result, loader, api = self.run_job()
        self.assertFalse(result)
        loader.assert_not_called()
        api.assert_not_called()

    def test_foreign_target_or_inactive_vehicle_is_skipped_without_api(self):
        for company, deleted in (("OTHER", False), ("TEST", True)):
            with self.subTest(company=company, deleted=deleted):
                self.m.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
                    "company_code": company, "status": "pending",
                    "next_analysis_at": NOW - timedelta(seconds=1)})
                self.vehicle.deleted = deleted
                self.m.db.session.commit()
                result, loader, api = self.run_job()
                self.assertTrue(result)
                loader.assert_not_called()
                api.assert_not_called()
                self.assertEqual(self.state().status, "skipped")

    def test_error_keeps_previous_result_redacts_key_and_retries_in_one_hour(self):
        state = self.state()
        state.result_json = '{"analysis":{"overview":"previous"}}'
        self.m.db.session.commit()
        key = "FAKE_KEY_FOR_REDACTION_TEST"
        def ai(payload, on_progress):
            raise ValueError("failed: " + key)
        with patch.dict("os.environ", {"OPENAI_API_KEY": key}), \
             self.assertLogs(self.m.app.logger, level="WARNING") as logs:
            result, _, _ = self.run_job(ai)
        self.assertFalse(result)
        state = self.state()
        self.assertEqual(state.status, "error")
        self.assertEqual(aware(state.next_analysis_at), NOW + timedelta(hours=1))
        self.assertIsNone(state.lease_token)
        self.assertNotIn(key, state.last_error)
        self.assertNotIn(key, "\n".join(logs.output))
        self.assertIn("[REDACTED]", state.last_error)
        self.assertEqual(json.loads(state.result_json)["analysis"]["overview"], "previous")

    def test_input_changed_during_ai_retains_new_hash_and_requeues(self):
        def ai(payload, on_progress):
            self.m.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({"input_hash": "new-input"})
            self.m.db.session.commit()
            return {"overview": "old-input-result", "recommendations": []}
        self.assertTrue(self.run_job(ai)[0])
        state = self.state()
        self.assertEqual((state.status, state.input_hash), ("pending", "new-input"))
        self.assertEqual(aware(state.next_analysis_at), NOW + timedelta(minutes=2))
        self.assertIsNone(state.lease_token)

    def test_new_lease_owner_result_cannot_be_overwritten(self):
        def ai(payload, on_progress):
            self.m.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
                "lease_token": "new-owner", "result_json": '{"winner":true}'})
            self.m.db.session.commit()
            return {"overview": "stale-result", "recommendations": []}
        self.assertFalse(self.run_job(ai)[0])
        state = self.state()
        self.assertEqual(state.lease_token, "new-owner")
        self.assertEqual(json.loads(state.result_json), {"winner": True})

    def test_lost_lease_error_cannot_mark_the_new_owner_as_failed(self):
        def ai(payload, on_progress):
            self.m.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
                "lease_token": "new-owner", "result_json": '{"winner":true}'})
            self.m.db.session.commit()
            on_progress()
            raise AssertionError("unreachable")
        with self.assertLogs(self.m.app.logger, level="WARNING"):
            self.assertFalse(self.run_job(ai)[0])
        state = self.state()
        self.assertEqual((state.status, state.lease_token), ("running", "new-owner"))
        self.assertEqual(json.loads(state.result_json), {"winner": True})

    def test_queue_leaves_outer_commit_to_caller(self):
        with patch.object(self.m, "datetime") as clock, patch.object(self.m.db.session, "commit") as commit:
            clock.now.return_value = NOW
            self.m.queue_vehicle_karte_analysis(self.vehicle, {"_fingerprints": fingerprints(important="new")})
            commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
