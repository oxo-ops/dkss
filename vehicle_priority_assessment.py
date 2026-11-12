"""Non-production maintenance-response priority prototype.

No I/O, clock reads, network, database, model calls, or operation decisions.
Only a trusted normalization/review adapter may supply verified facts. Merely
matching a quote or copying an AI output does NOT verify a fact's meaning.
Trial points are not government/manufacturer thresholds or probabilities.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from typing import Mapping


METHOD = "maintenance-response-priority-trial-v0.1"
POLICY_VERSION = "trial-20261110"
MEDIUM_MIN = 25
HIGH_MIN = 60
NEAR_DAYS = 30
NEAR_RATIO = 0.90
DISCLAIMER = (
    "点数・区分境界・接近基準は本システムの試行値です。"
    "公的・メーカー規定の点数、故障確率、運行可否ではありません。"
    "低は安全確認済みを意味しません。本番利用は未承認です。"
)


class InvalidInput(ValueError):
    """Reject broken contracts rather than invent a fourth priority label."""


class ProductionUseBlocked(RuntimeError):
    """This independent prototype cannot be enabled in production."""


@dataclass(frozen=True)
class Scope:
    company_code: str
    vehicle_id: int
    target: str


@dataclass(frozen=True)
class Evidence:
    source_id: str
    scope: Scope
    observed_on: date
    event_id: str
    excerpt: str
    # Review is supplied by a trusted adapter; raw AI output is never trusted.
    verified: bool = False
    kind: str = "record"  # record, instruction, reconciliation
    status: str = "current"  # current, open, resolved, past, negated, conditional, active, released


@dataclass(frozen=True)
class Reference:
    reference_id: str
    url: str
    issuer: str
    title: str
    version: str
    quote: str
    authority: str  # manufacturer, government, company
    verified: bool = False
    applicable: bool = False
    immediate_action: bool = False


@dataclass(frozen=True)
class Fact:
    code: str
    source_ids: tuple[str, ...]
    verified: bool = False
    reference_ids: tuple[str, ...] = ()
    baseline_source_ids: tuple[str, ...] = ()
    comparison_verified: bool = False
    # A trusted adapter may attest precise same-day order; never reverses dates.
    comparison_order_verified: bool = False


@dataclass(frozen=True)
class TimingFact:
    source_ids: tuple[str, ...]
    reference_ids: tuple[str, ...]
    # The existing timing pipeline owns origin, applicability and interval rules.
    calculation_permitted: bool = False
    calculation_verified: bool = False
    origin_verified: bool = False
    combination_verified: bool = False
    due_on: date | None = None
    elapsed: float | None = None
    interval: float | None = None
    elapsed_unit: str | None = None
    interval_unit: str | None = None
    legal_deadline: bool = False


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    scope: Scope
    event_id: str | None = None
    facts: tuple[Fact, ...] = ()
    timings: tuple[TimingFact, ...] = ()
    missing_conditions: tuple[str, ...] = ()
    input_is_current: bool | None = None


IMPACT_POINTS = {"impact_minor": 10, "impact_functional": 25, "impact_safety": 40}
STATE_POINTS = {"state_open": 10, "state_worsening": 25, "state_recurrent": 25}
KNOWN_CODES = frozenset(IMPACT_POINTS) | frozenset(STATE_POINTS) | {
    "preventive_plan", "no_timing_required", "explicit_planned_action",
    "record_discrepancy", "safety_issue_open", "required_safety_check_not_done",
    "operation_instruction_active", "manufacturer_immediate_condition",
}
STATUSES = {"current", "open", "resolved", "past", "negated", "conditional", "active", "released"}


def label_for_score(score: int) -> str:
    if type(score) is not int or not 0 <= score <= 100:
        raise InvalidInput("score must be an integer in 0..100")
    return "高" if score >= HIGH_MIN else "中" if score >= MEDIUM_MIN else "低"


def _finite_nonnegative(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def _validate(candidate: Candidate, evidence: Mapping[str, Evidence],
              references: Mapping[str, Reference], as_of: date) -> None:
    scope = candidate.scope
    if (not candidate.candidate_id or not scope.company_code or not scope.target
            or type(scope.vehicle_id) is not int or scope.vehicle_id <= 0 or type(as_of) is not date):
        raise InvalidInput("candidate identity, scope and explicit date are required")
    if candidate.input_is_current is not None and type(candidate.input_is_current) is not bool:
        raise InvalidInput("input_is_current must be boolean or null")
    if candidate.event_id is not None and (not isinstance(candidate.event_id, str) or not candidate.event_id.strip()):
        raise InvalidInput("event_id must be a nonempty string or null")
    if any(not isinstance(v, str) or not v.strip() for v in candidate.missing_conditions):
        raise InvalidInput("missing_conditions must contain nonempty strings")
    for key, source in evidence.items():
        if key != source.source_id or not key or type(source.observed_on) is not date:
            raise InvalidInput("invalid evidence identity/date")
        if source.kind not in {"record", "instruction", "reconciliation"} or source.status not in STATUSES:
            raise InvalidInput("invalid evidence kind/status")
        if type(source.verified) is not bool or not source.event_id or not source.excerpt.strip():
            raise InvalidInput("invalid evidence verification/event/excerpt")
    for key, reference in references.items():
        if key != reference.reference_id or not key or reference.authority not in {"manufacturer", "government", "company"}:
            raise InvalidInput("invalid reference identity/authority")
        if any(type(flag) is not bool for flag in (reference.verified, reference.applicable, reference.immediate_action)):
            raise InvalidInput("reference flags must be booleans")
    for fact in candidate.facts:
        if fact.code not in KNOWN_CODES or type(fact.verified) is not bool or type(fact.comparison_verified) is not bool or type(fact.comparison_order_verified) is not bool:
            raise InvalidInput("unknown fact code or invalid verification")


def assess_priority(candidate: Candidate, evidence: Mapping[str, Evidence],
                    references: Mapping[str, Reference], *, as_of: date,
                    mode: str = "shadow") -> dict:
    """Return one deterministic high/middle/low label for a valid candidate.

    Missing/invalidly supported facts remain explicit. No model prose is parsed.
    mode is deliberately limited to shadow, with no hidden enable flag.
    """
    if mode != "shadow":
        raise ProductionUseBlocked("Trial only: real-case and expert validation is required before a separate production integration.")
    _validate(candidate, evidence, references, as_of)
    ignored: list[dict] = []
    accepted: list[Fact] = []
    used_ids: set[str] = set()
    used_refs: set[str] = set()
    source_conflicts: set[str] = set()
    missing = list(candidate.missing_conditions)

    def reviewed_sources(ids: tuple[str, ...], *, baseline: bool = False,
                         instruction: bool = False, reconciliation: bool = False) -> bool:
        if not ids:
            return False
        for sid in ids:
            source = evidence.get(sid)
            if (source is None or not source.verified or source.scope != candidate.scope
                    or source.observed_on > as_of):
                return False
            if baseline:
                if source.kind != "record" or source.status in {"negated", "conditional", "released"}:
                    return False
                continue
            # Same component is insufficient: do not combine an impact from one
            # finding with progression/urgency from an unrelated finding.
            if not candidate.event_id or source.event_id != candidate.event_id:
                return False
            if instruction:
                if source.kind != "instruction" or source.status != "active":
                    return False
                terminal = "released"
            elif reconciliation:
                if source.kind != "reconciliation" or source.status != "current":
                    return False
                terminal = "resolved"
            else:
                if source.kind != "record" or source.status not in {"current", "open"}:
                    return False
                terminal = "resolved"
            # A verified later event-specific resolution supersedes this fact.
            # Equal-day contradictions are not silently resolved in either direction.
            for newer in evidence.values():
                if (newer.verified and newer.scope == source.scope and newer.kind == source.kind
                        and newer.event_id == source.event_id and newer.status == terminal
                        and newer.observed_on <= as_of):
                    if newer.observed_on > source.observed_on:
                        return False
                    if newer.observed_on == source.observed_on:
                        source_conflicts.add(sid)
        return True

    def reviewed_references(ids: tuple[str, ...], *, immediate: bool = False,
                            legal: bool = False) -> bool:
        if not ids:
            return False
        for rid in ids:
            ref = references.get(rid)
            if (ref is None or not ref.verified or not ref.applicable or not ref.url
                    or not ref.issuer or not ref.title or not ref.version or not ref.quote):
                return False
            if immediate and (ref.authority != "manufacturer" or not ref.immediate_action):
                return False
            if legal and ref.authority != "government":
                return False
        return True

    for fact in candidate.facts:
        code = fact.code
        valid = fact.verified and reviewed_sources(
            fact.source_ids, instruction=code == "operation_instruction_active",
            reconciliation=code == "record_discrepancy")
        if fact.reference_ids:
            valid = valid and reviewed_references(fact.reference_ids)
        if code == "manufacturer_immediate_condition":
            valid = valid and reviewed_references(fact.reference_ids, immediate=True)
        if code == "required_safety_check_not_done":
            valid = valid and reviewed_references(fact.reference_ids)
        if code in {"state_worsening", "state_recurrent"}:
            valid = valid and fact.comparison_verified and reviewed_sources(fact.baseline_source_ids, baseline=True)
            if valid:
                current = [evidence[sid] for sid in fact.source_ids]
                previous = [evidence[sid] for sid in fact.baseline_source_ids]
                previous_day = max(s.observed_on for s in previous)
                current_day = min(s.observed_on for s in current)
                valid = ((previous_day < current_day or
                          (fact.comparison_order_verified is True and previous_day == current_day))
                         and not set(fact.source_ids) & set(fact.baseline_source_ids))
                if code == "state_recurrent":
                    valid = (valid and all(s.status == "resolved" for s in previous)
                             and not {s.event_id for s in current} & {s.event_id for s in previous})
        if not valid:
            ignored.append({"code": code, "reason": "根拠・適用条件・現在状態の確認要"})
            continue
        accepted.append(fact)
        used_ids.update(fact.source_ids + fact.baseline_source_ids)
        used_refs.update(fact.reference_ids)

    timing_results: list[dict] = []
    for index, timing in enumerate(candidate.timings):
        flags = (timing.calculation_permitted, timing.calculation_verified,
                 timing.origin_verified, timing.combination_verified, timing.legal_deadline)
        valid = all(type(v) is bool for v in flags) and all(flags[:4])
        valid = valid and reviewed_sources(timing.source_ids) and reviewed_references(
            timing.reference_ids, legal=timing.legal_deadline)
        points: list[int] = []
        if timing.due_on is not None:
            if type(timing.due_on) is not date:
                valid = False
            else:
                remaining = (timing.due_on - as_of).days
                points.append(35 if remaining <= 0 else 25 if remaining <= NEAR_DAYS else 10)
        ratio_present = any(v is not None for v in (
            timing.elapsed, timing.interval, timing.elapsed_unit, timing.interval_unit))
        if ratio_present:
            ratio_valid = (_finite_nonnegative(timing.elapsed) and _finite_nonnegative(timing.interval)
                           and timing.interval > 0 and timing.elapsed_unit == timing.interval_unit
                           and timing.elapsed_unit in {"km", "days", "months"})
            valid = valid and ratio_valid
            if ratio_valid:
                # Compare products instead of dividing, preserving exact 90% boundary.
                points.append(35 if timing.elapsed >= timing.interval
                              else 25 if timing.elapsed >= NEAR_RATIO * timing.interval else 10)
        if timing.legal_deadline and timing.due_on is None:
            valid = False
        if not valid or not points:
            ignored.append({"code": f"timing:{index}", "reason": "期限の計算・単位・起算・適用条件を確認要"})
            continue
        timing_results.append({"points": max(points), "source_ids": sorted(set(timing.source_ids)),
                               "reference_ids": sorted(set(timing.reference_ids)),
                               "due_on": timing.due_on.isoformat() if timing.due_on else None,
                               "legal_due": timing.legal_deadline and timing.due_on <= as_of})
        used_ids.update(timing.source_ids)
        used_refs.update(timing.reference_ids)

    codes = {fact.code for fact in accepted}
    preventive = "preventive_plan" in codes
    positive_codes = codes & (set(IMPACT_POINTS) | set(STATE_POINTS) | {
        "safety_issue_open", "required_safety_check_not_done", "operation_instruction_active",
        "manufacturer_immediate_condition", "explicit_planned_action"})
    discrepancy_only = "record_discrepancy" in codes and not positive_codes and not timing_results

    def factor(axis: str, choices: Mapping[str, int], default: int | None) -> dict:
        matches = [fact for fact in accepted if fact.code in choices]
        points = max((choices[fact.code] for fact in matches), default=default)
        return {"axis": axis, "points": points, "fact_codes": sorted({fact.code for fact in matches}),
                "source_ids": sorted({sid for fact in matches for sid in fact.source_ids}),
                "reference_ids": sorted({rid for fact in matches for rid in fact.reference_ids})}

    impact = factor("impact", IMPACT_POINTS, 0 if preventive or discrepancy_only else None)
    state = factor("state", STATE_POINTS, 0 if preventive or discrepancy_only else None)
    timing = factor("timing", {"explicit_planned_action": 10, "no_timing_required": 0},
                    0 if discrepancy_only else None)
    if timing_results:
        timing["points"] = max([row["points"] for row in timing_results]
                               + ([timing["points"]] if timing["points"] is not None else []))
        timing["source_ids"] = sorted(set(timing["source_ids"]) | {
            sid for row in timing_results for sid in row["source_ids"]})
        timing["reference_ids"] = sorted(set(timing["reference_ids"]) | {
            rid for row in timing_results for rid in row["reference_ids"]})
    factors = [impact, timing, state]
    floors: list[dict] = []
    for code, minimum in (("operation_instruction_active", HIGH_MIN),
                          ("manufacturer_immediate_condition", HIGH_MIN),
                          ("safety_issue_open", MEDIUM_MIN),
                          ("required_safety_check_not_done", MEDIUM_MIN)):
        matches = [fact for fact in accepted if fact.code == code]
        if matches:
            floors.append({"code": code, "minimum": minimum,
                           "source_ids": sorted({sid for fact in matches for sid in fact.source_ids}),
                           "reference_ids": sorted({rid for fact in matches for rid in fact.reference_ids})})
    for row in timing_results:
        if row["legal_due"]:
            floors.append({"code": "verified_legal_deadline_due", "minimum": HIGH_MIN,
                           "source_ids": row["source_ids"], "reference_ids": row["reference_ids"]})
    base_score = sum(f["points"] for f in factors if f["points"] is not None)
    effective_score = max([base_score] + [floor["minimum"] for floor in floors])
    missing_axes = [f["axis"] for f in factors if f["points"] is None]
    missing.extend(f"{axis}の根拠を確認要" for axis in missing_axes)
    missing.extend(row["reason"] for row in ignored)
    if source_conflicts:
        missing.append("同日・同一事象の未解消/解消記録が矛盾。現在状態を確認要")
    if candidate.input_is_current is not True:
        missing.append("入力の最新性を確認要。記録の古さだけで指摘や停止指示を解除しません")
    missing = sorted(set(missing))
    evidence_status = ("記録不一致" if discrepancy_only else "根拠不足" if not accepted and not timing_results
                       else "一部確認要" if missing else "根拠あり")
    priority = label_for_score(effective_score)
    observations = sorted({evidence[sid].observed_on.isoformat() for sid in used_ids})
    deadlines = sorted({row["due_on"] for row in timing_results if row["due_on"]})
    relevant_evidence = {key: asdict(value) for key, value in evidence.items() if value.scope == candidate.scope}
    referenced_ids = {rid for fact in candidate.facts for rid in fact.reference_ids} | {
        rid for timing_fact in candidate.timings for rid in timing_fact.reference_ids}
    source_hash = _digest({"evidence": relevant_evidence,
                           "references": {key: asdict(references[key]) for key in sorted(referenced_ids) if key in references}})
    return {
        "candidate_id": candidate.candidate_id, "scope": asdict(candidate.scope), "event_id": candidate.event_id,
        "method": METHOD, "policy_version": POLICY_VERSION, "policy_status": "trial",
        "production_enabled": False, "threshold_origin": "system_trial_not_official",
        "as_of": as_of.isoformat(), "label": priority, "priority": priority,
        "base_score": base_score, "effective_score": effective_score,
        "floor_adjustment": effective_score - base_score, "factors": factors,
        "applied_floors": floors, "evidence_status": evidence_status,
        "missing_axes": missing_axes, "missing_conditions": missing,
        "ignored_facts": ignored, "source_ids": sorted(used_ids),
        "reference_ids": sorted(used_refs), "source_fingerprint": source_hash,
        "evaluation_fingerprint": _digest({"candidate": asdict(candidate), "source_fingerprint": source_hash,
                                            "policy_version": POLICY_VERSION, "as_of": as_of}),
        "observed_on": observations[-1] if observations else None,
        "first_observed_on": observations[0] if observations else None,
        "earliest_due_on": deadlines[0] if deadlines else None,
        "requires_professional_review": bool(floors) or priority != "低" or bool(missing),
        "operation_decision": "human_only", "safety_cleared": False,
        "response_label": {"高": "判断・対応を優先", "中": "確認・対応を計画", "低": "通常管理・記録照合"}[priority],
        "disclaimer": DISCLAIMER,
    }


def priority_sort_key(result: Mapping) -> tuple:
    """Shared stable order; unknown dates are later, never invented as overdue."""
    rank = {"高": 0, "中": 1, "低": 2}[result["label"]]
    instruction = any(floor["code"] == "operation_instruction_active" for floor in result["applied_floors"])
    return (rank, not instruction, -result["effective_score"],
            result["earliest_due_on"] or "9999-12-31",
            result["first_observed_on"] or "9999-12-31", result["candidate_id"])


def build_shadow_projection(analysis: Mapping, candidates: Mapping[str, Candidate],
                            evidence: Mapping[str, Evidence], references: Mapping[str, Reference],
                            *, as_of: date, company_code: str, vehicle_id: int) -> dict:
    """Preview after the host has established its original proposal IDs/revisions.

    Preserve saved priority, ordering, risk fields, feedback and revision. Do not
    compute revision from this augmented projection or persist it as AI output.
    Every item requires an explicit normalization, even if it has no known facts.
    """
    if not company_code or type(vehicle_id) is not int or vehicle_id <= 0:
        raise InvalidInput("trusted host company/vehicle context is required")
    items = analysis.get("recommendations")
    if not isinstance(items, list):
        raise InvalidInput("recommendations must be a list")
    ids = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("proposal_id"), str) or not item["proposal_id"]:
            raise InvalidInput("host-assigned proposal_id required before shadow projection")
        if not isinstance(item.get("proposal_revision"), str) or not item["proposal_revision"]:
            raise InvalidInput("host-assigned proposal_revision required before shadow projection")
        ids.append(item["proposal_id"])
    if len(set(ids)) != len(ids) or set(candidates) != set(ids):
        raise InvalidInput("one explicit candidate per unique original proposal_id is required")
    output = deepcopy(dict(analysis))
    results = []
    for item in output["recommendations"]:
        current = candidates[item["proposal_id"]]
        if current.scope.company_code != company_code or current.scope.vehicle_id != vehicle_id:
            raise InvalidInput("candidate belongs to a different host company/vehicle")
        if current.candidate_id != item["proposal_id"] or current.scope.target != item.get("target"):
            raise InvalidInput("candidate identity and target must match the original proposal")
        result = assess_priority(current, evidence, references, as_of=as_of)
        item["priority_preview"] = result
        results.append(result)
    output["priority_preview_contract"] = METHOD
    output["priority_preview_order"] = [result["candidate_id"] for result in sorted(results, key=priority_sort_key)]
    output["priority_preview_production_enabled"] = False
    return output
