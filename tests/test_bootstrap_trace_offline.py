"""Real pinned app/CLI and SQLAlchemy; fake DBAPI; all sockets forbidden."""
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import psycopg2
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, Index, event
from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2
from sqlalchemy.schema import CreateIndex
from sqlalchemy.exc import OperationalError
from bootstrap_trace_observer import StatementTrace, safe_settings
import bootstrap_trace_observer as observer
from bootstrap_trace_fixture import (allowed_indexes, isolated_environment, make_app, official_cli,
    validate_service_url, owned_database_name, OPTIONS)
from bootstrap_trace_guard import guard_empty, EXPECTED_GUARD_FLAGS

SECRET = "PRIVATE_SENTINEL postgresql://hidden:password@secret.invalid/db private@example.invalid"
TARGET = "uq_user_account_identity"


class StopBeforeIdentity(Exception):
    pass


class FakeCursor:
    def __init__(self, connection):
        self.connection=connection; self.description=None; self.rowcount=-1; self.rows=[]
    def execute(self, statement, parameters=None):
        con=self.connection; con.calls+=1
        if statement.startswith("SET TRANSACTION READ ONLY"):
            con.read_only=True
        elif "current_database()=" in statement:
            names=sorted(EXPECTED_GUARD_FLAGS)
            self.description=[(name,None,None,None,None,None,None) for name in names]
            self.rows=[tuple(con.guard_value for name in names)]
        elif statement.strip()=="SELECT 1":
            self.description=[("one",None,None,None,None,None,None)]; self.rows=[(1,)]
        elif statement.lstrip().startswith(("CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX")):
            if con.read_only: raise AssertionError("READ_ONLY_GUARD_LEAKED")
            con.ddl+=1
            if con.fail and TARGET in statement:
                con.failures+=1
                raise psycopg2.OperationalError("server closed the connection unexpectedly; "+SECRET)
        else:
            raise AssertionError("UNEXPECTED_SYNTHETIC_SQL")
        return self
    def fetchone(self): return self.rows.pop(0) if self.rows else None
    def fetchall(self): rows=self.rows; self.rows=[]; return rows
    def close(self): pass


class FakeConnection:
    def __init__(self, fail=False, guard_value=True):
        self.closed=0; self.autocommit=False; self.async_=0; self.notices=[]
        self.calls=0; self.ddl=0; self.failures=0; self.read_only=False
        self.pid_calls=0; self.rollbacks=0; self.commits=0
        self.fail=fail; self.guard_value=guard_value
    def cursor(self,*args,**kwargs): return FakeCursor(self)
    def rollback(self): self.read_only=False; self.rollbacks+=1
    def commit(self): self.commits+=1
    def close(self): self.closed=1
    def get_backend_pid(self): self.pid_calls+=1; return 24680
    def get_dsn_parameters(self):
        return {"sslmode":"verify-full", "options":OPTIONS, "host":SECRET, "user":SECRET, "password":SECRET}


class OfflineTests(unittest.TestCase):
    def exercise_cli(self, fail=False, guard_value=True):
        from dkss_app import master_generations, account_identity
        from dkss_app.extensions import db
        con=FakeConnection(fail=fail,guard_value=guard_value); attempts=[]; result={}
        def connect(*args,**kwargs):
            attempts.append(1)
            if len(attempts)>1: raise AssertionError("SECOND_CONNECTION_FORBIDDEN")
            return con
        with isolated_environment("synthetic-admin-password"), \
             patch.object(socket.socket,"connect",side_effect=AssertionError("NETWORK_FORBIDDEN")) as network, \
             patch.object(psycopg2,"connect",side_effect=connect), \
             patch.object(PGDialect_psycopg2,"on_connect",return_value=None), \
             patch.object(PGDialect_psycopg2,"initialize",return_value=None), \
             patch.object(PGDialect_psycopg2,"has_table",return_value=False), \
             patch.object(PGDialect_psycopg2,"has_sequence",return_value=False), \
             patch.object(master_generations,"validate_storage",side_effect=lambda c,**kw:c.exec_driver_sql("SELECT 1").scalar()), \
             patch.object(account_identity,"upgrade_account_identity",side_effect=StopBeforeIdentity):
            app=make_app("postgresql+psycopg2://trace:synthetic@127.0.0.1/synthetic")
            with app.app_context():
                engine=db.engine
                trace=StatementTrace(engine,db.metadata,allowed_indexes(),result)
                try:
                    if not guard_value:
                        with self.assertRaisesRegex(AssertionError,"SYNTHETIC_TARGET_OR_EMPTY_GUARD_FAILED"):
                            guard_empty(engine,"synthetic","trace",result)
                    else:
                        guard_empty(engine,"synthetic","trace",result)
                        expected=OperationalError if fail else StopBeforeIdentity
                        with self.assertRaises(expected):
                            official_cli(app)
                finally:
                    trace.close(); db.session.remove(); engine.dispose()
        network.assert_not_called()
        self.assertEqual(len(attempts),1); self.assertEqual(con.pid_calls,1)
        self.assertEqual(con.commits,0 if fail or not guard_value else 1)
        self.assertNotIn("PRIVATE_SENTINEL",json.dumps(result)); self.assertNotIn("postgresql://",json.dumps(result))
        return result,con

    def test_known_index_disconnect_through_real_inprocess_cli(self):
        result,con=self.exercise_cli(fail=True)
        trace=result["statement_trace"]; failed=trace["failed_operation"]
        self.assertTrue(result["empty_database_guard_passed"])
        self.assertEqual(con.failures,1); self.assertEqual(failed["family"],"CREATE_INDEX")
        self.assertEqual((failed["index"],failed["table"]),(TARGET,"user"))
        self.assertEqual(failed["backend_pid"],24680); self.assertGreaterEqual(failed["duration_ms"],0)
        self.assertTrue(failed["dialect_reports_disconnect"])
        self.assertFalse(trace["trace_incomplete"]); self.assertFalse(trace["automatic_retry"])
        self.assertFalse(trace["additional_SQL_executed"]); self.assertFalse(trace["server_settings_queried"])
        self.assertEqual(trace["physical_connection_count"],1)
        self.assertEqual(sum(trace["counters"].values()),con.calls)

    def test_all_pinned_ddl_complete_before_identity_without_guard_leak(self):
        result,con=self.exercise_cli()
        self.assertEqual(con.ddl,167)
        self.assertEqual(result["statement_trace"]["counters"]["CREATE_INDEX"],99)
        self.assertIsNone(result["statement_trace"]["failed_operation"])

    def test_false_guard_prevents_initialization(self):
        result,con=self.exercise_cli(guard_value=False)
        self.assertEqual(con.ddl,0); self.assertFalse(result.get("empty_database_guard_passed",False))

    def test_exported_components_are_exact_reviewed_source(self):
        source=Path(observer.__file__).read_text(); tree=ast.parse(source)
        manifest=json.loads(Path(__file__).with_name("bootstrap_trace_export.json").read_text())
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),manifest["export_sha256"])
        for name,expected in manifest["component_sha256"].items():
            node=next(n for n in tree.body if getattr(n,"name",None)==name)
            self.assertEqual(hashlib.sha256(ast.get_source_segment(source,node).encode()).hexdigest(),expected)

    def test_settings_do_not_export_private_values(self):
        result=safe_settings({"sslmode":"verify-full","sslrootcert":SECRET,"password":SECRET,
            "user":SECRET,"host":SECRET,"options":OPTIONS+" -c application_name="+SECRET,
            "connect_timeout":"10","keepalives":"1","tcp_user_timeout":SECRET})
        self.assertEqual(result["requested_options"],{"search_path":"public","statement_timeout":30000,"lock_timeout":3000})
        self.assertTrue(result["unrecognized_options_suppressed"])
        self.assertNotIn("PRIVATE",json.dumps(result)); self.assertNotIn("tcp_user_timeout",result)

    def test_identity_allowlist_bounded_output_and_listener_teardown(self):
        metadata=MetaData(); table=Table("user",metadata,Column("id",Integer)); index=Index(TARGET,table.c.id)
        engine=create_engine("postgresql+psycopg2://",creator=lambda:(_ for _ in ()).throw(AssertionError("NO_DB")))
        result={}; trace=StatementTrace(engine,metadata,{(TARGET,"user")},result)
        original=list(trace.listeners)
        try:
            foreign=Table("user",MetaData(),Column("id",Integer)); impostor=Index(TARGET,foreign.c.id)
            self.assertEqual(trace.classify(SimpleNamespace(compiled=SimpleNamespace(statement=CreateIndex(impostor))))[0],"UNRECOGNIZED_DDL_TARGET")
            for _ in range(100):
                context=SimpleNamespace(compiled=SimpleNamespace(statement=CreateIndex(index)))
                trace.before(SimpleNamespace(info={}),None,SECRET,{"password":SECRET},context,False)
                trace.after(None,None,None,None,context,False)
            self.assertEqual(len(trace.state["recent_operations"]),64)
            self.assertEqual(trace.state["counters"]["CREATE_INDEX"],100)
            self.assertNotIn("PRIVATE",json.dumps(result))
        finally:
            trace.close(); engine.dispose()
        self.assertTrue(all(not event.contains(e,n,c) for e,n,c in original))

    def test_service_and_database_guards_reject_external_or_unowned_targets(self):
        valid="postgresql+psycopg2://trace_ci:trace-admin-disposable-only@127.0.0.1:5432/dkss_trace_ci"
        env={"GITHUB_ACTIONS":"true","GITHUB_REPOSITORY":"oxo-ops/dkss"}
        self.assertEqual(validate_service_url(valid,env).host,"127.0.0.1")
        for value in (valid.replace("127.0.0.1","example.invalid"),valid+"?host=example.invalid",
                      valid.replace("dkss_trace_ci","existing"),valid.replace("trace-admin-disposable-only","other")):
            with self.assertRaises(RuntimeError): validate_service_url(value,env)
        with self.assertRaises(RuntimeError): validate_service_url(valid,{})
        with self.assertRaises(RuntimeError): owned_database_name("existing")
        self.assertEqual(owned_database_name("trace_owned_"+"a"*32),"trace_owned_"+"a"*32)

    def test_environment_isolation_removes_pg_overrides(self):
        with patch.dict(os.environ,{"PGHOST":"example.invalid","PGPASSWORD":SECRET,"PGSERVICE":"private"}):
            with isolated_environment("synthetic"):
                self.assertNotIn("PGHOST",os.environ); self.assertNotIn("PGPASSWORD",os.environ)
                self.assertNotIn("PGSERVICE",os.environ)
            self.assertEqual(os.environ["PGPASSWORD"],SECRET)

    def test_first_failure_is_frozen_and_observer_errors_do_not_replace_it(self):
        metadata=MetaData(); table=Table("user",metadata,Column("id",Integer)); index=Index(TARGET,table.c.id)
        engine=create_engine("postgresql+psycopg2://",creator=lambda:(_ for _ in ()).throw(AssertionError("NO_DB")))
        result={}; trace=StatementTrace(engine,metadata,{(TARGET,"user")},result)
        try:
            context=SimpleNamespace(compiled=SimpleNamespace(statement=CreateIndex(index)))
            trace.before(SimpleNamespace(info={}),None,SECRET,None,context,False)
            trace.error(SimpleNamespace(execution_context=context,is_disconnect=True))
            original=dict(trace.state["failed_operation"])
            trace.error(SimpleNamespace(execution_context=None,is_disconnect=False))
            self.assertEqual(trace.state["failed_operation"],original)
            broken=trace.protect(lambda:(_ for _ in ()).throw(ValueError(SECRET)))
            self.assertIsNone(broken()); self.assertTrue(trace.state["trace_incomplete"])
            self.assertNotIn("PRIVATE",json.dumps(result))
        finally:
            trace.close(); engine.dispose()

    def test_keyboard_interrupt_is_not_swallowed_by_observer(self):
        engine=create_engine("postgresql+psycopg2://",creator=lambda:(_ for _ in ()).throw(AssertionError("NO_DB")))
        trace=StatementTrace(engine,MetaData(),set(),{})
        try:
            interrupt=trace.protect(lambda:(_ for _ in ()).throw(KeyboardInterrupt()))
            with self.assertRaises(KeyboardInterrupt): interrupt()
        finally:
            trace.close(); engine.dispose()
