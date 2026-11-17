import sys,os,json
from pathlib import Path
root=Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
assert os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED')=='1'
assert Path(sys.modules['sitecustomize'].ROOT)==root
for event,args,expected in [('socket.connect',(None,('invalid.example',443)),'BROWSER_ACCEPTANCE_PYTHON_NETWORK_FORBIDDEN'),('sqlite3.connect',('file:forbidden',),'BROWSER_ACCEPTANCE_EXISTING_DATABASE_FORBIDDEN')]:
 try:sys.audit(event,*args)
 except RuntimeError as e:assert str(e)==expected
 else:raise AssertionError('isolation guard inactive')
repo=Path(sys.argv[1]);sys.path[:0]=[str(repo),str(repo/'tests')]
import hashlib,subprocess,re
expected_sha=os.environ.get('DKSS_EXPECTED_SHA','')
assert re.fullmatch('[0-9a-f]{40}',expected_sha),'exact committed candidate SHA required'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==expected_sha
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip(),'candidate must be clean'
out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
manifest=json.loads((Path(__file__).parent.parent/'browser-source-manifest.json').read_text())
for f,h in manifest.items():assert hashlib.sha256((repo/f).read_bytes()).hexdigest()==h, f
from test_driving_report_management import DrivingReportManagementTests as Base
from driving_report_data import payload,version
from html.parser import HTMLParser
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
from io import BytesIO
class Token(HTMLParser):
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if tag=='input' and d.get('name')=='csrf_token':self.value=d['value']
class Fixture(Base):pass
from urllib.parse import urlsplit
import hashlib,subprocess,re
from playwright.sync_api import sync_playwright,expect
case=Fixture();case.setUpClass();results=[];blocked=[]
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path=os.environ.get('DKSS_CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-background-networking'])
  try:
   for width in [390,1316]:
    for scene in ['success','conflict','csrf','expired','network-before','network-after','wrong-record']:
     with case.m.app.app_context():
      dburl=case.m.db.engine.url;assert dburl.drivername=='sqlite' and Path(dburl.database).resolve().is_relative_to(root)
     case.setUp();context=None;page=None
     try:
      row=case.imported();assert row.company_code=='TEST' and case.vehicle.chassis_number=='TEST-001'
      path=f'/safety/driving-reports/{row.id}';before=row.details_json;expected='\n架空指導文 <>& コピー対象';counts={'post':0,'get':0};assets=set()
      case.m.app.config['WTF_CSRF_ENABLED']=True
      context=browser.new_context(viewport={'width':width,'height':850},service_workers='block')
      def bridge(route):
       req=route.request;u=urlsplit(req.url)
       def deny(reason):blocked.append({'scene':scene,'reason':reason,'method':req.method,'path':u.path,'post_count':counts['post']});route.abort()
       if u.scheme!='http' or u.netloc!='localhost:8765':return deny('external origin')
       if req.method=='POST':
        if u.path!=path+'/review' or u.query or counts['post']:return deny('unexpected/repeated POST')
        counts['post']+=1
        raw=req.post_data_buffer or b'';ctype=req.headers.get('content-type','')
        if len(raw)>80000:return deny('body size')
        parsed=Request.from_values(method='POST',input_stream=BytesIO(raw),content_length=len(raw),content_type=ctype)
        allowed={'state','assignee','next_date','outcome','comparison_note','note','action','driver_explanation','csrf_token','version','return_to'}
        if parsed.files or not set(parsed.form)<=allowed or any(len(parsed.form.getlist(k))!=1 for k in parsed.form):return deny('fields')
        if parsed.form.get('note','').replace('\r\n','\n')!=expected or parsed.form.get('state')!='followup' or parsed.form.get('assignee'):return deny('non-synthetic')
        if req.headers.get('x-dkss-review-inplace')!='1':return deny('missing receipt request')
        if scene=='network-before':route.abort();return
        res=case.client.open(path+'/review',method='POST',data=raw,content_type=ctype,headers={'X-DKSS-Review-Inplace':'1'},follow_redirects=False)
        if scene in ['success','network-after','wrong-record']:
         assert res.status_code==200 and res.headers.get('X-DKSS-Review-Saved')=='1' and res.json['saved'] is True
        elif scene=='csrf':assert res.status_code==400
        elif scene=='conflict':assert res.status_code==409
        elif scene=='expired':assert res.status_code==302 and urlsplit(res.headers['Location']).path=='/login'
        if scene=='network-after':route.abort();return
        if scene=='wrong-record':
         route.fulfill(status=200,headers={'Content-Type':'application/json','X-DKSS-Review-Saved':'1'},body=json.dumps({'saved':True,'detail_url':'/safety/driving-reports/999999'}));return
       elif req.method=='GET':
        if u.path==path:counts['get']+=1
        elif u.path.startswith('/static/') and not u.path.startswith(('/static/uploads/','/static/manuals/')):assets.add(u.path)
        elif u.path not in ['/login','/api/notifications/unread-count','/api/notifications/recent','/api/push/vapid-public-key','/favicon.ico']:return deny('GET path')
        res=case.client.get(u.path+('?' +u.query if u.query else ''),follow_redirects=False)
       else:return deny('method')
       headers={k:v for k,v in res.headers if k.lower() not in ['set-cookie','content-length','content-encoding']}
       route.fulfill(status=res.status_code,headers=headers,body=res.data)
      def block_ws(ws):
       blocked.append({'scene':scene,'reason':'websocket forbidden'});ws.close()
      context.route_web_socket('**/*',block_ws)
      context.route('**/*',bridge);page=context.new_page();page.goto('http://localhost:8765'+path,wait_until='networkidle')
      page.locator('#report-review').evaluate('(el)=>el.open=true')
      form=page.locator('form[data-review-inplace]');form.locator('[name=note]').fill(expected);form.locator('[name=state]').select_option('followup')
      if scene=='conflict':form.locator('[name=version]').evaluate('(el)=>el.value="stale"')
      if scene=='csrf':form.locator('[name=csrf_token]').evaluate('(el)=>el.value="invalid-synthetic"')
      if scene=='expired':
       with case.client.session_transaction() as session:session.clear()
      form.evaluate('(f)=>{f.requestSubmit();f.requestSubmit()}')
      if scene=='success':
       expect(page.locator('form[data-review-inplace] textarea[name=note]')).to_have_value(expected.strip())
       assert urlsplit(page.url).path==path and counts['get']>=2
      else:
       page.locator('[data-review-recovery]').wait_for(state='visible')
       assert urlsplit(page.url).path==path
       assert form.locator('[name=note]').input_value()==expected
       assert form.locator('[name=note]').evaluate('(e)=>!e.readOnly')
       assert form.locator('[name=state]').is_enabled()
       assert form.locator('button[type=submit]').is_disabled()
       link=form.locator('[data-review-recovery] a');assert link.get_attribute('href')==path and link.get_attribute('target')=='_blank' and 'noopener' in link.get_attribute('rel')
       if scene in ['network-before','network-after','expired']:assert '保存結果を確認できません' in page.locator('[data-review-status]').inner_text()
       form.evaluate('(f)=>f.requestSubmit()');page.wait_for_timeout(50)
      assert counts['post']==1 and not blocked
      case.m.db.session.refresh(row);saved=scene in ['success','network-after','wrong-record'];assert (payload(row).get('review',{}).get('note')==expected.strip())==saved
      if not saved:assert row.details_json==before
      assert '/static/js/base.js' in assets and '/static/js/driving_report_detail.js' in assets
      assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
      page.screenshot(path=str(out/f'{width}-{scene}.png'),full_page=True)
      results.append({'width':width,'scene':scene,'post_count':counts['post'],'saved':saved,'base_js_loaded':True})
     except Exception as error:
      failure={'width':width,'scene':scene,'error_type':type(error).__name__,'error':str(error)}
      if page:
       try:page.screenshot(path=str(out/f'{width}-{scene}-FAILED.png'),full_page=True)
       except Exception:failure['screenshot_failed']=True
      results.append(failure);raise
     finally:
      if context:context.close()
      case.m.app.config['WTF_CSRF_ENABLED']=False;case.doCleanups();case.tearDown()
  finally:browser.close()
finally:
 case.tearDownClass();(out/'report.json').write_text(json.dumps({'cases':results,'blocked':blocked,'browser_executed':bool(results),'product_manifest':manifest},indent=2))
print('14 browser bridge cases passed')
