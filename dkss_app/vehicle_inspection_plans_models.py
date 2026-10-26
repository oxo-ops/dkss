"""Model registration, independently cached for each SQLAlchemy extension."""
from datetime import datetime
from zoneinfo import ZoneInfo

def get_models(db):
    registry = getattr(db, "_dkss_model_registry", None)
    if registry is None:
        registry = db._dkss_model_registry = {}
    key = 'vehicle_inspection_plans.py'
    if key in registry:
        return registry[key]
    class VehicleInspectionPlan(db.Model):
        __table_args__ = (db.UniqueConstraint('company_code', 'vehicle_record_id', 'kind', 'period_key', name='uq_inspection_plan_period'),)
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        vehicle_record_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False, index=True)
        kind = db.Column(db.String(30), nullable=False)
        period_key = db.Column(db.String(7), nullable=False)
        planned_month = db.Column(db.String(7), nullable=False)
        reservation_date = db.Column(db.String(10))
        document_date = db.Column(db.String(10))
        factory = db.Column(db.String(200), nullable=False, default='')
        note = db.Column(db.String(1000), nullable=False, default='')
        source = db.Column(db.String(30), nullable=False, default='manual')
        source_record_id = db.Column(db.Integer, db.ForeignKey('vehicle_periodic_inspection_record.id'))
        completed_record_id = db.Column(db.Integer, db.ForeignKey('vehicle_periodic_inspection_record.id'))
        status = db.Column(db.String(20), nullable=False, default='planned')
        version = db.Column(db.Integer, nullable=False, default=1)
        updated_by = db.Column(db.String(50), nullable=False, default='')
        updated_at = db.Column(db.String(40), nullable=False, default='')

    class VehicleInspectionPlanEvent(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        plan_id = db.Column(db.Integer, db.ForeignKey('vehicle_inspection_plan.id'), nullable=False)
        action = db.Column(db.String(30), nullable=False)
        detail_json = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.String(40), nullable=False)
        created_by = db.Column(db.String(50), nullable=False)

    class VehicleInspectionExecution(db.Model):
        """An actual inspection reported before its document arrives."""
        __table_args__ = (db.UniqueConstraint('company_code', 'vehicle_record_id', 'kind', 'performed_date', name='uq_inspection_execution_day'),)
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        vehicle_record_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False, index=True)
        kind = db.Column(db.String(30), nullable=False)
        performed_date = db.Column(db.String(10), nullable=False)
        plan_id = db.Column(db.Integer, db.ForeignKey('vehicle_inspection_plan.id'), unique=True)
        source_record_id = db.Column(db.Integer, db.ForeignKey('vehicle_periodic_inspection_record.id'), unique=True)
        next_month = db.Column(db.String(7))
        factory = db.Column(db.String(200), nullable=False, default='')
        note = db.Column(db.String(1000), nullable=False, default='')
        created_by = db.Column(db.String(50), nullable=False)
        created_at = db.Column(db.String(40), nullable=False)

    class VehicleInspectionExecutionEvidence(db.Model):
        execution_id = db.Column(db.Integer, db.ForeignKey('vehicle_inspection_execution.id'), primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        new_expiry = db.Column(db.String(10))
        previous_expiry = db.Column(db.String(10))
        document_id = db.Column(db.String(36), db.ForeignKey('vehicle_document_import_draft.id'))
        confirmation = db.Column(db.String(1000), nullable=False)
        attachment_confirmation = db.Column(db.String(1000))
        attached_at = db.Column(db.String(40))
        attached_by = db.Column(db.String(50))

    registry[key] = (VehicleInspectionPlan, VehicleInspectionPlanEvent, VehicleInspectionExecution, VehicleInspectionExecutionEvidence,)
    return registry[key]
