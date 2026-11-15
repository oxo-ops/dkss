"""Non-production session authority integration candidate.

Explicit TESTING-only opt-in. No default time limits and no automatic schema
creation. Request traffic never extends idle expiry; user-activity policy is a
separate acceptance gate, so polling cannot accidentally keep a session alive.
"""
import hashlib
import secrets
import time
import re
import os

from flask import current_app, request, session
from .extensions import db




def enabled():
    return bool(current_app.config.get('SESSION_AUTHORITY_CANDIDATE'))


def configure(app):
    if not app.config.get('SESSION_AUTHORITY_CANDIDATE'):
        return
    if not app.testing or app.config.get('SESSION_COOKIE_SECURE') or os.environ.get('RENDER') == 'true':
        raise RuntimeError('Session authority candidate is restricted to isolated tests')
    from sqlalchemy.engine import make_url
    url = make_url(app.config['SQLALCHEMY_DATABASE_URI'])
    sqlite_memory = url.get_backend_name() == 'sqlite' and url.database in (None, '', ':memory:')
    engine_options = app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})
    connect_args = engine_options.get('connect_args', {})
    if url.query or set(engine_options) - {'connect_args'} or set(connect_args) - {'options'}:
        raise RuntimeError('Connection overrides are not permitted for candidate tests')
    options = connect_args.get('options', '')
    isolated_pg = (url.get_backend_name() == 'postgresql' and
        url.host in ('127.0.0.1', 'localhost', '::1') and url.database == 'dkss_q02_ci' and
        re.fullmatch(r'-csearch_path=q02_session_[0-9a-f]{32} -cstatement_timeout=30000 -clock_timeout=10000', options))
    if not (sqlite_memory or isolated_pg):
        raise RuntimeError('Only in-memory SQLite or isolated q02 PostgreSQL schema permitted')
    for key in ('SESSION_AUTHORITY_IDLE_SECONDS', 'SESSION_AUTHORITY_ABSOLUTE_SECONDS'):
        value = app.config.get(key)
        if type(value) is not int or value <= 0:
            raise RuntimeError('Explicit positive test-only session limits required')
    if app.config['SESSION_AUTHORITY_IDLE_SECONDS'] > app.config['SESSION_AUTHORITY_ABSOLUTE_SECONDS']:
        raise RuntimeError('Idle lifetime must not exceed absolute lifetime')


def _hash(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def revoke_current():
    if not enabled():
        return
    from .session_authority_model import SessionAuthority
    token = session.get('authority_token')
    if isinstance(token, str) and len(token) == 64 and all(c in '0123456789abcdef' for c in token):
        db.session.execute(db.update(SessionAuthority).where(
            SessionAuthority.token_hash == _hash(token)).values(revoked=True))
        db.session.commit()


def issue(user):
    if not enabled():
        return
    from .session_authority_model import SessionAuthority
    revoke_current()
    token = secrets.token_hex(32)
    now = int(time.time())
    db.session.add(SessionAuthority(token_hash=_hash(token),
        account_identity=user.account_identity, issued_at=now,
        idle_until=now + current_app.config['SESSION_AUTHORITY_IDLE_SECONDS'],
        absolute_until=now + current_app.config['SESSION_AUTHORITY_ABSOLUTE_SECONDS']))
    db.session.commit()
    session['authority_token'] = token


def require_authority():
    if not enabled() or not session.get('username'):
        return None
    from .session_authority_model import SessionAuthority
    token = session.get('authority_token')
    row = None
    if isinstance(token, str) and len(token) == 64 and all(c in '0123456789abcdef' for c in token):
        now = int(time.time())
        row = db.session.execute(db.select(SessionAuthority.token_hash).where(
            SessionAuthority.token_hash == _hash(token),
            SessionAuthority.account_identity == session.get('account_identity'),
            SessionAuthority.revoked.is_(False),
            SessionAuthority.idle_until > now,
            SessionAuthority.absolute_until > now)).scalar_one_or_none()
    if row is None:
        session.clear()
        if request.path.startswith('/api/') or request.path == '/notifications/email-test':
            return {'ok': False, 'message': 'ログインが必要です。'}, 401
        from flask import redirect
        return redirect('/login')
    return None
