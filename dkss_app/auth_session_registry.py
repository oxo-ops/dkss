"""Durable logout revocation, separate from experimental shared-device policy.

Schema preparation and irreversible activation are explicit CLI operations.
Factory/import/request paths never create schema. No idle policy is introduced.
"""
import hashlib
import re
import secrets
import time

from flask import abort, g, request, session
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase

from .extensions import db


class RegistryBase(DeclarativeBase):
    pass


class AuthSessionPolicy(RegistryBase):
    __tablename__ = 'auth_session_policy'
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Integer, nullable=False)


class AuthSession(RegistryBase):
    __tablename__ = 'auth_session'
    token_hash = db.Column(db.String(64), primary_key=True)
    account_identity = db.Column(db.String(64), nullable=False, index=True)
    company_code = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    issued_at = db.Column(db.BigInteger, nullable=False)
    revoked = db.Column(db.Boolean, nullable=False, default=False)


def _failure():
    # Never persist partially authenticated state or delete a successor cookie.
    db.session.rollback()
    g.authority_api_rejected = True
    g.auth_registry_failure = True
    session.clear()  # request-local only; no authenticated error-page context
    abort(503, description='認証状態を確認できません。時間をおいてお試しください。')


def enforced():
    """Read durable policy, never an environment flag that could revive cookies.

    Missing schema is legacy-compatible only before first installation. A
    present but corrupt policy fails closed. Operators must not remove policy
    schema or roll back to binaries predating registry enforcement.
    """
    try:
        with db.session.no_autoflush:
            if not inspect(db.session.connection()).has_table('auth_session_policy'):
                if session.get('auth_session_token'):
                    _failure()
                return False
            version = db.session.execute(db.select(AuthSessionPolicy.version).where(
                AuthSessionPolicy.id == 1)).scalar_one_or_none()
            if version not in (0, 1):
                _failure()
            return version == 1
    except SQLAlchemyError:
        _failure()


def _token_hash():
    token = session.get('auth_session_token')
    if isinstance(token, str) and re.fullmatch(r'[0-9a-f]{64}', token):
        return hashlib.sha256(token.encode('ascii')).hexdigest()
    return None


def _owner_clause():
    return (AuthSession.account_identity == session.get('account_identity'),
            AuthSession.company_code == session.get('company_code'),
            AuthSession.username == session.get('username'))


def issue(user):
    if not enforced():
        return
    if not user.account_identity:
        _failure()
    token = secrets.token_hex(32)
    try:
        db.session.add(AuthSession(token_hash=hashlib.sha256(token.encode('ascii')).hexdigest(),
            account_identity=user.account_identity, company_code=user.company_code,
            username=user.username, issued_at=int(time.time()), revoked=False))
        db.session.commit()
    except SQLAlchemyError:
        _failure()
    session['auth_session_token'] = token


def revoke_current():
    required = enforced()
    token_hash = _token_hash()
    if not token_hash:
        # Anonymous/MFA-pending sessions have no fully authenticated token.
        if required and session.get('username'):
            _failure()
        return
    try:
        with db.session.no_autoflush:
            db.session.execute(db.update(AuthSession).where(
                AuthSession.token_hash == token_hash, *_owner_clause()).values(revoked=True))
        db.session.commit()
    except SQLAlchemyError:
        _failure()


def begin_replacement():
    if not enforced():
        return True
    token_hash = _token_hash()
    if not session.get('username') and not token_hash:
        return True
    if not token_hash:
        return False
    try:
        with db.session.no_autoflush:
            result = db.session.execute(db.update(AuthSession).where(
                AuthSession.token_hash == token_hash, *_owner_clause(),
                AuthSession.revoked.is_(False)).values(revoked=True))
        db.session.commit()
        return result.rowcount == 1
    except SQLAlchemyError:
        _failure()


def require_session():
    # Public anonymous entry remains available even when the DB is unavailable.
    # Authentication issuance still requires a successful registry commit.
    if not session.get('username'):
        return None
    required = enforced()
    token_hash = _token_hash()
    if not required and not session.get('auth_session_token'):
        return None
    try:
        with db.session.no_autoflush:
            valid = token_hash and db.session.execute(db.select(AuthSession.token_hash).where(
                AuthSession.token_hash == token_hash, *_owner_clause(),
                AuthSession.revoked.is_(False))).scalar_one_or_none()
    except SQLAlchemyError:
        _failure()
    if valid:
        return None  # Existing User/Company/password-generation checks still run.
    if request.endpoint != 'login':
        g.authority_api_rejected = True
    session.clear()
    if request.path.startswith('/api/') or request.path == '/notifications/email-test':
        g.authority_api_rejected = True
        return {'ok': False, 'message': 'ログインが必要です。'}, 401
    from flask import redirect
    return redirect('/login')


def prepare_schema():
    """Additive operator operation; no activation and no existing-table reset."""
    with db.engine.begin() as connection:
        existed = inspect(connection).has_table('auth_session_policy')
        if existed:
            version = connection.execute(db.select(AuthSessionPolicy.version).where(
                AuthSessionPolicy.id == 1)).scalar_one_or_none()
            if version not in (0, 1):
                raise RuntimeError('Existing authentication session policy is invalid')
        RegistryBase.metadata.create_all(connection)
        if not existed:
            connection.execute(db.insert(AuthSessionPolicy).values(id=1, version=0))


def activate():
    """One-way cutover: all legacy signed login cookies require reauthentication.

    Run only after all serving workers run this code. No deactivate operation.
    Keep schema/marker and token rows on rollback to an enforcement-capable build.
    """
    with db.engine.begin() as connection:
        inspector = inspect(connection)
        if not all(inspector.has_table(name) for name in ('auth_session_policy', 'auth_session')):
            raise RuntimeError('Prepare authentication session schema before activation')
        for table in (AuthSessionPolicy.__table__, AuthSession.__table__):
            actual = {column['name'] for column in inspector.get_columns(table.name)}
            if not set(table.columns.keys()).issubset(actual):
                raise RuntimeError('Authentication session schema is incomplete')
        version = connection.execute(db.select(AuthSessionPolicy.version).where(
            AuthSessionPolicy.id == 1).with_for_update()).scalar_one_or_none()
        if version not in (0, 1):
            raise RuntimeError('Authentication session policy is invalid')
        connection.execute(db.update(AuthSessionPolicy).where(
            AuthSessionPolicy.id == 1).values(version=1))
