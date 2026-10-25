"""Model registration, independently cached for each SQLAlchemy extension."""
from datetime import datetime
from zoneinfo import ZoneInfo

def get_models(db):
    registry = getattr(db, "_dkss_model_registry", None)
    if registry is None:
        registry = db._dkss_model_registry = {}
    key = 'vehicle_inspection_alerts.py'
    if key in registry:
        return registry[key]
    class InspectionPlanAlertDelivery(db.Model):
        __table_args__ = (db.UniqueConstraint('company_code', 'plan_id', 'revision', 'phase', 'bucket', 'target_username', name='uq_inspection_alert_delivery'),)
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        plan_id = db.Column(db.Integer, db.ForeignKey('vehicle_inspection_plan.id'), nullable=False, index=True)
        notification_id = db.Column(db.Integer, db.ForeignKey('notification.id'), nullable=False, index=True)
        target_username = db.Column(db.String(50), nullable=False)
        office = db.Column(db.String(100), nullable=False)
        revision = db.Column(db.String(64), nullable=False)
        phase = db.Column(db.String(30), nullable=False)
        bucket = db.Column(db.Integer, nullable=False)
        sent_day = db.Column(db.String(10), nullable=False)
        ended_status = db.Column(db.String(16))

    class InspectionPlanAlertRun(db.Model):
        company_code = db.Column(db.String(50), primary_key=True)
        checked_at = db.Column(db.String(40), nullable=False)
        local_day = db.Column(db.String(10), nullable=False)
        report_json = db.Column(db.Text, nullable=False, default='{}')
        input_signature = db.Column(db.String(64), nullable=False)

    class InspectionExpiryAlertDelivery(db.Model):
        __table_args__ = (db.UniqueConstraint('company_code', 'vehicle_record_id', 'expiry_date', 'office', 'phase', 'bucket', 'target_username', name='uq_inspection_expiry_alert_delivery'),)
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        vehicle_record_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False, index=True)
        expiry_date = db.Column(db.String(10), nullable=False)
        notification_id = db.Column(db.Integer, db.ForeignKey('notification.id'), nullable=False, index=True)
        target_username = db.Column(db.String(50), nullable=False)
        office = db.Column(db.String(100), nullable=False)
        phase = db.Column(db.String(30), nullable=False)
        bucket = db.Column(db.Integer, nullable=False)
        sent_day = db.Column(db.String(10), nullable=False)
        ended_status = db.Column(db.String(16))

    registry[key] = (InspectionPlanAlertDelivery, InspectionPlanAlertRun, InspectionExpiryAlertDelivery,)
    return registry[key]
