"""Opt-in, synthetic-only priority preview on the existing read API.

The normal application, saved analysis and operation decisions are unchanged.
No models, jobs, read-cache refreshes, database writes or external calls occur.
Normalized synthetic inputs are registered in process by an isolated test/demo;
they cannot be supplied or approved through query parameters or request JSON.
"""
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import date
import hashlib
import json
import os
from collections.abc import Mapping

from flask import abort, current_app, jsonify, request, session

from vehicle_priority_assessment import (
    Candidate, Evidence, InvalidInput, Reference, build_shadow_projection,
)


EXTENSION_KEY = "maintenance_priority_preview_fixtures"
ENABLE_KEY = "MAINTENANCE_PRIORITY_PREVIEW_ENABLED"
TIMING_VERSION = "priority-timing-preview-v1"


@dataclass(frozen=True)
class SyntheticTimingInput:
    """Host-only synthetic snapshots, revalidated on every preview GET.

    No request can supply these review flags or substitute a serialized bridge
    result. The host owns semantic correspondence to this exact proposal revision.
    """
    proposal_revision: str
    rule: Mapping
    timing: Mapping
    binding: object
    proposal_binding_verified: bool = False


def snapshot_hash(value):
    """Bind normalization to exact saved source and proposal bytes semantically."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class SyntheticPreviewFixture:
    company_code: str
    vehicle_id: int
    analysis_hash: str
    sources_hash: str
    as_of: date
    candidates: Mapping[str, Candidate]
    evidence: Mapping[str, Evidence]
    references: Mapping[str, Reference]
    synthetic_only: bool = True
    timing_conditions: Mapping[str, SyntheticTimingInput] = field(default_factory=dict)


def _enabled(app):
    return (app.config.get("TESTING") is True
            and app.config.get(ENABLE_KEY) is True
            and os.environ.get("RENDER") != "true")


def register_synthetic_fixture(app, fixture):
    """Only callable by isolated host setup; never a web mutation endpoint."""
    if not _enabled(app):
        raise InvalidInput("synthetic preview requires explicit isolated testing configuration")
    if not isinstance(fixture, SyntheticPreviewFixture) or fixture.synthetic_only is not True:
        raise InvalidInput("only synthetic fixture registration is supported")
    if (not fixture.company_code or type(fixture.vehicle_id) is not int or fixture.vehicle_id <= 0
            or type(fixture.as_of) is not date or not fixture.analysis_hash or not fixture.sources_hash):
        raise InvalidInput("invalid synthetic fixture identity or snapshot")
    app.extensions.setdefault(EXTENSION_KEY, {})[(fixture.company_code, fixture.vehicle_id)] = deepcopy(fixture)


def require_preview_access():
    # The application's normal before_request validates account identity and
    # refreshes role from the authenticated DB user before this handler runs.
    if not _enabled(current_app):
        abort(404)
    if session.get("role") not in {"admin", "itc"}:
        abort(403)
    if request.method != "GET":
        abort(405)


def _condition_envelope(status="absent"):
    return {"version": TIMING_VERSION, "status": status, "mode": "shadow",
            "production_enabled": False, "synthetic_only": True, "entries": [],
            "message": "条件表示用の合成データ登録はありません。" if status == "absent" else
                       "保存版と条件根拠の対応を確認できません。条件は表示していません。"}


def _condition_preview(fixture, decorated, source_map):
    """Separate factual output only. Never feeds conditions into the score/order.

    Whole saved analysis/source hashes were checked by preview_result. This
    additionally requires explicit host semantic review, exact proposal revision,
    scope/event/date and all original citations, then reruns the pure bridge.
    """
    from vehicle_priority_timing_sources import (
        TimingBinding, bridge_adopted_timing, timing_condition_payload,
    )

    envelope = _condition_envelope()
    try:
        inputs = fixture.timing_conditions
        if not isinstance(inputs, Mapping):
            raise InvalidInput("invalid condition registry")
        if not inputs:
            return envelope
        proposals = {item["proposal_id"]: item for item in decorated["recommendations"]}
        if not set(inputs).issubset(proposals):
            raise InvalidInput("condition proposal is absent")
        entries = []
        for proposal_id, value in inputs.items():
            proposal = proposals[proposal_id]
            candidate = fixture.candidates[proposal_id]
            if (not isinstance(value, SyntheticTimingInput)
                    or value.proposal_binding_verified is not True
                    or value.proposal_revision != proposal["proposal_revision"]
                    or not isinstance(value.binding, TimingBinding)):
                raise InvalidInput("condition proposal binding is not verified")
            binding = value.binding
            if (binding.scope != candidate.scope or binding.event_id != candidate.event_id
                    or binding.as_of != fixture.as_of):
                raise InvalidInput("condition scope, event or date mismatch")
            citation_lists = [proposal.get("source_ids", []), proposal.get("knowledge_ids", [])]
            if any(not isinstance(values, list) or any(not isinstance(s, str) for s in values)
                   for values in citation_lists):
                raise InvalidInput("invalid original citations")
            citations = {s for values in citation_lists for s in values}
            result = bridge_adopted_timing(value.rule, value.timing, binding,
                                           fixture.evidence, fixture.references)
            used = set(result.provenance_source_ids) | set(binding.event_source_ids)
            if not used.issubset(source_map) or not used.issubset(citations):
                raise InvalidInput("condition evidence absent from saved sources or proposal")
            entries.append({"proposal_id": proposal_id,
                            "proposal_revision": value.proposal_revision,
                            **timing_condition_payload(result)})
        envelope.update(status="available", entries=entries,
            company_code=fixture.company_code, vehicle_id=fixture.vehicle_id, as_of=fixture.as_of.isoformat(),
            message="非本番の合成条件表示です。原文・登録条件の事実表示で、点数や並び順には反映していません。")
        return envelope
    except (InvalidInput, TypeError, ValueError, KeyError, AttributeError, RecursionError):
        # Never leak a raw exception or expose part of a stale registration.
        return _condition_envelope("blocked")


def preview_result(vehicle, state, bundle):
    """Return a read-only preview without invoking the normal cache/AI path."""
    from .analysis_feedback import analysis_with_vehicle_feedback

    require_preview_access()
    raw_analysis = bundle.get("analysis")
    has_result = isinstance(raw_analysis, dict)
    sources = bundle.get("sources")
    source_map = sources if isinstance(sources, dict) else {}
    # Build identities from the ORIGINAL saved proposal before annotation.
    decorated = analysis_with_vehicle_feedback(raw_analysis, vehicle) if has_result else None
    metadata = {
        "status": "blocked", "mode": "shadow", "production_enabled": False,
        "synthetic_only": True,
        "message": "この保存版に対応する合成データの検証登録がありません。試算は表示していません。",
    }
    conditions = _condition_envelope("blocked")
    fixture = current_app.extensions.get(EXTENSION_KEY, {}).get((vehicle.company_code, vehicle.id))
    if has_result and isinstance(fixture, SyntheticPreviewFixture) and fixture.synthetic_only is True:
        try:
            if fixture.analysis_hash != snapshot_hash(raw_analysis) or fixture.sources_hash != snapshot_hash(source_map):
                raise InvalidInput("snapshot changed")
            if fixture.company_code != vehicle.company_code or fixture.vehicle_id != vehicle.id:
                raise InvalidInput("fixture scope changed")
            if any(source_id not in source_map for source_id in fixture.evidence):
                raise InvalidInput("normalized evidence is absent from saved sources")
            # No latest-input/cache computation occurs here. Never pretend that
            # a synthetic fixture proves the saved analysis is current.
            candidates = {key: replace(value, input_is_current=None)
                          for key, value in fixture.candidates.items()}
            decorated = build_shadow_projection(
                decorated, candidates, fixture.evidence, fixture.references,
                as_of=fixture.as_of, company_code=vehicle.company_code, vehicle_id=vehicle.id,
            )
            conditions = _condition_preview(fixture, decorated, source_map)
            metadata.update(status="available", as_of=fixture.as_of.isoformat(),
                            message="非本番の合成データ試算です。点数は試行値で、運行可否は人が判断します。保存版の最新性は未確認です。")
        except (InvalidInput, TypeError, ValueError):
            # Do not degrade an invalid binding into a seemingly valid low score,
            # expose exception text, or quietly render a previous preview.
            metadata["message"] = "保存版と検証根拠の対応を確認できません。試算は表示していません。"
    response = jsonify(
        ok=True, status=state.status if state else "waiting", has_result=has_result,
        is_current=None, input_summary=None, scheduled_comparison=None,
        message=metadata["message"], priority_preview=metadata,
        priority_timing_conditions=conditions,
        analysis=decorated, sources=source_map,
        coverage=bundle.get("coverage", {}) if has_result else {},
        comparison=bundle.get("comparison") if has_result else None,
        generated_at=bundle.get("generated_at") if has_result else None,
        analysis_method=bundle.get("analysis_method") if has_result else None,
    )
    response.headers["Cache-Control"] = "no-store"
    return response
