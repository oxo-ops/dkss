"""Q04 master record generations; independent of person/account identities.

Imports do not access a database. Existing storage is only changed by the
explicit upgrade function, never by a GET, a form token, or application startup.
"""
from uuid import UUID, uuid4

from flask import current_app, session
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy import MetaData, Table, inspect, select, text


KINDS = {'offices': 'office', 'vehicle-types': 'vehicle_type',
         'delivery-places': 'delivery_place', 'license-types': 'license_type',
         'patrol-content-types': 'patrol_content_type'}
FIELD = 'master_generation'
MESSAGE = '対象のマスタを識別できません。画面を再読み込みして再度お試しください。解消しない場合は管理者に移行状態の確認を依頼してください。'


class MasterFormConflict(Exception):
    pass


def new_generation():
    return str(uuid4())


def valid_generation(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value and UUID(value).int != 0
    except (ValueError, TypeError, AttributeError):
        return False


def issue_token(kind, company, ident, generation, operation):
    if kind not in KINDS or operation not in {'edit', 'delete'} or not valid_generation(generation):
        return ''
    return URLSafeSerializer(current_app.secret_key, salt='q04-master-generation-v1').dumps(
        [kind, company, ident, generation, operation])


def template_token(kind, ident, generation, operation):
    return issue_token(kind, session.get('company_code'), ident, generation, operation)


def template_context():
    return {'master_form_token': template_token}


def verify_token(row, operation, token):
    kind = next(kind for kind, table in KINDS.items() if table == row.__tablename__)
    if not valid_generation(row.master_generation) or not isinstance(token, str) or len(token) > 2048:
        raise MasterFormConflict(MESSAGE)
    try:
        payload = URLSafeSerializer(current_app.secret_key, salt='q04-master-generation-v1').loads(token)
    except BadData:
        raise MasterFormConflict(MESSAGE) from None
    if payload != [kind, row.company_code, row.id, row.master_generation, operation]:
        raise MasterFormConflict(MESSAGE)


def _tables(connection, schema=None):
    inspector = inspect(connection)
    schema = schema or inspector.default_schema_name
    available = set(inspector.get_table_names(schema=schema))
    return schema, available


def _ordinary_storage(connection, schema, name):
    # An UPDATE of metadata could fire custom business/audit triggers. Never
    # silently run those, or claim complete migration through a filtered RLS view.
    if connection.dialect.name == 'sqlite':
        quote = connection.dialect.identifier_preparer.quote
        extra = connection.scalar(text('SELECT name FROM ' + quote(schema)
            + ".sqlite_master WHERE type='trigger' AND tbl_name=:name LIMIT 1"), {'name': name})
    else:
        extra = connection.scalar(text(
            "SELECT c.relrowsecurity OR c.relkind <> 'r' "
            "OR EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal) "
            "OR EXISTS(SELECT 1 FROM pg_rewrite r WHERE r.ev_class=c.oid) "
            "OR EXISTS(SELECT 1 FROM pg_inherits i WHERE i.inhrelid=c.oid OR i.inhparent=c.oid) "
            'FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace '
            'WHERE n.nspname=:schema AND c.relname=:name'), {'schema': schema, 'name': name})
    if extra:
        raise RuntimeError(f'Custom master storage (trigger/rule/RLS/inheritance) requires DBA review: {name}')


def validate_storage(connection, schema=None, allow_empty=False):
    """Read-only validation. Missing/invalid generations are never inferred here."""
    schema, available = _tables(connection, schema)
    if allow_empty and not available.intersection(KINDS.values()):
        return
    for name in KINDS.values():
        if name not in available:
            raise RuntimeError(f'Master generation migration requires table: {name}')
        _ordinary_storage(connection, schema, name)
        table = Table(name, MetaData(), schema=schema, autoload_with=connection)
        if FIELD not in table.c:
            raise RuntimeError(f'Master generation migration is required: {name}.{FIELD}')
        seen = set()
        for ident, value in connection.execute(select(table.c.id, table.c[FIELD])):
            if not valid_generation(value) or value in seen:
                raise RuntimeError(f'Master generation is missing, invalid or duplicated: {name}.{FIELD}, id={ident}')
            seen.add(value)


def upgrade_storage(engine, schema=None):
    """Explicit, transactional, additive metadata migration. Never repair IDs/names.

    Writers must be stopped, including old application binaries. Preserve assigned
    generations on reruns. A malformed existing generation aborts the transaction.
    """
    with engine.connect() as connection:
        try:
            if connection.dialect.name == 'sqlite':
                connection.exec_driver_sql('BEGIN IMMEDIATE')
            elif connection.dialect.name == 'postgresql':
                connection.exec_driver_sql("SET LOCAL lock_timeout='2s'")
                connection.exec_driver_sql("SET LOCAL statement_timeout='15s'")
            else:
                raise ValueError('Only SQLite and PostgreSQL are supported')
            schema, available = _tables(connection, schema)
            if not set(KINDS.values()).issubset(available):
                raise RuntimeError('All five existing master tables are required; no bootstrap is performed')
            quote = connection.dialect.identifier_preparer.quote
            prefix = quote(schema) + '.'
            if connection.dialect.name == 'postgresql':
                targets = ', '.join(prefix + quote(name) for name in KINDS.values())
                connection.exec_driver_sql('LOCK TABLE ' + targets + ' IN ACCESS EXCLUSIVE MODE')
            report = {}
            for name in KINDS.values():
                _ordinary_storage(connection, schema, name)
            for name in KINDS.values():
                columns = {c['name'] for c in inspect(connection).get_columns(name, schema=schema)}
                if not {'id', 'company_code', 'name'}.issubset(columns):
                    raise RuntimeError(f'Unexpected legacy master shape: {name}')
                added = FIELD not in columns
                if added:
                    connection.exec_driver_sql('ALTER TABLE ' + prefix + quote(name)
                        + ' ADD COLUMN ' + quote(FIELD) + ' VARCHAR(36)')
                table = Table(name, MetaData(), schema=schema, autoload_with=connection)
                # Preserve existing values. Only previously unassigned metadata is populated.
                values = connection.execute(select(table.c.id, table.c[FIELD])).all()
                seen = set()
                for ident, value in values:
                    if value is not None and (not valid_generation(value) or value in seen):
                        raise RuntimeError(f'Invalid existing master generation: {name}, id={ident}')
                    if value is not None:
                        seen.add(value)
                assigned = 0
                for ident, value in values:
                    if value is None:
                        generation = new_generation()
                        if generation in seen:
                            raise RuntimeError('Master generation collision; no metadata was committed')
                        seen.add(generation)
                        result = connection.execute(table.update().where(table.c.id == ident,
                            table.c[FIELD].is_(None)).values({FIELD: generation}))
                        if result.rowcount != 1:
                            raise RuntimeError('Master changed during generation migration; stop writers and retry')
                        assigned += 1
                report[name] = dict(added_column=added, assigned=assigned)
            validate_storage(connection, schema)
            connection.commit()
            return report
        except Exception:
            connection.rollback()
            raise
