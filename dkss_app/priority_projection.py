"""Company/vehicle-scoped read adapter for normal response-priority projections.

No synthetic registry, production bypass flag, model/AI call, cache refresh,
notification, persistence, or database schema changes. Column queries avoid
reusing a stale ORM identity-map value; a dirty session is never autoflushed.
"""
from datetime import datetime
import json
import re
from zoneinfo import ZoneInfo

from vehicle_priority_projection import InspectionSnapshot, project_priority, inspection_provenance


def registered_inspection_provenance(vehicle, row):
    """Attach original server input provenance during ordinary analysis generation."""
    snap = InspectionSnapshot(vehicle.company_code, vehicle.id, row.id,
        f'{row.year}-{str(row.month).zfill(2)}-{str(row.day).zfill(2)}', row.status,
        row.checklist_snapshot_json, row.answers_json, row.operation_judgment_json,
        datetime.now(ZoneInfo('Asia/Tokyo')).date(), vehicle.gross_vehicle_weight)
    proof = inspection_provenance(snap)
    if proof and proof.get('instruction'):
        from .models import ChecklistEvent, db
        from vehicle_priority_inputs import fingerprint
        with db.session.no_autoflush:
            events = db.session.query(ChecklistEvent.detail_json).filter_by(
                company_code=vehicle.company_code, result_type='vehicle', result_id=row.id,
                event_type='運行判断').order_by(ChecklistEvent.id).limit(1001).all()
        exact = False
        if len(events) <= 1000:
            for event in events:
                try:
                    detail = json.loads(event.detail_json)
                except (TypeError, ValueError):
                    exact = False; break
                if not isinstance(detail, dict):
                    exact = False; break
                if fingerprint(detail.get('judgment')) == proof['instruction']['judgment_fingerprint']:
                    exact = True
        proof['instruction_available_for_generation'] = (
            exact and _instruction_context_is_current(row, vehicle.company_code, vehicle.id, snap.captured_on))
    return proof


def inspection_source_record_id(value):
    # SQLAlchemy Integer is a signed 32-bit key on PostgreSQL. Reject before
    # int()/DB binding: Unicode numerals, giant decimal strings and overflow.
    if not isinstance(value,str) or not re.fullmatch(r'inspection:[1-9][0-9]{0,9}',value):
        return None
    number = int(value[11:])
    return number if number <= 2147483647 else None


def project_registered_priorities(analysis, vehicle, sources, *, is_current=None, as_of=None):
    from .models import Vehicle, VehicleChecklistResult, ChecklistEvent, db
    from sqlalchemy.exc import SQLAlchemyError

    as_of = as_of or datetime.now(ZoneInfo('Asia/Tokyo')).date()
    snapshots, reason = [], None
    timing_results = {}
    confirmed_results = {}
    instruction_context_cache = {}
    try:
        if db.session.new or db.session.dirty or db.session.deleted:
            reason = '未保存変更があるため現在登録の優先度算定を保留しています'
        else:
            with db.session.no_autoflush:
                stored_vehicle = db.session.query(Vehicle.id, Vehicle.gross_vehicle_weight).filter_by(
                    company_code=vehicle.company_code, id=vehicle.id, deleted=False).first()
                if stored_vehicle is None:
                    reason = '会社・車両の現在登録を確認できません'
                else:
                    cited = set()
                    for item in (analysis or {}).get('recommendations', []):
                        if isinstance(item, dict) and isinstance(item.get('source_ids'), list):
                            for sid in item['source_ids']:
                                number = inspection_source_record_id(sid)
                                if number is not None:
                                    cited.add(number)
                    if len(cited) > 1000:
                        reason = '対象根拠が読取上限を超えるため対応を確認要'
                    elif cited:
                        m = VehicleChecklistResult
                        rows = db.session.query(m.id, m.year, m.month, m.day, m.status,
                            m.checklist_snapshot_json, m.answers_json, m.operation_judgment_json).filter(
                            m.company_code == vehicle.company_code, m.vehicle_record_id == vehicle.id,
                            m.id.in_(cited)).order_by(m.id).limit(1001).all()
                        if len(rows) > 1000:
                            reason = '引用点検の読取上限を超えたため保存版を保持しています'
                        else:
                            # Only the cited scoped inspections' registered history is read.
                            # No wall-clock ordering or automatic stop release is inferred.
                            e = ChecklistEvent
                            events = db.session.query(e.result_id,e.event_type,e.detail_json,e.actor_username,e.created_at).join(m,
                                m.id == e.result_id).filter(e.company_code == vehicle.company_code,
                                e.result_type == 'vehicle',m.company_code == vehicle.company_code,
                                m.vehicle_record_id == vehicle.id,m.id.in_(cited)).order_by(e.id).limit(1001).all()
                            if len(events) > 1000:
                                reason = '指摘の登録履歴が読取上限を超えたため保存版を保持しています'
                            else:
                                stopped, invalid = set(), set()
                                instructions, followups, replacements = {}, {}, {}
                                from vehicle_priority_inputs import fingerprint
                                for event in events:
                                    try:
                                        detail = json.loads(event.detail_json)
                                    except (TypeError,ValueError):
                                        invalid.add(event.result_id);continue
                                    if not isinstance(detail,dict):
                                        invalid.add(event.result_id);continue
                                    if event.event_type == '運行判断' and not isinstance(detail.get('judgment'),dict):
                                        invalid.add(event.result_id)
                                    if detail.get('repair') or detail.get('recheck'):
                                        before, after = detail.get('previous_defect'), detail.get('defect')
                                        if not isinstance(before, dict) or not isinstance(after, dict):
                                            invalid.add(event.result_id)
                                        elif (event.event_type == '再確認待ち' and after.get('status') == '再確認待ち'
                                                and after.get('repair') == detail.get('repair')
                                                and not detail.get('recheck')
                                                and all(before.get(key) == after.get(key) for key in
                                                    ('defect_no', 'item_no', 'reported_at', 'reported_answer'))):
                                            followups.setdefault(event.result_id, []).append(fingerprint(after))
                                    if event.event_type == '運行判断' and isinstance(detail.get('judgment'), dict):
                                        instructions.setdefault(event.result_id, []).append(fingerprint(detail['judgment']))
                                        if _verified_instruction_replacement(detail, event,
                                                vehicle.company_code, vehicle.id, as_of):
                                            replacements.setdefault(event.result_id, []).append((
                                                fingerprint(detail['previous_judgment']), fingerprint(detail['judgment'])))
                                    for key in ('previous_judgment','judgment'):
                                        value = detail.get(key)
                                        if key in detail and not isinstance(value,dict):
                                            invalid.add(event.result_id)
                                        elif isinstance(value,dict) and value.get('status') == '運行不可':
                                            stopped.add(event.result_id)
                                snapshots = [InspectionSnapshot(vehicle.company_code, vehicle.id, row.id,
                                    f'{row.year}-{str(row.month).zfill(2)}-{str(row.day).zfill(2)}', row.status,
                                    row.checklist_snapshot_json, row.answers_json, row.operation_judgment_json,
                                    as_of, stored_vehicle.gross_vehicle_weight,
                                    row.id not in invalid, row.id in stopped,
                                    tuple(instructions.get(row.id, [])), tuple(followups.get(row.id, [])),
                                    _instruction_context_is_current(row, vehicle.company_code, vehicle.id, as_of,
                                        cache=instruction_context_cache),
                                    tuple(replacements.get(row.id, []))) for row in rows]
    except SQLAlchemyError:
        # Leave the transaction policy to the caller. Do not commit/rollback or
        # expose SQL/parameters, and never turn unavailable facts into low.
        reason = '現在の登録根拠を取得できないため保存版の優先度を保持しています'
    if reason is None:
        from .priority_timing import project_registered_timing_priorities
        timing_results = project_registered_timing_priorities(analysis, vehicle, sources, as_of=as_of, is_current=is_current)
        from .priority_confirmed_projection import project_registered_confirmed_priorities
        confirmed_results = project_registered_confirmed_priorities(analysis, vehicle, sources, as_of=as_of, is_current=is_current)
    return project_priority(analysis, sources, snapshots, company_code=vehicle.company_code,
        vehicle_id=vehicle.id, as_of=as_of, is_current=is_current, unavailable_reason=reason, timing_results=timing_results, confirmed_results=confirmed_results)


def _other_operation_input_fingerprint(result_record, *, cache=None):
    from .models import VehicleChecklistResult as m, db
    from vehicle_priority_inputs import fingerprint
    cache = cache if cache is not None else {}
    key = (result_record.company_code, result_record.vehicle_record_id)
    if key not in cache:
        with db.session.no_autoflush:
            rows = db.session.query(m.id, m.year, m.month, m.day, m.status,
                m.answers_json, m.checklist_snapshot_json, m.operation_judgment_json).filter(
                m.company_code == result_record.company_code,
                m.vehicle_record_id == result_record.vehicle_record_id).order_by(m.id).limit(1001).all()
        cache[key] = [list(row) for row in rows] if len(rows) <= 1000 else None
    rows = cache[key]
    return fingerprint([row for row in rows if row[0] != result_record.id]) if rows is not None else None


def operation_instruction_context(result_record, recorded_at):
    """Audit metadata captured by the existing human decision POST, no new input."""
    from vehicle_priority_inputs import fingerprint
    return {'version': 'registered-operation-context-v1',
        'company_code': result_record.company_code, 'vehicle_id': result_record.vehicle_record_id,
        'record_id': result_record.id, 'recorded_at': recorded_at.isoformat(),
        'timezone': str(recorded_at.tzinfo),
        'other_inputs_fingerprint': _other_operation_input_fingerprint(result_record),
        'answers_fingerprint': fingerprint(result_record.answers_json),
        'checklist_fingerprint': fingerprint(result_record.checklist_snapshot_json)}


def _instruction_context_is_current(row, company_code, vehicle_id, as_of, *, cache=None):
    """Same business day, unchanged whole-vehicle basis, original actor identity.

    Earlier stops are retained as saved classes, never expired or released here.
    Stored offset and timezone are from the human decision transaction; today's
    user preferences cannot reinterpret an old naive timestamp.
    """
    from .models import User, db
    from types import SimpleNamespace
    from vehicle_priority_inputs import fingerprint
    try:
        judgment = json.loads(row.operation_judgment_json)
        if not isinstance(judgment, dict) or judgment.get('status') not in {'運行可', '運行不可'}:
            return False
        if (judgment.get('authority_confirmed') is not True
                or judgment.get('authority_role') not in {'整備管理者', '補助者'}
                or type(judgment.get('judged_by_user_id')) is not int or judgment['judged_by_user_id'] <= 0
                or not isinstance(judgment.get('judged_by_identity'), str) or not judgment['judged_by_identity']):
            return False
        context = judgment.get('priority_instruction_context')
        if (not isinstance(context, dict) or not isinstance(context.get('other_inputs_fingerprint'), str)
                or not re.fullmatch('[a-f0-9]{64}', context['other_inputs_fingerprint'])):
            return False
        stamp = datetime.fromisoformat(context['recorded_at'])
        zone = ZoneInfo(context['timezone'])
        now = datetime.now(zone)
        if (stamp.tzinfo is None or stamp > now or stamp.utcoffset() != stamp.astimezone(zone).utcoffset()
                or stamp.date() != now.date()
                or as_of != now.astimezone(ZoneInfo('Asia/Tokyo')).date()
                or stamp.strftime('%Y-%m-%d %H:%M:%S') != judgment.get('judged_at')
                or stamp.date().isoformat() != f'{row.year}-{str(row.month).zfill(2)}-{str(row.day).zfill(2)}'
                or context.get('version') != 'registered-operation-context-v1'
                or context.get('company_code') != company_code
                or context.get('vehicle_id') != vehicle_id or context.get('record_id') != row.id
                or context.get('answers_fingerprint') != fingerprint(row.answers_json)
                or context.get('checklist_fingerprint') != fingerprint(row.checklist_snapshot_json)):
            return False
        with db.session.no_autoflush:
            actor = db.session.query(User.id).filter_by(company_code=company_code,
                id=judgment.get('judged_by_user_id'), account_identity=judgment.get('judged_by_identity'),
                role='admin').first()
        if actor is None:
            return False
        scoped_row = SimpleNamespace(company_code=company_code, vehicle_record_id=vehicle_id, id=row.id)
        return context.get('other_inputs_fingerprint') == _other_operation_input_fingerprint(scoped_row, cache=cache)
    except (TypeError, ValueError, KeyError):
        return False



def _verified_instruction_replacement(detail, event, company_code, vehicle_id, as_of):
    """Validate a direct historical replacement, not present permission to drive."""
    before, after = detail.get('previous_judgment'), detail.get('judgment')
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    if (before.get('status') != '運行不可' or after.get('status') != '運行可'
            or type(before.get('version')) is not int or type(after.get('version')) is not int
            or after['version'] != before['version'] + 1
            or after.get('checks_confirmed') is not True
            or after.get('authority_confirmed') is not True
            or after.get('authority_role') not in {'整備管理者', '補助者'}
            or type(after.get('judged_by_user_id')) is not int or after['judged_by_user_id'] <= 0
            or not isinstance(after.get('judged_by_identity'), str) or not after['judged_by_identity']
            or event.actor_username != after.get('judged_by_username')
            or event.created_at != after.get('judged_at')):
        return False
    contexts = [v.get('priority_instruction_context') for v in (before, after)]
    try:
        stamps = []
        for judgment, context in zip((before, after), contexts):
            if (not isinstance(context, dict) or context.get('version') != 'registered-operation-context-v1'
                    or context.get('company_code') != company_code or context.get('vehicle_id') != vehicle_id
                    or context.get('record_id') != event.result_id):
                return False
            stamp = datetime.fromisoformat(context['recorded_at'])
            zone = ZoneInfo(context['timezone'])
            if (stamp.tzinfo is None or stamp.utcoffset() != stamp.astimezone(zone).utcoffset()
                    or stamp.strftime('%Y-%m-%d %H:%M:%S') != judgment.get('judged_at')
                    or stamp.astimezone(ZoneInfo('Asia/Tokyo')).date() > as_of):
                return False
            stamps.append(stamp)
        return stamps[0] <= stamps[1]
    except (KeyError, TypeError, ValueError):
        return False
