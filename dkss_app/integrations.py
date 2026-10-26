"""Wire existing integrations with explicit dependencies for each application."""
from maintenance_knowledge_import import register_knowledge_import
from public_maintenance_knowledge import register_public_knowledge
from vehicle_inspection_plans import register_inspection_plans
from vehicle_inspection_alerts import register_inspection_alerts
from vehicle_periodic_followups import register_periodic_followups
from vehicle_document_deletion import register_document_deletion
from .extensions import db
from . import common, models, analysis, maintenance, audit, access, vehicle_readers, vehicle_imports, http, serialization
from driving_report_management import register_driving_reports


def register_integrations(app):
    from .vehicle_couplings import register_vehicle_couplings
    register_vehicle_couplings(app)
    state = app.extensions["dkss"]
    state["knowledge_import_link"] = register_knowledge_import(
        app, db, models.VehicleMaintenanceKnowledge, common.prepare_maintenance_invoice_pdf)
    state["public_knowledge_tick"] = register_public_knowledge(
        app, db, models.Vehicle, models.Company, models.VehicleMaintenanceKnowledge)
    plan, event, service = register_inspection_plans(
        app, db, models.Vehicle, models.VehiclePeriodicInspectionRecord, models.Company,
        models.User, models.Office, models.VehicleDocumentImportDraft,
        Maintenance=models.VehicleMaintenanceRecord)
    state.update(VehicleInspectionPlan=plan, VehicleInspectionPlanEvent=event, inspection_plans=service)
    state["inspection_alerts"] = register_inspection_alerts(
        app, db, plan, event, service.Execution, models.VehiclePeriodicInspectionRecord,
        models.Vehicle, models.Company, models.User, models.Notification)
    state["periodic_followups"] = register_periodic_followups(
        app, db, models.VehiclePeriodicInspectionRecord, models.Vehicle, models.Company,
        models.User, models.VehicleMaintenanceRecord, models.Notification,
        maintenance.add_vehicle_maintenance_record_event, analysis.get_vehicle_karte_analysis_job_data)
    register_document_deletion(app, db, {
        'Vehicle': models.Vehicle,
        'VehicleDocumentImportDraft': models.VehicleDocumentImportDraft,
        'VehicleMaintenanceDocument': models.VehicleMaintenanceDocument,
        'VehicleMaintenanceRecord': models.VehicleMaintenanceRecord,
        'VehicleMaintenanceRecordEvent': models.VehicleMaintenanceRecordEvent,
        'VehiclePartReplacement': models.VehiclePartReplacement,
        'VehiclePartReplacementSource': models.VehiclePartReplacementSource,
        'VehiclePeriodicInspectionRecord': models.VehiclePeriodicInspectionRecord,
        'VehicleDrivingReportRecord': models.VehicleDrivingReportRecord,
        'VehicleImportPendingRecord': models.VehicleImportPendingRecord,
        'VehicleAnalysisFeedback': models.VehicleAnalysisFeedback,
        'VehicleKarteAnalysis': models.VehicleKarteAnalysis,
        'get_vehicle_karte_analysis_job_data': analysis.get_vehicle_karte_analysis_job_data,
        'queue_vehicle_karte_analysis': analysis.queue_vehicle_karte_analysis,
        'add_audit_log': audit.add_audit_log,
    })




    state['driving_report_service'] = register_driving_reports(app, db, {
        'VehicleDrivingReportRecord': models.VehicleDrivingReportRecord,
        'VehicleOperationRecord': models.VehicleOperationRecord,
        'Vehicle': models.Vehicle,
        'VehicleDocumentImportDraft': models.VehicleDocumentImportDraft,
        'User': models.User,
        'Notification': models.Notification,
        'require_master_admin': lambda: access.require_master_admin(),
        'vehicle_number': vehicle_readers.vehicle_number,
        'validate_vehicle_document_record': vehicle_imports.validate_vehicle_document_record,
        'return_form_errors': http.return_form_errors,
        'safe_json_dict': serialization.safe_json_dict,
    })
