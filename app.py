from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    send_file,
    url_for,
    flash,
    jsonify,
)
from markupsafe import escape
from werkzeug.utils import secure_filename, safe_join
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from uuid import uuid4
from daily_inspection_defaults import get_daily_inspection_default
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
import csv
import hashlib
from decimal import Decimal, InvalidOperation
from io import StringIO
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import NotFound, HTTPException
from botocore.exceptions import ClientError

from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import inspect, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.drawing.image import Image as ExcelImage
from io import BytesIO
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode
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
    if (
        request.headers.get("X-DKSS-Validation-Only") == "1"
        or request.headers.get("X-DKSS-Final-Submit") == "1"
    ):
        return return_form_errors(
            [
                (
                    "1回に送信できるファイルの合計は1GB以下です。",
                    ""
                )
            ],
            status_code=413
        )

    return return_form_errors(
        [
            (
                "1回に送信できるファイルの合計は1GB以下です。",
                ""
            )
        ],
        status_code=413
    )


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    if not session.get("username"):
        return redirect("/login")

    message = (
        "送信内容を確認できませんでした。"
        "画面を再読み込みして、もう一度お試しください。"
    )

    if (
        request.headers.get("X-DKSS-Validation-Only") == "1"
        or request.headers.get("X-DKSS-Final-Submit") == "1"
    ):
        return return_form_errors(
            [
                (
                    message,
                    ""
                )
            ],
            status_code=400
        )

    return return_form_errors(
        [
            (
                message,
                ""
            )
        ],
        status_code=400
    )


def return_form_errors(errors, status_code=400):
    if (
        request.headers.get("X-DKSS-Validation-Only") == "1"
        or request.headers.get("X-DKSS-Final-Submit") == "1"
    ):
        normalized_errors = []

        for error in errors:
            if (
                isinstance(error, (tuple, list))
                and len(error) == 2
            ):
                message, error_field = error
            else:
                message = error
                error_field = get_form_error_field(message)

            normalized_errors.append({
                "message": str(message) if isinstance(message, str) else "入力内容を確認してください。",
                "field": error_field or ""
            })

        response = jsonify({
            "errors": normalized_errors
        })
        response.status_code = status_code
        response.headers[
            "X-DKSS-Form-Errors"
        ] = "1"
        response.headers[
            "X-DKSS-Form-Error-Count"
        ] = str(len(normalized_errors))

        return response

    for error in errors:
        if (
            isinstance(error, (tuple, list))
            and len(error) == 2
        ):
            message, error_field = error
        else:
            message = error
            error_field = get_form_error_field(message)

        flash(
            message if isinstance(message, str) else "入力内容を確認してください。",
            f"error:{error_field or ''}"
        )

    response = app.make_response(
        ("", status_code)
    )
    response.headers[
        "X-DKSS-Form-Errors"
    ] = "1"

    return response


def checklist_form_data_to_dict(
    form_data,
    base_checklist=None
):
    if not form_data:
        return base_checklist

    checklist = dict(base_checklist or {})

    def first_value(key, default=""):
        values = form_data.get(key, [])

        if isinstance(values, list):
            return values[0] if values else default

        return values

    def list_values(key):
        values = form_data.get(key, [])

        if isinstance(values, list):
            return values

        return [values] if values else []

    item_types = list_values("item_type")
    item_categories = list_values("item_category")
    item_contents = list_values("item_content")
    input_types = list_values("input_type")
    choices_list = list_values("choices")
    criteria_list = list_values("criteria")
    approval_labels = list_values("approval_label")
    original_item_indexes = list_values(
        "original_item_index"
    )

    answer_required = {
        str(value)
        for value in list_values("answer_required")
    }
    shaded = {
        str(value)
        for value in list_values("shaded")
    }
    approval_allow_general = {
        str(value)
        for value in list_values(
            "approval_allow_general"
        )
    }

    old_items = (
        base_checklist.get("items", [])
        if base_checklist
        else []
    )

    items = []

    for i, item_type in enumerate(item_types):
        criteria_files = []

        if i < len(original_item_indexes):
            original_index = str(
                original_item_indexes[i] or ""
            ).strip()

            if original_index.isdigit():
                old_index = int(original_index)

                if 0 <= old_index < len(old_items):
                    criteria_files = list(
                        old_items[old_index].get(
                            "criteria_files",
                            []
                        )
                    )

        choices_text = (
            choices_list[i]
            if i < len(choices_list)
            else ""
        )

        items.append({
            "item_type": item_type,
            "category": (
                item_categories[i]
                if i < len(item_categories)
                else ""
            ),
            "content": (
                item_contents[i]
                if i < len(item_contents)
                else ""
            ),
            "input_type": (
                input_types[i]
                if i < len(input_types)
                else "select"
            ),
            "choices": [
                choice.strip()
                for choice in str(
                    choices_text or ""
                ).split(",")
                if choice.strip()
            ],
            "criteria": (
                criteria_list[i]
                if i < len(criteria_list)
                else ""
            ),
            "criteria_files": criteria_files,
            "answer_required": (
                str(i) in answer_required
            ),
            "shaded": str(i) in shaded,
            "approval_label": (
                approval_labels[i]
                if i < len(approval_labels)
                else ""
            ),
            "approval_allow_general": (
                str(i) in approval_allow_general
            ),
            "score_enabled": (
                first_value("score_enabled") == "1"
            ),
        })

    checklist.update({
        "name": first_value("name"),
        "target": first_value(
            "target",
            "安全管理"
        ),
        "frequency_value": first_value(
            "frequency_value"
        ),
        "frequency_unit": first_value(
            "frequency_unit"
        ),
        "display_type": first_value(
            "display_type"
        ),
        "print_portrait": (
            first_value("print_portrait") == "1"
        ),
        "print_half_month": (
            first_value("print_half_month") == "1"
        ),
        "reminder_enabled": (
            first_value("reminder_enabled") == "1"
        ),
        "reminder_time": first_value(
            "reminder_time",
            "08:00"
        ),
        "score_enabled": (
            first_value("score_enabled") == "1"
        ),
        "items": items,
    })

    return checklist


def get_form_error_field(message):
    field_map = {
        "発生日を入力してください。": "event_date",
        "発生日が不正です。": "event_date",
        "分類が不正です。": "category",
        "内容区分が不正です。": "content_type",
        "対象ユーザーを選択してください。": "target_user_search",
        "対象ユーザーが不正です。": "target_user_search",
        "対象ユーザー情報が不正です。": "target_user_search",
        "納入先を選択してください。": "delivery_place",
        "納入先が不正です。": "delivery_place",
        "内容は5000文字以内で入力してください。": "content_editor",
        "対策内容を入力してください。": "countermeasure",
        "対策内容は5000文字以内で入力してください。": "countermeasure",
        "対応者を選択してください。": "countermeasure_by_search",
        "対応者が不正です。": "countermeasure_by_search",
        "対応者情報が不正です。": "countermeasure_by_search",
        "対応期限が不正です。": "countermeasure_due_date",
        "差し戻し理由を入力してください。": "reject_reason",
        "差し戻し理由は5000文字以内で入力してください。": "reject_reason",
        "車台番号を入力してください。": "chassis_number",
        "同じ車台番号の車両が既に登録されています。": "chassis_number",
        "車両が不正です。": "vehicle_record_id",
        "ログインIDを入力してください。": "employee_id",
        "ログインIDは50文字以内で入力してください。": "employee_id",
        "このログインIDはすでに使用されています。": "employee_id",
        "ログインIDは作成後に変更できません。": "employee_id",
        "姓を入力してください。": "last_name",
        "姓は100文字以内で入力してください。": "last_name",
        "名は100文字以内で入力してください。": "first_name",
        "メールアドレスの形式が不正です。": "email_address",
        "パスワードを入力してください。": "password",
        "パスワードは8文字以上にしてください。": "password",
        "パスワードは128文字以内にしてください。": "password",
        "パスワードは英大文字・英小文字・数字・記号のうち3種類以上を使用してください。": "password",
        "ユーザー種別が不正です。": "role",
        "営業所が不正です。": "office",
        "無事故開始日が不正です。": "safe_start_date",
        "選択車両数が多すぎます。": "selected_vehicles",
        "免許種別が不正です。": "license_area",
        "免許有効期限が不正です。": "license_area",
        "初年度登録日が不正です。": "first_registration_date",
        "車検満了日が不正です。": "inspection_expiry",
        "車種が不正です。": "type",
        "車番・地域名は50文字以内で入力してください。": "plate_area",
        "車番・分類は50文字以内で入力してください。": "plate_class",
        "車番・ひらがなは10文字以内で入力してください。": "plate_kana",
        "車番は50文字以内で入力してください。": "plate_number",
        "車台番号は100文字以内で入力してください。": "chassis_number",
        "車体型式は100文字以内で入力してください。": "model_code",
        "車両メーカーは100文字以内で入力してください。": "manufacturer",
        "車両形状は100文字以内で入力してください。": "body_type",
        "車両総重量は整数で入力してください。": "gross_vehicle_weight",
        "車両総重量は0以上で入力してください。": "gross_vehicle_weight",
        "車両総重量の値が大きすぎます。": "gross_vehicle_weight",
        "最大積載量は整数で入力してください。": "max_payload",
        "最大積載量は0以上で入力してください。": "max_payload",
        "最大積載量の値が大きすぎます。": "max_payload",
        "会社コードを入力してください。": "company_code",
        "会社コードは50文字以内で入力してください。": "company_code",
        "会社コードは半角英数字・ハイフン・アンダースコアのみ使用できます。": "company_code",
        "この会社コードはすでに登録されています。": "company_code",
        "会社名を入力してください。": "company_name",
        "会社名は100文字以内で入力してください。": "company_name",
        "車両上限数は整数で入力してください。": "vehicle_limit",
        "車両上限数は0以上で入力してください。": "vehicle_limit",
        "車両上限数の値が大きすぎます。": "vehicle_limit",
        "通知対象が不正です。": "target_type",
        "タイトルを入力してください。": "title",
        "タイトルは200文字以内で入力してください。": "title",
        "本文は10000文字以内で入力してください。": "message_editor",
        "チェックリスト名を入力してください。": "name",
        "チェックリスト名は200文字以内で入力してください。": "name",
        "このチェックリストはすでに登録されています。": "name",
        "用途が不正です。": "target",
        "頻度は整数で入力してください。": "frequency_value",
        "頻度は1以上で入力してください。": "frequency_value",
        "頻度は9999以下で入力してください。": "frequency_value",
        "頻度単位が不正です。": "frequency_unit",
        "表示形式が不正です。": "display_type",
        "未実施通知時刻の形式が不正です。": "reminder_time",
        "重要度が不正です。": "priority",
        "状態が不正です。": "status",
        "修理担当者は100文字以内で入力してください。": "repair_person",
        "修理時間の形式が不正です。": "repair_time",
        "修理費用が不正です。": "cost",
        "修理費用は50文字以内で入力してください。": "cost",
        "修理費用は0以上で入力してください。": "cost",
    }

    if (
        request.path.startswith("/itc/news")
        and message in {
            "対象会社が不正です。",
            "対象営業所が不正です。",
            "対象ユーザーが不正です。",
        }
    ):
        return "newsTargetSearch"

    return field_map.get(message)


def is_html_document_request():
    if request.path.startswith("/api/"):
        return False

    if request.is_json:
        return False

    fetch_dest = request.headers.get(
        "Sec-Fetch-Dest",
        ""
    ).lower()

    if fetch_dest:
        return fetch_dest == "document"

    fetch_mode = request.headers.get(
        "Sec-Fetch-Mode",
        ""
    ).lower()

    if fetch_mode:
        return fetch_mode == "navigate"

    accept_header = request.headers.get(
        "Accept",
        ""
    ).lower()

    return "text/html" in accept_header


def build_safe_redirect_url(referrer, fallback="/"):
    if not referrer:
        return fallback

    normalized_referrer = referrer.replace("\\", "/")
    parsed_referrer = urlparse(normalized_referrer)

    if parsed_referrer.scheme and parsed_referrer.scheme not in {"http", "https"}:
        return fallback

    resolved_target = urlparse(urljoin(request.host_url, normalized_referrer))

    current_host = request.host.lower()
    resolved_host = resolved_target.hostname or ""
    if resolved_target.port:
        resolved_host = f"{resolved_host}:{resolved_target.port}"
    resolved_host = resolved_host.lower()

    if resolved_host != current_host:
        return fallback

    redirect_path = resolved_target.path or "/"
    if not redirect_path.startswith("/"):
        return fallback

    if resolved_target.query:
        return redirect_path + "?" + resolved_target.query

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
        500,
    }:
        return response

    if not is_html_document_request():
        return response

    message = response.get_data(
        as_text=True
    ).strip()

    form_errors_already_flashed = (
        response.headers.get(
            "X-DKSS-Form-Errors"
        ) == "1"
    )

    if not message and not form_errors_already_flashed:
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

    elif request.path.endswith("/countermeasure"):
        session["countermeasure_form_data"] = {
            "countermeasure": request.form.get(
                "countermeasure",
                ""
            ),
            "countermeasure_by": request.form.get(
                "countermeasure_by",
                ""
            ),
            "countermeasure_by_search": request.form.get(
                "countermeasure_by_search",
                ""
            ),
            "countermeasure_by_username": request.form.get(
                "countermeasure_by_username",
                ""
            ),
            "countermeasure_due_date": request.form.get(
                "countermeasure_due_date",
                ""
            ),
        }

    elif (
        request.path.startswith("/pointouts/")
        and request.path.endswith("/edit")
    ):
        session["pointout_edit_form_data"] = {
            "date": request.form.get("date", ""),
            "category": request.form.get("category", ""),
            "target_user": request.form.get("target_user", ""),
            "target_user_search": request.form.get(
                "target_user_search",
                ""
            ),
            "delivery_place": request.form.get(
                "delivery_place",
                ""
            ),
            "content_type": request.form.get(
                "content_type",
                ""
            ),
            "content": request.form.get("content", ""),
        }

    elif request.path.endswith("/reject"):
        session["pointout_reject_form_data"] = {
            "reject_reason": request.form.get(
                "reject_reason",
                ""
            ),
        }

    elif request.path == "/master/drivers/new":
        driver_form_data = request.form.to_dict(
            flat=True
        )
        driver_form_data.pop("password", None)

        session["driver_form_data"] = {
            **driver_form_data,
            "vehicles": request.form.getlist("vehicles"),
            "license_type": request.form.getlist(
                "license_type"
            ),
            "license_expiry": request.form.getlist(
                "license_expiry"
            ),
        }

    elif (
        request.path.startswith("/master/drivers/")
        and request.path.endswith("/edit")
    ):
        driver_form_data = request.form.to_dict(
            flat=True
        )
        driver_form_data.pop("password", None)

        session["driver_edit_form_data"] = {
            **driver_form_data,
            "vehicles": request.form.getlist("vehicles"),
            "license_type": request.form.getlist(
                "license_type"
            ),
            "license_expiry": request.form.getlist(
                "license_expiry"
            ),
        }

    elif request.path == "/master/vehicles/new":
        session["vehicle_form_data"] = request.form.to_dict(
            flat=True
        )

    elif (
        request.path.startswith("/master/vehicles/")
        and request.path.endswith("/edit")
    ):
        session["vehicle_edit_form_data"] = request.form.to_dict(
            flat=True
        )

    elif request.path == "/master/checklists/new":
        session["checklist_form_data"] = request.form.to_dict(
            flat=False
        )

    elif (
        request.path.startswith("/master/checklists/")
        and request.path.endswith("/edit")
    ):
        session["checklist_edit_form_data"] = request.form.to_dict(
            flat=False
        )

    if not form_errors_already_flashed:
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
    app.logger.warning(
        "アップロード検証エラー: %s",
        error
    )

    if (
        request.headers.get("X-DKSS-Validation-Only") == "1"
        or request.headers.get("X-DKSS-Final-Submit") == "1"
    ):
        return return_form_errors(
            [
                (
                    str(error)
                    or "アップロード内容を確認してください。",
                    ""
                )
            ],
            status_code=400
        )

    return "アップロード内容を確認してください。", 400


@app.errorhandler(HTTPException)
def handle_http_error(error):
    if error.code == 500:
        db.session.rollback()

    if not is_html_document_request():
        return error

    error_messages = {
        400: "入力内容を確認してください。",
        401: "ログインが必要です。",
        403: "この操作を行う権限がありません。",
        404: "ページが見つかりません。",
        405: "この操作は利用できません。",
        409: "処理を完了できませんでした。最新の状態を確認してください。",
        413: "1回に送信できるファイルの合計は1GB以下です。",
        429: "操作回数が多すぎます。少し待ってからもう一度お試しください。",
    }

    flash(
        error_messages.get(
            error.code,
            "処理中にエラーが発生しました。"
        ),
        "error:"
    )

    return redirect(
        build_safe_redirect_url(
            request.referrer,
            "/"
        )
    )

@app.errorhandler(Exception)
def handle_unexpected_error(error):
    db.session.rollback()

    if isinstance(error, HTTPException):
        return handle_http_error(error)

    app.logger.exception(
        "予期しないエラーが発生しました。"
    )

    if not is_html_document_request():
        if (
            request.path.startswith("/api/")
            or request.path == "/notifications/email-test"
        ):
            return {
                "ok": False,
                "message": "処理中にエラーが発生しました。"
            }, 500

        return "処理中にエラーが発生しました。", 500

    flash(
        "処理中にエラーが発生しました。もう一度お試しください。",
        "error:"
    )

    return redirect(
        build_safe_redirect_url(
            request.referrer,
            "/"
        )
    )


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
    source_file = db.Column(
        db.LargeBinary,
        nullable=False
    )
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
            return header.startswith(
                b"\x89PNG\r\n\x1a\n"
            )

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
        1
        for field_name in request.files.keys()
        for file in request.files.getlist(field_name)
        if file and file.filename
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


def delete_uploaded_file(filename, folder=None):
    company_code = session.get("company_code")

    if not company_code or not filename:
        return

    filename = os.path.basename(str(filename))

    if not filename:
        return

    if folder == "static/manuals":
        storage_folder = "manuals"
        base_folder = "static/manuals"
    else:
        storage_folder = "uploads"
        base_folder = app.config["UPLOAD_FOLDER"]

    if s3_client and S3_BUCKET_NAME:
        try:
            s3_client.delete_object(
                Bucket=S3_BUCKET_NAME,
                Key=(
                    f"{storage_folder}/"
                    f"{company_code}/"
                    f"{filename}"
                )
            )
        except ClientError:
            app.logger.exception(
                "アップロード済みファイルの削除に失敗しました。"
            )
        return

    safe_company_code = secure_filename(
        str(company_code)
    )
    safe_filename = secure_filename(
        filename
    )

    if (
        not safe_company_code
        or safe_company_code != company_code
        or not safe_filename
        or safe_filename != filename
    ):
        return

    file_path = safe_join(
        base_folder,
        safe_company_code,
        safe_filename
    )

    if file_path and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError:
            app.logger.exception(
                "アップロード済みファイルの削除に失敗しました。"
            )


def file_belongs_to_current_company(filename, folder="uploads"):
    company_code = session.get("company_code")

    if not company_code or not filename:
        return False

    filename = os.path.basename(filename)

    # =========================
    # プロフィール画像
    # =========================
    current_user = User.query.filter_by(
        company_code=company_code,
        username=session.get("username")
    ).first()

    if (
        current_user
        and current_user.profile_image == filename
    ):
        return True

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
    # チェックリスト評価基準添付
    # =========================
    checklist_records = Checklist.query.filter_by(
        company_code=company_code
    ).all()

    for checklist_record in checklist_records:
        checklist = checklist_to_dict(checklist_record)

        if any(
            filename in item.get(
                "criteria_files",
                []
            )
            for item in checklist.get(
                "items",
                []
            )
        ):
            return True

        for version in checklist.get(
            "version_history",
            []
        ):
            snapshot = version.get(
                "snapshot",
                {}
            )

            if any(
                filename in item.get(
                    "criteria_files",
                    []
                )
                for item in snapshot.get(
                    "items",
                    []
                )
            ):
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

        countermeasure_files = safe_json_str_list(
            patrol.countermeasure_files_json
        )

        if filename in countermeasure_files:
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

        judgment = safe_json_dict(result.operation_judgment_json)
        defects = judgment.get("defects") or []
        if not isinstance(defects, list):
            continue

        for defect in defects:
            if not isinstance(defect, dict):
                continue

            reported_answer = defect.get("reported_answer") or {}
            if not isinstance(reported_answer, dict):
                continue

            reported_files = reported_answer.get("files") or []
            if (
                isinstance(reported_files, list)
                and filename in reported_files
            ):
                return True

    maintenance_records = VehicleMaintenanceRecord.query.filter_by(
        company_code=company_code
    ).all()

    for record in maintenance_records:
        if filename in safe_json_str_list(record.files_json):
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
                s3_object = s3_client.get_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=object_key
                )

                file_buffer = BytesIO(
                    s3_object["Body"].read()
                )

                return send_file(
                    file_buffer,
                    mimetype=s3_object.get(
                        "ContentType",
                        "application/octet-stream"
                    ),
                    download_name=filename,
                    max_age=0
                )

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
        "unsafe-none"
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
        session["name"] = (
            f"{current_user.last_name or ''}"
            f"{current_user.first_name or ''}"
        )
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
            "login_csrf_token",
            "mfa",
            "register",
            "static",
            "service_worker"
        }
        or request.endpoint is None
    ):
        return None

    if not session.get("username"):
        if (
            request.path.startswith("/api/")
            or request.path == "/notifications/email-test"
        ):
            return {
                "ok": False,
                "message": "ログインが必要です。"
            }, 401

        return redirect("/login")

    current_user = User.query.filter_by(
        company_code=session.get("company_code"),
        username=session.get("username")
    ).first()

    if not current_user or current_user.login_locked:
        session.clear()

        if (
            request.path.startswith("/api/")
            or request.path == "/notifications/email-test"
        ):
            return {
                "ok": False,
                "message": "ログインが必要です。"
            }, 401

        return redirect("/login")

    if (
        session.get("password_changed_at")
        != current_user.password_changed_at
    ):
        session.clear()

        if (
            request.path.startswith("/api/")
            or request.path == "/notifications/email-test"
        ):
            return {
                "ok": False,
                "message": "ログインが必要です。"
            }, 401

        return redirect("/login")

    session["role"] = current_user.role
    session["name"] = (
        f"{current_user.last_name or ''}"
        f"{current_user.first_name or ''}"
    )
    session["office"] = current_user.office
    session["profile_image"] = current_user.profile_image

    if current_user.role != "itc":
        current_company = Company.query.filter_by(
            company_code=current_user.company_code
        ).first()

        if not current_company or not current_company.active:
            session.clear()

            if (
                request.path.startswith("/api/")
                or request.path == "/notifications/email-test"
            ):
                return {
                    "ok": False,
                    "message": "この会社では現在システムを利用できません。"
                }, 403

            return redirect("/login")
        
    if (
        session.get("password_expired")
        and request.endpoint not in {
            "settings",
            "logout"
        }
    ):
        if (
            request.path.startswith("/api/")
            or request.path == "/notifications/email-test"
        ):
            return {
                "ok": False,
                "message": "パスワードの変更が必要です。"
            }, 403

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
        "number": (
            " ".join(
                value
                for value in [
                    vehicle.plate_area or "",
                    vehicle.plate_class or "",
                    vehicle.plate_kana or "",
                    vehicle.plate_number or "",
                ]
                if value
            )
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

def ensure_daily_inspection_checklist():
    company_code = session.get("company_code")
    template = get_daily_inspection_default()

    company = Company.query.filter_by(
        company_code=company_code
    ).with_for_update().first()

    if not company:
        raise ValueError("会社情報を確認できません。")

    existing_checklist = None

    for checklist in Checklist.query.filter_by(
        company_code=company_code,
        target="車両管理"
    ).all():
        items = safe_json_dict_list(checklist.items_json)

        if items and items[0].get("fixed_template_code") == template["template_code"]:
            existing_checklist = checklist
            break

    items = []

    for source in template["items"]:
        item = dict(source)
        item.update({
            "answer_required": False,
            "comment_required": False,
            "score_enabled": False,
            "criteria_files": []
        })
        items.append(item)

    for field in template["footer_fields"]:
        item = {
            "item_type": field["field_type"],
            "item_code": f"footer_{field['order']}",
            "category": "",
            "content": field["label"]
        }

        if field["field_type"] == "check":
            item.update({
                "input_type": "select",
                "choices": list(field["choices"]),
                "criteria": template["criteria"],
                "answer_required": False,
                "comment_required": False,
                "score_enabled": False,
                "criteria_files": [],
                "shaded": False
            })

        if field["field_type"] == "approval":
            item["approval_label"] = field["label"]
            item["approval_allow_general"] = False

        items.append(item)

    items[0]["fixed_template_code"] = template["template_code"]
    items[0]["fixed_template_version"] = template["template_version"]

    if existing_checklist:
        if safe_json_dict_list(existing_checklist.items_json) != items:
            existing_checklist.items_json = json.dumps(items, ensure_ascii=False)
            db.session.flush()
        return existing_checklist

    checklist = Checklist(
        company_code=company_code,
        name=template["name"],
        target="車両管理",
        frequency_value="1",
        frequency_unit="day",
        display_type="month",
        print_portrait=False,
        print_half_month=template["print_half_month"],
        reminder_enabled=False,
        reminder_time="08:00",
        active=True,
        items_json=json.dumps(items, ensure_ascii=False),
        version_history_json="[]",
        notify_users_json="[]"
    )

    db.session.add(checklist)
    db.session.flush()

    return checklist


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
        "fixed_template_code": (
            items[0].get("fixed_template_code", "")
            if items
            else ""
        ),
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

def vehicle_checklist_result_to_dict(result):
    return {
        "id": result.id,
        "index": result.id,
        "company_code": result.company_code,
        "checklist_id": result.checklist_id,
        "vehicle_record_id": result.vehicle_record_id,
        "operation_judgment": safe_json_dict(result.operation_judgment_json),
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
        full_name = (
            f"{user.last_name or ''}"
            f"{user.first_name or ''}"
        )

        if not full_name or not user.username:
            continue

        usernames_by_name.setdefault(
            full_name,
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
                    (
                        f"{target_user.last_name or ''}"
                        f"{target_user.first_name or ''}"
                    ),
                    title,
                    (
                        f"{checklist.name}："
                        f"車両 {' '.join(value for value in [vehicle.plate_area or '', vehicle.plate_class or '', vehicle.plate_kana or '', vehicle.plate_number or ''] if value) or 'ナンバー未登録'} の"
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
        "countermeasure_files": safe_json_str_list(
            result.countermeasure_files_json
        ),
        "countermeasure_by": result.countermeasure_by,
        "countermeasure_by_username": (
            result.countermeasure_by_username
        ),
        "countermeasure_due_date": (
            result.countermeasure_due_date
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

    unread_count = Notification.query.filter(
        Notification.company_code == user.company_code,
        Notification.target_username == user.username,
        Notification.deleted_at.is_(None),
        db.or_(
            Notification.read.is_(False),
            Notification.read.is_(None)
        )
    ).count()

    payload = json.dumps(
        {
            "title": str(title or "")[:200],
            "message": str(message or "")[:10000],
            "link": build_absolute_app_url(link),
            "unread_count": unread_count,
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
            app.logger.warning(
                "Web Push送信エラー: %s",
                e
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

        except Exception:
            app.logger.exception(
                "Web Push送信中に予期しないエラーが発生しました。"
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

    except Exception:
        app.logger.exception(
            "メール通知送信中に予期しないエラーが発生しました。"
        )
        return False
def dispatch_external_notification(
    user,
    title,
    message,
    link="",
    notification_id=None
):
    if not user:
        return

    push_link = link

    if notification_id is not None:
        if str(link or "").strip():
            push_link = f"/notifications/{notification_id}/open"
        else:
            push_link = f"/notifications/{notification_id}"

    send_web_push_notification(
        user,
        title,
        message,
        push_link
    )

    if user.email_notify_enabled:
        send_email_notification(
            user,
            title,
            message,
            link
        )

def build_notification_workflow_context(
    result_record,
    result_type,
    action,
    approval_index=None
):
    latest_event = ChecklistEvent.query.filter_by(
        company_code=result_record.company_code,
        result_type=result_type,
        result_id=result_record.id
    ).order_by(
        ChecklistEvent.id.desc()
    ).first()

    context = {
        "result_type": result_type,
        "result_id": result_record.id,
        "action": action,
        "event_id": latest_event.id if latest_event else 0,
    }

    if approval_index is not None:
        context["approval_index"] = approval_index

    return context

def add_notification(
    target_user,
    title,
    message,
    link="",
    files=None,
    company_code=None,
    target_username=None,
    workflow_context=None
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

        target_user = (
            f"{target_user_record.last_name or ''}"
            f"{target_user_record.first_name or ''}"
        )
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
        workflow_context_json=json.dumps(
            workflow_context
            if isinstance(workflow_context, dict)
            else {},
            ensure_ascii=False
        ),
        read=False,
        created_at=datetime.now(ZoneInfo("UTC")).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    )

    db.session.add(notification)
    db.session.commit()

    if target_user_record:
        dispatch_external_notification(
            target_user_record,
            title,
            message,
            link,
            notification_id=notification.id
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
        full_name = (
            f"{user.last_name or ''}"
            f"{user.first_name or ''}"
        )

        if not full_name or not user.username:
            continue

        users_by_name.setdefault(
            full_name,
            []
        ).append(user)

    notified_usernames = set()

    for user in users:
        name = (
            f"{user.last_name or ''}"
            f"{user.first_name or ''}"
        )
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
    if not is_same_company_result(result):
        return False

    if not approval:
        return False

    approval_user = User.query.filter_by(
        company_code=result.get("company_code"),
        username=session.get("username")
    ).first()

    if not approval_user:
        return False

    if approval_user.role == "admin":
        return True

    return (
        approval.get("allow_general", False)
        and approval_user.role == "user"
    )


def can_reject_checklist_result(result, approval=None):
    if not is_same_company_result(result):
        return False

    if not approval:
        return False

    approval_user = User.query.filter_by(
        company_code=result.get("company_code"),
        username=session.get("username")
    ).first()

    if not approval_user:
        return False

    if approval_user.role == "admin":
        return True

    return (
        approval.get("allow_general", False)
        and approval_user.role == "user"
    )

def vehicle_number(vehicle):
    return (
        vehicle.get("number")
        or (
            f"{vehicle.get('plate_area', '')} "
            f"{vehicle.get('plate_class', '')} "
            f"{vehicle.get('plate_kana', '')} "
            f"{vehicle.get('plate_number', '')}"
        ).strip()
        or "ナンバー未登録"
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

@app.template_filter("vehicle_icon")
def vehicle_icon(vehicle_type="", body_type=""):
    import unicodedata

    def normalize(value):
        text = unicodedata.normalize(
            "NFKC",
            str(value or "")
        ).casefold()

        text = "".join(
            chr(ord(char) + 0x60)
            if "\u3041" <= char <= "\u3096"
            else char
            for char in text
        )

        return "".join(
            char
            for char in text
            if char.isalnum()
        )

    rules = [
        (
            "tractor.png",
            (
                "トラクタ",
                "トレーラーヘッド",
                "トレーラヘッド",
                "ヘッド",
                "tractor",
                "prime mover",
            )
        ),
        (
            "trailer.png",
            (
                "トレーラ",
                "トレイラ",
                "被牽引",
                "被けん引",
                "trailer",
            )
        ),
        (
            "crane.png",
            (
                "クレーン",
                "ユニック",
                "crane",
                "unic",
            )
        ),
        (
            "flatbed.png",
            (
                "平ボディ",
                "平ボデー",
                "平車",
                "フラットベッド",
                "flatbed",
            )
        ),
        (
            "car.png",
            (
                "乗用",
                "普通車",
                "軽乗用",
                "セダン",
                "passenger car",
                "sedan",
                "suv",
            )
        ),
    ]

    for value in (vehicle_type, body_type):
        text = normalize(value)

        if not text:
            continue

        for filename, aliases in rules:
            if any(
                normalize(alias) in text
                for alias in aliases
            ):
                return filename

    return "truck.png"


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

    except Exception:
        app.logger.exception(
            "メールアドレス変更確認メール送信中に予期しないエラーが発生しました。"
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

@app.route("/login/csrf-token", methods=["GET"])
def login_csrf_token():
    from flask_wtf.csrf import generate_csrf

    response = jsonify({
        "csrf_token": generate_csrf()
    })
    response.headers["Cache-Control"] = "no-store"
    return response


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
                session["name"] = (
                    f"{user.last_name or ''}"
                    f"{user.first_name or ''}"
                )
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
                session["name"] = (
                    f"{user.last_name or ''}"
                    f"{user.first_name or ''}"
                )
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
        form_errors = []
        form_error_status = 400

        title = request.form.get("title", "").strip()
        message = request.form.get("message", "")

        if not title:
            form_errors.append((
                "タイトルを入力してください。",
                "title"
            ))
        elif len(title) > 200:
            form_errors.append((
                "タイトルは200文字以内で入力してください。",
                "title"
            ))

        if len(message) > 10000:
            form_errors.append((
                "本文は10000文字以内で入力してください。",
                "message_editor"
            ))

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
                form_errors.append((
                    "対象会社が不正です。",
                    "target_company"
                ))
                form_error_status = 403
            else:
                target_users = user_query.all()

        elif target_type == "office":
            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=target_value
            ).first()

            if not valid_office:
                form_errors.append((
                    "対象営業所が不正です。",
                    "target_office"
                ))
                form_error_status = 403
            else:
                target_users = user_query.filter_by(
                    office=target_value
                ).all()

        elif target_type == "user":
            target_user = User.query.filter_by(
                company_code=company_code,
                username=target_value
            ).first()

            if not target_user:
                form_errors.append((
                    "対象ユーザーが不正です。",
                    "target_user_search"
                ))
                form_error_status = 403
            else:
                target_users = [target_user]

        else:
            form_errors.append((
                "通知対象が不正です。",
                "target_type"
            ))

        if form_errors:
            return return_form_errors(
                form_errors,
                form_error_status
            )

        file_names = []

        uploaded_files = [
            file
            for file in request.files.getlist("files")
            if file and file.filename
        ]

        for file in uploaded_files:
            original_filename = os.path.basename(
                str(file.filename or "")
            )

            extension = os.path.splitext(
                original_filename
            )[1].lower()

            if (
                extension not in ALLOWED_UPLOAD_EXTENSIONS
                or not is_valid_uploaded_file(
                    file,
                    extension
                )
            ):
                return "添付ファイルの検証に失敗しました。", 400

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
                (
                    f"{user.last_name or ''}"
                    f"{user.first_name or ''}"
                ),
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
        form_errors = []
        form_error_status = 400

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
                form_errors.append((
                    "対象会社が不正です。",
                    "target_company"
                ))
                form_error_status = 403

        elif target_type == "office":
            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=target_value
            ).first()

            if not valid_office:
                form_errors.append((
                    "対象営業所が不正です。",
                    "target_office"
                ))
                form_error_status = 403

        elif target_type == "user":
            valid_user = User.query.filter_by(
                company_code=company_code,
                username=target_value
            ).first()

            if not valid_user:
                form_errors.append((
                    "対象ユーザーが不正です。",
                    "target_user_search"
                ))
                form_error_status = 403

        elif target_type not in [
            "all",
            "admins"
        ]:
            form_errors.append((
                "通知対象が不正です。",
                "target_type"
            ))

        title = request.form.get("title", "").strip()
        message = request.form.get("message", "")

        if not title:
            form_errors.append((
                "タイトルを入力してください。",
                "title"
            ))
        elif len(title) > 200:
            form_errors.append((
                "タイトルは200文字以内で入力してください。",
                "title"
            ))

        if len(message) > 10000:
            form_errors.append((
                "本文は10000文字以内で入力してください。",
                "message_editor"
            ))

        if form_errors:
            return return_form_errors(
                form_errors,
                form_error_status
            )

        files = safe_json_str_list(
            news.files_json
        )

        uploaded_files = [
            file
            for file in request.files.getlist(
                "files"
            )
            if file and file.filename
        ]

        for file in uploaded_files:
            original_filename = os.path.basename(
                str(file.filename or "")
            )

            extension = os.path.splitext(
                original_filename
            )[1].lower()

            if (
                extension not in ALLOWED_UPLOAD_EXTENSIONS
                or not is_valid_uploaded_file(
                    file,
                    extension
                )
            ):
                return "添付ファイルの検証に失敗しました。", 400

        for file in uploaded_files:
            filename = save_uploaded_file(file)

            if filename:
                files.append(filename)

        news.title = title
        news.message = message
        news.target_type = target_type
        news.target_value = target_value

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

    files_to_delete = safe_json_str_list(
        news.files_json
    )

    db.session.delete(news)
    db.session.commit()

    for filename in files_to_delete:
        filename = os.path.basename(
            str(filename or "")
        )

        if not filename:
            continue

        still_referenced = False

        notification_records = Notification.query.filter_by(
            company_code=company_code
        ).all()

        for notification in notification_records:
            notification_files = safe_json_str_list(
                notification.files_json
            )

            if filename in notification_files:
                still_referenced = True
                break

        if still_referenced:
            continue

        if s3_client and S3_BUCKET_NAME:
            try:
                s3_client.delete_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=(
                        f"uploads/"
                        f"{company_code}/"
                        f"{filename}"
                    )
                )
            except ClientError:
                app.logger.warning(
                    "お知らせ添付ファイルのS3削除に失敗しました。",
                    exc_info=True
                )
        else:
            safe_filename = secure_filename(
                filename
            )

            if not safe_filename:
                continue

            file_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                company_code,
                safe_filename
            )

            if os.path.exists(file_path):
                os.remove(file_path)

    return redirect("/itc")

NOTIFICATION_CATEGORY_LABELS = {
    "safety": "安全",
    "vehicle": "車両",
    "general": "共通",
}

NOTIFICATION_TYPE_LABELS = {
    "approval_request": "承認依頼",
    "rejected": "差し戻し",
    "resubmitted": "再申請",
    "mention": "メンション",
    "operation_request": "運行判断依頼",
    "operation_result": "運行判断結果",
    "confirmation_request": "確認依頼",
    "defect": "異常報告",
    "recheck": "整備・再確認",
    "reminder": "未実施のお知らせ",
    "approved": "承認完了",
    "completed": "点検完了",
    "notice": "お知らせ",
}

def get_operation_judgment_notification_state(notification, context):
    def state(status, label, requires_action=False):
        return {
            "workflow_status": status,
            "workflow_label": label,
            "requires_action": requires_action,
        }

    result_id = context.get("result_id")
    event_id = context.get("event_id")

    if (
        context.get("result_type") != "vehicle"
        or type(result_id) is not int
        or result_id <= 0
        or type(event_id) is not int
        or event_id < 0
    ):
        return state("unknown", "対応状態を確認できません")

    result_record = VehicleChecklistResult.query.filter_by(
        company_code=notification.company_code,
        id=result_id
    ).first()

    if not result_record:
        return state("closed", "対象記録がないため終了")

    events = ChecklistEvent.query.filter(
        ChecklistEvent.company_code == notification.company_code,
        ChecklistEvent.result_type == "vehicle",
        ChecklistEvent.result_id == result_id,
        ChecklistEvent.id > event_id,
        ChecklistEvent.event_type.in_(["運行判断", "差し戻し"])
    ).order_by(ChecklistEvent.id.asc()).all()

    for event in events:
        if event.event_type == "差し戻し":
            return state("rejected", "差し戻しにより終了")

        detail = safe_json_dict(event.detail_json)
        judgment = detail.get("judgment")

        if (
            isinstance(judgment, dict)
            and judgment.get("status") in ("運行可", "運行不可")
        ):
            return state("completed", "対応済み")

    if result_record.status == "差し戻し":
        return state("rejected", "差し戻しにより終了")

    judgment = safe_json_dict(result_record.operation_judgment_json)

    if judgment.get("status") in ("運行可", "運行不可"):
        return state("completed", "対応済み")

    if notification.target_username not in (
        judgment.get("requested_usernames") or []
    ):
        return state("closed", "担当変更により終了")

    if judgment.get("status") == "判定保留":
        return state("pending", "再判断待ち", True)

    return state("pending", "対応待ち", True)

def get_correction_notification_state(notification, context):
    def state(status, label, requires_action=False):
        return {
            "workflow_status": status,
            "workflow_label": label,
            "requires_action": requires_action,
        }

    result_models = {
        "safety": ChecklistResult,
        "vehicle": VehicleChecklistResult,
    }
    result_type = context.get("result_type")
    result_model = result_models.get(result_type)
    result_id = context.get("result_id")
    event_id = context.get("event_id")

    if (
        result_model is None
        or type(result_id) is not int
        or result_id <= 0
        or type(event_id) is not int
        or event_id < 0
    ):
        return state("unknown", "対応状態を確認できません")

    result_record = result_model.query.filter_by(
        company_code=notification.company_code,
        id=result_id
    ).first()

    if not result_record:
        return state("closed", "対象記録がないため終了")

    resubmission = ChecklistEvent.query.filter(
        ChecklistEvent.company_code == notification.company_code,
        ChecklistEvent.result_type == result_type,
        ChecklistEvent.result_id == result_id,
        ChecklistEvent.id > event_id,
        ChecklistEvent.event_type == "再申請"
    ).order_by(ChecklistEvent.id.asc()).first()

    if resubmission:
        return state("completed", "再申請済み")

    return state("pending", "修正待ち", True)

def get_notification_actor_name(notification):
    context = safe_json_dict(notification.workflow_context_json)

    if not context:
        event = get_notification_legacy_judgment_event(notification)
        if event:
            return str(event.actor_name or "").strip()

        message = str(notification.message or "")
        title = str(notification.title or "").strip()
        if (
            title.endswith((
                "：再確認待ち",
                "：再確認済み・異常なし",
                "：再確認で異常あり",
            ))
            and get_notification_summary(notification) != message
        ):
            return message.splitlines()[5].partition("：")[2].strip()
        return ""

    event_id = context.get("event_id")
    result_id = context.get("result_id")
    result_type = context.get("result_type")

    if (
        type(event_id) is not int
        or event_id <= 0
        or type(result_id) is not int
        or result_id <= 0
        or result_type not in ("safety", "vehicle")
    ):
        return ""

    event = ChecklistEvent.query.filter_by(
        id=event_id,
        company_code=notification.company_code,
        result_type=result_type,
        result_id=result_id
    ).first()

    if not event:
        return ""

    return str(event.actor_name or "").strip()

def get_recheck_notification_state(notification):
    def state(status="", label="", requires_action=False):
        return {
            "workflow_status": status,
            "workflow_label": label,
            "requires_action": requires_action,
        }

    if (
        notification.company_code != session.get("company_code")
        or notification.target_username != session.get("username")
        or get_notification_summary(notification)
        == str(notification.message or "")
    ):
        return state()

    result_type, result_id = get_notification_result_reference(notification)
    parsed_link = urlparse(str(notification.link or ""))
    match = re.fullmatch(
        r"vehicle-flow-defect-([1-9]\d{0,9})-([1-9]\d{0,9})",
        parsed_link.fragment
    )
    if result_type != "vehicle" or not match:
        return state()

    result_record = VehicleChecklistResult.query.filter_by(
        id=result_id,
        company_code=notification.company_code
    ).first()
    if not result_record:
        return state()

    judgment = safe_json_dict(result_record.operation_judgment_json)
    defects = judgment.get("defects")
    if not isinstance(defects, list):
        return state()

    defect_no = int(match.group(2))
    defect = next((
        item for item in defects
        if isinstance(item, dict)
        and type(item.get("defect_no")) is int
        and item["defect_no"] == defect_no
    ), None)
    if not defect:
        return state()

    event = str(notification.title or "").strip().rpartition("：")[2]
    entry_key = "repair" if event == "再確認待ち" else "recheck"
    entry = defect.get(entry_key)
    if (
        not isinstance(entry, dict)
        or not notification.created_at
        or (
            entry.get("notification_created_at")
            or entry.get("recorded_at")
        ) != notification.created_at
    ):
        return state()

    current_status = defect.get("status")
    if event == "再確認待ち":
        if current_status == "再確認待ち":
            return state("pending", "再確認待ち", True)
        if current_status in ("対応待ち", "解消"):
            return state("completed", "再確認済み")

    elif event == "再確認で異常あり":
        if current_status == "対応待ち":
            return state("pending", "整備待ち", True)
        if current_status in ("整備中", "再確認待ち"):
            return state("completed", "整備登録済み")

    elif event == "再確認済み・異常なし":
        if current_status == "解消":
            return state("completed", "不具合解消")

    return state()


def get_notification_workflow_state(notification):
    def state(status, label, requires_action=False):
        return {
            "workflow_status": status,
            "workflow_label": label,
            "requires_action": requires_action,
        }

    context = safe_json_dict(notification.workflow_context_json)

    if not context:
        return get_recheck_notification_state(notification)

    if context.get("action") == "operation_judgment":
        return get_operation_judgment_notification_state(
            notification,
            context
        )

    if context.get("action") == "correction":
        return get_correction_notification_state(
            notification,
            context
        )

    if context.get("action") != "approval":
        return state("", "")

    result_models = {
        "safety": ChecklistResult,
        "vehicle": VehicleChecklistResult,
    }
    result_type = context.get("result_type")
    result_model = result_models.get(result_type)
    result_id = context.get("result_id")
    approval_index = context.get("approval_index")
    event_id = context.get("event_id")

    if (
        result_model is None
        or type(result_id) is not int
        or result_id <= 0
        or type(approval_index) is not int
        or approval_index < 0
        or type(event_id) is not int
        or event_id < 0
    ):
        return state("unknown", "対応状態を確認できません")

    result_record = result_model.query.filter_by(
        company_code=notification.company_code,
        id=result_id
    ).first()

    if not result_record:
        return state("closed", "対象記録がないため終了")

    events = ChecklistEvent.query.filter(
        ChecklistEvent.company_code == notification.company_code,
        ChecklistEvent.result_type == result_type,
        ChecklistEvent.result_id == result_id,
        ChecklistEvent.id > event_id,
        ChecklistEvent.event_type.in_(
            ["承認", "差し戻し", "運行判断"]
        )
    ).order_by(
        ChecklistEvent.id.asc()
    ).all()

    for event in events:
        if event.event_type == "差し戻し":
            return state("rejected", "差し戻しにより終了")

        detail = safe_json_dict(event.detail_json)

        if (
            event.event_type == "承認"
            and detail.get("approval_index") == approval_index
        ):
            return state("completed", "対応済み")

        if (
            result_type == "vehicle"
            and event.event_type == "運行判断"
            and approval_index == 0
        ):
            judgment = detail.get("judgment")

            if (
                isinstance(judgment, dict)
                and judgment.get("status") in ("運行可", "運行不可")
            ):
                return state("completed", "対応済み")

    if result_record.status == "差し戻し":
        return state("rejected", "差し戻しにより終了")

    approvals = safe_json_dict_list(result_record.approvals_json)

    if approval_index >= len(approvals):
        return state("unknown", "対象の承認工程を確認できません")

    if result_type == "vehicle" and approval_index == 0:
        judgment = safe_json_dict(
            result_record.operation_judgment_json
        )

        if judgment.get("status") == "判定保留":
            return state("pending", "再判断待ち", True)

    approval = approvals[approval_index]

    if (
        approval.get("approved_by")
        or approval.get("approved_by_username")
    ):
        return state("completed", "対応済み")

    return state("pending", "対応待ち", True)

def get_notification_legacy_judgment_event(notification):
    company_code = session.get("company_code")
    username = session.get("username")
    if (
        not company_code or not username
        or notification.company_code != company_code
        or notification.target_username != username
        or safe_json_dict(notification.workflow_context_json)
    ):
        return None

    title = str(notification.title or "").strip()
    if title not in (
        "車両の運行判断：運行可",
        "車両の運行判断：運行不可",
        "車両の運行判断：判定保留",
    ):
        return None

    message = str(notification.message or "")
    if get_notification_summary(notification) == message:
        return None

    parsed_link = urlparse(str(notification.link or ""))
    path_match = re.fullmatch(
        r"/vehicle/checklists/([1-9]\d{0,9})/?", parsed_link.path
    )
    if not path_match or parsed_link.fragment != "vehicle-flow-judgment":
        return None

    try:
        pairs = parse_qsl(parsed_link.query, max_num_fields=20)
        values = {}
        for key in ("vehicle_record_id", "year", "month", "active_day"):
            matches = [value for name, value in pairs if name == key]
            if len(matches) != 1 or not re.fullmatch(r"\d{1,10}", matches[0]):
                return None
            values[key] = int(matches[0])

        checklist_id = int(path_match.group(1))
        vehicle_id = values["vehicle_record_id"]
        if not (
            0 < checklist_id <= 2147483647
            and 0 < vehicle_id <= 2147483647
        ):
            return None

        target_date = datetime(
            values["year"], values["month"], values["active_day"]
        )
        lines = message.splitlines()
        body_date = datetime.strptime(
            lines[0][len("点検日："):], "%Y-%m-%d"
        )
        if target_date != body_date or not notification.created_at:
            return None
    except (ValueError, OverflowError):
        return None

    cache = request.environ.setdefault("dkss.legacy_judgment_events", {})
    cache_key = notification.id
    if cache_key in cache:
        return cache[cache_key]

    events = ChecklistEvent.query.join(
        VehicleChecklistResult,
        (VehicleChecklistResult.id == ChecklistEvent.result_id)
        & (VehicleChecklistResult.company_code == ChecklistEvent.company_code)
    ).filter(
        ChecklistEvent.company_code == company_code,
        ChecklistEvent.result_type == "vehicle",
        ChecklistEvent.event_type == "運行判断",
        ChecklistEvent.created_at == notification.created_at,
        VehicleChecklistResult.checklist_id == checklist_id,
        VehicleChecklistResult.vehicle_record_id == vehicle_id,
        VehicleChecklistResult.year == str(target_date.year),
        VehicleChecklistResult.month.in_(
            [str(target_date.month), f"{target_date.month:02d}"]
        ),
        VehicleChecklistResult.day.in_(
            [str(target_date.day), f"{target_date.day:02d}"]
        ),
    ).all()

    decision = title.rpartition("：")[2]
    reason = "\n".join(lines[2:])[len("理由："):].strip()
    matches = []
    for event in events:
        judgment = safe_json_dict(event.detail_json).get("judgment")
        if (
            isinstance(judgment, dict)
            and judgment.get("status") == decision
            and str(judgment.get("reason") or "").strip() == reason
        ):
            matches.append(event)

    matched_event = matches[0] if len(matches) == 1 else None
    cache[cache_key] = matched_event
    return matched_event


def get_notification_result_reference(notification):
    context = safe_json_dict(notification.workflow_context_json)
    if context:
        return context.get("result_type"), context.get("result_id")

    parsed_link = urlparse(str(notification.link or ""))
    match = re.fullmatch(
        r"/(safety|vehicle)/checklist-results/(\d+)(?:/.*)?",
        parsed_link.path
    )
    if match:
        return match.group(1), int(match.group(2))

    if re.fullmatch(r"/vehicle/checklists/\d+/?", parsed_link.path):
        match = re.fullmatch(
            r"vehicle-flow-defect-([1-9]\d{0,9})-([1-9]\d{0,9})",
            parsed_link.fragment
        )
        if match:
            result_id = int(match.group(1))
            if result_id <= 2147483647:
                return "vehicle", result_id

    event = get_notification_legacy_judgment_event(notification)
    if event:
        return "vehicle", event.result_id

    return None, None


def get_notification_target_lookup(notifications):
    company_code = session.get("company_code")
    username = session.get("username")
    lookup = {
        "results": {},
        "checklists": {},
        "vehicles": {},
    }

    if not company_code or not username:
        return lookup

    result_ids = {"safety": set(), "vehicle": set()}

    for notification in notifications:
        if (
            notification.company_code != company_code
            or notification.target_username != username
        ):
            continue

        result_type, result_id = get_notification_result_reference(
            notification
        )

        if (
            result_type in result_ids
            and type(result_id) is int
            and 0 < result_id <= 2147483647
        ):
            result_ids[result_type].add(result_id)

    models = {
        "safety": ChecklistResult,
        "vehicle": VehicleChecklistResult,
    }

    for result_type, ids in result_ids.items():
        if not ids:
            continue

        model = models[result_type]
        records = model.query.filter(
            model.company_code == company_code,
            model.id.in_(ids)
        ).all()

        for record in records:
            lookup["results"][(result_type, record.id)] = record

    records = list(lookup["results"].values())
    checklist_ids = {record.checklist_id for record in records}
    vehicle_ids = {
        vehicle_id
        for record in records
        for vehicle_id in [
            getattr(record, "vehicle_record_id", None),
            getattr(record, "target_vehicle_record_id", None),
        ]
        if vehicle_id
    }

    if checklist_ids:
        lookup["checklists"] = {
            record.id: record
            for record in Checklist.query.filter(
                Checklist.company_code == company_code,
                Checklist.id.in_(checklist_ids)
            ).all()
        }

    if vehicle_ids:
        lookup["vehicles"] = {
            record.id: record
            for record in Vehicle.query.filter(
                Vehicle.company_code == company_code,
                Vehicle.id.in_(vehicle_ids)
            ).all()
        }

    return lookup

def get_notification_target_info(notification, lookup=None):
    company_code = session.get("company_code")
    username = session.get("username")

    if (
        not company_code
        or not username
        or notification.company_code != company_code
        or notification.target_username != username
    ):
        return None

    result_type, result_id = get_notification_result_reference(
        notification
    )

    result_models = {
        "safety": ChecklistResult,
        "vehicle": VehicleChecklistResult,
    }
    result_model = result_models.get(result_type)

    if (
        result_model is None
        or type(result_id) is not int
        or result_id <= 0
        or result_id > 2147483647
    ):
        return None

    if lookup is not None:
        result_record = lookup["results"].get((result_type, result_id))
    else:
        result_record = result_model.query.filter_by(
            id=result_id,
            company_code=company_code
        ).first()

    if not result_record:
        return None

    # 記録時点の点検表名を優先する。
    snapshot = safe_json_dict(
        result_record.checklist_snapshot_json
    )
    checklist_name = snapshot.get("name")

    if not isinstance(checklist_name, str):
        checklist_name = ""

    checklist_name = checklist_name.strip()

    if not checklist_name:
        if lookup is not None:
            checklist_record = lookup["checklists"].get(
                result_record.checklist_id
            )
        else:
            checklist_record = Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=company_code
            ).first()

        if checklist_record:
            checklist_name = checklist_record.name

    target_label = ""
    office = ""
    period_label = result_record.checked_date or ""

    if result_type == "vehicle":
        vehicle_id = result_record.vehicle_record_id

        date_parts = [
            str(value).strip()
            for value in (
                result_record.year,
                result_record.month,
                result_record.day
            )
            if value not in (None, "", "0", 0)
        ]

        if date_parts:
            period_label = "/".join(date_parts)

    else:
        vehicle_id = result_record.target_vehicle_record_id
        target_label = result_record.target_user or ""
        office = result_record.target_office or ""

    if vehicle_id:
        if lookup is not None:
            vehicle_record = lookup["vehicles"].get(vehicle_id)
        else:
            vehicle_record = Vehicle.query.filter_by(
                id=vehicle_id,
                company_code=company_code
            ).first()

        if vehicle_record:
            target_label = vehicle_number({
                "plate_area": vehicle_record.plate_area or "",
                "plate_class": vehicle_record.plate_class or "",
                "plate_kana": vehicle_record.plate_kana or "",
                "plate_number": vehicle_record.plate_number or "",
            })
            office = office or vehicle_record.office or ""

    return {
        "checklist_name": checklist_name or "点検記録",
        "target_label": target_label,
        "period_label": period_label,
        "office": office,
    }

def get_notification_summary(notification):
    message = str(notification.message or "")
    title = str(notification.title or "").strip()
    path = urlparse(str(notification.link or "")).path

    if not path.startswith("/vehicle/"):
        return message

    operation_results = {
        "車両の運行判断：運行可": (
            "運行可", "運行可と判断されました。",
        ),
        "車両の運行判断：運行不可": (
            "運行不可", "運行不可と判断されました。",
        ),
        "車両の運行判断：判定保留": (
            "判定保留", "運行判断が保留になりました。",
        ),
    }
    if title in operation_results:
        lines = message.splitlines()
        decision, description = operation_results[title]
        if (
            len(lines) < 3
            or not lines[0].startswith("点検日：")
            or lines[1] != "判断：" + decision
            or not lines[2].startswith("理由：")
        ):
            return message

        reason = "\n".join(lines[2:])[len("理由："):].strip()
        reason_preview = " ".join(reason.splitlines())
        if len(reason_preview) > 100:
            reason_preview = reason_preview[:100] + "…"

        return "\n".join(part for part in (
            description,
            lines[0],
            "理由：" + reason_preview if reason_preview else "",
        ) if part)

    events = {
        "再確認待ち": (
            "再確認待ち",
            "整備を登録しました。",
        ),
        "再確認済み・異常なし": (
            "解消",
            "再確認を完了しました。異常はありません。",
        ),
        "再確認で異常あり": (
            "対応待ち",
            "再確認を行いました。異常が残っています。",
        ),
    }
    vehicle, separator, event = title.rpartition("：")
    if not separator or event not in events:
        return message

    keys = (
        "対象車両", "点検日", "項目", "対応状況",
        "次にすること", "実施者", "実施日時",
    )
    lines = message.splitlines()
    if len(lines) < 8 or not lines[7].startswith("内容："):
        return message

    fields = {}
    for key, line in zip(keys, lines[:7]):
        prefix = key + "："
        if not line.startswith(prefix):
            return message
        fields[key] = line[len(prefix):].strip()

    expected_status, description = events[event]
    if (
        fields["対象車両"] != vehicle
        or fields["対応状況"] != expected_status
        or not fields["次にすること"]
        or not fields["項目"]
    ):
        return message

    actor = fields["実施者"]
    event_message = (actor + "さんが" if actor else "") + description
    next_action = fields["次にすること"]
    redundant_prefix = "この不具合の再確認は完了しました。"
    if (
        event == "再確認済み・異常なし"
        and next_action.startswith(redundant_prefix)
    ):
        next_action = next_action[len(redundant_prefix):]

    return "\n".join(part for part in (
        event_message,
        next_action,
        "対象項目：" + fields["項目"],
    ) if part)


def get_notification_display_info(notification):
    title = str(notification.title or "").strip()
    path = urlparse(str(notification.link or "")).path

    if path.startswith(("/vehicle/", "/vehicle-patrols/")):
        category = "vehicle"
    elif path.startswith(("/safety/", "/pointouts/")):
        category = "safety"
    else:
        category = "general"

    notification_type = "notice"
    action_label = "該当ページを確認"

    if title == "メンションされました":
        notification_type = "mention"
        action_label = "メンションを確認"

    elif category in ("safety", "vehicle"):
        if "再申請" in title:
            notification_type = "resubmitted"
            action_label = "変更内容を確認"

        elif title in (
            "安全チェックリスト承認依頼",
            "車両チェックリスト承認依頼",
        ):
            notification_type = "approval_request"
            action_label = "承認内容を確認"

        elif title in (
            "安全パトロールが差し戻されました",
            "チェックリストが差し戻されました",
            "車両チェックリストが差し戻されました",
        ):
            notification_type = "rejected"
            action_label = "差し戻し内容を確認"

        elif (
            title == "運行判断の依頼"
            or title.startswith("運行可否の再判定依頼：")
        ):
            notification_type = "operation_request"
            action_label = "運行判断を確認"

        elif title in (
            "車両の運行判断：運行可",
            "車両の運行判断：運行不可",
            "車両の運行判断：判定保留",
        ):
            notification_type = "operation_result"
            action_label = "判断結果を確認"

        elif title == "安全パトロール確認依頼":
            notification_type = "confirmation_request"
            action_label = "確認内容を開く"

        elif title.startswith("日常点検の異常報告："):
            notification_type = "defect"
            action_label = "不具合を確認"

        elif title.endswith((
            "：再確認待ち",
            "：再確認済み・異常なし",
            "：再確認で異常あり",
        )):
            notification_type = "recheck"
            action_label = "整備・再確認内容を確認"

        elif title == "車両点検が未実施です":
            notification_type = "reminder"
            action_label = "点検内容を確認"

        elif title in (
            "安全パトロールが承認されました",
            "チェックリストが承認されました",
            "車両チェックリストが承認されました",
        ):
            notification_type = "approved"
            action_label = "承認結果を確認"

        elif title in (
            "安全チェックリスト完了のお知らせ",
            "車両点検完了のお知らせ",
        ):
            notification_type = "completed"
            action_label = "点検結果を確認"

    action_label = {
        "approval_request": "承認内容を確認",
        "operation_request": "運行判断を確認",
        "operation_result": "判断結果を確認",
        "resubmitted": "変更内容を確認",
        "rejected": "差し戻しを確認",
        "mention": "メンション確認",
        "recheck": "再確認を見る",
        "defect": "不具合を確認",
        "reminder": "点検内容を確認",
        "approved": "承認結果を確認",
        "completed": "点検結果を確認",
        "confirmation_request": "内容を確認",
    }.get(notification_type, "内容を確認")

    if notification_type == "recheck":
        event = title.rpartition("：")[2]
        action_label = {
            "再確認待ち": "再確認を見る",
            "再確認で異常あり": "整備を確認",
            "再確認済み・異常なし": "結果を確認",
        }.get(event, action_label)

    return {
        "category": category,
        "category_label": NOTIFICATION_CATEGORY_LABELS[category],
        "notification_type": notification_type,
        "type_label": NOTIFICATION_TYPE_LABELS[notification_type],
        "action_label": action_label,
        "summary_message": get_notification_summary(notification),
    }

def get_notification_list_state(current_view=None):
    view = (
        current_view
        if current_view is not None
        else request.values.get("view", "inbox")
    )

    if view not in ("inbox", "unread", "action", "deleted"):
        view = "inbox"

    category = request.values.get("category", "")
    notification_type = request.values.get("type", "")
    search_query = request.values.get("q", "").strip()[:200]

    if category not in NOTIFICATION_CATEGORY_LABELS:
        category = ""

    if notification_type not in NOTIFICATION_TYPE_LABELS:
        notification_type = ""

    return {
        "view": view,
        "category": category,
        "type": notification_type,
        "q": search_query,
    }

def get_notification_workflow_states():
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return {}

    records = Notification.query.filter(
        Notification.company_code == company_code,
        Notification.target_username == username,
        Notification.deleted_at.is_(None),
        Notification.workflow_context_json.isnot(None),
        Notification.workflow_context_json != "{}"
    ).all()

    return {
        str(notification.id): get_notification_workflow_state(notification)
        for notification in records
    }


def get_notification_action_count():
    return sum(
        1
        for state in get_notification_workflow_states().values()
        if state["requires_action"]
    )

def get_unread_notification_count():
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return 0

    return Notification.query.filter(
        Notification.company_code == company_code,
        Notification.target_username == username,
        Notification.deleted_at.is_(None),
        db.or_(
            Notification.read.is_(False),
            Notification.read.is_(None)
        )
    ).count()


@app.context_processor
def inject_notification_count():
    return {
        "unread_notification_count":
            get_unread_notification_count()
    }

@app.route("/api/notifications/recent")
def notification_recent():
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return jsonify({"error": "login_required"}), 401

    records = Notification.query.filter(
        Notification.company_code == company_code,
        Notification.target_username == username,
        Notification.deleted_at.is_(None)
    ).all()
    records = sort_notification_records(records)[:5]

    target_lookup = get_notification_target_lookup(records)
    items = []

    for notification in records:
        display_info = get_notification_display_info(notification)
        workflow_state = get_notification_workflow_state(notification)
        target_info = get_notification_target_info(
            notification, target_lookup
        )

        items.append({
            "id": notification.id,
            "title": str(notification.title or ""),
            "message": display_info["summary_message"],
            "read": bool(notification.read),
            "created_at": str(notification.created_at or ""),
            "time_label": format_notification_datetime(
                notification.created_at, "time"
            ),
            "day_key": format_notification_datetime(
                notification.created_at, "group"
            ),
            "day_label": format_notification_datetime(
                notification.created_at, "group"
            ),
            "category_label": display_info["category_label"],
            "type_label": display_info["type_label"],
            "workflow_label": workflow_state["workflow_label"],
            "workflow_status": workflow_state["workflow_status"],
            "requires_action": workflow_state["requires_action"],
            "target_info": target_info,
            "detail_url": url_for(
                "notification_detail",
                index=notification.id,
                view="inbox"
            ),
        })

    response = jsonify({
        "notifications": items,
        "unread_count": get_unread_notification_count(),
        "list_url": url_for("notifications"),
    })
    response.headers["Cache-Control"] = "no-store"
    return response

@app.route("/api/notifications/unread-count")
def notification_unread_count():
    if not session.get("company_code") or not session.get("username"):
        return jsonify({"error": "login_required"}), 401

    counts = {
        "unread_count": get_unread_notification_count()
    }

    if request.args.get("include_action") == "1":
        workflow_states = get_notification_workflow_states()

        counts["action_count"] = sum(
            1
            for state in workflow_states.values()
            if state["requires_action"]
        )
        counts["workflow_states"] = workflow_states

    response = jsonify(counts)
    response.headers["Cache-Control"] = "no-store"
    return response

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

        last_name = request.form.get(
            "last_name",
            ""
        ).strip()

        first_name = request.form.get(
            "first_name",
            ""
        ).strip()

        name = last_name + first_name

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
            or not last_name
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

        elif len(last_name) > 100:
            error = "姓は100文字以内で入力してください。"

        elif len(first_name) > 100:
            error = "名は100文字以内で入力してください。"

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
                last_name=last_name,
                first_name=first_name or None,
                office=office,
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
                    name=(last_name or "") + (first_name or ""),
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
                return redirect(
                    url_for(
                        "login",
                        company_code=company_code
                    )
                )

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

        if action == "profile_image":
            profile_image = request.files.get(
                "profile_image"
            )

            if profile_image and profile_image.filename:
                old_profile_image = os.path.basename(
                    str(
                        current_user.profile_image
                        or ""
                    )
                )

                saved_filename = save_uploaded_file(
                    profile_image
                )

                if saved_filename:
                    current_user.profile_image = (
                        saved_filename
                    )

                    db.session.commit()

                    session["profile_image"] = (
                        saved_filename
                    )

                    if (
                        old_profile_image
                        and old_profile_image != saved_filename
                    ):
                        if s3_client and S3_BUCKET_NAME:
                            try:
                                s3_client.delete_object(
                                    Bucket=S3_BUCKET_NAME,
                                    Key=(
                                        f"uploads/"
                                        f"{current_user.company_code}/"
                                        f"{old_profile_image}"
                                    )
                                )
                            except ClientError:
                                app.logger.warning(
                                    "旧プロフィール画像のS3削除に失敗しました。",
                                    exc_info=True
                                )
                        else:
                            safe_filename = secure_filename(
                                old_profile_image
                            )

                            if safe_filename:
                                file_path = os.path.join(
                                    app.config["UPLOAD_FOLDER"],
                                    current_user.company_code,
                                    safe_filename
                                )

                                if os.path.exists(file_path):
                                    os.remove(file_path)

            return redirect("/settings")

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
                    User.last_name.ilike(keyword_like),
                    User.first_name.ilike(keyword_like),
                    User.username.ilike(keyword_like),
                    User.office.ilike(keyword_like)
                )
            )

        for user in query.order_by(
            User.last_name.asc(),
            User.first_name.asc()
        ).limit(10).all():
            results.append({
                "id": user.username,
                "name": (
                    f"{user.last_name or ''}"
                    f"{user.first_name or ''}"
                ),
                "sub": user.office or ""
            })

    return {"results": results}

@app.route("/api/approval-candidates")
def approval_candidates():
    company_code = session.get("company_code")
    office = session.get("office") or ""

    if not company_code or not office:
        return {"users": []}

    users = User.query.filter(
        User.company_code == company_code,
        User.office == office,
        User.role == "admin"
    ).order_by(
        User.last_name.asc(),
        User.first_name.asc()
    ).all()

    return {
        "users": [
            {
                "name": (
                    f"{user.last_name or ''}"
                    f"{user.first_name or ''}"
                ),
                "username": user.username,
                "office": user.office or ""
            }
            for user in users
        ]
    }


@app.route("/api/mention-users")
def mention_users():
    keyword = request.args.get("q", "").strip()

    if len(keyword) > 100:
        return {"users": []}, 400

    if not keyword:
        return {"users": []}

    user_query = User.query.filter_by(
        company_code=session.get("company_code")
    )

    if request.args.get("exact_username") == "1":
        user_query = user_query.filter(
            User.username == keyword
        )
    elif keyword:
        keyword_like = f"%{keyword}%"

        user_query = user_query.filter(
            db.or_(
                User.last_name.ilike(keyword_like),
                User.first_name.ilike(keyword_like),
                User.username.ilike(keyword_like),
                (
                    db.func.coalesce(User.last_name, "")
                    + db.func.coalesce(User.first_name, "")
                ).ilike(keyword_like)
            )
        )

    approval_scope = request.args.get("approval_scope", "")
    if approval_scope == "admin":
        user_query = user_query.filter(User.role == "admin")
    elif approval_scope == "admin_user":
        user_query = user_query.filter(User.role.in_(["admin", "user"]))

    matched_users = (
        user_query
        .order_by(
            User.last_name.asc(),
            User.first_name.asc()
        )
        .limit(5)
        .all()
    )

    users = [
        {
            "name": (
                f"{user.last_name or ''}"
                f"{user.first_name or ''}"
            ),
            "username": user.username,
            "office": user.office or "",
            "role": user.role or "user"
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
                    "registration_number": " ".join(
                        value
                        for value in [
                            usage_vehicle.plate_area or "",
                            usage_vehicle.plate_class or "",
                            usage_vehicle.plate_kana or "",
                            usage_vehicle.plate_number or "",
                        ]
                        if value
                    ),
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

                target_label = " ".join(
                    value
                    for value in [
                        target_vehicle_record.plate_area or "",
                        target_vehicle_record.plate_class or "",
                        target_vehicle_record.plate_kana or "",
                        target_vehicle_record.plate_number or "",
                    ]
                    if value
                ) or "ナンバー未登録"

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

                        target_label = " ".join(
                        value
                        for value in [
                            target_vehicle_record.plate_area or "",
                            target_vehicle_record.plate_class or "",
                            target_vehicle_record.plate_kana or "",
                            target_vehicle_record.plate_number or "",
                        ]
                        if value
                    ) or "ナンバー未登録"

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
                    "target_value": (
                        result_record.target_username
                        if target_type == "user"
                        else result_record.target_office
                        if target_type == "office"
                        else result_record.vehicle_record_id
                        if is_vehicle_checklist
                        else result_record.target_vehicle_record_id
                        if target_type == "vehicle"
                        else None
                    ),
                    "lowest_score_rate": None,
                    "year": "",
                    "month": "",
                    "day": "",
                }

            target_stats[key]["score"] += target_score
            target_stats[key]["max_score"] += target_max_score
            target_stats[key]["count"] += 1

            current_score_rate = target_score / target_max_score

            if (
                target_stats[key]["lowest_score_rate"] is None
                or current_score_rate < target_stats[key]["lowest_score_rate"]
            ):
                target_stats[key]["lowest_score_rate"] = current_score_rate
                target_stats[key]["year"] = getattr(
                    result_record, "year", ""
                ) or ""
                target_stats[key]["month"] = getattr(
                    result_record, "month", ""
                ) or ""
                target_stats[key]["day"] = getattr(
                    result_record, "day", ""
                ) or ""


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
                "target_value": stats.get("target_value"),
                "year": stats.get("year", ""),
                "month": stats.get("month", ""),
                "day": stats.get("day", ""),
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
            "frequency_unit": checklist_record.frequency_unit,
            "display_type": checklist_record.display_type,
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

def get_notification_target_link(notification):
    link = str(notification.link or "").strip()

    if (
        not link.startswith("/")
        or link.startswith("//")
        or "\\" in link
        or any(ord(character) < 32 for character in link)
    ):
        return ""

    parsed_link = urlparse(link)

    if parsed_link.scheme or parsed_link.netloc:
        return ""

    if notification.title == "車両チェックリスト承認依頼":
        match = re.fullmatch(
            r"/vehicle/checklists/(\d+)/?",
            parsed_link.path
        )

        if match:
            checklist_record = Checklist.query.filter_by(
                id=int(match.group(1)),
                company_code=notification.company_code
            ).first()

            if (
                checklist_record
                and checklist_to_dict(checklist_record).get(
                    "fixed_template_code"
                ) == "daily_inspection_truck_trailer"
            ):
                parsed_link = parsed_link._replace(
                    fragment="vehicle-flow-judgment"
                )

    return parsed_link.geturl()


@app.route("/notifications/<int:index>/open")
def open_notification_target(index):
    list_state = get_notification_list_state()

    notification = Notification.query.filter(
        Notification.id == index,
        Notification.company_code == session.get("company_code"),
        Notification.target_username == session.get("username")
    ).first()

    if not notification:
        return redirect(url_for("notifications", **list_state))

    if notification.deleted_at is not None:
        return redirect(
            url_for(
                "notification_detail",
                index=index,
                **list_state
            )
        )

    target_link = get_notification_target_link(notification)

    if not target_link:
        flash(
            "この通知には有効な移動先がありません。",
            "error:"
        )
        return redirect(url_for("notifications", **list_state))

    parsed_link = urlparse(target_link)

    query_parameters = [
        (key, value)
        for key, value in parse_qsl(
            parsed_link.query,
            keep_blank_values=True
        )
        if key != "_notification_id"
    ]

    query_parameters.append(("_notification_id", str(index)))

    target_link = parsed_link._replace(
        query=urlencode(query_parameters)
    ).geturl()

    return redirect(target_link)

@app.after_request
def mark_notification_read_after_target_display(response):
    notification_id = request.args.get(
        "_notification_id",
        type=int
    )

    if (
        request.method != "GET"
        or response.status_code != 200
        or response.mimetype != "text/html"
        or not notification_id
        or notification_id <= 0
        or notification_id > 2147483647
        or not session.get("company_code")
        or not session.get("username")
    ):
        return response

    response.headers["Cache-Control"] = "no-store"

    try:
        notification = Notification.query.filter(
            Notification.id == notification_id,
            Notification.company_code == session.get("company_code"),
            Notification.target_username == session.get("username")
        ).first()

        if (
            not notification
            or notification.deleted_at is not None
            or notification.read
        ):
            return response

        target_link = get_notification_target_link(notification)

        if not target_link:
            return response

        parsed_link = urlparse(target_link)

        if request.path != parsed_link.path:
            return response

        expected_parameters = {}

        for key, value in parse_qsl(
            parsed_link.query,
            keep_blank_values=True
        ):
            if key == "_notification_id":
                continue

            expected_parameters.setdefault(key, []).append(value)

        for key, values in expected_parameters.items():
            if request.args.getlist(key) != values:
                return response

        notification.read = True
        db.session.commit()

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception(
            "通知経由で開いたページの既読更新に失敗しました。"
        )

        flash(
            "通知の既読状態を更新できませんでした。"
            "通知一覧からもう一度お試しください。",
            "error:"
        )

        return redirect(url_for("notifications"))

    return response

def sort_notification_records(records, newest=True):
    dated_records = []
    undated_records = []

    for record in records:
        sort_key = format_notification_datetime(
            record.created_at, "sort"
        )

        if sort_key:
            dated_records.append((sort_key, record.id, record))
        else:
            undated_records.append(record)

    dated_records.sort(
        key=lambda entry: entry[:2],
        reverse=newest
    )
    undated_records.sort(key=lambda record: record.id, reverse=newest)

    return [entry[2] for entry in dated_records] + undated_records


@app.template_filter("notification_datetime")
def format_notification_datetime(value, mode="detail"):
    text = str(value or "").strip()

    try:
        value_dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        if mode == "key":
            return "unknown"
        if mode in ("day", "group"):
            return "日時不明"
        return ""

    local_now = request.environ.get("dkss.notification_local_now")
    if local_now is None:
        local_now = get_user_local_now(
            session.get("company_code"),
            session.get("username")
        )
        request.environ["dkss.notification_local_now"] = local_now

    if value_dt.tzinfo is not None:
        value_dt = value_dt.astimezone(local_now.tzinfo)

    day = value_dt.date()
    today = local_now.date()
    time_text = value_dt.strftime("%H:%M")

    if mode == "key":
        return day.isoformat()

    if mode == "sort":
        sort_dt = value_dt
        if sort_dt.tzinfo is None:
            sort_dt = sort_dt.replace(tzinfo=local_now.tzinfo)
        return sort_dt.astimezone(ZoneInfo("UTC")).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )

    if mode == "time":
        return time_text

    if mode == "date":
        return value_dt.strftime("%m/%d")

    if mode == "group":
        if day == today:
            return "今日"
        if day == today - timedelta(days=1):
            return "昨日"
        if day > today:
            return f"{day.year}年{day.month}月{day.day}日"

        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        previous_month_start = (
            month_start - timedelta(days=1)
        ).replace(day=1)

        if day >= week_start:
            return "今週"
        if day >= week_start - timedelta(days=7):
            return "先週"
        if day >= month_start:
            return "今月"
        if day >= previous_month_start:
            return "先月"
        return "それ以前"

    if mode == "day":
        if day == today:
            return "今日"
        if day == today - timedelta(days=1):
            return "昨日"
        if day.year == today.year:
            return f"{day.month}月{day.day}日"
        return f"{day.year}年{day.month}月{day.day}日"

    if mode == "recent":
        if day == today:
            return time_text
        if day == today - timedelta(days=1):
            return f"昨日 {time_text}"
        if day.year == today.year:
            return f"{day.month}月{day.day}日 {time_text}"
        return f"{day.year}年{day.month}月{day.day}日 {time_text}"

    return f"{day.year}年{day.month}月{day.day}日 {time_text}"

@app.route("/notifications")
def notifications():
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return redirect("/")
    current_sort = request.args.get(
        "sort",
        session.get("notification_sort", "newest")
    )

    if current_sort not in ("newest", "oldest"):
        current_sort = "newest"

    session["notification_sort"] = current_sort

    current_view = request.args.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "inbox"

    selected_category = request.args.get("category", "")
    selected_type = request.args.get("type", "")
    search_query = request.args.get("q", "").strip()[:200]

    if selected_category not in NOTIFICATION_CATEGORY_LABELS:
        selected_category = ""

    if selected_type not in NOTIFICATION_TYPE_LABELS:
        selected_type = ""

    query = Notification.query.filter(
        Notification.company_code == company_code,
        Notification.target_username == username
    )

    if current_view == "deleted":
        query = query.filter(
            Notification.deleted_at.isnot(None)
        )
    else:
        query = query.filter(
            Notification.deleted_at.is_(None)
        )

        if current_view == "unread":
            query = query.filter(
                db.or_(
                    Notification.read.is_(False),
                    Notification.read.is_(None)
                )
            )

    notification_records = query.order_by(
        Notification.id.desc()
    ).all()
    notification_records = sort_notification_records(
        notification_records,
        newest=current_sort == "newest"
    )
    target_lookup = get_notification_target_lookup(
        notification_records
    )

    items = []
    search_text = search_query.casefold()

    for notification in notification_records:
        display_info = get_notification_display_info(notification)

        if (
            selected_category
            and display_info["category"] != selected_category
        ):
            continue

        if (
            selected_type
            and display_info["notification_type"] != selected_type
        ):
            continue

        target_info = (
            get_notification_target_info(notification, target_lookup)
            or {}
        )

        if search_text:
            searchable_text = "\n".join([
                str(notification.title or ""),
                str(notification.message or ""),
                str(notification.target_user or ""),
                str(get_notification_actor_name(notification) or ""),
                str(target_info.get("checklist_name") or ""),
                str(target_info.get("target_label") or ""),
                str(target_info.get("office") or ""),
                str(target_info.get("period_label") or ""),
            ]).casefold()

            if search_text not in searchable_text:
                continue

        workflow_state = get_notification_workflow_state(notification)

        if (
            current_view == "action"
            and not workflow_state["requires_action"]
        ):
            continue

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
            "deleted_at": notification.deleted_at,
            "target_info": target_info,
            **display_info,
            **workflow_state,
        })

    return render_template(
        "notifications.html",
        notifications=items,
        current_sort=current_sort,
        inbox_notification_count=Notification.query.filter(
            Notification.company_code == company_code,
            Notification.target_username == username,
            Notification.deleted_at.is_(None)
        ).count(),
        action_notification_count=get_notification_action_count(),
        current_view=current_view,
        selected_category=selected_category,
        selected_type=selected_type,
        search_query=search_query,
        category_labels=NOTIFICATION_CATEGORY_LABELS,
        type_labels=NOTIFICATION_TYPE_LABELS
    )

@app.route("/notifications/<int:index>")
def notification_detail(index):
    panel_only = request.args.get("panel") == "1"

    notification = Notification.query.filter(
        Notification.id == index,
        Notification.company_code == session.get("company_code"),
        Notification.target_username == session.get("username")
    ).first()

    current_view = request.args.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "inbox"

    if not notification:
        if panel_only:
            return jsonify({
                "error": "通知が見つかりません。"
            }), 404

        return redirect(
            url_for("notifications", **get_notification_list_state(current_view))
        )

    is_deleted = notification.deleted_at is not None

    if is_deleted:
        current_view = "deleted"
    elif current_view == "deleted":
        current_view = "inbox"

    should_mark_as_read = (
        not panel_only
        and not is_deleted
        and not notification.read
    )

    notification_dict = {
        "id": notification.id,
        "index": notification.id,
        "target_user": notification.target_user,
        "actor_name": get_notification_actor_name(notification),
        "title": notification.title,
        "message": notification.message,
        "link": notification.link,
        "files": safe_json_str_list(
            notification.files_json
        ),
        "read": True if should_mark_as_read else notification.read,
        "created_at": notification.created_at,
        "deleted_at": notification.deleted_at,
        **get_notification_display_info(notification),
        **get_notification_workflow_state(notification),
    }

    if notification_dict["title"] == "車両チェックリスト承認依頼":
        link = notification_dict.get("link") or ""
        parsed_link = urlparse(link)
        match = re.fullmatch(
            r"/vehicle/checklists/(\d+)/?",
            parsed_link.path
        )

        if match:
            checklist_record = Checklist.query.filter_by(
                id=int(match.group(1)),
                company_code=session.get("company_code")
            ).first()

            if (
                checklist_record
                and checklist_to_dict(checklist_record).get(
                    "fixed_template_code"
                ) == "daily_inspection_truck_trailer"
            ):
                notification_dict["link"] = parsed_link._replace(
                    fragment="vehicle-flow-judgment"
                ).geturl()

    if not panel_only:
        list_state = get_notification_list_state(current_view)

        if (
            current_view == "unread" and notification.read
        ) or (
            current_view == "action"
            and not notification_dict["requires_action"]
        ):
            list_state["view"] = "inbox"

        return redirect(url_for(
            "notifications",
            notification=notification.id,
            **list_state
        ))

    try:
        notification_dict["target_info"] = (
            get_notification_target_info(notification)
        )

        if should_mark_as_read:
            notification.read = True

        rendered_page = render_template(
            "notification_detail.html",
            notification=notification_dict,
            index=notification.id,
            current_view=current_view,
            list_state=get_notification_list_state(current_view),
            panel_only=panel_only
        )

        if panel_only:
            response = jsonify({
                "html": rendered_page,
                "notification_id": notification.id,
                "read": bool(notification.read),
                "deleted": is_deleted,
            })
            response.headers["Cache-Control"] = "no-store"
            return response

        if should_mark_as_read:
            db.session.commit()

        return rendered_page

    except SQLAlchemyError:
        db.session.rollback()
        if panel_only:
            return jsonify({
                "error": "通知を開けませんでした。もう一度お試しください。"
            }), 500
        flash(
            "通知を開けませんでした。もう一度お試しください。",
            "error:"
        )

        return redirect(
            url_for("notifications", **get_notification_list_state(current_view))
        )

@app.route("/api/notifications/<int:index>/read", methods=["POST"])
@limiter.limit("120 per minute")
def mark_notification_read(index):
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return jsonify({
            "error": "ログインし直してください。"
        }), 401

    try:
        notification = Notification.query.filter(
            Notification.id == index,
            Notification.company_code == company_code,
            Notification.target_username == username
        ).with_for_update().first()

        if not notification:
            return jsonify({
                "error": "通知が見つかりません。"
            }), 404

        if notification.deleted_at is not None:
            return jsonify({
                "error": "この通知は削除済みです。"
            }), 409

        notification.read = True
        db.session.flush()

        unread_count = get_unread_notification_count()
        db.session.commit()

        response = jsonify({
            "notification_id": index,
            "read": True,
            "unread_count": unread_count,
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("通知の既読処理に失敗しました。")

        return jsonify({
            "error": "既読にできませんでした。もう一度お試しください。"
        }), 500
@app.route(
    "/api/notifications/<int:index>/delete",
    methods=["POST"], defaults={"undo": False}
)
@app.route(
    "/api/notifications/<int:index>/undo-delete",
    methods=["POST"], defaults={"undo": True}
)
@limiter.limit("20 per minute")
def update_notification_popover_delete(index, undo):
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return jsonify({"error": "ログインし直してください。"}), 401

    deletion_time = None

    if undo:
        payload = request.get_json(silent=True)
        value = payload.get("deleted_at") if isinstance(payload, dict) else None

        try:
            if not isinstance(value, str) or not value or len(value) > 64:
                raise ValueError()
            deletion_time = datetime.fromisoformat(value)
            if deletion_time.tzinfo is not None:
                raise ValueError()
        except (TypeError, ValueError):
            return jsonify({"error": "削除の取り消し情報が正しくありません。"}), 400

    try:
        notification = Notification.query.filter(
            Notification.id == index,
            Notification.company_code == company_code,
            Notification.target_username == username
        ).with_for_update().first()

        if not notification:
            return jsonify({"error": "通知が見つかりません。"}), 404

        if undo:
            if notification.deleted_at != deletion_time:
                return jsonify({"error": "この削除は取り消せません。"}), 409
            notification.deleted_at = None
            audit_action = "notification_delete_undone"
            audit_detail = "通知の削除を取り消し"
        else:
            if notification.deleted_at is not None:
                return jsonify({"error": "この通知は削除済みです。"}), 409
            notification.deleted_at = datetime.now(
                ZoneInfo("UTC")
            ).replace(tzinfo=None)
            audit_action = "notification_deleted"
            audit_detail = "通知を削除済みに移動"

        add_audit_log(
            action=audit_action,
            target_type="notification",
            target_id=notification.id,
            detail=f"{audit_detail}: {notification.title}",
            company_code=company_code,
        )
        db.session.flush()
        unread_count = get_unread_notification_count()
        inbox_count = Notification.query.filter(
            Notification.company_code == company_code,
            Notification.target_username == username,
            Notification.deleted_at.is_(None)
        ).count()
        deleted_at = notification.deleted_at
        db.session.commit()

        response = jsonify({
            "notification_id": index,
            "deleted_at": deleted_at.isoformat() if deleted_at else None,
            "read": bool(notification.read),
            "unread_count": unread_count,
            "inbox_count": inbox_count,
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("最近の通知の削除・取り消しに失敗しました。")
        return jsonify({
            "error": "通知を更新できませんでした。もう一度お試しください。"
        }), 500


@app.route("/notifications/<int:index>/delete", methods=["POST"])
@limiter.limit("20 per minute")
def delete_notification(index):
    current_view = request.args.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "inbox"

    back_url = url_for("notifications", **get_notification_list_state(current_view))

    notification = Notification.query.filter(
        Notification.id == index,
        Notification.company_code == session.get("company_code"),
        Notification.target_username == session.get("username")
    ).first()

    if not notification or notification.deleted_at is not None:
        return redirect(back_url)

    try:
        deleted_at = datetime.now(
            ZoneInfo("UTC")
        ).replace(tzinfo=None)

        notification.deleted_at = deleted_at

        add_audit_log(
            action="notification_deleted",
            target_type="notification",
            target_id=notification.id,
            detail=f"通知を削除済みに移動: {notification.title}",
            company_code=notification.company_code,
        )

        db.session.commit()

        flash(
            {
                "count": 1,
                "deleted_at": deleted_at.isoformat(),
                "view": current_view,
            },
            "notification_deleted"
        )

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("通知の削除処理に失敗しました。")
        flash(
            "通知を削除できませんでした。もう一度お試しください。",
            "error:"
        )

    return redirect(back_url)

@app.route("/notifications/<int:index>/restore", methods=["POST"])
@limiter.limit("20 per minute")
def restore_notification(index):
    current_view = request.args.get("view", "deleted")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "deleted"

    back_url = url_for("notifications", **get_notification_list_state(current_view))

    notification = Notification.query.filter(
        Notification.id == index,
        Notification.company_code == session.get("company_code"),
        Notification.target_username == session.get("username")
    ).first()

    if not notification or notification.deleted_at is None:
        return redirect(back_url)

    try:
        notification.deleted_at = None

        add_audit_log(
            action="notification_restored",
            target_type="notification",
            target_id=notification.id,
            detail=f"通知を受信箱へ復元: {notification.title}",
            company_code=notification.company_code,
        )

        db.session.commit()

        flash(
            "1件の通知を受信箱へ戻しました。",
            "notification_success"
        )

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("通知の復元処理に失敗しました。")
        flash(
            "通知を復元できませんでした。もう一度お試しください。",
            "error:"
        )

    return redirect(back_url)

@app.route("/notifications/bulk", methods=["POST"])
@limiter.limit("20 per minute")
def bulk_notifications():
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return redirect("/")

    current_view = request.form.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "inbox"

    back_url = url_for("notifications", **get_notification_list_state(current_view))

    action = request.form.get("action", "")
    action_labels = {
        "read": "既読にしました",
        "unread": "未読に戻しました",
        "delete": "削除済みに移動しました",
        "restore": "受信箱へ戻しました",
    }

    if action not in action_labels:
        flash("通知の操作を選択してください。", "error:")
        return redirect(back_url)

    try:
        notification_ids = list(dict.fromkeys(
            int(value)
            for value in request.form.getlist("notification_ids")
        ))
    except (ValueError, TypeError):
        flash("通知の選択内容が正しくありません。", "error:")
        return redirect(back_url)

    if (
        not notification_ids
        or any(
            value <= 0 or value > 2147483647
            for value in notification_ids
        )
    ):
        flash("操作する通知を選択してください。", "error:")
        return redirect(back_url)

    if len(notification_ids) > 500:
        flash("一度に操作できる通知は500件までです。", "error:")
        return redirect(back_url)

    try:
        records = Notification.query.filter(
            Notification.company_code == company_code,
            Notification.target_username == username,
            Notification.id.in_(notification_ids)
        ).order_by(
            Notification.id.asc()
        ).with_for_update().all()

        deleted_at = datetime.now(
            ZoneInfo("UTC")
        ).replace(tzinfo=None)

        changed_count = 0

        for notification in records:
            before = (
                notification.read,
                notification.deleted_at
            )

            if action == "read":
                if notification.deleted_at is not None:
                    continue
                notification.read = True

            elif action == "unread":
                notification.deleted_at = None
                notification.read = False

            elif action == "delete":
                if notification.deleted_at is not None:
                    continue
                notification.deleted_at = deleted_at

            elif action == "restore":
                notification.deleted_at = None

            after = (
                notification.read,
                notification.deleted_at
            )

            if before == after:
                continue

            changed_count += 1

            add_audit_log(
                action=f"notification_bulk_{action}",
                target_type="notification",
                target_id=notification.id,
                detail=f"通知の一括操作: {notification.title}",
                company_code=company_code,
            )

        db.session.commit()

        if action == "delete" and changed_count:
            flash(
                {
                    "count": changed_count,
                    "deleted_at": deleted_at.isoformat(),
                    "view": current_view,
                },
                "notification_deleted"
            )
        else:
            flash(
                f"{changed_count}件の通知を"
                f"{action_labels[action]}。",
                "notification_success"
            )

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("通知の一括操作に失敗しました。")
        flash(
            "通知を更新できませんでした。もう一度お試しください。",
            "error:"
        )

    return redirect(back_url)

@app.route("/notifications/read-all", methods=["POST"])
@limiter.limit("20 per minute")
def mark_all_notifications_read():
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return redirect("/")

    current_view = request.form.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action"):
        current_view = "inbox"

    back_url = url_for("notifications", **get_notification_list_state(current_view))

    try:
        records = Notification.query.filter(
            Notification.company_code == company_code,
            Notification.target_username == username,
            Notification.deleted_at.is_(None),
            db.or_(
                Notification.read.is_(False),
                Notification.read.is_(None)
            )
        ).order_by(
            Notification.id.asc()
        ).with_for_update().all()

        changed_count = len(records)

        for notification in records:
            notification.read = True

        if changed_count:
            add_audit_log(
                action="notification_read_all",
                target_type="notification",
                detail=f"受信箱の未読通知{changed_count}件を既読に変更",
                company_code=company_code,
            )

        db.session.commit()

        flash(
            f"{changed_count}件の通知を既読にしました。",
            "notification_success"
        )

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("通知の一括既読処理に失敗しました。")
        flash(
            "通知を既読にできませんでした。もう一度お試しください。",
            "error:"
        )

    return redirect(back_url)
@app.route("/notifications/undo-delete", methods=["POST"])
@limiter.limit("20 per minute")
def undo_notification_delete():
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return redirect("/")

    current_view = request.form.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "inbox"

    back_url = url_for("notifications", **get_notification_list_state(current_view))

    deletion_time = request.form.get("deleted_at", "")

    try:
        if not deletion_time or len(deletion_time) > 64:
            raise ValueError()

        deleted_at = datetime.fromisoformat(deletion_time)

        if deleted_at.tzinfo is not None:
            raise ValueError()

    except (ValueError, TypeError):
        flash(
            "削除の取り消し情報が正しくありません。",
            "error:"
        )
        return redirect(back_url)

    try:
        records = Notification.query.filter(
            Notification.company_code == company_code,
            Notification.target_username == username,
            Notification.deleted_at == deleted_at
        ).order_by(
            Notification.id.asc()
        ).with_for_update().all()

        restored_count = len(records)

        for notification in records:
            notification.deleted_at = None

            add_audit_log(
                action="notification_delete_undone",
                target_type="notification",
                target_id=notification.id,
                detail=f"通知の削除を取り消し: {notification.title}",
                company_code=company_code,
            )

        db.session.commit()

        flash(
            f"{restored_count}件の通知を受信箱へ戻しました。",
            "notification_success"
        )

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("通知の削除取り消しに失敗しました。")
        flash(
            "削除を取り消せませんでした。もう一度お試しください。",
            "error:"
        )

    return redirect(back_url)

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
        form_errors = []

        company_code = request.form.get(
            "company_code",
            ""
        ).strip()
        company_name = request.form.get(
            "company_name",
            ""
        ).strip()

        if not company_code:
            form_errors.append((
                "会社コードを入力してください。",
                "company_code"
            ))
        elif len(company_code) > 50:
            form_errors.append((
                "会社コードは50文字以内で入力してください。",
                "company_code"
            ))
        elif not re.fullmatch(
            r"[A-Za-z0-9_-]+",
            company_code
        ):
            form_errors.append((
                "会社コードは半角英数字・ハイフン・"
                "アンダースコアのみ使用できます。",
                "company_code"
            ))

        if not company_name:
            form_errors.append((
                "会社名を入力してください。",
                "company_name"
            ))
        elif len(company_name) > 100:
            form_errors.append((
                "会社名は100文字以内で入力してください。",
                "company_name"
            ))

        duplicate_company = Company.query.filter_by(
            company_code=company_code
        ).first()

        if duplicate_company:
            form_errors.append((
                "この会社コードはすでに登録されています。",
                "company_code"
            ))

        vehicle_limit = 0

        try:
            vehicle_limit = parse_nonnegative_int(
                request.form.get("vehicle_limit"),
                "車両上限数"
            )
        except UploadValidationError:
            form_errors.append((
                "車両上限数の入力内容を確認してください。",
                "vehicle_limit"
            ))

        if form_errors:
            return return_form_errors(
                form_errors,
                409 if duplicate_company else 400
            )

        company = Company(
            company_code=company_code,
            company_name=company_name,
            vehicle_limit=vehicle_limit,
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
        form_errors = []

        company_name = request.form.get(
            "company_name",
            ""
        ).strip()

        if not company_name:
            form_errors.append((
                "会社名を入力してください。",
                "company_name"
            ))
        elif len(company_name) > 100:
            form_errors.append((
                "会社名は100文字以内で入力してください。",
                "company_name"
            ))

        vehicle_limit = 0

        try:
            vehicle_limit = parse_nonnegative_int(
                request.form.get("vehicle_limit"),
                "車両上限数"
            )
        except UploadValidationError:
            form_errors.append((
                "車両上限数の入力内容を確認してください。",
                "vehicle_limit"
            ))

        if form_errors:
            return return_form_errors(form_errors)

        company.company_name = company_name
        company.vehicle_limit = vehicle_limit
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
    office_filter = request.args.get("office", "").strip()
    status_filter = request.args.get("status", "").strip()
    category = request.args.get("category", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    mine = request.args.get("mine") == "1"
    pending = request.args.get("pending") == "1"

    if len(keyword) > 100:
        return "検索条件が長すぎます。", 400

    for date_value in [date_from, date_to]:
        if not date_value:
            continue

        try:
            datetime.strptime(
                date_value,
                "%Y-%m-%d"
            )
        except ValueError:
            return "発生日の検索条件が不正です。", 400

    if (
        date_from
        and date_to
        and date_from > date_to
    ):
        return "発生日の開始日と終了日が不正です。", 400

    query = PatrolResult.query.filter(
        PatrolResult.company_code == session.get("company_code"),
        PatrolResult.target_type == view_type
    )

    if office_filter:
        query = query.filter(
            PatrolResult.office == office_filter
        )

    if status_filter == "not_started":
        query = query.filter(
            PatrolResult.category != "Good",
            PatrolResult.countermeasure == ""
        )
    elif status_filter == "waiting":
        query = query.filter(
            PatrolResult.category != "Good",
            PatrolResult.countermeasure != "",
            PatrolResult.approval_status == "承認待ち"
        )
    elif status_filter == "rejected":
        query = query.filter(
            PatrolResult.category != "Good",
            PatrolResult.approval_status == "差し戻し"
        )
    elif status_filter == "approved":
        query = query.filter(
            PatrolResult.category != "Good",
            PatrolResult.approval_status == "承認済み"
        )
    elif status_filter == "none":
        query = query.filter(
            PatrolResult.category == "Good"
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

    if date_from:
        query = query.filter(
            PatrolResult.date >= date_from
        )

    if date_to:
        query = query.filter(
            PatrolResult.date <= date_to
        )

    if keyword:
        keyword_like = f"%{keyword}%"

        keyword_filters = [
            PatrolResult.office.ilike(keyword_like),
            PatrolResult.content.ilike(keyword_like),
            PatrolResult.content_type.ilike(keyword_like),
        ]

        if view_type == "user":
            keyword_filters.append(
                PatrolResult.target_user.ilike(keyword_like)
            )
        elif view_type == "delivery_place":
            keyword_filters.append(
                PatrolResult.delivery_place.ilike(keyword_like)
            )

        query = query.filter(
            or_(*keyword_filters)
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
    allowed_page_sizes = {10, 20, 50}

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
        office_filter=office_filter,
        status_filter=status_filter,
        category_filter=category,
        date_from=date_from,
        date_to=date_to,
        role=role,
        show_target_user=view_type == "user",
        drivers=driver_options,
        offices=offices_for_current_company(),
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
            form_errors.append((
                "分類が不正です。",
                "category"
            ))

        if not date:
            form_errors.append((
                "発生日を入力してください。",
                "event_date"
            ))
        else:
            try:
                datetime.strptime(
                    date,
                    "%Y-%m-%d"
                )
            except ValueError:
                form_errors.append((
                    "発生日が不正です。",
                    "event_date"
                ))
        # =========================
        # 対象種別検証
        # =========================

        if target_type not in PATROL_VIEW_TYPES:
            form_errors.append((
                "対象種別が不正です。",
                "target_type"
            ))

        target_office = session.get("office") or ""

        # =========================
        # 対象ユーザー検証
        # =========================

        if target_type == "user":
            if not target_user:
                form_errors.append((
                    "対象ユーザーを選択してください。",
                    "target_user_search"
                ))
            else:
                target_driver = Driver.query.filter_by(
                    company_code=company_code,
                    employee_id=target_user
                ).first()

                if not target_driver:
                    form_errors.append((
                        "対象ユーザーが不正です。",
                        "target_user_search"
                    ))
                else:
                    target_user_record = User.query.filter_by(
                        company_code=company_code,
                        username=target_driver.employee_id
                    ).first()

                    if not target_user_record:
                        form_errors.append((
                            "対象ユーザー情報が不正です。",
                            "target_user_search"
                        ))
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
                form_errors.append((
                    "納入先を選択してください。",
                    "delivery_place"
                ))

            if delivery_place:
                valid_delivery_place = DeliveryPlace.query.filter_by(
                    company_code=company_code,
                    name=delivery_place
                ).first()

                if not valid_delivery_place:
                    form_errors.append((
                        "納入先が不正です。",
                        "delivery_place"
                    ))

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
                form_errors.append((
                    "内容区分が不正です。",
                    "content_type"
                ))

        if len(content) > 5000:
            form_errors.append((
                "内容は5000文字以内で入力してください。",
                "content_editor"
            ))

        if form_errors:
            return return_form_errors(form_errors)

        # =========================
        # 添付ファイル
        # =========================

        uploaded_files = [
            file
            for file in request.files.getlist("files")
            if file and file.filename
        ]

        file_names = []

        for file in uploaded_files:
            original_filename = os.path.basename(
                str(file.filename or "")
            )

            extension = os.path.splitext(
                original_filename
            )[1].lower()

            if (
                extension not in ALLOWED_UPLOAD_EXTENSIONS
                or not is_valid_uploaded_file(
                    file,
                    extension
                )
            ):
                return "添付ファイルの検証に失敗しました。", 400

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
    requested_target_type = request.args.get(
        "target_type",
        ""
    ).strip()

    form_target_type = session.pop(
        "pointout_form_target_type",
        (
            requested_target_type
            if requested_target_type in {
                "user",
                "delivery_place"
            }
            else "user"
        )
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

    countermeasure_form_data = session.pop(
        "countermeasure_form_data",
        {}
    )

    pointout_reject_form_data = session.pop(
        "pointout_reject_form_data",
        {}
    )

    return render_template(
        "pointout_detail.html",
        result=result,
        index=result_record.id,
        manuals=manuals_for_current_company(),
        drivers=drivers_for_current_company(),
        countermeasure_form_data=countermeasure_form_data,
        pointout_reject_form_data=pointout_reject_form_data,
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

    pointout_edit_form_data = session.pop(
        "pointout_edit_form_data",
        {}
    )

    if request.method == "POST":
        company_code = session.get("company_code")
        form_errors = []

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
            form_errors.append((
                "分類が不正です。",
                "category"
            ))

        if not date:
            form_errors.append((
                "発生日を入力してください。",
                "event_date"
            ))
        else:
            try:
                datetime.strptime(
                    date,
                    "%Y-%m-%d"
                )
            except ValueError:
                form_errors.append((
                    "発生日が不正です。",
                    "event_date"
                ))

        content_type = request.form.get(
            "content_type",
            ""
        ).strip()

        content = request.form.get(
            "content",
            ""
        ).strip()

        if len(content) > 5000:
            form_errors.append((
                "内容は5000文字以内で入力してください。",
                "content_editor"
            ))

        # =========================
        # 内容区分検証
        # =========================

        if content_type:
            valid_content_type = PatrolContentType.query.filter_by(
                company_code=company_code,
                name=content_type
            ).first()

            if not valid_content_type:
                form_errors.append((
                    "内容区分が不正です。",
                    "content_type"
                ))

        validated_target_user = result_record.target_user
        validated_target_username = result_record.target_username
        validated_office = result_record.office
        validated_delivery_place = result_record.delivery_place

        validated_target_user = result_record.target_user
        validated_target_username = result_record.target_username
        validated_office = result_record.office
        validated_delivery_place = result_record.delivery_place

        # =========================
        # 対象ユーザー検証
        # =========================

        if result_record.target_type == "user":
            target_username = request.form.get(
                "target_user",
                ""
            ).strip()

            if not target_username:
                form_errors.append((
                    "対象ユーザーを選択してください。",
                    "target_user_search"
                ))
            else:
                target_driver = Driver.query.filter_by(
                    company_code=company_code,
                    employee_id=target_username
                ).first()

                if not target_driver:
                    form_errors.append((
                        "対象ユーザーが不正です。",
                        "target_user_search"
                    ))
                else:
                    target_user_record = User.query.filter_by(
                        company_code=company_code,
                        username=target_driver.employee_id
                    ).first()

                    if not target_user_record:
                        form_errors.append((
                            "対象ユーザー情報が不正です。",
                            "target_user_search"
                        ))
                    else:
                        validated_target_user = (
                            target_driver.name
                        )
                        validated_target_username = (
                            target_user_record.username
                        )
                        validated_office = (
                            target_driver.office or ""
                        )
                        validated_delivery_place = ""

        # =========================
        # 納入先検証
        # =========================

        elif result_record.target_type == "delivery_place":
            delivery_place = request.form.get(
                "delivery_place",
                ""
            ).strip()

            if not delivery_place:
                form_errors.append(
                    "納入先を選択してください。"
                )
            else:
                valid_delivery_place = DeliveryPlace.query.filter_by(
                    company_code=company_code,
                    name=delivery_place
                ).first()

                if not valid_delivery_place:
                    form_errors.append((
                        "納入先が不正です。",
                        "delivery_place"
                    ))
                else:
                    validated_delivery_place = delivery_place
                    validated_target_user = ""
                    validated_target_username = ""

        else:
            return "対象種別が不正です。", 400

        if form_errors:
            return return_form_errors(form_errors)

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

        uploaded_files = [
            file
            for file in request.files.getlist(
                "files"
            )
            if file and file.filename
        ]

        for file in uploaded_files:
            original_filename = os.path.basename(
                str(file.filename or "")
            )

            extension = os.path.splitext(
                original_filename
            )[1].lower()

            if (
                extension not in ALLOWED_UPLOAD_EXTENSIONS
                or not is_valid_uploaded_file(
                    file,
                    extension
                )
            ):
                return "添付ファイルの検証に失敗しました。入力内容を確認してください。", 400

        for file in uploaded_files:
            filename = save_uploaded_file(file)

            if filename:
                files.append(filename)

        result_record.date = date
        result_record.category = category
        result_record.content_type = content_type
        result_record.content = content
        result_record.target_user = validated_target_user
        result_record.target_username = validated_target_username
        result_record.office = validated_office
        result_record.delivery_place = validated_delivery_place

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
        pointout_edit_form_data=pointout_edit_form_data,
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

    form_errors = []

    countermeasure = request.form.get(
        "countermeasure",
        ""
    ).strip()

    if not countermeasure:
        form_errors.append((
            "対策内容を入力してください。",
            "countermeasure"
        ))
    elif len(countermeasure) > 5000:
        form_errors.append((
            "対策内容は5000文字以内で入力してください。",
            "countermeasure"
        ))

    countermeasure_by_employee_id = request.form.get(
        "countermeasure_by",
        ""
    ).strip()

    countermeasure_driver = None
    countermeasure_user = None

    if not countermeasure_by_employee_id:
        form_errors.append((
            "対応者を選択してください。",
            "countermeasure_by_search"
        ))
    else:
        countermeasure_driver = Driver.query.filter_by(
            company_code=result_record.company_code,
            employee_id=countermeasure_by_employee_id
        ).first()

        if not countermeasure_driver:
            form_errors.append((
                "対応者が不正です。",
                "countermeasure_by_search"
            ))
        else:
            countermeasure_user = User.query.filter_by(
                company_code=result_record.company_code,
                username=countermeasure_driver.employee_id
            ).first()

            if not countermeasure_user:
                form_errors.append((
                    "対応者情報が不正です。",
                    "countermeasure_by_search"
                ))

    countermeasure_due_date = request.form.get(
        "countermeasure_due_date",
        ""
    ).strip()

    if countermeasure_due_date:
        try:
            datetime.strptime(
                countermeasure_due_date,
                "%Y-%m-%d"
            )
        except ValueError:
            form_errors.append((
                "対応期限が不正です。",
                "countermeasure_due_date"
            ))

    if form_errors:
        session["countermeasure_form_data"] = {
            "countermeasure": request.form.get(
                "countermeasure",
                ""
            ),
            "countermeasure_by": request.form.get(
                "countermeasure_by",
                ""
            ),
            "countermeasure_by_search": request.form.get(
                "countermeasure_by_search",
                ""
            ),
            "countermeasure_by_username": request.form.get(
                "countermeasure_by_username",
                ""
            ),
            "countermeasure_due_date": request.form.get(
                "countermeasure_due_date",
                ""
            ),
        }

        for message in form_errors:
            flash(
                message,
                f"error:{get_form_error_field(message) or ''}"
            )

        if result_record.countermeasure:
            return redirect(
                f"/pointouts/{result_record.id}?edit_countermeasure=1"
            )

        return redirect(
            f"/pointouts/{result_record.id}"
        )

    countermeasure_files = safe_json_str_list(
        result_record.countermeasure_files_json
    )

    delete_countermeasure_files = request.form.getlist(
        "delete_countermeasure_files"
    )

    if len(delete_countermeasure_files) > 50:
        return (
            "一度に削除できる添付ファイルは50件までです。",
            400
        )

    pending_delete_countermeasure_files = []

    for delete_file in delete_countermeasure_files:
        delete_file = os.path.basename(
            delete_file
        )

        if delete_file not in countermeasure_files:
            continue

        countermeasure_files.remove(delete_file)

        pending_delete_countermeasure_files.append(
            delete_file
        )

    uploaded_countermeasure_files = [
        file
        for file in request.files.getlist(
            "countermeasure_files"
        )
        if file and file.filename
    ]

    for file in uploaded_countermeasure_files:
        original_filename = os.path.basename(
            str(file.filename or "")
        )

        extension = os.path.splitext(
            original_filename
        )[1].lower()

        if (
            extension not in ALLOWED_UPLOAD_EXTENSIONS
            or not is_valid_uploaded_file(
                file,
                extension
            )
        ):
            return "添付ファイルの検証に失敗しました。", 400

    for file in uploaded_countermeasure_files:
        try:
            saved_file = save_uploaded_file(file)
        except UploadValidationError:
            return "添付ファイルの検証に失敗しました。", 400

        if saved_file:
            countermeasure_files.append(saved_file)

    result_record.countermeasure = countermeasure

    result_record.countermeasure_files_json = json.dumps(
        countermeasure_files,
        ensure_ascii=False
    )

    result_record.countermeasure_by = (
        countermeasure_driver.name
    )

    result_record.countermeasure_by_username = (
        countermeasure_user.username
    )

    result_record.countermeasure_due_date = (
        countermeasure_due_date
    )

    result_record.approval_status = "承認待ち"
    result_record.reject_reason = ""

    db.session.commit()

    for delete_file in pending_delete_countermeasure_files:
        deleted = False

        if s3_client and S3_BUCKET_NAME:
            try:
                s3_client.delete_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=(
                        f"uploads/"
                        f"{result_record.company_code}/"
                        f"{delete_file}"
                    )
                )
                deleted = True
            except ClientError:
                print(
                    "S3対策添付ファイル削除エラー"
                )
        else:
            safe_file_name = secure_filename(
                delete_file
            )

            if not safe_file_name:
                continue

            file_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                result_record.company_code,
                safe_file_name
            )

            if os.path.exists(file_path):
                os.remove(file_path)
                deleted = True

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
            (target_user.last_name or "") + (target_user.first_name or ""),
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

    if not reject_reason:
        return "差し戻し理由を入力してください。", 400

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
            (target_user.last_name or "") + (target_user.first_name or ""),
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

    files_to_delete = (
        safe_json_str_list(
            result_record.files_json
        )
        + safe_json_str_list(
            result_record.countermeasure_files_json
        )
    )

    add_audit_log(
        action="patrol_result_deleted",
        target_type="patrol_result",
        target_id=result_record.id,
        detail=f"安全パトロール結果削除: target_type={view_type}",
        company_code=result_record.company_code,
    )

    company_code = result_record.company_code

    db.session.delete(result_record)
    db.session.commit()

    for filename in files_to_delete:
        filename = os.path.basename(
            str(filename or "")
        )

        if not filename:
            continue

        still_referenced = False

        checklist_results = ChecklistResult.query.filter_by(
            company_code=company_code
        ).all()

        for checklist_result in checklist_results:
            answers = safe_json_dict_list(
                checklist_result.answers_json
            )

            if any(
                filename in answer.get("files", [])
                for answer in answers
            ):
                still_referenced = True
                break

        if still_referenced:
            continue

        if s3_client and S3_BUCKET_NAME:
            try:
                s3_client.delete_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=(
                        f"uploads/"
                        f"{company_code}/"
                        f"{filename}"
                    )
                )
            except ClientError:
                app.logger.warning(
                    "安全パトロール添付ファイルのS3削除に失敗しました。",
                    exc_info=True
                )
        else:
            safe_filename = secure_filename(
                filename
            )

            if not safe_filename:
                continue

            file_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                company_code,
                safe_filename
            )

            if os.path.exists(file_path):
                os.remove(file_path)

    return redirect(f"/pointouts?type={view_type}")

@app.route("/vehicle-patrols/new", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
def new_vehicle_patrol():

    if request.method == "POST":
        form_errors = []

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
            form_errors.append((
                "車両が不正です。",
                "vehicle_record_id"
            ))

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
            form_errors.append((
                "分類が不正です。",
                "category"
            ))

        if priority not in {
            "高",
            "中",
            "低"
        }:
            form_errors.append((
                "重要度が不正です。",
                "priority"
            ))

        if status not in {
            "未対応",
            "対応中",
            "修理完了"
        }:
            form_errors.append((
                "状態が不正です。",
                "status"
            ))
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
            form_errors.append((
                "修理担当者は100文字以内で入力してください。",
                "repair_person"
            ))

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
            except UploadValidationError:
                return "修理時間の入力内容を確認してください。", 400

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
            "/" if request.form.get("next") == "/" else "/vehicle-patrols"
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
        "/" if request.form.get("next") == "/" else "/vehicle-patrols"
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
            "/" if request.form.get("next") == "/" else "/vehicle-patrols"
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
        "/" if request.form.get("next") == "/" else "/vehicle-patrols"
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
        form_errors = []

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
            form_errors.append((
                "状態が不正です。",
                "status"
            ))
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
            form_errors.append((
                "修理担当者は100文字以内で入力してください。",
                "repair_person"
            ))
        
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
                    form_errors.append((
                        f"{field_name}が不正です。",
                        "occurred_date" if field_name == "発生日" else "repair_date"
                    ))

        if repair_time:
            try:
                repair_time = parse_time_hhmm(
                    repair_time,
                    "修理時間"
                )
            except UploadValidationError:
                return "修理時間の入力内容を確認してください。", 400

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

@app.route("/master")
def master():
    return redirect("/master/drivers")

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
        vehicle_record_ids = safe_json_str_list(
            driver.vehicles_json
        )

        vehicle_records = Vehicle.query.filter(
            Vehicle.company_code == driver.company_code,
            Vehicle.id.in_([
                int(vehicle_id)
                for vehicle_id in vehicle_record_ids
                if str(vehicle_id).isdigit()
            ])
        ).all()

        vehicle_map = {
            str(vehicle.id): vehicle
            for vehicle in vehicle_records
        }

        vehicle_labels = []

        for vehicle_id in vehicle_record_ids:
            vehicle_record = vehicle_map.get(
                str(vehicle_id)
            )

            if not vehicle_record:
                continue

            plate = " ".join(
                filter(
                    None,
                    [
                        vehicle_record.plate_area,
                        vehicle_record.plate_class,
                        vehicle_record.plate_kana,
                        vehicle_record.plate_number,
                    ]
                )
            )

            vehicle_labels.append(
                plate or "ナンバー未登録"
            )

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
            "vehicles": vehicle_labels,
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
        form_errors = []

        employee_id = request.form.get(
            "employee_id",
            ""
        ).strip()

        last_name = request.form.get(
            "last_name",
            ""
        ).strip()

        first_name = request.form.get(
            "first_name",
            ""
        ).strip()

        name = last_name + first_name

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
            form_errors.append((
                "選択車両数が多すぎます。",
                "selected_vehicles"
            ))

        # =========================
        # 基本入力チェック
        # =========================

        if not employee_id:
            form_errors.append((
                "ログインIDを入力してください。",
                "employee_id"
            ))
        elif len(employee_id) > 50:
            form_errors.append((
                "ログインIDは50文字以内で入力してください。",
                "employee_id"
            ))

        if not last_name:
            form_errors.append((
                "姓を入力してください。",
                "last_name"
            ))
        elif len(last_name) > 100:
            form_errors.append((
                "姓は100文字以内で入力してください。",
                "last_name"
            ))

        if len(first_name) > 100:
            form_errors.append((
                "名は100文字以内で入力してください。",
                "first_name"
            ))

        if email_address and not is_valid_email_address(
            email_address
        ):
            form_errors.append((
                "メールアドレスの形式が不正です。",
                "email_address"
            ))

        if not password:
            form_errors.append((
                "パスワードを入力してください。",
                "password"
            ))
        elif len(password) < 8:
            form_errors.append((
                "パスワードは8文字以上にしてください。",
                "password"
            ))
        elif len(password) > 128:
            form_errors.append((
                "パスワードは128文字以内にしてください。",
                "password"
            ))
        elif password_type_count < 3:
            form_errors.append((
                "パスワードは英大文字・英小文字・数字・記号の"
                "うち3種類以上を使用してください。",
                "password"
            ))

        # =========================
        # ロール検証
        # =========================

        if role not in ["admin", "user"]:
            form_errors.append((
                "ユーザー種別が不正です。",
                "role"
            ))
        if safe_start_date:
            try:
                datetime.strptime(
                    safe_start_date,
                    "%Y-%m-%d"
                )
            except ValueError:
                form_errors.append((
                    "無事故開始日が不正です。",
                    "safe_start_date"
                ))

        # =========================
        # ログインID重複確認
        # =========================

        if User.query.filter_by(
            company_code=company_code,
            username=employee_id
        ).first():
            form_errors.append((
                "このログインIDはすでに使用されています。",
                "employee_id"
            ))

        # =========================
        # 営業所検証
        # =========================

        if office:
            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=office
            ).first()

            if not valid_office:
                form_errors.append((
                    "営業所が不正です。",
                    "office"
                ))

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
                form_errors.append((
                    "選択された車両が不正です。",
                    "selected_vehicles"
                ))
                break

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
            form_errors.append((
                "免許情報の件数が多すぎます。",
                "license_area"
            ))

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

            license_has_error = False

            if license_type not in valid_license_types:
                form_errors.append((
                    "免許種別が不正です。",
                    "license_area"
                ))
                license_has_error = True

            if expiry:
                try:
                    datetime.strptime(
                        expiry,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    form_errors.append((
                        "免許有効期限が不正です。",
                        "license_area"
                    ))
                    license_has_error = True

            if not license_has_error:
                licenses.append({
                    "type": license_type,
                    "expiry": expiry
                })

        if form_errors:
            return return_form_errors(form_errors)

        # =========================
        # Driver作成
        # =========================

        driver = Driver(
            company_code=company_code,
            employee_id=employee_id,
            name=(last_name or "") + (first_name or ""),
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
            last_name=last_name,
            first_name=first_name or None,
            office=office,
            email_address=email_address or None,
            email_notify_enabled=bool(email_address)
        )

        db.session.add(user)
        db.session.add(driver)
        db.session.commit()

        return redirect("/master/drivers")

    driver_form_data = session.pop(
        "driver_form_data",
        {}
    )

    form_driver = None

    if driver_form_data:
        form_driver = {
            "employee_id": driver_form_data.get(
                "employee_id",
                ""
            ),
            "last_name": driver_form_data.get(
                "last_name",
                ""
            ),
            "first_name": driver_form_data.get(
                "first_name",
                ""
            ),
            "name": (
                driver_form_data.get("last_name", "")
                + driver_form_data.get("first_name", "")
            ),
            "email_address": driver_form_data.get(
                "email_address",
                ""
            ),
            "role": driver_form_data.get(
                "role",
                "user"
            ),
            "office": driver_form_data.get(
                "office",
                ""
            ),
            "safe_start_date": driver_form_data.get(
                "safe_start_date",
                ""
            ),
            "licenses": [
                {
                    "type": license_type,
                    "expiry": expiry
                }
                for license_type, expiry in zip(
                    driver_form_data.get(
                        "license_type",
                        []
                    ),
                    driver_form_data.get(
                        "license_expiry",
                        []
                    )
                )
            ],
        }

    selected_vehicles = []

    selected_vehicle_record_ids = [
        int(vehicle_record_id)
        for vehicle_record_id in driver_form_data.get(
            "vehicles",
            []
        )
        if str(vehicle_record_id).isdigit()
    ]

    if selected_vehicle_record_ids:
        selected_vehicle_records = Vehicle.query.filter(
            Vehicle.company_code == company_code,
            Vehicle.id.in_(selected_vehicle_record_ids),
            Vehicle.deleted == False
        ).all()

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
        driver=form_driver,
        offices=offices_for_current_company(),
        selected_vehicles=selected_vehicles,
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
        form_errors = []

        company_code = driver.company_code

        old_employee_id = driver.employee_id

        new_employee_id = request.form.get(
            "employee_id",
            ""
        ).strip()

        last_name = request.form.get(
            "last_name",
            ""
        ).strip()

        first_name = request.form.get(
            "first_name",
            ""
        ).strip()

        name = last_name + first_name

        email_address = request.form.get(
            "email_address",
            ""
        ).strip().lower()

        role = request.form.get(
            "role",
            "user"
        ).strip()

        existing_user = User.query.filter_by(
            company_code=company_code,
            username=old_employee_id
        ).first()

        if existing_user and existing_user.role == "itc":
            role = "itc"

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
            form_errors.append((
                "選択車両数が多すぎます。",
                "selected_vehicles"
            ))

        # =========================
        # 基本入力チェック
        # =========================

        if not new_employee_id:
            form_errors.append((
                "ログインIDを入力してください。",
                "employee_id"
            ))
        elif len(new_employee_id) > 50:
            form_errors.append((
                "ログインIDは50文字以内で入力してください。",
                "employee_id"
            ))
        elif new_employee_id != old_employee_id:
            form_errors.append((
                "ログインIDは作成後に変更できません。",
                "employee_id"
            ))

        if not last_name:
            form_errors.append((
                "姓を入力してください。",
                "last_name"
            ))
        elif len(last_name) > 100:
            form_errors.append((
                "姓は100文字以内で入力してください。",
                "last_name"
            ))

        if len(first_name) > 100:
            form_errors.append((
                "名は100文字以内で入力してください。",
                "first_name"
            ))

        if email_address and not is_valid_email_address(
            email_address
        ):
            form_errors.append((
                "メールアドレスの形式が不正です。",
                "email_address"
            ))

        if new_password:
            if len(new_password) < 8:
                form_errors.append((
                    "パスワードは8文字以上にしてください。",
                    "password"
                ))
            elif len(new_password) > 128:
                form_errors.append((
                    "パスワードは128文字以内にしてください。",
                    "password"
                ))
            elif password_type_count < 3:
                form_errors.append((
                    "パスワードは英大文字・英小文字・数字・記号の"
                    "うち3種類以上を使用してください。",
                    "password"
                ))

        # =========================
        # ロール検証
        # =========================

        if role not in ["admin", "user", "itc"]:
            form_errors.append((
                "ユーザー種別が不正です。",
                "role"
            ))
        if safe_start_date:
            try:
                datetime.strptime(
                    safe_start_date,
                    "%Y-%m-%d"
                )
            except ValueError:
                form_errors.append((
                    "無事故開始日が不正です。",
                    "safe_start_date"
                ))

        # =========================
        # ログインID重複確認
        # =========================

        if new_employee_id != old_employee_id:
            existing_user = User.query.filter_by(
                company_code=company_code,
                username=new_employee_id
            ).first()

            if existing_user:
                form_errors.append((
                    "このログインIDはすでに使用されています。",
                    "employee_id"
                ))

        # =========================
        # 営業所検証
        # =========================

        if office:
            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=office
            ).first()

            if not valid_office:
                form_errors.append((
                    "営業所が不正です。",
                    "office"
                ))

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
                form_errors.append((
                    "選択された車両が不正です。",
                    "selected_vehicles"
                ))
                break

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
            form_errors.append((
                "免許情報の件数が多すぎます。",
                "license_area"
            ))

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

            license_has_error = False

            if license_type not in valid_license_types:
                form_errors.append((
                    "免許種別が不正です。",
                    "license_area"
                ))
                license_has_error = True

            if expiry:
                try:
                    datetime.strptime(
                        expiry,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    form_errors.append((
                        "免許有効期限が不正です。",
                        "license_area"
                    ))
                    license_has_error = True

            if not license_has_error:
                licenses.append({
                    "type": license_type,
                    "expiry": expiry
                })

        if form_errors:
            return return_form_errors(form_errors)

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
                return return_form_errors([
                    "ユーザー情報が見つかりません。"
                    "再作成するためパスワードを入力してください。"
                ])

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
                last_name=last_name,
                first_name=first_name or None,
                office=office,
                email_address=email_address or None,
                email_notify_enabled=bool(email_address),

            )

            db.session.add(user)

        else:
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
                    return return_form_errors([
                        (
                            "現在または過去5回以内に使用した"
                            "パスワードは使用できません。",
                            "password"
                        )
                    ])

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

            user.username = new_employee_id
            user.role = role
            user.last_name = last_name
            user.first_name = first_name or None
            user.office = office
            user.email_address = email_address or None
            user.email_notify_enabled = bool(email_address)

        # =========================
        # Driver更新
        # =========================

        driver.employee_id = new_employee_id
        driver.name = (last_name or "") + (first_name or "")
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

    user = User.query.filter_by(
        company_code=driver.company_code,
        username=driver.employee_id
    ).first()

    driver_dict["last_name"] = (
        user.last_name if user else ""
    )
    driver_dict["first_name"] = (
        user.first_name if user else ""
    )

    driver_edit_form_data = session.pop(
        "driver_edit_form_data",
        {}
    )

    if driver_edit_form_data:
        driver_dict.update({
            "employee_id": driver_edit_form_data.get(
                "employee_id",
                driver_dict["employee_id"]
            ),
            "last_name": driver_edit_form_data.get(
                "last_name",
                driver_dict.get("last_name", "")
            ),
            "first_name": driver_edit_form_data.get(
                "first_name",
                driver_dict.get("first_name", "")
            ),
            "name": (
                driver_edit_form_data.get("last_name", "")
                + driver_edit_form_data.get("first_name", "")
            ) or driver_dict["name"],
            "email_address": driver_edit_form_data.get(
                "email_address",
                driver_dict["email_address"]
            ),
            "role": driver_edit_form_data.get(
                "role",
                driver_dict["role"]
            ),
            "office": driver_edit_form_data.get(
                "office",
                driver_dict["office"]
            ),
            "safe_start_date": driver_edit_form_data.get(
                "safe_start_date",
                driver_dict["safe_start_date"]
            ),
            "vehicles": driver_edit_form_data.get(
                "vehicles",
                driver_dict["vehicles"]
            ),
            "licenses": [
                {
                    "type": license_type,
                    "expiry": expiry
                }
                for license_type, expiry in zip(
                    driver_edit_form_data.get(
                        "license_type",
                        []
                    ),
                    driver_edit_form_data.get(
                        "license_expiry",
                        []
                    )
                )
            ],
        })


    selected_vehicle_records = []

    if driver_edit_form_data:
        driver_dict["vehicles"] = driver_edit_form_data.get(
            "vehicles",
            driver_dict["vehicles"]
        )

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

def build_vehicle_document_record(
    draft,
    record_index,
    values
):
    mileage = (
        Decimal(values["mileage"])
        if values.get("mileage") is not None
        else None
    )

    if draft.document_type == "inspection":
        return VehiclePeriodicInspectionRecord(
            company_code=draft.company_code,
            vehicle_record_id=values["vehicle_record_id"],
            inspection_type=values["inspection_type"],
            inspection_date=values["record_date"],
            mileage=mileage,
            content=values["content"],
            details_json=json.dumps(
                values,
                ensure_ascii=False
            ),
            source_draft_id=draft.id,
            source_record_index=record_index,
            created_by_username=session.get("username")
        )

    if draft.document_type == "driving_report":
        return VehicleDrivingReportRecord(
            company_code=draft.company_code,
            vehicle_record_id=values["vehicle_record_id"],
            operation_date=values["record_date"],
            mileage=mileage,
            content=values["content"],
            details_json=json.dumps(
                values,
                ensure_ascii=False
            ),
            source_draft_id=draft.id,
            source_record_index=record_index,
            created_by_username=session.get("username")
        )

    if draft.document_type == "maintenance":
        return VehicleMaintenanceRecord(
            company_code=draft.company_code,
            vehicle_record_id=values["vehicle_record_id"],
            entry_date=values["record_date"],
            mileage=mileage,
            content=values["content"],
            created_by_username=session.get("username"),
            created_at=datetime.now(
                ZoneInfo("Asia/Tokyo")
            ).isoformat(timespec="seconds")
        )

    raise ValueError("資料の種類が不正です。")


def validate_vehicle_document_record(
    draft,
    record_index,
    original_record,
    form
):
    row_key = f"{draft.id}_{record_index}"
    values = dict(original_record)
    errors = []

    vehicle_value = form.get(
        f"vehicle_{row_key}", ""
    ).strip()
    record_date = form.get(
        f"date_{row_key}", ""
    ).strip()
    mileage_text = form.get(
        f"mileage_{row_key}", ""
    ).strip()
    content = form.get(
        f"content_{row_key}", ""
    ).strip()

    values.update({
        "vehicle_record_id": vehicle_value,
        "record_date": record_date,
        "mileage": mileage_text or None,
        "content": content
    })

    try:
        vehicle_id = int(vehicle_value)

        if not 0 < vehicle_id <= 9223372036854775807:
            raise ValueError

        vehicle = Vehicle.query.filter_by(
            id=vehicle_id,
            company_code=draft.company_code
        ).first()

        if vehicle is None:
            raise ValueError

        values["vehicle_record_id"] = vehicle.id
    except (ValueError, TypeError):
        errors.append((
            "同じ会社の対象車両を選択してください。",
            f"vehicle_{row_key}"
        ))

    try:
        parsed_date = datetime.strptime(
            record_date, "%Y-%m-%d"
        )

        if parsed_date.strftime("%Y-%m-%d") != record_date:
            raise ValueError
    except ValueError:
        errors.append((
            "記録の日付を正しく入力してください。",
            f"date_{row_key}"
        ))

    if mileage_text:
        try:
            mileage = Decimal(mileage_text)

            if (
                not mileage.is_finite()
                or mileage < 0
                or mileage > Decimal("999999999999.99")
                or mileage != mileage.quantize(Decimal("0.01"))
            ):
                raise ValueError

            values["mileage"] = format(mileage, ".2f")
        except (InvalidOperation, ValueError):
            errors.append((
                "積算走行距離は0以上、小数点以下2桁までで入力してください。",
                f"mileage_{row_key}"
            ))

    if len(content) > 5000:
        errors.append((
            "記録内容は5000文字以内で入力してください。",
            f"content_{row_key}"
        ))

    if draft.document_type == "inspection":
        inspection_type = form.get(
            f"inspection_type_{row_key}", ""
        ).strip()
        values["inspection_type"] = inspection_type

        if inspection_type not in {
            "3month", "12month", "other"
        }:
            errors.append((
                "点検区分を選択してください。",
                f"inspection_type_{row_key}"
            ))

    return values, errors


def prepare_vehicle_document_import(files, document_type):
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return [], [
            ("ログイン情報を確認してください。", "")
        ]

    if document_type not in {
        "inspection",
        "driving_report",
        "maintenance"
    }:
        return [], [
            ("資料の種類を選択してください。", "document_type")
        ]

    uploaded_files = [
        file
        for file in files
        if file and file.filename
    ]

    if not uploaded_files:
        return [], [
            ("ファイルを選択してください。", "document_files")
        ]

    if len(uploaded_files) > 50:
        return [], [
            (
                "1回に取り込めるファイルは50件までです。",
                "document_files"
            )
        ]

    batch_id = str(uuid4())
    drafts = []
    errors = []

    for file in uploaded_files:
        filename = os.path.basename(
            file.filename.replace("\\", "/")
        )
        extension = os.path.splitext(filename)[1].lower()

        if not filename or len(filename) > 255:
            errors.append((
                "ファイル名は1～255文字にしてください。",
                "document_files"
            ))
            continue

        if extension not in {".pdf", ".png", ".jpg", ".jpeg"}:
            errors.append((
                f"{filename}：PDF・PNG・JPEGを選択してください。",
                "document_files"
            ))
            continue

        if not is_valid_uploaded_file(file, extension):
            errors.append((
                f"{filename}：ファイルの内容が不正です。",
                "document_files"
            ))
            continue

        try:
            file.stream.seek(0)
            source_file = file.read()
        except (OSError, ValueError):
            errors.append((
                f"{filename}：ファイルを読み込めませんでした。",
                "document_files"
            ))
            continue

        if not source_file:
            errors.append((
                f"{filename}：ファイルが空です。",
                "document_files"
            ))
            continue

        drafts.append(VehicleDocumentImportDraft(
            id=str(uuid4()),
            batch_id=batch_id,
            company_code=company_code,
            created_by_username=username,
            document_type=document_type,
            source_filename=filename,
            source_file=source_file,
            source_sha256=hashlib.sha256(
                source_file
            ).hexdigest()
        ))

    if errors:
        return [], errors

    return drafts, []


@app.route(
    "/vehicle/data-import",
    methods=["GET", "POST"]
)
def vehicle_data_import():
    if not require_master_admin():
        return redirect(url_for("vehicle_karte_list"))

    if request.method == "GET":
        return render_template(
            "vehicle_data_import.html"
        )

    drafts, errors = prepare_vehicle_document_import(
        request.files.getlist("document_files"),
        request.form.get("document_type", "")
    )

    if errors:
        return return_form_errors(errors)

    if request.headers.get("X-DKSS-Validation-Only") == "1":
        return jsonify({"ok": True})

    try:
        db.session.add_all(drafts)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception(
            "資料取り込みの確認用データを保存できませんでした"
        )
        return return_form_errors(
            [(
                "資料を保存できませんでした。もう一度お試しください。",
                "document_files"
            )],
            status_code=500
        )

    return redirect(url_for(
        "vehicle_document_import_preview",
        batch_id=drafts[0].batch_id
    ))


@app.route(
    "/vehicle/data-import/<batch_id>/confirm",
    methods=["POST"]
)
@limiter.limit("10 per minute")
def vehicle_document_import_confirm(batch_id):
    if not require_master_admin():
        return return_form_errors(
            [("この操作を行う権限がありません。", "")],
            status_code=403
        )

    validation_only = (
        request.headers.get("X-DKSS-Validation-Only") == "1"
    )

    query = VehicleDocumentImportDraft.query.filter_by(
        batch_id=batch_id,
        company_code=session.get("company_code"),
        created_by_username=session.get("username")
    )

    if not validation_only:
        query = query.with_for_update()

    drafts = query.order_by(
        VehicleDocumentImportDraft.id
    ).all()

    if not drafts:
        raise NotFound()

    if any(draft.status != "preview" for draft in drafts):
        return return_form_errors(
            [(
                "この資料の取り込み確認は終了しています。",
                ""
            )],
            status_code=409
        )

    included = set(request.form.getlist("include"))
    known_keys = set()
    submissions = []
    previews = {}
    errors = []

    for draft in drafts:
        preview = safe_json_dict(draft.preview_json)
        original_records = preview.get("records")

        if original_records is None:
            original_records = [{}]

        if (
            not isinstance(original_records, list)
            or not original_records
            or not all(
                isinstance(record, dict)
                for record in original_records
            )
        ):
            errors.append((
                f"{draft.source_filename}：確認データを取得できませんでした。",
                ""
            ))
            continue

        updated_records = []

        for record_index, original_record in enumerate(
            original_records
        ):
            row_key = f"{draft.id}_{record_index}"
            known_keys.add(row_key)

            values, row_errors = validate_vehicle_document_record(
                draft,
                record_index,
                original_record,
                request.form
            )
            values["include"] = row_key in included
            updated_records.append(values)

            if row_key not in included:
                continue

            errors.extend(row_errors)

            if not row_errors:
                submissions.append((
                    draft,
                    record_index,
                    values
                ))

        preview["records"] = updated_records
        previews[draft.id] = preview

    if included - known_keys:
        errors.append((
            "取り込み対象が不正です。画面を再読み込みしてください。",
            ""
        ))

    if not included:
        errors.append((
            "取り込む記録を選択してください。",
            ""
        ))

    if errors:
        if not validation_only:
            try:
                for draft in drafts:
                    if draft.id in previews:
                        draft.preview_json = json.dumps(
                            previews[draft.id],
                            ensure_ascii=False
                        )

                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.exception(
                    "資料取り込みの編集内容を保持できませんでした"
                )
                return return_form_errors(
                    [(
                        "編集内容を保存できませんでした。もう一度お試しください。",
                        ""
                    )],
                    status_code=500
                )

        return return_form_errors(errors)

    if validation_only:
        return jsonify({"ok": True})

    try:
        saved_preview_count = 0

        for draft_id, preview in previews.items():
            saved_preview_count += (
                VehicleDocumentImportDraft.query
                .filter_by(
                    id=draft_id,
                    batch_id=batch_id,
                    company_code=session.get("company_code"),
                    created_by_username=session.get("username"),
                    status="preview"
                )
                .update(
                    {
                        "preview_json": json.dumps(
                            preview,
                            ensure_ascii=False
                        )
                    },
                    synchronize_session=False
                )
            )

        if saved_preview_count != len(drafts):
            db.session.rollback()
            return return_form_errors(
                [(
                    "この資料はすでに処理されています。取り込み結果を確認してください。",
                    ""
                )],
                status_code=409
            )

        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception(
            "資料取り込みの編集内容を保存できませんでした"
        )
        return return_form_errors(
            [(
                "編集内容を保存できませんでした。もう一度お試しください。",
                ""
            )],
            status_code=500
        )

    try:
        claimed_count = (
            VehicleDocumentImportDraft.query
            .filter(
                VehicleDocumentImportDraft.id.in_(
                    [draft.id for draft in drafts]
                ),
                VehicleDocumentImportDraft.company_code
                == session.get("company_code"),
                VehicleDocumentImportDraft.created_by_username
                == session.get("username"),
                VehicleDocumentImportDraft.status == "preview"
            )
            .update(
                {"status": "processing"},
                synchronize_session=False
            )
        )

        if claimed_count != len(drafts):
            db.session.rollback()
            return return_form_errors(
                [(
                    "この資料はすでに処理されています。取り込み結果を確認してください。",
                    ""
                )],
                status_code=409
            )

        results = {draft.id: [] for draft in drafts}

        for draft, record_index, values in submissions:
            record = build_vehicle_document_record(
                draft,
                record_index,
                values
            )
            db.session.add(record)
            db.session.flush()

            results[draft.id].append({
                "record_id": record.id,
                "record_index": record_index,
                "vehicle_record_id": values["vehicle_record_id"],
                "document_type": draft.document_type
            })

        completed_at = datetime.now(ZoneInfo("UTC"))

        for draft in drafts:
            draft.preview_json = json.dumps(
                previews[draft.id],
                ensure_ascii=False
            )
            draft.result_json = json.dumps(
                {"records": results[draft.id]},
                ensure_ascii=False
            )
            draft.status = (
                "completed"
                if results[draft.id]
                else "skipped"
            )
            draft.completed_at = completed_at

        db.session.commit()
    except (SQLAlchemyError, ValueError, InvalidOperation):
        db.session.rollback()
        app.logger.exception(
            "資料取り込みの反映に失敗しました"
        )
        return return_form_errors(
            [(
                "記録を反映できませんでした。入力内容を確認して、もう一度お試しください。",
                ""
            )],
            status_code=500
        )

    flash(
        f"資料から{len(submissions)}件の記録を反映しました。",
        "success"
    )

    return redirect(url_for("vehicle_data_import"))


@app.route(
    "/vehicle/periodic-inspections/<int:record_id>/source"
)
def vehicle_periodic_inspection_source(record_id):
    record = VehiclePeriodicInspectionRecord.query.filter_by(
        id=record_id,
        company_code=session.get("company_code")
    ).first_or_404()

    draft = VehicleDocumentImportDraft.query.filter_by(
        id=record.source_draft_id,
        company_code=record.company_code,
        status="completed"
    ).first_or_404()

    extension = os.path.splitext(
        draft.source_filename
    )[1].lower()

    mimetype = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg"
    }.get(extension)

    if not mimetype:
        raise NotFound()

    response = send_file(
        BytesIO(draft.source_file),
        mimetype=mimetype,
        download_name=draft.source_filename,
        as_attachment=False,
        conditional=False,
        etag=False,
        max_age=0
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"

    return response


@app.route(
    "/vehicle/data-import/files/<draft_id>"
)
def vehicle_document_import_source(draft_id):
    if not require_master_admin():
        raise NotFound()

    draft = (
        VehicleDocumentImportDraft.query
        .filter_by(
            id=draft_id,
            company_code=session.get("company_code"),
            created_by_username=session.get("username")
        )
        .first_or_404()
    )

    extension = os.path.splitext(
        draft.source_filename
    )[1].lower()

    mimetype = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg"
    }.get(extension)

    if not mimetype:
        raise NotFound()

    response = send_file(
        BytesIO(draft.source_file),
        mimetype=mimetype,
        download_name=draft.source_filename,
        as_attachment=False,
        conditional=False,
        etag=False,
        max_age=0
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"

    return response


@app.route(
    "/vehicle/data-import/<batch_id>/preview"
)
def vehicle_document_import_preview(batch_id):
    if not require_master_admin():
        return redirect(url_for("vehicle_karte_list"))

    drafts = (
        VehicleDocumentImportDraft.query
        .filter_by(
            batch_id=batch_id,
            company_code=session.get("company_code"),
            created_by_username=session.get("username")
        )
        .order_by(
            VehicleDocumentImportDraft.created_at,
            VehicleDocumentImportDraft.id
        )
        .all()
    )

    if not drafts:
        raise NotFound()

    pending_drafts = [
        draft
        for draft in drafts
        if draft.status == "preview"
    ]

    if not pending_drafts:
        flash(
            "この資料の取り込み確認は終了しています。",
            "info"
        )
        return redirect(url_for("vehicle_data_import"))

    vehicles = (
        Vehicle.query
        .filter_by(
            company_code=session.get("company_code")
        )
        .order_by(
            Vehicle.plate_area,
            Vehicle.plate_class,
            Vehicle.plate_kana,
            Vehicle.plate_number,
            Vehicle.id
        )
        .all()
    )

    vehicle_choices = [
        {
            "id": vehicle.id,
            "number": " ".join(
                str(value)
                for value in [
                    vehicle.plate_area,
                    vehicle.plate_class,
                    vehicle.plate_kana,
                    vehicle.plate_number
                ]
                if value
            ),
            "chassis_number": vehicle.chassis_number or "",
            "deleted": bool(vehicle.deleted)
        }
        for vehicle in vehicles
    ]

    documents = [
        {
            "id": draft.id,
            "filename": draft.source_filename,
            "document_type": draft.document_type,
            "preview": safe_json_dict(draft.preview_json)
        }
        for draft in pending_drafts
    ]

    return render_template(
        "vehicle_document_import_preview.html",
        batch_id=batch_id,
        documents=documents,
        vehicle_choices=vehicle_choices
    )


@app.route(
    "/vehicle/operation-import",
    methods=["GET", "POST"]
)
def vehicle_operation_import():
    if request.method == "GET":
        return render_template(
            "vehicle_operation_import.html"
        )

    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return return_form_errors(
            [("ログイン情報を確認してください。", "")],
            status_code=403
        )

    csv_file = request.files.get("csv_file")

    if not csv_file or not csv_file.filename:
        return return_form_errors([
            ("CSVファイルを選択してください。", "csv_file")
        ])

    filename = os.path.basename(
        csv_file.filename.replace("\\", "/")
    )

    if not filename.lower().endswith(".csv"):
        return return_form_errors([
            ("CSV形式のファイルを選択してください。", "csv_file")
        ])

    if len(filename) > 255:
        return return_form_errors([
            ("ファイル名は255文字以内にしてください。", "csv_file")
        ])

    try:
        csv_file.stream.seek(0)
        file_bytes = csv_file.read()
        read_vehicle_operation_csv(file_bytes)
    except UploadValidationError as error:
        return return_form_errors([
            (str(error), "csv_file")
        ])

    if request.headers.get("X-DKSS-Validation-Only") == "1":
        return jsonify({"ok": True})

    draft = VehicleOperationImportDraft(
        id=str(uuid4()),
        company_code=company_code,
        created_by_username=username,
        source_filename=filename,
        source_file=file_bytes,
    )

    try:
        db.session.add(draft)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception(
            "デジタコCSVの一時保存に失敗しました。"
        )
        return return_form_errors(
            [(
                "CSVを保存できませんでした。もう一度お試しください。",
                "csv_file"
            )],
            status_code=500
        )

    return redirect(url_for(
        "vehicle_operation_import_preview",
        draft_id=draft.id
    ))


@app.route("/vehicle/operation-import/<draft_id>/preview")
def vehicle_operation_import_preview(draft_id):
    draft = (
        VehicleOperationImportDraft.query
        .filter_by(
            id=draft_id,
            company_code=session.get("company_code"),
            created_by_username=session.get("username")
        )
        .first_or_404()
    )

    if draft.status != "preview":
        flash(
            "このCSVの取込確認は終了しています。",
            "info"
        )
        return redirect(url_for(
            "vehicle_operation_import"
        ))

    try:
        csv_rows = read_vehicle_operation_csv(
            draft.source_file
        )
        vehicles, preview_rows = (
            build_vehicle_operation_import_preview(
                csv_rows,
                draft.company_code
            )
        )
    except UploadValidationError as error:
        flash(str(error), "error:csv_file")
        return redirect(url_for(
            "vehicle_operation_import"
        ))

    vehicle_ids = {vehicle.id for vehicle in vehicles}
    saved_selections = safe_json_dict(
        draft.selection_json
    )

    for row in preview_rows:
        row["include"] = bool(
            not row["errors"]
            and not row["duplicate_in_file"]
            and row["existing_record_id"] is None
        )

        selection = saved_selections.get(
            str(row["line_number"])
        )

        if not isinstance(selection, dict):
            continue

        selected_id = selection.get("vehicle_record_id")

        if selected_id is None:
            row["vehicle_record_id"] = None
        elif (
            isinstance(selected_id, int)
            and not isinstance(selected_id, bool)
            and selected_id in vehicle_ids
        ):
            row["vehicle_record_id"] = selected_id
        else:
            row["vehicle_record_id"] = None

        row["include"] = bool(
            selection.get("include") is True
            and not row["errors"]
            and row["existing_record_id"] is None
        )

    vehicle_choices = [
        {
            "id": vehicle.id,
            "number": vehicle_number({
                "plate_area": vehicle.plate_area or "",
                "plate_class": vehicle.plate_class or "",
                "plate_kana": vehicle.plate_kana or "",
                "plate_number": vehicle.plate_number or "",
            }),
            "chassis_number": vehicle.chassis_number or "",
            "office": vehicle.office or "",
            "inspection_expiry": vehicle.inspection_expiry or "",
        }
        for vehicle in vehicles
    ]

    vehicle_choices_by_id = {
        choice["id"]: choice
        for choice in vehicle_choices
    }

    for row in preview_rows:
        row["selected_vehicle_choice"] = (
            vehicle_choices_by_id.get(
                row["vehicle_record_id"]
            )
        )

    grouped_vehicle_rows = {}

    for row in preview_rows:
        if (
            row["errors"]
            or row["existing_record_id"] is not None
            or not row["include"]
        ):
            continue

        source_row = row["source_row"]
        source_code = str(
            source_row.get("車両コード") or ""
        ).strip()
        source_number = str(
            source_row.get("車両") or ""
        ).strip()

        group_key = (
            source_code,
            normalize_vehicle_operation_plate(
                source_number
            ),
        )

        group = grouped_vehicle_rows.setdefault(
            group_key,
            {
                "index": len(grouped_vehicle_rows),
                "source_code": source_code,
                "source_number": source_number,
                "source_office": str(
                    source_row.get("車両：事業所") or ""
                ).strip(),
                "line_numbers": [],
                "candidate_vehicle_ids": set(),
                "selected_vehicle_ids": set(),
                "has_unselected": False,
            },
        )

        group["line_numbers"].append(
            row["line_number"]
        )
        group["candidate_vehicle_ids"].update(
            row["candidate_vehicle_ids"]
        )

        selected_id = row["vehicle_record_id"]

        if selected_id is None:
            group["has_unselected"] = True
        else:
            group["selected_vehicle_ids"].add(
                selected_id
            )

    vehicle_resolution_groups = []

    for group in grouped_vehicle_rows.values():
        if (
            not group["has_unselected"]
            and len(group["selected_vehicle_ids"]) == 1
        ):
            continue

        group["candidate_choices"] = [
            vehicle_choices_by_id[vehicle_id]
            for vehicle_id in sorted(
                group["candidate_vehicle_ids"]
            )
            if vehicle_id in vehicle_choices_by_id
        ]
        group["row_count"] = len(
            group["line_numbers"]
        )

        vehicle_resolution_groups.append(group)

    saved_errors = safe_json_dict(
        draft.result_json
    ).get("form_errors", [])

    errors_by_field = {}

    if isinstance(saved_errors, list):
        for error in saved_errors:
            if (
                not isinstance(error, (list, tuple))
                or len(error) != 2
            ):
                continue

            message, field = error

            if not isinstance(message, str):
                continue

            if not isinstance(field, str) or not field:
                continue

            errors_by_field.setdefault(field, []).append(
                message
            )

    for row in preview_rows:
        line_number = row["line_number"]
        row["submission_errors"] = list(dict.fromkeys(
            errors_by_field.get(
                f"vehicle_{line_number}",
                []
            )
            + errors_by_field.get(
                f"include_{line_number}",
                []
            )
        ))

    return render_template(
        "vehicle_operation_import_preview.html",
        draft=draft,
        preview_rows=preview_rows,
        vehicle_choices=vehicle_choices,
        vehicle_resolution_groups=vehicle_resolution_groups,
    )


@app.route(
    "/vehicle/operation-import/<draft_id>/confirm",
    methods=["POST"]
)
@limiter.limit("10 per minute")
def vehicle_operation_import_confirm(draft_id):
    company_code = session.get("company_code")
    username = session.get("username")

    draft = (
        VehicleOperationImportDraft.query
        .filter_by(
            id=draft_id,
            company_code=company_code,
            created_by_username=username
        )
        .first_or_404()
    )

    if draft.status != "preview":
        flash(
            "このCSVの取込確認は終了しています。",
            "info"
        )
        return redirect(url_for(
            "vehicle_operation_import"
        ))

    validation_only = (
        request.headers.get("X-DKSS-Validation-Only") == "1"
    )

    try:
        csv_rows = read_vehicle_operation_csv(
            draft.source_file
        )
        selections, records, errors = (
            get_vehicle_operation_import_submission(
                csv_rows,
                company_code,
                request.form
            )
        )

        submitted_confirmations = set(
            request.form.getlist(
                "confirmed_vehicle_mapping"
            )
        )
        previous_selections = safe_json_dict(
            draft.selection_json
        )

        for line_number, selection in selections.items():
            selected_id = selection.get(
                "vehicle_record_id"
            )
            previous = previous_selections.get(
                str(line_number),
                {}
            )

            if not isinstance(previous, dict):
                previous = {}

            selection["mapping_confirmed"] = bool(
                selection.get("include") is True
                and selected_id is not None
                and (
                    f"{line_number}:{selected_id}"
                    in submitted_confirmations
                    or (
                        previous.get("mapping_confirmed") is True
                        and previous.get("vehicle_record_id")
                        == selected_id
                    )
                )
            )
    except UploadValidationError as error:
        return return_form_errors([
            (str(error), "")
        ])

    if errors:
        if not validation_only:
            try:
                draft.selection_json = json.dumps(
                    selections,
                    ensure_ascii=False
                )
                draft.result_json = json.dumps(
                    {"form_errors": errors},
                    ensure_ascii=False
                )
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.exception(
                    "デジタコCSVの選択内容を保存できませんでした。"
                )
                return return_form_errors(
                    [(
                        "選択内容を保存できませんでした。"
                        "もう一度お試しください。",
                        ""
                    )],
                    status_code=500
                )

        if (
            validation_only
            or request.headers.get("X-DKSS-Final-Submit") == "1"
        ):
            return return_form_errors(errors)

        return return_form_errors([
            (
                f"確認が必要な項目が{len(errors)}件あります。"
                "表の確認事項を確認してください。"
                "選択内容は保存されています。",
                ""
            )
        ])

    if validation_only:
        return jsonify({"ok": True})

    try:
        claimed = (
            VehicleOperationImportDraft.query
            .filter_by(
                id=draft_id,
                company_code=company_code,
                created_by_username=username,
                status="preview"
            )
            .update(
                {"status": "processing"},
                synchronize_session=False
            )
        )

        if claimed != 1:
            db.session.rollback()
            flash(
                "このCSVはすでに処理されています。",
                "info"
            )
            return redirect(url_for(
                "vehicle_operation_import"
            ))

        report_numbers = [
            record["values"]["report_number"]
            for record in records
        ]
        existing_reports = set()

        for start in range(0, len(report_numbers), 400):
            existing_records = (
                VehicleOperationRecord.query
                .filter(
                    VehicleOperationRecord.company_code == company_code,
                    VehicleOperationRecord.report_number.in_(
                        report_numbers[start:start + 400]
                    )
                )
                .all()
            )

            existing_reports.update(
                record.report_number
                for record in existing_records
            )

        imported_at = datetime.now(
            ZoneInfo("Asia/Tokyo")
        ).strftime("%Y-%m-%d %H:%M:%S")

        added_count = 0
        skipped_count = 0

        for record in records:
            values = record["values"]

            if values["report_number"] in existing_reports:
                skipped_count += 1
                continue

            db.session.add(VehicleOperationRecord(
                company_code=company_code,
                vehicle_record_id=record["vehicle_record_id"],
                source_filename=draft.source_filename,
                imported_by_username=username,
                imported_at=imported_at,
                **values
            ))
            added_count += 1

        confirmed_pairs = {
            f"{line_number}:{selection['vehicle_record_id']}"
            for line_number, selection in selections.items()
            if (
                selection.get("mapping_confirmed") is True
                and selection.get("include") is True
                and selection.get("vehicle_record_id") is not None
            )
        }
        selected_ids_by_key = {}
        confirmed_mapping_keys = set()

        for record in records:
            values = record["values"]
            vehicle_id = record["vehicle_record_id"]

            mapping_key = (
                str(
                    values.get("source_vehicle_code") or ""
                ).strip(),
                normalize_vehicle_operation_plate(
                    values.get("source_vehicle_number")
                ),
            )

            selected_ids_by_key.setdefault(
                mapping_key,
                set()
            ).add(vehicle_id)

            confirmation = (
                f"{record['line_number']}:{vehicle_id}"
            )

            if confirmation in confirmed_pairs:
                confirmed_mapping_keys.add(
                    mapping_key
                )

        existing_mappings = {
            (
                mapping.source_vehicle_code,
                mapping.source_vehicle_number,
            ): mapping
            for mapping in (
                VehicleOperationVehicleMapping.query
                .filter_by(company_code=company_code)
                .all()
            )
        }

        for mapping_key in confirmed_mapping_keys:
            selected_ids = selected_ids_by_key[
                mapping_key
            ]

            if len(selected_ids) != 1:
                continue

            source_code, source_number = mapping_key

            if not source_number:
                continue

            vehicle_id = next(iter(selected_ids))
            mapping = existing_mappings.get(
                mapping_key
            )

            if mapping is None:
                mapping = VehicleOperationVehicleMapping(
                    company_code=company_code,
                    source_vehicle_code=source_code,
                    source_vehicle_number=source_number,
                    vehicle_record_id=vehicle_id,
                    confirmed_by_username=username,
                )
                db.session.add(mapping)
            else:
                mapping.vehicle_record_id = vehicle_id
                mapping.confirmed_by_username = username

            mapping.confirmed_at = datetime.now(
                ZoneInfo("UTC")
            )

        draft.selection_json = json.dumps(
            selections,
            ensure_ascii=False
        )
        draft.result_json = json.dumps({
            "added_count": added_count,
            "skipped_count": skipped_count,
        })
        draft.status = "completed"
        draft.completed_at = datetime.now(
            ZoneInfo("UTC")
        )

        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        return return_form_errors(
            [(
                "他の取込で同じ日報が登録された可能性があります。"
                "確認画面を更新して、もう一度お試しください。",
                ""
            )],
            status_code=409
        )

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception(
            "デジタコCSVの登録に失敗しました。"
        )
        return return_form_errors(
            [(
                "運行実績を登録できませんでした。"
                "もう一度お試しください。",
                ""
            )],
            status_code=500
        )

    flash(
        f"運行実績を{added_count}件登録しました。"
        f"登録済みの{skipped_count}件は取り込みませんでした。",
        "success"
    )

    return redirect(url_for(
        "vehicle_operation_import"
    ))


@app.route("/master/vehicles/<int:vehicle_record_id>/karte")
@app.route("/vehicle/karte/<int:vehicle_record_id>")
def vehicle_karte(vehicle_record_id):
    vehicle = Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=session.get("company_code")
    ).first_or_404()

    number = vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or ""
    })

    open_defects = get_vehicle_open_inspection_defects(
        vehicle.company_code,
        vehicle.id
    )

    current_user = User.query.filter_by(
        company_code=session.get("company_code"),
        username=session.get("username")
    ).first()

    if current_user is not None:
        user_settings = safe_json_dict(
            current_user.dashboard_settings_json
        )

        if user_settings.get(
            "vehicle_karte_last_vehicle_id"
        ) != vehicle.id:
            user_settings[
                "vehicle_karte_last_vehicle_id"
            ] = vehicle.id

            current_user.dashboard_settings_json = json.dumps(
                user_settings,
                ensure_ascii=False
            )
            db.session.commit()

    mileage_records = (
        VehicleOperationRecord.query
        .filter(
            VehicleOperationRecord.company_code == vehicle.company_code,
            VehicleOperationRecord.vehicle_record_id == vehicle.id,
            VehicleOperationRecord.arrival_meter.isnot(None)
        )
        .order_by(
            VehicleOperationRecord.operation_date.asc(),
            db.func.coalesce(
                VehicleOperationRecord.arrival_at,
                VehicleOperationRecord.operation_date
            ).asc(),
            VehicleOperationRecord.id.asc()
        )
        .all()
    )

    mileage_by_date = {}

    for record in mileage_records:
        mileage_by_date[record.operation_date] = float(
            record.arrival_meter
        )

    karte_mileage_points = [
        {
            "date": operation_date,
            "mileage": mileage
        }
        for operation_date, mileage in sorted(
            mileage_by_date.items()
        )
    ]

    return render_template(
        "vehicle_karte.html",
        vehicle=vehicle,
        vehicle_number=number,
        open_defects=open_defects,
        karte_mileage_points=karte_mileage_points
    )


@app.route(
    "/vehicle/karte/<int:vehicle_record_id>/documents/<draft_id>/source"
)
def vehicle_karte_document_source(vehicle_record_id, draft_id):
    vehicle = Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=session.get("company_code")
    ).first_or_404()

    draft = VehicleDocumentImportDraft.query.filter_by(
        id=draft_id,
        company_code=vehicle.company_code,
        status="completed"
    ).first_or_404()

    records = safe_json_dict(
        draft.result_json
    ).get("records", [])

    if not isinstance(records, list):
        raise NotFound()

    belongs_to_vehicle = any(
        isinstance(record, dict)
        and str(record.get("vehicle_record_id", ""))
        == str(vehicle.id)
        for record in records
    )

    if not belongs_to_vehicle:
        raise NotFound()

    extension = os.path.splitext(
        draft.source_filename
    )[1].lower()

    mimetype = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg"
    }.get(extension)

    if not mimetype:
        raise NotFound()

    response = send_file(
        BytesIO(draft.source_file),
        mimetype=mimetype,
        download_name=draft.source_filename,
        as_attachment=False,
        conditional=False,
        etag=False,
        max_age=0
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"

    return response


@app.route(
    "/vehicle/karte/<int:vehicle_record_id>/operation-files/<draft_id>"
)
def vehicle_karte_operation_source(vehicle_record_id, draft_id):
    vehicle = Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=session.get("company_code")
    ).first_or_404()

    draft = VehicleOperationImportDraft.query.filter_by(
        id=draft_id,
        company_code=vehicle.company_code,
        status="completed"
    ).first_or_404()

    selections = safe_json_dict(draft.selection_json)

    belongs_to_vehicle = any(
        isinstance(selection, dict)
        and selection.get("include") is True
        and str(selection.get("vehicle_record_id", ""))
        == str(vehicle.id)
        for selection in selections.values()
    )

    if not belongs_to_vehicle:
        raise NotFound()

    response = send_file(
        BytesIO(draft.source_file),
        mimetype="text/csv",
        download_name=draft.source_filename,
        as_attachment=True,
        conditional=False,
        etag=False,
        max_age=0
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"

    return response


@app.route("/vehicle/karte/<int:vehicle_record_id>/documents")
def vehicle_karte_documents(vehicle_record_id):
    vehicle = Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=session.get("company_code")
    ).first_or_404()

    number = vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or ""
    })

    drafts = (
        VehicleDocumentImportDraft.query
        .with_entities(
            VehicleDocumentImportDraft.id,
            VehicleDocumentImportDraft.source_filename,
            VehicleDocumentImportDraft.document_type,
            VehicleDocumentImportDraft.result_json,
            VehicleDocumentImportDraft.completed_at
        )
        .filter(
            VehicleDocumentImportDraft.company_code
            == vehicle.company_code,
            VehicleDocumentImportDraft.status == "completed"
        )
        .order_by(
            VehicleDocumentImportDraft.completed_at.desc(),
            VehicleDocumentImportDraft.id.desc()
        )
        .all()
    )

    documents = []

    for draft in drafts:
        records = safe_json_dict(
            draft.result_json
        ).get("records", [])

        if not isinstance(records, list):
            continue

        vehicle_records = [
            record
            for record in records
            if isinstance(record, dict)
            and str(record.get("vehicle_record_id", ""))
            == str(vehicle.id)
        ]

        if not vehicle_records:
            continue

        documents.append({
            "draft_id": draft.id,
            "filename": draft.source_filename,
            "document_type": draft.document_type,
            "completed_at": draft.completed_at,
            "records": vehicle_records
        })

    open_defects = get_vehicle_open_inspection_defects(
        vehicle.company_code,
        vehicle.id
    )

    operation_drafts = (
        VehicleOperationImportDraft.query
        .with_entities(
            VehicleOperationImportDraft.id,
            VehicleOperationImportDraft.source_filename,
            VehicleOperationImportDraft.selection_json,
            VehicleOperationImportDraft.completed_at
        )
        .filter(
            VehicleOperationImportDraft.company_code
            == vehicle.company_code,
            VehicleOperationImportDraft.status == "completed"
        )
        .order_by(
            VehicleOperationImportDraft.completed_at.desc(),
            VehicleOperationImportDraft.id.desc()
        )
        .all()
    )

    for draft in operation_drafts:
        selections = safe_json_dict(draft.selection_json)

        belongs_to_vehicle = any(
            isinstance(selection, dict)
            and selection.get("include") is True
            and str(selection.get("vehicle_record_id", ""))
            == str(vehicle.id)
            for selection in selections.values()
        )

        if not belongs_to_vehicle:
            continue

        documents.append({
            "draft_id": draft.id,
            "filename": draft.source_filename,
            "document_type": "operation_csv",
            "completed_at": draft.completed_at,
            "records": []
        })

    documents.sort(
        key=lambda document: (
            document["completed_at"].isoformat()
            if document["completed_at"] is not None
            else ""
        ),
        reverse=True
    )

    return render_template(
        "vehicle_karte_documents.html",
        vehicle=vehicle,
        vehicle_number=number,
        open_defects=open_defects,
        documents=documents
    )


@app.route("/vehicle/karte/<int:vehicle_record_id>/inspections")
def vehicle_karte_inspections(vehicle_record_id):
    vehicle = Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=session.get("company_code")
    ).first_or_404()

    number = vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or ""
    })

    page = max(1, request.args.get("page", 1, type=int))

    inspection_page = (
        VehicleChecklistResult.query
        .filter_by(
            company_code=vehicle.company_code,
            vehicle_record_id=vehicle.id
        )
        .order_by(
            VehicleChecklistResult.checked_date.desc(),
            VehicleChecklistResult.id.desc()
        )
        .paginate(
            page=page,
            per_page=20,
            error_out=False
        )
    )

    inspection_snapshots = {
        record.id: safe_json_dict(record.checklist_snapshot_json)
        for record in inspection_page.items
    }

    inspection_links = {
        record.id: url_for(
            "vehicle_checklist_results",
            index=record.checklist_id,
            vehicle_record_id=vehicle.id,
            year=record.year,
            month=record.month,
            active_day=record.day
        )
        for record in inspection_page.items
    }

    periodic_page_number = max(
        1,
        request.args.get("periodic_page", 1, type=int)
    )

    periodic_inspection_page = (
        VehiclePeriodicInspectionRecord.query
        .filter_by(
            company_code=vehicle.company_code,
            vehicle_record_id=vehicle.id
        )
        .order_by(
            VehiclePeriodicInspectionRecord.inspection_date.desc(),
            VehiclePeriodicInspectionRecord.id.desc()
        )
        .paginate(
            page=periodic_page_number,
            per_page=20,
            error_out=False
        )
    )

    return render_template(
        "vehicle_karte_inspections.html",
        vehicle=vehicle,
        vehicle_number=number,
        inspection_page=inspection_page,
        inspection_snapshots=inspection_snapshots,
        inspection_results={
            record.id: vehicle_checklist_result_to_dict(record)
            for record in inspection_page.items
        },
        inspection_links=inspection_links,
        periodic_inspection_page=periodic_inspection_page,
        open_defects=get_vehicle_open_inspection_defects(
            vehicle.company_code,
            vehicle.id
        )
    )


def get_vehicle_karte_history_entries(company_code, vehicle_record_id):
    entries = []

    def normalize_date(value):
        text = str(value or "").strip()[:10]

        for date_format in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(
                    text,
                    date_format
                ).strftime("%Y-%m-%d")
            except ValueError:
                continue

        return ""

    inspection_records = VehicleChecklistResult.query.filter_by(
        company_code=company_code,
        vehicle_record_id=vehicle_record_id
    ).all()

    for record in inspection_records:
        snapshot = safe_json_dict(record.checklist_snapshot_json)
        items = safe_json_dict_list(
            json.dumps(snapshot.get("items") or [])
        )
        is_daily_inspection = any(
            item.get("fixed_template_code")
            == "daily_inspection_truck_trailer"
            for item in items
        )

        inspection_date = normalize_date(
            f"{record.year}-"
            f"{str(record.month).zfill(2)}-"
            f"{str(record.day).zfill(2)}"
        )

        entries.append({
            "key": f"inspection:{record.id}",
            "date": inspection_date,
            "kind": "日常点検" if is_daily_inspection else "点検",
            "content": snapshot.get("name") or "車両チェックリスト",
            "files": list(dict.fromkeys(
                filename
                for answer in safe_json_dict_list(record.answers_json)
                for filename in (
                    answer.get("files")
                    if isinstance(answer.get("files"), list)
                    else []
                )
                if isinstance(filename, str) and filename.strip()
            )),
            "mileage": None,
            "cost": None,
            "status": record.status or "",
            "actor": record.checked_by or record.checked_by_username or "",
            "link": url_for(
                "vehicle_checklist_results",
                index=record.checklist_id,
                vehicle_record_id=vehicle_record_id,
                year=record.year,
                month=record.month,
                active_day=record.day
            ),
        })

        if is_daily_inspection:
            judgment = safe_json_dict(record.operation_judgment_json)
            stored_defects = judgment.get("defects") or []
            defects = [
                dict(defect)
                for defect in stored_defects
                if isinstance(defect, dict)
            ] if isinstance(stored_defects, list) else []

            for answer in safe_json_dict_list(record.answers_json):
                if str(answer.get("value") or "").strip() != "×":
                    continue

                item_no = str(answer.get("item_no", ""))
                accounted_for = False

                for defect in defects:
                    if str(defect.get("item_no", "")) != item_no:
                        continue

                    rechecked_answer = defect.get("rechecked_answer") or {}
                    if not isinstance(rechecked_answer, dict):
                        rechecked_answer = {}

                    if (
                        defect.get("status") != "解消"
                        or all(
                            rechecked_answer.get(field) == answer.get(field)
                            for field in ("value", "comment", "files")
                        )
                    ):
                        accounted_for = True
                        break

                if not accounted_for:
                    defects.append({
                        "item_no": item_no,
                        "status": "対応待ち",
                        "reported_answer": dict(answer),
                    })

            if isinstance(defects, list):
                for defect_index, defect in enumerate(defects):
                    if not isinstance(defect, dict):
                        continue

                    answer = defect.get("reported_answer") or {}
                    if not isinstance(answer, dict):
                        answer = {}

                    item_name = str(answer.get("content") or "").strip()
                    comment = str(answer.get("comment") or "").strip()
                    content = " / ".join(
                        value for value in (item_name, comment) if value
                    )

                    entries.append({
                        "key": (
                            f"defect:{record.id}:{defect_index}"
                        ),
                        "date": (
                            normalize_date(defect.get("reported_at"))
                            or inspection_date
                        ),
                        "kind": "異常・指摘",
                        "content": content or "日常点検の不具合",
                        "files": list(dict.fromkeys(
                            filename
                            for filename in (
                                answer.get("files")
                                if isinstance(answer.get("files"), list)
                                else []
                            )
                            if isinstance(filename, str) and filename.strip()
                        )),
                        "mileage": None,
                        "cost": None,
                        "status": defect.get("status") or "",
                        "actor": (
                            defect.get("reported_by")
                            or record.checked_by
                            or record.checked_by_username
                            or ""
                        ),
                        "link": url_for(
                            "vehicle_checklist_results",
                            index=record.checklist_id,
                            vehicle_record_id=vehicle_record_id,
                            year=record.year,
                            month=record.month,
                            active_day=record.day
                        ),
                    })

    driving_reports = VehicleDrivingReportRecord.query.filter_by(
        company_code=company_code,
        vehicle_record_id=vehicle_record_id
    ).all()

    for record in driving_reports:
        entries.append({
            "key": f"driving-report:{record.id}",
            "date": normalize_date(record.operation_date),
            "kind": "安全運転日報",
            "content": record.content or "安全運転日報",
            "files": [],
            "mileage": record.mileage,
            "cost": None,
            "status": "",
            "actor": "",
            "link": url_for(
                "vehicle_driving_report_source",
                record_id=record.id
            ),
        })

    maintenance_records = VehicleMaintenanceRecord.query.filter_by(
        company_code=company_code,
        vehicle_record_id=vehicle_record_id
    ).all()

    for record in maintenance_records:
        entries.append({
            "key": f"maintenance:{record.id}",
            "date": (
                normalize_date(record.completion_date)
                or normalize_date(record.entry_date)
            ),
            "kind": record.category or "整備",
            "content": (
                record.content
                or record.repair_content
                or record.symptom
                or ""
            ),
            "files": list(dict.fromkeys(
                safe_json_str_list(record.files_json)
            )),
            "mileage": record.mileage,
            "cost": record.total_cost,
            "status": record.status or "",
            "actor": " / ".join(
                value
                for value in (
                    record.maintenance_company,
                    record.maintenance_person
                )
                if value
            ),
            "link": None,
        })

    repair_events = (
        ChecklistEvent.query
        .join(
            VehicleChecklistResult,
            ChecklistEvent.result_id == VehicleChecklistResult.id
        )
        .filter(
            ChecklistEvent.company_code == company_code,
            ChecklistEvent.result_type == "vehicle",
            ChecklistEvent.event_type.in_(["整備中", "再確認待ち"]),
            VehicleChecklistResult.company_code == company_code,
            VehicleChecklistResult.vehicle_record_id == vehicle_record_id
        )
        .all()
    )

    for event in repair_events:
        detail = safe_json_dict(event.detail_json)
        repair = detail.get("repair") or {}
        if not isinstance(repair, dict) or not repair:
            continue

        defect = detail.get("defect") or {}
        if not isinstance(defect, dict):
            defect = {}

        answer = defect.get("reported_answer") or {}
        if not isinstance(answer, dict):
            answer = {}

        item_name = str(answer.get("content") or "").strip()
        note = str(repair.get("note") or "").strip()
        content = " / ".join(
            value for value in (item_name, note) if value
        )

        result_record = db.session.get(
            VehicleChecklistResult,
            event.result_id
        )
        if not result_record:
            continue

        entries.append({
            "key": f"inspection-repair:{event.id}",
            "date": normalize_date(repair.get("performed_at")),
            "kind": "整備",
            "content": content or "日常点検の不具合対応",
            "mileage": None,
            "cost": None,
            "status": repair.get("status") or event.event_type or "",
            "actor": (
                repair.get("performed_by")
                or event.actor_name
                or ""
            ),
            "link": url_for(
                "vehicle_checklist_results",
                index=result_record.checklist_id,
                vehicle_record_id=vehicle_record_id,
                year=result_record.year,
                month=result_record.month,
                active_day=result_record.day
            ),
        })

    entries.sort(
        key=lambda entry: (entry["date"], entry["key"]),
        reverse=True
    )

    return entries


@app.route("/master/vehicles/<int:vehicle_record_id>/karte/history")
@app.route("/vehicle/karte/<int:vehicle_record_id>/history")
def vehicle_karte_history(vehicle_record_id):
    vehicle = Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=session.get("company_code")
    ).first_or_404()

    number = vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or ""
    })

    page = max(1, request.args.get("page", 1, type=int))
    selected_event_type = request.args.get("event_type", "").strip()
    selected_start_date = request.args.get("start_date", "").strip()
    selected_end_date = request.args.get("end_date", "").strip()

    history_date_errors = []

    for field_id, label, value in [
        ("history_start_date", "開始日", selected_start_date),
        ("history_end_date", "終了日", selected_end_date),
    ]:
        if not value:
            continue

        try:
            parsed_date = datetime.strptime(value, "%Y-%m-%d")
            if parsed_date.strftime("%Y-%m-%d") != value:
                raise ValueError
        except ValueError:
            history_date_errors.append((
                field_id,
                label + "を正しい日付で入力してください。",
            ))

    if (
        not history_date_errors
        and selected_start_date
        and selected_end_date
        and selected_start_date > selected_end_date
    ):
        history_date_errors.append((
            "history_end_date",
            "終了日は開始日以降の日付を選択してください。",
        ))

    for field_id, message in history_date_errors:
        flash(message, "error:" + field_id)

    from types import SimpleNamespace

    history_entries = get_vehicle_karte_history_entries(
        vehicle.company_code,
        vehicle.id
    )

    history_event_types = sorted({
        entry["kind"]
        for entry in history_entries
        if entry["kind"]
    })

    history_statuses = sorted({
        entry["status"]
        for entry in history_entries
        if entry["status"]
    })

    selected_status = request.args.get("status", "").strip()

    if history_date_errors:
        history_entries = []
    else:
        history_entries = [
            entry
            for entry in history_entries
            if (
                (
                    not selected_event_type
                    or entry["kind"] == selected_event_type
                )
                and (
                    not selected_status
                    or entry["status"] == selected_status
                )
                and (
                    not selected_start_date
                    or entry["date"] >= selected_start_date
                )
                and (
                    not selected_end_date
                    or (
                        entry["date"]
                        and entry["date"] <= selected_end_date
                    )
                )
            )
        ]

    per_page = 100
    total = len(history_entries)
    pages = (total + per_page - 1) // per_page
    offset = (page - 1) * per_page

    history_page = SimpleNamespace(
        items=history_entries[offset:offset + per_page],
        total=total,
        page=page,
        pages=pages,
        has_prev=page > 1,
        has_next=page < pages,
        prev_num=page - 1 if page > 1 else None,
        next_num=page + 1 if page < pages else None
    )

    return render_template(
        "vehicle_karte_history.html",
        vehicle=vehicle,
        vehicle_number=number,
        history_page=history_page,
        history_links={},
        history_details={},
        history_event_types=history_event_types,
        history_statuses=history_statuses,
        selected_event_type=selected_event_type,
        selected_status=selected_status,
        selected_start_date=selected_start_date,
        selected_end_date=selected_end_date,
        open_defects=get_vehicle_open_inspection_defects(
            vehicle.company_code,
            vehicle.id
        )
    ), (400 if history_date_errors else 200)


def get_vehicle_karte_usage_vehicles():
    company_code = session.get("company_code")
    username = session.get("username")

    if not company_code or not username:
        return []

    current_driver = Driver.query.filter_by(
        company_code=company_code,
        employee_id=username
    ).first()

    if current_driver is None:
        return []

    vehicle_ids = []
    for value in safe_json_str_list(
        current_driver.vehicles_json
    ):
        if not value.isdigit() or len(value) > 18:
            continue

        vehicle_id = int(value)
        if vehicle_id > 0 and vehicle_id not in vehicle_ids:
            vehicle_ids.append(vehicle_id)

    if not vehicle_ids:
        return []

    records = Vehicle.query.filter(
        Vehicle.company_code == company_code,
        Vehicle.deleted == False,
        Vehicle.id.in_(vehicle_ids)
    ).all()

    record_map = {
        record.id: record
        for record in records
    }

    return [
        record_map[vehicle_id]
        for vehicle_id in vehicle_ids
        if vehicle_id in record_map
    ]


@app.context_processor
def inject_vehicle_karte_choices():
    if request.endpoint not in {
        "vehicle_karte_list",
        "vehicle_karte",
        "vehicle_karte_history",
        "vehicle_karte_inspections",
        "vehicle_karte_documents",
    }:
        return {}

    company_code = session.get("company_code")
    if not company_code:
        return {"karte_vehicle_choices": []}

    vehicles = Vehicle.query.filter_by(
        company_code=company_code
    ).order_by(Vehicle.id.asc()).all()

    driver_names_by_vehicle = {
        str(record.id): []
        for record in vehicles
    }

    drivers = Driver.query.filter_by(
        company_code=company_code
    ).order_by(Driver.id.asc()).all()

    for driver in drivers:
        driver_name = (driver.name or "").strip()
        if not driver_name:
            continue

        for vehicle_id in safe_json_str_list(
            driver.vehicles_json
        ):
            names = driver_names_by_vehicle.get(
                vehicle_id
            )
            if names is not None and driver_name not in names:
                names.append(driver_name)

    choices = []
    for record in vehicles:
        number = vehicle_number({
            "plate_area": record.plate_area or "",
            "plate_class": record.plate_class or "",
            "plate_kana": record.plate_kana or "",
            "plate_number": record.plate_number or "",
        })

        choices.append({
            "id": record.id,
            "number": number,
            "chassis_number": record.chassis_number or "",
            "driver_names": "、".join(
                driver_names_by_vehicle.get(
                    str(record.id),
                    []
                )
            ),
        })

    operation_summary = {
        "current_mileage": None,
        "mileage_date": None,
    }

    vehicle_record_id = (
        request.view_args or {}
    ).get("vehicle_record_id")

    if any(
        record.id == vehicle_record_id
        for record in vehicles
    ):
        operation_summary = get_vehicle_operation_summary(
            company_code,
            vehicle_record_id
        )

    return {
        "karte_vehicle_choices": choices,
        "karte_usage_vehicles": get_vehicle_karte_usage_vehicles(),
        "karte_operation_summary": operation_summary,
    }


@app.route("/vehicle/karte")
def vehicle_karte_list():
    selected_value = request.args.get(
        "vehicle_record_id",
        ""
    ).strip()

    if selected_value:
        selected_id = request.args.get(
            "vehicle_record_id",
            type=int
        )

        if (
            selected_id is None
            or selected_id <= 0
            or selected_id > 9223372036854775807
        ):
            flash(
                "表示する車両を選択し直してください。",
                "error:karte_vehicle_search"
            )
            return render_template(
                "vehicle_karte.html",
                vehicle=None
            ), 400

        selected_vehicle = Vehicle.query.filter_by(
            id=selected_id,
            company_code=session.get("company_code")
        ).first()

        if selected_vehicle is None:
            flash(
                "選択した車両を表示できません。車両を選択し直してください。",
                "error:karte_vehicle_search"
            )
            return render_template(
                "vehicle_karte.html",
                vehicle=None
            ), 404

        return redirect(url_for(
            "vehicle_karte",
            vehicle_record_id=selected_vehicle.id
        ))

    usage_vehicles = get_vehicle_karte_usage_vehicles()

    if usage_vehicles:
        current_user = User.query.filter_by(
            company_code=session.get("company_code"),
            username=session.get("username")
        ).first()

        user_settings = safe_json_dict(
            current_user.dashboard_settings_json
        ) if current_user is not None else {}

        last_vehicle_id = str(user_settings.get(
            "vehicle_karte_last_vehicle_id",
            ""
        ))

        default_vehicle = next(
            (
                record
                for record in usage_vehicles
                if str(record.id) == last_vehicle_id
            ),
            usage_vehicles[0]
        )

        return redirect(url_for(
            "vehicle_karte",
            vehicle_record_id=default_vehicle.id
        ))

    return render_template(
        "vehicle_karte.html",
        vehicle=None
    )


@app.route("/master/vehicles")
def vehicle_master():
    return render_vehicle_list("vehicle_master.html")


def render_vehicle_list(template_name):
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

    plate_number_search = request.args.get(
        "plate_number_search", ""
    ).strip()
    chassis_number_search = request.args.get(
        "chassis_number_search", ""
    ).strip()

    search_errors = []

    if len(plate_number_search) > 100:
        search_errors.append((
            "車番の検索条件は100文字以内で入力してください。",
            "vehicle_search_plate_number"
        ))

    if len(chassis_number_search) > 100:
        search_errors.append((
            "車台番号の検索条件は100文字以内で入力してください。",
            "vehicle_search_chassis_number"
        ))

    if search_errors:
        return return_form_errors(search_errors)

    if plate_number_search:
        normalized_plate_number = "".join(
            plate_number_search.split()
        ).replace("-", "").replace("－", "")

        if normalized_plate_number:
            plate_number_expression = (
                db.func.coalesce(Vehicle.plate_area, "")
                + db.func.coalesce(Vehicle.plate_class, "")
                + db.func.coalesce(Vehicle.plate_kana, "")
                + db.func.coalesce(Vehicle.plate_number, "")
            )

            for separator in (" ", "　", "-", "－"):
                plate_number_expression = db.func.replace(
                    plate_number_expression,
                    separator,
                    ""
                )

            query = query.filter(
                plate_number_expression.ilike(
                    f"%{normalized_plate_number}%"
                )
            )

    if chassis_number_search:
        query = query.filter(
            Vehicle.chassis_number.ilike(
                f"%{chassis_number_search}%"
            )
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
    per_page = 10

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

        if template_name == "vehicle_master.html":
            item["open_defect_count"] = len(
                get_vehicle_open_inspection_defects(
                    company_code,
                    vehicle.id
                )
            )

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
        template_name,
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

@app.route("/master/vehicles/import/master", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
def register_vehicle_import_master():
    company_code = session.get("company_code")

    if not company_code or not require_master_admin():
        return return_form_errors([
            ("管理者権限が必要です。", "")
        ], status_code=403)

    master_kind = request.form.get("master_kind", "").strip()
    name = request.form.get("name", "").strip()

    master_models = {
        "office": (Office, "営業所"),
        "vehicle_type": (VehicleType, "車種"),
    }

    if master_kind not in master_models:
        return return_form_errors([
            ("登録するマスタの種類を確認してください。", "")
        ])

    model, label = master_models[master_kind]

    if not name:
        return return_form_errors([
            (f"{label}名を入力してください。", "name")
        ])

    if len(name) > 100:
        return return_form_errors([
            (f"{label}名は100文字以内で入力してください。", "name")
        ])

    existing = model.query.filter_by(
        company_code=company_code,
        name=name
    ).first()

    if existing:
        return return_form_errors([
            (
                f"{label}「{name}」はすでに登録されています。"
                "既存マスタへの割り当てを選択してください。",
                "name"
            )
        ], status_code=409)

    if request.headers.get("X-DKSS-Validation-Only") == "1":
        return jsonify({"ok": True})

    if request.form.get("confirmed") != "1":
        return return_form_errors([
            ("新規登録する内容を確認してください。", "")
        ])

    master = model(
        company_code=company_code,
        name=name
    )

    try:
        db.session.add(master)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("車両Excel取込のマスタ登録に失敗しました。")
        return return_form_errors([
            (
                f"{label}を登録できませんでした。"
                "入力内容を保持したまま、もう一度お試しください。",
                "name"
            )
        ], status_code=500)

    return jsonify({
        "ok": True,
        "master_kind": master_kind,
        "master": {
            "id": master.id,
            "name": master.name,
        },
    })


@app.route("/master/vehicles/import", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def import_vehicles():

    company_code = session.get("company_code")

    if request.method == "POST":

        excel_file = request.files.get("excel_file")

        if not excel_file or not excel_file.filename:
            return return_form_errors([
                (
                    "Excelファイルを選択してください。",
                    "excel_file"
                )
            ])

        if not excel_file.filename.lower().endswith(".xlsx"):
            return return_form_errors([
                (
                    "xlsx形式のExcelファイルを選択してください。",
                    "excel_file"
                )
            ])

        if not is_valid_uploaded_file(
            excel_file,
            ".xlsx"
        ):
            return return_form_errors([
                (
                    "Excelファイルの内容が不正です。",
                    "excel_file"
                )
            ])

        try:
            workbook = load_workbook(
                excel_file,
                data_only=True
            )
        except Exception:
            return return_form_errors([
                (
                    "Excelファイルを読み込めませんでした。",
                    "excel_file"
                )
            ])

        sheet = workbook.active

        if sheet.max_row > 5000:
            return return_form_errors([
                (
                    "一度に読み込めるExcelは5000行までです。",
                    "excel_file"
                )
            ])

        if sheet.max_column > 200:
            return return_form_errors([
                (
                    "一度に読み込めるExcelは200列までです。",
                    "excel_file"
                )
            ])

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
            return return_form_errors([
                (
                    "車両台帳の見出し行が見つかりませんでした。",
                    "excel_file"
                )
            ])

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
            return return_form_errors([
                (
                    "Excelに必要な見出しがありません："
                    + "、".join(missing_headers),
                    "excel_file"
                )
            ])

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

                "office": (
                    str(
                        row_values[header_map["営業所"]] or ""
                    ).strip()
                    if "営業所" in header_map
                    else ""
                ),

                "active_status": (
                    str(
                        row_values[header_map["有効／無効"]] or ""
                    ).strip()
                    if "有効／無効" in header_map
                    else ""
                ),

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

        valid_import_offices = {
            office.name
            for office in Office.query.filter_by(
                company_code=session.get("company_code")
            ).all()
        }

        for vehicle in vehicles_data:
            office = vehicle.get("office", "")
            active_status = vehicle.get("active_status", "")
            excel_row = vehicle.get("excel_row")

            if office and office not in valid_import_offices:
                return return_form_errors([
                    (
                        f"{excel_row}行目の営業所「{office}」は"
                        "営業所マスタに登録されていません。",
                        "excel_file"
                    )
                ])

            if active_status not in {"", "有効", "無効"}:
                return return_form_errors([
                    (
                        f"{excel_row}行目の有効／無効は"
                        "「有効」または「無効」で入力してください。",
                        "excel_file"
                    )
                ])

        def clean_preview_text(value):
            return str(
                "" if value is None else value
            ).strip()

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
            excel_vehicle_type = str(
                vehicle.get("vehicle_type_code", "") or ""
            ).strip()

            mapped_vehicle_type = vehicle_type_mapping_dict.get(
                excel_vehicle_type,
                ""
            )

            if (
                not mapped_vehicle_type
                and excel_vehicle_type in valid_vehicle_type_names
            ):
                mapped_vehicle_type = excel_vehicle_type

            vehicle["mapped_vehicle_type"] = mapped_vehicle_type
            
        processed_import_keys = set()

        for vehicle in vehicles_data:

            chassis_number = clean_preview_text(
                vehicle.get("chassis_number")
            )

            if not chassis_number:
                return return_form_errors([
                    (
                        f"{vehicle.get('excel_row')}行目の車台番号を入力してください。",
                        "excel_file"
                    )
                ])

            import_key = (
                "chassis",
                chassis_number
            )

            existing_vehicle = (
                existing_preview_by_chassis.get(
                    chassis_number
                )
            )

            vehicle["recommended_update_id"] = None

            if not existing_vehicle:
                candidates = get_vehicle_registration_plate_conflicts(
                    company_code,
                    vehicle.get("plate_area"),
                    vehicle.get("plate_class"),
                    vehicle.get("plate_kana"),
                    vehicle.get("plate_number"),
                    chassis_number,
                )
                complete_chassis = normalize_vehicle_operation_plate(
                    chassis_number
                )
                correction_candidates = []

                for candidate in candidates:
                    shortened_chassis = normalize_vehicle_operation_plate(
                        candidate["chassis_number"]
                    )

                    if (
                        shortened_chassis
                        and len(shortened_chassis) < len(complete_chassis)
                        and complete_chassis.startswith(shortened_chassis)
                        and clean_preview_text(candidate["chassis_number"])
                        not in incoming_chassis_numbers
                    ):
                        correction_candidates.append(candidate)

                if len(correction_candidates) == 1:
                    vehicle["recommended_update_id"] = (
                        correction_candidates[0]["id"]
                    )
                    existing_vehicle = Vehicle.query.filter_by(
                        id=vehicle["recommended_update_id"],
                        company_code=company_code,
                    ).first()

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

                if not vehicle.get("active_status"):
                    vehicle["active_status"] = (
                        "無効" if existing_vehicle.deleted else "有効"
                    )

                target_deleted = (
                    vehicle["active_status"] == "無効"
                )

                vehicle["reactivate"] = (
                    existing_vehicle.deleted and not target_deleted
                )

                vehicle["state_changed"] = (
                    bool(existing_vehicle.deleted) != target_deleted
                )

                if not vehicle.get("office"):
                    vehicle["office"] = (
                        existing_vehicle.office or ""
                    )

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

                vehicle_changed = (
                    bool(vehicle.get("recommended_update_id"))
                    or bool(vehicle.get("state_changed"))
                    or clean_preview_text(existing_vehicle.office)
                    != clean_preview_text(vehicle.get("office"))
                )

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

                if not vehicle.get("active_status"):
                    vehicle["active_status"] = "有効"

            vehicle["base_import_status"] = (
                vehicle["import_status"]
            )

            if is_excel_duplicate:
                vehicle["import_status"] = (
                    "Excel内重複"
                )
            processed_import_keys.add(import_key)



        company_vehicles = Vehicle.query.filter_by(
            company_code=company_code
        ).order_by(Vehicle.id.asc()).all()

        excel_plate_rows = {}

        for row_number, vehicle_data in enumerate(
            vehicles_data, start=1
        ):
            plate_key = tuple(
                normalize_vehicle_operation_plate(
                    vehicle_data.get(field_name)
                )
                for field_name in (
                    "plate_area",
                    "plate_class",
                    "plate_kana",
                    "plate_number",
                )
            )

            if all(plate_key):
                excel_plate_rows.setdefault(
                    plate_key, []
                ).append((
                    row_number,
                    str(
                        vehicle_data.get("chassis_number") or ""
                    ).strip(),
                ))

        for row_number, vehicle_data in enumerate(
            vehicles_data, start=1
        ):
            chassis_number = str(
                vehicle_data.get("chassis_number") or ""
            ).strip()

            vehicle_data["plate_conflicts"] = (
                get_vehicle_registration_plate_conflicts(
                    company_code,
                    vehicle_data.get("plate_area"),
                    vehicle_data.get("plate_class"),
                    vehicle_data.get("plate_kana"),
                    vehicle_data.get("plate_number"),
                    chassis_number,
                    existing_vehicles=company_vehicles,
                )
            )

            plate_key = tuple(
                normalize_vehicle_operation_plate(
                    vehicle_data.get(field_name)
                )
                for field_name in (
                    "plate_area",
                    "plate_class",
                    "plate_kana",
                    "plate_number",
                )
            )

            vehicle_data["excel_plate_conflicts"] = [
                {
                    "row_number": other_row,
                    "chassis_number": other_chassis,
                }
                for other_row, other_chassis in (
                    excel_plate_rows.get(plate_key, [])
                )
                if other_row != row_number
                and other_chassis
                and chassis_number
                and other_chassis != chassis_number
            ]

        return render_template(
            "vehicle_import_preview.html",
            vehicles=vehicles_data,
            offices=offices_for_current_company(),
            vehicle_types=vehicle_types_for_current_company(),
            vehicle_type_mapping_dict=vehicle_type_mapping_dict,
            vehicle_plate_candidates=[
                {
                    "id": vehicle.id,
                    "chassis_number": str(
                        vehicle.chassis_number or ""
                    ).strip(),
                    "plate_area": vehicle.plate_area or "",
                    "plate_class": vehicle.plate_class or "",
                    "plate_kana": vehicle.plate_kana or "",
                    "plate_number": vehicle.plate_number or "",
                    "office": vehicle.office or "",
                    "inactive": bool(vehicle.deleted),
                    "vehicle_type": vehicle.type or "",
                    "gross_vehicle_weight": vehicle.gross_vehicle_weight,
                    "model_code": vehicle.model_code or "",
                    "first_registration_date": vehicle.first_registration_date or "",
                    "inspection_expiry": vehicle.inspection_expiry or "",
                    "vehicle_name": vehicle.manufacturer or "",
                    "body_type": vehicle.body_type or "",
                    "max_payload": vehicle.max_payload,
                }
                for vehicle in company_vehicles
            ],
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
        for value in vehicle_types
    ]

    for i, vehicle_type in enumerate(vehicle_types):
        if vehicle_type and vehicle_type not in valid_vehicle_type_names:
            return return_form_errors([
                (
                    f"{i + 1}件目の車種「{vehicle_type}」は"
                    "車種マスタに登録されていません。"
                    "既存の車種への割り当て、または新規登録を確認してください。",
                    "vehicle_type"
                )
            ])
    
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

    offices = request.form.getlist("office")
    active_statuses = request.form.getlist("active_status")

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
        offices,
        active_statuses,
    ]

    form_list_lengths = {
        len(values)
        for values in form_lists
    }

    if len(form_list_lengths) != 1:
        return return_form_errors([
            (
                "取込データの件数が一致しません。"
                "Excel取込画面からやり直してください。",
                ""
            )
        ])

    import_count = len(chassis_numbers)

    if import_count > 5000:
        return return_form_errors([
            (
                "一度に取り込める車両は5000件までです。",
                ""
            )
        ])

    if import_count == 0:
        return return_form_errors([
            (
                "取込対象の車両がありません。",
                ""
            )
        ])

    valid_import_offices = {
        office.name
        for office in Office.query.filter_by(
            company_code=company_code
        ).all()
    }

    offices = [
        str(value or "").strip()
        for value in offices
    ]

    target_deleted_values = []

    for i in range(import_count):
        office = offices[i]
        active_status = str(active_statuses[i] or "").strip()
        vehicle_type_code = str(vehicle_type_codes[i] or "").strip()

        if vehicle_type_code and not vehicle_types[i]:
            return return_form_errors([
                (
                    f"{i + 1}件目の車種コード「{vehicle_type_code}」の"
                    "割り当てが未解決です。"
                    "既存の車種への割り当て、または新規登録を確認してください。",
                    "vehicle_type"
                )
            ])

        if len(office) > 100:
            return return_form_errors([
                (
                    f"{i + 1}件目の営業所は100文字以内で入力してください。",
                    "office"
                )
            ])

        if office and office not in valid_import_offices:
            return return_form_errors([
                (
                    f"{i + 1}件目の営業所「{office}」は"
                    "営業所マスタに登録されていません。",
                    "office"
                )
            ])

        if active_status not in {"有効", "無効"}:
            return return_form_errors([
                (
                    f"{i + 1}件目の有効／無効を選択してください。",
                    "active_status"
                )
            ])

        target_deleted_values.append(active_status == "無効")

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

    company_vehicles = Vehicle.query.filter_by(
        company_code=company_code
    ).order_by(Vehicle.id.asc()).all()

    excel_plate_chassis = {}

    for i in range(import_count):
        plate_key = tuple(
            normalize_vehicle_operation_plate(value)
            for value in (
                plate_areas[i],
                plate_classes[i],
                plate_kanas[i],
                plate_numbers[i],
            )
        )
        if all(plate_key):
            excel_plate_chassis.setdefault(
                plate_key, set()
            ).add(normalize_import_text(chassis_numbers[i]))

    vehicle_chassis_corrections = {}
    correction_target_ids = set()
    checked_chassis_numbers = set()
    resolution_errors = []

    for i in range(import_count):
        chassis_number = normalize_import_text(
            chassis_numbers[i]
        )

        if not chassis_number:
            continue

        if chassis_number in checked_chassis_numbers:
            continue

        checked_chassis_numbers.add(chassis_number)

        field_name = f"vehicle_plate_resolution_{i}"
        choice = request.form.get(
            field_name, ""
        ).strip()

        existing_vehicle = existing_vehicles_by_chassis.get(
            chassis_number
        )

        conflicts = get_vehicle_registration_plate_conflicts(
            company_code,
            plate_areas[i],
            plate_classes[i],
            plate_kanas[i],
            plate_numbers[i],
            chassis_number,
            existing_vehicles=company_vehicles,
        )

        plate_key = tuple(
            normalize_vehicle_operation_plate(value)
            for value in (
                plate_areas[i],
                plate_classes[i],
                plate_kanas[i],
                plate_numbers[i],
            )
        )

        excel_conflict = any(
            other_chassis
            and other_chassis != chassis_number
            for other_chassis in (
                excel_plate_chassis.get(plate_key, set())
            )
        )

        if not conflicts and not excel_conflict:
            if choice.startswith("update:"):
                resolution_errors.append((
                    f"No.{i + 1}の車両情報が変更されています。"
                    "車台番号の訂正対象を確認してください。",
                    field_name,
                ))
            continue

        if excel_conflict:
            resolution_errors.append((
                f"No.{i + 1}はExcel内に同じナンバーで異なる"
                "車台番号の行があります。"
                "車台番号またはナンバープレートを確認・訂正してください。",
                field_name,
            ))
            continue

        if existing_vehicle:
            resolution_errors.append((
                f"No.{i + 1}は登録済み車両同士でナンバーが重複しています。"
                "既存車両の重複を解消してから取り込んでください。",
                field_name,
            ))
            continue

        allowed_choices = {}
        conflict_ids = {
            candidate["id"]
            for candidate in conflicts
        }

        for candidate in company_vehicles:
            if candidate.id in conflict_ids:
                allowed_choices[
                    f"update:{candidate.id}"
                ] = candidate

        if choice not in allowed_choices:
            resolution_errors.append((
                f"No.{i + 1}は同じナンバーで異なる"
                "車台番号の車両があります。"
                "登録・更新方法を選択してください。",
                field_name,
            ))
            continue

        if not choice.startswith("update:"):
            continue

        target_vehicle = allowed_choices[choice]
        old_chassis = normalize_import_text(
            target_vehicle.chassis_number
        )

        if (
            target_vehicle.id in correction_target_ids
            or old_chassis in import_chassis_numbers
        ):
            resolution_errors.append((
                f"No.{i + 1}の訂正対象車両は、"
                "今回のExcel内の別の行でも使用されています。"
                "取り込む車台番号を確認してください。",
                field_name,
            ))
            continue

        correction_target_ids.add(target_vehicle.id)
        vehicle_chassis_corrections[chassis_number] = (
            target_vehicle
        )

    if resolution_errors:
        return return_form_errors(resolution_errors)

    for corrected_chassis, target_vehicle in (
        vehicle_chassis_corrections.items()
    ):
        existing_vehicles_by_chassis[
            corrected_chassis
        ] = target_vehicle

    counted_import_keys = set()
    new_vehicle_count = 0
    reactivate_vehicle_count = 0
    deactivate_vehicle_count = 0

    for i in range(import_count):

        chassis_number = normalize_import_text(
            chassis_numbers[i]
        )

        if not chassis_number:
            return return_form_errors([
                (
                    f"{i + 1}行目の車台番号を入力してください。",
                    "chassis_number"
                )
            ])

        import_key = (
            "chassis",
            chassis_number
        )

        if import_key in counted_import_keys:
            continue

        counted_import_keys.add(import_key)

        existing_vehicle = existing_vehicles_by_chassis.get(
            chassis_number
        )
        target_deleted = target_deleted_values[i]

        if existing_vehicle:
            if existing_vehicle.deleted and not target_deleted:
                reactivate_vehicle_count += 1
            elif not existing_vehicle.deleted and target_deleted:
                deactivate_vehicle_count += 1
        elif not target_deleted:
            new_vehicle_count += 1

    # 取込後の有効車両台数で上限チェック
    if company:
        projected_active_count = (
            current_count
            + new_vehicle_count
            + reactivate_vehicle_count
            - deactivate_vehicle_count
        )

        if projected_active_count > company.vehicle_limit:
            return return_form_errors([
                (
                    f"登録上限を超えます。"
                    f"現在の有効車両 {current_count} 台、"
                    f"有効車両の新規登録予定 {new_vehicle_count} 台、"
                    f"再有効化予定 {reactivate_vehicle_count} 台、"
                    f"無効化予定 {deactivate_vehicle_count} 台、"
                    f"取込後の有効車両 {projected_active_count} 台、"
                    f"上限 {company.vehicle_limit} 台です。",
                    ""
                )
            ])
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

        error = get_vehicle_text_length_error(
            value,
            field_name,
            max_length
        )

        if error:
            return None, f"{row_number}行目の{error}"

        return value, None

    def to_nonnegative_int(value, field_name, row_number):
        value = str("" if value is None else value).strip().replace(",", "")

        if not value:
            return None, None

        try:
            parsed = parse_nonnegative_int(
                value,
                field_name
            )
        except UploadValidationError as error:
            return None, f"{row_number}行目の{error}"

        return parsed, None

    def validate_import_date(value, field_name, row_number):
        value = clean_text(value)

        error = get_vehicle_date_error(
            value,
            field_name
        )

        if error:
            return "", f"{row_number}行目の{error}"

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
            return return_form_errors([
                (error, "chassis_number")
            ])

        plate_area, error = validate_text_length(
            normalize_import_text(
                plate_areas[i]
            ),
            "車番・地域名",
            50,
            i + 1
        )

        if error:
            return return_form_errors([
                (error, "plate_area")
            ])

        plate_class, error = validate_text_length(
            normalize_import_text(
                plate_classes[i]
            ),
            "車番・分類",
            50,
            i + 1
        )

        if error:
            return return_form_errors([
                (error, "plate_class")
            ])

        plate_kana, error = validate_text_length(
            normalize_import_text(
                plate_kanas[i]
            ),
            "車番・ひらがな",
            10,
            i + 1
        )

        if error:
            return return_form_errors([
                (error, "plate_kana")
            ])

        plate_number, error = validate_text_length(
            normalize_import_text(
                plate_numbers[i]
            ),
            "車番",
            50,
            i + 1
        )

        if error:
            return return_form_errors([
                (error, "plate_number")
            ])

        if not chassis_number:
            return return_form_errors([
                (
                    f"{i + 1}行目の車台番号を入力してください。",
                    "chassis_number"
                )
            ])

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
            return return_form_errors([
                (error, "gross_vehicle_weight")
            ])

        max_payload, error = to_nonnegative_int(
            max_payloads[i],
            "最大積載量",
            i + 1
        )

        if error:
            return return_form_errors([
                (error, "max_payload")
            ])

        first_registration_date, error = validate_import_date(
            first_registration_dates[i],
            "初年度登録日",
            i + 1
        )

        if error:
            return return_form_errors([
                (error, "first_registration_date")
            ])

        inspection_expiry, error = validate_import_date(
            inspection_expiries[i],
            "車検満了日",
            i + 1
        )

        if error:
            return return_form_errors([
                (error, "inspection_expiry")
            ])

        model_code, error = validate_text_length(
            model_codes[i],
            "車体型式",
            100,
            i + 1
        )

        if error:
            return return_form_errors([
                (error, "model_code")
            ])

        manufacturer, error = validate_text_length(
            vehicle_names[i],
            "車両メーカー",
            100,
            i + 1
        )

        if error:
            return return_form_errors([
                (error, "vehicle_name")
            ])

        body_type, error = validate_text_length(
            body_types[i],
            "車両形状",
            100,
            i + 1
        )

        if error:
            return return_form_errors([
                (error, "body_type")
            ])

        selected_vehicle_type, error = validate_text_length(
            vehicle_types[i],
            "車種",
            100,
            i + 1
        )

        if error:
            return return_form_errors([
                (error, "vehicle_type")
            ])
        
        # 車台番号が一致する車両、または確認済みの訂正対象を更新
        if existing_vehicle:
            update_values = {
                "chassis_number": chassis_number,
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
                "office": offices[i],
            }

            comparison_values = dict(update_values)
            comparison_values["type"] = selected_vehicle_type
            comparison_values["deleted"] = target_deleted_values[i]

            comparison_differences = {
                key: {
                    "before": getattr(existing_vehicle, key),
                    "submitted": value,
                    "blank_preserved": (
                        key in update_values and value in ("", None)
                    ),
                }
                for key, value in comparison_values.items()
                if getattr(existing_vehicle, key) != value
            }

            if comparison_differences or clean_text(plate_numbers[i]) in (
                "1594", "4624", "71", "553"
            ):
                app.logger.warning(
                    "VEHICLE_IMPORT_COMPARE row=%s id=%s chassis=%s differences=%s",
                    i + 1,
                    existing_vehicle.id,
                    chassis_number,
                    json.dumps(comparison_differences, ensure_ascii=False),
                )

            vehicle_changed = False
            target_deleted = target_deleted_values[i]

            if bool(existing_vehicle.deleted) != target_deleted:
                existing_vehicle.deleted = target_deleted
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

            type=selected_vehicle_type,
            office=offices[i],

            deleted=target_deleted_values[i],
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
            return return_form_errors([
                (
                    "車種コードは100文字以内で入力してください。",
                    "vehicle_type_code"
                )
            ])

        if len(vehicle_type_name) > 100:
            return return_form_errors([
                (
                    "車種は100文字以内で入力してください。",
                    "vehicle_type"
                )
            ])

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

def apply_vehicle_form_values(
    vehicle,
    form_data,
    validated_values
):
    for field_key in [
        "plate_area",
        "plate_class",
        "plate_kana",
        "plate_number",
        "model_code",
        "manufacturer",
        "body_type",
    ]:
        setattr(
            vehicle,
            field_key,
            form_data.get(field_key)
        )

    for field_key in [
        "chassis_number",
        "first_registration_date",
        "inspection_expiry",
        "gross_vehicle_weight",
        "max_payload",
        "type",
        "office",
    ]:
        setattr(
            vehicle,
            field_key,
            validated_values[field_key]
        )


def validate_vehicle_master_values(
    vehicle_type,
    office,
    company_code
):
    errors = []

    for value, model, field_name, field_key in [
        (vehicle_type, VehicleType, "車種", "type"),
        (office, Office, "営業所", "office"),
    ]:
        if value:
            valid_value = model.query.filter_by(
                company_code=company_code,
                name=value
            ).first()

            if not valid_value:
                errors.append((
                    f"{field_name}が不正です。",
                    field_key
                ))

    return errors


def get_vehicle_operation_import_submission(
    csv_rows,
    company_code,
    form_data
):
    selected_lines = set(form_data.getlist("include"))
    known_lines = {
        str(row["line_number"])
        for row in csv_rows
    }

    errors = []
    selections = {}
    records = []
    selected_reports = {}

    if not selected_lines:
        errors.append((
            "取り込む行にチェックを付けてください。",
            ""
        ))

    if not selected_lines.issubset(known_lines):
        errors.append((
            "取込対象の行を確認してください。",
            ""
        ))

    valid_vehicle_ids = {
        vehicle.id
        for vehicle in Vehicle.query.filter_by(
            company_code=company_code,
            deleted=False
        ).all()
    }

    for csv_row in csv_rows:
        line_number = csv_row["line_number"]
        line_key = str(line_number)
        field_name = f"vehicle_{line_number}"
        selected = line_key in selected_lines

        vehicle_id_text = str(
            form_data.get(field_name, "")
        ).strip()

        vehicle_id = None

        if re.fullmatch(r"[1-9][0-9]{0,17}", vehicle_id_text):
            candidate_id = int(vehicle_id_text)

            if candidate_id in valid_vehicle_ids:
                vehicle_id = candidate_id

        selections[line_key] = {
            "include": selected,
            "vehicle_record_id": vehicle_id,
        }

        if not selected:
            continue

        if vehicle_id is None:
            errors.append((
                f"{line_number}行目の登録先車両を選択してください。",
                field_name
            ))
            continue

        try:
            values = parse_vehicle_operation_csv_row(
                csv_row["source_row"],
                line_number
            )
        except UploadValidationError as error:
            errors.append((
                str(error),
                f"include_{line_number}"
            ))
            continue

        report_number = values["report_number"]

        if report_number in selected_reports:
            errors.append((
                f"{line_number}行目の日報番号は"
                f"{selected_reports[report_number]}行目と重複しています。"
                "取り込む行を1つだけ選択してください。",
                f"include_{line_number}"
            ))
            continue

        selected_reports[report_number] = line_number

        records.append({
            "line_number": line_number,
            "vehicle_record_id": vehicle_id,
            "values": values,
        })

    return selections, records, errors


def build_vehicle_operation_import_preview(csv_rows, company_code):
    if not company_code:
        raise UploadValidationError(
            "会社情報を確認できませんでした。"
        )

    vehicles, plate_candidates = (
        get_vehicle_operation_plate_candidates(company_code)
    )

    saved_vehicle_mappings = {}

    mappings = (
        VehicleOperationVehicleMapping.query
        .filter_by(company_code=company_code)
        .all()
    )

    for mapping in mappings:
        source_number = normalize_vehicle_operation_plate(
            mapping.source_vehicle_number
        )

        if mapping.vehicle_record_id not in (
            plate_candidates.get(source_number, [])
        ):
            continue

        mapping_key = (
            (mapping.source_vehicle_code or "").strip(),
            source_number,
        )
        saved_vehicle_mappings[mapping_key] = (
            mapping.vehicle_record_id
        )

    report_counts = {}

    for csv_row in csv_rows:
        report_number = (
            csv_row["source_row"]
            .get("日報番号", "")
            .strip()
        )

        if report_number:
            report_counts[report_number] = (
                report_counts.get(report_number, 0) + 1
            )

    report_numbers = sorted(report_counts)
    existing_records = {}

    for start in range(0, len(report_numbers), 400):
        records = (
            VehicleOperationRecord.query
            .filter(
                VehicleOperationRecord.company_code == company_code,
                VehicleOperationRecord.report_number.in_(
                    report_numbers[start:start + 400]
                )
            )
            .all()
        )

        for record in records:
            existing_records[record.report_number] = record.id

    preview_rows = []

    for csv_row in csv_rows:
        source_row = csv_row["source_row"]
        line_number = csv_row["line_number"]
        report_number = source_row.get("日報番号", "").strip()

        preview_row = {
            "line_number": line_number,
            "source_row": source_row,
            "values": {},
            "vehicle_record_id": None,
            "candidate_vehicle_ids": [],
            "duplicate_in_file": (
                report_counts.get(report_number, 0) > 1
            ),
            "existing_record_id": existing_records.get(
                report_number
            ),
            "errors": [],
        }

        try:
            values = parse_vehicle_operation_csv_row(
                source_row,
                line_number
            )
        except UploadValidationError as error:
            preview_row["errors"].append(str(error))
        else:
            values.pop("source_row_json", None)

            for field_name in (
                "departure_meter",
                "arrival_meter",
                "distance",
            ):
                if values[field_name] is not None:
                    values[field_name] = str(values[field_name])

            preview_row["values"] = values

            plate = normalize_vehicle_operation_plate(
                values.get("source_vehicle_number")
            )
            candidate_ids = plate_candidates.get(plate, [])

            preview_row["candidate_vehicle_ids"] = list(
                candidate_ids
            )

            mapping_key = (
                str(
                    values.get("source_vehicle_code") or ""
                ).strip(),
                plate,
            )
            mapped_vehicle_id = saved_vehicle_mappings.get(
                mapping_key
            )

            if mapped_vehicle_id is not None:
                preview_row["vehicle_record_id"] = (
                    mapped_vehicle_id
                )
            elif len(candidate_ids) == 1:
                preview_row["vehicle_record_id"] = (
                    candidate_ids[0]
                )

        preview_rows.append(preview_row)

    return vehicles, preview_rows


def get_vehicle_operation_summary(company_code, vehicle_record_id):
    latest_meter_record = (
        VehicleOperationRecord.query
        .filter(
            VehicleOperationRecord.company_code == company_code,
            VehicleOperationRecord.vehicle_record_id == vehicle_record_id,
            VehicleOperationRecord.arrival_meter.isnot(None)
        )
        .order_by(
            db.func.coalesce(
                VehicleOperationRecord.arrival_at,
                VehicleOperationRecord.operation_date
            ).desc(),
            VehicleOperationRecord.operation_date.desc(),
            VehicleOperationRecord.id.desc()
        )
        .first()
    )

    if latest_meter_record is None:
        return {
            "current_mileage": None,
            "mileage_date": None,
        }

    return {
        "current_mileage": latest_meter_record.arrival_meter,
        "mileage_date": (
            latest_meter_record.arrival_at
            or latest_meter_record.operation_date
        ),
    }


def get_vehicle_registration_plate_conflicts(
    company_code,
    plate_area,
    plate_class,
    plate_kana,
    plate_number,
    chassis_number,
    exclude_vehicle_id=None,
    existing_vehicles=None
):
    plate_parts = (
        plate_area,
        plate_class,
        plate_kana,
        plate_number,
    )
    normalized_parts = tuple(
        normalize_vehicle_operation_plate(value)
        for value in plate_parts
    )

    # 不完全なナンバーから同一車両と判断しない
    if not all(normalized_parts):
        return []

    if existing_vehicles is None:
        existing_vehicles = Vehicle.query.filter_by(
            company_code=company_code
        ).order_by(Vehicle.id.asc()).all()

    conflicts = []

    for vehicle in existing_vehicles:
        if vehicle.company_code != company_code:
            continue

        if vehicle.id == exclude_vehicle_id:
            continue
        existing_parts = tuple(
            normalize_vehicle_operation_plate(value)
            for value in (
                vehicle.plate_area,
                vehicle.plate_class,
                vehicle.plate_kana,
                vehicle.plate_number,
            )
        )

        if existing_parts != normalized_parts:
            continue

        if (
            str(vehicle.chassis_number or "").strip()
            == str(chassis_number or "").strip()
        ):
            continue

        conflicts.append({
            "id": vehicle.id,
            "chassis_number": vehicle.chassis_number or "",
            "office": vehicle.office or "",
            "inactive": bool(vehicle.deleted),
        })

    return conflicts


def normalize_vehicle_operation_plate(value):
    import unicodedata

    text = unicodedata.normalize(
        "NFKC",
        "" if value is None else str(value)
    ).strip()

    return re.sub(
        r"[\s\-‐‑‒–—―−・･.]+",
        "",
        text
    ).casefold()


def get_vehicle_operation_plate_candidates(company_code):
    vehicles = (
        Vehicle.query
        .filter_by(
            company_code=company_code,
            deleted=False
        )
        .order_by(Vehicle.id.asc())
        .all()
    )

    plate_candidates = {}

    for vehicle in vehicles:
        if not all((
            vehicle.plate_area,
            vehicle.plate_class,
            vehicle.plate_kana,
            vehicle.plate_number,
        )):
            continue

        plate = normalize_vehicle_operation_plate(
            vehicle_number({
                "plate_area": vehicle.plate_area,
                "plate_class": vehicle.plate_class,
                "plate_kana": vehicle.plate_kana,
                "plate_number": vehicle.plate_number,
            })
        )

        if plate:
            plate_candidates.setdefault(
                plate,
                []
            ).append(vehicle.id)

    return vehicles, plate_candidates


def parse_vehicle_operation_csv_row(source_row, line_number):
    try:
        report_number = source_row.get("日報番号", "").strip()

        if not report_number:
            raise UploadValidationError(
                "日報番号がありません。"
            )

        if len(report_number) > 100:
            raise UploadValidationError(
                "日報番号は100文字以内にしてください。"
            )

        operation_date = parse_vehicle_operation_date(
            source_row.get("運行日"),
            "運行日"
        )

        if operation_date is None:
            raise UploadValidationError(
                "運行日がありません。"
            )

        values = {
            "report_number": report_number,
            "operation_date": operation_date,
            "source_row_json": json.dumps(
                source_row,
                ensure_ascii=False
            ),
        }

        for csv_name, field_name in (
            ("車両コード", "source_vehicle_code"),
            ("車両", "source_vehicle_number"),
        ):
            text = source_row.get(csv_name, "").strip()

            if len(text) > 100:
                raise UploadValidationError(
                    f"{csv_name}は100文字以内にしてください。"
                )

            values[field_name] = text or None

        for csv_name, field_name in (
            ("出庫日時", "departure_at"),
            ("入庫日時", "arrival_at"),
        ):
            values[field_name] = parse_vehicle_operation_date(
                source_row.get(csv_name),
                csv_name,
                with_time=True
            )

        for csv_name, field_name in (
            ("出庫メータ", "departure_meter"),
            ("入庫メータ", "arrival_meter"),
            ("走行距離", "distance"),
        ):
            values[field_name] = parse_vehicle_operation_decimal(
                source_row.get(csv_name),
                csv_name
            )

        return values

    except UploadValidationError as error:
        raise UploadValidationError(
            f"CSVの{line_number}行目：{error}"
        ) from error


def read_vehicle_operation_csv(file_bytes):
    csv_text = None

    for encoding in ("utf-8-sig", "cp932"):
        try:
            csv_text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if csv_text is None:
        raise UploadValidationError(
            "CSVの文字コードを確認してください。"
        )

    if "\x00" in csv_text:
        raise UploadValidationError(
            "CSVファイルの内容が不正です。"
        )

    rows = []

    try:
        reader = csv.reader(
            StringIO(csv_text, newline=""),
            strict=True
        )
        headers = [
            value.strip()
            for value in next(reader, [])
        ]

        if not headers or any(not value for value in headers):
            raise UploadValidationError(
                "CSVの先頭行に項目名を設定してください。"
            )

        if len(headers) != len(set(headers)):
            raise UploadValidationError(
                "CSVの項目名が重複しています。"
            )

        missing_headers = [
            name
            for name in ("日報番号", "運行日")
            if name not in headers
        ]

        if missing_headers:
            raise UploadValidationError(
                "CSVに必要な項目がありません："
                + "、".join(missing_headers)
            )

        if not any(
            name in headers
            for name in ("車両コード", "車両")
        ):
            raise UploadValidationError(
                "CSVに車両コードまたは車両の項目が必要です。"
            )

        for values in reader:
            if not any(value.strip() for value in values):
                continue

            if len(values) != len(headers):
                raise UploadValidationError(
                    f"CSVの{reader.line_num}行目の列数が"
                    "項目名の列数と一致していません。"
                )

            rows.append({
                "line_number": reader.line_num,
                "source_row": dict(zip(headers, values)),
            })

    except csv.Error:
        raise UploadValidationError(
            "CSVの区切り文字・引用符を確認してください。"
        )

    if not rows:
        raise UploadValidationError(
            "CSVに運行実績のデータがありません。"
        )

    return rows


def parse_vehicle_operation_date(value, field_name, with_time=False):
    text = "" if value is None else str(value).strip()

    if not text:
        return None

    if with_time:
        formats = (
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M",
        )
        output_format = "%Y-%m-%d %H:%M:%S"
    else:
        formats = (
            "%Y/%m/%d",
            "%Y-%m-%d",
        )
        output_format = "%Y-%m-%d"

    for date_format in formats:
        try:
            parsed = datetime.strptime(text, date_format)
        except ValueError:
            continue

        return parsed.strftime(output_format)

    raise UploadValidationError(
        f"{field_name}の日付・時刻を確認してください。"
    )


def parse_vehicle_operation_decimal(value, field_name):
    text = "" if value is None else str(value).strip()

    if not text:
        return None

    if not re.fullmatch(
        r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?",
        text
    ):
        raise UploadValidationError(
            f"{field_name}は0以上の数値で入力してください。"
        )

    try:
        parsed = Decimal(text.replace(",", ""))
    except InvalidOperation:
        raise UploadValidationError(
            f"{field_name}の数値を確認してください。"
        )

    if not parsed.is_finite() or parsed > Decimal("999999999999.99"):
        raise UploadValidationError(
            f"{field_name}の値が大きすぎます。"
        )

    try:
        rounded = parsed.quantize(Decimal("0.01"))
    except InvalidOperation:
        raise UploadValidationError(
            f"{field_name}の数値を確認してください。"
        )

    if parsed != rounded:
        raise UploadValidationError(
            f"{field_name}は小数点以下2桁までで入力してください。"
        )

    return rounded


def parse_vehicle_weights(form_data):
    values = {
        "gross_vehicle_weight": 0,
        "max_payload": 0,
    }
    errors = []

    for field_key, field_name in [
        ("gross_vehicle_weight", "車両総重量"),
        ("max_payload", "最大積載量"),
    ]:
        try:
            values[field_key] = parse_nonnegative_int(
                form_data.get(field_key),
                field_name
            )
        except UploadValidationError:
            errors.append((
                f"{field_name}の入力内容を確認してください。",
                field_key
            ))

    return values, errors


def get_vehicle_text_length_error(
    value,
    field_name,
    max_length
):
    if len(value) > max_length:
        return (
            f"{field_name}は"
            f"{max_length}文字以内で入力してください。"
        )

    return None


def get_vehicle_date_error(value, field_name):
    if not value:
        return None

    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return f"{field_name}が不正です。"

    return None


def validate_vehicle_dates(
    first_registration_date,
    inspection_expiry
):
    errors = []

    for value, field_name, field_key in [
        (
            first_registration_date,
            "初年度登録日",
            "first_registration_date"
        ),
        (
            inspection_expiry,
            "車検満了日",
            "inspection_expiry"
        ),
    ]:
        error = get_vehicle_date_error(
            value,
            field_name
        )

        if error:
            errors.append((
                error,
                field_key
            ))

    return errors

def validate_vehicle_text_fields(form_data):
    field_settings = [
        ("plate_area", "車番・地域名", 50),
        ("plate_class", "車番・分類", 50),
        ("plate_kana", "車番・ひらがな", 10),
        ("plate_number", "車番", 50),
        ("chassis_number", "車台番号", 100),
        ("model_code", "車体型式", 100),
        ("manufacturer", "車両メーカー", 100),
        ("body_type", "車両形状", 100),
    ]

    errors = []

    for field_key, field_name, max_length in field_settings:
        value = form_data.get(field_key, "").strip()

        error = get_vehicle_text_length_error(
            value,
            field_name,
            max_length
        )

        if error:
            errors.append((
                error,
                field_key
            ))

    return errors


@app.route("/master/vehicles/register")
def vehicle_registration_method():
    return render_template(
        "vehicle_registration_method.html"
    )


@app.route("/master/vehicles/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def new_vehicle():
    if request.method == "POST":
        if request.form.get("vehicle_form_action") == "back":
            return render_template(
                "vehicle_form.html",
                vehicle=request.form.to_dict(flat=True),
                offices=offices_for_current_company(),
                vehicle_types=vehicle_types_for_current_company(),
                mode="new"
            )

        form_errors = []

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
                return return_form_errors([
                    ("登録可能台数の上限に達しています。", "")
                ], 409)

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

        form_errors.extend(
            validate_vehicle_dates(
                first_registration_date,
                inspection_expiry
            )
        )

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
            form_errors.append((
                "車台番号を入力してください。",
                "chassis_number"
            ))

        duplicate_vehicle = Vehicle.query.filter_by(
            company_code=company_code,
            chassis_number=chassis_number
        ).first()

        if duplicate_vehicle:
            if not duplicate_vehicle.deleted:
                return return_form_errors([
                    (
                        "同じ車台番号の車両が既に登録されています。",
                        "chassis_number"
                    )
                ], 409)

        form_errors.extend(
            validate_vehicle_text_fields(request.form)
        )

        form_errors.extend(
            validate_vehicle_master_values(
                vehicle_type,
                office,
                company_code
            )
        )
        weight_values, weight_errors = parse_vehicle_weights(
            request.form
        )
        form_errors.extend(weight_errors)

        gross_vehicle_weight = weight_values["gross_vehicle_weight"]
        max_payload = weight_values["max_payload"]

        if form_errors:
            return return_form_errors(form_errors)

        if request.form.get("vehicle_form_action") != "save":
            confirmation_values = request.form.to_dict(
                flat=True
            )
            confirmation_values.update({
                "chassis_number": chassis_number,
                "first_registration_date": first_registration_date,
                "inspection_expiry": inspection_expiry,
                "gross_vehicle_weight": gross_vehicle_weight,
                "max_payload": max_payload,
                "type": vehicle_type,
                "office": office,
            })

            return render_template(
                "vehicle_registration_confirm.html",
                vehicle=confirmation_values
            )

        vehicle = duplicate_vehicle or Vehicle(
            company_code=company_code,
            chassis_number=chassis_number
        )

        vehicle.deleted = False
        apply_vehicle_form_values(
            vehicle,
            request.form,
            {
                "chassis_number": chassis_number,
                "first_registration_date": first_registration_date,
                "inspection_expiry": inspection_expiry,
                "gross_vehicle_weight": gross_vehicle_weight,
                "max_payload": max_payload,
                "type": vehicle_type,
                "office": office,
            }
        )

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
        if request.form.get("vehicle_form_action") == "back":
            form_values = request.form.to_dict(flat=True)
            form_values["vehicle_record_id"] = vehicle.id

            return render_template(
                "vehicle_form.html",
                vehicle=form_values,
                index=vehicle.id,
                offices=offices_for_current_company(),
                vehicle_types=vehicle_types_for_current_company(),
                mode="edit"
            )

        form_errors = []

        chassis_number = (
            request.form.get("chassis_number", "").strip()
        )

        if not chassis_number:
            form_errors.append((
                "車台番号を入力してください。",
                "chassis_number"
            ))

        duplicate_vehicle = Vehicle.query.filter(
            Vehicle.company_code == vehicle.company_code,
            Vehicle.chassis_number == chassis_number,
            Vehicle.id != vehicle.id
        ).first()

        if duplicate_vehicle:
            return return_form_errors([
                (
                    "同じ車台番号の車両が既に登録されています。",
                    "chassis_number"
                )
            ], 409)

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

        form_errors.extend(
            validate_vehicle_dates(
                first_registration_date,
                inspection_expiry
            )
        )

        vehicle_type = (
            request.form.get("type", "").strip()
        )

        office = (
            request.form.get("office", "").strip()
        )

        form_errors.extend(
            validate_vehicle_text_fields(request.form)
        )


        form_errors.extend(
            validate_vehicle_master_values(
                vehicle_type,
                office,
                vehicle.company_code
            )
        )
        weight_values, weight_errors = parse_vehicle_weights(
            request.form
        )
        form_errors.extend(weight_errors)

        gross_vehicle_weight = weight_values["gross_vehicle_weight"]
        max_payload = weight_values["max_payload"]

        if form_errors:
            return return_form_errors(form_errors)

        if request.form.get("vehicle_form_action") != "save":
            confirmation_values = request.form.to_dict(
                flat=True
            )
            confirmation_values.update({
                "chassis_number": chassis_number,
                "first_registration_date": first_registration_date,
                "inspection_expiry": inspection_expiry,
                "gross_vehicle_weight": gross_vehicle_weight,
                "max_payload": max_payload,
                "type": vehicle_type,
                "office": office,
            })

            previous_values = {
                field_key: getattr(vehicle, field_key)
                for field_key in [
                    "plate_area",
                    "plate_class",
                    "plate_kana",
                    "plate_number",
                    "chassis_number",
                    "model_code",
                    "first_registration_date",
                    "manufacturer",
                    "body_type",
                    "gross_vehicle_weight",
                    "max_payload",
                    "type",
                    "office",
                    "inspection_expiry",
                ]
            }

            return render_template(
                "vehicle_edit_confirm.html",
                vehicle=confirmation_values,
                previous_vehicle=previous_values,
                index=vehicle.id
            )

        apply_vehicle_form_values(
            vehicle,
            request.form,
            {
                "chassis_number": chassis_number,
                "first_registration_date": first_registration_date,
                "inspection_expiry": inspection_expiry,
                "gross_vehicle_weight": gross_vehicle_weight,
                "max_payload": max_payload,
                "type": vehicle_type,
                "office": office,
            }
        )

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

    vehicle_edit_form_data = session.pop(
        "vehicle_edit_form_data",
        {}
    )

    if vehicle_edit_form_data:
        vehicle_dict.update(vehicle_edit_form_data)

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

    related_records = (
        (VehiclePatrol, "vehicle_record_id"),
        (VehicleChecklistResult, "vehicle_record_id"),
        (ChecklistResult, "target_vehicle_record_id"),
        (VehicleDrivingReportRecord, "vehicle_record_id"),
        (VehiclePeriodicInspectionRecord, "vehicle_record_id"),
        (VehicleOperationRecord, "vehicle_record_id"),
        (VehicleMaintenanceRecord, "vehicle_record_id"),
        (VehicleOperationVehicleMapping, "vehicle_record_id"),
    )

    for model, vehicle_field in related_records:
        related_record = model.query.filter(
            model.company_code == company_code,
            getattr(model, vehicle_field).in_(
                vehicle_record_ids_to_delete
            )
        ).first()

        if related_record:
            return return_form_errors([
                (
                    "履歴または運行実績の対応付けがある車両を"
                    "含むため完全削除できません。"
                    "対象車両は無効化してください。",
                    ""
                )
            ], status_code=409)

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

    related_records = (
        (VehiclePatrol, "vehicle_record_id"),
        (VehicleChecklistResult, "vehicle_record_id"),
        (ChecklistResult, "target_vehicle_record_id"),
        (VehicleDrivingReportRecord, "vehicle_record_id"),
        (VehiclePeriodicInspectionRecord, "vehicle_record_id"),
        (VehicleOperationRecord, "vehicle_record_id"),
        (VehicleMaintenanceRecord, "vehicle_record_id"),
        (VehicleOperationVehicleMapping, "vehicle_record_id"),
    )

    for model, vehicle_field in related_records:
        related_record = model.query.filter_by(
            company_code=vehicle.company_code,
            **{vehicle_field: vehicle_record_id}
        ).first()

        if related_record:
            return return_form_errors([
                (
                    "履歴または運行実績の対応付けがある車両は"
                    "完全削除できません。無効化してください。",
                    ""
                )
            ], status_code=409)

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

        old_filename = os.path.basename(
            str(manual.filename or "")
        )

        file = request.files.get("file")
        filename = save_uploaded_file(
            file,
            folder="static/manuals"
        )

        if filename:
            manual.filename = filename

        db.session.commit()

        if (
            filename
            and old_filename
            and old_filename != filename
        ):
            if s3_client and S3_BUCKET_NAME:
                try:
                    s3_client.delete_object(
                        Bucket=S3_BUCKET_NAME,
                        Key=(
                            f"manuals/"
                            f"{manual.company_code}/"
                            f"{old_filename}"
                        )
                    )
                except ClientError:
                    app.logger.warning(
                        "旧マニュアルファイルのS3削除に失敗しました。",
                        exc_info=True
                    )
            else:
                safe_filename = secure_filename(
                    old_filename
                )

                if safe_filename:
                    file_path = os.path.join(
                        "static/manuals",
                        manual.company_code,
                        safe_filename
                    )

                    if os.path.exists(file_path):
                        os.remove(file_path)

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

    filename = os.path.basename(
        str(manual.filename or "")
    )

    company_code = manual.company_code

    db.session.delete(manual)
    db.session.commit()

    if filename:
        if s3_client and S3_BUCKET_NAME:
            try:
                s3_client.delete_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=(
                        f"manuals/"
                        f"{company_code}/"
                        f"{filename}"
                    )
                )
            except ClientError:
                app.logger.warning(
                    "マニュアルファイルのS3削除に失敗しました。",
                    exc_info=True
                )
        else:
            safe_filename = secure_filename(
                filename
            )

            if safe_filename:
                file_path = os.path.join(
                    "static/manuals",
                    company_code,
                    safe_filename
                )

                if os.path.exists(file_path):
                    os.remove(file_path)

    return redirect("/master/manuals")

@app.route("/master/checklists")
def checklist_master():
    try:
        ensure_daily_inspection_checklist()
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("日常点検の標準様式の登録に失敗しました。")
        flash("日常点検の標準様式を登録できませんでした。", "error:")
        return render_template(
            "checklist_master.html",
            checklists=[],
            keyword=request.args.get("keyword", "").strip(),
            target=request.args.get("target", "").strip(),
            status=request.args.get("status", "").strip()
        ), 500

    checklists = checklists_for_current_company()
    company_code = session.get("company_code")

    keyword = request.args.get("keyword", "").strip()
    target = request.args.get("target", "").strip()
    status = request.args.get("status", "").strip()

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

    if keyword:
        keyword_lower = keyword.lower()
        checklists = [
            checklist
            for checklist in checklists
            if keyword_lower in checklist["name"].lower()
        ]

    if target:
        checklists = [
            checklist
            for checklist in checklists
            if checklist["target"] == target
        ]

    if status == "active":
        checklists = [
            checklist
            for checklist in checklists
            if checklist["active"]
        ]
    elif status == "inactive":
        checklists = [
            checklist
            for checklist in checklists
            if not checklist["active"]
        ]

    return render_template(
        "checklist_master.html",
        checklists=checklists,
        keyword=keyword,
        target=target,
        status=status
    )

@app.route("/master/checklists/new", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def new_checklist():
    if request.method == "POST":
        form_errors = []

        target = request.form.get("target", "").strip()

        if target not in {
            "安全管理",
            "車両管理"
        }:
            form_errors.append((
                "用途が不正です。",
                "target"
            ))

        item_categories = request.form.getlist("item_category")
        item_contents = request.form.getlist("item_content")
        input_types = request.form.getlist("input_type")
        item_types = request.form.getlist("item_type")
        approval_labels = request.form.getlist("approval_label")
        approval_allow_general_list = request.form.getlist("approval_allow_general")
        choices_list = request.form.getlist("choices")
        criteria_list = request.form.getlist("criteria")
        answer_required_list = request.form.getlist("answer_required")
        shaded_list = request.form.getlist("shaded")

        if len(item_types) > 500:
            form_errors.append((
                "チェック項目は500件以内で設定してください。",
                "item_type_0"
            ))

        for i, item_type in enumerate(item_types):
            if item_type not in {
                "check",
                "inspector",
                "approval"
            }:
                form_errors.append((
                    "項目種別が不正です。",
                    f"item_type_{i}"
                ))

        for i, input_type in enumerate(input_types):
            if input_type not in {
                "select",
                "text"
            }:
                form_errors.append((
                    "評価方式が不正です。",
                    f"input_type_{i}"
                ))

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
            form_errors.append((
                "チェック項目のデータが不正です。",
                "item_type_0"
            ))

        if form_errors:
            return return_form_errors(form_errors)

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

        reminder_time = "08:00"

        try:
            reminder_time = parse_time_hhmm(
                request.form.get("reminder_time") or "08:00",
                "未実施通知時刻"
            )
        except UploadValidationError:
            form_errors.append((
                "未実施通知時刻の入力内容を確認してください。",
                "reminder_time"
            ))

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
                    form_errors.append((
                        "承認ラベルは100文字以内で入力してください。",
                        f"approval_label_{i}"
                    ))

                items.append({
                    "item_type": "approval",
                    "approval_label": label,
                    "approval_allow_general": str(i) in approval_allow_general_list,
                    "criteria_files": [],
                })

                continue

            if i >= len(item_contents):
                continue

            if (
                not item_contents[i]
                and input_types[i] != "text"
            ):
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
                form_errors.append((
                    "カテゴリは100文字以内で入力してください。",
                    f"item_category_{i}"
                ))

            if len(content) > 500:
                form_errors.append((
                    "チェック内容は500文字以内で入力してください。",
                    f"item_content_{i}"
                ))

            if len(criteria) > 500:
                form_errors.append((
                    "判定基準は500文字以内で入力してください。",
                    f"criteria_{i}"
                ))

            choices = []

            if input_types[i] == "select":
                choices = [
                    choice.strip()
                    for choice in choices_list[i].split(",")
                    if choice.strip()
                ]

                if not choices:
                    form_errors.append((
                        "選択式のチェック項目には評価の選択肢を1つ以上入力してください。",
                        f"choices_{i}"
                    ))
                elif len(choices) > 100:
                    form_errors.append((
                        "選択肢は100個以内で入力してください。",
                        f"choices_{i}"
                    ))
                elif any(
                    len(choice) > 100
                    for choice in choices
                ):
                    form_errors.append((
                        "各選択肢は100文字以内で入力してください。",
                        f"choices_{i}"
                    ))

            item_index = len(items)

            items.append({
                "item_type": "check",
                "category": category,
                "content": content,
                "input_type": input_types[i],
                "choices": choices,
                "criteria": criteria,
                "criteria_files": [],
                "answer_required": str(i) in answer_required_list,
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
                form_errors.append((
                    "頻度は整数で入力してください。",
                    "frequency_value"
                ))
                frequency_number = None

            if frequency_number is not None:
                if frequency_number < 1:
                    form_errors.append((
                        "頻度は1以上で入力してください。",
                        "frequency_value"
                    ))
                elif frequency_number > 9999:
                    form_errors.append((
                        "頻度は9999以下で入力してください。",
                        "frequency_value"
                    ))
                else:
                    frequency_value = str(frequency_number)

            if frequency_unit not in {
                "day",
                "month",
                "year"
            }:
                form_errors.append((
                    "頻度単位が不正です。",
                    "frequency_unit"
                ))

            if display_type not in {
                "month",
                "year"
            }:
                form_errors.append((
                    "表示形式が不正です。",
                    "display_type"
                ))

        name = request.form.get("name", "").strip()

        if not name:
            form_errors.append((
                "チェックリスト名を入力してください。",
                "name"
            ))
        elif len(name) > 200:
            form_errors.append((
                "チェックリスト名は200文字以内で入力してください。",
                "name"
            ))

        duplicate_checklist = Checklist.query.filter_by(
            company_code=session.get("company_code"),
            name=name
        ).first()

        if duplicate_checklist:
            form_errors.append((
                "このチェックリストはすでに登録されています。",
                "name"
            ))

        if form_errors:
            return return_form_errors(
                form_errors,
                409 if duplicate_checklist else 400
            )

        pending_uploads = []

        if not session.get("company_code"):
            return "company_code is required for file upload.", 400

        upload_file_count = sum(
            1
            for field_name in request.files.keys()
            for file in request.files.getlist(field_name)
            if file and file.filename
        )

        if upload_file_count > 50:
            return (
                "一度にアップロードできるファイルは50件までです。",
                400
            )

        for item_index, form_index in pending_criteria_files:
            for file in request.files.getlist(
                f"criteria_files_{form_index}"
            ):
                if not file or not file.filename:
                    continue

                original_filename = os.path.basename(
                    str(file.filename or "")
                )

                extension = os.path.splitext(
                    original_filename
                )[1].lower()

                if (
                    extension not in ALLOWED_UPLOAD_EXTENSIONS
                    or not is_valid_uploaded_file(
                        file,
                        extension
                    )
                ):
                    return "添付ファイルの検証に失敗しました。", 400

                pending_uploads.append(
                    (item_index, file)
                )

        for item_index, file in pending_uploads:
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

    checklist_form_data = session.pop(
        "checklist_form_data",
        {}
    )

    retained_checklist = checklist_form_data_to_dict(
        checklist_form_data
    )

    return render_template(
        "checklist_form.html",
        checklist=retained_checklist,
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

    for result in query.order_by(
        ChecklistResult.checked_date.desc(),
        ChecklistResult.id.desc()
    ).all():
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
                "candidate_usernames": [],
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        result["approvals"] = approvals

    approval_items = [
        item
        for item in checklist.get("items", [])
        if item.get("item_type") == "approval"
    ]

    for approval_index, approval in enumerate(
        result.get("approvals", [])
    ):
        if (
            "allow_general" not in approval
            and approval_index < len(approval_items)
        ):
            approval["allow_general"] = approval_items[
                approval_index
            ].get(
                "approval_allow_general",
                False
            )

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
        if item.get("item_type") == "check"
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

    result_items = []

    for item, answer in zip(
        check_items,
        result["answers"]
    ):
        result_item = dict(answer)
        result_item["input_type"] = item.get(
            "input_type",
            ""
        )

        result_item["has_detail"] = bool(
            str(
                answer.get("comment", "")
                or ""
            ).strip()
            or answer.get("files")
        )

        result_items.append(result_item)

    checklist_event_records = ChecklistEvent.query.filter_by(
        company_code=result_record.company_code,
        result_type="safety",
        result_id=result_record.id
    ).order_by(
        ChecklistEvent.id.asc()
    ).all()

    checklist_events = []

    for event in checklist_event_records:
        checklist_events.append({
            "event_type": event.event_type,
            "actor_username": event.actor_username,
            "actor_name": event.actor_name,
            "created_at": event.created_at,
            "detail": safe_json_dict(
                event.detail_json
            ),
        })

    current_approval = next(
        (
            approval
            for approval in result.get("approvals", [])
            if not (
                approval.get("approved_by")
                or approval.get("approved_by_username")
            )
        ),
        None
    )

    return render_template(
        "checklist_result_detail.html",
        result=result,
        result_index=result_record.id,
        summary=summary,
        total_score=total_score,
        max_score=max_score,
        criteria_list=criteria_list,
        result_items=result_items,
        checklist=checklist,
        can_manage=can_manage_checklist_result(result),
        can_reject=can_reject_checklist_result(
            result,
            current_approval
        ),
        checklist_events=checklist_events,
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
        if item.get("item_type") == "check"
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
            " ".join(
                value
                for value in [
                    target_vehicle_record.plate_area or "",
                    target_vehicle_record.plate_class or "",
                    target_vehicle_record.plate_kana or "",
                    target_vehicle_record.plate_number or "",
                ]
                if value
            ) or "ナンバー未登録"
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
        ["実施者", result["checked_by"] or ""],
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

    # 押印欄（実施者・承認項目をマスタの並び順で出力）
    approval_items = [
        item
        for item in checklist["items"]
        if item.get("item_type") in {"inspector", "approval"}
    ]

    approval_results = result.get("approvals", [])

    stamp_entries = []

    approval_index = 0

    for item in approval_items:
        if item.get("item_type") == "inspector":
            stamp_entries.append({
                "label": "実施者",
                "approved_by": result.get("checked_by", ""),
                "approved_by_username": result.get(
                    "checked_by_username",
                    ""
                ),
                "approved_date": result.get("checked_date", ""),
            })
            continue

        label = (
            item.get("approval_label", "").strip()
            or "承認"
        )

        approval_result = (
            approval_results[approval_index]
            if approval_index < len(approval_results)
            else {}
        )

        stamp_entries.append({
            "label": label,
            "approved_by": approval_result.get("approved_by", ""),
            "approved_by_username": approval_result.get(
                "approved_by_username",
                ""
            ),
            "approved_date": approval_result.get("approved_date", ""),
        })

        approval_index += 1

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
                approval_user = User.query.filter_by(
                    company_code=result_record.company_code,
                    username=entry.get("approved_by_username")
                ).first()

                stamp_value = (
                    approval_user.last_name
                    if approval_user
                    else (
                        entry.get("approved_by")
                        or entry.get("approved_by_username")
                        or ""
                    )
                )

                if stamp_value and entry["approved_date"]:
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

    checklist = (
        result.get("checklist_snapshot")
        or checklist_to_dict(checklist_record)
    )

    if request.method == "POST":
        company_code = session.get("company_code")

        result_record = ChecklistResult.query.filter_by(
            id=result_index,
            company_code=company_code
        ).with_for_update().first()

        if not result_record:
            return redirect("/safety/checklists")

        if result_record.status == "承認済み":
            return redirect(
                f"/safety/checklist-results/{result_index}"
            )

        db.session.refresh(result_record)
        result = checklist_result_to_dict(result_record)

        if not can_manage_checklist_result(result):
            return redirect(
                f"/safety/checklist-results/{result_index}"
            )

        checklist = (
            result.get("checklist_snapshot")
            or checklist_to_dict(checklist_record)
        )

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
            return return_form_errors([
                (
                    "対象種別が不正です。",
                    "target_type"
                )
            ])

        # =========================
        # 個人
        # =========================

        if target_type == "user":
            if not target_user:
                return return_form_errors([
                    (
                        "対象ユーザーを選択してください。",
                        "target_user"
                    )
                ])

            target_driver = Driver.query.filter_by(
                company_code=company_code,
                employee_id=target_user
            ).first()

            if not target_driver:
                return return_form_errors([
                    (
                        "対象ユーザーが不正です。",
                        "target_user"
                    )
                ])

            target_user_record = User.query.filter_by(
                company_code=company_code,
                username=target_driver.employee_id
            ).first()

            if not target_user_record:
                return return_form_errors([
                    (
                        "対象ユーザー情報が不正です。",
                        "target_user"
                    )
                ])

            target_username = target_user_record.username
            target_user = target_driver.name

            target_office = target_driver.office or ""
            target_vehicle_record_id = None

        # =========================
        # 車両
        # =========================

        elif target_type == "vehicle":
            if not target_vehicle_record_id:
                return return_form_errors([
                    (
                        "対象車両を選択してください。",
                        "target_vehicle_record_id"
                    )
                ])

            vehicle = Vehicle.query.filter_by(
                company_code=company_code,
                id=target_vehicle_record_id,
                deleted=False
            ).first()

            if not vehicle:
                return return_form_errors([
                    (
                        "対象車両が不正です。",
                        "target_vehicle_record_id"
                    )
                ])

            target_office = vehicle.office or ""
            target_user = ""
            target_username = ""

        # =========================
        # 営業所
        # =========================

        elif target_type == "office":
            if not target_office:
                return return_form_errors([
                    (
                        "対象営業所を選択してください。",
                        "target_office"
                    )
                ])

            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=target_office
            ).first()

            if not valid_office:
                return return_form_errors([
                    (
                        "対象営業所が不正です。",
                        "target_office"
                    )
                ])

            target_user = ""
            target_username = ""
            target_vehicle_record_id = None

        previous_answers = [
            dict(answer)
            for answer in result.get("answers", [])
        ]

        previous_target = {
            "target_type": result_record.target_type or "",
            "target_user": result_record.target_user or "",
            "target_username": result_record.target_username or "",
            "target_vehicle_record_id": (
                result_record.target_vehicle_record_id
            ),
            "target_office": result_record.target_office or "",
        }

        answers = []
        answer_index = 0
        pending_answer_files = []

        for item in checklist["items"]:
            if item.get("item_type") != "check":
                continue

            value = request.form.get(
                f"answer_{answer_index}",
                ""
            )

            choices = item.get("choices", [])

            if item.get("input_type") == "select":
                if value and value not in choices:
                    return return_form_errors([
                        (
                            "評価値が不正です。",
                            f"answer_{answer_index}"
                        )
                    ])

            comment = request.form.get(
                f"comment_{answer_index}",
                ""
            ).strip()

            if (
                item.get("answer_required")
                and not value
            ):
                return return_form_errors([
                    (
                        "必須項目が未回答です。",
                        f"answer_{answer_index}"
                    )
                ])

            if len(comment) > 5000:
                return return_form_errors([
                    (
                        "コメントは5000文字以内で入力してください。",
                        f"comment_{answer_index}"
                    )
                ])

            file_names = []

            if answer_index < len(result["answers"]):
                file_names = list(
                    result["answers"][answer_index].get("files", [])
                )

            item_index = len(answers)

            answers.append({
                "item_no": answer_index,
                "category": item.get("category", ""),
                "content": item.get("content", ""),
                "criteria": item.get("criteria", ""),
                "criteria_files": item.get("criteria_files", []),
                "value": value,
                "comment": comment,
                "files": file_names,
                "patrol_link": (
                    request.form.get(
                        f"patrol_link_{answer_index}"
                    ) == "1"
                    if f"patrol_link_{answer_index}" in request.form
                    else (
                        previous_answers[answer_index].get(
                            "patrol_link",
                            False
                        )
                        if answer_index < len(previous_answers)
                        else False
                    )
                ),
            })

            pending_answer_files.append(
                (item_index, answer_index)
            )

            answer_index += 1

        pending_uploads = []

        upload_file_count = sum(
            1
            for field_name in request.files.keys()
            for file in request.files.getlist(field_name)
            if file and file.filename
        )

        if upload_file_count > 50:
            return return_form_errors([
                (
                    "一度にアップロードできるファイルは50件までです。",
                    ""
                )
            ])

        for item_index, form_index in pending_answer_files:
            for file in request.files.getlist(
                f"files_{form_index}"
            ):
                if not file or not file.filename:
                    continue

                original_filename = os.path.basename(
                    str(file.filename or "")
                )

                extension = os.path.splitext(
                    original_filename
                )[1].lower()

                if (
                    extension not in ALLOWED_UPLOAD_EXTENSIONS
                    or not is_valid_uploaded_file(
                        file,
                        extension
                    )
                ):
                    return return_form_errors([
                        (
                            "添付ファイルの検証に失敗しました。",
                            f"files_{form_index}"
                        )
                    ])

                pending_uploads.append(
                    (item_index, file)
                )

        result_record.target_type = target_type
        result_record.target_user = target_user
        result_record.target_username = target_username
        result_record.target_vehicle_record_id = target_vehicle_record_id
        result_record.target_office = target_office
        result_record.answers_json = json.dumps(answers, ensure_ascii=False)

        notify_usernames = [
            username.strip()
            for username in request.form.getlist(
                "notify_users"
            )
            if username.strip()
        ]

        notify_usernames = list(
            dict.fromkeys(notify_usernames)
        )

        if len(notify_usernames) > 500:
            return return_form_errors([
                (
                    "通知先ユーザー数が多すぎます。",
                    "notify_user_search"
                )
            ])

        valid_users = {
            user.username: user
            for user in User.query.filter_by(
                company_code=company_code
            ).all()
            if user.username
        }

        invalid_notify_usernames = [
            username
            for username in notify_usernames
            if username not in valid_users
        ]

        if invalid_notify_usernames:
            return return_form_errors([
                (
                    "通知先ユーザーが不正です。",
                    "notify_user_search"
                )
            ])

        result_record.notify_users_json = json.dumps(
            notify_usernames,
            ensure_ascii=False
        )

        approvals = []

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approval_index = len(approvals)

            submitted_candidate_usernames = [
                username.strip()
                for username in request.form.getlist(
                    f"approval_notify_users_{approval_index}"
                )
                if username.strip()
            ]

            if len(submitted_candidate_usernames) > 500:
                return return_form_errors([
                    (
                        "承認候補者数が多すぎます。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            invalid_candidate_usernames = [
                username
                for username in submitted_candidate_usernames
                if (
                    username not in valid_users
                    or not (
                        valid_users[username].role == "admin"
                        or (
                            item.get(
                                "approval_allow_general",
                                False
                            )
                            and valid_users[username].role == "user"
                        )
                    )
                )
            ]

            if invalid_candidate_usernames:
                return return_form_errors([
                    (
                        "承認者の選択内容が不正です。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get("approval_allow_general", False),
                "candidate_usernames": list(
                    dict.fromkeys(submitted_candidate_usernames)
                ),
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        saved_filenames = []

        try:
            for item_index, file in pending_uploads:
                filename = save_uploaded_file(file)

                if filename:
                    answers[item_index]["files"].append(filename)
                    saved_filenames.append(filename)

        except UploadValidationError:
            for filename in saved_filenames:
                delete_uploaded_file(filename)

            return return_form_errors([
                (
                    "添付ファイルの検証に失敗しました。",
                    ""
                )
            ])

        changes = []

        current_target = {
            "target_type": target_type,
            "target_user": target_user,
            "target_username": target_username,
            "target_vehicle_record_id": target_vehicle_record_id,
            "target_office": target_office,
        }

        if previous_target != current_target:
            changes.append({
                "type": "target",
                "before": previous_target,
                "after": current_target,
            })

        previous_answers_by_item_no = {
            answer.get("item_no"): answer
            for answer in previous_answers
            if answer.get("item_no") is not None
        }

        for answer_index, answer in enumerate(answers):
            item_no = answer.get("item_no")

            previous_answer = previous_answers_by_item_no.get(
                item_no
            )

            if previous_answer is None:
                previous_answer = (
                    previous_answers[answer_index]
                    if answer_index < len(previous_answers)
                    else {}
                )

            before = {
                "value": previous_answer.get("value", ""),
                "comment": previous_answer.get("comment", ""),
                "files": previous_answer.get("files", []),
                "patrol_link": previous_answer.get(
                    "patrol_link",
                    False
                ),
            }

            after = {
                "value": answer.get("value", ""),
                "comment": answer.get("comment", ""),
                "files": answer.get("files", []),
                "patrol_link": answer.get(
                    "patrol_link",
                    False
                ),
            }

            if before != after:
                changes.append({
                    "item_no": answer.get("item_no"),
                    "category": answer.get("category", ""),
                    "content": answer.get("content", ""),
                    "before": before,
                    "after": after,
                })

        if target_type in PATROL_VIEW_TYPES:
            previous_answers_by_item_no = {
                answer.get("item_no"): answer
                for answer in previous_answers
                if answer.get("item_no") is not None
            }

            for answer in answers:
                item_no = answer.get("item_no")

                previous_answer = (
                    previous_answers_by_item_no.get(
                        item_no,
                        {}
                    )
                )

                if (
                    answer.get("patrol_link")
                    and not previous_answer.get(
                        "patrol_link",
                        False
                    )
                ):
                    db.session.add(PatrolResult(
                        company_code=company_code,
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
                            f"{answer.get('category', '')}："
                            f"{answer.get('content', '')}"
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

        was_rejected = (
            result_record.status == "差し戻し"
        )

        result_record.status = (
            "承認待ち"
            if approvals
            else "点検完了"
        )
        result_record.approvals_json = json.dumps(
            approvals,
            ensure_ascii=False
        )
        result_record.notify_users_json = json.dumps(
            notify_usernames,
            ensure_ascii=False
        )
        result_record.approved_by = ""
        result_record.approved_by_username = ""
        result_record.approved_date = ""
        result_record.reject_reason = ""

        checklist_event = ChecklistEvent(
            company_code=result_record.company_code,
            result_type="safety",
            result_id=result_record.id,
            event_type=(
                "再申請"
                if was_rejected
                else "修正"
            ),
            actor_username=session.get("username"),
            actor_name=session.get("name"),
            detail_json=json.dumps(
                {
                    "changes": changes,
                    "approvals": approvals,
                },
                ensure_ascii=False
            ),
            created_at=datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        db.session.add(checklist_event)

        mention_text = "\n".join(
            "\n".join([
                answer.get("value", "") or "",
                answer.get("comment", "") or "",
            ])
            for answer in answers
        )

        try:
            db.session.commit()

        except IntegrityError:
            db.session.rollback()

            for filename in saved_filenames:
                delete_uploaded_file(filename)

            return return_form_errors(
                [
                    (
                        "安全チェックリストの更新に失敗しました。"
                        "もう一度お試しください。",
                        ""
                    )
                ],
                status_code=409
            )

        except SQLAlchemyError:
            db.session.rollback()

            for filename in saved_filenames:
                delete_uploaded_file(filename)

            return return_form_errors(
                [
                    (
                        "安全チェックリストの更新に失敗しました。"
                        "もう一度お試しください。",
                        ""
                    )
                ],
                status_code=500
            )

        approval_usernames = set(
            approvals[0].get("candidate_usernames") or []
        ) if approvals else set()

        notification_usernames = set(approval_usernames)

        if was_rejected:
            latest_rejection = ChecklistEvent.query.filter_by(
                company_code=company_code,
                result_type="safety",
                result_id=result_record.id,
                event_type="差し戻し"
            ).order_by(
                ChecklistEvent.id.desc()
            ).first()

            if latest_rejection and latest_rejection.actor_username:
                notification_usernames.add(
                    latest_rejection.actor_username
                )

        for target_username in sorted(notification_usernames):
            target_user = User.query.filter_by(
                company_code=company_code,
                username=target_username
            ).first()

            if not target_user:
                continue

            is_approval_recipient = (
                target_username in approval_usernames
            )

            if was_rejected:
                notification_title = (
                    "安全チェックリスト再申請の承認依頼"
                    if is_approval_recipient
                    else "安全チェックリスト修正・再申請のお知らせ"
                )
                notification_message = (
                    f"「{checklist_record.name}」が"
                    "修正・再申請されました。"
                    + (
                        "承認をお願いします。"
                        if is_approval_recipient
                        else "変更内容を確認してください。"
                    )
                )
            else:
                notification_title = "安全チェックリスト承認依頼"
                notification_message = (
                    f"「{checklist_record.name}」"
                    "の承認をお願いします。"
                )

            add_notification(
                (target_user.last_name or "")
                + (target_user.first_name or ""),
                notification_title,
                notification_message,
                f"/safety/checklist-results/{result_record.id}",
                company_code=company_code,
                target_username=target_user.username,
                workflow_context=(
                    build_notification_workflow_context(
                        result_record,
                        "safety",
                        "approval",
                        approval_index=0
                    )
                    if is_approval_recipient
                    else None
                )
            )

        if result_record.status == "点検完了":
            completion_notify_usernames = set(
                notify_usernames
            )

            if result_record.target_username:
                completion_notify_usernames.add(
                    result_record.target_username
                )

            if result_record.checked_by_username:
                completion_notify_usernames.add(
                    result_record.checked_by_username
                )

            for notify_username in completion_notify_usernames:
                notify_user = valid_users.get(
                    notify_username
                )

                if not notify_user:
                    continue

                add_notification(
                    (notify_user.last_name or "")
                    + (notify_user.first_name or ""),
                    "安全チェックリスト完了のお知らせ",
                    (
                        f"「{checklist_record.name}」の"
                        "チェックが完了しました。"
                    ),
                    f"/safety/checklist-results/{result_record.id}",
                    company_code=company_code,
                    target_username=notify_user.username
                )

        notify_mentions(
            mention_text,
            f"/safety/checklist-results/{result_record.id}"
        )

        return redirect(f"/safety/checklist-results/{result_record.id}")

    selected_notify_users = result.get(
        "notify_users",
        []
    )

    criteria_list = []

    for item in checklist["items"]:
        if item.get("item_type") != "check":
            continue

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
        selected_approval_users=[
            approval.get("candidate_usernames", [])
            for approval in result.get("approvals", [])
        ],
        offices=offices_for_current_company(),
        selected_notify_users=selected_notify_users
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

    files_to_delete = []

    for answer in safe_json_dict_list(
        result_record.answers_json
    ):
        files_to_delete.extend(
            answer.get("files", [])
        )

    company_code = result_record.company_code

    db.session.delete(result_record)
    db.session.commit()

    for filename in files_to_delete:
        filename = os.path.basename(
            str(filename or "")
        )

        if not filename:
            continue

        still_referenced = False

        patrol_records = PatrolResult.query.filter_by(
            company_code=company_code
        ).all()

        for patrol in patrol_records:
            patrol_files = safe_json_str_list(
                patrol.files_json
            )

            if filename in patrol_files:
                still_referenced = True
                break

        if still_referenced:
            continue

        if s3_client and S3_BUCKET_NAME:
            try:
                s3_client.delete_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=(
                        f"uploads/"
                        f"{company_code}/"
                        f"{filename}"
                    )
                )
            except ClientError:
                app.logger.warning(
                    "安全チェックリスト添付ファイルのS3削除に失敗しました。",
                    exc_info=True
                )
        else:
            safe_filename = secure_filename(
                filename
            )

            if not safe_filename:
                continue

            file_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                company_code,
                safe_filename
            )

            if os.path.exists(file_path):
                os.remove(file_path)

    return redirect(f"/safety/checklists/{checklist_id}")

@app.route("/vehicle/daily-inspections")
def vehicle_daily_inspection_entry():
    return redirect("/vehicle/checklists")

@app.route("/vehicle/checklists")
def vehicle_checklists():
    try:
        ensure_daily_inspection_checklist()
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("日常点検の標準様式の登録に失敗しました。")
        flash("日常点検の標準様式を登録できませんでした。", "error:")
        return render_template(
            "vehicle_checklists.html",
            checklists=[]
        ), 500

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
        return return_form_errors([
            (
                "表示年月が不正です。",
                None
            )
        ])

    if year_int < 2000 or year_int > 2100:
        return return_form_errors([
            (
                "表示年が不正です。",
                None
            )
        ])

    if month_int < 1 or month_int > 12:
        return return_form_errors([
            (
                "表示月が不正です。",
                None
            )
        ])

    year = str(year_int)
    month = str(month_int).zfill(2)

    if vehicle_record_id:
        valid_vehicle = Vehicle.query.filter_by(
            company_code=checklist_record.company_code,
            id=vehicle_record_id,
            deleted=False
        ).first()

        if not valid_vehicle:
            return return_form_errors([
                (
                    "対象車両が不正です。",
                    "vehicle_record_id"
                )
            ])
        
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

    input_days = list(display_days)

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

    for result_record in (query.all() if vehicle_record_id else []):
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

            if day_result:
                result_snapshot = (
                    day_result.get("checklist_snapshot") or {}
                )
                if result_snapshot:
                    day_checklist = result_snapshot

            if not day_checklist:
                continue

            if checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
                current_template = next(
                    (
                        item
                        for item in checklist.get("items", [])
                        if item.get("fixed_template_code")
                        == "daily_inspection_truck_trailer"
                    ),
                    {}
                )
                saved_template = next(
                    (
                        item
                        for item in day_checklist.get("items", [])
                        if item.get("fixed_template_code")
                        == "daily_inspection_truck_trailer"
                    ),
                    {}
                )
                current_version = current_template.get(
                    "fixed_template_version",
                    1
                )
                saved_version = saved_template.get(
                    "fixed_template_version",
                    current_version
                )

                if str(saved_version) == str(current_version):
                    day_checklist = checklist

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

    checklist_events = []

    if active_result and vehicle_record_id:
        checklist_event_records = (
            ChecklistEvent.query.filter_by(
                company_code=checklist_record.company_code,
                result_type="vehicle",
                result_id=active_result["id"]
            )
            .order_by(ChecklistEvent.id.asc())
            .all()
        )

        for event in checklist_event_records:
            checklist_events.append({
                "event_type": event.event_type,
                "actor_username": event.actor_username,
                "actor_name": event.actor_name,
                "created_at": event.created_at,
                "detail": safe_json_dict(event.detail_json),
            })

    vehicle_today = None
    if (
        vehicle_record_id
        and checklist.get("fixed_template_code")
        == "daily_inspection_truck_trailer"
    ):
        local_today = get_user_local_now(
            checklist_record.company_code,
            session.get("username")
        )
        vehicle_today = {
            "label": local_today.strftime("%Y/%m/%d"),
            "is_selected": (
                int(year) == local_today.year
                and int(month) == local_today.month
                and int(active_day) == local_today.day
            ),
            "url": url_for(
                "vehicle_checklist_results",
                index=checklist_record.id,
                vehicle_record_id=vehicle_record_id,
                year=str(local_today.year),
                month=local_today.strftime("%m"),
                active_day=local_today.strftime("%d")
            ),
        }

    other_vehicle_inspection_defects = []

    if checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
        other_vehicle_inspection_defects = [
            entry
            for entry in get_vehicle_open_inspection_defects(
                checklist_record.company_code,
                vehicle_record_id
            )
            if not active_result
            or entry["result_id"] != active_result["id"]
        ]

    vehicle_response_notify_names = []
    if active_result and checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
        response_judgment = active_result.get("operation_judgment", {})
        target_usernames = set(response_judgment.get("requested_usernames") or [])
        inspector_username = active_result.get("checked_by_username")

        if not target_usernames and inspector_username:
            inspector = User.query.filter_by(
                company_code=checklist_record.company_code,
                username=inspector_username
            ).first()
            if inspector and inspector.office:
                target_usernames.update(
                    user.username
                    for user in User.query.filter_by(
                        company_code=checklist_record.company_code,
                        office=inspector.office,
                        role="admin"
                    ).all()
                )

        if inspector_username:
            target_usernames.add(inspector_username)

        if target_usernames:
            notify_users = User.query.filter_by(
                company_code=checklist_record.company_code
            ).filter(User.username.in_(target_usernames)).all()
            vehicle_response_notify_names = [
                (user.last_name or "") + (user.first_name or "") or user.username
                for user in sorted(notify_users, key=lambda user: user.username)
            ]

    vehicle_judgment_names = []
    if active_result and checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
        assigned_usernames = set(
            active_result.get("operation_judgment", {}).get("requested_usernames") or []
        )
        if assigned_usernames:
            vehicle_judgment_names = [
                (user.last_name or "") + (user.first_name or "") or user.username
                for user in sorted(notify_users, key=lambda user: user.username)
                if user.username in assigned_usernames and user.role == "admin"
            ]

    vehicle_operation_managers = []
    if active_result and checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
        vehicle_operation_managers = [
            {
                "username": user.username,
                "name": (user.last_name or "") + (user.first_name or "") or user.username,
                "office": user.office or "",
            }
            for user in User.query.filter_by(
                company_code=checklist_record.company_code,
                role="admin"
            ).all()
        ]
        vehicle_operation_managers.sort(
            key=lambda user: (user["name"], user["username"])
        )

    return render_template(
        "vehicle_checklist_results.html",
        vehicle_operation_managers=vehicle_operation_managers,
        vehicle_judgment_names=vehicle_judgment_names,
        vehicle_response_notify_names=vehicle_response_notify_names,
        checklist=checklist,
        checklist_index=checklist_record.id,
        results=results,
        active_result=active_result,
        checklist_events=checklist_events,
        other_vehicle_inspection_defects=other_vehicle_inspection_defects,
        vehicle_today=vehicle_today,
        vehicle_operation_basis=(
            get_vehicle_operation_basis(
                checklist_record.company_code,
                vehicle_record_id
            )
            if checklist.get("fixed_template_code")
            == "daily_inspection_truck_trailer"
            else ""
        ),
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
        return return_form_errors([
            (
                "通知先設定を変更する権限がありません。",
                ""
            )
        ], status_code=403)    

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
        return return_form_errors([
            (
                "通知先ユーザー数が多すぎます。",
                "reminder_notify_user_search"
            )
        ])

    # =========================
    # チェックリスト検証
    # =========================

    checklist_record = Checklist.query.filter_by(
        id=checklist_index,
        company_code=company_code,
        active=True
    ).first()

    if not checklist_record:
        return return_form_errors([
            (
                "チェックリストが不正です。",
                ""
            )
        ], status_code=404)

    if checklist_record.target != "車両管理":
        return return_form_errors([
            (
                "チェックリスト種別が不正です。",
                ""
            )
        ])

    # =========================
    # 車両検証
    # =========================

    if not vehicle_record_id:
        return return_form_errors([
            (
                "車両を選択してください。",
                "vehicle_record_id"
            )
        ])

    vehicle = Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return return_form_errors([
            (
                "車両が不正です。",
                "vehicle_record_id"
            )
        ])

    # =========================
    # 通知先ユーザー検証
    # =========================

    valid_users = {
        user.username: user
        for user in User.query.filter_by(
            company_code=company_code
        ).all()
        if user.username
    }

    for username in notify_usernames:
        if username not in valid_users:
            return return_form_errors([
                (
                    "通知先ユーザーが不正です。",
                    "reminder_notify_user_search"
                )
            ])

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
    "/vehicle/checklist-results/<int:result_index>/defects/<int:defect_no>/repair",
    methods=["POST"]
)
@limiter.limit("20 per minute")
def save_vehicle_inspection_repair(result_index, defect_no):
    lock_error = lock_vehicle_inspection_updates(
        session.get("company_code"),
        result_index=result_index
    )
    if lock_error is not None:
        return lock_error
    company_code = session.get("company_code")
    current_user = User.query.filter_by(
        company_code=company_code,
        username=session.get("username")
    ).first()
    if not current_user or current_user.role not in {"admin", "user"}:
        return return_form_errors([("整備内容を登録する権限がありません。", "")], 403)

    result_record = VehicleChecklistResult.query.filter_by(
        id=result_index,
        company_code=company_code
    ).with_for_update().first()
    if not result_record:
        return return_form_errors([("対象の点検記録がありません。", "")], 404)

    snapshot = safe_json_dict(result_record.checklist_snapshot_json)
    if not any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in snapshot.get("items", [])
    ):
        return return_form_errors([("不具合対応の対象外の様式です。", "")], 400)

    previous_json = result_record.operation_judgment_json
    previous = safe_json_dict(previous_json)
    defects = [dict(item) for item in previous.get("defects", [])]
    defect = next(
        (item for item in defects if item.get("defect_no") == defect_no),
        None
    )
    if not defect:
        return return_form_errors([("対象の不具合がありません。", "")], 404)

    try:
        expected_version = int(request.form.get("judgment_version", ""))
        current_version = int(previous.get("version") or 0)
    except (TypeError, ValueError):
        return return_form_errors([("再読み込みして不具合の状態を確認してください。", "")], 409)

    if expected_version != current_version:
        return return_form_errors([("点検または不具合対応が更新されています。再読み込みしてください。", "")], 409)

    is_recheck = request.form.get("recheck_result") is not None

    if is_recheck:
        recheck_result = request.form.get("recheck_result", "").strip()
        if defect.get("status") != "再確認待ち":
            return return_form_errors([
                ("再確認待ちの不具合を選択してください。", "")
            ], 409)

        if recheck_result not in {"異常なし", "異常あり"}:
            return return_form_errors([
                ("再確認結果を選択してください。", f"recheck_result_{defect_no}")
            ])

        next_status = (
            "解消"
            if recheck_result == "異常なし"
            else "対応待ち"
        )
    else:
        next_status = request.form.get("repair_status", "").strip()
        if (
            defect.get("status") not in {"対応待ち", "整備中"}
            or next_status not in {"整備中", "再確認待ち"}
        ):
            return return_form_errors([
                ("現在の状態ではこの整備操作を行えません。", "")
            ], 409)

    note = request.form.get("repair_note", "").strip()
    if not note or len(note) > 5000:
        return return_form_errors([
            ("整備内容を1〜5000文字で入力してください。", f"repair_note_{defect_no}")
        ])

    local_now = get_user_local_now(company_code, current_user.username)
    try:
        performed_at = datetime.strptime(
            request.form.get("repair_performed_at", ""),
            "%Y-%m-%dT%H:%M"
        )
    except ValueError:
        return return_form_errors([
            ("整備実施日時を入力してください。", f"repair_performed_at_{defect_no}")
        ])

    if performed_at > local_now.replace(tzinfo=None):
        return return_form_errors([
            ("整備実施日時に未来の日時は指定できません。", f"repair_performed_at_{defect_no}")
        ])

    repair = {
        "status": next_status,
        "note": note,
        "performed_by": (current_user.last_name or "") + (current_user.first_name or ""),
        "performed_by_username": current_user.username,
        "performed_at": performed_at.strftime("%Y-%m-%d %H:%M"),
        "recorded_at": local_now.strftime("%Y-%m-%d %H:%M:%S"),
        "notification_created_at": local_now.astimezone(
            ZoneInfo("UTC")
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": str(local_now.tzinfo),
    }
    previous_defect = dict(defect)
    defect["status"] = next_status

    if is_recheck:
        try:
            previous_repair = defect.get("repair") or {}
            repair_completed_at = datetime.strptime(
                previous_repair.get("performed_at", ""),
                "%Y-%m-%d %H:%M"
            ).replace(
                tzinfo=ZoneInfo(
                    previous_repair.get("timezone") or "Asia/Tokyo"
                )
            )
        except (TypeError, ValueError, KeyError):
            return return_form_errors([
                ("整備実施日時を確認できません。整備記録を確認してください。", "")
            ], 409)

        if performed_at.replace(tzinfo=local_now.tzinfo) < repair_completed_at:
            return return_form_errors([
                (
                    "再確認日時は整備実施日時以降を指定してください。",
                    f"repair_performed_at_{defect_no}"
                )
            ])

        repair["result"] = recheck_result
        defect["recheck"] = repair
        defect["rechecked_answer"] = next(
            (
                dict(answer)
                for answer in safe_json_dict_list(result_record.answers_json)
                if str(answer.get("item_no", ""))
                == str(defect.get("item_no", ""))
            ),
            {}
        )
    else:
        defect["repair"] = repair

    judgment = {
        **previous,
        "defects": defects,
        "status": "未判定",
        "version": current_version + 1,
    }
    for key in (
        "reason", "judged_by", "judged_by_username",
        "judged_at", "authority_role", "authority_confirmed",
        "checks_confirmed", "checks_evidence"
    ):
        judgment.pop(key, None)

    if request.headers.get("X-DKSS-Validation-Only") == "1":
        return jsonify({"success": True})

    try:
        updated = VehicleChecklistResult.query.filter_by(
            id=result_record.id,
            company_code=company_code,
            operation_judgment_json=previous_json
        ).update(
            {"operation_judgment_json": json.dumps(judgment, ensure_ascii=False)},
            synchronize_session=False
        )
        if updated != 1:
            db.session.rollback()
            return return_form_errors([
                ("不具合対応が更新されています。再読み込みしてください。", "")
            ], 409)

        invalidate_other_vehicle_operation_judgments(result_record)

        db.session.add(ChecklistEvent(
            company_code=company_code,
            result_type="vehicle",
            result_id=result_record.id,
            event_type=next_status,
            actor_username=current_user.username,
            actor_name=repair["performed_by"],
            created_at=repair["recorded_at"],
            detail_json=json.dumps({
                "previous_defect": previous_defect,
                "defect": defect,
                "repair": {} if is_recheck else repair,
                "recheck": repair if is_recheck else {},
                "previous_judgment": previous,
            }, ensure_ascii=False)
        ))

        notification_targets = []
        if next_status == "再確認待ち" or is_recheck:
            target_usernames = set(previous.get("requested_usernames") or [])

            if not target_usernames:
                inspector = User.query.filter_by(
                    company_code=company_code,
                    username=result_record.checked_by_username
                ).first()

                if inspector and inspector.office:
                    target_usernames.update(
                        user.username
                        for user in User.query.filter_by(
                            company_code=company_code,
                            office=inspector.office,
                            role="admin"
                        ).all()
                    )

            if result_record.checked_by_username:
                target_usernames.add(result_record.checked_by_username)

            vehicle = Vehicle.query.filter_by(
                id=result_record.vehicle_record_id,
                company_code=company_code
            ).first()
            vehicle_name = (
                " ".join(value for value in [
                    vehicle.plate_area or "",
                    vehicle.plate_class or "",
                    vehicle.plate_kana or "",
                    vehicle.plate_number or ""
                ] if value)
                if vehicle else ""
            ) or f"車両ID：{result_record.vehicle_record_id}"

            item_name = (
                defect.get("reported_answer", {}).get("content") or ""
            )

            if not is_recheck:
                notification_action = "再確認待ち"
                next_action = (
                    "整備した箇所を再確認し、再確認結果を登録してください。"
                )
            elif next_status == "解消":
                notification_action = "再確認済み・異常なし"
                next_action = (
                    "この不具合の再確認は完了しました。"
                    "整備管理者は、ほかの未解消の不具合と点検結果を確認し、"
                    "運行可否を判断してください。"
                )
            else:
                notification_action = "再確認で異常あり"
                next_action = (
                    "異常が残っています。整備内容を確認し、"
                    "追加の整備を登録してください。"
                )

            notification_title = (
                f"{vehicle_name}：{notification_action}"
            )
            notification_message = (
                f"対象車両：{vehicle_name}\n"
                f"点検日：{result_record.year}/{result_record.month}/{result_record.day}\n"
                f"項目：No.{int(defect.get('item_no', 0)) + 1} {item_name}\n"
                f"対応状況：{next_status}\n"
                f"次にすること：{next_action}\n"
                f"実施者：{repair['performed_by']}\n"
                f"実施日時：{repair['performed_at']}\n"
                f"内容：{repair['note']}"
            )
            notification_link = url_for(
                "vehicle_checklist_results",
                index=result_record.checklist_id,
                vehicle_record_id=result_record.vehicle_record_id,
                year=result_record.year,
                month=result_record.month,
                active_day=result_record.day
            ) + (
                f"#vehicle-flow-defect-{result_record.id}-"
                f"{defect.get('defect_no')}"
            )

            for target_username in sorted(target_usernames):
                target_user = User.query.filter_by(
                    company_code=company_code,
                    username=target_username
                ).first()
                if not target_user:
                    continue

                notification = Notification(
                    company_code=company_code,
                    target_user=(target_user.last_name or "")
                    + (target_user.first_name or ""),
                    target_username=target_user.username,
                    title=notification_title,
                    message=notification_message,
                    link=notification_link,
                    files_json="[]",
                    read=False,
                    created_at=repair["notification_created_at"]
                )
                db.session.add(notification)
                notification_targets.append((target_user, notification))

        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("日常点検の整備内容の保存に失敗しました。")
        return return_form_errors([
            ("整備内容を保存できませんでした。もう一度お試しください。", "")
        ], 500)

    dispatch_vehicle_defect_notifications(result_record)

    for target_user, notification in notification_targets:
        try:
            dispatch_external_notification(
                target_user,
                notification.title,
                notification.message,
                notification.link,
                notification_id=notification.id
            )
        except Exception:
            app.logger.exception("不具合対応の外部通知に失敗しました。")

    from urllib.parse import parse_qsl, urlencode, urlunparse

    destination = url_for(
        "vehicle_checklist_results",
        index=result_record.checklist_id,
        vehicle_record_id=result_record.vehicle_record_id,
        year=result_record.year,
        month=result_record.month,
        active_day=result_record.day
    )
    target = "vehicle-flow-judgment"
    saved_result_id = result_record.id
    saved_defect_no = defect.get("defect_no")
    saved_item_no = int(defect.get("item_no", 0)) + 1
    saved_date = (
        f"{result_record.year}/"
        f"{str(result_record.month).zfill(2)}/"
        f"{str(result_record.day).zfill(2)}"
    )

    try:
        pending_defects = get_vehicle_open_inspection_defects(
            company_code,
            result_record.vehicle_record_id
        )
        next_entry = next(
            (
                entry for entry in pending_defects
                if entry.get("result_id") == saved_result_id
                and str(entry.get("defect", {}).get("defect_no"))
                == str(saved_defect_no)
            ),
            pending_defects[0] if pending_defects else None
        )
        if next_entry:
            destination = next_entry["link"]
            next_defect_no = next_entry.get("defect", {}).get("defect_no")
            target = (
                f"vehicle-flow-defect-{next_entry['result_id']}-{next_defect_no}"
                if next_defect_no is not None else "vehicle-flow-overview"
            )
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("保存後の不具合対応の移動先を取得できませんでした。")
        target = f"vehicle-flow-defect-{saved_result_id}-{saved_defect_no}"

    parts = urlparse(destination)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.update({
        "vehicle_saved": "recheck" if is_recheck else "repair",
        "vehicle_saved_item": str(saved_item_no),
        "vehicle_saved_date": saved_date,
    })
    redirect_url = urlunparse(parts._replace(
        query=urlencode(params),
        fragment=target
    ))
    if request.headers.get("X-DKSS-Final-Submit") == "1":
        return jsonify({"redirect_url": redirect_url})
    return redirect(redirect_url)


@app.route(
    "/vehicle/checklist-results/<int:result_index>/operation-judgment",
    methods=["POST"]
)
@limiter.limit("20 per minute")
def save_vehicle_operation_judgment(result_index):
    lock_error = lock_vehicle_inspection_updates(
        session.get("company_code"),
        result_index=result_index
    )
    if lock_error is not None:
        return lock_error
    result_record = (
        VehicleChecklistResult.query.filter_by(
            id=result_index,
            company_code=session.get("company_code")
        ).with_for_update().first()
    )
    if not result_record:
        return return_form_errors([("対象の点検記録がありません。", "")], 404)

    snapshot = safe_json_dict(result_record.checklist_snapshot_json)
    if not any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in snapshot.get("items", [])
    ):
        return return_form_errors([("運行判断の対象外の様式です。", "")], 400)

    if result_record.status not in {"承認待ち", "承認済み", "点検完了"}:
        return return_form_errors([("点検完了後に運行判断を記録してください。", "")], 409)

    vehicle = Vehicle.query.filter_by(
        id=result_record.vehicle_record_id,
        company_code=result_record.company_code,
        deleted=False
    ).first()
    if not vehicle:
        return return_form_errors([("対象車両を確認できません。", "")], 409)

    previous_json = result_record.operation_judgment_json
    previous = safe_json_dict(previous_json)
    current_user = User.query.filter_by(
        company_code=result_record.company_code,
        username=session.get("username")
    ).first()
    if request.form.get("action") == "assign_operation_manager":
        if not current_user or not (
            current_user.role == "admin"
            or (
                current_user.role == "user"
                and current_user.username == result_record.checked_by_username
            )
        ):
            return return_form_errors([("整備管理者・補助者の設定は、点検者または管理者が行ってください。", "")], 403)

        if previous.get("requested_usernames") or previous.get("status") not in {None, "", "未判定"}:
            return return_form_errors([("整備管理者・補助者または判断結果が既に登録されています。再読み込みしてください。", "")], 409)

        try:
            expected_version = int(request.form.get("judgment_version", ""))
            current_version = int(previous.get("version") or 0)
        except (TypeError, ValueError):
            return return_form_errors([("画面を再読み込みしてください。", "")], 409)

        if expected_version != current_version:
            return return_form_errors([("記録が更新されています。再読み込みしてください。", "")], 409)

        manager = User.query.filter_by(
            company_code=result_record.company_code,
            username=request.form.get("manager_username", "").strip(),
            role="admin"
        ).first()
        if not manager:
            return return_form_errors([("整備管理者・補助者を選択してください。", "manager_username")], 400)

        if request.headers.get("X-DKSS-Validation-Only") == "1":
            return jsonify({"success": True})

        judgment = dict(previous)
        judgment["requested_usernames"] = [manager.username]
        judgment["version"] = current_version + 1
        created_at = get_user_local_now(
            result_record.company_code, current_user.username
        ).strftime("%Y-%m-%d %H:%M:%S")
        manager_name = (
            (manager.last_name or "") + (manager.first_name or "")
            or manager.username
        )
        notification_link = url_for(
            "vehicle_checklist_results",
            index=result_record.checklist_id,
            vehicle_record_id=result_record.vehicle_record_id,
            year=result_record.year,
            month=result_record.month,
            active_day=result_record.day
        ) + "#vehicle-flow-judgment"
        notification_title = "運行判断の依頼"
        notification_message = (
            f"点検日：{result_record.year}/{result_record.month}/{result_record.day}\n"
            "整備管理者として運行判断を依頼されました。点検結果と不具合の対応状況を確認し、運行可否を登録してください。"
        )

        try:
            updated = VehicleChecklistResult.query.filter_by(
                id=result_record.id,
                company_code=result_record.company_code,
                operation_judgment_json=previous_json
            ).update({
                "operation_judgment_json": json.dumps(judgment, ensure_ascii=False)
            }, synchronize_session=False)

            if updated != 1:
                db.session.rollback()
                return return_form_errors([("記録が更新されています。再読み込みしてください。", "")], 409)

            db.session.add(ChecklistEvent(
                company_code=result_record.company_code,
                result_type="vehicle",
                result_id=result_record.id,
                event_type="運行管理者設定",
                actor_username=current_user.username,
                actor_name=(
                    (current_user.last_name or "") + (current_user.first_name or "")
                    or current_user.username
                ),
                created_at=created_at,
                detail_json=json.dumps({"運行管理者": manager_name}, ensure_ascii=False)
            ))
            notification = Notification(
                company_code=result_record.company_code,
                target_user=manager_name,
                target_username=manager.username,
                title=notification_title,
                message=notification_message,
                link=notification_link,
                files_json="[]",
                workflow_context_json=json.dumps(
                    build_notification_workflow_context(
                        result_record,
                        "vehicle",
                        "operation_judgment"
                    ),
                    ensure_ascii=False
                ),
                read=False,
                created_at=datetime.now(ZoneInfo("UTC")).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            )
            db.session.add(notification)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("運行管理者の設定に失敗しました。")
            return return_form_errors([("整備管理者・補助者を設定できませんでした。", "")], 500)

        try:
            dispatch_external_notification(
                manager,
                notification.title,
                notification.message,
                notification.link,
                notification_id=notification.id
            )
        except Exception:
            app.logger.exception("運行管理者設定の外部通知に失敗しました。")

        return redirect(notification_link)

    if (
        not current_user
        or current_user.role != "admin"
        or current_user.username not in previous.get("requested_usernames", [])
    ):
        return return_form_errors([("選択された運行判断の担当者が操作してください。", "")], 403)

    decision = request.form.get("decision", "").strip()
    reason = request.form.get("reason", "").strip()
    authority_role = request.form.get("authority_role", "").strip()

    if decision not in {"運行可", "運行不可", "判定保留"}:
        return return_form_errors([
            ("運行可・運行不可・判定保留を選択してください。", "decision")
        ])
    if len(reason) > 5000:
        return return_form_errors([("補足・判断理由は5000文字以内で入力してください。", "reason")])
    if decision in {"運行不可", "判定保留"} and not reason:
        return return_form_errors([("運行不可・判断保留の場合は理由を入力してください。", "reason")])
    if (
        authority_role not in {"整備管理者", "補助者"}
        or request.form.get("authority_confirmed") != "1"
    ):
        return return_form_errors([("対象車両の運行判断を行う権限があることを確認してください。", "authority_confirmed")], 403)

    try:
        expected_version = int(request.form.get("judgment_version", ""))
        current_version = int(previous.get("version", 0))
        expected_answers = json.loads(request.form.get("expected_answers", ""))
        expected_snapshot = json.loads(request.form.get("expected_snapshot", ""))
    except (TypeError, ValueError):
        return return_form_errors([("画面を再読み込みして、点検内容を確認してください。", "")], 409)

    if (
        expected_version != current_version
        or expected_answers != safe_json_dict_list(result_record.answers_json)
        or expected_snapshot != snapshot
    ):
        return return_form_errors([("点検内容または運行判断が更新されています。再読み込みして確認してください。", "")], 409)

    approval_items = [
        item for item in snapshot.get("items", [])
        if item.get("item_type") == "approval"
        or (
            item.get("item_type") == "operation_judgment"
            and item.get("item_code") == "footer_30"
        )
    ]
    previous_approvals_json = result_record.approvals_json
    approvals = safe_json_dict_list(previous_approvals_json)
    if len(approval_items) != 1 or len(approvals) > 1:
        return return_form_errors([("標準点検表の確認欄を確認してください。", "")], 409)
    if not approvals:
        approvals = [{
            "label": approval_items[0].get("approval_label", "整備管理者（又は補助者）"),
            "allow_general": False,
            "candidate_usernames": list(previous.get("requested_usernames", [])),
            "approved_by": "",
            "approved_by_username": "",
            "approved_date": "",
        }]

    checks_evidence = ""

    if decision == "運行可":
        if request.form.get("checks_confirmed") != "1":
            return return_form_errors([
                ("必要な点検・確認の実施を確認してください。", "checks_confirmed")
            ])

        if request.form.get("vehicle_operation_basis", "") != get_vehicle_operation_basis(
            result_record.company_code,
            result_record.vehicle_record_id
        ):
            return return_form_errors([
                ("この車両の点検・不具合対応が更新されています。再読み込みして確認してください。", "")
            ], 409)

        answers_by_no = {
            str(answer.get("item_no", "")): answer
            for answer in safe_json_dict_list(result_record.answers_json)
        }
        check_items = [
            item
            for item in snapshot.get("items", [])
            if item.get("item_type") == "check"
        ]

        for item_no, item in enumerate(check_items):
            if item.get("answer_required") and not str(
                answers_by_no.get(str(item_no), {}).get("value") or ""
            ).strip():
                return return_form_errors([
                    ("必須の点検項目に未回答があります。確認してから判断してください。", "decision")
                ])

    operation_notify_usernames = []
    operation_notify_targets = []

    if decision == "運行不可":
        submitted_usernames = [
            username.strip()
            for username in request.form.getlist(
                "approval_notify_users_operation"
            )
            if username.strip()
        ]

        if len(submitted_usernames) > 500:
            return return_form_errors([
                (
                    "運行管理者の通知先は500人以内で選択してください。",
                    "operation_notify_users"
                )
            ], 400)

        operation_notify_usernames = list(
            dict.fromkeys(submitted_usernames)
        )

        if operation_notify_usernames:
            operation_notify_targets = User.query.filter(
                User.company_code == result_record.company_code,
                User.role == "admin",
                User.username.in_(operation_notify_usernames)
            ).all()

            valid_usernames = {
                user.username
                for user in operation_notify_targets
            }

            if any(
                username not in valid_usernames
                for username in operation_notify_usernames
            ):
                return return_form_errors([
                    (
                        "通知先は同じ会社の管理者ユーザーから選択してください。",
                        "operation_notify_users"
                    )
                ], 400)

    if request.headers.get("X-DKSS-Validation-Only") == "1":
        return jsonify({"success": True})

    judged_at = get_user_local_now(
        result_record.company_code,
        current_user.username
    ).strftime("%Y-%m-%d %H:%M:%S")
    judgment = {
        **previous,
        "status": decision,
        "reason": reason,
        "judged_by": (current_user.last_name or "") + (current_user.first_name or ""),
        "judged_by_username": current_user.username,
        "judged_at": judged_at,
        "authority_role": authority_role,
        "authority_confirmed": True,
        "checks_confirmed": decision == "運行可",
        "checks_evidence": checks_evidence,
        "operation_notify_usernames": operation_notify_usernames,
        "version": current_version + 1
    }

    approval = approvals[0]
    approval_added = not (
        approval.get("approved_by") or approval.get("approved_by_username")
    )
    if approval_added:
        approval["approved_by"] = judgment["judged_by"]
        approval["approved_by_username"] = current_user.username
        approval["approved_date"] = judged_at[:16]

    try:
        updated = VehicleChecklistResult.query.filter_by(
            id=result_record.id,
            company_code=result_record.company_code,
            operation_judgment_json=previous_json,
            approvals_json=previous_approvals_json,
            answers_json=result_record.answers_json,
            checklist_snapshot_json=result_record.checklist_snapshot_json,
            status=result_record.status
        ).update(
            {
                "operation_judgment_json": json.dumps(judgment, ensure_ascii=False),
                "approvals_json": json.dumps(approvals, ensure_ascii=False),
                "status": "承認済み",
                "approved_by": approval.get("approved_by", ""),
                "approved_by_username": approval.get("approved_by_username", ""),
                "approved_date": approval.get("approved_date", ""),
                "reject_reason": "",
            },
            synchronize_session=False
        )
        if updated != 1:
            db.session.rollback()
            return return_form_errors([("点検記録が更新されています。再読み込みして確認してください。", "")], 409)

        judgment_event = ChecklistEvent(
            company_code=result_record.company_code,
            result_type="vehicle",
            result_id=result_record.id,
            event_type="運行判断",
            actor_username=current_user.username,
            actor_name=judgment["judged_by"],
            detail_json=json.dumps(
                {"previous_judgment": previous, "judgment": judgment},
                ensure_ascii=False
            ),
            created_at=judged_at
        )
        db.session.add(judgment_event)
        db.session.flush()

        notification_target = None
        notification_title = "車両の運行判断：" + decision
        notification_message = (
            f"点検日：{result_record.year}-{result_record.month}-{result_record.day}\n"
            f"判断：{decision}\n理由：{reason}"
        )
        notification_link = url_for(
            "vehicle_checklist_results",
            index=result_record.checklist_id,
            vehicle_record_id=result_record.vehicle_record_id,
            year=result_record.year,
            month=result_record.month,
            active_day=result_record.day
        ) + "#vehicle-flow-judgment"

        if result_record.checked_by_username:
            notification_target = User.query.filter_by(
                company_code=result_record.company_code,
                username=result_record.checked_by_username
            ).first()

        if notification_target:
            notification = Notification(
                company_code=result_record.company_code,
                target_user=(notification_target.last_name or "")
                + (notification_target.first_name or ""),
                target_username=notification_target.username,
                title=notification_title,
                message=notification_message,
                link=notification_link,
                files_json="[]",
                read=False,
                created_at=datetime.now(ZoneInfo("UTC")).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                workflow_context_json=json.dumps({
                    "result_type": "vehicle",
                    "result_id": result_record.id,
                    "event_id": judgment_event.id,
                    "action": "operation_result",
                }, ensure_ascii=False)
            )
            db.session.add(notification)
        operation_notifications = []

        for target in operation_notify_targets:
            if (
                notification_target
                and target.username == notification_target.username
            ):
                continue

            operation_notification = Notification(
                company_code=result_record.company_code,
                target_user=(
                    (target.last_name or "") + (target.first_name or "")
                    or target.username
                ),
                target_username=target.username,
                title=notification_title,
                message=notification_message,
                link=notification_link,
                files_json="[]",
                read=False,
                created_at=datetime.now(ZoneInfo("UTC")).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                workflow_context_json=json.dumps({
                    "result_type": "vehicle",
                    "result_id": result_record.id,
                    "event_id": judgment_event.id,
                    "action": "operation_result",
                }, ensure_ascii=False)
            )
            db.session.add(operation_notification)
            operation_notifications.append(
                (target, operation_notification)
            )

        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("運行判断の保存に失敗しました。")
        return return_form_errors([("運行判断を保存できませんでした。もう一度お試しください。", "")], 500)

    if notification_target:
        try:
            dispatch_external_notification(
                notification_target,
                notification.title,
                notification.message,
                notification.link,
                notification_id=notification.id
            )
        except Exception:
            app.logger.exception("運行判断の外部通知に失敗しました。")

    for target, operation_notification in operation_notifications:
        try:
            dispatch_external_notification(
                target,
                operation_notification.title,
                operation_notification.message,
                operation_notification.link,
                notification_id=operation_notification.id
            )
        except Exception:
            app.logger.exception(
                "運行不可の追加通知の外部配信に失敗しました。"
            )

    redirect_url = url_for(
        "vehicle_checklist_results",
        index=result_record.checklist_id,
        vehicle_record_id=result_record.vehicle_record_id,
        year=result_record.year,
        month=result_record.month,
        active_day=result_record.day
    ) + "#vehicle-flow-judgment"
    if request.headers.get("X-DKSS-Final-Submit") == "1":
        return jsonify({"redirect_url": redirect_url})
    return redirect(redirect_url)

@app.route(
    "/vehicle/checklist-results/<int:result_index>/approve/<int:approval_index>",
    methods=["POST"]
)
@limiter.limit("20 per minute")
def approve_vehicle_checklist_result(result_index, approval_index):
    lock_error = lock_vehicle_inspection_updates(
        session.get("company_code"),
        result_index=result_index
    )
    if lock_error is not None:
        return lock_error
    result_record = (
        VehicleChecklistResult.query
        .filter_by(
            id=result_index,
            company_code=session.get("company_code")
        )
        .with_for_update()
        .first()
    )

    if not result_record:
        return redirect("/vehicle/checklists")

    if result_record.status != "承認待ち":
        return redirect("/vehicle/checklists")

    approvals = safe_json_dict_list(
        result_record.approvals_json
    )
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
                "candidate_usernames": [],
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

    if approval_index < 0 or approval_index >= len(approvals):
        return redirect("/vehicle/checklists")

    current_approval_index = next(
        (
            index
            for index, item in enumerate(approvals)
            if not (
                item.get("approved_by")
                or item.get("approved_by_username")
            )
        ),
        None
    )

    if (
        current_approval_index is None
        or approval_index != current_approval_index
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

    approval_snapshot = safe_json_dict(result_record.checklist_snapshot_json)
    if any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in approval_snapshot.get("items", [])
    ):
        return return_form_errors([
            ("標準の日常点検表は、運行判断の欄から確認・判断を保存してください。", "")
        ], 409)

    result = vehicle_checklist_result_to_dict(result_record)

    approval_user = User.query.filter_by(
        company_code=result_record.company_code,
        username=session.get("username")
    ).first()

    if (
        not approval_user

        or not (
            approval_user.role == "admin"
            or (
                approval.get("allow_general", False)
                and approval_user.role == "user"
            )
        )
    ):
        return redirect("/vehicle/checklists")

    approval["approved_by"] = session.get("name")
    approval["approved_by_username"] = session.get("username")    
    approval["approved_date"] = get_user_local_now(
        result_record.company_code,
        session.get("username")
    ).strftime("%Y-%m-%d %H:%M")

    result_record.approvals_json = json.dumps(
        approvals,
        ensure_ascii=False
    )

    result_record.reject_reason = ""

    all_approved = all(
        (
            item.get("approved_by")
            or item.get("approved_by_username")
        )
        for item in approvals
    )

    if approvals and all_approved:
        result_record.status = "承認済み"
        result_record.approved_by = session.get("name")
        result_record.approved_by_username = session.get("username")
        result_record.approved_date = get_user_local_now(
            result_record.company_code,
            session.get("username")
        ).strftime("%Y-%m-%d %H:%M")
    else:
        result_record.status = "承認待ち"
        result_record.approved_by = ""
        result_record.approved_by_username = ""
        result_record.approved_date = ""

    checklist_event = ChecklistEvent(
        company_code=result_record.company_code,
        result_type="vehicle",
        result_id=result_record.id,
        event_type="承認",
        actor_username=session.get("username"),
        actor_name=session.get("name"),
        detail_json=json.dumps(
            {
                "approval_index": approval_index,
                "approval": dict(approval),
                "all_approved": all_approved,
            },
            ensure_ascii=False
        ),
        created_at=datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    db.session.add(checklist_event)
    db.session.commit()

    vehicle_record = Vehicle.query.filter_by(
        company_code=result_record.company_code,
        id=result_record.vehicle_record_id,
        deleted=False
    ).first()

    result_checklist = {}

    if result_record.checklist_snapshot_json:
        result_checklist = safe_json_dict(
            result_record.checklist_snapshot_json
        )

    if not result_checklist:
        checklist_record = Checklist.query.filter_by(
            id=result_record.checklist_id,
            company_code=result_record.company_code
        ).first()

        if checklist_record:
            result_checklist = checklist_to_dict(
                checklist_record
            )

    if result_checklist.get("frequency_unit") == "year":
        active_value = result_record.year

    elif result_checklist.get("display_type") == "month":
        active_value = result_record.day

    else:
        active_value = result_record.month

    notification_link = (
        f"/vehicle/checklists/{result_record.checklist_id}"
        f"?vehicle_record_id={result_record.vehicle_record_id}"
        f"&year={result_record.year}"
        f"&month={result_record.month}"
        f"&active_day={active_value}"
    )

    if result_record.status != "承認済み":
        next_approval_index, next_approval = next(
            (
                (index, item)
                for index, item in enumerate(
                    approvals[approval_index + 1:],
                    start=approval_index + 1
                )
                if not (
                    item.get("approved_by")
                    or item.get("approved_by_username")
                )
            ),
            (None, None)
        )

        if next_approval:

            for target_username in next_approval.get(
                "candidate_usernames",
                []
            ):
                target_user = User.query.filter_by(
                    company_code=result_record.company_code,
                    username=target_username
                ).first()

                if not target_user:
                    continue

                add_notification(
                    (target_user.last_name or "")
                    + (target_user.first_name or ""),
                    "車両チェックリスト承認依頼",
                    "次の承認をお願いします。",
                    notification_link,
                    company_code=result_record.company_code,
                    target_username=target_user.username,
                    workflow_context=build_notification_workflow_context(
                        result_record,
                        "vehicle",
                        "approval",
                        approval_index=next_approval_index
                    )
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
                (target_user.last_name or "") + (target_user.first_name or ""),
                "車両チェックリストが承認されました",
                (
                    f"車両 {' '.join(value for value in [vehicle_record.plate_area or '', vehicle_record.plate_class or '', vehicle_record.plate_kana or '', vehicle_record.plate_number or ''] if value) if vehicle_record else '-'} の"
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

@app.route(
    "/vehicle/checklist-results/<int:result_index>/reject",
    methods=["POST"]
)
@limiter.limit("20 per minute")
def reject_vehicle_checklist_result(result_index):
    lock_error = lock_vehicle_inspection_updates(
        session.get("company_code"),
        result_index=result_index
    )
    if lock_error is not None:
        return lock_error
    result_record = (
        VehicleChecklistResult.query
        .filter_by(
            id=result_index,
            company_code=session.get("company_code")
        )
        .with_for_update()
        .first()
    )

    if not result_record:
        return redirect("/vehicle/checklists")

    if result_record.status != "承認待ち":
        return redirect("/vehicle/checklists")

    approvals = safe_json_dict_list(
        result_record.approvals_json
    )

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
                "candidate_usernames": [],
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

    current_approval = next(
        (
            approval
            for approval in approvals
            if not (
                approval.get("approved_by")
                or approval.get("approved_by_username")
            )
        ),
        None
    )

    if not current_approval:
        return redirect("/vehicle/checklists")

    if "allow_general" not in current_approval:
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

        current_approval_index = approvals.index(
            current_approval
        )

        if current_approval_index < len(approval_items):
            current_approval["allow_general"] = (
                approval_items[
                    current_approval_index
                ].get(
                    "approval_allow_general",
                    False
                )
            )

    approval_user = User.query.filter_by(
        company_code=result_record.company_code,
        username=session.get("username")
    ).first()

    if (
        not approval_user
        or not (
            approval_user.role == "admin"
            or (
                current_approval.get(
                    "allow_general",
                    False
                )
                and approval_user.role == "user"
            )
        )
    ):
        return redirect("/vehicle/checklists")

    reject_reason = request.form.get(
        "reject_reason",
        ""
    ).strip()

    form_errors = []

    if not reject_reason:
        form_errors.append(
            (
                "差し戻し理由を入力してください。",
                "vehicleRejectReason"
            )
        )

    elif len(reject_reason) > 5000:
        form_errors.append(
            (
                "差し戻し理由は5000文字以内で入力してください。",
                "vehicleRejectReason"
            )
        )

    if form_errors:
        return return_form_errors(form_errors)

    previous_approvals = [
        dict(approval)
        for approval in approvals
    ]

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

    checklist_event = ChecklistEvent(
        company_code=result_record.company_code,
        result_type="vehicle",
        result_id=result_record.id,
        event_type="差し戻し",
        actor_username=session.get("username"),
        actor_name=session.get("name"),
        detail_json=json.dumps(
            {
                "reject_reason": reject_reason,
                "approval_label": (
                    current_approval.get("label", "")
                    if current_approval
                    else ""
                ),
                "previous_approvals": previous_approvals,
            },
            ensure_ascii=False
        ),
        created_at=datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    db.session.add(checklist_event)
    db.session.commit()

    result_checklist = safe_json_dict(
        result_record.checklist_snapshot_json
    )

    if not result_checklist:
        checklist_record = Checklist.query.filter_by(
            id=result_record.checklist_id,
            company_code=result_record.company_code
        ).first()

        if checklist_record:
            result_checklist = checklist_to_dict(
                checklist_record
            )

    if result_checklist.get("frequency_unit") == "year":
        active_value = result_record.year
    elif result_checklist.get("display_type") == "month":
        active_value = result_record.day
    else:
        active_value = result_record.month

    if result_record.checked_by_username:
        target_user = User.query.filter_by(
            company_code=result_record.company_code,
            username=result_record.checked_by_username
        ).first()

        if target_user:
            add_notification(
                (target_user.last_name or "")
                + (target_user.first_name or ""),
                "車両チェックリストが差し戻されました",
                (
                    "差し戻し理由："
                    f"{reject_reason}"
                ),
                (
                    f"/vehicle/checklists/"
                    f"{result_record.checklist_id}"
                    f"?vehicle_record_id="
                    f"{result_record.vehicle_record_id}"
                    f"&year={result_record.year}"
                    f"&month={result_record.month}"
                    f"&active_day={active_value}"
                ),
                company_code=result_record.company_code,
                target_username=target_user.username,
                workflow_context=build_notification_workflow_context(
                    result_record,
                    "vehicle",
                    "correction"
                )
            )

    if request.headers.get("X-DKSS-Validation-Only") == "1":
        return jsonify({
            "success": True,
            "status": "差し戻し"
        })

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

            if day_result:
                result_snapshot = (
                    day_result.get("checklist_snapshot") or {}
                )
                if result_snapshot:
                    day_checklist = result_snapshot

            if current_checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
                current_template = next(
                    (
                        item
                        for item in current_checklist.get("items", [])
                        if item.get("fixed_template_code")
                        == "daily_inspection_truck_trailer"
                    ),
                    {}
                )
                saved_template = next(
                    (
                        item
                        for item in day_checklist.get("items", [])
                        if item.get("fixed_template_code")
                        == "daily_inspection_truck_trailer"
                    ),
                    {}
                )
                current_version = current_template.get(
                    "fixed_template_version",
                    1
                )
                saved_version = saved_template.get(
                    "fixed_template_version",
                    current_version
                )

                if str(saved_version) == str(current_version):
                    day_checklist = current_checklist

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
        and checklist.get("fixed_template_code") != "daily_inspection_truck_trailer"
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
            vehicle_info["number"]
            or "ナンバー未登録"
        )

        sheet.merge_cells(
            start_row=4,
            start_column=1,
            end_row=4,
            end_column=end_column
        )

        sheet["A4"] = f"登録番号　{vehicle_number}"
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

        item_no = -1
        approval_row_positions = []

        for item in excel_checklist.get("items", []):

            if item.get("item_type") in {
                "inspector", "approval", "operation_judgment"
            }:
                approval_row_positions.append(current_row)
                current_row += 1
                continue

            if item.get("item_type") != "check":
                continue

            item_no += 1

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

        # 押印欄（実施者・承認項目をマスタの並び順で出力）
        approval_items = [
            item
            for item in excel_checklist.get("items", [])
            if item.get("item_type") in {
                "inspector", "approval", "operation_judgment"
            }
        ]

        for approval_index, approval_item in enumerate(approval_items):
            approval_row = approval_row_positions[approval_index]

            sheet.row_dimensions[approval_row].height = 28

            sheet.cell(
                row=approval_row,
                column=1,
                value=(
                    (approval_item.get("content") or "実施者")
                    if approval_item.get("item_type") == "inspector"
                    else (
                        approval_item.get("content") or "整備管理者"
                        if approval_item.get("item_type") == "operation_judgment"
                        else approval_item.get("approval_label", "") or "承認"
                    )
                )
            )

            for period_result in excel_period_results:
                if approval_item.get("item_type") == "operation_judgment":
                    continue

                if approval_item.get("item_type") == "inspector":
                    approval = {
                        "approved_by": period_result.get("checked_by", ""),
                        "approved_by_username": period_result.get(
                            "checked_by_username",
                            ""
                        ),
                    }
                else:
                    approvals = period_result.get("approvals", [])

                    approval_position = sum(
                        1
                        for previous_item in approval_items[:approval_index]
                        if previous_item.get("item_type") == "approval"
                    )

                    if approval_position >= len(approvals):
                        continue

                    approval = approvals[approval_position]

                if not (
                    approval.get("approved_by")
                    or approval.get("approved_by_username")
                ):
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

                approval_user = User.query.filter_by(
                    company_code=result_record.company_code,
                    username=approval.get("approved_by_username")
                ).first()

                sheet.cell(
                    row=approval_row,
                    column=column,
                    value=(
                        approval_user.last_name
                        if approval_user
                        else (
                            approval.get("approved_by")
                            or approval.get("approved_by_username")
                            or ""
                        )
                    )
                ).alignment = Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True
                )

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

def lock_vehicle_inspection_updates(
    company_code,
    vehicle_record_id=None,
    checklist=None,
    result_index=None
):
    if result_index is not None:
        record = VehicleChecklistResult.query.filter_by(
            id=result_index,
            company_code=company_code
        ).first()
        if not record:
            return None

        vehicle_record_id = record.vehicle_record_id
        checklist = safe_json_dict(record.checklist_snapshot_json)

    if not any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in (checklist or {}).get("items", [])
    ):
        return None

    try:
        locked = Vehicle.query.filter_by(
            company_code=company_code,
            id=vehicle_record_id,
            deleted=False
        ).update(
            {Vehicle.id: Vehicle.id},
            synchronize_session=False
        )

        if locked != 1:
            db.session.rollback()
            return return_form_errors([
                ("対象車両を確認できません。", "")
            ], 404)

        db.session.expire_all()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("日常点検の車両更新ロックに失敗しました。")
        return return_form_errors([
            ("この車両の保存処理が競合しました。少し待ってからもう一度操作してください。", "")
        ], 409)

    return None


def get_vehicle_operation_basis(company_code, vehicle_record_id):
    if not company_code or not vehicle_record_id:
        return ""

    from hashlib import sha256

    basis = []
    records = VehicleChecklistResult.query.filter_by(
        company_code=company_code,
        vehicle_record_id=vehicle_record_id
    ).order_by(VehicleChecklistResult.id.asc()).all()

    for record in records:
        snapshot = safe_json_dict(record.checklist_snapshot_json)
        if any(
            item.get("fixed_template_code") == "daily_inspection_truck_trailer"
            for item in snapshot.get("items", [])
        ):
            basis.append([
                record.id,
                record.answers_json,
                record.checklist_snapshot_json,
                record.operation_judgment_json,
                record.status,
            ])

    return sha256(
        json.dumps(basis, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def get_vehicle_open_inspection_defects(company_code, vehicle_record_id):
    if not company_code or not vehicle_record_id:
        return []

    records = VehicleChecklistResult.query.filter_by(
        company_code=company_code,
        vehicle_record_id=vehicle_record_id
    ).order_by(VehicleChecklistResult.id.asc()).all()

    open_defects = []

    for record in records:
        snapshot = safe_json_dict(record.checklist_snapshot_json)
        if not any(
            item.get("fixed_template_code") == "daily_inspection_truck_trailer"
            for item in snapshot.get("items", [])
        ):
            continue

        judgment = safe_json_dict(record.operation_judgment_json)
        defects = list(judgment.get("defects") or [])

        for answer in safe_json_dict_list(record.answers_json):
            if str(answer.get("value") or "").strip() != "×":
                continue

            item_no = str(answer.get("item_no", ""))
            accounted_for = any(
                str(defect.get("item_no", "")) == item_no
                and (
                    defect.get("status") != "解消"
                    or all(
                        defect.get("rechecked_answer", {}).get(field)
                        == answer.get(field)
                        for field in ("value", "comment", "files")
                    )
                )
                for defect in defects
            )
            if not accounted_for:
                defects.append({
                    "item_no": item_no,
                    "status": "対応待ち",
                    "reported_answer": dict(answer),
                })

        for defect in defects:
            if defect.get("status") == "解消":
                continue

            open_defects.append({
                "result_id": record.id,
                "judgment_version": judgment.get("version", 0),
                "inspection_date": (
                    f"{record.year}/"
                    f"{str(record.month).zfill(2)}/"
                    f"{str(record.day).zfill(2)}"
                ),
                "defect": dict(defect),
                "link": url_for(
                    "vehicle_checklist_results",
                    index=record.checklist_id,
                    vehicle_record_id=record.vehicle_record_id,
                    year=record.year,
                    month=record.month,
                    active_day=record.day
                ),
            })

    return open_defects


def get_vehicle_recent_inspection_repairs(company_code, vehicle_record_id):
    events = (
        ChecklistEvent.query
        .join(
            VehicleChecklistResult,
            ChecklistEvent.result_id == VehicleChecklistResult.id
        )
        .filter(
            ChecklistEvent.company_code == company_code,
            ChecklistEvent.result_type == "vehicle",
            ChecklistEvent.event_type.in_(["整備中", "再確認待ち"]),
            VehicleChecklistResult.company_code == company_code,
            VehicleChecklistResult.vehicle_record_id == vehicle_record_id
        )
        .order_by(
            ChecklistEvent.created_at.desc(),
            ChecklistEvent.id.desc()
        )
        .limit(5)
        .all()
    )

    repairs = []

    for event in events:
        detail = safe_json_dict(event.detail_json)
        repair = detail.get("repair") or {}

        if not repair:
            continue

        defect = detail.get("defect") or {}
        answer = defect.get("reported_answer") or {}

        repairs.append({
            "item_name": answer.get("content") or "",
            "note": repair.get("note") or "",
            "performed_by": repair.get("performed_by") or "",
            "performed_at": repair.get("performed_at") or "",
            "recorded_at": event.created_at,
            "status": repair.get("status") or "",
        })

    return repairs


def invalidate_other_vehicle_operation_judgments(result_record):
    if not result_record.vehicle_record_id:
        return

    local_now = get_user_local_now(
        result_record.company_code,
        session.get("username")
    )
    today = (local_now.year, local_now.month, local_now.day)
    reason = "同じ車両の点検・不具合対応が更新されたため、再判定が必要です。"

    with db.session.no_autoflush:
        records = VehicleChecklistResult.query.filter_by(
            company_code=result_record.company_code,
            vehicle_record_id=result_record.vehicle_record_id
        ).all()

    for record in records:
        if record.id == result_record.id:
            continue
        try:
            inspection_date = (
                int(record.year), int(record.month), int(record.day)
            )
        except (TypeError, ValueError):
            continue
        if inspection_date < today:
            continue

        checklist = safe_json_dict(record.checklist_snapshot_json)
        if not any(
            item.get("fixed_template_code") == "daily_inspection_truck_trailer"
            for item in checklist.get("items", [])
        ):
            continue

        previous = safe_json_dict(record.operation_judgment_json)
        if previous.get("status") != "運行可":
            continue

        judgment = {
            **previous,
            "status": "未判定",
            "version": int(previous.get("version") or 0) + 1,
            "reason": reason,
        }
        for key in (
            "judged_by", "judged_by_username", "judged_at",
            "authority_role", "authority_confirmed",
            "checks_confirmed", "checks_evidence"
        ):
            judgment.pop(key, None)

        record.operation_judgment_json = json.dumps(
            judgment, ensure_ascii=False
        )
        db.session.add(ChecklistEvent(
            company_code=record.company_code,
            result_type="vehicle",
            result_id=record.id,
            event_type="運行判断",
            actor_username=session.get("username"),
            actor_name=session.get("name"),
            created_at=local_now.strftime("%Y-%m-%d %H:%M:%S"),
            detail_json=json.dumps({
                "previous_judgment": previous,
                "judgment": judgment,
                "changed_result_id": result_record.id,
            }, ensure_ascii=False)
        ))

        vehicle = Vehicle.query.filter_by(
            company_code=record.company_code,
            id=record.vehicle_record_id
        ).first()
        vehicle_name = (
            " ".join(
                value for value in (
                    vehicle.plate_area or "",
                    vehicle.plate_class or "",
                    vehicle.plate_kana or "",
                    vehicle.plate_number or "",
                ) if value
            ) if vehicle else ""
        ) or f"車両ID：{record.vehicle_record_id}"
        notification_link = url_for(
            "vehicle_checklist_results",
            index=record.checklist_id,
            vehicle_record_id=record.vehicle_record_id,
            year=record.year,
            month=record.month,
            active_day=record.day
        ) + "#vehicle-flow-judgment"

        for username in sorted(set(previous.get("requested_usernames") or [])):
            target_user = User.query.filter_by(
                company_code=record.company_code,
                username=username,
                role="admin"
            ).first()
            if not target_user:
                continue

            notification = Notification(
                company_code=record.company_code,
                target_user=(target_user.last_name or "") + (target_user.first_name or ""),
                target_username=target_user.username,
                title="運行可否の再判定依頼：" + vehicle_name,
                message=(
                    f"対象車両：{vehicle_name}\n"
                    f"点検日：{record.year}/{record.month}/{record.day}\n"
                    f"{reason}\n"
                    "点検結果と未解消の不具合を確認し、運行可否を再登録してください。"
                ),
                link=notification_link,
                files_json="[]",
                workflow_context_json=json.dumps(
                    build_notification_workflow_context(
                        record,
                        "vehicle",
                        "operation_judgment"
                    ),
                    ensure_ascii=False
                ),
                read=False,
                created_at=datetime.now(ZoneInfo("UTC")).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            )
            db.session.add(notification)
            result_record._pending_defect_notifications = (
                getattr(result_record, "_pending_defect_notifications", [])
                + [(target_user, notification)]
            )


def dispatch_vehicle_defect_notifications(result_record):
    notifications = getattr(
        result_record,
        "_pending_defect_notifications",
        []
    )
    result_record._pending_defect_notifications = []

    for target_user, notification in notifications:
        try:
            dispatch_external_notification(
                target_user,
                notification.title,
                notification.message,
                notification.link,
                notification_id=notification.id
            )
        except Exception:
            app.logger.exception(
                "日常点検の異常報告の外部通知に失敗しました。"
            )


def reset_vehicle_operation_judgment(result_record, result_checklist):
    if not any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in result_checklist.get("items", [])
    ):
        return

    previous = safe_json_dict(result_record.operation_judgment_json)
    judgment = dict(previous)
    defects = list(judgment.get("defects") or [])

    for answer in safe_json_dict_list(result_record.answers_json):
        if str(answer.get("value") or "").strip() != "×":
            continue

        item_no = str(answer.get("item_no", ""))
        if not item_no or any(
            str(defect.get("item_no", "")) == item_no
            and (
                defect.get("status") != "解消"
                or all(
                    defect.get("rechecked_answer", {}).get(field)
                    == answer.get(field)
                    for field in ("value", "comment", "files")
                )
            )
            for defect in defects
        ):
            continue

        defects.append({
            "defect_no": len(defects) + 1,
            "item_no": item_no,
            "status": "対応待ち",
            "reported_by": session.get("name") or "",
            "reported_by_username": session.get("username") or "",
            "reported_at": get_user_local_now(
                result_record.company_code,
                session.get("username")
            ).strftime("%Y-%m-%d %H:%M:%S"),
            "reported_answer": dict(answer),
        })

    new_defects = defects[len(previous.get("defects") or []):]
    if new_defects:
        target_usernames = set(previous.get("requested_usernames") or [])

        if not target_usernames:
            inspector = User.query.filter_by(
                company_code=result_record.company_code,
                username=result_record.checked_by_username
            ).first()

            if inspector and inspector.office:
                target_usernames.update(
                    user.username
                    for user in User.query.filter_by(
                        company_code=result_record.company_code,
                        office=inspector.office,
                        role="admin"
                    ).all()
                )

        vehicle = Vehicle.query.filter_by(
            company_code=result_record.company_code,
            id=result_record.vehicle_record_id
        ).first()

        vehicle_name = (
            " ".join(
                value
                for value in (
                    vehicle.plate_area or "",
                    vehicle.plate_class or "",
                    vehicle.plate_kana or "",
                    vehicle.plate_number or "",
                )
                if value
            )
            if vehicle else ""
        ) or f"車両ID：{result_record.vehicle_record_id}"

        notification_link = url_for(
            "vehicle_checklist_results",
            index=result_record.checklist_id,
            vehicle_record_id=result_record.vehicle_record_id,
            year=result_record.year,
            month=result_record.month,
            active_day=result_record.day
        ) + (
            f"#vehicle-flow-defect-{result_record.id}-"
            f"{new_defects[0]['defect_no']}"
        )

        item_names = "\n".join(
            f"No.{int(defect['item_no']) + 1} "
            f"{defect.get('reported_answer', {}).get('content') or ''}"
            for defect in new_defects
        )

        for target_username in sorted(target_usernames):
            target_user = User.query.filter_by(
                company_code=result_record.company_code,
                username=target_username,
                role="admin"
            ).first()

            if not target_user:
                continue

            notification = Notification(
                company_code=result_record.company_code,
                target_user=(target_user.last_name or "")
                + (target_user.first_name or ""),
                target_username=target_user.username,
                title="日常点検の異常報告：" + vehicle_name,
                message=(
                    f"対象車両：{vehicle_name}\n"
                    f"点検日：{result_record.year}/{result_record.month}/{result_record.day}\n"
                    f"異常項目：\n{item_names}\n"
                    "不具合対応と運行可否の判断を確認してください。"
                ),
                link=notification_link,
                files_json="[]",
                read=False,
                created_at=datetime.now(ZoneInfo("UTC")).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            )
            db.session.add(notification)

            result_record._pending_defect_notifications = (
                getattr(result_record, "_pending_defect_notifications", [])
                + [(target_user, notification)]
            )

    judgment["defects"] = defects
    judgment["status"] = "未判定"
    judgment["version"] = int(previous.get("version") or 0) + 1

    for key in (
        "reason",
        "judged_by",
        "judged_by_username",
        "judged_at",
        "authority_role",
        "authority_confirmed",
        "checks_confirmed",
        "checks_evidence",
    ):
        judgment.pop(key, None)

    result_record.operation_judgment_json = json.dumps(
        judgment,
        ensure_ascii=False
    )

    invalidate_other_vehicle_operation_judgments(result_record)

    if previous.get("status") not in (
        "運行可",
        "運行不可",
        "判定保留",
    ):
        return

    vehicle = Vehicle.query.filter_by(
        company_code=result_record.company_code,
        id=result_record.vehicle_record_id
    ).first()
    vehicle_name = (
        " ".join(
            value for value in (
                vehicle.plate_area or "",
                vehicle.plate_class or "",
                vehicle.plate_kana or "",
                vehicle.plate_number or "",
            ) if value
        ) if vehicle else ""
    ) or f"車両ID：{result_record.vehicle_record_id}"
    notification_link = url_for(
        "vehicle_checklist_results",
        index=result_record.checklist_id,
        vehicle_record_id=result_record.vehicle_record_id,
        year=result_record.year,
        month=result_record.month,
        active_day=result_record.day
    ) + "#vehicle-flow-judgment"
    recorded_at = get_user_local_now(
        result_record.company_code,
        session.get("username")
    ).strftime("%Y-%m-%d %H:%M:%S")

    for username in sorted(set(previous.get("requested_usernames") or [])):
        target_user = User.query.filter_by(
            company_code=result_record.company_code,
            username=username,
            role="admin"
        ).first()
        if not target_user:
            continue

        notification = Notification(
            company_code=result_record.company_code,
            target_user=(target_user.last_name or "") + (target_user.first_name or ""),
            target_username=target_user.username,
            title="運行可否の再判定依頼：" + vehicle_name,
            message=(
                f"対象車両：{vehicle_name}\n"
                f"点検日：{result_record.year}/{result_record.month}/{result_record.day}\n"
                "点検内容が変更され、変更前の運行判断は無効になりました。"
                "点検結果と未解消の不具合を確認し、運行可否を再登録してください。"
            ),
            link=notification_link,
            files_json="[]",
            workflow_context_json=json.dumps(
                build_notification_workflow_context(
                    result_record,
                    "vehicle",
                    "operation_judgment"
                ),
                ensure_ascii=False
            ),
            read=False,
            created_at=datetime.now(ZoneInfo("UTC")).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        )
        db.session.add(notification)
        result_record._pending_defect_notifications = (
            getattr(result_record, "_pending_defect_notifications", [])
            + [(target_user, notification)]
        )

    db.session.add(ChecklistEvent(
        company_code=result_record.company_code,
        result_type="vehicle",
        result_id=result_record.id,
        event_type="運行判断",
        actor_username=session.get("username"),
        actor_name=session.get("name"),
        detail_json=json.dumps(
            {
                "previous_judgment": previous,
                "judgment": {
                    **judgment,
                    "reason": "点検内容が変更されたため、再判定が必要です。",
                },
            },
            ensure_ascii=False
        ),
        created_at=get_user_local_now(
            result_record.company_code,
            session.get("username")
        ).strftime("%Y-%m-%d %H:%M:%S")
    ))


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
        return return_form_errors([
            (
                "対象車両を選択してください。",
                "vehicle_record_id"
            )
        ])

    vehicle = Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return return_form_errors([
            (
                "対象車両が不正です。",
                "vehicle_record_id"
            )
        ])

    # =========================
    # 日付検証
    # =========================

    try:
        year_int = int(year)
        month_int = int(month)
        day_int = int(day)
    except (TypeError, ValueError):
        return return_form_errors([
            (
                "点検日が不正です。",
                "year"
            )
        ])

    if year_int < 2000 or year_int > 2100:
        return return_form_errors([
            (
                "点検年が不正です。",
                "year"
            )
        ])

    if checklist.get("frequency_unit") == "year":
        month_int = 1
        day_int = 1

    elif checklist.get("display_type") == "month":
        if month_int < 1 or month_int > 12:
            return return_form_errors([
                (
                    "点検月が不正です。",
                    "month"
                )
            ])

        try:
            datetime(
                year_int,
                month_int,
                day_int
            )
        except ValueError:
            return return_form_errors([
                (
                    "点検日が不正です。",
                    "day"
                )
            ])

    else:
        if month_int < 1 or month_int > 12:
            return return_form_errors([
                (
                    "点検月が不正です。",
                    "month"
                )
            ])

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

    lock_error = lock_vehicle_inspection_updates(
        company_code,
        vehicle_record_id=vehicle_record_id,
        checklist=checklist
    )
    if lock_error is not None:
        return lock_error

    result_record = (
        VehicleChecklistResult.query
        .filter_by(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day
        )
        .with_for_update()
        .first()
    )

    if (
        result_record
        and result_record.status in {
            "承認待ち",
            "承認済み"
        }
    ):
        return return_form_errors([
            (
                (
                    "承認待ちの点検結果は変更できません。"
                    if result_record.status == "承認待ち"
                    else "承認済みの点検結果は変更できません。"
                ),
                ""
            )
        ], status_code=403)

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
        return return_form_errors([
            (
                "チェック項目が不正です。",
                ""
            )
        ])

    check_items = [
        item
        for item in result_checklist.get("items", [])
        if item.get("item_type") == "check"
    ]

    if item_no < 0 or item_no >= len(check_items):
        return return_form_errors([
            (
                "チェック項目が不正です。",
                ""
            )
        ])

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

        if value and value not in valid_choices:
            return return_form_errors([
                (
                    "回答値が不正です。",
                    f"answer_{item_no}"
                )
            ])

    if not result_record and not value:
        return jsonify({
            "success": True
        })

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

    previous_value = answer.get("value", "")

    answer["value"] = value
    answer["category"] = category
    answer["content"] = content
    answer["criteria"] = criteria

    if (
        not value.strip()
        and not str(answer.get("comment") or "").strip()
        and not answer.get("files")
    ):
        answers = [
            stored_answer
            for stored_answer in answers
            if stored_answer is not answer
        ]

    was_rejected = (
        result_record.status == "差し戻し"
    )

    result_record.checked_by = session.get("name")
    result_record.checked_by_username = session.get("username")
    result_record.checked_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    result_record.status = (
        "差し戻し"
        if was_rejected
        else "入力中"
    )

    previous_approvals = safe_json_dict_list(
        result_record.approvals_json
    )

    approvals = []

    for item in result_checklist.get("items", []):
        if item.get("item_type") != "approval":
            continue

        approval_index = len(approvals)

        previous_approval = (
            previous_approvals[approval_index]
            if approval_index < len(previous_approvals)
            else {}
        )

        approvals.append({
            "label": item.get("approval_label", ""),
            "allow_general": item.get("approval_allow_general", False),
            "candidate_usernames": previous_approval.get(
                "candidate_usernames",
                []
            ),
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
    if not was_rejected:
        result_record.reject_reason = ""
    result_record.answers_json = json.dumps(answers, ensure_ascii=False)

    if previous_value != value:
        reset_vehicle_operation_judgment(
            result_record,
            result_checklist
        )

    if was_rejected and previous_value != value:
        checklist_event = ChecklistEvent(
            company_code=result_record.company_code,
            result_type="vehicle",
            result_id=result_record.id,
            event_type="修正",
            actor_username=session.get("username"),
            actor_name=session.get("name"),
            detail_json=json.dumps(
                {
                    "changes": [
                        {
                            "item_no": item_no,
                            "before": previous_value,
                            "after": value,
                        }
                    ],
                },
                ensure_ascii=False
            ),
            created_at=datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
        db.session.add(checklist_event)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()

        return return_form_errors([
            (
                "同じ点検結果が同時に更新されました。"
                "画面を再読み込みして確認してください。",
                ""
            )
        ], status_code=409)

    dispatch_vehicle_defect_notifications(result_record)

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
        return return_form_errors([
            (
                "対象車両を選択してください。",
                "vehicle_record_id"
            )
        ])

    vehicle = Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return return_form_errors([
            (
                "対象車両が不正です。",
                "vehicle_record_id"
            )
        ])

    # =========================
    # 日付検証
    # =========================

    try:
        year_int = int(year)
        month_int = int(month)
        day_int = int(day)
    except (TypeError, ValueError):
        return return_form_errors([
            (
                "点検日が不正です。",
                "detailYear"
            )
        ])

    if year_int < 2000 or year_int > 2100:
        return return_form_errors([
            (
                "点検年が不正です。",
                "detailYear"
            )
        ])

    if checklist.get("frequency_unit") == "year":
        month_int = 1
        day_int = 1

    elif checklist.get("display_type") == "month":
        if month_int < 1 or month_int > 12:
            return return_form_errors([
                (
                    "点検月が不正です。",
                    "detailMonth"
                )
            ])

        try:
            datetime(
                year_int,
                month_int,
                day_int
            )
        except ValueError:
            return return_form_errors([
                (
                    "点検日が不正です。",
                    "detailDay"
                )
            ])

    else:
        if month_int < 1 or month_int > 12:
            return return_form_errors([
                (
                    "点検月が不正です。",
                    "detailMonth"
                )
            ])

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

    uploaded_files = [
        file
        for file in request.files.getlist("files")
        if file and file.filename
    ]

    if len(comment) > 5000:
        return return_form_errors([
            (
                "コメントは5000文字以内で入力してください。",
                "detailCommentEditor"
            )
        ])

    lock_error = lock_vehicle_inspection_updates(
        company_code,
        vehicle_record_id=vehicle_record_id,
        checklist=checklist
    )
    if lock_error is not None:
        return lock_error

    result_record = (
        VehicleChecklistResult.query
        .filter_by(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day
        )
        .with_for_update()
        .first()
    )

    if (
        result_record
        and result_record.status in {
            "承認待ち",
            "承認済み"
        }
    ):
        return return_form_errors([
            (
                (
                    "承認待ちの点検結果は変更できません。"
                    if result_record.status == "承認待ち"
                    else "承認済みの点検結果は変更できません。"
                ),
                ""
            )
        ], status_code=403)

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
        return return_form_errors([
            (
                "チェック項目が不正です。",
                "detailItemNo"
            )
        ])

    check_items = [
        item
        for item in result_checklist.get("items", [])
        if item.get("item_type") == "check"
    ]

    if item_no < 0 or item_no >= len(check_items):
        return return_form_errors([
            (
                "チェック項目が不正です。",
                "detailItemNo"
            )
        ])

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



    if (
        not result_record
        and not comment
        and not uploaded_files
    ):
        return jsonify({
            "success": True
        })

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

    if len(uploaded_files) > 50:
        return return_form_errors([
            (
                "一度にアップロードできるファイルは50件までです。",
                "detailPreview"
            )
        ])

    answer.setdefault("files", [])

    previous_files = list(
        answer.get("files", [])
    )

    for file in uploaded_files:
        original_filename = os.path.basename(
            str(file.filename or "")
        )

        extension = os.path.splitext(
            original_filename
        )[1].lower()

        if (
            extension not in ALLOWED_UPLOAD_EXTENSIONS
            or not is_valid_uploaded_file(
                file,
                extension
            )
        ):
            return return_form_errors([
                (
                    "添付ファイルの検証に失敗しました。",
                    "detailPreview"
                )
            ])

    saved_filenames = []

    for file in uploaded_files:
        try:
            filename = save_uploaded_file(file)
        except UploadValidationError:
            for saved_filename in saved_filenames:
                delete_uploaded_file(saved_filename)

            return return_form_errors([
                (
                    "添付ファイルの検証に失敗しました。",
                    "detailPreview"
                )
            ])

        if filename:
            saved_filenames.append(filename)
            answer["files"].append(filename)

    previous_comment = answer.get("comment", "")

    answer["comment"] = comment
    answer["category"] = category
    answer["content"] = content
    answer["criteria"] = criteria

    answer_value = answer.get("value", "")

    if (
        (answer_value is None or not str(answer_value).strip())
        and not comment
        and not answer.get("files")
    ):
        answers = [
            stored_answer
            for stored_answer in answers
            if stored_answer is not answer
        ]

    was_rejected = (
        result_record.status == "差し戻し"
    )

    previous_approvals = safe_json_dict_list(
        result_record.approvals_json
    )

    approvals = []

    for item in result_checklist.get("items", []):
        if item.get("item_type") != "approval":
            continue

        approval_index = len(approvals)

        previous_approval = (
            previous_approvals[approval_index]
            if approval_index < len(previous_approvals)
            else {}
        )

        approvals.append({
            "label": item.get("approval_label", ""),
            "allow_general": item.get("approval_allow_general", False),
            "candidate_usernames": previous_approval.get(
                "candidate_usernames",
                []
            ),
            "approved_by": "",
            "approved_by_username": "",
            "approved_date": "",
        })

    result_record.checked_by = session.get("name")
    result_record.checked_by_username = session.get("username")
    result_record.checked_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    result_record.status = (
        "差し戻し"
        if was_rejected
        else "入力中"
    )
    result_record.approved_by = ""
    result_record.approved_by_username = ""
    result_record.approved_date = ""
    result_record.approvals_json = json.dumps(
        approvals,
        ensure_ascii=False
    )
    if not was_rejected:
        result_record.reject_reason = ""
    result_record.answers_json = json.dumps(answers, ensure_ascii=False)

    if (
        previous_comment != comment
        or previous_files != answer.get("files", [])
    ):
        reset_vehicle_operation_judgment(
            result_record,
            result_checklist
        )

    if (
        was_rejected
        and (
            previous_comment != comment
            or previous_files != answer.get("files", [])
        )
    ):
        checklist_event = ChecklistEvent(
            company_code=result_record.company_code,
            result_type="vehicle",
            result_id=result_record.id,
            event_type="修正",
            actor_username=session.get("username"),
            actor_name=session.get("name"),
            detail_json=json.dumps(
                {
                    "changes": [
                        *(
                            [
                                {
                                    "item_no": item_no,
                                    "field": "comment",
                                    "before": previous_comment,
                                    "after": comment,
                                }
                            ]
                            if previous_comment != comment
                            else []
                        ),
                        *(
                            [
                                {
                                    "item_no": item_no,
                                    "field": "files",
                                    "before": previous_files,
                                    "after": answer.get("files", []),
                                }
                            ]
                            if previous_files != answer.get("files", [])
                            else []
                        ),
                    ],
                },
                ensure_ascii=False
            ),
            created_at=datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
        db.session.add(checklist_event)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()

        for filename in saved_filenames:
            delete_uploaded_file(filename)

        return return_form_errors([
            (
                "同じ点検結果が同時に更新されました。"
                "画面を再読み込みして確認してください。",
                ""
            )
        ], status_code=409)

    except SQLAlchemyError:
        db.session.rollback()

        for filename in saved_filenames:
            delete_uploaded_file(filename)

        return return_form_errors([
            (
                "車両チェックリストの更新に失敗しました。"
                "もう一度お試しください。",
                ""
            )
        ], status_code=500)
    
    dispatch_vehicle_defect_notifications(result_record)

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
        return return_form_errors([
            (
                "対象車両を選択してください。",
                "vehicle_record_id"
            )
        ])

    vehicle = Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return return_form_errors([
            (
                "対象車両が不正です。",
                "vehicle_record_id"
            )
        ])

    # =========================
    # 日付検証
    # =========================

    try:
        year_int = int(year)
        month_int = int(month)
        day_int = int(day)
    except (TypeError, ValueError):
        return return_form_errors([
            (
                "点検日が不正です。",
                "year"
            )
        ])

    if year_int < 2000 or year_int > 2100:
        return return_form_errors([
            (
                "点検年が不正です。",
                "year"
            )
        ])

    if checklist.get("frequency_unit") == "year":
        month_int = 1
        day_int = 1

    elif checklist.get("display_type") == "month":
        if month_int < 1 or month_int > 12:
            return return_form_errors([
                (
                    "点検月が不正です。",
                    "month"
                )
            ])

        try:
            datetime(
                year_int,
                month_int,
                day_int
            )
        except ValueError:
            return return_form_errors([
                (
                    "点検日が不正です。",
                    "day"
                )
            ])

    else:
        if month_int < 1 or month_int > 12:
            return return_form_errors([
                (
                    "点検月が不正です。",
                    "month"
                )
            ])

        day_int = 1

    year = str(year_int)
    month = str(month_int).zfill(2)
    day = str(day_int).zfill(2)

    lock_error = lock_vehicle_inspection_updates(
        company_code,
        vehicle_record_id=vehicle_record_id,
        checklist=checklist
    )
    if lock_error is not None:
        return lock_error

    # =========================
    # 結果取得
    # =========================

    result_record = (
        VehicleChecklistResult.query
        .filter_by(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day
        )
        .with_for_update()
        .first()
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
                checklist_for_date(
                    checklist,
                    year,
                    month,
                    day
                ),
                ensure_ascii=False
            )
        )

        db.session.add(result_record)

    if result_record.status in {
        "承認待ち",
        "承認済み"
    }:
        return return_form_errors([
            (
                (
                    "すでに承認待ちです。"
                    if result_record.status == "承認待ち"
                    else "すでに承認済みです。"
                ),
                ""
            )
        ], status_code=409)

    result_checklist = checklist_for_date(
        checklist,
        year,
        month,
        day
    )

    if result_record.checklist_snapshot_json:
        snapshot = safe_json_dict(
            result_record.checklist_snapshot_json
        )

        if snapshot:
            result_checklist = snapshot
    else:
        result_record.checklist_snapshot_json = json.dumps(
            result_checklist,
            ensure_ascii=False
        )

    answers = safe_json_dict_list(
        result_record.answers_json
    )

    check_items = [
        item
        for item in result_checklist.get("items", [])
        if item.get("item_type") == "check"
    ]

    answers_by_item_no = {}

    for answer in answers:
        try:
            answer_item_no = int(
                answer.get("item_no")
            )
        except (TypeError, ValueError):
            continue

        answers_by_item_no[answer_item_no] = answer

    for item_no, item in enumerate(check_items):
        answer = answers_by_item_no.get(item_no, {})

        value = str(
            answer.get("value", "")
            or ""
        ).strip()

        comment = str(
            answer.get("comment", "")
            or ""
        ).strip()

        if item.get("input_type") == "select":
            valid_choices = [
                str(choice)
                for choice in item.get(
                    "choices",
                    []
                )
            ]

            if value and value not in valid_choices:
                return return_form_errors([
                    (
                        "回答値が不正です。",
                        f"answer_{item_no}"
                    )
                ])

        if (
            item.get("answer_required")
            and not value
        ):
            return return_form_errors([
                (
                    "必須項目が未回答です。",
                    f"answer_{item_no}"
                )
            ])

        if len(comment) > 5000:
            return return_form_errors([
                (
                    "コメントは5000文字以内で入力してください。",
                    f"comment_{item_no}"
                )
            ])

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
        return return_form_errors([
            (
                "通知先ユーザー数が多すぎます。",
                "notify_user_search"
            )
        ])

    valid_users = {
        user.username: user
        for user in User.query.filter_by(
            company_code=company_code
        ).all()
        if user.username
    }

    for username in notify_usernames:
        if username not in valid_users:
            return return_form_errors([
                (
                    "通知先ユーザーが不正です。",
                    "notify_user_search"
                )
            ])

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

    if (
        not notify_usernames
        and session.get("username") in valid_users
    ):
        notify_usernames = [
            session.get("username")
        ]

    if any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in result_checklist.get("items", [])
    ):
        notify_usernames = []

    # =========================
    # 完了処理
    # =========================

    result_record.checked_by = session.get("name")
    result_record.checked_by_username = session.get("username")
    result_record.checked_date = (
        datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    approvals = []

    for item in result_checklist.get("items", []):
        if item.get("item_type") != "approval":
            continue

        approval_index = len(approvals)

        submitted_candidate_usernames = [
            username.strip()
            for username in request.form.getlist(
                f"approval_notify_users_{approval_index}"
            )
            if username.strip()
        ]

        if len(submitted_candidate_usernames) > 500:
            return return_form_errors([
                (
                    "承認候補者数が多すぎます。",
                    f"approval_user_search_{approval_index}"
                )
            ])

        invalid_candidate_usernames = [
            username
            for username in submitted_candidate_usernames
            if (
                username not in valid_users
                or not (
                    valid_users[username].role == "admin"
                    or (
                        item.get(
                            "approval_allow_general",
                            False
                        )
                        and valid_users[username].role == "user"
                    )
                )
            )
        ]

        if invalid_candidate_usernames:
            return return_form_errors([
                (
                    "承認者の選択内容が不正です。",
                    f"approval_user_search_{approval_index}"
                )
            ])

        candidate_usernames = list(
            dict.fromkeys(
                submitted_candidate_usernames
            )
        )

        approvals.append({
            "label": item.get("approval_label", ""),
            "allow_general": item.get(
                "approval_allow_general",
                False
            ),
            "candidate_usernames": candidate_usernames,
            "approved_by": "",
            "approved_by_username": "",
            "approved_date": "",
        })

    if any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in result_checklist.get("items", [])
    ):
        existing_defects = safe_json_dict(
            result_record.operation_judgment_json
        ).get("defects") or []

        has_unregistered_defect = any(
            str(answer.get("value") or "").strip() == "×"
            and str(answer.get("item_no", ""))
            and not any(
                str(defect.get("item_no", ""))
                == str(answer.get("item_no", ""))
                and (
                    defect.get("status") != "解消"
                    or all(
                        defect.get("rechecked_answer", {}).get(field)
                        == answer.get(field)
                        for field in ("value", "comment", "files")
                    )
                )
                for defect in existing_defects
            )
            for answer in answers
        )

        if has_unregistered_defect:
            reset_vehicle_operation_judgment(
                result_record,
                result_checklist
            )

        approval_items = [
            item
            for item in result_checklist.get("items", [])
            if item.get("item_type") == "approval"
        ]
        judgment = safe_json_dict(result_record.operation_judgment_json)
        judgment.setdefault("status", "未判定")
        judgment["requested_usernames"] = []

        for approval_index, item in enumerate(approval_items):
            if item.get("item_code") == "footer_30":
                previous_requested_usernames = safe_json_dict(
                    result_record.operation_judgment_json
                ).get("requested_usernames", [])

                next_requested_usernames = approvals[
                    approval_index
                ].get("candidate_usernames", [])

                if set(previous_requested_usernames) != set(
                    next_requested_usernames
                ):
                    judgment["version"] = int(
                        judgment.get("version") or 0
                    ) + 1

                judgment["requested_usernames"] = list(
                    approvals[approval_index].get("candidate_usernames", [])
                )
                break

        result_record.operation_judgment_json = json.dumps(
            judgment,
            ensure_ascii=False
        )

    has_system_approval = bool(approvals)

    was_rejected = (
        result_record.status == "差し戻し"
    )

    result_record.status = (
        "承認待ち"
        if has_system_approval
        else "点検完了"
    )
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

    if was_rejected:
        checklist_event = ChecklistEvent(
            company_code=result_record.company_code,
            result_type="vehicle",
            result_id=result_record.id,
            event_type="再申請",
            actor_username=session.get("username"),
            actor_name=session.get("name"),
            detail_json=json.dumps(
                {
                    "approvals": approvals,
                },
                ensure_ascii=False
            ),
            created_at=datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
        db.session.add(checklist_event)

    db.session.commit()
    dispatch_vehicle_defect_notifications(result_record)

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

    first_approval = (
        approvals[0]
        if has_system_approval and approvals
        else {}
    )
    approval_usernames = set(
        first_approval.get("candidate_usernames") or []
    )
    notification_usernames = set(approval_usernames)

    if was_rejected:
        latest_rejection = ChecklistEvent.query.filter_by(
            company_code=company_code,
            result_type="vehicle",
            result_id=result_record.id,
            event_type="差し戻し"
        ).order_by(
            ChecklistEvent.id.desc()
        ).first()

        if latest_rejection and latest_rejection.actor_username:
            notification_usernames.add(
                latest_rejection.actor_username
            )

    for target_username in sorted(notification_usernames):
        target_user = valid_users.get(target_username)

        if not target_user:
            continue

        is_approval_recipient = (
            target_username in approval_usernames
        )

        if was_rejected:
            notification_title = (
                "車両チェックリスト再申請の承認依頼"
                if is_approval_recipient
                else "車両チェックリスト修正・再申請のお知らせ"
            )
            notification_message = (
                f"「{checklist_record.name}」が"
                "修正・再申請されました。"
                + (
                    "承認をお願いします。"
                    if is_approval_recipient
                    else "変更内容を確認してください。"
                )
            )
        else:
            notification_title = "車両チェックリスト承認依頼"
            notification_message = (
                f"「{checklist_record.name}」"
                "の承認をお願いします。"
            )

        add_notification(
            (target_user.last_name or "")
            + (target_user.first_name or ""),
            notification_title,
            notification_message,
            notification_link,
            company_code=company_code,
            target_username=target_user.username,
            workflow_context=(
                build_notification_workflow_context(
                    result_record,
                    "vehicle",
                    "approval",
                    approval_index=0
                )
                if is_approval_recipient
                else None
            )
        )

    if not has_system_approval:
        for target_username in notify_usernames:
            target_user = valid_users[target_username]

            add_notification(
                (target_user.last_name or "") + (target_user.first_name or ""),
                "車両点検完了のお知らせ",
                (
                    f"{' '.join(value for value in [vehicle.plate_area or '', vehicle.plate_class or '', vehicle.plate_kana or '', vehicle.plate_number or ''] if value) or 'ナンバー未登録'} の"
                    f"「{checklist_record.name}」が"
                    "点検完了しました。"
                ),
                notification_link,
                company_code=company_code,
                target_username=target_user.username
            )

    completion_link = notification_link
    if any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in result_checklist.get("items", [])
    ):
        completion_link = url_for(
            "vehicle_checklist_results",
            index=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            active_day=active_day,
            vehicle_saved="complete"
        ) + "#vehicle-flow-completed"

    if request.headers.get("X-DKSS-Final-Submit") == "1":
        return jsonify({"success": True, "redirect_url": completion_link})

    return redirect(completion_link)

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
        lock_error = lock_vehicle_inspection_updates(
            session.get("company_code"),
            vehicle_record_id=request.form.get("vehicle_record_id", type=int),
            checklist=checklist
        )
        if lock_error is not None:
            return lock_error
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
            return return_form_errors([
                (
                    "対象車両を選択してください。",
                    "vehicle_record_id"
                )
            ])

        vehicle = Vehicle.query.filter_by(
            company_code=company_code,
            id=vehicle_record_id,
            deleted=False
        ).first()

        if not vehicle:
            return return_form_errors([
                (
                    "対象車両が不正です。",
                    "vehicle_record_id"
                )
            ])

        # =========================
        # 日付検証
        # =========================

        try:
            year_int = int(year)
            month_int = int(month)
            day_int = int(day)
        except (TypeError, ValueError):
            return return_form_errors([
                (
                    "点検日が不正です。",
                    "year"
                )
            ])

        if year_int < 2000 or year_int > 2100:
            return return_form_errors([
                (
                    "点検年が不正です。",
                    "year"
                )
            ])

        # 年次チェックリスト
        if checklist.get("frequency_unit") == "year":
            month_int = 1
            day_int = 1

        # 日単位表示
        elif checklist.get("display_type") == "month":
            if month_int < 1 or month_int > 12:
                return return_form_errors([
                    (
                        "点検月が不正です。",
                        "month"
                    )
                ])

            try:
                datetime(
                    year_int,
                    month_int,
                    day_int
                )
            except ValueError:
                return return_form_errors([
                    (
                        "点検日が不正です。",
                        "day"
                    )
                ])

        # 月単位など
        else:
            if month_int < 1 or month_int > 12:
                return return_form_errors([
                    (
                        "点検月が不正です。",
                        "month"
                    )
                ])

            day_int = 1

        year = str(year_int)
        month = str(month_int).zfill(2)
        day = str(day_int).zfill(2)

        checklist = checklist_for_date(
            checklist,
            year,
            month,
            day
        )

        existing_result = VehicleChecklistResult.query.filter_by(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day
        ).first()

        if existing_result:
            return redirect(
                url_for(
                    "vehicle_checklist_results",
                    index=checklist_record.id,
                    vehicle_record_id=vehicle_record_id,
                    year=year,
                    month=month,
                    active_day=day,
                )
            )

        answers = []
        answer_index = 0
        pending_answer_files = []

        for item in checklist["items"]:
            if item.get("item_type") != "check":
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

                if value and value not in valid_choices:
                    return return_form_errors([
                        (
                            "回答値が不正です。",
                            f"answer_{answer_index}"
                        )
                    ])



            comment = request.form.get(
                f"comment_{answer_index}",
                ""
            ).strip()

            if (
                item.get("answer_required")
                and not value
            ):
                return return_form_errors([
                    (
                        "必須項目が未回答です。",
                        f"answer_{answer_index}"
                    )
                ])

            if len(comment) > 5000:
                return return_form_errors([
                    (
                        "コメントは5000文字以内で入力してください。",
                        f"comment_{answer_index}"
                    )
                ])

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

        pending_uploads = []

        upload_file_count = sum(
            1
            for field_name in request.files.keys()
            for file in request.files.getlist(field_name)
            if file and file.filename
        )

        if upload_file_count > 50:
            return return_form_errors([
                (
                    "一度にアップロードできるファイルは50件までです。",
                    ""
                )
            ])

        for item_index, form_index in pending_answer_files:
            for file in request.files.getlist(
                f"files_{form_index}"
            ):
                if not file or not file.filename:
                    continue

                original_filename = os.path.basename(
                    str(file.filename or "")
                )

                extension = os.path.splitext(
                    original_filename
                )[1].lower()

                if (
                    extension not in ALLOWED_UPLOAD_EXTENSIONS
                    or not is_valid_uploaded_file(
                        file,
                        extension
                    )
                ):
                    return return_form_errors([
                        (
                            "添付ファイルの検証に失敗しました。",
                            f"files_{form_index}"
                        )
                    ])

                pending_uploads.append(
                    (item_index, file)
                )

        valid_users = {
            user.username: user
            for user in User.query.filter_by(
                company_code=company_code
            ).all()
            if user.username
        }

        approvals = []

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approval_index = len(approvals)

            submitted_candidate_usernames = [
                username.strip()
                for username in request.form.getlist(
                    f"approval_notify_users_{approval_index}"
                )
                if username.strip()
            ]

            if len(submitted_candidate_usernames) > 500:
                return return_form_errors([
                    (
                        "承認候補者数が多すぎます。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            invalid_candidate_usernames = [
                username
                for username in submitted_candidate_usernames
                if (
                    username not in valid_users
                    or not (
                        valid_users[username].role == "admin"
                        or (
                            item.get(
                                "approval_allow_general",
                                False
                            )
                            and valid_users[username].role == "user"
                        )
                    )
                )
            ]

            if invalid_candidate_usernames:
                return return_form_errors([
                    (
                        "承認者の選択内容が不正です。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            candidate_usernames = list(
                dict.fromkeys(
                    submitted_candidate_usernames
                )
            )

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get(
                    "approval_allow_general",
                    False
                ),
                "candidate_usernames": (
                    candidate_usernames
                ),
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        has_system_approval = bool(approvals)

        notify_usernames = (
            get_vehicle_checklist_notify_users(
                company_code,
                checklist_record.id,
                vehicle_record_id
            )
        )

        saved_filenames = []

        for item_index, file in pending_uploads:
            try:
                filename = save_uploaded_file(file)
            except UploadValidationError:
                for saved_filename in saved_filenames:
                    delete_uploaded_file(saved_filename)

                return return_form_errors([
                    (
                        "添付ファイルの検証に失敗しました。",
                        ""
                    )
                ])

            if filename:
                saved_filenames.append(filename)

                answers[item_index]["files"].append(
                    filename
                )

        answers = [
            answer
            for answer in answers
            if str(answer.get("value", "")).strip()
            or str(answer.get("comment", "")).strip()
            or answer.get("files")
        ]

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
            status=(
                "承認待ち"
                if has_system_approval
                else "点検完了"
            ),
            approved_by="",
            approved_by_username="",
            approved_date="",
            reject_reason="",
            approvals_json=json.dumps(
                approvals,
                ensure_ascii=False
            ),
            notify_users_json=json.dumps(
                notify_usernames,
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

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

            for filename in saved_filenames:
                delete_uploaded_file(filename)

            return return_form_errors([
                (
                    "同じ車両・点検日の結果が同時に登録されました。"
                    "画面を再読み込みして確認してください。",
                    ""
                )
            ], status_code=409)

        except SQLAlchemyError:
            db.session.rollback()

            for filename in saved_filenames:
                delete_uploaded_file(filename)

            return return_form_errors([
                (
                    "車両チェックリストの保存に失敗しました。"
                    "もう一度お試しください。",
                    ""
                )
            ], status_code=500)
        
        if has_system_approval and approvals:
            first_approval = approvals[0]

            for username in (
                first_approval.get(
                    "candidate_usernames",
                    []
                )
                if first_approval
                else []
            ):
                target_user = valid_users.get(username)

                if not target_user:
                    continue

                add_notification(
                    target_user=(target_user.last_name or "")
                    + (target_user.first_name or ""),
                    company_code=company_code,
                    target_username=username,
                    title="車両チェックリスト承認依頼",
                    workflow_context=build_notification_workflow_context(
                        result,
                        "vehicle",
                        "approval",
                        approval_index=0
                    ),
                    message=(
                        f"「{checklist.get('name', '車両チェックリスト')}」"
                        "の承認をお願いします。"
                    ),
                    link=url_for(
                        "vehicle_checklist_results",
                        index=checklist_record.id,
                        vehicle_record_id=vehicle_record_id,
                        year=year,
                        month=month,
                        active_day=day,
                    ),
                )

        if not has_system_approval:
            for target_username in notify_usernames:
                target_user = valid_users.get(
                    target_username
                )

                if not target_user:
                    continue

                add_notification(
                    (
                        (target_user.last_name or "")
                        + (target_user.first_name or "")
                    ),
                    "車両点検完了のお知らせ",
                    (
                        f"「{checklist_record.name}」が"
                        "点検完了しました。"
                    ),
                    url_for(
                        "vehicle_checklist_results",
                        index=checklist_record.id,
                        vehicle_record_id=vehicle_record_id,
                        year=year,
                        month=month,
                        active_day=day,
                    ),
                    company_code=company_code,
                    target_username=target_user.username
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
            return return_form_errors([
                (
                    "対象種別が不正です。",
                    "target_type"
                )
            ])

        # =========================
        # 個人
        # =========================

        if target_type == "user":
            if not target_user:
                return return_form_errors([
                    (
                        "対象ユーザーを選択してください。",
                        "target_user"
                    )
                ])

            target_driver = Driver.query.filter_by(
                company_code=company_code,
                employee_id=target_user
            ).first()

            if not target_driver:
                return return_form_errors([
                    (
                        "対象ユーザーが不正です。",
                        "target_user"
                    )
                ])

            target_user_record = User.query.filter_by(
                company_code=company_code,
                username=target_driver.employee_id
            ).first()

            if not target_user_record:
                return return_form_errors([
                    (
                        "対象ユーザー情報が不正です。",
                        "target_user"
                    )
                ])

            target_username = target_user_record.username
            target_user = target_driver.name
            target_office = target_driver.office or ""
            target_vehicle_record_id = None

        # =========================
        # 車両
        # =========================

        elif target_type == "vehicle":
            if not target_vehicle_record_id:
                return return_form_errors([
                    (
                        "対象車両を選択してください。",
                        "target_vehicle_record_id"
                    )
                ])

            vehicle = Vehicle.query.filter_by(
                company_code=company_code,
                id=target_vehicle_record_id,
                deleted=False
            ).first()

            if not vehicle:
                return return_form_errors([
                    (
                        "対象車両が不正です。",
                        "target_vehicle_record_id"
                    )
                ])

            target_office = vehicle.office or ""
            target_user = ""

        # =========================
        # 営業所
        # =========================

        elif target_type == "office":
            if not target_office:
                return return_form_errors([
                    (
                        "対象営業所を選択してください。",
                        "target_office"
                    )
                ])

            valid_office = Office.query.filter_by(
                company_code=company_code,
                name=target_office
            ).first()

            if not valid_office:
                return return_form_errors([
                    (
                        "対象営業所が不正です。",
                        "target_office"
                    )
                ])

            target_user = ""
            target_vehicle_record_id = None

        pending_answer_files = []

        for item in checklist["items"]:
            if item.get("item_type") != "check":
                continue

            value = request.form.get(
                f"answer_{answer_index}",
                ""
            )

            choices = item.get("choices", [])

            if (
                item.get("input_type") == "select"
                and value
                and value not in choices
            ):
                return return_form_errors([
                    (
                        "評価値が不正です。",
                        f"answer_{answer_index}"
                    )
                ])

            comment = request.form.get(
                f"comment_{answer_index}",
                ""
            ).strip()

            if (
                item.get("answer_required")
                and not value
            ):
                return return_form_errors([
                    (
                        "必須項目が未回答です。",
                        f"answer_{answer_index}"
                    )
                ])

            if len(comment) > 5000:
                return return_form_errors([
                    (
                        "コメントは5000文字以内で入力してください。",
                        f"comment_{answer_index}"
                    )
                ])

            patrol_link = request.form.get(
                f"patrol_link_{answer_index}"
            )

            item_index = len(answers)

            answers.append({
                "item_no": answer_index,
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

        pending_uploads = []

        upload_file_count = sum(
            1
            for field_name in request.files.keys()
            for file in request.files.getlist(field_name)
            if file and file.filename
        )

        if upload_file_count > 50:
            return return_form_errors([
                (
                    "一度にアップロードできるファイルは50件までです。",
                    ""
                )
            ])

        for item_index, form_index in pending_answer_files:
            for file in request.files.getlist(
                f"files_{form_index}"
            ):
                if not file or not file.filename:
                    continue

                original_filename = os.path.basename(
                    str(file.filename or "")
                )

                extension = os.path.splitext(
                    original_filename
                )[1].lower()

                if (
                    extension not in ALLOWED_UPLOAD_EXTENSIONS
                    or not is_valid_uploaded_file(
                        file,
                        extension
                    )
                ):
                    return return_form_errors([
                        (
                            "添付ファイルの検証に失敗しました。",
                            f"files_{form_index}"
                        )
                    ])

                pending_uploads.append(
                    (item_index, file)
                )



        notify_usernames = [
            username.strip()
            for username in request.form.getlist(
                "notify_users"
            )
            if username.strip()
        ]

        notify_usernames = list(
            dict.fromkeys(notify_usernames)
        )

        if len(notify_usernames) > 500:
            return return_form_errors([
                (
                    "通知先ユーザー数が多すぎます。",
                    "notify_user_search"
                )
            ])

        valid_users = {
            user.username: user
            for user in User.query.filter_by(
                company_code=company_code
            ).all()
            if user.username
        }

        invalid_notify_usernames = [
            username
            for username in notify_usernames
            if username not in valid_users
        ]

        if invalid_notify_usernames:
            return return_form_errors([
                (
                    "通知先ユーザーが不正です。",
                    "notify_user_search"
                )
            ])

        approvals = []

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approval_index = len(approvals)

            submitted_candidate_usernames = [
                username.strip()
                for username in request.form.getlist(
                    f"approval_notify_users_{approval_index}"
                )
                if username.strip()
            ]

            if len(submitted_candidate_usernames) > 500:
                return return_form_errors([
                    (
                        "承認候補者数が多すぎます。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            invalid_candidate_usernames = [
                username
                for username in submitted_candidate_usernames
                if (
                    username not in valid_users
                    or not (
                        valid_users[username].role == "admin"
                        or (
                            item.get(
                                "approval_allow_general",
                                False
                            )
                            and valid_users[username].role == "user"
                        )
                    )
                )
            ]

            if invalid_candidate_usernames:
                return return_form_errors([
                    (
                        "承認者の選択内容が不正です。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            candidate_usernames = list(
                dict.fromkeys(
                    submitted_candidate_usernames
                )
            )

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get(
                    "approval_allow_general",
                    False
                ),
                "candidate_usernames": list(
                    dict.fromkeys(candidate_usernames)
                ),
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        saved_filenames = []

        try:
            for item_index, file in pending_uploads:
                filename = save_uploaded_file(file)

                if filename:
                    answers[item_index]["files"].append(filename)
                    saved_filenames.append(filename)

        except UploadValidationError:
            for filename in saved_filenames:
                delete_uploaded_file(filename)

            return return_form_errors([
                (
                    "添付ファイルの検証に失敗しました。",
                    ""
                )
            ])

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
            status=(
                "承認待ち"
                if approvals
                else "点検完了"
            ),
            approvals_json=json.dumps(
                approvals,
                ensure_ascii=False
            ),
            notify_users_json=json.dumps(
                notify_usernames,
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

        try:
            db.session.commit()

        except IntegrityError:
            db.session.rollback()

            for filename in saved_filenames:
                delete_uploaded_file(filename)

            return return_form_errors(
                [
                    (
                        "安全チェックリストの保存に失敗しました。"
                        "もう一度お試しください。",
                        ""
                    )
                ],
                status_code=409
            )

        except SQLAlchemyError:
            db.session.rollback()

            for filename in saved_filenames:
                delete_uploaded_file(filename)

            return return_form_errors(
                [
                    (
                        "安全チェックリストの保存に失敗しました。"
                        "もう一度お試しください。",
                        ""
                    )
                ],
                status_code=500
            )
        
        first_approval_usernames = (
            approvals[0].get("candidate_usernames") or []
        ) if approvals else []

        for approval_username in first_approval_usernames:
            approval_user = User.query.filter_by(
                company_code=company_code,
                username=approval_username
            ).first()

            if not approval_user:
                continue

            add_notification(
                (approval_user.last_name or "")
                + (approval_user.first_name or ""),
                "安全チェックリスト承認依頼",
                (
                    f"「{checklist_record.name}」の"
                    "承認をお願いします。"
                ),
                f"/safety/checklist-results/{result.id}",
                company_code=company_code,
                target_username=approval_user.username,
                workflow_context=build_notification_workflow_context(
                    result,
                    "safety",
                    "approval",
                    approval_index=0
                )
            )

        if result.status == "点検完了":
            completion_notify_usernames = set()

            if target_type == "user" and target_username:
                completion_notify_usernames.add(
                    target_username
                )

            if session.get("username"):
                completion_notify_usernames.add(
                    session.get("username")
                )

            for notify_username in completion_notify_usernames:
                notify_user = User.query.filter_by(
                    company_code=company_code,
                    username=notify_username
                ).first()

                if not notify_user:
                    continue

                add_notification(
                    (notify_user.last_name or "") + (notify_user.first_name or ""),
                    "安全チェックリスト完了のお知らせ",
                    (
                        f"「{checklist_record.name}」の"
                        f"チェックが完了しました。"
                    ),
                    f"/safety/checklist-results/{result.id}",
                    company_code=company_code,
                    target_username=notify_user.username
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
        if item.get("item_type") != "check":
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
@limiter.limit(
    "10 per minute",
    methods=["POST"],
    deduct_when=lambda response: (
        request.headers.get("X-DKSS-Validation-Only") != "1"
    )
)
def edit_checklist(index):
    checklist_record = Checklist.query.filter_by(
        id=index,
        company_code=session.get("company_code")
    ).first()

    if not checklist_record:
        return redirect("/master/checklists")

    checklist = checklist_to_dict(checklist_record)

    if checklist.get("fixed_template_code"):
        if request.method == "POST":
            return return_form_errors(
                [("標準の日常点検表は固定様式のため、変更できません。", "")],
                403
            )
        return redirect("/master/checklists")

    if request.method == "POST":
        form_errors = []

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
            form_errors.append((
                "用途が不正です。",
                "target"
            ))

        if (
            has_vehicle_results
            and checklist_record.target != target
        ):
            return return_form_errors(
                [(
                    "車両点検履歴が存在するため、用途は変更できません。",
                    "target"
                )],
                409
            )        
        item_categories = request.form.getlist("item_category")
        item_contents = request.form.getlist("item_content")
        input_types = request.form.getlist("input_type")
        item_types = request.form.getlist("item_type")
        original_item_indexes = request.form.getlist(
            "original_item_index"
        )
        approval_labels = request.form.getlist("approval_label")
        approval_allow_general_list = request.form.getlist("approval_allow_general")
        choices_list = request.form.getlist("choices")
        criteria_list = request.form.getlist("criteria")
        answer_required_list = request.form.getlist("answer_required")
        shaded_list = request.form.getlist("shaded")

        if len(item_types) > 500:
            form_errors.append((
                "チェック項目は500件以内で設定してください。",
                "item_type_0"
            ))

        for i, item_type in enumerate(item_types):
            if item_type not in {
                "check",
                "inspector",
                "approval"
            }:
                form_errors.append((
                    "項目種別が不正です。",
                    f"item_type_{i}"
                ))

        for i, input_type in enumerate(input_types):
            if input_type not in {
                "select",
                "text"
            }:
                form_errors.append((
                    "評価方式が不正です。",
                    f"input_type_{i}"
                ))

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
            form_errors.append((
                "チェック項目のデータが不正です。",
                "item_type_0"
            ))

        if form_errors:
            return return_form_errors(form_errors)

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

        reminder_time = "08:00"

        try:
            reminder_time = parse_time_hhmm(
                request.form.get("reminder_time") or "08:00",
                "未実施通知時刻"
            )
        except UploadValidationError:
            form_errors.append((
                "未実施通知時刻の入力内容を確認してください。",
                "reminder_time"
            ))

        name = request.form.get("name", "").strip()

        if not name:
            form_errors.append((
                "チェックリスト名を入力してください。",
                "name"
            ))
        elif len(name) > 200:
            form_errors.append((
                "チェックリスト名は200文字以内で入力してください。",
                "name"
            ))

        duplicate_checklist = Checklist.query.filter(
            Checklist.company_code == checklist_record.company_code,
            Checklist.name == name,
            Checklist.id != checklist_record.id
        ).first()

        if duplicate_checklist:
            form_errors.append((
                "このチェックリストはすでに登録されています。",
                "name"
            ))

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
                form_errors.append((
                    "頻度は整数で入力してください。",
                    "frequency_value"
                ))
                frequency_number = None

            if frequency_number is not None:
                if frequency_number < 1:
                    form_errors.append((
                        "頻度は1以上で入力してください。",
                        "frequency_value"
                    ))
                elif frequency_number > 9999:
                    form_errors.append((
                        "頻度は9999以下で入力してください。",
                        "frequency_value"
                    ))

            if frequency_unit not in {
                "day",
                "month",
                "year"
            }:
                form_errors.append((
                    "頻度単位が不正です。",
                    "frequency_unit"
                ))

            if display_type not in {
                "month",
                "year"
            }:
                form_errors.append((
                    "表示形式が不正です。",
                    "display_type"
                ))
            
        old_items = checklist.get("items", [])

        old_criteria_files = {
            filename
            for item in old_items
            for filename in item.get(
                "criteria_files",
                []
            )
            if filename
        }

        items = []
        pending_criteria_files = []

        for i in range(len(item_types)):
            item_type = item_types[i]

            if item_type == "inspector":
                items.append({
                    "item_type": "inspector",
                    "content": (
                        str(item_contents[i] or "").strip()
                        if i < len(item_contents)
                        else ""
                    ),
                })
                continue

            if item_type == "approval":
                label = ""

                if i < len(approval_labels):
                    label = approval_labels[i].strip()

                if len(label) > 100:
                    form_errors.append((
                        "承認ラベルは100文字以内で入力してください。",
                        f"approval_label_{i}"
                    ))

                items.append({
                    "item_type": "approval",
                    "approval_label": label,
                    "approval_allow_general": str(i) in approval_allow_general_list,
                    "criteria_files": [],
                })

                continue

            if i >= len(item_contents):
                continue

            if (
                not item_contents[i]
                and input_types[i] != "text"
            ):
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
                form_errors.append((
                    "カテゴリは100文字以内で入力してください。",
                    f"item_category_{i}"
                ))

            if len(content) > 500:
                form_errors.append((
                    "チェック内容は500文字以内で入力してください。",
                    f"item_content_{i}"
                ))

            if len(criteria) > 500:
                form_errors.append((
                    "判定基準は500文字以内で入力してください。",
                    f"criteria_{i}"
                ))

            choices = []

            if input_types[i] == "select":
                choices = [
                    choice.strip()
                    for choice in choices_list[i].split(",")
                    if choice.strip()
                ]

                if not choices:
                    form_errors.append((
                        "選択式のチェック項目には評価の選択肢を1つ以上入力してください。",
                        f"choices_{i}"
                    ))
                elif len(choices) > 100:
                    form_errors.append((
                        "選択肢は100個以内で入力してください。",
                        f"choices_{i}"
                    ))
                elif any(
                    len(choice) > 100
                    for choice in choices
                ):
                    form_errors.append((
                        "各選択肢は100文字以内で入力してください。",
                        f"choices_{i}"
                    ))

            criteria_files = []

            original_item_index = ""

            if i < len(original_item_indexes):
                original_item_index = str(
                    original_item_indexes[i] or ""
                ).strip()

            if original_item_index.isdigit():
                old_index = int(
                    original_item_index
                )

                if 0 <= old_index < len(old_items):
                    criteria_files = list(
                        old_items[old_index].get(
                            "criteria_files",
                            []
                        )
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
                "answer_required": str(i) in answer_required_list,
                "shaded": str(i) in shaded_list,
                "score_enabled": score_enabled,
            })

            pending_criteria_files.append((item_index, i))

        if form_errors:
            return return_form_errors(
                form_errors,
                409 if duplicate_checklist else 400
            )

        pending_uploads = []

        upload_file_count = sum(
            1
            for field_name in request.files.keys()
            for file in request.files.getlist(field_name)
            if file and file.filename
        )

        if upload_file_count > 50:
            return return_form_errors([
                "一度にアップロードできるファイルは50件までです。"
            ])

        if (
            upload_file_count > 0
            and not session.get("company_code")
        ):
            return return_form_errors([
                "company_code is required for file upload."
            ])

        for item_index, form_index in pending_criteria_files:
            for file in request.files.getlist(
                f"criteria_files_{form_index}"
            ):
                if not file or not file.filename:
                    continue

                original_filename = os.path.basename(
                    str(file.filename or "")
                )

                extension = os.path.splitext(
                    original_filename
                )[1].lower()

                if (
                    extension not in ALLOWED_UPLOAD_EXTENSIONS
                    or not is_valid_uploaded_file(
                        file,
                        extension
                    )
                ):
                    return return_form_errors([
                        "添付ファイルの検証に失敗しました。"
                    ])

                pending_uploads.append(
                    (item_index, file)
                )

        create_new_version = request.form.get(
            "create_new_version",
            ""
        )

        if create_new_version not in {"0", "1"}:
            response = app.make_response(("", 409))
            response.headers[
                "X-DKSS-Choose-Checklist-Version"
            ] = "1"
            return response

        for item_index, file in pending_uploads:
            filename = save_uploaded_file(file)

            if filename:
                items[item_index]["criteria_files"].append(filename)

        version_history = safe_json_dict_list(
            checklist_record.version_history_json
        )

        new_checklist_revision = {
            **checklist,
            "name": name,
            "target": target,
            "frequency_value": (
                str(frequency_number)
                if target == "車両管理"
                else ""
            ),
            "frequency_unit": (
                frequency_unit
                if target == "車両管理"
                else ""
            ),
            "display_type": (
                display_type
                if target == "車両管理"
                else ""
            ),
            "print_portrait": (
                print_portrait
                if target == "車両管理"
                else False
            ),
            "print_half_month": (
                print_half_month
                if target == "車両管理"
                else False
            ),
            "items": items,
        }

        if (
            create_new_version == "1"
            and checklist_revision_key(checklist)
            != checklist_revision_key(new_checklist_revision)
        ):
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

        if create_new_version == "0":
            updated_snapshot_json = json.dumps(
                new_checklist_revision,
                ensure_ascii=False
            )

            ChecklistResult.query.filter_by(
                company_code=checklist_record.company_code,
                checklist_id=checklist_record.id
            ).update(
                {
                    "checklist_snapshot_json": updated_snapshot_json
                },
                synchronize_session=False
            )

            VehicleChecklistResult.query.filter_by(
                company_code=checklist_record.company_code,
                checklist_id=checklist_record.id
            ).update(
                {
                    "checklist_snapshot_json": updated_snapshot_json
                },
                synchronize_session=False
            )

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

        new_criteria_files = {
            filename
            for item in items
            for filename in item.get(
                "criteria_files",
                []
            )
            if filename
        }

        removed_criteria_files = (
            old_criteria_files
            - new_criteria_files
        )

        db.session.commit()

        company_code = checklist_record.company_code

        for filename in removed_criteria_files:
            filename = os.path.basename(
                str(filename or "")
            )

            if not filename:
                continue

            still_referenced = False

            for other_checklist in Checklist.query.filter_by(
                company_code=company_code
            ).all():
                other_data = checklist_to_dict(
                    other_checklist
                )

                if any(
                    filename in item.get(
                        "criteria_files",
                        []
                    )
                    for item in other_data.get(
                        "items",
                        []
                    )
                ):
                    still_referenced = True
                    break

                for version in other_data.get(
                    "version_history",
                    []
                ):
                    snapshot = version.get(
                        "snapshot",
                        {}
                    )

                    if any(
                        filename in item.get(
                            "criteria_files",
                            []
                        )
                        for item in snapshot.get(
                            "items",
                            []
                        )
                    ):
                        still_referenced = True
                        break

                if still_referenced:
                    break

            if not still_referenced:
                result_records = ChecklistResult.query.filter_by(
                    company_code=company_code
                ).all()

                for result_record in result_records:
                    answers = safe_json_dict_list(
                        result_record.answers_json
                    )

                    if any(
                        filename in answer.get(
                            "criteria_files",
                            []
                        )
                        for answer in answers
                    ):
                        still_referenced = True
                        break

                    snapshot = safe_json_dict(
                        result_record.checklist_snapshot_json
                    )

                    if any(
                        filename in item.get(
                            "criteria_files",
                            []
                        )
                        for item in snapshot.get(
                            "items",
                            []
                        )
                    ):
                        still_referenced = True
                        break

            if not still_referenced:
                result_records = VehicleChecklistResult.query.filter_by(
                    company_code=company_code
                ).all()

                for result_record in result_records:
                    answers = safe_json_dict_list(
                        result_record.answers_json
                    )

                    if any(
                        filename in answer.get(
                            "criteria_files",
                            []
                        )
                        for answer in answers
                    ):
                        still_referenced = True
                        break

                    snapshot = safe_json_dict(
                        result_record.checklist_snapshot_json
                    )

                    if any(
                        filename in item.get(
                            "criteria_files",
                            []
                        )
                        for item in snapshot.get(
                            "items",
                            []
                        )
                    ):
                        still_referenced = True
                        break

            if still_referenced:
                continue

            if s3_client and S3_BUCKET_NAME:
                try:
                    s3_client.delete_object(
                        Bucket=S3_BUCKET_NAME,
                        Key=(
                            f"uploads/"
                            f"{company_code}/"
                            f"{filename}"
                        )
                    )
                except ClientError:
                    app.logger.warning(
                        "旧評価基準ファイルのS3削除に失敗しました。",
                        exc_info=True
                    )
            else:
                safe_filename = secure_filename(
                    filename
                )

                if safe_filename:
                    file_path = os.path.join(
                        app.config["UPLOAD_FOLDER"],
                        company_code,
                        safe_filename
                    )

                    if os.path.exists(file_path):
                        os.remove(file_path)

        return redirect("/master/checklists")

    checklist_edit_form_data = session.pop(
        "checklist_edit_form_data",
        {}
    )

    retained_checklist = checklist_form_data_to_dict(
        checklist_edit_form_data,
        checklist
    )

    return render_template(
        "checklist_form.html",
        checklist=retained_checklist,
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

    if checklist_to_dict(source).get("fixed_template_code"):
        return return_form_errors(
            [("標準の日常点検表は固定様式のため、複製できません。", "")],
            403
        )

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

    if checklist_to_dict(checklist).get("fixed_template_code"):
        return return_form_errors(
            [("標準の日常点検表は固定様式のため、無効化できません。", "")],
            403
        )

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

    if checklist_to_dict(checklist).get("fixed_template_code"):
        return return_form_errors(
            [("標準の日常点検表は固定様式のため、削除できません。", "")],
            403
        )

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

    files_to_delete = []

    checklist_data = checklist_to_dict(
        checklist
    )

    for item in checklist_data.get(
        "items",
        []
    ):
        files_to_delete.extend(
            item.get(
                "criteria_files",
                []
            )
        )

    company_code = checklist.company_code

    VehicleChecklistNotifySetting.query.filter_by(
        company_code=company_code,
        checklist_id=checklist.id
    ).delete(synchronize_session=False)

    db.session.delete(checklist)
    db.session.commit()

    for filename in files_to_delete:
        filename = os.path.basename(
            str(filename or "")
        )

        if not filename:
            continue

        still_referenced = False

        other_checklists = Checklist.query.filter_by(
            company_code=company_code
        ).all()

        for other_checklist in other_checklists:
            other_data = checklist_to_dict(
                other_checklist
            )

            if any(
                filename in item.get(
                    "criteria_files",
                    []
                )
                for item in other_data.get(
                    "items",
                    []
                )
            ):
                still_referenced = True
                break

            for version in other_data.get(
                "version_history",
                []
            ):
                snapshot = version.get(
                    "snapshot",
                    {}
                )

                if any(
                    filename in item.get(
                        "criteria_files",
                        []
                    )
                    for item in snapshot.get(
                        "items",
                        []
                    )
                ):
                    still_referenced = True
                    break

            if still_referenced:
                break

        if not still_referenced:
            safety_results = ChecklistResult.query.filter_by(
                company_code=company_code
            ).all()

            for result_record in safety_results:
                snapshot = safe_json_dict(
                    result_record.checklist_snapshot_json
                )

                if any(
                    filename in item.get(
                        "criteria_files",
                        []
                    )
                    for item in snapshot.get(
                        "items",
                        []
                    )
                ):
                    still_referenced = True
                    break

        if not still_referenced:
            vehicle_results = VehicleChecklistResult.query.filter_by(
                company_code=company_code
            ).all()

            for result_record in vehicle_results:
                snapshot = safe_json_dict(
                    result_record.checklist_snapshot_json
                )

                if any(
                    filename in item.get(
                        "criteria_files",
                        []
                    )
                    for item in snapshot.get(
                        "items",
                        []
                    )
                ):
                    still_referenced = True
                    break

        if still_referenced:
            continue

        if s3_client and S3_BUCKET_NAME:
            try:
                s3_client.delete_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=(
                        f"uploads/"
                        f"{company_code}/"
                        f"{filename}"
                    )
                )
            except ClientError:
                app.logger.warning(
                    "チェックリスト評価基準添付のS3削除に失敗しました。",
                    exc_info=True
                )
        else:
            safe_filename = secure_filename(
                filename
            )

            if not safe_filename:
                continue

            file_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                company_code,
                safe_filename
            )

            if os.path.exists(file_path):
                os.remove(file_path)

    return redirect("/master/checklists")


@app.route(
    "/safety/checklist-results/<int:result_index>/approve/<int:approval_index>",
    methods=["POST"]
)
@limiter.limit("20 per minute")
def approve_checklist_result(result_index, approval_index):
    result_record = (
        ChecklistResult.query
        .filter_by(
            id=result_index,
            company_code=session.get("company_code")
        )
        .with_for_update()
        .first()
    )

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
                "candidate_usernames": [],
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

    current_approval_index = next(
        (
            index
            for index, item in enumerate(approvals)
            if not (
                item.get("approved_by")
                or item.get("approved_by_username")
            )
        ),
        None
    )

    if approval_index != current_approval_index:
        return redirect(
            f"/safety/checklist-results/{result_index}"
        )

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
        return redirect(
            f"/safety/checklist-results/{result_index}"
        )

    if not can_approve_checklist_result(result, approval):
        return redirect(f"/safety/checklist-results/{result_index}")

    approval["approved_by"] = session.get("name")
    approval["approved_by_username"] = session.get("username")    
    approval["approved_date"] = get_user_local_now(
        result_record.company_code,
        session.get("username")
    ).strftime("%Y-%m-%d %H:%M")

    result_record.approvals_json = json.dumps(
        approvals,
        ensure_ascii=False
    )

    result_record.reject_reason = ""

    all_approved = all(
        (
            item.get("approved_by")
            or item.get("approved_by_username")
        )
        for item in approvals
    )

    if approvals and all_approved:
        result_record.status = "承認済み"
        result_record.approved_by = session.get("name")
        result_record.approved_by_username = session.get("username")        
        result_record.approved_date = get_user_local_now(
            result_record.company_code,
            session.get("username")
        ).strftime("%Y-%m-%d %H:%M")
    else:
        result_record.status = "承認待ち"
        result_record.approved_by = ""
        result_record.approved_by_username = ""
        result_record.approved_date = ""

    checklist_event = ChecklistEvent(
        company_code=result_record.company_code,
        result_type="safety",
        result_id=result_record.id,
        event_type="承認",
        actor_username=session.get("username"),
        actor_name=session.get("name"),
        detail_json=json.dumps(
            {
                "approval_index": approval_index,
                "approval": dict(approval),
                "all_approved": all_approved,
            },
            ensure_ascii=False
        ),
        created_at=datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    db.session.add(checklist_event)

    db.session.commit()

    if result_record.status != "承認済み":
        next_approval_index, next_approval = next(
            (
                (index, item)
                for index, item in enumerate(
                    approvals[approval_index + 1:],
                    start=approval_index + 1
                )
                if not (
                    item.get("approved_by")
                    or item.get("approved_by_username")
                )
            ),
            (None, None)
        )

        for target_username in (
            next_approval.get(
                "candidate_usernames",
                []
            )
            if next_approval
            else []
        ):
            target_user = User.query.filter_by(
                company_code=result_record.company_code,
                username=target_username
            ).first()

            if not target_user:
                continue

            add_notification(
                (target_user.last_name or "")
                + (target_user.first_name or ""),
                "安全チェックリスト承認依頼",
                "次の承認をお願いします。",
                f"/safety/checklist-results/{result_record.id}",
                company_code=result_record.company_code,
                target_username=target_user.username,
                workflow_context=build_notification_workflow_context(
                    result_record,
                    "safety",
                    "approval",
                    approval_index=next_approval_index
                )
            )

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
                (target_user.last_name or "") + (target_user.first_name or ""),
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
    result_record = (
        ChecklistResult.query
        .filter_by(
            id=result_index,
            company_code=session.get("company_code")
        )
        .with_for_update()
        .first()
    )

    if not result_record:
        return redirect("/safety/checklists")

    if result_record.status != "承認待ち":
        return redirect(
            f"/safety/checklist-results/{result_index}"
        )

    result = checklist_result_to_dict(result_record)

    approvals = safe_json_dict_list(
        result_record.approvals_json
    )

    if not approvals:
        checklist = safe_json_dict(
            result_record.checklist_snapshot_json
        )

        if not checklist:
            checklist_record = Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                checklist = checklist_to_dict(
                    checklist_record
                )

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get(
                    "approval_allow_general",
                    False
                ),
                "candidate_usernames": [],
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

    current_approval_index = next(
        (
            index
            for index, approval in enumerate(approvals)
            if not (
                approval.get("approved_by")
                or approval.get("approved_by_username")
            )
        ),
        None
    )

    current_approval = (
        approvals[current_approval_index]
        if current_approval_index is not None
        else None
    )

    if (
        current_approval is not None
        and "allow_general" not in current_approval
    ):
        checklist = safe_json_dict(
            result_record.checklist_snapshot_json
        )

        if not checklist:
            checklist_record = Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                checklist = checklist_to_dict(
                    checklist_record
                )

        approval_items = [
            item
            for item in checklist.get("items", [])
            if item.get("item_type") == "approval"
        ]

        if current_approval_index < len(approval_items):
            current_approval["allow_general"] = approval_items[
                current_approval_index
            ].get(
                "approval_allow_general",
                False
            )

    if not can_reject_checklist_result(
        result,
        current_approval
    ):
        return redirect(
            f"/safety/checklist-results/{result_index}"
        )

    reject_reason = request.form.get(
        "reject_reason",
        ""
    ).strip()

    form_errors = []

    if not reject_reason:
        form_errors.append(
            (
                "差し戻し理由を入力してください。",
                "reject_reason"
            )
        )

    elif len(reject_reason) > 5000:
        form_errors.append(
            (
                "差し戻し理由は5000文字以内で入力してください。",
                "reject_reason"
            )
        )

    if form_errors:
        return return_form_errors(form_errors)

    previous_approvals = [
        dict(approval)
        for approval in approvals
    ]

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

    checklist_event = ChecklistEvent(
        company_code=result_record.company_code,
        result_type="safety",
        result_id=result_record.id,
        event_type="差し戻し",
        actor_username=session.get("username"),
        actor_name=session.get("name"),
        detail_json=json.dumps(
            {
                "reject_reason": reject_reason,
                "approval_label": (
                    current_approval.get("label", "")
                    if current_approval
                    else ""
                ),
                "previous_approvals": previous_approvals,
            },
            ensure_ascii=False
        ),
        created_at=datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    db.session.add(checklist_event)

    notify_usernames = set()

    if result_record.checked_by_username:
        notify_usernames.add(
            result_record.checked_by_username
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
            (target_user.last_name or "") + (target_user.first_name or ""),
            "チェックリストが差し戻されました",
            reject_reason or "チェックリストが差し戻されました。",
            f"/safety/checklist-results/{result_record.id}",
            company_code=result_record.company_code,
            target_username=target_user.username,
            workflow_context=build_notification_workflow_context(
                result_record,
                "safety",
                "correction"
            )
        )

    return redirect(f"/safety/checklist-results/{result_record.id}")

def init_db():
    with app.app_context():
        db.create_all()

        inspector = inspect(db.engine)

        existing_user_columns = [
            column["name"]
            for column in inspector.get_columns("user")
        ]

        if "last_name" not in existing_user_columns:
            if "name" in existing_user_columns:
                db.session.execute(
                    db.text(
                        'ALTER TABLE "user" '
                        'RENAME COLUMN name TO last_name'
                    )
                )
            else:
                db.session.execute(
                    db.text(
                        'ALTER TABLE "user" '
                        'ADD COLUMN last_name VARCHAR(100)'
                    )
                )

            db.session.commit()
            inspector = inspect(db.engine)

        existing_user_columns = [
            column["name"]
            for column in inspector.get_columns("user")
        ]

        if "first_name" not in existing_user_columns:
            db.session.execute(
                db.text(
                    'ALTER TABLE "user" '
                    'ADD COLUMN first_name VARCHAR(100)'
                )
            )
            db.session.commit()

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
                last_name="ITC管理者",
                first_name=None,
                office="ITC",
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

        duplicate_vehicle_checklist_result = (
            db.session.query(
                VehicleChecklistResult.company_code,
                VehicleChecklistResult.checklist_id,
                VehicleChecklistResult.vehicle_record_id,
                VehicleChecklistResult.year,
                VehicleChecklistResult.month,
                VehicleChecklistResult.day
            )
            .group_by(
                VehicleChecklistResult.company_code,
                VehicleChecklistResult.checklist_id,
                VehicleChecklistResult.vehicle_record_id,
                VehicleChecklistResult.year,
                VehicleChecklistResult.month,
                VehicleChecklistResult.day
            )
            .having(
                db.func.count(VehicleChecklistResult.id) > 1
            )
            .first()
        )

        if duplicate_vehicle_checklist_result:
            raise RuntimeError(
                "車両チェックリスト結果に同一会社・チェックリスト・"
                "車両・点検日の重複があります。"
            )

        db.session.execute(
            db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_vehicle_checklist_result_target_date "
                "ON vehicle_checklist_result "
                "(company_code, checklist_id, vehicle_record_id, "
                "year, month, day)"
            )
        )

        db.session.commit()

init_db()

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
            "VARCHAR(5) NOT NULL DEFAULT '08:00'"
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
        ("notify_users_json", "TEXT"),
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

        matched_users = User.query.filter(
            User.company_code == checklist_result.company_code,
            (
                User.last_name
                + db.func.coalesce(User.first_name, "")
            ) == checked_by_name
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

        matched_users = User.query.filter(
            User.company_code == checklist_result.company_code,
            (
                User.last_name
                + db.func.coalesce(User.first_name, "")
            ) == target_name
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

        matched_users = User.query.filter(
            User.company_code == checklist_result.company_code,
            (
                User.last_name
                + db.func.coalesce(User.first_name, "")
            ) == approved_by_name
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

            matched_users = User.query.filter(
                User.company_code == checklist_result.company_code,
                (
                    User.last_name
                    + db.func.coalesce(User.first_name, "")
                ) == approved_by_name
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
        ("operation_judgment_json", "TEXT"),
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

        matched_users = User.query.filter(
            User.company_code == result.company_code,
            (
                User.last_name
                + db.func.coalesce(User.first_name, "")
            ) == checked_by_name
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

        matched_users = User.query.filter(
            User.company_code == result.company_code,
            (
                User.last_name
                + db.func.coalesce(User.first_name, "")
            ) == approved_by_name
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

            matched_users = User.query.filter(
                User.company_code == result.company_code,
                (
                    User.last_name
                    + db.func.coalesce(User.first_name, "")
                ) == approved_by_name
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
            "first_name",
            "VARCHAR(100)"
        ),
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
        (
            "profile_image",
            "VARCHAR(255)"
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
        ("deleted_at", "TIMESTAMP"),
        ("workflow_context_json", "TEXT DEFAULT '{}'"),
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

    if (
        "countermeasure_files_json"
        not in existing_patrol_result_columns
    ):
        db.session.execute(
            db.text(
                "ALTER TABLE patrol_result "
                "ADD COLUMN countermeasure_files_json TEXT"
            )
        )

        db.session.commit()

    if (
        "countermeasure_due_date"
        not in existing_patrol_result_columns
    ):
        db.session.execute(
            db.text(
                "ALTER TABLE patrol_result "
                "ADD COLUMN countermeasure_due_date VARCHAR(20)"
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

        matched_users = User.query.filter(
            User.company_code == notification.company_code,
            (
                User.last_name
                + db.func.coalesce(User.first_name, "")
            ) == target_name
        ).all()

        if len(matched_users) != 1:
            continue

        notification.target_username = (
            matched_users[0].username
        )

    db.session.commit()


if __name__ == "__main__":
    app.run(debug=False)