"""Read-time response priority, separate from saved AI output and risk explanations.

Only the host's scoped, current registration snapshots enter normalization. No
free-text severity detection, AI evidence approval, persistence, or operation
decision occurs here. Unsupported legacy proposals keep their saved class with
no invented score. Invalid legacy data is a data state, not a fourth class.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json

from daily_inspection_defaults import get_daily_inspection_default
from vehicle_priority_assessment import (
    Candidate, Evidence, Fact, Scope, assess_priority, METHOD, POLICY_VERSION,
)

VERSION = 'maintenance-response-priority-v1'
DISCLAIMER = ('点数・区分境界はシステムの試行値です。公的・メーカー指定の点数、故障確率、運行可否ではありません。'
              '低は安全確認済みを意味せず、本格運用前に整備担当者の確認が必要です。')
LABELS = ('高', '中', '低')
AXES = ('impact', 'timing', 'state')
# Exact short standard brake items only. Long/compound items need an explicit
# item reference beyond the existing 24-character target contract.
SAFETY_CODES = frozenset({'daily_02', 'daily_03'})
DEFAULT = get_daily_inspection_default()
STANDARD = {item['item_code']: item for item in DEFAULT['items']}


@dataclass(frozen=True)
class InspectionSnapshot:
    company_code: str
    vehicle_id: int
    record_id: int
    inspection_on: str
    status: str
    checklist_json: str
    answers_json: str
    judgment_json: str
    captured_on: date
    gross_vehicle_weight: object = None
    stop_history_reviewed: bool = False
    has_stop_history: bool = False


def inspection_provenance(row):
    """Server-owned input proof: selected event identity, original item and answer.

    Other events and mutable row status are deliberately not an identity key.
    The full fingerprint is retained for audit, not used to rebind a candidate.
    No raw comments, identities or attachments are duplicated in this proof.
    """
    try:
        judgment = json.loads(row.judgment_json)
        checklist = json.loads(row.checklist_json)
        defects = judgment.get('defects') if isinstance(judgment, dict) else None
        fields = checklist.get('items') if isinstance(checklist, dict) else None
    except (TypeError, ValueError):
        return None
    if (not isinstance(defects, list) or any(not isinstance(v, dict) for v in defects)
            or not isinstance(fields, list) or not fields or any(not isinstance(v, dict) for v in fields)):
        return None
    checks = [v for v in fields if v.get('item_type') == 'check']
    events = []
    for defect in defects:
        number = str(defect.get('item_no'))
        field = checks[int(number)] if number.isascii() and number.isdecimal() and len(number) < 6 and int(number) < len(checks) else {}
        definition = {key: field.get(key) for key in ('item_code','content','input_type','choices','criteria')}
        definition.update(template_code=fields[0].get('fixed_template_code'),
                          template_version=fields[0].get('fixed_template_version'))
        events.append({'defect_no': defect.get('defect_no'), 'item_no': number,
            'item_code': field.get('item_code'), 'item_content': field.get('content'),
            'item_definition_fingerprint': _hash(definition),
            'reported_at': defect.get('reported_at'),
            'answer_fingerprint': _hash(defect.get('reported_answer')),
            'had_followup': 'repair' in defect or 'recheck' in defect})
    snapshot = {key: value for key, value in vars(row).items()
                if key not in {'captured_on','stop_history_reviewed','has_stop_history'}}
    return {'version': 'registered-inspection-priority-source-v1',
        'company_code': row.company_code, 'vehicle_id': row.vehicle_id, 'record_id': row.record_id,
        'inspection_on': row.inspection_on, 'judgment_version': judgment.get('version'),
        'operation_judgment_status': judgment.get('status'),
        'snapshot_fingerprint': _hash(snapshot), 'events': events}


def _bound_event(item, proof, row):
    current = inspection_provenance(row)
    if not isinstance(proof, dict) or not isinstance(current, dict):
        return None, '元分析入力の事象証明がないため保存版を保持します'
    for key in ('version','company_code','vehicle_id','record_id','inspection_on'):
        if key not in proof or proof[key] != current[key]:
            return None, '元分析入力と会社・車両・点検の対応を確認できません'
    events = proof.get('events')
    if not isinstance(events, list):
        return None, '元の指摘事象の対応を確認要'
    selected = [v for v in events if isinstance(v, dict) and _text(v.get('item_content')) == _text(item.get('target'))]
    if len(selected) != 1:
        return None, '元提案と単一の具体的な指摘事象の対応を確認要'
    selected = selected[0]
    if proof.get('operation_judgment_status') == '運行不可' or selected.get('had_followup') is not False:
        return None, '元入力に停止指示又は修理・再確認があります。指示の解除・対象範囲を推定せず保存版を保持します'
    now = [v for v in current['events'] if v.get('defect_no') == selected.get('defect_no')]
    identity = ('defect_no','item_no','item_code','item_content','item_definition_fingerprint','reported_at','answer_fingerprint')
    if len(now) != 1 or any(key not in selected or selected[key] != now[0].get(key) for key in identity):
        return None, '元の指摘番号・報告・回答・項目版との一致を確認できません。別事象へ付け替えず保存版を保持します'
    return selected['defect_no'], None


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), default=str).encode()).hexdigest()


def _day(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _text(value):
    return ' '.join(value.split()) if isinstance(value, str) else ''


def _legacy(item, as_of, reasons, fingerprint):
    label = item.get('priority') if item.get('priority') in LABELS else None
    return {
        'version': VERSION, 'candidate_id': item.get('proposal_id'),
        'proposal_revision': item.get('proposal_revision'), 'method': METHOD,
        'policy_version': POLICY_VERSION, 'policy_status': 'trial',
        'calculation_status': 'legacy_preserved' if label else 'invalid_legacy',
        'label': label, 'base_score': None, 'effective_score': None,
        'floor_adjustment': None, 'as_of': as_of.isoformat(), 'observed_at': None,
        'captured_on': as_of.isoformat(),
        'factors': [{'axis': axis, 'points': None, 'source_ids': [],
                     'rule_ids': [], 'reference_ids': []} for axis in AXES],
        'applied_floors': [], 'missing_axes': list(AXES),
        'evidence_status': '保存版・要確認' if label else '保存データ要確認',
        'missing_conditions': sorted(set(reasons)), 'source_ids': [],
        'applicable_reference_ids': [], 'source_fingerprint': fingerprint,
        'requires_professional_review': True, 'operation_decision': 'human_only',
        'safety_cleared': False, 'earliest_due_on': None, 'first_observed_on': None,
        'disclaimer': '保存された区分です。新方式の点数は算定していません。低は安全確認済みを意味せず、運行可否は人が判断します。',
    }


def _inspection_candidate(item, row, as_of, is_current, event_number):
    """Normalize only a bound, unrepaired, no-stop-history brake finding.

    Existing stop instructions are never transferred from a row-wide judgment
    to a component proposal. No expiry, release or time-zone order is inferred.
    """
    sid = f'inspection:{row.record_id}'
    observed = _day(row.inspection_on)
    if row.captured_on != as_of or observed is None or observed > as_of:
        return None, '点検日・取得基準日の対応を確認要'
    if row.status not in {'承認済み', '点検完了'}:
        return None, '点検の登録状態を確認要'
    if row.stop_history_reviewed is not True or row.has_stop_history is not False:
        return None, '停止指示の履歴・解除範囲を確認要。指示を解除せず保存版を保持します'
    try:
        checklist, answers, judgment = (json.loads(v) for v in (row.checklist_json,row.answers_json,row.judgment_json))
    except (TypeError, ValueError):
        return None, '点検の構造化記録を確認要'
    if not isinstance(checklist, dict) or not isinstance(answers, list) or not isinstance(judgment, dict):
        return None, '点検の構造化記録を確認要'
    if judgment.get('status') == '運行不可':
        return None, '現在登録の停止指示の対象・解除範囲を確認要。保存版を保持します'
    items = checklist.get('items')
    if (not isinstance(items, list) or not items or any(not isinstance(v, dict) for v in items)
            or items[0].get('fixed_template_code') != DEFAULT['template_code']
            or type(items[0].get('fixed_template_version')) is not int
            or items[0]['fixed_template_version'] != DEFAULT['template_version']):
        return None, '標準点検項目の版と凡例を確認要'
    checks = [v for v in items if v.get('item_type') == 'check']
    matches = [(index,field,STANDARD.get(field.get('item_code'))) for index,field in enumerate(checks)
               if field.get('item_code') in STANDARD and _text(item.get('target')) == _text(STANDARD[field['item_code']]['content'])]
    if len(matches) != 1:
        return None, '提案対象と具体的な標準点検項目の対応を確認要'
    index, field, canonical = matches[0]
    if (field.get('content') != canonical['content'] or field.get('input_type') != 'select'
            or field.get('choices') != DEFAULT['choices'] or field.get('criteria') != DEFAULT['criteria']):
        return None, '点検項目の原文・凡例が標準版と一致しません'
    if canonical['item_code'] not in SAFETY_CODES:
        return None, 'この項目の影響度・安全条件の通常接続は未実装です。保存版を保持します'
    matching_answers = [v for v in answers if isinstance(v, dict) and str(v.get('item_no')) == str(index)]
    defects = judgment.get('defects')
    if (len(matching_answers) != 1 or not isinstance(defects, list)
            or any(not isinstance(v, dict) for v in defects)):
        return None, '指摘と回答の一意な対応を確認要'
    answer = matching_answers[0]
    matched = [v for v in defects if str(v.get('item_no')) == str(index)]
    if len(matched) != 1 or matched[0].get('defect_no') != event_number:
        return None, '複数事象・再発を含む指摘の対応は未接続です'
    defect = matched[0]
    if 'repair' in defect or 'recheck' in defect:
        return None, '修理・再確認を含む未解消指摘の停止履歴・現在状態は未接続です。保存版を保持します'
    report = defect.get('reported_answer')
    if (defect.get('status') != '対応待ち' or type(defect.get('defect_no')) is not int
            or defect['defect_no'] <= 0 or not isinstance(report, dict)
            or answer.get('value') != '×' or answer.get('content') != canonical['content']
            or any(report.get(key) != answer.get(key) for key in ('item_no','content','value','comment','files'))):
        return None, '現在の未解消事象と当初回答の対応を確認要（完了回答だけでは解消扱いしません）'
    reported = _day(defect.get('reported_at'))
    if reported is None or not observed <= reported <= as_of:
        return None, '指摘の登録日時を確認要'
    scope = Scope(row.company_code, row.vehicle_id, item['target'])
    event = f'{sid}:defect:{event_number}'
    evidence = {sid: Evidence(sid, scope, reported, event,
        f'{canonical["item_code"]}: 異常回答・登録状態 {defect["status"]}', True, 'record', 'open')}
    facts = tuple(Fact(code,(sid,),True) for code in ('state_open','safety_issue_open','impact_safety'))
    candidate = Candidate(item['proposal_id'], scope, event, facts=facts,
        missing_conditions=('対応期限はこの点検記録だけでは確定しません',
            '現在の登録状態であり、実車の再診断ではありません'), input_is_current=is_current)
    result = assess_priority(candidate, evidence, {}, as_of=as_of)
    result['first_observed_on'] = reported.isoformat()
    result['disclaimer'] = DISCLAIMER
    return result, None


def priority_order_key(item):
    value = item.get('priority_assessment') or {}
    label = value.get('label')
    score = value.get('effective_score')
    instruction = any(f.get('code') == 'operation_instruction_active'
                      for f in value.get('applied_floors', []) if isinstance(f, dict))
    return (LABELS.index(label) if label in LABELS else 3, not instruction,
        -(score if type(score) is int else -1), value.get('earliest_due_on') or '9999-12-31',
        value.get('first_observed_on') or '9999-12-31', str(item.get('proposal_id') or ''))


def project_priority(analysis, sources, inspections, *, company_code, vehicle_id, as_of,
                     is_current=None, unavailable_reason=None):
    """Append assessment after the host fixed original proposal identity/revision."""
    if not isinstance(analysis, dict):
        return analysis
    if not company_code or type(vehicle_id) is not int or vehicle_id <= 0 or type(as_of) is not date:
        raise ValueError('trusted priority projection scope/date required')
    output = deepcopy(analysis)
    proposals = output.get('recommendations')
    if not isinstance(proposals, list):
        return output
    source_map = sources if isinstance(sources, dict) else {}
    scoped = {f'inspection:{v.record_id}': v for v in inspections
              if isinstance(v, InspectionSnapshot) and v.company_code == company_code
              and v.vehicle_id == vehicle_id and v.captured_on == as_of}
    registered_fingerprint = _hash([vars(scoped[sid]) for sid in sorted(scoped)])
    for item in proposals:
        if not isinstance(item, dict):
            continue
        reasons = [unavailable_reason] if unavailable_reason else []
        refs = item.get('source_ids')
        ref_values = refs if isinstance(refs, list) else []
        valid_identity = all(isinstance(item.get(k), str) and item[k] for k in ('proposal_id', 'proposal_revision', 'target'))
        valid_refs = isinstance(refs, list) and all(isinstance(v, str) and v in source_map for v in refs)
        result = None
        matching = [sid for sid in set(refs or []) if sid in scoped] if valid_refs else []
        if not valid_identity or not valid_refs:
            reasons.append('元提案の識別子・版・根拠IDを確認要')
        elif unavailable_reason:
            pass
        elif item.get('category') == '記録確認':
            reasons.append('記録照合と実車の安全指摘の区別は旧文章から推定しません')
        elif len(matching) != 1 or len({sid for sid in refs if sid.startswith('inspection:')}) != 1:
            reasons.append('提案と現在の具体的な点検事象の一意な対応は未接続です')
        else:
            sid = matching[0]
            original = source_map[sid]
            proof = original.get('priority_provenance') if isinstance(original, dict) else None
            event_number, reason = _bound_event(item, proof, scoped[sid])
            if reason:
                reasons.append(reason)
            else:
                result, reason = _inspection_candidate(item, scoped[sid], as_of, is_current, event_number)
                if reason:
                    reasons.append(reason)
        fingerprint = _hash({'company': company_code, 'vehicle': vehicle_id, 'as_of': as_of,
            'sources': {sid: source_map.get(sid) for sid in ref_values if isinstance(sid, str)},
            'registered_fingerprint': registered_fingerprint})
        value = _legacy(item, as_of, reasons, fingerprint)
        if result is not None:
            value.update({key: result[key] for key in ('label', 'base_score', 'effective_score',
                'floor_adjustment', 'applied_floors', 'evidence_status', 'missing_axes',
                'missing_conditions', 'source_ids', 'requires_professional_review', 'disclaimer',
                'earliest_due_on', 'first_observed_on')})
            value.update(calculation_status='computed', observed_at=result['observed_on'],
                applicable_reference_ids=result['reference_ids'],
                factors=[dict(axis=f['axis'], points=f['points'], source_ids=f['source_ids'],
                    rule_ids=f['fact_codes'], reference_ids=f['reference_ids']) for f in result['factors']])
            item['priority'] = value['label']
        item['priority_assessment'] = value
    output['priority_assessment_version'] = VERSION
    ordered_indices = sorted((index for index,value in enumerate(proposals) if isinstance(value,dict)),
                             key=lambda index: priority_order_key(proposals[index]))
    output['priority_order_format'] = 'source_indices_v1'
    output['priority_order_indices'] = ordered_indices
    output['priority_order'] = [proposals[index]['proposal_id'] for index in ordered_indices
                               if isinstance(proposals[index].get('proposal_id'),str)]
    return output
