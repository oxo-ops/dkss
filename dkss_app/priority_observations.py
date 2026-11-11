"""Read original inspection observations for optional comparison confirmation.

This supplies recorded facts, never a recurrence/worsening interpretation or a
score. A new defect number, equal text, keyword, or absence of a record is not
semantic confirmation. The existing human repair/recheck events are retained
with their original actor generation, source version and verbatim notes.
"""
from copy import deepcopy
from datetime import date, datetime
import json
import re
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vehicle_priority_inputs import fingerprint
from vehicle_priority_projection import InspectionSnapshot, inspection_provenance

VERSION = 'registered-inspection-observation-v1'
MAX_REFERENCES = 50
MAX_EVENTS = 1000
REF = re.compile(r'inspection:([1-9][0-9]{0,9}):defect:([1-9][0-9]{0,9}):[0-9a-f]{24}\Z')
IDENTITY = ('defect_no', 'item_no', 'reported_at', 'reported_answer')


def _object(raw):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _actor(value):
    try:
        return (type(value.actor_user_id) is int and value.actor_user_id > 0
                and str(UUID(value.actor_identity)) == value.actor_identity
                and isinstance(value.actor_username, str) and bool(value.actor_username))
    except (ValueError, TypeError, AttributeError):
        return False


def _transition(event, before, after, detail, as_of):
    """Validate only the exact semantics of the existing repair/recheck POST."""
    if (not _actor(event) or any(before.get(k) != after.get(k) for k in IDENTITY)
            or not isinstance(before.get('reported_answer'), dict)):
        return None
    previous = detail.get('previous_judgment')
    previous_defects = previous.get('defects') if isinstance(previous, dict) else None
    if (not isinstance(previous_defects, list) or type(previous.get('version')) is not int
            or previous['version'] < 0
            or sum(value == before for value in previous_defects) != 1):
        return None
    repair, recheck = detail.get('repair'), detail.get('recheck')
    is_recheck = isinstance(recheck, dict) and bool(recheck)
    action = recheck if is_recheck else repair
    if (not isinstance(action, dict) or not action
            or not isinstance(action.get('note'), str) or not action['note'].strip()
            or action.get('performed_by_username') != event.actor_username
            or action.get('recorded_at') != event.created_at
            or action.get('status') != after.get('status') or event.event_type != after.get('status')):
        return None
    performed = _date(action.get('performed_at'))
    recorded = _date(action.get('recorded_at'))
    reported = _date(before.get('reported_at'))
    if None in (performed, recorded, reported) or not reported <= performed <= recorded <= as_of:
        return None
    try:
        zone = ZoneInfo(action.get('timezone'))
        local = datetime.fromisoformat(action['recorded_at']).replace(tzinfo=zone)
        utc = datetime.fromisoformat(action.get('notification_created_at', '').replace('Z', '+00:00'))
        if local.utcoffset() is None or utc.utcoffset() is None or local != utc:
            return None
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        return None
    expected = deepcopy(before)
    expected['status'] = after.get('status')
    if is_recheck:
        result = action.get('result')
        if (repair or before.get('status') != '再確認待ち'
                or result not in {'異常なし', '異常あり'}
                or after.get('status') != ('解消' if result == '異常なし' else '対応待ち')
                or not isinstance(before.get('repair'), dict)
                or _date(before['repair'].get('performed_at')) is None
                or _date(before['repair'].get('performed_at')) > performed
                or not isinstance(after.get('rechecked_answer'), dict)
                or str(after['rechecked_answer'].get('item_no')) != str(before.get('item_no'))
                or after['rechecked_answer'].get('content') != before['reported_answer'].get('content')):
            return None
        expected['recheck'] = action
        expected['rechecked_answer'] = after['rechecked_answer']
        kind = 'recheck'
    else:
        if recheck or before.get('status') not in {'対応待ち', '整備中'} or after.get('status') not in {'整備中', '再確認待ち'}:
            return None
        expected['repair'] = action
        kind = 'repair'
    if expected != after:
        return None
    return {'source_id': f'checklist_event:{event.id}', 'event_id': event.id,
        'kind': kind, 'status': after['status'], 'result': action.get('result'),
        'performed_at': action['performed_at'], 'recorded_at': action['recorded_at'],
        'timezone': action['timezone'], 'note': action['note'],
        'actor_identity': event.actor_identity, 'actor_user_id': event.actor_user_id,
        'actor_username': event.actor_username, 'actor_name': event.actor_name,
        'before_fingerprint': fingerprint(before), 'after_fingerprint': fingerprint(after),
        'source_fingerprint': fingerprint({'detail': detail, 'actor_identity': event.actor_identity,
            'actor_user_id': event.actor_user_id, 'actor_username': event.actor_username,
            'created_at': event.created_at}), 'judgment_version_before': previous['version']}


def _observation(vehicle, row, events, ref, as_of):
    snap = InspectionSnapshot(vehicle.company_code, vehicle.id, row.id,
        f'{row.year}-{str(row.month).zfill(2)}-{str(row.day).zfill(2)}', row.status,
        row.checklist_snapshot_json, row.answers_json, row.operation_judgment_json, as_of)
    proof = inspection_provenance(snap)
    offered = [v for v in (proof or {}).get('events', []) if v.get('input_ref') == ref]
    judgment = _object(row.operation_judgment_json)
    if len(offered) != 1 or not judgment:
        return None
    selected = offered[0]
    matches = [v for v in judgment.get('defects', []) if isinstance(v, dict) and v.get('defect_no') == selected['defect_no']]
    if len(matches) != 1 or not isinstance(matches[0].get('reported_answer'), dict):
        return None
    defect = matches[0]
    if (_date(snap.inspection_on) is None or _date(defect.get('reported_at')) is None
            or not _date(snap.inspection_on) <= _date(defect['reported_at']) <= as_of
            or defect['reported_answer'].get('content') != selected.get('item_content')):
        return None
    transitions, last, version, valid = [], None, None, True
    for event in events:
        detail = _object(event.detail_json)
        if detail is None:
            valid = False; break
        before, after = detail.get('previous_defect'), detail.get('defect')
        numbers = [value.get('defect_no') for value in (before, after) if isinstance(value, dict)]
        if selected['defect_no'] not in numbers:
            continue
        if (not isinstance(before, dict) or not isinstance(after, dict)
                or any(before.get(k) != defect.get(k) for k in IDENTITY)
                or (last is not None and last != before)):
            valid = False; break
        if last is None and ('repair' in before or 'recheck' in before or before.get('status') != '対応待ち'):
            valid = False; break
        transition = _transition(event, before, after, detail, as_of)
        if transition is None or (version is not None and transition['judgment_version_before'] <= version):
            valid = False; break
        transitions.append(transition); last = after; version = transition['judgment_version_before']
    verified = valid and bool(transitions) and last == defect
    resolved = (verified and transitions[-1]['kind'] == 'recheck'
                and transitions[-1]['result'] == '異常なし' and defect.get('status') == '解消'
                and any(v['kind'] == 'repair' and v['status'] == '再確認待ち' for v in transitions))
    return {'input_ref': ref, 'source_id': f'inspection:{row.id}',
        'record_id': row.id, 'defect_no': selected['defect_no'],
        'item_code': selected['item_code'], 'target': selected['item_content'],
        'reported_at': defect['reported_at'], 'reported_answer': deepcopy(defect['reported_answer']),
        'registered_status': defect.get('status'), 'original_identity': deepcopy(selected),
        'current_defect_fingerprint': fingerprint(defect),
        'lifecycle_verified': verified, 'resolved_after_repair_and_recheck': resolved,
        'transitions': transitions if verified else [],
        'comparison_verified': False,
        'missing_conditions': [
            '同じ症状・位置の再発、または比較条件をそろえた悪化の確認は、この事象番号や記録文だけから推定しません',
            *([] if verified else ['整備・再確認の原記録、担当者の本人識別、版の連鎖を確認要'])]}


def read_inspection_observation_sources(vehicle, input_refs, *, as_of=None):
    """Bounded, company/vehicle-scoped raw facts; no backfill, scoring or writes."""
    from .models import Vehicle, VehicleChecklistResult as Result, ChecklistEvent as Event, db
    from sqlalchemy.exc import SQLAlchemyError
    as_of = as_of or datetime.now(ZoneInfo('Asia/Tokyo')).date()
    output = {'version': VERSION, 'company_code': vehicle.company_code, 'vehicle_id': vehicle.id,
        'observations': [], 'missing_conditions': []}
    def held(message):
        output['observations'] = []
        output['missing_conditions'] = [message]
        return output
    if (type(as_of) is not date or not isinstance(input_refs, (list, tuple))
            or not 1 <= len(input_refs) <= MAX_REFERENCES or len(set(v for v in input_refs if isinstance(v, str))) != len(input_refs)):
        return held('比較する元事象の参照を個別に指定してください')
    parsed = [REF.fullmatch(ref) if isinstance(ref, str) else None for ref in input_refs]
    if any(not value or max(int(value[1]), int(value[2])) > 2147483647 for value in parsed):
        return held('元事象の参照形式を確認要')
    if db.session.new or db.session.dirty or db.session.deleted:
        return held('未保存変更があるため元事象の照合を保留しています')
    ids = {int(value[1]) for value in parsed}
    try:
        with db.session.no_autoflush:
            exists = db.session.query(Vehicle.id).filter_by(company_code=vehicle.company_code, id=vehicle.id, deleted=False).first()
            if not exists:
                return held('会社・車両の現在登録を確認できません')
            rows = db.session.query(Result.id, Result.year, Result.month, Result.day, Result.status,
                Result.checklist_snapshot_json, Result.answers_json, Result.operation_judgment_json).filter(
                Result.company_code == vehicle.company_code, Result.vehicle_record_id == vehicle.id,
                Result.id.in_(ids)).order_by(Result.id).all()
            if len(rows) != len(ids):
                return held('同じ会社・車両の元事象を確認できません')
            events = db.session.query(Event.id, Event.result_id, Event.event_type, Event.detail_json,
                Event.actor_username, Event.actor_user_id, Event.actor_identity, Event.actor_name,
                Event.created_at).join(Result, Result.id == Event.result_id).filter(
                Event.company_code == vehicle.company_code, Event.result_type == 'vehicle',
                Result.company_code == vehicle.company_code, Result.vehicle_record_id == vehicle.id,
                Result.id.in_(ids)).order_by(Event.id).limit(MAX_EVENTS + 1).all()
            if len(events) > MAX_EVENTS:
                return held('元事象の履歴が読取上限を超えるため、部分履歴では比較しません')
            rows = {row.id: row for row in rows}
            for ref, parsed_ref in zip(input_refs, parsed):
                number = int(parsed_ref[1])
                result = _observation(vehicle, rows[number], [v for v in events if v.result_id == number], ref, as_of)
                if result is None:
                    return held('元事象の回答・対象・版との一致を確認できません')
                output['observations'].append(result)
    except SQLAlchemyError:
        return held('元事象を読み取れないため比較を保留しています')
    return output
