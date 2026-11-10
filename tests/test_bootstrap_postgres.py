"""Opt-in acceptance against the marked GitHub Actions PostgreSQL service only."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from bootstrap_postgres_checks import boundary_test, verify_full_bootstrap

ROOT = Path(__file__).resolve().parents[1]
MARKER = "DKSS_BOOTSTRAP_SYNTHETIC_ONLY"


def validate_service_url(value, environment):
    if environment.get("GITHUB_ACTIONS") != "true" or environment.get("GITHUB_REPOSITORY") != "oxo-ops/dkss":
        raise RuntimeError("Only the explicitly provisioned GitHub Actions service is allowed")
    url = make_url(value)
    if (url.drivername != "postgresql+psycopg2" or url.host != "127.0.0.1"
            or url.database != "dkss_bootstrap_ci" or url.username != "bootstrap_ci"
            or url.password != "bootstrap-disposable-ci-only" or url.query
            or url.port is None or not 1 <= url.port <= 65535):
        raise RuntimeError("Refusing anything except the dedicated loopback bootstrap service")
    return url


class ServiceGuardTests(unittest.TestCase):
    def setUp(self):
        self.env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "oxo-ops/dkss"}
        self.url = "postgresql+psycopg2://bootstrap_ci:bootstrap-disposable-ci-only@127.0.0.1:5432/dkss_bootstrap_ci"

    def test_only_dedicated_service_configuration_is_accepted(self):
        self.assertEqual(validate_service_url(self.url, self.env).database, "dkss_bootstrap_ci")

    def test_external_host_existing_database_credentials_and_query_overrides_are_rejected(self):
        for value in (self.url.replace("127.0.0.1", "db.example.invalid"),
                      self.url.replace("dkss_bootstrap_ci", "production"),
                      self.url.replace("bootstrap_ci:", "real_user:"),
                      self.url.replace("bootstrap-disposable-ci-only", "other"),
                      self.url + "?host=db.example.invalid", self.url.replace(":5432", "")):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                validate_service_url(value, self.env)

    def test_local_environment_and_wrong_repository_are_rejected(self):
        for env in ({}, {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "other/repo"}):
            with self.assertRaises(RuntimeError):
                validate_service_url(self.url, env)


class PostgreSQLBootstrapAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("DKSS_BOOTSTRAP_REQUIRE_POSTGRES") != "1":
            raise unittest.SkipTest("Explicit isolated bootstrap service required")
        cls.url = validate_service_url(os.environ.get("DKSS_BOOTSTRAP_POSTGRES_URL", ""), os.environ)
        cls.admin = create_engine(cls.url, isolation_level="AUTOCOMMIT",
                                  connect_args={"hostaddr": "127.0.0.1", "connect_timeout": 5,
                                                "options": "-cstatement_timeout=30000 -clock_timeout=10000"})
        cls.addClassCleanup(cls.admin.dispose)
        with cls.admin.connect() as connection:
            marker = connection.scalar(text("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()"))
            if marker != MARKER:
                raise RuntimeError("Refusing an unmarked database: service ownership not established")
            if connection.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")) != 0:
                raise RuntimeError("The marker database must remain empty")
            print("POSTGRES_BOOTSTRAP_VERSION", connection.scalar(text("SHOW server_version")), flush=True)

    def setUp(self):
        self.database = "bootstrap_owned_" + uuid4().hex
        with self.admin.connect() as connection:
            # Name is locally generated lowercase hex, never user-supplied SQL.
            connection.exec_driver_sql('CREATE DATABASE "' + self.database + '" TEMPLATE template0')
        # Service container teardown owns all temporary databases. Avoid any
        # cross-session DROP/termination behavior in this acceptance test.
        self.url_value = self.url.set(database=self.database).render_as_string(hide_password=False)
        self.temp = tempfile.TemporaryDirectory(prefix="dkss-bootstrap-assets-")
        self.addCleanup(self.temp.cleanup)
        self.password = secrets.token_urlsafe(32)
        self.env = {"PATH": os.defpath, "HOME": self.temp.name, "LANG": "C.UTF-8", "TZ": "UTC",
                    "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1", "FLASK_SKIP_DOTENV": "1",
                    "DATABASE_URL": self.url_value, "SECRET_KEY": secrets.token_urlsafe(40),
                    "ITC_INITIAL_PASSWORD": self.password, "RENDER": "", "RATELIMIT_STORAGE_URI": "memory://",
                    "AWS_EC2_METADATA_DISABLED": "true", "AWS_CONFIG_FILE": os.devnull,
                    "AWS_SHARED_CREDENTIALS_FILE": os.devnull, "S3_BUCKET_NAME": "", "OPENAI_API_KEY": "",
                    "SMTP_HOST": "", "VAPID_PRIVATE_KEY": "", "VAPID_PUBLIC_KEY": "",
                    "DOCUMENT_IMPORT_WORKER_ENABLED": "0"}

    def test_normal_formal_cli_completes_and_creates_schema_extras_and_administrator(self):
        result = subprocess.run([sys.executable, "-m", "flask", "--app", "app", "init-db"],
                                cwd=ROOT, env=self.env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180)
        output = result.stdout + result.stderr
        for secret in (self.url_value, self.password, self.env["SECRET_KEY"]):
            output = output.replace(secret, "<synthetic-value-redacted>")
        artifacts = ROOT / "bootstrap-evidence"
        artifacts.mkdir(exist_ok=True)
        (artifacts / "formal-cli.log").write_text(output, encoding="utf-8")
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("DATABASE_INITIALIZED", result.stdout)
        evidence = verify_full_bootstrap(self.url_value, self.env, self.password)
        (artifacts / "formal-verification.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print("POSTGRES_FORMAL_INIT_VERIFIED", json.dumps(evidence), flush=True)

    def test_candidate_boundary_avoids_second_physical_connection(self):
        evidence = boundary_test(self.url_value, self.env)
        self.assertEqual(evidence["physical_connection_attempts"], 1)
        self.assertFalse(evidence["injection_fired"])
        print("POSTGRES_CANDIDATE_BOUNDARY", json.dumps(evidence), flush=True)

    def test_former_session_held_boundary_exercises_injected_failure(self):
        evidence = boundary_test(self.url_value, self.env, control=True)
        self.assertTrue(evidence["injection_fired"])
        print("POSTGRES_OLD_BOUNDARY_CONTROL", json.dumps(evidence), flush=True)


if __name__ == "__main__":
    unittest.main()
