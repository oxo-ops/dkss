"""Form-time person evidence; separate from stored Q03/Q08 identity history."""
import re
import hashlib
import hmac
import json

from flask import current_app, request, session
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from .extensions import db
from .models import User


def _signer():
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt='q03-person-selection-v1')


def _fingerprint(state):
    secret = current_app.config['SECRET_KEY']
    key = secret if isinstance(secret, bytes) else secret.encode('utf8')
    return hmac.new(key, b'q03-choice-v1\0' + json.dumps(state[:3], separators=(',', ':')).encode(), hashlib.sha256).hexdigest()


def _states(rows):
    states = {}
    for name, identity, role, locked, *extra in rows:
        # A legacy duplicate login is ambiguous even if the last row happens
        # to match. Do not choose one of the accounts by query order.
        states[name] = None if name in states or not identity else [identity, role, bool(locked), *extra]
    return states


def issue():
    """Freeze this form's choices, never refresh evidence on a confirmation POST."""
    if 'q03.person_selection_token' not in request.environ:
        with db.session.no_autoflush:
            rows = db.session.execute(select(User.username, User.account_identity, User.role, User.login_locked)
                .where(User.company_code == session.get('company_code')).order_by(User.id)).all()
        choices = {name: _fingerprint(state) if state else None for name, state in _states(rows).items()}
        request.environ['q03.person_selection_token'] = _signer().dumps({'company': session.get('company_code'),
            'actor': session.get('account_identity'), 'choices': choices})
    return request.environ['q03.person_selection_token']


def selected_names():
    names = set()
    for field in request.form:
        if field == 'approval_notify_users_operation' and request.form.get('decision') != '運行不可':
            continue
        if field in {'notify_users', 'reminder_notify_users', 'manager_username', 'approval_notify_users_operation'} or re.fullmatch(r'approval_notify_users_\d+', field):
            names.update(v.strip() for v in request.form.getlist(field) if v.strip())
    if request.form.get('target_type') == 'user':
        names.add(request.form.get('target_user', '').strip())
    names.discard('')
    return names


def validate(*, actor_only=False):
    """Hold selected accounts until save; a stale/absent proof never binds B.

    The existing view still checks resource ownership, roles, record versions
    and general approval. This evidence grants no permission by itself.
    """
    names = set() if actor_only else selected_names()
    def conflict(status=409):
        from .http import return_form_errors
        db.session.rollback()
        return return_form_errors([('選択した利用者を確認できませんでした。画面を再読み込みし、本人を確認して選択し直してください。', '')], status)
    choices = None
    if names:
        try:
            evidence = _signer().loads(request.form.get('person_selection_token', ''))
        except BadData:
            return conflict()
        if not isinstance(evidence, dict) or evidence.get('company') != session.get('company_code') or not evidence.get('actor') or evidence['actor'] != session.get('account_identity'):
            return conflict()
        choices = evidence.get('choices')
        if not isinstance(choices, dict):
            return conflict()
        if any(name not in choices for name in names):
            # Preserve normal invalid-selection handling; never let an unknown
            # extra field bypass generation checks on the real selection.
            return conflict(400)
    actor = session.get('username')
    try:
        with db.session.no_autoflush:
            connection = db.session.connection()
            # SQLite SELECT does not necessarily begin a DBAPI transaction.
            # Reserve the writer before comparing. No commit is performed here.
            if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql('BEGIN IMMEDIATE')
            rows = db.session.execute(select(User.username, User.account_identity, User.role, User.login_locked, User.password_changed_at)
                .where(User.company_code == session.get('company_code'), User.username.in_(names | {actor}))
                .order_by(User.id).with_for_update(read=True)).all()
    except OperationalError as error:
        sqlite_code = getattr(error.orig, 'sqlite_errorcode', None)
        if getattr(error.orig, 'pgcode', None) in {'55P03', '40001', '40P01'} or (isinstance(sqlite_code, int) and (sqlite_code & 255) in {5, 6}):
            return conflict()
        raise
    current = _states(rows)
    actual_actor = current.get(actor)
    if not actual_actor or actual_actor[0] != session.get('account_identity') or actual_actor[1] != session.get('role') or actual_actor[2] or (actual_actor[3] or '') != (session.get('password_changed_at') or ''):
        return conflict()
    if choices is not None and any(not current.get(name) or not current[name][0] or choices.get(name) != _fingerprint(current[name]) for name in names | {actor}):
        return conflict()
    return None
