#!/usr/bin/env python3
"""Exact-head, synthetic ordinary-priority UI acceptance using a GET-only Flask bridge."""
import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

ORIGIN = 'http://127.0.0.1:8765'


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--chromium', type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preflight-only', action='store_true')
    mode.add_argument('--run-browser', action='store_true')
    args = parser.parse_args()
    require(os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED') == '1', 'Isolated runner required')
    require(os.environ.get('DATABASE_URL') == 'sqlite:///:memory:', 'Disposable DB only')
    repo, out = args.repo.resolve(), args.artifacts.resolve()
    sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    tree = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
    require(sha == args.expected_sha, 'Wrong exact head')
    require(not subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True).strip(), 'Dirty source')
    if args.run_browser:
        require(args.chromium and args.chromium.is_file(), 'Installed Chromium path required')
    os.chdir(repo); sys.path[:0] = [str(repo), str(repo / 'tests')]; out.mkdir(parents=True, exist_ok=True)
    from test_priority_common_routes import CommonPriorityRouteTests
    from test_dashboard_saved_proposals import DashboardSavedProposalTests
    from sqlalchemy import event
    from unittest.mock import patch
    report = dict(candidate_sha=sha, candidate_tree=tree, fixture_only=True, production_accessed=False,
                  browser_started=False, browser_acceptance_passed=False, cases=[], page_errors=[],
                  blocked_requests=[], failed_gets=[], writes=[], started_utc=datetime.now(timezone.utc).isoformat())
    case = CommonPriorityRouteTests(); started = setup = listening = False
    active = ['fixture']
    try:
        case.setUpClass(); started = True; case.setUp(); setup = True
        m = case.m
        root = Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
        require(m.db.engine.url.drivername == 'sqlite' and Path(m.db.engine.url.database).resolve().is_relative_to(root), 'Fixture root mismatch')
        user = DashboardSavedProposalTests.configure(case)
        user.dashboard_settings_json = json.dumps({'vehicle_karte_last_vehicle_id': case.vehicle.id})
        m.db.session.commit()
        state, bundle, inspection = case.seed_analysis()
        original = bundle['analysis']['recommendations'][0]
        # These are explicitly legacy proposals with no invented new numeric score.
        bundle['analysis']['recommendations'] += [dict(deepcopy(original), target=f'保存対象{i}',
            title=f'保存提案{i}', priority=label, current_state='保存された状態', reason='保存された理由', timing='記録確認')
            for i, label in enumerate(('高', '中', '低', '低', '低', ''))]
        bundle['analysis']['recommendations'][0].update(current_state='標準点検の具体的な異常回答', reason='元の点検を確認', timing='責任者に確認')
        state.result_json = json.dumps(bundle, ensure_ascii=False); m.db.session.commit()
        before = case.original_snapshot()
        def request(path):
            parsed = urlsplit(path)
            active[0] = parsed.path
            response = case.client.get(path)
            if response.status_code >= 400: report['failed_gets'].append({'path': parsed.path, 'status': response.status_code})
            return response
        def track(_conn, _cursor, statement, _parameters, _context, _many):
            verb = statement.lstrip().split(None, 1)[0].upper()
            if verb in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'CREATE', 'ALTER', 'DROP'}:
                match = re.match(r'\s*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+["`]?([A-Za-z_][A-Za-z_0-9]*)', statement, re.I)
                report['writes'].append(dict(path=active[0], verb=verb, table=match.group(1) if match else 'UNKNOWN'))
        def validate():
            m.db.session.expire_all()
            require(case.original_snapshot() == before, 'Analysis, source, judgment, feedback, evaluation, notification or maintenance changed')
            for row in report['writes']:
                allowed = row['path'] == '/' and row['table'] == 'company_usage_summary' and row['verb'] in {'INSERT', 'UPDATE'}
                allowed |= row['path'] in {'/api/notifications/recent','/api/notifications/unread-count'} and (row['verb'],row['table']) in {('UPDATE','company'),('INSERT','inspection_plan_alert_run'),('UPDATE','inspection_plan_alert_run')}
                allowed |= row['path'] == f'/vehicle/karte/{case.vehicle.id}' and row['table'] == 'user' and row['verb'] == 'UPDATE'
                require(allowed, 'Unexpected ordinary-page write')
        event.listen(m.db.engine, 'before_cursor_execute', track); listening = True
        with ExitStack() as stack:
            stack.enter_context(case.frozen_projection(bundle))
            stack.enter_context(patch.object(m, 'analyze_vehicle_karte', side_effect=AssertionError('No AI')))
            stack.enter_context(patch.object(m, 'queue_vehicle_karte_analysis', side_effect=AssertionError('No queue')))
            data = request(case.url).json
            items = data['analysis']['recommendations']; target = items[0]['target']
            require(items[0]['priority_assessment']['effective_score'] == 50, 'Real scoped ORM medium projection missing')
            computed_id = items[0]['proposal_id']
            expected = data['analysis']['priority_order']
            require(len(expected) == 7, 'Fixture count')
            for path in ('/', f'/vehicle/karte/{case.vehicle.id}', f'/vehicle/karte/{case.vehicle.id}/analysis'):
                require(request(path).status_code == 200, 'Normal route unavailable')
            validate(); report['cases'].append('PREFLIGHT: normal GET + dashboard + overview + analysis; source/answer/ID unchanged')
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
                            report['blocked_requests'].append(dict(method=req.method, host=parsed.hostname, path=parsed.path));route.abort();return
                        response = request(parsed.path + ('?' + parsed.query if parsed.query else ''))
                        headers = {k:v for k,v in response.headers.items() if k.lower() not in {'content-length','transfer-encoding','connection','set-cookie'}}
                        route.fulfill(status=response.status_code,headers=headers,body=response.get_data())
                    context.route('**/*', bridge)
                    page = context.new_page();page.on('pageerror',lambda error:report['page_errors'].append(str(error)))
                    for width,height in ((1440,900),(1024,768),(768,700),(390,700),(320,640)):
                        page.set_viewport_size(dict(width=width,height=height))
                        page.goto(ORIGIN+f'/vehicle/karte/{case.vehicle.id}',wait_until='networkidle')
                        rows=page.locator('#ko-ai .ko-proposal');expect(rows).to_have_count(5)
                        require(rows.evaluate_all('(rows)=>rows.map(r=>r.dataset.proposalId)') == expected[:5], 'Overview order differs')
                        computed = page.locator(f'#ko-ai .ko-proposal[data-proposal-id="{computed_id}"]')
                        expect(computed.locator('.ko-priority')).to_have_text('中 · 50点')
                        require(computed.locator('.ko-priority').evaluate('''badge => {
                            const range=document.createRange();range.selectNodeContents(badge);
                            return range.getClientRects().length===1 && badge.scrollWidth<=badge.clientWidth+1;
                        }'''), 'Computed overview badge wraps or overflows')
                        require(computed.evaluate('row => row.children[0].getBoundingClientRect().right <= row.querySelector(".ko-proposal-copy").getBoundingClientRect().left'), 'Computed badge overlaps proposal text')
                        expect(rows.first.locator('.priority-response-note')).to_contain_text('保存版')
                        require(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'Overview page overflow')
                        page.screenshot(path=str(out/f'overview-{width}.png'),full_page=True)
                        computed.get_by_role('link',name=re.compile('詳細：')).click()
                        drawer=page.locator('.ka-reference-drawer');expect(drawer).to_be_visible()
                        expect(drawer.locator('.ka-drawer-priority-row .ka-ai-priority')).to_have_text('中 · 50点')
                        details=drawer.locator('.priority-response-details');details.locator('summary').click()
                        expect(details).to_contain_text('基本点 50点');expect(details).to_contain_text('0点の判定ではありません')
                        expect(details).to_contain_text('運行可否・既存指示の解除は責任者')
                        page.screenshot(path=str(out/f'detail-{width}.png'),full_page=True)
                        source_link=details.locator('.priority-response-source').first
                        source_link.scroll_into_view_if_needed();expect(source_link).to_be_in_viewport()
                        require(source_link.get_attribute('href').startswith(ORIGIN+'/'), 'Source link is not same-origin')
                        disclaimer=details.locator('.priority-response-disclaimer')
                        disclaimer.scroll_into_view_if_needed();expect(disclaimer).to_be_in_viewport()
                        page.screenshot(path=str(out/f'detail-bottom-{width}.png'),full_page=True)
                        page.keyboard.press('Escape');expect(drawer).to_be_hidden()
                        page.locator('.ka7-proposal-table tr').filter(has_text=target).locator('.ka-reference-detail-button').click()
                        expect(drawer).to_be_visible();drawer.get_by_role('button',name='提案の詳細を閉じる').click();expect(drawer).to_be_hidden()
                        require(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'Analysis page overflow')
                        page.goto(ORIGIN+'/',wait_until='networkidle')
                        panel=page.locator('.dashboard-attention-panel').first
                        expect(panel.locator('.dashboard-attention-preview tbody tr')).to_have_count(5)
                        expect(panel.locator('.dashboard-attention-priority').filter(has_text='中 · 50点')).to_have_count(1)
                        preview=panel.locator('.dashboard-attention-preview')
                        expect(preview.locator('.dashboard-priority-note').filter(has_text='要確認')).to_be_visible()
                        legacy_notes=preview.locator('.dashboard-priority-note').filter(has_text='保存版・算定根拠を確認')
                        expect(legacy_notes).to_have_count(4)
                        for note in legacy_notes.all():expect(note).to_be_visible()
                        panel.get_by_role('button',name='全件を見る').click()
                        invalid=panel.locator('tr').filter(has_text='保存対象5')
                        expect(invalid.locator('.dashboard-priority-note')).to_be_visible()
                        expect(invalid.locator('.dashboard-priority-note')).to_have_text('優先度の元データを確認してください。')
                        expect(invalid.locator('.dashboard-attention-priority')).to_have_count(0)
                        page.screenshot(path=str(out/f'dashboard-{width}.png'),full_page=True)
                        report['cases'].append(f'BROWSER {width}: common score/order, legacy no score, source details, repeated open/Escape/Close, contained page')
                    page.goto(ORIGIN+f'/vehicle/karte/{case.vehicle.id}',wait_until='networkidle')
                    page.locator(f'#ko-ai .ko-proposal[data-proposal-id="{computed_id}"]').get_by_role('link',name=re.compile('詳細：')).click()
                    expect(page.locator('.ka-reference-drawer')).to_be_visible()
                    page.go_back(wait_until='networkidle');expect(page.locator('#ko-ai .ko-proposal')).to_have_count(5)
                    page.go_forward(wait_until='networkidle');expect(page.locator('.ka-reference-drawer')).to_be_visible()
                    validate();require(not report['page_errors'] and not report['failed_gets'] and not report['blocked_requests'],'Browser request or script error')
                    report.update(status='PASS',browser_acceptance_passed=True,saved_records_unchanged=True)
                    return 0
                except Exception:
                    if 'page' in locals() and not page.is_closed():page.screenshot(path=str(out/'failure.png'),full_page=True)
                    raise
                finally:browser.close()
    except Exception as error:
        report.update(status='FAILED_OR_BLOCKED',error_type=type(error).__name__)
        if isinstance(error,AssertionError):report['safe_failure']=str(error)
        raise
    finally:
        if listening:event.remove(m.db.engine,'before_cursor_execute',track)
        if setup:case.tearDown()
        if started:case.tearDownClass()
        report['finished_utc']=datetime.now(timezone.utc).isoformat()
        (out/('preflight-result.json' if args.preflight_only else 'browser-result.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':raise SystemExit(main())
