#!/usr/bin/env python3
"""UI⑤ acceptance: real Chromium, synthetic Flask GET bridge, existing CSP."""
import argparse
import json
import os
from pathlib import Path
import sys
import subprocess
from urllib.parse import parse_qs, urlsplit

ORIGIN = 'http://127.0.0.1:8765'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--chromium', type=Path, required=True)
    args = parser.parse_args()
    require(os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED') == '1', 'Use isolated runner')
    repo = args.repo.resolve(); output = args.artifacts.resolve(); output.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(repo), str(repo/'tests')]
    source_head = subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    source_tree = subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD^{tree}'],text=True).strip()
    require(not subprocess.check_output(['git','-C',str(repo),'status','--porcelain','--untracked-files=all'],text=True).strip(),'Candidate must be clean')
    from test_vehicle_comparison_panels import VehicleComparisonRouteTests
    from playwright.sync_api import sync_playwright
    case = VehicleComparisonRouteTests()
    report = dict(source_head=source_head, source_tree=source_tree, status='FAIL', browser_started=False, cases=[], errors=[],
                  external_requests=[], non_get_requests=[],
                  transport='in-process Flask GET bridge, no live login/TLS', synthetic_only=True)
    case.setUpClass(); case.setUp()
    try:
        url = case.seed(); m = case.m
        require(m.db.engine.url.drivername == 'sqlite', 'SQLite fixture required')
        require(Path(m.db.engine.url.database).resolve().is_relative_to(Path(os.environ['DKSS_VALIDATION_TMP']).resolve()), 'DB outside isolated directory')
        def saved():
            return [[(r.id, r.total_cost, r.status, r.completion_date, r.invoice_details_json) for r in m.VehicleMaintenanceRecord.query.order_by(m.VehicleMaintenanceRecord.id)],
                    [(r.id,r.part_name,r.part_number,r.mileage) for r in m.VehiclePartReplacement.query.order_by(m.VehiclePartReplacement.id)]]
        before=saved()
        def bridge(route):
            request=route.request; parsed=urlsplit(request.url)
            if f'{parsed.scheme}://{parsed.netloc}' != ORIGIN:
                report['external_requests'].append(request.url);route.abort();return
            if request.method != 'GET':
                report['non_get_requests'].append(request.method+' '+parsed.path);route.abort();return
            response=case.client.get(parsed.path+('?' + parsed.query if parsed.query else ''))
            headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-length','set-cookie','transfer-encoding','connection'}}
            route.fulfill(status=response.status_code,headers=headers,body=response.get_data())
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=str(args.chromium),headless=True,args=['--no-sandbox'])
            report['browser_started']=True
            context=browser.new_context(service_workers='block')
            context.route('**/*',bridge)
            page=context.new_page()
            page.on('pageerror',lambda error:report['errors'].append(str(error)))
            page.add_init_script("window.ui5Csp=[];document.addEventListener('securitypolicyviolation',e=>window.ui5Csp.push({directive:e.violatedDirective,source:e.sourceFile,line:e.lineNumber}));")
            def visit(path=url):
                page.goto(ORIGIN+path,wait_until='networkidle')
                require(page.locator('.ka5-comparison-grid').is_visible(),'Comparison panels hidden')
            def geometry(label):
                result=page.locator('.ka5-comparison-grid').evaluate('''root=>({
                    rootOverflow:root.scrollWidth>root.clientWidth+1,
                    items:[...root.querySelectorAll('.ka5-panel,.ka5-rate-row,.ka5-rate-value')].map(e=>({class:e.className,overflow:e.scrollWidth>e.clientWidth+1,width:e.getBoundingClientRect().width})),
                    inline:root.querySelectorAll('[style]').length,
                    fills:[...root.querySelectorAll('.ka5-rate-track rect')].map(e=>({width:e.getBoundingClientRect().width,fill:getComputedStyle(e).fill})),
                    cols:getComputedStyle(root).gridTemplateColumns
                })''')
                require(not result['rootOverflow'] and not any(r['overflow'] for r in result['items']),f'Panel overflow: {label} {result}')
                require(result['inline']==0,'Inline style bypassed CSP')
                require(all(r['fill'] in ['rgb(45, 107, 179)','rgb(144, 170, 206)'] for r in result['fills']),'Bar colors not applied')
                require(not page.evaluate('window.ui5Csp'),'CSP violation')
                report['cases'].append(dict(case=label,geometry=result))
            for width in [1440,1024,768,390,320]:
                page.set_viewport_size(dict(width=width,height=1000));visit()
                require('6.00' in page.locator('[data-rate=current]').inner_text(),'Own rate missing')
                require('5.00' in page.locator('[data-rate=average]').inner_text(),'Peer average wrong')
                require('0 km' in page.locator('.ka5-parts-table').inner_text(),'Measured zero missing')
                geometry(f'facts-{width}')
                page.locator('.ka5-comparison-grid').screenshot(path=str(output/f'facts-{width}.png'))
            # Query, reload and browser history use actual GET form navigation.
            page.set_viewport_size(dict(width=390,height=1000));visit()
            page.locator('.ka5-peer-panel details summary').click()
            page.locator('select[name=peer_registration]').select_option('all_years')
            page.locator('input[name=peer_inactive]').check()
            page.locator('.ka7-peer-conditions button').click();page.wait_for_load_state('networkidle')
            q=parse_qs(urlsplit(page.url).query)
            require(q.get('peer_registration')==['all_years'] and q.get('peer_inactive')==['1'] and q.get('start_date')==['2026-09-01'],'Peer query lost')
            page.reload(wait_until='networkidle')
            require('15.00' in page.locator('[data-rate=average]').inner_text(),'Reload changed mean')
            page.locator('#ka-start-date').fill('2026-09-02')
            page.locator('.ka-period-form button').click();page.wait_for_load_state('networkidle')
            q=parse_qs(urlsplit(page.url).query)
            require(q.get('peer_registration')==['all_years'] and q.get('peer_inactive')==['1'],'Period lost peer settings')
            require('算出保留' in page.locator('[data-rate=current]').inner_text(),'Missing period rendered as zero')
            page.go_back(wait_until='networkidle')
            require('15.00' in page.locator('[data-rate=average]').inner_text(),'Back did not restore mean')
            page.go_back(wait_until='networkidle')
            require('5.00' in page.locator('[data-rate=average]').inner_text(),'Back did not restore original filters')
            link=page.locator('.ka5-parts-table a').first
            href=link.get_attribute('href')
            with page.expect_popup() as opened: link.click()
            popup=opened.value;popup.wait_for_load_state('networkidle')
            require(urlsplit(popup.url).path==href,'Part record destination wrong')
            require(popup.locator('body').is_visible(),'Part record not readable');popup.close()
            require(saved()==before,'Read flow mutated cost or parts')
            report['cases'].append('GET filters, reload, Back, part link, unchanged saved records')
            # Stress saved records, not hard-coded rendered values.
            for index in range(28):
                m.db.session.add(m.VehiclePartReplacement(company_code='TEST',vehicle_record_id=case.vehicle.id,
                    maintenance_record_id=case.parent.id,part_name=('長い部品名称と取付位置'*10)+str(index),
                    part_number=('PART-NUMBER-'*10)+str(index),replacement_date='2026-09-01',
                    mileage=1000,created_at='2026-09-01T00:00:00+09:00'))
            first=m.VehicleMaintenanceRecord.query.filter_by(vehicle_record_id=case.vehicle.id).first()
            first.total_cost=123456789
            m.db.session.commit()
            for width in [1440,390,320]:
                page.set_viewport_size(dict(width=width,height=1000));visit();geometry(f'large-numbers-long-many-{width}')
                require(page.locator('.ka5-parts-table tbody tr').count()==32,'Long records omitted')
                require(page.locator('.ka5-parts-scroll').evaluate('e=>e.scrollHeight>e.clientHeight'),'Many records not scrollable')
                page.locator('.ka5-parts-scroll').evaluate('e=>e.scrollTop=e.scrollHeight')
                page.locator('.ka5-comparison-grid').screenshot(path=str(output/f'long-many-{width}.png'))
            # All-zero costs still show both panels, SVG width 0 is genuine zero.
            for row in m.VehicleMaintenanceRecord.query.all():row.total_cost=0
            m.db.session.commit();visit();geometry('known-zero')
            require('0.00' in page.locator('[data-rate=current]').inner_text(),'Known zero missing')
            require(page.locator('[data-rate=current] rect').get_attribute('width')=='0','Zero bar invented')
            page.locator('.ka5-comparison-grid').screenshot(path=str(output/'zero-320.png'))
            # Missing costs and parts-only must remain visible.
            for row in m.VehicleMaintenanceRecord.query.all():row.total_cost=None
            m.db.session.commit();visit();geometry('parts-only')
            require('算出保留' in page.locator('[data-rate=current]').inner_text(),'Unknown cost became zero')
            m.VehiclePartReplacement.query.delete();m.db.session.commit();visit();geometry('empty-parts')
            require('対象期間の部品交換登録はありません' in page.locator('.ka5-parts-panel').inner_text(),'Empty state missing')
            page.locator('.ka5-comparison-grid').screenshot(path=str(output/'empty-320.png'))
            context.close()
            # The fact panels and native disclosure/forms function without JS.
            first.total_cost=600
            for row in m.VehicleMaintenanceRecord.query.filter_by(vehicle_record_id=case.vehicle.id):
                if row.id != first.id: row.total_cost=0
            m.db.session.add(m.VehiclePartReplacement(company_code='TEST',vehicle_record_id=case.vehicle.id,
                maintenance_record_id=case.parent.id,part_name='JS無効の実測差0',replacement_date='2026-09-01',
                mileage=1200,created_at='2026-09-01T00:00:00+09:00'))
            m.db.session.commit()
            nojs=browser.new_context(java_script_enabled=False,viewport=dict(width=390,height=1000),service_workers='block')
            nojs.route('**/*',bridge);page=nojs.new_page();page.goto(ORIGIN+url,wait_until='networkidle')
            require(page.locator('.ka5-comparison-grid').is_visible(),'No-JS panels hidden')
            require('6.00' in page.locator('[data-rate=current]').inner_text(),'No-JS numerical value missing')
            require('0 km' in page.locator('.ka5-parts-table').inner_text(),'No-JS measured zero missing')
            page.locator('.ka5-peer-panel details summary').click()
            page.locator('select[name=peer_registration]').select_option('all_years')
            page.locator('.ka7-peer-conditions button').click();page.wait_for_load_state('networkidle')
            require(parse_qs(urlsplit(page.url).query).get('peer_registration')==['all_years'],'No-JS form failed')
            page.locator('.ka5-comparison-grid').screenshot(path=str(output/'no-js-390.png'))
            report['cases'].append('No JavaScript: visible facts, native disclosure and GET form')
            nojs.close();browser.close()
        require(not report['errors'] and not report['external_requests'] and not report['non_get_requests'],'Browser error or external request')
        report['status']='PASS'
    finally:
        case.tearDown();case.tearDownClass()
        (output/'browser-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(dict(status=report['status'],cases=len(report['cases']),browser_started=True)))


if __name__=='__main__':main()
