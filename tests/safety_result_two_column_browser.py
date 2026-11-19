"""Count/order/permission preserving two-column list on the actual template."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from test_safety_result_action_contract import Contract
R=Path(__file__).resolve().parents[1];out=R/'safety-result-actions-output';out.mkdir(exist_ok=True)
report=[]
with sync_playwright() as p:
 b=p.chromium.launch()
 for width in [320,390,768,1440]:
  for count in [0,1,12]:
   for manage in [False,True]:
    styles=''.join('<style>'+(R/'static/css'/f).read_text()+'</style>' for f in ['style.css','entry_add_icon.css','responsive_layout.css','safety_result_actions.css','safety_result_two_column_list.css'])
    html='<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+styles+Contract().render(manage,count=count)
    pg=b.new_page(viewport={'width':width,'height':900});posts=[]
    def route(r):
     if r.request.method=='POST':posts.append(r.request.url)
     r.fulfill(body=html if r.request.url=='https://fixture.invalid/' else '<h1>Existing detail</h1>',content_type='text/html')
    pg.route('**/*',route);pg.goto('https://fixture.invalid/')
    assert pg.locator('.safety-results-count').inner_text()==f'{count}件の結果'
    assert pg.locator('.safety-result-mobile-card').count()==count
    scope='.safety-results-mobile-list' if width<=768 else '.safety-results-table'
    ids=pg.locator(scope+' a.safety-result-mobile-detail' if width<=768 else scope+' a.btn-detail').count()
    links=pg.locator(scope+' a').evaluate_all('(es)=>es.map(e=>e.getAttribute("href")).filter(h=>/^\\/safety\\/checklist-results\\/\\d+$/.test(h))')
    assert links==[f'/safety/checklist-results/{17+i}' for i in range(count)],links
    assert pg.locator(scope+' .btn-delete').count()==(count if manage else 0)
    assert pg.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
    if width<=768 and count:
     cells=pg.locator('.safety-result-list-columns').first.locator(':scope > div').all()
     rects=[x.bounding_box() for x in cells]
     assert len(rects)==2 and abs(rects[0]['y']-rects[1]['y'])<2
     assert rects[0]['x']+rects[0]['width']<=rects[1]['x']
     h=pg.locator('.safety-result-mobile-card').first.bounding_box()['height'];assert h<230,h
    pg.screenshot(path=str(out/f'two-column-{width}-{count}-{manage}.png'),full_page=True)
    if count:
     pg.locator(scope+' a[href="/safety/checklist-results/17"]').focus();pg.keyboard.press('Enter');pg.wait_for_url('https://fixture.invalid/safety/checklist-results/17')
    assert not posts
    report.append(dict(width=width,count=count,manage=manage,passed=True));pg.close()
 b.close()
(out/'two-column-report.json').write_text(json.dumps(report,indent=2))
print('PASS 24 count-preserving two-column cases')
