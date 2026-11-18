"""Synthetic guide only: no Flask, credentials, business data, or live requests."""
import json, os, re, subprocess, traceback
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2]
HEAD=os.environ.get('EXPECTED_HEAD','')
assert re.fullmatch(r'[0-9a-f]{40}',HEAD), 'Exact SHA required'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==HEAD
assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(), 'Clean checkout required'
OUT=Path(os.environ['ARTIFACTS']);OUT.mkdir(parents=True,exist_ok=True)
env=Environment(loader=FileSystemLoader(ROOT/'templates'))
partial=env.get_template('partials/first_use_guide.html').render(session={'username':'synthetic','aonagi_readonly_demo':True},request={'endpoint':'vehicle_karte_history'},url_for=lambda endpoint,filename,**kw:'/static/'+filename)
# Inline original CSS/JS to ensure the fixture cannot fetch external resources.
partial=re.sub(r'<link[^>]*>', '',partial)
partial=re.sub(r'<script[^>]*>.*?</script>','',partial,flags=re.S)
html='<!doctype html><html><head><meta charset="utf-8"><style>body{margin:16px}select,input,button{min-height:44px} .vehicle-history-categories{margin-top:100px;height:48px}</style><style>'+ (ROOT/'static/css/first_use_guide.css').read_text()+'</style></head><body>'+partial+'''<div class="vehicle-history-categories">種類</div><form class="vehicle-karte-history-filters"><select name="event_type"><option>すべて</option><option>整備</option></select><div style="height:1200px"></div><input id="history_start_date" type="date"><button type="submit">絞り込み</button></form><div style="height:900px"></div><a class="vehicle-history-record-link" href="/record">記録</a><div style="height:900px"></div></body></html>'''
report={'head':HEAD,'synthetic':True,'full_shell':False,'live_access':False,'rows':[],'blocked':[]};page=None
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch()
  try:
   for width in (320,390,1316):
    for reduced in ('no-preference','reduce'):
     row={'width':width,'reduced_motion':reduced,'passed':False};report['rows'].append(row)
     context=browser.new_context(viewport={'width':width,'height':844},reduced_motion=reduced,service_workers='block')
     def route(r):
      if r.request.method=='GET' and r.request.url=='https://fixture.invalid/history': r.fulfill(content_type='text/html',body=html)
      else:
       report['blocked'].append({'method':r.request.method,'url':r.request.url});r.abort()
     context.route('**/*',route)
     page=context.new_page()
     page.route_web_socket('**/*',lambda ws:(report['blocked'].append({'websocket':True}),ws.close()))
     page.goto('https://fixture.invalid/history')
     page.evaluate('''() => {localStorage.setItem('dkss:first-guide:v1:demo:vehicle_karte_history','1'); window.calls=[];window.samples=[];const f=Element.prototype.scrollIntoView;Element.prototype.scrollIntoView=function(o){calls.push(o);return f.call(this,o)};window.addEventListener('scroll',()=>samples.push(scrollY));document.querySelector('form').addEventListener('submit',e=>e.preventDefault());}''')
     page.add_script_tag(content=(ROOT/'static/js/first_use_guide.js').read_text())
     page.locator('[data-guide-open]').click()
     assert page.evaluate('scrollY')==0 and page.evaluate('calls.length')==0
     assert page.locator('[data-guide-count]').inner_text()=='1 / 5'
     page.locator('[data-guide-next]').click()
     assert page.evaluate('scrollY')==0 and page.evaluate('calls.length')==0
     page.screenshot(path=str(OUT/f'{width}-{reduced}-visible.png'))
     page.locator('[data-guide-next]').click();page.wait_for_timeout(1200)
     assert page.url=='https://fixture.invalid/history'
     assert page.evaluate('calls.at(-1).behavior')==('instant' if reduced=='reduce' else 'smooth')
     assert page.evaluate('scrollY')>0
     if reduced=='no-preference': assert page.evaluate('new Set(samples).size')>2, 'Smooth scroll needs intermediate positions'
     box=page.locator('#history_start_date').bounding_box();assert box['y']>=0 and box['y']+box['height']<=844
     page.screenshot(path=str(OUT/f'{width}-{reduced}-offscreen.png'))
     # Adjacent visible target must not recenter. End and Escape retain page URL.
     before=page.evaluate('({y:scrollY,n:calls.length})')
     page.locator('[data-guide-next]').click();page.wait_for_timeout(100)
     assert page.evaluate('scrollY')==before['y'] and page.evaluate('calls.length')==before['n']
     page.locator('[data-guide-next]').click();page.wait_for_timeout(1200)
     assert page.locator('[data-guide-next]').inner_text()=='終了'
     page.locator('[data-guide-next]').click();assert page.locator('.first-guide-panel').is_hidden()
     page.locator('[data-guide-open]').click();page.wait_for_timeout(1200)
     assert page.locator('[data-guide-count]').inner_text()=='1 / 5'
     page.keyboard.press('Escape');assert page.locator('.first-guide-panel').is_hidden()
     page.locator('[data-guide-open]').click();page.wait_for_timeout(1200)
     page.locator('select[name=event_type]').select_option(label='整備')
     page.locator('select[name=event_type]').click()
     assert page.locator('.first-guide-panel').is_hidden()
     assert page.url=='https://fixture.invalid/history' and page.locator('select').input_value()=='整備'
     row.update(passed=True,calls=page.evaluate('calls'),samples=page.evaluate('samples'))
     context.close();page=None
   assert not report['blocked'], 'Unexpected network attempt'
  finally: browser.close()
except Exception as exc:
 report['failure']={'type':type(exc).__name__,'message':str(exc)}
 if page:
  try: page.screenshot(path=str(OUT/'FAILED.png'))
  except Exception as shot: report['screenshot_error']=type(shot).__name__
 raise
finally: (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
