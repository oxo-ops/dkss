"""Synthetic browser behavior, uses real guide assets/partial. No application DB/network."""
import json,os,sys
from pathlib import Path
from types import SimpleNamespace as N
from jinja2 import Environment,FileSystemLoader
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.environ.get('GUIDE_ARTIFACT_DIR','guide-browser-output'));OUT.mkdir(parents=True,exist_ok=True)
env=Environment(loader=FileSystemLoader(ROOT/'templates'),autoescape=True)

def html(role='driver',mode='demo',notice=False,page='dashboard'):
 session={'username':'synthetic','role':role}
 if mode=='demo':session['aonagi_readonly_demo']=True
 guide=env.get_template('partials/first_use_guide.html').render(session=session,request=N(endpoint=page),url_for=lambda endpoint,filename,**kw:'/static/'+filename)
 target='<a class="dashboard-vehicle-action-primary dashboard-vehicle-action" href="/detail">日常点検表</a>' if role=='driver' else ''
 body=(('<div class="public-demo-notice">役割選択</div>') if notice else '')+f'<button id="sidebarToggle">メニュー</button><h1>合成検証</h1>{target}'
 if page=='vehicle_checklist_results':body+='<form id="vehicle_check_filter"><select name="vehicle_record_id"><option>対象車両</option></select></form><button class="js-open-detail inspection-item-detail" type="button">詳細</button>'
 return '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:20px;font:16px sans-serif;min-height:1600px}button,a,select{display:block;padding:12px;margin:12px 0;min-height:44px}h1{margin-top:140px}.first-guide-target{scroll-margin:40px}</style>'+body+'<form method="post" action="/save"><input name="csrf_token" value="synthetic"><input id="draft" value="未保存の入力"><button id="save">保存</button></form>'+guide

results=[]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 for width in [320,390,1280]:
  for role in ['driver','admin']:
   context=browser.new_context(viewport={'width':width,'height':844});posts=[]
   def respond(route):
    from urllib.parse import urlsplit,parse_qs
    u=urlsplit(route.request.url)
    if u.netloc!='fixture.invalid':return route.abort()
    if route.request.method!='GET':posts.append(u.path);return route.fulfill(status=400,body='No mutation allowed')
    if u.path.startswith('/static/'):
     path=ROOT/u.path.lstrip('/');return route.fulfill(status=200,body=path.read_bytes(),content_type='text/javascript' if path.suffix=='.js' else 'text/css')
    q=parse_qs(u.query);body=html(role,notice=q.get('notice')==['1'],page=q.get('page',['dashboard'])[0]);return route.fulfill(status=200,body=body,content_type='text/html; charset=utf-8')
   context.route('**/*',respond);page=context.new_page();page.goto('https://fixture.invalid/')
   panel=page.locator('#firstGuidePanel');panel.wait_for(state='visible')
   page.screenshot(path=str(OUT/f'{role}-{width}-loaded.png'),full_page=False)
   assert page.locator('.first-guide-target').count()==1
   assert page.locator('#draft').input_value()=='未保存の入力'
   if role=='admin':assert page.locator('[data-guide-title]').inner_text()=='ほかの画面へ'
   def bounds():
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    b=panel.bounding_box();assert b and b['x']>=0 and b['y']>=0 and b['x']+b['width']<=page.viewport_size['width']+1
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
   bounds();page.screenshot(path=str(OUT/f'{role}-{width}-initial.png'),full_page=False)
   page.locator('[data-guide-close]').click();assert not panel.is_visible()
   page.reload();assert not panel.is_visible()
   page.locator('[data-guide-open]').click();assert page.locator('[data-guide-close]').evaluate('(e)=>e===document.activeElement')
   page.keyboard.press('Escape');assert not panel.is_visible();assert page.locator('[data-guide-open]').evaluate('(e)=>e===document.activeElement')
   page.locator('[data-guide-open]').click();page.set_viewport_size({'width':844,'height':390});bounds()
   page.evaluate('window.scrollTo(0,100)');page.screenshot(path=str(OUT/f'{role}-{width}-landscape-scroll.png'));bounds()
   page.locator('[data-guide-close]').click();page.set_viewport_size({'width':width,'height':844})
   page.goto('https://fixture.invalid/?page=vehicle_checklist_results');panel.wait_for(state='visible')
   page.locator('[data-guide-next]').click();assert '詳細' in page.locator('[data-guide-title]').inner_text()
   page.locator('.js-open-detail').click();assert not panel.is_visible();assert page.locator('.js-open-detail').evaluate('(e)=>e===document.activeElement');assert page.locator('#draft').input_value()=='未保存の入力';assert not posts
   page.locator('[data-guide-open]').click();page.locator('.first-guide-target').evaluate('(e)=>e.hidden=true');expect(panel).not_to_be_visible()
   page.goto('https://fixture.invalid/?notice=1');assert not page.locator('#firstUseGuide').is_visible()
   results.append({'width':width,'role':role,'behavior':'pass','posts':len(posts)})
   context.close()
 browser.close()
(OUT/'report.json').write_text(json.dumps({'synthetic_only':True,'cases':results},indent=2))
