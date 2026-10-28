"""Company-scoped report access through explicit or unambiguous identities."""
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import abort, current_app, session
from sqlalchemy import inspect, text
from .extensions import db
from .models import User, VehicleDrivingReportRecord, DrivingReportReader, DrivingReportReflection
from driving_report_data import payload

READER_ROLES = {'user', 'admin', 'itc'}


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
    if username and (not user or user.login_locked):abort(400)
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
    from driving_identity_resolution import resolver
    return resolver().bindings(rows)


def resolve_import(row, username=None, reidentify=False):
    """Runs in the existing registration transaction, including pending vehicles."""
    from driving_identity_resolution import resolver, AUTO, usable
    if not administrator() or not ready():return
    service=resolver(fresh=reidentify)
    service.observe(row)
    if reidentify:
        service.grants.pop(row.id,None)
    if username == '__hold__':
        p=payload(row);p['identity_resolution']={'basis':'hold','at':datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()}
        row.details_json=json.dumps(p,ensure_ascii=False)
        return
    if username:
        user=next((u for u in service.users.values() if u.username==username and usable(u)),None)
        if not user:abort(400, '同じ会社のアカウントを選択してください。')
        basis='manual'
    else:
        user,basis=service.resolve(row)
    if not user:return
    assign([row],user.username,session['username'] if basis=='manual' else AUTO)
    # Keep the original fields; only record the resolution and its evidence.
    p=payload(row)
    p['identity_resolution']={'user_id':user.id,'basis':basis,'identity_hash':fingerprint(row),
        'source_system':p.get('source_system'),'driver_code':p.get('driver_code'),
        'valid_from':row.operation_date,'at':datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()}
    row.details_json=json.dumps(p,ensure_ascii=False)
    # Reuse this transaction's evidence for subsequent records in the same batch.
    from driving_identity_resolution import code_key, name
    key=code_key(row)
    if key and row.operation_date:
        service.evidence[key].append((row.operation_date,name(p.get('driver_name')),user))


def account_key(grant):
    return hashlib.sha256(json.dumps(['account',grant.company_code,grant.user_id]).encode()).hexdigest()[:24]
