"""Pure explicit record-to-proposal binding; no inference, I/O or persistence.

Only trusted host code may establish correspondence. Saved AI citations merely
constrain the chosen record; they never confirm the correspondence themselves.
All snapshots and original proposal revisions are bound before any projection.
"""
from dataclasses import dataclass, replace
from datetime import date
import hashlib
import json

from vehicle_priority_assessment import InvalidInput, Scope, build_shadow_projection
from vehicle_priority_sources import DefectSnapshot, normalize_registered_defects


BINDING_VERSION = "explicit-defect-proposal-shadow-v1"


def projection_snapshot_hash(value):
    """Digest exact JSON data, rejecting unrepresentable or non-finite values."""
    def validate(node):
        if type(node) is dict:
            if any(type(key) is not str for key in node):
                raise InvalidInput("projection object keys must be strings")
            for value in node.values():
                validate(value)
        elif type(node) is list:
            for value in node:
                validate(value)
        elif node is not None and type(node) not in (str, bool, int, float):
            raise InvalidInput("projection snapshot must contain JSON values only")
    try:
        validate(value)
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError, RecursionError):
        raise InvalidInput("projection snapshot must be finite JSON data") from None


@dataclass(frozen=True)
class ExplicitDefectBinding:
    proposal_id: str
    proposal_revision: str
    target: str
    source_id: str
    # This must come from the trusted host's explicit association, not AI text.
    correspondence_verified: bool = False


@dataclass(frozen=True)
class DefectBindingSet:
    company_code: str
    vehicle_id: int
    captured_on: date
    analysis_fingerprint: str
    sources_fingerprint: str
    records_fingerprint: str
    entries: tuple[ExplicitDefectBinding, ...]


def build_bound_defect_projection(analysis: dict, sources: dict, records: DefectSnapshot,
                                  bindings: DefectBindingSet, *, as_of: date) -> dict:
    """Project only exact, complete one-to-one bindings without changing originals.

    Closed records, duplicate records, absent/stale bindings and ambiguous scopes
    block the projection rather than producing a misleading low fallback. The
    first contract intentionally permits one defect record per original proposal.
    """
    if not isinstance(analysis, dict) or not isinstance(sources, dict) or not isinstance(bindings, DefectBindingSet):
        raise InvalidInput("explicit analysis, sources and binding set are required")
    if (not isinstance(records, DefectSnapshot) or bindings.company_code != records.company_code
            or type(bindings.vehicle_id) is not int or bindings.vehicle_id != records.vehicle_id
            or type(bindings.captured_on) is not date or bindings.captured_on != records.captured_on
            or type(bindings.entries) is not tuple):
        raise InvalidInput("binding scope or capture date differs from record snapshot")
    if bindings.analysis_fingerprint != projection_snapshot_hash(analysis) or bindings.sources_fingerprint != projection_snapshot_hash(sources):
        raise InvalidInput("saved analysis or sources changed after explicit binding")
    if any(key.startswith("priority_preview") or key == "priority_binding" for key in analysis):
        raise InvalidInput("bind original host proposals, not an earlier projection")
    proposals = analysis.get("recommendations")
    if not isinstance(proposals, list) or any(not isinstance(item, dict) for item in proposals):
        raise InvalidInput("original recommendation list is required")
    original = {}
    for item in proposals:
        identity = item.get("proposal_id")
        if (not isinstance(identity, str) or not identity.strip() or identity in original
                or not isinstance(item.get("proposal_revision"), str) or not item["proposal_revision"].strip()
                or not isinstance(item.get("target"), str) or not item["target"].strip()
                or "priority_preview" in item):
            raise InvalidInput("unique original host proposal identity, revision and target required")
        original[identity] = item
    normalized = normalize_registered_defects(records, as_of=as_of)
    if bindings.records_fingerprint != normalized["snapshot_fingerprint"]:
        raise InvalidInput("record snapshot changed after explicit binding")
    available = {row["record"]["source_id"]: row for row in normalized["items"]}
    candidates, evidence, selected, used_sources = {}, {}, [], set()
    for binding in bindings.entries:
        if (not isinstance(binding, ExplicitDefectBinding) or binding.correspondence_verified is not True
                or any(not isinstance(value, str) or not value.strip() for value in (
                    binding.proposal_id, binding.proposal_revision, binding.target, binding.source_id))
                or binding.proposal_id in candidates or binding.source_id in used_sources):
            raise InvalidInput("one verified explicit record binding per proposal is required")
        item = original.get(binding.proposal_id)
        if (item is None or item["proposal_revision"] != binding.proposal_revision
                or item["target"] != binding.target):
            raise InvalidInput("explicit binding differs from original proposal revision or target")
        citation_ids = item.get("source_ids")
        if (not isinstance(citation_ids, list) or any(not isinstance(sid, str) for sid in citation_ids)
                or binding.source_id not in citation_ids or binding.source_id not in sources
                or not isinstance(sources[binding.source_id], dict)):
            raise InvalidInput("selected record is absent from original citations or source map")
        normalized_item = available.get(binding.source_id)
        if normalized_item is None or normalized_item["record"]["registered_status"] == "修理完了":
            raise InvalidInput("selected record is absent, foreign or already registered repair-complete")
        scope = Scope(records.company_code, records.vehicle_id, binding.target)
        candidate = normalized_item["candidate"]
        # The host's verified association allows target rebinding; event identity
        # remains this exact record and is never inferred from component names.
        candidates[binding.proposal_id] = replace(candidate, candidate_id=binding.proposal_id,
                                                  scope=scope, input_is_current=None)
        evidence.update({sid: replace(value, scope=scope)
                         for sid, value in normalized_item["evidence"].items()})
        used_sources.add(binding.source_id)
        selected.append({"proposal_id": binding.proposal_id, "proposal_revision": binding.proposal_revision,
                         "target": binding.target, "record": normalized_item["record"]})
    if set(candidates) != set(original):
        raise InvalidInput("every original proposal needs an explicit verified binding")
    projection = build_shadow_projection(analysis, candidates, evidence, {}, as_of=as_of,
                                         company_code=records.company_code, vehicle_id=records.vehicle_id)
    projection["priority_binding"] = {"version": BINDING_VERSION, "mode": "shadow",
                                      "production_enabled": False,
                                      "analysis_fingerprint": bindings.analysis_fingerprint,
                                      "sources_fingerprint": bindings.sources_fingerprint,
                                      "records_fingerprint": bindings.records_fingerprint,
                                      "captured_on": records.captured_on.isoformat(), "selected": selected}
    return projection
