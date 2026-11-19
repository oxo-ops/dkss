"""Synthetic browser cookie-expiry acceptance. No production access; stale business POST must be rejected without writes."""
import argparse,json,os,sys,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from unittest.mock import patch
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--expected-sha');p.add_argument('--chromium');p.add_argument('--preflight-only',action='store_true');p.add_argument('--run-browser',action='store_true');a=p.parse_args()
repo=a.repo.resolve();out=a.artifacts.resolve();out.mkdir(parents=True,exist_ok=True)
assert os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED')=='1'
import sitecustomize
assert sitecustomize.ROOT==Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
for event,args in [('socket.connect',(None,('fixture.invalid',443))),('sqlite3.connect',('/not-fixture.db',))]:
 try:sys.audit(event,*args)
 except RuntimeError:pass
 else:raise AssertionError('guard inactive')
if not a.preflight_only:
 assert a.expected_sha and subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()==a.expected_sha
 assert not subprocess.check_output(['git','-C',str(repo),'status','--porcelain','--untracked-files=all'],text=True).strip()
sys.path[:0]=[str(repo),str(repo/'tests')]
from test_demo_inspection_compact import CompactDemoTests
case=CompactDemoTests();case.setUpClass()
report={'head':a.expected_sha,'fixture_only':True,'live_access':False,'cases':[],'blocked':[]}
def snap():return [(r.id,r.answers_json,r.status) for r in case.models.VehicleChecklistResult.query.order_by(case.models.VehicleChecklistResult.id).all()]
try:
 if a.preflight_only:
  import unittest
  import test_demo_session_recovery,test_demo_share_entry
  result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(m) for m in (test_demo_session_recovery,test_demo_share_entry)]))
  assert result.wasSuccessful();report['preflight_tests']=result.testsRun
 else:
  from playwright.sync_api import sync_playwright
  from http.server import HTTPServer,BaseHTTPRequestHandler
  from threading import Thread
  assert a.run_browser and a.chromium
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=a.chromium,headless=True)
   try:
    for width in (390,1316):
     for role in ('driver','manager'):
      case.setUp();before=snap();target='/pointouts';client=case.app.test_client(use_cookies=False)
      case.demo_active=False;case.login('checker',company='B')
      case.request('GET','/vehicle/checklists')
      normal_checklist=case.models.Checklist.query.filter_by(company_code='B').one().id
      case.demo_active=True
      record={'width':width,'role':role,'status':'running'};report['cases'].append(record);requests=[]
      class Handler(BaseHTTPRequestHandler):
       def log_message(self,*args):pass
       def do_GET(self):self.handle_request()
       def do_POST(self):self.handle_request()
       def handle_request(self):
        try:
         u=urlsplit(self.path);path=u.path;assert not u.scheme and not u.netloc and '..' not in path.split('/')
         allowed=(self.command=='GET' and path==f'/vehicle/checklists/{normal_checklist}') or path in (f'/vehicle/checklists/{case.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}', f'/vehicle/checklists/{case.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}/save-one', '/vehicle/checklists') or path in ('/demo','/demo/role','/','/login','/safety','/pointouts','/static/manifest.webmanifest','/favicon.ico','/api/approval-candidates','/api/notifications/recent','/api/notifications/unread-count','/api/push/vapid-public-key') or path.startswith(('/static/css/','/static/js/','/static/images/','/static/icons/','/static/vendor/','/static/guide/'))
         assert allowed,'unapproved path:'+path
         headers={'Cookie':self.headers.get('Cookie','')}
         if self.command=='POST':
          length=int(self.headers.get('Content-Length','0'));assert 0<length<8192
          data=parse_qs(self.rfile.read(length).decode(),keep_blank_values=True)
          if path=='/demo/role':
           assert set(data)=={'role','csrf_token','demo_entry'} and data['demo_entry']==['purpose'] and data['role']==[role] and len(data['csrf_token'])==1
          else:
           assert path==f'/vehicle/checklists/{case.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}/save-one'
           assert set(data)=={'vehicle_record_id','year','month','day','item_no','value','csrf_token'}
           assert data['vehicle_record_id']==[str(case.vehicle_id)] and data['value']==['✓']
           assert case.app.config['WTF_CSRF_ENABLED'] is True
          response=client.post(self.path,data={k:v[0] for k,v in data.items()},headers=headers)
         else:response=client.get(self.path,headers=headers)
         requests.append({'method':self.command,'path':path,'status':response.status_code,'location':response.location})
         if response.status_code in (301,302,303,307,308):
          loc=urlsplit(response.location);assert not loc.scheme and not loc.netloc
         self.send_response(response.status_code)
         for k,v in response.headers.items():
          if k.lower() not in ('content-length','content-encoding','connection'):self.send_header(k,v)
         self.send_header('Content-Length',str(len(response.data)));self.end_headers();self.wfile.write(response.data)
        except BaseException as e:
         report['blocked'].append(type(e).__name__+':'+str(e));self.send_response(500);self.end_headers()
      server=HTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start();origin=f'http://127.0.0.1:{server.server_port}'
      ctx=browser.new_context(viewport={'width':width,'height':844},service_workers='block')
      def route(r):
       if not r.request.url.startswith(origin+'/') or r.request.method not in ('GET','POST'):report['blocked'].append('network');r.abort()
       else:r.continue_()
      ctx.route('**/*',route)
      def ws(w):report['blocked'].append('websocket');w.close()
      ctx.route_web_socket('**/*',ws);page=ctx.new_page()
      try:
       # Previously distributed PC marker must work with no cookies, as must QR /demo.
       page.goto(origin+'/?__aonagi_entry=1',wait_until='networkidle')
       assert page.locator('.public-demo-notice').is_visible()
       record['fresh_marker_entry']=True
       page.screenshot(path=str(out/f'{width}-{role}-fresh-marker-entry.png'),full_page=True)
       ctx.clear_cookies()
       page.goto(origin+'/demo',wait_until='networkidle')
       assert page.locator('.public-demo-notice').is_visible()
       page.screenshot(path=str(out/f'{width}-{role}-fresh-qr-entry.png'),full_page=True)
       record['fresh_qr_entry']=True
       page.locator(f'form[action="/demo/role"] button[value="{role}"]').click();page.locator('.public-demo-notice').wait_for(state='detached');page.wait_for_load_state('networkidle')
       page.goto(origin+target,wait_until='networkidle');assert '/login' not in page.url
       cookies={c['name']:c for c in ctx.cookies()};name=case.app.config['SESSION_COOKIE_NAME'];assert 'dkss_demo_return' in cookies
       hint=cookies['dkss_demo_return'];assert hint['httpOnly'] and hint['secure'] and hint['sameSite']=='Lax'
       serializer=case.app.session_interface.get_signing_serializer(case.app)
       state=serializer.loads(cookies[name]['value']);assert state['demo_role']==role
       page.reload(wait_until='networkidle');current={c['name']:c for c in ctx.cookies()};assert serializer.loads(current[name]['value'])['demo_role']==role
       before_recovery=urlsplit(page.url)
       recovery_path=before_recovery.path+('?' + before_recovery.query if before_recovery.query else '')
       with patch('itsdangerous.timed.time.time',return_value=int(time.time())-1801):aged=serializer.dumps(state)
       replacement={k:v for k,v in current[name].items() if k in ('name','domain','path','expires','httpOnly','secure','sameSite')};replacement['value']=aged;ctx.add_cookies([replacement]);requests.clear()
       page.reload(wait_until='networkidle')
       assert page.locator('.public-demo-notice').is_visible();assert all(r['path']!='/login' for r in requests)
       assert any(r['path']==target and r['location']==recovery_path for r in requests)
       assert urlsplit(page.url).path==before_recovery.path
       assert parse_qs(urlsplit(page.url).query)==parse_qs(before_recovery.query)
       assert not any(r['path']=='/demo' for r in requests)
       after={c['name']:c for c in ctx.cookies()};assert serializer.loads(after[name]['value'])['demo_role']=='driver'
       assert snap()==before
       page.screenshot(path=str(out/f'{width}-{role}-recovered.png'),full_page=True)
       page.goto(origin+'/login',wait_until='networkidle')
       assert page.locator('input[name="company_code"]').is_visible()
       assert not page.locator('.public-demo-notice').count()
       assert 'dkss_demo_return' not in {c['name']:c for c in ctx.cookies()}
       page.screenshot(path=str(out/f'{width}-{role}-normal-login.png'),full_page=True)
       page.goto(origin+'/demo',wait_until='networkidle')
       assert urlsplit(page.url).query=='__aonagi_entry=1'
       assert page.locator('.public-demo-notice').is_visible()
       page.goto(origin+'/',wait_until='networkidle')
       assert urlsplit(page.url).path=='/login'
       assert page.locator('input[name="company_code"]').is_visible()
       assert 'dkss_demo_return' not in {c['name']:c for c in ctx.cookies()}
       page.screenshot(path=str(out/f'{width}-{role}-bare-home-login.png'),full_page=True)
       # Two real browser tabs sharing cookies: stale demo form cannot save in normal B.
       page.goto(origin+'/demo',wait_until='networkidle')
       oldtab=ctx.new_page();checklist=case.app.config['PUBLIC_DEMO_CHECKLIST_ID']
       oldtab.goto(origin+f'/vehicle/checklists/{checklist}?vehicle_record_id={case.vehicle_id}',wait_until='networkidle')
       stale_token=oldtab.locator('input[name="csrf_token"]').first.input_value()
       page.goto(origin+'/login',wait_until='networkidle')
       assert page.locator('input[name="company_code"]').is_visible()
       # Authenticate only the isolated fixture, never a real account or login bypass route.
       case.demo_active=False;case.client=case.app.test_client();case.login('checker',company='B')
       with case.client.session_transaction() as normal_state:normal_cookie=serializer.dumps(dict(normal_state))
       cookie_spec={'name':name,'value':normal_cookie,'url':origin,'httpOnly':True,'sameSite':'Lax'}
       ctx.add_cookies([cookie_spec]);previous_csrf=case.app.config['WTF_CSRF_ENABLED'];case.app.config['WTF_CSRF_ENABLED']=True
       try:
        data={'vehicle_record_id':str(case.vehicle_id),'year':'2026','month':'11','day':'19','item_no':'0','value':'✓','csrf_token':stale_token}
        status=oldtab.evaluate("async x=>(await fetch(x.path,{method:'POST',body:new URLSearchParams(x.data),redirect:'manual'})).status",{'path':f'/vehicle/checklists/{checklist}/save-one','data':data})
        assert status==400 and snap()==before
        # Back/Forward to the old marked demo home must not silently re-enter demo.
        page.go_back(wait_until='networkidle');page.reload(wait_until='networkidle')
        assert urlsplit(page.url).query=='__aonagi_entry=1'
        assert not page.locator('.public-demo-notice').count()
        assert any(r['path']=='/' and r['status']==409 for r in requests)
        normal_response=oldtab.goto(origin+'/vehicle/checklists',wait_until='networkidle')
        assert normal_response.status==200
        assert not oldtab.locator('.public-demo-notice').count()
        now={c['name']:c for c in ctx.cookies()};state=serializer.loads(now[name]['value'])
        assert state['company_code']=='B' and not state.get('aonagi_readonly_demo')
        record['shared_cookie_limit']='old common GET uses explicitly authenticated normal company; separate simultaneous sessions not supported'
        record['stale_post_status']=status;record['normal_company_preserved']=True
        page.screenshot(path=str(out/f'{width}-{role}-old-marked-tab-blocked.png'),full_page=True)
       finally:
        case.app.config['WTF_CSRF_ENABLED']=previous_csrf;case.demo_active=True;oldtab.close()
       assert all(r['status']==400 for r in requests if r['method']=='POST' and r['path'].endswith('/save-one'))
       record.update(status='passed',requests=requests,business_writes=False)
      except BaseException as e:
       record.update(status='failed',error=type(e).__name__+':'+str(e),requests=requests,current_url=page.url)
       try:page.screenshot(path=str(out/f'{width}-{role}-FAILED.png'),full_page=True)
       except BaseException as shot:record['screenshot_error']=type(shot).__name__
       raise
      finally:ctx.close();server.shutdown();server.server_close();thread.join(timeout=5);case.tearDown();case.doCleanups()
   finally:browser.close()
  assert not report['blocked']
finally:
 (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));case.tearDownClass()
