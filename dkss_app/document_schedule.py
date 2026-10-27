"""Cross-process OCR admission and company round-robin scheduling."""

import os
from datetime import timedelta
from uuid import uuid4
from flask import current_app
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from .extensions import db
from .models import (
    DocumentQueueSchedule as Schedule,
    VehicleDocumentImportDraft as Draft,
)


def ready():
    state = current_app.extensions["dkss"]
    if not state.get("document_schedule_ready"):
        state["document_schedule_ready"] = inspect(db.engine).has_table(
            Schedule.__tablename__
        )
    return bool(state.get("document_schedule_ready"))


def limits():
    values = []
    for key, default in [
        ("DOCUMENT_IMPORT_MAX_CONCURRENT", 2),
        ("DOCUMENT_IMPORT_COMPANY_CONCURRENT", 1),
    ]:
        value = int(os.environ.get(key, default))
        if not 1 <= value <= 32:
            raise ValueError(key + " must be between 1 and 32")
        values.append(value)
    return values


def claim_fair():
    from .document_import_queue import (
        metadata,
        result,
        now,
        lightweight_query,
        ACTIVE,
        MAX_ATTEMPTS,
        LEASE_SECONDS,
    )

    global_limit, company_limit = limits()
    for _ in range(8):
        turn = db.session.get(Schedule, 1, populate_existing=True)
        if turn is None:
            try:
                with db.session.begin_nested():
                    db.session.add(Schedule(id=1, version=0))
                    db.session.flush()
            except IntegrityError:
                db.session.rollback()
            turn = db.session.get(Schedule, 1, populate_existing=True)
        version, last = turn.version, turn.last_company or ""
        stamp = now()
        busy = {}
        for company, data in db.session.query(
            Draft.company_code, Draft.result_json
        ).filter_by(status="reading"):
            if str(metadata(data).get("lease_until", "")) > stamp.isoformat():
                busy[company] = busy.get(company, 0) + 1
        if sum(busy.values()) >= global_limit:
            db.session.rollback()
            return None
        companies = [
            r[0]
            for r in db.session.query(Draft.company_code)
            .filter(Draft.status.in_(ACTIVE))
            .distinct()
            .order_by(Draft.company_code)
            .all()
        ]
        companies = [c for c in companies if c > last] + [
            c for c in companies if c <= last
        ]
        contended = False
        for company in companies:
            if busy.get(company, 0) >= company_limit:
                continue
            rows = (
                lightweight_query()
                .filter_by(company_code=company)
                .filter(Draft.status.in_(ACTIVE))
                .order_by(Draft.created_at, Draft.id)
                .limit(200)
                .all()
            )
            for row in rows:
                old_status, old_json = row.status, row.result_json
                job = metadata(old_json)
                if not job or (
                    old_status == "reading"
                    and str(job.get("lease_until", "")) > stamp.isoformat()
                ):
                    continue
                attempts = job.get("attempts", 0)
                job.update(attempts=attempts + 1, updated_at=stamp.isoformat())
                if attempts >= MAX_ATTEMPTS:
                    status = "read_error"
                    job.update(
                        phase="error",
                        message="処理が繰り返し中断しました。「失敗分を再実行」からやり直してください。",
                    )
                else:
                    status = "reading"
                    job.update(
                        phase="reading",
                        token=str(uuid4()),
                        lease_until=(
                            stamp + timedelta(seconds=LEASE_SECONDS)
                        ).isoformat(),
                    )
                admitted = Schedule.query.filter_by(id=1, version=version).update(
                    {"version": version + 1, "last_company": company},
                    synchronize_session=False,
                )
                claimed = admitted and Draft.query.filter_by(
                    id=row.id, status=old_status, result_json=old_json
                ).update(
                    {"status": status, "result_json": result(job)},
                    synchronize_session=False,
                )
                if not claimed:
                    db.session.rollback()
                    contended = True
                    break
                ident = row.id
                db.session.commit()
                if status == "reading":
                    return ident, job["token"]
                contended = True
                break
            if contended:
                break
        if not contended:
            db.session.rollback()
            return None
    return None
