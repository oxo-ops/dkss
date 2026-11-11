"""Explicit server-issued proposal references; never AI approval of a fact.

The model may select one offered subject, but cannot mint an event or authorize
facts. Projection checks the original server proof against current scoped data.
"""
import hashlib
import json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), default=str).encode()).hexdigest()


def display_target(value):
    """One deterministic display name, not an AI-created component alias."""
    return ' '.join(value.split())[:24] if isinstance(value, str) else ''


def inspection_inputs(proof):
    if not isinstance(proof, dict):
        return []
    sid = f"inspection:{proof.get('record_id')}"
    result = []
    events = proof.get('events')
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or not event.get('input_ref'):
            continue
        result.append({'ref': event['input_ref'], 'kind': 'inspection_defect',
            'source_ids': [sid], 'target': event.get('item_content'),
            'display_target': display_target(event.get('item_content')),
            'item_code': event.get('item_code'), 'defect_no': event.get('defect_no')})
    instruction = proof.get('instruction')
    if (proof.get('instruction_available_for_generation') is True
            and isinstance(instruction, dict) and instruction.get('input_ref')):
        result.append({'ref': instruction['input_ref'], 'kind': 'registered_operation_instruction',
            'source_ids': [sid], 'target': '既存の運行判断の確認',
            'display_target': '既存の運行判断の確認',
            'recorded_status': instruction.get('status'), 'minimum_saved_priority': '高',
            'scope': 'この点検に登録された車両全体の既存判断。個別部品の原因ではありません。'})
    return result


def offered_priority_inputs(payload):
    values = []
    for record in payload.get('records', []):
        if isinstance(record, dict):
            offered = record.get('priority_inputs')
            if isinstance(offered, list):
                values.extend(offered)
    for knowledge in payload.get('maintenance_knowledge', []):
        if isinstance(knowledge, dict):
            offered = knowledge.get('priority_inputs')
            if isinstance(offered, list):
                values.extend(offered)
    return {value['ref']: value for value in values
            if isinstance(value, dict) and isinstance(value.get('ref'), str)}


def generation_priority_inputs(payload):
    """Use original server refs even when full-history review compresses records.

    A fully reviewed final stage may choose only a subject already present in
    its reviewed candidates. The large raw proof stays local, not in AI input.
    """
    original = payload.get('_risk_evidence_payload', payload)
    offered = offered_priority_inputs(original)
    if payload.get('analysis_stage') == 'final' and 'review_candidates' in payload:
        refs = {value['proposal'].get('priority_input_ref')
                for value in payload.get('review_candidates', [])
                if isinstance(value, dict) and isinstance(value.get('proposal'), dict)
                and isinstance(value['proposal'].get('priority_input_ref'), str)}
        offered = {ref: value for ref, value in offered.items() if ref in refs}
    return offered


def validate_priority_input(item, payload):
    """Preserve old output compatibility, reject invented/rebound explicit refs."""
    ref = item.get('priority_input_ref', '')
    if not isinstance(ref, str):
        raise ValueError('INVALID_PRIORITY_INPUT_REFERENCE')
    if not ref:
        return
    if item.get('category') != '整備・点検':
        raise ValueError('INVALID_PRIORITY_INPUT_CATEGORY')
    offered = generation_priority_inputs(payload).get(ref)
    if offered is None or not set(offered['source_ids']).issubset(item.get('source_ids', [])):
        raise ValueError('INVALID_PRIORITY_INPUT_REFERENCE')
    if item.get('target') != display_target(offered.get('target')):
        raise ValueError('INVALID_PRIORITY_INPUT_TARGET')
    if offered.get('kind') == 'registered_operation_instruction':
        # Newly generated output only. Later read failures retain this known
        # instruction priority; existing saved JSON is never migrated.
        item['priority'] = '高'

    if offered.get('kind') == 'confirmed_priority':
        labels = ('低', '中', '高')
        minimum = offered.get('minimum_saved_priority')
        if minimum not in labels or item.get('priority') not in labels:
            raise ValueError('INVALID_PRIORITY_INPUT_CONFIRMED_FLOOR')
        # This label comes from the server core using the original confirmed
        # proof, never a client/model score. New output only; no saved migration.
        item['priority'] = labels[max(labels.index(item['priority']), labels.index(minimum))]
