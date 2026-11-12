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
from exact_invoice_download import ExactInvoiceDownload

ORIGIN = 'http://127.0.0.1:8765'


def require(value, message):
    if not value:
        raise AssertionError(message)


def selected_headers(headers, names):
    lowered = {key.lower(): value for key, value in headers.items()}
    return {name: lowered.get(name) for name in names}


SOURCE_RESPONSE_HEADERS = ('content-type', 'content-length', 'content-range', 'accept-ranges',
    'content-encoding', 'content-disposition', 'cache-control', 'x-content-type-options')
SOURCE_REQUEST_HEADERS = ('range', 'if-range', 'accept', 'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site')
PREVIEW_STATE = """() => {
    const root = document.querySelector('.km-detail-panel .invoice-pdf-viewer');
    if (!root) return {present: false, ready: false, error: false};
    const pages = [...root.querySelectorAll('.invoice-pdf-page')];
    const canvases = [...root.querySelectorAll('.invoice-pdf-page canvas')];
    const total = root.querySelector('[data-pdf-count]')?.textContent.trim();
    const current = root.querySelector('[data-pdf-page]')?.value;
    const status = root.querySelector('[data-pdf-status]')?.textContent.trim();
    const dimensions = pages.map(e => ({width: parseFloat(e.style.width) || 0, height: parseFloat(e.style.height) || 0}));
    const raster = canvases.map(e => ({width: e.width, height: e.height}));
    const error = root.dataset.pdfError === 'true';
    const ready = !error && total === '1' && current === '1' && pages.length === 1
        && (status || '').includes('スクロールでページ移動') && canvases.length === 1
        && dimensions.every(e => e.width > 0 && e.height > 0)
        && raster.every(e => e.width > 0 && e.height > 0);
    return {present: true, ready, error, total, current, status, dimensions, raster,
        source_base: root.dataset.sourceBase, record_key: root.dataset.requestedRecordKey,
        disclosure_open: root.closest('details')?.open};
}"""


PREVIEW_GEOMETRY = """() => {
    const root = document.querySelector('.km-detail-panel .invoice-pdf-viewer');
    const canvas = root?.querySelector('.invoice-pdf-page canvas');
    const scroll = root?.querySelector('[data-pdf-scroll]');
    if (!canvas || !scroll) return null;
    const box = element => { const r = element.getBoundingClientRect();
        return {left:r.left, top:r.top, right:r.right, bottom:r.bottom, width:r.width, height:r.height}; };
    const paper = box(canvas);
    const clip = {left:0, top:0, right:innerWidth, bottom:innerHeight};
    const clipping = [];
    for (let node = canvas.parentElement; node; node = node.parentElement) {
        const style = getComputedStyle(node), rect = node.getBoundingClientRect();
        const x = /(auto|scroll|hidden|clip)/.test(style.overflowX);
        const y = /(auto|scroll|hidden|clip)/.test(style.overflowY);
        const raw = {left:rect.left+node.clientLeft,top:rect.top+node.clientTop,
            right:rect.left+node.clientLeft+node.clientWidth,bottom:rect.top+node.clientTop+node.clientHeight};
        // In this standards-mode document, the actual scrolling root's client
        // size is the viewport. Its scrolled bounding-box origin must not be
        // added to that size. Do not exempt BODY or other clipping ancestors.
        const viewportRoot = document.compatMode === 'CSS1Compat'
            && node === document.documentElement && node === document.scrollingElement;
        const bounds = viewportRoot ? {left:0,top:0,right:node.clientWidth,bottom:node.clientHeight} : raw;
        if (x || y) clipping.push({x,y,...bounds,raw_client_box:raw,
            box_kind:viewportRoot?'document_viewport':'client_box',tag_name:node.tagName || null,
            is_document_element:node===document.documentElement,is_body:node===document.body,
            is_scrolling_element:node===document.scrollingElement});
        if (x) {
            clip.left = Math.max(clip.left, bounds.left);
            clip.right = Math.min(clip.right, bounds.right);
        }
        if (y) {
            clip.top = Math.max(clip.top, bounds.top);
            clip.bottom = Math.min(clip.bottom, bounds.bottom);
        }
    }
    const visible = {left:Math.max(paper.left,clip.left), top:Math.max(paper.top,clip.top),
        right:Math.min(paper.right,clip.right), bottom:Math.min(paper.bottom,clip.bottom)};
    const region = {left:visible.left-paper.left, top:visible.top-paper.top,
        right:visible.right-paper.left, bottom:visible.bottom-paper.top};
    const page = canvas.closest('.invoice-pdf-page');
    const points = [[visible.left+1,visible.top+1],[visible.right-1,visible.top+1],
        [visible.left+1,visible.bottom-1],[visible.right-1,visible.bottom-1],
        [(visible.left+visible.right)/2,(visible.top+visible.bottom)/2]];
    const unobscured = visible.right-visible.left > 2 && visible.bottom-visible.top > 2
        && points.every(([x,y]) => page.contains(document.elementFromPoint(x,y)));
    return {paper, clip, region, clipping, viewport:{width:innerWidth,height:innerHeight},
        document_compat_mode:document.compatMode,
        document_viewport:{width:document.documentElement.clientWidth,height:document.documentElement.clientHeight},
        unobscured, raster:{width:canvas.width,height:canvas.height},
        scroll:{top:scroll.scrollTop,left:scroll.scrollLeft,width:scroll.clientWidth,height:scroll.clientHeight,
            extent_width:scroll.scrollWidth,extent_height:scroll.scrollHeight,
            overflow_y:getComputedStyle(scroll).overflowY}};
}"""


def verify_preview_regions(regions, observation):
    """Two real scroll positions must cover the entire stable rendered page.

    One CSS pixel is only for fractional border/scroll rounding. There is no
    percentage visibility exemption: both full width and continuous full height
    must be reached within the actual ancestor-clipped browser viewport.
    """
    require(len(regions) == 2 and [r['edge'] for r in regions] == ['top', 'bottom'],
            'Both real preview scroll endpoints are required')
    first, last = regions
    size = (first['paper']['width'], first['paper']['height'])
    require(size[0] > 2 and size[1] > 2 and observation.get('ready') is True and
            observation.get('error') is False and
            observation.get('dimensions') == [dict(width=size[0], height=size[1])] and
            observation.get('raster') == [first['raster']], 'Final preview dimensions or raster are stale')
    for sample in regions:
        paper, clip, region, scroll = (sample[key] for key in ('paper', 'clip', 'region', 'scroll'))
        viewport = sample['viewport']
        actual_clip = dict(left=0,top=0,right=viewport['width'],bottom=viewport['height'])
        for ancestor in sample['clipping']:
            bounds = {key: ancestor[key] for key in ('left','top','right','bottom')}
            root = (sample.get('document_compat_mode') == 'CSS1Compat' and
                    ancestor.get('is_document_element') is True and ancestor.get('is_scrolling_element') is True)
            if root:
                require(ancestor.get('box_kind') == 'document_viewport' and ancestor.get('tag_name') == 'HTML' and
                        ancestor.get('is_body') is False and bounds == dict(left=0,top=0,
                            right=sample['document_viewport']['width'],bottom=sample['document_viewport']['height']),
                        'Actual standards-mode scrolling root must use viewport coordinates')
            else:
                require(ancestor.get('box_kind') == 'client_box' and bounds == ancestor.get('raw_client_box'),
                        'Ordinary ancestor clipping cannot be omitted or replaced with viewport bounds')
            for axis, start, end in (('x','left','right'), ('y','top','bottom')):
                if ancestor[axis]:
                    actual_clip[start] = max(actual_clip[start], ancestor[start])
                    actual_clip[end] = min(actual_clip[end], ancestor[end])
        require(clip == actual_clip and viewport['width'] > 0 and viewport['height'] > 0 and
                abs(paper['right']-paper['left']-paper['width']) < 0.01 and
                abs(paper['bottom']-paper['top']-paper['height']) < 0.01,
                'Preview clipping does not match the real viewport and ancestors')
        require(sample.get('stable_samples', 0) >= 7 and sample.get('stable_ms', 0) >= 300 and
                (paper['width'], paper['height']) == size and sample['raster'] == first['raster'] and
                sample['raster']['width'] > 0 and sample['raster']['height'] > 0,
                'Preview resized or raster changed between endpoint captures')
        require(sample.get('unobscured') is True and clip['right'] > clip['left'] and
                clip['bottom'] > clip['top'] and scroll['width'] > 0 and scroll['height'] > 0 and
                scroll['overflow_y'] in ('auto', 'scroll'), 'Preview scroll window is clipped or obscured')
        expected = dict(left=max(paper['left'], clip['left'])-paper['left'],
            top=max(paper['top'], clip['top'])-paper['top'],
            right=min(paper['right'], clip['right'])-paper['left'],
            bottom=min(paper['bottom'], clip['bottom'])-paper['top'])
        require(region == expected and region['right']-region['left'] > 2 and
                region['bottom']-region['top'] > 2 and region['left'] <= 1 and
                region['right'] >= size[0]-1, 'Actual visible region does not cover the full page width')
        require(scroll['left'] <= 1 and scroll['extent_width'] >= scroll['width'] and
                scroll['extent_height'] >= scroll['height'], 'Invalid preview scroll geometry')
    require(first['scroll']['top'] <= 1 and
            abs(last['scroll']['top']-(last['scroll']['extent_height']-last['scroll']['height'])) <= 1 and
            first['region']['top'] <= 1 and last['region']['bottom'] >= size[1]-1 and
            first['region']['bottom'] + 1 >= last['region']['top'],
            'Preview top/bottom scrolling leaves an unreachable page region')


def verified_preview_fetch(events, observation, *, source_url, source_hash, page_url,
                           phase, scope_id, record_key, console_errors):
    """Correlate one fully rendered fixture preview, never infer an abort caller.

    Only the exact observed non-range GET/200/PDF response followed by either
    completion or ERR_ABORTED qualifies. This is not a general PDF.js exception.
    The caller separately ties any failure entry to the same Request object.
    """
    require(observation.get('width') in (1440, 390, 320) and
            observation.get('stage') in ('maintenance-tab', 'maintenance-record') and
            phase == f'width:{observation["width"]}/{observation["stage"]}' and
            scope_id == phase and observation.get('phase') == phase and observation.get('scope_id') == scope_id and
            observation.get('url') == page_url, 'Preview scope or page differs')
    require(observation.get('ready') is True and observation.get('error') is False and
            observation.get('present') is True and not observation.get('wait_error') and
            observation.get('total') == observation.get('current') == '1' and
            'スクロールでページ移動' in observation.get('status', '') and
            observation.get('source_base') == urlsplit(source_url).path and
            observation.get('record_key') == record_key and
            observation.get('disclosure_open') is True and
            observation.get('disclosure_closed') is True and
            observation.get('canvas_regions_reachable') is True,
            'Preview did not complete its real visible one-page disclosure')
    verify_preview_regions(observation.get('preview_regions', []), observation)
    for key in ('dimensions', 'raster'):
        values = observation.get(key, [])
        require(len(values) == 1 and values[0].get('width', 0) > 0 and
                values[0].get('height', 0) > 0, 'Preview lacks a positive one-page raster')
    require(not console_errors, 'Invoice preview reported a console error')
    require(len(events) == 4 and [e['event'] for e in events[:3]] ==
            ['request', 'bridge_response', 'response'] and
            events[-1]['event'] in ('requestfinished', 'requestfailed'),
            'Preview source must have one complete, ordered request sequence')
    request_id = events[0]['request_id']
    sequences = [e['sequence'] for e in events]
    require(sequences == sorted(set(sequences)) and sequences[-1] <= observation['source_event_end'],
            'Preview source events are duplicated, reordered, or late')
    for event in events:
        require(event.get('request_id') == request_id and event.get('url') == source_url and
                event.get('method') == 'GET' and event.get('resource_type') == 'fetch' and
                event.get('is_navigation_request') is False and event.get('phase') == phase and
                event.get('preview_scope_id') == scope_id and
                event.get('same_preview_main_frame') is True and event.get('frame_url') == page_url,
                'Preview source request identity, frame, or stage differs')
        headers = event.get('request_headers', {})
        require('range' in headers and 'if-range' in headers and
                headers['range'] is None and headers['if-range'] is None,
                'Range requests are outside this fixture preview classification')
    bridge, response, terminal = events[1:]
    require(bridge.get('response_headers') == response.get('response_headers'),
            'Browser preview headers differ from the verified bridge response')
    require(bridge.get('source_sha256') == source_hash and
            bridge.get('mimetype') == 'application/pdf' and
            0 < bridge.get('byte_length', 0) <= 2 * 65536,
            'Preview response does not contain the exact small fixture PDF')
    for event in (bridge, response):
        headers = event.get('response_headers', {})
        require(event.get('status') == 200 and headers.get('content-type') == 'application/pdf' and
                headers.get('content-length') == str(bridge['byte_length']) and
                headers.get('content-disposition', '').startswith('inline;') and
                all(key in headers and headers[key] is None for key in
                    ('content-range', 'accept-ranges', 'content-encoding')),
                'Preview response status or complete non-range PDF headers differ')
    require(terminal['event'] == 'requestfinished' or terminal.get('failure') == 'net::ERR_ABORTED',
            'Unrecognized preview request failure')
    return dict(request_id=request_id, scope_id=scope_id, phase=phase,
        width=observation['width'], stage=observation['stage'], page_url=page_url,
        source_url=source_url, source_sha256=source_hash, byte_length=bridge['byte_length'],
        event_sequences=sequences, terminal_event=terminal['event'], failure=terminal.get('failure'),
        classification='verified_rendered_preview_fetch', abort_caller_proven=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--case', choices=('normal', 'instruction', 'recheck', 'invoice', 'periodic_instruction', 'periodic_timing', 'confirmation_manufacturer', 'confirmation_legal', 'confirmation_progression'), required=True)
    parser.add_argument('--chromium', type=Path)
    parser.add_argument('--native-invoice-download-http', action='store_true')
    parser.add_argument('--invoice-preview-observe-only', action='store_true')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preflight-only', action='store_true')
    mode.add_argument('--run-browser', action='store_true')
    args = parser.parse_args()
    require(not args.native_invoice_download_http or (args.run_browser and args.case == 'invoice'),
            'Native HTTP experiment is restricted to the invoice browser case')
    require(not args.invoice_preview_observe_only or (args.run_browser and args.case == 'invoice' and
            not args.native_invoice_download_http), 'Preview-only diagnosis requires invoice browser without native HTTP experiment')
    if args.run_browser and args.case == 'invoice' and not args.invoice_preview_observe_only:
        require(args.native_invoice_download_http, 'Explicit official-CI native invoice HTTP experiment flag required')
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
    if args.invoice_preview_observe_only:
        report.update(diagnostic_only=True, full_invoice_browser_executed=False, native_download_reexecuted=False)
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
        invoice_failed_requests = {}
        invoice_preview_scope = None
        if args.case == 'invoice':
            report['invoice_source_events'] = []
            report['invoice_downloads'] = []
            report['invoice_http_transfers'] = []
            report['invoice_preview_observations'] = []
            report['invoice_preview_console_errors'] = []
            report['verified_invoice_preview_fetches'] = []
            report['verified_invoice_preview_cancellations'] = []
            report['native_invoice_http_experiment'] = bool(args.native_invoice_download_http)
            if not args.invoice_preview_observe_only:
                report.update(diagnostic_only=False, full_invoice_browser_selected=True,
                    full_invoice_browser_executed=False, native_download_attempted=False,
                    native_download_reexecuted=False)

        def observe_invoice_source(event, request, **details):
            if args.case != 'invoice' or request.url != ORIGIN + invoice_source_path:
                return
            request_id = invoice_request_ids.setdefault(request, len(invoice_request_ids) + 1)
            scope = invoice_preview_scope
            report['invoice_source_events'].append(dict(
                sequence=len(report['invoice_source_events']) + 1, event=event,
                phase=invoice_phase, request_id=request_id, url=request.url,
                method=request.method, resource_type=request.resource_type,
                is_navigation_request=request.is_navigation_request(),
                request_headers=selected_headers(request.headers, SOURCE_REQUEST_HEADERS),
                preview_scope_id=scope['id'] if scope else None,
                same_preview_main_frame=bool(scope and request.frame == scope['frame'] and
                    request.frame.page == scope['page']), frame_url=request.frame.url, **details))
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
                            response_headers=selected_headers(response.headers, SOURCE_RESPONSE_HEADERS),
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
                        'response', response.request, status=response.status,
                        response_headers=selected_headers(response.headers, SOURCE_RESPONSE_HEADERS)))
                    context.on('requestfinished', lambda request: observe_invoice_source('requestfinished', request))
                    context.on('requestfailed', lambda request: observe_invoice_source(
                        'requestfailed', request, failure=request.failure))
                def record_failed_request(request):
                    if pdf.record_request_failed(request):
                        return
                    entry = dict(method=request.method, url=request.url, failure=request.failure)
                    report['failed_requests'].append(entry)
                    if args.case == 'invoice' and request.url == ORIGIN + invoice_source_path:
                        invoice_failed_requests[request] = entry
                context.on('requestfailed', record_failed_request)
                page = context.new_page()
                page.on('pageerror', lambda error: report['page_errors'].append(str(error)))

                def record_invoice_preview_error(message):
                    if args.case != 'invoice' or not message.text.startswith('Invoice PDF preview failed'):
                        return
                    entry = dict(phase=invoice_phase, text=message.text)
                    report['invoice_preview_console_errors'].append(entry)
                    if len(message.args) > 1:
                        try:
                            entry['error'] = message.args[1].evaluate(
                                "e => ({name: String(e?.name || ''), message: String(e?.message || e)})")
                        except Exception as error:
                            entry['detail_unavailable'] = type(error).__name__

                if args.case == 'invoice':
                    page.on('console', record_invoice_preview_error)

                def settled_invoice_preview(entry):
                    previous, stable_samples = None, 0
                    # Seven equal samples span at least 300ms, exceeding the
                    # frozen viewer's 120ms ResizeObserver debounce. No style,
                    # viewport, zoom, application state, or renderer is patched.
                    for _ in range(100):
                        state, geometry = page.evaluate(PREVIEW_STATE), page.evaluate(PREVIEW_GEOMETRY)
                        entry.update(state)
                        if state.get('ready') and geometry and (state, geometry) == previous:
                            stable_samples += 1
                        else:
                            stable_samples = 1
                        if state.get('ready') and geometry and stable_samples >= 7:
                            geometry.update(stable_samples=stable_samples, stable_ms=(stable_samples-1)*50)
                            return geometry
                        previous = (state, geometry)
                        page.wait_for_timeout(50)
                    raise AssertionError('Invoice preview did not reach a stable final rendered size')

                def observe_invoice_preview(width, stage):
                    entry = dict(width=width, stage=stage, phase=invoice_phase, url=page.url,
                        scope_id=invoice_preview_scope['id'] if invoice_preview_scope else None)
                    report['invoice_preview_observations'].append(entry)
                    viewer = page.locator('.km-detail-panel .invoice-pdf-viewer')
                    disclosure = page.locator('.km-detail-panel details.km-original')
                    expect(viewer).to_have_count(1)
                    expect(viewer).to_have_attribute('data-source-base', invoice_source_path)
                    expect(viewer).to_have_attribute('data-requested-record-key', f'maintenance_{invoice_record.id}')
                    expect(disclosure).not_to_have_attribute('open', '')
                    disclosure.locator('summary').click()
                    expect(disclosure).to_have_attribute('open', '')
                    try:
                        page.wait_for_function('() => { const state = (' + PREVIEW_STATE + ')(); return state.ready || state.error; }', timeout=10000)
                        # The first ready raster can be removed by the viewer's
                        # pending 120ms fit/ResizeObserver render. Observe the
                        # same stable final state used below before branching;
                        # a second one-shot sample can land in that canvas gap.
                        settled_invoice_preview(entry)
                    except Exception as error:
                        entry['wait_error'] = type(error).__name__
                        entry.update(page.evaluate(PREVIEW_STATE))
                    finally:
                        page.screenshot(path=str(out / f'invoice-preview-{stage}-{width}.png'), full_page=True)
                    if entry['ready']:
                        canvas = viewer.locator('.invoice-pdf-page canvas')
                        expect(canvas).to_be_visible()
                        scroll = viewer.locator('[data-pdf-scroll]')
                        scroll.scroll_into_view_if_needed()
                        geometry = settled_invoice_preview(entry)
                        page.screenshot(path=str(out / f'invoice-preview-{stage}-{width}.png'), full_page=True)
                        entry['preview_regions'] = []
                        for edge in ('top', 'bottom'):
                            scroll.hover()
                            position = page.evaluate(PREVIEW_GEOMETRY)['scroll']
                            target = 0 if edge == 'top' else position['extent_height']-position['height']
                            page.mouse.wheel(0, target-position['top'])
                            scroll.evaluate("(e,edge) => new Promise((resolve,reject) => { const start=performance.now();"
                                "const check=()=>{ const target=edge==='top'?0:e.scrollHeight-e.clientHeight;"
                                "if(Math.abs(e.scrollTop-target)<=1)return resolve();"
                                "if(performance.now()-start>5000)return reject(new Error('Preview scroll endpoint not reached'));"
                                "requestAnimationFrame(check); };check(); })", edge)
                            geometry = settled_invoice_preview(entry)
                            geometry['edge'] = edge
                            entry['preview_regions'].append(geometry)
                            suffix = 'visible' if edge == 'top' else 'visible-bottom'
                            page.screenshot(path=str(out / f'invoice-preview-{stage}-{width}-{suffix}.png'))
                        verify_preview_regions(entry['preview_regions'], entry)
                        entry['canvas_regions_reachable'] = True
                    disclosure.locator('summary').click()
                    expect(disclosure).not_to_have_attribute('open', '')
                    entry['disclosure_closed'] = True
                    entry['source_event_end'] = len(report['invoice_source_events'])
                    return entry

                def accept_invoice_preview(width, stage):
                    entry = observe_invoice_preview(width, stage)
                    scope = invoice_preview_scope
                    events = [event for event in report['invoice_source_events']
                              if event.get('preview_scope_id') == scope['id']]
                    proof = verified_preview_fetch(events, entry,
                        source_url=ORIGIN + invoice_source_path, source_hash=original_hash,
                        page_url=scope['url'], phase=invoice_phase, scope_id=scope['id'],
                        record_key=f'maintenance_{invoice_record.id}',
                        console_errors=report['invoice_preview_console_errors'])
                    report['verified_invoice_preview_fetches'].append(proof)
                    if proof['terminal_event'] == 'requestfailed':
                        request = next(request for request, identity in invoice_request_ids.items()
                                       if identity == proof['request_id'])
                        failure = invoice_failed_requests.pop(request)
                        require(failure['method'] == 'GET' and failure['url'] == proof['source_url'] and
                                failure['failure'] == 'net::ERR_ABORTED' and
                                sum(item is failure for item in report['failed_requests']) == 1,
                                'Preview failure entry is not the same verified Request')
                        report['verified_invoice_preview_cancellations'].append(dict(proof, raw_failure=failure))
                        # Keep every source event and the exact raw failure in the
                        # classified report. All other failures stay fatal.
                        report['failed_requests'][:] = [item for item in report['failed_requests'] if item is not failure]

                if args.invoice_preview_observe_only:
                    # Evidence collection only. Never call the native receiver,
                    # never substitute this result for full invoice acceptance.
                    report.update(diagnostic_only=True, full_invoice_browser_executed=False,
                        native_download_reexecuted=False, status='PREVIEW_DIAGNOSTIC_IN_PROGRESS')
                    page.set_viewport_size(dict(width=1440, height=900))
                    invoice_phase = 'width:1440/diagnostic-history'
                    page.goto(ORIGIN + paths[0], wait_until='networkidle')
                    maintenance_path = f'/vehicle/karte/{case.vehicle.id}/maintenance'
                    tab = page.locator('.vehicle-karte-tabs').get_by_role('link', name='整備・修理', exact=True)
                    expect(tab).to_have_attribute('href', maintenance_path)
                    invoice_phase = 'width:1440/maintenance-tab'
                    tab.click()
                    expect(page).to_have_url(ORIGIN + maintenance_path)
                    page.wait_for_load_state('networkidle')
                    observe_invoice_preview(1440, 'maintenance-tab')
                    link = page.locator('.km-record-content a').filter(has_text='タイヤ交換（読取訂正）')
                    expect(link).to_have_count(1)
                    href = link.get_attribute('href')
                    target = urlsplit(urljoin(ORIGIN, href))
                    require(f'{target.scheme}://{target.netloc}' == ORIGIN and
                            target.path == maintenance_path + f'/{invoice_record.id}' and
                            target.fragment == 'maintenance_detail_panel', 'Diagnostic record target differs')
                    invoice_phase = 'width:1440/maintenance-record'
                    link.click()
                    expect(page).to_have_url(urljoin(ORIGIN, href))
                    page.wait_for_load_state('networkidle')
                    observe_invoice_preview(1440, 'maintenance-record')
                    require(snapshot() == before, 'Preview observation changed protected data')
                    report.update(status='PREVIEW_DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE',
                        browser_acceptance_passed=False, protected_records_unchanged=True,
                        previews_ready=all(item.get('ready') for item in report['invoice_preview_observations']))
                    report['cases'].append('1440px preview evidence only: real tab/record/disclosures, ready/raster or error DOM, selected headers and console; failed_requests retained; full acceptance and native download not rerun')
                    return 0

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
                        invoice_preview_scope = dict(id=invoice_phase, url=ORIGIN + maintenance_path,
                            page=page, frame=page.main_frame)
                        maintenance_tab.click()
                        expect(page).to_have_url(ORIGIN + maintenance_path)
                        page.wait_for_load_state('networkidle')
                        accept_invoice_preview(width, 'maintenance-tab')
                        record_link = page.locator('.km-record-content a').filter(has_text='タイヤ交換（読取訂正）')
                        expect(record_link).to_have_count(1)
                        record_href = record_link.get_attribute('href')
                        target = urlsplit(urljoin(ORIGIN, record_href))
                        require(f'{target.scheme}://{target.netloc}' == ORIGIN and
                                target.path == maintenance_path + f'/{invoice_record.id}' and
                                target.fragment == 'maintenance_detail_panel', 'Rendered link targets a different maintenance record')
                        invoice_phase = f'width:{width}/maintenance-record'
                        invoice_preview_scope = dict(id=invoice_phase, url=urljoin(ORIGIN, record_href),
                            page=page, frame=page.main_frame)
                        record_link.click()
                        expect(page).to_have_url(urljoin(ORIGIN, record_href))
                        page.wait_for_load_state('networkidle')
                        accept_invoice_preview(width, 'maintenance-record')
                        invoice_preview_scope = None
                        detail = page.locator('.km-detail-panel')
                        expect(detail).to_contain_text('タイヤ交換（読取訂正）')
                        download_link = detail.locator('.km-file-card[download]')
                        expect(download_link).to_have_count(1)
                        expect(download_link).to_have_attribute('href', invoice_source_path)
                        invoice_phase = f'width:{width}/original-download'
                        download_href = download_link.get_attribute('href')
                        download_attribute = download_link.get_attribute('download')
                        # The normal bridge remains unchanged. This one-shot
                        # response endpoint is solely for a native download GET
                        # that does not reach Playwright's route callback.
                        original_response = get(download_href)
                        receiver = ExactInvoiceDownload(urljoin(ORIGIN, download_href),
                            original_response.status_code, original_response.headers.to_wsgi_list(),
                            original_response.get_data(), original_hash, width=width)
                        report['invoice_http_transfers'].append(receiver.report)
                        report['native_download_attempted'] = True
                        with receiver:
                            with page.expect_download() as transfer:
                                download_link.click()
                            downloaded = transfer.value
                            download_failure = downloaded.failure()
                            download_result = dict(width=width, phase=invoice_phase,
                                href=download_href, download_attribute=download_attribute,
                                url=downloaded.url, suggested_filename=downloaded.suggested_filename,
                                failure=download_failure,
                                source_event_count=len(report['invoice_source_events']))
                            report['invoice_downloads'].append(download_result)
                            require(download_failure is None, f'Original download failed: {download_failure!r}')
                            require(downloaded.url == urljoin(ORIGIN, download_href) and
                                    downloaded.suggested_filename == download_attribute,
                                    'Native download URL or filename differs from the rendered original')
                            require(hashlib.sha256(Path(downloaded.path()).read_bytes()).hexdigest() == original_hash, 'Original download changed')
                            saved_bytes = Path(downloaded.path()).read_bytes()
                            download_result.update(saved_file_sha256=hashlib.sha256(saved_bytes).hexdigest(),
                                saved_file_byte_length=len(saved_bytes))
                        receiver.assert_complete()
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
                if args.case == 'invoice':
                    require(len(report['invoice_preview_observations']) ==
                            len(report['verified_invoice_preview_fetches']) == 6 and
                            not report['invoice_preview_console_errors'],
                            'All six invoice previews must finish visibly without console errors')
                require(not report['page_errors'] and not report['failed_gets'] and not report['blocked_requests'] and not report['failed_requests'], 'Browser request or script failure')
                require(snapshot() == before, 'Browser GET changed protected saved data')
                report.update(status='PASS', browser_acceptance_passed=True, protected_records_unchanged=True)
                if args.case == 'invoice':
                    report.update(full_invoice_browser_executed=True, native_download_reexecuted=True)
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
