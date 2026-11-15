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

from flask import current_app, request, session, g
from flask.sessions import SecureCookieSessionInterface
from .extensions import db




class CandidateSessionInterface(SecureCookieSessionInterface):
    """Rejected/losing responses must not overwrite a newer browser cookie."""
    def save_session(self, app, session, response):
        if g.get('authority_replacement_conflict') or g.get('authority_api_rejected'):
            response.vary.add('Cookie')
            response.cache_control.no_store = True
            return
        return super().save_session(app, session, response)


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
    if type(app.session_interface) is not SecureCookieSessionInterface:
        raise RuntimeError('Candidate requires the default cookie session interface')
    app.session_interface = CandidateSessionInterface()


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


def begin_replacement():
    """One authenticated successor may replace a particular old authority.

    This is a revocation CAS, not a device identity or a shared PIN. A failed
    transition is fail-closed; callers must not issue another token. Identity
    verification must already have succeeded before calling this function.
    """
    if not enabled():
        return True
    token = session.get('authority_token')
    if token is None:
        return True  # Initial login (or the existing validated MFA challenge).
    if not (isinstance(token, str) and len(token) == 64 and
            all(c in '0123456789abcdef' for c in token)):
        return False
    from .session_authority_model import SessionAuthority
    now = int(time.time())
    # Keep authority -> user lock order even if login dirtied User first.
    with db.session.no_autoflush:
        result = db.session.execute(db.update(SessionAuthority).where(
            SessionAuthority.token_hash == _hash(token),
            SessionAuthority.account_identity == session.get('account_identity'),
            SessionAuthority.revoked.is_(False),
            SessionAuthority.idle_until > now,
            SessionAuthority.absolute_until > now).values(revoked=True))
    db.session.commit()
    return result.rowcount == 1


def replacement_conflict_response():
    # Do not redirect or delete/set a cookie: either can race the winning tab.
    # Clearing only request-local state avoids rendering the prior person's UI.
    from flask import make_response, render_template
    g.authority_replacement_conflict = True
    session.clear()
    response = make_response(render_template('session_switch_conflict.html'), 409)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Session-Transition'] = 'conflict'
    return response


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
        # Rejected document requests are just as capable of arriving late as
        # polls. Only explicit login is allowed to reset a stale cookie.
        if request.endpoint != 'login':
            g.authority_api_rejected = True
        session.clear()
        if request.path.startswith('/api/') or request.path == '/notifications/email-test':
            # A late polling rejection must not delete a successor's cookie.
            # Interactive /login retains the existing explicit reset flow.
            g.authority_api_rejected = True
            return {'ok': False, 'message': 'ログインが必要です。'}, 401
        from flask import redirect
        return redirect('/login')
    return None


def commit_vehicle_write(vehicle_id):
    """Candidate-only commit fence for vehicle analysis feedback and evaluation routes.

    Locks are retained through the domain commit. Not a global commit hook and
    not a claim that external effects or all application writes are fenced.
    """
    if not enabled():
        db.session.commit()
        return
    from flask import abort
    from .session_authority_model import SessionAuthority
    from .models import Company, User, Vehicle
    token = session.get('authority_token')
    try:
        # Never autoflush the pending domain mutation before authorization.
        with db.session.no_autoflush:
            authority = None
            if isinstance(token, str) and re.fullmatch(r'[0-9a-f]{64}', token):
                authority = db.session.execute(db.select(SessionAuthority).where(
                    SessionAuthority.token_hash == _hash(token)).with_for_update()
                    .execution_options(populate_existing=True)).scalar_one_or_none()
            company = db.session.execute(db.select(Company).where(
                Company.company_code == session.get('company_code')).with_for_update()
                .execution_options(populate_existing=True)).scalar_one_or_none()
            user = db.session.execute(db.select(User).where(
                User.company_code == session.get('company_code'),
                User.username == session.get('username')).with_for_update()
                .execution_options(populate_existing=True)).scalar_one_or_none()
            vehicle = db.session.execute(db.select(Vehicle).where(
                Vehicle.id == vehicle_id).with_for_update()
                .execution_options(populate_existing=True)).scalar_one_or_none()
            now = int(time.time())  # evaluate after any lock wait
            valid = (authority is not None and not authority.revoked and
                authority.idle_until > now and authority.absolute_until > now and
                authority.account_identity == session.get('account_identity') and
                user is not None and not user.login_locked and
                user.account_identity == authority.account_identity and
                user.password_changed_at == session.get('password_changed_at') and
                user.role == session.get('role') and not session.get('password_expired') and
                (user.role == 'itc' or (company is not None and company.active)) and
                vehicle is not None and not vehicle.deleted and
                vehicle.company_code == user.company_code)
            if not valid:
                db.session.rollback()
                g.authority_api_rejected = True
                abort(401)
        # Revocation UPDATE must wait for the authority lock until this commit.
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
