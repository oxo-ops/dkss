"""Fail closed when the rollback build cannot interpret a saved analysis.

This is a retention boundary, not a priority implementation or a data migration.
Never normalize or rewrite a protected value, including malformed saved JSON.
"""
import json

ERROR = "saved_result_requires_newer_version"
MESSAGE = "保存済み結果を保持しています。この版では内容を正しく表示・更新できません。対応する新版で確認してください。"
BUSY_MESSAGE = "保存済み結果の保護確認が別の処理と競合しています。元の記録は変更していません。処理完了後に開き直してください。"


class SavedResultLockConflict(ValueError):
    """Refuse this source mutation after a complete transaction rollback."""


_ANALYSIS_KEYS = {"analysis", "sources", "coverage", "comparison", "fingerprints",
                  "analysis_method", "generated_at"}
_PERIODIC_KEYS = {"overview", "recommendations", "output_contract", "risk_contract",
                  "risk_text_contract", "model"}

_ITEM_TEXT_KEYS = {
    "priority", "category", "target", "title", "current_state", "action",
    "timing", "reason", "uncertainty", "confirmation_branch", "basis_type",
    "risk", "risk_status", "risk_basis", "risk_condition", "risk_effect",
}
_ITEM_LIST_KEYS = {"source_ids", "knowledge_ids", "risk_source_ids", "confirmation_steps"}
_ITEM_KEYS = _ITEM_TEXT_KEYS | _ITEM_LIST_KEYS | {"risk_evidence"}
_CONTRACTS = {"output_contract": "vehicle-preventive-v4", "risk_contract": "vehicle-risk-v4",
              "risk_text_contract": "condition-effect-v2"}


def _legacy_result(result):
    # Missing historical optional fields remain supported; present fields must
    # have the legacy type. Unknown nested result/recommendation fields are held.
    if not isinstance(result, dict) or set(result) - _PERIODIC_KEYS:
        return False
    for key in _PERIODIC_KEYS - {"recommendations"}:
        if key in result and not isinstance(result[key], str):
            return False
    if any(key in result and result[key] != value for key, value in _CONTRACTS.items()):
        return False
    items = result.get("recommendations", [])
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict) or set(item) - _ITEM_KEYS:
            return False
        if any(key in item and not isinstance(item[key], str) for key in _ITEM_TEXT_KEYS):
            return False
        for key in _ITEM_LIST_KEYS:
            if key in item and (not isinstance(item[key], list)
                                or any(not isinstance(value, str) for value in item[key])):
                return False
        if "risk_evidence" in item:
            entries = item["risk_evidence"]
            if not isinstance(entries, list) or any(
                not isinstance(entry, dict) or set(entry) != {"source_id", "quote"}
                or any(not isinstance(value, str) for value in entry.values())
                for entry in entries
            ):
                return False
    return True


def _object_without_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate saved-result key")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError("non-finite saved-result value")


def requires_newer_version(raw, *, periodic=False):
    """Hold incompatible bytes without interpreting priority/carry semantics.

    PR377 also uses policy_version=12. Check persisted priority fields recursively
    and validate the supported legacy envelopes, never just that version number.
    """
    if raw is None or raw == "":
        return False
    try:
        value = json.loads(raw, object_pairs_hook=_object_without_duplicates, parse_constant=_invalid_constant)
        if not isinstance(value, dict):
            return True
        if not value:
            return False
        if set(value) - (_PERIODIC_KEYS if periodic else _ANALYSIS_KEYS):
            return True
        if not periodic:
            for key in ("sources", "coverage", "fingerprints"):
                if key in value and not isinstance(value[key], dict):
                    return True
            if "comparison" in value and value["comparison"] is not None and not isinstance(value["comparison"], dict):
                return True
            for key in ("generated_at", "analysis_method"):
                if key in value and not isinstance(value[key], str):
                    return True
            for source in value.get("sources", {}).values():
                if not isinstance(source, dict) or set(source) - {"label", "url", "snapshot"}:
                    return True
                if any(key in source and not isinstance(source[key], str) for key in ("label", "url")):
                    return True
                if "snapshot" in source and not isinstance(source["snapshot"], dict):
                    return True
            fingerprints = value.get("fingerprints", {})
            version = fingerprints.get("policy_version")
            if version is not None and (type(version) is not int or version != 12):
                return True
            if any(key in fingerprints and not isinstance(fingerprints[key], str)
                   for key in ("important_hash", "routine_hash")):
                return True
            if "has_important_history" in fingerprints and type(fingerprints["has_important_history"]) is not bool:
                return True
        stack = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if any(key.startswith("priority_") for key in item):
                    return True
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
        return not _legacy_result(value if periodic else value.get("analysis", {}))
    except (ValueError, TypeError, RecursionError):
        return True
