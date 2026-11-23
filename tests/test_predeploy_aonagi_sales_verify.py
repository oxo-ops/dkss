from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, call, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import predeploy_aonagi_sales_verify as gate


SHA = "a" * 40
TARGET = "postgresql+psycopg2://synthetic:dummy@" + gate.HOST + "/" + gate.DATABASE
LIVE_GUARD = (gate.DATABASE, True, "on", "on")
EXPECTED_TABLES = [(name,) for name in gate.TABLES]


class SchemaVerifierTests(unittest.TestCase):
    def verify(self, schema=gate.EXPECTED_COLUMN, tables=None, live=None):
        tables = EXPECTED_TABLES if tables is None else tables
        live = LIVE_GUARD if live is None else live
        db = MagicMock()
        cur = db.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = live
        cur.fetchall.side_effect = [tables, [] if schema is None else [schema]]
        connect = MagicMock(return_value=db)
        result = gate.verify_existing_schema(
            connect, {"DATABASE_URL": TARGET, "PGSSLROOTCERT": "synthetic-ca"}
        )
        self.assertEqual(db.method_calls[0], call.set_session(readonly=True, autocommit=False))
        db.close.assert_called_once_with()
        db.commit.assert_not_called()
        return result, connect, cur

    def test_first_sql_is_under_forced_server_read_only_mode_and_tls(self):
        result, connect, cur = self.verify()
        self.assertTrue(result)
        args, kw = connect.call_args
        self.assertTrue(args[0].startswith("postgresql://synthetic:dummy@"))
        self.assertEqual(kw["host"], gate.HOST)
        self.assertEqual(kw["dbname"], gate.DATABASE)
        self.assertEqual(kw["port"], 5432)
        self.assertEqual(kw["sslmode"], "verify-full")
        self.assertEqual(kw["sslrootcert"], "synthetic-ca")
        self.assertEqual(kw["connect_timeout"], 10)
        self.assertIn("default_transaction_read_only=on", kw["options"])
        self.assertIn("search_path=pg_catalog", kw["options"])
        self.assertEqual(cur.execute.call_args_list, [
            call(gate.CONNECTION_CHECK), call(gate.TABLE_CHECK, gate.TABLES),
            call(gate.COLUMN_CHECK, (gate.TABLES[0],)),
        ])

    def test_wrong_connection_or_writable_session_stops_before_catalog_reads(self):
        for live in [("wrong", True, "on", "on"), (gate.DATABASE, False, "on", "on"),
                     (gate.DATABASE, True, "off", "on"), (gate.DATABASE, True, "on", "off")]:
            with self.subTest(live=live):
                result, _, cur = self.verify(live=live)
                self.assertFalse(result)
                cur.execute.assert_called_once_with(gate.CONNECTION_CHECK)

    def test_missing_tables_stop_before_column_read(self):
        result, _, cur = self.verify(tables=[EXPECTED_TABLES[0]])
        self.assertFalse(result)
        self.assertEqual(cur.execute.call_count, 2)

    def test_missing_column_or_malformed_exact_shape_never_migrates(self):
        for col in [None, ("text", True, "'legacy'::text", "", ""),
                    ("character varying(21)", True, "'legacy'::character varying", "", ""),
                    ("character varying(20)", False, "'legacy'::character varying", "", ""),
                    ("character varying(20)", True, "'wrong'::character varying", "", ""),
                    ("character varying(20)", True, "'legacy'::character varying", "s", "")]:
            with self.subTest(col=col):
                result, _, cur = self.verify(schema=col)
                self.assertFalse(result)
                self.assertEqual(cur.execute.call_count, 3)
                self.assertTrue(all(sql.args[0].strip().startswith("SELECT") for sql in cur.execute.call_args_list))


class GuardAndRunnerTests(unittest.TestCase):
    def test_exact_sha_db_tls_and_override_guard_reused_before_worker(self):
        samples = [
            ("--secret-dummy-value", TARGET, SHA),
            ("--expected-sha", TARGET, "b" * 40),
            ("--expected-sha", TARGET.replace(gate.HOST, "wrong.invalid"), SHA),
            ("--expected-sha", TARGET.replace(gate.DATABASE, "wrong_db"), SHA),
            ("--expected-sha", TARGET + "?sslmode=require", SHA),
            ("--expected-sha", TARGET + "?hostaddr=127.0.0.1", SHA),
        ]
        with TemporaryDirectory() as temp:
            ca = Path(temp, "ca.pem")
            ca.touch()
            for flag, dsn, actual_sha in samples:
                with self.subTest(flag=flag, dsn=dsn, actual_sha=actual_sha):
                    out = StringIO()
                    with patch.dict(os.environ, {"RENDER_GIT_COMMIT": actual_sha, "DATABASE_URL": dsn}, clear=True), \
                         patch("certifi.where", return_value=str(ca)), \
                         patch.object(gate.subprocess, "run") as run, redirect_stdout(out):
                        self.assertEqual(gate.main([flag, SHA]), 10)
                    run.assert_not_called()
                    self.assertEqual(out.getvalue(), "AONAGI_SCHEMA_VERIFY_STOP_GUARD\n")

    def test_worker_launch_scrubs_overrides_caps_timeout_and_contains_output(self):
        with TemporaryDirectory() as temp:
            ca = Path(temp, "ca.pem")
            ca.touch()
            state = {"DATABASE_URL": TARGET, "RENDER_GIT_COMMIT": SHA, "PGHOSTADDR": "127.0.0.1"}
            outcomes = [
                (subprocess.CompletedProcess([], 0, "dummy", "dummy"), None, 0, "AONAGI_SCHEMA_READ_ONLY_VERIFIED\n"),
                (subprocess.CompletedProcess([], 20, "dummy", "dummy"), None, 13, "AONAGI_SCHEMA_VERIFY_STOP_STATE\n"),
                (None, subprocess.TimeoutExpired(["dummy"], 120, output="dummy"), 11, "AONAGI_SCHEMA_VERIFY_STOP_TIMEOUT\n"),
                (None, RuntimeError("dummy"), 12, "AONAGI_SCHEMA_VERIFY_STOP_RUNNER\n"),
            ]
            for ret, err, status, msg in outcomes:
                out = StringIO()
                with patch.dict(os.environ, state, clear=True), \
                     patch("certifi.where", return_value=str(ca)), \
                     patch.object(gate.subprocess, "run", return_value=ret, side_effect=err) as run, redirect_stdout(out):
                    self.assertEqual(gate.main(["--expected-sha", SHA]), status)
                self.assertEqual(out.getvalue(), msg)
                args, kw = run.call_args
                self.assertEqual(args[0][-2:], ["--worker", SHA])
                self.assertEqual(kw["timeout"], 120)
                self.assertEqual(kw["stdout"], subprocess.DEVNULL)
                self.assertEqual(kw["stderr"], subprocess.DEVNULL)
                self.assertEqual(kw["env"]["PGSSLMODE"], "verify-full")
                self.assertNotIn("PGHOSTADDR", kw["env"])


if __name__ == "__main__":
    unittest.main()
