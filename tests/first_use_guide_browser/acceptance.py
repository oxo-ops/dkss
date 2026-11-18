"""Synthetic browser behavior, uses real guide assets/partial. No application DB/network."""
import json,os,sys,mimetypes
from pathlib import Path
from types import SimpleNamespace as N
from jinja2 import Environment,FileSystemLoader
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.environ.get('GUIDE_ARTIFACT_DIR','guide-browser-output'));OUT.mkdir(parents=True,exist_ok=True)
env=Environment(loader=FileSystemLoader(ROOT/'templates'),autoescape=True)

def html(role='driver',mode='demo',notice=False,page='dashboard',saved=False):
 session={'username':'synthetic','role':role}
 if mode=='demo':session['aonagi_readonly_demo']=True
 guide=env.get_template('partials/first_use_guide.html').render(session=session,request=N(endpoint=page),checklist={'fixed_template_code':'daily_inspection_truck_trailer'},url_for=lambda endpoint,filename,**kw:'/static/'+filename)
 target='<a class="dashboard-vehicle-action-primary dashboard-vehicle-action" href="/detail">日常点検表</a>' if role=='driver' else ''
 body=(('<div class="public-demo-notice">役割選択</div>') if notice else '')+f'<button id="sidebarToggle">メニュー</button><h1>合成検証</h1>{target}'
 if page=='vehicle_checklist_results':body+='<form id="vehicle_check_filter"><input id="vehicle_search" placeholder="車両を検索"><input type="hidden" name="vehicle_record_id"></form><button class="js-open-detail inspection-item-detail" type="button">詳細</button>'
 if page=='vehicle_checklist_results':
  body+='<div class="check-choice-buttons"><label>✓<input type="radio" name="value" value="✓"></label><label>×<input type="radio" name="value" value="×"></label></div><div class="vehicle-check-complete-form"><input class="approval-user-search" data-guide-title="運行判断の依頼先を選ぶ" placeholder="名前で検索"></div>'
  body+=('<input id="reminder_notify_user_search">' if role=='admin' else '<div class="reminder-readonly">点検未実施通知先 未設定</div>')
  body+='<button type="button" class="vehicle-check-complete-primary">点検完了</button>'
 if saved:
  body='<details id="vehicle-inspection-record"><summary>点検記録を確認</summary><button class="inspection-item-detail" type="button">ワイパーの拭き取り状態</button></details>'
 return '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:20px;font:16px sans-serif;min-height:1600px}button,a,select{display:block;padding:12px;margin:12px 0;min-height:44px}h1{margin-top:140px}.first-guide-target{scroll-margin:40px}</style>'+body+'<form method="post" action="/save"><input name="csrf_token" value="synthetic"><input id="draft" value="未保存の入力"><button id="save">保存</button></form>'+guide

results=[]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 for width in [320,390,1280,1440]:
  for role in ['driver','admin']:
   context=browser.new_context(viewport={'width':width,'height':844});posts=[]
   def respond(route):
    from urllib.parse import urlsplit,parse_qs
    u=urlsplit(route.request.url)
    if u.netloc!='fixture.invalid':return route.abort()
    if route.request.method!='GET':posts.append(u.path);return route.fulfill(status=400,body='No mutation allowed')
    if u.path.startswith('/static/'):
     path=ROOT/u.path.lstrip('/');return route.fulfill(status=200,body=path.read_bytes(),content_type=mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
    q=parse_qs(u.query);body=html(role,notice=q.get('notice')==['1'],page=q.get('page',['dashboard'])[0],saved=q.get('saved')==['1']);return route.fulfill(status=200,body=body,content_type='text/html; charset=utf-8')
   context.route('**/*',respond);page=context.new_page();page.goto('https://fixture.invalid/')
   panel=page.locator('#firstGuidePanel');panel.wait_for(state='visible')
   page.screenshot(path=str(OUT/f'{role}-{width}-loaded.png'),full_page=False)
   assert page.locator('.first-guide-target').count()==1
   assert page.locator('#draft').input_value()=='未保存の入力'
   if role=='admin':assert page.locator('#firstGuidePanel [data-guide-title]').inner_text()=='メニューから画面を選ぶ'
   def bounds():
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    b=panel.bounding_box();assert b and b['x']>=0 and b['y']>=0 and b['x']+b['width']<=page.viewport_size['width']+1
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('[data-guide-next]').evaluate('(e)=>{const p=e.parentElement,r=e.getBoundingClientRect(),b=p.getBoundingClientRect(),s=getComputedStyle(p);return Math.abs(b.right-r.right-parseFloat(s.paddingRight)-parseFloat(s.borderRightWidth))<2}')
   bounds();page.screenshot(path=str(OUT/f'{role}-{width}-initial.png'),full_page=False)
   page.locator('[data-guide-close]').click();assert not panel.is_visible()
   page.reload();assert not panel.is_visible()
   page.locator('[data-guide-open]').click();assert page.locator('[data-guide-close]').evaluate('(e)=>e===document.activeElement')
   page.keyboard.press('Escape');assert not panel.is_visible();assert page.locator('[data-guide-open]').evaluate('(e)=>e===document.activeElement')
   page.locator('[data-guide-open]').click();page.set_viewport_size({'width':844,'height':390});bounds()
   page.evaluate('window.scrollTo(0,100)');page.screenshot(path=str(OUT/f'{role}-{width}-landscape-scroll.png'));bounds()
   page.locator('[data-guide-close]').click();page.set_viewport_size({'width':width,'height':844})
   page.goto('https://fixture.invalid/?page=vehicle_checklist_results');panel.wait_for(state='visible')
   page.locator('[data-guide-next]').click();assert '詳細' in page.locator('#firstGuidePanel [data-guide-title]').inner_text()
   page.locator('.js-open-detail').click();assert not panel.is_visible();assert page.locator('.js-open-detail').evaluate('(e)=>e===document.activeElement');assert page.locator('#draft').input_value()=='未保存の入力';assert not posts
   page.locator('[data-guide-open]').click()
   assert page.locator('#firstGuidePanel [data-guide-title]').inner_text()=='評価を入れる'
   page.keyboard.press('Escape');expect(panel).not_to_be_visible()
   assert page.locator('[data-guide-open]').evaluate('(e)=>e===document.activeElement')
   page.locator('[data-guide-open]').click()
   expected=['車両を選ぶ','項目の詳細を見る','評価を入れる','運行判断の依頼先を選ぶ',
             '点検未実施通知先を選ぶ' if role=='admin' else '点検未実施通知先を確認する','点検を完了する']
   for step_no,heading in enumerate(expected):
    assert page.locator('#firstGuidePanel [data-guide-title]').inner_text()==heading
    bounds();assert page.locator('.first-guide-target').is_visible()
    if heading=='項目の詳細を見る':
     assert page.locator('[data-guide-picture]').is_visible()
     expect(page.locator('[data-guide-picture] img')).to_have_js_property('complete',True)
     expect(page.locator('[data-guide-picture] img')).to_have_js_property('naturalWidth',1098)
     box=page.locator('[data-guide-picture]').bounding_box()
     assert box and 255 <= box['width'] <= 265 and 340 <= box['height'] <= 355, box
     assert page.locator('[data-guide-next]').is_visible()
     next_box=page.locator('[data-guide-next]').bounding_box()
     assert next_box['y'] + next_box['height'] <= page.viewport_size['height'], next_box
    else:assert not page.locator('[data-guide-picture]').is_visible()
    page.screenshot(path=str(OUT/f'{role}-{width}-step-{step_no+1}.png'))
    page.locator('[data-guide-next]').click()
   assert not panel.is_visible();assert not posts
   page.locator('[data-guide-open]').click();page.locator('.first-guide-target').evaluate('(e)=>e.hidden=true');expect(panel).not_to_be_visible()
   # Explicit help works even when every real guide target is in a closed saved record.
   page.goto('https://fixture.invalid/?page=vehicle_checklist_results&saved=1')
   assert not page.locator('#vehicle-inspection-record').evaluate('(e)=>e.open')
   assert not panel.is_visible()
   page.locator('[data-guide-open]').click()
   assert page.locator('#vehicle-inspection-record').evaluate('(e)=>e.open')
   expect(panel).to_be_visible()
   assert page.locator('#firstGuidePanel [data-guide-title]').inner_text()=='項目の詳細を見る'
   bounds();assert page.locator('#draft').input_value()=='未保存の入力';assert not posts
   page.screenshot(path=str(OUT/f'{role}-{width}-saved-record-help.png'))
   page.locator('[data-guide-next]').click();expect(panel).not_to_be_visible()
   page.locator('[data-guide-open]').click();expect(panel).to_be_visible()
   page.locator('[data-guide-close]').click();expect(panel).not_to_be_visible()
   page.goto('https://fixture.invalid/?notice=1');assert not page.locator('#firstUseGuide').is_visible()
   results.append({'width':width,'role':role,'behavior':'pass','posts':len(posts)})
   context.close()
 browser.close()
(OUT/'report.json').write_text(json.dumps({'synthetic_only':True,'cases':results},indent=2))
