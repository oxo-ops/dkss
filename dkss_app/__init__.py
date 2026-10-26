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

    @app.cli.command("init-db")
    def init_database_command():
        """Apply existing compatibility migrations and bootstrap explicitly."""
        from .database import initialize_database as initialize
        initialize()
        print("DATABASE_INITIALIZED")

    if initialize_database:
        with app.app_context():
            from .database import initialize_database as initialize
            initialize()
    return app
