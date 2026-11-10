from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from itertools import product
import json
import unittest

from vehicle_priority_assessment import (
    Candidate, Evidence, Fact, InvalidInput, ProductionUseBlocked, Reference, Scope,
    TimingFact, assess_priority, build_shadow_projection, label_for_score, priority_sort_key,
)


DAY = date(2026, 11, 10)
SCOPE = Scope("synthetic-company", 1, "synthetic-brake")


def source(key="s1", **kwargs):
    fields = dict(source_id=key, scope=SCOPE, observed_on=DAY, event_id="event-1",
                  excerpt="Synthetic test fact, not a real vehicle record.", verified=True)
    fields.update(kwargs)
    return Evidence(**fields)


def ref(key="r1", **kwargs):
    fields = dict(reference_id=key, url="https://example.invalid/synthetic-rule",
                  issuer="Synthetic", title="Synthetic rule", version="test-only",
                  quote="Synthetic condition for testing, not manufacturer guidance.",
                  authority="manufacturer", verified=True, applicable=True)
    fields.update(kwargs)
    return Reference(**fields)


def fact(code, ids=("s1",), **kwargs):
    return Fact(code, ids, verified=True, **kwargs)


def timing(**kwargs):
    fields = dict(source_ids=("s1",), reference_ids=("r1",), calculation_permitted=True,
                  calculation_verified=True, origin_verified=True, combination_verified=True,
                  due_on=DAY)
    fields.update(kwargs)
    return TimingFact(**fields)


def candidate(*facts, **kwargs):
    fields = dict(candidate_id="proposal-1", scope=SCOPE, event_id="event-1", facts=tuple(facts), input_is_current=True)
    fields.update(kwargs)
    return Candidate(**fields)


def evaluate(item=None, sources=None, refs=None, **kwargs):
    return assess_priority(item or candidate(), sources if sources is not None else {"s1": source()},
                           refs if refs is not None else {"r1": ref()}, as_of=DAY, **kwargs)


def project(analysis, candidates, evidence, references, **kwargs):
    context = dict(as_of=DAY, company_code=SCOPE.company_code, vehicle_id=SCOPE.vehicle_id)
    context.update(kwargs)
    return build_shadow_projection(analysis, candidates, evidence, references, **context)


class BoundaryTests(unittest.TestCase):
    def test_label_boundaries(self):
        for score, expected in [(0, "低"), (24, "低"), (25, "中"), (59, "中"), (60, "高"), (100, "高")]:
            with self.subTest(score=score):
                self.assertEqual(label_for_score(score), expected)

    def test_label_rejects_non_scores(self):
        for score in [True, False, -1, 101, 25.0, None, float("nan"), "高"]:
            with self.subTest(score=score), self.assertRaises(InvalidInput):
                label_for_score(score)

    def test_timing_day_boundaries(self):
        for days, points in [(-1, 35), (0, 35), (1, 25), (30, 25), (31, 10)]:
            with self.subTest(days=days):
                result = evaluate(candidate(fact("preventive_plan"), timings=(timing(due_on=DAY + timedelta(days=days)),)))
                self.assertEqual(result["base_score"], points)

    def test_ratio_boundaries(self):
        for elapsed, points in [(0, 10), (8999, 10), (9000, 25), (9999, 25), (10000, 35), (10001, 35)]:
            with self.subTest(elapsed=elapsed):
                result = evaluate(candidate(fact("preventive_plan"), timings=(timing(
                    due_on=None, elapsed=elapsed, interval=10000, elapsed_unit="km", interval_unit="km"),)))
                self.assertEqual(result["base_score"], points)

    def test_all_point_combinations_have_three_labels_only(self):
        for impact, urgency, state in product((0, 10, 25, 40), (0, 10, 25, 35), (0, 10, 25)):
            score = impact + urgency + state
            self.assertIn(label_for_score(score), {"高", "中", "低"})

    def test_score_monotonicity(self):
        rank = {"低": 0, "中": 1, "高": 2}
        self.assertEqual([rank[label_for_score(i)] for i in range(101)],
                         sorted(rank[label_for_score(i)] for i in range(101)))


class EvidenceTests(unittest.TestCase):
    def test_missing_is_low_response_priority_not_safe_or_assessed_impact(self):
        result = evaluate()
        self.assertEqual(result["label"], "低")
        self.assertEqual(result["evidence_status"], "根拠不足")
        self.assertEqual(result["missing_axes"], ["impact", "timing", "state"])
        self.assertTrue(all(f["points"] is None for f in result["factors"]))
        self.assertFalse(result["safety_cleared"])
        self.assertEqual(result["operation_decision"], "human_only")

    def test_component_name_or_generic_risk_cannot_create_points(self):
        result = evaluate(candidate(), {"s1": source(excerpt="Brakes: generic danger and accident warning.")})
        self.assertEqual(result["base_score"], 0)
        self.assertEqual(result["applied_floors"], [])

    def test_unreviewed_ai_fact_does_not_score(self):
        result = evaluate(candidate(Fact("impact_safety", ("s1",))))
        self.assertEqual(result["base_score"], 0)
        self.assertEqual(len(result["ignored_facts"]), 1)

    def test_unreviewed_source_does_not_score(self):
        result = evaluate(candidate(fact("impact_safety")), {"s1": source(verified=False)})
        self.assertEqual(result["base_score"], 0)

    def test_missing_source_does_not_score(self):
        result = evaluate(candidate(fact("impact_safety", ("missing",))))
        self.assertEqual(result["base_score"], 0)

    def test_cross_scope_cannot_score(self):
        for scope in [replace(SCOPE, company_code="other"), replace(SCOPE, vehicle_id=2), replace(SCOPE, target="other")]:
            with self.subTest(scope=scope):
                result = evaluate(candidate(fact("impact_safety")), {"s1": source(scope=scope)})
                self.assertEqual(result["base_score"], 0)

    def test_same_component_different_event_cannot_be_combined(self):
        result = evaluate(candidate(fact("impact_safety"), fact("state_open", ("s2",))), {
            "s1": source(), "s2": source("s2", event_id="unrelated-event"),
        })
        self.assertEqual(result["base_score"], 40)
        self.assertIsNone(result["factors"][2]["points"])

    def test_missing_event_identity_cannot_bind_current_facts(self):
        result = evaluate(candidate(fact("impact_safety"), event_id=None))
        self.assertEqual(result["base_score"], 0)
        self.assertEqual(result["evidence_status"], "根拠不足")

    def test_past_negated_conditional_resolved_sources_cannot_be_current(self):
        for status in ["past", "negated", "conditional", "resolved", "released"]:
            with self.subTest(status=status):
                result = evaluate(candidate(fact("impact_safety"), fact("state_open")), {"s1": source(status=status)})
                self.assertEqual(result["base_score"], 0)

    def test_future_sources_do_not_score(self):
        result = evaluate(candidate(fact("impact_safety")), {"s1": source(observed_on=DAY + timedelta(days=1))})
        self.assertEqual(result["base_score"], 0)

    def test_old_unresolved_issue_is_not_discarded_just_because_old(self):
        result = evaluate(candidate(fact("safety_issue_open"), input_is_current=False),
                          {"s1": source(observed_on=DAY - timedelta(days=400), status="open")})
        self.assertEqual(result["label"], "中")
        self.assertTrue(any("最新性" in text for text in result["missing_conditions"]))

    def test_verified_later_resolution_suppresses_same_event(self):
        result = evaluate(candidate(fact("impact_safety"), fact("safety_issue_open")), {
            "s1": source(observed_on=DAY - timedelta(days=1), status="open"),
            "s2": source("s2", status="resolved"),
        })
        self.assertEqual(result["effective_score"], 0)

    def test_unreviewed_resolution_cannot_remove_safety_floor(self):
        result = evaluate(candidate(fact("safety_issue_open")), {
            "s1": source(observed_on=DAY - timedelta(days=1), status="open"),
            "s2": source("s2", status="resolved", verified=False),
        })
        self.assertEqual(result["label"], "中")

    def test_equal_day_conflict_retains_safety_floor_and_marks_uncertainty(self):
        result = evaluate(candidate(fact("safety_issue_open")), {
            "s1": source(status="open"), "s2": source("s2", status="resolved"),
        })
        self.assertEqual(result["label"], "中")
        self.assertTrue(any("矛盾" in text for text in result["missing_conditions"]))

    def test_resolution_of_other_event_cannot_remove_current_issue(self):
        result = evaluate(candidate(fact("safety_issue_open")), {
            "s1": source(observed_on=DAY - timedelta(days=1), status="open"),
            "s2": source("s2", event_id="other-event", status="resolved"),
        })
        self.assertEqual(result["label"], "中")

    def test_discrepancy_only_is_low_even_on_brakes(self):
        result = evaluate(candidate(fact("record_discrepancy")), {"s1": source(kind="reconciliation")})
        self.assertEqual(result["effective_score"], 0)
        self.assertEqual(result["evidence_status"], "記録不一致")
        self.assertTrue(all(f["points"] == 0 for f in result["factors"]))

    def test_new_safety_evidence_overrides_discrepancy_only(self):
        result = evaluate(candidate(fact("record_discrepancy"), fact("safety_issue_open", ("s2",))), {
            "s1": source(kind="reconciliation"), "s2": source("s2", status="open"),
        })
        self.assertEqual(result["label"], "中")
        self.assertNotEqual(result["evidence_status"], "記録不一致")


class SafetyFloorTests(unittest.TestCase):
    def test_specific_safety_unknown_gets_middle_floor(self):
        result = evaluate(candidate(fact("safety_issue_open"), missing_conditions=("測定結果を確認要",)))
        self.assertEqual(result["base_score"], 0)
        self.assertEqual(result["effective_score"], 25)
        self.assertEqual(result["floor_adjustment"], 25)
        self.assertIn("測定結果を確認要", result["missing_conditions"])

    def test_confirmed_required_safety_check_not_done_gets_middle(self):
        result = evaluate(candidate(fact("required_safety_check_not_done", reference_ids=("r1",))))
        self.assertEqual(result["label"], "中")

    def test_missing_check_record_is_not_confirmed_not_done(self):
        result = evaluate(candidate(fact("required_safety_check_not_done")))
        self.assertEqual(result["effective_score"], 0)

    def test_existing_active_operation_instruction_gets_high(self):
        result = evaluate(candidate(fact("operation_instruction_active")),
                          {"s1": source(kind="instruction", status="active")})
        self.assertEqual(result["effective_score"], 60)
        self.assertEqual(result["label"], "高")
        self.assertEqual(result["operation_decision"], "human_only")

    def test_ordinary_prose_cannot_become_operation_instruction(self):
        result = evaluate(candidate(fact("operation_instruction_active")))
        self.assertEqual(result["effective_score"], 0)

    def test_later_authoritative_release_removes_instruction_floor(self):
        result = evaluate(candidate(fact("operation_instruction_active")), {
            "s1": source(kind="instruction", status="active", observed_on=DAY - timedelta(days=1)),
            "s2": source("s2", kind="instruction", status="released"),
        })
        self.assertEqual(result["effective_score"], 0)

    def test_repair_record_cannot_release_operation_instruction(self):
        result = evaluate(candidate(fact("operation_instruction_active")), {
            "s1": source(kind="instruction", status="active", observed_on=DAY - timedelta(days=1)),
            "s2": source("s2", kind="record", status="resolved"),
        })
        self.assertEqual(result["label"], "高")

    def test_manufacturer_immediate_condition_with_vehicle_match_gets_high(self):
        result = evaluate(candidate(fact("manufacturer_immediate_condition", reference_ids=("r1",))),
                          refs={"r1": ref(immediate_action=True)})
        self.assertEqual(result["label"], "高")

    def test_generic_manufacturer_warning_is_not_immediate(self):
        result = evaluate(candidate(fact("manufacturer_immediate_condition", reference_ids=("r1",))))
        self.assertEqual(result["effective_score"], 0)

    def test_unverified_inapplicable_reference_cannot_support_floor(self):
        for changed in [dict(verified=False), dict(applicable=False), dict(quote=""), dict(authority="company")]:
            with self.subTest(changed=changed):
                result = evaluate(candidate(fact("manufacturer_immediate_condition", reference_ids=("r1",))),
                                  refs={"r1": ref(immediate_action=True, **changed)})
                self.assertEqual(result["effective_score"], 0)

    def test_ordinary_maintenance_due_is_middle_not_high(self):
        result = evaluate(candidate(fact("preventive_plan"), timings=(timing(),)))
        self.assertEqual(result["effective_score"], 35)
        self.assertEqual(result["label"], "中")

    def test_verified_legal_deadline_due_gets_high_review_priority(self):
        result = evaluate(candidate(fact("preventive_plan"), timings=(timing(legal_deadline=True),)),
                          refs={"r1": ref(authority="government")})
        self.assertEqual(result["base_score"], 35)
        self.assertEqual(result["effective_score"], 60)
        self.assertEqual(result["operation_decision"], "human_only")

    def test_manufacturer_reference_cannot_be_legal_deadline(self):
        result = evaluate(candidate(timings=(timing(legal_deadline=True),)))
        self.assertEqual(result["effective_score"], 0)

    def test_future_legal_deadline_is_not_immediate_high(self):
        result = evaluate(candidate(fact("preventive_plan"), timings=(timing(legal_deadline=True, due_on=DAY + timedelta(days=1)),)),
                          refs={"r1": ref(authority="government")})
        self.assertEqual(result["effective_score"], 25)

    def test_strongest_floor_wins_without_adding_floors(self):
        result = evaluate(candidate(fact("safety_issue_open"), fact("manufacturer_immediate_condition", reference_ids=("r1",))),
                          refs={"r1": ref(immediate_action=True)})
        self.assertEqual(result["effective_score"], 60)
        self.assertEqual(len(result["applied_floors"]), 2)


class TimingAndProgressTests(unittest.TestCase):
    def test_timing_requires_every_validation_flag(self):
        for name in ["calculation_permitted", "calculation_verified", "origin_verified", "combination_verified"]:
            with self.subTest(name=name):
                result = evaluate(candidate(timings=(timing(**{name: False}),)))
                self.assertEqual(result["base_score"], 0)
                self.assertIsNone(result["factors"][1]["points"])

    def test_timing_rejects_numeric_bool_verification(self):
        result = evaluate(candidate(timings=(timing(calculation_permitted=1),)))
        self.assertEqual(result["base_score"], 0)

    def test_invalid_ratios_cannot_be_due(self):
        for invalid in [dict(elapsed=-1), dict(elapsed=float("nan")), dict(elapsed=float("inf")),
                        dict(elapsed=True), dict(interval=0), dict(interval=-1), dict(interval=None),
                        dict(interval=float("inf")), dict(interval_unit="miles"), dict(elapsed_unit=None)]:
            fields = dict(due_on=None, elapsed=10000, interval=10000, elapsed_unit="km", interval_unit="km")
            fields.update(invalid)
            with self.subTest(invalid=invalid):
                result = evaluate(candidate(timings=(timing(**fields),)))
                self.assertEqual(result["base_score"], 0)

    def test_invalid_date_is_not_a_deadline(self):
        result = evaluate(candidate(timings=(timing(due_on="2026-11-10"),)))
        self.assertEqual(result["base_score"], 0)

    def test_empty_timing_is_unknown_not_zero_interval(self):
        result = evaluate(candidate(timings=(timing(due_on=None),)))
        self.assertIsNone(result["factors"][1]["points"])

    def test_earlier_of_verified_distance_or_date_controls(self):
        result = evaluate(candidate(fact("preventive_plan"), timings=(timing(
            due_on=DAY + timedelta(days=100), elapsed=11000, interval=10000, elapsed_unit="km", interval_unit="km"),)))
        self.assertEqual(result["base_score"], 35)

    def test_both_due_axes_count_once(self):
        result = evaluate(candidate(fact("preventive_plan"), timings=(timing(
            due_on=DAY, elapsed=11000, interval=10000, elapsed_unit="km", interval_unit="km"),)))
        self.assertEqual(result["base_score"], 35)

    def test_duplicate_facts_count_once_per_axis(self):
        result = evaluate(candidate(fact("impact_safety"), fact("impact_safety"), fact("state_open"), fact("state_open")))
        self.assertEqual(result["base_score"], 50)

    def test_recurrence_requires_distinct_resolved_previous_event(self):
        result = evaluate(candidate(fact("impact_safety"), fact("state_recurrent", baseline_source_ids=("old",), comparison_verified=True), event_id="new"), {
            "s1": source(event_id="new"), "old": source("old", event_id="old", observed_on=DAY - timedelta(days=10), status="resolved"),
        })
        self.assertEqual(result["effective_score"], 65)
        self.assertEqual(result["label"], "高")

    def test_same_event_duplicate_is_not_recurrence(self):
        result = evaluate(candidate(fact("state_recurrent", baseline_source_ids=("old",), comparison_verified=True)), {
            "s1": source(), "old": source("old", observed_on=DAY - timedelta(days=10), status="resolved"),
        })
        self.assertEqual(result["base_score"], 0)

    def test_unresolved_previous_event_is_not_recurrence_after_repair(self):
        result = evaluate(candidate(fact("state_recurrent", baseline_source_ids=("old",), comparison_verified=True), event_id="new"), {
            "s1": source(event_id="new"), "old": source("old", event_id="old", observed_on=DAY - timedelta(days=10), status="open"),
        })
        self.assertEqual(result["base_score"], 0)

    def test_comparison_requires_semantic_review(self):
        result = evaluate(candidate(fact("state_worsening", baseline_source_ids=("old",))), {
            "s1": source(), "old": source("old", observed_on=DAY - timedelta(days=10)),
        })
        self.assertEqual(result["base_score"], 0)

    def test_verified_worsening_can_be_same_issue_with_two_observations(self):
        result = evaluate(candidate(fact("state_worsening", baseline_source_ids=("old",), comparison_verified=True)), {
            "s1": source(), "old": source("old", observed_on=DAY - timedelta(days=10)),
        })
        self.assertEqual(result["base_score"], 25)


class IntegrationContractTests(unittest.TestCase):
    def test_shadow_only_with_no_production_enable_switch(self):
        for mode in ["production", "live", "approved", "", None]:
            with self.subTest(mode=mode), self.assertRaises(ProductionUseBlocked):
                evaluate(mode=mode)

    def test_metadata_explicitly_states_trial_nonproduction_and_human_decision(self):
        result = evaluate()
        self.assertEqual(result["policy_status"], "trial")
        self.assertFalse(result["production_enabled"])
        self.assertEqual(result["threshold_origin"], "system_trial_not_official")
        self.assertIn("試行値", result["disclaimer"])
        self.assertEqual(result["priority"], result["label"])
        self.assertNotIn("未評価", result["label"])

    def test_result_is_json_serializable(self):
        result = evaluate(candidate(fact("preventive_plan"), timings=(timing(),)))
        self.assertEqual(json.loads(json.dumps(result, ensure_ascii=False)), result)

    def test_repeated_evaluation_is_deterministic(self):
        item = candidate(fact("impact_safety"), fact("state_open"))
        self.assertEqual(evaluate(item), evaluate(item))

    def test_inputs_are_not_mutated(self):
        item = candidate(fact("safety_issue_open"))
        sources = {"s1": source()}
        refs = {"r1": ref()}
        before = deepcopy((item, sources, refs))
        evaluate(item, sources, refs)
        self.assertEqual((item, sources, refs), before)

    def test_irrelevant_other_vehicle_source_does_not_change_result(self):
        item = candidate(fact("impact_safety"))
        before = evaluate(item)
        after = evaluate(item, {"s1": source(), "other": source("other", scope=replace(SCOPE, vehicle_id=999))})
        self.assertEqual(before, after)

    def test_changed_source_bytes_change_fingerprint(self):
        item = candidate(fact("impact_safety"))
        before = evaluate(item)
        after = evaluate(item, {"s1": source(excerpt="Changed reviewed synthetic source.")})
        self.assertNotEqual(before["source_fingerprint"], after["source_fingerprint"])

    def test_sort_higher_priority_first(self):
        low = evaluate(candidate(candidate_id="low"))
        mid = evaluate(candidate(fact("safety_issue_open"), candidate_id="mid"))
        high = evaluate(candidate(fact("manufacturer_immediate_condition", reference_ids=("r1",)), candidate_id="high"), refs={"r1": ref(immediate_action=True)})
        self.assertEqual([r["candidate_id"] for r in sorted([mid, low, high], key=priority_sort_key)], ["high", "mid", "low"])

    def test_sort_existing_instruction_before_other_high_score(self):
        instruction = evaluate(candidate(fact("operation_instruction_active"), candidate_id="instruction"), {"s1": source(kind="instruction", status="active")})
        high_score = evaluate(candidate(fact("impact_safety"), fact("state_open"), timings=(timing(),), candidate_id="high_score"))
        self.assertGreater(high_score["effective_score"], instruction["effective_score"])
        self.assertEqual(sorted([high_score, instruction], key=priority_sort_key)[0]["candidate_id"], "instruction")

    def test_sort_known_due_before_unknown_then_stable_id(self):
        base = evaluate(candidate(fact("safety_issue_open")))
        unknown = {**base, "candidate_id": "a", "earliest_due_on": None}
        known = {**base, "candidate_id": "b", "earliest_due_on": "2026-11-15"}
        self.assertEqual(sorted([unknown, known], key=priority_sort_key)[0]["candidate_id"], "b")
        self.assertEqual(sorted([{**base, "candidate_id": "z"}, {**base, "candidate_id": "a"}], key=priority_sort_key)[0]["candidate_id"], "a")

    def test_invalid_scope_and_unknown_codes_rejected(self):
        for item in [candidate(scope=replace(SCOPE, vehicle_id=True)), candidate(scope=replace(SCOPE, company_code="")),
                     candidate(Fact("AI_says_high", ("s1",), verified=True))]:
            with self.subTest(item=item), self.assertRaises(InvalidInput):
                evaluate(item)

    def test_new_safety_fact_cannot_reduce_priority(self):
        original = candidate(fact("preventive_plan"), timings=(timing(),))
        updated = replace(original, facts=original.facts + (fact("impact_safety"), fact("state_open")))
        self.assertGreaterEqual(evaluate(updated)["effective_score"], evaluate(original)["effective_score"])

    def test_shadow_projection_preserves_priority_revision_feedback_and_order(self):
        original = {"recommendations": [
            {"proposal_id": "low", "proposal_revision": "original-1", "target": SCOPE.target,
             "priority": "高", "feedback": {"status": "completed"}, "source_ids": ["s1"],
             "risk_status": "unassessed", "risk": "機能への影響は未判定です。"},
            {"proposal_id": "mid", "proposal_revision": "original-2", "target": SCOPE.target, "priority": "低"},
        ]}
        before = deepcopy(original)
        candidates = {"low": candidate(candidate_id="low"),
                      "mid": candidate(fact("safety_issue_open"), candidate_id="mid")}
        output = project(original, candidates, {"s1": source()}, {})
        self.assertEqual(original, before)
        self.assertEqual(output["priority_preview_order"], ["mid", "low"])
        self.assertFalse(output["priority_preview_production_enabled"])
        for old, new in zip(original["recommendations"], output["recommendations"]):
            self.assertEqual({k: v for k, v in new.items() if k != "priority_preview"}, old)
            self.assertIn(new["priority_preview"]["label"], {"高", "中", "低"})

    def test_shadow_projection_requires_complete_mapping(self):
        analysis = {"recommendations": [{"proposal_id": "p", "proposal_revision": "v", "target": SCOPE.target}]}
        with self.assertRaises(InvalidInput):
            project(analysis, {}, {}, {})

    def test_shadow_projection_requires_original_identity_before_annotation(self):
        for item in [{"target": SCOPE.target}, {"proposal_id": "p", "target": SCOPE.target}]:
            with self.subTest(item=item), self.assertRaises(InvalidInput):
                project({"recommendations": [item]}, {}, {}, {})

    def test_shadow_projection_rejects_target_mismatch(self):
        analysis = {"recommendations": [{"proposal_id": "p", "proposal_revision": "v", "target": "other"}]}
        with self.assertRaises(InvalidInput):
            project(analysis, {"p": candidate(candidate_id="p")}, {}, {})

    def test_shadow_projection_allows_no_recommendations_without_inventing_work(self):
        output = project({"recommendations": []}, {}, {}, {})
        self.assertEqual(output["recommendations"], [])
        self.assertEqual(output["priority_preview_order"], [])

    def test_shadow_projection_rejects_other_host_company_or_vehicle(self):
        analysis = {"recommendations": [{"proposal_id": "p", "proposal_revision": "v", "target": SCOPE.target}]}
        for context in [dict(company_code="other"), dict(vehicle_id=2)]:
            with self.subTest(context=context), self.assertRaises(InvalidInput):
                project(analysis, {"p": candidate(candidate_id="p")}, {}, {}, **context)

    def test_shadow_projection_rejects_invalid_host_identity(self):
        for context in [dict(company_code=""), dict(vehicle_id=True), dict(vehicle_id=0)]:
            with self.subTest(context=context), self.assertRaises(InvalidInput):
                project({"recommendations": []}, {}, {}, {}, **context)


if __name__ == "__main__":
    unittest.main()
