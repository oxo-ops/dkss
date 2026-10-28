"""Generation evidence for explicit reminder settings, separate from Q03 subjects."""
import json
from datetime import datetime, timezone

from flask import has_request_context, request, session
from sqlalchemy import event, inspect, select, text
from werkzeug.exceptions import ServiceUnavailable

from .extensions import db
from .models import User, VehicleChecklistNotifySetting, VehicleChecklistResult
from .serialization import safe_json_dict, safe_json_dict_list, safe_json_str_list


class VehicleChecklistNotifyAccount(db.Model):
    __table_args__ = (db.Index('ix_checklist_notify_account_setting', 'company_code', 'setting_id', 'id'),)
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=False)
    setting_id = db.Column(db.Integer, nullable=False)
    identities_json = db.Column(db.Text, nullable=False)
    actor_identity = db.Column(db.String(36))
    actor_name = db.Column(db.String(200))
    created_at = db.Column(db.String(40), nullable=False)


def initialize_notify_identities():
    with db.engine.begin() as connection:
        if connection.dialect.name == 'postgresql':
            connection.execute(text('SELECT pg_advisory_xact_lock(824700028)'))
        VehicleChecklistNotifyAccount.__table__.create(connection, checkfirst=True)


@event.listens_for(VehicleChecklistNotifySetting, 'after_insert')
@event.listens_for(VehicleChecklistNotifySetting, 'after_update')
def capture_explicit_setting(mapper, connection, setting):
    # Only an explicit authenticated save can attest the current selected users.
    # A migration, unrelated update, or historical name match cannot do so.
    if not has_request_context() or request.endpoint != 'save_vehicle_checklist_reminder_notify_users':
        return
    if setting.company_code != session.get('company_code') or not session.get('account_identity'):
        return
    actor = connection.execute(select(User.account_identity, User.last_name, User.first_name).where(
        User.company_code == setting.company_code,
        User.account_identity == session['account_identity'])).first()
    if not actor:
        return
    if not inspect(connection).has_table(VehicleChecklistNotifyAccount.__tablename__):
        raise ServiceUnavailable('通知先の本人確認用ストレージを初期化してください。')
    users = {}
    for username, identity in connection.execute(select(User.username, User.account_identity).where(
            User.company_code == setting.company_code)):
        users.setdefault(username, []).append(identity)
    identities = {name: users[name][0] for name in safe_json_str_list(setting.notify_users_json)
                  if len(users.get(name, [])) == 1 and users[name][0]}
    connection.execute(VehicleChecklistNotifyAccount.__table__.insert().values(
        company_code=setting.company_code, setting_id=setting.id,
        identities_json=json.dumps(identities, ensure_ascii=False), actor_identity=actor.account_identity,
        actor_name=(actor.last_name or '') + (actor.first_name or ''),
        created_at=datetime.now(timezone.utc).isoformat()))


def resolved_notify_users(company_code, checklist_id, vehicle_record_id):
    if not vehicle_record_id:
        return []
    setting = VehicleChecklistNotifySetting.query.filter_by(company_code=company_code,
        checklist_id=checklist_id, vehicle_record_id=vehicle_record_id).first()
    identities = set()
    names = None
    if setting:
        if not inspect(db.engine).has_table(VehicleChecklistNotifyAccount.__tablename__):
            return []
        evidence = VehicleChecklistNotifyAccount.query.filter_by(company_code=company_code,
            setting_id=setting.id).order_by(VehicleChecklistNotifyAccount.id.desc()).first()
        if not evidence:
            return []
        saved = safe_json_dict(evidence.identities_json)
        names = set(safe_json_str_list(setting.notify_users_json))
        identities = {identity for name, identity in saved.items()
                      if name in names and isinstance(identity, str) and identity}
    else:
        # Q03's generation columns/JSON are optional until #283 is merged.
        # Numeric user IDs, usernames and names are not generation evidence.
        for result in VehicleChecklistResult.query.filter_by(company_code=company_code,
                checklist_id=checklist_id, vehicle_record_id=vehicle_record_id).all():
            for field in ('checked_by_identity', 'approved_by_identity'):
                identity = getattr(result, field, None)
                if identity:
                    identities.add(identity)
            identities.update(a['approved_by_identity'] for a in safe_json_dict_list(result.approvals_json)
                if isinstance(a.get('approved_by_identity'), str) and a['approved_by_identity'])
    if not identities:
        return []
    query = User.query.filter(User.company_code == company_code, User.account_identity.in_(identities))
    if names is not None:
        query = query.filter(User.username.in_(names))
    return query.order_by(User.username).all()
