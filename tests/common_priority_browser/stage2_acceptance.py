#!/usr/bin/env python3
"""Ordinary existing-input priority flows in disposable authenticated fixtures."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
from unittest.mock import patch

ORIGIN = 'http://127.0.0.1:8765'


def require(value, message):
    if not value:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--case', choices=('instruction', 'recheck', 'timing'), required=True)
    parser.add_argument('--chromium', type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preflight-only', action='store_true')
    mode.add_argument('--run-browser', action='store_true')
    args = parser.parse_args()
    require(os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED') == '1', 'Isolation required')
    require(os.environ.get('DATABASE_URL') == 'sqlite:///:memory:', 'Disposable DB only')
    repo, out = args.repo.resolve(), args.artifacts.resolve()
    sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    tree = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
    require(sha == args.expected_sha, 'Exact head mismatch')
    require(not subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True).strip(), 'Dirty source')
    if args.run_browser:
        require(args.chromium and args.chromium.is_file(), 'Authorized browser path required')
    os.chdir(repo); sys.path[:0] = [str(repo), str(repo / 'tests')]; out.mkdir(parents=True, exist_ok=True)
    from sqlalchemy import event
    from vehicle_priority_inputs import offered_priority_inputs, validate_priority_input
    if args.case == 'timing':
        from test_priority_adopted_timing import AdoptedTimingPriorityTests as Case
    else:
        from test_priority_stage2_workflow import PriorityStage2WorkflowTests as Case
    case = Case(); started = setup = listening = False
    report = dict(candidate_sha=sha, candidate_tree=tree, scenario=args.case, fixture_only=True,
        production_accessed=False, browser_started=False, browser_acceptance_passed=False,
        cases=[], page_errors=[], failed_gets=[], blocked_requests=[], writes=[],
        started_utc=datetime.now(timezone.utc).isoformat())
    active = ['fixture']
    try:
        case.setUpClass(); started = True; case.setUp(); setup = True
        if args.case == 'timing':
            m, app, db = case.m, case.m.app, case.m.db
            case.setup_rule()
            payload, sources = case.generate()
            option = next(v for v in offered_priority_inputs(payload).values() if v['kind'] == 'adopted_timing')
            item = dict(priority='低', category='整備・点検', target=option['display_target'],
                title='登録された交換基準の確認', action='登録実績と適用基準を確認',
                current_state='登録実績に基づく交換計画', reason='採用済み基準と元実績', timing='記録された期限を確認',
                source_ids=option['source_ids'], priority_input_ref=option['ref'])
            validate_priority_input(item, payload)
            bundle = dict(analysis={'recommendations': [item]}, sources=sources, fingerprints=payload['_fingerprints'])
            state = m.VehicleKarteAnalysis(company_code=case.vehicle.company_code, vehicle_record_id=case.vehicle.id,
                status='completed', result_json=json.dumps(bundle, ensure_ascii=False, default=str))
            db.session.add(state); db.session.commit()
            expected_score = 35
        else:
            m, app, db = case.models, case.app, case.db
            case.begin_priority()
            if args.case == 'instruction':
                case.decide('運行不可')
                bundle, state = case.generate('registered_operation_instruction')
                expected_score = 60
            else:
                case.decide('運行可'); case.repair_priority()
                bundle, state = case.generate()
                expected_score = 25
            case.login('admin')
        root = Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
        require(db.engine.url.drivername == 'sqlite' and Path(db.engine.url.database).resolve().is_relative_to(root), 'Wrong fixture DB')
        company = case.vehicle.company_code
        user = m.User.query.filter_by(company_code=company, username='admin').one()
        user.office = case.vehicle.office = '試験営業所'
        user.dashboard_settings_json = json.dumps({'vehicle_karte_last_vehicle_id': case.vehicle.id})
        if not m.Office.query.filter_by(company_code=company, name='試験営業所').first():
            db.session.add(m.Office(company_code=company, name='試験営業所'))
        db.session.add(m.Driver(company_code=company, employee_id='admin', name='検証 管理者',
            office='試験営業所', vehicles_json=json.dumps([str(case.vehicle.id)])))
        db.session.commit()
        vehicle_id = case.vehicle.id
        url = f'/vehicle/karte/{vehicle_id}/analysis/result'
        def snapshot():
            db.session.expire_all()
            excluded = {'company_usage_summary', 'company', 'inspection_plan_alert_run', 'user'}
            return {table.name: [tuple(row) for row in db.session.execute(table.select().order_by(*table.primary_key.columns))]
                for table in db.metadata.sorted_tables if table.name not in excluded}
        before = snapshot()
        def request(path):
            active[0] = urlsplit(path).path
            response = case.client.get(path)
            if response.status_code >= 400:
                report['failed_gets'].append(dict(path=active[0], status=response.status_code))
            return response
        def track(_conn, _cursor, statement, _parameters, _context, _many):
            verb = statement.lstrip().split(None, 1)[0].upper()
            if verb in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'CREATE', 'ALTER', 'DROP'}:
                match = re.match(r'\s*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+["`]?([A-Za-z_][A-Za-z_0-9]*)', statement, re.I)
                report['writes'].append(dict(path=active[0], verb=verb, table=match.group(1) if match else 'UNKNOWN'))
        def validate():
            require(snapshot() == before, 'Protected saved records changed')
            for row in report['writes']:
                allowed = row['path'] == '/' and row['table'] == 'company_usage_summary' and row['verb'] in {'INSERT', 'UPDATE'}
                allowed |= row['path'] in {'/api/notifications/recent', '/api/notifications/unread-count'} and (row['verb'], row['table']) in {('UPDATE', 'company'), ('INSERT', 'inspection_plan_alert_run'), ('UPDATE', 'inspection_plan_alert_run')}
                allowed |= row['path'] == f'/vehicle/karte/{vehicle_id}' and row['table'] == 'user' and row['verb'] == 'UPDATE'
                require(allowed, 'Unexpected ordinary-page write')
        event.listen(db.engine, 'before_cursor_execute', track); listening = True
        with ExitStack() as stack:
            # Only cache freshness/peer payload is held fixed. Actual priority
            # source, event, adoption and current-record adapters run unchanged.
            stack.enter_context(patch('dkss_app.analysis.get_vehicle_analysis_read_projection', return_value=(
                {'fingerprints': bundle['fingerprints'], 'input_summary': {}, 'comparison': None}, True)))
            data = request(url).json
            items = data['analysis']['recommendations']; require(len(items) == 1, 'One ordinary candidate expected')
            item = items[0]; assessment = item['priority_assessment']
            require(assessment['effective_score'] == expected_score, 'Expected ordinary score missing')
            if args.case in {'instruction', 'recheck'}:
                require(all(f['points'] is None for f in assessment['factors']), 'Unknown axes were filled')
            subject = assessment.get('subject_label') or item['target']
            proposal_id = item['proposal_id']; label = item['priority']; badge_text = f'{label} · {expected_score}点'
            for path in ('/', f'/vehicle/karte/{vehicle_id}', f'/vehicle/karte/{vehicle_id}/analysis'):
                require(request(path).status_code == 200, 'Normal view unavailable')
            validate(); report['cases'].append(f'PREFLIGHT {args.case}: ordinary API + three views; score {expected_score}; protected records unchanged')
            if args.preflight_only:
                report['status'] = 'PREFLIGHT_PASS_BROWSER_NOT_RUN'; return 0
            from playwright.sync_api import sync_playwright, expect
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=str(args.chromium.resolve()))
                report.update(browser_started=True, browser_version=browser.version)
                try:
                    context = browser.new_context(service_workers='block')
                    def bridge(route):
                        req = route.request; parsed = urlsplit(req.url)
                        if f'{parsed.scheme}://{parsed.netloc}' != ORIGIN or req.method != 'GET':
                            report['blocked_requests'].append(dict(method=req.method, host=parsed.hostname, path=parsed.path)); route.abort(); return
                        response = request(parsed.path + ('?' + parsed.query if parsed.query else ''))
                        headers = {k: v for k, v in response.headers.items() if k.lower() not in {'content-length', 'transfer-encoding', 'connection', 'set-cookie'}}
                        route.fulfill(status=response.status_code, headers=headers, body=response.get_data())
                    context.route('**/*', bridge)
                    page = context.new_page(); page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
                    for width, height in ((1440, 900), (1024, 768), (768, 700), (390, 700), (320, 640)):
                        page.set_viewport_size(dict(width=width, height=height))
                        page.goto(ORIGIN + f'/vehicle/karte/{vehicle_id}', wait_until='networkidle')
                        row = page.locator(f'#ko-ai .ko-proposal[data-proposal-id="{proposal_id}"]')
                        expect(row.locator('.ko-priority')).to_have_text(badge_text)
                        require(row.locator('.ko-priority').evaluate('b=>{const r=document.createRange();r.selectNodeContents(b);return r.getClientRects().length===1}'), 'Score badge wraps')
                        if args.case == 'instruction': expect(row.locator('.priority-response-note')).to_contain_text('責任者・整備担当者の判断を優先')
                        require(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), 'Overview overflow')
                        page.screenshot(path=str(out / f'overview-{width}.png'), full_page=True)
                        row.get_by_role('link', name=re.compile('詳細：')).click()
                        drawer = page.locator('.ka-reference-drawer'); expect(drawer).to_be_visible()
                        expect(drawer.locator('.ka-drawer-priority-row .ka-ai-priority')).to_have_text(badge_text)
                        details = drawer.locator('.priority-response-details'); details.locator('summary').click()
                        expect(details).to_contain_text(subject)
                        if args.case == 'instruction':
                            attribution = details.locator('.priority-response-instruction'); expect(attribution).to_contain_text('車両全体')
                            expect(attribution).to_contain_text(assessment['instruction_details']['actor_name'])
                            expect(attribution).to_contain_text(assessment['instruction_details']['recorded_at'])
                            attribution.scroll_into_view_if_needed(); expect(attribution).to_be_in_viewport()
                        elif args.case == 'recheck':
                            expect(details).to_contain_text('再確認待ち'); expect(details).to_contain_text('下限による調整：+25点')
                            expect(details).to_contain_text('0点の判定ではありません')
                        else:
                            reference = details.locator('.priority-response-reference'); expect(reference).to_contain_text('適用した交換基準')
                            expect(reference).to_contain_text(assessment['timing_reference']['quote'])
                            expect(reference).to_contain_text(assessment['timing_origin_on'])
                            reference.scroll_into_view_if_needed(); expect(reference).to_be_in_viewport()
                        page.screenshot(path=str(out / f'detail-{width}.png'), full_page=True)
                        disclaimer = details.locator('.priority-response-disclaimer'); disclaimer.scroll_into_view_if_needed(); expect(disclaimer).to_be_in_viewport()
                        expect(disclaimer).to_contain_text('運行可否・既存指示の解除は責任者')
                        page.screenshot(path=str(out / f'detail-bottom-{width}.png'), full_page=True)
                        page.keyboard.press('Escape'); expect(drawer).to_be_hidden()
                        page.locator('.ka-reference-detail-button').first.click(); expect(drawer).to_be_visible()
                        drawer.get_by_role('button', name='提案の詳細を閉じる').click(); expect(drawer).to_be_hidden()
                        page.goto(ORIGIN + '/', wait_until='networkidle')
                        panel = page.locator('.dashboard-attention-panel').first
                        expect(panel.locator('.dashboard-attention-priority')).to_have_text(badge_text)
                        expect(panel.locator('.dashboard-priority-note')).to_be_visible()
                        if args.case == 'instruction': expect(panel.locator('.dashboard-priority-note')).to_contain_text('責任者・整備担当者の判断を優先')
                        require(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), 'Dashboard overflow')
                        page.screenshot(path=str(out / f'dashboard-{width}.png'), full_page=True)
                        report['cases'].append(f'BROWSER {args.case} {width}: score, canonical subject, evidence, disclaimer, repeated detail Close/Escape, contained layout')
                    page.goto(ORIGIN + f'/vehicle/karte/{vehicle_id}', wait_until='networkidle')
                    page.locator('#ko-ai .ko-proposal-detail').click(); expect(page.locator('.ka-reference-drawer')).to_be_visible()
                    page.go_back(wait_until='networkidle'); expect(page.locator('#ko-ai .ko-proposal')).to_have_count(1)
                    page.go_forward(wait_until='networkidle'); expect(page.locator('.ka-reference-drawer')).to_be_visible()
                    validate(); require(not report['page_errors'] and not report['failed_gets'] and not report['blocked_requests'], 'Browser request/script failure')
                    report.update(status='PASS', browser_acceptance_passed=True, saved_records_unchanged=True)
                    return 0
                except Exception:
                    if 'page' in locals() and not page.is_closed(): page.screenshot(path=str(out / 'failure.png'), full_page=True)
                    raise
                finally:
                    browser.close()
    finally:
        if listening: event.remove(db.engine, 'before_cursor_execute', track)
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (out / 'browser-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        if setup: case.tearDown(); case.doCleanups()
        if started: case.tearDownClass()
        print(json.dumps({k: v for k, v in report.items() if k != 'writes'}, ensure_ascii=False, default=str))


if __name__ == '__main__':
    raise SystemExit(main())
