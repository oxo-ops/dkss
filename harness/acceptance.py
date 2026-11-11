#!/usr/bin/env python3
"""Exact-candidate browser coverage for the connected normal-screen fixture.

Fixture POSTs are real Flask requests. Browser access is same-origin GET-only,
bridged in-process: it cannot send writes or connect to a live application.
Only the separate confirmation_* cases allow their two explicit fixture POSTs.
"""
import argparse
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from html import escape
from urllib.parse import parse_qs, urljoin, urlsplit
from native_pdf_navigation import NativePdfNavigation

ORIGIN = 'http://127.0.0.1:8765'


def require(value, message):
    if not value:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--case', choices=('normal', 'instruction', 'recheck', 'invoice', 'periodic_instruction', 'periodic_timing', 'confirmation_manufacturer', 'confirmation_legal', 'confirmation_progression'), required=True)
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
    if args.case.startswith('confirmation_'):
        from confirmation_acceptance import run
        return run(args, sha, tree, out, ORIGIN)
    import test_video_connected_flows as flows
    if args.case.startswith('periodic_'):
        import test_priority_periodic_consumers as periodic
        case = (periodic.PeriodicPriorityWorkflowTests() if args.case == 'periodic_instruction'
                else periodic.PeriodicTimingPriorityTests())
    else:
        case = flows.ConnectedInvoiceFlowTests() if args.case == 'invoice' else flows.ConnectedInspectionFlowTests()
    started = setup = False
    report = dict(candidate_sha=sha, candidate_tree=tree, scenario=args.case,
        status='FAILED', fixture_only=True, production_accessed=False, browser_started=False,
        browser_acceptance_passed=False, page_errors=[], blocked_requests=[], failed_gets=[],
        cases=[], failed_requests=[], redirects=[], notification_navigations=[],
        native_http_redirect_browser_covered=False,
        redirect_transport='Only the verified notification GET uses a synthetic same-origin meta-refresh relay',
        started_utc=datetime.now(timezone.utc).isoformat())
    notice_open_path = notice_destination = None
    try:
        case.setUpClass(); started = True; case.setUp(); setup = True
        if args.case.startswith('periodic_'):
            if args.case == 'periodic_instruction':
                case.prepare(decision='運行不可')
                case.execute_normal_job('registered_operation_instruction')
                score, label = 60, '高'
            else:
                case.setup_rule(); case.check_saved_read()
                score, label = 35, '中'
            m, app, db = case.m, case.m.app, case.m.db
            data = case.client.get(case.api).json
            require(data['status'] == 'completed', 'Periodic normal generation did not finish')
            items = data['result']['recommendations']
            require(len(items) == 1, 'Periodic fixture must identify one exact proposal')
            periodic_item = items[0]
            assessment = periodic_item['priority_assessment']
            require((assessment['label'], assessment['effective_score']) == (label, score), 'Wrong periodic common assessment')
            require(data['result']['priority_summary'] == dict(labels={v: int(v == label) for v in ('高', '中', '低')},
                    invalid_count=0, proposal_count=1), 'Periodic counts do not match the proposal')
            badge = f'{label} · {score}点'
            paths = [case.api.replace('/suggestions', '/followup')]
            report['cases'].append(f'Normal periodic POST/job/save/GET retains source proof and common {score}/counts; model wording synthetic')
        elif args.case == 'invoice':
            case.test_invoice_confirm_correct_resend_and_late_cost_stay_one_actual()
            m, app, db = case.m, case.m.app, case.m.db
            actual = case.actuals()[0]
            invoice_record = m.VehicleMaintenanceRecord.query.one()
            invoice_source = json.loads(invoice_record.invoice_details_json)['source']
            original_hash = invoice_source['sha256']
            invoice_source_path = f'/vehicle/karte/{case.vehicle.id}/documents/{invoice_source["draft_id"]}/source'
            report['invoice_source_navigations'] = []
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
            notice_id = notice.id
            notice_open_path = f'/notifications/{notice_id}/open'
            landing = case.client.get(notice_open_path, follow_redirects=True)
            require(landing.status_code == 200 and notice.read, 'Notification target did not open')
            require(len(landing.history) == 1 and landing.history[0].status_code == 302,
                    'Notification must make one real redirect')
            notice_location = landing.history[0].headers['Location']
            notice_destination = urljoin(ORIGIN + notice_open_path, notice_location)
            destination = urlsplit(notice_destination)
            source_url = bundle['sources'][f'inspection:{case.row.id}']['url']
            source = urlsplit(source_url)
            source_query = parse_qs(source.query, keep_blank_values=True)
            target_query = parse_qs(destination.query, keep_blank_values=True)
            require(target_query.pop('_notification_id', None) == [str(notice_id)],
                    'Notification redirect identity differs')
            require(f'{destination.scheme}://{destination.netloc}' == ORIGIN and
                    destination.path == source.path == landing.request.path and
                    target_query == source_query and destination.path != notice_open_path,
                    'Notification redirect differs from the exact inspection source')
            report['notification_source'] = dict(notification_id=notice_id,
                inspection_result_id=case.row.id, checklist_id=case.row.checklist_id,
                vehicle_id=case.vehicle.id, source_url=source_url,
                flask_location=notice_location, expected_url=notice_destination)
            notice_target = landing.request.path
            related_notice = related_item = related_source_url = None
            if args.case in ('instruction', 'recheck'):
                case.login('checker')
                owned = m.Notification.query.filter_by(company_code='A', target_username='checker')
                related_notice = (owned.filter_by(title='車両の運行判断：運行不可').one()
                    if args.case == 'instruction' else owned.filter(m.Notification.title.like('%：再確認待ち')).one())
                landing = case.client.get(f'/notifications/{related_notice.id}/open', follow_redirects=True)
                require(landing.status_code == 200 and related_notice.read, 'Related notice target failed')
                recent = case.client.get('/api/notifications/recent')
                related = next(n['related_priority'] for n in recent.json['notifications'] if n['id'] == related_notice.id)
                require(related and related['count'] == 1, 'Same-event notification projection missing')
                related_item = related['items'][0]
                require((related_item['proposal_id'], related_item['proposal_revision'], related_item['score']) ==
                        (proposal_id, item['proposal_revision'], score), 'Notification rebound to a different proposal')
                require(related_item['url'] == f'/vehicle/karte/{case.vehicle.id}/analysis#proposal={proposal_id}', 'Wrong related proposal link')
                detail = case.client.get(f'/notifications/{related_notice.id}?panel=1')
                require(detail.status_code == 200 and badge in detail.json['html'], 'Related notice detail score missing')
                related_source_url = bundle['sources'][f'inspection:{case.row.id}']['url']
                require(case.client.get(related_source_url).status_code == 200, 'Same inspection source inaccessible')
                case.login('admin')
                # An ordinary approval request is unsupported by this new adapter.
                unsupported = case.client.get(f'/notifications/{notice.id}?panel=1')
                require('notification-related-priority-detail' not in unsupported.json['html'], 'Unsupported notice acquired a score')
                report['cases'].append(f'Owned checker notification shares exact event/proposal/revision/{score}; unsupported approval has no summary')
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
        pdf = NativePdfNavigation(report, ORIGIN)
        invoice_phase = 'setup'
        invoice_request_ids = {}
        if args.case == 'invoice':
            report['invoice_source_events'] = []
            report['invoice_downloads'] = []

        def observe_invoice_source(event, request, **details):
            if args.case != 'invoice' or request.url != ORIGIN + invoice_source_path:
                return
            request_id = invoice_request_ids.setdefault(request, len(invoice_request_ids) + 1)
            report['invoice_source_events'].append(dict(
                sequence=len(report['invoice_source_events']) + 1, event=event,
                phase=invoice_phase, request_id=request_id, url=request.url,
                method=request.method, resource_type=request.resource_type,
                is_navigation_request=request.is_navigation_request(), **details))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(args.chromium.resolve()))
            report.update(browser_started=True, browser_version=browser.version)
            try:
                context = browser.new_context(service_workers='block')
                def bridge(route):
                    request = route.request; parsed = urlsplit(request.url)
                    if f'{parsed.scheme}://{parsed.netloc}' != ORIGIN or request.method != 'GET':
                        if pdf.abort_if_native(route): return
                        report['blocked_requests'].append(dict(url=request.url, scheme=parsed.scheme,
                            method=request.method, host=parsed.hostname, path=parsed.path,
                            resource_type=request.resource_type))
                        route.abort(); return
                    response = get(parsed.path + ('?' + parsed.query if parsed.query else ''))
                    if args.case == 'invoice' and request.url == ORIGIN + invoice_source_path:
                        observe_invoice_source('bridge_response', request,
                            status=response.status_code, mimetype=response.mimetype,
                            content_disposition=response.headers.get('Content-Disposition'),
                            byte_length=len(response.get_data()),
                            source_sha256=hashlib.sha256(response.get_data()).hexdigest())
                    if args.case == 'invoice' and parsed.path == invoice_source_path and request.is_navigation_request():
                        report['invoice_source_navigations'].append(dict(
                            url=request.url, status=response.status_code, mimetype=response.mimetype,
                            resource_type=request.resource_type,
                            source_sha256=hashlib.sha256(response.get_data()).hexdigest()))
                    headers = {key: value for key, value in response.headers.items()
                               if key.lower() not in {'content-length', 'transfer-encoding', 'connection', 'set-cookie'}}
                    if 300 <= response.status_code < 400:
                        location = response.headers.get('Location', '')
                        target = urljoin(request.url, location)
                        destination = urlsplit(target)
                        report['redirects'].append(dict(request_url=request.url,
                            status=response.status_code, location=location, resolved_url=target,
                            transport='synthetic_meta_refresh_not_native_http_redirect'))
                        require(response.status_code == 302 and parsed.path == notice_open_path and
                                request.is_navigation_request() and request.resource_type == 'document',
                                'Unexpected redirect outside the single approved notification GET')
                        require(location and f'{destination.scheme}://{destination.netloc}' == ORIGIN and
                                target == notice_destination and destination.path != parsed.path,
                                'Unsafe, looping or different notification redirect')
                        # Playwright routes only the first URL of an HTTP redirect.
                        # Relay this verified Location as a new same-origin navigation
                        # without sockets, inline scripts, CSP relaxation or POSTs.
                        headers = {key: value for key, value in headers.items()
                                   if key.lower() not in {'location', 'content-type'}}
                        headers['Content-Type'] = 'text/html; charset=utf-8'
                        body = ('<!doctype html><meta charset="utf-8">'
                                '<meta http-equiv="refresh" content="0;url=' + escape(target, quote=True) + '">'
                                '<title>Synthetic notification redirect relay</title>')
                        route.fulfill(status=200, headers=headers, body=body)
                        return
                    pdf.observe_response(request, response.status_code, headers, response.get_data())
                    route.fulfill(status=response.status_code, headers=headers, body=response.get_data())
                context.route('**/*', bridge)
                if args.case == 'invoice':
                    context.on('request', lambda request: observe_invoice_source('request', request))
                    context.on('response', lambda response: observe_invoice_source(
                        'response', response.request, status=response.status))
                    context.on('requestfinished', lambda request: observe_invoice_source('requestfinished', request))
                    context.on('requestfailed', lambda request: observe_invoice_source(
                        'requestfailed', request, failure=request.failure))
                context.on('requestfailed', lambda request: None if pdf.record_request_failed(request) else report['failed_requests'].append(
                    dict(method=request.method, url=request.url, failure=request.failure)))
                page = context.new_page()
                page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
                for width, height in ((1440, 900), (390, 780), (320, 640)):
                    page.set_viewport_size(dict(width=width, height=height))
                    if args.case.startswith('periodic_'):
                        page.goto(ORIGIN + paths[0], wait_until='networkidle')
                        cards = page.locator('[data-proposal-list] .pf-proposal')
                        expect(cards).to_have_count(1)
                        expect(cards.locator('.card-title-row strong')).to_have_text('1. ' + periodic_item['title'])
                        expect(cards.locator('.priority-response-badge')).to_have_text(badge)
                        expect(page.locator('[data-proposal-status]')).to_contain_text('AI提案 1件')
                        expect(page.locator('[data-proposal-status]')).to_contain_text(f'{label}1件')
                        details = cards.locator('.priority-response-details')
                        details.locator('summary').click()
                        expect(details.locator('.priority-response-subject')).to_contain_text(assessment['subject_label'])
                        expect(details.locator('.priority-response-disclaimer')).to_contain_text('運行可否')
                        if args.case == 'periodic_instruction':
                            expect(details.locator('.priority-response-instruction')).to_contain_text('運行不可')
                            expect(details.locator('.priority-response-instruction')).to_contain_text(assessment['instruction_details']['actor_name'])
                        else:
                            reference = details.locator('.priority-response-reference')
                            expect(reference).to_contain_text(assessment['timing_reference']['quote'])
                            expect(reference.locator('a')).to_have_attribute('href', assessment['timing_reference']['url'])
                        require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Periodic priority overflow')
                        page.screenshot(path=str(out / f'{args.case}-{width}.png'), full_page=True)
                        details.locator('summary').click()
                        expect(details).not_to_have_attribute('open', '')
                        details.locator('summary').click()
                        expect(details).to_have_attribute('open', '')
                        page.locator('.pf-intro').get_by_role('link', name='点検一覧へ').click()
                        page.wait_for_load_state('networkidle')
                        require(urlsplit(page.url).path != paths[0], 'Periodic list link did not navigate')
                        page.go_back(wait_until='networkidle')
                        expect(page.locator('.priority-response-badge')).to_have_text(badge)
                        report['cases'].append(f'Browser {width}: periodic {score} badge/counts/source details and actual list/back navigation; no generation POST')
                    elif args.case == 'invoice':
                        invoice_phase = f'width:{width}/history'
                        # History opens this invoice's original PDF, not its
                        # maintenance-detail page. Follow that real rendered link.
                        page.goto(ORIGIN + paths[0], wait_until='networkidle')
                        source_link = page.locator('.vehicle-history-record-link')
                        expect(source_link).to_have_count(1)
                        expect(source_link).to_have_attribute('href', invoice_source_path)
                        source_url = urljoin(ORIGIN, source_link.get_attribute('href'))
                        invoice_phase = f'width:{width}/history-original'
                        pdf.begin(page, source_url, original_hash)
                        navigation_count = len(report['invoice_source_navigations'])
                        with page.expect_response(lambda response: response.url == source_url and
                                response.request.is_navigation_request()) as opened:
                            source_link.click(no_wait_after=True)
                        require(opened.value.status == 200, 'History original source did not open')
                        expect(page).to_have_url(source_url)
                        require(len(report['invoice_source_navigations']) == navigation_count + 1,
                                'History click did not make one original-source navigation')
                        navigation = report['invoice_source_navigations'][-1]
                        require(navigation['url'] == source_url and navigation['mimetype'] == 'application/pdf' and
                                navigation['resource_type'] == 'document' and navigation['source_sha256'] == original_hash,
                                'History navigation reached a different original source')
                        page.wait_for_url(source_url, wait_until='networkidle')
                        pdf.finish(page, opened.value)
                        pdf.end()
                        invoice_phase = f'width:{width}/history-back'
                        page.go_back(wait_until='networkidle')
                        expect(page).to_have_url(ORIGIN + paths[0])
                        expect(page.locator('main')).to_contain_text('タイヤ交換（読取訂正）')
                        # Keep the detail and download acceptance through the
                        # actual maintenance tab and exact rendered record link.
                        maintenance_path = f'/vehicle/karte/{case.vehicle.id}/maintenance'
                        maintenance_tab = page.locator('.vehicle-karte-tabs').get_by_role('link', name='整備・修理', exact=True)
                        expect(maintenance_tab).to_have_attribute('href', maintenance_path)
                        invoice_phase = f'width:{width}/maintenance-tab'
                        maintenance_tab.click()
                        expect(page).to_have_url(ORIGIN + maintenance_path)
                        record_link = page.locator('.km-record-content a').filter(has_text='タイヤ交換（読取訂正）')
                        expect(record_link).to_have_count(1)
                        record_href = record_link.get_attribute('href')
                        target = urlsplit(urljoin(ORIGIN, record_href))
                        require(f'{target.scheme}://{target.netloc}' == ORIGIN and
                                target.path == maintenance_path + f'/{invoice_record.id}' and
                                target.fragment == 'maintenance_detail_panel', 'Rendered link targets a different maintenance record')
                        invoice_phase = f'width:{width}/maintenance-record'
                        record_link.click()
                        expect(page).to_have_url(urljoin(ORIGIN, record_href))
                        detail = page.locator('.km-detail-panel')
                        expect(detail).to_contain_text('タイヤ交換（読取訂正）')
                        download_link = detail.locator('.km-file-card[download]')
                        expect(download_link).to_have_count(1)
                        expect(download_link).to_have_attribute('href', invoice_source_path)
                        invoice_phase = f'width:{width}/original-download'
                        download_href = download_link.get_attribute('href')
                        download_attribute = download_link.get_attribute('download')
                        with page.expect_download() as transfer:
                            download_link.click()
                        downloaded = transfer.value
                        download_failure = downloaded.failure()
                        report['invoice_downloads'].append(dict(width=width, phase=invoice_phase,
                            href=download_href, download_attribute=download_attribute,
                            url=downloaded.url, suggested_filename=downloaded.suggested_filename,
                            failure=download_failure,
                            source_event_count=len(report['invoice_source_events'])))
                        require(download_failure is None, f'Original download failed: {download_failure!r}')
                        require(hashlib.sha256(Path(downloaded.path()).read_bytes()).hexdigest() == original_hash, 'Original download changed')
                        report['cases'].append(f'Browser {width}: rendered history -> exact original PDF GET/hash -> Back -> maintenance tab -> same record -> preserved original download/hash; native PDF viewer rendering not covered')
                        invoice_phase = f'width:{width}/connected-views'
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
                        unsupported_row = page.locator(f'.notification-wrapper[data-notification-id="{notice.id}"]')
                        expect(unsupported_row.locator('.notification-related-priority')).to_have_count(0)
                        open_link = page.locator(f'a.js-notification-open[href^="{notice_open_path}"]').first
                        actual_href = open_link.get_attribute('href')
                        require(actual_href and urlsplit(urljoin(ORIGIN, actual_href)).path == notice_open_path,
                                'Rendered notification href differs')
                        navigation = dict(width=width, actual_href=actual_href,
                            expected_url=notice_destination, inspection_result_id=case.row.id)
                        report['notification_navigations'].append(navigation)
                        open_link.click()
                        expect(page).to_have_url(notice_destination)
                        page.wait_for_load_state('networkidle')
                        navigation['arrived_url'] = page.url
                        require(page.url == notice_destination, 'Notification opened a different source')
                        expect(page.locator('main')).to_contain_text('ブレーキ')
                        report['cases'].append(f'Browser {width}: rendered notification click -> real Flask Location -> synthetic same-origin relay -> exact inspection target (not native HTTP redirect)')
                        if related_notice is not None:
                            case.login('checker')
                            page.goto(ORIGIN + '/notifications', wait_until='networkidle')
                            note_row = page.locator(f'.notification-wrapper[data-notification-id="{related_notice.id}"]')
                            expect(note_row.locator('.notification-related-priority')).to_contain_text(badge)
                            note_row.locator('.notification-item').click()
                            detail = page.locator('#notificationDetailPane .notification-related-priority-detail')
                            expect(detail).to_be_visible()
                            expect(detail).to_contain_text(badge)
                            expect(detail).to_contain_text('運行可否は人が判断')
                            require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Related notification overflow')
                            page.screenshot(path=str(out / f'notification-related-{width}.png'), full_page=True)
                            detail.locator(f'a[href="{related_item["url"]}"]').click()
                            drawer = page.locator('.ka-reference-drawer')
                            expect(drawer).to_be_visible()
                            require(urlsplit(page.url).fragment == 'proposal=' + proposal_id, 'Notification selected wrong proposal')
                            expect(drawer.locator('.ka-drawer-priority-row .ka-ai-priority')).to_have_text(badge)
                            expect(drawer.locator('#ka-reference-drawer-title')).to_have_text(related_item['subject'])
                            original_link = drawer.locator('.ka-action-original-link')
                            expect(original_link).to_have_attribute('href', urljoin(ORIGIN, related_source_url))
                            with page.expect_popup() as opened:
                                original_link.click()
                            original_page = opened.value
                            original_page.wait_for_load_state('networkidle')
                            require(urlsplit(original_page.url).path == urlsplit(related_source_url).path, 'Related priority source differs')
                            expect(original_page.locator('main')).to_contain_text('ブレーキ')
                            original_page.close()
                            page.screenshot(path=str(out / f'notification-proposal-{width}.png'), full_page=True)
                            report['cases'].append(f'Browser {width}: checker notification list/detail -> exact proposal #{proposal_id} -> same inspection source; score {score}')
                            case.login('admin')
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
                require(not report['page_errors'] and not report['failed_gets'] and not report['blocked_requests'] and not report['failed_requests'], 'Browser request or script failure')
                require(snapshot() == before, 'Browser GET changed protected saved data')
                report.update(status='PASS', browser_acceptance_passed=True, protected_records_unchanged=True)
                return 0
            except Exception:
                if 'page' in locals() and not page.is_closed():
                    report['failure_url'] = page.url
                    page.screenshot(path=str(out / 'failure.png'), full_page=True)
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
