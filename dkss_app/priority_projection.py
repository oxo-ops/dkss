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
    return inspection_provenance(snap)


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
                            events = db.session.query(e.result_id,e.event_type,e.detail_json).join(m,
                                m.id == e.result_id).filter(e.company_code == vehicle.company_code,
                                e.result_type == 'vehicle',m.company_code == vehicle.company_code,
                                m.vehicle_record_id == vehicle.id,m.id.in_(cited)).order_by(e.id).limit(1001).all()
                            if len(events) > 1000:
                                reason = '指摘の登録履歴が読取上限を超えたため保存版を保持しています'
                            else:
                                stopped, invalid = set(), set()
                                for event in events:
                                    try:
                                        detail = json.loads(event.detail_json)
                                    except (TypeError,ValueError):
                                        invalid.add(event.result_id);continue
                                    if not isinstance(detail,dict):
                                        invalid.add(event.result_id);continue
                                    if event.event_type == '運行判断' and not isinstance(detail.get('judgment'),dict):
                                        invalid.add(event.result_id)
                                    if any(detail.get(key) for key in ('repair','recheck')):
                                        invalid.add(event.result_id)
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
                                    row.id not in invalid, row.id in stopped) for row in rows]
    except SQLAlchemyError:
        # Leave the transaction policy to the caller. Do not commit/rollback or
        # expose SQL/parameters, and never turn unavailable facts into low.
        reason = '現在の登録根拠を取得できないため保存版の優先度を保持しています'
    return project_priority(analysis, sources, snapshots, company_code=vehicle.company_code,
        vehicle_id=vehicle.id, as_of=as_of, is_current=is_current, unavailable_reason=reason)
