"""Synthetic real-Flask, real-browser-cookie acceptance; never production access."""
import argparse,json,os,sys,time,subprocess
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--chromium');p.add_argument('--expected-sha');p.add_argument('--preflight-only',action='store_true');a=p.parse_args()
r=a.repo.resolve();out=a.artifacts.resolve();out.mkdir(parents=True,exist_ok=True)
assert os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED')=='1'
if not a.preflight_only:
 assert a.expected_sha
 assert os.environ.get('SOURCE_HEAD')==a.expected_sha # exact clean source and patched hashes checked by runner
import sitecustomize
assert sitecustomize.ROOT==Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
try:sys.audit('socket.connect',None,('fixture.invalid',443))
except RuntimeError:pass
else:raise AssertionError('guard inactive')
sys.path[:0]=[str(r),str(r/'tests')]
from test_demo_seed_share import SeedShare
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
c=SeedShare();c.setUpClass();c.setUp();c.clock=datetime.now(ZoneInfo('Asia/Tokyo'))
c.app.config['PUBLIC_DEMO_UNTIL']=int(time.time())+86400*100

report={'overall':'incomplete','tested_head':a.expected_sha,'synthetic_only':True,'browser_started':False,'blocked':[],'posts':[],'checks':[]}
try:
 target=f'/vehicle/checklists/{c.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}?vehicle_record_id={c.vehicle_id}&year={c.clock.year}&month={c.clock.month}&active_day={c.clock.day}&__aonagi_entry=1'
 before=[(x.id,x.answers_json,x.operation_judgment_json) for x in c.models.VehicleChecklistResult.query.all()]
 def snapshot():return [(x.id,x.answers_json,x.operation_judgment_json) for x in c.models.VehicleChecklistResult.query.all()]
 # A cookie managed by an unrelated visitor must never replace ordinary identity.
 normal=c.app.test_client();c.demo_active=False;c.client=normal;c.login('admin')
 cookie_name=c.app.config.get('SESSION_COOKIE_NAME','session');normal_cookie=normal.get_cookie(cookie_name).value
 if a.preflight_only:
  from threading import Thread
  results=[]
  def probe():
   client=c.app.test_client();res=client.get(target);results.append(res.status_code);results.append(any(k.lower()=='set-cookie' for k,v in res.headers.items()));results.append(client.get(target).status_code)
  t=Thread(target=probe);t.start();t.join(10);assert results==[302,True,200],results
  report['checks'].append('real-cookie bridge thread preflight passed')
 else:
  assert a.chromium
  from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
  from threading import Thread,Lock
  request_lock=Lock()
  from playwright.sync_api import sync_playwright
  class Bridge(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):self.handle_request('GET')
   def do_POST(self):self.handle_request('POST')
   def handle_request(self,method):
    try:
     u=urlsplit(self.path);assert not u.netloc and not u.scheme and '..' not in u.path.split('/')
     allow={'/','/demo','/demo/role',urlsplit(target).path,'/api/approval-candidates','/api/notifications/recent','/api/notifications/unread-count','/api/push/vapid-public-key','/static/manifest.webmanifest','/favicon.ico'}
     assert u.path in allow or u.path.startswith(('/static/css/','/static/js/','/static/images/','/static/icons/','/static/vendor/'))
     data=None
     if method=='POST':
      assert u.path=='/demo/role';n=int(self.headers.get('Content-Length','0'));assert 0<n<8192
      assert self.headers.get('Content-Type','').startswith('application/x-www-form-urlencoded')
      data=parse_qs(self.rfile.read(n).decode(),keep_blank_values=True);assert set(data)=={'role','csrf_token'} and data['role']==['manager'] and len(data['csrf_token'])==1
      data={k:v[0] for k,v in data.items()};report['posts'].append('role-only')
     client=c.app.test_client(use_cookies=False)
     with request_lock:
      res=client.open(self.path,method=method,headers={'Cookie':self.headers.get('Cookie','')},data=data)
     if 300<=res.status_code<400:assert res.status_code==302 and res.location.startswith('/') and not res.location.startswith('//')
     self.send_response(res.status_code)
     for k,v in res.headers.items():
      if k.lower() not in ('content-length','content-encoding','connection'):self.send_header(k,v)
     self.send_header('Content-Length',str(len(res.data)));self.end_headers();self.wfile.write(res.data)
    except BaseException as error:
     report['blocked'].append(type(error).__name__);self.send_response(500);self.end_headers()
  server=ThreadingHTTPServer(('127.0.0.1',0),Bridge);thread=Thread(target=server.serve_forever,daemon=True);thread.start();origin=f'http://127.0.0.1:{server.server_port}'
  def guard(route):
   if urlsplit(route.request.url).netloc!=urlsplit(origin).netloc:report['blocked'].append('external');route.abort()
   else:route.continue_()
  def decode(ctx):
   raw=next(x['value'] for x in ctx.cookies() if x['name']==cookie_name)
   return c.app.session_interface.get_signing_serializer(c.app).loads(raw)
  try:
   with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=a.chromium,headless=True);report['browser_started']=True
    contexts=[]
    try:
     current=datetime.now(ZoneInfo('Asia/Tokyo'))
     month_first=(current.replace(day=28)+timedelta(days=4)).replace(day=1)
     year_first=current.replace(year=current.year+1,month=1,day=1)
     for scenario,clock in [('ordinary',current),('month-first',month_first),('year-first',year_first)]:
      c.clock=clock;previous=(clock-timedelta(days=1)).date()
      target=f'/vehicle/checklists/{c.target.checklist}?vehicle_record_id={c.target.vehicle}&year={clock.year}&month={clock.month}&active_day={clock.day}&__aonagi_entry=1'
      for width in (320,390,768,1280):
       one=browser.new_context(viewport={'width':width,'height':844},service_workers='block');two=browser.new_context(viewport={'width':width,'height':844},service_workers='block');contexts.extend([one,two])
       def reject_ws(ws):report['blocked'].append('websocket');ws.close()
       for ctx in (one,two):ctx.route('**/*',guard);ctx.route_web_socket('**/*',reject_ws)
       page=one.new_page();response=page.goto(origin+target,wait_until='networkidle');assert response.status==200
       copied=page.url;fresh=two.new_page();assert fresh.goto(copied,wait_until='networkidle').status==200
       assert decode(one)['public_demo_token']!=decode(two)['public_demo_token']
       for ctx in (one,two):
        identity=decode(ctx);assert identity['company_code']=='A' and identity['username']=='checker' and identity['demo_role']=='driver' and identity['role']=='user'
       row=c.models.VehicleChecklistResult.query.filter_by(company_code='A',year=str(previous.year),month=f'{previous.month:02}',day=f'{previous.day:02}').one()
       assert row.status=='入力中' and len(json.loads(row.answers_json))==27
       stable=snapshot();fresh.reload(wait_until='networkidle');assert snapshot()==stable
       assert c.models.Notification.query.count()==0 and c.models.VehicleKarteAnalysis.query.count()==0
       fresh.screenshot(path=str(out/f'{scenario}-{width}-arrival.png'),full_page=True)
       record=fresh.locator('#vehicle-inspection-record')
       if record.count() and record.get_attribute('open') is None:record.locator('summary').first.click()
       assert fresh.locator('.vehicle-standard-daily-table').first.is_visible()
       if clock.day==1:
        values=fresh.locator(f'td.prior-month-projection[data-date="{previous.isoformat()}"]')
        assert sum(v.strip()=='✓' for v in values.all_text_contents())==27
        if width<=768:assert values.first.is_visible()
        else:assert not values.first.is_visible()
       else:
        values=fresh.locator(f'td.center-cell[data-day="{previous.day:02}"]')
        assert sum(v.strip()=='✓' for v in values.all_text_contents())==27
       fresh.screenshot(path=str(out/f'{scenario}-{width}-before.png'),full_page=True)
       if width<=768:
        bounds=values.first.evaluate('(e)=>{const p=e.getBoundingClientRect(),n=e.parentElement.querySelector("td.mobile-current-date").getBoundingClientRect();return {left:p.left,right:p.right,currentLeft:n.left,currentRight:n.right,width:innerWidth};}')
        assert bounds['left']>=-1 and bounds['right']<=bounds['currentLeft']+1 and bounds['currentRight']<=bounds['width']+1,bounds
       # Existing item action, not a synthetic substitute; open/close without save.
       button=fresh.locator('.js-open-detail:visible').first;button.scroll_into_view_if_needed();button.click()
       assert fresh.locator('#detailModal').is_visible()
       assert fresh.locator('#detailCommentEditor').count()==1
       fresh.keyboard.press('Escape')
       # Escape behavior is recorded, not invented as a product requirement.
       modal_open=fresh.locator('#detailModal').is_visible()
       if modal_open:
        save=fresh.locator('#detailModal button[type="submit"]');save.scroll_into_view_if_needed()
        box=save.bounding_box();assert box and box['width']>=44 and box['height']>=44
        assert box['x']>=0 and box['x']+box['width']<=width+1
        assert fresh.locator('#detailModal input[type="file"]').count()==2
        fresh.screenshot(path=str(out/f'{scenario}-{width}-modal.png'),full_page=True)
        fresh.locator('.js-close-detail-modal').click()
       assert not fresh.locator('#detailModal').is_visible()
       fresh.screenshot(path=str(out/f'{scenario}-{width}.png'),full_page=True)
       assert snapshot()==stable
       report['checks'].append({'scenario':scenario,'width':width,'previous_values':27,'two_sessions':True,'saved_input_status':'入力中','escape_closed':not modal_open,'unchanged_after_view':True})
    finally:
     for ctx in contexts:ctx.close()
     browser.close()
  finally:server.shutdown();server.server_close();thread.join(5)
 assert not report['blocked'],report['blocked'];assert not report['posts']
 if not a.preflight_only:assert len(report['checks'])==12
 report['overall']='passed'
except BaseException as error:
 report['overall']='failed';report['failure_class']=type(error).__name__;raise
finally:
 c.tearDown();c.doCleanups();c.tearDownClass();(out/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
