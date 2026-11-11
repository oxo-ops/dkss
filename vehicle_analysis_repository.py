"""SQLAlchemy adapters for vehicle analysis; no import from the application."""
from dataclasses import dataclass
from datetime import timedelta
import json

from sqlalchemy.exc import IntegrityError

from vehicle_saved_result_guard import requires_newer_version


@dataclass
class AnalysisInputRecords:
    maintenance: list
    operations: list
    parts: list
    defects: list
    periodic: list


class VehicleAnalysisInputRepository:
    def __init__(self, *, maintenance, operations, parts, defects, periodic, canonical_operations=None):
        self.maintenance = maintenance
        self.operations = operations
        self.parts = parts
        self.defects = defects
        self.periodic = periodic
        self.canonical_operations = canonical_operations

    def load(self, vehicle, as_of):
        scope = {"company_code": vehicle.company_code, "vehicle_record_id": vehicle.id}
        maintenance = self.maintenance.query.filter_by(**scope).all()
        operations = self.operations.query.filter_by(**scope).filter(
            self.operations.operation_date <= as_of.isoformat(),
        ).all()
        if self.canonical_operations is not None:
            operations = self.canonical_operations(vehicle.company_code, vehicle.id, operations, end=as_of.isoformat())
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
        state = self.State.query.filter_by(**scope).populate_existing().with_for_update().first()
        if state is None:
            try:
                with self.db.session.begin_nested():
                    state = self.State(**scope)
                    self.db.session.add(state)
                    self.db.session.flush()
            except IntegrityError:
                state = self.State.query.filter_by(**scope).populate_existing().with_for_update().one()
        return state

    def get(self, state_id):
        return self.db.session.get(self.State, state_id)

    def writable(self, state_id, token=None):
        query = self.State.query.filter_by(id=state_id)
        if token is not None:
            query = query.filter_by(lease_token=token)
        state = query.populate_existing().with_for_update().first()
        if state is None or requires_newer_version(state.result_json):
            self.db.session.rollback()
            return None
        return state

    def claim(self, state_id, input_hash, token, now):
        state = self.writable(state_id)
        if state is None:
            return False
        claimed = self.State.query.filter(
            self.State.id == state_id,
            self.State.input_hash == input_hash,
            self.State.result_json == state.result_json,
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
        state = self.writable(state_id, token)
        if state is None:
            return
        self.State.query.filter_by(id=state_id, lease_token=token, result_json=state.result_json).update({
            "status": "skipped", "next_analysis_at": None, "lease_token": None,
            "lease_expires_at": None,
            "last_error": "対象車両が存在しないか、無効になっています。",
        }, synchronize_session=False)
        self.db.session.commit()

    def renew(self, state_id, token, now):
        state = self.writable(state_id, token)
        if state is None:
            raise RuntimeError("ANALYSIS_LEASE_LOST")
        renewed = self.State.query.filter_by(
            id=state_id, lease_token=token, status="running", result_json=state.result_json,
        ).update({"lease_expires_at": now + timedelta(minutes=3)}, synchronize_session=False)
        if renewed != 1:
            self.db.session.rollback()
            raise RuntimeError("ANALYSIS_LEASE_LOST")
        self.db.session.commit()

    def finish(self, state_id, token, *, claimed_hash, snapshot_hash, bundle, finished, method):
        state = self.writable(state_id, token)
        if state is None:
            return False
        changed = state.input_hash not in {claimed_hash, snapshot_hash}
        updates = {
            "result_json": json.dumps(bundle, ensure_ascii=False, default=str),
            "last_analyzed_at": finished if method == "ai" else None,
            "last_error": None, "lease_token": None, "lease_expires_at": None,
            "status": "pending" if changed else "completed",
            "next_analysis_at": finished + timedelta(minutes=2) if changed else None,
        }
        if not changed:
            updates["input_hash"] = snapshot_hash
        # Row lock on PostgreSQL plus compare-and-swap for the checked bytes.
        written = self.State.query.filter_by(
            id=state_id, lease_token=token, result_json=state.result_json,
            input_hash=state.input_hash,
        ).update(updates, synchronize_session=False)
        self.db.session.commit()
        return written == 1

    def rollback(self):
        self.db.session.rollback()

    def fail(self, state_id, token, code, retry_at):
        state = self.writable(state_id, token)
        if state is None:
            return
        self.State.query.filter_by(id=state_id, lease_token=token, result_json=state.result_json).update({
            "status": "error", "last_error": code, "next_analysis_at": retry_at,
            "lease_token": None, "lease_expires_at": None,
        }, synchronize_session=False)
        self.db.session.commit()
