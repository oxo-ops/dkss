"""Generation-bound optional confirmations -> the shared priority projection.

Only a proof captured with a newly generated proposal can apply a confirmation.
Saved labels/identities are never backfilled from today's approval. Explicit
withdrawal suppresses only the offer based on that exact confirmation event.
"""
from copy import deepcopy
from datetime import datetime
import re
from zoneinfo import ZoneInfo

from vehicle_priority_assessment import Candidate, assess_priority
from vehicle_priority_inputs import display_target
from vehicle_priority_projection import DISCLAIMER

PROOF_KEY = 'priority_confirmation_proof'
MAX_CONFIRMATIONS = 100
REF = re.compile(r'confirmation:([1-9][0-9]{0,9}):([0-9a-f]{24})\Z')
PROOF_FIELDS = ('version', 'company_code', 'vehicle_id', 'event_id', 'kind', 'selection',
    'fingerprint', 'sources', 'statements', 'subject', 'source_ids', 'confirmed_at', 'actor')


def confirmation_ref(value):
    return f"confirmation:{value['event_id']}:{value['fingerprint'][:24]}"


def _proof(entry):
    return {key: deepcopy(entry[key]) for key in PROOF_FIELDS}


def _assessment(entry, candidate_id, *, as_of, is_current):
    kind = entry['kind']
    preview = entry['preview']
    stamp = datetime.fromisoformat(entry['confirmed_at'])
    if stamp.utcoffset() is None or stamp.date() > as_of:
        raise ValueError('確認日時を確認要')
    if kind == 'progression':
        from .priority_progression import progression_confirmation_inputs as inputs
        values = inputs(preview, event_id=entry['event_id'], confirmed_on=stamp.date(), as_of=as_of)
    elif kind == 'manufacturer_immediate':
        from .priority_manufacturer_evidence import manufacturer_confirmation_inputs as inputs
        values = inputs(preview, event_id=entry['event_id'], confirmed_on=stamp.date())
    elif kind == 'legal_deadline':
        from .priority_certificate_sources import certificate_confirmation_inputs as inputs
        values = inputs(preview, event_id=entry['event_id'], confirmed_on=stamp.date(), as_of=as_of)
    else:
        raise ValueError('確認の種別を確認要')
    if values.get('skip_assessment') or not (values.get('facts') or values.get('timings')):
        return None
    candidate = Candidate(candidate_id, values['scope'], values['event_id'],
        facts=values.get('facts', ()), timings=values.get('timings', ()),
        missing_conditions=values.get('missing_conditions', ()), input_is_current=is_current)
    result = assess_priority(candidate, values['evidence'], values['references'], as_of=as_of)
    if not result['source_ids'] or result['evidence_status'] == '根拠不足':
        return None  # Failure to apply a fact is not a verified zero/low assessment.
    actor = entry['actor']
    result['confirmation_details'] = {'kind': kind, 'event_id': entry['event_id'],
        'confirmed_at': entry['confirmed_at'], 'actor_name': actor.get('name') or actor['username'],
        'statements': [value['label'] for value in preview['statements']],
        'display_sources': deepcopy(preview.get('display_sources', []))}
    result['disclaimer'] = DISCLAIMER
    return result


def attach_confirmed_priority_inputs(vehicle, payload, sources, *, as_of=None):
    """Offer current confirmed subjects and bind their ORIGINAL proof at generation."""
    from .priority_confirmations import confirmation_statuses
    as_of = as_of or datetime.now(ZoneInfo('Asia/Tokyo')).date()
    from sqlalchemy.exc import SQLAlchemyError
    try:
        entries = confirmation_statuses(vehicle, as_of=as_of)
    except (ValueError, TypeError, SQLAlchemyError):
        return []
    if len(entries) > MAX_CONFIRMATIONS:
        return []
    attached = []
    for entry in entries:
        if entry['status'] != 'active':
            continue
        try:
            result = _assessment(entry, f'confirmation:{entry["event_id"]}', as_of=as_of, is_current=True)
            if result is None:
                continue
            sid = f'priority_confirmation:{entry["event_id"]}'
            proof = _proof(entry)
            required = list(dict.fromkeys(entry['source_ids'] + [sid]))
            link = f'/vehicle/karte/{vehicle.id}/analysis#priority-evidence'
            source = {'label': '確認した優先度の根拠：' + entry['subject'], 'url': link, PROOF_KEY: proof}
            sources[sid] = source
            links = entry['preview'].get('source_links') or {}
            for source_id in required:
                if source_id == sid:
                    continue
                metadata = links.get(source_id) if isinstance(links, dict) else None
                if isinstance(metadata, dict):
                    sources[source_id] = {**sources.get(source_id, {}), **deepcopy(metadata)}
            # Every model citation must have an authorized server source. A
            # reference that cannot be displayed is not silently fabricated.
            if any(source_id not in sources for source_id in required):
                sources.pop(sid, None)
                continue
            offer = {'ref': confirmation_ref(entry), 'kind': 'confirmed_priority',
                'target': entry['subject'], 'display_target': display_target(entry['subject']),
                'source_ids': required, 'minimum_saved_priority': result['label']}
            payload.setdefault('records', []).append({'source_id': sid, 'date': entry['confirmed_at'][:10],
                'type': '人が確認した優先度の根拠', 'content': entry['subject'],
                'confirmation_kind': entry['kind'], 'original_observations': deepcopy(entry['preview'].get('display_sources', [])), 'confirmed_statements': [v['label'] for v in entry['preview']['statements']],
                'source_ids': required, 'priority_inputs': [offer]})
            attached.append(offer)
        except (ValueError, TypeError, KeyError):
            continue
    return attached


def project_registered_confirmed_priorities(analysis, vehicle, sources, *, as_of, is_current=None):
    """Map original recommendation indexes to (result, missing reason)."""
    from .priority_confirmations import confirmation_statuses
    from sqlalchemy.exc import SQLAlchemyError
    items = analysis.get('recommendations') if isinstance(analysis, dict) else None
    if not isinstance(items, list):
        return {}
    requested = [(index, item) for index, item in enumerate(items)
        if isinstance(item, dict) and isinstance(item.get('priority_input_ref'), str)
        and item['priority_input_ref'].startswith('confirmation:')]
    if not requested:
        return {}
    if len(requested) > MAX_CONFIRMATIONS:
        return {index: (None, '確認した根拠の読取上限を超えたため保存区分を保持します') for index, _ in requested}
    try:
        entries = {entry['event_id']: entry for entry in confirmation_statuses(vehicle, as_of=as_of)}
    except (ValueError, TypeError, SQLAlchemyError):
        return {index: (None, '確認した根拠の現在状態を読み取れないため保存区分を保持します') for index, _ in requested}
    values = {}
    for index, item in requested:
        reason = '生成時の確認原本・本人・版と現在の確認を照合できないため保存区分を保持します'
        values[index] = (None, reason)
        try:
            ref = REF.fullmatch(item['priority_input_ref'])
            if ref is None or int(ref[1]) > 2147483647:
                continue
            number = int(ref[1]); sid = f'priority_confirmation:{number}'
            source = sources.get(sid) if isinstance(sources, dict) else None
            saved = source.get(PROOF_KEY) if isinstance(source, dict) else None
            current = entries.get(number)
            if (not isinstance(saved, dict) or current is None or saved != _proof(current)
                    or saved['company_code'] != vehicle.company_code or saved['vehicle_id'] != vehicle.id
                    or confirmation_ref(saved) != item['priority_input_ref']
                    or item.get('target') != display_target(saved['subject'])
                    or item.get('category') != '整備・点検'
                    or not isinstance(item.get('source_ids'), list)
                    or not set(saved['source_ids'] + [sid]).issubset(item['source_ids'])):
                continue
            if current['status'] in {'withdrawn', 'resolved'}:
                values[index] = ({'suppressed': True,
                    'reason': (current.get('terminal') or {}).get('reason') or 'この事実確認が明示的に取り消されたため、当該確認に基づく提案のみを表示対象から外しました'}, None)
            elif current['status'] == 'active':
                result = _assessment(current, item['proposal_id'], as_of=as_of, is_current=is_current)
                values[index] = (result, None if result is not None else 'この条件で新しい点数を付ける根拠が成立していないため、保存区分を保持します')
            else:
                values[index] = (None, '確認後に元記録・適用日・原本が変わったため、前の区分を無点数で保持しています。元の根拠を再確認してください')
        except (ValueError, TypeError, KeyError):
            continue
    return values
