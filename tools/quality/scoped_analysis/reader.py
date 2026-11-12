"""Explicit, read-only PostgreSQL acceptance reader. No CLI or auto invocation.

Call only in a fresh, authorized application/request context. Company-wide
maintenance knowledge is retained; vehicle records are limited to target+cohort.
This guards trusted ORM readers, not arbitrary malicious code with DB access.
"""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import json
from dataclasses import dataclass
from sqlalchemy import event, text
from sqlalchemy.orm import with_loader_criteria
from .pilot import Target, digest


@dataclass(frozen=True)
class ReadScope:
    company: str
    targets: tuple
    comparison_ids: tuple

    def __post_init__(self):
        if (not isinstance(self.company, str) or not self.company.strip()
                or type(self.targets) is not tuple or not 1 <= len(self.targets) <= 5
                or type(self.comparison_ids) is not tuple or len(self.comparison_ids) > 5
                or any(type(v) is not int or v <= 0 for v in self.targets + self.comparison_ids)
                or len(set(self.targets)) != len(self.targets)
                or len(set(self.comparison_ids)) != len(self.comparison_ids)):
            raise ValueError('INVALID_READ_SCOPE')


def read_scoped_inputs(scope):
    """Return detached snapshots; always rollback, never generate/cache/save.

    Requires a fresh session so preloaded identities or pending changes cannot
    bypass scoping. Rejects non-PostgreSQL rather than simulating READ ONLY.
    """
    if not isinstance(scope, ReadScope):
        raise ValueError('INVALID_READ_SCOPE')
    from dkss_app.extensions import db
    from dkss_app.models import Vehicle
    from dkss_app.analysis import get_vehicle_karte_analysis_job_data
    session = db.session()
    if session.in_transaction() or session.identity_map or session.new or session.dirty or session.deleted:
        raise ValueError('FRESH_READ_SESSION_REQUIRED')
    if db.engine.dialect.name != 'postgresql':
        raise ValueError('POSTGRES_READ_ONLY_REQUIRED')
    ids = tuple(sorted(set(scope.targets + scope.comparison_ids)))
    criteria = []
    for mapper in db.Model.registry.mappers:
        cls = mapper.class_
        if hasattr(cls, 'company_code'):
            criteria.append(with_loader_criteria(cls, cls.company_code == scope.company, include_aliases=True))
        if hasattr(cls, 'vehicle_record_id'):
            criteria.append(with_loader_criteria(cls, cls.vehicle_record_id.in_(ids), include_aliases=True))
    criteria.append(with_loader_criteria(Vehicle, Vehicle.id.in_(ids), include_aliases=True))

    transaction = None

    def forbid_write(*args):
        raise ValueError('READ_ACCEPTANCE_WRITES_FORBIDDEN')

    def scoped_select(state):
        if session.get_transaction() is not transaction:
            raise ValueError('READ_TRANSACTION_CHANGED')
        if not state.is_select or not state.is_orm_statement:
            raise ValueError('ONLY_SCOPED_ORM_READS_ALLOWED')
        state.statement = state.statement.options(*criteria)

    try:
        # First SQL after begin: snapshot and write prohibition cover every
        # subsequent query, including raw DB writes accidentally added later.
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        session.execute(text("SET LOCAL statement_timeout = '10000'"))
        session.execute(text("SET LOCAL lock_timeout = '5000'"))
        transaction = session.get_transaction()
        event.listen(session, 'do_orm_execute', scoped_select)
        event.listen(session, 'before_commit', forbid_write)
        event.listen(session, 'before_flush', forbid_write)
        try:
            results = []
            for vehicle_id in scope.targets:
                vehicle = session.query(Vehicle).filter_by(
                    company_code=scope.company, id=vehicle_id, deleted=False).one_or_none()
                if vehicle is None:
                    raise ValueError('SCOPED_VEHICLE_UNAVAILABLE')
                payload, sources = get_vehicle_karte_analysis_job_data(
                    vehicle, comparison_vehicle_ids=scope.comparison_ids)
                # No lazy objects may escape the transaction. The current builder
                # returns dictionaries; digest rejects unexpected ORM objects.
                def json_value(value):
                    if isinstance(value, (Decimal, date, datetime)):
                        return str(value)  # Same conversion as the existing wire serializer.
                    raise TypeError('UNSUPPORTED_SCOPED_INPUT_VALUE')
                detached = json.loads(json.dumps(payload, ensure_ascii=False,
                    allow_nan=False, default=json_value))
                revision = digest(detached)
                results.append({'target': Target(scope.company, vehicle.id, revision),
                                'payload': detached, 'sources': deepcopy(sources)})
            return results
        finally:
            event.remove(session, 'do_orm_execute', scoped_select)
            event.remove(session, 'before_commit', forbid_write)
            event.remove(session, 'before_flush', forbid_write)
    finally:
        session.rollback()
        session.expunge_all()
