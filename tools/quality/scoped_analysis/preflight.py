"""Explicit ordinary-input preflight. No count, generation, credentials or writes.

Production entry requires PostgreSQL and a fresh application session. The private
SQLite in-memory path exists only for isolated tests, never as a production
fallback. Company-wide maintenance knowledge is an explicit disclosure category.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
import json
from sqlalchemy import event, text
from sqlalchemy.orm import with_loader_criteria
from .pilot import Target, digest, positive_int


@dataclass(frozen=True)
class NormalReadScope:
    company: str
    vehicle_id: int
    state_id: int
    allowed_vehicle_ids: tuple
    company_knowledge_allowed: bool

    def __post_init__(self):
        if (not isinstance(self.company, str) or not self.company.strip()
                or not positive_int(self.vehicle_id) or not positive_int(self.state_id)
                or type(self.allowed_vehicle_ids) is not tuple or not self.allowed_vehicle_ids
                or any(not positive_int(v) for v in self.allowed_vehicle_ids)
                or len(set(self.allowed_vehicle_ids)) != len(self.allowed_vehicle_ids)
                or self.vehicle_id not in self.allowed_vehicle_ids
                or self.company_knowledge_allowed is not True):
            raise ValueError('EXPLICIT_NORMAL_READ_SCOPE_REQUIRED')


@dataclass(frozen=True)
class NormalInputSnapshot:
    target: Target
    state_id: int
    comparison_vehicle_ids: tuple
    payload: dict = field(repr=False)
    sources: object = field(repr=False)
    company_knowledge_authorized: bool = True


def _detach(value):
    def convert(item):
        if isinstance(item, (date, datetime, Decimal)):
            return str(item)
        raise TypeError('UNSUPPORTED_NORMAL_INPUT_VALUE')
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=convert))


def _snapshot(scope, payload, sources):
    detached = _detach(payload)
    comparison = detached.get('comparison')
    if not isinstance(comparison, dict):
        raise ValueError('NORMAL_COMPARISON_EVIDENCE_REQUIRED')
    bounds = comparison.get('comparison_scope')
    if (not isinstance(bounds, dict) or bounds.get('acceptance_limited')
            or bounds.get('same_company_only') is not True
            or bounds.get('target_vehicle_excluded') is not True):
        raise ValueError('NORMAL_COMPARISON_SCOPE_REQUIRED')
    peers = bounds.get('cohort_vehicle_ids')
    if (not isinstance(peers, list) or any(not positive_int(v) for v in peers)
            or len(set(peers)) != len(peers) or scope.vehicle_id in peers
            or not set(peers).issubset(scope.allowed_vehicle_ids)):
        raise ValueError('NORMAL_COHORT_OUTSIDE_APPROVED_SCOPE')
    return NormalInputSnapshot(Target(scope.company, scope.vehicle_id, digest(detached)),
                               scope.state_id, tuple(sorted(peers)), detached, _detach(sources))


def read_normal_input(scope):
    """Read the unmodified ordinary input inside one READ ONLY snapshot.

    The trusted ordinary builder may read company vehicle metadata to discover
    the full cohort. It is never given a restricted comparison-ID argument.
    No snapshot leaves this function if the complete resulting cohort exceeds
    the authorized set. All company-bearing ORM reads are company-filtered.
    """
    from dkss_app.extensions import db
    from dkss_app.models import Vehicle, VehicleKarteAnalysis
    from dkss_app.analysis import get_vehicle_karte_analysis_job_data
    if db.engine.dialect.name != 'postgresql':
        raise ValueError('POSTGRES_READ_ONLY_REQUIRED')
    return _read(scope, db.session(), db.Model.registry, Vehicle, VehicleKarteAnalysis,
                 get_vehicle_karte_analysis_job_data)


def _read(scope, session, registry, Vehicle, State, build_input, *, _sqlite_memory_test=False):
    if not isinstance(scope, NormalReadScope):
        raise ValueError('EXPLICIT_NORMAL_READ_SCOPE_REQUIRED')
    if session.in_transaction() or session.identity_map or session.new or session.dirty or session.deleted:
        raise ValueError('FRESH_READ_SESSION_REQUIRED')
    engine = session.get_bind()
    sqlite_test = (_sqlite_memory_test is True and engine.dialect.name == 'sqlite'
                   and engine.url.database in (None, '', ':memory:'))
    if engine.dialect.name != 'postgresql' and not sqlite_test:
        raise ValueError('POSTGRES_READ_ONLY_REQUIRED')
    criteria = []
    for mapper in registry.mappers:
        cls = mapper.class_
        if hasattr(cls, 'company_code'):
            criteria.append(with_loader_criteria(cls, cls.company_code == scope.company, include_aliases=True))
    transaction = None

    def forbid_write(*args):
        raise ValueError('NORMAL_PREFLIGHT_WRITES_FORBIDDEN')

    def ordinary_select(state):
        if session.get_transaction() is not transaction:
            raise ValueError('NORMAL_READ_TRANSACTION_CHANGED')
        if not state.is_select or not state.is_orm_statement:
            raise ValueError('ONLY_NORMAL_COMPANY_ORM_READS_ALLOWED')
        state.statement = state.statement.options(*criteria)

    try:
        if sqlite_test:
            session.execute(text('PRAGMA query_only = ON'))
        else:
            session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            session.execute(text("SET LOCAL statement_timeout = '10000'"))
            session.execute(text("SET LOCAL lock_timeout = '5000'"))
        transaction = session.get_transaction()
        event.listen(session, 'do_orm_execute', ordinary_select)
        event.listen(session, 'before_commit', forbid_write)
        event.listen(session, 'before_flush', forbid_write)
        try:
            state = session.query(State).filter_by(id=scope.state_id,
                company_code=scope.company, vehicle_record_id=scope.vehicle_id).one_or_none()
            vehicle = session.query(Vehicle).filter_by(id=scope.vehicle_id,
                company_code=scope.company, deleted=False).one_or_none()
            if state is None or vehicle is None:
                raise ValueError('NORMAL_STATE_OR_VEHICLE_UNAVAILABLE')
            payload, sources = build_input(vehicle)  # no scoped override, no partial comparison
            result = _snapshot(scope, payload, sources)
            # Verify cohort IDs against same-company rows in this same snapshot.
            ids = session.query(Vehicle.id).filter(Vehicle.id.in_(result.comparison_vehicle_ids)).all()
            if {row[0] for row in ids} != set(result.comparison_vehicle_ids):
                raise ValueError('NORMAL_COHORT_COMPANY_MISMATCH')
            return result
        finally:
            event.remove(session, 'do_orm_execute', ordinary_select)
            event.remove(session, 'before_commit', forbid_write)
            event.remove(session, 'before_flush', forbid_write)
    finally:
        session.rollback()
        session.expunge_all()
        if sqlite_test:
            session.execute(text('PRAGMA query_only = OFF'))
            session.rollback()
