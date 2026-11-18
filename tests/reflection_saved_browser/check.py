"""Disposable fixture only. No Live, AI, SMTP or application POST."""
import argparse,sys,os,types,tempfile,unittest,json,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--out',required=True);p.add_argument('--pg',action='store_true');p.add_argument('--browser',action='store_true');a=p.parse_args()
r=Path(a.repo).resolve();out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True);sys.path[:0]=[str(r/'tests'),str(r)];os.chdir(r)
if a.pg:
 # Adapt only the disposable test setup, never product source. Constant PG URL
 # is the dedicated CI service, not configurable by user or inherited secrets.
 name='test_driving_reflection_identity';path=r/'tests'/f'{name}.py';s=path.read_text()
 s=s.replace("'DATABASE_URL': 'sqlite:///' + str(database)","'DATABASE_URL': 'postgresql://fixture:fixture@127.0.0.1:55441/reflection_fixture'")
 s=s.replace("if dialect.name != 'sqlite' or not args or Path(args[0]).resolve() != database.resolve():", "if dialect.name != 'postgresql' or kwargs.get('host') != '127.0.0.1' or str(kwargs.get('port')) != '55441' or kwargs.get('dbname') != 'reflection_fixture' or kwargs.get('user') != 'fixture':")
 assert "'DATABASE_URL': 'sqlite:///" not in s and "kwargs.get('dbname')" in s
 m=types.ModuleType(name);m.__file__=str(path);sys.modules[name]=m;exec(compile(s,str(path),'exec'),m.__dict__)
import test_demo_reflection_saved_period as suite
import test_driving_reflection_identity as identity
# SQLite baseline does not enforce this FK. Preserve the real PG constraint by
# seeding the referenced synthetic draft before each synthetic report.
_original_save=identity.ReflectionIdentityTests.save
def save_with_parent(self,i=1,**kw):
 from dkss_app.models import VehicleDocumentImportDraft
 import hashlib
 key='fixture-'+str(i)
 if self.m.db.session.get(VehicleDocumentImportDraft,key) is None:
  data=b'synthetic fixture, not an original document'
  self.m.db.session.add(VehicleDocumentImportDraft(id=key,batch_id='reflection-fixture',company_code='TEST',created_by_username='admin',document_type='driving_report',source_filename='synthetic.txt',source_file=data,source_sha256=hashlib.sha256(data).hexdigest(),status='completed'))
  self.m.db.session.flush()
 return _original_save(self,i,**kw)
identity.ReflectionIdentityTests.save=save_with_parent
checks=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(suite),unittest.defaultTestLoader.loadTestsFromModule(identity)])
result=unittest.TextTestRunner(verbosity=2).run(checks)
if not result.wasSuccessful():raise SystemExit(1)
if not a.browser:raise SystemExit(0)
C=suite.SavedPeriodTests;C.setUpClass();case=C('test_render_labels_actual_period_without_claiming_today_completed');case.setUp()
try:
 case.call(18,seed=True);pages={day:case.call(day,html=True) for day in (19,20)}
finally:case.tearDown();C.tearDownClass();C.doClassCleanups()
styles=['style.css','driving_reports.css','driving_workspace_ui.css']
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  if self.path.startswith('/fixture/'):
   day=int(self.path.rsplit('/',1)[1]);body=('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'+''.join('<link rel="stylesheet" href="/static/css/'+x+'">' for x in styles)+'<main class="driving-page" style="padding:16px">'+pages[day]+'</main><script src="/static/js/driving_reports.js"></script>').encode();mime='text/html'
  elif self.path in ['/static/css/'+x for x in styles]+['/static/js/driving_reports.js']:
   body=(r/self.path.lstrip('/')).read_bytes();mime='text/css' if self.path.endswith('.css') else 'text/javascript'
  else:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',51249),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
from playwright.sync_api import sync_playwright
report=[]
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True)
  for day in (19,20):
   for width in (320,390,1316):
    ctx=browser.new_context(viewport={'width':width,'height':900},service_workers='block');page=ctx.new_page();bad=[];posts=[]
    def deny_ws(ws):
     bad.append('websocket');ws.close()
    page.route_web_socket('**/*',deny_ws)
    def route(rt):
     u=rt.request.url
     if not u.startswith('http://127.0.0.1:51249/'):
      bad.append('nonloopback');rt.abort();return
     if '/safety/driving-reports/reflection' in u:
      posts.append(rt.request.method);rt.fulfill(status=202,content_type='application/json',body=json.dumps({'key':page.locator('[data-reflection]').get_attribute('data-key'),'status':'pending'}));return
     if rt.request.method!='GET':bad.append('unexpected-method');rt.abort();return
     rt.continue_()
    page.route('**/*',route);page.goto(f'http://127.0.0.1:51249/fixture/{day}');page.wait_for_timeout(100)
    label=page.locator('[data-reflection-snapshot-period]');assert label.is_visible() and label.inner_text()=='2026/11/01〜2026/11/18の分析'
    assert page.locator('[data-reflection]').get_attribute('data-status')=='new' and posts==[]
    assert page.locator('[data-reflection]').get_attribute('data-auto-refresh')=='false'
    links=page.locator('[data-analysis-destination]').evaluate_all('(xs)=>xs.map(x=>x.getAttribute("href"))');assert links and all('period=custom' in x for x in links)
    page.screenshot(path=str(out/f'{day}-{width}-saved.png'),full_page=True)
    page.locator('[data-reflection-form] button').click();page.wait_for_function('document.querySelector("[data-reflection-status]").textContent.includes("作成しています")')
    assert label.is_visible() and '11/18' in label.inner_text() and page.locator('.driving-finding').count()>0 and posts==['POST']
    page.screenshot(path=str(out/f'{day}-{width}-pending.png'),full_page=True);assert not bad
    report.append({'day':day,'width':width,'pending_period_retained':True,'auto_posts':0,'links':len(links),'external_requests':len(bad)});ctx.close()
  browser.close()
except BaseException as exc:
 # Fixed diagnostic strings only, not exception bodies or application data.
 report.append({'failed':True,'exception_type':type(exc).__name__,'external_requests':len(bad) if 'bad' in locals() else None})
 try:
  if 'page' in locals() and not page.is_closed():page.screenshot(path=str(out/'failure.png'),full_page=True)
 except Exception:pass
 raise
finally:
 server.shutdown();server.server_close()
 (out/'report.json').write_text(json.dumps(report,indent=2))
