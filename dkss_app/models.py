"""Core table definitions. No app creation, connections, DDL or data writes."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy.orm import synonym
from zoneinfo import ZoneInfo
from .extensions import db

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    company_name = db.Column(
        db.String(100),
        nullable=False
    )

    vehicle_limit = db.Column(
        db.Integer,
        default=0
    )

    active = db.Column(
        db.Boolean,
        default=True
    )


class CompanyUsageSummary(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    user_count = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    vehicle_count = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    login_count = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    checklist_result_count = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    last_used_at = db.Column(
        db.String(20),
        nullable=True
    )

    updated_at = db.Column(
        db.String(20),
        nullable=True
    )


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    username = db.Column(
        db.String(50),
        nullable=False
    )

    password = db.Column(
        db.String(255),
        nullable=False
    )

    password_history_json = db.Column(
        db.Text,
        default="[]",
        nullable=False
    )

    password_changed_at = db.Column(
        db.String(20),
        nullable=True
    )

    last_login_at = db.Column(
        db.String(20),
        nullable=True
    )

    failed_login_count = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    login_locked = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    last_name = db.Column(
        db.String(100),
        nullable=False
    )

    first_name = db.Column(
        db.String(100),
        nullable=True
    )

    role = db.Column(
        db.String(20),
        default="user"
    )

    office = db.Column(
        db.String(100)
    )

    dashboard_settings_json = db.Column(
        db.Text,
        default="{}"
    )

    timezone = db.Column(
        db.String(100),
        default="Asia/Tokyo",
        nullable=False
    )

    email_address = db.Column(
        db.String(255)
    )

    profile_image = db.Column(
        db.String(255),
        nullable=True
    )

    email_notify_enabled = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    mfa_code_hash = db.Column(
        db.String(255),
        nullable=True
    )

    mfa_code_expires_at = db.Column(
        db.String(20),
        nullable=True
    )

    mfa_code_sent_at = db.Column(
        db.String(20),
        nullable=True
    )

    pending_email_address = db.Column(
        db.String(255),
        nullable=True
    )

    email_change_code_hash = db.Column(
        db.String(255),
        nullable=True
    )

    email_change_code_expires_at = db.Column(
        db.String(20),
        nullable=True
    )


class Vehicle(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "company_code",
            "chassis_number",
            name="uq_vehicle_company_chassis_number"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)

    # 車番・ナンバー
    plate_area = db.Column(db.String(50))
    plate_class = db.Column(db.String(50))
    plate_kana = db.Column(db.String(10))
    plate_number = db.Column(db.String(50))

    # 車両台帳情報
    chassis_number = db.Column(
        db.String(100),
        nullable=True
    )
    model_code = db.Column(db.String(100))
    engine_code = db.Column(db.String(100), nullable=True)
    first_registration_date = db.Column(db.String(20))
    manufacturer = db.Column(db.String(100))
    body_type = db.Column(db.String(100))

    gross_vehicle_weight = db.Column(db.Integer)
    max_payload = db.Column(db.Integer)

    # 既存項目
    type = db.Column(db.String(100))
    office = db.Column(db.String(100))
    inspection_expiry = db.Column(db.String(20))

    # 廃車・登録外になってもデータ自体は残す
    deleted = db.Column(
        db.Boolean,
        default=False
    )


class VehicleCoupling(db.Model):
    """Registered tractor/trailer combinations, independent of live coupling."""
    __table_args__ = (
        db.UniqueConstraint("company_code", "towing_vehicle_id", "trailer_vehicle_id",
                            name="uq_vehicle_coupling_pair"),
        db.CheckConstraint("towing_vehicle_id <> trailer_vehicle_id",
                           name="ck_vehicle_coupling_distinct"),
        db.CheckConstraint("kind IN ('semi', 'full')", name="ck_vehicle_coupling_kind"),
        db.Index("ix_vehicle_coupling_towing", "company_code", "towing_vehicle_id"),
        db.Index("ix_vehicle_coupling_trailer", "company_code", "trailer_vehicle_id"),
        {"sqlite_autoincrement": True},
    )
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=False)
    towing_vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)
    trailer_vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.String(30), nullable=False)
    created_by_username = db.Column(db.String(50), nullable=False)


class VehicleKarteNote(db.Model):
    __table_args__ = (db.UniqueConstraint("company_code", "vehicle_record_id"),)
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=False)
    vehicle_record_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)
    content = db.Column(db.Text, nullable=False, default="")
    version = db.Column(db.Integer, nullable=False, default=1)
    updated_by_username = db.Column(db.String(50))
    updated_at = db.Column(db.String(30))


class VehicleType(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)


class VehicleTypeImportMapping(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    excel_value = db.Column(
        db.String(100),
        nullable=False
    )

    vehicle_type_name = db.Column(
        db.String(100),
        nullable=False
    )


class LicenseType(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)


class DrivingReportReader(db.Model):
    __table_args__ = (db.Index('ix_driving_reader_company_user', 'company_code', 'user_id'),)
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=False, index=True)
    report_id = db.Column(db.Integer, db.ForeignKey('vehicle_driving_report_record.id', ondelete='CASCADE'), nullable=False, unique=True)
    username = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    identity_hash = db.Column(db.String(64), nullable=False)
    confirmed_by = db.Column(db.String(50), nullable=False)
    confirmed_at = db.Column(db.String(40), nullable=False)


class DrivingReportReflection(db.Model):
    """Persisted results are addressed by the current authorized input fingerprint."""
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=False, index=True)
    cache_key = db.Column(db.String(64), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    result_json = db.Column(db.Text, nullable=False, default='{}')
    created_at = db.Column(db.String(40), nullable=False)
    updated_at = db.Column(db.String(40), nullable=False)


class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    employee_id = db.Column(db.String(50), nullable=False)

    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50))
    office = db.Column(db.String(100))
    safe_start_date = db.Column(db.String(20))

    vehicles_json = db.Column(db.Text, default="[]")
    licenses_json = db.Column(db.Text, default="[]")


class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=True
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )
    message = db.Column(db.Text)
    files_json = db.Column(db.Text, default="[]")

    target_type = db.Column(db.String(50))
    target_value = db.Column(db.String(100))

    created_at = db.Column(db.String(20))


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50))

    target_user = db.Column(db.String(100), nullable=False)
    target_username = db.Column(db.String(50))
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    link = db.Column(db.String(200))
    files_json = db.Column(db.Text, default="[]")

    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.String(20))
    deleted_at = db.Column(db.DateTime, nullable=True)
    workflow_context_json = db.Column(
        db.Text,
        default="{}"
    )


class PushSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    username = db.Column(
        db.String(50),
        nullable=False
    )

    endpoint = db.Column(
        db.Text,
        nullable=False,
        unique=True
    )

    p256dh = db.Column(
        db.Text,
        nullable=False
    )

    auth = db.Column(
        db.Text,
        nullable=False
    )

    created_at = db.Column(
        db.String(20),
        nullable=False
    )


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    username = db.Column(
        db.String(100)
    )

    action = db.Column(
        db.String(100),
        nullable=False
    )

    target_type = db.Column(
        db.String(100)
    )

    target_id = db.Column(
        db.String(100)
    )

    detail = db.Column(
        db.Text
    )

    ip_address = db.Column(
        db.String(100)
    )

    created_at = db.Column(
        db.String(20),
        nullable=False
    )


class Office(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)


class DeliveryPlace(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)


class MasterDisplayOrder(db.Model):
    """Company-wide order by stable master IDs, independent of names."""
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    ordered_ids_json = db.Column(db.Text, nullable=False, default="[]")
    version = db.Column(db.Integer, nullable=False, default=1)
    __table_args__ = (db.UniqueConstraint("company_code", "kind"),)
    __mapper_args__ = {"version_id_col": version}


class PatrolContentType(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)


class Manual(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100))
    filename = db.Column(db.String(200))


class VehiclePatrol(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)

    vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id"),
        nullable=False
    )
    occurred_date = db.Column(db.String(20))
    category = db.Column(db.String(100))
    priority = db.Column(db.String(50))
    content = db.Column(db.Text)

    cause = db.Column(db.Text)
    temporary_action = db.Column(db.Text)
    repair_content = db.Column(db.Text)

    status = db.Column(db.String(50), default="未対応")

    repair_date = db.Column(db.String(20))
    repair_person = db.Column(db.String(100))
    repair_time = db.Column(db.String(50))
    parts = db.Column(db.Text)
    cost = db.Column(db.String(50))


class VehicleDrivingReportRecord(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "source_draft_id",
            "source_record_index",
            name="uq_driving_report_source_record"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )
    vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id"),
        nullable=False,
        index=True
    )
    operation_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle_operation_record.id"),
        index=True
    )

    report_number = db.Column(db.String(100))
    operation_date = db.Column(
        db.String(20),
        nullable=False,
        index=True
    )
    mileage = db.Column(db.Numeric(14, 2))
    content = db.Column(db.Text)

    details_json = db.Column(
        db.Text,
        nullable=False,
        default="{}"
    )

    source_draft_id = db.Column(
        db.String(36),
        db.ForeignKey("vehicle_document_import_draft.id"),
        nullable=False
    )
    source_record_index = db.Column(
        db.Integer,
        nullable=False
    )

    created_by_username = db.Column(
        db.String(50),
        nullable=False
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(ZoneInfo("UTC"))
    )


class VehiclePeriodicInspectionRecord(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "source_draft_id",
            "source_record_index",
            name="uq_periodic_inspection_source_record"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )
    vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id"),
        nullable=False,
        index=True
    )

    inspection_type = db.Column(
        db.String(30),
        nullable=False
    )
    inspection_date = db.Column(
        db.String(20),
        nullable=False,
        index=True
    )
    completion_date = db.Column(db.String(20))
    next_inspection_date = db.Column(db.String(20))
    mileage = db.Column(db.Numeric(14, 2))

    inspection_company = db.Column(db.String(200))
    inspector_name = db.Column(db.String(100))
    content = db.Column(db.Text)

    details_json = db.Column(
        db.Text,
        nullable=False,
        default="{}"
    )

    source_draft_id = db.Column(
        db.String(36),
        db.ForeignKey("vehicle_document_import_draft.id"),
        nullable=False
    )
    source_record_index = db.Column(
        db.Integer,
        nullable=False
    )

    created_by_username = db.Column(
        db.String(50),
        nullable=False
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(ZoneInfo("UTC"))
    )


class VehicleDocumentSource(db.Model):
    company_code = db.Column(db.String(50), primary_key=True)
    sha256 = db.Column(db.String(64), primary_key=True)
    content = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(ZoneInfo("UTC")),
    )


class DocumentQueueSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Integer, nullable=False, default=0)
    last_company = db.Column(db.String(50), nullable=True)


class DomainSchemaRevision(db.Model):
    revision = db.Column(db.String(80), primary_key=True)
    applied_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(ZoneInfo("UTC")),
    )


class AnalysisInputEpoch(db.Model):
    company_code = db.Column(db.String(50), primary_key=True)
    bucket = db.Column(db.String(80), primary_key=True)
    revision = db.Column(db.BigInteger, nullable=False, default=0)


class AnalysisInputReadCache(db.Model):
    company_code = db.Column(db.String(50), primary_key=True)
    vehicle_record_id = db.Column(db.Integer, primary_key=True)
    context_hash = db.Column(db.String(64), nullable=False)
    input_revision = db.Column(db.BigInteger, nullable=False)
    projection_json = db.Column(db.Text, nullable=False)
    computed_at = db.Column(db.DateTime(timezone=True), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)


class VehicleDocumentImportDraft(db.Model):
    id = db.Column(db.String(36), primary_key=True)

    batch_id = db.Column(
        db.String(36),
        nullable=False,
        index=True
    )
    company_code = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )
    created_by_username = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )

    document_type = db.Column(
        db.String(30),
        nullable=False
    )
    source_filename = db.Column(
        db.String(255),
        nullable=False
    )
    _source_file = db.Column('source_file', db.LargeBinary, nullable=False)

    def _read_source_file(self):
        from .document_sources import read_source
        return read_source(self)

    def _write_source_file(self, value):
        self._shared_source = None
        self._source_file = value

    source_file = synonym('_source_file', descriptor=property(_read_source_file, _write_source_file))
    source_sha256 = db.Column(
        db.String(64),
        nullable=False,
        index=True
    )

    preview_json = db.Column(
        db.Text,
        nullable=False,
        default="{}"
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default="preview"
    )
    result_json = db.Column(
        db.Text,
        nullable=False,
        default="{}"
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(ZoneInfo("UTC"))
    )
    completed_at = db.Column(
        db.DateTime(timezone=True)
    )


class VehicleImportPending(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "company_code", "match_key",
            name="uq_vehicle_import_pending_match"
        ),
    )

    id = db.Column(db.String(36), primary_key=True)
    company_code = db.Column(
        db.String(50), nullable=False, index=True
    )
    match_key = db.Column(db.String(255), nullable=False)
    status = db.Column(
        db.String(20), nullable=False, default="pending", index=True
    )
    identity_json = db.Column(
        db.Text, nullable=False, default="{}"
    )
    resolved_vehicle_id = db.Column(
        db.Integer, db.ForeignKey("vehicle.id"), index=True
    )
    resolution_json = db.Column(
        db.Text, nullable=False, default="{}"
    )
    created_by_username = db.Column(db.String(50), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(ZoneInfo("UTC"))
    )
    resolved_at = db.Column(db.DateTime(timezone=True))


class VehicleImportPendingRecord(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "company_code", "source_kind", "record_key",
            name="uq_vehicle_import_pending_record"
        ),
    )

    id = db.Column(db.String(36), primary_key=True)
    company_code = db.Column(
        db.String(50), nullable=False, index=True
    )
    pending_id = db.Column(
        db.String(36), db.ForeignKey("vehicle_import_pending.id"),
        nullable=False, index=True
    )
    source_kind = db.Column(db.String(30), nullable=False)
    record_key = db.Column(db.String(64), nullable=False)
    operation_draft_id = db.Column(
        db.String(36), db.ForeignKey("vehicle_operation_import_draft.id"),
        index=True
    )
    document_draft_id = db.Column(
        db.String(36), db.ForeignKey("vehicle_document_import_draft.id"),
        index=True
    )
    source_record_index = db.Column(db.Integer, nullable=False)
    record_date = db.Column(db.String(30), index=True)
    payload_json = db.Column(db.Text, nullable=False, default="{}")
    status = db.Column(
        db.String(20), nullable=False, default="pending", index=True
    )
    vehicle_record_id = db.Column(
        db.Integer, db.ForeignKey("vehicle.id"), index=True
    )
    result_json = db.Column(db.Text, nullable=False, default="{}")
    created_by_username = db.Column(db.String(50), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(ZoneInfo("UTC"))
    )
    applied_at = db.Column(db.DateTime(timezone=True))


class VehicleMaintenanceDocument(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "company_code", "source_draft_id", "source_record_index",
            name="uq_maintenance_document_source"
        ),
        db.CheckConstraint(
            "(maintenance_record_id IS NOT NULL AND inspection_record_id IS NULL) "
            "OR (maintenance_record_id IS NULL AND inspection_record_id IS NOT NULL)",
            name="ck_maintenance_document_target"
        ),
        db.CheckConstraint(
            "financial_status IN ('pending','confirmed','duplicate','superseded','excluded')",
            name="ck_maintenance_document_financial_status"
        ),
        db.CheckConstraint(
            "parts_status IN ('pending','confirmed','not_applicable')",
            name="ck_maintenance_document_parts_status"
        ),
        db.CheckConstraint(
            "source_record_index >= 0",
            name="ck_maintenance_document_source_index"
        ),
    )

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_code = db.Column(db.String(50), nullable=False, index=True)
    vehicle_record_id = db.Column(
        db.Integer, db.ForeignKey("vehicle.id"), nullable=False, index=True
    )
    maintenance_record_id = db.Column(
        db.Integer, db.ForeignKey("vehicle_maintenance_record.id"), index=True
    )
    inspection_record_id = db.Column(
        db.Integer, db.ForeignKey("vehicle_periodic_inspection_record.id"), index=True
    )
    source_draft_id = db.Column(
        db.String(36), db.ForeignKey("vehicle_document_import_draft.id"),
        nullable=False, index=True
    )
    source_record_index = db.Column(db.Integer, nullable=False)
    pending_record_id = db.Column(
        db.String(36), db.ForeignKey("vehicle_import_pending_record.id"),
        unique=True
    )
    related_document_id = db.Column(
        db.String(36), db.ForeignKey("vehicle_maintenance_document.id"), index=True
    )
    payload_json = db.Column(db.Text, nullable=False, default="{}")
    decision_json = db.Column(db.Text, nullable=False, default="{}")
    financial_status = db.Column(
        db.String(20), nullable=False, default="pending", index=True
    )
    parts_status = db.Column(
        db.String(20), nullable=False, default="pending", index=True
    )
    created_by_username = db.Column(db.String(100), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(ZoneInfo("UTC"))
    )
    reviewed_by_username = db.Column(db.String(100))
    reviewed_at = db.Column(db.DateTime(timezone=True))


class VehicleOperationVehicleMapping(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "company_code",
            "source_vehicle_code",
            "source_vehicle_number",
            name="uq_operation_vehicle_mapping"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )
    source_vehicle_code = db.Column(
        db.String(100),
        nullable=False
    )
    source_vehicle_number = db.Column(
        db.String(100),
        nullable=False
    )
    vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id"),
        nullable=False,
        index=True
    )
    confirmed_by_username = db.Column(
        db.String(50),
        nullable=False
    )
    confirmed_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(ZoneInfo("UTC"))
    )


class VehicleOperationImportDraft(db.Model):
    id = db.Column(db.String(36), primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )
    created_by_username = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )

    source_filename = db.Column(
        db.String(255),
        nullable=False
    )
    source_file = db.Column(
        db.LargeBinary,
        nullable=False
    )
    selection_json = db.Column(
        db.Text,
        nullable=False,
        default="{}"
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="preview"
    )
    result_json = db.Column(
        db.Text,
        nullable=False,
        default="{}"
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(ZoneInfo("UTC"))
    )
    completed_at = db.Column(
        db.DateTime(timezone=True)
    )


class VehicleOperationRecord(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "company_code",
            "report_number",
            name="uq_vehicle_operation_company_report"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )
    vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id"),
        nullable=False,
        index=True
    )

    report_number = db.Column(
        db.String(100),
        nullable=False
    )
    operation_date = db.Column(
        db.String(20),
        nullable=False,
        index=True
    )

    source_vehicle_code = db.Column(db.String(100))
    source_vehicle_number = db.Column(db.String(100))

    departure_at = db.Column(db.String(30))
    arrival_at = db.Column(db.String(30))

    departure_meter = db.Column(db.Numeric(14, 2))
    arrival_meter = db.Column(db.Numeric(14, 2))
    distance = db.Column(db.Numeric(14, 2))

    source_row_json = db.Column(
        db.Text,
        nullable=False,
        default="{}"
    )
    source_filename = db.Column(db.String(255))

    imported_by_username = db.Column(db.String(50))
    imported_at = db.Column(db.String(30))


class VehicleMaintenanceRecord(db.Model):
    @property
    def cost_office(self):
        from .maintenance_facts import cost_office
        return cost_office(self)

    @cost_office.setter
    def cost_office(self, value):
        from .maintenance_facts import set_cost_office
        set_cost_office(self, value)

    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False,
        index=True
    )
    vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id"),
        nullable=False,
        index=True
    )

    category = db.Column(db.String(50))
    status = db.Column(db.String(50))

    entry_date = db.Column(db.String(20))
    completion_date = db.Column(db.String(20))
    mileage = db.Column(db.Numeric(14, 2))

    content = db.Column(db.Text)
    symptom = db.Column(db.Text)
    cause = db.Column(db.Text)
    temporary_action = db.Column(db.Text)
    repair_content = db.Column(db.Text)

    maintenance_company = db.Column(db.String(200))
    maintenance_person = db.Column(db.String(100))
    repair_hours = db.Column(db.Numeric(10, 2))

    invoice_number = db.Column(db.String(100))
    invoice_date = db.Column(db.String(20))
    invoice_details_json = db.Column(
        db.Text,
        nullable=False,
        default="{}",
        server_default="{}",
    )

    labor_cost = db.Column(db.Numeric(14, 2))
    parts_cost = db.Column(db.Numeric(14, 2))
    other_cost = db.Column(db.Numeric(14, 2))
    tax_amount = db.Column(db.Numeric(14, 2))
    total_cost = db.Column(db.Numeric(14, 2))

    line_items_json = db.Column(
        db.Text,
        nullable=False,
        default="[]"
    )
    files_json = db.Column(
        db.Text,
        nullable=False,
        default="[]"
    )
    notes = db.Column(db.Text)

    created_by_username = db.Column(db.String(50))
    created_at = db.Column(db.String(30))
    updated_by_username = db.Column(db.String(50))
    updated_at = db.Column(db.String(30))


class VehicleMaintenanceKnowledge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    part_name = db.Column(db.String(100), nullable=False)
    manufacturer = db.Column(db.String(100), nullable=False, default="")
    model_code = db.Column(db.String(100), nullable=False, default="")
    conditions = db.Column(db.Text, nullable=False)
    guidance = db.Column(db.Text, nullable=False)
    source_kind = db.Column(db.String(30), nullable=False)
    source_reference = db.Column(db.Text, nullable=False)
    provider = db.Column(db.String(150), nullable=False)
    valid_from = db.Column(db.String(10), nullable=False)
    valid_until = db.Column(db.String(10), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="draft")
    created_by = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.String(30), nullable=False)
    confirmed_by = db.Column(db.String(50))
    confirmed_at = db.Column(db.String(30))
    retired_by = db.Column(db.String(50))
    retired_at = db.Column(db.String(30))
    retirement_reason = db.Column(db.Text)


class VehicleAnalysisFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=False, index=True)
    vehicle_record_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False, index=True)
    proposal_key = db.Column(db.String(64), nullable=False, index=True)
    proposal_revision = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    comment = db.Column(db.Text, nullable=False, default="")
    snapshot_json = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.String(30), nullable=False)


class VehicleAnalysisEvaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=False, index=True)
    vehicle_record_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False, index=True)
    proposal_key = db.Column(db.String(64), nullable=False)
    proposal_revision = db.Column(db.String(64), nullable=False)
    verdict = db.Column(db.String(20), nullable=False)
    comment = db.Column(db.Text, nullable=False, default="")
    snapshot_json = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.String(30), nullable=False)


class VehicleKarteAnalysis(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "company_code",
            "vehicle_record_id",
            name="uq_vehicle_karte_analysis_company_vehicle",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False,
        index=True,
    )
    vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id"),
        nullable=False,
        index=True,
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="pending",
    )
    input_hash = db.Column(db.String(64))
    result_json = db.Column(
        db.Text,
        nullable=False,
        default="{}",
    )

    last_analyzed_at = db.Column(
        db.DateTime(timezone=True)
    )
    next_analysis_at = db.Column(
        db.DateTime(timezone=True),
        index=True,
    )
    request_reason = db.Column(db.String(200))

    lease_token = db.Column(db.String(36))
    lease_expires_at = db.Column(
        db.DateTime(timezone=True)
    )
    last_error = db.Column(db.String(500))


class VehicleMaintenanceRecordEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False,
        index=True,
    )
    vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id"),
        nullable=False,
        index=True,
    )
    maintenance_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle_maintenance_record.id"),
        nullable=False,
        index=True,
    )

    action = db.Column(
        db.String(50),
        nullable=False,
    )
    status_before = db.Column(db.String(50))
    status_after = db.Column(db.String(50))

    changes_json = db.Column(
        db.Text,
        nullable=False,
        default="[]",
    )
    created_by_username = db.Column(db.String(100))
    created_at = db.Column(
        db.String(30),
        nullable=False,
    )


class VehiclePartReplacement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(
        db.String(50), nullable=False, index=True
    )
    vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id"),
        nullable=False,
        index=True,
    )
    maintenance_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle_maintenance_record.id"),
        nullable=False,
        index=True,
    )
    part_name = db.Column(db.String(200), nullable=False)
    part_number = db.Column(db.String(100))
    quantity = db.Column(
        db.Numeric(14, 2), nullable=False, default=1
    )
    replacement_date = db.Column(
        db.String(20), nullable=False
    )
    mileage = db.Column(db.Numeric(14, 2))
    cost = db.Column(db.Numeric(14, 2))
    notes = db.Column(db.Text)
    created_by_username = db.Column(db.String(100))
    created_at = db.Column(db.String(30), nullable=False)
    updated_by_username = db.Column(db.String(100))
    updated_at = db.Column(db.String(30))


class VehiclePartReplacementSource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(
        db.String(50), nullable=False, index=True
    )
    maintenance_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle_maintenance_record.id"),
        nullable=False,
        index=True,
    )
    replacement_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle_part_replacement.id"),
        nullable=False,
        unique=True,
    )
    source_line_index = db.Column(
        db.Integer, nullable=False
    )
    source_line_version = db.Column(
        db.String(64), nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "maintenance_record_id",
            "source_line_index",
            name="uq_maintenance_part_source_line",
        ),
    )


class Checklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)

    name = db.Column(db.String(200), nullable=False)
    target = db.Column(db.String(100))

    frequency_value = db.Column(db.String(20))
    frequency_unit = db.Column(db.String(20))
    display_type = db.Column(db.String(20))
    print_portrait = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    print_half_month = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    reminder_enabled = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    reminder_time = db.Column(
        db.String(5),
        default="08:00",
        nullable=False
    )

    items_json = db.Column(db.Text, default="[]")

    version_history_json = db.Column(
        db.Text,
        default="[]"
    )

    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    notify_users_json = db.Column(
        db.Text,
        default="[]"
    )


class ChecklistResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    checklist_id = db.Column(
        db.Integer,
        nullable=False
    )

    target_type = db.Column(db.String(50))
    target_user = db.Column(db.String(100))
    target_username = db.Column(db.String(50))
    target_vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id")
    )
    target_office = db.Column(db.String(100))

    checked_by = db.Column(db.String(100))
    checked_by_username = db.Column(db.String(50))
    checked_date = db.Column(db.String(30))

    status = db.Column(db.String(30))

    approved_by = db.Column(db.String(100))
    approved_by_username = db.Column(db.String(50))
    approved_date = db.Column(db.String(30))
    reject_reason = db.Column(db.Text)

    approvals_json = db.Column(
        db.Text,
        default="[]"
    )

    notify_users_json = db.Column(
        db.Text,
        default="[]"
    )

    answers_json = db.Column(
        db.Text,
        default="[]"
    )

    checklist_snapshot_json = db.Column(
        db.Text,
        default=""
    )


class VehicleChecklistResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    checklist_id = db.Column(
        db.Integer,
        nullable=False
    )

    vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id"),
        nullable=False
    )

    year = db.Column(db.String(10))
    month = db.Column(db.String(10))
    day = db.Column(db.String(10))

    checked_by = db.Column(db.String(100))
    checked_by_username = db.Column(db.String(50))
    checked_date = db.Column(db.String(30))

    status = db.Column(db.String(30))

    approved_by = db.Column(db.String(100))
    approved_by_username = db.Column(db.String(50))
    approved_date = db.Column(db.String(30))

    reject_reason = db.Column(db.Text)

    approvals_json = db.Column(
        db.Text,
        default="[]"
    )

    notify_users_json = db.Column(
        db.Text,
        default="[]"
    )

    answers_json = db.Column(
        db.Text,
        default="[]"
    )

    checklist_snapshot_json = db.Column(
        db.Text,
        default=""
    )

    operation_judgment_json = db.Column(
        db.Text,
        default="{}"
    )


class ChecklistEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    result_type = db.Column(
        db.String(20),
        nullable=False
    )

    result_id = db.Column(
        db.Integer,
        nullable=False
    )

    event_type = db.Column(
        db.String(50),
        nullable=False
    )

    actor_username = db.Column(
        db.String(50)
    )

    actor_name = db.Column(
        db.String(100)
    )

    detail_json = db.Column(
        db.Text,
        default="{}"
    )

    created_at = db.Column(
        db.String(30),
        nullable=False
    )


class VehicleChecklistNotifySetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    checklist_id = db.Column(
        db.Integer,
        nullable=False
    )

    vehicle_record_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id"),
        nullable=False
    )

    notify_users_json = db.Column(
        db.Text,
        default="[]"
    )


class PatrolResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    created_by_username = db.Column(
        db.String(100)
    )

    created_by_name = db.Column(
        db.String(100)
    )

    date = db.Column(
        db.String(20)
    )

    office = db.Column(
        db.String(100)
    )

    delivery_place = db.Column(
        db.String(100)
    )

    category = db.Column(
        db.String(50)
    )

    content_type = db.Column(
        db.String(50)
    )

    target_type = db.Column(
        db.String(50)
    )

    target_user = db.Column(
        db.String(100)
    )

    target_username = db.Column(
        db.String(50)
    )

    content = db.Column(
        db.Text
    )

    files_json = db.Column(
        db.Text,
        default="[]"
    )

    countermeasure = db.Column(
        db.Text
    )

    countermeasure_files_json = db.Column(
        db.Text,
        default="[]"
    )

    countermeasure_by = db.Column(
        db.String(100)
    )

    countermeasure_by_username = db.Column(
        db.String(50)
    )

    countermeasure_due_date = db.Column(
        db.String(20)
    )

    approval_status = db.Column(
        db.String(30)
    )

    reject_reason = db.Column(
        db.Text
    )


class VehicleMaintenanceInspectionLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_code = db.Column(db.String(50), nullable=False, index=True)
    vehicle_record_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False, index=True)
    maintenance_record_id = db.Column(db.Integer, db.ForeignKey("vehicle_maintenance_record.id"), nullable=False, index=True)
    inspection_result_id = db.Column(db.Integer, db.ForeignKey("vehicle_checklist_result.id"), nullable=False, index=True)
    defect_no = db.Column(db.Integer, nullable=False)
    __table_args__ = (db.UniqueConstraint("maintenance_record_id", "inspection_result_id", "defect_no", name="uq_maintenance_inspection_defect"),)
