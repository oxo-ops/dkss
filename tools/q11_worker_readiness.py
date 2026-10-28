"""Actual worker stop/crash drill with fake AI and a pinned PR #278 cluster.

Uses the real 15-second heartbeat and 120-second lease. No external API calls.
"""
import argparse
from datetime import datetime, timezone
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time

from q11_pg_readiness import bootstrap


def child(bootstrap_path, port, stopped, release, calls, auto_stop):
    b = bootstrap(bootstrap_path)
    app = b.make_app(port, "q11_source")
    sys.path.insert(0, str(b.ROOT / "tests"))
    from unittest.mock import patch
    from test_inspection_document_ai import extraction
    from dkss_app import vehicle_imports, document_import_queue as queue
    from dkss_app.document_import_worker import run_worker

    def fake(source, filename=None, progress_callback=None):
        with open(calls, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(dict(filename=filename, pid=os.getpid(), time=datetime.now(timezone.utc).isoformat())) + "\n")
        if not release.wait(180):
            raise RuntimeError("synthetic extractor release timed out")
        result = extraction(source)
        result["records"][0]["chassis_number"] = "Q11A-FAKE"
        if auto_stop:
            stopped.set()
        return result

    with patch.object(vehicle_imports, "vehicle_document_extractor", return_value=fake), patch.object(
        queue, "detect_document_types", return_value=dict(types=["inspection"], certainty="clear", supported=True)):
        run_worker(app, stopped)


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
    processes, result, start = [], {"status": "failed", "cases": []}, time.perf_counter()
    ctx = multiprocessing.get_context("spawn")
    calls = c.work / "fake-ai-calls.jsonl"

    def state(ident):
        with c.connect("q11_source") as conn:
            row = b.query(conn, "SELECT status,result_json,preview_json FROM vehicle_document_import_draft WHERE id=%s", (ident,))[0]
        return row[0], json.loads(row[1]).get("ocr_job", {}), row[2]

    def start_worker(auto_stop=False, ready=False):
        stopped, release = ctx.Event(), ctx.Event()
        if ready:
            release.set()
        p = ctx.Process(target=child, args=(str(Path(args.bootstrap).resolve()), c.port, stopped, release, str(calls), auto_stop))
        p.start()
        processes.append(p)
        return p, stopped, release

    def await_calls(number, process):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            rows = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
            if len(rows) >= number:
                return
            b.require(process.is_alive(), "worker exited before mock AI")
            time.sleep(.2)
        raise AssertionError("worker never reached mock AI")

    def record(name, evidence):
        result["cases"].append(dict(name=name, status="passed", evidence=evidence))
        b.write_json(c.work / "worker-result.json", result)
        print("PASS", name, flush=True)

    try:
        c.start()
        c.create("q11_source")
        _, _, original = b.seed(c, c.work / "fixture-files")
        with c.connect("q11_source") as conn:
            b.query(conn, "UPDATE vehicle_document_import_draft SET status='queued',result_json=%s WHERE id='Q11A-queue'",
                    (json.dumps(dict(ocr_job=dict(phase="queued", attempts=0, requested_type="inspection"))),))
        p, stopped, release = start_worker()
        await_calls(1, p)
        stopped.set()  # The same cooperative stop event used by the CLI signal handler.
        release.set()
        p.join(30)
        b.require(not p.is_alive() and p.exitcode == 0 and state("Q11A-queue")[0] == "preview", "graceful worker drain failed")
        record("actual_worker_cooperative_stop_drains_current_job", dict(exitcode=p.exitcode, status="preview"))
        with c.connect("q11_source") as conn:
            b.query(conn, """INSERT INTO vehicle_document_import_draft
              (id,batch_id,company_code,created_by_username,document_type,source_filename,source_file,source_sha256,status,preview_json,result_json,created_at)
              VALUES('Q11A-crash','Q11A-crash','Q11A','q11admin','inspection','crash.pdf',''::bytea,%s,'queued','{}',%s,now())""",
              (b.sha(original), json.dumps(dict(ocr_job=dict(phase="queued", attempts=0, requested_type="inspection")))))
        p, _, _ = start_worker()
        await_calls(2, p)
        before = state("Q11A-crash")[1]
        time.sleep(17)
        during = state("Q11A-crash")[1]
        b.require(during["lease_until"] > before["lease_until"], "real heartbeat did not renew")
        record("actual_worker_heartbeat_renews_while_ai_waits", dict(initial_lease=before["lease_until"], renewed_lease=during["lease_until"]))
        p.terminate()
        p.join(10)
        b.require(not p.is_alive() and p.exitcode != 0, "worker was not terminated")
        status, dead_job, preview = state("Q11A-crash")
        b.require(status == "reading" and preview == "{}", "crash unexpectedly persisted a result")
        deadline = datetime.fromisoformat(dead_job["lease_until"])
        # A live successor must not steal the unexpired lease. Start it now.
        successor, _, _ = start_worker(auto_stop=True, ready=True)
        while datetime.now(timezone.utc) <= deadline:
            rows = calls.read_text(encoding="utf-8").splitlines()
            b.require(len(rows) == 2, "successor stole an unexpired lease")
            remaining = (deadline-datetime.now(timezone.utc)).total_seconds()
            print(f"WAIT real lease expiry: {max(0, remaining):.1f}s", flush=True)
            time.sleep(min(10, max(.1, remaining)))
        record("successor_does_not_steal_real_unexpired_lease", dict(lease_deadline=deadline.isoformat()))
        await_calls(3, successor)
        successor.join(30)
        final_status, final_job, _ = state("Q11A-crash")
        b.require(not successor.is_alive() and successor.exitcode == 0 and final_status == "preview", "crashed worker job did not recover")
        b.require(final_job["attempts"] == 2, "expected exactly two attempts after crash")
        with c.connect("q11_source") as conn:
            business = b.query(conn, "SELECT count(*) FROM vehicle_periodic_inspection_record")[0][0]
            drafts = b.query(conn, "SELECT count(*) FROM vehicle_document_import_draft WHERE id='Q11A-crash'")[0][0]
        invocations = [json.loads(x) for x in calls.read_text(encoding="utf-8").splitlines()]
        repeated = sum(x["filename"] == "crash.pdf" for x in invocations)
        b.require(business == 0 and drafts == 1 and repeated == 2, "unexpected duplication or automatic registration")
        record("crash_recovers_after_real_expiry_without_business_duplication", dict(status=final_status, attempts=final_job["attempts"], fake_ai_calls=repeated, draft_rows=drafts, business_rows=business, external_api_calls=0))
        result["status"] = "passed"
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join(10)
        try:
            c.stop()
            result["cluster_stopped"] = not c.started
        except Exception as error:
            result.update(status="failed", stop_error=str(error))
        result["total_seconds"] = time.perf_counter()-start
        b.write_json(c.work / "worker-result.json", result)
    print(json.dumps(dict(status=result["status"], cases=len(result["cases"]), report=str(c.work / "worker-result.json"))))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
