#!/usr/bin/env python3
"""Synthetic dashboard rendering and expansion in real Chromium, without a server."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

ORIGIN = 'http://127.0.0.1:8765'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--artifacts', required=True, type=Path)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--chromium', type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--preflight-only', action='store_true')
    modes.add_argument('--run-browser', action='store_true')
    args = parser.parse_args()
    require(os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED') == '1', 'Use isolated runner')
    require(os.environ.get('DATABASE_URL') == 'sqlite:///:memory:', 'No external DB allowed')
    repo, output = args.repo.resolve(), args.artifacts.resolve()
    sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    tree = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
    require(sha == args.expected_sha, 'Exact source SHA does not match')
    require(not subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain', '--untracked-files=all'], text=True).strip(), 'Source must be clean')
    if args.run_browser:
        require(args.chromium is not None and args.chromium.is_file(), 'Explicit installed Chromium required')
    output.mkdir(parents=True, exist_ok=True)
    os.chdir(repo)
    sys.path[:0] = [str(repo), str(repo / 'tests')]
    from test_dashboard_saved_proposals import DashboardSavedProposalTests, Document
    from sqlalchemy import event
    case = DashboardSavedProposalTests()
    report = dict(candidate_sha=sha, candidate_tree=tree, fixture_only=True,
                  production_accessed=False, browser_started=False, browser_acceptance_passed=False,
                  transport='in-process Flask GET bridge', cases=[], geometry=[],
                  page_errors=[], blocked_requests=[], failed_gets=[], database_mutations=[],
                  started_utc=datetime.now(timezone.utc).isoformat())
    started = setup = listening = False
    active = ['fixture']
    try:
        case.setUpClass(); started = True
        case.setUp(); setup = True
        m = case.m
        root = Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
        require(m.db.engine.url.drivername == 'sqlite' and Path(m.db.engine.url.database).resolve().is_relative_to(root), 'Wrong fixture database')
        user = case.configure()
        user.dashboard_settings_json = json.dumps({'vehicle_karte_last_vehicle_id': case.vehicle.id})
        m.db.session.commit()
        case.save(case.vehicle, case.recommendations(7))
        other = m.Vehicle(company_code='TEST', chassis_number='dashboard-second', office='試験営業所')
        m.db.session.add(other); m.db.session.flush()
        case.save(other, case.recommendations(8))
        def snapshot():
            return [(r.company_code, r.vehicle_record_id, r.status, r.result_json)
                    for r in m.VehicleKarteAnalysis.query.order_by(m.VehicleKarteAnalysis.id).all()]
        before = snapshot()
        dashboard_endpoint = m.app.url_map.bind('localhost').match('/', method='GET')[0]
        notification_endpoints = {m.app.url_map.bind('localhost').match(path, method='GET')[0]
            for path in ('/api/notifications/recent', '/api/notifications/unread-count')}
        def validate_saved():
            m.db.session.expire_all()
            require(snapshot() == before, 'Saved recommendations changed')
            require(m.VehicleAnalysisFeedback.query.count() == 0, 'Feedback was created')
            for write in report['database_mutations']:
                allowed = (write['endpoint'] == dashboard_endpoint and
                    write['table'] == 'company_usage_summary' and write['verb'] in {'INSERT', 'UPDATE'})
                allowed |= (write['endpoint'] in notification_endpoints and
                    (write['verb'], write['table']) in {('UPDATE', 'company'),
                        ('INSERT', 'inspection_plan_alert_run'), ('UPDATE', 'inspection_plan_alert_run')})
                require(allowed, 'Unexpected database write')
        def request(path):
            parsed = urlsplit(path)
            endpoint, _ = m.app.url_map.bind('localhost').match(parsed.path, method='GET')
            old = active[0]; active[0] = endpoint
            try:
                response = case.client.get(path)
                if response.status_code >= 400:
                    report['failed_gets'].append(dict(path=parsed.path, status=response.status_code))
                return response
            finally:
                active[0] = old
        def track(_conn, _cursor, statement, _parameters, _context, _many):
            verb = statement.lstrip().split(None, 1)[0].upper()
            if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'REPLACE'}:
                match = re.match(r'\s*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+["`]?([A-Za-z_][A-Za-z_0-9]*)', statement, re.I)
                report['database_mutations'].append(dict(endpoint=active[0], verb=verb, table=match.group(1) if match else 'UNKNOWN'))
        event.listen(m.db.engine, 'before_cursor_execute', track); listening = True
        response = request('/')
        require(response.status_code == 200, 'Dashboard failed')
        panels = Document(response.get_data(as_text=True)).root.find(cls='dashboard-attention-panel')
        require(len(panels) == 2, 'Missing groups')
        for panel, remaining in zip(panels, (2, 3)):
            require(len(panel.find(cls='dashboard-attention-preview')[0].find(tag='tbody')[0].find(tag='tr')) == 5, 'Wrong preview count')
            require(f'残り{remaining}件' in panel.find(cls='dashboard-attention-more')[0].text, 'Wrong remaining count')
        validate_saved()
        report['cases'].append('PREFLIGHT: two independent five-row previews and exact remaining counts')
        if args.preflight_only:
            report['status'] = 'PREFLIGHT_PASS_BROWSER_NOT_RUN'
            return 0
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=str(args.chromium.resolve()))
            report.update(browser_started=True, browser_version=browser.version)
            try:
                context = browser.new_context(service_workers='block')
                def bridge(route):
                    req = route.request; parsed = urlsplit(req.url)
                    if f'{parsed.scheme}://{parsed.netloc}' != ORIGIN or req.method != 'GET':
                        report['blocked_requests'].append(dict(method=req.method, host=parsed.hostname, path=parsed.path))
                        route.abort(); return
                    result = request(parsed.path + ('?' + parsed.query if parsed.query else ''))
                    headers = {k: v for k, v in result.headers.items() if k.lower() not in {'content-length', 'transfer-encoding', 'connection', 'set-cookie'}}
                    route.fulfill(status=result.status_code, headers=headers, body=result.get_data())
                context.route('**/*', bridge)
                page = context.new_page()
                page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
                for width, height in ((1440, 900), (1180, 757), (900, 700), (768, 700), (390, 600), (320, 600)):
                    page.set_viewport_size(dict(width=width, height=height))
                    page.goto(ORIGIN + '/', wait_until='networkidle')
                    panels = page.locator('.dashboard-attention-panel')
                    expect(panels).to_have_count(2)
                    for i, remaining in enumerate((2, 3)):
                        panel = panels.nth(i)
                        preview = panel.locator('.dashboard-attention-preview')
                        rows = preview.locator('tbody tr')
                        expect(rows).to_have_count(5)
                        geometry = preview.evaluate('''e => ({client:e.clientHeight, scroll:e.scrollHeight,
                            maxHeight:getComputedStyle(e).maxHeight, rows:e.querySelectorAll('tbody tr').length})''')
                        geometry.update(width=width, height=height, group=i)
                        report['geometry'].append(geometry)
                        require(geometry['maxHeight'] == 'none' and geometry['client'] + 1 >= geometry['scroll'], 'Preview rows are internally clipped')
                        for row in (rows.first, rows.last):
                            row.scroll_into_view_if_needed()
                            expect(row).to_be_in_viewport()
                            link = row.get_by_role('link', name=re.compile('根拠・対応'))
                            require(re.search(r'/karte/\d+/analysis#proposal=[0-9a-f]{64}$', link.get_attribute('href') or '') is not None, 'Saved proposal link changed')
                        details = panel.locator('.dashboard-attention-more')
                        all_button = panel.get_by_role('button', name='全件を見る')
                        expect(details).not_to_have_attribute('open', '')
                        expect(all_button).to_have_attribute('aria-expanded', 'false')
                        all_button.click()
                        expect(details).to_have_attribute('open', '')
                        expect(all_button).to_have_attribute('aria-expanded', 'true')
                        expect(details.locator('tbody tr')).to_have_count(remaining)
                        details.locator('summary').click()
                        expect(details).not_to_have_attribute('open', '')
                        expect(all_button).to_have_attribute('aria-expanded', 'false')
                        details.locator('summary').focus()
                        page.keyboard.press('Enter')
                        expect(details).to_have_attribute('open', '')
                        expect(all_button).to_have_attribute('aria-expanded', 'true')
                        details.locator('summary').click()
                    require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Page horizontal overflow')
                    page.screenshot(path=str(output / f'dashboard-{width}x{height}.png'), full_page=True)
                    report['cases'].append(f'BROWSER {width}x{height}: five reachable rows, labels, repeated pointer/keyboard expansion, contained width')
                page.goto(ORIGIN + f'/vehicle/karte/{case.vehicle.id}/history', wait_until='networkidle')
                page.go_back(wait_until='networkidle')
                expect(page.locator('.dashboard-attention-preview tbody tr')).to_have_count(10)
                page.go_forward(wait_until='networkidle')
                expect(page.locator('.vehicle-karte-history-panel')).to_be_visible()
                page.go_back(wait_until='networkidle')
                expect(page.locator('.dashboard-attention-preview tbody tr')).to_have_count(10)
                # Native details remain usable when JavaScript is unavailable.
                plain = browser.new_context(java_script_enabled=False, service_workers='block', viewport=dict(width=390, height=600))
                plain.route('**/*', bridge)
                nojs = plain.new_page(); nojs.goto(ORIGIN + '/', wait_until='networkidle')
                details = nojs.locator('.dashboard-attention-more').first
                details.locator('summary').click()
                expect(details).to_have_attribute('open', '')
                plain.close()
                validate_saved()
                require(not report['page_errors'] and not report['blocked_requests'] and not report['failed_gets'], 'Unexpected request or script failure')
                report.update(status='PASS', saved_recommendations_unchanged=True, browser_acceptance_passed=True)
                return 0
            except Exception:
                if 'page' in locals() and not page.is_closed():
                    page.screenshot(path=str(output / 'failure.png'), full_page=True)
                raise
            finally:
                browser.close()
    except Exception as error:
        report.update(status='FAILED_OR_BLOCKED', error_type=type(error).__name__)
        if isinstance(error, AssertionError):
            report['safe_failure'] = str(error)
        raise
    finally:
        if listening: event.remove(m.db.engine, 'before_cursor_execute', track)
        if setup: case.tearDown()
        if started: case.tearDownClass()
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output / ('preflight-result.json' if args.preflight_only else 'browser-result.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    raise SystemExit(main())
