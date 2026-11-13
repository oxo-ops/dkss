"""Company registration capabilities and approval transactions.

A shared invite is permission to APPLY, never permission to log in. The first
administrator is an ITC-verified customer representative, not the first visitor.
All writers take the company row lock before inspecting approval/account state.
"""
from datetime import datetime, timedelta
from functools import wraps
from hashlib import sha256
import secrets
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import (Company, CompanyRegistrationInvite as Invite,
                     CompanyRegistrationApplication as Application, Driver, Office, User)
from .audit import add_audit_log, update_company_usage_summary


class InviteError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _transaction(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
            db.session.commit()
            return result
        except InviteError:
            db.session.rollback()
            raise
        except SQLAlchemyError:
            db.session.rollback()
            # SQL and bound parameters can contain password hashes. Never chain.
            raise InviteError('処理を完了できませんでした。登録状況を確認してください。', 409) from None
    return call


def lock_company(company_code):
    company = Company.query.filter_by(company_code=company_code).populate_existing().with_for_update().first()
    if not company or not company.active or company.company_code.upper() == 'ITC':
        raise InviteError('この会社の登録受付は利用できません。', 404)
    return company


def _actor(actor):
    current = User.query.filter_by(id=actor.id, account_identity=actor.account_identity).populate_existing().first() if actor else None
    if not current or not current.account_identity or current.login_locked:
        raise InviteError('操作権限がありません。', 403)
    company = Company.query.filter_by(company_code=current.company_code, active=True).first()
    if not company:
        raise InviteError('操作権限がありません。', 403)
    return current


def _manager(company, actor, allow_itc=True):
    actor = _actor(actor)
    if allow_itc and actor.role == 'itc' and actor.company_code.upper() == 'ITC':
        return actor
    if actor.role != 'admin' or actor.company_code != company.company_code:
        raise InviteError('操作権限がありません。', 403)
    return actor


def _audit(action, company, actor=None, target_id='', detail=''):
    add_audit_log(action=action, target_type='company_registration', target_id=str(target_id),
                  company_code=company.company_code, username=actor.username if actor else 'registration', detail=detail)


def _purge_pending(invite_ids, status):
    if invite_ids:
        Application.query.filter(Application.invite_id.in_(invite_ids), Application.status == 'pending').update(
            {'status': status, 'password_hash': None, 'decided_at': datetime.utcnow()}, synchronize_session='fetch')


def _expire_pending(company_code):
    """Caller holds the company lock; free expired IDs and remove stale hashes."""
    ids = [row.id for row in Invite.query.filter(
        Invite.company_code == company_code,
        Invite.expires_at <= datetime.utcnow()).all()]
    count = Application.query.filter(Application.invite_id.in_(ids), Application.status == 'pending').count() if ids else 0
    _purge_pending(ids, 'expired')
    return count


@_transaction
def expire_pending_applications():
    """Explicit maintenance command; no external services, schema changes or tokens."""
    codes = [row.company_code for row in Application.query.filter_by(status='pending').with_entities(Application.company_code).distinct().order_by(Application.company_code).all()]
    total = 0
    for code in codes:
        # Include inactive companies: expiry must still erase password hashes.
        company = Company.query.filter_by(company_code=code).populate_existing().with_for_update().first()
        if company:
            total += _expire_pending(code)
    return total


@_transaction
def issue_invite(company_code, actor, days=7):
    company = lock_company(company_code)
    actor = _manager(company, actor)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
        raise InviteError('有効期限は1〜30日で指定してください。')
    old = Invite.query.filter_by(company_code=company_code, revoked_at=None).all()
    now = datetime.utcnow()
    for invite in old:
        invite.revoked_at = now
    _purge_pending([row.id for row in old], 'revoked')
    token = secrets.token_urlsafe(32)
    invite = Invite(company_code=company_code, token_hash=sha256(token.encode()).hexdigest(),
                    created_at=now, expires_at=now + timedelta(days=days), created_by=actor.account_identity)
    db.session.add(invite)
    db.session.flush()
    _audit('company_invite_issued', company, actor, invite.id)
    return invite, token


@_transaction
def revoke_invite(invite_id, actor):
    row = db.session.get(Invite, invite_id)
    if not row:
        raise InviteError('登録URLが見つかりません。', 404)
    company = lock_company(row.company_code)
    actor = _manager(company, actor)
    row = Invite.query.filter_by(id=invite_id).populate_existing().one()
    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        _purge_pending([row.id], 'revoked')
        _audit('company_invite_revoked', company, actor, row.id)
    return row


def validate_invite(raw_token, lock=False):
    if not isinstance(raw_token, str) or not 40 <= len(raw_token) <= 100:
        raise InviteError('登録URLが無効か、有効期限が切れています。', 404)
    row = Invite.query.filter_by(token_hash=sha256(raw_token.encode()).hexdigest()).first()
    if not row:
        raise InviteError('登録URLが無効か、有効期限が切れています。', 404)
    company = lock_company(row.company_code) if lock else Company.query.filter_by(company_code=row.company_code, active=True).first()
    if lock:
        row = Invite.query.filter_by(id=row.id).populate_existing().one()
    if not company or company.company_code.upper() == 'ITC' or row.revoked_at or row.expires_at <= datetime.utcnow():
        raise InviteError('登録URLが無効か、有効期限が切れています。', 404)
    return row, company


@_transaction
def submit_application(raw_token, form):
    invite, company = validate_invite(raw_token, lock=True)
    _expire_pending(company.company_code)
    from .auth import is_valid_email_address
    if any(key in form for key in ('role', 'company_code', 'company_id')):
        raise InviteError('会社・権限は登録URLから決まります。')
    values = {key: str(form.get(key, '')).strip() for key in ('employee_id', 'last_name', 'first_name', 'email_address', 'office')}
    values['email_address'] = values['email_address'].lower()
    password = form.get('password', '')
    if not isinstance(password, str):
        raise InviteError('パスワードの形式が不正です。')
    types = sum((any(c.islower() for c in password), any(c.isupper() for c in password),
                 any(c.isdigit() for c in password), any(not c.isalnum() for c in password)))
    if not values['employee_id'] or len(values['employee_id']) > 50 or not values['last_name'] or len(values['last_name'] + values['first_name']) > 100:
        raise InviteError('ログインID（50文字以内）と氏名（合計100文字以内）を入力してください。')
    email = values['email_address']
    if (email and (len(email) > 255 or not is_valid_email_address(email))) or (current_app.config.get('MFA_ENABLED') and not email):
        raise InviteError('有効なメールアドレスを入力してください。多要素認証が有効な場合は必須です。')
    if not 8 <= len(password) <= 128 or types < 3:
        raise InviteError('パスワードは8〜128文字で英小文字・英大文字・数字・記号のうち3種類以上を含めてください。')
    code = company.company_code
    office = values['office']
    if office and not Office.query.filter_by(company_code=code, name=office).first():
        raise InviteError('営業所が不正です。')
    if (User.query.filter_by(company_code=code, username=values['employee_id']).first()
            or Driver.query.filter_by(company_code=code, employee_id=values['employee_id']).first()
            or Application.query.filter_by(company_code=code, username=values['employee_id'], status='pending').first()):
        raise InviteError('このログインIDでは登録できません。会社の管理者に確認してください。', 409)
    if Application.query.filter_by(company_code=code, status='pending').count() >= 1000:
        raise InviteError('登録受付の上限に達しています。会社の管理者に確認してください。', 429)
    row = Application(company_code=code, invite_id=invite.id, username=values['employee_id'],
        last_name=values['last_name'], first_name=values['first_name'] or None,
        email_address=email or None, office=office or None,
        password_hash=generate_password_hash(password), status='pending')
    db.session.add(row)
    db.session.flush()
    _audit('company_registration_submitted', company, target_id=row.id)
    return row


def _application(application_id, actor):
    row = db.session.get(Application, application_id)
    if not row:
        raise InviteError('登録申請が見つかりません。', 404)
    company = lock_company(row.company_code)
    actor = _manager(company, actor)
    row = Application.query.filter_by(id=application_id).populate_existing().one()
    if row.status != 'pending':
        raise InviteError('この申請は処理済みです。', 409)
    return row, company, actor


@_transaction
def approve_application(application_id, actor, role='user', verification_reason=''):
    row, company, actor = _application(application_id, actor)
    code = company.company_code
    has_admin = User.query.filter_by(company_code=code, role='admin').first() is not None
    is_itc = actor.role == 'itc' and actor.company_code.upper() == 'ITC'
    if not has_admin:
        if not is_itc or role != 'admin' or not 10 <= len(verification_reason.strip()) <= 500:
            raise InviteError('最初の管理者は、導入時に確認した顧客責任者について確認記録を入力して承認してください。', 403)
    elif is_itc:
        raise InviteError('会社の管理者が登録申請を承認してください。', 403)
    if role not in ('user', 'admin'):
        raise InviteError('指定された権限は利用できません。')
    invite = db.session.get(Invite, row.invite_id)
    if not invite or invite.company_code != code or invite.revoked_at or invite.expires_at <= datetime.utcnow():
        raise InviteError('申請元の登録URLは失効しています。新しいURLから申請してください。', 409)
    from .auth import is_valid_email_address
    if current_app.config.get('MFA_ENABLED') and (not row.email_address or not is_valid_email_address(row.email_address)):
        raise InviteError('多要素認証に必要なメールアドレスがありません。再申請してください。', 409)
    if not row.password_hash:
        raise InviteError('この申請は承認できません。再申請してください。', 409)
    if (User.query.filter_by(company_code=code, username=row.username).first()
            or Driver.query.filter_by(company_code=code, employee_id=row.username).first()):
        raise InviteError('同じログインIDが既に登録されています。', 409)
    if row.office and not Office.query.filter_by(company_code=code, name=row.office).first():
        raise InviteError('申請された営業所が変更されています。再申請してください。', 409)
    user = User(company_code=code, username=row.username, password=row.password_hash,
        password_history_json='[]', password_changed_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        last_name=row.last_name, first_name=row.first_name, role=role, office=row.office,
        email_address=row.email_address, email_notify_enabled=False)
    driver = Driver(company_code=code, employee_id=row.username, name=row.last_name + (row.first_name or ''),
        role=role, office=row.office, safe_start_date=datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d'),
        vehicles_json='[]', licenses_json='[]')
    db.session.add_all([user, driver])
    row.status = 'approved'
    row.decided_at = datetime.utcnow()
    row.decided_by = actor.account_identity
    row.verification_reason = verification_reason.strip() if not has_admin else None
    row.approved_role = role
    row.password_hash = None
    db.session.flush()
    _audit('company_registration_approved', company, actor, row.id,
           '初回責任者確認済み' if not has_admin else '会社管理者による承認: ' + role)
    update_company_usage_summary(code)
    return user


@_transaction
def reject_application(application_id, actor):
    row, company, actor = _application(application_id, actor)
    if actor.role == 'itc' and User.query.filter_by(company_code=company.company_code, role='admin').first():
        raise InviteError('会社の管理者が登録申請を処理してください。', 403)
    row.status = 'rejected'
    row.password_hash = None
    row.decided_at = datetime.utcnow()
    row.decided_by = actor.account_identity
    _audit('company_registration_rejected', company, actor, row.id)
    return row


def upgrade_invite_schema():
    """Explicit migration: only the two additive tables; never called on reads."""
    with db.engine.begin() as connection:
        Invite.__table__.create(bind=connection, checkfirst=True)
        Application.__table__.create(bind=connection, checkfirst=True)
