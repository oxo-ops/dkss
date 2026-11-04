"""Opt-in disposable PostgreSQL TLS acceptance; no external target is allowed."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, event, text
from bootstrap_trace_fixture import (ADMIN_DB, ADMIN_LOGIN, APP_LOGIN, APP_PASSWORD, MARKER,
    allowed_indexes, isolated_environment, make_app, official_cli, owned_database_name,
    tls_url, validate_service_url)
from bootstrap_trace_guard import guard_empty
from bootstrap_trace_observer import StatementTrace


class PostgreSQLTraceAcceptance(unittest.TestCase):
    def save_evidence(self,result,password,url):
        encoded=json.dumps(result,indent=2)
        for secret in (password,APP_PASSWORD,url.render_as_string(hide_password=False)):
            self.assertNotIn(secret,encoded)
        destination=Path("bootstrap-trace-evidence")
        destination.mkdir(exist_ok=True)
        partial=destination/"synthetic-tls-inprocess-result.partial"
        partial.write_text(encoded+"\n",encoding="utf-8")
        partial.replace(destination/"synthetic-tls-inprocess-result.json")

    @classmethod
    def setUpClass(cls):
        cls.base=validate_service_url(os.environ.get("DKSS_TRACE_POSTGRES_URL",""),os.environ)
        cls.ca=os.environ.get("DKSS_TRACE_CA","")
        cls.admin=create_engine(tls_url(cls.base,cls.ca),isolation_level="AUTOCOMMIT")
        cls.addClassCleanup(cls.admin.dispose)
        with cls.admin.connect() as connection:
            marker=connection.scalar(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"))
            if marker != MARKER:
                raise RuntimeError("SERVICE_OWNERSHIP_MARKER_REQUIRED")
            if connection.scalar(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'")) != 0:
                raise RuntimeError("MARKER_DATABASE_MUST_REMAIN_EMPTY")
            if not connection.scalar(text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")):
                raise RuntimeError("TLS_REQUIRED")
            if not 180000 <= int(connection.scalar(text("SHOW server_version_num"))) < 190000:
                raise RuntimeError("POSTGRESQL_18_REQUIRED")
            print("SYNTHETIC_SERVER_VERSION",connection.scalar(text("SHOW server_version")),flush=True)
            if connection.scalar(text("SELECT count(*) FROM pg_roles WHERE rolname=:role"),{"role":APP_LOGIN}) != 0:
                raise RuntimeError("SYNTHETIC_APP_ROLE_MUST_NOT_PREEXIST")
            # Only a fresh marked loopback fixture is reachable here. No user credentials.
            connection.exec_driver_sql("CREATE ROLE trace_ci_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %s",(APP_PASSWORD,))

    def test_tls_guard_inprocess_cli_and_exact_observer_complete(self):
        from dkss_app.extensions import db
        from bootstrap_postgres_checks import verify_full_bootstrap
        name=owned_database_name("trace_owned_"+uuid4().hex)
        with self.admin.connect() as connection:
            connection.exec_driver_sql('CREATE DATABASE "'+name+'" OWNER trace_ci_app TEMPLATE template0')
        url=tls_url(self.base.set(database=name,username=APP_LOGIN,password=APP_PASSWORD),self.ca)
        password="synthetic-admin-"+uuid4().hex
        result={}; calls=[]
        with isolated_environment(password) as environment:
            app=make_app(url)
            with app.app_context():
                engine=db.engine
                def validate_connect(dialect,record,args,kwargs):
                    if kwargs.get("hostaddr") != "127.0.0.1" or kwargs.get("dbname") != name or kwargs.get("user") != APP_LOGIN:
                        raise RuntimeError("CONNECTION_ESCAPED_SYNTHETIC_FIXTURE")
                    if kwargs.get("sslmode") != "verify-full":
                        raise RuntimeError("VERIFY_FULL_REQUIRED")
                    calls.append(1)
                event.listen(engine,"do_connect",validate_connect)
                trace=StatementTrace(engine,db.metadata,allowed_indexes(),result)
                output=io.StringIO()
                try:
                    guard_empty(engine,name,APP_LOGIN,result)
                    # This is the same official in-process invocation as the launcher,
                    # with synthetic fixture identity and no owner-email update.
                    with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
                        official_cli(app)
                    self.assertIn("DATABASE_INITIALIZED",output.getvalue())
                    result["formal_init_completed"]=True
                    with engine.connect() as connection:
                        role=connection.execute(text("SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user")).one()
                        self.assertEqual(tuple(role),(False,False,False))
                        self.assertEqual(connection.scalar(text("SHOW statement_timeout")),"30s")
                        self.assertEqual(connection.scalar(text("SHOW lock_timeout")),"3s")
                        self.assertEqual(connection.scalar(text("SHOW search_path")),"public")
                        connection.rollback()
                    state=result["statement_trace"]
                    self.assertIsNone(state["failed_operation"])
                    self.assertFalse(state["trace_incomplete"])
                    self.assertEqual(state["counters"]["CREATE_INDEX"],99)
                    self.assertEqual(state["physical_connection_count"],len(calls))
                    self.assertTrue(all(r["cached_connection_parameters"].get("sslmode")=="verify-full"
                        for r in state["cached_connection_observations"]))
                    self.assertTrue(all(r["dbapi_async_mode"] is False for r in state["cached_connection_observations"]))
                    self.assertFalse(state["driver_versions"]["wait_callback_installed"])
                finally:
                    # Preserve the bounded trace even if the CLI/verification failed.
                    # Artifact IO must not replace the original exception.
                    had_failure=sys.exc_info()[0] is not None
                    result["artifact_stage"]="AFTER_CLI_BEFORE_CLEANUP"
                    try:
                        self.save_evidence(result,password,url)
                    except Exception:
                        print("SYNTHETIC_TRACE_CHECKPOINT_WRITE_FAILED",flush=True)
                    trace.close()
                    for cleanup in (db.session.remove,
                            lambda:event.remove(engine,"do_connect",validate_connect),engine.dispose):
                        try:
                            cleanup()
                        except Exception:
                            result["fixture_cleanup_incomplete"]=True
                    result["artifact_stage"]="AFTER_CLEANUP"
                    try:
                        self.save_evidence(result,password,url)
                    except Exception:
                        print("SYNTHETIC_TRACE_FINAL_CHECKPOINT_WRITE_FAILED",flush=True)
                    if not had_failure and (trace.state["trace_incomplete"] or result.get("fixture_cleanup_incomplete")):
                        raise AssertionError("INCOMPLETE_TRACE_OR_CLEANUP_MUST_NOT_PASS")
            result["full_verification"]=verify_full_bootstrap(url.render_as_string(hide_password=False),environment,password)
        result["artifact_stage"]="FINAL_FULL_VERIFICATION_COMPLETE"
        self.save_evidence(result,password,url)
        print("SYNTHETIC_TLS_INIT_VERIFIED",json.dumps(result["full_verification"]),flush=True)
        # Container teardown, not DROP/termination, owns fixture cleanup.
