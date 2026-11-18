"""Isolated layout/GET contract. No deployed page, login, or business write."""
import os,json,asyncio,re,subprocess
from types import SimpleNamespace
from jinja2 import Environment
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parent
BASE=Path(os.environ.get('BASE_REPO','ui-followup-948-20261118')).resolve()
C=Path(os.environ.get('PRODUCT_REPO',str(ROOT/'candidate'))).resolve();OUT=Path(os.environ.get('ARTIFACTS',str(ROOT/'artifacts')));OUT.mkdir(exist_ok=True)
if os.environ.get('EXPECTED_SHA'):
 assert subprocess.check_output(['git','-C',str(C),'rev-parse','HEAD'],text=True).strip()==os.environ['EXPECTED_SHA']
 assert not subprocess.check_output(['git','-C',str(C),'status','--porcelain'],text=True).strip()
BASE=C if os.environ.get('PRODUCT_REPO') else BASE
source=(C/'templates/vehicle_karte_analysis.html').read_text()
form=re.search(r'<form method="get" class="ka-period-form".*?</form>',source,re.S).group()
form=Environment().from_string(form).render(url_for=lambda *a,**k:'/vehicle/1/analysis',vehicle=SimpleNamespace(id=1),analysis_comparison=SimpleNamespace(registration_scope='all',include_inactive=False),data=SimpleNamespace(start_date='2024-11-18',end_date='2026-11-18'))
async def main():
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True)
  rows=[]
  try:
   for width in [320,375,390,500,768,1316]:
    for locale in ['ja-JP','de-DE']:
     context=await browser.new_context(viewport={'width':width,'height':900},locale=locale)
     await context.route('**/*',lambda route:route.abort())
     page=await context.new_page();await page.route_web_socket('**/*',lambda ws:ws.close())
     await page.set_content('<html><body class="vehicle-list-ppt"><div class="ka3-shell"><div class="karte-costs karte-analysis ka3-page ka7-page"><header class="ka7-toolbar">'+form+'</header></div></div></body></html>')
     await page.add_style_tag(content=(BASE/'static/css/style.css').read_text())
     await page.add_style_tag(content=(C/'static/css/vehicle_karte_analysis.css').read_text())
     boxes=[await page.locator(s).bounding_box() for s in ['#ka-start-date','#ka-end-date','.ka-period-form button']]
     assert all(x and x['height']>=44 for x in boxes)
     if width<=500: assert max(x['y'] for x in boxes)-min(x['y'] for x in boxes)<2
     assert all(x['x']>=0 and x['x']+x['width']<=width+1 for x in boxes)
     await page.locator('#ka-start-date').fill('2026-01-01');await page.locator('#ka-end-date').fill('2026-11-18')
     await page.evaluate("document.querySelector('form').addEventListener('submit',e=>{e.preventDefault();window.result=Object.fromEntries(new FormData(e.target));})")
     await page.get_by_role('button',name='集計').click()
     assert await page.evaluate('window.result')=={'peer_registration':'all','start_date':'2026-01-01','end_date':'2026-11-18'}
     await page.screenshot(path=str(OUT/f'{width}-{locale}.png'),full_page=True)
     rows.append({'width':width,'locale':locale,'boxes':boxes,'passed':True});await context.close()
  except Exception as e:
   (OUT/'failure.json').write_text(json.dumps({'error':str(e),'width':width,'locale':locale}))
   try: await page.screenshot(path=str(OUT/'failure.png'),full_page=True)
   except Exception: pass
   raise
  finally:
   (OUT/'report.json').write_text(json.dumps({'head':os.environ.get('EXPECTED_SHA'),'cases':rows,'full_shell':False,'live':False},indent=2));await browser.close()
asyncio.run(main())
