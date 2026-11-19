"""Synthetic guide diagnostic only: no app server, database, or external network."""
from pathlib import Path
from jinja2 import Environment,FileSystemLoader
from types import SimpleNamespace as N
from playwright.sync_api import sync_playwright
from urllib.parse import urlsplit
import mimetypes,json,sys,time
R=Path.cwd(); OUT=Path(sys.argv[1]); OUT.mkdir(parents=True,exist_ok=True)
e=Environment(loader=FileSystemLoader(R/'templates'))
g=e.get_template('partials/first_use_guide.html').render(session={'username':'synthetic','role':'driver','aonagi_readonly_demo':True},request=N(endpoint='vehicle_karte_analysis'),url_for=lambda endpoint,filename,**kw:'/static/'+filename)
h='''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:20px;font:16px sans-serif}section.spacer{height:650px}button,a{padding:12px;min-height:44px}.ka7-kpis{height:160px}</style><script>window.trace=[];for(const type of ['pointerdown','pointerup','click'])document.addEventListener(type,e=>{const p=document.querySelector('#firstGuidePanel');window.trace.push({type,time:performance.now(),target:e.target.outerHTML.slice(0,150),count:p?.querySelector('[data-guide-count]')?.textContent,hidden:p?.hidden,y:scrollY});},true);</script><a class="vehicle-karte-tab" href="/history">履歴</a><section class="spacer"></section><input id="ka-start-date"><form class="ka-period-form"><button type="submit">集計</button></form><section class="spacer"></section><div class="ka7-kpis">実績</div><section class="spacer"></section><div id="ka-ai-results"><div class="ka7-proposals"><button class="ka-reference-detail-button">詳細</button></div></div><section class="spacer"></section>'''+g
out=[]
with sync_playwright() as p:
 b=p.chromium.launch(headless=True)
 for width in [390,501,1316]:
  for mode in ['rapid','settled','held-during-scroll','target-replaced']:
   c=b.new_context(viewport={'width':width,'height':757},reduced_motion='no-preference')
   def handle(route):
    u=urlsplit(route.request.url)
    if u.netloc!='fixture.invalid':return route.abort()
    if u.path.startswith('/static/'):
     f=R/u.path.lstrip('/');return route.fulfill(body=f.read_bytes(),content_type=mimetypes.guess_type(str(f))[0] or 'application/octet-stream')
    return route.fulfill(body=h,content_type='text/html')
   c.route('**/*',handle);page=c.new_page();page.goto('https://fixture.invalid/')
   observed=[]
   try:
    for i in range(6):
     panel=page.locator('#firstGuidePanel');observed.append({'count':page.locator('[data-guide-count]').inner_text(),'visible':panel.is_visible()})
     if mode=='settled':page.wait_for_timeout(900)
     if mode=='target-replaced' and i==4:
      page.evaluate("const el=document.querySelector('.ka-reference-detail-button');el.replaceWith(el.cloneNode(true));")
      page.wait_for_timeout(50)
     if mode=='held-during-scroll':
      box=page.locator('[data-guide-next]').bounding_box();page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.mouse.down();page.wait_for_timeout(350);page.mouse.up()
     else:page.locator('[data-guide-next]').click(timeout=2500)
     page.wait_for_timeout(25)
    result='completed' if not page.locator('#firstGuidePanel').is_visible() else 'still-open'
   except Exception as ex:result=str(ex).splitlines()[0]
   out.append({'width':width,'mode':mode,'result':result,'states':observed,'trace':page.evaluate('window.trace')})
   page.screenshot(path=str(OUT/f'{width}-{mode}.png'));c.close()
 b.close()
(OUT/'diagnostic.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps([{k:v for k,v in x.items() if k!='trace'} for x in out],ensure_ascii=False,indent=2))
