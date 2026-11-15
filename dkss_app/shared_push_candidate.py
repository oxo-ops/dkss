"""Isolated shared-device push candidate, never a production feature flag.

A queued push cannot be recalled. Candidate payloads therefore contain no
person-specific text, counts, or destination, even when authority is current.
"""
import hashlib
import os
import time
from flask import current_app, session, has_app_context
from sqlalchemy.orm import DeclarativeBase
from .extensions import db


class PushCandidateBase(DeclarativeBase):
    pass


class PushAuthorityBinding(PushCandidateBase):
    __tablename__ = 'push_authority_binding_candidate'
    subscription_id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), nullable=False)
    endpoint_hash = db.Column(db.String(64), nullable=False)
    company_code = db.Column(db.String(50), nullable=False)
    account_identity = db.Column(db.String(64), nullable=False)


def enabled():
    if not has_app_context() or not current_app.config.get('SHARED_PUSH_CANDIDATE'):
        return False
    if (not current_app.testing or not current_app.config.get('SESSION_AUTHORITY_CANDIDATE')
            or current_app.config.get('SESSION_COOKIE_SECURE') or os.environ.get('RENDER') == 'true'):
        raise RuntimeError('Shared push candidate requires isolated session-authority tests')
    # The session-authority factory guard validates isolated database and limits.
    from .session_authority import CandidateSessionInterface
    if not isinstance(current_app.session_interface, CandidateSessionInterface):
        raise RuntimeError('Shared push candidate requires configured session authority')
    return True


def bind(subscription):
    """Caller has authenticated via the real authority middleware. Same transaction."""
    from .session_authority_model import SessionAuthority
    token = session.get('authority_token')
    if not isinstance(token, str) or len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
        return False
    token_hash = hashlib.sha256(token.encode('ascii')).hexdigest()
    now = int(time.time())
    active = db.session.execute(db.select(SessionAuthority.token_hash).where(
        SessionAuthority.token_hash == token_hash,
        SessionAuthority.account_identity == subscription.owner_identity,
        SessionAuthority.revoked.is_(False), SessionAuthority.idle_until > now,
        SessionAuthority.absolute_until > now)).scalar_one_or_none()
    if active is None:
        return False
    db.session.flush()
    row = db.session.get(PushAuthorityBinding, subscription.id)
    if row is None:
        row = PushAuthorityBinding(subscription_id=subscription.id)
        db.session.add(row)
    row.token_hash = token_hash
    row.endpoint_hash = hashlib.sha256(subscription.endpoint.encode()).hexdigest()
    row.company_code = subscription.company_code
    row.account_identity = subscription.owner_identity
    return True


def eligible(subscription):
    """Recheck directly in DB, not a potentially cached authority ORM instance."""
    from .session_authority_model import SessionAuthority
    now = int(time.time())
    return db.session.execute(db.select(PushAuthorityBinding.subscription_id).join(
        SessionAuthority, SessionAuthority.token_hash == PushAuthorityBinding.token_hash).where(
        PushAuthorityBinding.subscription_id == subscription.id,
        PushAuthorityBinding.endpoint_hash == hashlib.sha256(subscription.endpoint.encode()).hexdigest(),
        PushAuthorityBinding.company_code == subscription.company_code,
        PushAuthorityBinding.account_identity == subscription.owner_identity,
        SessionAuthority.account_identity == subscription.owner_identity,
        SessionAuthority.revoked.is_(False), SessionAuthority.idle_until > now,
        SessionAuthority.absolute_until > now)).scalar_one_or_none() is not None


def unbind(subscription):
    db.session.execute(db.delete(PushAuthorityBinding).where(
        PushAuthorityBinding.subscription_id == subscription.id))


def payload():
    # Safe for an older installed worker too: no reliance on a SW update race.
    return {'title': 'DKSS', 'message': 'お知らせがあります。ログインして確認してください。',
            'link': '/notifications', 'unread_count': 0}
