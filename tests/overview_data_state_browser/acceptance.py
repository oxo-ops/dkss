#!/usr/bin/env python3
"""Narrow ordinary-overview browser acceptance with synthetic Flask GET responses.

No server socket, live login or production DB. Normal notification GETs remain
active; this suite does not misrepresent the entire ordinary app as read-only.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, urlsplit

PUBLIC_SHA = "779c9f2f3ff1e8dc3574e12c82019bdd4e8d436c"
FROZEN_TREE = "9ce8508d28a03960f6c07eead1a1ba3ea13e7186"
ORIGIN = "http://127.0.0.1:8765"
DATA_STATE = "保存された優先度を確認できません。詳細から元の提案を確認してください。"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--chromium", type=Path)
    parser.add_argument("--allow-identical-tree-preflight", action="store_true")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preflight-only", action="store_true")
    modes.add_argument("--run-browser", action="store_true")
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.artifacts.resolve()
    require(os.environ.get("DKSS_BROWSER_ACCEPTANCE_ISOLATED") == "1", "Use isolated runner")
    require(os.environ.get("DATABASE_URL") == "sqlite:///:memory:", "No external DB allowed")
    sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
    require(tree == FROZEN_TREE, "Wrong frozen source tree")
    require(not args.allow_identical_tree_preflight or args.preflight_only, "Tree-only flag cannot launch browser")
    require(sha == PUBLIC_SHA or args.allow_identical_tree_preflight, "Wrong frozen source commit")
    require(not subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"], text=True).strip(), "Candidate must be clean")
    if args.run_browser:
        require(args.chromium is not None and args.chromium.is_file(), "Explicit installed Chromium required")
    output.mkdir(parents=True, exist_ok=True)
    os.chdir(repo)
    sys.path[:0] = [str(repo), str(repo / "tests")]
    from test_vehicle_priority_preview import VehiclePriorityPreviewTests, PreviewHTML
    from dkss_app.analysis_feedback import vehicle_analysis_maintenance_value
    from sqlalchemy import event

    report = dict(candidate_sha=sha, candidate_tree=tree, frozen_public_sha=PUBLIC_SHA,
                  frozen_source_tree=FROZEN_TREE, source_tree_equal=True,
                  started_utc=datetime.now(timezone.utc).isoformat(), fixture_only=True,
                  production_accessed=False, browser_started=False, browser_acceptance_passed=False,
                  transport="in-process Flask WSGI GET bridge", cases=[], database_mutations=[],
                  page_errors=[], blocked_external_requests=[], non_get_requests=[], failed_gets=[],
                  notification_gets=0, ordinary_app_globally_read_only=False)
    case = VehiclePriorityPreviewTests()
    class_started = setup_started = listening = False
    active_request = ["fixture"]
    try:
        case.setUpClass(); class_started = True
        case.setUp(); setup_started = True
        m = case.m
        require(m.db.engine.url.drivername == "sqlite", "Wrong DB driver")
        require(Path(m.db.engine.url.database).resolve().is_relative_to(Path(os.environ["DKSS_VALIDATION_TMP"]).resolve()), "DB outside disposable fixture")
        # Exactly five synthetic saved proposals. Malformed values are deliberately
        # preserved, not normalized by the fixture or replaced by a fourth label.
        state, bundle, _unused_preview_fixture = case.save_synthetic_analysis(("unexpected", "低", None, "高", "中"))
        items = bundle["analysis"]["recommendations"]
        for i, item in enumerate(items):
            item["action"] = f"合成対応{i}：元の提案本文を保持"
        with m.app.test_request_context("/"):
            for source_id, source in bundle["sources"].items():
                record = m.VehicleMaintenanceRecord.query.filter_by(id=int(source_id.split(":")[1]), company_code="TEST", vehicle_record_id=case.vehicle.id).one()
                rendered = vehicle_analysis_maintenance_value(record)
                source.update(url=rendered["url"], label=rendered["label"])
        state.result_json = json.dumps(bundle, ensure_ascii=False)
        identities = [m.vehicle_analysis_proposal_ids(item) for item in items]
        for index, status in ((0, "accepted"), (2, "in_progress")):
            key, revision = identities[index]
            m.db.session.add(m.VehicleAnalysisFeedback(company_code="TEST", vehicle_record_id=case.vehicle.id,
                proposal_key=key, proposal_revision=revision, status=status, comment=f"合成保持{index}",
                created_by="admin", created_at="2026-11-10T00:00:00Z", snapshot_json="{}"))
        # A normal preference is seeded as part of synthetic setup, not disabled.
        # Re-reading this same vehicle should not need to rewrite that preference.
        user = m.User.query.filter_by(company_code="TEST", username="admin").one()
        user.dashboard_settings_json = json.dumps({"vehicle_karte_last_vehicle_id":case.vehicle.id})
        m.db.session.commit()
        state_id = state.id
        before_json = state.result_json
        before_settings = user.dashboard_settings_json
        def feedback_snapshot():
            return [(r.id, r.proposal_key, r.proposal_revision, r.status, r.comment, r.snapshot_json) for r in m.VehicleAnalysisFeedback.query.order_by(m.VehicleAnalysisFeedback.id).all()]
        before_feedback = feedback_snapshot()
        overview = f"/vehicle/karte/{case.vehicle.id}"
        analysis = overview + "/analysis"
        result_path = analysis + "/result"
        def request(path):
            parsed = urlsplit(path)
            try:
                endpoint, _values = m.app.url_map.bind("localhost").match(parsed.path, method="GET")
            except Exception:
                endpoint = "unmatched_route"
            previous = active_request[0]
            active_request[0] = endpoint
            try:
                response = case.client.get(path)
                if response.status_code >= 400:
                    report["failed_gets"].append(dict(endpoint=endpoint, status=response.status_code))
                return response
            finally:
                active_request[0] = previous
        def track_write(_connection, _cursor, statement, _parameters, _context, _many):
            tokens = statement.lstrip().split(None, 1)
            verb = tokens[0].upper() if tokens else ""
            if verb in {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "REPLACE"}:
                match = re.match(r'\s*(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|(?:CREATE|ALTER|DROP)\s+(?:TABLE|INDEX))\s+["`]?([A-Za-z_][A-Za-z_0-9]*)', statement, re.I)
                report["database_mutations"].append(dict(endpoint=active_request[0], verb=verb, table=match.group(1) if match else "UNIDENTIFIED"))
        event.listen(m.db.engine, "before_cursor_execute", track_write); listening = True
        def projection(data):
            return [{"priority_present":"priority" in p, "priority":p.get("priority"),
                     "proposal_id":p["proposal_id"], "proposal_revision":p["proposal_revision"],
                     "action":p["action"], "feedback":p.get("feedback")}
                    for p in data["analysis"]["recommendations"]]
        initial = request(result_path)
        require(initial.status_code == 200, "Saved result route failed")
        initial = initial.json
        require("priority_preview" not in initial, "Unexpected preview projection")
        require(initial["is_current"] is False, "Stale source sentinel was normalized")
        saved_projection = projection(initial)
        require([p["priority"] for p in saved_projection] == ["unexpected", "低", None, "高", "中"], "Saved priority values changed")
        require([(p["proposal_id"], p["proposal_revision"]) for p in saved_projection] == identities, "Saved identity changed")
        require([p["action"] for p in saved_projection] == [p["action"] for p in items], "Saved action changed")
        require(saved_projection[0]["feedback"]["status"] == "accepted" and saved_projection[2]["feedback"]["status"] == "in_progress", "Synthetic feedback missing")
        for source in initial["sources"].values():
            parts = urlsplit(source["url"])
            require(not parts.scheme and not parts.netloc and parts.path.startswith("/"), "Source must be same origin")
            require(request(source["url"]).status_code == 200, "Saved source route failed")
        for path in (overview, analysis):
            response = request(path)
            require(response.status_code == 200, "Ordinary document route failed")
            require(PreviewHTML(response.get_data(as_text=True)).body.get("data-priority-preview") == "false", "Ordinary page incorrectly suppresses notifications")
        def assert_saved_unchanged():
            m.db.session.expire_all()
            require(m.VehicleKarteAnalysis.query.get(state_id).result_json == before_json, "Saved analysis bytes changed")
            require(feedback_snapshot() == before_feedback, "Saved feedback changed")
            require(m.User.query.filter_by(company_code="TEST", username="admin").one().dashboard_settings_json == before_settings, "Saved preference changed")
            require(projection(request(result_path).json) == saved_projection, "Saved value identity action or feedback changed")
        assert_saved_unchanged()
        report["cases"].append("PREFLIGHT: exact source, five synthetic persisted proposals, invalid/null preserved, source links, ordinary route and saved identity/action/feedback unchanged")
        if args.preflight_only:
            require(not report["database_mutations"], "Preflight overview/result unexpectedly wrote SQL")
            report["status"] = "PREFLIGHT_PASS_BROWSER_NOT_RUN"
            return 0

        from importlib.metadata import version
        from playwright.sync_api import sync_playwright, expect
        report.update(python_version=sys.version.split()[0], playwright_version=version("playwright"))
        # Existing normal notification maintenance is deliberately active. Only
        # these documented background writes may occur; proposal writes never may.
        notification_endpoints = {m.app.url_map.bind("localhost").match(path, method="GET")[0]
                                  for path in ("/api/notifications/recent", "/api/notifications/unread-count")}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=str(args.chromium.resolve()))
            report.update(browser_started=True, browser_version=browser.version)
            try:
                context = browser.new_context(viewport={"width":1440,"height":1000}, service_workers="block")
                def bridge(route):
                    req = route.request; parsed = urlsplit(req.url)
                    if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
                        report["blocked_external_requests"].append(parsed.hostname or "unknown")
                        route.abort(); return
                    if req.method != "GET":
                        report["non_get_requests"].append(dict(method=req.method,path=parsed.path))
                        route.abort(); return
                    if parsed.path == "/api/notifications/unread-count":
                        report["notification_gets"] += 1
                    response = request(parsed.path + ("?"+parsed.query if parsed.query else ""))
                    headers = {k:v for k,v in response.headers.items() if k.lower() not in {"content-length","transfer-encoding","connection","set-cookie"}}
                    route.fulfill(status=response.status_code,headers=headers,body=response.get_data())
                context.route("**/*",bridge)
                page = context.new_page()
                page.on("pageerror",lambda error: report["page_errors"].append(str(error)))
                expected_order = [3,4,1,0,2]
                for width in (1440,390):
                    page.set_viewport_size({"width":width,"height":1000})
                    prior_notifications = report["notification_gets"]
                    page.goto(ORIGIN+overview,wait_until="networkidle")
                    rows = page.locator(".ko-proposal")
                    expect(rows).to_have_count(5)
                    expect(page.locator("[data-ko-summary-count]")).to_have_text("5件")
                    expect(page.locator(".ko-proposal > .ko-priority")).to_have_text(["高","中","低"])
                    for badge_index in range(3):
                        expect(page.locator(".ko-proposal > .ko-priority").nth(badge_index)).to_be_visible()
                    require(rows.evaluate_all("els => els.map(e => e.dataset.proposalId)") == [identities[i][0] for i in expected_order], "Proposal order or identity changed")
                    require("未評価" not in page.locator("#ko-ai").inner_text(), "Fourth classification visible")
                    require(report["notification_gets"] > prior_notifications, "Ordinary notification polling not observed")
                    expect(page.locator("body")).to_have_attribute("data-priority-preview","false")
                    for row_index,item_index in enumerate(expected_order):
                        row = rows.nth(row_index); item = items[item_index]
                        expect(row.locator(".ko-proposal-heading strong")).to_have_text(item["target"])
                        expect(row.locator(".ko-proposal-action")).to_have_text(item["action"])
                        link = row.locator(".ko-proposal-detail")
                        expected_url = ORIGIN + analysis + "#proposal=" + quote(identities[item_index][0],safe="")
                        expect(link).to_have_attribute("href",expected_url)
                        expect(link).to_be_visible()
                        require(link.evaluate("e => e.getBoundingClientRect().height >= 44"),"Detail touch target too small")
                        if item_index in (0,2):
                            expect(row).to_have_attribute("data-priority-data-state","invalid")
                            expect(row.locator(".ko-priority")).to_have_count(0)
                            expect(row.locator('[aria-label^="対応優先度："]')).to_have_count(0)
                            expect(row.locator(".ko-proposal-data-state")).to_have_text(DATA_STATE)
                            expect(row.locator(".ko-proposal-data-state")).to_be_visible()
                            expect(row.locator(".ko-badge")).to_have_text("対応中" if item_index==2 else "採用")
                        else:
                            expect(row.locator(".ko-proposal-data-state")).to_have_count(0)
                    require(page.locator("#ko-ai").evaluate("e => e.scrollWidth <= e.clientWidth + 1"),"Proposal panel overflow")
                    require(page.locator(".ko-proposal-data-state").evaluate_all("els => els.every(e => e.scrollWidth <= e.clientWidth + 1)"),"Data state text overflow")
                    page.screenshot(path=str(output/f"overview-data-state-{width}.png"),full_page=True)
                    # Both malformed proposals retain an executable exact detail
                    # destination at both widths; no source/freshness guard bypass.
                    for item_index in (0,2):
                        page.goto(ORIGIN+overview,wait_until="networkidle")
                        link = page.locator(f'.ko-proposal[data-proposal-id="{identities[item_index][0]}"] .ko-proposal-detail')
                        expected_url = link.get_attribute("href")
                        with page.expect_navigation(wait_until="domcontentloaded"):
                            link.click()
                        dialog = page.locator(".ka-reference-drawer")
                        expect(dialog).to_be_visible()
                        require(page.url == expected_url,"Detail target changed")
                        expect(dialog.locator("#ka-reference-drawer-title")).to_have_text(items[item_index]["target"])
                        expect(dialog.locator(".ka-drawer-summary-action p")).to_have_text(items[item_index]["action"])
                        page.get_by_role("button",name="提案の詳細を閉じる",exact=True).click()
                        expect(dialog).to_be_hidden()
                    report["cases"].append(f"ORDINARY {width}: three valid badges, invalid/null data-state-only, original order/action/feedback and both exact details")
                assert_saved_unchanged()
                allowed_sql = {("UPDATE","company"),("INSERT","inspection_plan_alert_run"),("UPDATE","inspection_plan_alert_run")}
                require(all(w["endpoint"] in notification_endpoints and (w["verb"],w["table"]) in allowed_sql for w in report["database_mutations"]),"Unexpected write outside normal notification maintenance")
                require(not report["page_errors"] and not report["non_get_requests"] and not report["blocked_external_requests"] and not report["failed_gets"],"Browser request or script failure")
                report.update(saved_state_unchanged=True,normal_notification_polling_observed=True,browser_acceptance_passed=True,status="PASS")
                return 0
            except Exception:
                if "page" in locals() and not page.is_closed():
                    page.screenshot(path=str(output/"failure.png"),full_page=True)
                raise
            finally:
                browser.close()
    except Exception as error:
        report.update(status="FAILED_OR_BLOCKED",error_type=type(error).__name__)
        if isinstance(error,AssertionError):report["safe_failure"]=str(error)
        raise
    finally:
        if listening:event.remove(m.db.engine,"before_cursor_execute",track_write)
        if setup_started:case.tearDown()
        if class_started:case.tearDownClass()
        report["finished_utc"]=datetime.now(timezone.utc).isoformat()
        (output/("preflight-result.json" if args.preflight_only else "browser-result.json")).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
        print(json.dumps(report,ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
