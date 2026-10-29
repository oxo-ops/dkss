"""Receipt ownership is an immutable Q08 account generation, never a name lookup."""
from flask import has_request_context, session, request
from sqlalchemy import String, and_, event, inspect, text
from sqlalchemy.orm import Session
from .extensions import db
from .account_identity import current_identity


def private_response(response):
    if request.endpoint in {'enqueue_documents','document_import_job','document_import_status',
        'retry_document_import','delete_document_import','document_import_kind',
        'vehicle_document_import_preview','vehicle_document_import_confirm','vehicle_document_import_source'}:
        response.headers['Cache-Control']='private, no-store'
    return response


def identity_for_actor(company_code, username, lock=False):
    from .models import User, Company
    query=db.session.query(User.account_identity).join(Company, Company.company_code==User.company_code).filter(
        User.company_code==company_code, User.username==username,
        User.role.in_({'admin','itc'}), User.login_locked.is_(False), Company.active.is_(True))
    if has_request_context():
        identity=current_identity()
        if not identity or session.get('company_code')!=company_code or session.get('username')!=username:
            return None
        query=query.filter(User.account_identity==identity)
    if lock:
        # HTTP confirmation takes its existing company write lock separately.
        # A company share lock here can deadlock when two requests upgrade it.
        query=query.with_for_update(read=True,of=[User])
    return query.scalar()


def owner_clause(model, company_code=None, username=None):
    if company_code is None and has_request_context():
        company_code,username=session.get('company_code'),session.get('username')
    identity=identity_for_actor(company_code,username)
    return and_(model.company_code==company_code,model.owner_identity==identity) if identity else db.false()


def owns(row, company_code=None, username=None):
    if company_code is None and has_request_context():
        company_code,username=session.get('company_code'),session.get('username')
    identity=identity_for_actor(company_code,username)
    return bool(identity and row.company_code==company_code and row.owner_identity==identity)


def active_owner_username(row, lock=False, lock_company=True):
    from .models import User, Company
    if not row.owner_identity:
        return None
    query=db.session.query(User.username).join(Company,Company.company_code==User.company_code).filter(
        User.company_code==row.company_code, User.account_identity==row.owner_identity,
        User.role.in_({'admin','itc'}),User.login_locked.is_(False),Company.active.is_(True))
    if lock:
        query=query.with_for_update(read=True,of=[User,Company] if lock_company else [User])
    return query.scalar()


@event.listens_for(Session,'before_flush')
def bind_new_receipts(session_,flush_context,instances):
    from .models import VehicleDocumentImportDraft as Draft, User
    for row in session_.dirty:
        if isinstance(row,Draft) and inspect(row).attrs.owner_identity.history.has_changes():
            raise ValueError('Receipt ownership is immutable; do not rebind old account generations')
    # Trusted new-row writers and test fixtures share Q08's new-user UUID binding.
    # Persisted legacy rows are never backfilled. Worker children set the parent UUID explicitly.
    for row in list(session_.new):
        if not isinstance(row,Draft) or row.owner_identity:
            continue
        if has_request_context():
            if row.company_code==session.get('company_code') and row.created_by_username==session.get('username'):
                row.owner_identity=current_identity()
            continue
        users=[u for u in session_.new if isinstance(u,User) and u.company_code==row.company_code
            and u.username==row.created_by_username and u not in session_.deleted]
        if not users:
            users=session_.query(User).filter_by(company_code=row.company_code,username=row.created_by_username).limit(2).all()
        if len(users)==1 and users[0] not in session_.deleted:
            row.owner_identity=users[0].account_identity


def upgrade_import_owners(engine):
    """Add nullable evidence only; existing originals/results remain unbound and unchanged."""
    with engine.begin() as c:
        columns={col['name']:col for col in inspect(c).get_columns('vehicle_document_import_draft')}
        if 'owner_identity' in columns:
            kind=columns['owner_identity']['type']
            if not isinstance(kind,String) or (kind.length is not None and kind.length<36):
                raise RuntimeError('Existing receipt owner column cannot store account UUIDs; inspect the schema first')
        if 'owner_identity' not in columns:
            c.execute(text('ALTER TABLE vehicle_document_import_draft ADD COLUMN owner_identity VARCHAR(36)'))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_vehicle_document_import_draft_owner_identity '
            'ON vehicle_document_import_draft (owner_identity)'))
