"""Optional, explicit comparison of two original observations for the S axis.

The user confirms the relation; the server verifies the selected observations,
repair/resolution history, version and scope. No keyword or new defect number
establishes recurrence, and no comparison is inferred from missing records.
"""
from copy import deepcopy
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo

from vehicle_priority_assessment import Scope, Evidence, Fact
from vehicle_priority_inputs import fingerprint
from vehicle_priority_projection import DEFAULT, STANDARD, SAFETY_CODES
from .priority_observations import inspection_observation_options, read_inspection_observation_sources

VERSION = 'confirmed-inspection-progression-v1'
KIND = 'progression'
SELECTION = re.compile(r'(inspection:[1-9][0-9]{0,9}:defect:[1-9][0-9]{0,9}:[0-9a-f]{24})\|(reported|event:[1-9][0-9]{0,9})\Z')


def _day(value):
    try:
        return datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        return None


def _offset_time(value):
    try:
        stamp = datetime.fromisoformat(value)
        return stamp if stamp.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def _observations(source):
    report = source['reported_answer']
    values = [{'value': source['input_ref'] + '|reported', 'input_ref': source['input_ref'],
        'source_id': source['input_ref'] + ':reported', 'kind': 'reported',
        'observed_at': source['reported_at'], 'observed_at_iso': (source.get('reported_at_iso')
            if _offset_time(source.get('reported_at_iso')) and _offset_time(source['reported_at_iso']).strftime('%Y-%m-%d %H:%M:%S') == source['reported_at'] else None), 'status': 'reported',
        'text': str(report.get('content') or '') + '\n回答：' + str(report.get('value') or '')
            + '\n記載：' + str(report.get('comment') or ''),
        'source_url': source['source_url']}]
    for entry in source['transitions'] if source['lifecycle_verified'] else []:
        if entry['kind'] != 'recheck':
            continue
        precise = (datetime.fromisoformat(entry['performed_at']).replace(tzinfo=ZoneInfo(entry['timezone'])).isoformat()
            if len(entry['performed_at']) > 10 else None)
        values.append({'value': source['input_ref'] + f'|event:{entry["event_id"]}',
            'input_ref': source['input_ref'], 'source_id': entry['source_id'], 'kind': 'recheck',
            'observed_at': entry['performed_at'], 'observed_at_iso': precise, 'status': entry['status'], 'result': entry['result'],
            'event_id': entry['event_id'], 'text': entry['note'],
            'source_fingerprint': entry['source_fingerprint'], 'source_url': source['source_url']})
    return values


def options(vehicle, *, as_of):
    source = inspection_observation_options(vehicle, as_of=as_of)
    current, baseline = [], []
    for row in source['options']:
        origin = row['observation']
        for value in _observations(origin):
            option = {'value': value['value'], 'label':
                f"{value['observed_at']} / {origin['target']} / 指摘{origin['defect_no']} / "
                + ('元の報告' if value['kind'] == 'reported' else f"再確認：{value['result']}"),
                'source_url': value['source_url']}
            baseline.append(option)
            if origin['registered_open_answer_matches'] and value.get('result') != '異常なし':
                current.append(option)
    return {'fields': [
        {'key': 'current_observation', 'label': '現在の未解消の観測', 'type': 'select', 'options': current},
        {'key': 'baseline_observation', 'label': '比較元の観測', 'type': 'select', 'options': baseline},
        {'key': 'relation', 'label': '確認する関係', 'type': 'select', 'options': [
            {'value': 'recurrent', 'label': '修理・異常なし確認後の同症状の再発'},
            {'value': 'worsening', 'label': '同じ条件で比較した症状の悪化'}]}],
        'missing_conditions': source['missing_conditions']}


def _selection(selection):
    if (not isinstance(selection, dict) or set(selection) != {'current_observation', 'baseline_observation', 'relation'}
            or selection.get('relation') not in {'recurrent', 'worsening'}):
        raise ValueError('比較する2つの観測と確認する関係を選択してください')
    values = [SELECTION.fullmatch(selection[key]) if isinstance(selection[key], str) else None
              for key in ('current_observation', 'baseline_observation')]
    if any(value is None for value in values) or selection['current_observation'] == selection['baseline_observation']:
        raise ValueError('同一の記録を前後両方に使わず、別の原観測を選択してください')
    return values


def _read(vehicle, selection, as_of):
    selected = _selection(selection)
    refs = list(dict.fromkeys(value[1] for value in selected))
    result = read_inspection_observation_sources(vehicle, refs, as_of=as_of)
    if result['missing_conditions']:
        raise ValueError(' / '.join(result['missing_conditions']))
    by_ref = {source['input_ref']: source for source in result['observations']}
    values = []
    for key, ref in zip(('current_observation', 'baseline_observation'), selected):
        origin = by_ref.get(ref[1])
        choices = [value for value in _observations(origin) if value['value'] == selection[key]] if origin else []
        if len(choices) != 1:
            raise ValueError('選択した原観測の版と整備・再確認履歴を照合できません')
        values.append({'origin': origin, 'observation': choices[0]})
    return values


def progression_terminal_reason(vehicle, selection, *, as_of):
    """An explicit same-defect resolution suppresses only its confirmation offer."""
    try:
        values = _selection(selection)
        current = read_inspection_observation_sources(vehicle, [values[0][1]], as_of=as_of)
        if current['missing_conditions'] or len(current['observations']) != 1:
            return None
        value = current['observations'][0]
        if value['resolved_after_repair_and_recheck']:
            return '同じ指摘が整備後の異常なし再確認で解消したため、この比較確認の提案を表示対象から外しました'
    except (ValueError, TypeError, KeyError):
        pass
    return None


def preview(vehicle, selection, *, as_of):
    current, baseline = _read(vehicle, selection, as_of)
    now, old = current['origin'], baseline['origin']
    observed, previous = current['observation'], baseline['observation']
    if not now['registered_open_answer_matches'] or observed.get('result') == '異常なし':
        raise ValueError('現在の原回答と同じ未解消指摘を確認できません。解消した指摘へS25を継続しません')
    if any(not value['stop_history_reviewed'] or value['has_registered_stop_history'] for value in (now, old)):
        raise ValueError('既存の停止指示の対象・解除範囲をこの比較確認で置き換えず、元の指示を確認してください')
    if (now['original_identity']['item_definition_fingerprint'] != old['original_identity']['item_definition_fingerprint']
            or now['target'] != old['target']):
        raise ValueError('比較する対象項目・様式の版が一致していません。異なる部位へ点数を転用しません')
    before_day, after_day = _day(previous['observed_at']), _day(observed['observed_at'])
    before_time, after_time = _offset_time(previous.get('observed_at_iso')), _offset_time(observed.get('observed_at_iso'))
    same_day_order = (before_day == after_day and before_time is not None and after_time is not None and before_time < after_time)
    if (before_day is None or after_day is None or not before_day <= after_day <= as_of
            or (before_time is not None and after_time is not None and before_time >= after_time)
            or (before_day == after_day and not same_day_order)):
        raise ValueError('原観測の日時で前後関係を確認できません。同日の順序は日付や申告だけから補いません')
    relation = selection['relation']
    if relation == 'recurrent':
        if (now['input_ref'] == old['input_ref'] or not old['resolved_after_repair_and_recheck']
                or previous['kind'] != 'recheck' or previous.get('result') != '異常なし'
                or previous['source_id'] != old['transitions'][-1]['source_id']):
            raise ValueError('再発の比較元は、修理後の異常なし再確認で解消した別の指摘を選択してください')
        final_statement = {'key': 'recurrent_after_resolution', 'label':
            '比較元で修理後の異常なしを確認し、その後の別観測で同じ症状が再発したことを確認しました。'}
    else:
        final_statement = {'key': 'worsening_comparison', 'label':
            '未解消の継続や時間経過だけでなく、比較元の観測より後に、同じ位置・方法・条件で比べた元観測が悪化したことを確認しました。'}
    sources = {'version': VERSION, 'company_code': vehicle.company_code, 'vehicle_id': vehicle.id,
        'current': current, 'baseline': baseline, 'relation': relation,
        'comparison_order_verified': same_day_order}
    source_ids = list(dict.fromkeys([now['source_id'], old['source_id'], observed['source_id'], previous['source_id']]))
    labels = ((current, '現在の観測'), (baseline, '比較元の観測'))
    display = []
    links = {}
    for value, label in labels:
        origin, record = value['origin'], value['observation']
        display.append({'label': label, 'text': origin['target'] + '\n観測：' + record['observed_at'] + '\n' + record['text'], 'url': origin['source_url']})
        links[record['source_id']] = {'label': label + '：' + origin['target'], 'url': origin['source_url']}
        links[origin['source_id']] = {'label': origin['target'], 'url': origin['source_url']}
        if label == '比較元の観測' and relation == 'recurrent':
            for transition in origin['transitions']:
                display.append({'label': '比較元の' + ('整備' if transition['kind'] == 'repair' else '再確認'),
                    'text': transition['performed_at'] + '\n' + transition['note'], 'url': origin['source_url']})
    return {'kind': KIND, 'selection': deepcopy(selection), 'subject': now['target'],
        'source_ids': source_ids, 'fingerprint': fingerprint(sources), 'sources': sources,
        'source_links': links, 'display_sources': display,
        'statements': [
            {'key': 'current_open_observation', 'label': '現在の観測は、選択した元記録に残る同じ未解消の指摘です。'},
            {'key': 'same_symptom_position', 'label': '2つの観測は、同じ具体的な症状・位置を対象にしています。'},
            final_statement]}


def progression_confirmation_inputs(preview, *, event_id, confirmed_on, as_of=None):
    """Map a revalidated, explicitly confirmed preview to the approved core."""
    if preview.get('kind') != KIND or type(event_id) is not int or event_id <= 0 or type(confirmed_on) is not date:
        raise ValueError('確認イベントの対象・版を確認要')
    sources = preview['sources']
    current, baseline = sources['current'], sources['baseline']
    now, old = current['origin'], baseline['origin']
    observed, previous = current['observation'], baseline['observation']
    scope = Scope(sources['company_code'], sources['vehicle_id'], preview['subject'])
    target_event = f"inspection:{now['record_id']}:defect:{now['defect_no']}"
    old_event = f"inspection:{old['record_id']}:defect:{old['defect_no']}"
    audit = f'priority_confirmation:{event_id}'
    evidence = {
        observed['source_id']: Evidence(observed['source_id'], scope, _day(observed['observed_at']), target_event,
            observed['text'], True, 'record', 'open'),
        previous['source_id']: Evidence(previous['source_id'], scope, _day(previous['observed_at']), old_event,
            previous['text'], True, 'record', 'resolved' if sources['relation'] == 'recurrent' else 'past'),
        audit: Evidence(audit, scope, confirmed_on, target_event,
            '元の2観測と同じ症状・位置・比較関係を担当者が明示確認', True, 'record', 'current')}
    code = 'state_recurrent' if sources['relation'] == 'recurrent' else 'state_worsening'
    facts = [Fact(code, (observed['source_id'], audit), True,
        baseline_source_ids=(previous['source_id'],), comparison_verified=True,
        comparison_order_verified=sources.get('comparison_order_verified') is True)]
    # The existing strict standard brake predicate is independent of the user's
    # relation confirmation. No impact points are inferred for other subjects.
    item_code = now['item_code']
    if item_code in SAFETY_CODES:
        canonical = STANDARD[item_code]
        definition = {key: canonical.get(key, DEFAULT.get(key)) for key in ('item_code', 'content', 'input_type', 'choices', 'criteria')}
        definition.update(template_code=DEFAULT['template_code'], template_version=DEFAULT['template_version'])
        if now['original_identity']['item_definition_fingerprint'] == fingerprint(definition):
            facts.append(Fact('impact_safety', (observed['source_id'],), True))
    return {'scope': scope, 'event_id': target_event, 'facts': tuple(facts), 'timings': (),
        'evidence': evidence, 'references': {}, 'missing_conditions': (
            '対応時期の点数はこの比較確認だけでは確定しません',
            '元記録の関係を人が確認したもので、運行可否や既存指示の解除は自動判定しません')}
