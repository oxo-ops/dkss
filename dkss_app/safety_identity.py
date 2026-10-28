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

GENERATION_FIELDS = {
    'target_user_id': 'target_identity', 'checked_by_user_id': 'checked_by_identity',
    'approved_by_user_id': 'approved_by_identity', 'created_by_user_id': 'created_by_identity',
    'countermeasure_by_user_id': 'countermeasure_by_identity', 'actor_user_id': 'actor_identity',
}


def user_identity(company, username, *, lock=False):
    values = user_identities(company, [username]) if company and username else []
    return values[0] if values else None


def user_identities(company, usernames):
    from .models import User
    names = list(dict.fromkeys(usernames or []))
    with db.session.no_autoflush:
        rows = db.session.execute(select(User.username, User.account_identity).where(
            User.company_code == company, User.username.in_(names)).order_by(User.id)
            .with_for_update(read=True, key_share=True)).all()
    found = dict(rows)
    return [found.get(name) for name in names]


def selected_candidate_identities(company, usernames, previous):
    known = {}
    for approval in previous:
        names = approval.get('candidate_usernames') or []
        identities = approval.get('candidate_identities') or []
        for index, name in enumerate(names):
            value = identities[index] if index < len(identities) else None
            known.setdefault(name, set()).add(value)
    names = list(dict.fromkeys(usernames or []))
    fresh_names = [name for name in names if name not in known]
    fresh = dict(zip(fresh_names, user_identities(company, fresh_names)))
    return [(next(iter(known[name])) if len(known[name]) == 1 else None)
        if name in known else fresh[name] for name in names]


def as_dict(value):
    try:
        result = json.loads(value or '{}')
    except (ValueError, TypeError):
        return {}
    return result if isinstance(result, dict) else {}


def as_list(value):
    try:
        result = json.loads(value or '[]')
    except (ValueError, TypeError):
        return []
    return result if isinstance(result, list) else []


def notification_bindings(record, usernames):
    previous = as_dict(record.notification_identities_json)
    old_names = set(as_list(record.notify_users_json))
    fresh = [n for n in usernames if n not in old_names]
    resolved = dict(zip(fresh, user_identities(record.company_code, fresh)))
    return json.dumps({n: previous.get(n) if n in old_names else resolved.get(n)
        for n in usernames}, ensure_ascii=False)


def recipient(record, username, role=None):
    """Translate a stored workflow subject to Q08 without changing generation."""
    from .models import User
    evidence = set()
    for field, numeric in IDENTITY_FIELDS.get(record.__tablename__, {}).items():
        if getattr(record, field) == username:
            evidence.add(getattr(record, GENERATION_FIELDS[numeric]))
    for approval in as_list(getattr(record, 'approvals_json', None)):
        for index, name in enumerate(approval.get('candidate_usernames') or []):
            if name == username:
                identities = approval.get('candidate_identities') or []
                evidence.add(identities[index] if index < len(identities) else None)
        if approval.get('approved_by_username') == username:
            evidence.add(approval.get('approved_by_identity'))
    judgment = as_dict(getattr(record, 'operation_judgment_json', None))
    for index, name in enumerate(judgment.get('requested_usernames') or []):
        if name == username:
            identities = judgment.get('requested_identities') or []
            evidence.add(identities[index] if index < len(identities) else None)
    notified = as_dict(getattr(record, 'notification_identities_json', None))
    if username in notified:
        evidence.add(notified[username])
    if len(evidence) != 1 or not next(iter(evidence), None):
        return None
    query = User.query.filter_by(company_code=record.company_code,
        username=username, account_identity=next(iter(evidence)))
    return query.filter_by(role=role).first() if role else query.first()


def user_id(company, username, *, lock=False):
    from .models import User
    if not company or not username:
        return None
    query = select(User.id).where(User.company_code == company, User.username == username)
    if lock:
        query = query.with_for_update(read=True, key_share=True)
    with db.session.no_autoflush:
        return db.session.execute(query).scalar_one_or_none()


def user_ids(company, usernames):
    from .models import User
    names = list(dict.fromkeys(usernames or []))
    with db.session.no_autoflush:
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


def is_current(saved_identity):
    if not isinstance(saved_identity, str) or not saved_identity:
        return False
    from .account_identity import current_identity
    return saved_identity == current_identity()


def is_candidate(approval):
    values = approval.get('candidate_identities')
    return isinstance(values, list) and any(
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
        names.update(as_list(getattr(row, 'notify_users_json', None)))
        names.discard(None)
        users = {name: (ident, generation) for name, ident, generation in connection.execute(select(User.username, User.id, User.account_identity).where(
            User.company_code == row.company_code, User.username.in_(names))
            .with_for_update(read=True, key_share=True)).all()}
        for username_field, id_field in fields.items():
            # Server-side lookup also ignores supplied/foreign identity IDs.
            ident, generation = users.get(getattr(row, username_field), (None, None))
            setattr(row, id_field, ident)
            setattr(row, GENERATION_FIELDS[id_field], generation)
        if hasattr(row, 'approvals_json') and isinstance(approvals, list):
            for approval in approvals:
                if not isinstance(approval, dict):
                    continue
                if 'candidate_user_ids' not in approval:
                    approval['candidate_user_ids'] = [users[n][0] for n in
                        approval.get('candidate_usernames', []) if n in users]
                if 'candidate_identities' not in approval:
                    approval['candidate_identities'] = [users.get(n, (None, None))[1]
                        for n in approval.get('candidate_usernames', [])]
                ident, generation = users.get(approval.get('approved_by_username'), (None, None))
                approval['approved_by_user_id'] = ident
                approval['approved_by_identity'] = generation
            row.approvals_json = json.dumps(approvals, ensure_ascii=False)
        if hasattr(row, 'operation_judgment_json') and isinstance(judgment, dict) and judgment:
            if 'requested_user_ids' not in judgment:
                judgment['requested_user_ids'] = [users[n][0] for n in
                    judgment.get('requested_usernames', []) if n in users]
            if 'requested_identities' not in judgment:
                judgment['requested_identities'] = [users.get(n, (None, None))[1]
                    for n in judgment.get('requested_usernames', [])]
            row.operation_judgment_json = json.dumps(judgment, ensure_ascii=False)
        if hasattr(row, 'notification_identities_json') and not row.notification_identities_json:
            row.notification_identities_json = json.dumps({n: users.get(n, (None, None))[1]
                for n in as_list(row.notify_users_json)}, ensure_ascii=False)
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
            for column in (GENERATION_FIELDS[field] for field in fields.values()):
                if column not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} VARCHAR(36)'))
            if table in {'checklist_result', 'vehicle_checklist_result'} and 'notification_identities_json' not in existing:
                connection.execute(text(f'ALTER TABLE {table} ADD COLUMN notification_identities_json TEXT'))
