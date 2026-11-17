"""Permitted isolated CI only; no Live routes or real data."""
import argparse,os,json,hashlib,re
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parent;ROOT=R.parents[1];ORIGIN='https://fixture.invalid'
p=argparse.ArgumentParser();p.add_argument('--chromium',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True);a=p.parse_args()
assert os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED')=='1'
head=os.environ.get('DKSS_COST_VERIFIED_HEAD','');assert re.fullmatch('[0-9a-f]{40}',head)
m=json.loads((R/'manifest.json').read_text())
for path,sha in m['sha256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
reports=[];a.artifacts.mkdir(parents=True,exist_ok=True)
(a.artifacts/'provenance.json').write_text(json.dumps({'head':head,'product_sha256':m['sha256'],'full_shell':False,'live_access':False},indent=2))
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path=str(a.chromium),headless=True)
 try:
  for width in (320,390,768,1316):
   for scenario,values in m['scenarios'].items():
    ctx=browser.new_context(viewport={'width':width,'height':800},service_workers='block');blocked=[];scripts=[]
    def route(r):
     u=urlsplit(r.request.url)
     if u.scheme+'://'+u.netloc!=ORIGIN or r.request.method!='GET':blocked.append(r.request.url);r.abort();return
     if u.path=='/case':r.fulfill(content_type='text/html',body=(R/f'{scenario}.html').read_text());return
     if u.path=='/static/js/vehicle_karte_costs.js':
      assert parse_qs(u.query)=={'v':[m['version']]};scripts.append(r.request.url);r.fulfill(path=str(ROOT/u.path.lstrip('/')));return
     if u.path in ('/static/css/style.css','/static/css/responsive_layout.css'):r.fulfill(path=str(ROOT/u.path.lstrip('/')));return
     blocked.append(r.request.url);r.abort()
    def reject_ws(ws):
     blocked.append('websocket');ws.close()
    ctx.route('**/*',route);ctx.route_web_socket('**/*',reject_ws);page=ctx.new_page()
    page.add_init_script('''window.__costText=[];const orig=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(text,x,y,...rest){const m=this.measureText(text);window.__costText.push({canvas:this.canvas.id,text:String(text),x,y,align:this.textAlign,left:x-m.actualBoundingBoxLeft,right:x+m.actualBoundingBoxRight,top:y-m.actualBoundingBoxAscent,bottom:y+m.actualBoundingBoxDescent});return orig.call(this,text,x,y,...rest)};''')
    try:
     page.goto(ORIGIN+'/case',wait_until='load');page.evaluate('document.fonts.ready');assert scripts and not blocked
     labels=page.locator('canvas').evaluate_all('(es)=>Object.fromEntries(es.map(e=>[e.id,e.getAttribute("aria-label")]))')
     expected=page.evaluate('(vs)=>vs.map((v,i)=>(2024+i)+"年："+(v===null?"金額記録なし":Number(v).toLocaleString("ja-JP",{maximumFractionDigits:2})+"円")).join("、")',values)
     assert labels['kc-yearly-chart']==expected
     if scenario in ('missing','mixed'):assert '金額未入力' in page.locator('body').inner_text()
     summary=page.locator('details.kc-chart-data > summary');summary.focus();page.keyboard.press('Enter')
     assert page.locator('details.kc-chart-data').get_attribute('open') is not None
     assert page.locator('details.kc-chart-data tbody tr').count()==12
     page.keyboard.press('Enter');assert page.locator('details.kc-chart-data').get_attribute('open') is None
     text=page.evaluate('window.__costText');bounds=page.locator('canvas').evaluate_all('(es)=>Object.fromEntries(es.map(e=>[e.id,{width:e.clientWidth,height:e.clientHeight}]))')
     if scenario in ('unknown','missing'):assert any(t['text']=='金額の記録はありません' for t in text)
     if scenario in ('tiny_only','tiny_negative'):
      for cid in ('kc-monthly-chart','kc-yearly-chart'):
       ticks=[x['text'] for x in text if x['canvas']==cid and x['align']=='right'];assert ticks and len(set(ticks))==5
     overflow=[t for t in text if t['canvas'] in bounds and (t['left'] < -1 or t['right']>bounds[t['canvas']]['width']+1 or t['top'] < -1 or t['bottom']>bounds[t['canvas']]['height']+1)]
     assert not blocked
     if overflow:
      reports.append(dict(head=head,width=width,scenario=scenario,status='failed',error_type='CanvasTextOverflow',aria=labels,text=text,bounds=bounds,text_overflow=overflow,script_urls=scripts))
      raise AssertionError('CanvasTextOverflow')
     reports.append(dict(head=head,width=width,scenario=scenario,status='passed',aria=labels,text=text,bounds=bounds,text_overflow=overflow,script_urls=scripts))
     page.screenshot(path=str(a.artifacts/f'{width}-{scenario}.png'),full_page=True)
    except BaseException as error:
     diagnostic={'head':head,'width':width,'scenario':scenario,'status':'failed','error_type':type(error).__name__,'blocked_count':len(blocked)}
     try:
      page.screenshot(path=str(a.artifacts/f'{width}-{scenario}-FAILED.png'),full_page=True)
      diagnostic['failure_image']=f'{width}-{scenario}-FAILED.png'
     except BaseException as capture_error:
      diagnostic['capture_error_type']=type(capture_error).__name__
     if reports and reports[-1].get('width')==width and reports[-1].get('scenario')==scenario and reports[-1].get('status')=='failed':
      reports[-1].update({k:v for k,v in diagnostic.items() if k!='error_type'})
     else:reports.append(diagnostic)
     raise
    finally:ctx.close()
 finally:browser.close();(a.artifacts/'report.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
assert len(reports)==40
assert all(r['status']=='passed' for r in reports)
assert not any(r['text_overflow'] for r in reports),'Canvas text overflow: inspect images; do not hide known or new failures'
print('PASS 40 conditions; visual image review and real device acceptance remain')
