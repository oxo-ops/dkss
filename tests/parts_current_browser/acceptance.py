"""Real Chromium renders synthetic current-parts cards without network or live login."""
import argparse
from datetime import timedelta
import json
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
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'artifacts', 'chromium'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    require(os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED') == '1', 'Isolated runner required')
    repo = args.repo.resolve()
    output = args.artifacts.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(repo), str(repo / 'tests')]
    require(not subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True).strip(), 'Clean source required')
    report = dict(status='FAIL', source_head=subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
                  synthetic_only=True, cases=[], external_requests=0, non_get_requests=0, page_errors=0)
    from test_parts_current_distance import CurrentPartDistanceTests
    from playwright.sync_api import sync_playwright
    cls = CurrentPartDistanceTests
    cls.setUpClass()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(args.chromium), headless=True)
            for scenario in ('completed', 'unconfirmed', 'invoice', 'future', 'conflict', 'negative'):
                case = cls()
                case.setUp()
                try:
                    m = case.m
                    require(m.db.engine.url.drivername == 'sqlite', 'SQLite required')
                    require(Path(m.db.engine.url.database).resolve().is_relative_to(Path(os.environ['DKSS_VALIDATION_TMP']).resolve()), 'Isolated DB required')
                    options = {}
                    if scenario in ('unconfirmed', 'invoice'):
                        options['status'] = '入庫中'
                    if scenario == 'invoice':
                        options['invoice'] = True
                    if scenario == 'future':
                        options['completion'] = (m.datetime.now(m.ZoneInfo('Asia/Tokyo')).date() + timedelta(days=1)).isoformat()
                    if scenario == 'negative':
                        options['mileage'] = -100
                    parent, part = case.prepare(**options)
                    if scenario == 'conflict':
                        m.db.session.add(m.VehiclePartReplacement(company_code='TEST', vehicle_record_id=case.vehicle.id,
                            maintenance_record_id=parent.id, part_name='タイヤ', replacement_date=part.replacement_date,
                            mileage=1200, created_at=part.created_at))
                        m.db.session.commit()
                    expected = dict(completed='交換後 500 km', invoice='交換後 500 km',
                        unconfirmed='交換の実施未確認', future='基準日までの交換を確認できません',
                        conflict='同日の交換時距離が不一致', negative='交換時距離が未取得・不正')[scenario]
                    def saved():
                        return ([(r.id, r.status, r.completion_date, r.invoice_details_json) for r in m.VehicleMaintenanceRecord.query.order_by(m.VehicleMaintenanceRecord.id)],
                                [(r.id, r.mileage) for r in m.VehiclePartReplacement.query.order_by(m.VehiclePartReplacement.id)])
                    before = saved()
                    def bridge(route):
                        request = route.request
                        parsed = urlsplit(request.url)
                        if f'{parsed.scheme}://{parsed.netloc}' != ORIGIN:
                            report['external_requests'] += 1
                            route.abort()
                            return
                        if request.method != 'GET':
                            report['non_get_requests'] += 1
                            route.abort()
                            return
                        response = case.client.get(parsed.path + ('?' + parsed.query if parsed.query else ''))
                        headers = {k: v for k, v in response.headers.items() if k.lower() not in {'content-length', 'set-cookie', 'transfer-encoding', 'connection'}}
                        route.fulfill(status=response.status_code, headers=headers, body=response.get_data())
                    context = browser.new_context(service_workers='block')
                    try:
                        context.route('**/*', bridge)
                        page = context.new_page()
                        def page_error(_):
                            report['page_errors'] += 1
                        page.on('pageerror', page_error)
                        page.add_init_script("window.cardCsp=[];document.addEventListener('securitypolicyviolation',e=>window.cardCsp.push(e.violatedDirective));")
                        for width in (1440, 390):
                            page.set_viewport_size(dict(width=width, height=1000))
                            page.goto(ORIGIN + f'/vehicle/karte/{case.vehicle.id}/parts', wait_until='networkidle')
                            card = page.locator('.kp-current')
                            require(card.is_visible(), 'Card hidden')
                            text = ' '.join(card.inner_text().split())
                            require(expected in text, f'Expected state missing: {scenario}')
                            if scenario not in ('completed', 'invoice'):
                                require(page.locator('.kp-current-distance b').count() == 0, 'Held numeric value displayed')
                            geometry = card.evaluate("""root => ({overflow:root.scrollWidth>root.clientWidth+1,
                                rows:[...root.querySelectorAll('.kp-current-row,.kp-current-meter,.kp-current-distance')].map(e=>e.scrollWidth>e.clientWidth+1)})""")
                            require(not geometry['overflow'] and not any(geometry['rows']), f'Card overflow: {scenario}/{width}')
                            require(not page.evaluate('window.cardCsp'), 'CSP violation')
                            card.screenshot(path=str(output / f'{scenario}-{width}.png'))
                            page.reload(wait_until='networkidle')
                            require(expected in ' '.join(card.inner_text().split()), 'Reload changed state')
                            report['cases'].append(dict(scenario=scenario, width=width, geometry=geometry))
                        if scenario == 'completed':
                            part.mileage = 1500
                            m.db.session.commit()
                            before = saved()
                            page.reload(wait_until='networkidle')
                            require('交換後 0 km' in ' '.join(card.inner_text().split()), 'Known zero missing')
                            card.screenshot(path=str(output / 'known-zero-390.png'))
                        require(saved() == before, 'GET altered saved records')
                    finally:
                        context.close()
                finally:
                    case.tearDown()
            browser.close()
        require(not any(report[k] for k in ('external_requests', 'non_get_requests', 'page_errors')), 'Unexpected browser request/error')
        report['status'] = 'PASS'
    finally:
        cls.tearDownClass()
        (output / 'browser-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(dict(status=report['status'], cases=len(report['cases']))))


if __name__ == '__main__':
    main()
