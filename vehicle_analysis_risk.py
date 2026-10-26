"""Risk explanation contract. No API, database, vehicle state or timing mutations."""
import re
import unicodedata

RISK_CONTRACT = "vehicle-risk-v4"
UNKNOWN_RISK = "機能への影響は未判定です。"

RISK_INSTRUCTIONS = """
【車両リスク判定 v4：状態・想定影響・期限を分ける】
車両の実記録と適用できる整備知識を結び付け、何が起こり得るため何を確認するかを説明してください。
点検の起算日や計測値が不明で期限計算がheldでも、機能の一般的な知識を使った条件付きの懸念は説明できます。期限が不明なことだけで機能への影響も未判定に固定しないでください。
一方、知識に点検項目・周期が書かれているだけでは、現在の異常や具体的な機能低下の証拠になりません。対象部品の名前だけから原因、事故、運行不可を断定しないでください。
risk_basisは次のいずれかです。
recorded_impact：実記録に機能への影響が明記され、その記録内容を説明する。過去の記録を現在の確定診断にしない。
registered_knowledge：今回適用できる登録知識に影響の説明があり、当該車両の状態と結び付ける。
general_knowledge：整備の一般知識を使い、成立条件を明示した可能性として説明する。メーカーの指定・確定診断・実測結果と表現しない。
unknown：上のどの根拠でも具体的影響を説明できない場合。
risk_basisはリスク説明の根拠であり、提案全体のbasis_typeと区別する。点検内容の根拠は登録知識、影響の説明は一般知識、という組合せを許す。
説明できる場合はrisk_status=supported。supportedは説明の根拠があるという意味で、実車に異常が確認されたという意味ではありません。
risk_conditionは影響が生じる条件又は記録上確認された範囲を30文字以内で示す。一般知識・登録知識の場合は「〜の場合」「〜すると」等の条件文にする。risk_effectは条件を除いた想定影響を48文字以内で示し、未確認の影響は「可能性」「おそれ」「懸念」のいずれかを含む文章にする。例：risk_condition="水分が残留する場合"、risk_effect="機能が低下するおそれがあります。"。表示用riskはサーバーが条件と影響を結合するため、AIは出力しない。発生確率や残寿命を創作しない。
risk_source_idsはサーバーがrisk_evidenceから作るため出力しない。risk_evidenceには車両側の実際の根拠IDを1件以上含め、source_idsに含まれるIDのみ指定する。登録知識をリスクの根拠にした場合は該当knowledge_idの原文引用も含める。
risk_evidenceは[{source_id,quote}]。車両状態の根拠と、登録知識を使う場合は機能影響の根拠を、各入力の原文から2〜120文字で引用する。一般知識の説明を入力に書かれた引用として創作しない。
説明できなければrisk_status=unassessed、risk_basis=unknown、risk_effect=""、risk_condition=""、risk_evidence=[]とする。未判定を低リスク・異常なしと扱わない。
記録の不一致、起算日不足、参照件数、処理保留等の内部メモをriskへ入れない。照合はシステム側で行い、既存情報の探し直し・再取込・専門項目の追加入力を通常の対応にしない。
対応時期の数値は従来どおり計算許可済みtiming_factsだけを使う。一般知識によるリスク説明を理由に未計算の交換期限を作らない。
優先度は根拠のある症状・影響・必要な対応時期から決める。情報不足を高リスクにも低リスクにも置き換えない。
解消後の再発等の新しい根拠がなければ、解消済みの異常を現在のリスクとして繰り返さない。一般的な危険を列挙するためだけに提案件数を増やさない。
""".strip()


def risk_output_properties():
    text = {"type": "string"}
    return {
        "risk_effect": {"type": "string", "maxLength": 48},
        "risk_status": {"type": "string", "enum": ["supported", "unassessed"]},
        "risk_basis": {"type": "string", "enum": ["recorded_impact", "registered_knowledge", "general_knowledge", "unknown"]},
        "risk_condition": {"type": "string", "maxLength": 30},
        "risk_evidence": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "properties": {"source_id": text, "quote": {"type": "string", "minLength": 2, "maxLength": 120}},
            "required": ["source_id", "quote"], "additionalProperties": False}},
    }


def _normalize(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            if key not in {"source_id", "source_ids", "url", "sha256", "document_checksum"}:
                yield from _texts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _texts(child)



def compose_risk_text(item):
    """Derive the display text without dropping a condition or truncating evidence."""
    condition, effect = item.get("risk_condition"), item.get("risk_effect")
    if not isinstance(condition, str) or not isinstance(effect, str) or len(condition)>30 or len(effect)>48:
        raise ValueError("INVALID_ANALYSIS_RISK:CONDITION_EFFECT_FORMAT")
    if item.get("risk_status") == "unassessed":
        if condition or effect:
            raise ValueError("INVALID_ANALYSIS_RISK:UNKNOWN_CONTRACT")
        return UNKNOWN_RISK
    if not condition.strip() or not effect.strip():
        raise ValueError("INVALID_ANALYSIS_RISK:CONDITION_EFFECT_EMPTY")
    separator = "、" if item.get("risk_basis") in ("general_knowledge", "registered_knowledge") else "："
    return condition + separator + effect


def compose_vehicle_risk_data(data):
    # Review responses have a different schema and no recommendation objects.
    if not isinstance(data, dict) or not isinstance(data.get("recommendations"), list):
        return
    for item in data["recommendations"]:
        if not isinstance(item, dict):
            raise ValueError("INVALID_ANALYSIS_RISK:ITEM_FORMAT")
        item["risk"] = compose_risk_text(item)
        entries = item.get("risk_evidence")
        if not isinstance(entries, list) or len(entries)>3:
            raise ValueError("INVALID_ANALYSIS_RISK:EVIDENCE_FORMAT")
        refs = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry)!={"source_id", "quote"} or not isinstance(entry["source_id"], str):
                raise ValueError("INVALID_ANALYSIS_RISK:EVIDENCE_FORMAT")
            if entry["source_id"] not in refs:
                refs.append(entry["source_id"])
        # IDs are derived only; the validator below still checks every source and quote.
        item["risk_source_ids"] = refs


def validate_vehicle_risk(item, payload):
    """Check attribution and source quotations; this does not certify a diagnosis."""
    def reject(reason):
        # Only a fixed code is logged: no model text, source data or credentials.
        raise ValueError("INVALID_ANALYSIS_RISK:" + reason)

    if item.get("risk") != compose_risk_text(item):
        reject("DISPLAY_TEXT_MISMATCH")
    status, basis = item.get("risk_status"), item.get("risk_basis")
    risk, condition = item.get("risk"), item.get("risk_condition")
    refs, evidence = item.get("risk_source_ids"), item.get("risk_evidence")
    source_ids = item.get("source_ids")
    if (status not in ("supported", "unassessed") or not isinstance(risk, str)
            or not risk.strip() or len(risk) > 80 or not isinstance(condition, str) or len(condition) > 30
            or not isinstance(refs, list) or len(refs) > 10 or not isinstance(source_ids, list)
            or any(not isinstance(s, str) or s not in source_ids for s in refs)
            or not isinstance(evidence, list) or len(evidence) > 3):
        reject("FIELD_FORMAT")
    if status == "unassessed":
        if basis != "unknown" or risk != UNKNOWN_RISK or condition or refs or evidence:
            reject("UNKNOWN_CONTRACT")
        return
    if basis not in ("recorded_impact", "registered_knowledge", "general_knowledge") or not condition.strip() or not refs:
        reject("SUPPORTED_BASIS")
    if any(word in _normalize(risk) for word in ("完了回答", "記録の不一致", "起算日が不明", "source_id", "レコード", "参照件数")):
        reject("INTERNAL_MEMO")
    records = {row.get("source_id"): row for row in payload.get("records", []) if isinstance(row, dict)}
    vehicle_source = payload.get("vehicle_source") or {}
    if vehicle_source.get("source_id"):
        records[vehicle_source["source_id"]] = vehicle_source
    knowledge = {row.get("source_id"): row for row in payload.get("maintenance_knowledge", []) if isinstance(row, dict)}
    vehicle_refs = set(refs) & records.keys()
    knowledge_refs = set(refs) & knowledge.keys()
    if not vehicle_refs or any(s not in records and s not in knowledge for s in refs):
        reject("SOURCE_NOT_IN_INPUT")
    if basis == "recorded_impact" and knowledge_refs:
        reject("RECORDED_BASIS_HAS_KNOWLEDGE")
    if basis == "registered_knowledge" and not knowledge_refs:
        reject("REGISTERED_BASIS_MISSING_KNOWLEDGE")
    if basis == "general_knowledge" and knowledge_refs:
        reject("GENERAL_BASIS_HAS_KNOWLEDGE")
    sources = {**records, **knowledge}
    cited = set()
    for entry in evidence:
        if not isinstance(entry, dict) or set(entry) != {"source_id", "quote"}:
            reject("EVIDENCE_FORMAT")
        sid, quote = entry["source_id"], entry["quote"]
        if not isinstance(sid, str) or sid not in refs or not isinstance(quote, str) or not 2 <= len(quote.strip()) <= 120:
            reject("EVIDENCE_SOURCE_OR_LENGTH")
        # Quotes must occur inside one source text field; joining fields could fabricate a quote.
        if not any(_normalize(quote) in _normalize(text) for text in _texts(sources[sid])):
            reject("QUOTE_NOT_IN_SOURCE_FIELD")
        cited.add(sid)
    if set(refs) != cited:
        reject("EVIDENCE_COVERAGE")
    if basis in ("general_knowledge", "registered_knowledge"):
        # Require the condition in the user-facing risk, not only hidden metadata.
        if _normalize(condition) not in _normalize(risk):
            reject("CONDITION_NOT_IN_RISK")
        if not any(word in condition for word in ("場合", "とき", "すると", "すれば", "たら", "なら")):
            reject("CONDITION_NOT_CONDITIONAL")
        if not any(word in item["risk_effect"] for word in ("可能性", "おそれ", "懸念")):
            reject("POSSIBILITY_NOT_EXPLICIT")
    item["risk_source_ids"] = list(dict.fromkeys(refs))
