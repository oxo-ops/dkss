"""Synthetic real-Flask, real-browser-cookie acceptance; never production access."""
import argparse,json,os,sys,time,subprocess
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--chromium');p.add_argument('--expected-sha');p.add_argument('--preflight-only',action='store_true');a=p.parse_args()
r=a.repo.resolve();out=a.artifacts.resolve();out.mkdir(parents=True,exist_ok=True)
assert os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED')=='1'
if not a.preflight_only:
 assert a.expected_sha and subprocess.check_output(['git','-C',str(r),'rev-parse','HEAD'],text=True).strip()==a.expected_sha
 assert not subprocess.check_output(['git','-C',str(r),'status','--porcelain','--untracked-files=all'],text=True).strip()
import sitecustomize
assert sitecustomize.ROOT==Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
try:sys.audit('socket.connect',None,('fixture.invalid',443))
except RuntimeError:pass
else:raise AssertionError('guard inactive')
sys.path[:0]=[str(r),str(r/'tests')]
from test_demo_inspection_compact import CompactDemoTests
c=CompactDemoTests();c.setUpClass();c.setUp();c.begin(defect=True)
report={'synthetic_only':True,'browser_started':False,'blocked':[],'posts':[],'checks':[]}
try:
 target=f'/vehicle/checklists/{c.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}?vehicle_record_id={c.vehicle_id}&year=2026&month=10&active_day=23&__aonagi_entry=1'
 before=[(x.id,x.answers_json,x.operation_judgment_json) for x in c.models.VehicleChecklistResult.query.all()]
 def snapshot():return [(x.id,x.answers_json,x.operation_judgment_json) for x in c.models.VehicleChecklistResult.query.all()]
 # A cookie managed by an unrelated visitor must never replace ordinary identity.
 normal=c.app.test_client();c.demo_active=False;c.client=normal;c.login('admin')
 cookie_name=c.app.config.get('SESSION_COOKIE_NAME','session');normal_cookie=normal.get_cookie(cookie_name).value
 if a.preflight_only:
  from threading import Thread
  results=[]
  def probe():
   client=c.app.test_client(use_cookies=False);res=client.get(target);results.append(res.status_code);results.append(any(k.lower()=='set-cookie' for k,v in res.headers.items()))
  t=Thread(target=probe);t.start();t.join(10);assert results==[302,True],results
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
     allow={'/','/demo','/demo/role',urlsplit(target).path,'/api/approval-candidates','/api/notifications/recent','/api/notifications/unread-count','/api/push/vapid-public-key','/static/manifest.webmanifest','/favicon.ico','/static/guide/inspection-detail-open.png'}
     assert u.path in allow or u.path.startswith(('/static/css/','/static/js/','/static/images/','/static/icons/','/static/vendor/'))
     data=None
     if method=='POST':
      assert u.path=='/demo/role';n=int(self.headers.get('Content-Length','0'));assert 0<n<8192
      assert self.headers.get('Content-Type','').startswith('application/x-www-form-urlencoded')
      data=parse_qs(self.rfile.read(n).decode(),keep_blank_values=True);assert set(data)=={'role','csrf_token','demo_entry'} and data['demo_entry']==['purpose'] and data['role']==['manager'] and len(data['csrf_token'])==1
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
     for width in (390,1280):
      one=browser.new_context(viewport={'width':width,'height':844},service_workers='block');two=browser.new_context(viewport={'width':width,'height':844},service_workers='block');ordinary=browser.new_context(service_workers='block');contexts.extend([one,two,ordinary])
      for ctx in (one,two,ordinary):ctx.route('**/*',guard);ctx.route_web_socket('**/*',lambda ws:ws.close())
      page=one.new_page();page.goto(origin+'/demo',wait_until='networkidle');page.locator('button[name="role"][value="manager"]').click();page.locator('.public-demo-notice').wait_for(state='detached');page.wait_for_url(origin+'/?__aonagi_entry=1');page.wait_for_load_state('networkidle');assert decode(one)['demo_role']=='manager'
      page.goto(origin+target,wait_until='networkidle');copied=page.url;first=decode(one)
      fresh=two.new_page();response=fresh.goto(copied,wait_until='networkidle');assert response.status==200
      second=decode(two);assert second['demo_role']=='driver' and second['role']=='user';assert first['public_demo_token']!=second['public_demo_token'];assert first['company_code']==second['company_code']=='A'
      assert response.headers['referrer-policy']=='same-origin' and 'no-store' in response.headers['cache-control']
      assert fresh.locator('#vehicle_workspace_date').is_visible();assert '__aonagi_entry=1' in fresh.url
      token=second['public_demo_token'];fresh.reload(wait_until='networkidle');assert decode(two)['public_demo_token']==token
      fresh.screenshot(path=str(out/f'{width}-fresh-initial.png'),full_page=True)
      page.screenshot(path=str(out/f'{width}-source-initial.png'),full_page=True)
      # Existing GET form stays a GET and carries only the public hint.
      form=fresh.locator('#vehicle_check_filter');assert form.locator('input[name="__aonagi_entry"]').count()==1
      form.evaluate('(f)=>f.requestSubmit()');fresh.wait_for_load_state('networkidle');assert '__aonagi_entry=1' in fresh.url
      fresh.goto(copied+'#vehicle-flow-judgment',wait_until='networkidle');assert fresh.evaluate('location.hash')=='#vehicle-flow-judgment'
      assert fresh.locator('#vehicle-operation-panel').is_visible()
      # Saved-result flags belong to existing UI, not URL sanitation. They must
      # be consumed by that UI or retained unchanged, never silently removed.
      page.goto(origin+target.replace('&__aonagi_entry=1','')+'&vehicle_saved=repair&vehicle_saved_item=1&vehicle_saved_date=2026%2F10%2F23#vehicle-flow-defect-'+str(c.row.id)+'-1',wait_until='networkidle')
      assert page.evaluate('location.hash').startswith('#vehicle-flow-defect-')
      assert page.locator('.vehicle-save-feedback').count()>0
      assert 'vehicle_saved=' not in page.url and '__aonagi_entry=1' in page.url
      saved_copy=page.url
      savedvisitor=browser.new_context(viewport={'width':width,'height':844},service_workers='block');contexts.append(savedvisitor);savedvisitor.route('**/*',guard);savedvisitor.route_web_socket('**/*',lambda ws:ws.close())
      savedpage=savedvisitor.new_page();assert savedpage.goto(saved_copy,wait_until='networkidle').status==200
      assert decode(savedvisitor)['demo_role']=='driver' and decode(savedvisitor)['public_demo_token']!=first['public_demo_token']
      assert savedpage.evaluate('location.hash')==page.evaluate('location.hash')
      savedpage.screenshot(path=str(out/f'{width}-saved-copy-driver.png'),full_page=True)
      completed_url=origin+target.replace('&__aonagi_entry=1','')+'&vehicle_saved=complete#vehicle-flow-completed'
      page.goto(completed_url,wait_until='networkidle');assert 'vehicle_saved=complete' in page.url and '__aonagi_entry=1' in page.url
      assert page.evaluate('location.hash')=='#vehicle-flow-completed'
      completevisitor=browser.new_context(viewport={'width':width,'height':844},service_workers='block');contexts.append(completevisitor);completevisitor.route('**/*',guard)
      completepage=completevisitor.new_page();assert completepage.goto(page.url,wait_until='networkidle').status==200
      assert decode(completevisitor)['demo_role']=='driver' and completepage.evaluate('location.hash')=='#vehicle-flow-completed'
      assert completepage.locator('#vehicle-flow-completed').is_visible()
      completepage.screenshot(path=str(out/f'{width}-completed-copy-driver.png'),full_page=True)
      fresh.goto(copied,wait_until='networkidle')

      for name,pg in [('source-manager',page),('fresh-driver',fresh)]:pg.screenshot(path=str(out/f'{width}-{name}.png'),full_page=True)
      # Normal authenticated context keeps its principal and is denied entry.
      ordinary.add_cookies([{'name':cookie_name,'value':normal_cookie,'url':origin}]);normalpage=ordinary.new_page();denial=normalpage.goto(copied,wait_until='networkidle');assert denial.status==409
      assert not decode(ordinary).get('aonagi_readonly_demo') and decode(ordinary)['username']=='admin'
      # Browser Back returns to same marked page, without copying any credentials.
      fresh.goto(origin+'/?__aonagi_entry=1',wait_until='networkidle');fresh.go_back(wait_until='networkidle');assert fresh.url==copied and decode(two)['public_demo_token']==token
      assert snapshot()==before
      report['checks'].append({'width':width,'fresh_driver':True,'separate_session':True,'ordinary_preserved':True,'reload_back':True,'business_data_unchanged':True})
    finally:
     for ctx in contexts:ctx.close()
     browser.close()
  finally:server.shutdown();server.server_close();thread.join(5)
 assert snapshot()==before;assert not report['blocked'],report['blocked']
finally:
 c.tearDown();c.doCleanups();c.tearDownClass();(out/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
