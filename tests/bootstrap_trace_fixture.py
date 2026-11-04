"""Synthetic-only initialization fixture. Never accepts an external DB target."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

SOURCE_SHA = "008ed6e41352a852828f10193972e6e415f9a20e"
ADMIN_DB = "dkss_trace_ci"
ADMIN_LOGIN = "trace_ci"
ADMIN_PASSWORD = "trace-admin-disposable-only"
APP_LOGIN = "trace_ci_app"
APP_PASSWORD = "trace-app-disposable-only"
MARKER = "DKSS_TRACE_SYNTHETIC_ONLY"
OPTIONS = "-c search_path=public -c statement_timeout=30000 -c lock_timeout=3000"


def check_source(root):
    manifest = json.loads((Path(__file__).with_name("bootstrap_trace_source_files.json")).read_text())
    if manifest["source_sha"] != SOURCE_SHA:
        raise RuntimeError("PINNED_SOURCE_SHA_MISMATCH")
    for name, expected in manifest["files"].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError("PINNED_APPLICATION_SOURCE_CHANGED")
    return len(manifest["files"])


def allowed_indexes():
    manifest = json.loads(Path(__file__).with_name("bootstrap_trace_indexes.json").read_text())
    if manifest["source_sha"] != SOURCE_SHA or len(manifest["indexes"]) != 99:
        raise RuntimeError("INDEX_MANIFEST_CHANGED")
    return frozenset((row["name"], row["table"]) for row in manifest["indexes"])


def validate_service_url(value, environment):
    from sqlalchemy.engine import make_url
    if environment.get("GITHUB_ACTIONS") != "true" or environment.get("GITHUB_REPOSITORY") != "oxo-ops/dkss":
        raise RuntimeError("OWNED_GITHUB_SERVICE_REQUIRED")
    url = make_url(value)
    if (url.drivername != "postgresql+psycopg2" or url.host != "127.0.0.1"
            or url.database != ADMIN_DB or url.username != ADMIN_LOGIN
            or url.password != ADMIN_PASSWORD or url.query
            or type(url.port) is not int or not 1 <= url.port <= 65535):
        raise RuntimeError("ONLY_SYNTHETIC_LOOPBACK_SERVICE_ALLOWED")
    return url


def tls_url(url, ca):
    ca = Path(ca).resolve(strict=True)
    if not ca.is_file() or ca.stat().st_size > 65536 or b"-----BEGIN CERTIFICATE-----" not in ca.read_bytes():
        raise RuntimeError("JOB_CERTIFICATE_REQUIRED")
    return url.update_query_dict({"hostaddr": "127.0.0.1", "sslmode": "verify-full",
        "sslrootcert": str(ca), "connect_timeout": "10", "passfile": os.devnull,
        "options": OPTIONS, "application_name": "dkss-synthetic-trace-ci"})


def owned_database_name(value):
    if not re.fullmatch(r"trace_owned_[0-9a-f]{32}", value):
        raise RuntimeError("INVALID_SYNTHETIC_DATABASE_NAME")
    return value


@contextlib.contextmanager
def isolated_environment(password):
    original = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="dkss-trace-ci-") as home:
        safe = {key: original[key] for key in ("PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in original}
        safe.update(HOME=home, USERPROFILE=home, LANG="C.UTF-8", TZ="UTC", PYTHONDONTWRITEBYTECODE="1",
            FLASK_SKIP_DOTENV="1", ITC_INITIAL_PASSWORD=password, SECRET_KEY=secrets.token_urlsafe(40), RENDER="", DATABASE_URL="",
            AWS_EC2_METADATA_DISABLED="true", AWS_CONFIG_FILE=os.devnull,
            AWS_SHARED_CREDENTIALS_FILE=os.devnull, S3_BUCKET_NAME="", OPENAI_API_KEY="",
            SMTP_HOST="", VAPID_PRIVATE_KEY="", VAPID_PUBLIC_KEY="", VAPID_SUBJECT="mailto:ci@example.invalid",
            DOCUMENT_IMPORT_WORKER_ENABLED="0", RATELIMIT_STORAGE_URI="memory://")
        os.environ.clear()
        os.environ.update(safe)
        try:
            yield dict(safe)
        finally:
            os.environ.clear()
            os.environ.update(original)


def make_app(url):
    from dkss_app import create_app
    return create_app({"SQLALCHEMY_DATABASE_URI": url,
        "SECRET_KEY": secrets.token_urlsafe(40), "TESTING": True}, initialize_database=False)


def official_cli(app):
    from flask.cli import ScriptInfo
    app.cli.main(args=["init-db"], standalone_mode=False,
        obj=ScriptInfo(create_app=lambda: app, set_debug_flag=False))
