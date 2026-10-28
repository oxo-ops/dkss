"""Additional synthetic role/ACL drill; reuses pinned PR #278 for cluster/seed.

Requires --bootstrap pointing to PR #278 tools/q11_recovery.py. No existing DSN.
This is authorization testing with local trust authentication, not a password test.
"""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_BLOB = "8bc201d336d45d92a393221b5745f71e25f3ab15"


def bootstrap(path):
    raw = Path(path).read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if digest != BOOTSTRAP_BLOB:
        raise ValueError("Expected the unmodified PR #278 bootstrap blob")
    spec = importlib.util.spec_from_file_location("q11_recovery_bootstrap", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    return module


@contextmanager
def login(cluster, role, database):
    import psycopg2
    connection = psycopg2.connect(host="127.0.0.1", port=cluster.port, user=role,
                                  dbname=database, connect_timeout=5, application_name="q11-readiness-only")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def catalog(b, conn):
    return {name: b.query(conn, statement) for name, statement in {
        "extensions": "SELECT e.extname,e.extversion,n.nspname,pg_get_userbyid(e.extowner) FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY 1",
        "objects": "SELECT c.relname,c.relkind,pg_get_userbyid(c.relowner),coalesce(c.relacl::text,'') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m') ORDER BY 1",
        "defaults": "SELECT pg_get_userbyid(defaclrole),n.nspname,defaclobjtype,defaclacl::text FROM pg_default_acl a LEFT JOIN pg_namespace n ON n.oid=a.defaclnamespace ORDER BY 1,2,3",
        "functions": "SELECT p.oid::regprocedure::text,pg_get_userbyid(p.proowner),(SELECT jsonb_agg(jsonb_build_array(pg_get_userbyid(a.grantor),CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,a.privilege_type,a.is_grantable) ORDER BY a.grantor,a.grantee,a.privilege_type) FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a),p.prosecdef FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' ORDER BY 1",
        "schemas": "SELECT nspname,pg_get_userbyid(nspowner),nspacl::text FROM pg_namespace WHERE nspname='public'",
    }.items()}


def run(b, c):
    from psycopg2 import sql
    c.create("q11_source")
    b.seed(c, c.work / "fixture-files")
    q = b.query
    with c.connect("q11_source") as conn:
        for role in ("q11_owner", "q11_app", "q11_backup", "q11_restore", "q11_denied"):
            q(conn, sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(sql.Identifier(role)))
        q(conn, "GRANT q11_owner TO q11_restore WITH INHERIT FALSE")
        q(conn, "ALTER DATABASE q11_source OWNER TO q11_owner")
        q(conn, "COMMENT ON DATABASE q11_source IS 'Q11_SYNTHETIC_ONLY'")
        q(conn, "ALTER SCHEMA public OWNER TO q11_owner")
        for name, kind in q(conn, "SELECT c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','S') ORDER BY (c.relkind='S'),c.relname"):
            q(conn, sql.SQL("ALTER " + ("SEQUENCE" if kind == "S" else "TABLE") + " {} OWNER TO q11_owner").format(sql.Identifier(name)))
        for (identity,) in q(conn, "SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'"):
            q(conn, sql.SQL("ALTER FUNCTION " + identity + " OWNER TO q11_owner"))
        q(conn, "SET ROLE q11_owner")
        q(conn, "CREATE EXTENSION hstore WITH SCHEMA public")
        q(conn, "REVOKE ALL ON SCHEMA public FROM PUBLIC")
        q(conn, "GRANT USAGE ON SCHEMA public TO q11_app,q11_backup")
        q(conn, "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO q11_app")
        q(conn, "GRANT SELECT ON ALL TABLES IN SCHEMA public TO q11_backup")
        q(conn, "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO q11_app")
        q(conn, "GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO q11_backup")
        q(conn, "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC")
        q(conn, "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO q11_app")
        q(conn, "ALTER DEFAULT PRIVILEGES FOR ROLE q11_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")
        for grant in ("GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO q11_app", "GRANT SELECT ON TABLES TO q11_backup",
                      "GRANT USAGE,SELECT ON SEQUENCES TO q11_app", "GRANT SELECT ON SEQUENCES TO q11_backup",
                      "GRANT EXECUTE ON FUNCTIONS TO q11_app"):
            q(conn, "ALTER DEFAULT PRIVILEGES FOR ROLE q11_owner IN SCHEMA public " + grant)
    report = {"cases": [], "bootstrap_blob": BOOTSTRAP_BLOB}

    def case(name, action):
        start = time.perf_counter()
        value = action()
        report["cases"].append(dict(name=name, status="passed", seconds=time.perf_counter()-start, evidence=value))
        b.write_json(c.work / "readiness.json", report)
        print("PASS", name, flush=True)

    def denied(role, statement, database="q11_source"):
        import psycopg2
        try:
            with login(c, role, database) as conn:
                q(conn, statement)
        except psycopg2.Error as error:
            b.require(error.pgcode == "42501", "expected insufficient privilege, got " + str(error.pgcode))
            return {"expected_sqlstate": error.pgcode}
        raise AssertionError("privileged operation unexpectedly allowed")

    def application():
        with login(c, "q11_app", "q11_source") as conn:
            row = q(conn, "INSERT INTO manual(company_code,title,filename) VALUES('Q11A','synthetic role test','new.pdf') RETURNING id")[0]
            value = q(conn, "SELECT 'a=>b'::hstore -> 'a'")[0][0]
        b.require(value == "b", "trusted extension not usable")
        return dict(new_manual_id=row[0], hstore=value)
    case("runtime_dml_sequence_and_extension", application)
    case("runtime_cannot_create_table", lambda: denied("q11_app", "CREATE TABLE public.q11_forbidden(id int)"))
    case("runtime_cannot_assume_owner", lambda: denied("q11_app", "SET ROLE q11_owner"))
    case("backup_cannot_write", lambda: denied("q11_backup", "DELETE FROM manual"))
    with c.connect("q11_source") as conn:
        q(conn, "REVOKE SELECT ON vehicle_document_source FROM q11_backup")
    bad = c.command("pg_dump", "-U", "q11_backup", "-Fc", "-d", "q11_source", "-f", c.work / "denied.dump", check=False)
    b.require(bad["returncode"] != 0 and "permission denied" in bad["stderr"], "incomplete backup not rejected")
    case("backup_missing_read_privilege_rejected", lambda: {"expected_nonzero": bad["returncode"]})
    with c.connect("q11_source") as conn:
        q(conn, "SET ROLE q11_owner")
        q(conn, "GRANT SELECT ON vehicle_document_source TO q11_backup")
    archive = c.work / "acl.dump"
    c.command("pg_dump", "-U", "q11_backup", "-Fc", "-d", "q11_source", "-f", archive)
    with c.connect("q11_source") as conn:
        before = catalog(b, conn)
    for name in ("q11_acl_restore", "q11_no_acl", "q11_denied_restore"):
        c.create(name)
        with c.connect(name) as conn:
            q(conn, sql.SQL("ALTER DATABASE {} OWNER TO q11_owner").format(sql.Identifier(name)))
            q(conn, sql.SQL("COMMENT ON DATABASE {} IS 'Q11_SYNTHETIC_ONLY'").format(sql.Identifier(name)))
    restored = c.command("pg_restore", "-U", "q11_restore", "--role=q11_owner", "--exit-on-error", "--single-transaction", "-d", "q11_acl_restore", archive)
    with c.connect("q11_acl_restore") as conn:
        after = catalog(b, conn)
    b.write_json(c.work / "catalog-before.json", before)
    b.write_json(c.work / "catalog-after.json", after)
    b.require(before == after, "owner/ACL/default ACL/extension catalog mismatch")
    case("limited_restore_preserves_owner_acl_defaults_extension", lambda: dict(restore_seconds=restored["duration_seconds"], archive_sha256=b.sha(archive.read_bytes()), catalog=after))
    with login(c, "q11_restore", "q11_acl_restore") as conn:
        q(conn, "SET ROLE q11_owner")
        q(conn, "CREATE TABLE public.q11_future(id serial PRIMARY KEY, note text)")
        q(conn, "CREATE FUNCTION public.q11_future_value() RETURNS integer LANGUAGE sql AS 'SELECT 7'")
    with login(c, "q11_app", "q11_acl_restore") as conn:
        q(conn, "INSERT INTO q11_future(note) VALUES('new synthetic row')")
        b.require(q(conn, "SELECT q11_future_value()")[0][0] == 7, "new function ACL missing")
    with login(c, "q11_backup", "q11_acl_restore") as conn:
        count = q(conn, "SELECT count(*) FROM q11_future")[0][0]
    b.require(count == 1, "default privileges not applied to future object")
    case("future_table_and_sequence_default_acl", lambda: dict(rows=count))
    with c.connect("q11_acl_restore") as conn:
        # Isolate function EXECUTE denial from schema USAGE denial.
        q(conn, "GRANT USAGE ON SCHEMA public TO q11_denied")
    case("future_function_not_public", lambda: denied("q11_denied", "SELECT public.q11_future_value()", "q11_acl_restore"))
    c.command("pg_restore", "-U", "q11_restore", "--role=q11_owner", "--no-privileges", "--exit-on-error", "--single-transaction", "-d", "q11_no_acl", archive)
    case("omitted_acl_runtime_access_rejected", lambda: denied("q11_app", "SELECT count(*) FROM manual", "q11_no_acl"))
    failed = c.command("pg_restore", "-U", "q11_denied", "--role=q11_owner", "--exit-on-error", "--single-transaction", "-d", "q11_denied_restore", archive, check=False)
    with c.connect("q11_denied_restore") as conn:
        partial = q(conn, "SELECT count(*) FROM pg_tables WHERE schemaname='public'")[0][0]
    b.require(failed["returncode"] != 0 and partial == 0 and "permission denied to set role" in failed["stderr"], "unauthorized restore did not fail for the expected privilege")
    case("unapproved_restore_role_rejected", lambda: dict(returncode=failed["returncode"], partial_tables=partial))
    inventory = ROOT / "tools/q11_pg_inventory.sql"
    c.command("psql", "-X", "-qAt", "-d", "q11_acl_restore", "-v", "q11_expected_db=q11_acl_restore", "-f", inventory)
    wrong = c.command("psql", "-X", "-qAt", "-d", "q11_acl_restore", "-v", "q11_expected_db=q11_wrong", "-f", inventory, check=False)
    b.require(wrong["returncode"] == 3 and "Refusing unmarked or unexpected database" in wrong["stderr"], "inventory wrong-target guard not effective")
    case("read_only_inventory_and_target_guard", lambda: dict(wrong_target_returncode=wrong["returncode"]))
    b.write_json(c.work / "catalog-before.json", before)
    b.write_json(c.work / "catalog-after.json", after)
    report["status"] = "passed"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument("--pg-bin", required=True)
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args()
    b = bootstrap(args.bootstrap)
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            del os.environ[key]
    c = b.Cluster(args.pg_bin, args.work_dir)
    result, started = {"status": "failed"}, time.perf_counter()
    try:
        c.start()
        result = run(b, c)
    except Exception as error:
        partial = c.work / "readiness.json"
        if partial.exists():
            result = json.loads(partial.read_text(encoding="utf-8"))
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        try:
            c.stop()
            result["cluster_stopped"] = not c.started
        except Exception as error:
            result.update(status="failed", stop_error=str(error))
        result["total_seconds"] = time.perf_counter() - started
        b.write_json(c.work / "result.json", result)
    print(json.dumps({"status": result["status"], "report": str(c.work / "result.json")}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
