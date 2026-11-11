#!/usr/bin/env python3
"""Exact-candidate browser coverage for the connected normal-screen fixture.

Fixture POSTs are real Flask requests. Browser access is same-origin GET-only,
bridged in-process: it cannot send writes or connect to a live application.
"""
import argparse
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ORIGIN = 'http://127.0.0.1:8765'


def require(value, message):
    if not value:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--case', choices=('normal', 'instruction', 'recheck', 'invoice'), required=True)
    parser.add_argument('--chromium', type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preflight-only', action='store_true')
    mode.add_argument('--run-browser', action='store_true')
    args = parser.parse_args()
    require(os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED') == '1', 'Isolated wrapper required')
    require(os.environ.get('DATABASE_URL') == 'sqlite:///:memory:', 'Disposable DB required')
    repo, out = args.repo.resolve(), args.artifacts.resolve()
    sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    tree = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
    require(sha == args.expected_sha, 'Exact candidate SHA mismatch')
    require(not subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True).strip(), 'Clean candidate required')
    if args.run_browser:
        require(args.chromium and args.chromium.is_file(), 'Authorized Chromium path required')
    os.chdir(repo); sys.path[:0] = [str(repo), str(repo / 'tests')]
    out.mkdir(parents=True, exist_ok=True)
    import test_video_connected_flows as flows
    case = flows.ConnectedInvoiceFlowTests() if args.case == 'invoice' else flows.ConnectedInspectionFlowTests()
    started = setup = False
    report = dict(candidate_sha=sha, candidate_tree=tree, scenario=args.case,
        status='FAILED', fixture_only=True, production_accessed=False, browser_started=False,
        browser_acceptance_passed=False, page_errors=[], blocked_requests=[], failed_gets=[],
        cases=[], started_utc=datetime.now(timezone.utc).isoformat())
    try:
        case.setUpClass(); started = True; case.setUp(); setup = True
        if args.case == 'invoice':
            case.test_invoice_confirm_correct_resend_and_late_cost_stay_one_actual()
            m, app, db = case.m, case.m.app, case.m.db
            actual = case.actuals()[0]
            invoice_record = m.VehicleMaintenanceRecord.query.one()
            original_hash = json.loads(invoice_record.invoice_details_json)['source']['sha256']
            report['cases'].append('Real upload/worker/confirmation, correction, duplicate refusal and late cost review; one actual')
            paths = [f'/vehicle/karte/{case.vehicle.id}/{tail}' for tail in
                     ('history', 'costs?year=' + str(flows.today().year), 'parts', 'analysis')]
        else:
            m, app, db = case.models, case.app, case.db
            case.begin_priority(); case.configure_dashboard()
            case.decide('運行不可' if args.case == 'instruction' else '運行可')
            if args.case == 'recheck': case.repair_priority()
            bundle, saved = case.generate('registered_operation_instruction' if args.case == 'instruction' else 'inspection_defect')
            score = {'normal': 50, 'instruction': 60, 'recheck': 25}[args.case]
            item = case.three_views(score, bundle, saved)
            analysis = case.current_analysis()
            expected_order = analysis['priority_order']
            proposal_id = item['proposal_id']
            badge = ('高' if score == 60 else '中') + f' · {score}点'
            report['cases'].append(f'Real inspection submit/human decision; unfrozen normal projection and 3-page identity/order/{score} score')
            paths = ['/', f'/vehicle/karte/{case.vehicle.id}', f'/vehicle/karte/{case.vehicle.id}/analysis']
            notice = m.Notification.query.filter_by(company_code='A', target_username='admin').order_by(m.Notification.id).first()
            require(notice is not None, 'Inspection notification missing')
            # Mark only this synthetic notice read through the real GET target
            # before the protected baseline. Reopening it in-browser stays GET-only;
            # unread auto-mark POST behavior is not covered by this harness.
            landing = case.client.get(f'/notifications/{notice.id}/open', follow_redirects=True)
            require(landing.status_code == 200 and notice.read, 'Notification target did not open')
            notice_target = landing.request.path
        root = Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
        require(db.engine.url.drivername == 'sqlite' and Path(db.engine.url.database).resolve().is_relative_to(root), 'Wrong fixture database')

        def snapshot():
            db.session.expire_all()
            # Normal GET updates last-selected vehicle, usage and periodic notice
            # bookkeeping; business records and saved analysis remain protected.
            exclude = {'company_usage_summary', 'company', 'inspection_plan_alert_run', 'user'}
            return {t.name: [tuple(row) for row in db.session.execute(t.select().order_by(*t.primary_key.columns))]
                    for t in db.metadata.sorted_tables if t.name not in exclude}
        before = snapshot()

        def get(path):
            response = case.client.get(path)
            if response.status_code >= 400:
                report['failed_gets'].append(dict(path=path, status=response.status_code))
            return response
        for path in paths:
            require(get(path).status_code == 200, 'Ordinary screen GET failed')
        require(snapshot() == before, 'GET changed protected saved data')
        if args.preflight_only:
            report['status'] = 'PREFLIGHT_PASS_BROWSER_NOT_RUN'
            return 0
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(args.chromium.resolve()))
            report.update(browser_started=True, browser_version=browser.version)
            try:
                context = browser.new_context(service_workers='block')
                def bridge(route):
                    request = route.request; parsed = urlsplit(request.url)
                    if f'{parsed.scheme}://{parsed.netloc}' != ORIGIN or request.method != 'GET':
                        report['blocked_requests'].append(dict(method=request.method, host=parsed.hostname, path=parsed.path))
                        route.abort(); return
                    response = get(parsed.path + ('?' + parsed.query if parsed.query else ''))
                    headers = {key: value for key, value in response.headers.items()
                               if key.lower() not in {'content-length', 'transfer-encoding', 'connection', 'set-cookie'}}
                    route.fulfill(status=response.status_code, headers=headers, body=response.get_data())
                context.route('**/*', bridge)
                page = context.new_page()
                page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
                for width, height in ((1440, 900), (390, 780), (320, 640)):
                    page.set_viewport_size(dict(width=width, height=height))
                    if args.case == 'invoice':
                        # Use the rendered history link, then the rendered source
                        # download. Do not fabricate a direct document navigation.
                        page.goto(ORIGIN + paths[0], wait_until='networkidle')
                        page.locator(f'.vehicle-history-record-link[href*="/maintenance/{invoice_record.id}"]').first.click()
                        expect(page.locator('.km-detail-panel')).to_contain_text('タイヤ交換（読取訂正）')
                        with page.expect_download() as transfer:
                            page.locator('.km-file-card[download]').first.click()
                        downloaded = transfer.value
                        require(downloaded.failure() is None, 'Original download failed')
                        require(hashlib.sha256(Path(downloaded.path()).read_bytes()).hexdigest() == original_hash, 'Original download changed')
                        report['cases'].append(f'Browser {width}: history -> same maintenance -> preserved original download')
                        for number, path in enumerate(paths):
                            page.goto(ORIGIN + path, wait_until='networkidle')
                            if '/history' in path: expect(page.locator('main')).to_contain_text('タイヤ交換（読取訂正）')
                            if '/costs' in path: expect(page.locator('main')).to_contain_text('163,000')
                            if '/parts' in path: expect(page.locator('main')).to_contain_text('タイヤ')
                            if '/analysis' in path:
                                expect(page.locator('.ka5-parts-panel')).to_contain_text('タイヤ')
                                expect(page.locator('.ka5-peer-panel')).to_be_visible()
                                expect(page.locator('.ka5-parts-table tbody tr')).to_have_count(1)
                            require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Invoice page overflow')
                            page.screenshot(path=str(out / f'invoice-{number}-{width}.png'), full_page=True)
                        page.go_back(wait_until='networkidle')
                        expect(page.locator('main')).to_contain_text('タイヤ')
                        page.go_forward(wait_until='networkidle')
                        expect(page.locator('.ka5-parts-panel')).to_contain_text('タイヤ')
                    else:
                        page.goto(ORIGIN + '/notifications', wait_until='networkidle')
                        page.locator(f'a.js-notification-open[href^="/notifications/{notice.id}/open"]').first.click()
                        page.wait_for_load_state('networkidle')
                        require(urlsplit(page.url).path == notice_target, 'Notification opened a different source')
                        expect(page.locator('main')).to_contain_text('ブレーキ')
                        report['cases'].append(f'Browser {width}: existing notification -> its real inspection target')
                        page.goto(ORIGIN + '/', wait_until='networkidle')
                        panel = page.locator('.dashboard-attention-panel').first
                        expect(page.locator('.dashboard-safety-attention')).to_contain_text('動画連続受入の安全確認')
                        links = panel.locator('tbody a[href*="#proposal="]')
                        require([urlsplit(x).fragment.split('=', 1)[1] for x in links.evaluate_all('(nodes)=>nodes.map(n=>n.href)')] == expected_order, 'Dashboard order mismatch')
                        expect(panel.locator('tbody tr').filter(has=page.locator(f'a[href$="#proposal={proposal_id}"]')).locator('.dashboard-attention-priority')).to_have_text(badge)
                        page.screenshot(path=str(out / f'dashboard-{width}.png'), full_page=True)
                        page.goto(ORIGIN + f'/vehicle/karte/{case.vehicle.id}', wait_until='networkidle')
                        expect(page.locator('#ko-ai .ko-proposal')).to_have_count(3)
                        require(page.locator('#ko-ai .ko-proposal').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.proposalId)') == expected_order, 'Overview order mismatch')
                        row = page.locator(f'#ko-ai .ko-proposal[data-proposal-id="{proposal_id}"]')
                        expect(row.locator('.ko-priority')).to_have_text(badge)
                        row.locator('.ko-proposal-detail').click()
                        drawer = page.locator('.ka-reference-drawer')
                        expect(drawer).to_be_visible()
                        expect(drawer.locator('.ka-drawer-priority-row .ka-ai-priority')).to_have_text(badge)
                        expect(page.locator('.ka5-peer-panel')).to_be_visible()
                        expect(page.locator('.ka5-parts-panel')).to_be_visible()
                        page.screenshot(path=str(out / f'analysis-detail-{width}.png'), full_page=True)
                        page.keyboard.press('Escape'); expect(drawer).to_be_hidden()
                        page.locator('.ka-reference-detail-button').first.click(); expect(drawer).to_be_visible()
                        drawer.get_by_role('button', name='提案の詳細を閉じる').click(); expect(drawer).to_be_hidden()
                        page.go_back(wait_until='networkidle')
                        page.go_forward(wait_until='networkidle')
                        require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Priority page overflow')
                    report['cases'].append(f'Browser connected normal screens, width {width}, navigation and saved records')
                require(not report['page_errors'] and not report['failed_gets'] and not report['blocked_requests'], 'Browser request or script failure')
                require(snapshot() == before, 'Browser GET changed protected saved data')
                report.update(status='PASS', browser_acceptance_passed=True, protected_records_unchanged=True)
                return 0
            except Exception:
                if 'page' in locals() and not page.is_closed(): page.screenshot(path=str(out / 'failure.png'), full_page=True)
                raise
            finally:
                browser.close()
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (out / 'browser-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        if setup: case.tearDown(); case.doCleanups()
        if started: case.tearDownClass()
        print(json.dumps(report, ensure_ascii=False, default=str))


if __name__ == '__main__':
    raise SystemExit(main())
