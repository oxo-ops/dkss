"""Isolated, opt-in DB reader for the registered-defect priority adapter.

No HTTP route, background job, model mutation or normal application caller.
The pure engine remains shadow-only. This is a development integration seam.
"""
from datetime import date
import os

from flask import current_app

from vehicle_priority_assessment import InvalidInput, ProductionUseBlocked
from vehicle_priority_sources import DefectRecord, DefectSnapshot, assess_registered_defects

ENABLE_KEY = "MAINTENANCE_PRIORITY_RECORD_ADAPTER_ENABLED"


def read_registered_defect_snapshot(*, company_code, vehicle_id, captured_on):
    """Read scoped stored fields; never reuse AI prose or historical status claims."""
    if (current_app.config.get("TESTING") is not True
            or current_app.config.get(ENABLE_KEY) is not True
            or os.environ.get("RENDER") == "true"):
        raise ProductionUseBlocked("registered-defect adapter requires explicit isolated testing configuration")
    if (not isinstance(company_code, str) or not company_code.strip()
            or type(vehicle_id) is not int or vehicle_id <= 0 or type(captured_on) is not date):
        raise InvalidInput("trusted company, vehicle and capture date are required")
    from .models import Vehicle, VehiclePatrol, db
    # no_autoflush prevents a read from flushing unrelated pending ORM edits.
    # Reject such sessions as well so persisted and in-memory facts cannot mix.
    if db.session.new or db.session.dirty or db.session.deleted:
        raise InvalidInput("read adapter requires a clean ORM session")
    with db.session.no_autoflush:
        vehicle = Vehicle.query.filter_by(company_code=company_code, id=vehicle_id, deleted=False).first()
        if vehicle is None:
            raise InvalidInput("vehicle is absent from the supplied host scope")
        rows = VehiclePatrol.query.filter_by(company_code=company_code, vehicle_record_id=vehicle_id).populate_existing().order_by(VehiclePatrol.id).all()
        snapshot = DefectSnapshot(company_code, vehicle_id, captured_on, tuple(
            DefectRecord(row.id, row.company_code, row.vehicle_record_id, row.occurred_date,
                         row.content, row.status, row.repair_date) for row in rows))
    return snapshot


def read_registered_defect_priorities(*, company_code, vehicle_id, captured_on):
    snapshot = read_registered_defect_snapshot(company_code=company_code, vehicle_id=vehicle_id,
                                               captured_on=captured_on)
    return assess_registered_defects(snapshot, as_of=captured_on)


def read_bound_registered_defect_priorities(analysis, sources, bindings):
    """Isolated host integration; current stored values must match explicit binding."""
    from vehicle_priority_binding import DefectBindingSet, build_bound_defect_projection
    if not isinstance(bindings, DefectBindingSet):
        raise InvalidInput("explicit binding set required")
    snapshot = read_registered_defect_snapshot(company_code=bindings.company_code,
                                               vehicle_id=bindings.vehicle_id, captured_on=bindings.captured_on)
    return build_bound_defect_projection(analysis, sources, snapshot, bindings, as_of=bindings.captured_on)
