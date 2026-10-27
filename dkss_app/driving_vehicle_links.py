"""Vehicle suggestions never grant report access or contribute driving metrics."""
import hashlib
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import abort, has_request_context, session
from sqlalchemy import event, inspect, select
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import ChecklistEvent, User, Vehicle, VehicleChecklistResult
from . import driving_access
from driving_report_insights import digest, summarize

DAILY = 'daily_inspection_truck_trailer'
ORIGIN = '日常点検の入力開始'


class DrivingVehicleCorrection(db.Model):
    """Append-only revisions, scoped to one account and inspection occurrence."""
    __table_args__ = (db.UniqueConstraint('company_code', 'user_id', 'inspection_id', 'revision',
                                        name='uq_driving_vehicle_correction_revision'),)
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    inspection_id = db.Column(db.Integer, nullable=False)
    evidence_key = db.Column(db.String(64), nullable=False)
    revision = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(20), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    actor_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.String(40), nullable=False)


def as_dict(value):
    try:
        value = json.loads(value or '{}')
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def target_day(result):
    try:
        return date(int(result.year), int(result.month), int(result.day)).isoformat()
    except (TypeError, ValueError):
        return None


def daily(result):
    return as_dict(result.checklist_snapshot_json).get('fixed_template_code') == DAILY


@event.listens_for(VehicleChecklistResult, 'after_insert')
def preserve_inspection_origin(mapper, connection, result):
    """Capture the authenticated initial account inside the insertion transaction.

    Existing rows are deliberately not backfilled from mutable checked_by fields.
    No schema or external work is performed by this listener.
    """
    if not has_request_context() or not daily(result) or not target_day(result):
        return
    if result.company_code != session.get('company_code'):
        return
    actor = connection.execute(select(User.id).where(
        User.company_code == result.company_code, User.username == session.get('username'))).scalar_one_or_none()
    if actor is None or result.checked_by_username != session.get('username'):
        return
    connection.execute(ChecklistEvent.__table__.insert().values(
        company_code=result.company_code, result_type='vehicle', result_id=result.id,
        event_type=ORIGIN, actor_username=session['username'], actor_name=session.get('name', ''),
        detail_json=json.dumps({'user_id': actor, 'vehicle_id': result.vehicle_record_id,
                                'day': target_day(result), 'checklist_id': result.checklist_id}, ensure_ascii=False),
        created_at=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()))


def label(vehicle):
    return ' '.join(str(getattr(vehicle, field) or '') for field in
                    ('plate_area', 'plate_class', 'plate_kana', 'plate_number')).strip() or vehicle.chassis_number or '車両 ' + str(vehicle.id)


def subject(board):
    company = session['company_code']
    if not driving_access.administrator() or board.get('personal_view'):
        return User.query.filter(User.company_code==company, User.username==session['username'],
                                 User.role.in_(driving_access.READER_ROLES)).first()
    focus = board.get('selected_driver')
    if not focus:
        return None
    matches = [u for u in User.query.filter_by(company_code=company).all()
               if digest(['account', company, u.id]) == focus['key']]
    return matches[0] if len(matches) == 1 else None


def sources(user, period):
    """Only durable origin evidence can identify an account; editors cannot."""
    query = db.session.query(VehicleChecklistResult, ChecklistEvent).join(
        ChecklistEvent, (ChecklistEvent.result_id == VehicleChecklistResult.id) &
        (ChecklistEvent.company_code == VehicleChecklistResult.company_code)).filter(
        VehicleChecklistResult.company_code == user.company_code,
        ChecklistEvent.result_type == 'vehicle', ChecklistEvent.event_type == ORIGIN,
        VehicleChecklistResult.status.in_(['点検完了', '承認待ち', '承認済み']))
    if period.get('start'):
        query = query.filter(VehicleChecklistResult.year >= period['start'][:4])
    if period.get('end'):
        query = query.filter(VehicleChecklistResult.year <= period['end'][:4])
    by_result = {}
    for result, origin in query.all():
        evidence = as_dict(origin.detail_json)
        day = target_day(result)
        if not day or not daily(result) or evidence.get('user_id') != user.id:
            continue
        if evidence.get('vehicle_id') != result.vehicle_record_id or evidence.get('day') != day or evidence.get('checklist_id') != result.checklist_id:
            continue
        if (period.get('start') and day < period['start']) or (period.get('end') and day > period['end']):
            continue
        by_result.setdefault(result.id, []).append((result, origin, day))
    # Multiple origins are ambiguous even if an old import duplicated an event.
    return [values[0] for values in by_result.values() if len(values) == 1]


def evidence_key(result, origin, day):
    return hashlib.sha256(json.dumps([result.company_code, result.id, result.vehicle_record_id,
        result.checklist_id, day, origin.id, origin.detail_json], ensure_ascii=False).encode()).hexdigest()


def group_vehicles(panel):
    groups = {v['id']: {'id': v['id'], 'label': v['label'], 'trip': v, 'candidates': []}
              for v in panel['trips']}
    for item in panel['candidates']:
        groups.setdefault(item['vehicle_id'], {'id': item['vehicle_id'], 'label': item['label'],
                                               'trip': None, 'candidates': []})['candidates'].append(item)
    panel['groups'] = list(groups.values())
    return panel


def build(board, facts, filters):
    user = subject(board)
    focus = board.get('selected_driver')
    own = [f for f in facts if (focus and f['driver_key'] == focus['key']) or
           (user and not driving_access.administrator())]
    # An administrator's unresolved OCR identity is not a confirmed personal link.
    confirmed = [f for f in own if f.get('identity_confirmed')]
    vehicles = Vehicle.query.filter_by(company_code=session['company_code']).all()
    by_id = {v.id: v for v in vehicles}
    trips = []
    for vid in sorted({f['vehicle_id'] for f in confirmed}):
        if vid not in by_id:
            continue
        vf = [f for f in confirmed if f['vehicle_id'] == vid]
        trips.append({'id': vid, 'label': label(by_id[vid]), 'dates': sorted({f['date'] for f in vf}),
                      'summary': summarize(vf)})
    result = {'user_id': user.id if user else None, 'trips': trips, 'candidates': [],
              'choices': [], 'corrections': [], 'ready': False}
    if user is None:
        return group_vehicles(result)
    ready = inspect(db.engine).has_table(DrivingVehicleCorrection.__tablename__)
    result['ready'] = ready
    edits, history = {}, {}
    if ready:
        for edit in DrivingVehicleCorrection.query.filter_by(company_code=user.company_code, user_id=user.id).order_by(DrivingVehicleCorrection.revision).all():
            edits[edit.inspection_id] = edit
            history.setdefault(edit.inspection_id, []).append(edit)
    used = {(f['vehicle_id'], f['date']) for f in confirmed}
    for inspection, origin, day in sources(user, board['period']):
        vid = inspection.vehicle_record_id
        if vid not in by_id:
            continue
        key = evidence_key(inspection, origin, day)
        last = edits.get(inspection.id)
        edit = last if last and last.evidence_key == key else None
        replacement = edit.vehicle_id if edit and edit.action == 'replace' else vid
        if replacement not in by_id:
            continue
        item = {'inspection_id': inspection.id, 'day': day, 'original_id': vid,
                'original_label': label(by_id[vid]), 'vehicle_id': replacement,
                'label': label(by_id[replacement]), 'evidence_key': key,
                'revision': last.revision if last else 0,
                'action': edit.action if edit else 'reset', 'from_correction': bool(edit and edit.action != 'reset'),
                'reported': (replacement, day) in used,
                'history': [{'at': e.created_at, 'action': {'exclude': '乗っていない', 'replace': '車両を変更', 'reset': '修正を取消'}[e.action],
                             'label': label(by_id[e.vehicle_id]) if e.vehicle_id in by_id else ''}
                            for e in history.get(inspection.id, []) if e.evidence_key == key]}
        # Vehicle filters apply to effective candidates without altering the report facts.
        if filters.get('vehicle') and str(replacement) != str(filters['vehicle']):
            continue
        from driving_report_conditions import apply
        from types import SimpleNamespace
        if not apply([SimpleNamespace(vehicle_record_id=replacement)], vehicles, filters):
            continue
        if edit and edit.action != 'reset':
            result['corrections'].append(item)
        if item['action'] != 'exclude' and not item['reported']:
            result['candidates'].append(item)
    # Existing company-scoped vehicle pages allow reading these vehicle identities.
    # No report/maintenance data or permissions are added by these choices.
    result['choices'] = [{'id': v.id, 'label': label(v)} for v in vehicles if not v.deleted]
    return group_vehicles(result)


def save_correction(panel, actor, form):
    if not panel['ready']:
        abort(503, '車両候補の修正は準備中です。')
    try:
        iid, revision = int(form.get('inspection_id', '')), int(form.get('revision', ''))
    except (TypeError, ValueError):
        abort(400)
    item = next((i for i in panel['candidates'] + panel['corrections'] if i['inspection_id'] == iid), None)
    if item is None:
        abort(404)
    if item['revision'] != revision or item['evidence_key'] != form.get('evidence_key'):
        abort(409, '候補が更新されました。再表示してください。')
    action = form.get('action')
    if action not in {'exclude', 'replace', 'reset'}:
        abort(400)
    vid = None
    if action == 'replace':
        try:
            vid = int(form.get('vehicle_id', ''))
        except (TypeError, ValueError):
            abort(400)
        if vid not in {v['id'] for v in panel['choices']}:
            abort(404)
    edit = DrivingVehicleCorrection(company_code=actor.company_code, user_id=panel['user_id'],
        inspection_id=iid, evidence_key=item['evidence_key'], revision=revision + 1, action=action,
        vehicle_id=vid, actor_user_id=actor.id, created_at=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat())
    db.session.add(edit)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409, '候補が更新されました。再表示してください。')
