#!/usr/bin/env python3
"""Synthetic-only, fixed-source condition-preview Chromium acceptance.

Preparation only until an authorized execution environment contains the fixed
candidate. Flask GET bridge; no listener, production access or network DB.
"""
import argparse
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

CANDIDATE_SHA = "f0005bb4a7fe7b8674f4dfe1f319228ac4de1089"
CANDIDATE_TREE = "b4cddb88a6137855d0b0a03a579b0f2106f24592"
ORIGIN = "http://127.0.0.1:8765"
SCENARIOS = (
    ("calendar-and", "all", [{"metric":"period_days","value":45},{"metric":"period_months","value":1}], "2026-12-15"),
    ("calendar-or", "any", [{"metric":"period_days","value":45},{"metric":"period_months","value":1}], "2026-11-30"),
    ("mixed-and", "all", [{"metric":"distance_km","value":1000},{"metric":"period_months","value":1}], None),
    ("single-month", "single", [{"metric":"period_months","value":1}], "2026-11-30"),
)
RELATIONS = {"all":"すべての条件（AND）", "any":"いずれかの条件（OR）", "single":"単独条件"}
UNITS = {"km":"km", "days":"日", "calendar_months":"暦月"}


def require(condition, message):
    if not condition: raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo",type=Path,required=True)
    parser.add_argument("--artifacts",type=Path,required=True)
    parser.add_argument("--chromium",type=Path)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preflight-only",action="store_true")
    modes.add_argument("--run-browser",action="store_true")
    args=parser.parse_args();repo=args.repo.resolve();output=args.artifacts.resolve()
    output.mkdir(parents=True,exist_ok=True)
    require(not any(output.iterdir()), "Artifact directory must be new and empty")
    report=dict(candidate_sha=None,candidate_tree=None,started_utc=datetime.now(timezone.utc).isoformat(),
        fixture_only=True,production_accessed=False,browser_started=False,browser_acceptance_passed=False,
        transport="in-process real Flask GET responses",cases=[],database_mutations=[],page_errors=[],
        blocked_external_requests=[],non_get_requests=[],failed_gets=[],intentional_fetch_failures=0,cleanup_errors=[])
    class_started=False;setup_started=False;listening=False;primary_failure=False
    def cleanup(label, function):
        try:
            function()
        except Exception as error:
            report["cleanup_errors"].append(dict(stage=label,error_type=type(error).__name__))
    try:
        require(os.environ.get("DKSS_BROWSER_ACCEPTANCE_ISOLATED")=="1","Use isolated runner")
        require(os.environ.get("DATABASE_URL")=="sqlite:///:memory:","No external DB")
        sha=subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()
        tree=subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD^{tree}"],text=True).strip()
        report.update(candidate_sha=sha,candidate_tree=tree)
        require(sha==CANDIDATE_SHA and tree==CANDIDATE_TREE,"Wrong fixed candidate")
        require(not subprocess.check_output(["git","-C",str(repo),"status","--porcelain","--untracked-files=all"],text=True).strip(),"Candidate must be clean")
        if args.run_browser:require(args.chromium and args.chromium.is_file(),"Explicit installed Chromium required")
        os.chdir(repo);sys.path[:0]=[str(repo),str(repo/"tests")]
        from test_priority_timing_preview import PriorityTimingPreviewTests
        from vehicle_priority_timing_sources import timing_snapshot_hash, reference_snapshot_hash
        from sqlalchemy import event
        report.update(candidate_sha=sha,candidate_tree=tree)
        case=PriorityTimingPreviewTests()
        case.setUpClass();class_started=True
        with ExitStack() as stack:
            if args.run_browser:
                from importlib.metadata import version
                from playwright.sync_api import sync_playwright,expect
                p=sync_playwright().start()
                stack.callback(lambda: cleanup("playwright.stop",p.stop))
                browser=p.chromium.launch(headless=True,executable_path=str(args.chromium.resolve()))
                stack.callback(lambda: cleanup("browser.close",browser.close))
                report.update(browser_started=True,browser_version=browser.version,
                    playwright_version=version("playwright"),python_version=sys.version.split()[0])
            for scenario,relation,criteria,expected_date in SCENARIOS:
                case.setUp();setup_started=True;m=case.m
                try:
                    require(m.db.engine.url.drivername=="sqlite","Unexpected DB driver")
                    require(Path(m.db.engine.url.database).resolve().is_relative_to(Path(os.environ["DKSS_VALIDATION_TMP"]).resolve()),"DB outside disposable root")
                    state,bundle,fixture,key=case.condition_fixture(relation,criteria)
                    value=fixture.timing_conditions[key]
                    # Synthetic host input only: preserve a long original quote,
                    # including markup-looking text, with matching reference hashes.
                    quote="【合成条件・実車の規定ではありません】元の条件を省略せず表示します。\n"+json.dumps(criteria,ensure_ascii=False)+"\n<img src=x onerror=window.__syntheticInjected=1>\n"+("SYNTHETIC_LONG_TOKEN_"*12)
                    rule=deepcopy(value.rule);rule["source_quote"]=quote
                    refs={rid:replace(ref,quote=quote) for rid,ref in fixture.references.items()}
                    bindings=tuple(replace(rb,reference_hash=reference_snapshot_hash(refs[rb.reference_id])) for rb in value.binding.reference_bindings)
                    value=replace(value,rule=rule,binding=replace(value.binding,
                        snapshot_hash=timing_snapshot_hash(rule,value.timing),reference_bindings=bindings))
                    fixture=replace(fixture,references=refs,timing_conditions={key:value})
                    m.db.session.add(m.VehicleAnalysisFeedback(company_code="TEST",vehicle_record_id=case.vehicle.id,
                        proposal_key=key,proposal_revision=value.proposal_revision,status="in_progress",comment="合成・保持確認",
                        created_by="admin",created_at="2026-11-10T00:00:00Z",snapshot_json="{}"))
                    m.db.session.commit();state_id=state.id;saved_json=state.result_json
                    def feedback():return [(x.id,x.proposal_key,x.proposal_revision,x.status,x.comment,x.snapshot_json) for x in m.VehicleAnalysisFeedback.query.order_by(m.VehicleAnalysisFeedback.id).all()]
                    saved_feedback=feedback()
                    saved_settings=m.User.query.filter_by(company_code="TEST",username="admin").one().dashboard_settings_json
                    active=["outside_request"]
                    def track(_conn,_cur,statement,_params,_ctx,_many):
                        parts=statement.lstrip().split(None,1);verb=parts[0].upper() if parts else ""
                        if verb in {"INSERT","UPDATE","DELETE","CREATE","ALTER","DROP","REPLACE"}:
                            match=re.match(r'\s*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|(?:CREATE|ALTER|DROP)\s+(?:TABLE|INDEX))\s+["`]?([A-Za-z_][A-Za-z_0-9]*)',statement,re.I)
                            report["database_mutations"].append(dict(scenario=scenario,endpoint=active[0],verb=verb,table=match.group(1) if match else "UNIDENTIFIED"))
                    event.listen(m.db.engine,"before_cursor_execute",track);listening=True
                    def request(path):
                        previous=active[0]
                        try:
                            active[0]=m.app.url_map.bind("localhost").match(urlsplit(path).path,method="GET")[0]
                            response=case.client.get(path)
                            if response.status_code>=400:report["failed_gets"].append(dict(endpoint=active[0],status=response.status_code))
                            return response
                        finally:active[0]=previous
                    case.install(replace(fixture,timing_conditions={}))
                    baseline=request(case.url).json
                    case.install(fixture);data=request(case.url).json
                    require(data["priority_preview"]["status"]=="available","Priority fixture unavailable")
                    require(data["priority_timing_conditions"]["status"]=="available","Condition fixture unavailable")
                    require(data["analysis"]==baseline["analysis"] and data["sources"]==baseline["sources"],"Conditions altered score/order/source projection")
                    entry=data["priority_timing_conditions"]["entries"][0];group=entry["condition_group"]
                    require(entry["relation"]==relation and group["source_quote"]==quote,"Original quote/relation changed")
                    require(group["calendar_threshold_on"]==expected_date,"Group calendar date wrong")
                    require(entry["scoring_input_emitted"]==(relation!="all"),"AND emitted scoring input")
                    if any(c["metric"]=="period_months" for c in group["conditions"]):
                        c=next(c for c in group["conditions"] if c["metric"]=="period_months")
                        require(c["threshold"]=="1" and c["unit"]=="calendar_months" and c["quantity_unit"]=="days" and c["due_on"]=="2026-11-30" and c["remaining_quantity"]=="20","Month/day fixture contract wrong")
                    bad_refs={rid:replace(ref,version="different-version") for rid,ref in refs.items()}
                    stale_fixture=replace(fixture,references=bad_refs)
                    case.install(stale_fixture);blocked=request(case.url).json
                    require(blocked["priority_timing_conditions"]["status"]=="blocked" and blocked["priority_timing_conditions"]["entries"]==[],"Version mismatch not blocked")
                    require(blocked["analysis"]==data["analysis"],"Version mismatch changed valid score")
                    case.install(fixture)
                    url=f"/vehicle/karte/{case.vehicle.id}/analysis?priority_preview=1"
                    require(request(url).status_code==200,"Preview document failed")
                    if args.run_browser:
                        context=browser.new_context(viewport={"width":1440,"height":1000},service_workers="block")
                        try:
                            fail_next=[False]
                            def bridge(route):
                                req=route.request;parsed=urlsplit(req.url)
                                if f"{parsed.scheme}://{parsed.netloc}"!=ORIGIN:
                                    report["blocked_external_requests"].append(parsed.hostname or "unknown");route.abort();return
                                if req.method!="GET":
                                    report["non_get_requests"].append(dict(method=req.method,path=parsed.path));route.abort();return
                                if fail_next[0] and parsed.path.endswith("/analysis/result"):
                                    fail_next[0]=False;report["intentional_fetch_failures"]+=1;route.abort("failed");return
                                response=request(parsed.path+("?"+parsed.query if parsed.query else ""))
                                headers={k:v for k,v in response.headers.items() if k.lower() not in {"content-length","transfer-encoding","connection","set-cookie"}}
                                route.fulfill(status=response.status_code,headers=headers,body=response.get_data())
                            context.route("**/*",bridge)
                            page=context.new_page();page.clock.install()
                            page.on("pageerror",lambda error:report["page_errors"].append(str(error)))
                            for width in (1440,390):
                                page.set_viewport_size({"width":width,"height":1000})
                                page.goto(ORIGIN+url,wait_until="networkidle")
                                section=page.locator(".priority-timing-preview")
                                expect(section).to_have_count(1);expect(section).to_be_visible()
                                expect(section.locator(".priority-timing-source-quote")).to_be_visible()
                                require(section.locator(".priority-timing-source-quote").text_content()==quote,"Original quote not preserved as text")
                                expect(section.locator("img,script")).to_have_count(0)
                                require(page.evaluate("window.__syntheticInjected === undefined"),"Markup executed")
                                expect(section).to_contain_text(RELATIONS[relation])
                                expect(section.locator(".priority-timing-disclaimer")).to_contain_text("点数・区分・並び順に連動していません")
                                rows=section.locator(".priority-timing-condition");expect(rows).to_have_count(len(group["conditions"]))
                                for index,c in enumerate(group["conditions"]):
                                    row=rows.nth(index);expect(row).to_be_visible()
                                    expect(row).to_contain_text(f'条件値：{c["threshold"]} {UNITS[c["unit"]]}')
                                    expect(row).to_contain_text(f'経過量：{c["elapsed_quantity"]} {UNITS[c["quantity_unit"]]} / 残量：{c["remaining_quantity"]} {UNITS[c["quantity_unit"]]} / 超過量：{c["excess_quantity"]} {UNITS[c["quantity_unit"]]}')
                                    expect(row).to_contain_text(f'起算日：{c["baseline_on"]} / 記録基準日：{c["reference_on"]}')
                                    if c["due_on"]:expect(row).to_contain_text(f'条件の算出日：{c["due_on"]}')
                                if expected_date:expect(section).to_contain_text(f"条件全体の暦上の成立日：{expected_date}")
                                else:
                                    expect(section).to_contain_text("条件全体の暦上の成立日は算出していません")
                                    require("条件全体の暦上の成立日：" not in section.inner_text(),"Mixed distance fabricated a calendar date")
                                require(section.evaluate("e => e.scrollWidth <= e.clientWidth + 1"),"Condition panel overflow")
                                require(section.locator(".priority-timing-source-quote").evaluate("e => e.scrollWidth <= e.clientWidth + 1"),"Original quote overflow")
                                page.locator(".priority-preview-card").screenshot(path=str(output/f"{scenario}-{width}.png"))
                            # One representative live refresh cycle verifies stale
                            # removal, restore, and interrupted-fetch recovery without
                            # mutating response/DOM or weakening the real API guard.
                            if scenario=="calendar-and":
                                badge=page.locator(".priority-preview-card .priority-preview-badge").inner_text()
                                def tick():page.clock.fast_forward(60010)
                                case.install(stale_fixture);tick()
                                expect(page.locator('[data-condition-status="blocked"]')).to_be_visible()
                                expect(page.locator(".priority-timing-preview")).to_have_count(0)
                                expect(page.locator(".priority-preview-card .priority-preview-badge")).to_have_text(badge)
                                page.locator(".priority-preview").screenshot(path=str(output/"version-mismatch-390.png"))
                                case.install(fixture);tick();expect(page.locator(".priority-timing-preview")).to_have_count(1)
                                fail_next[0]=True;tick()
                                expect(page.locator(".priority-timing-preview")).to_have_count(0)
                                expect(page.locator(".priority-preview-card")).to_have_count(0)
                                expect(page.locator(".priority-preview-blocker")).to_be_visible()
                                tick();expect(page.locator(".priority-timing-preview")).to_have_count(1)
                                expect(page.locator(".priority-preview-card .priority-preview-badge")).to_have_text(badge)
                                report["cases"].append("Live refresh: reference-version mismatch removes only conditions; restore has no duplicate; interrupted GET clears stale score/conditions and recovers")
                        except Exception:
                            if "page" in locals() and not page.is_closed():
                                cleanup("failure.screenshot",lambda: page.screenshot(path=str(output/f"failure-{scenario}.png"),full_page=True))
                            raise
                        finally:cleanup("context.close",context.close)
                    final=request(case.url).json
                    require(final["analysis"]==data["analysis"],"Final score/order/ID/revision/action/feedback projection changed")
                    m.db.session.expire_all()
                    require(m.VehicleKarteAnalysis.query.get(state_id).result_json==saved_json,"Saved analysis changed")
                    require(feedback()==saved_feedback,"Saved feedback changed")
                    require(m.User.query.filter_by(company_code="TEST",username="admin").one().dashboard_settings_json==saved_settings,"Saved preference changed")
                    require(not report["database_mutations"],"Synthetic preview emitted SQL mutation")
                    report["cases"].append(f"{scenario}: original quote, exact condition facts and score/state invariants"+(" at 1440/390" if args.run_browser else " preflight only"))
                finally:
                    if listening:
                        cleanup("sql_listener.remove",lambda: event.remove(m.db.engine,"before_cursor_execute",track));listening=False
                    if setup_started:
                        cleanup("case.tearDown",case.tearDown);setup_started=False
            require(not report["page_errors"] and not report["blocked_external_requests"] and not report["non_get_requests"] and not report["failed_gets"],"Unexpected browser script/request failure")
            report.update(saved_state_unchanged=True,status="PASS" if args.run_browser else "PREFLIGHT_PASS_BROWSER_NOT_RUN",browser_acceptance_passed=bool(args.run_browser))
            return 0
    except Exception as error:
        primary_failure=True
        report.update(status="FAILED_OR_BLOCKED",error_type=type(error).__name__)
        if isinstance(error,AssertionError):report["safe_failure"]=str(error)
        raise
    finally:
        if class_started:cleanup("case.tearDownClass",case.tearDownClass)
        if report["cleanup_errors"]:
            report.update(status="FAILED_OR_BLOCKED",browser_acceptance_passed=False)
        report["finished_utc"]=datetime.now(timezone.utc).isoformat()
        (output/("browser-result.json" if args.run_browser else "preflight-result.json")).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
        print(json.dumps(report,ensure_ascii=False))
        if report["cleanup_errors"] and not primary_failure:
            raise RuntimeError("ACCEPTANCE_CLEANUP_FAILED")

if __name__=="__main__":raise SystemExit(main())
