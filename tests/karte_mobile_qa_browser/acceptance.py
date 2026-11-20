"""Read-only, synthetic regression for mobile QA fixes. No app or DB access."""
import os,json,mimetypes
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.environ.get('QA_ARTIFACT_DIR','karte-mobile-qa-output'));OUT.mkdir(parents=True,exist_ok=True)
styles=['style.css','vehicle_karte_analysis.css','first_use_guide.css','karte_mobile_header_search.css']
html='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+''.join(f'<link rel="stylesheet" href="/static/css/{s}">' for s in styles)+'''<body class="vehicle-list-ppt"><main class="ka3-shell" style="padding:12px;width:100%;box-sizing:border-box"><h1 class="mobile-shell-title" style="display:block;width:150px;font-size:16px"><span class="karte-title-part">車両カルテ</span><wbr><span class="karte-title-part">・整備・修理</span></h1><nav class="vehicle-karte-tabs" style="display:flex;overflow:auto;width:100%;flex-wrap:nowrap">'''+''.join(f'<a style="flex:0 0 90px" class="vehicle-karte-tab" '+('aria-current="page" ' if i==7 else '')+f'href="#tab{i}">{name}</a>' for i,name in enumerate(['概要','履歴','点検','整備・修理','部品','費用','書類','分析']))+'''</nav><div class="karte-maintenance karte-costs karte-analysis ka3-page ka7-page"><header class="ka7-toolbar"><form class="ka-period-form"><input type="hidden"><label for="ka-start-date">実績の集計期間</label><input id="ka-start-date" type="date" value="2026-10-20"><span>～</span><label class="km-sr-only">終了日</label><input id="ka-end-date" type="date" value="2026-11-20"><button>集計</button></form></header></div><figure data-guide-ai-picture style="width:280px"><img src="/static/guide/ai-evidence-open.png" width="390" height="844"></figure></main><script src="/static/js/vehicle_karte_layout.js"></script>'''
results=[]
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
 for w in [320,390,400,500,768,1440]:
  page=b.new_page(viewport={'width':w,'height':844})
  def route(r):
   from urllib.parse import urlsplit
   u=urlsplit(r.request.url)
   if u.netloc!='fixture.invalid':return r.abort()
   f=ROOT/u.path.lstrip('/')
   if u.path.startswith('/static/'):return r.fulfill(body=f.read_bytes(),content_type=mimetypes.guess_type(str(f))[0] or 'application/octet-stream')
   r.fulfill(body=html,content_type='text/html')
  page.route('**/*',route);page.goto('https://fixture.invalid/');page.wait_for_load_state('load')
  page.locator('img').evaluate('(e)=>e.decode()')
  page.screenshot(path=str(OUT/f'karte-{w}.png'))
  boxes=[page.locator(s).bounding_box() for s in ['#ka-start-date','#ka-end-date','.ka-period-form button']]
  if w<=500:assert max(x['y'] for x in boxes)-min(x['y'] for x in boxes)<2,boxes
  tab=page.locator('[aria-current]').bounding_box();strip=page.locator('.vehicle-karte-tabs').bounding_box()
  assert tab['x']>=strip['x']-1 and tab['x']+tab['width']<=strip['x']+strip['width']+1
  assert page.locator('[data-guide-ai-picture] img').evaluate('(e)=>getComputedStyle(e).objectFit')=='cover'
  if w<=500:
   for part in page.locator('.karte-title-part').all():assert part.bounding_box()['height']<24
  page.screenshot(path=str(OUT/f'karte-{w}.png'));results.append({'width':w,'passed':True,'dates':boxes});page.close()
 b.close()
(OUT/'results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))
