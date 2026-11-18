"""Real Flask output, anonymous SQLite fixtures, zero production/network access."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument('--repo', type=Path, required=True)
parser.add_argument('--artifacts', type=Path, required=True)
parser.add_argument('--chromium')
parser.add_argument('--preflight-only', action='store_true')
args = parser.parse_args()
sys.path[:0] = [str(args.repo), str(args.repo / 'tests')]
from test_dashboard_safety_attention import DashboardSafetyAttentionTests
from dkss_app import dashboard as module
case = DashboardSafetyAttentionTests()
case.setUpClass(); case.setUp()
args.artifacts.mkdir(parents=True, exist_ok=True)
report = {'synthetic_only': True, 'cases': [], 'blocked': []}
class Clock(datetime):
    @classmethod
    def now(cls, tz=None): return cls(2026, 11, 18, 12, tzinfo=tz)
try:
    case.configure()
    case.vehicle.office = '試験営業所'
    case.m.db.session.commit()
    case.save(case.vehicle, case.recommendations(6))
    for i in range(6): case.patrol(f'構内の安全確認事項 {i + 1}', approval_status='差し戻し' if i == 1 else '承認待ち')
    source_rows = case.seed_trend()
    # Only modify the two owned anonymous source records; other-office and
    # unauthorized records remain present to exercise permission filtering.
    for row in source_rows[:2]:
        items = [dict(item_type='check', input_type='select', category='安全分野', content=name,
                      choices=['○', '△', '×']) for name in [
                          '歩行者と車両の動線確認', '荷締め用具・台木の整理', '灯火類の点灯・損傷',
                          '作業前の安全確認・声掛け', '保護具の着用', '長い項目名でも画面から飛び出さず元の記録が確認できること']]
        row.checklist_snapshot_json = json.dumps({'items': items}, ensure_ascii=False)
        row.answers_json = json.dumps([{'value': '×'} for _ in items])
    case.m.db.session.commit()
    with patch.object(module._dkss_common, 'datetime', Clock):
        html, _ = case.page()
    assert 'office-trends-video' in html and '残り' in html
    assert '他社秘密' not in html and '他営業所秘密' not in html
    if not args.preflight_only:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(**({'executable_path': args.chromium} if args.chromium else {}))
            for width in [320, 390, 768, 1440]:
                context = browser.new_context(viewport={'width': width, 'height': 1000}, device_scale_factor=1)
                def bridge(route):
                    url = urlsplit(route.request.url)
                    if url.hostname != '127.0.0.1' or route.request.method != 'GET':
                        report['blocked'].append(route.request.url); route.abort(); return
                    if url.path == '/': route.fulfill(status=200, content_type='text/html', body=html); return
                    with patch.object(module._dkss_common, 'datetime', Clock): response = case.client.get(url.path + ('?' + url.query if url.query else ''))
                    route.fulfill(status=response.status_code, headers={k:v for k,v in response.headers.items() if k.lower() not in ['set-cookie','content-length','content-encoding']}, body=response.data)
                context.route('**/*', bridge)
                page = context.new_page(); page.goto('http://127.0.0.1/', wait_until='networkidle')
                panel = page.locator('.office-trends-video'); panel.scroll_into_view_if_needed()
                assert panel.locator('.office-trend-panel > .office-trend-row').count() == 5
                assert panel.locator('.office-action-panel > .office-action-list > li').count() == 5
                boxes = panel.evaluate("el => [...el.children].map(x => ({x:x.getBoundingClientRect().x,y:x.getBoundingClientRect().y,w:x.getBoundingClientRect().width}))")
                if width > 700: assert abs(boxes[0]['w'] - boxes[1]['w']) < 1
                else: assert boxes[1]['y'] > boxes[0]['y']
                assert panel.evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                panel.screenshot(path=str(args.artifacts / f'office-{width}.png'))
                panel.locator('.office-trend-row > summary').first.click()
                assert panel.locator('.office-trend-row[open] .office-trend-records a').first.is_visible()
                panel.locator('.office-action-panel > .office-panel-more > summary').click()
                assert panel.locator('.office-action-panel > .office-panel-more .office-action-link').first.is_visible()
                report['cases'].append({'width': width, 'passed': True, 'columns': boxes})
                context.close()
            browser.close()
    report['preflight_passed'] = True
    report['browser_verified'] = not args.preflight_only and len(report['cases']) == 4 and not report['blocked']
finally:
    (args.artifacts / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    case.tearDown(); case.tearDownClass()
