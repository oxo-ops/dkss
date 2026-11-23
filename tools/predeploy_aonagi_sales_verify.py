"""Read-only company invite schema gate for an exact ALSEON release SHA.

Use only as the reviewed Render pre-deploy command for the sales candidate:
    python -B tools/predeploy_aonagi_sales_verify.py --expected-sha <full SHA>
This does not import or start the web app, initializers, or migration CLI.
"""
from contextlib import closing
import os
from pathlib import Path
import subprocess
import sys

try:
    from predeploy_company_invites import DATABASE, HOST, TABLES, guarded_environment
except ImportError:
    guarded_environment = None  # Missing guard is a fixed-output stop, never a fallback.


DB_OPTIONS = (
    "-c default_transaction_read_only=on -c lock_timeout=5000 "
    "-c statement_timeout=60000 -c search_path=pg_catalog"
)
CONNECTION_CHECK = """
SELECT pg_catalog.current_database(),
       (SELECT ssl FROM pg_catalog.pg_stat_ssl
        WHERE pid = pg_catalog.pg_backend_pid()),
       pg_catalog.current_setting('default_transaction_read_only'),
       pg_catalog.current_setting('transaction_read_only')
"""
TABLE_CHECK = """
SELECT c.relname::text
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relpersistence = 'p'
  AND c.relname::text IN (%s, %s)
"""
COLUMN_CHECK = """
SELECT pg_catalog.format_type(a.atttypid, a.atttypmod),
       a.attnotnull,
       pg_catalog.pg_get_expr(d.adbin, d.adrelid),
       a.attgenerated,
       a.attidentity
FROM pg_catalog.pg_attribute AS a
JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_attrdef AS d ON d.adrelid = c.oid AND d.adnum = a.attnum
WHERE n.nspname = 'public' AND c.relname = %s AND c.relkind = 'r'
  AND c.relpersistence = 'p'
  AND a.attname = 'purpose' AND a.attnum > 0 AND NOT a.attisdropped
"""
EXPECTED_COLUMN = ("character varying(20)", True, "'legacy'::character varying", "", "")


def verify_existing_schema(connect, guarded_env):
    """Use only after the fixed host/DB, exact SHA, and CA guard has passed."""
    dsn = guarded_env["DATABASE_URL"]
    if dsn.startswith("postgresql+psycopg2://"):
        dsn = "postgresql://" + dsn.split("://", 1)[1]
    # The fixed kwargs additionally constrain how libpq parses any DSN;
    # server startup options enable read-only before the first SQL.
    with closing(connect(
        dsn,
        host=HOST,
        port=5432,
        dbname=DATABASE,
        sslmode="verify-full",
        sslrootcert=guarded_env["PGSSLROOTCERT"],
        connect_timeout=10,
        options=DB_OPTIONS,
        application_name="aonagi-sales-predeploy-verify",
    )) as connection:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute(CONNECTION_CHECK)
            if cursor.fetchone() != (DATABASE, True, "on", "on"):
                return False
            cursor.execute(TABLE_CHECK, TABLES)
            tables = cursor.fetchall()
            if len(tables) != len(TABLES) or set(tables) != {(name,) for name in TABLES}:
                return False
            cursor.execute(COLUMN_CHECK, (TABLES[0],))
            return cursor.fetchall() == [EXPECTED_COLUMN]
        # closing() closes/rolls back; there is no commit path.


def worker(expected_sha):
    # Even driver or native child diagnostics must not echo the DSN.
    with open(os.devnull, "wb") as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
    try:
        import certifi
        import psycopg2

        env = guarded_environment(os.environ, expected_sha, certifi.where())
        os.environ.clear()
        os.environ.update(env)
        return 0 if verify_existing_schema(psycopg2.connect, env) else 20
    except BaseException:
        return 21


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Reject malformed invocations without echoing any argument text.
    if len(argv) != 2 or argv[0] != "--expected-sha":
        print("AONAGI_SCHEMA_VERIFY_STOP_GUARD")
        return 10
    expected_sha = argv[1]
    try:
        import certifi

        if guarded_environment is None:
            raise RuntimeError("Missing existing guard")
        env = guarded_environment(os.environ, expected_sha, certifi.where())
    except BaseException:
        print("AONAGI_SCHEMA_VERIFY_STOP_GUARD")
        return 10
    try:
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", expected_sha],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=120, check=False,
        )
    except subprocess.TimeoutExpired:
        print("AONAGI_SCHEMA_VERIFY_STOP_TIMEOUT")
        return 11
    except BaseException:
        print("AONAGI_SCHEMA_VERIFY_STOP_RUNNER")
        return 12
    if completed.returncode:
        print("AONAGI_SCHEMA_VERIFY_STOP_STATE")
        return 13
    print("AONAGI_SCHEMA_READ_ONLY_VERIFIED")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        sys.exit(worker(sys.argv[2]))
    sys.exit(main())
