"""Hatch application factory. Importing the package does not create an app or touch a DB."""
from pathlib import Path
from datetime import timedelta
import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from .extensions import db, csrf, limiter

ROOT = Path(__file__).resolve().parent.parent


def create_app(config=None, *, initialize_database=False):
    app = Flask("app", root_path=str(ROOT), instance_path=str(ROOT / "instance"))
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    production = os.environ.get("RENDER") == "true"
    values = {
        "SECRET_KEY": os.environ.get("SECRET_KEY"),
        "SQLALCHEMY_DATABASE_URI": os.environ.get("DATABASE_URL") or "sqlite:///dkss.db",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "RATELIMIT_STORAGE_URI": os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
        "MFA_ENABLED": os.environ.get("MFA_ENABLED", "true").lower() == "true",
        "VAPID_PRIVATE_KEY": os.environ.get("VAPID_PRIVATE_KEY", ""),
        "VAPID_PUBLIC_KEY": os.environ.get("VAPID_PUBLIC_KEY", ""),
        "VAPID_SUBJECT": os.environ.get("VAPID_SUBJECT", "mailto:maho_shiokawa@isz.co.jp"),
        "S3_BUCKET_NAME": os.environ.get("S3_BUCKET_NAME", ""),
        "AWS_REGION": os.environ.get("AWS_REGION", "ap-northeast-1"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "SESSION_COOKIE_NAME": "__Host-dkss_session" if production else "dkss_session",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": production,
        "SESSION_COOKIE_PATH": "/",
        "SESSION_COOKIE_DOMAIN": None,
        "PERMANENT_SESSION_LIFETIME": timedelta(minutes=30),
        "SESSION_REFRESH_EACH_REQUEST": True,
        "MAX_CONTENT_LENGTH": 1024 * 1024 * 1024,
        "UPLOAD_FOLDER": "static/uploads",
    }
    if config:
        values.update(config)
    if not values["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY environment variable is required")
    if production and values["RATELIMIT_STORAGE_URI"] == "memory://":
        raise RuntimeError("本番環境では共有RATELIMIT_STORAGE_URIが必要です。")
    if production and not values["DATABASE_URL"] and not (config and config.get("SQLALCHEMY_DATABASE_URI")):
        raise RuntimeError("本番環境ではDATABASE_URLが必要です。")
    app.config.update(values)
    from .display import format_distance_km
    app.jinja_env.filters["distance_km"] = format_distance_km
    db.init_app(app)
    from . import account_identity
    from . import import_owner
    app.after_request(import_owner.private_response)
    csrf.init_app(app)
    limiter.init_app(app)
    app.extensions["dkss"] = {"s3_client": None}
    if values["S3_BUCKET_NAME"]:
        import boto3
        app.extensions["dkss"]["s3_client"] = boto3.client(
            "s3", region_name=values["AWS_REGION"],
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"))

    from .routes import register_core_routes
    from .integrations import register_integrations
    register_core_routes(app)
    register_integrations(app)
    from .public_assets import install as install_public_assets
    install_public_assets(app)

    @app.cli.command("init-db")
    def init_database_command():
        """Apply existing compatibility migrations and bootstrap explicitly."""
        from .database import initialize_database as initialize
        initialize()
        from .document_sources import upgrade_storage
        from .analysis_read_cache import upgrade_read_cache
        upgrade_storage()
        upgrade_read_cache()
        print("DATABASE_INITIALIZED")

    @app.cli.command("upgrade-account-identity")
    def upgrade_account_identity_command():
        """Add account-generation columns; quarantine ambiguous old ownership."""
        account_identity.upgrade_account_identity()
        print("ACCOUNT_IDENTITY_UPGRADED")

    @app.cli.command("init-checklist-notify-identities")
    def init_checklist_notify_identities():
        """Create reminder assignment evidence without inferring old owners."""
        from .checklist_notify_identity import initialize_notify_identities
        initialize_notify_identities()
        print("CHECKLIST_NOTIFY_IDENTITIES_INITIALIZED")

    @app.cli.command("upgrade-domain-storage")
    def upgrade_domain_storage():
        from .document_sources import upgrade_storage
        from .analysis_read_cache import upgrade_read_cache

        upgrade_storage()
        upgrade_read_cache()
        print("DOMAIN_STORAGE_UPGRADED")


    @app.cli.command("clear-analysis-read-cache")
    def clear_analysis_read_cache():
        from .models import AnalysisInputReadCache

        with db.engine.begin() as connection:
            connection.execute(AnalysisInputReadCache.__table__.delete())
        print("ANALYSIS_READ_CACHE_CLEARED")


    @app.cli.command("compact-document-sources")
    def compact_document_sources():
        from .document_sources import compact_sources

        print("DOCUMENT_SOURCES_COMPACTED", compact_sources())


    @app.cli.command("restore-inline-document-sources")
    def restore_inline_document_sources():
        from .document_sources import restore_inline_sources

        print("DOCUMENT_SOURCES_RESTORED", restore_inline_sources())


    @app.cli.command("document-import-worker")
    def document_import_worker_command():
        import signal
        import threading
        from .document_import_worker import run_worker

        stopped = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stopped.set())
        run_worker(app, stopped)

    if initialize_database:
        with app.app_context():
            from .database import initialize_database as initialize
            initialize()
    return app
