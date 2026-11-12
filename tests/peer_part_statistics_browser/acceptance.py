#!/usr/bin/env python3
"""Synthetic peer-part facts and comparison filters in Chromium, without a server."""
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
    from test_peer_part_statistics_display import PeerPartStatisticsDisplayTests, Document
    from sqlalchemy import event
    case = PeerPartStatisticsDisplayTests()
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
        user = m.User.query.filter_by(company_code='TEST', username='admin').one()
        user.dashboard_settings_json = json.dumps({'vehicle_karte_last_vehicle_id': case.vehicle.id})
        peer = case.peer()
        for i in range(14):
            case.part(peer, name=f'合成登録部品{i:02}' + ('長い登録名' * 12 if i == 0 else ''), number=f'PART-{i:02}')
        case.part(case.peer(first_registration_date='2021-01-01'), name='別年の合成部品')
        case.part(case.peer(deleted=True), name='無効車の合成部品')
        m.db.session.commit()
        def snapshot():
            return ([(r.id, r.company_code, r.vehicle_record_id, r.part_name, str(r.quantity), r.replacement_date)
                     for r in m.VehiclePartReplacement.query.order_by(m.VehiclePartReplacement.id)],
                    [(r.id, r.status, r.result_json) for r in m.VehicleKarteAnalysis.query.all()])
        before = snapshot()
        notification_endpoints = {m.app.url_map.bind('localhost').match(path, method='GET')[0]
            for path in ('/api/notifications/recent', '/api/notifications/unread-count')}
        def validate_saved():
            m.db.session.expire_all()
            require(snapshot() == before, 'Parts or saved analysis changed')
            require(m.VehicleAnalysisFeedback.query.count() == 0, 'Feedback was created')
            for write in report['database_mutations']:
                allowed = (write['endpoint'] in notification_endpoints and
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
        response = request(case.path())
        require(response.status_code == 200, 'Analysis page failed')
        panels = Document(response.get_data(as_text=True)).root.find(cls='ka-peer-parts')
        require(len(panels) == 1, 'Missing peer-parts panel')
        require(len(panels[0].find(tag='tbody')[0].find(tag='tr')) == 14, 'Wrong number of registration groups')
        require('比較対象 1台' in panels[0].text, 'Wrong denominator')
        validate_saved()
        report['cases'].append('PREFLIGHT: exact 14 registration groups and one peer, no factual writes')
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
                    page.goto(ORIGIN + case.path(), wait_until='networkidle')
                    details = page.locator('#ka-peer-parts')
                    expect(details).not_to_have_attribute('open', '')
                    summary = details.locator('summary')
                    summary.click()
                    expect(details).to_have_attribute('open', '')
                    expect(details.locator('tbody tr')).to_have_count(14)
                    expect(details.locator('tbody tr').first.locator('td')).to_have_text(['1件', '1台'])
                    expect(details.locator('.ka-peer-parts-note')).to_contain_text('件数の多さだけで故障多発や交換時期を判断しない')
                    viewport = details.locator('.ka-peer-parts-scroll')
                    geometry = viewport.evaluate('e => ({clientWidth:e.clientWidth, scrollWidth:e.scrollWidth, clientHeight:e.clientHeight, scrollHeight:e.scrollHeight})')
                    geometry.update(width=width, height=height)
                    report['geometry'].append(geometry)
                    require(geometry['clientHeight'] + 1 >= geometry['scrollHeight'], 'Rows clipped vertically')
                    last = details.locator('tbody tr').last
                    last.scroll_into_view_if_needed(); expect(last).to_be_in_viewport()
                    # Reach the rightmost count within the table scroll container.
                    if width <= 390:
                        viewport.evaluate('e => { e.scrollLeft = 0; }')
                        viewport.focus()
                        require(viewport.evaluate('e => e.scrollLeft == 0'), 'Keyboard scroll starts at left edge')
                        page.keyboard.press('ArrowRight')
                        for _ in range(20):
                            if viewport.evaluate('e => e.scrollLeft > 0'):
                                break
                            page.wait_for_timeout(50)
                        require(viewport.evaluate('e => e.scrollLeft > 0'), 'ArrowRight scrolls the table')
                        cell = last.locator('td').last
                        cell.scroll_into_view_if_needed(); expect(cell).to_be_in_viewport(ratio=1)
                        require(viewport.evaluate('e => e.scrollLeft > 0'), 'No horizontal table scroll')
                    summary.click(); expect(details).not_to_have_attribute('open', '')
                    summary.focus(); page.keyboard.press('Enter')
                    expect(details).to_have_attribute('open', '')
                    require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Page horizontal overflow')
                    page.screenshot(path=str(output / f'peer-parts-{width}x{height}.png'), full_page=True)
                    report['cases'].append(f'BROWSER {width}x{height}: all 14 rows, counts and caution visible, repeated pointer/keyboard expansion, contained width')
                # Real GET form submission must update both scope and facts.
                page.set_viewport_size(dict(width=1180, height=757))
                page.goto(ORIGIN + case.path(), wait_until='networkidle')
                form = page.locator('#ka-reference-peer-conditions')
                form.locator('[name=peer_registration]').select_option('all_years')
                form.locator('[name=peer_inactive]').check()
                form.get_by_role('button', name='比較', exact=True).click()
                page.wait_for_load_state('networkidle')
                details = page.locator('#ka-peer-parts'); details.locator('summary').click()
                expect(details.locator('tbody tr')).to_have_count(16)
                expect(details.locator('.ka-peer-parts-scope')).to_contain_text('比較対象 3台')
                page.go_back(wait_until='networkidle')
                expect(page.locator('#ka-peer-parts tbody tr')).to_have_count(14)
                page.go_forward(wait_until='networkidle')
                expect(page.locator('#ka-peer-parts tbody tr')).to_have_count(16)
                page.locator('#ka-start-date').fill('2026-10-01')
                page.locator('.ka-period-form').get_by_role('button', name='集計', exact=True).click()
                page.wait_for_load_state('networkidle')
                details = page.locator('#ka-peer-parts'); details.locator('summary').click()
                expect(details.locator('table')).to_have_count(0)
                expect(details.locator('.ka-peer-parts-empty')).to_contain_text('実際に交換がなかったことを示すものではありません')
                page.reload(wait_until='networkidle')
                expect(page.locator('#ka-peer-parts table')).to_have_count(0)
                report['cases'].append('BROWSER: condition submit, period submit, Back/Forward, reload, empty record distinction')
                plain = browser.new_context(java_script_enabled=False, service_workers='block', viewport=dict(width=390, height=600))
                plain.route('**/*', bridge)
                nojs = plain.new_page(); nojs.goto(ORIGIN + case.path(), wait_until='networkidle')
                details = nojs.locator('#ka-peer-parts'); details.locator('summary').click()
                expect(details).to_have_attribute('open', '')
                expect(details.locator('tbody tr')).to_have_count(14)
                plain.close()
                report['cases'].append('BROWSER: native details and facts without JavaScript')
                validate_saved()
                require(not report['page_errors'] and not report['blocked_requests'] and not report['failed_gets'], 'Unexpected request or script failure')
                report.update(status='PASS', parts_and_saved_analysis_unchanged=True, browser_acceptance_passed=True)
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
