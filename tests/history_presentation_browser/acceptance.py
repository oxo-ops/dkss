#!/usr/bin/env python3
"""Narrow history rendering/nav acceptance; synthetic SQLite, Flask GET bridge."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

PUBLIC_SHA = '38891e31e4065359cf5f2aa55fb3873917685939'
FROZEN_TREE = '3f940872a47e898225ecd9c66e53603e82098bf1'
ORIGIN = 'http://127.0.0.1:8765'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--chromium', type=Path)
    parser.add_argument('--allow-identical-tree-preflight', action='store_true')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--preflight-only', action='store_true')
    modes.add_argument('--run-browser', action='store_true')
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.artifacts.resolve()
    require(os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED') == '1', 'Use isolated runner')
    require(os.environ.get('DATABASE_URL') == 'sqlite:///:memory:', 'No external DB allowed')
    sha = subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'], text=True).strip()
    tree = subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD^{tree}'], text=True).strip()
    require(tree == FROZEN_TREE, 'Wrong frozen source tree')
    require(not args.allow_identical_tree_preflight or args.preflight_only, 'Tree-only flag cannot launch browser')
    require(sha == PUBLIC_SHA or args.allow_identical_tree_preflight, 'Wrong frozen source commit')
    require(not subprocess.check_output(['git','-C',str(repo),'status','--porcelain','--untracked-files=all'], text=True).strip(), 'Candidate must be clean')
    if args.run_browser:
        require(args.chromium is not None and args.chromium.is_file(), 'Explicit installed Chromium required')
    output.mkdir(parents=True, exist_ok=True)
    os.chdir(repo)
    sys.path[:0] = [str(repo), str(repo/'tests')]
    from test_workflow_regressions import WorkflowRegressionTests
    from test_vehicle_karte_navigation import Sidebar
    from sqlalchemy import event
    report = dict(candidate_sha=sha, candidate_tree=tree, frozen_public_sha=PUBLIC_SHA,
                  started_utc=datetime.now(timezone.utc).isoformat(), fixture_only=True,
                  production_accessed=False, browser_started=False, browser_acceptance_passed=False,
                  transport='in-process Flask WSGI GET bridge', cases=[], geometry=[],
                  page_errors=[], non_get_requests=[], blocked_external_requests=[], failed_gets=[],
                  database_mutations=[], normal_notification_gets=0, ordinary_app_globally_read_only=False)
    case = WorkflowRegressionTests()
    class_started = setup_started = listening = False
    active_request = ['fixture']
    try:
        case.setUpClass(); class_started = True
        case.setUp(); setup_started = True
        m = case.m
        require(m.db.engine.url.drivername == 'sqlite', 'Wrong DB driver')
        require(Path(m.db.engine.url.database).resolve().is_relative_to(Path(os.environ['DKSS_VALIDATION_TMP']).resolve()), 'DB outside disposable fixture')
        for index in range(25):
            m.db.session.add(m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=case.vehicle.id,
                content=f'合成履歴{index:02d}', status='完了', entry_date='2026-11-10'))
        user = m.User.query.filter_by(company_code='TEST', username='admin').one()
        user.dashboard_settings_json = json.dumps({'vehicle_karte_last_vehicle_id':case.vehicle.id})
        m.db.session.commit()
        def snapshot():
            return [(r.id, r.entry_date, r.content, r.status, r.vehicle_record_id, r.company_code)
                    for r in m.VehicleMaintenanceRecord.query.order_by(m.VehicleMaintenanceRecord.id).all()]
        before = snapshot()
        history = f'/master/vehicles/{case.vehicle.id}/karte/history'
        canonical = f'/vehicle/karte/{case.vehicle.id}/history'
        def request(path):
            parsed = urlsplit(path)
            try:
                endpoint, _values = m.app.url_map.bind('localhost').match(parsed.path, method='GET')
            except Exception:
                endpoint = 'unmatched_route'
            previous = active_request[0]; active_request[0] = endpoint
            try:
                response = case.client.get(path)
                if response.status_code >= 400:
                    report['failed_gets'].append(dict(endpoint=endpoint,status=response.status_code))
                return response
            finally:
                active_request[0] = previous
        def track_write(_connection,_cursor,statement,_parameters,_context,_many):
            tokens = statement.lstrip().split(None,1)
            verb = tokens[0].upper() if tokens else ''
            if verb in {'INSERT','UPDATE','DELETE','CREATE','ALTER','DROP','REPLACE'}:
                match = re.match(r'\s*(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|(?:CREATE|ALTER|DROP)\s+(?:TABLE|INDEX))\s+["`]?([A-Za-z_][A-Za-z_0-9]*)', statement,re.I)
                report['database_mutations'].append(dict(endpoint=active_request[0],verb=verb,table=match.group(1) if match else 'UNIDENTIFIED'))
        event.listen(m.db.engine,'before_cursor_execute',track_write); listening = True
        for path in (history,canonical,history+'?category=maintenance&page=2&per_page=10'):
            response = request(path)
            require(response.status_code == 200,'History route failed')
            nav = Sidebar(response.get_data(as_text=True))
            require([a['href'] for a in nav.active] == ['/vehicle/karte'],'Wrong history sidebar selection')
            require(nav.active[0].get('aria-current') == 'page','Missing current page semantics')
        require(snapshot() == before,'History data changed in preflight')
        require(not report['database_mutations'],'History route wrote SQL')
        report['cases'].append('PREFLIGHT: both aliases, filtered page, selected Karte nav, 25 synthetic records unchanged')
        if args.preflight_only:
            report['status'] = 'PREFLIGHT_PASS_BROWSER_NOT_RUN'; return 0
        from importlib.metadata import version
        from playwright.sync_api import sync_playwright, expect
        report.update(python_version=sys.version.split()[0],playwright_version=version('playwright'))
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True,executable_path=str(args.chromium.resolve()))
            report.update(browser_started=True,browser_version=browser.version)
            try:
                context = browser.new_context(viewport={'width':1440,'height':1000},service_workers='block')
                def bridge(route):
                    req = route.request; parsed = urlsplit(req.url)
                    if f'{parsed.scheme}://{parsed.netloc}' != ORIGIN:
                        report['blocked_external_requests'].append(parsed.hostname or 'unknown'); route.abort(); return
                    if req.method != 'GET':
                        report['non_get_requests'].append(dict(method=req.method,path=parsed.path)); route.abort(); return
                    if parsed.path == '/api/notifications/unread-count': report['normal_notification_gets'] += 1
                    response = request(parsed.path+('?' + parsed.query if parsed.query else ''))
                    headers = {k:v for k,v in response.headers.items() if k.lower() not in {'content-length','transfer-encoding','connection','set-cookie'}}
                    route.fulfill(status=response.status_code,headers=headers,body=response.get_data())
                context.route('**/*',bridge)
                page = context.new_page()
                page.on('pageerror',lambda error:report['page_errors'].append(str(error)))
                def nav_check():
                    active = page.locator('.sidebar-nav a.active')
                    expect(active).to_have_count(1)
                    expect(active).to_have_attribute('href','/vehicle/karte')
                    expect(active).to_have_attribute('aria-current','page')
                    expect(page.locator('.sidebar-nav a[href="/master/drivers"]')).not_to_have_attribute('aria-current','page')
                def geometry(width):
                    values = page.locator('td.vehicle-history-date').evaluate_all('''els => els.map(e => {
                        const cell=e.getBoundingClientRect(), text=e.querySelector('.vehicle-history-date-text').getBoundingClientRect();
                        const marker=getComputedStyle(e,'::before');
                        return {cellLeft:cell.left,cellRight:cell.right,textLeft:text.left,textRight:text.right,
                            markerRight:cell.left+parseFloat(marker.left)+parseFloat(marker.width),
                            markerContent:marker.content,paddingLeft:getComputedStyle(e).paddingLeft,
                            text:e.textContent.trim()};
                    })''')
                    report['geometry'].append(dict(width=width,rows=values))
                    require(len(values)>0,'Missing history dates')
                    if width>=769:
                        require(all(v['paddingLeft']=='28px' for v in values),'Desktop date gutter overridden')
                        require(all(v['textLeft']-v['markerRight']>=6 for v in values),'Timeline marker overlaps date')
                        require(all(v['textRight']<=v['cellRight']+1 for v in values),'Date text crosses adjacent column')
                    else:
                        require(all('日付' in v['markerContent'] for v in values),'Mobile date label lost')
                    require(page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),'Page horizontal overflow')
                for width in (1440,1024,901,900,769,768,390):
                    page.set_viewport_size({'width':width,'height':1000})
                    for path in (history,canonical):
                        page.goto(ORIGIN+path,wait_until='networkidle')
                        nav_check(); geometry(width)
                        expect(page.locator('.vehicle-karte-history-table tbody tr')).to_have_count(10)
                    page.screenshot(path=str(output/f'history-{width}.png'),full_page=True)
                    if width<=900:
                        page.locator('#sidebarToggle').click()
                        expect(page.locator('.sidebar-nav a.active')).to_be_visible()
                        page.screenshot(path=str(output/f'history-nav-{width}.png'),full_page=True)
                        page.locator('#sidebarOverlay').click(position={'x':width-20,'y':600})
                        expect(page.locator('#sidebarToggle')).to_have_attribute('aria-expanded','false')
                        expect(page.locator('body')).not_to_have_class(re.compile(r'.*sidebar-open.*'))
                    with page.expect_navigation(wait_until='domcontentloaded'):
                        page.locator('.vehicle-history-categories a[data-category="maintenance"]').click()
                    nav_check()
                    first_url = page.url
                    require(parse_qs(urlsplit(first_url).query).get('category') == ['maintenance'], 'Category navigation failed')
                    first_content = page.locator('.vehicle-history-content').first.inner_text()
                    with page.expect_navigation(wait_until='domcontentloaded'):
                        page.get_by_role('link',name='次のページ',exact=True).click()
                    nav_check(); geometry(width)
                    second_url = page.url
                    require(parse_qs(urlsplit(second_url).query).get('page') == ['2'], 'Pagination did not reach page 2')
                    second_content = page.locator('.vehicle-history-content').first.inner_text()
                    require(second_content != first_content, 'Pagination did not change visible records')
                    page.go_back(wait_until='domcontentloaded'); nav_check()
                    require(page.url == first_url, 'Back did not restore first page URL')
                    expect(page.locator('.vehicle-history-content').first).to_have_text(first_content)
                    page.go_forward(wait_until='domcontentloaded'); nav_check()
                    require(page.url == second_url, 'Forward did not restore second page URL')
                    expect(page.locator('.vehicle-history-content').first).to_have_text(second_content)
                    with page.expect_navigation(wait_until='domcontentloaded'):
                        page.locator('.vehicle-history-categories a[data-category="other"]').click()
                    nav_check()
                    require(parse_qs(urlsplit(page.url).query).get('category') == ['other'], 'Empty category navigation failed')
                    expect(page.locator('.vehicle-karte-history-table')).to_have_count(0)
                    report['cases'].append(f'BROWSER {width}: both aliases, date geometry, selected nav, mobile drawer, filter/page/back/forward/empty')
                page.set_viewport_size({'width':1440,'height':1000})
                page.goto(ORIGIN+'/master/drivers',wait_until='networkidle')
                expect(page.locator('.sidebar-nav a.active')).to_have_attribute('href','/master/drivers')
                page.goto(ORIGIN+history,wait_until='networkidle'); nav_check()
                page.go_back(wait_until='domcontentloaded')
                expect(page.locator('.sidebar-nav a.active')).to_have_attribute('href','/master/drivers')
                page.go_forward(wait_until='domcontentloaded'); nav_check()
                m.db.session.expire_all()
                require(snapshot()==before,'Saved history data changed')
                allowed={('UPDATE','company'),('INSERT','inspection_plan_alert_run'),('UPDATE','inspection_plan_alert_run')}
                notification_endpoints={m.app.url_map.bind('localhost').match(path,method='GET')[0] for path in ('/api/notifications/recent','/api/notifications/unread-count')}
                require(all(w['endpoint'] in notification_endpoints and (w['verb'],w['table']) in allowed for w in report['database_mutations']),'Unexpected write outside normal notifications')
                require(report['normal_notification_gets']>0,'Normal notification polling missing')
                require(not report['page_errors'] and not report['non_get_requests'] and not report['blocked_external_requests'] and not report['failed_gets'],'Browser request or script failure')
                report.update(status='PASS',saved_history_unchanged=True,browser_acceptance_passed=True)
                return 0
            except Exception:
                if 'page' in locals() and not page.is_closed():page.screenshot(path=str(output/'failure.png'),full_page=True)
                raise
            finally:
                browser.close()
    except Exception as error:
        report.update(status='FAILED_OR_BLOCKED',error_type=type(error).__name__)
        if isinstance(error,AssertionError):report['safe_failure']=str(error)
        raise
    finally:
        if listening:event.remove(m.db.engine,'before_cursor_execute',track_write)
        if setup_started:case.tearDown()
        if class_started:case.tearDownClass()
        report['finished_utc']=datetime.now(timezone.utc).isoformat()
        (output/('preflight-result.json' if args.preflight_only else 'browser-result.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    raise SystemExit(main())
