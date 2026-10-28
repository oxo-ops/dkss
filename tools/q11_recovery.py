"""Q11 synthetic recovery drill. Owns a NEW loopback-only PostgreSQL cluster.

No existing server URL, bucket, credential or production data is accepted.
Run with Python from requirements.txt; PostgreSQL binaries must be supplied.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import json
import multiprocessing
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_files(root, manifest):
    """Read-only, offline comparison against a trusted pre-backup manifest."""
    start = time.perf_counter()
    root = Path(root).resolve(strict=True)
    require(root.is_dir(), "root must be a directory")
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("nonempty manifest required")
    seen, results = set(), []
    for row in manifest:
        if not isinstance(row, dict):
            raise ValueError("manifest row must be an object")
        key = row.get("key")
        if (not isinstance(key, str) or not key or key.startswith("/")
                or "\\" in key or ":" in key
                or any(p in {"", ".", ".."} for p in key.split("/")) or key in seen):
            raise ValueError("unsafe or duplicate key")
        if (type(row.get("size")) is not int or row["size"] < 0
                or not isinstance(row.get("sha256"), str)
                or not re.fullmatch("[0-9a-f]{64}", row["sha256"])):
            raise ValueError("invalid size or SHA256")
        seen.add(key)
        path = root.joinpath(*PurePosixPath(key).parts).resolve()
        if not path.is_relative_to(root):
            raise ValueError("path escapes root")
        item = {"key": key, "expected_size": row["size"], "expected_sha256": row["sha256"]}
        if not path.is_file():
            item.update(status="missing", actual_size=None, actual_sha256=None)
        else:
            digest, size = hashlib.sha256(), 0
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
            actual = digest.hexdigest()
            item.update(actual_size=size, actual_sha256=actual,
                        status="matched" if (size, actual) == (row["size"], row["sha256"]) else "mismatch")
        results.append(item)
    return {"status": "passed" if all(r["status"] == "matched" for r in results) else "failed",
            "checked": len(results), "matched": sum(r["status"] == "matched" for r in results),
            "duration_seconds": time.perf_counter() - start, "files": results}


class Cluster:
    def __init__(self, pg_bin, work):
        self.bin, self.work = Path(pg_bin).resolve(), Path(work).resolve()
        # Refuse reuse, even of an empty preexisting directory. Never delete a cluster.
        self.work.mkdir(parents=True, exist_ok=False)
        self.data, self.started = self.work / "pgdata", False
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PG")}
        self.env.update(PGHOST="127.0.0.1", PGPORT=str(self.port), PGUSER="q11",
                        PGCONNECT_TIMEOUT="5", PGAPPNAME="q11-synthetic-drill")
        self.commands = []

    def command(self, name, *args, check=True):
        exe = self.bin / (name + (".exe" if os.name == "nt" else ""))
        start = time.perf_counter()
        # File handles avoid Windows server children retaining communicate() pipes.
        out_path = self.work / f"command-{len(self.commands):02d}.stdout.log"
        err_path = self.work / f"command-{len(self.commands):02d}.stderr.log"
        with out_path.open("wb") as out, err_path.open("wb") as err:
            result = subprocess.run([str(exe), *map(str, args)], env=self.env,
                                    stdout=out, stderr=err, timeout=120)
        item = dict(command=name, args=list(map(str, args)), returncode=result.returncode,
                    duration_seconds=time.perf_counter() - start,
                    stdout=out_path.read_text(encoding="utf-8", errors="replace"),
                    stderr=err_path.read_text(encoding="utf-8", errors="replace"))
        self.commands.append(item)
        write_json(self.work / "commands.json", self.commands)
        if check and result.returncode:
            raise RuntimeError(f"{name} failed ({result.returncode}): {item['stderr']}")
        return item

    def start(self):
        self.command("initdb", "-D", self.data, "-U", "q11", "-A", "trust", "--no-locale", "-E", "UTF8")
        (self.data / "postgresql.auto.conf").write_text("unix_socket_directories = ''\n", encoding="utf-8")
        self.started = True  # Also attempt cleanup if pg_ctl times out after spawning.
        self.command("pg_ctl", "-D", self.data, "-l", self.work / "postgres.log", "-w", "start",
                     "-o", f"-h 127.0.0.1 -p {self.port} -c fsync=on")
        self.started = True

    def stop(self):
        if self.started:
            if (self.data / "postmaster.pid").exists():
                self.command("pg_ctl", "-D", self.data, "-w", "stop", "-m", "fast")
            self.started = False

    @contextmanager
    def connect(self, database):
        import psycopg2
        # All databases and connection parameters are generated by this drill.
        require(re.fullmatch(r"q11_[a-z_]+", database) is not None, "invalid fixture DB")
        conn = psycopg2.connect(host="127.0.0.1", port=self.port, user="q11", dbname=database,
                                connect_timeout=5, application_name="q11-synthetic-drill")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, database):
        self.command("createdb", "-T", "template0", database)

    def clone(self, database, archive):
        self.create(database)
        return self.command("pg_restore", "--exit-on-error", "--single-transaction",
                            "--no-owner", "--no-privileges", "-d", database, archive)

    def app(self, database):
        return make_app(self.port, database)

    def url(self, database):
        return f"postgresql+psycopg2://q11@127.0.0.1:{self.port}/{database}"


def make_app(port, database):
    require(type(port) is int and 0 < port < 65536, "invalid local port")
    require(re.fullmatch(r"q11_[a-z_]+", database) is not None, "invalid fixture DB")
    url = f"postgresql+psycopg2://q11@127.0.0.1:{port}/{database}"
    # Override external integration settings before importing the app.
    os.environ.update(RENDER="", SECRET_KEY="q11-synthetic-only", ITC_INITIAL_PASSWORD="Q11-Fake-742!",
                      DATABASE_URL=url, S3_BUCKET_NAME="", OPENAI_API_KEY="",
                      SMTP_HOST="", VAPID_PRIVATE_KEY="", VAPID_PUBLIC_KEY="",
                      DOCUMENT_IMPORT_WORKER_ENABLED="0", AWS_EC2_METADATA_DISABLED="true",
                      RATELIMIT_STORAGE_URI="memory://", MFA_ENABLED="false",
                      DOCUMENT_IMPORT_MAX_CONCURRENT="2", DOCUMENT_IMPORT_COMPANY_CONCURRENT="1")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from dkss_app import create_app
    return create_app({"TESTING": True, "WTF_CSRF_ENABLED": False,
                       "SQLALCHEMY_DATABASE_URI": url})

def interrupted_rollback_worker(port):
    """Terminate an actual child process after the first committed restored row."""
    app = make_app(port, "q11_interrupted")
    from sqlalchemy import event
    from dkss_app.extensions import db
    from dkss_app.document_sources import restore_inline_sources
    with app.app_context():
        event.listen(db.session, "after_commit", lambda session: os._exit(17))
        restore_inline_sources()


def query(conn, statement, params=None):
    with conn.cursor() as cursor:
        cursor.execute(statement, params)
        return cursor.fetchall() if cursor.description else []


def snapshot(conn):
    from psycopg2 import sql
    query(conn, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    query(conn, "SET LOCAL timezone='UTC'")
    query(conn, "SET LOCAL search_path=public,pg_catalog")
    tables = {}
    for (name,) in query(conn, "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"):
        rows = query(conn, sql.SQL("SELECT row_to_json(t)::text FROM {} t").format(sql.Identifier(name)))
        tables[name] = dict(count=len(rows), sha256=sha("\n".join(sorted(r[0] for r in rows)).encode()))
    sequences = {}
    for name, *settings in query(conn, "SELECT sequencename,data_type::text,start_value,min_value,max_value,increment_by,cycle,cache_size FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename"):
        sequences[name] = dict(settings=settings, state=list(query(conn, sql.SQL("SELECT last_value,is_called FROM {}").format(sql.Identifier(name)))[0]))
    schema = {}
    for name, statement in {
        "columns": "SELECT table_name,column_name,udt_name,character_maximum_length,numeric_precision,numeric_scale,datetime_precision,collation_name,domain_name,is_nullable,column_default FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position",
        "constraints": "SELECT c.relname,x.conname,pg_get_constraintdef(x.oid) FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY 1,2",
        "indexes": "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2",
        "triggers": "SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY 1,2",
        "functions": "SELECT p.oid::regprocedure::text,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind='f' ORDER BY 1",
    }.items():
        schema[name] = [list(r) for r in query(conn, statement)]
    raw_constraints = [list(row) for row in schema["constraints"]]
    normalized = []
    for table, name, definition in raw_constraints:
        if definition.startswith("CHECK "):
            # pg_dump/restore reparses expressions (e.g. varchar[]::text[]).
            # Reparse BOTH sides through PostgreSQL, not regex or ignored diffs.
            # Only session-local temporary tables are written; public data is read-only.
            query(conn, sql.SQL("CREATE TEMP TABLE q11_parse_check (LIKE {})").format(sql.Identifier(table)))
            query(conn, sql.SQL("ALTER TABLE pg_temp.q11_parse_check ADD CONSTRAINT q11_check ") + sql.SQL(definition))
            definition = query(conn, "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='pg_temp.q11_parse_check'::regclass AND conname='q11_check'")[0][0]
            query(conn, "DROP TABLE pg_temp.q11_parse_check")
        normalized.append([table, name, definition])
    schema["constraints"] = normalized
    return dict(tables=tables, sequences=sequences, schema=schema, raw_constraints=raw_constraints)


def compare_snapshots(before, after):
    differences = []
    for category in ("tables", "sequences", "schema"):
        left, right = before[category], after[category]
        for key in sorted(set(left) | set(right)):
            if left.get(key) != right.get(key):
                differences.append(dict(category=category, name=key, before=left.get(key), after=right.get(key)))
    return differences


def integrity(conn):
    from psycopg2 import sql
    checks = {}
    checks["shared_hash_mismatches"] = query(conn, "SELECT count(*) FROM vehicle_document_source WHERE encode(sha256(content),'hex')<>sha256")[0][0]
    checks["active_source_mismatches"] = query(conn, """SELECT count(*) FROM vehicle_document_import_draft d
      LEFT JOIN vehicle_document_source s ON s.company_code=d.company_code AND s.sha256=d.source_sha256
      WHERE d.status<>'deleted' AND (coalesce(octet_length(CASE WHEN octet_length(d.source_file)>0 THEN d.source_file ELSE s.content END),0)=0
      OR encode(sha256(CASE WHEN octet_length(d.source_file)>0 THEN d.source_file ELSE s.content END),'hex') IS DISTINCT FROM d.source_sha256)""")[0][0]
    checks["knowledge_hash_mismatches"] = query(conn, "SELECT count(*) FROM maintenance_knowledge_document WHERE encode(sha256(original_data),'hex')<>checksum")[0][0]
    checks["maintenance_company_mismatches"] = query(conn, "SELECT count(*) FROM vehicle_maintenance_record r JOIN vehicle v ON v.id=r.vehicle_record_id WHERE r.company_code IS DISTINCT FROM v.company_code")[0][0]
    fks = query(conn, """SELECT x.conname,c.relname,p.relname,x.confmatchtype,
      array_agg(a.attname ORDER BY k.ord),array_agg(b.attname ORDER BY k.ord)
      FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid JOIN pg_class p ON p.oid=x.confrelid
      JOIN pg_namespace n ON n.oid=c.relnamespace
      CROSS JOIN LATERAL unnest(x.conkey,x.confkey) WITH ORDINALITY k(child,parent,ord)
      JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.child
      JOIN pg_attribute b ON b.attrelid=p.oid AND b.attnum=k.parent
      WHERE x.contype='f' AND n.nspname='public' GROUP BY x.oid,c.relname,p.relname ORDER BY x.conname""")
    foreign_keys = {}
    for name, child, parent, match, cols, refs in fks:
        nonnull = (sql.SQL(" OR ") if match == "f" else sql.SQL(" AND ")).join(
            sql.SQL("c.{} IS NOT NULL").format(sql.Identifier(c)) for c in cols)
        equal = sql.SQL(" AND ").join(sql.SQL("c.{}=p.{}").format(sql.Identifier(c), sql.Identifier(p)) for c, p in zip(cols, refs))
        statement = sql.SQL("SELECT count(*) FROM {} c WHERE ({}) AND NOT EXISTS (SELECT 1 FROM {} p WHERE {})").format(
            sql.Identifier(child), nonnull, sql.Identifier(parent), equal)
        foreign_keys[child + "." + name] = query(conn, statement)[0][0]
    return dict(checks=checks, foreign_keys=foreign_keys,
                violations=sum(checks.values()) + sum(foreign_keys.values()))


def seed(cluster, files):
    app = cluster.app("q11_source")
    from dkss_app.extensions import db
    from dkss_app.models import Company, User, Vehicle, Manual, VehicleMaintenanceRecord
    from dkss_app.models import VehicleKarteAnalysis, AnalysisInputReadCache
    from dkss_app.models import VehicleDocumentSource as Source, VehicleDocumentImportDraft as Draft
    from dkss_app.document_sources import upgrade_storage
    from dkss_app.analysis_read_cache import upgrade_read_cache
    from dkss_app import document_import_queue as queue
    from pypdf import PdfWriter
    from io import BytesIO
    pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    original, manifest = pdf.getvalue(), []
    with app.app_context():
        # Explicit schema creation on this newly created synthetic database only.
        db.create_all()
        upgrade_storage()
        upgrade_read_cache()
        for company in ("Q11A", "Q11B"):
            db.session.add(Company(company_code=company, company_name=company, active=True, vehicle_limit=10))
            db.session.add(User(company_code=company, username="q11admin", password="unused",
                                last_name="架空", first_name="検証", role="admin", password_changed_at="2026-10-28 00:00:00"))
            vehicle = Vehicle(company_code=company, chassis_number=company + "-FAKE", office="異動後")
            db.session.add(vehicle)
            db.session.flush()
            db.session.add(VehicleKarteAnalysis(company_code=company, vehicle_record_id=vehicle.id,
                status="completed", input_hash="a" * 64, result_json='{"synthetic_saved_ai":"retain"}'))
            db.session.add(AnalysisInputReadCache(company_code=company, vehicle_record_id=vehicle.id,
                context_hash="a" * 64, input_revision=0, projection_json='{"synthetic_projection":true}',
                computed_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc)+timedelta(minutes=5)))
            for i, cost in enumerate((None, 0, 12345)):
                record = VehicleMaintenanceRecord(company_code=company, vehicle_record_id=vehicle.id,
                    entry_date="2026/09/01" if i == 0 else "2026-10-01", total_cost=cost,
                    cost_office=None if i == 0 else "整備当時", files_json=json.dumps(["a.pdf"]) if i == 0 else "[]")
                db.session.add(record)
            db.session.add(Manual(company_code=company, title="架空マニュアル", filename="legacy.pdf" if company == "Q11A" else "b.pdf"))
            db.session.add(Source(company_code=company, sha256=sha(original), content=original))
            for suffix, status, inline in (("shared1", "completed", False), ("shared2", "completed", False),
                                            ("inline", "completed", True), ("deleted", "deleted", False)):
                db.session.add(Draft(id=company + "-" + suffix, batch_id=company + "-" + suffix,
                    company_code=company, created_by_username="q11admin", document_type="inspection",
                    source_filename="synthetic.pdf", source_file=original if inline else b"",
                    source_sha256=sha(original), status=status, preview_json="{}", result_json="{}"))
            table = db.metadata.tables["maintenance_knowledge_document"]
            db.session.execute(table.insert().values(id=company + "-knowledge", company_code=company,
                checksum=sha(original), filename="knowledge.pdf", original_data=original, mimetype="application/pdf",
                knowledge_ids_json="[]", extraction_json="{}", created_by="q11admin", created_at="2026-10-28"))
            for key in (f"uploads/{company}/a.pdf", "manuals/legacy.pdf" if company == "Q11A" else "manuals/Q11B/b.pdf"):
                data = original + ("\n" + key).encode()
                target = files.joinpath(*key.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                manifest.append(dict(company_code=company, key=key, size=len(data), sha256=sha(data), version_id=None))
        # Persist an in-flight lease in the dump, without calling external AI.
        db.session.add(Draft(id="Q11A-queue", batch_id="Q11A-queue", company_code="Q11A",
            created_by_username="q11admin", document_type="inspection", source_filename="queue.pdf",
            source_file=b"", source_sha256=sha(original), status="queued", preview_json="{}",
            result_json=queue.result(dict(phase="queued", attempts=0, requested_type="inspection"))))
        db.session.commit()
        claim = queue.claim_next()
        require(claim and claim[0] == "Q11A-queue", "fixture lease not claimed")
        db.session.remove()
        db.engine.dispose()
    return manifest, claim, original


def file_references(conn, manifest):
    inventory = {(r["company_code"], r["key"]) for r in manifest}
    references = []
    for ident, company, values in query(conn, "SELECT id,company_code,files_json FROM vehicle_maintenance_record"):
        for filename in json.loads(values or "[]"):
            references.append(("maintenance", ident, company, f"uploads/{company}/{filename}"))
    for ident, company, filename in query(conn, "SELECT id,company_code,filename FROM manual WHERE filename IS NOT NULL"):
        preferred, legacy = f"manuals/{company}/{filename}", f"manuals/{filename}"
        key = preferred if (company, preferred) in inventory else legacy
        references.append(("manual", ident, company, key))
    missing = [r for r in references if (r[2], r[3]) not in inventory]
    return dict(checked=len(references), missing=missing)


class Drill:
    def __init__(self, cluster):
        self.cluster = cluster
        self.report = dict(status="running", started_at=datetime.now(timezone.utc).isoformat(), cases=[],
                           scope="synthetic loopback PostgreSQL and local files; no AWS requests",
                           script_sha256=sha(Path(__file__).read_bytes()), python_version=sys.version,
                           acceptance="synthetic_functional_only")

    def case(self, name, action):
        start = time.perf_counter()
        try:
            evidence = action()
            self.report["cases"].append(dict(name=name, status="passed", duration_seconds=time.perf_counter()-start, evidence=evidence))
            print("PASS", name, flush=True)
            return evidence
        except Exception as error:
            self.report["cases"].append(dict(name=name, status="failed", duration_seconds=time.perf_counter()-start,
                                               error=f"{type(error).__name__}: {error}"))
            raise
        finally:
            write_json(self.cluster.work / "report.json", self.report)

    def execute(self):
        c = self.cluster
        files, restored = c.work / "files-source", c.work / "files-restored"
        files.mkdir()
        c.create("q11_source")
        manifest, claim, original = seed(c, files)
        write_json(c.work / "manifest.json", manifest)
        with c.connect("q11_source") as conn:
            baseline = snapshot(conn)
        write_json(c.work / "before.json", baseline)
        archive = c.work / "baseline.dump"

        def dump_restore():
            dump = c.command("pg_dump", "-Fc", "--no-owner", "--no-privileges", "-d", "q11_source", "-f", archive)
            restore = c.clone("q11_restored", archive)
            with c.connect("q11_restored") as conn:
                after = snapshot(conn)
            write_json(c.work / "after.json", after)
            diff = compare_snapshots(baseline, after)
            require(not diff, "restored database differs from frozen baseline")
            return dict(dump_sha256=sha(archive.read_bytes()), dump_seconds=dump["duration_seconds"],
                        restore_seconds=restore["duration_seconds"],
                        tables=len(after["tables"]), rows=sum(t["count"] for t in after["tables"].values()),
                        sequences=len(after["sequences"]), differences=diff)
        self.case("dump_restore_exact_snapshot", dump_restore)

        def healthy():
            with c.connect("q11_restored") as conn:
                result = integrity(conn)
                refs = file_references(conn, manifest)
            require(result["violations"] == 0 and not refs["missing"], "invalid restored references")
            shutil.copytree(files, restored)
            result.update(files=verify_files(restored, manifest), file_references=refs)
            require(result["files"]["status"] == "passed", "originals differ")
            return result
        self.case("restored_hashes_foreign_keys_and_local_files", healthy)

        def incomplete_manifest():
            with c.connect("q11_restored") as conn:
                result = file_references(conn, manifest[1:])
            require(len(result["missing"]) == 1, "missing DB-to-file manifest reference undetected")
            return dict(expected_rejection=True, references=result)
        self.case("database_file_manifest_reference_missing", incomplete_manifest)

        for name, mutation in (("missing_file", lambda p: p.unlink()),
                               ("same_size_file_corruption", lambda p: p.write_bytes(bytes([p.read_bytes()[0] ^ 1]) + p.read_bytes()[1:]))):
            def file_failure(name=name, mutation=mutation):
                target = c.work / name
                shutil.copytree(restored, target)
                mutation(target.joinpath(*manifest[0]["key"].split("/")))
                result = verify_files(target, manifest)
                require(result["status"] == "failed" and result["matched"] == len(manifest)-1, "file fault undetected")
                return dict(expected_rejection=True, verification=result)
            self.case(name, file_failure)

        def database_fault(database, statement, predicate):
            c.clone(database, archive)
            with c.connect(database) as conn:
                query(conn, statement)
            with c.connect(database) as conn:
                result = integrity(conn)
            require(predicate(result), "database integrity fault undetected")
            return dict(expected_rejection=True, integrity=result)
        self.case("missing_shared_source", lambda: database_fault("q11_missing_source",
            "DELETE FROM vehicle_document_source WHERE company_code='Q11A'",
            lambda r: r["checks"]["active_source_mismatches"] == 3))
        self.case("tampered_shared_source", lambda: database_fault("q11_tampered_source",
            "UPDATE vehicle_document_source SET content=decode('00','hex') WHERE company_code='Q11B'",
            lambda r: r["checks"]["shared_hash_mismatches"] == 1 and r["checks"]["active_source_mismatches"] == 2))
        self.case("tampered_knowledge_original", lambda: database_fault("q11_tampered_knowledge",
            "UPDATE maintenance_knowledge_document SET original_data=decode('00','hex') WHERE company_code='Q11A'",
            lambda r: r["checks"]["knowledge_hash_mismatches"] == 1))
        self.case("cross_company_reference", lambda: database_fault("q11_wrong_company",
            "UPDATE vehicle_maintenance_record SET company_code='Q11B' WHERE id=(SELECT min(id) FROM vehicle_maintenance_record)",
            lambda r: r["checks"]["maintenance_company_mismatches"] == 1))
        self.case("foreign_key_orphan", lambda: database_fault("q11_orphan",
            "SET LOCAL session_replication_role=replica; UPDATE vehicle_maintenance_record SET vehicle_record_id=2147483647 WHERE id=(SELECT min(id) FROM vehicle_maintenance_record)",
            lambda r: sum(r["foreign_keys"].values()) == 1))

        def count_fault():
            c.clone("q11_counts", archive)
            with c.connect("q11_counts") as conn:
                query(conn, "DELETE FROM manual WHERE id=(SELECT min(id) FROM manual)")
            with c.connect("q11_counts") as conn:
                after = snapshot(conn)
            diff = compare_snapshots(baseline, after)
            require(any(d["name"] == "manual" and d["before"]["count"] - d["after"]["count"] == 1 for d in diff), "row loss undetected")
            return dict(expected_rejection=True, differences=diff)
        self.case("row_count_mismatch", count_fault)

        def constraint_fault():
            c.clone("q11_constraint", archive)
            with c.connect("q11_constraint") as conn:
                query(conn, "ALTER TABLE vehicle_coupling DROP CONSTRAINT ck_vehicle_coupling_kind")
                query(conn, "ALTER TABLE vehicle_coupling ADD CONSTRAINT ck_vehicle_coupling_kind CHECK (kind IN ('semi'))")
            with c.connect("q11_constraint") as conn:
                after = snapshot(conn)
            diff = compare_snapshots(baseline, after)
            require(any(d["category"] == "schema" and d["name"] == "constraints" for d in diff), "changed CHECK semantics undetected")
            # Keep JSON small; complete raw and normalized definitions are in snapshots.
            return dict(expected_rejection=True, detected_categories=[d["name"] for d in diff])
        self.case("changed_check_constraint_detected", constraint_fault)

        def schema_or_sequence_fault(database, statement, category):
            c.clone(database, archive)
            with c.connect(database) as conn:
                query(conn, statement)
            with c.connect(database) as conn:
                diff = compare_snapshots(baseline, snapshot(conn))
            require(any(d["category"] == category for d in diff), "schema or sequence drift undetected")
            return dict(expected_rejection=True, detected_categories=[d["name"] for d in diff])
        self.case("column_length_change_detected", lambda: schema_or_sequence_fault("q11_column",
            "ALTER TABLE manual ALTER COLUMN title TYPE varchar(201)", "schema"))
        self.case("sequence_state_change_detected", lambda: schema_or_sequence_fault("q11_sequence",
            "SELECT setval('manual_id_seq',1,false)", "sequences"))

        def broken_restore():
            broken = c.work / "truncated.dump"
            data = archive.read_bytes()
            broken.write_bytes(data[:len(data)//2])
            c.create("q11_broken")
            result = c.command("pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges", "-d", "q11_broken", broken, check=False)
            with c.connect("q11_broken") as conn:
                count = query(conn, "SELECT count(*) FROM pg_tables WHERE schemaname='public'")[0][0]
            require(result["returncode"] != 0 and count == 0, "failed restore was not atomic")
            with c.connect("q11_source") as conn:
                require(not compare_snapshots(baseline, snapshot(conn)), "source changed during failed restore")
            return dict(expected_rejection=True, restore_returncode=result["returncode"], partial_tables=count)
        self.case("truncated_dump_restore_rejected_atomically", broken_restore)
        self.case("inline_rollback_and_idempotency", lambda: self.rollback("q11_rollback", archive, original))
        self.case("rollback_partial_failure_repair_and_retry", lambda: self.rollback("q11_partial", archive, original, fault=True))
        self.case("rollback_process_exit_and_resume", lambda: self.interrupted_rollback(archive, original))
        self.case("compaction_locked_row_then_retry", lambda: self.compaction(archive))
        self.case("restored_ocr_lease_recovery_and_retry_limit", lambda: self.queue_recovery(archive, claim))
        self.case("cache_clear_upgrade_and_new_sequence_write", lambda: self.cache_and_sequence(archive))

        def database_restart():
            import psycopg2
            c.stop()
            down_at = time.perf_counter()
            try:
                with c.connect("q11_source"):
                    pass
            except psycopg2.OperationalError:
                pass
            else:
                raise AssertionError("stopped DB unexpectedly accepted a connection")
            c.started = True
            c.command("pg_ctl", "-D", c.data, "-l", c.work / "postgres.log", "-w", "start",
                      "-o", f"-h 127.0.0.1 -p {c.port} -c fsync=on")
            with c.connect("q11_source") as conn:
                diff = compare_snapshots(baseline, snapshot(conn))
            require(not diff, "restart changed frozen source database")
            return dict(connection_failure_observed=True, restart_and_verify_seconds=time.perf_counter()-down_at, differences=diff)
        self.case("database_outage_restart_and_persistence", database_restart)

    def rollback(self, database, archive, original, fault=False):
        c = self.cluster
        c.clone(database, archive)
        if fault:
            with c.connect(database) as conn:
                query(conn, "UPDATE vehicle_document_import_draft SET source_sha256=repeat('0',64) WHERE id='Q11A-shared2'")
        app = c.app(database)
        from dkss_app.extensions import db
        from dkss_app.models import VehicleDocumentImportDraft as Draft
        from dkss_app.document_sources import restore_inline_sources
        with app.app_context():
            try:
                if fault:
                    try:
                        restore_inline_sources()
                    except ValueError as error:
                        require("SOURCE_CHANGED" in str(error), "wrong rollback rejection")
                    else:
                        raise AssertionError("corrupt rollback accepted")
                    db.session.expire_all()
                    require(db.session.get(Draft, "Q11A-shared1")._source_file == original, "earlier commit not preserved")
                    row = db.session.get(Draft, "Q11A-shared2")
                    row.source_sha256 = sha(original)
                    db.session.commit()
                moved = restore_inline_sources()
                require(moved == (3 if fault else 5), "unexpected rollback row count")
                require(restore_inline_sources() == 0, "rollback not idempotent")
                rows = Draft.query.all()
                require(all((r.source_file == b"" and r._source_file == b"") if r.status == "deleted" else r._source_file == original for r in rows), "rollback changed originals or revived deletion")
                return dict(restored_after_repair=moved, second_run=0, deleted_rows=2, original_sha256=sha(original), partial_commit_checked=fault)
            finally:
                db.session.remove()
                db.engine.dispose()

    def interrupted_rollback(self, archive, original):
        c = self.cluster
        c.clone("q11_interrupted", archive)
        child = multiprocessing.get_context("spawn").Process(target=interrupted_rollback_worker, args=(c.port,))
        child.start()
        child.join(30)
        if child.is_alive():
            child.terminate()
            child.join(5)
            raise AssertionError("interrupted rollback child timed out")
        require(child.exitcode == 17, "rollback did not reach injected process exit")
        app = c.app("q11_interrupted")
        from dkss_app.extensions import db
        from dkss_app.models import VehicleDocumentImportDraft as Draft
        from dkss_app.document_sources import restore_inline_sources
        with app.app_context():
            try:
                require(db.session.get(Draft, "Q11A-queue")._source_file == original, "committed row lost on child exit")
                remaining = restore_inline_sources()
                require(remaining == 4 and restore_inline_sources() == 0, "resume after process exit failed")
                require(all((r.source_file == b"" and r._source_file == b"") if r.status == "deleted" else r._source_file == original for r in Draft.query.all()), "process exit damaged originals")
                return dict(child_exitcode=child.exitcode, rows_committed_before_exit=1, resumed=remaining, repeated=0)
            finally:
                db.session.remove()
                db.engine.dispose()

    def compaction(self, archive):
        c = self.cluster
        c.clone("q11_compact", archive)
        app = c.app("q11_compact")
        from dkss_app.extensions import db
        from dkss_app.document_sources import compact_sources
        with c.connect("q11_compact") as lock:
            query(lock, "SELECT id FROM vehicle_document_import_draft WHERE id='Q11A-inline' FOR UPDATE")
            with app.app_context():
                try:
                    first = compact_sources(batch_size=1)
                    require(first == 1, "locked source not skipped")
                finally:
                    db.session.remove()
            # Lock released by committing this independent connection.
        with app.app_context():
            try:
                second, third = compact_sources(batch_size=1), compact_sources(batch_size=1)
                require((second, third) == (1, 0), "skipped row not recovered on retry")
            finally:
                db.session.remove()
                db.engine.dispose()
        with c.connect("q11_compact") as conn:
            result = integrity(conn)
        require(result["violations"] == 0, "compaction damaged originals")
        return dict(first=first, after_unlock=second, repeated=third, integrity=result)

    def queue_recovery(self, archive, old_claim):
        c = self.cluster
        c.clone("q11_queue", archive)
        app = c.app("q11_queue")
        from dkss_app.extensions import db
        from dkss_app.models import VehicleDocumentImportDraft as Draft
        from dkss_app import document_import_queue as queue
        with app.app_context():
            try:
                for _ in range(2):
                    row = db.session.get(Draft, "Q11A-queue")
                    job = queue.metadata(row.result_json)
                    job["lease_until"] = "2000-01-01"
                    row.result_json = queue.result(job)
                    db.session.commit()
                    claim = queue.claim_next()
                    require(claim and claim[1] != old_claim[1], "expired restored lease not reclaimed")
                require(not queue.renew(*old_claim), "stale worker renewed")
                require(not queue.finish(*old_claim, error=ValueError("NO_INSPECTION_FOUND")), "stale worker wrote")
                row = db.session.get(Draft, "Q11A-queue")
                job = queue.metadata(row.result_json)
                job["lease_until"] = "2000-01-01"
                row.result_json = queue.result(job)
                db.session.commit()
                require(queue.claim_next() is None, "retry limit bypassed")
                db.session.expire_all()
                require(db.session.get(Draft, "Q11A-queue").status == "read_error", "retry limit not recorded")
                require(queue.retry_failed("Q11A-queue", "Q11A", "q11admin") == 1, "explicit retry failed")
                require(queue.claim_next() is not None, "explicit retry not claimable")
                return dict(reclaims=2, stale_renew=False, stale_finish=False, max_attempts=3, manual_retry=1, external_calls=0)
            finally:
                db.session.remove()
                db.engine.dispose()

    def cache_and_sequence(self, archive):
        c = self.cluster
        c.clone("q11_cache", archive)
        with c.connect("q11_cache") as conn:
            before = snapshot(conn)
        app = c.app("q11_cache")
        from dkss_app.extensions import db
        from dkss_app.analysis_read_cache import upgrade_read_cache
        from dkss_app.models import AnalysisInputReadCache, Vehicle
        with app.app_context():
            try:
                db.session.query(AnalysisInputReadCache).delete()
                db.session.commit()
                upgrade_read_cache()
            finally:
                db.session.remove()
                db.engine.dispose()
        with c.connect("q11_cache") as conn:
            after = snapshot(conn)
        diff = compare_snapshots(before, after)
        allowed = {"analysis_input_read_cache", "analysis_input_epoch"}
        require(all(d["category"] == "tables" and d["name"] in allowed for d in diff), "cache operations changed business data or schema")
        require(any(d["name"] == "analysis_input_epoch" for d in diff), "input epoch did not advance")
        with app.app_context():
            try:
                old_ids = {v.id for v in Vehicle.query.all()}
                row = Vehicle(company_code="Q11A", chassis_number="Q11-NEW-SYNTHETIC")
                db.session.add(row)
                db.session.commit()
                require(row.id not in old_ids, "sequence collision")
                new_id = row.id
            finally:
                db.session.remove()
                db.engine.dispose()
        return dict(expected_cache_differences=diff, new_vehicle_id=new_id, business_tables_unchanged_before_insert=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, help="Directory with initdb, pg_ctl, pg_dump, pg_restore, createdb")
    parser.add_argument("--work-dir", required=True, help="NEW directory for the owned cluster and JSON evidence")
    args = parser.parse_args(argv)
    # libpq and SQLAlchemy must not inherit services, options, or password files.
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            del os.environ[key]
    start = time.perf_counter()
    cluster = Cluster(args.pg_bin, args.work_dir)
    drill = Drill(cluster)
    try:
        cluster.start()
        drill.report["postgres_version"] = cluster.command("pg_dump", "--version")["stdout"].strip()
        drill.execute()
        drill.report["status"] = "passed"
    except Exception as error:
        drill.report.update(status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        try:
            cluster.stop()
            drill.report["cluster_stopped"] = not cluster.started
        except Exception as error:
            drill.report.update(status="failed", cleanup_error=str(error), cluster_stopped=False)
        drill.report.update(duration_seconds=time.perf_counter()-start, finished_at=datetime.now(timezone.utc).isoformat())
        write_json(cluster.work / "report.json", drill.report)
    print(json.dumps(dict(status=drill.report["status"], cases=len(drill.report["cases"]),
                          duration_seconds=drill.report["duration_seconds"], report=str(cluster.work / "report.json"))))
    return 0 if drill.report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
