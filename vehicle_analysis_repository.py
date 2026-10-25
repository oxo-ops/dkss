"""SQLAlchemy adapters for vehicle analysis; no import from the application."""
from dataclasses import dataclass
from datetime import timedelta
import json

from sqlalchemy.exc import IntegrityError


@dataclass
class AnalysisInputRecords:
    maintenance: list
    operations: list
    parts: list
    defects: list
    periodic: list


class VehicleAnalysisInputRepository:
    def __init__(self, *, maintenance, operations, parts, defects, periodic):
        self.maintenance = maintenance
        self.operations = operations
        self.parts = parts
        self.defects = defects
        self.periodic = periodic

    def load(self, vehicle, as_of):
        scope = {"company_code": vehicle.company_code, "vehicle_record_id": vehicle.id}
        maintenance = self.maintenance.query.filter_by(**scope).all()
        operations = self.operations.query.filter_by(**scope).filter(
            self.operations.operation_date <= as_of.isoformat(),
        ).all()
        # Both child and parent must belong to the same company/vehicle.
        parts = self.parts.query.join(
            self.maintenance, self.parts.maintenance_record_id == self.maintenance.id,
        ).filter(
            self.parts.company_code == vehicle.company_code,
            self.parts.vehicle_record_id == vehicle.id,
            self.maintenance.company_code == vehicle.company_code,
            self.maintenance.vehicle_record_id == vehicle.id,
        ).all()
        defects = self.defects.query.filter_by(**scope).all()
        periodic = self.periodic.query.filter_by(**scope).all()
        return AnalysisInputRecords(maintenance, operations, parts, defects, periodic)


class VehicleAnalysisJobRepository:
    """Conditional claims and writes; each mutation retains its lease token."""

    def __init__(self, *, db, state_model, vehicle_model):
        self.db = db
        self.State = state_model
        self.Vehicle = vehicle_model

    def get_or_create(self, vehicle):
        scope = {"company_code": vehicle.company_code, "vehicle_record_id": vehicle.id}
        state = self.State.query.filter_by(**scope).first()
        if state is None:
            try:
                with self.db.session.begin_nested():
                    state = self.State(**scope)
                    self.db.session.add(state)
                    self.db.session.flush()
            except IntegrityError:
                state = self.State.query.filter_by(**scope).one()
        return state

    def get(self, state_id):
        return self.db.session.get(self.State, state_id)

    def claim(self, state_id, input_hash, token, now):
        claimed = self.State.query.filter(
            self.State.id == state_id,
            self.State.input_hash == input_hash,
            self.State.status.in_({"pending", "error", "running"}),
            self.State.next_analysis_at <= now,
            self.db.or_(self.State.lease_expires_at.is_(None),
                        self.State.lease_expires_at <= now),
        ).update({
            "status": "running", "lease_token": token,
            "lease_expires_at": now + timedelta(minutes=3),
        }, synchronize_session=False)
        self.db.session.commit()
        return bool(claimed)

    def find_vehicle(self, company_code, vehicle_record_id):
        return self.Vehicle.query.filter_by(
            id=vehicle_record_id, company_code=company_code, deleted=False,
        ).first()

    def skip(self, state_id, token):
        self.State.query.filter_by(id=state_id, lease_token=token).update({
            "status": "skipped", "next_analysis_at": None, "lease_token": None,
            "lease_expires_at": None,
            "last_error": "対象車両が存在しないか、無効になっています。",
        }, synchronize_session=False)
        self.db.session.commit()

    def renew(self, state_id, token, now):
        renewed = self.State.query.filter_by(
            id=state_id, lease_token=token, status="running",
        ).update({"lease_expires_at": now + timedelta(minutes=3)}, synchronize_session=False)
        if renewed != 1:
            self.db.session.rollback()
            raise RuntimeError("ANALYSIS_LEASE_LOST")
        self.db.session.commit()

    def finish(self, state_id, token, *, claimed_hash, snapshot_hash, bundle, finished, method):
        self.db.session.expire_all()
        state = self.State.query.filter_by(
            id=state_id, lease_token=token,
        ).with_for_update().first()
        if state is None:
            self.db.session.rollback()
            return False
        changed = state.input_hash not in {claimed_hash, snapshot_hash}
        state.result_json = json.dumps(bundle, ensure_ascii=False, default=str)
        state.last_analyzed_at = finished if method == "ai" else None
        state.last_error = None
        state.lease_token = None
        state.lease_expires_at = None
        if changed:
            state.status = "pending"
            state.next_analysis_at = finished + timedelta(minutes=2)
        else:
            state.status = "completed"
            state.input_hash = snapshot_hash
            state.next_analysis_at = None
        self.db.session.commit()
        return True

    def rollback(self):
        self.db.session.rollback()

    def fail(self, state_id, token, code, retry_at):
        self.State.query.filter_by(id=state_id, lease_token=token).update({
            "status": "error", "last_error": code, "next_analysis_at": retry_at,
            "lease_token": None, "lease_expires_at": None,
        }, synchronize_session=False)
        self.db.session.commit()
