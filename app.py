from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    send_file,
    url_for,
    flash,
)
from werkzeug.utils import secure_filename, safe_join
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from uuid import uuid4
import os
import json
import boto3
import calendar
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr
from pywebpush import webpush, WebPushException
import secrets
import zipfile
import re
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import NotFound
from botocore.exceptions import ClientError

from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.drawing.image import Image as ExcelImage
from io import BytesIO
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
)

csrf = CSRFProtect(app)

RATELIMIT_STORAGE_URI = os.environ.get(
    "RATELIMIT_STORAGE_URI",
    "memory://"
)

if (
    os.environ.get("RENDER") == "true"
    and RATELIMIT_STORAGE_URI == "memory://"
):
    raise RuntimeError(
        "本番環境では共有RATELIMIT_STORAGE_URIが必要です。"
    )

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=RATELIMIT_STORAGE_URI,
)

secret_key = os.environ.get("SECRET_KEY")

if not secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable is required"
    )

app.secret_key = secret_key
MFA_ENABLED = (
    os.environ.get("MFA_ENABLED", "true").lower() == "true"
)

VAPID_PRIVATE_KEY = os.environ.get(
    "VAPID_PRIVATE_KEY",
    ""
)

VAPID_PUBLIC_KEY = os.environ.get(
    "VAPID_PUBLIC_KEY",
    ""
)

VAPID_SUBJECT = os.environ.get(
    "VAPID_SUBJECT",
    "mailto:maho_shiokawa@isz.co.jp"
)

DATABASE_URL = os.environ.get("DATABASE_URL")

if (
    os.environ.get("RENDER") == "true"
    and not DATABASE_URL
):
    raise RuntimeError(
        "本番環境ではDATABASE_URLが必要です。"
    )

app.config["SQLALCHEMY_DATABASE_URI"] = (
    DATABASE_URL
    or "sqlite:///dkss.db"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config.update(
    SESSION_COOKIE_NAME=(
        "__Host-dkss_session"
        if os.environ.get("RENDER") == "true"
        else "dkss_session"
    ),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        os.environ.get("RENDER") == "true"
    ),
    SESSION_COOKIE_PATH="/",
    SESSION_COOKIE_DOMAIN=None,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_REFRESH_EACH_REQUEST=True,
)

app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024

@app.errorhandler(413)
def file_too_large(error):
    return "1回に送信できるファイルの合計は1GB以下です。", 413
def return_form_errors(errors, status_code=400):
    for message in errors:
        error_field = get_form_error_field(message)
        flash(
            message,
            f"error:{error_field or ''}"
        )

    return "", status_code


def get_form_error_field(message):
    field_map = {
        "発生日を入力してください。": "event_date",
        "発生日が不正です。": "event_date",
        "対象ユーザーを選択してください。": "target_user_search",
        "対象ユーザーが不正です。": "target_user_search",
        "対象ユーザー情報が不正です。": "target_user_search",
        "納入先を選択してください。": "delivery_place",
        "納入先が不正です。": "delivery_place",
        "内容は5000文字以内で入力してください。": "content_editor",
        "車台番号を入力してください。": "chassis_number",
        "同じ車台番号の車両が既に登録されています。": "chassis_number",
    }

    return field_map.get(message)


def build_safe_redirect_url(referrer, fallback="/"):
    if not referrer:
        return fallback

    normalized_referrer = referrer.replace("\\", "/")
    parsed_referrer = urlparse(normalized_referrer)

    if parsed_referrer.scheme or parsed_referrer.netloc:
        if (
            parsed_referrer.scheme not in {"http", "https"}
            or parsed_referrer.netloc != request.host
        ):
            return fallback

    redirect_path = parsed_referrer.path or "/"

    if not redirect_path.startswith("/"):
        return fallback

    if parsed_referrer.query:
        return redirect_path + "?" + parsed_referrer.query

    return redirect_path


@app.after_request
def redirect_form_errors(response):
    if request.method != "POST":
        return response

    if request.path.startswith("/api/"):
        return response

    if response.status_code not in {
        400,
        403,
        409,
        413,
        429,
    }:
        return response

    if not request.accept_mimetypes.accept_html:
        return response

    if (
        request.path != "/pointouts/new"
        and not request.path.startswith("/master/")
    ):
        return response

    message = response.get_data(
        as_text=True
    ).strip()

    if not message:
        if request.path != "/pointouts/new":
            message = "入力内容を確認してください。"

    error_field = get_form_error_field(message)

    if request.path == "/pointouts/new":
        target_type = request.form.get(
            "target_type",
            "user"
        ).strip()

        if target_type in {"user", "delivery_place"}:
            session["pointout_form_target_type"] = target_type

        session["pointout_form_data"] = {
            "date": request.form.get("date", ""),
            "category": request.form.get("category", ""),
            "target_user": request.form.get("target_user", ""),
            "target_user_search": request.form.get("target_user_search", ""),
            "delivery_place": request.form.get("delivery_place", ""),
            "content_type": request.form.get("content_type", ""),
            "content": request.form.get("content", ""),
        }

    elif request.path == "/master/vehicles/new":
        session["vehicle_form_data"] = request.form.to_dict(
            flat=True
        )

    flash(
        message,
        f"error:{error_field or ''}"
    )

    if request.path == "/pointouts/new":
        return redirect("/pointouts/new")

    return redirect(
        build_safe_redirect_url(
            request.referrer,
            request.path
        )
    )

class UploadValidationError(ValueError):
    pass


@app.errorhandler(UploadValidationError)
def handle_upload_validation_error(error):
    return str(error), 400

def parse_nonnegative_int(value, field_name):
    value = str(value or "").strip()

    if not value:
        return 0

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise UploadValidationError(
            f"{field_name}は整数で入力してください。"
        )

    if parsed < 0:
        raise UploadValidationError(
            f"{field_name}は0以上で入力してください。"
        )

    if parsed > 2147483647:
        raise UploadValidationError(
            f"{field_name}の値が大きすぎます。"
        )

    return parsed

def parse_time_hhmm(value, field_name):
    value = str(value or "").strip()

    try:
        parsed = datetime.strptime(
            value,
            "%H:%M"
        )
    except ValueError:
        raise UploadValidationError(
            f"{field_name}の形式が不正です。"
        )

    return parsed.strftime("%H:%M")

def sanitize_excel_formulas(workbook):
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows():
            for cell in row:
                value = cell.value

                if not isinstance(value, str):
                    continue

                stripped_value = value.lstrip()

                if stripped_value.startswith(
                    ("=", "+", "-", "@")
                ):
                    cell.value = "'" + value

db = SQLAlchemy(app)
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

    name = db.Column(
        db.String(100),
        nullable=False
    )

    role = db.Column(
        db.String(20),
        default="user"
    )

    office = db.Column(
        db.String(100)
    )

    favorite_vehicles_json = db.Column(
        db.Text,
        default="[]"
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
        nullable=False
    )
    model_code = db.Column(db.String(100))
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

def add_audit_log(
    action,
    target_type="",
    target_id="",
    detail="",
    company_code=None,
    username=None,
):
    company_code = str(
        company_code
        or session.get("company_code")
        or ""
    ).strip()

    username = str(
        username
        or session.get("username")
        or ""
    ).strip()

    action = str(action or "").strip()
    target_type = str(target_type or "").strip()
    target_id = str(target_id or "").strip()
    detail = str(detail or "")
    ip_address = str(
        request.remote_addr or ""
    ).strip()

    if len(detail) > 5000:
        detail = detail[:5000]

    if len(ip_address) > 100:
        ip_address = ip_address[:100]

    if len(company_code) > 50:
        company_code = company_code[:50]

    if len(username) > 100:
        username = username[:100]

    if len(action) > 100:
        action = action[:100]

    if len(target_type) > 100:
        target_type = target_type[:100]

    if len(target_id) > 100:
        target_id = target_id[:100]

    audit_log = AuditLog(
        company_code=company_code,
        username=username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=ip_address,
        created_at=datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    )

    db.session.add(audit_log)


def cleanup_old_audit_logs(retention_days=365):
    cutoff = (
        datetime.now() - timedelta(days=retention_days)
    ).strftime("%Y-%m-%d %H:%M:%S")

    AuditLog.query.filter(
        AuditLog.created_at < cutoff
    ).delete(synchronize_session=False)

    db.session.commit()


def update_company_usage_summary(
    company_code,
    increment_login=False
):
    if not company_code:
        return

    summary = CompanyUsageSummary.query.filter_by(
        company_code=company_code
    ).first()

    if not summary:
        summary = CompanyUsageSummary(
            company_code=company_code
        )
        db.session.add(summary)

    summary.user_count = User.query.filter_by(
        company_code=company_code
    ).count()

    summary.vehicle_count = Vehicle.query.filter_by(
        company_code=company_code,
        deleted=False
    ).count()

    summary.checklist_result_count = (
        ChecklistResult.query.filter_by(
            company_code=company_code
        ).count()
        +
        VehicleChecklistResult.query.filter_by(
            company_code=company_code
        ).count()
    )

    if increment_login:
        summary.login_count = (
            summary.login_count or 0
        ) + 1

    summary.last_used_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    summary.updated_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

class Office(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)

class DeliveryPlace(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)

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

    countermeasure_by = db.Column(
        db.String(100)
    )

    countermeasure_by_username = db.Column(
        db.String(50)
    )

    approval_status = db.Column(
        db.String(30)
    )

    reject_reason = db.Column(
        db.Text
    )

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".mts",
    ".m2ts",
    ".mpg",
    ".mpeg",
    ".xlsx",
    ".docx",
}

UPLOAD_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mts": "video/mp2t",
    ".m2ts": "video/mp2t",
    ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg",
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument."
        "spreadsheetml.sheet"
    ),
    ".docx": (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    ),
}

def is_valid_uploaded_file(file, extension):
    stream = file.stream
    original_position = stream.tell()

    try:
        stream.seek(0)
        header = stream.read(16)
        stream.seek(0)
        if extension == ".pdf":
            return header.startswith(b"%PDF-")

        if extension == ".png":
            return header == b"\x89PNG\r\n\x1a\n"

        if extension in {".jpg", ".jpeg"}:
            return header.startswith(b"\xff\xd8\xff")

        if extension in {".mp4", ".mov"}:
            return (
                len(header) >= 8
                and header[4:8] == b"ftyp"
            )

        if extension == ".avi":
            return (
                len(header) >= 12
                and header[:4] == b"RIFF"
                and header[8:12] == b"AVI "
            )

        if extension in {".mkv", ".webm"}:
            return header.startswith(
                b"\x1a\x45\xdf\xa3"
            )

        if extension in {".mts", ".m2ts"}:
            return (
                header.startswith(b"\x47")
                or (
                    len(header) >= 5
                    and header[4:5] == b"\x47"
                )
            )

        if extension in {".mpg", ".mpeg"}:
            return header.startswith(
                (b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3")
            )

        if extension in {".docx", ".xlsx"}:
            try:
                with zipfile.ZipFile(stream) as archive:
                    infos = archive.infolist()

                    if len(infos) > 5000:
                        return False
                    if any(
                        info.file_size > 50 * 1024 * 1024
                        for info in infos
                    ):
                        return False

                    total_uncompressed_size = sum(
                        info.file_size
                        for info in infos
                    )

                    if total_uncompressed_size > 100 * 1024 * 1024:
                        return False

                    if any(
                        (
                            info.file_size > 0
                            and info.compress_size == 0
                        )
                        or (
                            info.file_size > 1024 * 1024
                            and info.compress_size > 0
                            and info.file_size / info.compress_size > 100
                        )
                        for info in infos
                    ):
                        return False
                    
                    names = [
                        info.filename
                        for info in infos
                    ]

                    if extension == ".docx":
                        return (
                            "[Content_Types].xml" in names
                            and "word/document.xml" in names
                        )
                    return (
                        "[Content_Types].xml" in names
                        and "xl/workbook.xml" in names
                    )

            except (
                zipfile.BadZipFile,
                zipfile.LargeZipFile,
                OSError,
                RuntimeError,
                ValueError
            ):
                return False

        return False

    finally:
        stream.seek(original_position)

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "")
AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")

s3_client = None

if S3_BUCKET_NAME:
    s3_client = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY")
    )


def save_uploaded_file(file, folder=None):
    if not file or not file.filename:
        return ""

    upload_file_count = sum(
        len(request.files.getlist(field_name))
        for field_name in request.files.keys()
    )

    if upload_file_count > 50:
        raise UploadValidationError(
            "一度にアップロードできるファイルは50件までです。"
        )

    company_code = session.get("company_code")

    if not company_code:
        raise UploadValidationError(
            "company_code is required for file upload."
        )

    original_filename = os.path.basename(
        str(file.filename or "")
    )

    extension = os.path.splitext(
        original_filename
    )[1].lower()

    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise UploadValidationError(
            "許可されていないファイル形式です。"
        )

    if not is_valid_uploaded_file(
        file,
        extension
    ):
        raise UploadValidationError(
            "ファイルの内容と形式が一致しません。"
        )

    extension_suffixes = {
        ".pdf": ".pdf",
        ".png": ".png",
        ".jpg": ".jpg",
        ".jpeg": ".jpeg",
        ".mp4": ".mp4",
        ".mov": ".mov",
        ".avi": ".avi",
        ".mkv": ".mkv",
        ".webm": ".webm",
        ".mts": ".mts",
        ".m2ts": ".m2ts",
        ".mpg": ".mpg",
        ".mpeg": ".mpeg",
        ".xlsx": ".xlsx",
        ".docx": ".docx",
    }

    filename = (
        f"{uuid4().hex}"
        f"{extension_suffixes[extension]}"
    )

    if folder == "static/manuals":
        storage_folder = "manuals"
    else:
        storage_folder = "uploads"

    # =========================
    # S3
    # uploads/会社コード/ファイル名
    # =========================
    if s3_client and S3_BUCKET_NAME:
        object_key = (
            f"{storage_folder}/"
            f"{company_code}/"
            f"{filename}"
        )

        s3_client.upload_fileobj(
            file,
            S3_BUCKET_NAME,
            object_key,
            ExtraArgs={
                "ContentType": UPLOAD_CONTENT_TYPES[extension],
                "ServerSideEncryption": "AES256",
                "CacheControl": "no-store"
            }
        )

        add_audit_log(
            action="file_uploaded",
            target_type="file",
            target_id=filename,
            detail=f"ファイルアップロード: {extension}",
            company_code=company_code,
        )

        return filename

    # =========================
    # ローカル
    # static/uploads/会社コード/
    # =========================
    if storage_folder == "manuals":
        base_folder = "static/manuals"
    else:
        base_folder = app.config["UPLOAD_FOLDER"]

    safe_company_code = secure_filename(
        str(company_code)
    )

    if (
        not safe_company_code
        or safe_company_code != company_code
    ):
        raise UploadValidationError(
            "Invalid company code."
        )

    save_folder = safe_join(
        base_folder,
        safe_company_code
    )

    if not save_folder:
        raise UploadValidationError(
            "Invalid company code."
        )

    os.makedirs(
        save_folder,
        exist_ok=True
    )

    save_path = os.path.join(
        save_folder,
        filename
    )

    file.save(save_path)

    add_audit_log(
        action="file_uploaded",
        target_type="file",
        target_id=filename,
        detail=f"ファイルアップロード: {extension}",
        company_code=company_code,
    )

    return filename

def file_belongs_to_current_company(filename, folder="uploads"):
    company_code = session.get("company_code")

    if not company_code or not filename:
        return False

    filename = os.path.basename(filename)

    # =========================
    # マニュアル
    # =========================
    if folder == "manuals":
        return Manual.query.filter_by(
            company_code=company_code,
            filename=filename
        ).first() is not None

    # =========================
    # お知らせ
    # =========================
    news_records = News.query.filter_by(
        company_code=company_code
    ).all()

    for news in news_records:
        can_view_news = False

        if news.target_type in ["all", "company"]:
            can_view_news = True

        elif news.target_type == "admins":
            can_view_news = session.get("role") in [
                "admin",
                "itc"
            ]

        elif news.target_type == "office":
            can_view_news = (
                news.target_value
                == (session.get("office") or "")
            )

        elif news.target_type == "user":
            can_view_news = (
                news.target_value
                == session.get("username")
            )

        if not can_view_news:
            continue

        files = safe_json_str_list(
            news.files_json
        )

        if filename in files:
            return True

    # =========================
    # 通知
    # =========================
    notification_records = Notification.query.filter(
        Notification.company_code == company_code,
        Notification.target_username == session.get("username")
    ).all()

    for notification in notification_records:
        files = safe_json_str_list(
            notification.files_json
        )

        if filename in files:
            return True

    # =========================
    # 安全パトロール
    # =========================
    patrol_records = PatrolResult.query.filter_by(
        company_code=company_code
    ).all()

    for patrol in patrol_records:
        patrol_dict = patrol_result_to_dict(patrol)

        if not can_view_patrol_result(patrol_dict):
            continue

        files = safe_json_str_list(
            patrol.files_json
        )

        if filename in files:
            return True

    # =========================
    # 安全チェックリスト結果添付
    # =========================
    checklist_result_records = ChecklistResult.query.filter_by(
        company_code=company_code
    ).all()

    for result in checklist_result_records:
        result_dict = checklist_result_to_dict(result)

        if not can_view_checklist_result(result_dict):
            continue

        answers = safe_json_dict_list(
            result.answers_json
        )

        for answer in answers:
            if filename in answer.get("files", []):
                return True

            if filename in answer.get(
                "criteria_files",
                []
            ):
                return True

    # =========================
    # 車両チェックリスト結果添付
    # =========================
    vehicle_result_records = VehicleChecklistResult.query.filter_by(
        company_code=company_code
    ).all()

    for result in vehicle_result_records:
        answers = safe_json_dict_list(
            result.answers_json
        )

        for answer in answers:
            if filename in answer.get("files", []):
                return True

            if filename in answer.get(
                "criteria_files",
                []
            ):
                return True

    return False

def load_upload_bytes(filename):
    company_code = session.get("company_code")

    if not company_code or not filename:
        return None

    filename = os.path.basename(
        str(filename)
    )

    if not filename:
        return None

    if s3_client and S3_BUCKET_NAME:
        buffer = BytesIO()

        try:
            s3_client.download_fileobj(
                S3_BUCKET_NAME,
                (
                    f"uploads/"
                    f"{company_code}/"
                    f"{filename}"
                ),
                buffer
            )

        except ClientError:
            print(
                "S3添付ファイル取得エラー"
            )
            return None

        buffer.seek(0)
        return buffer

    file_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        company_code,
        filename
    )

    if not os.path.exists(file_path):
        return None

    with open(file_path, "rb") as file:
        return BytesIO(file.read())


@app.route("/files/<folder>/<filename>")
def uploaded_file(folder, filename):
    if folder not in {"uploads", "manuals"}:
        return "Not found", 404

    company_code = session.get("company_code")

    if not company_code:
        return "Not found", 404

    filename = os.path.basename(filename)

    if not file_belongs_to_current_company(
        filename,
        folder
    ):
        return "File not found", 404

    if s3_client and S3_BUCKET_NAME:
        object_keys = [
            (
                f"{folder}/"
                f"{company_code}/"
                f"{filename}"
            ),
            (
                f"{folder}/"
                f"{filename}"
            ),
        ]

        for object_key in object_keys:
            try:
                s3_client.head_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=object_key
                )

                url = s3_client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": S3_BUCKET_NAME,
                        "Key": object_key,
                        "ResponseCacheControl": "no-store"
                    },
                    ExpiresIn=300
                )

                return redirect(url)

            except ClientError:
                continue

        return "File not found", 404

    if folder == "manuals":
        local_path = (
            f"/static/manuals/"
            f"{company_code}/"
            f"{filename}"
        )
    else:
        local_path = (
            f"/static/uploads/"
            f"{company_code}/"
            f"{filename}"
        )

    return redirect(local_path)


@app.route("/static/uploads/<path:filename>")
def s3_uploads_file(filename):
    company_code = session.get("company_code")

    if not company_code:
        return "File not found", 404

    # URL側に会社コードを入れさせない
    filename = os.path.basename(filename)

    if not file_belongs_to_current_company(
        filename,
        "uploads"
    ):
        return "File not found", 404

    if s3_client and S3_BUCKET_NAME:
        object_keys = [
            (
                f"uploads/"
                f"{company_code}/"
                f"{filename}"
            ),
            (
                f"uploads/"
                f"{filename}"
            ),
        ]

        for object_key in object_keys:
            try:
                s3_client.head_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=object_key
                )

                url = s3_client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": S3_BUCKET_NAME,
                        "Key": object_key,
                        "ResponseCacheControl": "no-store"
                    },
                    ExpiresIn=300
                )

                return redirect(url)

            except ClientError:
                continue

        return "File not found", 404

    try:
        return app.send_static_file(
            f"uploads/{company_code}/{filename}"
        )
    except NotFound:
        pass

    try:
        return app.send_static_file(
            f"uploads/{filename}"
        )
    except NotFound:
        return "File not found", 404


@app.route("/static/manuals/<path:filename>")
def s3_manual_file(filename):
    company_code = session.get("company_code")

    if not company_code:
        return "File not found", 404

    filename = os.path.basename(filename)

    if not file_belongs_to_current_company(
        filename,
        "manuals"
    ):
        return "File not found", 404

    if s3_client and S3_BUCKET_NAME:
        try:
            url = s3_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": S3_BUCKET_NAME,
                    "Key": (
                        f"manuals/"
                        f"{company_code}/"
                        f"{filename}"
                    ),
                    "ResponseCacheControl": "no-store"
                },
                ExpiresIn=300
            )

            return redirect(url)

        except ClientError:
            print("S3取得エラー")
            return "File not found", 404

    return app.send_static_file(
        f"manuals/{company_code}/{filename}"
    )

@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"

    response.headers["Referrer-Policy"] = (
        "strict-origin-when-cross-origin"
    )

    response.headers["X-Frame-Options"] = "DENY"

    response.headers["Cross-Origin-Embedder-Policy"] = (
        "require-corp"
    )

    response.headers["Cross-Origin-Opener-Policy"] = (
        "same-origin"
    )

    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )

    s3_csp_source = ""
    if S3_BUCKET_NAME:
        s3_csp_source = (
            f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com "
        )

    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        f"img-src 'self' data: blob: {s3_csp_source}; "
        "media-src 'self' blob:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "frame-src 'none'; "
        "worker-src 'self' blob:; "
        "manifest-src 'self'"
    )
    
    protected_static_file = (
        request.path.startswith("/static/uploads/")
        or request.path.startswith("/static/manuals/")
    )

    if request.path == "/static/manifest.webmanifest":
        response.headers["Cache-Control"] = (
            "no-cache, must-revalidate"
        )

    if (
        protected_static_file
        or not request.path.startswith("/static/")
    ):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        
    if os.environ.get("RENDER") == "true":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    return response

PATROL_VIEW_TYPES = {"user", "delivery_place"}

@app.before_request
def require_login():
    # 保護対象のstaticファイル
    if (
        request.path.startswith("/static/uploads/")
        or request.path.startswith("/static/manuals/")
    ):
        if not session.get("username"):
            return redirect("/login")

        current_user = User.query.filter_by(
            company_code=session.get("company_code"),
            username=session.get("username")
        ).first()

        if not current_user or current_user.login_locked:
            session.clear()
            return redirect("/login")

        if (
            session.get("password_changed_at")
            != current_user.password_changed_at
        ):
            session.clear()
            return redirect("/login")

        session["role"] = current_user.role
        session["name"] = current_user.name
        session["office"] = current_user.office

        if current_user.role != "itc":
            current_company = Company.query.filter_by(
                company_code=current_user.company_code
            ).first()

            if not current_company or not current_company.active:
                session.clear()
                return redirect("/login")

        parts = request.path.strip("/").split("/")

        if len(parts) < 3:
            return "File not found", 404

        folder = parts[1]
        filename = os.path.basename(parts[-1])

        if folder not in {"uploads", "manuals"}:
            return "File not found", 404

        if not file_belongs_to_current_company(
            filename,
            folder
        ):
            return "File not found", 404
    if (
        request.endpoint in {
            "login",
            "mfa",
            "register",
            "static",
            "service_worker"
        }
        or request.endpoint is None
    ):
        return None

    if not session.get("username"):
        return redirect("/login")

    current_user = User.query.filter_by(
        company_code=session.get("company_code"),
        username=session.get("username")
    ).first()

    if not current_user or current_user.login_locked:
        session.clear()
        return redirect("/login")

    if (
        session.get("password_changed_at")
        != current_user.password_changed_at
    ):
        session.clear()
        return redirect("/login")

    session["role"] = current_user.role
    session["name"] = current_user.name
    session["office"] = current_user.office
    if current_user.role != "itc":
        current_company = Company.query.filter_by(
            company_code=current_user.company_code
        ).first()

        if not current_company or not current_company.active:
            session.clear()
            return redirect("/login")
        
    if (
        session.get("password_expired")
        and request.endpoint not in {
            "settings",
            "logout"
        }
    ):
        return redirect("/settings")

    # =========================
    # マスタ管理は管理者のみ
    # =========================
    if request.path == "/master" or request.path.startswith("/master/"):
        if session.get("role") not in ["admin", "itc"]:
            return redirect("/")

    return None


def require_itc():
    return session.get("role") == "itc"

def require_master_admin():
    return session.get("role") in ["admin", "itc"]

def get_company(company_code):
    return Company.query.filter_by(
        company_code=company_code
    ).first()


def offices_for_current_company():
    query = Office.query.filter_by(
        company_code=session.get("company_code")
    )

    return [
        {
            "id": office.id,
            "index": office.id,
            "company_code": office.company_code,
            "name": office.name
        }
        for office in query.all()
    ]

def delivery_places_for_current_company():
    query = DeliveryPlace.query.filter_by(
        company_code=session.get("company_code")
    )

    return [
        {
            "id": place.id,
            "index": place.id,
            "company_code": place.company_code,
            "name": place.name
        }
        for place in query.all()
    ]

def patrol_content_types_for_current_company():
    query = PatrolContentType.query.filter_by(
        company_code=session.get("company_code")
    )

    return [
        {
            "id": item.id,
            "index": item.id,
            "company_code": item.company_code,
            "name": item.name
        }
        for item in query.all()
    ]

def manuals_for_current_company():
    query = Manual.query.filter_by(
        company_code=session.get("company_code")
    )

    return [
        {
            "id": manual.id,
            "index": manual.id,
            "company_code": manual.company_code,
            "title": manual.title,
            "category": manual.category,
            "filename": manual.filename,
        }
        for manual in query.all()
    ]

def vehicle_patrol_to_dict(patrol):
    vehicle = Vehicle.query.filter_by(
        company_code=patrol.company_code,
        id=patrol.vehicle_record_id
    ).first()

    return {
        "chassis_number": (
            vehicle.chassis_number
            if vehicle
            else ""
        ),
        "id": patrol.id,
        "index": patrol.id,
        "company_code": patrol.company_code,
        "vehicle_record_id": patrol.vehicle_record_id,
        "occurred_date": patrol.occurred_date,
        "category": patrol.category,
        "priority": patrol.priority,
        "content": patrol.content,
        "cause": patrol.cause,
        "temporary_action": patrol.temporary_action,
        "repair_content": patrol.repair_content,
        "status": patrol.status,
        "repair_date": patrol.repair_date,
        "repair_person": patrol.repair_person,
        "repair_time": patrol.repair_time,
        "parts": patrol.parts,
        "cost": patrol.cost,
    }


def vehicle_patrols_for_current_company():
    query = VehiclePatrol.query.filter_by(
        company_code=session.get("company_code")
    )

    return [
        vehicle_patrol_to_dict(patrol)
        for patrol in query.order_by(VehiclePatrol.id.desc()).all()
    ]

def checklist_to_dict(checklist):
    items = safe_json_dict_list(
        checklist.items_json
    )

    return {
        "id": checklist.id,
        "index": checklist.id,
        "company_code": checklist.company_code,
        "name": checklist.name,
        "target": checklist.target,
        "frequency_value": checklist.frequency_value,
        "frequency_unit": checklist.frequency_unit,
        "display_type": checklist.display_type,
        "active": bool(checklist.active),
        "print_portrait": bool(checklist.print_portrait),
        "print_half_month": bool(checklist.print_half_month),
        "reminder_enabled": bool(checklist.reminder_enabled),
        "reminder_time": checklist.reminder_time or "08:00",
        "items": items,
        "version_history": safe_json_dict_list(
            checklist.version_history_json
        ),
        "score_enabled": any(
            item.get("score_enabled", False)
            for item in items
            if item.get("item_type") == "check"
        ),
    }

def checklist_revision_key(checklist):
    revision_data = {
        "name": checklist.get("name", ""),
        "target": checklist.get("target", ""),
        "frequency_value": checklist.get(
            "frequency_value",
            ""
        ),
        "frequency_unit": checklist.get(
            "frequency_unit",
            ""
        ),
        "display_type": checklist.get(
            "display_type",
            ""
        ),
        "print_portrait": bool(
            checklist.get("print_portrait")
        ),
        "print_half_month": bool(
            checklist.get("print_half_month")
        ),
        "items": checklist.get("items", []),
    }

    return json.dumps(
        revision_data,
        ensure_ascii=False,
        sort_keys=True
    )

def checklist_for_date(
    checklist,
    year,
    month,
    day
):
    current_checklist = {
        key: value
        for key, value in checklist.items()
        if key != "version_history"
    }

    try:
        target_date = datetime(
            int(year),
            int(month),
            int(day)
        ).date()
    except (TypeError, ValueError):
        return current_checklist

    version_history = []

    for version in checklist.get(
        "version_history",
        []
    ):
        try:
            change_datetime = datetime.strptime(
                version.get("effective_until", ""),
                "%Y-%m-%d %H:%M:%S"
            )
        except (TypeError, ValueError):
            continue

        snapshot = version.get("snapshot") or {}

        if not isinstance(snapshot, dict):
            continue

        version_history.append({
            "change_date": change_datetime.date(),
            "snapshot": snapshot
        })

    version_history.sort(
        key=lambda version: version["change_date"]
    )

    for version in version_history:
        if target_date < version["change_date"]:
            return version["snapshot"]

    return current_checklist


def checklists_for_current_company():
    query = Checklist.query.filter_by(
        company_code=session.get("company_code")
    )

    return [
        checklist_to_dict(checklist)
        for checklist in query.all()
    ]

def safe_json_list(value):
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []

    return parsed if isinstance(parsed, list) else []

def safe_json_str_list(value):
    return [
        item
        for item in safe_json_list(value)
        if isinstance(item, str) and item.strip()
    ]

def safe_json_dict_list(value):
    return [
        item
        for item in safe_json_list(value)
        if isinstance(item, dict)
    ]

def safe_json_dict(value):
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}

    return parsed if isinstance(parsed, dict) else {}

def parse_password_history(value):
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return None

    if not isinstance(parsed, list):
        return None

    if not all(
        isinstance(item, str)
        for item in parsed
    ):
        return None

    return parsed

def checklist_result_to_dict(result):
    return {
        "id": result.id,
        "index": result.id,
        "company_code": result.company_code,
        "checklist_id": result.checklist_id,
        "target_type": result.target_type,
        "target_user": result.target_user,
        "target_username": result.target_username,
        "target_vehicle_record_id": result.target_vehicle_record_id,
        "target_office": result.target_office,
        "checked_by": result.checked_by,
        "checked_by_username": result.checked_by_username,
        "checked_date": result.checked_date,
        "status": result.status,
        "approved_by": result.approved_by,
        "approved_by_username": result.approved_by_username,        
        "approved_date": result.approved_date,
        "reject_reason": result.reject_reason,
        "approvals": safe_json_dict_list(result.approvals_json),
        "answers": safe_json_dict_list(result.answers_json),
        "checklist_snapshot": (
            safe_json_dict(result.checklist_snapshot_json)
            if result.checklist_snapshot_json
            else {}
        ),
    }

def vehicle_checklist_result_to_dict(result):
    return {
        "id": result.id,
        "index": result.id,
        "company_code": result.company_code,
        "checklist_id": result.checklist_id,
        "vehicle_record_id": result.vehicle_record_id,
        "year": result.year,
        "month": result.month,
        "day": result.day,
        "checked_by": result.checked_by,
        "checked_by_username": result.checked_by_username,
        "checked_date": result.checked_date,
        "status": result.status,
        "approved_by": result.approved_by,
        "approved_by_username": result.approved_by_username,
        "approved_date": result.approved_date,
        "reject_reason": result.reject_reason,
        "approvals": safe_json_dict_list(result.approvals_json),
        "notify_users": safe_json_str_list(
            result.notify_users_json
        ),
        "answers": safe_json_dict_list(result.answers_json),
        "checklist_snapshot": (
            safe_json_dict(result.checklist_snapshot_json)
            if result.checklist_snapshot_json
            else {}
        ),
    }

def get_vehicle_checklist_notify_users(
    company_code,
    checklist_id,
    vehicle_record_id
):
    if not vehicle_record_id:
        return []

    setting = VehicleChecklistNotifySetting.query.filter_by(
        company_code=company_code,
        checklist_id=checklist_id,
        vehicle_record_id=vehicle_record_id
    ).first()

    if setting:
        return safe_json_str_list(
            setting.notify_users_json
        )

    # 初回だけ、過去の点検者・承認者から自動作成
    notify_usernames = set()

    company_users = User.query.filter_by(
        company_code=company_code
    ).all()

    valid_usernames = {
        user.username
        for user in company_users
        if user.username
    }

    usernames_by_name = {}

    for user in company_users:
        if not user.name or not user.username:
            continue

        usernames_by_name.setdefault(
            user.name,
            []
        ).append(
            user.username
        )

    def add_notify_user(value):
        value = str(value or "").strip()

        if not value:
            return

        if value in valid_usernames:
            notify_usernames.add(value)
            return

        matched_usernames = (
            usernames_by_name.get(
                value,
                []
            )
        )

        if len(matched_usernames) == 1:
            notify_usernames.add(
                matched_usernames[0]
            )

    past_results = VehicleChecklistResult.query.filter_by(
        company_code=company_code,
        checklist_id=checklist_id,
        vehicle_record_id=vehicle_record_id
    ).all()

    for result in past_results:
        add_notify_user(
            result.checked_by_username
            or result.checked_by
        )

        add_notify_user(
            result.approved_by_username
            or result.approved_by
        )

        approvals = safe_json_dict_list(
            result.approvals_json
        )
        for approval in approvals:
            add_notify_user(
                approval.get("approved_by_username")
                or approval.get("approved_by")
            )

    return sorted(
        notify_usernames
    )

def get_user_local_now(company_code, target_username):
    user = User.query.filter_by(
        company_code=company_code,
        username=target_username
    ).first()

    timezone_name = (
        user.timezone
        if user and user.timezone
        else "Asia/Tokyo"
    )

    try:
        return datetime.now(
            ZoneInfo(timezone_name)
        )
    except Exception:
        return datetime.now(
            ZoneInfo("Asia/Tokyo")
        )


def is_vehicle_checklist_completed_on_date(
    company_code,
    checklist_id,
    vehicle_record_id,
    target_date
):
    result = VehicleChecklistResult.query.filter_by(
        company_code=company_code,
        checklist_id=checklist_id,
        vehicle_record_id=vehicle_record_id,
        year=str(target_date.year),
        month=str(target_date.month).zfill(2),
        day=str(target_date.day).zfill(2)
    ).first()

    return result is not None

def send_vehicle_checklist_reminders(company_code):
    checklists = Checklist.query.filter_by(
        company_code=company_code,
        target="車両管理",
        reminder_enabled=True,
        active=True
    ).all()

    for checklist in checklists:

        # 今回は日次点検のみ対象
        if (
            checklist.frequency_unit != "day"
            or str(checklist.frequency_value or "1") != "1"
        ):
            continue

        reminder_time = (
            checklist.reminder_time
            or "08:00"
        )

        vehicles = Vehicle.query.filter_by(
            company_code=company_code,
            deleted=False
        ).all()

        for vehicle in vehicles:

            notify_users = (
                get_vehicle_checklist_notify_users(
                    company_code,
                    checklist.id,
                    vehicle.id
                )
            )

            for target_username in notify_users:

                target_user = User.query.filter_by(
                    company_code=company_code,
                    username=target_username
                ).first()

                if not target_user:
                    continue

                local_now = get_user_local_now(
                    company_code,
                    target_username
                )

                current_time = local_now.strftime(
                    "%H:%M"
                )

                if current_time < reminder_time:
                    continue

                local_date = local_now.date()

                if is_vehicle_checklist_completed_on_date(
                    company_code,
                    checklist.id,
                    vehicle.id,
                    local_date
                ):
                    continue

                reminder_date = (
                    local_date.strftime("%Y-%m-%d")
                )

                title = "車両点検が未実施です"

                if checklist.frequency_unit == "year":
                    active_day = str(local_date.year)
                elif checklist.display_type == "month":
                    active_day = str(local_date.day).zfill(2)
                else:
                    active_day = str(local_date.month).zfill(2)

                link = (
                    f"/vehicle/checklists/{checklist.id}"
                    f"?vehicle_record_id={vehicle.id}"
                    f"&year={local_date.year}"
                    f"&month={str(local_date.month).zfill(2)}"
                    f"&active_day={active_day}"
                )

                # 同じ人・車両・現地日付では1回だけ
                already_sent = Notification.query.filter_by(
                    company_code=company_code,
                    target_username=target_username,
                    title=title,
                    link=link
                ).first()

                if already_sent:
                    continue

                add_notification(
                    target_user.name,
                    title,
                    (
                        f"{checklist.name}："
                        f"車両 {vehicle.chassis_number} の"
                        f"本日の点検が完了していません。"
                    ),
                    link,
                    company_code=company_code,
                    target_username=target_username
                )
                
def patrol_result_to_dict(result):
    return {
        "id": result.id,
        "index": result.id,
        "company_code": result.company_code,
        "created_by_username": result.created_by_username,
        "created_by_name": result.created_by_name,
        "date": result.date,
        "office": result.office,
        "delivery_place": result.delivery_place,
        "category": result.category,
        "content_type": result.content_type,
        "target_type": result.target_type,
        "target_user": result.target_user,
        "target_username": result.target_username,
        "content": result.content,
        "files": safe_json_str_list(
            result.files_json
        ),
        "countermeasure": result.countermeasure,
        "countermeasure_by": result.countermeasure_by,
        "countermeasure_by_username": (
            result.countermeasure_by_username
        ),        
        "approval_status": result.approval_status,
        "reject_reason": result.reject_reason,
    }

@app.route("/service-worker.js")
def service_worker():
    response = app.send_static_file(
        "js/service-worker.js"
    )
    response.headers[
        "Service-Worker-Allowed"
    ] = "/"
    response.headers[
        "Cache-Control"
    ] = "no-cache"
    return response


@app.route("/api/push/vapid-public-key")
def push_vapid_public_key():
    if not VAPID_PUBLIC_KEY:
        return {
            "publicKey": "",
            "error": "VAPID public key is not configured."
        }, 503

    return {
        "publicKey": VAPID_PUBLIC_KEY
    }

@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return {"error": "Unauthorized"}, 401

    data = request.get_json(silent=True) or {}

    endpoint = str(
        data.get("endpoint") or ""
    ).strip()

    keys = data.get("keys") or {}

    p256dh = str(
        keys.get("p256dh") or ""
    ).strip()

    auth = str(
        keys.get("auth") or ""
    ).strip()

    if not endpoint or not p256dh or not auth:
        return {
            "error": "Invalid push subscription."
        }, 400

    if (
        len(endpoint) > 4000
        or len(p256dh) > 1000
        or len(auth) > 1000
    ):
        return {
            "error": "Push subscription is too large."
        }, 400

    subscription = PushSubscription.query.filter_by(
        endpoint=endpoint
    ).first()

    if subscription:
        subscription.company_code = company_code
        subscription.username = username
        subscription.p256dh = p256dh
        subscription.auth = auth

    else:
        subscription = PushSubscription(
            company_code=company_code,
            username=username,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            created_at=datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        db.session.add(subscription)

    db.session.commit()

    return {
        "success": True
    }


@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return {"error": "Unauthorized"}, 401

    data = request.get_json(silent=True) or {}
    endpoint = str(
        data.get("endpoint") or ""
    ).strip()

    if not endpoint:
        return {"error": "Invalid push subscription."}, 400

    subscription = PushSubscription.query.filter_by(
        endpoint=endpoint,
        company_code=company_code,
        username=username
    ).first()

    if subscription:
        db.session.delete(subscription)
        db.session.commit()

    return {"success": True}


def send_web_push_notification(
    user,
    title,
    message,
    link=""
):
    if not user:
        return False

    if (
        not VAPID_PRIVATE_KEY
        or not VAPID_PUBLIC_KEY
        or not VAPID_SUBJECT
    ):
        print(
            "Web Push未送信：VAPID設定がありません。"
        )
        return False

    subscriptions = PushSubscription.query.filter_by(
        company_code=user.company_code,
        username=user.username
    ).all()

    if not subscriptions:
        return False

    payload = json.dumps(
        {
            "title": str(title or "")[:200],
            "message": str(message or "")[:10000],
            "link": build_absolute_app_url(link),
        },
        ensure_ascii=False
    )

    sent = False

    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    },
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={
                    "sub": VAPID_SUBJECT
                },
                ttl=300,
                timeout=20,
            )

            sent = True

        except WebPushException as e:
            print(
                "Web Push送信エラー:",
                repr(e)
            )

            response = getattr(
                e,
                "response",
                None
            )

            if (
                response is not None
                and response.status_code in (404, 410)
            ):
                db.session.delete(subscription)
                db.session.commit()

        except Exception as e:
            print(
                "Web Push送信エラー:",
                repr(e)
            )

    return sent

@app.route("/api/push/test", methods=["POST"])
def push_test():
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return {"success": False, "error": "Unauthorized"}, 401

    user = User.query.filter_by(
        company_code=company_code,
        username=username
    ).first()

    if not user:
        return {"success": False, "error": "User not found"}, 404

    sent = send_web_push_notification(
        user,
        "DKSS テスト通知",
        "端末通知のテストです。",
        "/notifications"
    )

    if not sent:
        return {
            "success": False,
            "error": "Push notification was not sent."
        }, 400

    return {"success": True}

def send_email_notification(
    user,
    title,
    message,
    link="",
    require_opt_in=True
):
    if not user:
        return False

    if require_opt_in and not user.email_notify_enabled:
        return False

    title = str(title or "").strip()

    if (
        not title
        or len(title) > 200
        or "\r" in title
        or "\n" in title
    ):
        return False

    message = str(message or "")

    if len(message) > 10000:
        return False

    if not is_valid_email_address(
        user.email_address
    ):
        return False

    smtp_host = os.environ.get("SMTP_HOST", "")
    try:
        smtp_port = int(
            os.environ.get("SMTP_PORT", "587")
        )
    except (TypeError, ValueError):
        print(
            "メール通知未送信：SMTP_PORTが不正です。"
        )
        return False
    smtp_username = os.environ.get(
        "SMTP_USERNAME",
        ""
    )
    smtp_password = os.environ.get(
        "SMTP_PASSWORD",
        ""
    )
    smtp_from = os.environ.get(
        "SMTP_FROM",
        smtp_username
    )

    if not smtp_host:
        print(
            "メール通知未送信：SMTP設定がありません。"
        )
        return False

    if not is_valid_email_address(smtp_from):
        print(
            "メール通知未送信：SMTP_FROM が不正です。"
        )
        return False

    full_link = build_absolute_app_url(link)

    email = EmailMessage()

    email["Subject"] = title
    email["From"] = smtp_from
    email["To"] = user.email_address

    body = message or ""

    if full_link:
        body += (
            "\n\n"
            "該当画面を開く：\n"
            f"{full_link}"
        )

    email.set_content(body)

    try:
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=20
        ) as server:
            server.starttls()

            if smtp_username:
                server.login(
                    smtp_username,
                    smtp_password
                )

            server.send_message(email)

        return True

    except Exception as e:
        print(
            "メール通知送信エラー:",
            repr(e)
        )
        return False
def dispatch_external_notification(
    user,
    title,
    message,
    link=""
):
    if not user:
        return

    send_web_push_notification(
        user,
        title,
        message,
        link
    )

    if user.email_notify_enabled:
        send_email_notification(
            user,
            title,
            message,
            link
        )

def add_notification(
    target_user,
    title,
    message,
    link="",
    files=None,
    company_code=None,
    target_username=None
):
    target_user = str(target_user or "").strip()
    title = str(title or "").strip()
    message = str(message or "")

    if not target_user:
        return

    if len(target_user) > 100:
        return

    if not title or len(title) > 200:
        return

    if len(message) > 10000:
        return

    if target_username is not None:
        target_username = str(
            target_username
        ).strip()

        if len(target_username) > 50:
            return

    notification_company_code = (
        company_code
        or session.get("company_code")
    )

    link = str(link or "").strip()

    if (
        len(link) > 200
        or (
            link
            and (
                not link.startswith("/")
                or link.startswith("//")
                or "\\" in link
                or "\r" in link
                or "\n" in link
            )
        )
    ):
        link = ""

    target_user_record = None

    if target_username:
        target_user_record = User.query.filter_by(
            company_code=notification_company_code,
            username=target_username
        ).first()

        if not target_user_record:
            return

        target_user = target_user_record.name
        target_username = target_user_record.username

    notification = Notification(
        company_code=notification_company_code,
        target_user=target_user,
        target_username=target_username,
        title=title,
        message=message,
        link=link,
        files_json=json.dumps(
            files or [],
            ensure_ascii=False
        ),
        read=False,
        created_at=datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )
    )

    db.session.add(notification)
    db.session.commit()

    if target_user_record:
        dispatch_external_notification(
            target_user_record,
            title,
            message,
            link
        )

def build_absolute_app_url(link=""):
    link = str(link or "").strip()

    if not link:
        return ""

    if (
        not link.startswith("/")
        or link.startswith("//")
        or "\\" in link
        or "\r" in link
        or "\n" in link
    ):
        return ""

    base_url = os.environ.get(
        "APP_BASE_URL",
        "https://dkss.onrender.com"
    ).rstrip("/")

    return base_url + link

def add_news(
    title,
    message,
    files=None,
    target_type="",
    target_value="",
    company_code=None
):
    title = str(title or "").strip()
    message = str(message or "")
    target_type = str(target_type or "").strip()
    target_value = str(target_value or "").strip()

    if not title or len(title) > 200:
        return

    if len(message) > 10000:
        return

    if len(target_type) > 50:
        return

    if len(target_value) > 100:
        return

    news_company_code = (
        company_code
        or session.get("company_code")
    )

    if not news_company_code:
        raise ValueError(
            "News company_code is required."
        )

    news = News(
        company_code=news_company_code,
        title=title,
        message=message,
        files_json=json.dumps(
            files or [],
            ensure_ascii=False
        ),
        target_type=target_type,
        target_value=target_value,
        created_at=datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )
    )

    db.session.add(news)
    db.session.flush()

    add_audit_log(
        action="news_created",
        target_type="news",
        target_id=news.id,
        detail=f"お知らせ作成: {news.title}",
        company_code=news.company_code,
    )

    db.session.commit()


def notify_mentions(text, link=""):
    if not text:
        return

    users = User.query.filter_by(
        company_code=session.get("company_code")
    ).all()

    users_by_name = {}

    for user in users:
        if not user.name or not user.username:
            continue

        users_by_name.setdefault(
            user.name,
            []
        ).append(user)

    notified_usernames = set()

    for user in users:
        name = user.name
        username = user.username

        if not name or not username:
            continue

        stable_tag = f"[[{username}|{name}]]"

        if stable_tag in text:
            add_notification(
                name,
                "メンションされました",
                text,
                link,
                target_username=username
            )
            notified_usernames.add(username)
            continue

        name_matches = users_by_name.get(
            name,
            []
        )

        if len(name_matches) != 1:
            continue

        legacy_mention = "@" + name
        legacy_tag = f"[[{name}]]"

        if (
            legacy_mention in text
            or legacy_tag in text
        ):
            if username in notified_usernames:
                continue

            add_notification(
                name,
                "メンションされました",
                text,
                link,
                target_username=username
            )
            notified_usernames.add(username)

def is_same_company_result(result):
    company_code = result.get("company_code")
    return company_code == session.get("company_code")


def can_view_patrol_result(result):
    role = session.get("role")

    if role in ["itc", "admin"]:
        return is_same_company_result(result)

    if not is_same_company_result(result):
        return False

    if result.get("target_type") == "delivery_place":
        return True

    if result.get("created_by_username") == session.get("username"):
        return True

    return (
        result.get("target_type") == "user"
        and result.get("target_username")
        == session.get("username")
    )


def can_edit_patrol_result(result):
    if not is_same_company_result(result):
        return False

    if session.get("role") in ["admin", "itc"]:
        return True

    return (
        result.get("created_by_username")
        == session.get("username")
    )


def can_countermeasure_patrol_result(result):
    if not is_same_company_result(result):
        return False

    if session.get("role") in ["admin", "itc"]:
        return True

    # 作成者
    if (
        result.get("created_by_username")
        == session.get("username")
    ):
        return True

    # 個人対象なら対象本人
    return (
        result.get("target_type") == "user"
        and result.get("target_username")
        == session.get("username")
    )


def can_delete_patrol_result(result):
    return can_edit_patrol_result(result)


def can_approve_patrol_result(result):
    if not is_same_company_result(result):
        return False

    return session.get("role") in ["admin", "itc"]


def can_view_checklist_result(result):
    role = session.get("role")

    if not is_same_company_result(result):
        return False

    if role in ["admin", "itc"]:
        return True

    if (
        result.get("checked_by_username")
        == session.get("username")
    ):
        return True

    return (
        result.get("target_type") == "user"
        and result.get("target_username")
        == session.get("username")
    )


def can_manage_checklist_result(result):
    role = session.get("role")

    if not is_same_company_result(result):
        return False

    if role in ["admin", "itc"]:
        return True

    return (
        result.get("checked_by_username")
        == session.get("username")
    )


def can_approve_checklist_result(result, approval=None):
    role = session.get("role")

    if not is_same_company_result(result):
        return False

    if role in ["admin", "itc"]:
        return True

    if not approval:
        return False

    return approval.get("allow_general", False)


def can_reject_checklist_result(result):
    if not is_same_company_result(result):
        return False

    return session.get("role") in ["admin", "itc"]

def vehicle_number(vehicle):
    return (
        vehicle.get("chassis_number")
        or vehicle.get("number")
        or (
            f"{vehicle.get('plate_area', '')} "
            f"{vehicle.get('plate_class', '')} "
            f"{vehicle.get('plate_kana', '')} "
            f"{vehicle.get('plate_number', '')}"
        ).strip()
    )


def delete_vehicle_related_data(vehicle):

    VehicleChecklistNotifySetting.query.filter_by(
        company_code=vehicle.company_code,
        vehicle_record_id=vehicle.id
    ).delete(synchronize_session=False)


def vehicles_with_numbers(include_inactive=False):

    query = Vehicle.query.filter_by(
        company_code=session.get("company_code")
    )

    if not include_inactive:
        query = query.filter_by(
            deleted=False
        )

    vehicles = []

    for vehicle in query.all():

        item = {
            "index": vehicle.id,
            "id": vehicle.id,
            "company_code": vehicle.company_code,
            "vehicle_record_id": vehicle.id,
            "deleted": vehicle.deleted,

            "plate_area": vehicle.plate_area,
            "plate_class": vehicle.plate_class,
            "plate_kana": vehicle.plate_kana,
            "plate_number": vehicle.plate_number,

            "chassis_number": vehicle.chassis_number,
            "model_code": vehicle.model_code,
            "first_registration_date": vehicle.first_registration_date,
            "manufacturer": vehicle.manufacturer,
            "body_type": vehicle.body_type,

            "gross_vehicle_weight": vehicle.gross_vehicle_weight,
            "max_payload": vehicle.max_payload,

            "type": vehicle.type,
            "office": vehicle.office,
            "inspection_expiry": vehicle.inspection_expiry,
        }

        item["number"] = vehicle_number(item)

        vehicles.append(item)

    return vehicles

def vehicle_types_for_current_company():
    query = VehicleType.query.filter_by(
        company_code=session.get("company_code")
    )

    return [
        {
            "id": vehicle_type.id,
            "index": vehicle_type.id,
            "company_code": vehicle_type.company_code,
            "name": vehicle_type.name
        }
        for vehicle_type in query.all()
    ]

def license_types_for_current_company():
    query = LicenseType.query.filter_by(
        company_code=session.get("company_code")
    )

    return [
        {
            "id": license_type.id,
            "index": license_type.id,
            "company_code": license_type.company_code,
            "name": license_type.name
        }
        for license_type in query.all()
    ]

def user_for_driver(driver):
    return User.query.filter_by(
        company_code=driver.company_code,
        username=driver.employee_id
    ).first()


def driver_to_dict(driver):
    user = user_for_driver(driver)

    return {
        "index": driver.id,
        "id": driver.id,
        "company_code": driver.company_code,
        "employee_id": driver.employee_id,
        "username": user.username if user else "",
        "email_address": user.email_address if user else "",
        "name": driver.name,
        "role": driver.role,
        "office": driver.office,
        "safe_start_date": driver.safe_start_date,
        "vehicles": safe_json_str_list(
            driver.vehicles_json
        ),
        "licenses": safe_json_dict_list(
            driver.licenses_json
        ),
    }


def drivers_for_current_company():
    query = Driver.query.filter_by(
        company_code=session.get("company_code")
    )

    return [
        driver_to_dict(driver)
        for driver in query.all()
    ]

def send_mfa_code_email(user, code):
    if not user or not user.email_address:
        return False

    return send_email_notification(
        user=user,
        title="ログイン認証コード",
        message=(
            "ログイン認証コードは以下です。\n\n"
            f"{code}\n\n"
            "このコードの有効期限は10分です。"
        ),
        require_opt_in=False,
    )

def is_valid_email_address(value):
    value = str(value or "").strip()

    if (
        not value
        or len(value) > 255
        or "\r" in value
        or "\n" in value
    ):
        return False

    _, parsed_address = parseaddr(value)

    if parsed_address != value:
        return False

    if "@" not in parsed_address:
        return False

    local_part, domain = parsed_address.rsplit("@", 1)

    return bool(
        local_part
        and domain
        and "." in domain
    )

def send_email_change_code_email(
    email_address,
    code
):
    if not is_valid_email_address(
        email_address
    ):
        return False

    smtp_host = os.environ.get("SMTP_HOST", "")
    try:
        smtp_port = int(
            os.environ.get("SMTP_PORT", "587")
        )
    except (TypeError, ValueError):
        print(
            "メールアドレス変更確認メール未送信：SMTP_PORTが不正です。"
        )
        return False
    smtp_username = os.environ.get(
        "SMTP_USERNAME",
        ""
    )
    smtp_password = os.environ.get(
        "SMTP_PASSWORD",
        ""
    )
    smtp_from = os.environ.get(
        "SMTP_FROM",
        smtp_username
    )

    if not smtp_host:
        return False

    if not is_valid_email_address(smtp_from):
        return False

    email = EmailMessage()

    email["Subject"] = "メールアドレス変更確認コード"
    email["From"] = smtp_from
    email["To"] = email_address

    email.set_content(
        "メールアドレス変更確認コードは以下です。\n\n"
        f"{code}\n\n"
        "このコードの有効期限は10分です。"
    )

    try:
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=20
        ) as server:
            server.starttls()

            if smtp_username:
                server.login(
                    smtp_username,
                    smtp_password
                )

            server.send_message(email)

        return True

    except Exception as e:
        print(
            "メールアドレス変更確認メール送信エラー:",
            repr(e)
        )
        return False
def create_email_change_code(
    user,
    new_email_address
):
    code = f"{secrets.randbelow(1000000):06d}"

    user.pending_email_address = new_email_address

    user.email_change_code_hash = (
        generate_password_hash(code)
    )

    user.email_change_code_expires_at = (
        datetime.now() + timedelta(minutes=10)
    ).strftime("%Y-%m-%d %H:%M:%S")

    return code
        
def create_mfa_code(user):
    now = datetime.now()

    if user.mfa_code_sent_at:
        try:
            last_sent_at = datetime.strptime(
                user.mfa_code_sent_at,
                "%Y-%m-%d %H:%M:%S"
            )

            if (
                now - last_sent_at
                < timedelta(seconds=60)
            ):
                return None

        except ValueError:
            pass

    code = f"{secrets.randbelow(1000000):06d}"

    user.mfa_code_hash = generate_password_hash(
        code
    )

    user.mfa_code_expires_at = (
        now + timedelta(minutes=10)
    ).strftime("%Y-%m-%d %H:%M:%S")

    user.mfa_code_sent_at = now.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    db.session.commit()

    return code

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    error = None

    if request.method == "POST":
        company_code = request.form.get(
            "company_code",
            ""
        ).strip()
        username = request.form.get(
            "username",
            ""
        ).strip()
        password = request.form.get(
            "password",
            ""
        )

        if (
            len(company_code) > 50
            or len(username) > 50
            or len(password) > 255
        ):
            error = (
                "会社コード、ユーザーID、"
                "またはパスワードが違います。"
            )
            return render_template(
                "login.html",
                error=error
            )

        user = User.query.filter_by(
            company_code=company_code,
            username=username
        ).first()

        if user and user.login_locked:
            error = (
                "アカウントがロックされています。"
                "管理者へお問い合わせください。"
            )

        elif user and check_password_hash(
            user.password,
            password
        ):

            now = datetime.now()

            if user.last_login_at:
                try:
                    last_login_at = datetime.strptime(
                        user.last_login_at,
                        "%Y-%m-%d %H:%M:%S"
                    )

                    if (
                        now - last_login_at
                        >= timedelta(days=90)
                    ):
                        user.login_locked = True

                        add_audit_log(
                            action="account_locked",
                            target_type="user",
                            target_id=user.username,
                            detail="90日以上未使用によるアカウントロック",
                            company_code=user.company_code,
                            username=user.username,
                        )

                        db.session.commit()

                        return render_template(
                            "login.html",
                            error=(
                                "90日以上ログインがなかったため、"
                                "アカウントがロックされました。"
                                "管理者へお問い合わせください。"
                            )
                        )

                except ValueError:
                    pass

            user.failed_login_count = 0

            password_expired = False

            if user.password_changed_at:
                try:
                    password_changed_at = datetime.strptime(
                        user.password_changed_at,
                        "%Y-%m-%d %H:%M:%S"
                    )

                    password_expired = (
                        datetime.now() - password_changed_at
                        >= timedelta(days=90)
                    )

                except ValueError:
                    password_expired = True
            else:
                # 既存ユーザーは導入時点から90日を数える
                user.password_changed_at = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            db.session.commit()

            company = get_company(user.company_code)
            if (
                user.role != "itc"
                and (
                    not company
                    or not company.active
                )
            ):
                return render_template(
                    "login.html",
                    error=(
                        "この会社は現在利用停止中です。"
                        "ITCへお問い合わせください。"
                    )
                )

            if not MFA_ENABLED:
                user.last_login_at = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                add_audit_log(
                    action="login_success",
                    target_type="user",
                    target_id=user.username,
                    detail="パスワード認証成功（MFA一時無効）",
                    company_code=user.company_code,
                    username=user.username,
                )

                update_company_usage_summary(
                    user.company_code,
                    increment_login=True
                )
                
                db.session.commit()

                session.clear()
                session.permanent = True
                session["company_code"] = user.company_code
                session["username"] = user.username
                session["role"] = user.role
                session["name"] = user.name
                session["office"] = user.office

                session["password_changed_at"] = (
                    user.password_changed_at
                )
                session["password_expired"] = password_expired

                if password_expired:
                    return redirect("/settings")

                if user.role == "itc":
                    return redirect("/itc")

                return redirect("/")
          
            code = create_mfa_code(user)
            if code is None:
                return render_template(
                    "login.html",
                    error=(
                        "認証コードは60秒に1回まで送信できます。"
                        "少し待ってからもう一度お試しください。"
                    )
                )
            if not send_mfa_code_email(user, code):
                user.mfa_code_hash = None
                user.mfa_code_expires_at = None
                user.mfa_code_sent_at = None
                db.session.commit()

                return render_template(
                    "login.html",
                    error=(
                        "認証コードを送信できませんでした。"
                        "登録メールアドレスまたは"
                        "メール設定を確認してください。"
                    )
                )

            session.clear()
            session.permanent = True
            session["mfa_pending_company_code"] = (
                user.company_code
            )
            session["mfa_pending_username"] = (
                user.username
            )
            session["mfa_password_expired"] = (
                password_expired
            )
            session["mfa_password_changed_at"] = (
                user.password_changed_at
            )
            session["mfa_attempts"] = 0

            return redirect("/mfa")
            
        else:
            if user:
                user.failed_login_count = (
                    user.failed_login_count or 0
                ) + 1

                if user.failed_login_count >= 10:
                    user.login_locked = True

                    add_audit_log(
                        action="account_locked",
                        target_type="user",
                        target_id=user.username,
                        detail="パスワード認証10回失敗によるアカウントロック",
                        company_code=user.company_code,
                        username=user.username,
                    )

            add_audit_log(
                action="login_failed",
                target_type="user",
                target_id=username,
                detail="パスワード認証失敗",
                company_code=company_code,
                username=username,
            )

            db.session.commit()

            error = (
                "会社コード、ユーザーID、"
                "またはパスワードが違います。"
            )

    return render_template("login.html", error=error)

@app.route("/mfa", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def mfa():
    company_code = session.get(
        "mfa_pending_company_code"
    )
    username = session.get(
        "mfa_pending_username"
    )

    if not company_code or not username:
        return redirect("/login")

    user = User.query.filter_by(
        company_code=company_code,
        username=username
    ).first()

    if not user or user.login_locked:
        session.clear()
        return redirect("/login")

    if user.role != "itc":
        company = Company.query.filter_by(
            company_code=user.company_code
        ).first()

        if not company or not company.active:
            session.clear()
            return redirect("/login")

    if (
        session.get("mfa_password_changed_at")
        != user.password_changed_at
    ):
        session.clear()
        return redirect("/login")
    
    error = None

    if request.method == "POST":
        code = request.form.get(
            "code",
            ""
        ).strip()

        if (
            not user.mfa_code_hash
            or not user.mfa_code_expires_at
        ):
            error = "認証コードが無効です。"

        else:
            try:
                expires_at = datetime.strptime(
                    user.mfa_code_expires_at,
                    "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                expires_at = datetime.min

            if datetime.now() > expires_at:
                user.mfa_code_hash = None
                user.mfa_code_expires_at = None
                db.session.commit()

                session.clear()

                return render_template(
                    "login.html",
                    error=(
                        "認証コードの有効期限が切れています。"
                        "もう一度ログインしてください。"
                    )
                )

            elif (
                len(code) != 6
                or not code.isdigit()
                or not check_password_hash(
                    user.mfa_code_hash,
                    code
                )
            ):
                attempts = (
                    session.get("mfa_attempts", 0) + 1
                )
                session["mfa_attempts"] = attempts

                add_audit_log(
                    action="mfa_failed",
                    target_type="user",
                    target_id=user.username,
                    detail=f"MFA認証失敗 {attempts}回目",
                    company_code=user.company_code,
                    username=user.username,
                )

                db.session.commit()

                if attempts >= 5:
                    user.mfa_code_hash = None
                    user.mfa_code_expires_at = None

                    add_audit_log(
                        action="mfa_code_invalidated",
                        target_type="user",
                        target_id=user.username,
                        detail="MFA認証5回失敗による認証コード無効化",
                        company_code=user.company_code,
                        username=user.username,
                    )

                    db.session.commit()

                    session.clear()

                    return render_template(
                        "login.html",
                        error=(
                            "認証コードを5回間違えたため、"
                            "認証コードを無効化しました。"
                            "もう一度ログインしてください。"
                        )
                    )

                error = (
                    "認証コードが違います。"
                    f"あと{5 - attempts}回入力できます。"
                )

            else:
                password_expired = session.get(
                    "mfa_password_expired",
                    False
                )

                user.mfa_code_hash = None
                user.mfa_code_expires_at = None
                user.last_login_at = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                add_audit_log(
                    action="login_success",
                    target_type="user",
                    target_id=user.username,
                    detail="MFA認証成功",
                    company_code=user.company_code,
                    username=user.username,
                )

                update_company_usage_summary(
                    user.company_code,
                    increment_login=True
                )

                db.session.commit()

                session.clear()
                session.permanent = True
                session["company_code"] = user.company_code
                session["username"] = user.username
                session["role"] = user.role
                session["name"] = user.name
                session["office"] = user.office
                session["password_changed_at"] = (
                    user.password_changed_at
                )
                session["password_expired"] = (
                    password_expired
                )

                if password_expired:
                    return redirect("/settings")

                if user.role == "itc":
                    return redirect("/itc")

                return redirect("/")

    return render_template(
        "mfa.html",
        error=error
    )

@app.route("/itc/news/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def itc_new_news():
    if not require_itc():
        return redirect("/")

    company_code = session.get("company_code")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        message = request.form.get("message", "")

        if not title:
            return "タイトルを入力してください。", 400

        if len(title) > 200:
            return "タイトルは200文字以内で入力してください。", 400

        if len(message) > 10000:
            return "本文は10000文字以内で入力してください。", 400

        target_type = request.form.get("target_type")
        target_value = request.form.get("target_value", "").strip()

        # =========================
        # 通知対象を現在の会社内だけに限定
        # =========================

        user_query = User.query.filter_by(
            company_code=company_code
        )

        target_users = []

        if target_type == "all":
            target_users = user_query.all()

        elif target_type == "admins":
            target_users = user_query.filter_by(
                role="admin"
            ).all()

        elif target_type == "company":
            # 他社コードをPOSTされても無視する
            if target_value != company_code:
                return "対象会社が不正です。", 403

            target_users = user_query.all()

        elif target_type == "office":
            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=target_value
            ).first()

            if not valid_office:
                return "対象営業所が不正です。", 403

            target_users = user_query.filter_by(
                office=target_value
            ).all()

        elif target_type == "user":
            target_user = User.query.filter_by(
                company_code=company_code,
                username=target_value
            ).first()

            if not target_user:
                return "対象ユーザーが不正です。", 403

            target_users = [target_user]

        else:
            return "通知対象が不正です。", 400

        file_names = []

        uploaded_files = request.files.getlist("files")

        for file in uploaded_files:
            filename = save_uploaded_file(file)

            if filename:
                file_names.append(filename)

        # =========================
        # News登録
        # =========================

        add_news(
            title,
            message,
            files=file_names,
            target_type=target_type,
            target_value=target_value
        )

        # =========================
        # 通知登録
        # =========================

        for user in target_users:
            add_notification(
                user.name,
                title,
                message,
                "",
                files=file_names,
                company_code=company_code,
                target_username=user.username
            )

        notify_mentions(
            message,
            "/notifications"
        )

        return redirect("/itc")

    # =========================
    # GET
    # =========================

    company = Company.query.filter_by(
        company_code=company_code
    ).first()

    companies = [company] if company else []

    users = User.query.filter(
        User.company_code == company_code,
        User.role != "itc"
    ).all()

    return render_template(
        "itc_news_form.html",
        companies=companies,
        offices=offices_for_current_company(),
        users=users,
        news=None,
        mode="new"
    )

@app.route("/itc/news/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def itc_edit_news(index):
    if not require_itc():
        return redirect("/")

    company_code = session.get("company_code")

    news = News.query.filter_by(
        id=index,
        company_code=company_code
    ).first()

    if not news:
        return redirect("/itc")

    if request.method == "POST":
        target_type = request.form.get("target_type")
        target_value = request.form.get(
            "target_value",
            ""
        ).strip()

        # =========================
        # 通知対象を現在の会社内だけに限定
        # =========================

        if target_type == "company":
            if target_value != company_code:
                return "対象会社が不正です。", 403

        elif target_type == "office":
            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=target_value
            ).first()

            if not valid_office:
                return "対象営業所が不正です。", 403

        elif target_type == "user":
            valid_user = User.query.filter_by(
                company_code=company_code,
                username=target_value
            ).first()

            if not valid_user:
                return "対象ユーザーが不正です。", 403

        elif target_type not in [
            "all",
            "admins"
        ]:
            return "通知対象が不正です。", 400

        title = request.form.get("title", "").strip()
        message = request.form.get("message", "")

        if not title:
            return "タイトルを入力してください。", 400

        if len(title) > 200:
            return "タイトルは200文字以内で入力してください。", 400

        if len(message) > 10000:
            return "本文は10000文字以内で入力してください。", 400

        news.title = title
        news.message = message
        news.target_type = target_type
        news.target_value = target_value

        files = safe_json_str_list(
            news.files_json
        )

        uploaded_files = request.files.getlist(
            "files"
        )

        for file in uploaded_files:
            filename = save_uploaded_file(file)

            if filename:
                files.append(filename)

        news.files_json = json.dumps(
            files,
            ensure_ascii=False
        )

        add_audit_log(
            action="news_updated",
            target_type="news",
            target_id=news.id,
            detail=f"お知らせ編集: {news.title}",
            company_code=news.company_code,
        )

        db.session.commit()

        return redirect("/itc")

    # =========================
    # GET
    # =========================

    company = Company.query.filter_by(
        company_code=company_code
    ).first()

    companies = [company] if company else []

    users = User.query.filter(
        User.company_code == company_code,
        User.role != "itc"
    ).all()

    news_dict = {
        "id": news.id,
        "index": news.id,
        "title": news.title,
        "message": news.message,
        "files": safe_json_str_list(
            news.files_json
        ),
        "target_type": news.target_type,
        "target_value": news.target_value,
        "created_at": news.created_at,
    }

    return render_template(
        "itc_news_form.html",
        news=news_dict,
        index=news.id,
        mode="edit",
        companies=companies,
        offices=offices_for_current_company(),
        users=users
    )

@app.route("/itc/news/<int:index>/delete", methods=["POST"])
@limiter.limit("10 per minute")
def itc_delete_news(index):
    if not require_itc():
        return redirect("/")

    company_code = session.get("company_code")

    news = News.query.filter_by(
        id=index,
        company_code=company_code
    ).first()

    if not news:
        return redirect("/itc")

    add_audit_log(
        action="news_deleted",
        target_type="news",
        target_id=news.id,
        detail=f"お知らせ削除: {news.title}",
        company_code=news.company_code,
    )

    db.session.delete(news)
    db.session.commit()

    return redirect("/itc")

@app.context_processor
def inject_notification_count():
    username = session.get("username")

    unread_count = 0

    if username:
        unread_count = Notification.query.filter(
            Notification.company_code == session.get("company_code"),
            Notification.read == False,
            Notification.target_username == username
        ).count()

    return {
        "unread_notification_count": unread_count
    }

@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def register():
    error = None

    company_code_from_url = request.args.get(
        "company_code",
        ""
    ).strip()

    if request.method == "POST":
        company_code = company_code_from_url

        name = request.form.get(
            "name",
            ""
        ).strip()

        employee_id = request.form.get(
            "employee_id",
            ""
        ).strip()

        email_address = request.form.get(
            "email_address",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        office = request.form.get(
            "office",
            ""
        ).strip()

        password_type_count = sum([
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ])

        company = Company.query.filter_by(
            company_code=company_code
        ).first()

        if (
            not company_code
            or not name
            or not employee_id
            or not password
        ):
            error = "必須項目を入力してください。"

        elif not company:
            error = "会社コードが存在しません。"

        elif not company.active:
            error = "この会社は現在利用停止中です。"

        elif len(employee_id) > 50:
            error = "ログインIDは50文字以内で入力してください。"

        elif len(name) > 100:
            error = "氏名は100文字以内で入力してください。"

        elif email_address and not is_valid_email_address(
            email_address
        ):
            error = "メールアドレスの形式が不正です。"

        elif len(password) < 8:
            error = "パスワードは8文字以上にしてください。"

        elif len(password) > 128:
            error = "パスワードは128文字以内にしてください。"

        elif password_type_count < 3:
            error = (
                "パスワードは英大文字・英小文字・数字・記号の"
                "うち3種類以上を使用してください。"
            )

        elif User.query.filter_by(
            company_code=company_code,
            username=employee_id
        ).first():
            error = "このログインIDはすでに使用されています。"

        elif office and not Office.query.filter_by(
            company_code=company_code,
            name=office
        ).first():
            error = "営業所が不正です。"

        else:
            user = User(
                company_code=company_code,
                username=employee_id,
                password=generate_password_hash(password),
                password_changed_at=datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                role="user",
                name=name,
                office=office,
                favorite_vehicles_json="[]",
                email_address=email_address or None,
                email_notify_enabled=bool(email_address)
            )

            driver = Driver.query.filter_by(
                company_code=company_code,
                employee_id=employee_id
            ).first()

            db.session.add(user)

            if not driver:
                driver = Driver(
                    company_code=company_code,
                    employee_id=employee_id,
                    name=name,
                    role="user",
                    office=office,
                    safe_start_date=datetime.now().strftime(
                        "%Y-%m-%d"
                    ),
                    vehicles_json="[]",
                    licenses_json="[]"
                )
                db.session.add(driver)

            add_audit_log(
                action="user_registered",
                target_type="user",
                target_id=employee_id,
                detail="招待URLからユーザー登録",
                company_code=company_code,
                username=employee_id,
            )

            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                error = (
                    "このログインIDはすでに使用されています。"
                    "画面を再読み込みして確認してください。"
                )
            else:
                return redirect("/login")

    company = None

    if company_code_from_url:
        company = Company.query.filter_by(
            company_code=company_code_from_url,
            active=True
        ).first()

    offices = []

    if company:
        offices = Office.query.filter_by(
            company_code=company.company_code
        ).order_by(
            Office.name.asc()
        ).all()

    return render_template(
        "register.html",
        error=error,
        company_code=company_code_from_url,
        offices=offices
    )

@app.route("/logout", methods=["POST"])
def logout():
    add_audit_log(
        action="logout",
        target_type="user",
        target_id=session.get("username", ""),
        detail="ユーザーがログアウト",
    )

    db.session.commit()

    session.clear()
    return redirect("/login")
    
@app.route("/settings", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def settings():
    current_user = User.query.filter_by(
        company_code=session.get("company_code"),
        username=session.get("username")
    ).first()

    if not current_user:
        session.clear()
        return redirect("/login")

    error = None
    notification_success = None
    password_success = None

    if request.method == "POST":
        action = request.form.get("action", "password")

        if action == "notifications":
            new_email_address = (
                request.form.get("email_address", "").strip()
            )

            if (
                new_email_address
                and not is_valid_email_address(
                    new_email_address
                )
            ):
                error = "メールアドレスの形式が不正です。"

            notification_current_password = (
                request.form.get(
                    "notification_current_password",
                    ""
                )
            )

            old_email_address = (
                current_user.email_address or ""
            )

            if error:
                pass

            elif (
                new_email_address != old_email_address
                and not check_password_hash(
                    current_user.password,
                    notification_current_password
                )
            ):
                error = (
                    "メールアドレスを変更するには、"
                    "現在のパスワードを入力してください。"
                )

            else:
                timezone_name = (
                    request.form.get("timezone")
                    or current_user.timezone
                    or "Asia/Tokyo"
                ).strip()

                try:
                    ZoneInfo(timezone_name)
                except Exception:
                    error = "タイムゾーンが不正です。"
                else:
                    email_notify_enabled = (
                        request.form.get("email_notify_enabled") == "1"
                    )

                    current_user.timezone = timezone_name
                    current_user.email_notify_enabled = email_notify_enabled

                    if new_email_address != old_email_address:
                        code = create_email_change_code(
                            current_user,
                            new_email_address
                        )

                        if not send_email_change_code_email(
                            new_email_address,
                            code
                        ):
                            current_user.pending_email_address = None
                            current_user.email_change_code_hash = None
                            current_user.email_change_code_expires_at = None
                            db.session.rollback()

                            error = (
                                "変更先メールアドレスへ"
                                "確認コードを送信できませんでした。"
                            )

                        else:
                            db.session.commit()
                            session["email_change_attempts"] = 0

                            return redirect("/settings/email/verify")

                    else:
                        db.session.commit()
                        notification_success = "通知設定を保存しました。"

        else:
            current_password = request.form.get(
                "current_password",
                ""
            )
            new_password = request.form.get(
                "new_password",
                ""
            )
            new_password_confirm = request.form.get(
                "new_password_confirm",
                ""
            )

            password_type_count = sum([
                any(c.islower() for c in new_password or ""),
                any(c.isupper() for c in new_password or ""),
                any(c.isdigit() for c in new_password or ""),
                any(
                    not c.isalnum()
                    for c in new_password or ""
                ),
            ])

            password_history = parse_password_history(
                current_user.password_history_json
            )

            if password_history is None:
                error = (
                    "パスワード履歴データが不正です。"
                    "管理者へお問い合わせください。"
                )
                return render_template(
                    "settings.html",
                    user=current_user,
                    error=error,
                    notification_success=notification_success,
                    password_success=password_success,
                )
            
            reused_password = (
                check_password_hash(
                    current_user.password,
                    new_password or ""
                )
                or any(
                    check_password_hash(
                        old_password_hash,
                        new_password or ""
                    )
                    for old_password_hash in password_history[-5:]
                )
            )

            if not check_password_hash(
                current_user.password,
                current_password
            ):
                error = "現在のパスワードが違います。"

            elif not new_password:
                error = "新しいパスワードを入力してください。"

            elif len(new_password) < 8:
                error = "パスワードは8文字以上にしてください。"

            elif len(new_password) > 128:
                error = "パスワードは128文字以内にしてください。"

            elif password_type_count < 3:
                error = (
                    "パスワードは英大文字・英小文字・数字・記号の"
                    "うち3種類以上を使用してください。"
                )

            elif new_password != new_password_confirm:
                error = "新しいパスワードが一致しません。"

            elif reused_password:
                error = (
                    "現在または過去5回以内に使用した"
                    "パスワードは使用できません。"
                )

            else:
                password_history.append(
                    current_user.password
                )

                current_user.password_history_json = json.dumps(
                    password_history[-5:]
                )

                current_user.password = generate_password_hash(
                    new_password
                )

                current_user.password_changed_at = (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                session["password_changed_at"] = (
                    current_user.password_changed_at
                )
                session["password_expired"] = False
                add_audit_log(
                    action="password_changed",
                    target_type="user",
                    target_id=current_user.username,
                    detail="本人によるパスワード変更",
                    company_code=current_user.company_code,
                    username=current_user.username,
                )

                db.session.commit()
                password_success = "パスワードを変更しました。"

    return render_template(
        "settings.html",
        user=current_user,
        error=error,
        notification_success=notification_success,
        password_success=password_success,
    )

@app.route(
    "/settings/email/verify",
    methods=["GET", "POST"]
)
@limiter.limit("5 per minute", methods=["POST"])
def verify_email_change():
    current_user = User.query.filter_by(
        company_code=session.get("company_code"),
        username=session.get("username")
    ).first()

    if not current_user:
        session.clear()
        return redirect("/login")

    if (
        not current_user.pending_email_address
        or not current_user.email_change_code_hash
        or not current_user.email_change_code_expires_at
    ):
        return redirect("/settings")

    error = None

    if request.method == "POST":
        code = request.form.get(
            "code",
            ""
        ).strip()

        try:
            expires_at = datetime.strptime(
                current_user.email_change_code_expires_at,
                "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            expires_at = datetime.min

        if datetime.now() > expires_at:
            current_user.pending_email_address = None
            current_user.email_change_code_hash = None
            current_user.email_change_code_expires_at = None

            db.session.commit()

            session.pop(
                "email_change_attempts",
                None
            )

            error = (
                "確認コードの有効期限が切れています。"
                "もう一度メールアドレス変更を行ってください。"
            )

        elif (
            len(code) != 6
            or not code.isdigit()
            or not check_password_hash(
                current_user.email_change_code_hash,
                code
            )
        ):
            attempts = (
                session.get("email_change_attempts", 0) + 1
            )

            session["email_change_attempts"] = attempts

            if attempts >= 5:
                current_user.pending_email_address = None
                current_user.email_change_code_hash = None
                current_user.email_change_code_expires_at = None

                add_audit_log(
                    action="email_change_code_invalidated",
                    target_type="user",
                    target_id=current_user.username,
                    detail="メール変更確認コード5回失敗による無効化",
                    company_code=current_user.company_code,
                    username=current_user.username,
                )

                db.session.commit()

                session.pop(
                    "email_change_attempts",
                    None
                )

                return redirect("/settings")

            error = (
                "確認コードが違います。"
                f"あと{5 - attempts}回入力できます。"
            )

        else:
            current_user.email_address = (
                current_user.pending_email_address
            )

            current_user.pending_email_address = None
            current_user.email_change_code_hash = None
            current_user.email_change_code_expires_at = None

            session.pop(
                "email_change_attempts",
                None
            )

            add_audit_log(
                action="email_changed",
                target_type="user",
                target_id=current_user.username,
                detail="メール確認完了によるメールアドレス変更",
                company_code=current_user.company_code,
                username=current_user.username,
            )

            db.session.commit()

            return redirect("/settings")

    return render_template(
        "email_change_verify.html",
        error=error
    )

@app.route("/api/news-targets")
def news_targets():
    target_type = request.args.get("type", "")
    keyword = request.args.get("q", "").strip()

    if len(keyword) > 100:
        return {"results": []}, 400

    company_code = session.get("company_code")
    role = session.get("role")

    results = []

    # ITC専用機能
    if role != "itc":
        return {"results": []}, 403

    if target_type == "company":
        query = Company.query.filter_by(
            company_code=company_code
        )

        if keyword:
            keyword_like = f"%{keyword}%"
            query = query.filter(
                db.or_(
                    Company.company_name.ilike(keyword_like),
                    Company.company_code.ilike(keyword_like)
                )
            )

        for company in query.order_by(
            Company.company_name.asc()
        ).limit(10).all():
            results.append({
                "id": company.company_code,
                "name": company.company_name,
                "sub": "会社コード：" + company.company_code
            })

    elif target_type == "office":
        query = Office.query.filter_by(
            company_code=company_code
        )

        if keyword:
            keyword_like = f"%{keyword}%"
            query = query.filter(
                Office.name.ilike(keyword_like)
            )

        for office in query.order_by(
            Office.name.asc()
        ).limit(10).all():
            results.append({
                "id": office.name or "",
                "name": office.name or "",
                "sub": "営業所"
            })

    elif target_type == "user":
        query = User.query.filter(
            User.company_code == company_code,
            User.role != "itc"
        )

        if keyword:
            keyword_like = f"%{keyword}%"
            query = query.filter(
                db.or_(
                    User.name.ilike(keyword_like),
                    User.username.ilike(keyword_like),
                    User.office.ilike(keyword_like)
                )
            )

        for user in query.order_by(
            User.name.asc()
        ).limit(10).all():
            results.append({
                "id": user.username,
                "name": user.name or "",
                "sub": user.office or ""
            })

    return {"results": results}

@app.route("/api/mention-users")
def mention_users():
    keyword = request.args.get("q", "").strip()

    if len(keyword) > 100:
        return {"users": []}, 400

    user_query = User.query.filter_by(
        company_code=session.get("company_code")
    )

    if keyword:
        keyword_like = f"%{keyword}%"

        user_query = user_query.filter(
            db.or_(
                User.name.ilike(keyword_like),
                User.username.ilike(keyword_like)
            )
        )

    matched_users = (
        user_query
        .order_by(User.name.asc())
        .limit(10)
        .all()
    )

    users = [
        {
            "name": user.name or "",
            "username": user.username,
            "office": user.office or ""
        }
        for user in matched_users
    ]

    return {"users": users}

@app.route("/api/vehicles")
def search_vehicles():

    keyword = request.args.get("q", "").strip()

    if len(keyword) > 100:
        return {"results": []}, 400

    company_code = session.get("company_code")

    query = Vehicle.query.filter_by(
        company_code=company_code,
        deleted=False
    )
    if keyword:

        keyword_like = f"%{keyword}%"

        query = query.filter(
            db.or_(
                Vehicle.plate_area.ilike(keyword_like),
                Vehicle.plate_class.ilike(keyword_like),
                Vehicle.plate_kana.ilike(keyword_like),
                Vehicle.plate_number.ilike(keyword_like),
                Vehicle.chassis_number.ilike(keyword_like),
                Vehicle.model_code.ilike(keyword_like),
                Vehicle.manufacturer.ilike(keyword_like),
            )
        )

    vehicles = (
        query
        .order_by(Vehicle.id.asc())
        .limit(20)
        .all()
    )

    results = []

    for vehicle in vehicles:

        number = " ".join(
            value
            for value in [
                vehicle.plate_area or "",
                vehicle.plate_class or "",
                vehicle.plate_kana or "",
                vehicle.plate_number or "",
            ]
            if value
        )

        results.append({
            "id": vehicle.id,
            "vehicle_record_id": vehicle.id,
            "number": number,
            "chassis_number": vehicle.chassis_number or "",
            "manufacturer": vehicle.manufacturer or "",
            "model_code": vehicle.model_code or "",
        })

    return {
        "results": results
    }

@app.route("/dashboard/settings", methods=["POST"])
@limiter.limit("20 per minute")
def save_dashboard_settings():
    current_user = User.query.filter_by(
        company_code=session.get("company_code"),
        username=session.get("username")
    ).first()

    if not current_user:
        session.clear()
        return redirect("/login")

    office = request.form.get("office", "").strip()
    period = request.form.get("period", "30d").strip()

    if office:
        valid_office = Office.query.filter_by(
            company_code=session.get("company_code"),
            name=office
        ).first()

        if not valid_office:
            office = ""

    if period not in ["7d", "30d", "90d", "365d"]:
        period = "30d"

    settings = safe_json_dict(
        current_user.dashboard_settings_json
    )
    settings["office"] = office
    settings["period"] = period
    settings["show_summary"] = (
        request.form.get("show_summary") == "1"
    )

    settings["show_vehicles"] = (
        request.form.get("show_vehicles") == "1"
    )

    settings["show_my_checklists"] = (
        request.form.get("show_my_checklists") == "1"
    )

    settings["show_analysis"] = (
        request.form.get("show_analysis") == "1"
    )

    settings["show_ranking"] = (
        request.form.get("show_ranking") == "1"
    )

    settings["show_inspection"] = (
        request.form.get("show_inspection") == "1"
    )

    settings["show_pending"] = (
        request.form.get("show_pending") == "1"
    )

    current_user.dashboard_settings_json = json.dumps(
        settings,
        ensure_ascii=False
    )

    db.session.commit()

    return redirect("/")

@app.route("/")
def dashboard():
    today = datetime.now().date()
    user_name = session.get("name")

    company_code = session.get("company_code")

    update_company_usage_summary(company_code)
    db.session.commit()

    current_user = User.query.filter_by(
        company_code=company_code,
        username=session.get("username")
    ).first()

    dashboard_settings = {
        "office": "",
        "period": "30d",
        "show_summary": True,
        "show_vehicles": True,
        "show_my_checklists": True,
        "show_analysis": True,
        "show_ranking": True,
        "show_inspection": True,
        "show_pending": True,
    }

    if current_user:
        saved_dashboard_settings = safe_json_dict(
            current_user.dashboard_settings_json
        )
        dashboard_settings.update(saved_dashboard_settings)

    period_days = {
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "365d": 365,
    }.get(
        dashboard_settings.get("period"),
        30
    )

    dashboard_start_date = (
        today - timedelta(days=period_days - 1)
    ).strftime("%Y-%m-%d")

    # 自分の無事故無違反日数
    my_driver = Driver.query.filter_by(
        company_code=company_code,
        employee_id=session.get("username")
    ).first()

    my_safe_days = 0

    my_vehicle_record_ids = []

    if my_driver:
        my_vehicle_record_ids = [
            int(vehicle_record_id)
            for vehicle_record_id in safe_json_str_list(
                my_driver.vehicles_json
            )
            if vehicle_record_id.isdigit()
        ]

    if my_driver and my_driver.safe_start_date:
        try:
            start_date = datetime.strptime(
                my_driver.safe_start_date,
                "%Y-%m-%d"
            ).date()

            my_safe_days = (today - start_date).days
        except ValueError:
            my_safe_days = 0

    # 社内ランキング
    ranking_query = Driver.query.filter(
        Driver.company_code == company_code,
        Driver.safe_start_date.isnot(None),
        Driver.safe_start_date != ""
    )

    if dashboard_settings.get("office"):
        ranking_query = ranking_query.filter(
            Driver.office == dashboard_settings["office"]
        )

    ranking_records = (
        ranking_query
        .order_by(Driver.safe_start_date.asc())
        .limit(10)
        .all()
    )

    ranking = []

    for driver in ranking_records:
        try:
            start_date = datetime.strptime(
                driver.safe_start_date,
                "%Y-%m-%d"
            ).date()
        except ValueError:
            continue

        ranking.append({
            "id": driver.id,
            "index": driver.id,
            "employee_id": driver.employee_id,
            "name": driver.name,
            "role": driver.role,
            "office": driver.office,
            "safe_start_date": driver.safe_start_date,
            "safe_days": (today - start_date).days,
        })

    # 自分のGood件数
    my_good_count = PatrolResult.query.filter_by(
        company_code=session.get("company_code"),
        target_type="user",
        target_username=session.get("username"),
        category="Good"
    ).count()

    # 自分に対する未対応指摘
    my_pending_pointouts = []

    pending_records = PatrolResult.query.filter_by(
        company_code=session.get("company_code"),
        target_type="user",
        target_username=session.get("username")
    ).filter(
        PatrolResult.category != "Good",
        PatrolResult.approval_status != "承認済み"
    ).order_by(
        PatrolResult.id.desc()
    ).all()

    for record in pending_records:
        my_pending_pointouts.append(
            patrol_result_to_dict(record)
        )

    # 車検が近い車両
    inspection_alerts = []

    inspection_limit_date = (
        today + timedelta(days=90)
    ).strftime("%Y-%m-%d")


    inspection_vehicle_query = Vehicle.query.filter(
        Vehicle.company_code == company_code,
        Vehicle.deleted == False,
        Vehicle.inspection_expiry.isnot(None),
        Vehicle.inspection_expiry != "",
        Vehicle.inspection_expiry <= inspection_limit_date
    )

    if dashboard_settings.get("office"):
        inspection_vehicle_query = inspection_vehicle_query.filter(
            Vehicle.office == dashboard_settings["office"]
        )

    inspection_vehicle_records = (
        inspection_vehicle_query
        .order_by(Vehicle.inspection_expiry.asc())
        .all()
    )


    for vehicle in inspection_vehicle_records:

        try:
            expiry_date = datetime.strptime(
                vehicle.inspection_expiry,
                "%Y-%m-%d"
            ).date()
        except ValueError:
            continue


        remaining_days = (
            expiry_date - today
        ).days


        item = {
            "vehicle_record_id": vehicle.id,
            "chassis_number": vehicle.chassis_number,
            "number": " ".join(
                value
                for value in [
                    vehicle.plate_area or "",
                    vehicle.plate_class or "",
                    vehicle.plate_kana or "",
                    vehicle.plate_number or "",
                ]
                if value
            ),
            "type": vehicle.type or "",
            "body_type": vehicle.body_type or "",
            "inspection_expiry": vehicle.inspection_expiry,
            "remaining_days": remaining_days,
        }

        inspection_alerts.append(item)

    setup_tasks = []

    if session.get("role") == "admin":
        company_code = session.get("company_code")

        if Office.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "営業所マスタ",
                "description": "営業所を登録してください。",
                "url": "/master/offices"
            })

        if VehicleType.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "車種マスタ",
                "description": "車両登録で使用する車種を登録してください。",
                "url": "/master/vehicle-types"
            })

        if LicenseType.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "免許種別マスタ",
                "description": "ドライバー登録で使用する免許種別を登録してください。",
                "url": "/master/license-types"
            })

        if DeliveryPlace.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "納入先マスタ",
                "description": "安全パトロールで使用する納入先を登録してください。",
                "url": "/master/delivery-places"
            })

        if Vehicle.query.filter_by(
            company_code=company_code,
            deleted=False
        ).count() == 0:
            setup_tasks.append({
                "name": "車両マスタ",
                "description": "車両管理・点検で使用する車両を登録してください。",
                "url": "/master/vehicles"
            })

        if Checklist.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "チェックリストマスタ",
                "description": "安全管理・車両管理で使用するチェックリストを登録してください。",
                "url": "/master/checklists"
            })

    def dashboard_score_value(value):
        text = str(value or "").strip()

        symbol_scores = {
            # 良好
            "○": 2.0,
            "〇": 2.0,
            "✓": 2.0,
            "✔": 2.0,
            "☑": 2.0,

            # 注意
            "△": 1.0,
            "▲": 1.0,

            # 不良
            "×": 0.0,
            "✕": 0.0,
            "✖": 0.0,
            "✗": 0.0,
            "✘": 0.0,
            "X": 0.0,
            "x": 0.0,
        }

        if text in symbol_scores:
            return symbol_scores[text]

        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    checklist_score_summaries = []
    my_checklist_summaries = []

    score_checklists = Checklist.query.filter_by(
        company_code=company_code,
        active=True
    ).filter(
        Checklist.target.in_(["安全管理", "車両管理"])
    ).all()

    for checklist_record in score_checklists:
        checklist = checklist_to_dict(checklist_record)

        has_dashboard_score = checklist.get("score_enabled") or any(
            dashboard_score_value(choice) is not None
            for item in checklist.get("items", [])
            if item.get("item_type") == "check"
            and item.get("input_type") == "select"
            for choice in item.get("choices", [])
        )

        is_vehicle_checklist = (
            checklist_record.target == "車両管理"
        )

        if (
            not has_dashboard_score
            and not is_vehicle_checklist
        ):
            continue

        check_items = [
            item
            for item in checklist.get("items", [])
            if item.get("item_type") == "check"
        ]

        if is_vehicle_checklist:

            vehicle_result_query = VehicleChecklistResult.query.filter_by(
                company_code=company_code,
                checklist_id=checklist_record.id
            ).filter(
                VehicleChecklistResult.checked_date >= dashboard_start_date
            )

            if dashboard_settings.get("office"):
                office_vehicle_record_ids = [
                    vehicle.id
                    for vehicle in Vehicle.query.filter_by(
                        company_code=company_code,
                        office=dashboard_settings["office"],
                        deleted=False
                    ).all()
                ]

                vehicle_result_query = vehicle_result_query.filter(
                    VehicleChecklistResult.vehicle_record_id.in_(
                        office_vehicle_record_ids
                    )
                )

            result_records = vehicle_result_query.all()
            my_result_records = [
                result_record
                for result_record in result_records
                if result_record.vehicle_record_id in my_vehicle_record_ids
            ]

        else:

            safety_result_query = ChecklistResult.query.filter_by(
                company_code=company_code,
                checklist_id=checklist_record.id
            ).filter(
                ChecklistResult.checked_date >= dashboard_start_date
            )

            if dashboard_settings.get("office"):
                safety_result_query = safety_result_query.filter(
                    ChecklistResult.target_office == dashboard_settings["office"]
                )

            result_records = safety_result_query.all()

            # ログイン中ユーザー本人が対象の結果
            my_result_records = [
                result_record
                for result_record in result_records
                if (
                    result_record.target_type == "user"
                    and result_record.target_username
                    == session.get("username")
                )
            ]

        max_score = 100

        result_scores = []

        for result_record in result_records:
            answers = safe_json_dict_list(
                result_record.answers_json
            )

            result_check_items = check_items

            if (
                is_vehicle_checklist
                and result_record.checklist_snapshot_json
            ):
                result_snapshot = safe_json_dict(
                    result_record.checklist_snapshot_json
                )

                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get(
                            "items",
                            []
                        )
                        if item.get("item_type") == "check"
                    ]

            total_score = 0
            total_max_score = 0

            for item, answer in zip(
                result_check_items,
                answers
            ):
                if item.get("input_type") != "select":
                    continue

                numeric_choices = [
                    dashboard_score_value(choice)
                    for choice in item.get("choices", [])
                ]

                numeric_choices = [
                    value
                    for value in numeric_choices
                    if value is not None
                ]

                if not numeric_choices:
                    continue

                score_value = dashboard_score_value(
                    answer.get("value")
                )

                if score_value is None:
                    continue

                total_score += score_value
                total_max_score += max(numeric_choices)

            if total_max_score > 0:
                result_scores.append(
                    round(
                        total_score / total_max_score * 100,
                        1
                    )
                )

        score_distribution = {}

        for score in result_scores:
            score_value = float(score)
            score_label = (
                int(score_value)
                if score_value.is_integer()
                else score_value
            )

            score_distribution[score_label] = (
                score_distribution.get(score_label, 0) + 1
            )

        average_score = (
            round(
                sum(result_scores) / len(result_scores),
                1
            )
            if result_scores
            else None
        )

        if is_vehicle_checklist:
            for usage_vehicle_id in my_vehicle_record_ids:
                vehicle_result_records = [
                    result_record
                    for result_record in my_result_records
                    if result_record.vehicle_record_id == usage_vehicle_id
                ]

                vehicle_result_scores = []
                vehicle_category_stats = {}

                for result_record in vehicle_result_records:
                    answers = safe_json_dict_list(
                        result_record.answers_json
                    )

                    result_check_items = check_items

                    if result_record.checklist_snapshot_json:
                        result_snapshot = safe_json_dict(
                            result_record.checklist_snapshot_json
                        )

                        if result_snapshot:
                            result_check_items = [
                                item
                                for item in result_snapshot.get(
                                    "items",
                                    []
                                )
                                if item.get("item_type") == "check"
                            ]

                    total_score = 0
                    total_max_score = 0

                    for item, answer in zip(
                        result_check_items,
                        answers
                    ):
                        if item.get("input_type") != "select":
                            continue

                        numeric_choices = [
                            dashboard_score_value(choice)
                            for choice in item.get(
                                "choices",
                                []
                            )
                        ]

                        numeric_choices = [
                            value
                            for value in numeric_choices
                            if value is not None
                        ]

                        if not numeric_choices:
                            continue

                        score_value = dashboard_score_value(
                            answer.get("value")
                        )

                        if score_value is None:
                            continue

                        item_max_score = max(
                            numeric_choices
                        )

                        total_score += score_value
                        total_max_score += item_max_score

                        category = (
                            item.get("category")
                            or "その他"
                        ).strip()

                        if category not in vehicle_category_stats:
                            vehicle_category_stats[category] = {
                                "score": 0,
                                "max_score": 0,
                            }

                        vehicle_category_stats[
                            category
                        ]["score"] += score_value

                        vehicle_category_stats[
                            category
                        ]["max_score"] += item_max_score

                    if total_max_score > 0:
                        vehicle_result_scores.append(
                            round(
                                total_score
                                / total_max_score
                                * 100,
                                1
                            )
                        )

                vehicle_average_score = (
                    round(
                        sum(vehicle_result_scores)
                        / len(vehicle_result_scores),
                        1
                    )
                    if vehicle_result_scores
                    else None
                )

                vehicle_category_analysis = []

                for (
                    category,
                    stats
                ) in vehicle_category_stats.items():
                    if stats["max_score"] <= 0:
                        continue

                    score_rate = round(
                        stats["score"]
                        / stats["max_score"]
                        * 100,
                        1
                    )

                    vehicle_category_analysis.append({
                        "category": category,
                        "score_rate": score_rate,
                        "improvement_rate": round(
                            100 - score_rate,
                            1
                        ),
                    })

                vehicle_category_analysis.sort(
                    key=lambda item: item["score_rate"]
                )

                vehicle_category_analysis = (
                    vehicle_category_analysis[:2]
                )

                average_difference = (
                    round(
                        vehicle_average_score
                        - average_score,
                        1
                    )
                    if (
                        vehicle_average_score is not None
                        and average_score is not None
                    )
                    else None
                )

                usage_vehicle = Vehicle.query.filter_by(
                    company_code=company_code,
                    id=usage_vehicle_id,
                    deleted=False
                ).first()

                if not usage_vehicle:
                    continue

                my_checklist_summaries.append({
                    "id": checklist_record.id,
                    "name": checklist_record.name,
                    "target": checklist_record.target,
                    "vehicle_record_id": usage_vehicle_id,
                    "chassis_number": (
                        usage_vehicle.chassis_number
                        if usage_vehicle
                        else ""
                    ),
                    "target_user": user_name,
                    "target_username": session.get(
                        "username"
                    ),
                    "average_score": vehicle_average_score,
                    "overall_average_score": average_score,
                    "average_difference": average_difference,
                    "result_count": len(
                        vehicle_result_scores
                    ),
                    "max_score": max_score,
                    "category_analysis": (
                        vehicle_category_analysis
                    ),
                })

        else:
            my_result_scores = []

            for result_record in my_result_records:
                answers = safe_json_dict_list(
                    result_record.answers_json
                )

                result_check_items = check_items

                total_score = 0
                total_max_score = 0

                for item, answer in zip(
                    result_check_items,
                    answers
                ):
                    if item.get("input_type") != "select":
                        continue

                    numeric_choices = [
                        dashboard_score_value(choice)
                        for choice in item.get(
                            "choices",
                            []
                        )
                    ]

                    numeric_choices = [
                        value
                        for value in numeric_choices
                        if value is not None
                    ]

                    if not numeric_choices:
                        continue

                    score_value = dashboard_score_value(
                        answer.get("value")
                    )

                    if score_value is None:
                        continue

                    total_score += score_value
                    total_max_score += max(
                        numeric_choices
                    )

                if total_max_score > 0:
                    my_result_scores.append(
                        round(
                            total_score
                            / total_max_score
                            * 100,
                            1
                        )
                    )

            my_average_score = (
                round(
                    sum(my_result_scores)
                    / len(my_result_scores),
                    1
                )
                if my_result_scores
                else None
            )

            my_category_stats = {}

            for result_record in my_result_records:
                answers = safe_json_dict_list(
                    result_record.answers_json
                )

                for item, answer in zip(
                    check_items,
                    answers
                ):
                    if item.get("input_type") != "select":
                        continue

                    category = (
                        item.get("category")
                        or "その他"
                    ).strip()

                    numeric_choices = []

                    for choice in item.get(
                        "choices",
                        []
                    ):
                        score_value = (
                            dashboard_score_value(
                                choice
                            )
                        )

                        if score_value is not None:
                            numeric_choices.append(
                                score_value
                            )

                    if not numeric_choices:
                        continue

                    score = dashboard_score_value(
                        answer.get("value")
                    )

                    if score is None:
                        continue

                    item_max_score = max(
                        numeric_choices
                    )

                    if category not in my_category_stats:
                        my_category_stats[category] = {
                            "score": 0,
                            "max_score": 0,
                        }

                    my_category_stats[
                        category
                    ]["score"] += score

                    my_category_stats[
                        category
                    ]["max_score"] += item_max_score

            my_category_analysis = []

            for (
                category,
                stats
            ) in my_category_stats.items():
                if stats["max_score"] <= 0:
                    continue

                score_rate = round(
                    stats["score"]
                    / stats["max_score"]
                    * 100,
                    1
                )

                my_category_analysis.append({
                    "category": category,
                    "score_rate": score_rate,
                    "improvement_rate": round(
                        100 - score_rate,
                        1
                    ),
                })

            my_category_analysis.sort(
                key=lambda item: item["score_rate"]
            )

            my_category_analysis = (
                my_category_analysis[:2]
            )

            if my_average_score is not None:
                average_difference = (
                    round(
                        my_average_score
                        - average_score,
                        1
                    )
                    if average_score is not None
                    else None
                )

                my_checklist_summaries.append({
                    "id": checklist_record.id,
                    "name": checklist_record.name,
                    "target": checklist_record.target,
                    "target_user": user_name,
                    "target_username": session.get(
                        "username"
                    ),
                    "average_score": my_average_score,
                    "overall_average_score": average_score,
                    "average_difference": average_difference,
                    "result_count": len(
                        my_result_scores
                    ),
                    "max_score": max_score,
                    "category_analysis": (
                        my_category_analysis
                    ),
                })

        # カテゴリ別の評価を集計
        category_stats = {}

        for result_record in result_records:
            answers = safe_json_dict_list(
                result_record.answers_json
            )

            result_check_items = check_items

            if (
                is_vehicle_checklist
                and result_record.checklist_snapshot_json
            ):
                result_snapshot = safe_json_dict(
                    result_record.checklist_snapshot_json
                )

                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get(
                            "items",
                            []
                        )
                        if item.get("item_type") == "check"
                    ]

            for item, answer in zip(
                result_check_items,
                answers
            ):
                if item.get("input_type") != "select":
                    continue

                category = (
                    item.get("category") or "その他"
                ).strip()

                numeric_choices = []

                for choice in item.get("choices", []):
                    score_value = dashboard_score_value(choice)

                    if score_value is not None:
                        numeric_choices.append(score_value)

                if not numeric_choices:
                    continue

                score = dashboard_score_value(
                    answer.get("value")
                )

                if score is None:
                    continue

                item_max_score = max(numeric_choices)

                if category not in category_stats:
                    category_stats[category] = {
                        "score": 0,
                        "max_score": 0,
                        "count": 0,
                    }

                category_stats[category]["score"] += score
                category_stats[category]["max_score"] += item_max_score
                category_stats[category]["count"] += 1

        category_analysis = []

        for category, stats in category_stats.items():
            if stats["max_score"] <= 0:
                continue

            score_rate = round(
                stats["score"] / stats["max_score"] * 100,
                1
            )

            category_analysis.append({
                "category": category,
                "score_rate": score_rate,
                "improvement_rate": round(
                    100 - score_rate,
                    1
                ),
                "count": stats["count"],
            })

        # 改善が必要な順
        category_analysis.sort(
            key=lambda item: item["score_rate"]
        )

        # 点検項目別の評価を集計
        item_stats = {}

        for result_record in result_records:
            answers = safe_json_dict_list(
                result_record.answers_json
            )

            result_check_items = check_items

            if (
                is_vehicle_checklist
                and result_record.checklist_snapshot_json
            ):
                result_snapshot = safe_json_dict(
                    result_record.checklist_snapshot_json
                )

                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get(
                            "items",
                            []
                        )
                        if item.get("item_type") == "check"
                    ]

            for item, answer in zip(
                result_check_items,
                answers
            ):
                if item.get("input_type") != "select":
                    continue

                content = (
                    item.get("content") or "項目名なし"
                ).strip()

                category = (
                    item.get("category") or "その他"
                ).strip()

                numeric_choices = []

                for choice in item.get("choices", []):
                    score_value = dashboard_score_value(choice)

                    if score_value is not None:
                        numeric_choices.append(score_value)

                if not numeric_choices:
                    continue

                score = dashboard_score_value(
                    answer.get("value")
                )

                if score is None:
                    continue

                item_max_score = max(numeric_choices)

                key = (category, content)

                if key not in item_stats:
                    item_stats[key] = {
                        "score": 0,
                        "max_score": 0,
                        "count": 0,
                        "result": result_record,
                        "lowest_score": score,
                    }

                item_stats[key]["score"] += score
                item_stats[key]["max_score"] += item_max_score
                item_stats[key]["count"] += 1

                if score < item_stats[key]["lowest_score"]:
                    item_stats[key]["lowest_score"] = score
                    item_stats[key]["result"] = result_record

        improvement_items = []

        for (category, content), stats in item_stats.items():
            if stats["max_score"] <= 0:
                continue

            score_rate = round(
                stats["score"] / stats["max_score"] * 100,
                1
            )

            result_record = stats.get("result")
            result_url = ""

            if result_record:
                if is_vehicle_checklist:
                    if checklist.get("frequency_unit") == "year":
                        active_day = result_record.year
                    elif checklist.get("display_type") == "month":
                        active_day = result_record.day
                    else:
                        active_day = result_record.month

                    result_url = url_for(
                        "vehicle_checklist_results",
                        index=checklist_record.id,
                        vehicle_record_id=result_record.vehicle_record_id,
                        year=result_record.year,
                        month=result_record.month,
                        active_day=active_day,
                    )
                else:
                    result_url = url_for(
                        "checklist_result_detail",
                        result_index=result_record.id,
                    )

            improvement_items.append({
                "category": category,
                "content": content,
                "score_rate": score_rate,
                "improvement_rate": round(
                    100 - score_rate,
                    1
                ),
                "count": stats["count"],
                "result_url": result_url,
            })

        improvement_items.sort(
            key=lambda item: item["improvement_rate"],
            reverse=True
        )

        improvement_items = improvement_items[:5]
        target_stats = {}

        for result_record in result_records:

            if is_vehicle_checklist:
                target_type = "vehicle"

                target_vehicle_record = Vehicle.query.filter_by(
                    company_code=company_code,
                    id=result_record.vehicle_record_id
                ).first()

                if not target_vehicle_record:
                    continue

                target_label = target_vehicle_record.chassis_number

            else:
                target_type = result_record.target_type

                if target_type == "user":
                    # 個人名は管理者だけ集計対象にする
                    if session.get("role") not in ["admin", "itc"]:
                        continue

                    target_label = result_record.target_user

                elif target_type == "vehicle":
                    target_vehicle_record = Vehicle.query.filter_by(
                        company_code=company_code,
                        id=result_record.target_vehicle_record_id
                    ).first()

                    if not target_vehicle_record:
                        continue

                    target_label = target_vehicle_record.chassis_number

                elif target_type == "office":
                    target_label = result_record.target_office

                else:
                    continue

            if not target_label:
                continue

            answers = safe_json_dict_list(
                result_record.answers_json
            )

            result_check_items = check_items

            if (
                is_vehicle_checklist
                and result_record.checklist_snapshot_json
            ):
                result_snapshot = safe_json_dict(
                    result_record.checklist_snapshot_json
                )

                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get(
                            "items",
                            []
                        )
                        if item.get("item_type") == "check"
                    ]

            target_score = 0
            target_max_score = 0

            for item, answer in zip(
                result_check_items,
                answers
            ):
                if item.get("input_type") != "select":
                    continue

                numeric_choices = []

                for choice in item.get("choices", []):
                    score_value = dashboard_score_value(choice)

                    if score_value is not None:
                        numeric_choices.append(score_value)

                if not numeric_choices:
                    continue

                score = dashboard_score_value(
                    answer.get("value")
                )

                if score is None:
                    continue

                target_score += score
                target_max_score += max(numeric_choices)

            if target_max_score <= 0:
                continue

            key = (target_type, target_label)

            if key not in target_stats:
                target_stats[key] = {
                    "score": 0,
                    "max_score": 0,
                    "count": 0,
                    "vehicle_record_id": (
                        result_record.vehicle_record_id
                        if is_vehicle_checklist
                        else result_record.target_vehicle_record_id
                        if target_type == "vehicle"
                        else None
                    ),
                }

            target_stats[key]["score"] += target_score
            target_stats[key]["max_score"] += target_max_score
            target_stats[key]["count"] += 1


        target_analysis = []

        for (target_type, target_label), stats in target_stats.items():
            if stats["max_score"] <= 0:
                continue

            score_rate = round(
                stats["score"] / stats["max_score"] * 100,
                1
            )

            target_analysis.append({
                "target_type": target_type,
                "target_label": target_label,
                "vehicle_record_id": stats.get("vehicle_record_id"),
                "score_rate": score_rate,
                "improvement_rate": round(
                    100 - score_rate,
                    1
                ),
                "count": stats["count"],
            })

        target_analysis.sort(
            key=lambda item: item["improvement_rate"],
            reverse=True
        )

        target_analysis = target_analysis[:5]

        for target in target_analysis:

            target["vehicle_type"] = ""
            target["body_type"] = ""

            if target["target_type"] == "vehicle":

                target_vehicle = Vehicle.query.filter_by(
                    company_code=company_code,
                    id=target.get("vehicle_record_id")
                ).first()

                if target_vehicle:
                    target["vehicle_record_id"] = target_vehicle.id
                    target["vehicle_type"] = target_vehicle.type or ""
                    target["body_type"] = target_vehicle.body_type or ""

        if not has_dashboard_score:
            continue

        checklist_score_summaries.append({
            "id": checklist_record.id,
            "name": checklist_record.name,
            "target": checklist_record.target,
            "average_score": average_score,
            "result_count": len(result_scores),
            "scores": result_scores,
            "max_score": max_score,
            "score_distribution": score_distribution,
            "category_analysis": category_analysis,
            "target_analysis": target_analysis,
            "improvement_items": improvement_items,
        })

    my_vehicles = Vehicle.query.filter(
        Vehicle.company_code == company_code,
        Vehicle.deleted == False,
        Vehicle.id.in_(my_vehicle_record_ids)
    ).all() if my_vehicle_record_ids else []

    my_vehicle_analysis = {}

    for vehicle in my_vehicles:

        vehicle_result_rates = []
        vehicle_result_count = 0
        vehicle_latest_date = ""
        vehicle_category_stats = {}

        for checklist_record in score_checklists:

            if checklist_record.target != "車両管理":
                continue

            checklist = checklist_to_dict(
                checklist_record
            )

            vehicle_results = (
                VehicleChecklistResult.query.filter_by(
                    company_code=company_code,
                    checklist_id=checklist_record.id,
                    vehicle_record_id=vehicle.id
                )
                .filter(
                    VehicleChecklistResult.checked_date
                    >= dashboard_start_date
                )
                .all()
            )

            for result_record in vehicle_results:

                answers = safe_json_dict_list(
                    result_record.answers_json
                )

                result_checklist = checklist

                if result_record.checklist_snapshot_json:
                    snapshot = safe_json_dict(
                        result_record.checklist_snapshot_json
                    )

                    if snapshot:
                        result_checklist = snapshot

                check_items = [
                    item
                    for item in result_checklist.get("items", [])
                    if item.get("item_type") == "check"
                ]

                result_score = 0
                result_max_score = 0

                for item, answer in zip(
                    check_items,
                    answers
                ):

                    if item.get("input_type") != "select":
                        continue

                    numeric_choices = [
                        dashboard_score_value(choice)
                        for choice in item.get("choices", [])
                    ]

                    numeric_choices = [
                        value
                        for value in numeric_choices
                        if value is not None
                    ]

                    if not numeric_choices:
                        continue

                    score = dashboard_score_value(
                        answer.get("value")
                    )

                    if score is None:
                        continue

                    result_score += score
                    result_max_score += max(
                        numeric_choices
                    )
                    category = (
                        item.get("category")
                        or "その他"
                    )

                    if category not in vehicle_category_stats:
                        vehicle_category_stats[category] = {
                            "score": 0,
                            "max_score": 0,
                        }

                    vehicle_category_stats[category]["score"] += score
                    vehicle_category_stats[category]["max_score"] += max(
                        numeric_choices
                    )

                if result_max_score > 0:
                    vehicle_result_rates.append(
                        round(
                            result_score
                            / result_max_score
                            * 100,
                            1
                        )
                    )
                    vehicle_result_count += 1

                if (
                    result_record.checked_date
                    and result_record.checked_date
                    > vehicle_latest_date
                ):
                    vehicle_latest_date = (
                        result_record.checked_date
                    )

        score_rate = None

        if vehicle_result_rates:
            score_rate = round(
                sum(vehicle_result_rates)
                / len(vehicle_result_rates),
                1
            )

        vehicle_category_analysis = []

        for category, stats in vehicle_category_stats.items():

            if stats["max_score"] <= 0:
                continue

            category_score_rate = round(
                stats["score"]
                / stats["max_score"]
                * 100,
                1
            )

            vehicle_category_analysis.append({
                "category": category,
                "score_rate": category_score_rate,
                "improvement_rate": round(
                    100 - category_score_rate,
                    1
                ),
            })

        vehicle_category_analysis.sort(
            key=lambda item: item["improvement_rate"],
            reverse=True
        )

        vehicle_category_analysis = (
            vehicle_category_analysis[:2]
        )

        my_vehicle_analysis[
            vehicle.id
        ] = {
            "score_rate": score_rate,
            "result_count": vehicle_result_count,
            "latest_date": vehicle_latest_date,
            "category_analysis": vehicle_category_analysis,
        }

    return render_template(
        "index.html",
        my_safe_days=my_safe_days,
        ranking=ranking,
        my_good_count=my_good_count,
        my_pending_pointouts=my_pending_pointouts,
        inspection_alerts=inspection_alerts,
        setup_tasks=setup_tasks,
        checklist_score_summaries=checklist_score_summaries,
        my_checklist_summaries=my_checklist_summaries,
        my_user_name=user_name,
        my_vehicles=my_vehicles,
        my_vehicle_analysis=my_vehicle_analysis,
        dashboard_settings=dashboard_settings,
        dashboard_offices=offices_for_current_company(),
        is_dashboard_admin=session.get("role") in ["admin", "itc"],
    )

@app.route("/notifications")
def notifications():
    username = session.get("username")

    items = []

    notification_records = Notification.query.filter(
        Notification.company_code == session.get("company_code"),
        Notification.target_username == username
    ).order_by(Notification.id.desc()).all()

    for notification in notification_records:
        items.append({
            "id": notification.id,
            "index": notification.id,
            "target_user": notification.target_user,
            "title": notification.title,
            "message": notification.message,
            "link": notification.link,
            "files": safe_json_str_list(
                notification.files_json
            ),
            "read": notification.read,
            "created_at": notification.created_at,
        })

    return render_template(
        "notifications.html",
        notifications=items
    )

@app.route("/notifications/<int:index>")
def notification_detail(index):
    notification = Notification.query.filter(
        Notification.id == index,
        Notification.company_code == session.get("company_code"),
        Notification.target_username == session.get("username")
    ).first()

    if not notification:
        return redirect("/notifications")

    notification.read = True
    db.session.commit()

    notification_dict = {
        "id": notification.id,
        "index": notification.id,
        "target_user": notification.target_user,
        "title": notification.title,
        "message": notification.message,
        "link": notification.link,
        "files": safe_json_str_list(
            notification.files_json
        ),
        "read": notification.read,
        "created_at": notification.created_at,
    }

    return render_template(
        "notification_detail.html",
        notification=notification_dict,
        index=notification.id
    )

@app.route("/notifications/<int:index>/delete", methods=["POST"])
@limiter.limit("20 per minute")
def delete_notification(index):
    notification = Notification.query.filter(
        Notification.id == index,
        Notification.company_code == session.get("company_code"),
        Notification.target_username == session.get("username")
    ).first()

    if not notification:
        return redirect("/notifications")

    add_audit_log(
        action="notification_deleted",
        target_type="notification",
        target_id=notification.id,
        detail=f"通知削除: {notification.title}",
        company_code=notification.company_code,
    )

    db.session.delete(notification)
    db.session.commit()

    return redirect("/notifications")

@app.route("/itc")
def itc_dashboard():
    if not require_itc():
        return redirect("/")

    companies = Company.query.order_by(
        Company.company_name.asc()
    ).all()

    company_summaries = []

    for company in companies:
        usage = CompanyUsageSummary.query.filter_by(
            company_code=company.company_code
        ).first()

        vehicle_count = (
            usage.vehicle_count
            if usage
            else 0
        )

        company_summaries.append({
            "id": company.id,
            "company_code": company.company_code,
            "company_name": company.company_name,
            "vehicle_limit": company.vehicle_limit,
            "active": company.active,
            "vehicle_count": vehicle_count,
            "remaining_vehicles": (
                company.vehicle_limit - vehicle_count
            ),
            "user_count": usage.user_count if usage else 0,
            "login_count": usage.login_count if usage else 0,
            "checklist_result_count": (
                usage.checklist_result_count if usage else 0
            ),
            "last_used_at": usage.last_used_at if usage else None,
        })

    company_code = session.get("company_code")

    news_items = []

    news_records = News.query.filter_by(
        company_code=company_code
    ).order_by(
        News.id.desc()
    ).all()

    for news in news_records:
        visible = False

        if news.target_type in ["all", "admins"]:
            visible = True

        elif (
            news.target_type == "company"
            and news.target_value == company_code
        ):
            visible = True

        elif news.target_type == "office":
            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=news.target_value
            ).first()

            visible = valid_office is not None

        elif news.target_type == "user":
            valid_user = User.query.filter_by(
                company_code=company_code,
                username=news.target_value
            ).first()

            visible = valid_user is not None

        if not visible:
            continue

        news_items.append({
            "id": news.id,
            "index": news.id,
            "title": news.title,
            "message": news.message,
            "files": safe_json_str_list(
                news.files_json
            ),
            "target_type": news.target_type,
            "target_value": news.target_value,
            "created_at": news.created_at,
        })

    return render_template(
        "itc_dashboard.html",
        companies=company_summaries,
        news=news_items
    )

@app.route("/itc/companies/new", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def itc_new_company():
    if not require_itc():
        return redirect("/")

    if request.method == "POST":
        company_code = request.form.get(
            "company_code",
            ""
        ).strip()
        company_name = request.form.get(
            "company_name",
            ""
        ).strip()

        if not company_code:
            return "会社コードを入力してください。", 400

        if len(company_code) > 50:
            return "会社コードは50文字以内で入力してください。", 400

        if not re.fullmatch(r"[A-Za-z0-9_-]+", company_code):
            return (
                "会社コードは半角英数字・ハイフン・"
                "アンダースコアのみ使用できます。",
                400
            )

        if not company_name:
            return "会社名を入力してください。", 400

        if len(company_name) > 100:
            return "会社名は100文字以内で入力してください。", 400

        if Company.query.filter_by(
            company_code=company_code
        ).first():
            return "この会社コードはすでに登録されています。", 409

        company = Company(
            company_code=company_code,
            company_name=company_name,
            vehicle_limit=parse_nonnegative_int(
                request.form.get("vehicle_limit"),
                "車両上限数"
            ),
            active=True,
        )

        db.session.add(company)

        default_content_types = [
            "落下",
            "車両",
            "環境",
            "荷扱い",
            "ルール違反",
            "Good",
            "その他",
        ]

        for name in default_content_types:
            db.session.add(
                PatrolContentType(
                    company_code=company.company_code,
                    name=name
                )
            )

        add_audit_log(
            action="company_created",
            target_type="company",
            target_id=company.company_code,
            detail=f"会社登録: {company.company_name}",
            company_code=session.get("company_code"),
        )
        db.session.commit()

        return redirect("/itc")

    return render_template(
        "itc_company_form.html",
        company=None,
        index=None,
        mode="new"
    )

@app.route("/itc/companies/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def itc_edit_company(index):
    if not require_itc():
        return redirect("/")

    company = Company.query.filter_by(
        id=index
    ).first()

    if not company:
        return redirect("/itc")

    if request.method == "POST":
        company_name = request.form.get(
            "company_name",
            ""
        ).strip()

        if not company_name:
            return "会社名を入力してください。", 400

        if len(company_name) > 100:
            return "会社名は100文字以内で入力してください。", 400

        company.company_name = company_name
        company.vehicle_limit = parse_nonnegative_int(
            request.form.get("vehicle_limit"),
            "車両上限数"
        )
        company.active = request.form.get("active") == "1"

        add_audit_log(
            action="company_updated",
            target_type="company",
            target_id=company.company_code,
            detail=f"会社情報変更: {company.company_name}",
            company_code=session.get("company_code"),
        )

        db.session.commit()

        return redirect("/itc")

    company_dict = {
        "company_code": company.company_code,
        "company_name": company.company_name,
        "vehicle_limit": company.vehicle_limit,
        "active": company.active,
    }

    return render_template(
        "itc_company_form.html",
        company=company_dict,
        index=company.id,
        mode="edit"
    )

@app.route("/safety")
def safety():
    return redirect("/pointouts")

@app.route("/pointouts")
def pointouts():
    role = session.get("role")

    view_type = request.args.get("type", "user")
    if view_type not in PATROL_VIEW_TYPES:
        view_type = "user"

    keyword = request.args.get("keyword", "").strip()
    category = request.args.get("category", "").strip()
    mine = request.args.get("mine") == "1"
    pending = request.args.get("pending") == "1"

    if len(keyword) > 100:
        return "検索条件が長すぎます。", 400

    query = PatrolResult.query.filter(
        PatrolResult.company_code == session.get("company_code"),
        PatrolResult.target_type == view_type
    )

    if mine and view_type == "user":
        query = query.filter(
            PatrolResult.target_username
            == session.get("username")
        )

    if pending:
        query = query.filter(
            PatrolResult.category != "Good",
            PatrolResult.approval_status != "承認済み"
        )

    if category:
        query = query.filter(
            PatrolResult.category == category
        )

    if keyword:
        keyword_like = f"%{keyword}%"

        if view_type == "user":
            query = query.filter(
                PatrolResult.target_user.ilike(keyword_like)
            )
        elif view_type == "delivery_place":
            query = query.filter(
                PatrolResult.delivery_place.ilike(keyword_like)
            )

    result_records = query.order_by(
        PatrolResult.id.desc()
    ).all()

    visible_results = []

    for result_record in result_records:
        result = patrol_result_to_dict(result_record)

        if not can_view_patrol_result(result):
            continue

        result["can_manage"] = can_edit_patrol_result(result)
        visible_results.append(result)
    allowed_page_sizes = {5, 8, 10}

    try:
        page_size = int(
            request.args.get(
                "page_size",
                "10"
            )
        )
    except ValueError:
        page_size = 10

    if page_size not in allowed_page_sizes:
        page_size = 10

    try:
        page = max(
            int(
                request.args.get(
                    "page",
                    "1"
                )
            ),
            1
        )
    except ValueError:
        page = 1

    total_results = len(
        visible_results
    )

    total_pages = max(
        1,
        (
            total_results
            + page_size
            - 1
        ) // page_size
    )

    if page > total_pages:
        page = total_pages

    start_index = (
        page - 1
    ) * page_size

    paginated_results = (
        visible_results[
            start_index:
            start_index + page_size
        ]
    )

    driver_options = Driver.query.filter(
        Driver.company_code == session.get("company_code")
    ).order_by(
        Driver.name.asc()
    ).all()

    return render_template(
        "pointouts.html",
        patrol_results=paginated_results,
        total_results=total_results,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        view_type=view_type,
        keyword=keyword,
        role=role,
        show_target_user=view_type == "user",
        drivers=driver_options,
        delivery_places=delivery_places_for_current_company(),
    )


@app.route("/pointouts/new", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
def new_pointout():
    if request.method == "POST":
        company_code = session.get("company_code")
        form_errors = []

        target_type = request.form.get(
            "target_type",
            ""
        ).strip()

        target_user = request.form.get(
            "target_user",
            ""
        ).strip()
        target_username = ""

        delivery_place = request.form.get(
            "delivery_place",
            ""
        ).strip()

        content_type = request.form.get(
            "content_type",
            ""
        ).strip()

        category = request.form.get(
            "category",
            ""
        ).strip()

        content = request.form.get(
            "content",
            ""
        ).strip()

        date = request.form.get(
            "date",
            ""
        ).strip()
        if category not in {
            "安全",
            "品質",
            "Good"
        }:
            return "分類が不正です。", 400

        if not date:
            form_errors.append(
                "発生日を入力してください。"
            )
        else:
            try:
                datetime.strptime(
                    date,
                    "%Y-%m-%d"
                )
            except ValueError:
                form_errors.append(
                    "発生日が不正です。"
                )        

        # =========================
        # 対象種別検証
        # =========================

        if target_type not in PATROL_VIEW_TYPES:
            return "対象種別が不正です。", 400

        target_office = session.get("office") or ""

        # =========================
        # 対象ユーザー検証
        # =========================

        if target_type == "user":
            if not target_user:
                form_errors.append(
                    "対象ユーザーを選択してください。"
                )
            else:
                target_driver = Driver.query.filter_by(
                    company_code=company_code,
                    employee_id=target_user
                ).first()

                if not target_driver:
                    form_errors.append(
                        "対象ユーザーが不正です。"
                    )
                else:
                    target_user_record = User.query.filter_by(
                        company_code=company_code,
                        username=target_driver.employee_id
                    ).first()

                    if not target_user_record:
                        form_errors.append(
                            "対象ユーザー情報が不正です。"
                        )
                    else:
                        target_username = target_user_record.username
                        target_user = target_driver.name
                        target_office = target_driver.office or ""

            delivery_place = ""

        # =========================
        # 納入先検証
        # =========================

        elif target_type == "delivery_place":
            if not delivery_place:
                form_errors.append(
                    "納入先を選択してください。"
                )

            if delivery_place:
                valid_delivery_place = DeliveryPlace.query.filter_by(
                    company_code=company_code,
                    name=delivery_place
                ).first()

                if not valid_delivery_place:
                    form_errors.append(
                        "納入先が不正です。"
                    )

            target_user = ""

        # =========================
        # 内容区分検証
        # =========================

        if content_type:
            valid_content_type = PatrolContentType.query.filter_by(
                company_code=company_code,
                name=content_type
            ).first()

            if not valid_content_type:
                return "内容区分が不正です。", 400

        if len(content) > 5000:
            form_errors.append(
                "内容は5000文字以内で入力してください。"
            )

        if form_errors:
            return return_form_errors(form_errors)

        # =========================
        # 添付ファイル
        # =========================

        uploaded_files = request.files.getlist("files")

        file_names = []

        for file in uploaded_files:
            filename = save_uploaded_file(file)

            if filename:
                file_names.append(filename)

        # =========================
        # 登録
        # =========================

        result = PatrolResult(
            company_code=company_code,
            created_by_username=session.get("username"),
            created_by_name=session.get("name"),
            date=date,
            office=target_office,
            category=category,
            content_type=content_type,
            target_type=target_type,
            target_user=target_user,
            target_username=(
                target_username
                if target_type == "user"
                else ""
            ),
            delivery_place=delivery_place,
            content=content,
            files_json=json.dumps(
                file_names,
                ensure_ascii=False
            ),
            countermeasure="",
            approval_status="未対応",
            reject_reason=""
        )

        db.session.add(result)
        db.session.commit()

        # 個人対象のときだけ通知
        if target_type == "user":
            add_notification(
                result.target_user,
                "安全パトロール確認依頼",
                "あなたに確認が必要な安全パトロールがあります。",
                f"/pointouts/{result.id}",
                company_code=company_code,
                target_username=result.target_username
            )

        notify_mentions(
            result.content,
            f"/pointouts/{result.id}"
        )

        if target_type == "delivery_place":
            return redirect(
                "/pointouts?type=delivery_place"
            )

        return redirect(
            "/pointouts?type=user"
        )
    form_target_type = session.pop(
        "pointout_form_target_type",
        "user"
    )

    form_data = session.pop(
        "pointout_form_data",
        {}
    )

    return render_template(
        "new_pointout.html",
        form_target_type=form_target_type,
        form_data=form_data,
        drivers=drivers_for_current_company(),
        delivery_places=delivery_places_for_current_company(),
        manuals=manuals_for_current_company(),
        content_types=patrol_content_types_for_current_company(),
    )

@app.route("/pointouts/<int:index>")
def pointout_detail(index):
    result_record = PatrolResult.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/pointouts")

    result = patrol_result_to_dict(result_record)

    if not can_view_patrol_result(result):
        return redirect("/pointouts")

    return render_template(
        "pointout_detail.html",
        result=result,
        index=result_record.id,
        manuals=manuals_for_current_company(),
        can_manage=can_edit_patrol_result(result),
        can_countermeasure=can_countermeasure_patrol_result(
            result
        ),
        can_approve=can_approve_patrol_result(result),
    )
    
@app.route("/pointouts/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
def edit_pointout(index):

    result_record = PatrolResult.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/pointouts")

    if result_record.approval_status == "承認済み":
        return redirect(f"/pointouts/{index}")

    result = patrol_result_to_dict(result_record)

    if not can_edit_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    if request.method == "POST":
        company_code = session.get("company_code")

        date = request.form.get(
            "date",
            ""
        ).strip()

        category = request.form.get(
            "category",
            ""
        ).strip()

        if category not in {
            "安全",
            "品質",
            "Good"
        }:
            return "分類が不正です。", 400

        if not date:
            return "発生日を入力してください。", 400

        try:
            datetime.strptime(
                date,
                "%Y-%m-%d"
            )
        except ValueError:
            return "発生日が不正です。", 400

        content_type = request.form.get(
            "content_type",
            ""
        ).strip()

        content = request.form.get(
            "content",
            ""
        ).strip()

        if len(content) > 5000:
            return "内容は5000文字以内で入力してください。", 400

        # =========================
        # 内容区分検証
        # =========================

        if content_type:
            valid_content_type = PatrolContentType.query.filter_by(
                company_code=company_code,
                name=content_type
            ).first()

            if not valid_content_type:
                return "内容区分が不正です。", 400

        # =========================
        # 対象ユーザー検証
        # =========================

        if result_record.target_type == "user":
            target_username = request.form.get(
                "target_user",
                ""
            ).strip()

            if not target_username:
                return "対象ユーザーを選択してください。", 400

            target_driver = Driver.query.filter_by(
                company_code=company_code,
                employee_id=target_username
            ).first()

            if not target_driver:
                return "対象ユーザーが不正です。", 400

            target_user_record = User.query.filter_by(
                company_code=company_code,
                username=target_driver.employee_id
            ).first()

            if not target_user_record:
                return "対象ユーザー情報が不正です。", 400

            result_record.target_user = (
                target_driver.name
            )

            result_record.target_username = (
                target_user_record.username
            )

            result_record.office = (
                target_driver.office or ""
            )

            result_record.delivery_place = ""

        # =========================
        # 納入先検証
        # =========================

        elif result_record.target_type == "delivery_place":
            delivery_place = request.form.get(
                "delivery_place",
                ""
            ).strip()

            if not delivery_place:
                return "納入先を選択してください。", 400

            valid_delivery_place = DeliveryPlace.query.filter_by(
                company_code=company_code,
                name=delivery_place
            ).first()

            if not valid_delivery_place:
                return "納入先が不正です。", 400

            result_record.delivery_place = delivery_place
            result_record.target_user = ""
            result_record.target_username = ""

        else:
            return "対象種別が不正です。", 400

        # =========================
        # 基本情報更新
        # =========================

        result_record.date = date
        result_record.category = category
        result_record.content_type = content_type
        result_record.content = content

        # =========================
        # 既存添付
        # =========================

        files = safe_json_str_list(
            result_record.files_json
        )

        delete_files = request.form.getlist(
            "delete_files"
        )

        if len(delete_files) > 50:
            return (
                "一度に削除できる添付ファイルは50件までです。",
                400
            )

        pending_delete_files = []

        for delete_file in delete_files:
            delete_file = os.path.basename(
                delete_file
            )

            if delete_file not in files:
                continue

            files.remove(delete_file)
            pending_delete_files.append(delete_file)

        # =========================
        # 新規添付
        # =========================

        uploaded_files = request.files.getlist(
            "files"
        )

        try:
            for file in uploaded_files:
                filename = save_uploaded_file(file)

                if filename:
                    files.append(filename)

        except UploadValidationError as error:
            db.session.rollback()

            result = patrol_result_to_dict(
                result_record
            )

            return render_template(
                "edit_pointout.html",
                result=result,
                index=result_record.id,
                drivers=drivers_for_current_company(),
                delivery_places=delivery_places_for_current_company(),
                manuals=manuals_for_current_company(),
                error=str(error),
            ), 400

        result_record.files_json = json.dumps(
            files,
            ensure_ascii=False
        )

        db.session.commit()

        for delete_file in pending_delete_files:
            deleted = False

            if s3_client and S3_BUCKET_NAME:
                try:
                    s3_client.delete_object(
                        Bucket=S3_BUCKET_NAME,
                        Key=(
                            f"uploads/"
                            f"{company_code}/"
                            f"{delete_file}"
                        )
                    )
                    deleted = True
                except ClientError:
                    print(
                        "S3添付ファイル削除エラー"
                    )
            else:
                safe_file_name = secure_filename(delete_file)

                if not safe_file_name:
                    continue

                file_path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    company_code,
                    safe_file_name
                )

                if os.path.exists(file_path):
                    os.remove(file_path)

                deleted = True

            if deleted:
                add_audit_log(
                    action="file_deleted",
                    target_type="file",
                    target_id=delete_file,
                    detail="安全パトロール添付ファイル削除",
                    company_code=company_code,
                )

        db.session.commit()

        notify_mentions(
            result_record.content,
            f"/pointouts/{result_record.id}"
        )

        return redirect(
            f"/pointouts/{result_record.id}"
        )

    return render_template(
        "edit_pointout.html",
        result=result,
        index=result_record.id,
        drivers=drivers_for_current_company(),
        delivery_places=delivery_places_for_current_company(),
        manuals=manuals_for_current_company(),
    )

@app.route("/pointouts/<int:index>/countermeasure/new")
def new_countermeasure(index):
    result_record = PatrolResult.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/pointouts")

    result = patrol_result_to_dict(result_record)

    if not can_countermeasure_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    return render_template(
        "countermeasure.html",
        result=result,
        index=result_record.id
    )


@app.route("/pointouts/<int:index>/countermeasure", methods=["POST"])
@limiter.limit("20 per minute")
def register_countermeasure(index):
    result_record = PatrolResult.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/pointouts")

    if result_record.approval_status == "承認済み":
        return redirect(f"/pointouts/{index}")

    result = patrol_result_to_dict(result_record)

    if not can_countermeasure_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    countermeasure = request.form.get(
        "countermeasure",
        ""
    ).strip()

    if len(countermeasure) > 5000:
        return "是正内容は5000文字以内で入力してください。", 400

    result_record.countermeasure = countermeasure

    result_record.countermeasure_by = (
        session.get("name")
    )

    result_record.countermeasure_by_username = (
        session.get("username")
    )

    result_record.approval_status = "承認待ち"
    result_record.reject_reason = ""

    db.session.commit()

    notify_mentions(
        result_record.countermeasure,
        f"/pointouts/{result_record.id}"
    )

    return redirect(f"/pointouts/{result_record.id}")


@app.route("/pointouts/<int:index>/approve", methods=["POST"])
@limiter.limit("20 per minute")
def approve_countermeasure(index):
    result_record = PatrolResult.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/pointouts")

    if result_record.approval_status != "承認待ち":
        return redirect(f"/pointouts/{index}")

    result = patrol_result_to_dict(result_record)

    if not can_approve_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    result_record.approval_status = "承認済み"
    result_record.reject_reason = ""

    notify_usernames = {
        username
        for username in [
            result_record.created_by_username,
            result_record.target_username,
            result_record.countermeasure_by_username
        ]
        if username
    }

    db.session.commit()

    for target_username in notify_usernames:
        target_user = User.query.filter_by(
            company_code=result_record.company_code,
            username=target_username
        ).first()

        if not target_user:
            continue

        add_notification(
            target_user.name,
            "安全パトロールが承認されました",
            "安全パトロールの対応が承認されました。",
            f"/pointouts/{result_record.id}",
            company_code=result_record.company_code,
            target_username=target_user.username
        )

    return redirect(f"/pointouts/{result_record.id}")


@app.route("/pointouts/<int:index>/reject", methods=["POST"])
@limiter.limit("20 per minute")
def reject_countermeasure(index):
    result_record = PatrolResult.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/pointouts")

    if result_record.approval_status != "承認待ち":
        return redirect(f"/pointouts/{index}")

    result = patrol_result_to_dict(result_record)

    if not can_approve_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    reject_reason = request.form.get(
        "reject_reason",
        ""
    ).strip()

    if len(reject_reason) > 5000:
        return "差し戻し理由は5000文字以内で入力してください。", 400

    result_record.approval_status = "差し戻し"
    result_record.reject_reason = reject_reason

    notify_usernames = set()

    if result_record.created_by_username:
        notify_usernames.add(
            result_record.created_by_username
        )

    if result_record.target_username:
        notify_usernames.add(
            result_record.target_username
        )

    if result_record.countermeasure_by_username:
        notify_usernames.add(
            result_record.countermeasure_by_username
        )

    db.session.commit()

    for target_username in notify_usernames:
        target_user = User.query.filter_by(
            company_code=result_record.company_code,
            username=target_username
        ).first()

        if not target_user:
            continue

        add_notification(
            target_user.name,
            "安全パトロールが差し戻されました",
            reject_reason
            or "安全パトロールが差し戻されました。",
            f"/pointouts/{result_record.id}",
            company_code=result_record.company_code,
            target_username=target_user.username
        )
        
    notify_mentions(
        reject_reason,
        f"/pointouts/{result_record.id}"
    )

    return redirect(f"/pointouts/{result_record.id}")


@app.route("/pointouts/<int:index>/delete", methods=["POST"])
@limiter.limit("20 per minute")
def delete_pointout(index):
    result_record = PatrolResult.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/pointouts")

    if result_record.approval_status == "承認済み":
        return redirect(f"/pointouts/{index}")

    result = patrol_result_to_dict(result_record)

    if not can_delete_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    view_type = result.get("target_type", "user")

    add_audit_log(
        action="patrol_result_deleted",
        target_type="patrol_result",
        target_id=result_record.id,
        detail=f"安全パトロール結果削除: target_type={view_type}",
        company_code=result_record.company_code,
    )

    db.session.delete(result_record)
    db.session.commit()

    return redirect(f"/pointouts?type={view_type}")

@app.route("/vehicle-patrols/new", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
def new_vehicle_patrol():

    if request.method == "POST":

        vehicle_record_id = request.form.get(
            "vehicle_record_id",
            type=int
        )

        vehicle = Vehicle.query.filter_by(
            company_code=session.get("company_code"),
            id=vehicle_record_id,
            deleted=False
        ).first()

        if not vehicle:
            return "車両が不正です。", 403

        category = request.form.get("category", "").strip()
        priority = request.form.get("priority", "").strip()
        status = request.form.get("status", "未対応").strip()

        if category not in {
            "故障",
            "不具合",
            "事故",
            "点検指摘",
            "その他"
        }:
            return "分類が不正です。", 400

        if priority not in {
            "高",
            "中",
            "低"
        }:
            return "重要度が不正です。", 400

        if status not in {
            "未対応",
            "対応中",
            "修理完了"
        }:
            return "状態が不正です。", 400
        occurred_date = request.form.get(
            "occurred_date",
            ""
        ).strip()

        repair_date = request.form.get(
            "repair_date",
            ""
        ).strip()

        repair_time = request.form.get(
            "repair_time",
            ""
        ).strip()

        repair_person = request.form.get(
            "repair_person",
            ""
        ).strip()

        cost = request.form.get(
            "cost",
            ""
        ).strip()

        if len(repair_person) > 100:
            return "修理担当者は100文字以内で入力してください。", 400

        for value, field_name in [
            (
                occurred_date,
                "発生日"
            ),
            (
                repair_date,
                "修理日"
            )
        ]:
            if value:
                try:
                    datetime.strptime(
                        value,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    return f"{field_name}が不正です。", 400

        if repair_time:
            try:
                repair_time = parse_time_hhmm(
                    repair_time,
                    "修理時間"
                )
            except UploadValidationError as error:
                return str(error), 400

        if cost:
            normalized_cost = cost.replace(",", "")

            if not normalized_cost.isdigit():
                return "修理費用が不正です。", 400

            if len(normalized_cost) > 50:
                return "修理費用は50文字以内で入力してください。", 400

            if int(normalized_cost) < 0:
                return "修理費用は0以上で入力してください。", 400

            cost = normalized_cost        

        content = request.form.get(
            "content",
            ""
        ).strip()
        cause = request.form.get(
            "cause",
            ""
        ).strip()
        temporary_action = request.form.get(
            "temporary_action",
            ""
        ).strip()
        repair_content = request.form.get(
            "repair_content",
            ""
        ).strip()
        parts = request.form.get(
            "parts",
            ""
        ).strip()

        for value, field_name in [
            (content, "内容"),
            (cause, "原因"),
            (temporary_action, "応急処置"),
            (repair_content, "修理内容"),
            (parts, "使用部品"),
        ]:
            if len(value) > 5000:
                return (
                    f"{field_name}は5000文字以内で入力してください。",
                    400
                )
            
        patrol = VehiclePatrol(
            company_code=session.get("company_code"),
            vehicle_record_id=vehicle.id,
            occurred_date=occurred_date,
            category=category,
            priority=priority,
            content=content,
            cause=cause,
            temporary_action=temporary_action,
            repair_content=repair_content,
            status=status,
            repair_date=repair_date,
            repair_person=repair_person,
            repair_time=repair_time,
            parts=parts,
            cost=cost
        )

        db.session.add(patrol)
        db.session.commit()

        return redirect("/vehicle-patrols")

    return render_template(
        "vehicle_patrol_form.html",
        patrol=None,
        selected_vehicle=None,
        mode="new"
    )


@app.route("/usage-vehicles/add", methods=["POST"])
@limiter.limit("30 per minute")
def add_usage_vehicle():
    vehicle_record_id = request.form.get(
        "vehicle_record_id",
        type=int
    )

    if not vehicle_record_id:
        return redirect("/vehicle-patrols")

    vehicle = Vehicle.query.filter_by(
        company_code=session.get("company_code"),
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return redirect("/vehicle-patrols")

    current_driver = Driver.query.filter_by(
        company_code=session.get("company_code"),
        employee_id=session.get("username")
    ).first()

    if not current_driver:
        return redirect(
            build_safe_redirect_url(
                request.form.get("next"),
                "/vehicle-patrols"
            )
        )

    usage_vehicles = safe_json_str_list(
        current_driver.vehicles_json
    )

    vehicle_record_id_str = str(vehicle.id)

    if vehicle_record_id_str not in usage_vehicles:
        usage_vehicles.append(vehicle_record_id_str)

    current_driver.vehicles_json = json.dumps(
        usage_vehicles,
        ensure_ascii=False
    )

    db.session.commit()

    return redirect(
        build_safe_redirect_url(
            request.form.get("next"),
            "/vehicle-patrols"
        )
    )

@app.route(
    "/usage-vehicles/remove/<int:vehicle_record_id>",
    methods=["POST"]
)
@limiter.limit("30 per minute")
def remove_usage_vehicle(vehicle_record_id):
    current_driver = Driver.query.filter_by(
        company_code=session.get("company_code"),
        employee_id=session.get("username")
    ).first()

    if not current_driver:
        return redirect(
            build_safe_redirect_url(
                request.form.get("next"),
                "/vehicle-patrols"
            )
        )

    usage_vehicles = safe_json_str_list(
        current_driver.vehicles_json
    )

    vehicle_record_id_str = str(vehicle_record_id)

    if vehicle_record_id_str in usage_vehicles:
        usage_vehicles.remove(vehicle_record_id_str)

    current_driver.vehicles_json = json.dumps(
        usage_vehicles,
        ensure_ascii=False
    )

    db.session.commit()

    return redirect(
        build_safe_redirect_url(
            request.form.get("next"),
            "/vehicle-patrols"
        )
    )

@app.route("/vehicle-patrols")
def vehicle_patrols():

    keyword = request.args.get("keyword", "").strip()
    status_filter = request.args.get("status", "active")

    if len(keyword) > 100:
        return "検索条件が長すぎます。", 400

    current_driver = Driver.query.filter_by(
        company_code=session.get("company_code"),
        employee_id=session.get("username")
    ).first()

    usage_vehicles = (
        safe_json_str_list(current_driver.vehicles_json)
        if current_driver
        else []
    )

    usage_vehicle_records = Vehicle.query.filter(
        Vehicle.company_code == session.get("company_code"),
        Vehicle.deleted == False,
        Vehicle.id.in_([
            int(vehicle_record_id)
            for vehicle_record_id in usage_vehicles
            if vehicle_record_id.isdigit()
        ])
    ).all() if usage_vehicles else []

    usage_patrols = []
    other_patrols = []

    query = VehiclePatrol.query.join(
        Vehicle,
        Vehicle.id == VehiclePatrol.vehicle_record_id
    ).filter(
        VehiclePatrol.company_code == session.get("company_code")
    )

    if status_filter == "active":
        query = query.filter(
            VehiclePatrol.status != "修理完了"
        )
    elif status_filter:
        query = query.filter(
            VehiclePatrol.status == status_filter
        )

    if keyword:
        keyword_like = f"%{keyword}%"

        query = query.filter(
            db.or_(
                Vehicle.chassis_number.ilike(keyword_like),
                Vehicle.plate_number.ilike(keyword_like),
                VehiclePatrol.content.ilike(keyword_like),
                VehiclePatrol.repair_person.ilike(keyword_like)
            )
        )

    patrol_records = query.order_by(
        VehiclePatrol.id.desc()
    ).all()

    for patrol_record in patrol_records:
        patrol = vehicle_patrol_to_dict(patrol_record)

        if str(patrol.get("vehicle_record_id")) in usage_vehicles:
            usage_patrols.append(patrol)
        else:
            other_patrols.append(patrol)

    return render_template(
        "vehicle_patrols.html",
        usage_patrols=usage_patrols,
        other_patrols=other_patrols,
        usage_vehicles=usage_vehicles,
        usage_vehicle_records=usage_vehicle_records,
        keyword=keyword,
        status_filter=status_filter
    )

@app.route("/vehicle-patrols/<int:index>")
def vehicle_patrol_detail(index):

    patrol = VehiclePatrol.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not patrol:
        return redirect("/vehicle-patrols")

    if patrol.company_code != session.get("company_code"):
        return redirect("/vehicle-patrols")

    return render_template(
        "vehicle_patrol_detail.html",
        patrol=vehicle_patrol_to_dict(patrol),
        index=patrol.id
    )

@app.route("/vehicle-patrols/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
def edit_vehicle_patrol(index):

    if session.get("role") not in ["admin", "itc"]:
        return redirect("/vehicle-patrols")

    patrol = VehiclePatrol.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not patrol:
        return redirect("/vehicle-patrols")

    if request.method == "POST":
        vehicle_record_id = request.form.get(
            "vehicle_record_id",
            type=int
        )

        vehicle = Vehicle.query.filter_by(
            company_code=session.get("company_code"),
            id=vehicle_record_id,
            deleted=False
        ).first()

        if not vehicle:
            return "車両が不正です。", 403

        category = request.form.get("category", "").strip()
        priority = request.form.get("priority", "").strip()
        status = request.form.get("status", "未対応").strip()

        if category not in {
            "故障",
            "不具合",
            "事故",
            "点検指摘",
            "その他"
        }:
            return "分類が不正です。", 400

        if priority not in {
            "高",
            "中",
            "低"
        }:
            return "重要度が不正です。", 400

        if status not in {
            "未対応",
            "対応中",
            "修理完了"
        }:
            return "状態が不正です。", 400
        occurred_date = request.form.get(
            "occurred_date",
            ""
        ).strip()

        repair_date = request.form.get(
            "repair_date",
            ""
        ).strip()

        repair_time = request.form.get(
            "repair_time",
            ""
        ).strip()

        repair_person = request.form.get(
            "repair_person",
            ""
        ).strip()

        cost = request.form.get(
            "cost",
            ""
        ).strip()

        if len(repair_person) > 100:
            return "修理担当者は100文字以内で入力してください。", 400
        
        for value, field_name in [
            (
                occurred_date,
                "発生日"
            ),
            (
                repair_date,
                "修理日"
            )
        ]:
            if value:
                try:
                    datetime.strptime(
                        value,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    return f"{field_name}が不正です。", 400

        if repair_time:
            try:
                repair_time = parse_time_hhmm(
                    repair_time,
                    "修理時間"
                )
            except UploadValidationError as error:
                return str(error), 400

        if cost:
            normalized_cost = cost.replace(",", "")

            if not normalized_cost.isdigit():
                return "修理費用が不正です。", 400

            if len(normalized_cost) > 50:
                return "修理費用は50文字以内で入力してください。", 400

            if int(normalized_cost) < 0:
                return "修理費用は0以上で入力してください。", 400

            cost = normalized_cost

        content = request.form.get(
            "content",
            ""
        ).strip()
        cause = request.form.get(
            "cause",
            ""
        ).strip()
        temporary_action = request.form.get(
            "temporary_action",
            ""
        ).strip()
        repair_content = request.form.get(
            "repair_content",
            ""
        ).strip()
        parts = request.form.get(
            "parts",
            ""
        ).strip()

        for value, field_name in [
            (content, "内容"),
            (cause, "原因"),
            (temporary_action, "応急処置"),
            (repair_content, "修理内容"),
            (parts, "使用部品"),
        ]:
            if len(value) > 5000:
                return (
                    f"{field_name}は5000文字以内で入力してください。",
                    400
                )
            
        patrol.vehicle_record_id = vehicle.id
        patrol.occurred_date = occurred_date
        patrol.category = category
        patrol.priority = priority
        patrol.content = content

        patrol.cause = cause
        patrol.temporary_action = temporary_action
        patrol.repair_content = repair_content

        patrol.repair_date = repair_date
        patrol.repair_person = repair_person
        patrol.repair_time = repair_time
        patrol.parts = parts
        patrol.cost = cost
        patrol.status = status

        db.session.commit()

        return redirect(f"/vehicle-patrols/{patrol.id}")

    selected_vehicle = None

    vehicle = Vehicle.query.filter_by(
        company_code=patrol.company_code,
        id=patrol.vehicle_record_id
    ).first()

    if vehicle:

        number = " ".join(
            value
            for value in [
                vehicle.plate_area or "",
                vehicle.plate_class or "",
                vehicle.plate_kana or "",
                vehicle.plate_number or "",
            ]
            if value
        )

        selected_vehicle = {
            "vehicle_record_id": vehicle.id,
            "chassis_number": vehicle.chassis_number,
            "number": number,
            "manufacturer": vehicle.manufacturer or "",
            "model_code": vehicle.model_code or "",
        }


    return render_template(
        "vehicle_patrol_form.html",
        patrol=vehicle_patrol_to_dict(patrol),
        index=patrol.id,
        selected_vehicle=selected_vehicle,
        mode="edit"
    )

@app.route("/vehicle-patrols/<int:index>/delete", methods=["POST"])
@limiter.limit("20 per minute")
def delete_vehicle_patrol(index):

    if session.get("role") not in ["admin", "itc"]:
        return redirect("/vehicle-patrols")

    patrol = VehiclePatrol.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not patrol:
        return redirect("/vehicle-patrols")

    add_audit_log(
        action="vehicle_patrol_deleted",
        target_type="vehicle_patrol",
        target_id=patrol.id,
        detail=(
            "車両パトロール・修理履歴削除: "
            f"vehicle_record_id={patrol.vehicle_record_id}"
        ),
        company_code=patrol.company_code,
    )

    db.session.delete(patrol)
    db.session.commit()

    return redirect("/vehicle-patrols")

@app.route("/master/vehicle-types")
def vehicle_type_master():
    return render_template(
        "vehicle_type_master.html",
        vehicle_types=vehicle_types_for_current_company()
    )

@app.route("/master/license-types")
def license_type_master():
    return render_template(
        "license_type_master.html",
        license_types=license_types_for_current_company()
    )


@app.route("/master/license-types/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def new_license_type():
    if request.method == "POST":

        name = request.form.get("name", "").strip()

        if not name:
            return "免許種別名を入力してください。", 400

        if len(name) > 100:
            return "免許種別名は100文字以内で入力してください。", 400

        if LicenseType.query.filter_by(
            company_code=session.get("company_code"),
            name=name
        ).first():
            return "この免許種別はすでに登録されています。", 409

        license_type = LicenseType(
            company_code=session.get("company_code"),
            name=name
        )

        db.session.add(license_type)
        db.session.commit()

        return redirect("/master/license-types")

    return render_template(
        "license_type_form.html",
        license_type=None,
        mode="new"
    )


@app.route("/master/license-types/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def edit_license_type(index):
    license_type = LicenseType.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not license_type:
        return redirect("/master/license-types")

    if request.method == "POST":

        name = request.form.get("name", "").strip()

        if not name:
            return "免許種別名を入力してください。", 400

        if len(name) > 100:
            return "免許種別名は100文字以内で入力してください。", 400

        duplicate_license_type = LicenseType.query.filter(
            LicenseType.company_code == license_type.company_code,
            LicenseType.name == name,
            LicenseType.id != license_type.id
        ).first()

        if duplicate_license_type:
            return "この免許種別はすでに登録されています。", 409

        old_name = license_type.name

        drivers = Driver.query.filter_by(
            company_code=license_type.company_code
        ).all()

        for driver in drivers:
            licenses = safe_json_dict_list(
                driver.licenses_json
            )

            changed = False

            for license in licenses:
                if license.get("type") == old_name:
                    license["type"] = name
                    changed = True

            if changed:
                driver.licenses_json = json.dumps(
                    licenses,
                    ensure_ascii=False
                )

        license_type.name = name

        db.session.commit()

        return redirect("/master/license-types")

    return render_template(
        "license_type_form.html",
        license_type={
            "id": license_type.id,
            "name": license_type.name
        },
        mode="edit"
    )


@app.route("/master/license-types/<int:index>/delete", methods=["POST"])
@limiter.limit("10 per minute")
def delete_license_type(index):
    license_type = LicenseType.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not license_type:
        return redirect("/master/license-types")

    license_type_in_use = any(
        any(
            license.get("type") == license_type.name
            for license in safe_json_dict_list(
                driver.licenses_json
            )
        )
        for driver in Driver.query.filter_by(
            company_code=license_type.company_code
        ).all()
    )

    if license_type_in_use:
        return (
            "ドライバーに登録されている免許種別は削除できません。",
            409
        )

    add_audit_log(
        action="license_type_deleted",
        target_type="license_type",
        target_id=license_type.id,
        detail=f"免許種別削除: {license_type.name}",
        company_code=license_type.company_code,
    )

    db.session.delete(license_type)
    db.session.commit()

    return redirect("/master/license-types")

@app.route("/master/vehicle-types/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def new_vehicle_type():
    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if not name:
            return "車種名を入力してください。", 400

        if len(name) > 100:
            return "車種名は100文字以内で入力してください。", 400

        if VehicleType.query.filter_by(
            company_code=session.get("company_code"),
            name=name
        ).first():
            return "この車種はすでに登録されています。", 409

        vehicle_type = VehicleType(
            company_code=session.get("company_code"),
            name=name
        )

        db.session.add(vehicle_type)
        db.session.commit()

        return redirect("/master/vehicle-types")

    return render_template(
        "vehicle_type_form.html",
        vehicle_type=None,
        mode="new"
    )


@app.route("/master/vehicle-types/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def edit_vehicle_type(index):
    vehicle_type = VehicleType.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not vehicle_type:
        return redirect("/master/vehicle-types")

    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if not name:
            return "車種名を入力してください。", 400

        if len(name) > 100:
            return "車種名は100文字以内で入力してください。", 400

        duplicate_vehicle_type = VehicleType.query.filter(
            VehicleType.company_code == vehicle_type.company_code,
            VehicleType.name == name,
            VehicleType.id != vehicle_type.id
        ).first()

        if duplicate_vehicle_type:
            return "この車種はすでに登録されています。", 409

        old_name = vehicle_type.name

        Vehicle.query.filter_by(
            company_code=vehicle_type.company_code,
            type=old_name
        ).update(
            {"type": name},
            synchronize_session=False
        )

        VehicleTypeImportMapping.query.filter_by(
            company_code=vehicle_type.company_code,
            vehicle_type_name=old_name
        ).update(
            {"vehicle_type_name": name},
            synchronize_session=False
        )

        vehicle_type.name = name
        db.session.commit()

        return redirect("/master/vehicle-types")

    return render_template(
        "vehicle_type_form.html",
        vehicle_type={
            "id": vehicle_type.id,
            "name": vehicle_type.name
        },
        mode="edit"
    )


@app.route("/master/vehicle-types/<int:index>/delete", methods=["POST"])
@limiter.limit("10 per minute")
def delete_vehicle_type(index):
    vehicle_type = VehicleType.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not vehicle_type:
        return redirect("/master/vehicle-types")

    Vehicle.query.filter_by(
        company_code=vehicle_type.company_code,
        type=vehicle_type.name
    ).update(
        {"type": ""},
        synchronize_session=False
    )

    VehicleTypeImportMapping.query.filter_by(
        company_code=vehicle_type.company_code,
        vehicle_type_name=vehicle_type.name
    ).delete(synchronize_session=False)

    add_audit_log(
        action="vehicle_type_deleted",
        target_type="vehicle_type",
        target_id=vehicle_type.id,
        detail=f"車種削除: {vehicle_type.name}",
        company_code=vehicle_type.company_code,
    )

    db.session.delete(vehicle_type)
    db.session.commit()

    return redirect("/master/vehicle-types")

@app.route("/vehicle")
def vehicle():
    return render_template("vehicle.html")


@app.route("/analysis")
def analysis():
    return render_template("analysis.html")


@app.route("/manuals")
def manuals():
    return render_template("manuals.html")


@app.route("/master")
def master():
    return render_template("master_menu.html")

@app.route("/master/offices")
def office_master():
    return render_template(
        "office_master.html",
        offices=offices_for_current_company()
    )

@app.route("/master/offices/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def new_office():
    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if not name:
            return "営業所名を入力してください。", 400

        if len(name) > 100:
            return "営業所名は100文字以内で入力してください。", 400

        if Office.query.filter_by(
            company_code=session.get("company_code"),
            name=name
        ).first():
            return "この営業所はすでに登録されています。", 409

        office = Office(
            company_code=session.get("company_code"),
            name=name
        )

        db.session.add(office)
        db.session.commit()

        return redirect("/master/offices")

    return render_template(
        "office_form.html",
        office=None,
        index=None,
        mode="new"
    )


@app.route("/master/offices/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def edit_office(index):
    office = Office.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not office:
        return redirect("/master/offices")

    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if not name:
            return "営業所名を入力してください。", 400

        if len(name) > 100:
            return "営業所名は100文字以内で入力してください。", 400

        if name != office.name:
            duplicate_office = Office.query.filter(
                Office.company_code == office.company_code,
                Office.name == name,
                Office.id != office.id
            ).first()

            if duplicate_office:
                return "この営業所はすでに登録されています。", 409

            patrol_in_use = PatrolResult.query.filter_by(
                company_code=office.company_code,
                office=office.name
            ).first()

            checklist_in_use = ChecklistResult.query.filter_by(
                company_code=office.company_code,
                target_office=office.name
            ).first()

            news_in_use = News.query.filter_by(
                company_code=office.company_code,
                target_type="office",
                target_value=office.name
            ).first()

            if patrol_in_use or checklist_in_use or news_in_use:
                return (
                    "履歴またはお知らせで使用されている営業所は変更できません。",
                    409
                )

            old_name = office.name

            Driver.query.filter_by(
                company_code=office.company_code,
                office=old_name
            ).update(
                {"office": name},
                synchronize_session=False
            )

            User.query.filter_by(
                company_code=office.company_code,
                office=old_name
            ).update(
                {"office": name},
                synchronize_session=False
            )

            Vehicle.query.filter_by(
                company_code=office.company_code,
                office=old_name
            ).update(
                {"office": name},
                synchronize_session=False
            )

        office.name = name
        db.session.commit()

        return redirect("/master/offices")

    office_dict = {
        "id": office.id,
        "index": office.id,
        "company_code": office.company_code,
        "name": office.name
    }

    return render_template(
        "office_form.html",
        office=office_dict,
        index=office.id,
        mode="edit"
    )


@app.route("/master/offices/<int:index>/delete", methods=["POST"])
@limiter.limit("10 per minute")
def delete_office(index):
    office = Office.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not office:
        return redirect("/master/offices")

    patrol_in_use = PatrolResult.query.filter_by(
        company_code=office.company_code,
        office=office.name
    ).first()

    checklist_in_use = ChecklistResult.query.filter_by(
        company_code=office.company_code,
        target_office=office.name
    ).first()

    news_in_use = News.query.filter_by(
        company_code=office.company_code,
        target_type="office",
        target_value=office.name
    ).first()

    if patrol_in_use or checklist_in_use or news_in_use:
        return (
            "履歴またはお知らせで使用されている営業所は削除できません。",
            409
        )

    Driver.query.filter_by(
        company_code=office.company_code,
        office=office.name
    ).update(
        {"office": ""},
        synchronize_session=False
    )

    User.query.filter_by(
        company_code=office.company_code,
        office=office.name
    ).update(
        {"office": ""},
        synchronize_session=False
    )

    Vehicle.query.filter_by(
        company_code=office.company_code,
        office=office.name
    ).update(
        {"office": ""},
        synchronize_session=False
    )

    add_audit_log(
        action="office_deleted",
        target_type="office",
        target_id=office.id,
        detail=f"営業所削除: {office.name}",
        company_code=office.company_code,
    )

    db.session.delete(office)
    db.session.commit()

    return redirect("/master/offices")

@app.route("/master/delivery-places/import", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def import_delivery_places():

    if request.method == "POST":

        excel_file = request.files.get("excel_file")

        if not excel_file or not excel_file.filename:
            return "Excelファイルを選択してください。", 400

        if not excel_file.filename.lower().endswith(".xlsx"):
            return "xlsx形式のExcelファイルを選択してください。", 400

        if not is_valid_uploaded_file(
            excel_file,
            ".xlsx"
        ):
            return "Excelファイルの内容が不正です。", 400

        try:
            workbook = load_workbook(
                excel_file,
                data_only=True
            )
        except Exception:
            return "Excelファイルを読み込めませんでした。", 400

        sheet = workbook.active

        if sheet.max_row > 5000:
            return (
                "一度に読み込めるExcelは5000行までです。",
                400
            )

        if sheet.max_column > 200:
            return (
                "一度に読み込めるExcelは200列までです。",
                400
            )

        header_names = {
            "納入先",
            "納入先名",
            "納入先名称",
            "配送先",
            "配送先名",
            "届け先",
            "届先",
            "得意先",
            "得意先名",
            "顧客名",
            "現場名",
        }

        def normalize_header(value):
            return (
                str(value or "")
                .strip()
                .replace(" ", "")
                .replace("　", "")
            )

        header_row = None
        delivery_column = None
        candidate_columns = []

        scan_end_row = min(sheet.max_row, 30)

        for row_number in range(1, scan_end_row + 1):

            row_candidates = []

            for column_number in range(
                1,
                sheet.max_column + 1
            ):
                cell_value = sheet.cell(
                    row=row_number,
                    column=column_number
                ).value

                normalized_value = normalize_header(
                    cell_value
                )

                if normalized_value in header_names:
                    row_candidates.append({
                        "column": column_number,
                        "header": str(cell_value).strip()
                    })

            if row_candidates:
                header_row = row_number
                candidate_columns = row_candidates

                if len(row_candidates) == 1:
                    delivery_column = row_candidates[0][
                        "column"
                    ]

                break

        if delivery_column:

            def normalize_delivery_name(value):
                return "".join(
                    str(value or "").split()
                ).casefold()

            existing_places = DeliveryPlace.query.filter_by(
                company_code=session.get("company_code")
            ).all()

            existing_names = {
                normalize_delivery_name(place.name)
                for place in existing_places
                if normalize_delivery_name(place.name)
            }

            delivery_places_data = []
            processed_names = set()

            for row_number in range(
                header_row + 1,
                sheet.max_row + 1
            ):
                cell_value = sheet.cell(
                    row=row_number,
                    column=delivery_column
                ).value

                place_name = str(
                    cell_value or ""
                ).strip()

                # 空欄は読み飛ばす
                if not place_name:
                    continue

                normalized_name = normalize_delivery_name(
                    place_name
                )

                if normalized_name in processed_names:
                    import_status = "Excel内重複"

                elif normalized_name in existing_names:
                    import_status = "登録済み"

                else:
                    import_status = "新規"

                processed_names.add(normalized_name)

                delivery_places_data.append({
                    "excel_row": row_number,
                    "name": place_name,
                    "import_status": import_status,
                })

            if not delivery_places_data:
                return (
                    "納入先として読み込めるデータが"
                    "見つかりませんでした。",
                    400
                )

            return render_template(
                "delivery_place_import_preview.html",
                delivery_places=delivery_places_data,
            )

        # 自動判定できない場合は、ユーザーに列を選択してもらう
        selectable_columns = []

        for column_number in range(1, sheet.max_column + 1):

            sample_values = []

            for row_number in range(1, min(sheet.max_row, 5) + 1):

                value = sheet.cell(
                    row=row_number,
                    column=column_number
                ).value

                if value is not None and str(value).strip():
                    sample_values.append(str(value).strip())

            selectable_columns.append({
                "column": column_number,
                "samples": sample_values[:3],
            })

        sheet_rows = []

        for row in sheet.iter_rows(values_only=True):
            sheet_rows.append([
                "" if value is None else str(value)
                for value in row
            ])

        if candidate_columns:
            message = (
                "納入先と思われる列が複数見つかりました。"
                "使用する列を選択してください。"
            )
            start_row = (header_row or 0) + 1

        else:
            message = (
                "納入先の列を自動判定できませんでした。"
                "使用する列を選択してください。"
            )
            start_row = 1

        return render_template(
            "delivery_place_import_column_select.html",
            columns=selectable_columns,
            rows_json=json.dumps(
                sheet_rows,
                ensure_ascii=False
            ),
            start_row=start_row,
            message=message,
        )

    return render_template(
        "delivery_place_import.html"
    )

@app.route(
    "/master/delivery-places/import/column-select",
    methods=["POST"]
)
@limiter.limit("10 per minute")
def select_delivery_place_import_column():

    rows_json = request.form.get("rows_json", "[]")
    delivery_column = request.form.get(
        "delivery_column",
        type=int
    )
    start_row = request.form.get(
        "start_row",
        1,
        type=int
    )

    if (
        not delivery_column
        or delivery_column < 1
        or delivery_column > 200
    ):
        return "納入先の列が不正です。", 400

    if (
        start_row < 1
        or start_row > 5000
    ):
        return "開始行が不正です。", 400

    try:
        sheet_rows = json.loads(rows_json)
    except (TypeError, ValueError):
        return "Excelデータを読み込めませんでした。", 400

    if not isinstance(sheet_rows, list):
        return "Excelデータの形式が不正です。", 400

    if not all(
        isinstance(row, list)
        for row in sheet_rows
    ):
        return "Excelデータの形式が不正です。", 400

    if len(sheet_rows) > 5000:
        return (
            "一度に読み込めるExcelは5000行までです。",
            400
        )

    if any(
        len(row) > 200
        for row in sheet_rows
    ):
        return (
            "一度に読み込めるExcelは200列までです。",
            400
        )

    def normalize_delivery_name(value):
        return "".join(
            str(value or "").split()
        ).casefold()

    existing_places = DeliveryPlace.query.filter_by(
        company_code=session.get("company_code")
    ).all()

    existing_names = {
        normalize_delivery_name(place.name)
        for place in existing_places
        if normalize_delivery_name(place.name)
    }

    delivery_places_data = []
    processed_names = set()

    # HTML側は1列目、2列目…の1始まり
    column_index = delivery_column - 1

    # start_rowもExcel行番号の1始まり
    for row_number in range(
        start_row,
        len(sheet_rows) + 1
    ):

        row = sheet_rows[row_number - 1]

        if column_index >= len(row):
            continue

        place_name = str(
            row[column_index] or ""
        ).strip()

        # 空欄は読み飛ばす
        if not place_name:
            continue

        normalized_header = (
            place_name
            .replace(" ", "")
            .replace("　", "")
        )

        # 見出しそのものは納入先として取り込まない
        manual_header_names = {
            "納入先",
            "納入先名",
            "納入先名称",
            "配送先",
            "配送先名",
            "届け先",
            "届先",
            "得意先",
            "得意先名",
            "顧客名",
            "現場名",
        }

        if normalized_header in manual_header_names:
            continue

        # 「納入先一覧」のようなタイトル行も読み飛ばす
        if (
            "一覧" in normalized_header
            and any(
                word in normalized_header
                for word in [
                    "納入先",
                    "配送先",
                    "届け先",
                    "届先",
                    "得意先",
                    "顧客",
                    "現場",
                ]
            )
        ):
            continue
        normalized_name = normalize_delivery_name(
            place_name
        )

        if normalized_name in processed_names:
            import_status = "Excel内重複"

        elif normalized_name in existing_names:
            import_status = "登録済み"

        else:
            import_status = "新規"

        processed_names.add(normalized_name)

        delivery_places_data.append({
            "excel_row": row_number,
            "name": place_name,
            "import_status": import_status,
        })

    if not delivery_places_data:
        return (
            "選択した列に納入先として読み込める"
            "データがありませんでした。",
            400
        )

    return render_template(
        "delivery_place_import_preview.html",
        delivery_places=delivery_places_data,
    )

@app.route(
    "/master/delivery-places/import/confirm",
    methods=["POST"]
)
@limiter.limit("10 per minute")
def confirm_delivery_place_import():

    company_code = session.get("company_code")

    submitted_names = request.form.getlist(
        "delivery_place_name"
    )

    if len(submitted_names) > 5000:
        return (
            "一度に取り込める納入先は5000件までです。",
            400
        )

    def normalize_delivery_name(value):
        return "".join(
            str(value or "").split()
        ).casefold()

    existing_places = DeliveryPlace.query.filter_by(
        company_code=company_code
    ).all()

    existing_names = {
        normalize_delivery_name(place.name)
        for place in existing_places
        if normalize_delivery_name(place.name)
    }

    processed_names = set()

    registered_count = 0
    existing_count = 0
    duplicate_count = 0

    for submitted_name in submitted_names:

        place_name = str(
            submitted_name or ""
        ).strip()

        if not place_name:
            continue

        if len(place_name) > 100:
            return (
                "納入先名は100文字以内で入力してください。",
                400
            )

        normalized_name = normalize_delivery_name(
            place_name
        )

        # 送信された一覧内で同じ納入先が重複している
        if normalized_name in processed_names:
            duplicate_count += 1
            continue

        processed_names.add(normalized_name)

        # データベースにすでに登録されている
        if normalized_name in existing_names:
            existing_count += 1
            continue

        place = DeliveryPlace(
            company_code=company_code,
            name=place_name
        )

        db.session.add(place)

        existing_names.add(normalized_name)
        registered_count += 1

    db.session.commit()

    return render_template(
        "delivery_place_import_complete.html",
        registered_count=registered_count,
        existing_count=existing_count,
        duplicate_count=duplicate_count,
    )

@app.route("/master/delivery-places")
def delivery_place_master():
    return render_template(
        "delivery_place_master.html",
        delivery_places=delivery_places_for_current_company()
    )


@app.route("/master/delivery-places/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def new_delivery_place():
    if request.method == "POST":

        name = request.form.get("name", "").strip()

        if not name:
            return "納入先名を入力してください。", 400

        if len(name) > 100:
            return "納入先名は100文字以内で入力してください。", 400

        if DeliveryPlace.query.filter_by(
            company_code=session.get("company_code"),
            name=name
        ).first():
            return "この納入先はすでに登録されています。", 409

        place = DeliveryPlace(
            company_code=session.get("company_code"),
            name=name
        )

        db.session.add(place)
        db.session.commit()

        return redirect("/master/delivery-places")

    return render_template(
        "delivery_place_form.html",
        place=None,
        index=None,
        mode="new"
    )


@app.route("/master/delivery-places/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def edit_delivery_place(index):
    place = DeliveryPlace.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not place:
        return redirect("/master/delivery-places")

    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if not name:
            return "納入先名を入力してください。", 400

        if len(name) > 100:
            return "納入先名は100文字以内で入力してください。", 400

        if name != place.name:
            duplicate_place = DeliveryPlace.query.filter(
                DeliveryPlace.company_code == place.company_code,
                DeliveryPlace.name == name,
                DeliveryPlace.id != place.id
            ).first()

            if duplicate_place:
                return "この納入先はすでに登録されています。", 409

            place_in_use = PatrolResult.query.filter_by(
                company_code=place.company_code,
                delivery_place=place.name
            ).first()

            if place_in_use:
                return (
                    "安全パトロール履歴で使用されている納入先は変更できません。",
                    409
                )

        place.name = name
        db.session.commit()

        return redirect("/master/delivery-places")

    return render_template(
        "delivery_place_form.html",
        place={
            "id": place.id,
            "index": place.id,
            "company_code": place.company_code,
            "name": place.name
        },
        index=place.id,
        mode="edit"
    )


@app.route("/master/delivery-places/<int:index>/delete", methods=["POST"])
@limiter.limit("10 per minute")
def delete_delivery_place(index):
    place = DeliveryPlace.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not place:
        return redirect("/master/delivery-places")

    place_in_use = PatrolResult.query.filter_by(
        company_code=place.company_code,
        delivery_place=place.name
    ).first()

    if place_in_use:
        return (
            "安全パトロール履歴で使用されている納入先は削除できません。",
            409
        )

    add_audit_log(
        action="delivery_place_deleted",
        target_type="delivery_place",
        target_id=place.id,
        detail=f"納入先削除: {place.name}",
        company_code=place.company_code,
    )

    db.session.delete(place)
    db.session.commit()

    return redirect("/master/delivery-places")

@app.route("/master/patrol-content-types")
def patrol_content_type_master():
    return render_template(
        "patrol_content_type_master.html",
        content_types=patrol_content_types_for_current_company()
    )


@app.route("/master/patrol-content-types/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def new_patrol_content_type():
    if request.method == "POST":

        name = request.form.get("name", "").strip()

        if not name:
            return "内容区分名を入力してください。", 400

        if len(name) > 100:
            return "内容区分名は100文字以内で入力してください。", 400

        if PatrolContentType.query.filter_by(
            company_code=session.get("company_code"),
            name=name
        ).first():
            return "この内容区分はすでに登録されています。", 409

        item = PatrolContentType(
            company_code=session.get("company_code"),
            name=name
        )

        db.session.add(item)
        db.session.commit()

        return redirect("/master/patrol-content-types")

    return render_template(
        "patrol_content_type_form.html",
        item=None,
        mode="new"
    )


@app.route("/master/patrol-content-types/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def edit_patrol_content_type(index):
    item = PatrolContentType.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not item:
        return redirect("/master/patrol-content-types")

    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if not name:
            return "内容区分名を入力してください。", 400

        if len(name) > 100:
            return "内容区分名は100文字以内で入力してください。", 400

        if name != item.name:
            duplicate_item = PatrolContentType.query.filter(
                PatrolContentType.company_code == item.company_code,
                PatrolContentType.name == name,
                PatrolContentType.id != item.id
            ).first()

            if duplicate_item:
                return "この内容区分はすでに登録されています。", 409

            item_in_use = PatrolResult.query.filter_by(
                company_code=item.company_code,
                content_type=item.name
            ).first()

            if item_in_use:
                return (
                    "安全パトロール履歴で使用されている内容区分は変更できません。",
                    409
                )

        item.name = name
        db.session.commit()

        return redirect("/master/patrol-content-types")

    return render_template(
        "patrol_content_type_form.html",
        item=item,
        mode="edit"
    )


@app.route("/master/patrol-content-types/<int:index>/delete", methods=["POST"])
@limiter.limit("10 per minute")
def delete_patrol_content_type(index):
    item = PatrolContentType.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not item:
        return redirect("/master/patrol-content-types")

    item_in_use = PatrolResult.query.filter_by(
        company_code=item.company_code,
        content_type=item.name
    ).first()

    if item_in_use:
        return (
            "安全パトロール履歴で使用されている内容区分は削除できません。",
            409
        )

    add_audit_log(
        action="patrol_content_type_deleted",
        target_type="patrol_content_type",
        target_id=item.id,
        detail=f"安全パトロール内容区分削除: {item.name}",
        company_code=item.company_code,
    )

    db.session.delete(item)
    db.session.commit()
    return redirect("/master/patrol-content-types")

@app.route("/master/drivers")
def driver_master():
    keyword = request.args.get("keyword", "").strip()
    office = request.args.get("office", "").strip()
    vehicle = request.args.get("vehicle", "").strip()

    if (
        len(keyword) > 100
        or len(office) > 100
        or len(vehicle) > 100
    ):
        return "検索条件が長すぎます。", 400

    if office:
        valid_office = Office.query.filter_by(
            company_code=session.get("company_code"),
            name=office
        ).first()

        if not valid_office:
            return "営業所が不正です。", 400

    if vehicle:
        if not vehicle.isdigit():
            return "車両が不正です。", 400

        valid_vehicle = Vehicle.query.filter_by(
            company_code=session.get("company_code"),
            id=int(vehicle),
            deleted=False
        ).first()

        if not valid_vehicle:
            return "車両が不正です。", 400
        
    query = Driver.query.filter(
        Driver.company_code == session.get("company_code")
    )

    if keyword:
        keyword_like = f"%{keyword}%"

        query = query.filter(
            db.or_(
                Driver.employee_id.ilike(keyword_like),
                Driver.name.ilike(keyword_like)
            )
        )

    if office:
        query = query.filter(
            Driver.office == office
        )

    if vehicle:
        query = query.filter(
            Driver.vehicles_json.contains(f'"{vehicle}"')
        )

    driver_records = query.order_by(
        Driver.id.asc()
    ).all()

    filtered_drivers = []

    for driver in driver_records:
        driver_item = {
            "index": driver.id,
            "id": driver.id,
            "company_code": driver.company_code,
            "employee_id": driver.employee_id,
            "username": driver.employee_id,
            "name": driver.name,
            "role": driver.role,
            "office": driver.office,
            "safe_start_date": driver.safe_start_date,
            "vehicles": safe_json_str_list(
                driver.vehicles_json
            ),
            "licenses": safe_json_dict_list(
                driver.licenses_json
            ),
        }

        safe_start_date = driver.safe_start_date

        if safe_start_date:
            try:
                start_date = datetime.strptime(
                    safe_start_date,
                    "%Y-%m-%d"
                )
                days = (
                    datetime.today() - start_date
                ).days
            except ValueError:
                days = 0
        else:
            days = 0

        years = days // 365
        remaining_days = days % 365

        driver_item["safe_days_display"] = (
            f"{years}年{remaining_days}日継続中"
            if years > 0
            else f"{days}日継続中"
        )

        filtered_drivers.append(driver_item)

    return render_template(
        "driver_master.html",
        drivers=filtered_drivers,
        offices=offices_for_current_company(),
        keyword=keyword,
        office=office,
        vehicle=vehicle,
    )

@app.route("/master/drivers/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def new_driver():
    company_code = session.get("company_code")

    if request.method == "POST":
        employee_id = request.form.get(
            "employee_id",
            ""
        ).strip()

        name = request.form.get(
            "name",
            ""
        ).strip()

        email_address = request.form.get(
            "email_address",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        password_type_count = sum([
            any(c.islower() for c in password or ""),
            any(c.isupper() for c in password or ""),
            any(c.isdigit() for c in password or ""),
            any(
                not c.isalnum()
                for c in password or ""
            ),
        ])

        role = request.form.get(
            "role",
            "user"
        ).strip()

        office = request.form.get(
            "office",
            ""
        ).strip()

        safe_start_date = request.form.get(
            "safe_start_date",
            ""
        ).strip()

        selected_vehicles = request.form.getlist(
            "vehicles"
        )

        if len(selected_vehicles) > 1000:
            return "選択車両数が多すぎます。", 400

        # =========================
        # 基本入力チェック
        # =========================

        if not employee_id:
            return "ログインIDを入力してください。", 400

        if len(employee_id) > 50:
            return "ログインIDは50文字以内で入力してください。", 400

        if not name:
            return "氏名を入力してください。", 400

        if len(name) > 100:
            return "氏名は100文字以内で入力してください。", 400

        if email_address and not is_valid_email_address(
            email_address
        ):
            return "メールアドレスの形式が不正です。", 400

        if not password:
            return "パスワードを入力してください。", 400

        if len(password) < 8:
            return "パスワードは8文字以上にしてください。", 400

        if len(password) > 128:
            return "パスワードは128文字以内にしてください。", 400

        if password_type_count < 3:
            return (
                "パスワードは英大文字・英小文字・数字・記号の"
                "うち3種類以上を使用してください。",
                400
            )

        # =========================
        # ロール検証
        # =========================

        if role not in ["admin", "user"]:
            return "ユーザー種別が不正です。", 400
        if safe_start_date:
            try:
                datetime.strptime(
                    safe_start_date,
                    "%Y-%m-%d"
                )
            except ValueError:
                return "無事故開始日が不正です。", 400        

        # =========================
        # ログインID重複確認
        # =========================

        if User.query.filter_by(
            company_code=company_code,
            username=employee_id
        ).first():
            return "このログインIDはすでに使用されています。", 400

        # =========================
        # 営業所検証
        # =========================

        if office:
            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=office
            ).first()

            if not valid_office:
                return "営業所が不正です。", 400

        # =========================
        # 車両検証
        # =========================

        valid_vehicle_record_ids = {
            str(vehicle.id)
            for vehicle in Vehicle.query.filter_by(
                company_code=company_code,
                deleted=False
            ).all()
        }

        for vehicle_record_id in selected_vehicles:
            if vehicle_record_id not in valid_vehicle_record_ids:
                return "選択された車両が不正です。", 400

        # =========================
        # 免許種別検証
        # =========================

        valid_license_types = {
            item.name
            for item in LicenseType.query.filter_by(
                company_code=company_code
            ).all()
        }

        licenses = []

        license_types = request.form.getlist(
            "license_type"
        )

        license_expiries = request.form.getlist(
            "license_expiry"
        )

        if (
            len(license_types) > 100
            or len(license_expiries) > 100
        ):
            return "免許情報の件数が多すぎます。", 400

        for license_type, expiry in zip(
            license_types,
            license_expiries
        ):
            license_type = (
                license_type or ""
            ).strip()

            expiry = (
                expiry or ""
            ).strip()

            if not license_type:
                continue

            if license_type not in valid_license_types:
                return "免許種別が不正です。", 400

            if expiry:
                try:
                    datetime.strptime(
                        expiry,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    return "免許有効期限が不正です。", 400

            licenses.append({
                "type": license_type,
                "expiry": expiry
            })

        # =========================
        # Driver作成
        # =========================

        driver = Driver(
            company_code=company_code,
            employee_id=employee_id,
            name=name,
            role=role,
            office=office,
            safe_start_date=safe_start_date,
            vehicles_json=json.dumps(
                selected_vehicles,
                ensure_ascii=False
            ),
            licenses_json=json.dumps(
                licenses,
                ensure_ascii=False
            )
        )

        # =========================
        # User作成
        # =========================

        user = User(
            company_code=company_code,
            username=employee_id,
            password=generate_password_hash(
                password
            ),
            password_changed_at=datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            role=role,
            name=name,
            office=office,
            favorite_vehicles_json="[]",
            email_address=email_address or None,
            email_notify_enabled=bool(email_address)
        )

        db.session.add(user)
        db.session.add(driver)
        db.session.commit()

        return redirect("/master/drivers")

    return render_template(
        "driver_form.html",
        driver=None,
        offices=offices_for_current_company(),
        selected_vehicles=[],
        license_types=license_types_for_current_company(),
        mode="new"
    )

@app.route("/master/drivers/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def edit_driver(index):
    driver = Driver.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not driver:
        return redirect("/master/drivers")

    if request.method == "POST":
        company_code = driver.company_code

        old_employee_id = driver.employee_id

        new_employee_id = request.form.get(
            "employee_id",
            ""
        ).strip()

        name = request.form.get(
            "name",
            ""
        ).strip()

        email_address = request.form.get(
            "email_address",
            ""
        ).strip().lower()

        role = request.form.get(
            "role",
            "user"
        ).strip()

        office = request.form.get(
            "office",
            ""
        ).strip()

        safe_start_date = request.form.get(
            "safe_start_date",
            ""
        ).strip()

        new_password = request.form.get(
            "password",
            ""
        )

        password_type_count = sum([
            any(c.islower() for c in new_password or ""),
            any(c.isupper() for c in new_password or ""),
            any(c.isdigit() for c in new_password or ""),
            any(
                not c.isalnum()
                for c in new_password or ""
            ),
        ])

        selected_vehicles = request.form.getlist(
            "vehicles"
        )

        if len(selected_vehicles) > 1000:
            return "選択車両数が多すぎます。", 400

        # =========================
        # 基本入力チェック
        # =========================

        if not new_employee_id:
            return "ログインIDを入力してください。", 400

        if len(new_employee_id) > 50:
            return "ログインIDは50文字以内で入力してください。", 400

        if new_employee_id != old_employee_id:
            return "ログインIDは作成後に変更できません。", 400

        if not name:
            return "氏名を入力してください。", 400

        if len(name) > 100:
            return "氏名は100文字以内で入力してください。", 400

        if email_address and not is_valid_email_address(
            email_address
        ):
            return "メールアドレスの形式が不正です。", 400

        if new_password:
            if len(new_password) < 8:
                return "パスワードは8文字以上にしてください。", 400

            if len(new_password) > 128:
                return "パスワードは128文字以内にしてください。", 400

            if password_type_count < 3:
                return (
                    "パスワードは英大文字・英小文字・数字・記号の"
                    "うち3種類以上を使用してください。",
                    400
                )
        # =========================
        # ロール検証
        # =========================

        if role not in ["admin", "user"]:
            return "ユーザー種別が不正です。", 400
        if safe_start_date:
            try:
                datetime.strptime(
                    safe_start_date,
                    "%Y-%m-%d"
                )
            except ValueError:
                return "無事故開始日が不正です。", 400        

        # =========================
        # ログインID重複確認
        # =========================

        if new_employee_id != old_employee_id:
            existing_user = User.query.filter_by(
                company_code=company_code,
                username=new_employee_id
            ).first()

            if existing_user:
                return (
                    "このログインIDはすでに使用されています。",
                    400
                )

        # =========================
        # 営業所検証
        # =========================

        if office:
            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=office
            ).first()

            if not valid_office:
                return "営業所が不正です。", 400

        # =========================
        # 車両検証
        # =========================

        valid_vehicle_record_ids = {
            str(vehicle.id)
            for vehicle in Vehicle.query.filter_by(
                company_code=company_code,
                deleted=False
            ).all()
        }

        for vehicle_record_id in selected_vehicles:
            if vehicle_record_id not in valid_vehicle_record_ids:
                return "選択された車両が不正です。", 400

        # =========================
        # 免許種別検証
        # =========================

        valid_license_types = {
            item.name
            for item in LicenseType.query.filter_by(
                company_code=company_code
            ).all()
        }

        licenses = []

        license_types = request.form.getlist(
            "license_type"
        )

        license_expiries = request.form.getlist(
            "license_expiry"
        )

        if (
            len(license_types) > 100
            or len(license_expiries) > 100
        ):
            return "免許情報の件数が多すぎます。", 400

        for license_type, expiry in zip(
            license_types,
            license_expiries
        ):
            license_type = (
                license_type or ""
            ).strip()

            expiry = (
                expiry or ""
            ).strip()

            if not license_type:
                continue

            if license_type not in valid_license_types:
                return "免許種別が不正です。", 400

            if expiry:
                try:
                    datetime.strptime(
                        expiry,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    return "免許有効期限が不正です。", 400

            licenses.append({
                "type": license_type,
                "expiry": expiry
            })

        # =========================
        # User取得
        # =========================

        user = User.query.filter_by(
            company_code=company_code,
            username=old_employee_id
        ).first()

        # Userが消えている異常状態なら
        # 固定パスワードを勝手に作らない
        if not user:
            if not new_password:
                return (
                    "ユーザー情報が見つかりません。"
                    "再作成するためパスワードを入力してください。",
                    400
                )

            user = User(
                company_code=company_code,
                username=new_employee_id,
                password=generate_password_hash(
                    new_password
                ),
                password_changed_at=datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                role=role,
                name=name,
                office=office,
                email_address=email_address or None,
                email_notify_enabled=bool(email_address),
                favorite_vehicles_json="[]"
            )

            db.session.add(user)

        else:
            user.username = new_employee_id
            user.role = role
            user.name = name
            user.office = office
            user.email_address = email_address or None
            user.email_notify_enabled = bool(email_address)
            user.favorite_vehicles_json = "[]"

            if new_password:
                password_history = parse_password_history(
                    user.password_history_json
                )

                if password_history is None:
                    return (
                        "パスワード履歴データが不正です。",
                        500
                    )

                reused_password = (
                    check_password_hash(
                        user.password,
                        new_password
                    )
                    or any(
                        check_password_hash(
                            old_password_hash,
                            new_password
                        )
                        for old_password_hash in password_history[-5:]
                    )
                )

                if reused_password:
                    return (
                        "現在または過去5回以内に使用した"
                        "パスワードは使用できません。",
                        400
                    )

                password_history.append(
                    user.password
                )

                user.password_history_json = json.dumps(
                    password_history[-5:]
                )

                user.password = generate_password_hash(
                    new_password
                )

                user.password_changed_at = (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )

                user.failed_login_count = 0
                user.login_locked = False

                add_audit_log(
                    action="admin_password_reset",
                    target_type="user",
                    target_id=user.username,
                    detail="管理者によるパスワード変更・アカウントロック解除",
                    company_code=user.company_code,
                )
        # =========================
        # Driver更新
        # =========================

        driver.employee_id = new_employee_id
        driver.name = name
        driver.role = role
        driver.office = office
        driver.safe_start_date = safe_start_date
        driver.vehicles_json = json.dumps(
            selected_vehicles,
            ensure_ascii=False
        )
        driver.licenses_json = json.dumps(
            licenses,
            ensure_ascii=False
        )

        db.session.commit()

        return redirect("/master/drivers")

    driver_dict = driver_to_dict(driver)


    selected_vehicle_records = []

    if driver_dict["vehicles"]:

        selected_vehicle_record_ids = [
            int(vehicle_record_id)
            for vehicle_record_id in driver_dict["vehicles"]
            if str(vehicle_record_id).isdigit()
        ]

        selected_vehicle_records = Vehicle.query.filter(
            Vehicle.company_code == driver.company_code,
            Vehicle.id.in_(selected_vehicle_record_ids),
            Vehicle.deleted == False
        ).all()


    selected_vehicles = []

    for vehicle in selected_vehicle_records:

        number = " ".join(
            value
            for value in [
                vehicle.plate_area or "",
                vehicle.plate_class or "",
                vehicle.plate_kana or "",
                vehicle.plate_number or "",
            ]
            if value
        )

        selected_vehicles.append({
            "vehicle_record_id": vehicle.id,
            "chassis_number": vehicle.chassis_number,
            "number": number,
            "type": vehicle.type or "",
        })


    return render_template(
        "driver_form.html",
        driver=driver_dict,
        index=driver.id,
        offices=offices_for_current_company(),
        selected_vehicles=selected_vehicles,
        license_types=license_types_for_current_company(),
        mode="edit"
    )


@app.route("/master/drivers/<int:index>/delete", methods=["POST"])
@limiter.limit("10 per minute")
def delete_driver(index):
    driver = Driver.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not driver:
        return redirect("/master/drivers")

    username = driver.employee_id

    approved_checklist_result = ChecklistResult.query.filter(
        ChecklistResult.company_code == driver.company_code,
        ChecklistResult.status == "承認済み",
        db.or_(
            ChecklistResult.checked_by_username == username,
            ChecklistResult.approved_by_username == username,
            ChecklistResult.target_username == username
        )
    ).first()

    approved_vehicle_result = VehicleChecklistResult.query.filter(
        VehicleChecklistResult.company_code == driver.company_code,
        VehicleChecklistResult.status == "承認済み",
        db.or_(
            VehicleChecklistResult.checked_by_username == username,
            VehicleChecklistResult.approved_by_username == username
        )
    ).first()

    approved_patrol_result = PatrolResult.query.filter(
        PatrolResult.company_code == driver.company_code,
        PatrolResult.approval_status == "承認済み",
        db.or_(
            PatrolResult.created_by_username == username,
            PatrolResult.target_username == username,
            PatrolResult.countermeasure_by_username == username
        )
    ).first()

    active_checklist_result = ChecklistResult.query.filter(
        ChecklistResult.company_code == driver.company_code,
        ChecklistResult.status != "承認済み",
        db.or_(
            ChecklistResult.checked_by_username == username,
            ChecklistResult.target_username == username
        )
    ).first()

    active_vehicle_result = VehicleChecklistResult.query.filter(
        VehicleChecklistResult.company_code == driver.company_code,
        VehicleChecklistResult.status != "承認済み",
        VehicleChecklistResult.checked_by_username == username
    ).first()

    active_patrol_result = PatrolResult.query.filter(
        PatrolResult.company_code == driver.company_code,
        PatrolResult.approval_status != "承認済み",
        db.or_(
            PatrolResult.created_by_username == username,
            PatrolResult.target_username == username,
            PatrolResult.countermeasure_by_username == username
        )
    ).first()

    if (
        active_checklist_result
        or active_vehicle_result
        or active_patrol_result
    ):
        return (
            "進行中の点検・安全パトロールに関係する"
            "ドライバーは削除できません。",
            409
        )

    approved_step_result = False

    approved_checklist_results = ChecklistResult.query.filter_by(
        company_code=driver.company_code,
        status="承認済み"
    ).all()

    for result in approved_checklist_results:
        approvals = safe_json_dict_list(
            result.approvals_json
        )

        if any(
            approval.get("approved_by_username") == username
            for approval in approvals
        ):
            approved_step_result = True
            break

    if not approved_step_result:
        approved_vehicle_results = VehicleChecklistResult.query.filter_by(
            company_code=driver.company_code,
            status="承認済み"
        ).all()

        for result in approved_vehicle_results:
            approvals = safe_json_dict_list(
                result.approvals_json
            )

            if any(
                approval.get("approved_by_username") == username
                for approval in approvals
            ):
                approved_step_result = True
                break

    if (
        approved_checklist_result
        or approved_vehicle_result
        or approved_patrol_result
        or approved_step_result
    ):
        return (
            "承認済みの履歴に関係するドライバーは削除できません。",
            409
        )

    notify_settings = VehicleChecklistNotifySetting.query.filter_by(
        company_code=driver.company_code
    ).all()

    for setting in notify_settings:
        notify_usernames = safe_json_str_list(
            setting.notify_users_json
        )

        if username in notify_usernames:
            notify_usernames = [
                item
                for item in notify_usernames
                if item != username
            ]

            setting.notify_users_json = json.dumps(
                notify_usernames,
                ensure_ascii=False
            )

    user = User.query.filter_by(
        company_code=driver.company_code,
        username=username
    ).first()

    if user:
        db.session.delete(user)

    add_audit_log(
        action="driver_deleted",
        target_type="driver",
        target_id=driver.employee_id,
        detail=f"ドライバー削除: {driver.name}",
        company_code=driver.company_code,
    )

    db.session.delete(driver)
    db.session.commit()
    return redirect("/master/drivers")

@app.route("/master/vehicles")
def vehicle_master():
    keyword = request.args.get("keyword", "").strip()
    office = request.args.get("office", "").strip()
    vehicle_type = request.args.get("vehicle_type", "").strip()
    status = request.args.get("status", "").strip()
    manufacturer = request.args.get("manufacturer", "").strip()
    model_code = request.args.get("model_code", "").strip()

    if (
        len(keyword) > 100
        or len(office) > 100
        or len(vehicle_type) > 100
        or len(status) > 50
        or len(manufacturer) > 100
        or len(model_code) > 100
    ):
        return "検索条件が長すぎます。", 400

    if status not in {"", "active", "inactive"}:
        return "状態が不正です。", 400

    company_code = session.get("company_code")

    if office:
        valid_office = Office.query.filter_by(
            company_code=company_code,
            name=office
        ).first()

        if not valid_office:
            return "営業所が不正です。", 400

    if vehicle_type:
        valid_vehicle_type = VehicleType.query.filter_by(
            company_code=company_code,
            name=vehicle_type
        ).first()

        if not valid_vehicle_type:
            return "車種が不正です。", 400

    if manufacturer:
        valid_manufacturer = Vehicle.query.filter_by(
            company_code=company_code,
            manufacturer=manufacturer
        ).first()

        if not valid_manufacturer:
            return "メーカーが不正です。", 400

    if model_code:
        valid_model_code = Vehicle.query.filter_by(
            company_code=company_code,
            model_code=model_code
        ).first()

        if not valid_model_code:
            return "型式が不正です。", 400
        
    query = Vehicle.query.filter_by(
        company_code=company_code
    )


    # キーワード検索
    if keyword:

        keyword_like = f"%{keyword}%"

        query = query.filter(
            db.or_(
                Vehicle.plate_area.ilike(keyword_like),
                Vehicle.plate_class.ilike(keyword_like),
                Vehicle.plate_kana.ilike(keyword_like),
                Vehicle.plate_number.ilike(keyword_like),
                Vehicle.chassis_number.ilike(keyword_like),
                Vehicle.model_code.ilike(keyword_like),
                Vehicle.manufacturer.ilike(keyword_like),
                Vehicle.body_type.ilike(keyword_like),
            )
        )


    # 有効・無効
    if status == "active":
        query = query.filter(
            Vehicle.deleted == False
        )

    elif status == "inactive":
        query = query.filter(
            Vehicle.deleted == True
        )


    # メーカー・車名
    if manufacturer:
        query = query.filter(
            Vehicle.manufacturer == manufacturer
        )


    # 型式
    if model_code:
        query = query.filter(
            Vehicle.model_code == model_code
        )


    # 営業所
    if office:
        query = query.filter(
            Vehicle.office == office
        )


    # 車種
    if vehicle_type:
        query = query.filter(
            Vehicle.type == vehicle_type
        )


    # メーカー候補
    manufacturers = [
        item[0]
        for item in db.session.query(Vehicle.manufacturer)
        .filter(
            Vehicle.company_code == session.get("company_code"),
            Vehicle.manufacturer.isnot(None),
            Vehicle.manufacturer != ""
        )
        .distinct()
        .order_by(Vehicle.manufacturer)
        .all()
    ]


    # 型式候補
    model_codes = [
        item[0]
        for item in db.session.query(Vehicle.model_code)
        .filter(
            Vehicle.company_code == session.get("company_code"),
            Vehicle.model_code.isnot(None),
            Vehicle.model_code != ""
        )
        .distinct()
        .order_by(Vehicle.model_code)
        .all()
    ]


    # ページ分割
    page = request.args.get("page", 1, type=int)
    per_page = 100

    total_count = query.count()

    total_pages = max(
        1,
        (total_count + per_page - 1) // per_page
    )

    if page < 1:
        page = 1

    if page > total_pages:
        page = total_pages


    vehicle_records = (
        query
        .order_by(Vehicle.id.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )


    filtered_vehicles = []

    for vehicle in vehicle_records:

        item = {
            "index": vehicle.id,
            "id": vehicle.id,
            "company_code": vehicle.company_code,
            "vehicle_record_id": vehicle.id,
            "deleted": vehicle.deleted,

            "plate_area": vehicle.plate_area,
            "plate_class": vehicle.plate_class,
            "plate_kana": vehicle.plate_kana,
            "plate_number": vehicle.plate_number,

            "chassis_number": vehicle.chassis_number,
            "model_code": vehicle.model_code,
            "first_registration_date": vehicle.first_registration_date,
            "manufacturer": vehicle.manufacturer,
            "body_type": vehicle.body_type,

            "gross_vehicle_weight": vehicle.gross_vehicle_weight,
            "max_payload": vehicle.max_payload,

            "type": vehicle.type,
            "office": vehicle.office,
            "inspection_expiry": vehicle.inspection_expiry,
        }

        item["number"] = vehicle_number(item)

        filtered_vehicles.append(item)

    company = Company.query.filter_by(
        company_code=session.get("company_code")
    ).first()

    vehicle_limit = 0

    vehicle_count = Vehicle.query.filter_by(
        company_code=session.get("company_code"),
        deleted=False
    ).count()

    remaining_vehicles = 0

    if company:
        vehicle_limit = company.vehicle_limit
        remaining_vehicles = vehicle_limit - vehicle_count

    return render_template(
        "vehicle_master.html",
        vehicles=filtered_vehicles,
        offices=offices_for_current_company(),
        vehicle_types=vehicle_types_for_current_company(),
        keyword=keyword,
        office=office,
        vehicle_type=vehicle_type,
        status=status,
        manufacturer=manufacturer,
        model_code=model_code,

        manufacturers=manufacturers,
        model_codes=model_codes,

        vehicle_limit=vehicle_limit,
        vehicle_count=vehicle_count,
        remaining_vehicles=remaining_vehicles,

        page=page,
        total_pages=total_pages,
        total_count=total_count,
    )

@app.route("/master/vehicles/import", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def import_vehicles():

    if request.method == "POST":

        excel_file = request.files.get("excel_file")

        if not excel_file or not excel_file.filename:
            return "Excelファイルを選択してください。", 400

        if not excel_file.filename.lower().endswith(".xlsx"):
            return "xlsx形式のExcelファイルを選択してください。", 400

        if not is_valid_uploaded_file(
            excel_file,
            ".xlsx"
        ):
            return "Excelファイルの内容が不正です。", 400

        try:
            workbook = load_workbook(
                excel_file,
                data_only=True
            )
        except Exception:
            return "Excelファイルを読み込めませんでした。", 400

        sheet = workbook.active

        if sheet.max_row > 5000:
            return (
                "一度に読み込めるExcelは5000行までです。",
                400
            )

        if sheet.max_column > 200:
            return (
                "一度に読み込めるExcelは200列までです。",
                400
            )

        header_row = None

        for row in sheet.iter_rows():
            values = [cell.value for cell in row]

            if (
                "ID" in values
                and "車両番号" in values
                and "車体番号" in values
                and "車番" in values
            ):
                header_row = row[0].row
                break

        if header_row is None:
            return "車両台帳の見出し行が見つかりませんでした。", 400

        headers = [
            cell.value
            for cell in sheet[header_row]
        ]

        header_map = {
            name: index
            for index, name in enumerate(headers)
            if name is not None
        }
        required_headers = [
            "車種コード",
            "車番・地域名",
            "車番・分類",
            "車番・ひらがな",
            "車番",
            "車両総重量",
            "車体番号",
            "車体型式",
            "初年度車検",
            "車検期間終了日",
            "車両メーカー",
            "車両形状",
            "最大積載量",
        ]

        missing_headers = [
            header
            for header in required_headers
            if header not in header_map
        ]

        if missing_headers:
            return (
                "Excelに必要な見出しがありません："
                + "、".join(missing_headers),
                400
            )
        def normalize_excel_date(value):
            if value in (None, ""):
                return ""

            if hasattr(value, "strftime"):
                return value.strftime("%Y-%m-%d")

            return str(value).strip()
        vehicles_data = []

        for data_row in range(header_row + 1, sheet.max_row + 1):

            row_values = [
                cell.value
                for cell in sheet[data_row]
            ]

            # 空行は読み飛ばす
            if not any(value is not None for value in row_values):
                continue

            plate_number = row_values[header_map["車番"]]
            chassis_number = row_values[header_map["車体番号"]]



            vehicle_data = {
                "excel_row": data_row,

                "vehicle_type_code": str(
                    row_values[header_map["車種コード"]] or ""
                ).strip(),

                "plate_area": row_values[header_map["車番・地域名"]],
                "plate_class": row_values[header_map["車番・分類"]],
                "plate_kana": row_values[header_map["車番・ひらがな"]],
                "plate_number": plate_number,

                "gross_vehicle_weight": row_values[header_map["車両総重量"]],
                "chassis_number": chassis_number,
                "model_code": row_values[header_map["車体型式"]],

                "first_registration_date": normalize_excel_date(
                    row_values[header_map["初年度車検"]]
                ),
                "inspection_expiry": normalize_excel_date(
                    row_values[header_map["車検期間終了日"]]
                ),

                "vehicle_name_raw": row_values[header_map["車両メーカー"]],
                "body_type_raw": row_values[header_map["車両形状"]],

                "vehicle_name": row_values[header_map["車両メーカー"]],
                "body_type": row_values[header_map["車両形状"]],

                "max_payload": row_values[header_map["最大積載量"]],
            }

            vehicles_data.append(vehicle_data)

        def clean_preview_text(value):
            return str(value or "").strip()

        def preview_int(value):
            cleaned_value = clean_preview_text(
                value
            ).replace(",", "")

            if not cleaned_value:
                return None

            try:
                return int(float(cleaned_value))
            except (TypeError, ValueError):
                return None

        incoming_chassis_numbers = {
            clean_preview_text(
                vehicle.get("chassis_number")
            )
            for vehicle in vehicles_data
            if clean_preview_text(
                vehicle.get("chassis_number")
            )
        }


        existing_preview_records = []

        if incoming_chassis_numbers:
            existing_preview_records.extend(
                Vehicle.query.filter(
                    Vehicle.company_code
                    == session.get("company_code"),
                    db.func.trim(
                        Vehicle.chassis_number
                    ).in_(incoming_chassis_numbers)
                ).all()
            )

        existing_preview_by_chassis = {}

        for existing_vehicle in existing_preview_records:

            existing_chassis = clean_preview_text(
                existing_vehicle.chassis_number
            )

            if existing_chassis:
                existing_preview_by_chassis[
                    existing_chassis
                ] = existing_vehicle

        # この会社で過去に保存した
        # Excel車種コード → 車種名 の対応を取得
        vehicle_type_mappings = VehicleTypeImportMapping.query.filter_by(
            company_code=session.get("company_code")
        ).all()

        valid_vehicle_type_names = {
            vehicle_type.name
            for vehicle_type in VehicleType.query.filter_by(
                company_code=session.get("company_code")
            ).all()
        }

        vehicle_type_mapping_dict = {
            mapping.excel_value: mapping.vehicle_type_name
            for mapping in vehicle_type_mappings
            if mapping.vehicle_type_name in valid_vehicle_type_names
        }

        for vehicle in vehicles_data:
            vehicle["mapped_vehicle_type"] = (
                vehicle_type_mapping_dict.get(
                    vehicle.get("vehicle_type_code", ""),
                    ""
                )
            )
            
        processed_import_keys = set()

        for vehicle in vehicles_data:

            chassis_number = clean_preview_text(
                vehicle.get("chassis_number")
            )

            if not chassis_number:
                return (
                    f"{vehicle.get('excel_row')}行目の車台番号を入力してください。",
                    400
                )

            import_key = (
                "chassis",
                chassis_number
            )

            existing_vehicle = (
                existing_preview_by_chassis.get(
                    chassis_number
                )
            )

            is_excel_duplicate = (
                import_key in processed_import_keys
            )

            if existing_vehicle:

                if not clean_preview_text(
                    vehicle.get("mapped_vehicle_type")
                ):
                    existing_vehicle_type = clean_preview_text(
                        existing_vehicle.type
                    )

                    if (
                        existing_vehicle_type
                        in valid_vehicle_type_names
                    ):
                        vehicle["mapped_vehicle_type"] = (
                            existing_vehicle_type
                        )

                if existing_vehicle.deleted:
                    vehicle["reactivate"] = True
                else:
                    vehicle["reactivate"] = False

                update_values = {
                    "plate_area": clean_preview_text(
                        vehicle.get("plate_area")
                    ),
                    "plate_class": clean_preview_text(
                        vehicle.get("plate_class")
                    ),
                    "plate_kana": clean_preview_text(
                        vehicle.get("plate_kana")
                    ),
                    "plate_number": clean_preview_text(
                        vehicle.get("plate_number")
                    ),
                    "gross_vehicle_weight": preview_int(
                        vehicle.get(
                            "gross_vehicle_weight"
                        )
                    ),
                    "model_code": clean_preview_text(
                        vehicle.get("model_code")
                    ),
                    "first_registration_date":
                        clean_preview_text(
                            vehicle.get(
                                "first_registration_date"
                            )
                        ),
                    "inspection_expiry":
                        clean_preview_text(
                            vehicle.get(
                                "inspection_expiry"
                            )
                        ),
                    "manufacturer": clean_preview_text(
                        vehicle.get("vehicle_name")
                    ),
                    "body_type": clean_preview_text(
                        vehicle.get("body_type")
                    ),
                    "max_payload": preview_int(
                        vehicle.get("max_payload")
                    ),
                }

                vehicle_changed = False
                if vehicle.get("reactivate"):
                    vehicle_changed = True

                for field_name, new_value in (
                    update_values.items()
                ):
                    # Excelが空欄なら既存値を維持
                    if new_value in ("", None):
                        continue

                    old_value = getattr(
                        existing_vehicle,
                        field_name
                    )

                    if isinstance(new_value, int):
                        try:
                            old_value = int(old_value)
                        except (TypeError, ValueError):
                            old_value = None
                    else:
                        old_value = clean_preview_text(
                            old_value
                        )

                    if old_value != new_value:
                        vehicle_changed = True
                        break

                mapped_vehicle_type = clean_preview_text(
                    vehicle.get("mapped_vehicle_type")
                )

                if (
                    mapped_vehicle_type
                    and clean_preview_text(existing_vehicle.type)
                    != mapped_vehicle_type
                ):
                    vehicle_changed = True
                        
                if vehicle_changed:
                    vehicle["import_status"] = "更新"
                else:
                    vehicle["import_status"] = (
                        "変更なし"
                    )

            else:
                vehicle["import_status"] = "新規"

            vehicle["base_import_status"] = (
                vehicle["import_status"]
            )

            if is_excel_duplicate:
                vehicle["import_status"] = (
                    "Excel内重複"
                )
            processed_import_keys.add(import_key)



        return render_template(
            "vehicle_import_preview.html",
            vehicles=vehicles_data,
            vehicle_types=vehicle_types_for_current_company(),
            vehicle_type_mapping_dict=vehicle_type_mapping_dict,
        )
    
    return render_template(
        "vehicle_import.html"
    )

@app.route("/master/vehicles/import/confirm", methods=["POST"])
@limiter.limit("10 per minute")
def confirm_vehicle_import():

    company_code = session.get("company_code")

    vehicle_type_codes = request.form.getlist(
        "vehicle_type_code"
    )

    vehicle_types = request.form.getlist(
        "vehicle_type"
    )

    valid_vehicle_type_names = {
        vehicle_type.name
        for vehicle_type in VehicleType.query.filter_by(
            company_code=company_code
        ).all()
    }

    vehicle_types = [
        str(value or "").strip()
        if str(value or "").strip() in valid_vehicle_type_names
        else ""
        for value in vehicle_types
    ]
    
    plate_areas = request.form.getlist("plate_area")
    plate_classes = request.form.getlist("plate_class")
    plate_kanas = request.form.getlist("plate_kana")
    plate_numbers = request.form.getlist("plate_number")

    gross_weights = request.form.getlist("gross_vehicle_weight")
    chassis_numbers = request.form.getlist("chassis_number")
    model_codes = request.form.getlist("model_code")

    first_registration_dates = request.form.getlist(
        "first_registration_date"
    )

    inspection_expiries = request.form.getlist(
        "inspection_expiry"
    )

    vehicle_names = request.form.getlist("vehicle_name")
    body_types = request.form.getlist("body_type")
    max_payloads = request.form.getlist("max_payload")

    form_lists = [
        vehicle_type_codes,
        vehicle_types,
        plate_areas,
        plate_classes,
        plate_kanas,
        plate_numbers,
        gross_weights,
        chassis_numbers,
        model_codes,
        first_registration_dates,
        inspection_expiries,
        vehicle_names,
        body_types,
        max_payloads,
    ]

    form_list_lengths = {
        len(values)
        for values in form_lists
    }

    if len(form_list_lengths) != 1:
        return (
            "取込データの件数が一致しません。"
            "Excel取込画面からやり直してください。",
            400
        )

    import_count = len(chassis_numbers)

    if import_count > 5000:
        return (
            "一度に取り込める車両は5000件までです。",
            400
        )

    if import_count == 0:
        return (
            "取込対象の車両がありません。",
            400
        )
    company = Company.query.filter_by(
        company_code=company_code
    ).first()

    current_count = Vehicle.query.filter_by(
        company_code=company_code,
        deleted=False
    ).count()


    def normalize_import_text(value):
        return str(value or "").strip()

    import_chassis_numbers = {
        normalize_import_text(value)
        for value in chassis_numbers
        if normalize_import_text(value)
    }

    existing_vehicle_records = []

    if import_chassis_numbers:
        existing_vehicle_records.extend(
            Vehicle.query.filter(
                Vehicle.company_code == company_code,
                db.func.trim(
                    Vehicle.chassis_number
                ).in_(import_chassis_numbers)
            ).all()
        )

    existing_vehicles_by_chassis = {}

    for existing_vehicle in existing_vehicle_records:

        existing_chassis = normalize_import_text(
            existing_vehicle.chassis_number
        )

        if existing_chassis:
            existing_vehicles_by_chassis[
                existing_chassis
            ] = existing_vehicle

    counted_import_keys = set()
    new_vehicle_count = 0
    reactivate_vehicle_count = 0

    for i in range(import_count):

        chassis_number = normalize_import_text(
            chassis_numbers[i]
        )

        if not chassis_number:
            return (
                f"{i + 1}行目の車台番号を入力してください。",
                400
            )

        import_key = (
            "chassis",
            chassis_number
        )

        existing_vehicle = (
            existing_vehicles_by_chassis.get(
                chassis_number
            )
        )

        if existing_vehicle:
            if (
                existing_vehicle.deleted
                and import_key not in counted_import_keys
            ):
                counted_import_keys.add(import_key)
                reactivate_vehicle_count += 1

            continue

        if import_key in counted_import_keys:
            continue

        counted_import_keys.add(import_key)
        new_vehicle_count += 1

    # 新規登録予定台数で上限チェック
    if company:
        if (
            current_count
            + new_vehicle_count
            + reactivate_vehicle_count
            > company.vehicle_limit
        ):
            return (
                f"登録上限を超えます。"
                f"現在 {current_count} 台、"
                f"新規登録予定 {new_vehicle_count} 台、"
                f"再有効化予定 {reactivate_vehicle_count} 台、"
                f"上限 {company.vehicle_limit} 台です。"
            )
    # 今回のExcel内ですでに処理した車両
    processed_import_keys = set()
    processed_row_indexes = set()
    registered_count = 0
    updated_count = 0
    unchanged_count = 0
    duplicate_skip_count = 0

    def clean_text(value):
        return str(value or "").strip()

    def validate_text_length(
        value,
        field_name,
        max_length,
        row_number
    ):
        value = clean_text(value)

        if len(value) > max_length:
            return (
                None,
                f"{row_number}行目の{field_name}は"
                f"{max_length}文字以内で入力してください。"
            )

        return value, None

    def to_nonnegative_int(value, field_name, row_number):
        value = clean_text(value).replace(",", "")

        if not value:
            return None

        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None, (
                f"{row_number}行目の"
                f"{field_name}は整数で入力してください。"
            )

        if parsed < 0:
            return None, (
                f"{row_number}行目の"
                f"{field_name}は0以上で入力してください。"
            )

        if parsed > 2147483647:
            return None, (
                f"{row_number}行目の"
                f"{field_name}の値が大きすぎます。"
            )

        return parsed, None

    def validate_import_date(value, field_name, row_number):
        value = clean_text(value)

        if not value:
            return "", None

        try:
            datetime.strptime(
                value,
                "%Y-%m-%d"
            )
        except ValueError:
            return "", (
                f"{row_number}行目の"
                f"{field_name}が不正です。"
            )

        return value, None

    for i in range(import_count):

        chassis_number, error = validate_text_length(
            normalize_import_text(
                chassis_numbers[i]
            ),
            "車台番号",
            100,
            i + 1
        )

        if error:
            return error, 400

        plate_area, error = validate_text_length(
            normalize_import_text(
                plate_areas[i]
            ),
            "車番・地域名",
            50,
            i + 1
        )

        if error:
            return error, 400

        plate_class, error = validate_text_length(
            normalize_import_text(
                plate_classes[i]
            ),
            "車番・分類",
            50,
            i + 1
        )

        if error:
            return error, 400

        plate_kana, error = validate_text_length(
            normalize_import_text(
                plate_kanas[i]
            ),
            "車番・ひらがな",
            10,
            i + 1
        )

        if error:
            return error, 400

        plate_number, error = validate_text_length(
            normalize_import_text(
                plate_numbers[i]
            ),
            "車番",
            50,
            i + 1
        )

        if error:
            return error, 400

        if not chassis_number:
            return (
                f"{i + 1}行目の車台番号を入力してください。",
                400
            )

        import_key = (
            "chassis",
            chassis_number
        )

        existing_vehicle = (
            existing_vehicles_by_chassis.get(
                chassis_number
            )
        )

        # Excel内で同じ車両が重複している場合
        if import_key in processed_import_keys:
            duplicate_skip_count += 1
            continue

        processed_import_keys.add(import_key)
        processed_row_indexes.add(i)
        gross_vehicle_weight, error = to_nonnegative_int(
            gross_weights[i],
            "車両総重量",
            i + 1
        )

        if error:
            return error, 400

        max_payload, error = to_nonnegative_int(
            max_payloads[i],
            "最大積載量",
            i + 1
        )

        if error:
            return error, 400

        first_registration_date, error = validate_import_date(
            first_registration_dates[i],
            "初年度登録日",
            i + 1
        )

        if error:
            return error, 400

        inspection_expiry, error = validate_import_date(
            inspection_expiries[i],
            "車検満了日",
            i + 1
        )

        if error:
            return error, 400

        model_code, error = validate_text_length(
            model_codes[i],
            "車体型式",
            100,
            i + 1
        )

        if error:
            return error, 400

        manufacturer, error = validate_text_length(
            vehicle_names[i],
            "車両メーカー",
            100,
            i + 1
        )

        if error:
            return error, 400

        body_type, error = validate_text_length(
            body_types[i],
            "車両形状",
            100,
            i + 1
        )

        if error:
            return error, 400

        selected_vehicle_type, error = validate_text_length(
            vehicle_types[i],
            "車種",
            100,
            i + 1
        )

        if error:
            return error, 400
        
        # 車台番号が一致する既存車両を更新
        if existing_vehicle:
            update_values = {
                "plate_area": clean_text(plate_areas[i]),
                "plate_class": clean_text(plate_classes[i]),
                "plate_kana": clean_text(plate_kanas[i]),
                "plate_number": clean_text(plate_numbers[i]),
                "gross_vehicle_weight": gross_vehicle_weight,
                "model_code": model_code,
                "first_registration_date": first_registration_date,
                "inspection_expiry": inspection_expiry,
                "manufacturer": manufacturer,
                "body_type": body_type,
                "max_payload": max_payload,
            }

            vehicle_changed = False
            if existing_vehicle.deleted:
                existing_vehicle.deleted = False
                vehicle_changed = True

            for field_name, new_value in update_values.items():
                # Excelが空欄なら既存値を残す
                if new_value in ("", None):
                    continue

                if getattr(existing_vehicle, field_name) != new_value:
                    setattr(
                        existing_vehicle,
                        field_name,
                        new_value
                    )
                    vehicle_changed = True


            if clean_text(existing_vehicle.type) != selected_vehicle_type:
                existing_vehicle.type = selected_vehicle_type
                vehicle_changed = True

            if vehicle_changed:
                updated_count += 1
            else:
                unchanged_count += 1

            continue

        vehicle = Vehicle(
            company_code=company_code,

            plate_area=plate_area,
            plate_class=plate_class,
            plate_kana=plate_kana,
            plate_number=plate_number,

            gross_vehicle_weight=gross_vehicle_weight,

            chassis_number=chassis_number,
            model_code=model_code,

            first_registration_date=first_registration_date,
            inspection_expiry=inspection_expiry,

            # 画面上は「車名」だが、
            # 現在のDBでは manufacturer に保存
            manufacturer=manufacturer,

            body_type=body_type,

            max_payload=max_payload,

            # 今回のExcel登録対象外
            type=selected_vehicle_type,
            office="",

            deleted=False,
        )

        db.session.add(vehicle)

        registered_count += 1

    # Excel車種コードごとに今回選ばれた車種を整理
    mapping_candidates = {}

    for i, (
        excel_value,
        vehicle_type_name
    ) in enumerate(
        zip(
            vehicle_type_codes,
            vehicle_types
        )
    ):

        if i not in processed_row_indexes:
            continue
        
        excel_value = str(excel_value or "").strip()
        vehicle_type_name = str(
            vehicle_type_name or ""
        ).strip()

        if not excel_value:
            continue

        if len(excel_value) > 100:
            return (
                "車種コードは100文字以内で入力してください。",
                400
            )

        if len(vehicle_type_name) > 100:
            return (
                "車種は100文字以内で入力してください。",
                400
            )

        mapping_candidates.setdefault(
            excel_value,
            set()
        ).add(vehicle_type_name)

    # 同じコードの選択内容が一致している場合だけ学習
    for excel_value, selected_types in mapping_candidates.items():

        mapping = VehicleTypeImportMapping.query.filter_by(
            company_code=company_code,
            excel_value=excel_value
        ).first()

        # 同じコードに複数の車種が指定されている
        # → 自動判定できないので学習しない
        if len(selected_types) > 1:
            if mapping:
                db.session.delete(mapping)
            continue

        vehicle_type_name = next(iter(selected_types))

        if vehicle_type_name:
            if mapping:
                mapping.vehicle_type_name = vehicle_type_name
            else:
                db.session.add(
                    VehicleTypeImportMapping(
                        company_code=company_code,
                        excel_value=excel_value,
                        vehicle_type_name=vehicle_type_name
                    )
                )
        elif mapping:
            db.session.delete(mapping)
            
    db.session.commit()

    return render_template(
        "vehicle_import_complete.html",
        registered_count=registered_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
        duplicate_skip_count=duplicate_skip_count,
    )

@app.route("/master/vehicles/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def new_vehicle():
    if request.method == "POST":
        company_code = session.get("company_code")

        vehicle_count = Vehicle.query.filter_by(
            company_code=company_code,
            deleted=False
        ).count()

        company = Company.query.filter_by(
            company_code=company_code
        ).first()

        if company:
            if vehicle_count >= company.vehicle_limit:
                return "登録可能台数の上限に達しています。", 409

        first_registration_date = (
            request.form.get(
                "first_registration_date",
                ""
            ).strip()
        )

        inspection_expiry = (
            request.form.get(
                "inspection_expiry",
                ""
            ).strip()
        )

        for value, field_name in [
            (
                first_registration_date,
                "初年度登録日"
            ),
            (
                inspection_expiry,
                "車検満了日"
            )
        ]:
            if value:
                try:
                    datetime.strptime(
                        value,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    return f"{field_name}が不正です。", 400
        vehicle_type = (
            request.form.get("type", "").strip()
        )

        office = (
            request.form.get("office", "").strip()
        )
        chassis_number = (
            request.form.get("chassis_number", "").strip()
        )

        if not chassis_number:
            return "車台番号を入力してください。", 400

        duplicate_vehicle = Vehicle.query.filter_by(
            company_code=company_code,
            chassis_number=chassis_number
        ).first()

        if duplicate_vehicle:
            if not duplicate_vehicle.deleted:
                return "同じ車台番号の車両が既に登録されています。", 409

            duplicate_vehicle.deleted = False
        text_fields = [
            (
                request.form.get("plate_area", "").strip(),
                "車番・地域名",
                50
            ),
            (
                request.form.get("plate_class", "").strip(),
                "車番・分類",
                50
            ),
            (
                request.form.get("plate_kana", "").strip(),
                "車番・ひらがな",
                10
            ),
            (
                request.form.get("plate_number", "").strip(),
                "車番",
                50
            ),
            (
                request.form.get("chassis_number", "").strip(),
                "車台番号",
                100
            ),
            (
                request.form.get("model_code", "").strip(),
                "車体型式",
                100
            ),
            (
                request.form.get("manufacturer", "").strip(),
                "車両メーカー",
                100
            ),
            (
                request.form.get("body_type", "").strip(),
                "車両形状",
                100
            ),
        ]

        for value, field_name, max_length in text_fields:
            if len(value) > max_length:
                return (
                    f"{field_name}は"
                    f"{max_length}文字以内で入力してください。",
                    400
                )

        if vehicle_type:
            valid_vehicle_type = VehicleType.query.filter_by(
                company_code=company_code,
                name=vehicle_type
            ).first()

            if not valid_vehicle_type:
                return "車種が不正です。", 400

        if office:
            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=office
            ).first()

            if not valid_office:
                return "営業所が不正です。", 400
        vehicle = duplicate_vehicle or Vehicle(
            company_code=company_code,
            chassis_number=chassis_number
        )

        vehicle.deleted = False
        vehicle.plate_area = request.form.get("plate_area")
        vehicle.plate_class = request.form.get("plate_class")
        vehicle.plate_kana = request.form.get("plate_kana")
        vehicle.plate_number = request.form.get("plate_number")

        vehicle.chassis_number = chassis_number
        vehicle.model_code = request.form.get("model_code")
        vehicle.first_registration_date = first_registration_date
        vehicle.manufacturer = request.form.get("manufacturer")
        vehicle.body_type = request.form.get("body_type")

        vehicle.gross_vehicle_weight = parse_nonnegative_int(
            request.form.get("gross_vehicle_weight"),
            "車両総重量"
        )
        vehicle.max_payload = parse_nonnegative_int(
            request.form.get("max_payload"),
            "最大積載量"
        )

        vehicle.type = vehicle_type
        vehicle.office = office
        vehicle.inspection_expiry = inspection_expiry

        if not duplicate_vehicle:
            db.session.add(vehicle)
        db.session.commit()

        return redirect("/master/vehicles")

    return render_template(
        "vehicle_form.html",
        vehicle=session.pop(
            "vehicle_form_data",
            None
        ),
        offices=offices_for_current_company(),
        vehicle_types=vehicle_types_for_current_company(),
        mode="new"
    )


@app.route("/master/vehicles/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def edit_vehicle(index):
    vehicle = Vehicle.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not vehicle:
        return redirect("/master/vehicles")

    if request.method == "POST":
        chassis_number = (
            request.form.get("chassis_number", "").strip()
        )

        if not chassis_number:
            return "車台番号を入力してください。", 400

        duplicate_vehicle = Vehicle.query.filter(
            Vehicle.company_code == vehicle.company_code,
            Vehicle.chassis_number == chassis_number,
            Vehicle.id != vehicle.id
        ).first()

        if duplicate_vehicle:
            return "同じ車台番号の車両が既に登録されています。", 409

        first_registration_date = (
            request.form.get(
                "first_registration_date",
                ""
            ).strip()
        )

        inspection_expiry = (
            request.form.get(
                "inspection_expiry",
                ""
            ).strip()
        )

        for value, field_name in [
            (
                first_registration_date,
                "初年度登録日"
            ),
            (
                inspection_expiry,
                "車検満了日"
            )
        ]:
            if value:
                try:
                    datetime.strptime(
                        value,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    return f"{field_name}が不正です。", 400
        vehicle_type = (
            request.form.get("type", "").strip()
        )

        office = (
            request.form.get("office", "").strip()
        )

        text_fields = [
            (
                request.form.get("plate_area", "").strip(),
                "車番・地域名",
                50
            ),
            (
                request.form.get("plate_class", "").strip(),
                "車番・分類",
                50
            ),
            (
                request.form.get("plate_kana", "").strip(),
                "車番・ひらがな",
                10
            ),
            (
                request.form.get("plate_number", "").strip(),
                "車番",
                50
            ),
            (
                request.form.get("chassis_number", "").strip(),
                "車台番号",
                100
            ),
            (
                request.form.get("model_code", "").strip(),
                "車体型式",
                100
            ),
            (
                request.form.get("manufacturer", "").strip(),
                "車両メーカー",
                100
            ),
            (
                request.form.get("body_type", "").strip(),
                "車両形状",
                100
            ),
        ]

        for value, field_name, max_length in text_fields:
            if len(value) > max_length:
                return (
                    f"{field_name}は"
                    f"{max_length}文字以内で入力してください。",
                    400
                )

        if vehicle_type:
            valid_vehicle_type = VehicleType.query.filter_by(
                company_code=vehicle.company_code,
                name=vehicle_type
            ).first()

            if not valid_vehicle_type:
                return "車種が不正です。", 400

        if office:
            valid_office = Office.query.filter_by(
                company_code=vehicle.company_code,
                name=office
            ).first()

            if not valid_office:
                return "営業所が不正です。", 400
        vehicle.plate_area = request.form.get("plate_area")
        vehicle.plate_class = request.form.get("plate_class")
        vehicle.plate_kana = request.form.get("plate_kana")
        vehicle.plate_number = request.form.get("plate_number")

        vehicle.chassis_number = chassis_number
        vehicle.model_code = request.form.get("model_code")
        vehicle.first_registration_date = first_registration_date
        vehicle.manufacturer = request.form.get("manufacturer")
        vehicle.body_type = request.form.get("body_type")

        vehicle.gross_vehicle_weight = parse_nonnegative_int(
            request.form.get("gross_vehicle_weight"),
            "車両総重量"
        )

        vehicle.max_payload = parse_nonnegative_int(
            request.form.get("max_payload"),
            "最大積載量"
        )

        vehicle.type = vehicle_type
        vehicle.office = office
        vehicle.inspection_expiry = inspection_expiry

        db.session.commit()

        return redirect("/master/vehicles")

    vehicle_dict = {
        "vehicle_record_id": vehicle.id,
        "plate_area": vehicle.plate_area,
        "plate_class": vehicle.plate_class,
        "plate_kana": vehicle.plate_kana,
        "plate_number": vehicle.plate_number,
        "chassis_number": vehicle.chassis_number,
        "model_code": vehicle.model_code,
        "first_registration_date": vehicle.first_registration_date,
        "manufacturer": vehicle.manufacturer,
        "body_type": vehicle.body_type,
        "gross_vehicle_weight": vehicle.gross_vehicle_weight,
        "max_payload": vehicle.max_payload,
        "number": vehicle_number({
            "chassis_number": vehicle.chassis_number,
            "plate_area": vehicle.plate_area,
            "plate_class": vehicle.plate_class,
            "plate_kana": vehicle.plate_kana,
            "plate_number": vehicle.plate_number,
        }),
        "type": vehicle.type,
        "office": vehicle.office,
        "inspection_expiry": vehicle.inspection_expiry,
    }

    return render_template(
        "vehicle_form.html",
        vehicle=vehicle_dict,
        index=vehicle.id,
        offices=offices_for_current_company(),
        vehicle_types=vehicle_types_for_current_company(),
        mode="edit"
    )

@app.route("/master/vehicles/<int:index>/inactive", methods=["POST"])
@limiter.limit("10 per minute")
def toggle_vehicle_inactive(index):

    vehicle = Vehicle.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not vehicle:
        return redirect("/master/vehicles")

    new_inactive = (
        request.form.get("inactive") == "1"
    )

    # 無効から有効へ戻す場合は登録上限を確認
    if vehicle.deleted and not new_inactive:
        company = Company.query.filter_by(
            company_code=vehicle.company_code
        ).first()

        current_active_count = Vehicle.query.filter_by(
            company_code=vehicle.company_code,
            deleted=False
        ).count()

        if (
            company
            and current_active_count >= company.vehicle_limit
        ):
            return (
                f"登録上限を超えるため有効化できません。"
                f"現在 {current_active_count} 台、"
                f"上限 {company.vehicle_limit} 台です。"
            )

    vehicle.deleted = new_inactive

    db.session.commit()

    return redirect("/master/vehicles")

@app.route("/master/vehicles/bulk-delete", methods=["POST"])
@limiter.limit("10 per minute")
def bulk_delete_vehicles():

    vehicle_indexes = request.form.getlist("vehicle_ids")

    if len(vehicle_indexes) > 1000:
        return "一度に処理できる車両は1000件までです。", 400

    if not vehicle_indexes:
        return redirect("/master/vehicles")

    company_code = session.get("company_code")

    vehicles_to_delete = Vehicle.query.filter(
        Vehicle.id.in_(vehicle_indexes),
        Vehicle.company_code == company_code
    ).all()

    if not vehicles_to_delete:
        return redirect("/master/vehicles")

    vehicle_record_ids_to_delete = {
        vehicle.id
        for vehicle in vehicles_to_delete
    }

    vehicle_patrol_in_use = VehiclePatrol.query.filter(
        VehiclePatrol.company_code == company_code,
        VehiclePatrol.vehicle_record_id.in_(
            vehicle_record_ids_to_delete
        )
    ).first()

    vehicle_checklist_in_use = VehicleChecklistResult.query.filter(
        VehicleChecklistResult.company_code == company_code,
        VehicleChecklistResult.vehicle_record_id.in_(
            vehicle_record_ids_to_delete
        )
    ).first()

    checklist_in_use = ChecklistResult.query.filter(
        ChecklistResult.company_code == company_code,
        ChecklistResult.target_vehicle_record_id.in_(
            vehicle_record_ids_to_delete
        )
    ).first()

    if (
        vehicle_patrol_in_use
        or vehicle_checklist_in_use
        or checklist_in_use
    ):
        return (
            "履歴がある車両を含むため完全削除できません。"
            "対象車両は無効化してください。",
            409
        )

    delete_vehicle_patterns = [
        f'"{vehicle_record_id}"'
        for vehicle_record_id in vehicle_record_ids_to_delete
    ]


    # ドライバーの車両割当から削除
    driver_query = Driver.query.filter(
        Driver.company_code == company_code
    )

    if delete_vehicle_patterns:
        driver_query = driver_query.filter(
            db.or_(
                *[
                    Driver.vehicles_json.contains(pattern)
                    for pattern in delete_vehicle_patterns
                ]
            )
        )

    for driver in driver_query.all():

        driver_vehicles = safe_json_str_list(
            driver.vehicles_json
        )

        new_driver_vehicles = [
            vehicle_record_id
            for vehicle_record_id in driver_vehicles
            if vehicle_record_id not in {
                str(record_id)
                for record_id in vehicle_record_ids_to_delete
            }
        ]

        if new_driver_vehicles != driver_vehicles:

            driver.vehicles_json = json.dumps(
                new_driver_vehicles,
                ensure_ascii=False
            )
    # 車両に紐づく通知設定を削除してから車両本体を完全削除
    for vehicle in vehicles_to_delete:

        delete_vehicle_related_data(vehicle)

        add_audit_log(
            action="vehicle_deleted",
            target_type="vehicle",
            target_id=vehicle.id,
            detail="車両一括削除による完全削除",
            company_code=vehicle.company_code,
        )

        db.session.delete(vehicle)


    db.session.commit()

    return redirect("/master/vehicles")

@app.route("/master/vehicles/bulk-inactive", methods=["POST"])
@limiter.limit("10 per minute")
def bulk_inactive_vehicles():

    company_code = session.get("company_code")

    vehicle_indexes = request.form.getlist("vehicle_ids")

    if len(vehicle_indexes) > 1000:
        return "一度に処理できる車両は1000件までです。", 400

    if not vehicle_indexes:
        return redirect("/master/vehicles")

    vehicles_to_inactivate = Vehicle.query.filter(
        Vehicle.id.in_(vehicle_indexes),
        Vehicle.company_code == company_code,
        Vehicle.deleted == False
    ).all()

    Vehicle.query.filter(
        Vehicle.id.in_(vehicle_indexes),
        Vehicle.company_code == company_code
    ).update(
        {"deleted": True},
        synchronize_session=False
    )

    for vehicle in vehicles_to_inactivate:
        add_audit_log(
            action="vehicle_inactivated",
            target_type="vehicle",
            target_id=vehicle.id,
            detail="車両を一括無効化",
            company_code=vehicle.company_code,
        )

    db.session.commit()

    return redirect("/master/vehicles")

@app.route("/master/vehicles/bulk-active", methods=["POST"])
@limiter.limit("10 per minute")
def bulk_active_vehicles():

    company_code = session.get("company_code")
    vehicle_indexes = request.form.getlist("vehicle_ids")

    if len(vehicle_indexes) > 1000:
        return "一度に処理できる車両は1000件までです。", 400

    if not vehicle_indexes:
        return redirect("/master/vehicles")

    vehicles_to_activate = Vehicle.query.filter(
        Vehicle.id.in_(vehicle_indexes),
        Vehicle.company_code == company_code,
        Vehicle.deleted == True
    ).all()

    if not vehicles_to_activate:
        return redirect("/master/vehicles")

    company = Company.query.filter_by(
        company_code=company_code
    ).first()

    current_active_count = Vehicle.query.filter_by(
        company_code=company_code,
        deleted=False
    ).count()

    activate_count = len(vehicles_to_activate)

    if (
        company
        and current_active_count + activate_count
        > company.vehicle_limit
    ):
        return (
            f"登録上限を超えるため有効化できません。"
            f"現在 {current_active_count} 台、"
            f"有効化予定 {activate_count} 台、"
            f"上限 {company.vehicle_limit} 台です。"
        )

    for vehicle in vehicles_to_activate:
        vehicle.deleted = False

    for vehicle in vehicles_to_activate:
        add_audit_log(
            action="vehicle_activated",
            target_type="vehicle",
            target_id=vehicle.id,
            detail="車両を一括有効化",
            company_code=vehicle.company_code,
        )
        
    db.session.commit()

    return redirect("/master/vehicles")

@app.route("/master/vehicles/<int:index>/delete", methods=["POST"])
@limiter.limit("10 per minute")
def delete_vehicle(index):
    vehicle = Vehicle.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not vehicle:
        return redirect("/master/vehicles")

    vehicle_record_id = vehicle.id

    vehicle_patrol_in_use = VehiclePatrol.query.filter_by(
        company_code=vehicle.company_code,
        vehicle_record_id=vehicle_record_id
    ).first()

    vehicle_checklist_in_use = VehicleChecklistResult.query.filter_by(
        company_code=vehicle.company_code,
        vehicle_record_id=vehicle_record_id
    ).first()

    checklist_in_use = ChecklistResult.query.filter_by(
        company_code=vehicle.company_code,
        target_vehicle_record_id=vehicle_record_id
    ).first()

    if (
        vehicle_patrol_in_use
        or vehicle_checklist_in_use
        or checklist_in_use
    ):
        return (
            "履歴がある車両は完全削除できません。"
            "無効化してください。",
            409
        )

    vehicle_record_id_str = str(vehicle_record_id)

    for driver in Driver.query.filter(
        Driver.company_code == vehicle.company_code,
        Driver.vehicles_json.contains(f'"{vehicle_record_id_str}"')
    ).all():
        vehicles = safe_json_str_list(
            driver.vehicles_json
        )

        if vehicle_record_id_str in vehicles:
            vehicles.remove(vehicle_record_id_str)
            driver.vehicles_json = json.dumps(
                vehicles,
                ensure_ascii=False
            )
    # 車両に紐づく通知設定を削除
    delete_vehicle_related_data(vehicle)

    add_audit_log(
        action="vehicle_deleted",
        target_type="vehicle",
        target_id=vehicle.id,
        detail="車両を完全削除",
        company_code=vehicle.company_code,
    )

    # 車両本体を完全削除
    db.session.delete(vehicle)

    db.session.commit()
    return redirect("/master/vehicles")

@app.route("/master/manuals")
def manual_master():
    return render_template(
        "manual_master.html",
        manuals=manuals_for_current_company()
    )

@app.route("/master/manuals/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def new_manual():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()

        if not title:
            return "タイトルを入力してください。", 400

        if len(title) > 200:
            return "タイトルは200文字以内で入力してください。", 400

        if len(category) > 100:
            return "カテゴリは100文字以内で入力してください。", 400

        file = request.files.get("file")

        filename = save_uploaded_file(
            file,
            folder="static/manuals"
        )

        manual = Manual(
            company_code=session.get("company_code"),
            title=title,
            category=category,
            filename=filename
        )

        db.session.add(manual)
        db.session.commit()

        return redirect("/master/manuals")

    return render_template(
        "manual_form.html",
        manual=None,
        index=None,
        mode="new"
    )

@app.route("/master/manuals/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def edit_manual(index):
    manual = Manual.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not manual:
        return redirect("/master/manuals")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()

        if not title:
            return "タイトルを入力してください。", 400

        if len(title) > 200:
            return "タイトルは200文字以内で入力してください。", 400

        if len(category) > 100:
            return "カテゴリは100文字以内で入力してください。", 400

        manual.title = title
        manual.category = category

        file = request.files.get("file")
        filename = save_uploaded_file(
            file,
            folder="static/manuals"
        )

        if filename:
            manual.filename = filename

        db.session.commit()

        return redirect("/master/manuals")

    manual_dict = {
        "id": manual.id,
        "index": manual.id,
        "company_code": manual.company_code,
        "title": manual.title,
        "category": manual.category,
        "filename": manual.filename,
    }

    return render_template(
        "manual_form.html",
        manual=manual_dict,
        index=manual.id,
        mode="edit"
    )

@app.route("/master/manuals/<int:index>/delete", methods=["POST"])
@limiter.limit("10 per minute")
def delete_manual(index):
    manual = Manual.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not manual:
        return redirect("/master/manuals")

    add_audit_log(
        action="manual_deleted",
        target_type="manual",
        target_id=manual.id,
        detail=f"マニュアル削除: {manual.title}",
        company_code=manual.company_code,
    )

    db.session.delete(manual)
    db.session.commit()

    return redirect("/master/manuals")

@app.route("/master/checklists")
def checklist_master():
    checklists = checklists_for_current_company()
    company_code = session.get("company_code")

    for checklist in checklists:
        checklist_id = checklist["id"]

        has_safety_results = ChecklistResult.query.filter_by(
            company_code=company_code,
            checklist_id=checklist_id
        ).first()

        has_vehicle_results = VehicleChecklistResult.query.filter_by(
            company_code=company_code,
            checklist_id=checklist_id
        ).first()

        checklist["has_results"] = bool(
            has_safety_results or has_vehicle_results
        )

    return render_template(
        "checklist_master.html",
        checklists=checklists
    )

@app.route("/master/checklists/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def new_checklist():
    if request.method == "POST":

        target = request.form.get("target", "").strip()

        if target not in {
            "安全管理",
            "車両管理"
        }:
            return "用途が不正です。", 400

        item_categories = request.form.getlist("item_category")
        item_contents = request.form.getlist("item_content")
        input_types = request.form.getlist("input_type")
        item_types = request.form.getlist("item_type")
        approval_labels = request.form.getlist("approval_label")
        approval_allow_general_list = request.form.getlist("approval_allow_general")
        choices_list = request.form.getlist("choices")
        criteria_list = request.form.getlist("criteria")
        comment_required_list = request.form.getlist("comment_required")
        shaded_list = request.form.getlist("shaded")

        if len(item_types) > 500:
            return "チェック項目は500件以内で設定してください。", 400

        if any(
            item_type not in {
                "check",
                "inspector",
                "approval"
            }
            for item_type in item_types
        ):
            return "項目種別が不正です。", 400

        if any(
            input_type not in {
                "select",
                "text"
            }
            for input_type in input_types
        ):
            return "評価方式が不正です。", 400

        required_list_length = len(item_types)

        if any(
            len(values) < required_list_length
            for values in [
                item_categories,
                item_contents,
                input_types,
                choices_list,
                criteria_list
            ]
        ):
            return "チェック項目のデータが不正です。", 400

        score_enabled = request.form.get("score_enabled") == "1"
        print_portrait = (
            request.form.get("target") == "車両管理"
            and request.form.get("print_portrait") == "1"
        )
        print_half_month = (
            request.form.get("target") == "車両管理"
            and request.form.get("print_half_month") == "1"
        )

        reminder_enabled = (
            request.form.get("reminder_enabled") == "1"
        )

        reminder_time = parse_time_hhmm(
            request.form.get("reminder_time") or "08:00",
            "未実施通知時刻"
        )

        items = []
        pending_criteria_files = []

        for i in range(len(item_types)):
            item_type = item_types[i]

            if item_type == "inspector":
                items.append({
                    "item_type": "inspector",
                })
                continue

            if item_type == "approval":
                label = ""

                if i < len(approval_labels):
                    label = approval_labels[i].strip()

                if len(label) > 100:
                    return (
                        "承認ラベルは100文字以内で入力してください。",
                        400
                    )

                items.append({
                    "item_type": "approval",
                    "approval_label": label,
                    "approval_allow_general": str(i) in approval_allow_general_list,
                    "criteria_files": [],
                })

                continue

            if i >= len(item_contents):
                continue

            if not item_contents[i]:
                continue

            category = str(
                item_categories[i] or ""
            ).strip()
            content = str(
                item_contents[i] or ""
            ).strip()
            criteria = str(
                criteria_list[i] or ""
            ).strip()

            if len(category) > 100:
                return (
                    "カテゴリは100文字以内で入力してください。",
                    400
                )

            if len(content) > 500:
                return (
                    "チェック内容は500文字以内で入力してください。",
                    400
                )

            if len(criteria) > 500:
                return (
                    "判定基準は500文字以内で入力してください。",
                    400
                )

            choices = []

            if input_types[i] == "select":
                choices = [
                    choice.strip()
                    for choice in choices_list[i].split(",")
                    if choice.strip()
                ]

                if not choices:
                    return (
                        "選択式のチェック項目には評価の選択肢を1つ以上入力してください。",
                        400
                    )

                if len(choices) > 100:
                    return (
                        "選択肢は100個以内で入力してください。",
                        400
                    )

                if any(
                    len(choice) > 100
                    for choice in choices
                ):
                    return (
                        "各選択肢は100文字以内で入力してください。",
                        400
                    )

            item_index = len(items)

            items.append({
                "item_type": "check",
                "category": category,
                "content": content,
                "input_type": input_types[i],
                "choices": choices,
                "criteria": criteria,
                "criteria_files": [],
                "comment_required": str(i) in comment_required_list,
                "shaded": str(i) in shaded_list,
                "score_enabled": score_enabled,
            })

            pending_criteria_files.append((item_index, i))

        frequency_value = ""
        frequency_unit = ""
        display_type = ""

        if target == "車両管理":
            frequency_value = request.form.get(
                "frequency_value",
                ""
            ).strip()
            frequency_unit = request.form.get(
                "frequency_unit",
                ""
            ).strip()
            display_type = request.form.get(
                "display_type",
                ""
            ).strip()

            try:
                frequency_number = int(frequency_value)
            except (TypeError, ValueError):
                return "頻度は整数で入力してください。", 400

            if frequency_number < 1:
                return "頻度は1以上で入力してください。", 400

            if frequency_number > 9999:
                return "頻度は9999以下で入力してください。", 400

            frequency_value = str(frequency_number)

            if frequency_unit not in {
                "day",
                "month",
                "year"
            }:
                return "頻度単位が不正です。", 400

            if display_type not in {
                "month",
                "year"
            }:
                return "表示形式が不正です。", 400

        name = request.form.get("name", "").strip()

        if not name:
            return "チェックリスト名を入力してください。", 400

        if len(name) > 200:
            return "チェックリスト名は200文字以内で入力してください。", 400

        if Checklist.query.filter_by(
            company_code=session.get("company_code"),
            name=name
        ).first():
            return "このチェックリストはすでに登録されています。", 409

        for item_index, form_index in pending_criteria_files:
            for file in request.files.getlist(
                f"criteria_files_{form_index}"
            ):
                filename = save_uploaded_file(file)

                if filename:
                    items[item_index]["criteria_files"].append(filename)

        checklist = Checklist(
            company_code=session.get("company_code"),
            name=name,
            target=target,
            frequency_value=frequency_value,
            frequency_unit=frequency_unit,
            display_type=display_type,
            print_portrait=print_portrait,
            print_half_month=print_half_month,
            reminder_enabled=reminder_enabled,
            reminder_time=reminder_time,
            items_json=json.dumps(items, ensure_ascii=False)
        )

        db.session.add(checklist)
        db.session.commit()

        return redirect("/master/checklists")

    return render_template(
        "checklist_form.html",
        checklist=None,
        index=None,
        mode="new"
    )

@app.route("/safety/checklists")
def safety_checklists():
    safety_lists = []

    for checklist in checklists_for_current_company():
        if (
            checklist["target"] == "安全管理"
            and checklist.get("active", True)
        ):
            safety_lists.append(checklist)

    return render_template(
        "safety_checklists.html",
        checklists=safety_lists
    )

@app.route("/safety/checklists/<int:index>")
def safety_checklist_results(index):
    checklist_record = Checklist.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not checklist_record:
        return redirect("/safety/checklists")

    checklist = checklist_to_dict(checklist_record)

    version_history = []

    for version in checklist.get("version_history", []):
        try:
            change_datetime = datetime.strptime(
                version.get("effective_until", ""),
                "%Y-%m-%d %H:%M:%S"
            )
        except (TypeError, ValueError):
            continue

        version_history.append({
            "change_date": change_datetime.date(),
            "snapshot": version.get("snapshot") or {}
        })

    version_history.sort(
        key=lambda version: version["change_date"]
    )

    results = []

    query = ChecklistResult.query.filter_by(
        company_code=session.get("company_code"),
        checklist_id=checklist_record.id
    )

    target_type = request.args.get("target_type", "").strip()
    target_value = request.args.get("target_value", "").strip()

    if target_type == "user" and target_value:
        query = query.filter(
            ChecklistResult.target_type == "user",
            ChecklistResult.target_username == target_value
        )

    elif target_type == "vehicle" and target_value:
        if not target_value.isdigit():
            return "対象車両が不正です。", 400

        query = query.filter(
            ChecklistResult.target_type == "vehicle",
            ChecklistResult.target_vehicle_record_id == int(target_value)
        )

    elif target_type == "office" and target_value:
        query = query.filter(
            ChecklistResult.target_type == "office",
            ChecklistResult.target_office == target_value
        )

    query = query.filter_by(
        company_code=session.get("company_code")
    )

    for result in query.order_by(ChecklistResult.id.desc()).all():
        item = checklist_result_to_dict(result)

        if not can_view_checklist_result(item):
            continue

        item["can_manage"] = can_manage_checklist_result(item)

        result_checklist = (
            item.get("checklist_snapshot")
            or checklist_for_date(
                checklist,
                item.get("checked_date", "")[:4],
                item.get("checked_date", "")[5:7],
                item.get("checked_date", "")[8:10]
            )
        )

        item["checklist_revision_key"] = checklist_revision_key(
            result_checklist
        )

        results.append(item)
    checklist_periods = []

    current_period = None

    # 期間判定は古い結果 → 新しい結果の順で行う
    for result in reversed(results):
        try:
            result_date = datetime.strptime(
                result.get("checked_date", ""),
                "%Y-%m-%d %H:%M"
            ).date()
        except (TypeError, ValueError):
            continue

        checklist_key = result.get(
            "checklist_revision_key"
        )

        if (
            current_period is None
            or checklist_key
            != current_period["checklist_revision_key"]
        ):
            current_period = {
                "start_date": result_date,
                "end_date": result_date,
                "checklist_revision_key": checklist_key,
                "checklist": (
                    result.get("checklist_snapshot")
                    or checklist
                ),
                "results": []
            }
            checklist_periods.append(current_period)
        else:
            current_period["end_date"] = result_date

        current_period["results"].append(result)

    # 一覧では最新の様式・最新の結果を上に表示する
    for period in checklist_periods:
        period["results"].reverse()

    checklist_periods.reverse()

    return render_template(
        "safety_checklist_results.html",
        checklist=checklist,
        checklist_index=checklist_record.id,
        results=results,
        checklist_periods=checklist_periods
    )


@app.route("/safety/checklist-results/<int:result_index>")
def checklist_result_detail(result_index):
    result_record = ChecklistResult.query.filter_by(
        id=result_index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/safety/checklists")

    result = checklist_result_to_dict(result_record)

    if not can_view_checklist_result(result):
        return redirect("/safety/checklists")

    checklist_record = Checklist.query.filter_by(
        id=result_record.checklist_id,
        company_code=result_record.company_code
    ).first()

    if not checklist_record:
        return redirect("/safety/checklists")

    checklist = (
        result.get("checklist_snapshot")
        or checklist_to_dict(checklist_record)
    )
    if not result.get("approvals"):
        approvals = []

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get("approval_allow_general", False),
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        result["approvals"] = approvals

    criteria_list = []

    for answer in result["answers"]:
        criteria = answer.get("criteria", "")
        if criteria and criteria not in criteria_list:
            criteria_list.append(criteria)

    summary = {}
    total_score = 0
    max_score = 0

    check_items = [
        item
        for item in checklist["items"]
        if item.get("item_type") != "approval"
    ]

    for item, answer in zip(check_items, result["answers"]):
        value = answer.get("value")

        # 自由記入は集計対象外
        if item.get("input_type") != "select":
            continue

        if value:
            if value not in summary:
                summary[value] = 0

            summary[value] += 1

        # 点数集計ONの場合だけ数値として計算
        if checklist.get("score_enabled"):
            try:
                total_score += float(value)
            except (TypeError, ValueError):
                pass

            numeric_choices = []

            for choice in item.get("choices", []):
                try:
                    numeric_choices.append(float(choice))
                except (TypeError, ValueError):
                    pass

            if numeric_choices:
                max_score += max(numeric_choices)

    return render_template(
        "checklist_result_detail.html",
        result=result,
        result_index=result_record.id,
        summary=summary,
        total_score=total_score,
        max_score=max_score,
        criteria_list=criteria_list,
        checklist=checklist,
        can_manage=can_manage_checklist_result(result),
        can_reject=can_reject_checklist_result(result),
    )

@app.route("/safety/checklist-results/<int:result_index>/excel")
def export_checklist_result_excel(result_index):

    result_record = ChecklistResult.query.filter_by(
        id=result_index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/safety/checklists")

    result = checklist_result_to_dict(result_record)

    if not can_view_checklist_result(result):
        return redirect("/safety/checklists")

    checklist_record = Checklist.query.filter_by(
        id=result_record.checklist_id,
        company_code=result_record.company_code
    ).first()

    if not checklist_record:
        return redirect("/safety/checklists")

    checklist = (
        result.get("checklist_snapshot")
        or checklist_to_dict(checklist_record)
    )
    # 評価基準
    criteria_list = []

    for answer in result["answers"]:
        criteria = answer.get("criteria", "")

        if criteria and criteria not in criteria_list:
            criteria_list.append(criteria)


    # チェック項目
    check_items = [
        item
        for item in checklist["items"]
        if item.get("item_type") != "approval"
    ]


    # 評価集計・合計点
    summary = {}
    total_score = 0
    max_score = 0

    for item, answer in zip(
        check_items,
        result["answers"]
    ):
        value = answer.get("value")

        # 自由記入は集計対象外
        if item.get("input_type") != "select":
            continue

        if value:
            summary[value] = summary.get(value, 0) + 1

        # 点数集計ONの場合だけ計算
        if checklist.get("score_enabled"):

            try:
                total_score += float(value)
            except (TypeError, ValueError):
                pass

            numeric_choices = []

            for choice in item.get("choices", []):
                try:
                    numeric_choices.append(float(choice))
                except (TypeError, ValueError):
                    pass

            if numeric_choices:
                max_score += max(numeric_choices)


    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "チェックリスト結果"
    sheet.sheet_view.view = "pageBreakPreview"
    sheet.sheet_view.showGridLines = False

    # タイトル
    sheet.merge_cells("A1:L1")

    sheet["A1"] = f"{checklist['name']} 結果"
    sheet["A1"].font = Font(size=16, bold=True)
    sheet["A1"].alignment = Alignment(
        horizontal="center",
        vertical="center"
    )

    sheet.row_dimensions[1].height = 28

    # 対象表示
    if result["target_type"] == "user":
        target_type_label = "ユーザー"
        target_value = result["target_user"] or "-"
    elif result["target_type"] == "vehicle":
        target_type_label = "車両"

        target_vehicle_record = Vehicle.query.filter_by(
            company_code=result["company_code"],
            id=result["target_vehicle_record_id"]
        ).first()

        target_value = (
            target_vehicle_record.chassis_number
            if target_vehicle_record
            else "-"
        )
    elif result["target_type"] == "office":
        target_type_label = "営業所"
        target_value = result["target_office"] or "-"
    else:
        target_type_label = "指定なし"
        target_value = ""

    info_rows = [
        ["実施日", result["checked_date"] or ""],
        ["点検者", result["checked_by"] or ""],
        ["対象", target_value or target_type_label],
        ["状態", result["status"] or ""],
    ]

    start_row = 3

    thin = Side(style="thin")

    for row_offset, values in enumerate(info_rows):
        row_number = start_row + row_offset

        # 見出し A:B
        sheet.merge_cells(
            start_row=row_number,
            start_column=1,
            end_row=row_number,
            end_column=2
        )

        label_cell = sheet.cell(
            row=row_number,
            column=1,
            value=values[0]
        )

        label_cell.font = Font(bold=True)
        label_cell.fill = PatternFill(
            fill_type="solid",
            fgColor="D9EAF7"
        )

        label_cell.alignment = Alignment(
            vertical="center",
            wrap_text=True
        )

        # 値 C:L
        sheet.merge_cells(
            start_row=row_number,
            start_column=3,
            end_row=row_number,
            end_column=12
        )

        value_cell = sheet.cell(
            row=row_number,
            column=3,
            value=values[1]
        )

        value_cell.alignment = Alignment(
            vertical="center",
            wrap_text=True
        )

        # 罫線
        for col_number in range(1, 13):
            sheet.cell(
                row=row_number,
                column=col_number
            ).border = Border(
                left=thin,
                right=thin,
                top=thin,
                bottom=thin
            )

    # 上部情報の下から次の表示を開始
    current_row = start_row + len(info_rows) + 2


    # 評価基準
    if criteria_list:

        criteria_title_cell = sheet.cell(
            row=current_row,
            column=1,
            value="評価基準"
        )

        criteria_title_cell.font = Font(bold=True)

        criteria_title_cell.fill = PatternFill(
            fill_type="solid",
            fgColor="D9EAF7"
        )

        # 見出しはA:Hを結合
        sheet.merge_cells(
            start_row=current_row,
            start_column=1,
            end_row=current_row,
            end_column=12
        )

        current_row += 1


        for criteria in criteria_list:

            sheet.merge_cells(
                start_row=current_row,
                start_column=1,
                end_row=current_row,
                end_column=12
            )

            criteria_cell = sheet.cell(
                row=current_row,
                column=1,
                value=criteria
            )

            criteria_cell.alignment = Alignment(
                vertical="top",
                wrap_text=True
            )

            for col_number in range(1, 13):
                sheet.cell(
                    row=current_row,
                    column=col_number
                ).border = Border(
                    left=thin,
                    right=thin,
                    top=thin,
                    bottom=thin
                )

            current_row += 1


    # 評価集計
    if checklist.get("score_enabled") and summary:

        # 見出し A:B
        sheet.merge_cells(
            start_row=current_row,
            start_column=1,
            end_row=current_row,
            end_column=2
        )

        summary_title_cell = sheet.cell(
            row=current_row,
            column=1,
            value="評価集計"
        )

        summary_title_cell.font = Font(bold=True)

        summary_title_cell.fill = PatternFill(
            fill_type="solid",
            fgColor="D9EAF7"
        )

        # 内容 C:H
        sheet.merge_cells(
            start_row=current_row,
            start_column=3,
            end_row=current_row,
            end_column=12
        )

        summary_text = " / ".join(
            f"{value}：{count}件"
            for value, count in summary.items()
        )

        sheet.cell(
            row=current_row,
            column=3,
            value=summary_text
        )

        for col_number in range(1, 13):
            sheet.cell(
                row=current_row,
                column=col_number
            ).border = Border(
                left=thin,
                right=thin,
                top=thin,
                bottom=thin
            )

        current_row += 1

    # 合計点
    if checklist.get("score_enabled"):

        # 見出し A:B
        sheet.merge_cells(
            start_row=current_row,
            start_column=1,
            end_row=current_row,
            end_column=2
        )

        score_title_cell = sheet.cell(
            row=current_row,
            column=1,
            value="合計点"
        )

        score_title_cell.font = Font(bold=True)

        score_title_cell.fill = PatternFill(
            fill_type="solid",
            fgColor="D9EAF7"
        )

        # 点数 C:H
        sheet.merge_cells(
            start_row=current_row,
            start_column=3,
            end_row=current_row,
            end_column=12
        )

        sheet.cell(
            row=current_row,
            column=3,
            value=(
                f"{int(total_score)} / {int(max_score)}点"
                if max_score
                else f"{int(total_score)}点"
            )
        )

        for col_number in range(1, 13):
            sheet.cell(
                row=current_row,
                column=col_number
            ).border = Border(
                left=thin,
                right=thin,
                top=thin,
                bottom=thin
            )

        current_row += 2

    else:
        current_row += 1

    # チェック結果
    result_header_row = current_row
    sheet.row_dimensions[result_header_row].height = 24

    # A:B = カテゴリ
    # C:G = チェック内容
    # H   = 評価
    # I:L = コメント
    header_ranges = [
        ("カテゴリ", 1, 2),
        ("チェック内容", 3, 7),
        ("評価", 8, 8),
        ("コメント", 9, 12),
    ]

    for header, start_col, end_col in header_ranges:

        sheet.merge_cells(
            start_row=current_row,
            start_column=start_col,
            end_row=current_row,
            end_column=end_col
        )

        cell = sheet.cell(
            row=current_row,
            column=start_col,
            value=header
        )

        cell.font = Font(bold=True)

        cell.fill = PatternFill(
            fill_type="solid",
            fgColor="D9EAF7"
        )

        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True
        )

        for col_number in range(
            start_col,
            end_col + 1
        ):
            sheet.cell(
                row=current_row,
                column=col_number
            ).border = Border(
                left=thin,
                right=thin,
                top=thin,
                bottom=thin
            )

    current_row += 1


    for item, answer in zip(
        check_items,
        result["answers"]
    ):

        # カテゴリ A:B
        sheet.merge_cells(
            start_row=current_row,
            start_column=1,
            end_row=current_row,
            end_column=2
        )

        sheet.cell(
            row=current_row,
            column=1,
            value=answer.get("category", "")
        )

        # チェック内容 C:G
        sheet.merge_cells(
            start_row=current_row,
            start_column=3,
            end_row=current_row,
            end_column=7
        )

        sheet.cell(
            row=current_row,
            column=3,
            value=answer.get("content", "")
        )

        # コメント I:L
        sheet.merge_cells(
            start_row=current_row,
            start_column=9,
            end_row=current_row,
            end_column=12
        )

        if item.get("input_type") == "select":

            sheet.cell(
                row=current_row,
                column=8,
                value=answer.get("value", "")
            )

            sheet.cell(
                row=current_row,
                column=9,
                value=answer.get("comment", "") or ""
            )

        else:

            sheet.cell(
                row=current_row,
                column=9,
                value=answer.get("value", "") or ""
            )

        # 罫線
        for col_number in range(1, 13):
            sheet.cell(
                row=current_row,
                column=col_number
            ).border = Border(
                left=thin,
                right=thin,
                top=thin,
                bottom=thin
            )

        current_row += 1

    # 12列構成
    # A～Lはすべて同じ幅
    for column_letter in [
        "A", "B", "C", "D", "E", "F",
        "G", "H", "I", "J", "K", "L"
    ]:
        sheet.column_dimensions[column_letter].width = 9

    # 折り返し
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(
                horizontal=cell.alignment.horizontal,
                vertical=cell.alignment.vertical or "top",
                wrap_text=True
            )


    import math
    import unicodedata


    def text_width(text):
        width = 0

        for char in str(text or ""):
            if unicodedata.east_asian_width(char) in ("W", "F", "A"):
                width += 2
            else:
                width += 1

        return width


    def wrapped_line_count(text, available_width):
        text = str(text or "")

        if not text:
            return 1

        line_count = 0

        for line in text.split("\n"):
            line_count += max(
                1,
                math.ceil(
                    text_width(line) / available_width
                )
            )

        return line_count


    # チェック項目の文字量に応じて行高を調整
    for row_number in range(
        result_header_row + 1,
        current_row
    ):

        # チェック内容 C:G
        content = sheet.cell(
            row=row_number,
            column=3
        ).value or ""

        # コメント I:L
        comment = sheet.cell(
            row=row_number,
            column=9
        ).value or ""

        content_lines = wrapped_line_count(
            content,
            52
        )

        comment_lines = wrapped_line_count(
            comment,
            41
        )

        line_count = max(
            content_lines,
            comment_lines
        )

        sheet.row_dimensions[row_number].height = max(
            20,
            (line_count * 17) + 2
        )

    # 評価列 H を中央揃え
    for row_number in range(
        result_header_row + 1,
        current_row
    ):
        sheet.cell(
            row=row_number,
            column=8
        ).alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True
        )

    # 承認・押印欄
    approval_items = [
        item
        for item in checklist["items"]
        if item.get("item_type") == "approval"
    ]

    approval_results = result.get("approvals", [])

    stamp_entries = []

    for approval_index, item in enumerate(approval_items):
        label = item.get("approval_label", "").strip()

        if not label:
            continue

        approval_result = (
            approval_results[approval_index]
            if approval_index < len(approval_results)
            else {}
        )

        stamp_entries.append({
            "label": label,
            "approved_by": approval_result.get("approved_by", ""),
            "approved_date": approval_result.get("approved_date", ""),
        })

    stamp_headers = [
        entry["label"]
        for entry in stamp_entries
    ]

    stamp_start_row = current_row + 2

    if stamp_headers:

        # 承認欄タイトル
        stamp_title_cell = sheet.cell(
            row=stamp_start_row,
            column=12,
            value="確認・押印"
        )

        stamp_title_cell.font = Font(bold=True)

        stamp_title_cell.alignment = Alignment(
            horizontal="right",
            vertical="center"
        )

        # 1行につき最大6つ
        entry_chunks = [
            stamp_entries[i:i + 6]
            for i in range(0, len(stamp_entries), 6)
        ]

        row_number = stamp_start_row + 1

        for entry_chunk in entry_chunks:

            item_count = len(entry_chunk)

            stamp_header_row = row_number
            stamp_box_row = row_number + 1

            # 押印欄はセル結合しない
            # A～Lは全列同じ幅
            # 1項目につき1セル、間に1セル空けて均等配置
            #
            # 1個 → L
            # 2個 → J / L
            # 3個 → H / J / L
            # 4個 → F / H / J / L
            # 5個 → D / F / H / J / L
            # 6個 → B / D / F / H / J / L

            all_stamp_columns = [7, 8, 9, 10, 11, 12]

            stamp_columns = all_stamp_columns[
                6 - item_count:
            ]

            for entry, column in zip(
                entry_chunk,
                stamp_columns
            ):

                # 見出し
                header_cell = sheet.cell(
                    row=stamp_header_row,
                    column=column,
                    value=entry["label"]
                )

                header_cell.font = Font(bold=True)

                header_cell.alignment = Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True
                )

                header_cell.border = Border(
                    left=thin,
                    right=thin,
                    top=thin,
                    bottom=thin
                )

                # 押印内容
                stamp_value = entry["approved_by"]

                if entry["approved_by"] and entry["approved_date"]:
                    stamp_value += (
                        f"\n{entry['approved_date']}"
                    )

                stamp_cell = sheet.cell(
                    row=stamp_box_row,
                    column=column,
                    value=stamp_value
                )

                stamp_cell.alignment = Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True
                )

                stamp_cell.border = Border(
                    left=thin,
                    right=thin,
                    top=thin,
                    bottom=thin
                )

            sheet.row_dimensions[
                stamp_header_row
            ].height = 22

            sheet.row_dimensions[
                stamp_box_row
            ].height = 55

            row_number = stamp_box_row + 1

        current_row = row_number

    # A4印刷設定
    sheet.sheet_properties.pageSetUpPr.fitToPage = True

    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.orientation = sheet.ORIENTATION_PORTRAIT
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0

    # 印刷時に水平方向の中央へ配置
    sheet.print_options.horizontalCentered = True

    # 印刷範囲
    sheet.print_area = f"A1:L{current_row - 1}"

    # 余白
    sheet.page_margins.left = 0.25
    sheet.page_margins.right = 0.25
    sheet.page_margins.top = 0.25
    sheet.page_margins.bottom = 0.25
    sheet.page_margins.header = 0.2
    sheet.page_margins.footer = 0.2

    # 2ページ目以降もチェック結果の見出しを表示
    sheet.print_title_rows = (
        f"{result_header_row}:{result_header_row}"
    )

    # 添付画像シート
    attachment_items = []

    for answer in result["answers"]:
        for filename in answer.get("files", []):
            extension = os.path.splitext(filename)[1].lower()

            if extension in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
                attachment_type = "image"

            elif extension in [
                ".mp4",
                ".webm",
                ".mov",
                ".m4v",
                ".avi",
                ".mkv",
                ".mts",
                ".m2ts",
                ".mpg",
                ".mpeg",
            ]:
                attachment_type = "video"

            else:
                continue

            attachment_items.append({
                "category": answer.get("category", ""),
                "content": answer.get("content", ""),
                "filename": filename,
                "type": attachment_type,
            })

    if attachment_items:
        attachment_sheet = workbook.create_sheet("添付画像")
        attachment_sheet.sheet_view.showGridLines = False

        attachment_sheet["A1"] = "添付画像"
        attachment_sheet["A1"].font = Font(
            size=16,
            bold=True
        )

        attachment_row = 3

        for attachment in attachment_items:
            attachment_sheet["A" + str(attachment_row)] = "カテゴリ"
            attachment_sheet["B" + str(attachment_row)] = attachment["category"]

            attachment_sheet["A" + str(attachment_row + 1)] = "チェック内容"
            attachment_sheet["B" + str(attachment_row + 1)] = attachment["content"]

            if attachment["type"] == "image":

                image_buffer = load_upload_bytes(
                    attachment["filename"]
                )

                if image_buffer:
                    excel_image = ExcelImage(image_buffer)

                    excel_image.width = 420
                    excel_image.height = 280

                    attachment_sheet.add_image(
                        excel_image,
                        f"B{attachment_row + 2}"
                    )

                attachment_sheet.row_dimensions[
                    attachment_row + 2
                ].height = 215

                attachment_row += 18

            elif attachment["type"] == "video":

                video_cell = attachment_sheet[
                    "B" + str(attachment_row + 2)
                ]

                video_cell.value = "▶ 動画を開く"

                video_cell.hyperlink = url_for(
                    "uploaded_file",
                    folder="uploads",
                    filename=attachment["filename"],
                    _external=True
                )

                video_cell.style = "Hyperlink"

                attachment_row += 5

        attachment_sheet.column_dimensions["A"].width = 14
        attachment_sheet.column_dimensions["B"].width = 65

    output = BytesIO()

    sanitize_excel_formulas(workbook)

    workbook.save(output)
    output.seek(0)

    safe_checklist_name = checklist["name"].replace("/", "_").replace("\\", "_")
    safe_checked_date = (
        (result["checked_date"] or "")
        .replace("/", "-")
        .replace(":", "-")
    )

    filename = (
        f"{safe_checklist_name}_"
        f"{safe_checked_date}_"
        f"結果.xlsx"
    )

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )

@app.route("/safety/checklist-results/<int:result_index>/edit", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
def edit_checklist_result(result_index):
    result_record = ChecklistResult.query.filter_by(
        id=result_index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/safety/checklists")

    if result_record.status == "承認済み":
        return redirect(
            f"/safety/checklist-results/{result_index}"
        )

    result = checklist_result_to_dict(result_record)

    if not can_manage_checklist_result(result):
        return redirect(f"/safety/checklist-results/{result_index}")

    checklist_record = Checklist.query.filter_by(
        id=result_record.checklist_id,
        company_code=result_record.company_code
    ).first()

    if not checklist_record:
        return redirect("/safety/checklists")

    checklist = checklist_to_dict(checklist_record)

    if request.method == "POST":
        company_code = session.get("company_code")

        target_type = request.form.get(
            "target_type",
            ""
        ).strip()

        target_user = request.form.get(
            "target_user",
            ""
        ).strip()
        target_username = ""

        target_vehicle_record_id = request.form.get(
            "target_vehicle_record_id",
            type=int
        )

        target_office = request.form.get(
            "target_office",
            ""
        ).strip()

        # =========================
        # 対象種別検証
        # =========================

        if target_type not in {
            "",
            "user",
            "vehicle",
            "office"
        }:
            return "対象種別が不正です。", 400

        # =========================
        # 個人
        # =========================

        if target_type == "user":
            if not target_user:
                return "対象ユーザーを選択してください。", 400

            target_driver = Driver.query.filter_by(
                company_code=company_code,
                employee_id=target_user
            ).first()

            if not target_driver:
                return "対象ユーザーが不正です。", 400

            target_user_record = User.query.filter_by(
                company_code=company_code,
                username=target_driver.employee_id
            ).first()

            if not target_user_record:
                return "対象ユーザー情報が不正です。", 400

            target_username = target_user_record.username
            target_user = target_driver.name

            target_office = target_driver.office or ""
            target_vehicle_record_id = None

        # =========================
        # 車両
        # =========================

        elif target_type == "vehicle":
            if not target_vehicle_record_id:
                return "対象車両を選択してください。", 400

            vehicle = Vehicle.query.filter_by(
                company_code=company_code,
                id=target_vehicle_record_id,
                deleted=False
            ).first()

            if not vehicle:
                return "対象車両が不正です。", 400

            target_office = vehicle.office or ""
            target_user = ""
            target_username = ""

        # =========================
        # 営業所
        # =========================

        elif target_type == "office":
            if not target_office:
                return "対象営業所を選択してください。", 400

            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=target_office
            ).first()

            if not valid_office:
                return "対象営業所が不正です。", 400

            target_user = ""
            target_username = ""
            target_vehicle_record_id = None

        answers = []
        answer_index = 0
        pending_answer_files = []

        for item in checklist["items"]:
            if item.get("item_type") == "approval":
                continue

            value = request.form.get(
                f"answer_{answer_index}",
                ""
            )

            choices = item.get("choices", [])

            if item.get("input_type") == "select":
                if value not in choices:
                    return "評価値が不正です。", 400

            elif not value.strip():
                return "必須項目を入力してください。", 400

            comment = request.form.get(
                f"comment_{answer_index}",
                ""
            ).strip()

            if (
                item.get("comment_required")
                and not comment
            ):
                return "必須コメントを入力してください。", 400

            if len(comment) > 5000:
                return "コメントは5000文字以内で入力してください。", 400

            file_names = []

            if answer_index < len(result["answers"]):
                file_names = list(
                    result["answers"][answer_index].get("files", [])
                )

            item_index = len(answers)

            answers.append({
                "category": item.get("category", ""),
                "content": item.get("content", ""),
                "criteria": item.get("criteria", ""),
                "criteria_files": item.get("criteria_files", []),
                "value": value,
                "comment": comment,
                "files": file_names,
                "patrol_link": False,
            })

            pending_answer_files.append(
                (item_index, answer_index)
            )

            answer_index += 1

        for item_index, form_index in pending_answer_files:
            for file in request.files.getlist(
                f"files_{form_index}"
            ):
                filename = save_uploaded_file(file)

                if filename:
                    answers[item_index]["files"].append(filename)

        result_record.target_type = target_type
        result_record.target_user = target_user
        result_record.target_username = target_username
        result_record.target_vehicle_record_id = target_vehicle_record_id
        result_record.target_office = target_office
        result_record.answers_json = json.dumps(answers, ensure_ascii=False)

        approvals = []

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get("approval_allow_general", False),
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        result_record.status = "承認待ち"
        result_record.approvals_json = json.dumps(
            approvals,
            ensure_ascii=False
        )
        result_record.approved_by = ""
        result_record.approved_by_username = ""
        result_record.approved_date = ""
        result_record.reject_reason = ""

        mention_text = "\n".join(
            "\n".join([
                answer.get("value", "") or "",
                answer.get("comment", "") or "",
            ])
            for answer in answers
        )

        db.session.commit()

        notify_mentions(
            mention_text,
            f"/safety/checklist-results/{result_record.id}"
        )

        return redirect(f"/safety/checklist-results/{result_record.id}")

    criteria_list = []

    for item in checklist["items"]:
        criteria = item.get("criteria", "")

        if criteria and criteria not in criteria_list:
            criteria_list.append(criteria)

    selected_vehicle = None

    if result.get("target_vehicle_record_id"):

        vehicle_record = Vehicle.query.filter_by(
            company_code=session.get("company_code"),
            id=result.get("target_vehicle_record_id")
        ).first()

        if vehicle_record:

            number = " ".join(
                value
                for value in [
                    vehicle_record.plate_area or "",
                    vehicle_record.plate_class or "",
                    vehicle_record.plate_kana or "",
                    vehicle_record.plate_number or "",
                ]
                if value
            )

            selected_vehicle = {
                "vehicle_record_id": vehicle_record.id,
                "chassis_number": vehicle_record.chassis_number,
                "number": number,
                "manufacturer": vehicle_record.manufacturer or "",
                "model_code": vehicle_record.model_code or "",
            }
    return render_template(
        "checklist_result_form.html",
        checklist=checklist,
        index=checklist_record.id,
        result=result,
        result_index=result_record.id,
        mode="edit",
        criteria_list=criteria_list,
        drivers=drivers_for_current_company(),
        selected_vehicle=selected_vehicle,
        offices=offices_for_current_company()
    )

@app.route("/safety/checklist-results/<int:result_index>/delete", methods=["POST"])
@limiter.limit("20 per minute")
def delete_checklist_result(result_index):
    result_record = ChecklistResult.query.filter_by(
        id=result_index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/safety/checklists")

    if result_record.status == "承認済み":
        return redirect(
            f"/safety/checklist-results/{result_index}"
        )

    result = checklist_result_to_dict(result_record)

    if not can_manage_checklist_result(result):
        return redirect(f"/safety/checklist-results/{result_index}")

    checklist_id = result_record.checklist_id

    add_audit_log(
        action="checklist_result_deleted",
        target_type="checklist_result",
        target_id=result_record.id,
        detail=f"安全チェックリスト結果削除: checklist_id={checklist_id}",
        company_code=result_record.company_code,
    )

    db.session.delete(result_record)
    db.session.commit()

    return redirect(f"/safety/checklists/{checklist_id}")

@app.route("/vehicle/checklists")
def vehicle_checklists():
    vehicle_lists = []

    for checklist in checklists_for_current_company():
        if (
            checklist["target"] == "車両管理"
            and checklist.get("active", True)
        ):
            vehicle_lists.append(checklist)

    return render_template(
        "vehicle_checklists.html",
        checklists=vehicle_lists
    )

@app.route("/vehicle/checklists/<int:index>")
def vehicle_checklist_results(index):
    checklist_record = Checklist.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not checklist_record:
        return redirect("/vehicle/checklists")

    checklist = checklist_to_dict(checklist_record)

    if checklist["target"] != "車両管理":
        return redirect("/vehicle/checklists")

    year = request.args.get(
        "year",
        str(datetime.now().year)
    ).strip()

    month = request.args.get(
        "month",
        str(datetime.now().month).zfill(2)
    ).strip()

    vehicle_record_id = request.args.get(
        "vehicle_record_id",
        type=int
    )

    try:
        year_int = int(year)
        month_int = int(month)
    except (TypeError, ValueError):
        return "表示年月が不正です。", 400

    if year_int < 2000 or year_int > 2100:
        return "表示年が不正です。", 400

    if month_int < 1 or month_int > 12:
        return "表示月が不正です。", 400

    year = str(year_int)
    month = str(month_int).zfill(2)

    if vehicle_record_id:
        valid_vehicle = Vehicle.query.filter_by(
            company_code=checklist_record.company_code,
            id=vehicle_record_id,
            deleted=False
        ).first()

        if not valid_vehicle:
            return "対象車両が不正です。", 400
        
    if checklist.get("frequency_unit") == "year":
        default_active_day = str(datetime.now().year)
    elif checklist.get("display_type") == "month":
        default_active_day = str(datetime.now().day).zfill(2)
    else:
        default_active_day = str(datetime.now().month).zfill(2)

    active_day = request.args.get("active_day", default_active_day)

    if not active_day:
        active_day = datetime.now().strftime("%d")

    display_days = []
    input_days = []
    display_weekdays = {}
    week_names = ["月", "火", "水", "木", "金", "土", "日"]

    frequency_unit = checklist.get("frequency_unit", "")
    display_mode = "month"

    if frequency_unit == "year":
        display_mode = "year_list"
        base_year = int(year)

        for y in range(base_year, base_year + 5):
            display_days.append(y)
            display_weekdays[y] = {
                "name": "",
                "is_weekend": False
            }

    elif checklist.get("display_type") == "month":
        display_mode = "day_list"

        import calendar
        last_day = calendar.monthrange(int(year), int(month))[1]

        for day in range(1, last_day + 1):
            display_days.append(day)

            weekday_index = datetime(int(year), int(month), day).weekday()

            display_weekdays[day] = {
                "name": week_names[weekday_index],
                "is_weekend": weekday_index in [5, 6]
            }

        input_days = list(range(1, last_day + 1))


    else:
        display_mode = "month_list"

        for m in range(1, 13):
            display_days.append(m)
            display_weekdays[m] = {
                "name": "",
                "is_weekend": False
            }

    checklist_periods = []

    if display_mode == "day_list":
        version_history = []

        for version in checklist.get("version_history", []):
            try:
                change_datetime = datetime.strptime(
                    version.get("effective_until", ""),
                    "%Y-%m-%d %H:%M:%S"
                )
            except (TypeError, ValueError):
                continue

            version_history.append({
                "change_date": change_datetime.date(),
                "snapshot": version.get("snapshot") or {}
            })

        version_history.sort(
            key=lambda version: version["change_date"]
        )

        current_checklist = {
            key: value
            for key, value in checklist.items()
            if key != "version_history"
        }

        current_period = None
        current_checklist_key = None

        for day in display_days:
            target_date = datetime(
                int(year),
                int(month),
                int(day)
            ).date()

            day_checklist = current_checklist

            for version in version_history:
                if target_date < version["change_date"]:
                    day_checklist = version["snapshot"]
                    break

            checklist_key = checklist_revision_key(
                day_checklist
            )

            if checklist_key != current_checklist_key:
                current_period = {
                    "start_day": day,
                    "end_day": day,
                    "checklist": day_checklist
                }

                checklist_periods.append(current_period)
                current_checklist_key = checklist_key

            else:
                current_period["end_day"] = day

    results = []

    query = VehicleChecklistResult.query.filter_by(
        company_code=checklist_record.company_code,
        checklist_id=checklist_record.id
    )

    if vehicle_record_id:
        query = query.filter_by(
            vehicle_record_id=vehicle_record_id
        )

    for result_record in query.all():
        result = vehicle_checklist_result_to_dict(result_record)

        if display_mode == "year_list":
            if int(result.get("year", 0)) not in [int(d) for d in display_days]:
                continue

        elif display_mode == "month_list":
            if str(result.get("year")) != str(year):
                continue

        else:
            if str(result.get("year")) != str(year):
                continue

            if str(result.get("month")).zfill(2) != str(month).zfill(2):
                continue

        results.append(result)

    if display_mode == "day_list":
        for period in checklist_periods:
            start_day = period["start_day"]
            end_day = period["end_day"]

            period["days"] = [
                day
                for day in display_days
                if start_day <= day <= end_day
            ]

            period["results"] = [
                result
                for result in results
                if start_day
                <= int(result.get("day", 0))
                <= end_day
            ]

    if display_mode == "day_list" and checklist_periods:
        table_sections = []

        results_by_day = {}

        for result in results:
            try:
                result_day = int(result.get("day", 0))
            except (TypeError, ValueError):
                continue

            results_by_day[result_day] = result

        current_section = None
        current_checklist_key = None

        for day in display_days:
            day_result = results_by_day.get(day)
            day_checklist = None

            for period in checklist_periods:
                if (
                    period["start_day"]
                    <= day
                    <= period["end_day"]
                ):
                    day_checklist = period["checklist"]
                    break

            if not day_checklist:
                continue

            checklist_key = checklist_revision_key(
                day_checklist
            )

            if checklist_key != current_checklist_key:
                current_section = {
                    "start_day": day,
                    "end_day": day,
                    "days": [day],
                    "results": [],
                    "checklist": day_checklist
                }

                table_sections.append(current_section)
                current_checklist_key = checklist_key

            else:
                current_section["end_day"] = day
                current_section["days"].append(day)

            if day_result:
                current_section["results"].append(day_result)

    else:
        table_sections = [{
            "checklist": checklist,
            "days": display_days,
            "results": results
        }]

    selected_notify_users = []
    active_result = None

    for result in results:
        if display_mode == "year_list":
            is_active_result = (
                str(result.get("year")) == str(active_day)
            )

        elif display_mode == "month_list":
            is_active_result = (
                str(result.get("month")).zfill(2)
                == str(active_day).zfill(2)
            )

        else:
            is_active_result = (
                str(result.get("day")).zfill(2)
                == str(active_day).zfill(2)
            )

        if is_active_result:
            active_result = result
            selected_notify_users = result.get("notify_users", [])
            break

    if active_result:
        snapshot = active_result.get("checklist_snapshot") or {}

        if snapshot:
            checklist = snapshot

    selected_reminder_notify_users = (
        get_vehicle_checklist_notify_users(
            checklist_record.company_code,
            checklist_record.id,
            vehicle_record_id
        )
        if vehicle_record_id
        else []
    )

    valid_vehicle_ids = {
        vehicle.id
        for vehicle in Vehicle.query.filter_by(
            company_code=checklist_record.company_code,
            deleted=False
        ).all()
    }

    current_driver = Driver.query.filter_by(
        company_code=session.get("company_code"),
        employee_id=session.get("username")
    ).first()

    usage_vehicle_ids = [
        int(vehicle_record_id)
        for vehicle_record_id in (
            safe_json_str_list(current_driver.vehicles_json)
            if current_driver
            else []
        )
        if vehicle_record_id.isdigit()
        and int(vehicle_record_id) in valid_vehicle_ids
    ]

    usage_vehicles = Vehicle.query.filter(
        Vehicle.company_code == checklist_record.company_code,
        Vehicle.deleted == False,
        Vehicle.id.in_(usage_vehicle_ids)
    ).all() if usage_vehicle_ids else []

    selected_vehicle = None

    if vehicle_record_id:

        vehicle_record = valid_vehicle

        if vehicle_record:

            number = " ".join(
                value
                for value in [
                    vehicle_record.plate_area or "",
                    vehicle_record.plate_class or "",
                    vehicle_record.plate_kana or "",
                    vehicle_record.plate_number or "",
                ]
                if value
            )

            selected_vehicle = {
                "vehicle_record_id": vehicle_record.id,
                "chassis_number": vehicle_record.chassis_number,
                "number": number,
                "manufacturer": vehicle_record.manufacturer or "",
                "model_code": vehicle_record.model_code or "",
            }

    return render_template(
        "vehicle_checklist_results.html",
        checklist=checklist,
        checklist_index=checklist_record.id,
        results=results,
        selected_notify_users=selected_notify_users,
        selected_reminder_notify_users=selected_reminder_notify_users,
        selected_vehicle=selected_vehicle,
        usage_vehicle_ids=usage_vehicle_ids,
        usage_vehicles=usage_vehicles,
        year=year,
        month=month,
        vehicle_record_id=vehicle_record_id,
        active_day=active_day,
        display_days=display_days,
        input_days=input_days,
        display_weekdays=display_weekdays,
        display_mode=display_mode,
        checklist_periods=checklist_periods,
        table_sections=table_sections
    )

@app.route(
    "/vehicle/checklists/<int:checklist_index>/reminder-notify-users",
    methods=["POST"]
)
@limiter.limit("10 per minute")
def save_vehicle_checklist_reminder_notify_users(checklist_index):
    company_code = session.get("company_code")
    if session.get("role") not in ["admin", "itc"]:
        return {
            "ok": False,
            "message": "通知先設定を変更する権限がありません。"
        }, 403    

    vehicle_record_id = request.form.get(
        "vehicle_record_id",
        type=int
    )

    notify_usernames = [
        username.strip()
        for username in request.form.getlist(
            "reminder_notify_users"
        )
        if username.strip()
    ]

    if len(notify_usernames) > 500:
        return {
            "ok": False,
            "message": "通知先ユーザー数が多すぎます。"
        }, 400

    # =========================
    # チェックリスト検証
    # =========================

    checklist_record = Checklist.query.filter_by(
        id=checklist_index,
        company_code=company_code,
        active=True
    ).first()

    if not checklist_record:
        return {
            "ok": False,
            "message": "チェックリストが不正です。"
        }, 404

    if checklist_record.target != "車両管理":
        return {
            "ok": False,
            "message": "チェックリスト種別が不正です。"
        }, 400

    # =========================
    # 車両検証
    # =========================

    if not vehicle_record_id:
        return {
            "ok": False,
            "message": "車両を選択してください。"
        }, 400

    vehicle = Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return {
            "ok": False,
            "message": "車両が不正です。"
        }, 400

    # =========================
    # 通知先ユーザー検証
    # =========================

    valid_usernames = {
        user.username
        for user in User.query.filter_by(
            company_code=company_code
        ).all()
        if user.username
    }

    for username in notify_usernames:
        if username not in valid_usernames:
            return {
                "ok": False,
                "message": "通知先ユーザーが不正です。"
            }, 400

    # 重複除去
    notify_usernames = list(
        dict.fromkeys(notify_usernames)
    )

    # =========================
    # 設定保存
    # =========================

    setting = VehicleChecklistNotifySetting.query.filter_by(
        company_code=company_code,
        checklist_id=checklist_record.id,
        vehicle_record_id=vehicle_record_id
    ).first()

    if not setting:
        setting = VehicleChecklistNotifySetting(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id
        )

        db.session.add(setting)

    setting.notify_users_json = json.dumps(
        notify_usernames,
        ensure_ascii=False
    )

    db.session.commit()

    return {
        "ok": True
    }

@app.route(
    "/vehicle/checklist-reminders/test",
    methods=["POST"]
)
@limiter.limit("5 per minute")
def test_vehicle_checklist_reminders():

    if session.get("role") not in ["admin", "itc"]:
        return {"ok": False}, 403

    send_vehicle_checklist_reminders(
        session.get("company_code")
    )

    return {"ok": True}

@app.route(
    "/notifications/email-test",
    methods=["POST"]
)
@limiter.limit("5 per minute")
def test_email_notification():
    current_user = User.query.filter_by(
        company_code=session.get("company_code"),
        username=session.get("username")
    ).first()

    if not current_user:
        return {
            "ok": False,
            "message": "ユーザーが見つかりません。"
        }, 404

    if not current_user.email_notify_enabled:
        return {
            "ok": False,
            "message": "メール通知がOFFです。"
        }, 400

    if not current_user.email_address:
        return {
            "ok": False,
            "message": "メールアドレスが未設定です。"
        }, 400

    sent = send_email_notification(
        current_user,
        "メール通知テスト",
        "通知メールの送信テストです。",
        "/settings"
    )

    if not sent:
        return {
            "ok": False,
            "message": "メール送信に失敗しました。"
        }, 500

    return {
        "ok": True,
        "message": "メールを送信しました。"
    }
    
@app.route(
    "/vehicle/checklist-results/<int:result_index>/approve/<int:approval_index>",
    methods=["POST"]
)
@limiter.limit("20 per minute")
def approve_vehicle_checklist_result(result_index, approval_index):
    result_record = VehicleChecklistResult.query.filter_by(
        id=result_index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/vehicle/checklists")

    if result_record.status != "承認待ち":
        return redirect("/vehicle/checklists")

    approvals = safe_json_dict_list(
        result_record.approvals_json
    )
    if not approvals:
        checklist_record = Checklist.query.filter_by(
            id=result_record.checklist_id,
            company_code=result_record.company_code
        ).first()

        if checklist_record:
            checklist = checklist_to_dict(checklist_record)

            for item in checklist.get("items", []):
                if item.get("item_type") != "approval":
                    continue

                approvals.append({
                    "label": item.get("approval_label", ""),
                    "allow_general": item.get("approval_allow_general", False),
                    "approved_by": "",
                    "approved_by_username": "",
                    "approved_date": "",
                })

    if approval_index < 0 or approval_index >= len(approvals):
        return redirect("/vehicle/checklists")

    if any(
        not (
            item.get("approved_by")
            or item.get("approved_by_username")
        )
        for item in approvals[:approval_index]
    ):
        return redirect("/vehicle/checklists")

    approval = approvals[approval_index]

    # 旧データに allow_general が無い場合は
    # 記録時点のチェックリストから補完
    if "allow_general" not in approval:
        approval_checklist = {}

        if result_record.checklist_snapshot_json:
            approval_checklist = safe_json_dict(
                result_record.checklist_snapshot_json
            )

        if not approval_checklist:
            checklist_record = Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                approval_checklist = checklist_to_dict(
                    checklist_record
                )

        approval_items = [
            item
            for item in approval_checklist.get("items", [])
            if item.get("item_type") == "approval"
        ]

        if approval_index < len(approval_items):
            approval["allow_general"] = approval_items[
                approval_index
            ].get(
                "approval_allow_general",
                False
            )

    if (
        approval.get("approved_by")
        or approval.get("approved_by_username")
    ):
        return redirect("/vehicle/checklists")

    # 旧データに allow_general が無い場合は
    # 記録時点のチェックリストから補完
    if "allow_general" not in approval:
        approval_checklist = {}

        if result_record.checklist_snapshot_json:
            approval_checklist = safe_json_dict(
                result_record.checklist_snapshot_json
            )

        if not approval_checklist:
            checklist_record = Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                approval_checklist = checklist_to_dict(
                    checklist_record
                )

        approval_items = [
            item
            for item in approval_checklist.get("items", [])
            if item.get("item_type") == "approval"
        ]

        if approval_index < len(approval_items):
            approval["allow_general"] = approval_items[
                approval_index
            ].get(
                "approval_allow_general",
                False
            )

    result = vehicle_checklist_result_to_dict(result_record)

    if not can_approve_checklist_result(result, approval):
        return redirect("/vehicle/checklists")

    approval["approved_by"] = session.get("name")
    approval["approved_by_username"] = session.get("username")    
    approval["approved_date"] = datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    result_record.approvals_json = json.dumps(
        approvals,
        ensure_ascii=False
    )

    result_record.reject_reason = ""

    all_approved = all(
        item.get("approved_by")
        for item in approvals
    )

    if approvals and all_approved:
        result_record.status = "承認済み"
        result_record.approved_by = session.get("name")
        result_record.approved_by_username = session.get("username")
        result_record.approved_date = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )
    else:
        result_record.status = "承認待ち"
        result_record.approved_by = ""
        result_record.approved_by_username = ""
        result_record.approved_date = ""

    db.session.commit()

    vehicle_record = Vehicle.query.filter_by(
        company_code=result_record.company_code,
        id=result_record.vehicle_record_id,
        deleted=False
    ).first()

    checklist_record = Checklist.query.filter_by(
        id=result_record.checklist_id,
        company_code=result_record.company_code
    ).first()

    if checklist_record:
        checklist = checklist_to_dict(checklist_record)

        if checklist.get("frequency_unit") == "year":
            active_value = result_record.year

        elif checklist.get("display_type") == "month":
            active_value = result_record.day

        else:
            active_value = result_record.month

    else:
        active_value = result_record.day

    notification_link = (
        f"/vehicle/checklists/{result_record.checklist_id}"
        f"?vehicle_record_id={result_record.vehicle_record_id}"
        f"&year={result_record.year}"
        f"&month={result_record.month}"
        f"&active_day={active_value}"
    )

    if result_record.status == "承認済み":
        notify_usernames = set(
            safe_json_str_list(
                result_record.notify_users_json
            )
        )

        if result_record.checked_by_username:
            notify_usernames.add(
                result_record.checked_by_username
            )

        for target_username in notify_usernames:
            target_user = User.query.filter_by(
                company_code=result_record.company_code,
                username=target_username
            ).first()

            if not target_user:
                continue

            add_notification(
                target_user.name,
                "車両チェックリストが承認されました",
                (
                    f"車両 {vehicle_record.chassis_number if vehicle_record else '-'} の"
                    "チェックリストの承認が完了しました。"
                ),
                notification_link,
                company_code=result_record.company_code,
                target_username=target_user.username
            )

    return redirect(
        f"/vehicle/checklists/{result_record.checklist_id}"
        f"?vehicle_record_id={result_record.vehicle_record_id}"
        f"&year={result_record.year}"
        f"&month={result_record.month}"
        f"&active_day={active_value}"
    )

@app.route("/vehicle/checklist-results/<int:result_index>/excel")
def export_vehicle_checklist_result_excel(result_index):
    result_record = VehicleChecklistResult.query.filter_by(
        id=result_index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/vehicle/checklists")
    result = vehicle_checklist_result_to_dict(result_record)

    checklist_record = Checklist.query.filter_by(
        id=result_record.checklist_id,
        company_code=result_record.company_code
    ).first()

    if not checklist_record:
        return redirect("/vehicle/checklists")

    checklist = (
        result.get("checklist_snapshot")
        or checklist_to_dict(checklist_record)
    )

    # 点検頻度
    try:
        frequency_value = int(
            checklist.get("frequency_value") or 1
        )
    except (TypeError, ValueError):
        frequency_value = 1

    frequency_unit = checklist.get(
        "frequency_unit",
        ""
    )

    display_type = checklist.get(
        "display_type",
        ""
    )

    # Excelの表示単位を決定
    if frequency_unit == "year":
        excel_display_mode = "year"

    elif display_type == "month":
        excel_display_mode = "day"

    else:
        excel_display_mode = "month"

    vehicle_record = Vehicle.query.filter_by(
        company_code=result_record.company_code,
        id=result_record.vehicle_record_id
    ).first()

    vehicle_info = {
        "vehicle_record_id": result_record.vehicle_record_id,
        "chassis_number": (
            vehicle_record.chassis_number
            if vehicle_record
            else ""
        ),
        "number": "",
        "manufacturer": "",
        "model_code": "",
    }

    if vehicle_record:
        vehicle_info["number"] = " ".join(
            value
            for value in [
                vehicle_record.plate_area or "",
                vehicle_record.plate_class or "",
                vehicle_record.plate_kana or "",
                vehicle_record.plate_number or "",
            ]
            if value
        )

        vehicle_info["manufacturer"] = (
            vehicle_record.manufacturer or ""
        )

        vehicle_info["model_code"] = (
            vehicle_record.model_code or ""
        )

    # 点検頻度に応じて出力対象を取得
    result_query = VehicleChecklistResult.query.filter_by(
        company_code=result_record.company_code,
        checklist_id=result_record.checklist_id,
        vehicle_record_id=result_record.vehicle_record_id
    )

    if frequency_unit == "year":
        # 年次・複数年ごとの点検
        result_records = result_query.order_by(
            VehicleChecklistResult.year.asc()
        ).all()

    elif display_type == "month":
        # 日次系
        result_records = result_query.filter_by(
            year=result_record.year,
            month=result_record.month
        ).order_by(
            VehicleChecklistResult.day.asc()
        ).all()

    else:
        # 月例・3か月ごと・6か月ごと等
        result_records = result_query.filter_by(
            year=result_record.year
        ).order_by(
            VehicleChecklistResult.month.asc()
        ).all()

    period_results = [
        vehicle_checklist_result_to_dict(record)
        for record in result_records
    ]

    excel_sections = []

    if excel_display_mode == "day":
        master_checklist = checklist_to_dict(
            checklist_record
        )

        version_history = []

        for version in master_checklist.get(
            "version_history",
            []
        ):
            try:
                change_datetime = datetime.strptime(
                    version.get("effective_until", ""),
                    "%Y-%m-%d %H:%M:%S"
                )
            except (TypeError, ValueError):
                continue

            version_history.append({
                "change_date": change_datetime.date(),
                "snapshot": version.get("snapshot") or {}
            })

        version_history.sort(
            key=lambda version: version["change_date"]
        )

        current_checklist = {
            key: value
            for key, value in master_checklist.items()
            if key != "version_history"
        }

        results_by_day = {}

        for period_result in period_results:
            try:
                result_day = int(
                    period_result.get("day", 0)
                )
            except (TypeError, ValueError):
                continue

            results_by_day[result_day] = period_result

        days_in_month = calendar.monthrange(
            int(result_record.year),
            int(result_record.month)
        )[1]

        current_section = None
        current_checklist_key = None

        for day in range(1, days_in_month + 1):
            target_date = datetime(
                int(result_record.year),
                int(result_record.month),
                day
            ).date()

            day_checklist = current_checklist

            for version in version_history:
                if target_date < version["change_date"]:
                    day_checklist = version["snapshot"]
                    break

            day_result = results_by_day.get(day)

            checklist_key = checklist_revision_key(
                day_checklist
            )

            if checklist_key != current_checklist_key:
                current_section = {
                    "start_day": day,
                    "end_day": day,
                    "checklist": day_checklist,
                    "results": []
                }

                excel_sections.append(current_section)
                current_checklist_key = checklist_key

            else:
                current_section["end_day"] = day

            if day_result:
                current_section["results"].append(
                    day_result
                )

    if excel_display_mode == "day" and excel_sections:
        excel_render_sections = excel_sections
    else:
        excel_render_sections = [{
            "start_day": None,
            "end_day": None,
            "checklist": checklist,
            "results": period_results
        }]

    # 月間帳票を半月ごとに分ける設定
    half_month_mode = (
        excel_display_mode == "day"
        and checklist.get("print_half_month")
        and len(excel_render_sections) == 1
    )

    workbook = Workbook()

    excel_section = excel_render_sections[0]

    excel_checklist = excel_section["checklist"]
    excel_period_results = excel_section["results"]

    sheet = workbook.active

    if (
        excel_display_mode == "day"
        and excel_section["start_day"] is not None
        and excel_section["end_day"] is not None
    ):
        sheet.title = (
            f"{excel_section['start_day']}～"
            f"{excel_section['end_day']}日"
        )
    else:
        sheet.title = "車両点検結果"

    def render_excel_section(
        sheet,
        excel_checklist,
        excel_period_results
    ):
        
        # 印刷設定
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        if excel_checklist.get("print_portrait"):
            sheet.page_setup.orientation = sheet.ORIENTATION_PORTRAIT
        else:
            sheet.page_setup.orientation = sheet.ORIENTATION_LANDSCAPE
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.print_options.horizontalCentered = True

        # 点検頻度に応じた列幅
        sheet.column_dimensions["A"].width = 42

        if excel_display_mode == "day":
            days_in_month = calendar.monthrange(
                int(result_record.year),
                int(result_record.month)
            )[1]

            end_column = days_in_month + 1

            if half_month_mode:
                period_width = 7.0
            else:
                period_width = 3.8

        elif excel_display_mode == "month":
            end_column = 13
            period_width = 6

        else:
            end_column = 6
            period_width = 12

        for column in range(2, end_column + 1):
            sheet.column_dimensions[
                sheet.cell(row=1, column=column).column_letter
            ].width = period_width

        # タイトル
        title_end_column = end_column

        sheet.merge_cells(
            start_row=1,
            start_column=1,
            end_row=2,
            end_column=title_end_column
        )

        title_cell = sheet["A1"]
        if excel_display_mode == "day":
            title_cell.value = (
                f"{result_record.year}年 "
                f"{int(result_record.month)}月 "
                f"{excel_checklist.get('name', '車両点検表')}"
            )

        elif excel_display_mode == "month":
            title_cell.value = (
                f"{result_record.year}年 "
                f"{excel_checklist.get('name', '車両点検表')}"
            )

        else:
            title_cell.value = (
                f"{excel_checklist.get('name', '車両点検表')}"
            )
        title_cell.font = Font(
            bold=True,
            size=16
        )
        title_cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )

        # 評価基準
        criteria_list = []

        for item in excel_checklist.get("items", []):
            if item.get("item_type") != "check":
                continue

            criteria = (item.get("criteria") or "").strip()

            if criteria and criteria not in criteria_list:
                criteria_list.append(criteria)

        if criteria_list:
            criteria_text = "評価基準：\n" + "\n".join(criteria_list)

            # 評価基準の改行数と文字量から必要な行数を計算
            chars_per_line = 100
            line_count = 0

            for line in criteria_text.split("\n"):
                line_count += max(
                    1,
                    (len(line) + chars_per_line - 1) // chars_per_line
                )

            sheet.row_dimensions[3].height = max(
                24,
                line_count * 18
            )

            sheet.merge_cells(
                start_row=3,
                start_column=1,
                end_row=3,
                end_column=end_column
            )

            criteria_cell = sheet.cell(
                row=3,
                column=1,
                value=criteria_text
            )

            criteria_cell.font = Font(
                size=9
            )

            criteria_cell.alignment = Alignment(
                horizontal="left",
                vertical="center",
                wrap_text=True
            )

        # 月間帳票の車両情報
        vehicle_number = (
            vehicle_info["chassis_number"]
            or vehicle_info["number"]
        )

        sheet.merge_cells(
            start_row=4,
            start_column=1,
            end_row=4,
            end_column=end_column
        )

        sheet["A4"] = f"車台番号　{vehicle_number}"
        sheet["A4"].font = Font(bold=True)
        sheet["A4"].alignment = Alignment(
            horizontal="left",
            vertical="center"
        )

        # 点検表ヘッダー
        header_row = 5
        weekday_row = 6

        sheet["A5"] = "点検項目"

        sheet.merge_cells(
            start_row=5,
            start_column=1,
            end_row=6,
            end_column=1
        )

        year = int(result_record.year)
        month = int(result_record.month)

        if excel_display_mode == "day":
            # 日次：1～31日
            days_in_month = calendar.monthrange(
                year,
                month
            )[1]

            weekday_names = [
                "月", "火", "水", "木", "金", "土", "日"
            ]

            for day in range(1, days_in_month + 1):
                column = day + 1

                if day <= days_in_month:
                    sheet.cell(
                        row=header_row,
                        column=column,
                        value=day
                    )

                    weekday_index = datetime(
                        year,
                        month,
                        day
                    ).weekday()

                    sheet.cell(
                        row=weekday_row,
                        column=column,
                        value=weekday_names[weekday_index]
                    )

                    if weekday_index == 5:
                        sheet.cell(
                            row=weekday_row,
                            column=column
                        ).font = Font(color="0000FF")

                    elif weekday_index == 6:
                        sheet.cell(
                            row=weekday_row,
                            column=column
                        ).font = Font(color="FF0000")

        elif excel_display_mode == "month":
            # 月例・3か月・6か月ごと等：1～12月
            for month_no in range(1, 13):
                column = month_no + 1

                sheet.cell(
                    row=header_row,
                    column=column,
                    value=f"{month_no}月"
                )

                sheet.merge_cells(
                    start_row=header_row,
                    start_column=column,
                    end_row=weekday_row,
                    end_column=column
                )

        else:
            # 年次・複数年ごと
            base_year = int(result_record.year)

            for offset in range(5):
                column = offset + 2
                target_year = base_year + offset

                sheet.cell(
                    row=header_row,
                    column=column,
                    value=f"{target_year}年"
                )

                sheet.merge_cells(
                    start_row=header_row,
                    start_column=column,
                    end_row=weekday_row,
                    end_column=column
                )

        # 点検項目を縦に並べる
        current_row = 7
        previous_category = None
        category_rows = set()
        shaded_rows = set()

        for item_no, item in enumerate(excel_checklist.get("items", [])):

            if item.get("item_type") != "check":
                continue

            category = item.get("category", "").strip()
            content = item.get("content", "").strip()

            # カテゴリが変わったら横一列のカテゴリ行を追加
            if category and category != previous_category:
                category_row = current_row
                category_rows.add(category_row)

                sheet.merge_cells(
                    start_row=category_row,
                    start_column=1,
                    end_row=category_row,
                    end_column=end_column
                )

                category_cell = sheet.cell(
                    row=category_row,
                    column=1,
                    value=f"（{category}）"
                )

                category_cell.font = Font(bold=True)
                category_cell.alignment = Alignment(
                    horizontal="left",
                    vertical="center"
                )

                sheet.row_dimensions[category_row].height = 20

                current_row += 1
                previous_category = category

            # 点検項目にはカテゴリ名を付けない
            item_text = content

            # 点検項目の文字量に応じて行高を調整
            import math
            import unicodedata

            def item_text_width(text):
                width = 0

                for char in str(text or ""):
                    if unicodedata.east_asian_width(char) in ("W", "F", "A"):
                        width += 2
                    else:
                        width += 1

                return width


            item_line_count = 0

            for line in item_text.split("\n"):
                item_line_count += max(
                    1,
                    math.ceil(item_text_width(line) / 42)
                )

            sheet.row_dimensions[current_row].height = max(
                21,
                item_line_count * 18 + 4
            )

            sheet.cell(
                row=current_row,
                column=1,
                value=item_text
            )

            sheet.cell(
                row=current_row,
                column=1
            ).alignment = Alignment(
                vertical="center",
                wrap_text=True,
            )

            if item.get("shaded"):
                shaded_rows.add(current_row)

                shaded_fill = PatternFill(
                    fill_type="solid",
                    fgColor="D9D9D9"
                )

                for column in range(1, end_column + 1):
                    sheet.cell(
                        row=current_row,
                        column=column
                    ).fill = shaded_fill

            # 点検結果を表示単位に応じて入れる
            for period_result in excel_period_results:

                if excel_display_mode == "day":
                    try:
                        period_value = int(
                            period_result.get("day", 0)
                        )
                    except (TypeError, ValueError):
                        continue

                    if period_value < 1 or period_value > 31:
                        continue

                    column = period_value + 1

                elif excel_display_mode == "month":
                    try:
                        period_value = int(
                            period_result.get("month", 0)
                        )
                    except (TypeError, ValueError):
                        continue

                    if period_value < 1 or period_value > 12:
                        continue

                    column = period_value + 1

                else:
                    try:
                        period_year = int(
                            period_result.get("year", 0)
                        )
                    except (TypeError, ValueError):
                        continue

                    year_offset = period_year - base_year

                    if year_offset < 0 or year_offset >= 5:
                        continue

                    column = year_offset + 2

                matched_answer = None

                for answer in period_result.get("answers", []):
                    answer_item_no = answer.get("item_no")

                    # item_no があるデータは番号だけで照合
                    if answer_item_no not in (None, ""):
                        if str(answer_item_no) == str(item_no):
                            matched_answer = answer
                            break
                        continue

                    # item_no が無い旧データだけカテゴリー＋内容で照合
                    if (
                        answer.get("category", "")
                        == item.get("category", "")
                        and answer.get("content", "")
                        == item.get("content", "")
                    ):
                        matched_answer = answer
                        break

                if not matched_answer:
                    continue

                result_cell = sheet.cell(
                    row=current_row,
                    column=column,
                    value=matched_answer.get("value", "") or ""
                )

                result_cell.alignment = Alignment(
                    horizontal="center",
                    vertical="center"
                )

            current_row += 1

        if excel_checklist.get("score_enabled"):
            score_row = current_row

            sheet.cell(
                row=score_row,
                column=1,
                value="合計点"
            )

            sheet.cell(
                row=score_row,
                column=1
            ).font = Font(bold=True)

            for period_result in excel_period_results:
                total_score = 0

                for answer in period_result.get("answers", []):
                    try:
                        total_score += float(answer.get("value") or 0)
                    except (TypeError, ValueError):
                        pass

                if excel_display_mode == "day":
                    try:
                        column = int(period_result.get("day", 0)) + 1
                    except (TypeError, ValueError):
                        continue

                elif excel_display_mode == "month":
                    try:
                        column = int(period_result.get("month", 0)) + 1
                    except (TypeError, ValueError):
                        continue

                else:
                    try:
                        period_year = int(period_result.get("year", 0))
                    except (TypeError, ValueError):
                        continue

                    year_offset = period_year - base_year

                    if year_offset < 0 or year_offset >= 5:
                        continue

                    column = year_offset + 2

                sheet.cell(
                    row=score_row,
                    column=column,
                    value=int(total_score)
                )

            current_row += 1

        # 点検実施者
        inspector_row = current_row

        sheet.cell(
            row=inspector_row,
            column=1,
            value="点検実施者"
        )

        for period_result in excel_period_results:

            if excel_display_mode == "day":
                try:
                    period_value = int(
                        period_result.get("day", 0)
                    )
                except (TypeError, ValueError):
                    continue

                if period_value < 1 or period_value > 31:
                    continue

                column = period_value + 1

            elif excel_display_mode == "month":
                try:
                    period_value = int(
                        period_result.get("month", 0)
                    )
                except (TypeError, ValueError):
                    continue

                if period_value < 1 or period_value > 12:
                    continue

                column = period_value + 1

            else:
                try:
                    period_year = int(
                        period_result.get("year", 0)
                    )
                except (TypeError, ValueError):
                    continue

                year_offset = period_year - base_year

                if year_offset < 0 or year_offset >= 5:
                    continue

                column = year_offset + 2

            inspector_cell = sheet.cell(
                row=inspector_row,
                column=column,
                value=period_result.get("checked_by", "") or ""
            )

            inspector_cell.alignment = Alignment(
                horizontal="center",
                vertical="center",
                wrap_text=True
            )

        current_row += 1

        # 承認欄
        approval_items = [
            item
            for item in excel_checklist.get("items", [])
            if item.get("item_type") == "approval"
        ]

        for approval_index, approval_item in enumerate(approval_items):
            approval_row = current_row

            sheet.row_dimensions[approval_row].height = 28

            sheet.cell(
                row=approval_row,
                column=1,
                value=approval_item.get("approval_label", "") or "承認"
            )

            for period_result in excel_period_results:
                approvals = period_result.get("approvals", [])

                if approval_index >= len(approvals):
                    continue

                approval = approvals[approval_index]

                if not approval.get("approved_by"):
                    continue

                if excel_display_mode == "day":
                    try:
                        column = int(period_result.get("day", 0)) + 1

                    except (TypeError, ValueError):
                        continue

                elif excel_display_mode == "month":
                    try:
                        column = int(period_result.get("month", 0)) + 1
                    except (TypeError, ValueError):
                        continue

                else:
                    try:
                        period_year = int(period_result.get("year", 0))
                    except (TypeError, ValueError):
                        continue

                    year_offset = period_year - base_year

                    if year_offset < 0 or year_offset >= 5:
                        continue

                    column = year_offset + 2

                sheet.cell(
                    row=approval_row,
                    column=column,
                    value=approval.get("approved_by", "")
                ).alignment = Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True
                )

            current_row += 1

        # 表全体の罫線・配置
        thin = Side(
            style="thin",
            color="000000"
        )

        table_end_row = current_row - 1

        for row_number in range(5, table_end_row + 1):

            # カテゴリ行は横一列にして日付マスの縦線を付けない
            if row_number in category_rows:
                no_border = Side(style=None)

                for category_column in range(
                    1,
                    title_end_column + 1
                ):
                    category_cell = sheet.cell(
                        row=row_number,
                        column=category_column
                    )

                    category_cell.border = Border(
                        left=(
                            thin
                            if category_column == 1
                            else no_border
                        ),
                        right=(
                            thin
                            if category_column == title_end_column
                            else no_border
                        ),
                        top=thin,
                        bottom=thin
                    )

                continue

            for column_number in range(1, title_end_column + 1):

                cell = sheet.cell(
                    row=row_number,
                    column=column_number
                )

                cell.border = Border(
                    left=thin,
                    right=thin,
                    top=thin,
                    bottom=thin
                )

                if column_number >= 2:
                    cell.alignment = Alignment(
                        horizontal="center",
                        vertical="center",
                        wrap_text=True
                    )

        # ヘッダー装飾
        header_fill = PatternFill(
            fill_type="solid",
            fgColor="D9E1F2"
        )

        for row_number in range(header_row, weekday_row + 1):
            for column_number in range(1, title_end_column + 1):
                header_cell = sheet.cell(
                    row=row_number,
                    column=column_number
                )

                header_cell.fill = header_fill
                header_cell.font = Font(bold=True)
                header_cell.alignment = Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True
                )

        # 日次表の土日列を薄く色付け
        if excel_display_mode == "day":
            saturday_fill = PatternFill(
                fill_type="solid",
                fgColor="EAF2F8"
            )

            sunday_fill = PatternFill(
                fill_type="solid",
                fgColor="FCE8E6"
            )

            for day in range(1, days_in_month + 1):
                if day > days_in_month:
                    continue

                column = day + 1

                weekday_index = datetime(
                    year,
                    month,
                    day
                ).weekday()

                if weekday_index == 5:
                    fill = saturday_fill
                elif weekday_index == 6:
                    fill = sunday_fill
                else:
                    continue

                for row_number in range(
                    header_row,
                    table_end_row + 1
                ):
                    if row_number in shaded_rows:
                        continue

                    sheet.cell(
                        row=row_number,
                        column=column
                    ).fill = fill


        # 日次表の土日文字色を再設定
        if excel_display_mode == "day":
            for column_number in range(2, title_end_column + 1):

                weekday_cell = sheet.cell(
                    row=weekday_row,
                    column=column_number
                )

                if weekday_cell.value == "土":
                    weekday_cell.font = Font(
                        bold=True,
                        color="0000FF"
                    )

                elif weekday_cell.value == "日":
                    weekday_cell.font = Font(
                        bold=True,
                        color="FF0000"
                    )

        return {
            "table_end_row": table_end_row,
            "title_end_column": title_end_column,
            "days_in_month": (
                days_in_month
                if excel_display_mode == "day"
                else None
            )
        }

    render_info = render_excel_section(
        sheet,
        excel_checklist,
        excel_period_results
    )

    table_end_row = render_info["table_end_row"]
    title_end_column = render_info["title_end_column"]

    if excel_display_mode == "day":
        days_in_month = render_info["days_in_month"]

    rendered_sheets = [{
        "sheet": sheet,
        "checklist": excel_checklist,
        "render_info": render_info,
        "start_day": excel_section["start_day"],
        "end_day": excel_section["end_day"]
    }]

    if (
        excel_display_mode == "day"
        and not half_month_mode
        and len(excel_render_sections) > 1
    ):
        for extra_section in excel_render_sections[1:]:
            extra_sheet = workbook.create_sheet()

            extra_sheet.title = (
                f"{extra_section['start_day']}～"
                f"{extra_section['end_day']}日"
            )

            extra_checklist = extra_section["checklist"]
            extra_results = extra_section["results"]

            extra_render_info = render_excel_section(
                extra_sheet,
                extra_checklist,
                extra_results
            )

            rendered_sheets.append({
                "sheet": extra_sheet,
                "checklist": extra_checklist,
                "render_info": extra_render_info,
                "start_day": extra_section["start_day"],
                "end_day": extra_section["end_day"]
            })

    if excel_display_mode == "day" and not half_month_mode:
        for rendered_sheet in rendered_sheets:
            period_sheet = rendered_sheet["sheet"]
            start_day = rendered_sheet["start_day"]
            end_day = rendered_sheet["end_day"]

            if start_day is None or end_day is None:
                continue

            for day in range(1, days_in_month + 1):
                if start_day <= day <= end_day:
                    continue

                column = day + 1
                column_letter = period_sheet.cell(
                    row=5,
                    column=column
                ).column_letter

                period_sheet.column_dimensions[
                    column_letter
                ].hidden = True

    # 半月ごとに分ける場合は、表・裏の2シートにする
    if half_month_mode:
        sheet.title = "表 1～15日"

        back_sheet = workbook.copy_worksheet(sheet)
        back_sheet.title = "裏 16日～月末"

        # 表：16日～月末を非表示
        for day in range(16, days_in_month + 1):
            column = day + 1
            column_letter = sheet.cell(
                row=5,
                column=column
            ).column_letter
            sheet.column_dimensions[column_letter].hidden = True

        # 裏：1～15日を非表示
        for day in range(1, 16):
            column = day + 1
            column_letter = back_sheet.cell(
                row=5,
                column=column
            ).column_letter
            back_sheet.column_dimensions[column_letter].hidden = True

    # Excelファイルをメモリ上に保存
    output = BytesIO()

    if half_month_mode:
        print_sheet_entries = [
            {
                "sheet": sheet,
                "checklist": excel_checklist,
                "render_info": render_info
            },
            {
                "sheet": back_sheet,
                "checklist": excel_checklist,
                "render_info": render_info
            }
        ]
    else:
        print_sheet_entries = rendered_sheets

    for print_entry in print_sheet_entries:
        print_sheet = print_entry["sheet"]
        print_checklist = print_entry["checklist"]
        print_render_info = print_entry["render_info"]

        print_sheet.print_area = (
            f"A1:{print_sheet.cell(
                row=print_render_info["table_end_row"],
                column=print_render_info["title_end_column"]
            ).coordinate}"
        )

        print_sheet.sheet_properties.pageSetUpPr.fitToPage = True
        print_sheet.page_setup.paperSize = print_sheet.PAPERSIZE_A4

        if print_checklist.get("print_portrait"):
            print_sheet.page_setup.orientation = (
                print_sheet.ORIENTATION_PORTRAIT
            )
        else:
            print_sheet.page_setup.orientation = (
                print_sheet.ORIENTATION_LANDSCAPE
            )

        print_sheet.page_setup.fitToWidth = 1
        print_sheet.page_setup.fitToHeight = 0
        print_sheet.print_options.horizontalCentered = True

        print_sheet.page_margins.left = 0.25
        print_sheet.page_margins.right = 0.25
        print_sheet.page_margins.top = 0.25
        print_sheet.page_margins.bottom = 0.25
        print_sheet.page_margins.header = 0.2
        print_sheet.page_margins.footer = 0.2

    sanitize_excel_formulas(workbook)
    workbook.save(output)
    output.seek(0)

    filename = (
        f"{checklist.get('name', '車両点検表')}_"
        f"{result_record.year}"
    )

    if excel_display_mode == "day":
        filename += f"_{int(result_record.month):02d}"

    filename += ".xlsx"

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )

@app.route("/vehicle/checklists/<int:index>/save-one", methods=["POST"])
@limiter.limit("20 per minute")
def save_vehicle_checklist_one(index):
    checklist_record = Checklist.query.filter_by(
        id=index,
        company_code=session.get("company_code"),
        active=True
    ).first()

    if not checklist_record:
        return redirect("/vehicle/checklists")

    checklist = checklist_to_dict(checklist_record)

    if checklist.get("target") != "車両管理":
        return redirect("/vehicle/checklists")

    company_code = session.get("company_code")

    vehicle_record_id = request.form.get(
        "vehicle_record_id",
        type=int
    )

    year = request.form.get(
        "year",
        ""
    ).strip()

    month = request.form.get(
        "month",
        ""
    ).strip()

    day = request.form.get(
        "day",
        ""
    ).strip()

    # =========================
    # 車両検証
    # =========================

    if not vehicle_record_id:
        return "対象車両を選択してください。", 400

    vehicle = Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return "対象車両が不正です。", 400

    # =========================
    # 日付検証
    # =========================

    try:
        year_int = int(year)
        month_int = int(month)
        day_int = int(day)
    except (TypeError, ValueError):
        return "点検日が不正です。", 400

    if year_int < 2000 or year_int > 2100:
        return "点検年が不正です。", 400

    if checklist.get("frequency_unit") == "year":
        month_int = 1
        day_int = 1

    elif checklist.get("display_type") == "month":
        if month_int < 1 or month_int > 12:
            return "点検月が不正です。", 400

        try:
            datetime(
                year_int,
                month_int,
                day_int
            )
        except ValueError:
            return "点検日が不正です。", 400

    else:
        if month_int < 1 or month_int > 12:
            return "点検月が不正です。", 400

        day_int = 1

    year = str(year_int)
    month = str(month_int).zfill(2)
    day = str(day_int).zfill(2)

    if checklist.get("frequency_unit") == "year":
        active_day = year
    elif checklist.get("display_type") == "month":
        active_day = day
    else:
        active_day = month

    item_no_raw = request.form.get(
        "item_no",
        ""
    ).strip()

    value = request.form.get(
        "value",
        ""
    )

    result_record = VehicleChecklistResult.query.filter_by(
        company_code=company_code,
        checklist_id=checklist_record.id,
        vehicle_record_id=vehicle_record_id,
        year=year,
        month=month,
        day=day
    ).first()

    if (
        result_record
        and result_record.status == "承認済み"
    ):
        return "承認済みの点検結果は変更できません。", 403

    result_checklist = checklist_for_date(
        checklist,
        year,
        month,
        day
    )

    if (
        result_record
        and result_record.checklist_snapshot_json
    ):
        snapshot = safe_json_dict(
            result_record.checklist_snapshot_json
        )

        if snapshot:
            result_checklist = snapshot

    # =========================
    # チェック項目検証
    # =========================

    try:
        item_no = int(item_no_raw)
    except (TypeError, ValueError):
        return "チェック項目が不正です。", 400

    check_items = [
        item
        for item in result_checklist.get("items", [])
        if item.get("item_type") == "check"
    ]

    if item_no < 0 or item_no >= len(check_items):
        return "チェック項目が不正です。", 400

    checklist_item = check_items[item_no]

    # 項目情報はPOST値を信用せず
    # チェックリストマスタから取得
    category = checklist_item.get(
        "category",
        ""
    )

    content = checklist_item.get(
        "content",
        ""
    )

    criteria = checklist_item.get(
        "criteria",
        ""
    )

    # =========================
    # 回答値検証
    # =========================

    input_type = checklist_item.get(
        "input_type",
        ""
    )

    if input_type == "select":
        valid_choices = [
            str(choice)
            for choice in checklist_item.get(
                "choices",
                []
            )
        ]

        if value not in valid_choices:
            return "回答値が不正です。", 400
        
    if not result_record:
        result_record = VehicleChecklistResult(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day,
            checked_by=session.get("name"),
            checked_by_username=session.get("username"),
            checked_date=datetime.now(
                ZoneInfo("Asia/Tokyo")
            ).strftime("%Y-%m-%d %H:%M"),
            status="入力中",
            approved_by="",
            approved_by_username="",
            approved_date="",
            reject_reason="",
            answers_json="[]",
            checklist_snapshot_json=json.dumps(
                result_checklist,
                ensure_ascii=False
            )
        )

        db.session.add(result_record)

    answers = safe_json_dict_list(
        result_record.answers_json
    )
    answer = None

    for a in answers:
        if str(a.get("item_no", "")) == str(item_no):
            answer = a
            break

    if not answer:
        answer = {
            "item_no": item_no,
            "category": category,
            "content": content,
            "criteria": criteria,
            "value": "",
            "comment": "",
            "files": []
        }
        answers.append(answer)

    answer["value"] = value
    answer["category"] = category
    answer["content"] = content
    answer["criteria"] = criteria

    result_record.checked_by = session.get("name")
    result_record.checked_by_username = session.get("username")
    result_record.checked_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    result_record.status = "入力中"
    approvals = []

    for item in result_checklist.get("items", []):
        if item.get("item_type") != "approval":
            continue

        approvals.append({
            "label": item.get("approval_label", ""),
            "allow_general": item.get("approval_allow_general", False),
            "approved_by": "",
            "approved_by_username": "",
            "approved_date": "",
        })

    result_record.approved_by = ""
    result_record.approved_by_username = ""
    result_record.approved_date = ""
    result_record.approvals_json = json.dumps(
        approvals,
        ensure_ascii=False
    )
    result_record.reject_reason = ""
    result_record.answers_json = json.dumps(answers, ensure_ascii=False)

    db.session.commit()

    notify_mentions(
        value,
        f"/vehicle/checklists/{checklist_record.id}"
        f"?vehicle_record_id={vehicle_record_id}"
        f"&year={year}"
        f"&month={month}"
        f"&active_day={active_day}"
    )

    return redirect(
        url_for(
            "vehicle_checklist_results",
            index=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            active_day=active_day,
        )
    )

@app.route("/vehicle/checklists/<int:index>/save-detail", methods=["POST"])
@limiter.limit("20 per minute")
def save_vehicle_checklist_detail(index):
    checklist_record = Checklist.query.filter_by(
        id=index,
        company_code=session.get("company_code"),
        active=True
    ).first()

    if not checklist_record:
        return redirect("/vehicle/checklists")

    checklist = checklist_to_dict(checklist_record)

    if checklist.get("target") != "車両管理":
        return redirect("/vehicle/checklists")

    company_code = session.get("company_code")

    vehicle_record_id = request.form.get(
        "vehicle_record_id",
        type=int
    )

    year = request.form.get(
        "year",
        ""
    ).strip()

    month = request.form.get(
        "month",
        ""
    ).strip()

    day = request.form.get(
        "day",
        ""
    ).strip()

    # =========================
    # 車両検証
    # =========================

    if not vehicle_record_id:
        return "対象車両を選択してください。", 400

    vehicle = Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return "対象車両が不正です。", 400

    # =========================
    # 日付検証
    # =========================

    try:
        year_int = int(year)
        month_int = int(month)
        day_int = int(day)
    except (TypeError, ValueError):
        return "点検日が不正です。", 400

    if year_int < 2000 or year_int > 2100:
        return "点検年が不正です。", 400

    if checklist.get("frequency_unit") == "year":
        month_int = 1
        day_int = 1

    elif checklist.get("display_type") == "month":
        if month_int < 1 or month_int > 12:
            return "点検月が不正です。", 400

        try:
            datetime(
                year_int,
                month_int,
                day_int
            )
        except ValueError:
            return "点検日が不正です。", 400

    else:
        if month_int < 1 or month_int > 12:
            return "点検月が不正です。", 400

        day_int = 1

    year = str(year_int)
    month = str(month_int).zfill(2)
    day = str(day_int).zfill(2)

    item_no_raw = request.form.get(
        "item_no",
        ""
    ).strip()

    if checklist.get("frequency_unit") == "year":
        active_day = year
    elif checklist.get("display_type") == "month":
        active_day = day
    else:
        active_day = month

    comment = request.form.get(
        "comment",
        ""
    ).strip()

    if len(comment) > 5000:
        return "コメントは5000文字以内で入力してください。", 400

    result_record = VehicleChecklistResult.query.filter_by(
        company_code=company_code,
        checklist_id=checklist_record.id,
        vehicle_record_id=vehicle_record_id,
        year=year,
        month=month,
        day=day
    ).first()

    if (
        result_record
        and result_record.status == "承認済み"
    ):
        return "承認済みの点検結果は変更できません。", 403

    result_checklist = checklist_for_date(
        checklist,
        year,
        month,
        day
    )

    if (
        result_record
        and result_record.checklist_snapshot_json
    ):
        snapshot = safe_json_dict(
            result_record.checklist_snapshot_json
        )

        if snapshot:
            result_checklist = snapshot

    # =========================
    # チェック項目検証
    # =========================

    try:
        item_no = int(item_no_raw)
    except (TypeError, ValueError):
        return "チェック項目が不正です。", 400

    check_items = [
        item
        for item in result_checklist.get("items", [])
        if item.get("item_type") == "check"
    ]

    if item_no < 0 or item_no >= len(check_items):
        return "チェック項目が不正です。", 400

    checklist_item = check_items[item_no]

    category = checklist_item.get(
        "category",
        ""
    )

    content = checklist_item.get(
        "content",
        ""
    )

    criteria = checklist_item.get(
        "criteria",
        ""
    )
    
    if not result_record:
        result_record = VehicleChecklistResult(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day,
            checked_by=session.get("name"),
            checked_by_username=session.get("username"),
            checked_date=datetime.now(
                ZoneInfo("Asia/Tokyo")
            ).strftime("%Y-%m-%d %H:%M"),
            status="入力中",
            approved_by="",
            approved_by_username="",
            approved_date="",
            reject_reason="",
            answers_json="[]",
            checklist_snapshot_json=json.dumps(
                result_checklist,
                ensure_ascii=False
            )
        )
        db.session.add(result_record)

    answers = safe_json_dict_list(
        result_record.answers_json
    )

    answer = None

    for a in answers:
        if str(a.get("item_no", "")) == str(item_no):
            answer = a
            break

    if not answer:
        answer = {
            "category": category,
            "item_no": item_no,
            "content": content,
            "criteria": criteria,
            "value": "",
            "comment": "",
            "files": []
        }
        answers.append(answer)

    uploaded_files = request.files.getlist("files")
    answer.setdefault("files", [])

    for file in uploaded_files:
        filename = save_uploaded_file(file)

        if filename:
            answer["files"].append(filename)

    answer["comment"] = comment
    answer["category"] = category
    answer["content"] = content
    answer["criteria"] = criteria

    approvals = []

    for item in result_checklist.get("items", []):
        if item.get("item_type") != "approval":
            continue

        approvals.append({
            "label": item.get("approval_label", ""),
            "allow_general": item.get("approval_allow_general", False),
            "approved_by": "",
            "approved_by_username": "",
            "approved_date": "",
        })

    result_record.checked_by = session.get("name")
    result_record.checked_by_username = session.get("username")
    result_record.checked_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    result_record.status = "入力中"
    result_record.approved_by = ""
    result_record.approved_by_username = ""
    result_record.approved_date = ""
    result_record.approvals_json = json.dumps(
        approvals,
        ensure_ascii=False
    )
    result_record.reject_reason = ""
    result_record.answers_json = json.dumps(answers, ensure_ascii=False)

    if request.form.get("patrol_link") == "1":
        existing_patrol = VehiclePatrol.query.filter_by(
            company_code=checklist_record.company_code,
            vehicle_record_id=vehicle_record_id,
            occurred_date=f"{year}-{month}-{day}",
            category="点検指摘",
            content=content
        ).first()

        if existing_patrol:
            existing_patrol.temporary_action = comment
        else:
            db.session.add(VehiclePatrol(
                company_code=checklist_record.company_code,
                vehicle_record_id=vehicle_record_id,
                occurred_date=f"{year}-{month}-{day}",
                category="点検指摘",
                priority="中",
                content=content,
                cause="",
                temporary_action=comment,
                repair_content="",
                status="未対応",
                repair_date="",
                repair_person="",
                repair_time="",
                parts="",
                cost=""
            ))

    db.session.commit()

    notify_mentions(
        comment,
        f"/vehicle/checklists/{checklist_record.id}?vehicle_record_id={vehicle_record_id}&year={year}&month={month}&active_day={active_day}"
    )

    return redirect(
        url_for(
            "vehicle_checklist_results",
            index=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            active_day=active_day,
        )
    )

@app.route("/vehicle/checklists/<int:index>/complete", methods=["POST"])
@limiter.limit("20 per minute")
def complete_vehicle_checklist(index):
    company_code = session.get("company_code")

    checklist_record = Checklist.query.filter_by(
        id=index,
        company_code=company_code,
        active=True
    ).first()

    if not checklist_record:
        return redirect("/vehicle/checklists")

    checklist = checklist_to_dict(checklist_record)

    if checklist.get("target") != "車両管理":
        return redirect("/vehicle/checklists")

    vehicle_record_id = request.form.get(
        "vehicle_record_id",
        type=int
    )

    year = request.form.get(
        "year",
        ""
    ).strip()

    month = request.form.get(
        "month",
        ""
    ).strip()

    day = request.form.get(
        "day",
        ""
    ).strip()

    if checklist.get("frequency_unit") == "year":
        active_day = year
    elif checklist.get("display_type") == "month":
        active_day = day
    else:
        active_day = month

    # =========================
    # 車両検証
    # =========================

    if not vehicle_record_id:
        return "対象車両を選択してください。", 400

    vehicle = Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return "対象車両が不正です。", 400

    # =========================
    # 日付検証
    # =========================

    try:
        year_int = int(year)
        month_int = int(month)
        day_int = int(day)
    except (TypeError, ValueError):
        return "点検日が不正です。", 400

    if year_int < 2000 or year_int > 2100:
        return "点検年が不正です。", 400

    if checklist.get("frequency_unit") == "year":
        month_int = 1
        day_int = 1

    elif checklist.get("display_type") == "month":
        if month_int < 1 or month_int > 12:
            return "点検月が不正です。", 400

        try:
            datetime(
                year_int,
                month_int,
                day_int
            )
        except ValueError:
            return "点検日が不正です。", 400

    else:
        if month_int < 1 or month_int > 12:
            return "点検月が不正です。", 400

        day_int = 1

    year = str(year_int)
    month = str(month_int).zfill(2)
    day = str(day_int).zfill(2)

    # =========================
    # 結果取得
    # =========================

    result_record = VehicleChecklistResult.query.filter_by(
        company_code=company_code,
        checklist_id=checklist_record.id,
        vehicle_record_id=vehicle_record_id,
        year=year,
        month=month,
        day=day
    ).first()

    if not result_record:
        return redirect(
            url_for(
                "vehicle_checklist_results",
                index=checklist_record.id,
                vehicle_record_id=vehicle_record_id,
                year=year,
                month=month,
                active_day=active_day,
            )
        )

    if result_record.status == "承認済み":
        return "承認済みの点検結果は変更できません。", 403

    result_checklist = checklist

    if result_record.checklist_snapshot_json:
        snapshot = safe_json_dict(
            result_record.checklist_snapshot_json
        )

        if snapshot:
            result_checklist = snapshot

    answers = safe_json_dict_list(
        result_record.answers_json
    )

    check_items = [
        item
        for item in result_checklist.get("items", [])
        if item.get("item_type") == "check"
    ]

    answered_item_numbers = {
        str(answer.get("item_no", ""))
        for answer in answers
    }

    missing_item_numbers = [
        index
        for index in range(len(check_items))
        if str(index) not in answered_item_numbers
    ]

    if missing_item_numbers:
        return (
            "未入力のチェック項目があります。"
            "すべての項目を入力してから完了してください。",
            400
        )

    # =========================
    # 通知先ユーザー検証
    # =========================

    notify_usernames = [
        username.strip()
        for username in request.form.getlist(
            "notify_users"
        )
        if username.strip()
    ]

    if len(notify_usernames) > 500:
        return "通知先ユーザー数が多すぎます。", 400

    valid_users = {
        user.username: user
        for user in User.query.filter_by(
            company_code=company_code
        ).all()
        if user.username
    }

    for username in notify_usernames:
        if username not in valid_users:
            return "通知先ユーザーが不正です。", 400

    notify_usernames = list(
        dict.fromkeys(notify_usernames)
    )

    if not notify_usernames:
        notify_usernames = (
            get_vehicle_checklist_notify_users(
                company_code,
                checklist_record.id,
                vehicle_record_id
            )
        )

    notify_usernames = [
        username
        for username in notify_usernames
        if username in valid_users
    ]

    # =========================
    # 完了処理
    # =========================

    result_record.status = "承認待ち"
    result_record.checked_by = session.get("name")
    result_record.checked_by_username = session.get("username")
    result_record.checked_date = (
        datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    approvals = []

    for item in result_checklist.get("items", []):
        if item.get("item_type") != "approval":
            continue

        approvals.append({
            "label": item.get("approval_label", ""),
            "allow_general": item.get("approval_allow_general", False),
            "approved_by": "",
            "approved_by_username": "",
            "approved_date": "",
        })

    result_record.approved_by = ""
    result_record.approved_by_username = ""
    result_record.approved_date = ""
    result_record.approvals_json = json.dumps(
        approvals,
        ensure_ascii=False
    )
    result_record.reject_reason = ""

    result_record.notify_users_json = json.dumps(
        notify_usernames,
        ensure_ascii=False
    )

    db.session.commit()

    # =========================
    # 通知
    # =========================

    notification_link = url_for(
        "vehicle_checklist_results",
        index=checklist_record.id,
        vehicle_record_id=vehicle_record_id,
        year=year,
        month=month,
        active_day=active_day,
    )

    for target_username in notify_usernames:
        target_user = valid_users[target_username]

        add_notification(
            target_user.name,
            "車両点検完了のお知らせ",
            (
                f"{vehicle.chassis_number} の"
                f"「{checklist_record.name}」が"
                f"点検完了しました。"
            ),
            notification_link,
            company_code=company_code,
            target_username=target_user.username
        )

    return redirect(
        notification_link
    )

@app.route("/vehicle/checklists/<int:index>/new", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
def new_vehicle_checklist_result(index):
    checklist_record = Checklist.query.filter_by(
        id=index,
        company_code=session.get("company_code"),
        active=True
    ).first()

    if not checklist_record:
        return redirect("/vehicle/checklists")

    checklist = checklist_to_dict(checklist_record)

    if checklist["target"] != "車両管理":
        return redirect("/vehicle/checklists")

    if request.method == "POST":
        company_code = session.get("company_code")

        vehicle_record_id = request.form.get(
            "vehicle_record_id",
            type=int
        )

        year = request.form.get(
            "year",
            ""
        ).strip()

        month = request.form.get(
            "month",
            ""
        ).strip()

        day = request.form.get(
            "day",
            ""
        ).strip()

        # =========================
        # 車両検証
        # =========================

        if not vehicle_record_id:
            return "対象車両を選択してください。", 400

        vehicle = Vehicle.query.filter_by(
            company_code=company_code,
            id=vehicle_record_id,
            deleted=False
        ).first()

        if not vehicle:
            return "対象車両が不正です。", 400

        # =========================
        # 日付検証
        # =========================

        try:
            year_int = int(year)
            month_int = int(month)
            day_int = int(day)
        except (TypeError, ValueError):
            return "点検日が不正です。", 400

        if year_int < 2000 or year_int > 2100:
            return "点検年が不正です。", 400

        # 年次チェックリスト
        if checklist.get("frequency_unit") == "year":
            month_int = 1
            day_int = 1

        # 日単位表示
        elif checklist.get("display_type") == "month":
            if month_int < 1 or month_int > 12:
                return "点検月が不正です。", 400

            try:
                datetime(
                    year_int,
                    month_int,
                    day_int
                )
            except ValueError:
                return "点検日が不正です。", 400

        # 月単位など
        else:
            if month_int < 1 or month_int > 12:
                return "点検月が不正です。", 400

            day_int = 1

        year = str(year_int)
        month = str(month_int).zfill(2)
        day = str(day_int).zfill(2)

        answers = []
        answer_index = 0
        pending_answer_files = []

        for item in checklist["items"]:
            if item.get("item_type") == "approval":
                continue

            value = request.form.get(
                f"answer_{answer_index}",
                ""
            )

            input_type = item.get(
                "input_type",
                ""
            )

            # =========================
            # 回答値検証
            # =========================

            if input_type == "select":
                valid_choices = [
                    str(choice)
                    for choice in item.get(
                        "choices",
                        []
                    )
                ]

                if value not in valid_choices:
                    return "回答値が不正です。", 400
                
            comment = request.form.get(
                f"comment_{answer_index}",
                ""
            ).strip()

            if len(comment) > 5000:
                return "コメントは5000文字以内で入力してください。", 400

            item_index = len(answers)

            answers.append({
                "item_no": answer_index,
                "category": item.get("category", ""),
                "content": item.get("content", ""),
                "criteria": item.get("criteria", ""),
                "value": value,
                "comment": comment,
                "files": []
            })

            pending_answer_files.append(
                (item_index, answer_index)
            )

            answer_index += 1

        for item_index, form_index in pending_answer_files:
            for file in request.files.getlist(
                f"files_{form_index}"
            ):
                filename = save_uploaded_file(file)

                if filename:
                    answers[item_index]["files"].append(filename)

        approvals = []

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get("approval_allow_general", False),
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        result = VehicleChecklistResult(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day,
            checked_by=session.get("name"),
            checked_by_username=session.get("username"),
            checked_date=datetime.now(
                ZoneInfo("Asia/Tokyo")
            ).strftime("%Y-%m-%d %H:%M"),
            status="承認待ち",
            approved_by="",
            approved_by_username="",
            approved_date="",
            reject_reason="",
            approvals_json=json.dumps(
                approvals,
                ensure_ascii=False
            ),
            answers_json=json.dumps(answers, ensure_ascii=False),
            checklist_snapshot_json=json.dumps(
                checklist,
                ensure_ascii=False
            )
        )

        db.session.add(result)
        db.session.commit()

        mention_text = "\n".join(
            "\n".join([
                answer.get("value", "") or "",
                answer.get("comment", "") or "",
            ])
            for answer in answers
        )

        notify_mentions(
            mention_text,
            f"/vehicle/checklists/{checklist_record.id}"
        )

        return redirect(
            url_for(
                "vehicle_checklist_results",
                index=checklist_record.id,
                vehicle_record_id=vehicle_record_id,
                year=year,
                month=month,
            )
        )
        
    return render_template(
        "vehicle_checklist_form.html",
        checklist=checklist,
        checklist_index=checklist_record.id,
        mode="new",
        now_year=datetime.now().year,
        now_month=datetime.now().month,
        now_day=datetime.now().day
    )

@app.route("/safety/checklists/<int:index>/new", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
def new_safety_checklist_result(index):
    checklist_record = Checklist.query.filter_by(
        id=index,
        company_code=session.get("company_code"),
        active=True
    ).first()

    if not checklist_record:
        return redirect("/safety/checklists")

    checklist = checklist_to_dict(checklist_record)

    if request.method == "POST":
        company_code = session.get("company_code")

        answers = []
        answer_index = 0

        target_type = request.form.get(
            "target_type",
            ""
        ).strip()

        target_user = request.form.get(
            "target_user",
            ""
        ).strip()

        target_username = ""

        target_vehicle_record_id = request.form.get(
            "target_vehicle_record_id",
            type=int
        )

        target_office = request.form.get(
            "target_office",
            ""
        ).strip()

        # =========================
        # 対象種別検証
        # =========================

        if target_type not in {
            "",
            "user",
            "vehicle",
            "office"
        }:
            return "対象種別が不正です。", 400

        # =========================
        # 個人
        # =========================

        if target_type == "user":
            if not target_user:
                return "対象ユーザーを選択してください。", 400

            target_driver = Driver.query.filter_by(
                company_code=company_code,
                employee_id=target_user
            ).first()

            if not target_driver:
                return "対象ユーザーが不正です。", 400

            target_user_record = User.query.filter_by(
                company_code=company_code,
                username=target_driver.employee_id
            ).first()

            if not target_user_record:
                return "対象ユーザー情報が不正です。", 400

            target_username = target_user_record.username
            target_user = target_driver.name
            target_office = target_driver.office or ""
            target_vehicle_record_id = None

        # =========================
        # 車両
        # =========================

        elif target_type == "vehicle":
            if not target_vehicle_record_id:
                return "対象車両を選択してください。", 400

            vehicle = Vehicle.query.filter_by(
                company_code=company_code,
                id=target_vehicle_record_id,
                deleted=False
            ).first()

            if not vehicle:
                return "対象車両が不正です。", 400

            target_office = vehicle.office or ""
            target_user = ""

        # =========================
        # 営業所
        # =========================

        elif target_type == "office":
            if not target_office:
                return "対象営業所を選択してください。", 400

            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=target_office
            ).first()

            if not valid_office:
                return "対象営業所が不正です。", 400

            target_user = ""
            target_vehicle_record_id = None

        pending_answer_files = []

        for item in checklist["items"]:
            if item.get("item_type") == "approval":
                continue

            value = request.form.get(
                f"answer_{answer_index}",
                ""
            )

            choices = item.get("choices", [])

            if item.get("input_type") == "select":
                if value not in choices:
                    return "評価値が不正です。", 400

            elif not value.strip():
                return "必須項目を入力してください。", 400

            comment = request.form.get(
                f"comment_{answer_index}",
                ""
            ).strip()

            if (
                item.get("comment_required")
                and not comment
            ):
                return "必須コメントを入力してください。", 400

            if len(comment) > 5000:
                return "コメントは5000文字以内で入力してください。", 400

            patrol_link = request.form.get(
                f"patrol_link_{answer_index}"
            )

            item_index = len(answers)

            answers.append({
                "category": item.get("category", ""),
                "content": item.get("content", ""),
                "criteria": item.get("criteria", ""),
                "criteria_files": item.get("criteria_files", []),
                "value": value,
                "comment": comment,
                "files": [],
                "patrol_link": patrol_link == "1",
            })

            pending_answer_files.append(
                (item_index, answer_index)
            )

            answer_index += 1

        for item_index, form_index in pending_answer_files:
            for file in request.files.getlist(
                f"files_{form_index}"
            ):
                filename = save_uploaded_file(file)

                if filename:
                    answers[item_index]["files"].append(filename)

        if target_type in PATROL_VIEW_TYPES:
            for answer in answers:
                if not answer.get("patrol_link"):
                    continue

                db.session.add(PatrolResult(
                    company_code=session.get("company_code"),
                    created_by_username=session.get("username"),
                    created_by_name=session.get("name"),
                    date=datetime.now().strftime("%Y-%m-%d"),
                    delivery_place="",
                    category="点検指摘",
                    content_type="安全",
                    target_type=target_type,
                    target_user=target_user,
                    target_username=target_username,
                    office=target_office,
                    content=(
                        f"{answer.get('category', '')}：{answer.get('content', '')}"
                        f" / 評価：{answer.get('value') or '-'}"
                        f" / コメント：{answer.get('comment') or '-'}"
                    ),
                    files_json=json.dumps(
                        answer.get("files", []),
                        ensure_ascii=False
                    ),
                    countermeasure="",
                    approval_status="未対応",
                    reject_reason=""
                ))

        approvals = []

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get("approval_allow_general", False),
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        result = ChecklistResult(
            company_code=company_code,
            checklist_id=checklist_record.id,
            target_type=target_type,
            target_user=target_user,
            target_username=target_username,
            target_vehicle_record_id=target_vehicle_record_id,
            target_office=target_office,
            checked_by=session.get("name"),
            checked_by_username=session.get("username"),
            checked_date=datetime.now(
                ZoneInfo("Asia/Tokyo")
            ).strftime("%Y-%m-%d %H:%M"),
            approved_by="",
            approved_by_username="",
            approved_date="",
            reject_reason="",
            status="承認待ち",
            approvals_json=json.dumps(
                approvals,
                ensure_ascii=False
            ),
            answers_json=json.dumps(
                answers,
                ensure_ascii=False
            ),
            checklist_snapshot_json=json.dumps(
                checklist,
                ensure_ascii=False
            )
        )

        db.session.add(result)
        db.session.commit()

        if target_type == "user" and target_username:
            add_notification(
                target_user,
                "安全チェックリスト完了のお知らせ",
                (
                    f"「{checklist_record.name}」の"
                    f"チェックが完了しました。"
                ),
                f"/safety/checklist-results/{result.id}",
                company_code=company_code,
                target_username=target_username
            )

        mention_text = "\n".join(
            "\n".join([
                answer.get("value", "") or "",
                answer.get("comment", "") or "",
            ])
            for answer in answers
        )

        notify_mentions(
            mention_text,
            f"/safety/checklist-results/{result.id}"
        )

        return redirect(f"/safety/checklists/{checklist_record.id}")

    criteria_list = []

    for item in checklist["items"]:
        if item.get("item_type") == "approval":
            continue

        criteria = item.get("criteria", "")
        if criteria and criteria not in criteria_list:
            criteria_list.append(criteria)

    return render_template(
        "checklist_result_form.html",
        checklist=checklist,
        index=checklist_record.id,
        criteria_list=criteria_list,
        drivers=drivers_for_current_company(),
        selected_vehicle=None,
        offices=offices_for_current_company()
    )

@app.route("/master/checklists/<int:index>/edit", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def edit_checklist(index):
    checklist_record = Checklist.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not checklist_record:
        return redirect("/master/checklists")

    checklist = checklist_to_dict(checklist_record)

    if request.method == "POST":
        has_safety_results = ChecklistResult.query.filter_by(
            company_code=checklist_record.company_code,
            checklist_id=checklist_record.id
        ).first()

        has_vehicle_results = VehicleChecklistResult.query.filter_by(
            company_code=checklist_record.company_code,
            checklist_id=checklist_record.id
        ).first()

        target = request.form.get("target", "").strip()

        if target not in {
            "安全管理",
            "車両管理"
        }:
            return "用途が不正です。", 400

        if (
            has_vehicle_results
            and checklist_record.target != target
        ):
            return (
                "車両点検履歴が存在するため、用途は変更できません。",
                409
            )        
        item_categories = request.form.getlist("item_category")
        item_contents = request.form.getlist("item_content")
        input_types = request.form.getlist("input_type")
        item_types = request.form.getlist("item_type")
        approval_labels = request.form.getlist("approval_label")
        approval_allow_general_list = request.form.getlist("approval_allow_general")
        choices_list = request.form.getlist("choices")
        criteria_list = request.form.getlist("criteria")
        comment_required_list = request.form.getlist("comment_required")
        shaded_list = request.form.getlist("shaded")

        if len(item_types) > 500:
            return "チェック項目は500件以内で設定してください。", 400

        if any(
            item_type not in {
                "check",
                "inspector",
                "approval"
            }
            for item_type in item_types
        ):
            return "項目種別が不正です。", 400

        if any(
            input_type not in {
                "select",
                "text"
            }
            for input_type in input_types
        ):
            return "評価方式が不正です。", 400

        required_list_length = len(item_types)

        if any(
            len(values) < required_list_length
            for values in [
                item_categories,
                item_contents,
                input_types,
                choices_list,
                criteria_list
            ]
        ):
            return "チェック項目のデータが不正です。", 400

        score_enabled = request.form.get("score_enabled") == "1"
        print_portrait = (
            request.form.get("target") == "車両管理"
            and request.form.get("print_portrait") == "1"
        )
        print_half_month = (
            request.form.get("target") == "車両管理"
            and request.form.get("print_half_month") == "1"
        )
        reminder_enabled = (
            request.form.get("reminder_enabled") == "1"
        )

        reminder_time = parse_time_hhmm(
            request.form.get("reminder_time") or "17:00",
            "未実施通知時刻"
        )

        name = request.form.get("name", "").strip()

        if not name:
            return "チェックリスト名を入力してください。", 400

        if len(name) > 200:
            return "チェックリスト名は200文字以内で入力してください。", 400

        duplicate_checklist = Checklist.query.filter(
            Checklist.company_code == checklist_record.company_code,
            Checklist.name == name,
            Checklist.id != checklist_record.id
        ).first()

        if duplicate_checklist:
            return "このチェックリストはすでに登録されています。", 409

        frequency_number = None
        frequency_unit = ""
        display_type = ""

        if target == "車両管理":
            frequency_value = request.form.get(
                "frequency_value",
                ""
            ).strip()
            frequency_unit = request.form.get(
                "frequency_unit",
                ""
            ).strip()
            display_type = request.form.get(
                "display_type",
                ""
            ).strip()

            try:
                frequency_number = int(frequency_value)
            except (TypeError, ValueError):
                return "頻度は整数で入力してください。", 400

            if frequency_number < 1:
                return "頻度は1以上で入力してください。", 400

            if frequency_number > 9999:
                return "頻度は9999以下で入力してください。", 400

            if frequency_unit not in {
                "day",
                "month",
                "year"
            }:
                return "頻度単位が不正です。", 400

            if display_type not in {
                "month",
                "year"
            }:
                return "表示形式が不正です。", 400
            
        old_items = checklist.get("items", [])
        items = []
        pending_criteria_files = []

        for i in range(len(item_types)):
            item_type = item_types[i]

            if item_type == "inspector":
                items.append({
                    "item_type": "inspector",
                })
                continue

            if item_type == "approval":
                label = ""

                if i < len(approval_labels):
                    label = approval_labels[i].strip()

                if len(label) > 100:
                    return (
                        "承認ラベルは100文字以内で入力してください。",
                        400
                    )

                items.append({
                    "item_type": "approval",
                    "approval_label": label,
                    "approval_allow_general": str(i) in approval_allow_general_list,
                    "criteria_files": [],
                })

                continue

            if i >= len(item_contents):
                continue

            if not item_contents[i]:
                continue

            category = str(
                item_categories[i] or ""
            ).strip()
            content = str(
                item_contents[i] or ""
            ).strip()
            criteria = str(
                criteria_list[i] or ""
            ).strip()

            if len(category) > 100:
                return (
                    "カテゴリは100文字以内で入力してください。",
                    400
                )

            if len(content) > 500:
                return (
                    "チェック内容は500文字以内で入力してください。",
                    400
                )

            if len(criteria) > 500:
                return (
                    "判定基準は500文字以内で入力してください。",
                    400
                )

            choices = []

            if input_types[i] == "select":
                choices = [
                    choice.strip()
                    for choice in choices_list[i].split(",")
                    if choice.strip()
                ]

                if not choices:
                    return (
                        "選択式のチェック項目には評価の選択肢を1つ以上入力してください。",
                        400
                    )

                if len(choices) > 100:
                    return (
                        "選択肢は100個以内で入力してください。",
                        400
                    )

                if any(
                    len(choice) > 100
                    for choice in choices
                ):
                    return (
                        "各選択肢は100文字以内で入力してください。",
                        400
                    )

            criteria_files = []

            if i < len(old_items):
                criteria_files = list(
                    old_items[i].get("criteria_files", [])
                )

            item_index = len(items)

            items.append({
                "item_type": "check",
                "category": category,
                "content": content,
                "input_type": input_types[i],
                "choices": choices,
                "criteria": criteria,
                "criteria_files": criteria_files,
                "comment_required": str(i) in comment_required_list,
                "shaded": str(i) in shaded_list,
                "score_enabled": score_enabled,
            })

            pending_criteria_files.append((item_index, i))

        for item_index, form_index in pending_criteria_files:
            for file in request.files.getlist(
                f"criteria_files_{form_index}"
            ):
                filename = save_uploaded_file(file)

                if filename:
                    items[item_index]["criteria_files"].append(filename)

        version_history = safe_json_dict_list(
            checklist_record.version_history_json
        )

        if has_safety_results or has_vehicle_results:
            version_history.append({
                "effective_until": datetime.now(
                    ZoneInfo("Asia/Tokyo")
                ).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "snapshot": {
                    key: value
                    for key, value in checklist.items()
                    if key != "version_history"
                }
            })

        checklist_record.version_history_json = json.dumps(
            version_history,
            ensure_ascii=False
        )

        checklist_record.name = name
        checklist_record.target = target
        checklist_record.reminder_enabled = reminder_enabled
        checklist_record.reminder_time = reminder_time

        if target == "車両管理":
            checklist_record.frequency_value = str(
                frequency_number
            )
            checklist_record.frequency_unit = frequency_unit
            checklist_record.display_type = display_type
            checklist_record.print_portrait = print_portrait
            checklist_record.print_half_month = print_half_month
        else:
            checklist_record.frequency_value = ""
            checklist_record.frequency_unit = ""
            checklist_record.display_type = ""
            checklist_record.print_portrait = False
            checklist_record.print_half_month = False

        checklist_record.items_json = json.dumps(items, ensure_ascii=False)

        db.session.commit()

        return redirect("/master/checklists")

    return render_template(
        "checklist_form.html",
        checklist=checklist,
        index=checklist_record.id,
        mode="edit"
    )


@app.route("/master/checklists/<int:index>/duplicate", methods=["POST"])
@limiter.limit("10 per minute")
def duplicate_checklist(index):
    company_code = session.get("company_code")

    source = Checklist.query.filter_by(
        id=index,
        company_code=company_code
    ).first()

    if not source:
        return redirect("/master/checklists")

    base_name = f"{source.name}（コピー）"
    new_name = base_name
    copy_no = 2

    while Checklist.query.filter_by(
        company_code=company_code,
        name=new_name
    ).first():
        new_name = f"{source.name}（コピー{copy_no}）"
        copy_no += 1

    duplicated = Checklist(
        company_code=company_code,
        name=new_name,
        target=source.target,
        frequency_value=source.frequency_value,
        frequency_unit=source.frequency_unit,
        display_type=source.display_type,
        print_portrait=source.print_portrait,
        print_half_month=source.print_half_month,
        reminder_enabled=source.reminder_enabled,
        reminder_time=source.reminder_time,
        active=True,
        items_json=source.items_json,
        notify_users_json=source.notify_users_json,
        version_history_json="[]"
    )

    db.session.add(duplicated)
    db.session.flush()

    add_audit_log(
        action="duplicate_checklist",
        target_type="checklist",
        target_id=str(duplicated.id),
        detail=f"{source.name} から {new_name} を複製"
    )

    db.session.commit()

    return redirect(
        f"/master/checklists/{duplicated.id}/edit?duplicated=1"
    )


@app.route("/master/checklists/<int:index>/toggle-active", methods=["POST"])
@limiter.limit("10 per minute")
def toggle_checklist_active(index):
    checklist = Checklist.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not checklist:
        return redirect("/master/checklists")

    checklist.active = not checklist.active

    add_audit_log(
        action="checklist_activated" if checklist.active else "checklist_deactivated",
        target_type="checklist",
        target_id=str(checklist.id),
        detail=f"{checklist.name} を"
        f"{'有効化' if checklist.active else '無効化'}"
    )

    db.session.commit()

    return redirect("/master/checklists")


@app.route("/master/checklists/<int:index>/delete", methods=["POST"])
@limiter.limit("10 per minute")
def delete_checklist(index):
    checklist = Checklist.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not checklist:
        return redirect("/master/checklists")

    has_safety_results = ChecklistResult.query.filter_by(
        company_code=checklist.company_code,
        checklist_id=checklist.id
    ).first()

    has_vehicle_results = VehicleChecklistResult.query.filter_by(
        company_code=checklist.company_code,
        checklist_id=checklist.id
    ).first()

    if has_safety_results or has_vehicle_results:
        return (
            "点検履歴が存在するチェックリストは削除できません。",
            409
        )

    add_audit_log(
        action="checklist_deleted",
        target_type="checklist",
        target_id=checklist.id,
        detail=f"チェックリスト削除: {checklist.name}",
        company_code=checklist.company_code,
    )

    VehicleChecklistNotifySetting.query.filter_by(
        company_code=checklist.company_code,
        checklist_id=checklist.id
    ).delete(synchronize_session=False)

    db.session.delete(checklist)
    db.session.commit()
    return redirect("/master/checklists")


@app.route(
    "/safety/checklist-results/<int:result_index>/approve/<int:approval_index>",
    methods=["POST"]
)
@limiter.limit("20 per minute")
def approve_checklist_result(result_index, approval_index):
    result_record = ChecklistResult.query.filter_by(
        id=result_index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/safety/checklists")

    if result_record.status != "承認待ち":
        return redirect(
            f"/safety/checklist-results/{result_index}"
        )

    result = checklist_result_to_dict(result_record)

    approvals = result.get("approvals", [])
    if not approvals:
        approval_checklist = {}

        if result_record.checklist_snapshot_json:
            approval_checklist = safe_json_dict(
                result_record.checklist_snapshot_json
            )

        if not approval_checklist:
            checklist_record = Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                approval_checklist = checklist_to_dict(
                    checklist_record
                )

        for item in approval_checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get(
                    "approval_allow_general",
                    False
                ),
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

    if approval_index < 0 or approval_index >= len(approvals):
        return redirect(f"/safety/checklist-results/{result_index}")

    if any(
        not (
            item.get("approved_by")
            or item.get("approved_by_username")
        )
        for item in approvals[:approval_index]
    ):
        return redirect(
            f"/safety/checklist-results/{result_index}"
        )

    approval = approvals[approval_index]

    if (
        approval.get("approved_by")
        or approval.get("approved_by_username")
    ):
        return redirect(
            f"/safety/checklist-results/{result_index}"
        )

    if not can_approve_checklist_result(result, approval):
        return redirect(f"/safety/checklist-results/{result_index}")

    approval["approved_by"] = session.get("name")
    approval["approved_by_username"] = session.get("username")    
    approval["approved_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    result_record.approvals_json = json.dumps(
        approvals,
        ensure_ascii=False
    )

    result_record.reject_reason = ""

    all_approved = all(
        item.get("approved_by")
        for item in approvals
    )

    if approvals and all_approved:
        result_record.status = "承認済み"
        result_record.approved_by = session.get("name")
        result_record.approved_by_username = session.get("username")        
        result_record.approved_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    else:
        result_record.status = "承認待ち"
        result_record.approved_by = ""
        result_record.approved_by_username = ""
        result_record.approved_date = ""

    db.session.commit()

    if result_record.status == "承認済み":
        notify_usernames = {
            username
            for username in [
                result_record.checked_by_username,
                result_record.target_username
            ]
            if username
        }

        for target_username in notify_usernames:
            target_user = User.query.filter_by(
                company_code=result_record.company_code,
                username=target_username
            ).first()

            if not target_user:
                continue

            add_notification(
                target_user.name,
                "チェックリストが承認されました",
                "チェックリストの承認が完了しました。",
                f"/safety/checklist-results/{result_record.id}",
                company_code=result_record.company_code,
                target_username=target_user.username
            )

    return redirect(f"/safety/checklist-results/{result_record.id}")

@app.route("/safety/checklist-results/<int:result_index>/reject", methods=["POST"])
@limiter.limit("20 per minute")
def reject_checklist_result(result_index):
    result_record = ChecklistResult.query.filter_by(
        id=result_index,
        company_code=session.get("company_code")
    ).first()

    if not result_record:
        return redirect("/safety/checklists")

    if result_record.status != "承認待ち":
        return redirect(
            f"/safety/checklist-results/{result_index}"
        )

    result = checklist_result_to_dict(result_record)

    if not can_reject_checklist_result(result):
        return redirect(f"/safety/checklist-results/{result_index}")

    reject_reason = request.form.get(
        "reject_reason",
        ""
    ).strip()

    if len(reject_reason) > 5000:
        return "差し戻し理由は5000文字以内で入力してください。", 400

    approvals = safe_json_dict_list(
        result_record.approvals_json
    )

    for approval in approvals:
        approval["approved_by"] = ""
        approval["approved_by_username"] = ""
        approval["approved_date"] = ""

    result_record.approvals_json = json.dumps(
        approvals,
        ensure_ascii=False
    )

    result_record.status = "差し戻し"
    result_record.approved_by = ""
    result_record.approved_by_username = ""
    result_record.approved_date = ""
    result_record.reject_reason = reject_reason

    notify_usernames = set()

    if result_record.checked_by_username:
        notify_usernames.add(
            result_record.checked_by_username
        )

    if result_record.target_username:
        notify_usernames.add(
            result_record.target_username
        )

    db.session.commit()

    for target_username in notify_usernames:
        target_user = User.query.filter_by(
            company_code=result_record.company_code,
            username=target_username
        ).first()

        if not target_user:
            continue

        add_notification(
            target_user.name,
            "チェックリストが差し戻されました",
            reject_reason or "チェックリストが差し戻されました。",
            f"/safety/checklist-results/{result_record.id}",
            company_code=result_record.company_code,
            target_username=target_user.username
        )

    return redirect(f"/safety/checklist-results/{result_record.id}")

def init_db():
    with app.app_context():
        db.create_all()

        cleanup_old_audit_logs()

        if not Company.query.filter_by(company_code="ITC").first():
            db.session.add(Company(
                company_code="ITC",
                company_name="ITC",
                vehicle_limit=9999,
                active=True
            ))
            db.session.commit()

        if not User.query.filter_by(
            company_code="ITC",
            username="itc"
        ).first():
            initial_password = os.environ.get(
                "ITC_INITIAL_PASSWORD"
            )

            if not initial_password:
                raise RuntimeError(
                    "ITC_INITIAL_PASSWORD environment variable is required "
                    "when creating the initial ITC administrator."
                )

            db.session.add(User(
                company_code="ITC",
                username="itc",
                password=generate_password_hash(
                    initial_password
                ),
                role="itc",
                name="ITC管理者",
                office="ITC",
                favorite_vehicles_json="[]"
            ))
            
        default_content_types = [
            "落下",
            "車両",
            "環境",
            "荷扱い",
            "ルール違反",
            "Good",
            "その他"
        ]

        for company in Company.query.all():
            for name in default_content_types:
                exists = PatrolContentType.query.filter_by(
                    company_code=company.company_code,
                    name=name
                ).first()

                if not exists:
                    db.session.add(PatrolContentType(
                        company_code=company.company_code,
                        name=name
                    ))

        db.session.commit()
        db.session.execute(
            db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_user_company_username "
                'ON "user" (company_code, username)'
            )
        )

        db.session.execute(
            db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_driver_company_employee_id "
                "ON driver (company_code, employee_id)"
            )
        )

        duplicate_vehicle_type = (
            db.session.query(
                VehicleType.company_code,
                VehicleType.name
            )
            .group_by(
                VehicleType.company_code,
                VehicleType.name
            )
            .having(
                db.func.count(VehicleType.id) > 1
            )
            .first()
        )

        if duplicate_vehicle_type:
            raise RuntimeError(
                "車種マスタに同一会社・同一名称の重複があります。"
            )

        db.session.execute(
            db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_vehicle_type_company_name "
                "ON vehicle_type (company_code, name)"
            )
        )

        db.session.commit()

with app.app_context():

    db.create_all()

    columns = [
        ("chassis_number", "VARCHAR(100)"),
        ("model_code", "VARCHAR(100)"),
        ("first_registration_date", "VARCHAR(20)"),
        ("manufacturer", "VARCHAR(100)"),
        ("body_type", "VARCHAR(100)"),
        ("gross_vehicle_weight", "INTEGER"),
        ("max_payload", "INTEGER"),
    ]

    inspector = inspect(db.engine)

    existing_columns = [
        column["name"]
        for column in inspector.get_columns("vehicle")
    ]

    for column_name, column_type in columns:
        if column_name not in existing_columns:
            db.session.execute(
                db.text(
                    f"ALTER TABLE vehicle "
                    f"ADD COLUMN {column_name} {column_type}"
                )
            )

    db.session.commit()

    if (
        db.engine.dialect.name == "postgresql"
        and "vehicle_id" in existing_columns
    ):
        db.session.execute(
            db.text(
                "ALTER TABLE vehicle "
                "ALTER COLUMN vehicle_id DROP NOT NULL"
            )
        )
        db.session.commit()

    if "vehicle_id" in existing_columns:
        for user in User.query.all():
            favorite_vehicle_ids = safe_json_str_list(
                user.favorite_vehicles_json
            )

            converted_favorites = []

            for favorite_vehicle_id in favorite_vehicle_ids:
                if str(favorite_vehicle_id).isdigit():
                    converted_favorites.append(
                        str(favorite_vehicle_id)
                    )
                    continue

                vehicle_row = db.session.execute(
                    db.text(
                        """
                        SELECT id
                        FROM vehicle
                        WHERE company_code = :company_code
                          AND vehicle_id = :vehicle_id
                        LIMIT 1
                        """
                    ),
                    {
                        "company_code": user.company_code,
                        "vehicle_id": favorite_vehicle_id,
                    }
                ).first()

                if vehicle_row:
                    converted_favorites.append(
                        str(vehicle_row.id)
                    )

            user.favorite_vehicles_json = json.dumps(
                converted_favorites,
                ensure_ascii=False
            )

        db.session.commit()

    for user in User.query.all():
        driver = Driver.query.filter_by(
            company_code=user.company_code,
            employee_id=user.username
        ).first()

        if not driver:
            continue

        usage_vehicle_ids = safe_json_str_list(
            driver.vehicles_json
        )

        for vehicle_record_id in safe_json_str_list(
            user.favorite_vehicles_json
        ):
            if (
                vehicle_record_id.isdigit()
                and vehicle_record_id not in usage_vehicle_ids
            ):
                usage_vehicle_ids.append(
                    vehicle_record_id
                )

        driver.vehicles_json = json.dumps(
            usage_vehicle_ids,
            ensure_ascii=False
        )

        user.favorite_vehicles_json = "[]"

    db.session.commit()

    if "vehicle_id" in existing_columns:
        for driver in Driver.query.all():
            vehicle_ids = safe_json_str_list(
                driver.vehicles_json
            )

            converted_vehicle_ids = []

            for vehicle_id in vehicle_ids:
                if str(vehicle_id).isdigit():
                    converted_vehicle_ids.append(
                        str(vehicle_id)
                    )
                    continue

                vehicle_row = db.session.execute(
                    db.text(
                        """
                        SELECT id
                        FROM vehicle
                        WHERE company_code = :company_code
                          AND vehicle_id = :vehicle_id
                        LIMIT 1
                        """
                    ),
                    {
                        "company_code": driver.company_code,
                        "vehicle_id": vehicle_id,
                    }
                ).first()

                if vehicle_row:
                    converted_vehicle_ids.append(
                        str(vehicle_row.id)
                    )

            driver.vehicles_json = json.dumps(
                list(dict.fromkeys(converted_vehicle_ids)),
                ensure_ascii=False
            )

        db.session.commit()

    vehicle_patrol_columns = [
        ("vehicle_record_id", "INTEGER"),
    ]

    existing_vehicle_patrol_columns = [
        column["name"]
        for column in inspector.get_columns(
            "vehicle_patrol"
        )
    ]

    for column_name, column_type in vehicle_patrol_columns:
        if column_name not in existing_vehicle_patrol_columns:
            db.session.execute(
                db.text(
                    f"ALTER TABLE vehicle_patrol "
                    f"ADD COLUMN {column_name} {column_type}"
                )
            )

    db.session.commit()

    if (
        "vehicle_id" in existing_vehicle_patrol_columns
        and "vehicle_id" in existing_columns
    ):
        db.session.execute(
            db.text(
                """
                UPDATE vehicle_patrol
                SET vehicle_record_id = (
                    SELECT vehicle.id
                    FROM vehicle
                    WHERE vehicle.company_code = vehicle_patrol.company_code
                      AND vehicle.vehicle_id = vehicle_patrol.vehicle_id
                )
                WHERE vehicle_record_id IS NULL
                  AND vehicle_id IS NOT NULL
                  AND vehicle_id != ''
                """
            )
        )

        db.session.commit()

    vehicle_checklist_notify_setting_columns = [
        ("vehicle_record_id", "INTEGER"),
    ]

    existing_vehicle_checklist_notify_setting_columns = [
        column["name"]
        for column in inspector.get_columns(
            "vehicle_checklist_notify_setting"
        )
    ]

    if (
        db.engine.dialect.name == "postgresql"
        and "vehicle_id" in existing_vehicle_checklist_notify_setting_columns
    ):
        db.session.execute(
            db.text(
                "ALTER TABLE vehicle_checklist_notify_setting "
                "ALTER COLUMN vehicle_id DROP NOT NULL"
            )
        )
        db.session.commit()

    for column_name, column_type in vehicle_checklist_notify_setting_columns:
        if column_name not in existing_vehicle_checklist_notify_setting_columns:
            db.session.execute(
                db.text(
                    f"ALTER TABLE vehicle_checklist_notify_setting "
                    f"ADD COLUMN {column_name} {column_type}"
                )
            )

    db.session.commit()

    if (
        "vehicle_id" in existing_vehicle_checklist_notify_setting_columns
        and "vehicle_id" in existing_columns
    ):
        db.session.execute(
            db.text(
                """
                UPDATE vehicle_checklist_notify_setting
                SET vehicle_record_id = (
                    SELECT vehicle.id
                    FROM vehicle
                    WHERE vehicle.company_code = vehicle_checklist_notify_setting.company_code
                      AND vehicle.vehicle_id = vehicle_checklist_notify_setting.vehicle_id
                )
                WHERE vehicle_record_id IS NULL
                  AND vehicle_id IS NOT NULL
                  AND vehicle_id != ''
                """
            )
        )

        db.session.commit()

    # =========================
    # News テナント分離
    # =========================

    inspector = inspect(db.engine)

    news_columns = [
        column["name"]
        for column in inspector.get_columns("news")
    ]

    if "company_code" not in news_columns:
        db.session.execute(
            db.text(
                "ALTER TABLE news "
                "ADD COLUMN company_code VARCHAR(50)"
            )
        )

        db.session.commit()

    # 既存のお知らせには会社情報が存在しないため、
    # 他社へ誤表示されないようITC所属として隔離する
    db.session.execute(
        db.text(
            "UPDATE news "
            "SET company_code = 'ITC' "
            "WHERE company_code IS NULL "
            "OR company_code = ''"
        )
    )

    db.session.commit()
    
    checklist_columns = [
        ("notify_users_json", "TEXT"),
        ("version_history_json", "TEXT"),
        (
            "active",
            "BOOLEAN NOT NULL DEFAULT TRUE"
        ),
        (
            "print_portrait",
            "BOOLEAN NOT NULL DEFAULT FALSE"
        ),
        (
            "print_half_month",
            "BOOLEAN NOT NULL DEFAULT FALSE"
        ),
                (
            "reminder_enabled",
            "BOOLEAN NOT NULL DEFAULT TRUE"
        ),
        (
            "reminder_time",
            "VARCHAR(5) NOT NULL DEFAULT '17:00'"
        ),
    ]

    existing_checklist_columns = [
        column["name"]
        for column in inspector.get_columns("checklist")
    ]

    for column_name, column_type in checklist_columns:
        if column_name not in existing_checklist_columns:
            db.session.execute(
                db.text(
                    f"ALTER TABLE checklist "
                    f"ADD COLUMN {column_name} {column_type}"
                )
            )

    checklist_result_columns = [
        ("approvals_json", "TEXT"),
        ("target_username", "VARCHAR(50)"),
        ("target_vehicle_record_id", "INTEGER"),
        ("checked_by_username", "VARCHAR(50)"),
        ("approved_by_username", "VARCHAR(50)"),
        ("checklist_snapshot_json", "TEXT"),
    ]

    existing_checklist_result_columns = [
        column["name"]
        for column in inspector.get_columns(
            "checklist_result"
        )
    ]

    for column_name, column_type in checklist_result_columns:
        if column_name not in existing_checklist_result_columns:
            db.session.execute(
                db.text(
                    f"ALTER TABLE checklist_result "
                    f"ADD COLUMN {column_name} {column_type}"
                )
            )

    db.session.commit()

    checklist_result_column_names = {
        column["name"]
        for column in inspector.get_columns(
            "checklist_result"
        )
    }

    vehicle_column_names = {
        column["name"]
        for column in inspector.get_columns(
            "vehicle"
        )
    }

    if (
        "target_vehicle" in checklist_result_column_names
        and "vehicle_id" in vehicle_column_names
    ):
        db.session.execute(
            db.text(
                """
                UPDATE checklist_result
                SET target_vehicle_record_id = (
                    SELECT vehicle.id
                    FROM vehicle
                    WHERE vehicle.company_code = checklist_result.company_code
                      AND vehicle.vehicle_id = checklist_result.target_vehicle
                )
                WHERE target_type = 'vehicle'
                  AND target_vehicle_record_id IS NULL
                  AND target_vehicle IS NOT NULL
                  AND target_vehicle != ''
                """
            )
        )

        db.session.commit()

    legacy_snapshot_results = (
        ChecklistResult.query.filter(
            db.or_(
                ChecklistResult.checklist_snapshot_json.is_(None),
                ChecklistResult.checklist_snapshot_json == ""
            )
        ).all()
    )

    for result in legacy_snapshot_results:
        checklist_record = Checklist.query.filter_by(
            id=result.checklist_id,
            company_code=result.company_code
        ).first()

        if not checklist_record:
            continue

        checklist = checklist_to_dict(checklist_record)

        checked_date = str(
            result.checked_date or ""
        )

        result_checklist = checklist_for_date(
            checklist,
            checked_date[:4],
            checked_date[5:7],
            checked_date[8:10]
        )

        result.checklist_snapshot_json = json.dumps(
            result_checklist,
            ensure_ascii=False
        )

    db.session.commit()

    legacy_checked_results = ChecklistResult.query.filter(
        db.or_(
            ChecklistResult.checked_by_username.is_(None),
            ChecklistResult.checked_by_username == ""
        ),
        ChecklistResult.checked_by.isnot(None),
        ChecklistResult.checked_by != ""
    ).all()

    for checklist_result in legacy_checked_results:
        checked_by_name = str(
            checklist_result.checked_by or ""
        ).strip()

        matched_users = User.query.filter_by(
            company_code=checklist_result.company_code,
            name=checked_by_name
        ).all()

        if len(matched_users) != 1:
            continue

        checklist_result.checked_by_username = (
            matched_users[0].username
        )

    db.session.commit()

    legacy_target_results = ChecklistResult.query.filter(
        ChecklistResult.target_type == "user",
        db.or_(
            ChecklistResult.target_username.is_(None),
            ChecklistResult.target_username == ""
        ),
        ChecklistResult.target_user.isnot(None),
        ChecklistResult.target_user != ""
    ).all()

    for checklist_result in legacy_target_results:
        target_name = str(
            checklist_result.target_user or ""
        ).strip()

        matched_users = User.query.filter_by(
            company_code=checklist_result.company_code,
            name=target_name
        ).all()

        if len(matched_users) != 1:
            continue

        checklist_result.target_username = (
            matched_users[0].username
        )

    db.session.commit()

    legacy_approved_results = ChecklistResult.query.filter(
        db.or_(
            ChecklistResult.approved_by_username.is_(None),
            ChecklistResult.approved_by_username == ""
        ),
        ChecklistResult.approved_by.isnot(None),
        ChecklistResult.approved_by != ""
    ).all()

    for checklist_result in legacy_approved_results:
        approved_by_name = str(
            checklist_result.approved_by or ""
        ).strip()

        matched_users = User.query.filter_by(
            company_code=checklist_result.company_code,
            name=approved_by_name
        ).all()

        if len(matched_users) != 1:
            continue

        checklist_result.approved_by_username = (
            matched_users[0].username
        )

    db.session.commit()

    legacy_approval_results = ChecklistResult.query.filter(
        ChecklistResult.approvals_json.isnot(None),
        ChecklistResult.approvals_json != ""
    ).all()

    for checklist_result in legacy_approval_results:
        approvals = safe_json_dict_list(
            checklist_result.approvals_json
        )

        changed = False

        for approval in approvals:
            if approval.get("approved_by_username"):
                continue

            approved_by_name = str(
                approval.get("approved_by") or ""
            ).strip()

            if not approved_by_name:
                continue

            matched_users = User.query.filter_by(
                company_code=checklist_result.company_code,
                name=approved_by_name
            ).all()

            if len(matched_users) != 1:
                continue

            approval["approved_by_username"] = (
                matched_users[0].username
            )
            changed = True

        if changed:
            checklist_result.approvals_json = json.dumps(
                approvals,
                ensure_ascii=False
            )

    db.session.commit()

    vehicle_checklist_result_columns = [
        ("notify_users_json", "TEXT"),
        ("approvals_json", "TEXT"),
        ("vehicle_record_id", "INTEGER"),
        ("checked_by_username", "VARCHAR(50)"),
        ("approved_by_username", "VARCHAR(50)"),
        ("checklist_snapshot_json", "TEXT"),
    ]

    existing_vehicle_checklist_result_columns = [
        column["name"]
        for column in inspector.get_columns(
            "vehicle_checklist_result"
        )
    ]

    for column_name, column_type in vehicle_checklist_result_columns:
        if column_name not in existing_vehicle_checklist_result_columns:
            db.session.execute(
                db.text(
                    f"ALTER TABLE vehicle_checklist_result "
                    f"ADD COLUMN {column_name} {column_type}"
                )
            )

    db.session.commit()

    vehicle_checklist_result_column_names = {
        column["name"]
        for column in inspector.get_columns(
            "vehicle_checklist_result"
        )
    }

    if (
        "vehicle_id" in vehicle_checklist_result_column_names
        and "vehicle_id" in vehicle_column_names
    ):
        db.session.execute(
            db.text(
                """
                UPDATE vehicle_checklist_result
                SET vehicle_record_id = (
                    SELECT vehicle.id
                    FROM vehicle
                    WHERE vehicle.company_code = vehicle_checklist_result.company_code
                      AND vehicle.vehicle_id = vehicle_checklist_result.vehicle_id
                )
                WHERE vehicle_record_id IS NULL
                  AND vehicle_id IS NOT NULL
                  AND vehicle_id != ''
                """
            )
        )

        db.session.commit()

    legacy_vehicle_snapshot_results = (
        VehicleChecklistResult.query.filter(
            db.or_(
                VehicleChecklistResult.checklist_snapshot_json.is_(None),
                VehicleChecklistResult.checklist_snapshot_json == ""
            )
        ).all()
    )

    for result in legacy_vehicle_snapshot_results:
        checklist_record = Checklist.query.filter_by(
            id=result.checklist_id,
            company_code=result.company_code
        ).first()

        if not checklist_record:
            continue

        checklist = checklist_to_dict(checklist_record)

        result_checklist = checklist_for_date(
            checklist,
            result.year,
            result.month,
            result.day
        )

        result.checklist_snapshot_json = json.dumps(
            result_checklist,
            ensure_ascii=False
        )

    db.session.commit()

    legacy_vehicle_checked_results = (
        VehicleChecklistResult.query.filter(
            db.or_(
                VehicleChecklistResult.checked_by_username.is_(None),
                VehicleChecklistResult.checked_by_username == ""
            ),
            VehicleChecklistResult.checked_by.isnot(None),
            VehicleChecklistResult.checked_by != ""
        ).all()
    )

    for result in legacy_vehicle_checked_results:
        checked_by_name = str(
            result.checked_by or ""
        ).strip()

        matched_users = User.query.filter_by(
            company_code=result.company_code,
            name=checked_by_name
        ).all()

        if len(matched_users) != 1:
            continue

        result.checked_by_username = (
            matched_users[0].username
        )

    legacy_vehicle_approved_results = (
        VehicleChecklistResult.query.filter(
            db.or_(
                VehicleChecklistResult.approved_by_username.is_(None),
                VehicleChecklistResult.approved_by_username == ""
            ),
            VehicleChecklistResult.approved_by.isnot(None),
            VehicleChecklistResult.approved_by != ""
        ).all()
    )

    for result in legacy_vehicle_approved_results:
        approved_by_name = str(
            result.approved_by or ""
        ).strip()

        matched_users = User.query.filter_by(
            company_code=result.company_code,
            name=approved_by_name
        ).all()

        if len(matched_users) != 1:
            continue

        result.approved_by_username = (
            matched_users[0].username
        )

    vehicle_approval_results = (
        VehicleChecklistResult.query.filter(
            VehicleChecklistResult.approvals_json.isnot(None),
            VehicleChecklistResult.approvals_json != ""
        ).all()
    )

    for result in vehicle_approval_results:
        approvals = safe_json_dict_list(
            result.approvals_json
        )

        changed = False

        for approval in approvals:
            if approval.get("approved_by_username"):
                continue

            approved_by_name = str(
                approval.get("approved_by") or ""
            ).strip()

            if not approved_by_name:
                continue

            matched_users = User.query.filter_by(
                company_code=result.company_code,
                name=approved_by_name
            ).all()

            if len(matched_users) != 1:
                continue

            approval["approved_by_username"] = (
                matched_users[0].username
            )
            changed = True

        if changed:
            result.approvals_json = json.dumps(
                approvals,
                ensure_ascii=False
            )

    db.session.commit()

    user_columns = [
        (
            "timezone",
            "VARCHAR(100) NOT NULL DEFAULT 'Asia/Tokyo'"
        ),
        (
            "email_address",
            "VARCHAR(255)"
        ),
        (
            "email_notify_enabled",
            "BOOLEAN NOT NULL DEFAULT FALSE"
        ),
                (
            "failed_login_count",
            "INTEGER NOT NULL DEFAULT 0"
        ),
        (
            "login_locked",
            "BOOLEAN NOT NULL DEFAULT FALSE"
        ),
                (
            "password_history_json",
            "TEXT NOT NULL DEFAULT '[]'"
        ),
                (
            "password_changed_at",
            "VARCHAR(20)"
        ),
                (
            "last_login_at",
            "VARCHAR(20)"
        ),
                (
            "mfa_code_hash",
            "VARCHAR(255)"
        ),
        (
            "mfa_code_expires_at",
            "VARCHAR(20)"
        ),
        (
            "mfa_code_sent_at",
            "VARCHAR(20)"
        ),
        (
            "pending_email_address",
            "VARCHAR(255)"
        ),
        (
            "email_change_code_hash",
            "VARCHAR(255)"
        ),
        (
            "email_change_code_expires_at",
            "VARCHAR(20)"
        ),
        ("dashboard_settings_json", "TEXT DEFAULT '{}'")
    ]

    existing_user_columns = [
        column["name"]
        for column in inspector.get_columns("user")
    ]

    for column_name, column_type in user_columns:
        if column_name not in existing_user_columns:
            db.session.execute(
                db.text(
                    f'ALTER TABLE "user" '
                    f"ADD COLUMN {column_name} {column_type}"
                )
            )

    db.session.commit()

    notification_columns = [
        ("company_code", "VARCHAR(50)"),
        ("target_username", "VARCHAR(50)"),
    ]

    inspector = inspect(db.engine)

    existing_patrol_result_columns = [
        column["name"]
        for column in inspector.get_columns(
            "patrol_result"
        )
    ]

    if (
        "target_username"
        not in existing_patrol_result_columns
    ):
        db.session.execute(
            db.text(
                "ALTER TABLE patrol_result "
                "ADD COLUMN target_username VARCHAR(50)"
            )
        )

        db.session.commit()
    if (
        "countermeasure_by_username"
        not in existing_patrol_result_columns
    ):
        db.session.execute(
            db.text(
                "ALTER TABLE patrol_result "
                "ADD COLUMN countermeasure_by_username VARCHAR(50)"
            )
        )

        db.session.commit()

    legacy_patrol_results = PatrolResult.query.filter(
        PatrolResult.target_type == "user",
        db.or_(
            PatrolResult.target_username.is_(None),
            PatrolResult.target_username == ""
        )
    ).all()

    for patrol_result in legacy_patrol_results:
        target_name = str(
            patrol_result.target_user or ""
        ).strip()

        if not target_name:
            continue

        matched_drivers = Driver.query.filter_by(
            company_code=patrol_result.company_code,
            name=target_name
        ).all()

        if len(matched_drivers) != 1:
            continue

        matched_user = User.query.filter_by(
            company_code=patrol_result.company_code,
            username=matched_drivers[0].employee_id
        ).first()

        if not matched_user:
            continue

        patrol_result.target_username = (
            matched_user.username
        )

    db.session.commit()

    legacy_countermeasure_results = PatrolResult.query.filter(
        db.or_(
            PatrolResult.countermeasure_by_username.is_(None),
            PatrolResult.countermeasure_by_username == ""
        ),
        PatrolResult.countermeasure_by.isnot(None),
        PatrolResult.countermeasure_by != ""
    ).all()

    for patrol_result in legacy_countermeasure_results:
        countermeasure_name = str(
            patrol_result.countermeasure_by or ""
        ).strip()

        matched_users = User.query.filter_by(
            company_code=patrol_result.company_code,
            name=countermeasure_name
        ).all()

        if len(matched_users) != 1:
            continue

        patrol_result.countermeasure_by_username = (
            matched_users[0].username
        )

    db.session.commit()

    existing_notification_columns = [
        column["name"]
        for column in inspector.get_columns(
            "notification"
        )
    ]

    for column_name, column_type in notification_columns:
        if column_name not in existing_notification_columns:
            db.session.execute(
                db.text(
                    f"ALTER TABLE notification "
                    f"ADD COLUMN {column_name} {column_type}"
                )
            )

        db.session.commit()

    legacy_notifications = Notification.query.filter(
        db.or_(
            Notification.target_username.is_(None),
            Notification.target_username == ""
        ),
        Notification.target_user.isnot(None),
        Notification.target_user != ""
    ).all()

    for notification in legacy_notifications:
        target_name = str(
            notification.target_user or ""
        ).strip()

        matched_users = User.query.filter_by(
            company_code=notification.company_code,
            name=target_name
        ).all()

        if len(matched_users) != 1:
            continue

        notification.target_username = (
            matched_users[0].username
        )

    db.session.commit()

init_db()


if __name__ == "__main__":
    app.run(debug=False)