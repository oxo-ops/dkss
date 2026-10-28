"""Explicit, company-scoped readership; OCR names never grant access."""
import hashlib
import json
import unicodedata
from collections import defaultdict
from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import abort, current_app, session, request, has_request_context
from sqlalchemy import inspect, text
from .extensions import db
from .models import User, Driver, VehicleDrivingReportRecord, DrivingReportReader, DrivingReportReflection
from driving_report_data import payload

READER_ROLES = {'user', 'admin', 'itc'}


def _request_read(key, load):
    if not has_request_context():return load()
    owner = (session.get('company_code'), session.get('username'), session.get('role'))
    cache = request.environ.setdefault('dkss.driving.reads', {})
    cache_key = (owner, key)
    if cache_key not in cache:cache[cache_key] = load()
    return cache[cache_key]


def company_users():
    return _request_read('company_users', lambda: User.query.filter_by(company_code=session['company_code']).all())


def company_drivers():
    return _request_read('company_drivers', lambda: Driver.query.filter_by(company_code=session['company_code']).all())


def administrator():
    return session.get('role') in {'admin', 'itc'}


def fingerprint(row):
    p = payload(row)
    fields = [row.company_code, row.vehicle_record_id, p.get('source_system'),
              p.get('driver_code'), p.get('driver_name'), row.operation_date]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def ready():
    state = current_app.extensions['dkss']
    if not state.get('driving_readers_ready'):
        state['driving_readers_ready'] = inspect(db.engine).has_table(DrivingReportReader.__tablename__)
    return bool(state.get('driving_readers_ready'))


def initialize_driving_access(app):
    from .driving_vehicle_links import DrivingVehicleCorrection
    with app.app_context():
        with db.engine.begin() as connection:
            if connection.dialect.name == 'postgresql':
                connection.execute(text('SELECT pg_advisory_xact_lock(824700027)'))
            DrivingReportReader.__table__.create(connection, checkfirst=True)
            DrivingReportReflection.__table__.create(connection, checkfirst=True)
            DrivingVehicleCorrection.__table__.create(connection, checkfirst=True)
        app.extensions['dkss']['driving_readers_ready'] = True


def visible(rows, personal=False):
    if administrator() and not personal:
        return list(rows)
    if session.get('role') not in READER_ROLES or not ready():
        return []
    user=User.query.filter_by(company_code=session.get('company_code'),username=session.get('username')).first()
    if not user:return []
    grants = bindings(rows)
    return [r for r in rows if r.company_code == session.get('company_code') and
            r.id in grants and grants[r.id].user_id == user.id]


def require_report(row):
    if row.company_code != session.get('company_code') or not visible([row]):
        abort(404)
    return row


def reader(row):
    return DrivingReportReader.query.filter_by(company_code=row.company_code, report_id=row.id).first() if ready() else None


def assign(rows, username, actor):
    if not administrator():
        abort(403)
    if not ready():
        abort(503, '閲覧設定の準備中です。管理者へお問い合わせください。')
    user=User.query.filter(User.company_code==session['company_code'],User.username==username,User.role.in_(READER_ROLES)).first() if username else None
    if username and not user:abort(400)
    for row in rows:
        if row.company_code != session['company_code']:
            abort(404)
        grant = reader(row)
        if not username:
            if grant: db.session.delete(grant)
            continue
        if not grant:
            grant = DrivingReportReader(company_code=row.company_code, report_id=row.id)
            db.session.add(grant)
        grant.username = username
        grant.user_id = user.id
        grant.identity_hash = fingerprint(row)
        grant.confirmed_by = actor
        grant.confirmed_at = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()


def bindings(rows):
    if not ready():return {}
    company = session['company_code']
    ids = {r.id:r for r in rows if r.company_code == company}
    if not ids:return {}
    users = {u.id:u for u in company_users() if u.role in READER_ROLES}
    seeds = _request_read('identity_seeds', lambda: db.session.query(DrivingReportReader, VehicleDrivingReportRecord).join(
        VehicleDrivingReportRecord, DrivingReportReader.report_id == VehicleDrivingReportRecord.id
    ).filter(DrivingReportReader.company_code == company,
             VehicleDrivingReportRecord.company_code == company).all())
    explicit = {grant.report_id:grant for grant,row in seeds if row.id in ids}
    valid = [(grant,row) for grant,row in seeds if grant.user_id in users and grant.identity_hash == fingerprint(row)]
    result = {grant.report_id:grant for grant,row in valid if row.id in ids}
    masters = defaultdict(list)
    accounts = defaultdict(list)
    for master in company_drivers():masters[_code(master.employee_id)].append(master)
    for user in users.values():accounts[_code(user.username)].append(user)
    confirmed = defaultdict(list)
    for grant,row in valid:
        key = _identity_key(row)
        if key:confirmed[key].append((row.operation_date, grant.user_id))
    for row in ids.values():
        # A stale explicit decision or an explicit withdrawal must not be bypassed.
        if row.id in explicit or _withdrawn(row):continue
        p = payload(row)
        code = _code(p.get('driver_code'))
        name = _name(p.get('driver_name'))
        key = _identity_key(row)
        if not key or not row.operation_date:continue
        candidates = {uid for start,uid in confirmed.get(key, []) if start and start <= row.operation_date}
        if len(masters[code]) == len(accounts[code]) == 1:
            master,user = masters[code][0],accounts[code][0]
            if name and name == _name(master.name) == _name((user.last_name or '') + (user.first_name or '')):
                candidates.add(user.id)
        if len(candidates) == 1:
            user = users[next(iter(candidates))]
            result[row.id] = SimpleNamespace(report_id=row.id, company_code=company,
                user_id=user.id, username=user.username, identity_hash=fingerprint(row),
                confirmed_by='automatic', confirmed_at=None)
    return result


def _code(value):
    return unicodedata.normalize('NFKC', str(value or '')).strip()


def _name(value):
    return ''.join(_code(value).split())


def _identity_key(row):
    p = payload(row)
    source,code,name = _code(p.get('source_system')), _code(p.get('driver_code')), _name(p.get('driver_name'))
    return (source,code,name) if source and code and name else None


def _withdrawn(row):
    events = [e for e in payload(row).get('audit',[]) if e.get('kind') == 'reader']
    return bool(events and not (events[-1].get('detail') or {}).get('username'))


def account_key(grant):
    return hashlib.sha256(json.dumps(['account',grant.company_code,grant.user_id]).encode()).hexdigest()[:24]
