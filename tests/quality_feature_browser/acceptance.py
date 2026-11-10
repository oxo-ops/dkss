#!/usr/bin/env python3
"""Exact-candidate UI acceptance using synthetic SQLite and a WSGI request bridge.

No HTTP listener, real login, external DB or production URL is used. Playwright
fulfils loopback requests through Flask's authenticated synthetic test client.
--preflight-only never launches a browser. Browser results are separate evidence.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

PUBLIC_SHA = "8d36d64aaa7080e9e53538cf4433a752024e5614"
FROZEN_TREE = "0425395f26bcdfdbd8f7f7e6216b283bdc77e06f"
ORIGIN = "http://127.0.0.1:8765"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--chromium", type=Path)
    parser.add_argument("--allow-identical-tree-preflight", action="store_true",
                        help="Fixture-only validation of a clean checkout with the identical frozen tree")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--run-browser", action="store_true")
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.artifacts.resolve()
    if args.run_browser:
        require(args.chromium is not None and args.chromium.is_file(), "Provide the installed Chromium executable explicitly")
    require(os.environ.get("DKSS_BROWSER_ACCEPTANCE_ISOLATED") == "1", "Use run-isolated.sh")
    require(os.environ.get("DATABASE_URL") == "sqlite:///:memory:", "No external DB allowed")
    actual_sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    actual_tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
    require(actual_tree == FROZEN_TREE, "Wrong frozen source tree")
    require(not args.allow_identical_tree_preflight or args.preflight_only, "Tree-only validation cannot launch a browser")
    require(actual_sha == PUBLIC_SHA or args.allow_identical_tree_preflight, "Wrong frozen public candidate SHA")
    require(not subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"], text=True).strip(), "Candidate worktree must be clean")
    output.mkdir(parents=True, exist_ok=True)
    os.chdir(repo)
    sys.path[:0] = [str(repo), str(repo / "tests")]
    from test_vehicle_priority_preview import VehiclePriorityPreviewTests, PreviewHTML
    from dkss_app.models import VehicleDocumentImportDraft, VehiclePeriodicInspectionRecord, VehicleDrivingReportRecord
    from vehicle_priority_assessment import Fact
    from dkss_app.analysis_feedback import vehicle_analysis_maintenance_value
    from dkss_app.priority_preview import snapshot_hash
    from sqlalchemy import event

    report = dict(candidate_sha=actual_sha, candidate_tree=actual_tree, frozen_public_sha=PUBLIC_SHA,
                  frozen_source_tree=FROZEN_TREE, source_tree_equal=True,
                  identical_tree_preflight=args.allow_identical_tree_preflight, started_utc=datetime.now(timezone.utc).isoformat(),
                  mode="preflight" if args.preflight_only else "real-browser", cases=[],
                  page_errors=[], blocked_external_requests=[], non_get_requests=[],
                  fixture_only=True, production_accessed=False, browser_started=False,
                  browser_acceptance_passed=False, transport="in-process Flask WSGI bridge")
    case = VehiclePriorityPreviewTests()
    class_started = setup_started = False
    try:
        case.setUpClass(); class_started = True
        case.setUp(); setup_started = True
        m = case.m
        # A disposable test DB created by the repository's own fixture.
        require(m.db.engine.url.drivername == "sqlite", "Unexpected DB driver")
        require(Path(m.db.engine.url.database).resolve().is_relative_to(Path(os.environ["DKSS_VALIDATION_TMP"]).resolve()), "Fixture DB outside disposable root")
        case.vehicle.model_code = "SYNTHETIC-MODEL"
        state, bundle, fixture = case.save_synthetic_analysis(("低", "中", "高", "中", "高", "低"))
        # The API-only fixture has source snapshots but no navigable links.
        # Build actual same-company record links with the application's serializer,
        # preserving saved proposals and intentionally stale fingerprints.
        expected_source_links = {}
        with m.app.test_request_context("/"):
            for source_id, source in bundle["sources"].items():
                record = m.VehicleMaintenanceRecord.query.filter_by(
                    id=int(source_id.split(":", 1)[1]), company_code="TEST",
                    vehicle_record_id=case.vehicle.id).one()
                saved_source = vehicle_analysis_maintenance_value(record)
                source.update(url=saved_source["url"], label=saved_source["label"])
                expected_source_links[source_id] = (saved_source["url"], record.content)
        state.result_json = json.dumps(bundle, ensure_ascii=False)
        fixture = replace(fixture, sources_hash=snapshot_hash(bundle["sources"]))
        first_key = next(iter(fixture.candidates))
        first_candidate = fixture.candidates[first_key]
        first_source = first_candidate.facts[0].source_ids[0]
        evidence = dict(fixture.evidence)
        evidence[first_source] = replace(evidence[first_source], kind="instruction", status="active")
        candidates = dict(fixture.candidates)
        candidates[first_key] = replace(first_candidate, facts=(Fact("operation_instruction_active", (first_source,), True),))
        case.install(replace(fixture, candidates=candidates, evidence=evidence))
        for row in m.VehicleMaintenanceRecord.query.all():
            row.status = "完了"
        for index in range(24):
            m.db.session.add(m.VehicleMaintenanceRecord(company_code="TEST", vehicle_record_id=case.vehicle.id,
                content=f"合成追加整備{index}", status="完了", entry_date="2026-11-10"))
        m.db.session.add(m.VehicleMaintenanceRecord(company_code="OTHER", vehicle_record_id=case.vehicle.id,
            content="PRIVATE_OTHER_COMPANY_SHOULD_NOT_APPEAR", status="完了", entry_date="2026-11-10"))
        source_bytes = b"SYNTHETIC BROWSER FIXTURE - NOT A REAL DOCUMENT"
        m.db.session.add(VehicleDocumentImportDraft(id="synthetic-browser-source", batch_id="synthetic-browser-batch",
            company_code="TEST", created_by_username="admin", document_type="inspection",
            source_filename="synthetic.txt", source_file=source_bytes,
            source_sha256=hashlib.sha256(source_bytes).hexdigest(), status="completed"))
        m.db.session.flush()
        m.db.session.add(VehiclePeriodicInspectionRecord(company_code="TEST", vehicle_record_id=case.vehicle.id,
            inspection_type="12か月点検", inspection_date="2026-11-10", content="合成定期点検",
            source_draft_id="synthetic-browser-source", source_record_index=0, created_by_username="admin"))
        m.db.session.add(VehicleDrivingReportRecord(company_code="TEST", vehicle_record_id=case.vehicle.id,
            operation_date="2026-11-10", content="合成安全運転日報",
            source_draft_id="synthetic-browser-source", source_record_index=1, created_by_username="admin"))
        other = m.Vehicle(company_code="TEST", chassis_number="SYNTHETIC-SECOND")
        m.db.session.add(other); m.db.session.flush()
        other_id = other.id
        m.db.session.add(m.Driver(company_code="TEST", employee_id="admin", name="Synthetic",
            vehicles_json=json.dumps([str(case.vehicle.id), str(other_id)])))
        first_revision = m.vehicle_analysis_proposal_ids(bundle["analysis"]["recommendations"][0])[1]
        m.db.session.add(m.VehicleAnalysisFeedback(company_code="TEST", vehicle_record_id=case.vehicle.id,
            proposal_key=first_key, proposal_revision=first_revision, status="in_progress", comment="合成・保持確認",
            created_by="admin", created_at="2026-11-10T00:00:00Z", snapshot_json="{}"))
        m.db.session.commit()
        state_id = state.id
        overview = f"/vehicle/karte/{case.vehicle.id}"
        analysis = overview + "/analysis"
        history = f"/master/vehicles/{case.vehicle.id}/karte/history"
        original_bytes = state.result_json
        original_ids = [m.vehicle_analysis_proposal_ids(p) for p in bundle["analysis"]["recommendations"]]
        feedback_before = [(r.proposal_key, r.proposal_revision, r.status, r.comment) for r in m.VehicleAnalysisFeedback.query.all()]

        # The fixture's signed test cookie was created for localhost. Let the
        # Flask client keep its original cookie domain; no cookie is exported.
        active_request = ["outside_request"]
        def request(path, method="GET", data=None, headers=None):
            parsed = urlsplit(path)
            try:
                endpoint, _values = m.app.url_map.bind("localhost").match(parsed.path, method=method)
            except Exception:
                endpoint = "unmatched_route"
            previous = active_request[0]
            active_request[0] = endpoint + (":preview" if parse_qs(parsed.query).get("priority_preview") == ["1"] else ":normal")
            try:
                return case.client.open(path, method=method, data=data, headers=headers or {})
            finally:
                active_request[0] = previous

        ordinary = request(analysis + "/result").json
        preview = request(analysis + "/result?priority_preview=1").json
        require(len(ordinary["analysis"]["recommendations"]) == 6, "Ordinary fixture missing proposals")
        require(ordinary["is_current"] is False, "Synthetic sentinel fingerprints must remain stale")
        require(preview["is_current"] is None, "Preview must not assert input freshness")
        linked_sources = {source_id for item in ordinary["analysis"]["recommendations"] for source_id in item["source_ids"]}
        require(linked_sources == set(expected_source_links), "Saved source coverage changed")
        for source_id in linked_sources:
            source = ordinary["sources"][source_id]
            expected_url, expected_content = expected_source_links[source_id]
            require(source["url"] == expected_url and source["label"], "Source navigation contract missing")
            parsed_source = urlsplit(source["url"])
            require(not parsed_source.scheme and not parsed_source.netloc and parsed_source.path.startswith("/"), "Source must be same-origin")
            evidence_response = request(source["url"])
            require(evidence_response.status_code == 200, "Saved source route failed")
            evidence_html = evidence_response.get_data(as_text=True)
            require(expected_content in evidence_html, "Saved source target record missing")
            require("PRIVATE_OTHER_COMPANY_SHOULD_NOT_APPEAR" not in evidence_html, "Saved source crossed company scope")
        report["saved_source_links_verified"] = len(linked_sources)
        report["ordinary_is_current"] = ordinary["is_current"]
        report["preview_is_current"] = preview["is_current"]
        require(preview["priority_preview"]["status"] == "available", "Preview fixture blocked")
        require({p["priority_preview"]["label"] for p in preview["analysis"]["recommendations"]} == {"高", "中", "低"}, "All three preview labels required")
        require([(p["proposal_id"], p["proposal_revision"]) for p in preview["analysis"]["recommendations"]] == original_ids, "Proposal identity changed")
        for path in [overview, analysis, overview + "?priority_preview=1", analysis + "?priority_preview=1", history]:
            response = request(path)
            require(response.status_code == 200, f"Fixture route failed: {path}")
            require("PRIVATE_OTHER_COMPANY_SHOULD_NOT_APPEAR" not in response.get_data(as_text=True), "Company boundary failed")
        history_inspection = request(history + "?category=inspection").get_data(as_text=True)
        history_other = request(history + "?category=other").get_data(as_text=True)
        require("合成定期点検" in history_inspection and "合成安全運転日報" in history_other, "Real persisted history fixture incomplete")
        preview_html = request(analysis + "?priority_preview=1").get_data(as_text=True)
        forms = [f for f in PreviewHTML(preview_html).forms if f.get("class") in ("ka-period-form", "ka7-peer-conditions")]
        require(len(forms) == 2, "Preview forms fixture missing")
        # Confirm the GET-navigation contract using the actual rendered pages.
        # Browser synchronization below must wait for these replacement documents.
        for registration in ("same_year", "all_years"):
            path = analysis + "?priority_preview=1&start_date=2026-01-01&end_date=2026-11-10&peer_registration=" + registration
            response = request(path)
            require(response.status_code == 200, "Preview navigation route failed")
            html = response.get_data(as_text=True)
            parsed = PreviewHTML(html)
            navigation_forms = [f for f in parsed.forms if f.get("class") in ("ka-period-form", "ka7-peer-conditions")]
            require(len(navigation_forms) == 2, "Preview replacement forms missing")
            for form in navigation_forms:
                require(form["fields"].get("priority_preview") == "1", "Replacement form lost preview")
                require(form["fields"].get("start_date") == "2026-01-01" and form["fields"].get("end_date") == "2026-11-10", "Replacement form lost dates")
            require('<details class="ka9-peer-settings"><summary>比較条件を変更</summary>' in html, "Synthetic no-peer form must start in a closed disclosure")
            require(any(link.get("class") == "vehicle-karte-tab" and link.get("href") == overview + "?priority_preview=1" for link in parsed.links), "Replacement page lost preview overview link")
        report["navigation_contract_preflight"] = "PASS: date/comparison GETs retain preview/dates; no-peer disclosure starts closed; overview link retained"
        report["cases"].append("PREFLIGHT: clean frozen source identity; synthetic persisted proposals/history; authenticated routes; six persisted same-company source links; stale freshness retained; three preview labels; identity and company scope")
        if args.preflight_only:
            report["status"] = "PREFLIGHT_PASS_BROWSER_NOT_RUN"
            return 0

        from importlib.metadata import version
        from playwright.sync_api import sync_playwright, expect
        report["python_version"] = sys.version.split()[0]
        report["playwright_version"] = version("playwright")
        writes = []
        report["database_mutations"] = writes
        def track_write(_connection, _cursor, statement, _parameters, _context, _many):
            verb = statement.lstrip().split(None, 1)[0].upper()
            if verb in {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "REPLACE"}:
                # Record only endpoint/action, operation and table identifier.
                # Never save SQL text, parameters, credentials or row values.
                match = re.match(r'\s*(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|(?:CREATE|ALTER|DROP)\s+(?:TABLE|INDEX))\s+["`]?([A-Za-z_][A-Za-z_0-9]*)', statement, re.I)
                writes.append(dict(action=active_request[0], verb=verb, table=match.group(1) if match else "UNIDENTIFIED"))

        with sync_playwright() as p:
            options = dict(headless=True)
            if args.chromium:
                options["executable_path"] = str(args.chromium.resolve())
            browser = p.chromium.launch(**options)
            report["browser_started"] = True
            report["browser_version"] = browser.version
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block")
                # No server socket: every app request invokes the real Flask
                # route through its synthetic test session in this process.
                def bridge(route):
                    req = route.request
                    parsed = urlsplit(req.url)
                    if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
                        report["blocked_external_requests"].append(f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
                        route.abort(); return
                    if req.method != "GET":
                        report["non_get_requests"].append(dict(method=req.method, path=parsed.path))
                        route.abort(); return
                    path = parsed.path + ("?" + parsed.query if parsed.query else "")
                    response = request(path)
                    headers = {k:v for k,v in response.headers.items()
                               if k.lower() not in {"content-length", "transfer-encoding", "connection", "set-cookie"}}
                    route.fulfill(status=response.status_code, headers=headers, body=response.get_data())
                context.route("**/*", bridge)
                page = context.new_page()
                page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                def visit(path):
                    page.goto(ORIGIN + path, wait_until="networkidle")
                def screenshot(name):
                    page.screenshot(path=str(output / (name + ".png")), full_page=True)
                for width in (1440, 1024, 390):
                    page.set_viewport_size({"width":width, "height":1000})
                    visit(overview)
                    page.locator(".ko-proposal").nth(4).wait_for()
                    require(page.locator(".ko-proposal").count() == 5, "Overview must show only five")
                    require(page.locator("[data-ko-summary-count]").inner_text() == "6件", "Saved total missing")
                    require(page.locator(".ko-proposal > .ko-priority").all_inner_texts() == ["高", "高", "中", "中", "低"], "Saved priority order wrong")
                    require(page.get_by_text("残り1件を分析で確認 →", exact=True).count() == 1, "Remaining link missing")
                    require(page.locator("#ko-ai").evaluate("e => e.scrollWidth <= e.clientWidth + 1"), "Proposal overflow")
                    require(page.locator(".ko-proposal-detail").first.evaluate("e => e.getBoundingClientRect().height >= 44"), "Small detail touch target")
                    screenshot(f"ordinary-{width}")
                report["cases"].append("VIDEO: five saved proposals, counts, order, touch target and layout at three widths")
                page.set_viewport_size({"width":1440, "height":1000})
                for index, close_by in ((4, "Escape"), (0, "button")):
                    visit(overview)
                    link = page.locator(".ko-proposal-detail").nth(index)
                    expected = link.get_attribute("href")
                    link.click()
                    close = page.get_by_role("button", name="提案の詳細を閉じる")
                    close.wait_for()
                    require(page.url == expected, "Wrong proposal destination")
                    if close_by == "Escape": page.keyboard.press("Escape")
                    else: close.click()
                    require(close.is_hidden(), "Detail did not close")
                    require("#proposal=" not in page.url, "Stale proposal hash")
                    page.go_back(wait_until="networkidle")
                    page.locator(".ko-proposal").nth(4).wait_for()
                    page.go_forward(wait_until="networkidle")
                    require("#proposal=" not in page.url, "Forward reopened stale detail")
                report["cases"].append("VIDEO: exact first/fifth proposal detail, Escape/Close, Back/Forward")
                visit(history + "?category=maintenance&page=2&per_page=10&start_date=2026-11-10&end_date=2026-11-10")
                for key, expected in (("",32),("inspection",1),("maintenance",30),("other",1)):
                    require(page.locator(f'a[data-category="{key}"] span').inner_text().strip() == str(expected), "Facet count wrong")
                require(page.locator(".vehicle-karte-history-table tbody tr").count() == 10, "Pagination page length wrong")
                page.locator('a[data-category="inspection"]').click()
                query = parse_qs(urlsplit(page.url).query)
                require("page" not in query and query.get("per_page") == ["10"] and query.get("start_date") == ["2026-11-10"], "Facet navigation lost filter/reset")
                require(page.locator(".vehicle-karte-history-table tbody tr").count() == 1, "Inspection facet wrong")
                page.go_back(wait_until="networkidle")
                require(parse_qs(urlsplit(page.url).query).get("page") == ["2"], "History back state lost")
                for width in (1440, 390):
                    page.set_viewport_size({"width":width,"height":1000})
                    visit(history)
                    require(page.locator(".vehicle-history-categories").evaluate("e => e.scrollWidth <= e.clientWidth + 1"), "Category overflow")
                    screenshot(f"history-{width}")
                report["cases"].append("HISTORY: persisted three-category rows, counts, pagination, filter retention, Back and narrow width")

                # From here every served application GET must remain read-only.
                before_settings = m.User.query.filter_by(company_code="TEST", username="admin").one().dashboard_settings_json
                event.listen(m.db.engine, "before_cursor_execute", track_write)
                try:
                    for width in (1440, 1024, 390):
                        page.set_viewport_size({"width":width,"height":1000})
                        visit(overview + "?priority_preview=1")
                        page.locator(".ko-proposal[data-priority-preview]").nth(4).wait_for()
                        badges = page.locator(".priority-preview-badge")
                        require(badges.count() == 5, "Preview badge count wrong")
                        require(badges.first.inner_text().startswith("高 · 60点"), "Preview order/score wrong")
                        require(page.locator("#ko-ai").evaluate("e => e.scrollWidth <= e.clientWidth + 1"), "Preview overflow")
                        require(page.locator("[data-note-edit]").count() == 0, "Note edit exposed in preview")
                        screenshot(f"priority-{width}")
                    page.locator(".ko-proposal-detail").first.click()
                    page.locator(".priority-preview-card").nth(5).wait_for()
                    require(parse_qs(urlsplit(page.url).query).get("priority_preview") == ["1"], "Detail lost preview")
                    require(page.locator(".priority-preview-disclaimer").count() == 6, "Disclaimer missing")
                    require(page.locator(".priority-preview-gaps").count() == 6, "Evidence missing display absent")
                    require(page.get_by_text("運行可否は人が判断してください。", exact=False).count() > 0, "Human decision notice absent")
                    page.locator(".ka-period-form input[name=start_date]").fill("2026-01-01")
                    page.locator(".ka-period-form input[name=end_date]").fill("2026-11-10")
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        page.locator(".ka-period-form button[type=submit]").click()
                    period_query = parse_qs(urlsplit(page.url).query)
                    require(period_query.get("priority_preview") == ["1"], "Period lost preview")
                    require(period_query.get("start_date") == ["2026-01-01"] and period_query.get("end_date") == ["2026-11-10"], "Period dates were not submitted")
                    expect(page.locator(".priority-preview-card")).to_have_count(6)
                    peer_details = page.locator("details.ka9-peer-settings")
                    expect(peer_details).to_have_count(1)
                    peer_summary = peer_details.locator("summary")
                    expect(peer_summary).to_be_visible()
                    if peer_details.get_attribute("open") is None:
                        peer_summary.click()
                    require(peer_details.get_attribute("open") is not None, "Comparison disclosure did not open")
                    peer_select = peer_details.locator('select[name=peer_registration]')
                    expect(peer_select).to_be_visible()
                    peer_select.select_option("all_years")
                    expect(peer_select).to_have_value("all_years")
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        page.locator('.ka7-peer-conditions button[type=submit]').click()
                    comparison_query = parse_qs(urlsplit(page.url).query)
                    require(comparison_query.get("priority_preview") == ["1"], "Comparison lost preview")
                    require(comparison_query.get("peer_registration") == ["all_years"], "Comparison choice was not submitted")
                    require(comparison_query.get("start_date") == ["2026-01-01"] and comparison_query.get("end_date") == ["2026-11-10"], "Comparison lost dates")
                    expect(page.locator(".priority-preview-card")).to_have_count(6)
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        page.locator(f'a.vehicle-karte-tab[href="{overview}?priority_preview=1"]').click()
                    page.locator(".ko-proposal").nth(4).wait_for()
                    switch = page.locator(f'a.karte-vehicle-switcher-link[href*="/vehicle/karte/{other_id}"]').first
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        switch.click()
                    require(parse_qs(urlsplit(page.url).query).get("priority_preview") == ["1"], "Vehicle switch lost preview")
                    require(urlsplit(page.url).path == f"/vehicle/karte/{other_id}", "Vehicle switch target wrong")
                    expect(page.locator("[data-ko-summary-count]")).to_have_text("試行表示不可")
                    page.go_back(wait_until="networkidle")
                    page.locator(".ko-proposal").nth(4).wait_for()
                    require(not writes, "Preview emitted database mutation")
                finally:
                    event.remove(m.db.engine, "before_cursor_execute", track_write)
                m.db.session.expire_all()
                require(m.User.query.filter_by(company_code="TEST", username="admin").one().dashboard_settings_json == before_settings, "Preview changed last vehicle setting")
                require(m.VehicleKarteAnalysis.query.get(state_id).result_json == original_bytes, "Stored analysis changed")
                require([(r.proposal_key,r.proposal_revision,r.status,r.comment) for r in m.VehicleAnalysisFeedback.query.all()] == feedback_before, "Feedback changed")
                # Normal return is a separate phase after the complete preview
                # listener/saved-state assertions. Normal notification maintenance
                # is deliberately not described as read-only.
                with page.expect_request(lambda req: urlsplit(req.url).path == "/api/notifications/unread-count") as normal_poll:
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        page.get_by_role("link", name="試行表示を終了して通常表示へ", exact=True).click()
                require(normal_poll.value.method == "GET", "Normal return did not resume notification GET")
                expect(page.locator("body")).to_have_attribute("data-priority-preview", "false")
                require("priority_preview" not in parse_qs(urlsplit(page.url).query), "Normal return retained preview")
                page.locator(".ko-proposal").nth(4).wait_for()
                report["cases"].append("NORMAL RETURN: explicit exit restores ordinary document and notification polling")
                require(not report["non_get_requests"], "Unexpected write request")
                require(not report["page_errors"], "Browser script error")
                report["cases"].append("PRIORITY: three labels, score/evidence separate, narrow width, period/comparison/vehicle navigation, blocked missing fixture, zero DB writes and preserved saved state")
                report["browser_acceptance_passed"] = True
                report["status"] = "PASS"
                return 0
            except Exception:
                if "page" in locals() and not page.is_closed():
                    try:
                        screenshot("failure")
                    except Exception:
                        pass
                raise
            finally:
                browser.close()
    except Exception as error:
        report["status"] = "FAILED_OR_BLOCKED"
        report["error_type"] = type(error).__name__
        # Assertions use fixed safe labels; avoid raw browser errors/URLs.
        if isinstance(error, AssertionError): report["safe_failure"] = str(error)
        raise
    finally:
        if setup_started: case.tearDown()
        if class_started: case.tearDownClass()
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        filename = "preflight-result.json" if args.preflight_only else "browser-result.json"
        (output / filename).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
