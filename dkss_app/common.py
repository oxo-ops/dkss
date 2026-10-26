"""Shared imports and immutable values. Importing this module performs no DB work."""
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
from vehicle_analysis_dates import parse_record_date
from vehicle_analysis_repository import VehicleAnalysisInputRepository, VehicleAnalysisJobRepository
from vehicle_analysis_summary import VehicleAnalysisSummaryService
from vehicle_analysis_service import (
    AnalysisComparisonSettings, VehicleAnalysisInputService,
    VehicleAnalysisQueueService, VehicleAnalysisJobService,
)
from daily_inspection_defaults import get_daily_inspection_default
from upload_validation import UploadValidationError
from vehicle_operation_csv import (
    normalize_vehicle_operation_plate,
    parse_vehicle_operation_csv_row,
    read_vehicle_operation_csv,
    parse_vehicle_operation_date,
    parse_vehicle_operation_decimal,
)
from vehicle_karte_analysis_ai import analyze_vehicle_karte
from maintenance_invoice_ai import (
    extract_maintenance_invoices,
    build_maintenance_invoice_preview,
    prepare_maintenance_invoice_pdf,
)
from inspection_document_ai import (
    extract_inspection_documents,
    build_inspection_preview,
    ITEM_FIELDS,
)
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
import hashlib
from decimal import Decimal, InvalidOperation
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import NotFound, HTTPException
from werkzeug.routing import BuildError
from botocore.exceptions import ClientError
from flask_limiter.util import get_remote_address
from sqlalchemy import case, inspect, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.drawing.image import Image as ExcelImage
from io import BytesIO
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode

from flask_wtf.csrf import CSRFError
from .extensions import db, csrf, limiter, SQLAlchemy, CSRFProtect, Limiter

MAINTENANCE_KNOWLEDGE_KINDS = ("整備士の知識", "社内基準", "メーカー公式資料")

UPLOAD_FOLDER = "static/uploads"

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

PATROL_VIEW_TYPES = {"user", "delivery_place"}

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
    "inspection_plan": "点検予定・実施確認",
    "periodic_issue": "点検簿の対応確認",
    "approved": "承認完了",
    "completed": "点検完了",
    "notice": "お知らせ",
    "vehicle_approvals": "点検結果・承認待ち",
    "vehicle_response": "運行判断・不具合対応",
}

VEHICLE_MAINTENANCE_ATTRIBUTE_FIELDS = (('engine_code', '\u30a8\u30f3\u30b8\u30f3\u578b\u5f0f', 100),)


from werkzeug.exceptions import Forbidden


from driving_report_ai import (extract_driving_reports, build_driving_report_preview,
    TEXT_FIELDS as DRIVING_TEXT_FIELDS, ITEM_FIELDS as DRIVING_ITEM_FIELDS, COLLECTIONS as DRIVING_COLLECTIONS)
