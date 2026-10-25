"""Model registration, independently cached for each SQLAlchemy extension."""
from datetime import datetime
from zoneinfo import ZoneInfo

def get_models(db):
    registry = getattr(db, "_dkss_model_registry", None)
    if registry is None:
        registry = db._dkss_model_registry = {}
    key = 'vehicle_periodic_followups.py'
    if key in registry:
        return registry[key]
    class PeriodicInspectionProposal(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        inspection_record_id = db.Column(db.Integer, db.ForeignKey('vehicle_periodic_inspection_record.id'), nullable=False)
        input_hash = db.Column(db.String(64), nullable=False)
        run_token = db.Column(db.String(36), nullable=False)
        status = db.Column(db.String(20), nullable=False)
        result_json = db.Column(db.Text, nullable=False, default='{}')
        error = db.Column(db.String(40))
        updated_at = db.Column(db.String(40), nullable=False)
        __table_args__ = (db.UniqueConstraint('company_code', 'inspection_record_id', name='uq_periodic_proposal_record'),)

    class PeriodicInspectionIssue(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        vehicle_record_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False, index=True)
        inspection_record_id = db.Column(db.Integer, db.ForeignKey('vehicle_periodic_inspection_record.id'), nullable=False, index=True)
        item_key = db.Column(db.String(30), nullable=False)
        evidence_json = db.Column(db.Text, nullable=False)
        description = db.Column(db.Text, nullable=False)
        status = db.Column(db.String(30), nullable=False, default='対応待ち')
        maintenance_record_id = db.Column(db.Integer, db.ForeignKey('vehicle_maintenance_record.id'), unique=True)
        version = db.Column(db.Integer, nullable=False, default=1)
        created_by = db.Column(db.String(50), nullable=False)
        created_at = db.Column(db.String(40), nullable=False)
        __table_args__ = (db.UniqueConstraint('company_code', 'inspection_record_id', 'item_key', name='uq_periodic_issue_item'),)

    class PeriodicInspectionIssueEvent(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        issue_id = db.Column(db.Integer, db.ForeignKey('periodic_inspection_issue.id'), nullable=False, index=True)
        action = db.Column(db.String(30), nullable=False)
        actor = db.Column(db.String(50), nullable=False)
        performed_date = db.Column(db.String(20))
        note = db.Column(db.Text, nullable=False)
        maintenance_record_id = db.Column(db.Integer, db.ForeignKey('vehicle_maintenance_record.id'))
        created_at = db.Column(db.String(40), nullable=False)
        notification_ids_json = db.Column(db.Text, nullable=False, default='[]')

    registry[key] = (PeriodicInspectionProposal, PeriodicInspectionIssue, PeriodicInspectionIssueEvent,)
    return registry[key]
