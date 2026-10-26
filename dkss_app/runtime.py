from flask import current_app as app
from .extensions import db
from .vehicle_inspection_plans_models import get_models
VehicleInspectionPlan, VehicleInspectionPlanEvent, _, _ = get_models(db)
