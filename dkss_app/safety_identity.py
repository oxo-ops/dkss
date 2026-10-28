"""Safety identities are captured at a new action, never inferred on reads.

IDs deliberately have no deleting FK: account deletion must not erase or
reassign an historical subject. Legacy NULL IDs remain unresolved.
"""
import json

from flask import has_request_context, request, session
from sqlalchemy import event, inspect, select, text

from .extensions import db


IDENTITY_FIELDS = {
    'checklist_result': {'target_username': 'target_user_id',
        'checked_by_username': 'checked_by_user_id', 'approved_by_username': 'approved_by_user_id'},
    'vehicle_checklist_result': {'checked_by_username': 'checked_by_user_id',
        'approved_by_username': 'approved_by_user_id'},
    'patrol_result': {'created_by_username': 'created_by_user_id',
        'target_username': 'target_user_id', 'countermeasure_by_username': 'countermeasure_by_user_id'},
    'checklist_event': {'actor_username': 'actor_user_id'},
}


def user_id(company, username, *, lock=False):
    from .models import User
    if not company or not username:
        return None
    query = select(User.id).where(User.company_code == company, User.username == username)
    if lock:
        query = query.with_for_update(read=True, key_share=True)
    return db.session.execute(query).scalar_one_or_none()


def user_ids(company, usernames):
    from .models import User
    names = list(dict.fromkeys(usernames or []))
    users = dict(db.session.execute(select(User.username, User.id).where(
        User.company_code == company, User.username.in_(names))
        .order_by(User.id).with_for_update(read=True, key_share=True)).all())
    return [users.get(name) for name in names]


def selected_candidate_ids(company, usernames, previous):
    """Unchanged form values must not silently rebind a retired candidate.

    Preserve evidence by username across the previous slots. Missing or
    conflicting old evidence stays unresolved; a fresh selection of another
    login can bind a new ID. Recovery of a reused login needs explicit review.
    """
    known = {}
    for approval in previous:
        names = approval.get('candidate_usernames') or []
        ids = approval.get('candidate_user_ids') or []
        for index, name in enumerate(names):
            value = ids[index] if index < len(ids) else None
            known.setdefault(name, set()).add(value if type(value) is int else None)
    names = list(dict.fromkeys(usernames or []))
    fresh = user_ids(company, [name for name in names if name not in known])
    new = dict(zip((name for name in names if name not in known), fresh))
    return [(next(iter(known[name])) if len(known[name]) == 1 else None)
            if name in known else new[name] for name in names]


def current_user_id():
    if not has_request_context():
        return None
    key = ('safety.user_id', session.get('company_code'), session.get('username'))
    if key not in request.environ:
        request.environ[key] = user_id(key[1], key[2])
    return request.environ[key]


def is_current(saved_id):
    return type(saved_id) is int and saved_id == current_user_id()


def is_candidate(approval):
    values = approval.get('candidate_user_ids')
    return isinstance(values, list) and current_user_id() is not None and any(
        is_current(value) for value in values)


def register_models(models):
    """New ORM records capture their subjects inside the insert transaction.

    No update listener: changing an unrelated field of legacy data must not
    adopt the current holder of a username. Explicit actions set their IDs.
    """
    def capture(mapper, connection, row):
        from .models import User
        fields = IDENTITY_FIELDS[row.__tablename__]
        try:
            approvals = json.loads(getattr(row, 'approvals_json', None) or '[]')
        except (ValueError, TypeError):
            approvals = None
        names = {getattr(row, field) for field in fields}
        if isinstance(approvals, list):
            for approval in approvals:
                if isinstance(approval, dict):
                    names.update(approval.get('candidate_usernames', []))
                    names.add(approval.get('approved_by_username'))
        try:
            judgment = json.loads(getattr(row, 'operation_judgment_json', None) or '{}')
        except (ValueError, TypeError):
            judgment = None
        if isinstance(judgment, dict):
            names.update(judgment.get('requested_usernames', []))
        names.discard(None)
        users = dict(connection.execute(select(User.username, User.id).where(
            User.company_code == row.company_code, User.username.in_(names))
            .with_for_update(read=True, key_share=True)).all())
        for username_field, id_field in fields.items():
            # Server-side lookup also ignores supplied/foreign identity IDs.
            setattr(row, id_field, users.get(getattr(row, username_field)))
        if hasattr(row, 'approvals_json') and isinstance(approvals, list):
            for approval in approvals:
                if not isinstance(approval, dict):
                    continue
                if 'candidate_user_ids' not in approval:
                    approval['candidate_user_ids'] = [users[n] for n in
                        approval.get('candidate_usernames', []) if n in users]
                approval['approved_by_user_id'] = users.get(approval.get('approved_by_username'))
            row.approvals_json = json.dumps(approvals, ensure_ascii=False)
        if hasattr(row, 'operation_judgment_json') and isinstance(judgment, dict) and judgment:
            if 'requested_user_ids' not in judgment:
                judgment['requested_user_ids'] = [users[n] for n in
                    judgment.get('requested_usernames', []) if n in users]
            row.operation_judgment_json = json.dumps(judgment, ensure_ascii=False)
    for model in models:
        event.listen(model, 'before_insert', capture)


def upgrade_storage():
    """Add nullable identity evidence only; never backfill current usernames."""
    with db.engine.begin() as connection:
        if connection.dialect.name == 'postgresql':
            connection.execute(text('SELECT pg_advisory_xact_lock(710032028)'))
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        for table, fields in IDENTITY_FIELDS.items():
            if table not in tables:
                continue
            existing = {c['name'] for c in inspector.get_columns(table)}
            for column in fields.values():
                if column not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} INTEGER'))
