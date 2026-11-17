"""Synthetic Flask bridge; only role POST permitted, never inspection writes."""
import argparse,os,sys,json,subprocess,hashlib
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--expected-sha');p.add_argument('--chromium');p.add_argument('--preflight-only',action='store_true');p.add_argument('--run-browser',action='store_true');a=p.parse_args()
repo=a.repo.resolve();out=a.artifacts.resolve();out.mkdir(parents=True,exist_ok=True)
assert os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED')=='1'
import sitecustomize
assert sitecustomize.ROOT==Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
for event,arg in [('socket.connect',(None,('fixture.invalid',443))),('sqlite3.connect',('/not-fixture.db',))]:
 try:sys.audit(event,*arg)
 except RuntimeError:pass
 else:raise AssertionError('isolation guard inactive')
if not a.preflight_only:
 assert a.expected_sha and subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()==a.expected_sha
 assert not subprocess.check_output(['git','-C',str(repo),'status','--porcelain','--untracked-files=all'],text=True).strip()
sys.path[:0]=[str(repo),str(repo/'tests')]
from test_demo_inspection_compact import CompactDemoTests
case=CompactDemoTests();case.setUpClass()
report={'head':a.expected_sha,'fixture_only':True,'live_access':False,'browser_started':False,'transport':'loopback-only HTTP; native redirects; synthetic Flask client session','cases':[],'blocked':[]}
ORIGIN='https://fixture.invalid'
def snapshot():
 return {'items':[(r.id,r.items_json) for r in case.models.Checklist.query.order_by(case.models.Checklist.id).all()], 'results':[(r.id,r.answers_json,r.status,r.operation_judgment_json) for r in case.models.VehicleChecklistResult.query.order_by(case.models.VehicleChecklistResult.id).all()]}
def setup():
 case.setUp();case.begin(defect=True)
 state=json.loads(case.row.operation_judgment_json);state['requested_usernames']=[] if scenario=='未判定' else ['admin']
 state['status']=scenario
 if scenario!='未判定':
  state.update(judged_at='2026-10-23 10:00:00',judged_by='合成管理者',judged_by_username='admin',reason='合成表示確認',checks_evidence='合成根拠');case.row.status='承認済み'
 case.row.operation_judgment_json=json.dumps(state,ensure_ascii=False);case.db.session.commit()
 return f'/vehicle/checklists/{case.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}?vehicle_record_id={case.vehicle_id}&year=2026&month=10&active_day=23' 
def cleanup():
 case.tearDown();case.doCleanups()
try:
 if a.preflight_only:
  for role,scenario in ((r,s) for r in ('driver','manager') for s in ('未判定','運行可','運行不可','判定保留')):
   target=setup()
   try:
    token,html=case.enter();before=snapshot()
    response=case.client.post('/demo/role',data={'role':role,'csrf_token':token});assert response.status_code==302 and response.location=='/'
    assert 'class="alert public-demo-notice"' not in case.client.get('/').get_data(as_text=True)
    text=case.client.get(target).get_data(as_text=True);assert 'エンジンのかかり具合、異音' in text and 'criteria-line-pre' in text
    assert snapshot()==before
    assert 'vehicle-operation-panel' in text and '現在の未解消不具合の対応状況' in text
    if scenario=='未判定':assert '整備管理者が未設定です。' in text and '整備管理者を選択' in text
    else:assert ('判断保留' if scenario=='判定保留' else scenario) in text
    assert 'vehicle-process-number' in text and 'aria-label="点検・不具合・運行判断の状態"' in text
    assert '整備管理者：未設定' not in text
    assert 'vehicle-operation-context-list' in text
    from threading import Thread
    threaded=[]
    def check_thread():
     try:threaded.append(case.client.get(target).status_code)
     except BaseException as error:threaded.append(type(error).__name__)
    thread=Thread(target=check_thread);thread.start();thread.join(timeout=10)
    assert threaded==[200],threaded
    report['cases'].append({'role':role,'scenario':scenario,'status':'preflight-passed'})
   finally:cleanup()
 else:
  assert a.run_browser and a.chromium
  from playwright.sync_api import sync_playwright
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=a.chromium,headless=True)
   report['browser_started']=True
   try:
    for width in (320,390,768,1316):
     for role,scenario in ((r,s) for r in ('driver','manager') for s in ('未判定','運行可','運行不可','判定保留')):
      target=setup();before=snapshot();ctx=browser.new_context(viewport={'width':width,'height':800},service_workers='block');requests=[];post_count=[0];errors=[]
      # Use a bound loopback server so Chromium follows real HTTP 302s.
      # Route interception alone does not intercept redirected requests.
      from http.server import HTTPServer,BaseHTTPRequestHandler
      from threading import Thread
      class BridgeHandler(BaseHTTPRequestHandler):
       def log_message(self,*args):pass
       def do_GET(self):self.handle_fixture('GET')
       def do_POST(self):self.handle_fixture('POST')
       def handle_fixture(self,method):
        try:
         u=urlsplit(self.path);path=u.path;query=('?'+u.query if u.query else '')
         assert not u.scheme and not u.netloc and '..' not in path.split('/')
         if method=='POST':
          length=int(self.headers.get('Content-Length','0'));assert 0<length<8192
          assert self.headers.get('Content-Type','').startswith('application/x-www-form-urlencoded')
          data=parse_qs(self.rfile.read(length).decode(),keep_blank_values=True)
          assert path=='/demo/role' and set(data)=={'role','csrf_token'} and data['role']==[role] and len(data['csrf_token'])==1 and not post_count[0]
          post_count[0]+=1;res=case.client.post(path,data={k:v[0] for k,v in data.items()})
          assert res.status_code==302 and res.location=='/'
         elif path in ('/demo','/',urlsplit(target).path,'/api/approval-candidates','/api/notifications/recent','/api/notifications/unread-count','/api/push/vapid-public-key','/static/manifest.webmanifest','/favicon.ico') or path.startswith(('/static/css/','/static/js/','/static/images/','/static/icons/','/static/vendor/')):
          if path==urlsplit(target).path:assert parse_qs(u.query).get('vehicle_record_id')==[str(case.vehicle_id)]
          res=case.client.get(path+query)
         else:raise AssertionError('GET outside synthetic allowlist')
         if 300<=res.status_code<400:assert res.status_code==302 and res.location=='/'
         requests.append({'method':method,'path':path,'status':res.status_code})
         self.send_response(res.status_code)
         for k,v in res.headers.items():
          if k.lower() not in ('set-cookie','content-length','content-encoding','connection'):self.send_header(k,v)
         self.send_header('Content-Length',str(len(res.data)));self.end_headers();self.wfile.write(res.data)
        except BaseException as error:
         report['blocked'].append(type(error).__name__+':'+str(error));self.send_response(500);self.end_headers()
      server=HTTPServer(('127.0.0.1',0),BridgeHandler);server_thread=Thread(target=server.serve_forever,daemon=True);server_thread.start()
      origin=f'http://127.0.0.1:{server.server_port}'
      def bridge(route):
       u=urlsplit(route.request.url)
       if u.scheme+'://'+u.netloc!=origin or route.request.method not in ('GET','POST'):
        report['blocked'].append('external-or-method');route.abort();return
       route.continue_()
      ctx.route('**/*',bridge)
      def reject_ws(ws):report['blocked'].append('websocket');ws.close()
      ctx.route_web_socket('**/*',reject_ws);page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
      record={'width':width,'role':role,'scenario':scenario,'status':'running'};report['cases'].append(record)
      try:
       page.goto(origin+'/demo',wait_until='networkidle');assert page.locator('.public-demo-notice').is_visible()
       entry_url=urlsplit(page.get_by_role('link',name='日常点検を開く',exact=True).get_attribute('href')); expected_entry=urlsplit(target.split('&year=')[0])
       assert entry_url.path==expected_entry.path and parse_qs(entry_url.query)=={**parse_qs(expected_entry.query),'__aonagi_entry':['1']}
       page.screenshot(path=str(out/f'{width}-{role}-{scenario}-entry.png'),full_page=True)
       page.locator(f'form[action="/demo/role"] button[name="role"][value="{role}"]').click()
       page.wait_for_url(lambda u:urlsplit(u).path=='/' and parse_qs(urlsplit(u).query)=={'__aonagi_entry':['1']});page.wait_for_load_state('networkidle')
       assert post_count[0]==1 and page.locator('.public-demo-notice').count()==0
       with case.client.session_transaction() as s:assert s['demo_role_selected'] is True and s['demo_role']==role
       page.screenshot(path=str(out/f'{width}-{role}-{scenario}-home.png'),full_page=True)
       page.goto(origin+target,wait_until='networkidle');assert page.locator('#vehicle_workspace_date').is_visible()
       assert page.locator('.public-demo-notice').count()==0
       assert page.locator('#vehicle_check_filter [name="vehicle_record_id"]').input_value()==str(case.vehicle_id)
       header=page.locator('.vehicle-workspace-header')
       assert header.is_visible() and '品川' in header.inner_text()
       date=page.locator('#vehicle_workspace_date');assert date.input_value()=='2026-10-23'
       assert date.bounding_box()['height']>=44
       page.screenshot(path=str(out/f'{width}-{role}-{scenario}-saved-top.png'),full_page=True)
       operation=page.locator('[data-vehicle-response-view="operation"]');assert operation.is_enabled()
       assert ('判断保留' if scenario=='判定保留' else scenario) in operation.inner_text()
       assert page.locator('.vehicle-process-number svg').count()==3
       assert page.locator('.vehicle-process-step').first.evaluate('(e)=>getComputedStyle(e).clipPath')=='none'
       operation.click()
       panel=page.locator('#vehicle-operation-panel');assert panel.is_visible()
       if scenario=='未判定':assert '整備管理者が未設定です。' in panel.inner_text()
       assert '現在の未解消不具合の対応状況' in panel.inner_text()
       assert '整備管理者：未設定' not in panel.inner_text()
       select=panel.locator('select[name="manager_username"]')
       if scenario=='未判定':
        assert select.count()==1 and select.is_visible()
        select.scroll_into_view_if_needed();assert select.bounding_box()['height']>=44
        assert panel.get_by_role('button',name='整備管理者を設定',exact=True).is_enabled()
       else:assert select.count()==0
       if width<=900:
        assert header.evaluate('(e)=>getComputedStyle(e).position')=='static'
        page.evaluate('window.scrollTo(0,Math.min(document.documentElement.scrollHeight-innerHeight,600))')
        page.wait_for_timeout(100)
        assert header.bounding_box()['y']+header.bounding_box()['height']<0,'header still covers scrolled content'
       assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
       page.screenshot(path=str(out/f'{width}-{role}-{scenario}-saved-operation.png'),full_page=True)
       assert snapshot()==before,'inspection data changed'
       page.goto(origin+'/demo',wait_until='networkidle');assert page.locator('.public-demo-notice').is_visible()
       assert not errors,errors;assert not report['blocked'],report['blocked']
       record.update(status='passed',requests=requests,inspection_unchanged=True)
      except BaseException as error:
       record.update(status='failed',error_type=type(error).__name__,error=str(error),requests=requests,page_errors=errors)
       try:page.screenshot(path=str(out/f'{width}-{role}-{scenario}-FAILED.png'),full_page=True)
       except BaseException as capture:record['capture_error']=type(capture).__name__
       raise
      finally:ctx.close();server.shutdown();server.server_close();server_thread.join(timeout=5);cleanup()
   finally:browser.close()
finally:
 case.tearDownClass();(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print('PASS',len(report['cases']),'synthetic cases; real device and visual acceptance remain')
