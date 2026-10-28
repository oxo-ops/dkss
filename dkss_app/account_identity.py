"""Immutable account generations. Never infer historical ownership from a login ID."""
from uuid import uuid4

from flask import has_request_context, session
from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from .extensions import db


def current_identity():
    return session.get('account_identity') if has_request_context() else None


def notification_owner_clause():
    from .models import Notification
    identity = current_identity()
    # Comparing NULL to NULL must never grant ownership of quarantined history.
    return Notification.owner_identity == identity if identity else db.false()


def owns_notification(notification):
    return bool(current_identity() and notification.owner_identity == current_identity()
                and notification.company_code == session.get('company_code'))


@event.listens_for(Session, 'before_flush')
def bind_new_notifications(session_, flush_context, instances):
    from .models import User, Notification, News
    for row in session_.dirty:
        if isinstance(row, User) and inspect(row).attrs.account_identity.history.has_changes():
            raise ValueError('Account identity is immutable; do not reassign historical ownership.')
        if isinstance(row, Notification) and inspect(row).attrs.owner_identity.history.has_changes():
            raise ValueError('Notification ownership is immutable.')
    new_users = [row for row in session_.new if isinstance(row, User)]
    for user in new_users:
        if not user.account_identity:
            user.account_identity = str(uuid4())
    # All notification writers (including workflow writers) use the same binding.
    news_targets = [row for row in session_.dirty if isinstance(row, News)
                    and (inspect(row).attrs.target_type.history.has_changes()
                         or inspect(row).attrs.target_value.history.has_changes())]
    for row in list(session_.new) + news_targets:
        if isinstance(row, News):
            if row.target_type != 'user':
                row.owner_identity = None
                continue
            if row in news_targets:
                row.owner_identity = None
            username = row.target_value
        elif isinstance(row, Notification):
            username = row.target_username
        else:
            continue
        if row.owner_identity:
            continue
        matches = [u for u in new_users if u.company_code == row.company_code
                   and u.username == username]
        if not matches and username:
            matches = session_.query(User).filter_by(company_code=row.company_code,
                                                     username=username).with_for_update(read=True).limit(2).all()
        if len(matches) == 1 and matches[0] not in session_.deleted:
            row.owner_identity = matches[0].account_identity


def upgrade_account_identity():
    """Explicit, additive migration. Existing notifications/audits remain unbound.

    Run with application writers stopped. No import/factory/GET executes DDL.
    The nullable columns permit a staged deployment; there is no username backfill.
    """
    columns = {
        'user': [('account_identity', 'VARCHAR(36)')],
        'notification': [('owner_identity', 'VARCHAR(36)')],
        'news': [('owner_identity', 'VARCHAR(36)')],
        'push_subscription': [('owner_identity', 'VARCHAR(36)')],
        'audit_log': [('actor_identity', 'VARCHAR(36)'), ('actor_name', 'VARCHAR(200)')],
        'vehicle_maintenance_record_event': [('actor_identity', 'VARCHAR(36)'), ('actor_name', 'VARCHAR(200)')],
    }
    with db.engine.begin() as connection:
        inspector = inspect(connection)
        for table, additions in columns.items():
            existing = {col['name'] for col in inspector.get_columns(table)}
            for name, type_ in additions:
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {name} {type_}'))
        # This identifies existing account rows, not owners of legacy notifications.
        for ident in connection.execute(text('SELECT id FROM "user" WHERE account_identity IS NULL')).scalars().all():
            connection.execute(text('UPDATE "user" SET account_identity=:identity WHERE id=:id AND account_identity IS NULL'),
                               {'identity': str(uuid4()), 'id': ident})
        for name, table, fields, unique in [
            ('uq_user_account_identity', 'user', 'account_identity', True),
            ('ix_notification_owner_identity', 'notification', 'company_code, owner_identity', False),
            ('ix_push_owner_identity', 'push_subscription', 'company_code, owner_identity', False),
        ]:
            connection.execute(text(f'CREATE {"UNIQUE " if unique else ""}INDEX IF NOT EXISTS {name} ON "{table}" ({fields})'))


def audit_actor_label(log):
    """Snapshots only. In particular, do not join a legacy username to today's User."""
    name = log.actor_name or log.username or ''
    return f'{name} [{log.actor_identity}]' if log.actor_identity else f'{name} [旧記録・本人未確認]'
