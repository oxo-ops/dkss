"""Registration only. Business functions have no import-time decorators."""
from . import access, analysis, analysis_feedback, audit, auth, checklist_common, checklist_notifications, checklists, companies, dashboard, database, directory_api, http, knowledge, maintenance, master_readers, masters, news, notifications, notifications_delivery, patrols, safety, safety_permissions, serialization, storage, vehicle_costs, vehicle_documents, vehicle_imports, vehicle_karte, vehicle_master, vehicle_operations, vehicle_pending, vehicle_readers
from .common import request, CSRFError, UploadValidationError, HTTPException
from .extensions import limiter


def register_core_routes(app):
    view = http.file_too_large
    view = app.errorhandler(413)(view)
    view = http.handle_csrf_error
    view = app.errorhandler(CSRFError)(view)
    view = http.redirect_form_errors
    view = app.after_request(view)
    view = http.handle_upload_validation_error
    view = app.errorhandler(UploadValidationError)(view)
    view = http.handle_http_error
    view = app.errorhandler(HTTPException)(view)
    view = http.handle_unexpected_error
    view = app.errorhandler(Exception)(view)
    view = knowledge.maintenance_knowledge_master
    view = app.route("/master/maintenance-knowledge", methods=["GET", "POST"])(view)
    view = knowledge.maintenance_knowledge_detail
    view = app.route("/vehicle/maintenance-knowledge/<int:knowledge_id>")(view)
    view = analysis_feedback.save_vehicle_analysis_feedback
    view = app.route("/vehicle/karte/<int:vehicle_record_id>/analysis/feedback", methods=["POST"])(view)
    view = analysis_feedback.save_vehicle_analysis_evaluation
    view = app.route("/vehicle/karte/<int:vehicle_record_id>/analysis/evaluation", methods=["POST"])(view)
    view = storage.uploaded_file
    view = app.route("/files/<folder>/<filename>")(view)
    view = storage.s3_uploads_file
    view = app.route("/static/uploads/<path:filename>")(view)
    view = storage.s3_manual_file
    view = app.route("/static/manuals/<path:filename>")(view)
    view = storage.add_security_headers
    view = app.after_request(view)
    view = access.require_login
    view = app.before_request(view)
    view = master_readers.save_master_display_order
    view = limiter.limit("60 per minute")(view)
    view = app.route("/master/<kind>/order", methods=["POST"])(view)
    view = master_readers.inject_master_office_order
    view = app.context_processor(view)
    view = notifications_delivery.service_worker
    view = app.route("/service-worker.js")(view)
    view = notifications_delivery.push_vapid_public_key
    view = app.route("/api/push/vapid-public-key")(view)
    view = notifications_delivery.push_subscribe
    view = app.route("/api/push/subscribe", methods=["POST"])(view)
    view = notifications_delivery.push_unsubscribe
    view = app.route("/api/push/unsubscribe", methods=["POST"])(view)
    view = notifications_delivery.push_test
    view = app.route("/api/push/test", methods=["POST"])(view)
    view = vehicle_readers.vehicle_icon
    view = app.template_filter("vehicle_icon")(view)
    view = auth.login_csrf_token
    view = app.route("/login/csrf-token", methods=["GET"])(view)
    view = auth.login
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/login", methods=["GET", "POST"])(view)
    view = auth.mfa
    view = limiter.limit("5 per minute", methods=["POST"])(view)
    view = app.route("/mfa", methods=["GET", "POST"])(view)
    view = news.itc_new_news
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/itc/news/new", methods=["GET", "POST"])(view)
    view = news.itc_edit_news
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/itc/news/<int:index>/edit", methods=["GET", "POST"])(view)
    view = news.itc_delete_news
    view = limiter.limit("10 per minute")(view)
    view = app.route("/itc/news/<int:index>/delete", methods=["POST"])(view)
    view = notifications.inject_notification_count
    view = app.context_processor(view)
    view = notifications.notification_recent
    view = app.route("/api/notifications/recent")(view)
    view = notifications.notification_unread_count
    view = app.route("/api/notifications/unread-count")(view)
    view = auth.register
    view = limiter.limit("5 per minute", methods=["POST"])(view)
    view = app.route("/register", methods=["GET", "POST"])(view)
    view = auth.logout
    view = app.route("/logout", methods=["POST"])(view)
    view = auth.settings
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/settings", methods=["GET", "POST"])(view)
    view = auth.verify_email_change
    view = limiter.limit("5 per minute", methods=["POST"])(view)
    view = app.route(
        "/settings/email/verify",
        methods=["GET", "POST"]
    )(view)
    view = directory_api.news_targets
    view = app.route("/api/news-targets")(view)
    view = directory_api.approval_candidates
    view = app.route("/api/approval-candidates")(view)
    view = directory_api.mention_users
    view = app.route("/api/mention-users")(view)
    view = directory_api.search_vehicles
    view = app.route("/api/vehicles")(view)
    view = dashboard.save_dashboard_settings
    view = limiter.limit("20 per minute")(view)
    view = app.route("/dashboard/settings", methods=["POST"])(view)
    view = dashboard.dashboard
    view = app.route("/")(view)
    view = notifications.open_notification_target
    view = app.route("/notifications/<int:index>/open")(view)
    view = notifications.mark_notification_read_after_target_display
    view = app.after_request(view)
    view = notifications.format_notification_datetime
    view = app.template_filter("notification_datetime")(view)
    view = notifications.notifications
    view = app.route("/notifications")(view)
    view = notifications.notification_detail
    view = app.route("/notifications/<int:index>")(view)
    view = notifications.mark_notification_read
    view = limiter.limit("120 per minute")(view)
    view = app.route("/api/notifications/<int:index>/read", methods=["POST"])(view)
    view = notifications.update_notification_popover_delete
    view = limiter.limit("20 per minute")(view)
    view = app.route(
        "/api/notifications/<int:index>/undo-delete",
        methods=["POST"], defaults={"undo": True}
    )(view)
    view = app.route(
        "/api/notifications/<int:index>/delete",
        methods=["POST"], defaults={"undo": False}
    )(view)
    view = notifications.delete_notification
    view = limiter.limit("20 per minute")(view)
    view = app.route("/notifications/<int:index>/delete", methods=["POST"])(view)
    view = notifications.restore_notification
    view = limiter.limit("20 per minute")(view)
    view = app.route("/notifications/<int:index>/restore", methods=["POST"])(view)
    view = notifications.bulk_notifications
    view = limiter.limit("20 per minute")(view)
    view = app.route("/notifications/bulk", methods=["POST"])(view)
    view = notifications.mark_all_notifications_read
    view = limiter.limit("20 per minute")(view)
    view = app.route("/notifications/read-all", methods=["POST"])(view)
    view = notifications.undo_notification_delete
    view = limiter.limit("20 per minute")(view)
    view = app.route("/notifications/undo-delete", methods=["POST"])(view)
    view = companies.itc_dashboard
    view = app.route("/itc")(view)
    view = companies.itc_new_company
    view = limiter.limit("5 per minute", methods=["POST"])(view)
    view = app.route("/itc/companies/new", methods=["GET", "POST"])(view)
    view = companies.itc_edit_company
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/itc/companies/<int:index>/edit", methods=["GET", "POST"])(view)
    view = safety.safety
    view = app.route("/safety")(view)
    view = safety.pointouts
    view = app.route("/pointouts")(view)
    view = safety.new_pointout
    view = limiter.limit("20 per minute", methods=["POST"])(view)
    view = app.route("/pointouts/new", methods=["GET", "POST"])(view)
    view = safety.pointout_detail
    view = app.route("/pointouts/<int:index>")(view)
    view = safety.edit_pointout
    view = limiter.limit("20 per minute", methods=["POST"])(view)
    view = app.route("/pointouts/<int:index>/edit", methods=["GET", "POST"])(view)
    view = safety.register_countermeasure
    view = limiter.limit("20 per minute")(view)
    view = app.route("/pointouts/<int:index>/countermeasure", methods=["POST"])(view)
    view = safety.approve_countermeasure
    view = limiter.limit("20 per minute")(view)
    view = app.route("/pointouts/<int:index>/approve", methods=["POST"])(view)
    view = safety.reject_countermeasure
    view = limiter.limit("20 per minute")(view)
    view = app.route("/pointouts/<int:index>/reject", methods=["POST"])(view)
    view = safety.delete_pointout
    view = limiter.limit("20 per minute")(view)
    view = app.route("/pointouts/<int:index>/delete", methods=["POST"])(view)
    view = patrols.new_vehicle_patrol
    view = limiter.limit("20 per minute", methods=["POST"])(view)
    view = app.route("/vehicle-patrols/new", methods=["GET", "POST"])(view)
    view = patrols.add_usage_vehicle
    view = limiter.limit("30 per minute")(view)
    view = app.route("/usage-vehicles/add", methods=["POST"])(view)
    view = patrols.remove_usage_vehicle
    view = limiter.limit("30 per minute")(view)
    view = app.route(
        "/usage-vehicles/remove/<int:vehicle_record_id>",
        methods=["POST"]
    )(view)
    view = patrols.vehicle_patrols
    view = app.route("/vehicle-patrols")(view)
    view = patrols.vehicle_patrol_detail
    view = app.route("/vehicle-patrols/<int:index>")(view)
    view = patrols.edit_vehicle_patrol
    view = limiter.limit("20 per minute", methods=["POST"])(view)
    view = app.route("/vehicle-patrols/<int:index>/edit", methods=["GET", "POST"])(view)
    view = patrols.delete_vehicle_patrol
    view = limiter.limit("20 per minute")(view)
    view = app.route("/vehicle-patrols/<int:index>/delete", methods=["POST"])(view)
    view = masters.vehicle_type_master
    view = app.route("/master/vehicle-types")(view)
    view = masters.license_type_master
    view = app.route("/master/license-types")(view)
    view = masters.new_license_type
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/license-types/new", methods=["GET", "POST"])(view)
    view = masters.edit_license_type
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/license-types/<int:index>/edit", methods=["GET", "POST"])(view)
    view = masters.delete_license_type
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/license-types/<int:index>/delete", methods=["POST"])(view)
    view = masters.new_vehicle_type
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicle-types/new", methods=["GET", "POST"])(view)
    view = masters.edit_vehicle_type
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicle-types/<int:index>/edit", methods=["GET", "POST"])(view)
    view = masters.delete_vehicle_type
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/vehicle-types/<int:index>/delete", methods=["POST"])(view)
    view = masters.master
    view = app.route("/master")(view)
    view = masters.office_master
    view = app.route("/master/offices")(view)
    view = masters.new_office
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/offices/new", methods=["GET", "POST"])(view)
    view = masters.edit_office
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/offices/<int:index>/edit", methods=["GET", "POST"])(view)
    view = masters.delete_office
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/offices/<int:index>/delete", methods=["POST"])(view)
    view = masters.import_delivery_places
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/delivery-places/import", methods=["GET", "POST"])(view)
    view = masters.select_delivery_place_import_column
    view = limiter.limit("10 per minute")(view)
    view = app.route(
        "/master/delivery-places/import/column-select",
        methods=["POST"]
    )(view)
    view = masters.confirm_delivery_place_import
    view = limiter.limit("10 per minute")(view)
    view = app.route(
        "/master/delivery-places/import/confirm",
        methods=["POST"]
    )(view)
    view = masters.delivery_place_master
    view = app.route("/master/delivery-places")(view)
    view = masters.new_delivery_place
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/delivery-places/new", methods=["GET", "POST"])(view)
    view = masters.edit_delivery_place
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/delivery-places/<int:index>/edit", methods=["GET", "POST"])(view)
    view = masters.delete_delivery_place
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/delivery-places/<int:index>/delete", methods=["POST"])(view)
    view = masters.patrol_content_type_master
    view = app.route("/master/patrol-content-types")(view)
    view = masters.new_patrol_content_type
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/patrol-content-types/new", methods=["GET", "POST"])(view)
    view = masters.edit_patrol_content_type
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/patrol-content-types/<int:index>/edit", methods=["GET", "POST"])(view)
    view = masters.delete_patrol_content_type
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/patrol-content-types/<int:index>/delete", methods=["POST"])(view)
    view = masters.driver_master
    view = app.route("/master/drivers")(view)
    view = masters.new_driver
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/drivers/new", methods=["GET", "POST"])(view)
    view = masters.edit_driver
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/drivers/<int:index>/edit", methods=["GET", "POST"])(view)
    view = masters.delete_driver
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/drivers/<int:index>/delete", methods=["POST"])(view)
    view = vehicle_imports.vehicle_invoice_import_candidates
    view = app.route("/vehicle/document-import/<batch_id>/<draft_id>/<int:record_index>/maintenance-candidates")(view)
    from . import document_import_routes
    app.add_url_rule('/vehicle/data-import/jobs', 'enqueue_documents', document_import_routes.enqueue_documents, methods=['POST'])
    app.add_url_rule('/vehicle/data-import/jobs/<batch_id>', 'document_import_job', document_import_routes.document_import_job)
    app.add_url_rule('/vehicle/data-import/jobs/<batch_id>/status', 'document_import_status', document_import_routes.document_import_status)
    app.add_url_rule('/vehicle/data-import/jobs/<batch_id>/retry', 'retry_document_import', document_import_routes.retry_document_import, methods=['POST'])
    view = vehicle_imports.vehicle_data_import_progress
    view = app.route("/vehicle/data-import/progress", methods=["POST"])(view)
    view = vehicle_imports.vehicle_data_import
    view = app.route(
        "/vehicle/data-import",
        methods=["GET", "POST"]
    )(view)
    view = vehicle_imports.vehicle_document_import_confirm
    view = limiter.limit("10 per minute")(view)
    view = app.route(
        "/vehicle/data-import/<batch_id>/confirm",
        methods=["POST"]
    )(view)
    view = vehicle_imports.vehicle_driving_report_source
    view = app.route("/vehicle/driving-reports/<int:record_id>/source")(view)
    view = vehicle_imports.vehicle_periodic_inspection_source
    view = app.route(
        "/vehicle/periodic-inspections/<int:record_id>/source"
    )(view)
    view = vehicle_imports.vehicle_document_import_source
    view = app.route(
        "/vehicle/data-import/files/<draft_id>"
    )(view)
    view = vehicle_imports.vehicle_document_import_preview
    view = app.route(
        "/vehicle/data-import/<batch_id>/preview"
    )(view)
    view = vehicle_imports.vehicle_operation_import
    view = app.route(
        "/vehicle/operation-import",
        methods=["GET", "POST"]
    )(view)
    view = vehicle_imports.vehicle_operation_import_add_vehicle
    view = limiter.limit("10 per minute")(view)
    view = app.route(
        "/api/vehicle/operation-import/<draft_id>/vehicles",
        methods=["POST"]
    )(view)
    view = vehicle_imports.vehicle_operation_import_preview
    view = app.route("/vehicle/operation-import/<draft_id>/preview")(view)
    view = vehicle_imports.vehicle_operation_import_confirm
    view = limiter.limit("10 per minute")(view)
    view = app.route(
        "/vehicle/operation-import/<draft_id>/confirm",
        methods=["POST"]
    )(view)
    view = vehicle_imports.vehicle_operation_import_result
    view = app.route("/vehicle/operation-import/<draft_id>/result")(view)
    view = vehicle_karte.vehicle_karte
    view = app.route("/vehicle/karte/<int:vehicle_record_id>")(view)
    view = app.route("/master/vehicles/<int:vehicle_record_id>/karte")(view)
    view = vehicle_karte.vehicle_karte_note
    view = app.route("/vehicle/karte/<int:vehicle_record_id>/note", methods=["POST"])(view)
    view = vehicle_karte.vehicle_karte_document_source
    view = app.route(
        "/vehicle/karte/<int:vehicle_record_id>/documents/<draft_id>/source"
    )(view)
    view = vehicle_karte.vehicle_karte_operation_source
    view = app.route(
        "/vehicle/karte/<int:vehicle_record_id>/operation-files/<draft_id>"
    )(view)
    view = vehicle_karte.vehicle_karte_documents
    view = app.route("/vehicle/karte/<int:vehicle_record_id>/documents")(view)
    view = vehicle_karte.vehicle_karte_inspections
    view = app.route("/vehicle/karte/<int:vehicle_record_id>/inspections")(view)
    view = vehicle_karte.vehicle_karte_parts
    view = app.route("/vehicle/karte/<int:vehicle_record_id>/parts")(view)
    view = vehicle_karte.vehicle_karte_maintenance_form
    view = limiter.limit("20 per minute", methods=["POST"])(view)
    view = app.route(
        "/vehicle/karte/<int:vehicle_record_id>/maintenance/<int:record_id>/edit",
        methods=["GET", "POST"],
    )(view)
    view = app.route(
        "/vehicle/karte/<int:vehicle_record_id>/maintenance/new",
        defaults={"record_id": None},
        methods=["GET", "POST"],
    )(view)
    view = vehicle_karte.vehicle_karte_maintenance
    view = app.route(
        "/vehicle/karte/<int:vehicle_record_id>/maintenance/<int:record_id>"
    )(view)
    view = app.route(
        "/vehicle/karte/<int:vehicle_record_id>/maintenance",
        defaults={"record_id": None},
    )(view)
    view = vehicle_karte.vehicle_karte_history
    view = app.route("/vehicle/karte/<int:vehicle_record_id>/history")(view)
    view = app.route("/master/vehicles/<int:vehicle_record_id>/karte/history")(view)
    view = analysis.vehicle_karte_analysis_result
    view = app.route("/vehicle/karte/<int:vehicle_record_id>/analysis/result")(view)
    view = analysis.vehicle_karte_analysis_worker
    view = app.cli.command("vehicle-karte-analysis-worker")(view)
    view = analysis.vehicle_karte_analysis_tick
    view = app.cli.command("vehicle-karte-analysis-tick")(view)
    view = analysis.vehicle_karte_analysis
    view = app.route(
        "/vehicle/karte/<int:vehicle_record_id>/analysis",
        methods=["GET"],
    )(view)
    view = vehicle_costs.vehicle_karte_costs
    view = app.route("/vehicle/karte/<int:vehicle_record_id>/costs")(view)
    view = vehicle_karte.inject_vehicle_karte_choices
    view = app.context_processor(view)
    view = vehicle_karte.vehicle_karte_list
    view = app.route("/vehicle/karte")(view)
    view = vehicle_documents.vehicle_maintenance_document_duplicate
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicles/invoice-reviews/<document_id>/duplicate", methods=["POST"])(view)
    view = vehicle_documents.vehicle_maintenance_document_initial_cost
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicles/invoice-reviews/<document_id>/initial-cost", methods=["POST"])(view)
    view = vehicle_documents.vehicle_maintenance_document_correction
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicles/invoice-reviews/<document_id>/correction", methods=["POST"])(view)
    view = vehicle_documents.vehicle_maintenance_document_additional_cost
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicles/invoice-reviews/<document_id>/additional-cost", methods=["POST"])(view)
    view = vehicle_documents.vehicle_maintenance_document_parts
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicles/invoice-reviews/<document_id>/parts", methods=["POST"])(view)
    view = vehicle_documents.vehicle_maintenance_document_reviews
    view = app.route("/master/vehicles/invoice-reviews")(view)
    view = vehicle_pending.vehicle_master
    view = app.route("/master/vehicles")(view)
    view = vehicle_pending.vehicle_import_pending_review
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route(
        "/master/vehicles/pending/<pending_id>", methods=["GET", "POST"]
    )(view)
    view = vehicle_pending.vehicle_import_pending_operation_source
    view = app.route("/master/vehicles/pending/<pending_id>/sources/<draft_id>")(view)
    view = vehicle_pending.vehicle_import_pending_document_source
    view = app.route("/master/vehicles/pending/<pending_id>/document-sources/<draft_id>")(view)
    view = vehicle_pending.register_vehicle_import_master
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicles/import/master", methods=["POST"])(view)
    view = vehicle_master.import_vehicles
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicles/import", methods=["GET", "POST"])(view)
    view = vehicle_master.confirm_vehicle_import
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/vehicles/import/confirm", methods=["POST"])(view)
    view = vehicle_master.extract_vehicle_certificate_route
    view = limiter.limit("5 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicles/certificate/extract", methods=["POST"])(view)
    view = vehicle_master.vehicle_certificate_register
    view = app.route("/master/vehicles/certificate")(view)
    view = vehicle_master.vehicle_registration_method
    view = app.route("/master/vehicles/register")(view)
    view = vehicle_master.new_vehicle
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicles/new", methods=["GET", "POST"])(view)
    view = vehicle_master.edit_vehicle
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/vehicles/<int:index>/edit", methods=["GET", "POST"])(view)
    view = vehicle_master.toggle_vehicle_inactive
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/vehicles/<int:index>/inactive", methods=["POST"])(view)
    view = vehicle_master.bulk_delete_vehicles
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/vehicles/bulk-delete", methods=["POST"])(view)
    view = vehicle_master.bulk_inactive_vehicles
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/vehicles/bulk-inactive", methods=["POST"])(view)
    view = vehicle_master.bulk_active_vehicles
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/vehicles/bulk-active", methods=["POST"])(view)
    view = vehicle_master.delete_vehicle
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/vehicles/<int:index>/delete", methods=["POST"])(view)
    view = masters.manual_master
    view = app.route("/master/manuals")(view)
    view = masters.new_manual
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/manuals/new", methods=["GET", "POST"])(view)
    view = masters.edit_manual
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/manuals/<int:index>/edit", methods=["GET", "POST"])(view)
    view = masters.delete_manual
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/manuals/<int:index>/delete", methods=["POST"])(view)
    view = checklists.checklist_master
    view = app.route("/master/checklists")(view)
    view = checklists.new_checklist
    view = limiter.limit("10 per minute", methods=["POST"])(view)
    view = app.route("/master/checklists/new", methods=["GET", "POST"])(view)
    view = checklists.safety_checklists
    view = app.route("/safety/checklists")(view)
    view = checklists.safety_checklist_results
    view = app.route("/safety/checklists/<int:index>")(view)
    view = checklists.checklist_result_detail
    view = app.route("/safety/checklist-results/<int:result_index>")(view)
    view = checklists.export_checklist_result_excel
    view = app.route("/safety/checklist-results/<int:result_index>/excel")(view)
    view = checklists.edit_checklist_result
    view = limiter.limit("20 per minute", methods=["POST"])(view)
    view = app.route("/safety/checklist-results/<int:result_index>/edit", methods=["GET", "POST"])(view)
    view = checklists.delete_checklist_result
    view = limiter.limit("20 per minute")(view)
    view = app.route("/safety/checklist-results/<int:result_index>/delete", methods=["POST"])(view)
    view = checklists.vehicle_daily_inspection_entry
    view = app.route("/vehicle/daily-inspections")(view)
    view = checklists.vehicle_checklists
    view = app.route("/vehicle/checklists")(view)
    view = checklists.vehicle_checklist_results
    view = app.route("/vehicle/checklists/<int:index>")(view)
    view = checklists.save_vehicle_checklist_reminder_notify_users
    view = limiter.limit("10 per minute")(view)
    view = app.route(
        "/vehicle/checklists/<int:checklist_index>/reminder-notify-users",
        methods=["POST"]
    )(view)
    view = checklists.test_vehicle_checklist_reminders
    view = limiter.limit("5 per minute")(view)
    view = app.route(
        "/vehicle/checklist-reminders/test",
        methods=["POST"]
    )(view)
    view = checklists.test_email_notification
    view = limiter.limit("5 per minute")(view)
    view = app.route(
        "/notifications/email-test",
        methods=["POST"]
    )(view)
    view = checklists.save_vehicle_inspection_repair
    view = limiter.limit("20 per minute")(view)
    view = app.route(
        "/vehicle/checklist-results/<int:result_index>/defects/<int:defect_no>/repair",
        methods=["POST"]
    )(view)
    view = checklists.save_vehicle_operation_judgment
    view = limiter.limit("20 per minute")(view)
    view = app.route(
        "/vehicle/checklist-results/<int:result_index>/operation-judgment",
        methods=["POST"]
    )(view)
    view = checklists.approve_vehicle_checklist_result
    view = limiter.limit("20 per minute")(view)
    view = app.route(
        "/vehicle/checklist-results/<int:result_index>/approve/<int:approval_index>",
        methods=["POST"]
    )(view)
    view = checklists.reject_vehicle_checklist_result
    view = limiter.limit("20 per minute")(view)
    view = app.route(
        "/vehicle/checklist-results/<int:result_index>/reject",
        methods=["POST"]
    )(view)
    view = checklists.export_vehicle_checklist_result_excel
    view = app.route("/vehicle/checklist-results/<int:result_index>/excel")(view)
    view = checklists.save_vehicle_checklist_one
    view = limiter.limit("20 per minute")(view)
    view = app.route("/vehicle/checklists/<int:index>/save-one", methods=["POST"])(view)
    view = checklists.save_vehicle_checklist_detail
    view = limiter.limit("20 per minute")(view)
    view = app.route("/vehicle/checklists/<int:index>/save-detail", methods=["POST"])(view)
    view = checklists.complete_vehicle_checklist
    view = limiter.limit("20 per minute")(view)
    view = app.route("/vehicle/checklists/<int:index>/complete", methods=["POST"])(view)
    view = checklists.new_vehicle_checklist_result
    view = limiter.limit("20 per minute", methods=["POST"])(view)
    view = app.route("/vehicle/checklists/<int:index>/new", methods=["GET", "POST"])(view)
    view = checklists.new_safety_checklist_result
    view = limiter.limit("20 per minute", methods=["POST"])(view)
    view = app.route("/safety/checklists/<int:index>/new", methods=["GET", "POST"])(view)
    view = checklists.edit_checklist
    view = limiter.limit(
        "10 per minute",
        methods=["POST"],
        deduct_when=lambda response: (
            request.headers.get("X-DKSS-Validation-Only") != "1"
        )
    )(view)
    view = app.route("/master/checklists/<int:index>/edit", methods=["GET", "POST"])(view)
    view = checklists.duplicate_checklist
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/checklists/<int:index>/duplicate", methods=["POST"])(view)
    view = checklists.toggle_checklist_active
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/checklists/<int:index>/toggle-active", methods=["POST"])(view)
    view = checklists.delete_checklist
    view = limiter.limit("10 per minute")(view)
    view = app.route("/master/checklists/<int:index>/delete", methods=["POST"])(view)
    view = checklists.approve_checklist_result
    view = limiter.limit("20 per minute")(view)
    view = app.route(
        "/safety/checklist-results/<int:result_index>/approve/<int:approval_index>",
        methods=["POST"]
    )(view)
    view = checklists.reject_checklist_result
    view = limiter.limit("20 per minute")(view)
    view = app.route("/safety/checklist-results/<int:result_index>/reject", methods=["POST"])(view)
