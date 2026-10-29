"""Operation CSV receipts use Q02's authenticated account generation, not a login ID."""
from flask import abort, session
from sqlalchemy import String, event, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .extensions import db
from . import import_owner


def owner_clause():
    from .models import VehicleOperationImportDraft
    return import_owner.owner_clause(VehicleOperationImportDraft)


def shared_or_owned_clause():
    from .models import VehicleOperationImportDraft
    # Registered vehicle sources are company assets; private receipt access is separate.
    return db.or_(VehicleOperationImportDraft.status == 'completed', owner_clause())


def hold_owner(draft=None, *, vehicle_ids=()):
    """Hold vehicles before User, then verify the receipt before any mutation."""
    from .models import Vehicle
    try:
        with db.session.no_autoflush:
            connection = db.session.connection()
            if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql('BEGIN IMMEDIATE')
            ids = sorted({i for i in vehicle_ids if type(i) is int})
            if ids:
                db.session.execute(select(Vehicle.id).where(
                    Vehicle.company_code == session.get('company_code'), Vehicle.id.in_(ids)
                ).order_by(Vehicle.id).with_for_update(read=True)).all()
            identity = import_owner.identity_for_actor(session.get('company_code'), session.get('username'), lock=True)
    except OperationalError as error:
        code = getattr(error.orig, 'sqlite_errorcode', None)
        if getattr(error.orig, 'pgcode', None) in {'55P03', '40001', '40P01'} or (isinstance(code, int) and code & 255 in {5, 6}):
            db.session.rollback()
            abort(409, description='受付の保存処理が競合しました。画面を再取得してください。')
        raise
    if not identity or (draft is not None and (
            draft.company_code != session.get('company_code') or draft.owner_identity != identity)):
        db.session.rollback()
        abort(404)
    return identity


def hold_private_source(draft):
    if draft.status != 'completed':
        hold_owner(draft)


def private_csv_response(response):
    from flask import request
    if request.endpoint in {'vehicle_operation_import', 'vehicle_operation_import_preview',
                            'vehicle_operation_import_confirm', 'vehicle_operation_import_add_vehicle',
                            'vehicle_operation_import_result'}:
        response.headers['Cache-Control'] = 'private, no-store'
    return response


@event.listens_for(Session, 'before_flush')
def preserve_csv_owner(session_, flush_context, instances):
    from .models import VehicleOperationImportDraft
    for row in session_.dirty:
        if isinstance(row, VehicleOperationImportDraft) and inspect(row).attrs.owner_identity.history.has_changes():
            raise ValueError('CSV receipt ownership is immutable; legacy ownership needs separate verified recovery')


def upgrade_operation_csv_owners(engine):
    """Writers must be stopped. Append nullable evidence; never backfill legacy rows."""
    table = 'vehicle_operation_import_draft'
    index = 'ix_operation_csv_company_owner'
    with engine.begin() as connection:
        if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
        inspector = inspect(connection)
        if not inspector.has_table(table):
            raise RuntimeError('CSV receipt table is missing; apply the existing baseline first')
        columns = {c['name']: c for c in inspector.get_columns(table)}
        owner = columns.get('owner_identity')
        if owner and (not isinstance(owner['type'], String) or
                      (owner['type'].length is not None and owner['type'].length < 36) or not owner['nullable']):
            raise RuntimeError('Existing CSV owner column is incompatible; inspect storage before migration')
        existing = {i['name']: i for i in inspector.get_indexes(table)}.get(index)
        if existing and (existing['column_names'] != ['company_code', 'owner_identity'] or existing['unique']):
            raise RuntimeError('Existing CSV owner index is incompatible; inspect storage before migration')
        if connection.dialect.name == 'postgresql' and existing:
            valid = connection.scalar(text('SELECT i.indisvalid AND i.indisready FROM pg_index i '
                'JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace '
                'WHERE n.nspname=current_schema() AND c.relname=:name'), {'name': index})
            if valid is not True:
                raise RuntimeError('CSV owner index is not valid and ready')
        if owner is None:
            connection.execute(text('ALTER TABLE vehicle_operation_import_draft ADD COLUMN owner_identity VARCHAR(36)'))
        if not existing:
            connection.execute(text('CREATE INDEX ix_operation_csv_company_owner '
                                    'ON vehicle_operation_import_draft (company_code, owner_identity)'))
