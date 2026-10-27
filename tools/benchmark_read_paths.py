"""Benchmark real GET paths using only generated data in a disposable SQLite DB.

No production configuration, existing database or external API is used.
Run: python tools/benchmark_read_paths.py --vehicles 1 50 200 --samples 3
Outputs JSON to stdout. This is a sequential profiling baseline, not a load test.
"""
import argparse
from collections import Counter
import contextlib
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"


def seed(case, count):
    m = case.m
    today = m.datetime.now(m.ZoneInfo("Asia/Tokyo")).date()
    first = case.vehicle
    first.model_code = "BENCH-TRUCK"
    first.first_registration_date = "2020-01"
    first.office = "Bench"
    m.db.session.add(m.Office(company_code="TEST", name="Bench"))
    vehicles = [first]
    for index in range(1, count):
        vehicles.append(m.Vehicle(company_code="TEST", chassis_number=f"BENCH-{index:06}",
            model_code="BENCH-TRUCK", first_registration_date="2020-01", office="Bench"))
    m.db.session.add_all(vehicles)
    m.db.session.flush()
    checklist = m.Checklist(company_code="TEST", name="Benchmark daily", target="車両管理",
                            active=True, items_json="[]")
    m.db.session.add(checklist)
    m.db.session.flush()
    snapshot = json.dumps({"name": "Benchmark daily", "items": [
        {"fixed_template_code": "daily_inspection_truck_trailer"}]})
    for vehicle in vehicles:
        for index in range(12):
            performed = (today - timedelta(days=30 * index)).isoformat()
            m.db.session.add(m.VehicleMaintenanceRecord(company_code="TEST",
                vehicle_record_id=vehicle.id, entry_date=performed, completion_date=performed,
                status="完了", content="Benchmark service", mileage=100000-index*1000,
                total_cost=10000+index, created_at=performed))
            m.db.session.add(m.VehicleOperationRecord(company_code="TEST",
                vehicle_record_id=vehicle.id, report_number=f"BENCH-{vehicle.id}-{index}",
                operation_date=performed, arrival_meter=100000-index*1000, distance=100))
        for index in range(30):
            performed = today - timedelta(days=index)
            m.db.session.add(m.VehicleChecklistResult(company_code="TEST",
                vehicle_record_id=vehicle.id, checklist_id=checklist.id,
                year=str(performed.year), month=str(performed.month), day=str(performed.day),
                status="点検完了", answers_json="[]", checklist_snapshot_json=snapshot,
                operation_judgment_json="{}"))
    m.db.session.commit()
    return first.id


class SqlMeter:
    def __init__(self):
        self.reset()

    def reset(self):
        self.count = 0
        self.milliseconds = 0
        self.groups = Counter()

    def before(self, conn, cursor, statement, parameters, context, executemany):
        context._benchmark_started = time.perf_counter()
        self.count += 1
        operation = statement.lstrip().split(None, 1)[0].upper()
        match = re.search(r"\b(?:FROM|INTO|UPDATE)\s+[\"\[]?(\w+)", statement, re.I)
        self.groups[operation + ":" + (match.group(1) if match else "other")] += 1

    def after(self, conn, cursor, statement, parameters, context, executemany):
        self.milliseconds += (time.perf_counter() - context._benchmark_started) * 1000


def scenario(count, samples, compare=False, analysis_cache=False):
    from sqlalchemy import event
    import test_workflow_regressions as fixture
    case_type = fixture.WorkflowRegressionTests
    case_type.setUpClass()
    case = case_type()
    setup = False
    try:
        case.setUp()
        setup = True
        m = case.m
        vehicle_id = seed(case, count)
        if analysis_cache:
            from dkss_app.analysis_read_cache import upgrade_read_cache
            upgrade_read_cache()
            with m.app.test_request_context('/'):
                payload, sources = m.get_vehicle_karte_analysis_job_data(case.vehicle)
            m.db.session.add(m.VehicleKarteAnalysis(company_code='TEST', vehicle_record_id=vehicle_id,
                status='completed', result_json=json.dumps(dict(
                    analysis=dict(overview='Benchmark saved result', recommendations=[]),
                    fingerprints=payload['_fingerprints'], sources=sources,
                    comparison=payload['comparison'], generated_at='benchmark fixture'), default=str)))
            m.db.session.commit()
        meter = SqlMeter()
        engine = m.db.engine
        event.listen(engine, "before_cursor_execute", meter.before)
        event.listen(engine, "after_cursor_execute", meter.after)
        endpoints = {
            "dashboard": "/", "vehicle_overview": f"/vehicle/karte/{vehicle_id}",
            "analysis_result": f"/vehicle/karte/{vehicle_id}/analysis/result",
            "notification_unread": "/api/notifications/unread-count?include_action=1",
        }
        results = {}
        from vehicle_read_snapshot import VehicleReadSnapshot
        class UncachedReads(VehicleReadSnapshot):
            def rows(self, model):
                return tuple(model.query.filter_by(company_code=self.company_code,
                    vehicle_record_id=self.vehicle_record_id).all())
        def legacy_date(value, *, normalize=False):
            text = str(value or "")
            text = text.strip()[:10].replace("/", "-") if normalize else text[:10]
            try:
                return datetime.strptime(text, "%Y-%m-%d").date()
            except ValueError:
                return None
        try:
            with patch.object(m, "analyze_vehicle_karte", side_effect=AssertionError("AI called")) as ai, \
                 patch("socket.socket.connect", side_effect=AssertionError("Network called")) as network:
                for name, url in endpoints.items():
                    cache_compare = analysis_cache and name == 'analysis_result'
                    variants = ['uncached', 'cached'] if cache_compare else (["before", "after"] if compare else ["after"])
                    response_contract = None
                    observations = {variant: [] for variant in variants}
                    for iteration in range(samples + 1):
                        # Alternate order to reduce systematic cache/scheduling bias.
                        for variant in variants if iteration % 2 == 0 else list(reversed(variants)):
                            with contextlib.ExitStack() as stack:
                                if variant == 'uncached':
                                    stack.enter_context(patch('dkss_app.analysis_read_cache.AnalysisReadCacheRepository.token', return_value=None))
                                if variant == "before":
                                    stack.enter_context(patch.object(m, "parse_record_date", legacy_date))
                                    stack.enter_context(patch("vehicle_karte_overview.VehicleReadSnapshot", UncachedReads))
                                m.db.session.remove()
                                meter.reset()
                                started = time.perf_counter()
                                response = case.client.get(url)
                                elapsed = (time.perf_counter() - started) * 1000
                                if response.status_code != 200:
                                    raise RuntimeError(f"{name} returned {response.status_code}")
                                if cache_compare:
                                    data = response.get_json()
                                    if response_contract is None:
                                        response_contract = data
                                    elif data != response_contract:
                                        raise AssertionError('Cached analysis JSON differs from uncached response')
                                    if not data['has_result'] or not data['is_current']:
                                        raise AssertionError('Benchmark requires a current saved result')
                                observations[variant].append({
                                    "ms": round(elapsed, 3), "sql_count": meter.count,
                                    "sql_ms": round(meter.milliseconds, 3),
                                    "sql_groups": dict(sorted(meter.groups.items())),
                                })
                    summaries = {}
                    for variant, observations_for_variant in observations.items():
                        warm = observations_for_variant[1:]
                        timings = [sample["ms"] for sample in warm]
                        summaries[variant] = {
                            "first_request": observations_for_variant[0],
                            "warm_median_ms": round(statistics.median(timings), 3),
                            "warm_min_ms": min(timings), "warm_max_ms": max(timings),
                            "warm_sql_counts": [sample["sql_count"] for sample in warm],
                            "warm_sql_median_ms": round(statistics.median(sample["sql_ms"] for sample in warm), 3),
                            "warm_sql_groups": warm[-1]["sql_groups"],
                        }
                    results[name] = summaries if compare or cache_compare else summaries["after"]
                if ai.called or network.called:
                    raise RuntimeError("A measured path attempted an AI/network call.")
        finally:
            event.remove(engine, "before_cursor_execute", meter.before)
            event.remove(engine, "after_cursor_execute", meter.after)
        return {"vehicles": count, "maintenance_records": count * 12,
                "operation_records": count * 12, "daily_records": count * 30, "paths": results}
    finally:
        if setup:
            case.tearDown()
        case_type.tearDownClass()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vehicles", type=int, nargs="+", default=[1, 50, 200])
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--compare", action="store_true",
                        help="Alternate legacy date conversion/uncached reads with optimized reads.")
    parser.add_argument('--analysis-cache', action='store_true', help='Compare saved analysis responses with and without DB projection reuse.')
    args = parser.parse_args()
    if args.compare and args.analysis_cache:
        parser.error('--compare and --analysis-cache are mutually exclusive')
    if any(n < 1 or n > 1000 for n in args.vehicles) or not 1 <= args.samples <= 20:
        parser.error("vehicles must be 1..1000 and samples 1..20")
    # App startup/notification messages must not corrupt the JSON output.
    with contextlib.redirect_stdout(io.StringIO()):
        result = {"backend": "temporary SQLite", "samples": args.samples,
                  "concurrent_requests": 1, "external_calls": 0,
                  "comparison": "uncached vs cached saved analysis; identical JSON asserted" if args.analysis_cache else ("legacy conversion + uncached overview vs optimized" if args.compare else None),
                  "scenarios": [scenario(count, args.samples, args.compare, args.analysis_cache) for count in args.vehicles]}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
