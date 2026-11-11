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
    candidates = payload.get(DETERMINISTIC_KEY) or []
    carries = payload.get('_held_confirmed_priority_candidates') or []
    if not candidates and not carries:
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
    carry_keys = {value['key'] for value in carries}
    replaced_refs = {ref for candidate in candidates if candidate['key'] in carry_keys for ref in candidate['proposal']['priority_confirmation_refs']}
    consumed.update(index for index, item in enumerate(items) if isinstance(item, dict) and item.get('priority_input_ref') in replaced_refs)
    for candidate in candidates:
        if candidate['key'] in carry_keys:
            continue
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
        item.pop('priority_candidate_carryover', None)
        item['priority'] = proposal['priority']
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
    for carried in carries:
        refs = carried['proposal']['priority_confirmation_refs']
        output['recommendations'] = [item for item in output['recommendations'] if not isinstance(item, dict)
            or item.get('priority_input_ref') not in refs]
        output['recommendations'].append(deepcopy(carried['proposal']))
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
    if sum(entry['status'] == 'active' for entry in entries) > MAX_CONFIRMATIONS:
        raise ValueError('CONFIRMED_PRIORITY_CANDIDATE_LIMIT')
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
            source = {'label': '確認した優先度の根拠：' + entry['subject'], 'url': link, PROOF_KEY: proof,
                'priority_confirmation_display': deepcopy(result['confirmation_details'])}
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


CARRY_VERSION = 'previous-confirmed-priority-result-v1'


def _entry_key(saved):
    observation = _observation_ref(saved)
    event = ':'.join(observation.split(':')[:4]) if observation else 'certificate-expiry:' + saved['selection']['document_id']
    return fingerprint([{'company_code': saved['company_code'], 'vehicle_id': saved['vehicle_id'], 'target': saved['subject']}, event])


def _saved_candidates(analysis, sources, vehicle):
    """Inspect only already saved generation proof, never infer a new approval."""
    items = analysis.get('recommendations') if isinstance(analysis, dict) else None
    if not isinstance(items, list) or not isinstance(sources, dict):
        return []
    result = []
    for item in items:
        if not isinstance(item, dict) or item.get('priority') not in {'高', '中', '低'}:
            continue
        try:
            refs = item.get('priority_confirmation_refs', [item.get('priority_input_ref')])
            if (not isinstance(refs, list) or not 1 <= len(refs) <= MAX_CONFIRMATIONS
                    or any(not isinstance(ref, str) or REF.fullmatch(ref) is None for ref in refs)
                    or len(set(refs)) != len(refs) or item.get('priority_input_ref') not in refs):
                continue
            proofs = []
            for ref in refs:
                sid = f"priority_confirmation:{int(REF.fullmatch(ref)[1])}"
                value = sources.get(sid)
                saved = value.get(PROOF_KEY) if isinstance(value, dict) else None
                if (not isinstance(saved, dict) or set(PROOF_FIELDS) - set(saved)
                        or saved['company_code'] != vehicle.company_code or saved['vehicle_id'] != vehicle.id
                        or confirmation_ref(saved) != ref or item.get('category') != '整備・点検'
                        or item.get('target') != display_target(saved['subject'])
                        or not isinstance(item.get('source_ids'), list)
                        or not set(saved['source_ids'] + [sid]).issubset(item['source_ids'])):
                    raise ValueError('保存された原確認のscopeを確認要')
                proofs.append(saved)
            keys = {_entry_key(proof) for proof in proofs}
            if len(keys) != 1:
                continue
            result.append({'key': next(iter(keys)), 'proposal': deepcopy(item), 'proofs': deepcopy(proofs),
                'sources': {sid: deepcopy(sources[sid]) for sid in item['source_ids'] if sid in sources}})
        except (ValueError, TypeError, KeyError):
            continue
    if len(result) > MAX_CONFIRMATIONS:
        raise ValueError('CONFIRMED_PRIORITY_CANDIDATE_LIMIT')
    return result


def _candidate_state(candidate, statuses):
    remaining = []
    for saved in candidate['proofs']:
        current = statuses.get(saved['event_id'])
        if current is None or _proof(current) != saved:
            remaining.append('held')
        elif current['status'] not in {'withdrawn', 'resolved'}:
            remaining.append(current['status'])
    if not remaining:
        return 'terminal'
    return 'active' if all(value == 'active' for value in remaining) else 'held'


def _statuses(vehicle, as_of):
    from .priority_confirmations import confirmation_statuses
    from sqlalchemy.exc import SQLAlchemyError
    try:
        return {value['event_id']: value for value in confirmation_statuses(vehicle, as_of=as_of)}
    except (ValueError, TypeError, SQLAlchemyError):
        return {}  # Unavailable is not cancellation or a new fact.


def _historical_details(proofs, sources):
    values = []
    for proof in proofs:
        source = sources.get(f"priority_confirmation:{proof['event_id']}", {})
        display = source.get('priority_confirmation_display') if isinstance(source, dict) else None
        actor = proof['actor'].get('name') or proof['actor']['username']
        if (isinstance(display, dict) and display.get('event_id') == proof['event_id']
                and display.get('kind') == proof['kind'] and display.get('confirmed_at') == proof['confirmed_at']
                and display.get('actor_name') == actor):
            values.append(deepcopy(display))
        else:
            values.append({'kind': proof['kind'], 'event_id': proof['event_id'], 'confirmed_at': proof['confirmed_at'],
                'actor_name': actor, 'statements': ['当時の任意確認の保存記録です。現在の条件成立を示すものではありません。'],
                'display_sources': [{'label': '前回保存時の元確認',
                    'text': 'この保存世代には原文の表示内容を保存していません。元確認画面で当時の原本・観測を確認してください。',
                    'url': source.get('url') or f"/vehicle/karte/{proof['vehicle_id']}/analysis#priority-evidence"}]})
    return values


def _carry(candidate, previous_generated_at):
    from .analysis_feedback import vehicle_analysis_proposal_ids
    item = deepcopy(candidate['proposal'])
    old = item.get('priority_candidate_carryover')
    marker = old if isinstance(old, dict) and old.get('version') == CARRY_VERSION else None
    expected_dates = [proof['confirmed_at'] for proof in candidate['proofs']]
    if marker is not None and (marker.get('label') != item['priority'] or marker.get('confirmed_at') != expected_dates
            or re.fullmatch('[0-9a-f]{64}', str(marker.get('original_revision', ''))) is None):
        marker = None
    if marker is None:
        item.pop('priority_candidate_carryover', None)
        _, revision = vehicle_analysis_proposal_ids(item)
        marker = {'version': CARRY_VERSION, 'original_revision': revision,
            'previous_generated_at': str(previous_generated_at or ''),
            'confirmed_at': [proof['confirmed_at'] for proof in candidate['proofs']], 'label': item['priority'],
            'reason': '前回保存時の区分です。現在の原本・観測・適用日または確認者の情報を再検証できないため、現在の点数は表示していません。'}
    item['priority_candidate_carryover'] = deepcopy(marker)
    item['priority_historical_confirmations'] = _historical_details(candidate['proofs'], candidate['sources'])
    item['priority_confirmation_refs'] = [confirmation_ref(proof) for proof in candidate['proofs']]
    return {**deepcopy(candidate), 'proposal': item}


def _retain_sources(sources, candidate):
    for sid, value in candidate['sources'].items():
        if sid.startswith('priority_confirmation:'):
            sources[sid] = deepcopy(value)  # Exact old audit proof, never a current replacement.
        elif sid not in sources and isinstance(value, dict):
            # Only a link is needed for old history display. Never replace a
            # current inspection/timing/knowledge version with an old proof.
            sources[sid] = {key: deepcopy(value[key]) for key in ('label', 'url') if key in value}


def prepare_held_confirmed_candidates(vehicle, payload, sources, previous_bundle, *, as_of=None):
    """Keep saved history private; it is not supplied to AI as a current fact."""
    as_of = as_of or datetime.now(ZoneInfo('Asia/Tokyo')).date()
    previous_bundle = previous_bundle if isinstance(previous_bundle, dict) else {}
    candidates = _saved_candidates(previous_bundle.get('analysis'), previous_bundle.get('sources'), vehicle)
    statuses = _statuses(vehicle, as_of)
    payload['_previous_confirmed_priority_candidates'] = candidates
    payload['_previous_confirmed_priority_generated_at'] = previous_bundle.get('generated_at')
    carries = [_carry(value, previous_bundle.get('generated_at')) for value in candidates if _candidate_state(value, statuses) == 'held']
    payload['_held_confirmed_priority_candidates'] = carries
    for value in carries:
        _retain_sources(sources, value)


def reconcile_confirmed_candidates_before_save(vehicle, result, payload, sources, *, as_of=None):
    """Fence final save against cancellation or source changes during AI work."""
    as_of = as_of or datetime.now(ZoneInfo('Asia/Tokyo')).date()
    statuses = _statuses(vehicle, as_of)
    previous = payload.get('_previous_confirmed_priority_candidates') or []
    carries = [_carry(value, payload.get('_previous_confirmed_priority_generated_at'))
        for value in previous if _candidate_state(value, statuses) == 'held']
    for value in carries:
        _retain_sources(sources, value)
    payload['_held_confirmed_priority_candidates'] = carries
    final = finalize_confirmed_priority_candidates(result, payload)
    candidates = _saved_candidates(final, sources, vehicle)
    dispositions = {value['proposal']['priority_input_ref']: _candidate_state(value, statuses) for value in candidates}
    carry_refs = {ref for value in carries for ref in value['proposal']['priority_confirmation_refs']}
    removed = False
    items = []
    for item in final.get('recommendations', []):
        ref = item.get('priority_input_ref') if isinstance(item, dict) else None
        state = dispositions.get(ref)
        if state == 'terminal' or (state == 'held' and ref not in carry_refs):
            removed = True
            continue  # No previous saved result exists: do not invent one.
        items.append(item)
    final = deepcopy(final)
    final['recommendations'] = items
    if removed:
        final['priority_generation_notice'] = '生成中に取消・解消または根拠の変更を確認した候補は確定していません。現在の記録で再生成してください。'
    return final


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
        previous = _saved_candidates({'recommendations': [item]}, sources, vehicle)
        if previous:
            values[index] = ({'held': True,
                'historical_confirmation_details': _historical_details(previous[0]['proofs'], sources),
                'previous_result': deepcopy(item.get('priority_candidate_carryover'))}, reason)
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
            elif all(entry['status'] == 'active' for entry in remaining) and not item.get('priority_candidate_carryover'):
                result = _assessment_many(remaining, item['proposal_id'], as_of=as_of, is_current=is_current)
                if result is not None:
                    result['dedupe_base_candidates'] = _dedupe_candidates(item, base_refs)
                    if len(remaining) != len(checked):
                        result['missing_conditions'].append('取り消された確認根拠は算定から除外しています。元の点検状態・運行判断を変更するものではありません')
                values[index] = (result, None if result is not None else 'この条件で新しい点数を付ける根拠が成立していないため、保存区分を保持します')
            else:
                values[index] = ({'held': True, 'dedupe_base_candidates': _dedupe_candidates(item, base_refs), 'previous_result': deepcopy(item.get('priority_candidate_carryover')), 'historical_confirmation_details': _historical_details([_proof(entry) for entry in checked], sources)},
                    '確認後に元記録・適用日・原本が変わったため、前の区分を無点数で保持しています。元の根拠を再確認してください')
        except (ValueError, TypeError, KeyError):
            continue
    return values
