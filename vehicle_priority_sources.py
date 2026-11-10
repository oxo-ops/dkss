"""Pure shadow normalization of registered defect state, not a diagnosis.

Consumes an exact same-company/vehicle snapshot captured by trusted host code.
No AI text classification, I/O, clock reads, writes or operation decisions.
A recorded state is evidence of that registration, not proof of physical safety.
"""
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json

from vehicle_priority_assessment import Candidate, Evidence, Fact, InvalidInput, Scope, assess_priority


SOURCE_ADAPTER_VERSION = "registered-defect-state-shadow-v1"


@dataclass(frozen=True)
class DefectRecord:
    record_id: int
    company_code: str
    vehicle_id: int
    occurred_date: str | None
    content: str | None
    registered_status: str | None
    repair_date: str | None

    @property
    def source_id(self):
        return f"defect:{self.record_id}"


@dataclass(frozen=True)
class DefectSnapshot:
    company_code: str
    vehicle_id: int
    captured_on: date
    records: tuple[DefectRecord, ...]


def _date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    # Do not silently normalize basic dates or whitespace from legacy records.
    return parsed if parsed.isoformat() == value else None


def _validate(snapshot):
    if (not isinstance(snapshot, DefectSnapshot)
            or not isinstance(snapshot.company_code, str) or not snapshot.company_code.strip()
            or type(snapshot.vehicle_id) is not int or snapshot.vehicle_id <= 0
            or type(snapshot.captured_on) is not date or type(snapshot.records) is not tuple):
        raise InvalidInput("invalid defect snapshot scope or capture date")
    identities = set()
    for record in snapshot.records:
        if (not isinstance(record, DefectRecord) or type(record.record_id) is not int or record.record_id <= 0
                or record.company_code != snapshot.company_code or record.vehicle_id != snapshot.vehicle_id
                or type(record.vehicle_id) is not int or record.source_id in identities):
            raise InvalidInput("invalid, duplicate or foreign defect record")
        if any(value is not None and not isinstance(value, str) for value in (
                record.occurred_date, record.content, record.registered_status, record.repair_date)):
            raise InvalidInput("invalid registered defect field type")
        identities.add(record.source_id)


def normalize_registered_defects(snapshot: DefectSnapshot, *, as_of: date) -> dict:
    """Prepare immutable engine inputs for explicit host binding or assessment.

    This first source adapter creates RECORD candidates, not AI proposal IDs.
    Source citations alone cannot authorize semantic proposal/event binding.
    Closed records are retained as exclusions, not recreated as new tasks.
    Historical reconstruction and missing-axis severity inference are unsupported.
    """
    _validate(snapshot)
    if type(as_of) is not date or as_of != snapshot.captured_on:
        raise InvalidInput("current registration cannot be reconstructed for a different date")
    digest = hashlib.sha256(json.dumps(asdict(snapshot), sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":"), default=str).encode()).hexdigest()
    items, excluded = [], []
    for record in sorted(snapshot.records, key=lambda row: row.record_id):
        missing = ["影響度と対応期限はこの記録状態だけでは確定しません"]
        occurred, repaired = _date(record.occurred_date), _date(record.repair_date)
        if occurred is None:
            missing.append("発生日の記録を確認要")
        if not record.content or not record.content.strip():
            missing.append("指摘内容の記録を確認要")
        chronology_conflict = bool((occurred and occurred > as_of) or (repaired and repaired > as_of)
                                   or (occurred and repaired and repaired < occurred))
        if chronology_conflict:
            missing.append("発生日・修理日と取得日の関係を確認要")
        if record.repair_date and repaired is None:
            missing.append("修理日の記録を確認要")
        provenance = {"source_id": record.source_id, "record_id": record.record_id,
                      "occurred_date": record.occurred_date, "repair_date": record.repair_date,
                      "registered_status": record.registered_status, "content": record.content,
                      "state_observed_on": snapshot.captured_on.isoformat(),
                      "state_scope": "current_registration_not_historical_state_or_diagnosis"}
        if record.registered_status == "修理完了" and not chronology_conflict:
            excluded.append({**provenance, "reason": "registered_repair_complete",
                             "note": "現在の登録状態が修理完了のため、新しい未対応提案を作成しません。"})
            continue
        scope = Scope(snapshot.company_code, snapshot.vehicle_id, record.source_id)
        evidence, facts = {}, ()
        # Exact form-enum values only. Existing priority, component/category names,
        # narratives, repair comments and proposal answers are not scoring inputs.
        if record.registered_status in {"未対応", "対応中"} and not chronology_conflict:
            evidence[record.source_id] = Evidence(
                record.source_id, scope, snapshot.captured_on, record.source_id,
                f"登録状態：{record.registered_status}", verified=True, status="open")
            facts = (Fact("state_open", (record.source_id,), verified=True),)
        else:
            missing.append("現在の登録状態を確認要")
        candidate = Candidate(record.source_id, scope, record.source_id, facts=facts,
                              missing_conditions=tuple(missing), input_is_current=None)
        items.append({"record": provenance, "candidate": candidate, "evidence": evidence})
    return {"adapter_version": SOURCE_ADAPTER_VERSION, "mode": "shadow", "production_enabled": False,
            "candidate_kind": "registered_defect_record_not_ai_proposal",
            "company_code": snapshot.company_code, "vehicle_id": snapshot.vehicle_id,
            "captured_on": snapshot.captured_on.isoformat(), "snapshot_fingerprint": digest,
            "items": items, "excluded_records": excluded,
            "scope_note": "現在の登録状態だけを反映した部分試算。影響度・期限・再発は推測せず、保存済み優先度を置換しません。"}


def assess_registered_defects(snapshot: DefectSnapshot, *, as_of: date) -> dict:
    """Assess registered record candidates without binding them to AI proposals."""
    normalized = normalize_registered_defects(snapshot, as_of=as_of)
    return {**normalized, "items": [
        {"record": item["record"], "assessment": assess_priority(
            item["candidate"], item["evidence"], {}, as_of=as_of)}
        for item in normalized["items"]]}
