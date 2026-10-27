"""Company-scoped originals, legacy reads, explicit compaction and rollback."""

import hashlib
from flask import current_app
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from .extensions import db
from .models import (
    VehicleDocumentSource as Source,
    VehicleDocumentImportDraft as Draft,
    DocumentQueueSchedule,
    DomainSchemaRevision,
)

REVISION = "20261027_shared_document_sources"


def ready():
    state = current_app.extensions["dkss"]
    if not state.get("document_sources_ready"):
        state["document_sources_ready"] = inspect(db.engine).has_table(
            Source.__tablename__
        )
    return bool(state.get("document_sources_ready"))


def read_source(draft):
    if draft.status == "deleted":
        return b""
    if draft._source_file:
        return draft._source_file
    if not draft.company_code or not draft.source_sha256 or not ready():
        return b""
    key = (draft.company_code, draft.source_sha256)
    cached = getattr(draft, "_shared_source", None)
    if cached is not None and cached[0] == key:
        return cached[1].content
    source = db.session.get(Source, key)
    if source is not None:
        draft._shared_source = (key, source)
    return source.content if source else b""


def store_source(company_code, digest, content):
    if not company_code or hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("SOURCE_CHANGED")
    if not ready():
        return content

    def locked_source():
        return (
            Source.query.filter_by(company_code=company_code, sha256=digest)
            .with_for_update()
            .first()
        )

    source = locked_source()
    if source is None:
        try:
            with db.session.begin_nested():
                db.session.add(
                    Source(company_code=company_code, sha256=digest, content=content)
                )
                db.session.flush()
        except IntegrityError:
            source = locked_source()
            if source is None:
                raise
    if source is not None and source.content != content:
        raise ValueError("SOURCE_CHANGED")
    return b""


def purge_unreferenced(company_code, digest):
    if not ready():
        return
    db.session.flush()
    source = (
        Source.query.filter_by(company_code=company_code, sha256=digest)
        .with_for_update()
        .first()
    )
    if (
        source is not None
        and not Draft.query.filter_by(company_code=company_code, source_sha256=digest)
        .filter(Draft.status != "deleted", Draft._source_file == b"")
        .first()
    ):
        db.session.delete(source)


def upgrade_storage():
    with db.engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(824700028)"))
        for table in (
            Source.__table__,
            DocumentQueueSchedule.__table__,
            DomainSchemaRevision.__table__,
        ):
            table.create(connection, checkfirst=True)
        if (
            connection.execute(
                DomainSchemaRevision.__table__.select().where(
                    DomainSchemaRevision.revision == REVISION
                )
            ).first()
            is None
        ):
            connection.execute(
                DomainSchemaRevision.__table__.insert().values(revision=REVISION)
            )
    current_app.extensions["dkss"]["document_sources_ready"] = True


def compact_sources(batch_size=5):
    if not ready():
        raise RuntimeError("Run upgrade-domain-storage first")
    last_id, moved = "", 0
    while True:
        rows = (
            Draft.query.filter(
                Draft.id > last_id,
                Draft.status != "deleted",
                db.func.length(Draft._source_file) > 0,
            )
            .order_by(Draft.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
            .all()
        )
        if not rows:
            break
        for row in rows:
            last_id = row.id
            original = row._source_file
            inline = store_source(row.company_code, row.source_sha256, original)
            moved += Draft.query.filter_by(
                id=row.id,
                company_code=row.company_code,
                status=row.status,
                _source_file=original,
            ).update({"_source_file": inline}, synchronize_session=False)
        db.session.commit()
        db.session.expunge_all()
    return moved


def restore_inline_sources():
    last_id, restored = "", 0
    while True:
        row = (
            Draft.query.filter(
                Draft.id > last_id, Draft.status != "deleted", Draft._source_file == b""
            )
            .order_by(Draft.id)
            .with_for_update()
            .first()
        )
        if row is None:
            break
        last_id = row.id
        content = read_source(row)
        if not content or hashlib.sha256(content).hexdigest() != row.source_sha256:
            db.session.rollback()
            raise ValueError("SOURCE_CHANGED: cannot restore " + last_id)
        row.source_file = content
        db.session.commit()
        db.session.expunge_all()
        restored += 1
    return restored
