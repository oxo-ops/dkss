"""Real result template/CSS/confirmation JS; synthetic records; no live DB/network."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from test_safety_result_action_contract import Contract
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'safety-result-actions-output';OUT.mkdir(exist_ok=True)
report=[]
with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in [320,390,501,768,1024,1440]:
  for manage in [False,True]:
   content=Contract().render(manage)
   css=''.join('<style>'+ (ROOT/'static/css'/f).read_text()+'</style>' for f in ['style.css','entry_add_icon.css','responsive_layout.css','safety_result_actions.css'])
   html='<meta name="viewport" content="width=device-width,initial-scale=1"><meta charset="utf-8">'+css+'<body data-responsive-shell>'+content+'</body>'+ '<script>'+ (ROOT/'static/js/safety_checklist_results.js').read_text()+'</script>'
   page=browser.new_page(viewport={'width':width,'height':900})
   requests=[]
   def route(r):
    requests.append((r.request.method,r.request.url))
    if r.request.url=='https://fixture.invalid/':r.fulfill(body=html,content_type='text/html')
    else:r.fulfill(body='<h1>Destination</h1>',content_type='text/html')
   page.route('**/*',route)
   page.goto('https://fixture.invalid/')
   add=page.locator('.safety-results-new-button')
   assert add.get_attribute('href')=='/safety/checklists/13/new'
   if width<=768:
    for title in ['営業所安全確認', '営業所安全確認・長い名前のチェックリスト']:
     page.locator('.safety-results-title-row h2').evaluate('(e,s)=>e.textContent=s',title)
     box=add.bounding_box(); heading=page.locator('.safety-results-title-row h2').bounding_box()
     assert box['width']>=44 and box['height']>=44, box
     assert abs(box['y']-heading['y'])<=2 and box['x']>=heading['x']+heading['width']-1, (box,heading)
     assert box['x']+box['width']<=width,box
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
     page.screenshot(path=str(OUT/f'heading-{width}-{manage}-{len(title)}.png'),full_page=True)
    page.locator('.safety-results-title-row h2').evaluate('(e)=>e.textContent="営業所安全確認"')
   add.focus();page.keyboard.press('Enter')
   assert page.url=='https://fixture.invalid/safety/checklists/13/new'
   page.goto('https://fixture.invalid/')
   visible='.safety-results-mobile-list' if width<=768 else '.safety-results-table'
   controls=page.locator(visible).locator('a[href*="checklist-results/"],button.btn-delete')
   metrics=controls.evaluate_all("es=>es.map(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return {height:r.height,width:r.width,color:s.color,background:s.backgroundImage,radius:s.borderRadius}})")
   page.screenshot(path=str(OUT/f'actions-{width}-{manage}.png'),full_page=True)
   assert len(metrics)==(3 if manage else 1),metrics
   assert all(x['height']>=44 for x in metrics),metrics
   assert len({x['radius'] for x in metrics})==1,metrics
   assert metrics[0]['background'].startswith('linear-gradient'),metrics
   page.screenshot(path=str(OUT/f'actions-{width}-{manage}.png'),full_page=True)
   if manage:
    dialogs=[]
    def dismiss(d):dialogs.append(d.message);d.dismiss()
    page.on('dialog',dismiss)
    page.locator(visible+' .btn-delete').click()
    assert dialogs==['この結果を削除しますか？']
    assert not any(m=='POST' for m,u in requests),requests
    page.locator(visible+' .btn-edit').click()
    assert page.url=='https://fixture.invalid/safety/checklist-results/17/edit'
    page.goto('https://fixture.invalid/')
   page.locator(visible+' a[href="/safety/checklist-results/17"]').click()
   assert page.url=='https://fixture.invalid/safety/checklist-results/17'
   report.append(dict(width=width,manage=manage,metrics=metrics,clicks='passed'))
   page.close()
 browser.close()
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print('PASS 12 synthetic mobile/desktop cases')
