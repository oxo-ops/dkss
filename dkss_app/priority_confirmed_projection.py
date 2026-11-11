"""Generation-bound optional confirmations -> the shared priority projection.

Only a proof captured with a newly generated proposal can apply a confirmation.
Saved labels/identities are never backfilled from today's approval. Explicit
withdrawal suppresses only the offer based on that exact confirmation event.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import re
from zoneinfo import ZoneInfo

from vehicle_priority_assessment import Candidate, assess_priority
from vehicle_priority_inputs import display_target, fingerprint, generation_priority_inputs
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


def _input_values(entry, *, as_of):
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
    return values


def _group_key(values):
    return fingerprint([vars(values['scope']), values['event_id']])


def _assessment_many(entries, candidate_id, *, as_of, is_current):
    """Same original event only; core maxima/floors still own all scoring."""
    rows = [(entry, _input_values(entry, as_of=as_of)) for entry in entries]
    if not rows or any(values.get('skip_assessment') or not (values.get('facts') or values.get('timings')) for _, values in rows):
        return None
    if len({_group_key(values) for _, values in rows}) != 1:
        raise ValueError('異なる対象・原事象の確認を合算しません')
    facts, timings, evidence, references, missing, details = [], [], {}, {}, [], []
    for entry, values in rows:
        renamed = {key: (key if len(rows) == 1 else f"{key}:confirmation:{entry['event_id']}") for key in values['references']}
        for key, value in values['references'].items():
            references[renamed[key]] = replace(value, reference_id=renamed[key])
        for key, value in values['evidence'].items():
            previous = evidence.get(key)
            if previous is not None and replace(previous, excerpt=value.excerpt) != value:
                raise ValueError('同じ出典IDの観測・対象・状態が一致しません')
            evidence[key] = value
        facts.extend(replace(value, reference_ids=tuple(renamed[key] for key in value.reference_ids)) for value in values.get('facts', ()))
        timings.extend(replace(value, reference_ids=tuple(renamed[key] for key in value.reference_ids)) for value in values.get('timings', ()))
        missing.extend(values.get('missing_conditions', ()))
        actor, preview = entry['actor'], entry['preview']
        details.append({'kind': entry['kind'], 'event_id': entry['event_id'],
            'confirmed_at': entry['confirmed_at'], 'actor_name': actor.get('name') or actor['username'],
            'statements': [value['label'] for value in preview['statements']],
            'display_sources': deepcopy(preview.get('display_sources', []))})
    values = rows[0][1]
    candidate = Candidate(candidate_id, values['scope'], values['event_id'],
        facts=tuple(facts), timings=tuple(timings), missing_conditions=tuple(dict.fromkeys(missing)), input_is_current=is_current)
    result = assess_priority(candidate, evidence, references, as_of=as_of)
    if not result['source_ids'] or result['evidence_status'] == '根拠不足':
        return None
    result['confirmation_details'] = details[0]
    if len(details) > 1:
        result['confirmation_details_list'] = details
    result['disclaimer'] = DISCLAIMER
    return result


def _assessment(entry, candidate_id, *, as_of, is_current):
    return _assessment_many([entry], candidate_id, as_of=as_of, is_current=is_current)


DETERMINISTIC_KEY = '_confirmed_priority_candidates'
DETERMINISTIC_VERSION = 'confirmed-priority-candidates-v1'


def _observation_ref(entry):
    selection = entry['selection']
    if entry['kind'] == 'progression':
        return selection['current_observation'].split('|', 1)[0]
    if entry['kind'] == 'manufacturer_immediate':
        return selection['observation_input_ref']
    return None  # Whole-vehicle legal expiry never binds a component proposal.


def _deterministic_candidates(entries, *, as_of):
    groups = {}
    for entry in entries:
        key = _group_key(_input_values(entry, as_of=as_of))
        groups.setdefault(key, []).append(entry)
    result = []
    for key, group in sorted(groups.items()):
        group.sort(key=lambda entry: entry['event_id'])
        assessment = _assessment_many(group, 'confirmed:' + key, as_of=as_of, is_current=True)
        if assessment is None:
            continue
        refs = [confirmation_ref(entry) for entry in group]
        ids = sorted({sid for entry in group for sid in entry['source_ids'] + [f"priority_confirmation:{entry['event_id']}"]})
        knowledge = [sid for sid in ids if sid.startswith('knowledge:')]
        proposal = dict(priority=assessment['label'], category='整備・点検', target=display_target(group[0]['subject']),
            title='確認した原記録に基づく対応', current_state='元記録と適用条件を担当者が確認',
            action='根拠を確認し、責任者・整備担当者が対応', timing='確認した根拠に従って対応',
            reason='元の観測・原本と任意の事実確認から、承認済みの優先度条件を算定しています。',
            uncertainty='運行可否や既存指示の解除は自動判定していません。',
            confirmation_steps=['表示された元記録・原本と確認内容を確認', '責任者・整備担当者が対応を判断'],
            confirmation_branch='元記録や適用条件が変わった場合は根拠確認を訂正し、通常分析を更新してください。',
            risk='この候補は確認・対応の優先度です。運行可否は責任者が判断してください。',
            risk_status='unassessed', risk_basis='unknown', risk_condition='', risk_effect='', risk_evidence=[], risk_source_ids=[],
            basis_type='登録済み整備知識' if knowledge else '記録上の指摘・対応', knowledge_ids=knowledge,
            source_ids=ids, priority_input_ref=refs[0], priority_confirmation_refs=refs,
            priority_candidate_origin=DETERMINISTIC_VERSION)
        result.append({'key': key, 'proposal': proposal, 'score': assessment['effective_score'],
            'observation_refs': sorted({ref for entry in group if (ref := _observation_ref(entry))})})
    return result


def finalize_confirmed_priority_candidates(result, payload):
    """New generation only: fill valid facts omitted by AI, without a five-item cap.

    Private candidates are constructed by the server from verified inputs before
    model transport. Neither a model output nor today's GET can introduce them.
    Ordinary proposals stay byte-for-byte intact; projection deduplicates their
    display only while the exact confirmed candidate remains. Cancellation must
    not remove the original unresolved finding. The host assigns IDs/revisions
    afterward using its unchanged algorithm.
    """
    candidates = payload.get(DETERMINISTIC_KEY)
    if not candidates:
        return result
    if not isinstance(result, dict) or not isinstance(result.get('recommendations'), list):
        raise ValueError('INVALID_CONFIRMED_PRIORITY_RESULT')
    if not isinstance(candidates, list) or len(candidates) > MAX_CONFIRMATIONS:
        raise ValueError('CONFIRMED_PRIORITY_CANDIDATE_LIMIT')
    offered = generation_priority_inputs(payload)
    output = deepcopy(result)
    items = output['recommendations']
    consumed = set()
    replacements, appended = {}, []
    for candidate in candidates:
        proposal = candidate['proposal']
        refs = proposal['priority_confirmation_refs']
        if not refs or any(ref not in offered or offered[ref].get('kind') != 'confirmed_priority' for ref in refs):
            raise ValueError('INVALID_CONFIRMED_PRIORITY_CANDIDATE')
        matches = [index for index, item in enumerate(items) if index not in consumed and isinstance(item, dict)
            and item.get('category') == proposal['category'] and item.get('target') == proposal['target']
            and item.get('priority_input_ref') in refs]
        originals = [index for index, item in enumerate(items) if isinstance(item, dict)
            and item.get('category') == proposal['category'] and item.get('target') == proposal['target']
            and item.get('priority_input_ref') in candidate['observation_refs']]
        chosen = matches[0] if matches else (originals[0] if originals else None)
        item = deepcopy(items[chosen]) if chosen is not None else deepcopy(proposal)
        item.update({key: deepcopy(proposal[key]) for key in
            ('priority_input_ref', 'priority_confirmation_refs', 'priority_candidate_origin')})
        item['source_ids'] = sorted(set(item.get('source_ids', [])) | set(proposal['source_ids']))
        item['knowledge_ids'] = [sid for sid in item['source_ids'] if sid.startswith('knowledge:')]
        item['basis_type'] = '登録済み整備知識' if item['knowledge_ids'] else '記録上の指摘・対応'
        labels = ('低', '中', '高')
        item['priority'] = labels[max(labels.index(item['priority']), labels.index(proposal['priority']))]
        # Preserve different actions even for the same observation. Original
        # candidates remain stored unchanged and regain visibility on withdrawal.
        item['priority_base_candidates'] = [{key: items[index].get(key) for key in
            ('priority_input_ref', 'target', 'action', 'title')} for index in originals
            if items[index].get('action') == item.get('action') and items[index].get('title') == item.get('title')]
        if matches:
            replacements[chosen] = item
            consumed.update(index for index in matches if items[index].get('action') == item.get('action')
                and items[index].get('title') == item.get('title'))
        else:
            appended.append(item)
    output['recommendations'] = [replacements[index] if index in replacements else item
        for index, item in enumerate(items) if index not in consumed or index in replacements] + appended
    # Presentation recomputes these from the actual projected list, never AI totals.
    for key in ('priority_summary', 'priority_order', 'priority_order_format'):
        output.pop(key, None)
    return output


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
    attached, included = [], []
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
            included.append(entry)
        except (ValueError, TypeError, KeyError):
            continue
    if included:
        payload[DETERMINISTIC_KEY] = _deterministic_candidates(included, as_of=as_of)
    return attached


def _dedupe_candidates(item, base_refs):
    if item.get('priority_candidate_origin') != DETERMINISTIC_VERSION:
        return []
    values = item.get('priority_base_candidates')
    if not isinstance(values, list) or len(values) > 100:
        return []
    return [value for value in values if isinstance(value, dict)
        and set(value) == {'priority_input_ref', 'target', 'action', 'title'}
        and value['priority_input_ref'] in base_refs and value['target'] == item['target']
        and all(isinstance(value[key], str) and value[key] for key in ('action', 'title'))
        and value['action'] == item.get('action') and value['title'] == item.get('title')]


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
            refs = item.get('priority_confirmation_refs', [item['priority_input_ref']])
            if (not isinstance(refs, list) or not 1 <= len(refs) <= MAX_CONFIRMATIONS
                    or any(not isinstance(ref, str) for ref in refs) or len(set(refs)) != len(refs)
                    or item['priority_input_ref'] not in refs):
                continue
            checked, base_refs, keys = [], [], set()
            for raw_ref in refs:
                match = REF.fullmatch(raw_ref)
                if match is None or int(match[1]) > 2147483647:
                    raise ValueError('確認参照の形式を確認要')
                number = int(match[1]); sid = f'priority_confirmation:{number}'
                source = sources.get(sid) if isinstance(sources, dict) else None
                saved = source.get(PROOF_KEY) if isinstance(source, dict) else None
                current = entries.get(number)
                if (not isinstance(saved, dict) or current is None or saved != _proof(current)
                        or saved['company_code'] != vehicle.company_code or saved['vehicle_id'] != vehicle.id
                        or confirmation_ref(saved) != raw_ref
                        or item.get('target') != display_target(saved['subject'])
                        or item.get('category') != '整備・点検'
                        or not isinstance(item.get('source_ids'), list)
                        or not set(saved['source_ids'] + [sid]).issubset(item['source_ids'])):
                    raise ValueError('生成時の全確認proofを照合できません')
                observation = _observation_ref(saved)
                event = ':'.join(observation.split(':')[:4]) if observation else 'certificate-expiry:' + saved['selection']['document_id']
                keys.add((saved['company_code'], saved['vehicle_id'], saved['subject'], event))
                if observation:
                    base_refs.append(observation)
                checked.append(current)
            if len(keys) != 1:
                raise ValueError('異なる対象・原事象をまとめません')
            remaining = [entry for entry in checked if entry['status'] not in {'withdrawn', 'resolved'}]
            if not remaining:
                values[index] = ({'suppressed': True,
                    'reason': 'この候補の事実確認が取り消されたか元指摘が真正に解消したため、確認候補のみを表示対象から外しました'}, None)
            elif all(entry['status'] == 'active' for entry in remaining):
                result = _assessment_many(remaining, item['proposal_id'], as_of=as_of, is_current=is_current)
                if result is not None:
                    result['dedupe_base_candidates'] = _dedupe_candidates(item, base_refs)
                    if len(remaining) != len(checked):
                        result['missing_conditions'].append('取り消された確認根拠は算定から除外しています。元の点検状態・運行判断を変更するものではありません')
                values[index] = (result, None if result is not None else 'この条件で新しい点数を付ける根拠が成立していないため、保存区分を保持します')
            else:
                values[index] = ({'held': True, 'dedupe_base_candidates': _dedupe_candidates(item, base_refs)},
                    '確認後に元記録・適用日・原本が変わったため、前の区分を無点数で保持しています。元の根拠を再確認してください')
        except (ValueError, TypeError, KeyError):
            continue
    return values
