"""Actual detail modal HTML/CSS, synthetic data only, offline intercepted browser."""
import json
import os
from pathlib import Path
from jinja2 import Environment
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get('DETAIL_BUTTON_ARTIFACT_DIR', ROOT / 'detail-button-browser-output'))
OUT.mkdir(parents=True, exist_ok=True)
source = (ROOT / 'templates/vehicle_checklist_results.html').read_text()
modal = '<div id="detailModal"' + source.split('<div id="detailModal"', 1)[1].split('<div id="vehicleRejectModal"', 1)[0]
modal = Environment().from_string(modal).render(csrf_token=lambda: 'synthetic', checklist_index=1, vehicle_record_id=1)
modal = modal.replace('modal-bg is-hidden', 'modal-bg is-open')
html = '<meta name="viewport" content="width=device-width,initial-scale=1"><meta charset="utf-8">'
for file in ('style.css', 'vehicle_checklist_compact.css', 'responsive_layout.css'):
    html += '<style>' + (ROOT / 'static/css' / file).read_text() + '</style>'
html += '<body data-responsive-shell><main class="main-content">' + modal + '</main></body>'
cases = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, **({'executable_path':os.environ['CHROMIUM_PATH']} if os.environ.get('CHROMIUM_PATH') else {}))
    for width in (320, 390, 768, 1280):
        page = browser.new_page(viewport={'width': width, 'height': 844})
        page.route('**/*', lambda route: route.fulfill(status=200, body=html, content_type='text/html'))
        page.goto('https://fixture.invalid/')
        page.locator('#detailTitle').evaluate("(e)=>e.textContent='エンジンのかかり具合、異音 低速、加速の状態'")
        page.locator('#detailCriteriaText').evaluate("(e)=>e.textContent='✓ 正常 / × 異常'")
        controls = page.locator('#detailModal .action-row > .btn, #detailModal .file-upload-button')
        metrics = controls.evaluate_all("""es=>es.map(e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);return {width:r.width,height:r.height,left:r.left,right:r.right,bg:s.backgroundImage,color:s.color,radius:s.borderRadius}})""")
        assert len(metrics) == 4
        assert all(m['height'] >= 48 and m['left'] >= 0 and m['right'] <= width for m in metrics), metrics
        assert max(m['width'] for m in metrics)-min(m['width'] for m in metrics) < 1, metrics
        assert len({m['radius'] for m in metrics}) == 1, metrics
        page.screenshot(path=str(OUT / f'editable-{width}.png'))
        # Preserve visibility contracts used by the existing permission handler.
        page.locator('#detailModal button[type=submit], #detailModal .file-upload-button').evaluate_all('(es)=>es.forEach(e=>e.hidden=true)')
        assert not page.locator('#detailModal button[type=submit]').is_visible()
        assert not page.locator('#detailModal .file-upload-button').first.is_visible()
        assert page.locator('.js-close-detail-modal').is_visible()
        cases.append({'width': width, 'controls': metrics, 'readonly_hidden': True})
        page.close()
    browser.close()
(OUT / 'report.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2))
print(f'PASS: {len(cases)} viewports, equal control geometry and readonly visibility')
