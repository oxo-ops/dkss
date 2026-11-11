"""Read-time response priority, separate from saved AI output and risk explanations.

Only the host's scoped, current registration snapshots enter normalization. No
free-text severity detection, AI evidence approval, persistence, or operation
decision occurs here. Unsupported legacy proposals keep their saved class with
no invented score. Invalid legacy data is a data state, not a fourth class.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo
import hashlib
import json

from daily_inspection_defaults import get_daily_inspection_default
from vehicle_priority_inputs import inspection_inputs, display_target
from vehicle_priority_assessment import (
    Candidate, Evidence, Fact, Reference, Scope, assess_priority, METHOD, POLICY_VERSION,
)

VERSION = 'maintenance-response-priority-v1'
DISCLAIMER = ('点数・区分境界はシステムの試行値です。公的・メーカー指定の点数、故障確率、運行可否ではありません。'
              '低は安全確認済みを意味せず、本格運用前に整備担当者の確認が必要です。')
LABELS = ('高', '中', '低')
AXES = ('impact', 'timing', 'state')
# Exact standard brake items only. Explicit references support long targets
# without automatically approving any additional component or applicability.
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
    instruction_history_fingerprints: tuple = ()
    followup_history_fingerprints: tuple = ()
    instruction_context_verified: bool = False
    instruction_replacements: tuple = ()


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
    for event in events:
        identity = {key: event[key] for key in ('defect_no', 'item_no', 'item_code',
            'item_content', 'item_definition_fingerprint', 'reported_at', 'answer_fingerprint')}
        event['input_ref'] = f'inspection:{row.record_id}:defect:{event["defect_no"]}:{_hash(identity)[:24]}'
    instruction = None
    if judgment.get('status') == '運行不可':
        instruction = {key: judgment.get(key) for key in ('status', 'version', 'judged_at',
            'judged_by_identity', 'judged_by_user_id', 'judged_by', 'authority_role', 'authority_confirmed', 'reason', 'priority_instruction_context')}
        instruction['judgment_fingerprint'] = _hash(judgment)
        instruction['input_ref'] = f'inspection:{row.record_id}:instruction:{_hash(judgment)[:24]}'
    snapshot = {key: value for key, value in vars(row).items()
                if key not in {'captured_on','stop_history_reviewed','has_stop_history','instruction_history_fingerprints', 'followup_history_fingerprints', 'instruction_context_verified', 'instruction_replacements'}}
    return {'version': 'registered-inspection-priority-source-v1',
        'company_code': row.company_code, 'vehicle_id': row.vehicle_id, 'record_id': row.record_id,
        'inspection_on': row.inspection_on, 'judgment_version': judgment.get('version'),
        'operation_judgment_status': judgment.get('status'),
        'snapshot_fingerprint': _hash(snapshot), 'events': events, 'instruction': instruction}


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
    explicit = item.get('priority_input_ref')
    selected = [v for v in events if isinstance(v, dict) and (
        v.get('input_ref') == explicit if explicit else _text(v.get('item_content')) == _text(item.get('target')))]
    if len(selected) != 1:
        return None, '元提案と単一の具体的な指摘事象の対応を確認要'
    selected = selected[0]
    if explicit and item.get('target') != display_target(selected.get('item_content')):
        return None, '提案の表示対象と元の指摘対象が一致しません。別部品へ点数を転用しません'
    if proof.get('operation_judgment_status') == '運行不可' or (not explicit and selected.get('had_followup') is not False):
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
    """Normalize a bound brake finding or a verified pending-recheck transition.

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
    explicit = bool(item.get('priority_input_ref'))
    bound_defects = judgment.get('defects')
    bound = [v for v in bound_defects if isinstance(v, dict) and v.get('defect_no') == event_number] if isinstance(bound_defects, list) else []
    matches = [(index,field,STANDARD.get(field.get('item_code'))) for index,field in enumerate(checks)
               if field.get('item_code') in STANDARD and (
                   len(bound) == 1 and str(index) == str(bound[0].get('item_no')) if explicit
                   else _text(item.get('target')) == _text(STANDARD[field['item_code']]['content']))]
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
    followup = 'repair' in defect or 'recheck' in defect
    if followup and not explicit:
        return None, '修理・再確認を含む未解消指摘の停止履歴・現在状態は未接続です。保存版を保持します'
    if followup:
        repair = defect.get('repair')
        if (not isinstance(repair, dict) or _day(repair.get('performed_at')) is None
                or not observed <= _day(repair.get('performed_at')) <= as_of
                or not _text(repair.get('note'))
                or defect.get('status') != '再確認待ち'
                or _hash(defect) not in row.followup_history_fingerprints
                or 'recheck' in defect):
            return None, '修理・再確認の同一事象と未解消状態を確認要'
    report = defect.get('reported_answer')
    if (defect.get('status') not in ({'整備中', '再確認待ち'} if followup else {'対応待ち'}) or type(defect.get('defect_no')) is not int
            or defect['defect_no'] <= 0 or not isinstance(report, dict)
            or answer.get('value') != '×' or answer.get('content') != canonical['content']
            or any(report.get(key) != answer.get(key) for key in ('item_no','content','value','comment','files'))):
        return None, '現在の未解消事象と当初回答の対応を確認要（完了回答だけでは解消扱いしません）'
    reported = _day(defect.get('reported_at'))
    if reported is None or not observed <= reported <= as_of:
        return None, '指摘の登録日時を確認要'
    scope = Scope(row.company_code, row.vehicle_id, canonical['content'])
    event = f'{sid}:defect:{event_number}'
    evidence = {sid: Evidence(sid, scope, reported, event,
        f'{canonical["item_code"]}: 異常回答・登録状態 {defect["status"]}', True, 'record', 'open')}
    references = {}
    if followup:
        rid = 'dkss:daily-inspection-recheck:v1'
        references[rid] = Reference(rid, '/vehicle/checklists',
            'DKSS 点検・整備ワークフロー', '整備完了後の再確認', 'v1',
            '整備完了を記録後は再確認待ち。異常なしの再確認を別途登録すると解消になる。',
            'company', True, True)
        facts = (Fact('required_safety_check_not_done', (sid,), True, (rid,)),)
    else:
        facts = tuple(Fact(code,(sid,),True) for code in ('state_open','safety_issue_open','impact_safety'))
    candidate = Candidate(item['proposal_id'], scope, event, facts=facts,
        missing_conditions=('対応期限はこの点検記録だけでは確定しません',
            '登録上、当該安全指摘が整備完了後の再確認待ちです。現車で未実施とは断定しません' if followup else '現在の登録状態であり、実車の再診断ではありません'), input_is_current=is_current)
    result = assess_priority(candidate, evidence, references, as_of=as_of)
    result['first_observed_on'] = reported.isoformat()
    result['disclaimer'] = DISCLAIMER
    return result, None


def _instruction_candidate(item, proof, row, as_of, is_current):
    """A recorded whole-vehicle instruction is its own subject, never a cause."""
    current = inspection_provenance(row)
    original = proof.get('instruction') if isinstance(proof, dict) else None
    instruction = current.get('instruction') if isinstance(current, dict) else None
    try:
        current_judgment = json.loads(row.judgment_json)
    except (TypeError, ValueError):
        current_judgment = {}
    same_scope = isinstance(current, dict) and all(proof.get(key) == current.get(key) for key in
        ('version', 'company_code', 'vehicle_id', 'record_id', 'inspection_on'))
    if (isinstance(original, dict) and item.get('priority') == '高'
            and item.get('target') == '既存の運行判断の確認' and same_scope
            and item.get('priority_input_ref') == original.get('input_ref')
            and row.stop_history_reviewed
            and any(pair[0] == original.get('judgment_fingerprint') for pair in row.instruction_replacements)):
        # A verified direct replacement is a durable historical fact. It does
        # not assert today's operation status and cannot revive at midnight.
        return {'suppressed': True,
            'reason': '元の運行不可判断から同じ点検への運行可への明示変更が登録されています。既存指示の確認提案だけを非表示にしています'}, None
    if (item.get('priority') != '高' or item.get('target') != '既存の運行判断の確認' or not isinstance(original, dict)
            or original != instruction or item.get('priority_input_ref') != original.get('input_ref')
            or any(proof.get(key) != current.get(key) for key in
                   ('version', 'company_code', 'vehicle_id', 'record_id', 'inspection_on'))
            or row.captured_on != as_of or row.status != '承認済み'
            or not row.stop_history_reviewed or not row.instruction_context_verified
            or original.get('judgment_fingerprint') not in row.instruction_history_fingerprints):
        return None, '既存指示の原版・現在状態・登録履歴の一致を確認要。指示を解除せず保存版を保持します'
    try:
        stamp = datetime.fromisoformat(original['priority_instruction_context']['recorded_at'])
        observed = stamp.astimezone(ZoneInfo('Asia/Tokyo')).date() if stamp.tzinfo else None
    except (KeyError, TypeError, ValueError):
        observed = None
    actor_label = _text(original.get('judged_by')) or _text(current_judgment.get('judged_by_username'))
    if (original.get('authority_confirmed') is not True
            or original.get('authority_role') not in {'整備管理者', '補助者'}
            or not _text(original.get('judged_by_identity'))
            or type(original.get('judged_by_user_id')) is not int
            or original['judged_by_user_id'] <= 0 or not _text(original.get('reason'))
            or observed is None or observed > as_of or not actor_label):
        return None, '既存指示の権限・指示者・日時・理由の登録を確認要'
    sid = f'inspection:{row.record_id}'
    scope = Scope(row.company_code, row.vehicle_id, '既存の運行判断の確認')
    event = original['input_ref']
    evidence = {sid: Evidence(sid, scope, observed, event,
        '権限者が登録した車両全体の運行不可判断: ' + original['reason'], True, 'instruction', 'active')}
    candidate = Candidate(item['proposal_id'], scope, event,
        facts=(Fact('operation_instruction_active', (sid,), True),),
        missing_conditions=('個別部品の原因は認定していません。既存指示の対象・対応を責任者へ確認してください',),
        input_is_current=is_current)
    result = assess_priority(candidate, evidence, {}, as_of=as_of)
    result['disclaimer'] = DISCLAIMER
    result['instruction_details'] = {
        'scope': 'whole_vehicle', 'recorded_status': original['status'],
        'actor_name': actor_label,
        'authority_role': original['authority_role'],
        'recorded_at': original['priority_instruction_context']['recorded_at'],
        'reason': original['reason'], 'source_id': sid,
    }
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
                     is_current=None, unavailable_reason=None, timing_results=None):
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
    suppressed_indices = set()
    resolved_proposals = []
    for index, item in enumerate(proposals):
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
        elif str(item.get('priority_input_ref') or '').startswith('timing:'):
            result, reason = (timing_results or {}).get(index, (None, '適用済み時期の現在根拠を確認要'))
            if reason:
                reasons.append(reason)
        elif len(matching) != 1 or len({sid for sid in refs if sid.startswith('inspection:')}) != 1:
            reasons.append('提案と現在の具体的な点検事象の一意な対応は未接続です')
        else:
            sid = matching[0]
            original = source_map[sid]
            proof = original.get('priority_provenance') if isinstance(original, dict) else None
            offered = inspection_inputs(proof)
            instruction = next((v for v in offered if v['ref'] == item.get('priority_input_ref')
                                and v['kind'] == 'registered_operation_instruction'), None)
            if instruction:
                result, reason = _instruction_candidate(item, proof, scoped[sid], as_of, is_current)
            else:
                event_number, reason = _bound_event(item, proof, scoped[sid])
                if reason is None:
                    result, reason = _inspection_candidate(item, scoped[sid], as_of, is_current, event_number)
            if reason:
                reasons.append(reason)
        fingerprint = _hash({'company': company_code, 'vehicle': vehicle_id, 'as_of': as_of,
            'sources': {sid: source_map.get(sid) for sid in ref_values if isinstance(sid, str)},
            'registered_fingerprint': registered_fingerprint})
        if result is not None and result.get('suppressed') is True:
            suppressed_indices.add(index)
            resolved_proposals.append({
                'proposal_id': item['proposal_id'], 'proposal_revision': item['proposal_revision'],
                'source_ids': item['source_ids'], 'reason': result['reason']})
            continue
        value = _legacy(item, as_of, reasons, fingerprint)
        if result is not None:
            value.update({key: result[key] for key in ('label', 'base_score', 'effective_score',
                'floor_adjustment', 'applied_floors', 'evidence_status', 'missing_axes',
                'missing_conditions', 'source_ids', 'requires_professional_review', 'disclaimer',
                'earliest_due_on', 'first_observed_on')})
            value.update(calculation_status='computed', observed_at=result['observed_on'],
                applicable_reference_ids=result['reference_ids'],
                factors=[dict(axis=f['axis'], points=f['points'], source_ids=f['source_ids'],
                    rule_ids=sorted(set(f['fact_codes']) | set(f.get('rule_ids', []))),
                    reference_ids=f['reference_ids']) for f in result['factors']])
            if isinstance(result.get('scope'), dict) and isinstance(result['scope'].get('target'), str):
                value['subject_label'] = result['scope']['target']
            for field in ('instruction_details', 'timing_reference', 'timing_origin_on',
                          'timing_relation', 'timing_criteria', 'timing_rule_key'):
                if result.get(field) is not None:
                    value[field] = result[field]
            item['priority'] = value['label']
        item['priority_assessment'] = value
    proposals = [item for index, item in enumerate(proposals) if index not in suppressed_indices]
    output['recommendations'] = proposals
    output['priority_resolved_proposals'] = resolved_proposals
    output['priority_assessment_version'] = VERSION
    ordered_indices = sorted((index for index,value in enumerate(proposals) if isinstance(value,dict)),
                             key=lambda index: priority_order_key(proposals[index]))
    output['priority_order_format'] = 'source_indices_v1'
    output['priority_order_indices'] = ordered_indices
    output['priority_order'] = [proposals[index]['proposal_id'] for index in ordered_indices
                               if isinstance(proposals[index].get('proposal_id'),str)]
    return output
