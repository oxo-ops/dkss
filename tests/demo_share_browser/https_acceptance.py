"""TLS browser regression on disposable synthetic data, never a deployed service."""
import argparse,json,os,subprocess,sys,ssl
from pathlib import Path
from urllib.parse import urlsplit
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--chromium',required=True);p.add_argument('--expected-sha',required=True);a=p.parse_args()
r=a.repo.resolve();out=a.artifacts.resolve();out.mkdir(parents=True,exist_ok=True)
assert os.environ['DKSS_BROWSER_ACCEPTANCE_ISOLATED']=='1'
assert subprocess.check_output(['git','-C',str(r),'rev-parse','HEAD'],text=True).strip()==a.expected_sha
assert not subprocess.check_output(['git','-C',str(r),'status','--porcelain'],text=True).strip()
import sitecustomize
assert sitecustomize.ROOT==Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
try:sys.audit('socket.connect',None,('example.invalid',443))
except RuntimeError:pass
else:raise AssertionError('network guard absent')
sys.path[:0]=[str(r),str(r/'tests')]
from test_demo_inspection_compact import CompactDemoTests
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from threading import Thread,Lock
from playwright.sync_api import sync_playwright
c=CompactDemoTests();c.setUpClass();c.setUp();c.app.config['WTF_CSRF_ENABLED']=True
assert c.app.config['WTF_CSRF_SSL_STRICT']
report={'candidate_sha':a.expected_sha,'synthetic_only':True,'https':True,'blocked':[],'posts':[],'checks':[]}
path=f'/vehicle/checklists/{c.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}'
target=path+f'?vehicle_record_id={c.vehicle_id}&year=2026&month=10&active_day=23&__aonagi_entry=1'
lock=Lock()
class Bridge(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):self.handle_request('GET')
 def do_POST(self):self.handle_request('POST')
 def handle_request(self,method):
  try:
   u=urlsplit(self.path);assert not u.netloc and not u.scheme and '..' not in u.path.split('/')
   allow={'/','/demo','/demo/role',path,path+'/save-detail','/api/approval-candidates','/api/notifications/recent','/api/notifications/unread-count','/api/push/vapid-public-key','/static/manifest.webmanifest','/favicon.ico','/static/guide/inspection-detail-open.png'}
   assert u.path in allow or u.path.startswith(('/static/css/','/static/js/','/static/images/','/static/icons/','/static/vendor/'))
   data=None
   if method=='POST':
    assert u.path in {'/demo/role',path+'/save-detail'}
    n=int(self.headers.get('Content-Length','0'));assert 0<n<32768;data=self.rfile.read(n)
    # Only forms emitted by this fixture may write, with real CSRF validation.
    with c.app.test_request_context(self.path,method='POST',data=data,content_type=self.headers.get('Content-Type')):
     from flask import request
     if u.path=='/demo/role':
      assert set(request.form)=={'role','csrf_token','checklist_return','demo_entry'} and request.form['demo_entry']=='purpose'
      assert request.form['role'] in ('manager','driver') and request.form['checklist_return'].startswith(path+'?')
     else:
      assert request.form['vehicle_record_id']==str(c.vehicle_id)
      assert request.form['year']=='2026' and request.form['month']=='10' and request.form['day']=='23'
      assert request.form['comment']=='TLSブラウザ保存確認'
      assert not any(f.filename for f in request.files.values())
   client=c.app.test_client(use_cookies=False)
   with lock:
    res=client.open(self.path,method=method,base_url=origin,headers={'Cookie':self.headers.get('Cookie',''),'Referer':self.headers.get('Referer',''),'X-DKSS-Validation-Only':self.headers.get('X-DKSS-Validation-Only','')},data=data,content_type=self.headers.get('Content-Type'))
   if method=='POST':report['posts'].append({'path':u.path,'status':res.status_code,'same_origin_referrer':self.headers.get('Referer','').startswith(origin+'/')})
   if 300<=res.status_code<400:assert res.status_code==302 and res.location.startswith('/') and not res.location.startswith('//')
   self.send_response(res.status_code)
   for k,v in res.headers.items():
    if k.lower() not in ('content-length','content-encoding','connection'):self.send_header(k,v)
   self.send_header('Content-Length',str(len(res.data)));self.end_headers();self.wfile.write(res.data)
  except BaseException as error:
   report['blocked'].append(repr(error));self.send_response(500);self.end_headers()
try:
 tmp=sitecustomize.ROOT;cert=tmp/'local-test-cert.pem';key=tmp/'local-test-key.pem'
 subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1,DNS:localhost'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 server=ThreadingHTTPServer(('127.0.0.1',0),Bridge);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key);server.socket=tls.wrap_socket(server.socket,server_side=True)
 origin=f'https://127.0.0.1:{server.server_port}';thread=Thread(target=server.serve_forever,daemon=True);thread.start()
 def guard(route):
  if urlsplit(route.request.url).netloc!=urlsplit(origin).netloc:report['blocked'].append('external');route.abort()
  else:route.continue_()
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=a.chromium,headless=True)
   try:
    for role,width in [('manager',1280),('driver',390)]:
     # Trust applies solely to this generated loopback certificate, not production.
     ctx=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':844},service_workers='block');ctx.route('**/*',guard);ctx.route_web_socket('**/*',lambda ws:ws.close())
     page=ctx.new_page();res=page.goto(origin+target,wait_until='networkidle');assert res.status==200
     assert res.headers['referrer-policy']=='same-origin'
     count=c.models.VehicleChecklistResult.query.count()
     page.locator(f'button[name="role"][value="{role}"]').click();page.locator('.public-demo-notice').wait_for(state='detached');page.wait_for_load_state('networkidle')
     assert urlsplit(page.url).path==('/' if role=='manager' else path)
     # Purpose entry opens the current day; select the dated synthetic record for save coverage.
     page.goto(origin+target,wait_until='networkidle')
     assert urlsplit(page.url).path==path and f'vehicle_record_id={c.vehicle_id}' in page.url
     assert page.locator('#vehicle_workspace_date').is_visible()
     assert c.models.VehicleChecklistResult.query.count()==count
     page.screenshot(path=str(out/f'https-{role}-return.png'),full_page=True)
     report['checks'].append(role+' purpose destination and checklist access verified without record writes')
     if role=='driver':
      detail=next(x for x in page.locator('.inspection-item-detail').all() if x.is_visible())
      detail.click();assert page.locator('#detailModal').is_visible()
      page.locator('#detailCommentEditor').fill('TLSブラウザ保存確認')
      item=page.locator('#detailItemNo').input_value()
      with page.expect_navigation(wait_until='networkidle'):
       with page.expect_response(lambda response: urlsplit(response.url).path==path+'/save-detail') as saved:
        page.locator('#detailModal button[type="submit"]').click()
      assert saved.value.status==302
      assert urlsplit(page.url).path==path
      c.db.session.expire_all();rows=c.models.VehicleChecklistResult.query.filter_by(company_code='A').all()
      assert len(rows)==1
      answer=next(x for x in json.loads(rows[0].answers_json) if str(x['item_no'])==item)
      assert answer['comment']=='TLSブラウザ保存確認'
      next(x for x in page.locator('.inspection-item-detail').all() if x.is_visible()).click()
      assert page.locator('#detailCommentEditor').inner_text()=='TLSブラウザ保存確認'
      page.screenshot(path=str(out/'https-driver-saved.png'),full_page=True)
      report['checks'].append('HTTPS real form save persisted and redisplayed synthetic comment')
     ctx.close()
   finally:browser.close()
 finally:server.shutdown();server.server_close();thread.join(5)
 assert len(report['posts'])==3 and all(x['status']==302 and x['same_origin_referrer'] for x in report['posts']),report
 assert not report['blocked'],report
 report['passed']=True
finally:
 c.app.config['WTF_CSRF_ENABLED']=False;c.tearDown();c.doCleanups();c.tearDownClass();(out/'https-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
