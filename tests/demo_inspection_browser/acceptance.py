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
 return {'items':[(r.id,r.items_json) for r in case.models.Checklist.query.order_by(case.models.Checklist.id).all()], 'results':[(r.id,r.answers_json) for r in case.models.VehicleChecklistResult.query.order_by(case.models.VehicleChecklistResult.id).all()]}
def setup():
 case.setUp();return f'/vehicle/checklists/{case.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}?vehicle_record_id={case.vehicle_id}'
def cleanup():
 case.tearDown();case.doCleanups()
try:
 if a.preflight_only:
  for role in ('driver','manager'):
   target=setup()
   try:
    token,html=case.enter();before=snapshot();assert target in html
    response=case.client.post('/demo/role',data={'role':role,'csrf_token':token});assert response.status_code==302 and response.location=='/'
    assert 'class="alert public-demo-notice"' not in case.client.get('/').get_data(as_text=True)
    text=case.client.get(target).get_data(as_text=True);assert 'エンジンのかかり具合、異音' in text and 'criteria-line-pre' in text
    assert snapshot()==before
    from html.parser import HTMLParser
    class Controls(HTMLParser):
     def __init__(self):super().__init__();self.stack=[];self.buttons=[];self.files=[];self.forms=[]
     def handle_starttag(self,tag,attrs):
      at=dict(attrs);cl=at.get('class','').split()
      assert not {'mobile-detail-cell','mobile-detail-header','desktop-detail-button'}.intersection(cl)
      if 'inspection-item-detail' in cl:
       assert tag=='button' and at['type']=='button' and at['aria-controls']=='detailModal'
       assert not any(t=='form' for t,_ in self.stack)
       assert self.stack[-1][0]=='td' and self.stack[-1][1].get('class')=='fixed-item'
       assert at.get('data-day');self.buttons.append(at)
      if tag=='form':self.forms.append(at)
      if tag=='input' and at.get('type')=='file':self.files.append(at)
      if tag not in {'input','br','img','meta','link','hr','source','wbr'}:self.stack.append((tag,at))
     def handle_endtag(self,tag):
      for index in range(len(self.stack)-1,-1,-1):
       if self.stack[index][0]==tag:self.stack=self.stack[:index];break
    parsed=Controls();parsed.feed(text)
    assert len(parsed.buttons)==29
    assert any(f.get('enctype')=='multipart/form-data' and f.get('action','').endswith('/save-detail') for f in parsed.forms)
    assert any(f.get('capture')=='environment' for f in parsed.files)
    assert any('multiple' in f for f in parsed.files)
    assert '<label>写真・ファイル</label>' not in text
    assert 'file-upload-button-camera' in text and 'file-upload-button-secondary' in text
    from threading import Thread
    threaded=[]
    def check_thread():
     try:threaded.append(case.client.get(target).status_code)
     except BaseException as error:threaded.append(type(error).__name__)
    thread=Thread(target=check_thread);thread.start();thread.join(timeout=10)
    assert threaded==[200],threaded
    report['cases'].append({'role':role,'status':'preflight-passed'})
   finally:cleanup()
 else:
  assert a.run_browser and a.chromium
  from playwright.sync_api import sync_playwright
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=a.chromium,headless=True)
   report['browser_started']=True
   try:
    for width in (320,390,768,1316):
     for role in ('driver','manager'):
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
      record={'width':width,'role':role,'status':'running'};report['cases'].append(record)
      try:
       page.goto(origin+'/demo',wait_until='networkidle');assert page.locator('.public-demo-notice').is_visible()
       entry_url=urlsplit(page.get_by_role('link',name='日常点検を開く',exact=True).get_attribute('href')); expected_entry=urlsplit(target)
       assert entry_url.path==expected_entry.path and parse_qs(entry_url.query)=={**parse_qs(expected_entry.query),'__aonagi_entry':['1']}
       page.screenshot(path=str(out/f'{width}-{role}-entry.png'),full_page=True)
       page.locator(f'form[action="/demo/role"] button[name="role"][value="{role}"]').click()
       page.wait_for_url(lambda u:urlsplit(u).path=='/' and parse_qs(urlsplit(u).query)=={'__aonagi_entry':['1']});page.wait_for_load_state('networkidle')
       assert post_count[0]==1 and page.locator('.public-demo-notice').count()==0
       with case.client.session_transaction() as s:assert s['demo_role_selected'] is True and s['demo_role']==role
       toolbar=page.locator('.top-bar');help_button=toolbar.locator('[data-guide-open]');user=toolbar.locator('.top-bar-user')
       assert help_button.is_visible() and user.is_visible()
       hb=help_button.bounding_box();ub=user.bounding_box()
       assert hb['x']+hb['width']<=ub['x']+1 or ub['x']+ub['width']<=hb['x']+1 or hb['y']+hb['height']<=ub['y']+1 or ub['y']+ub['height']<=hb['y']+1,(hb,ub)
       assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
       title=page.locator('.dashboard-header')
       if title.count():
        tb=toolbar.bounding_box();db=title.bounding_box();assert tb['y']+tb['height']<=db['y']+1,(tb,db)
       page.screenshot(path=str(out/f'{width}-{role}-home.png'),full_page=True)
       page.goto(origin+target,wait_until='networkidle');assert page.locator('#vehicle_workspace_date').is_visible()
       assert page.locator('.public-demo-notice').count()==0
       assert page.locator('#vehicle_check_filter [name="vehicle_record_id"]').input_value()==str(case.vehicle_id)
       table=page.locator('.vehicle-standard-daily-table .monthly-check-table').first
       assert table.is_visible();assert 'エンジンのかかり具合、異音' in table.inner_text()
       all_items=json.loads(before['items'][0][1])
       original=[i['content'] for i in all_items if i.get('item_type')=='check' and str(i.get('item_code','')).startswith('daily_')]
       footer=[i['content'] for i in all_items if i.get('item_type')=='check' and not str(i.get('item_code','')).startswith('daily_')]
       assert len(original)==27,len(original)
       rendered=table.locator('.js-open-detail').evaluate_all('(es)=>es.map(e=>e.dataset.content)')
       assert all(value in rendered for value in original+footer),'original detail text lost'
       record['original_item_count']=len(original)
       record['footer_item_count']=len(footer)
       assert page.locator('.criteria-box').count()==page.locator('#detailModal .criteria-box').count()==1,'standard common notes still above table or modal criteria missing'
       assert page.locator('#detailCriteriaText').count()==1
       assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
       if width<=768:
        cells=table.locator('.fixed-item');visible=[c for c in cells.all() if c.is_visible()];assert visible
        row=next(c.locator('..') for c in visible if 'エンジンのかかり具合' in c.inner_text())
        boxes={k:row.locator(sel).bounding_box() for k,sel in [('item','.fixed-item'),('category','.fixed-category'),('current','.mobile-current-date')]}
        assert boxes['item']['width']>boxes['current']['width'],boxes
        choices=row.locator('.mobile-current-date .check-choice-button');assert choices.count()==2
        for control in choices.all():
         b=control.bounding_box();assert b['width']>=35.5 and b['height']>=43.5,b
        detail=row.locator('.inspection-item-detail')
        assert all(b['width']>=43.5 and b['height']>=43.5 for b in [detail.bounding_box()])
        for d in table.locator('th.mobile-current-date .mobile-date-label').all():
         if d.is_visible():assert d.inner_text().strip().endswith('日') and d.inner_text().strip()[:-1].isdigit(),d.inner_text()
        for header in table.locator('th.mobile-previous-date, th.mobile-current-date').all():
         if header.is_visible():
          assert header.evaluate('(e)=>{const r=document.createRange();r.selectNodeContents(e);const t=r.getBoundingClientRect(),b=e.getBoundingClientRect();return t.left>=b.left-1&&t.right<=b.right+1}'),header.inner_text()
        wrapper=page.locator('.vehicle-check-table-scroll.vehicle-standard-daily-table').first
        assert wrapper.evaluate('(e)=>{const a=e.getBoundingClientRect(),b=e.parentElement.getBoundingClientRect();return a.left>=b.left-1&&a.right<=b.right+1}')
        record['columns']=boxes
       else:detail=next(x for x in table.locator('.inspection-item-detail').all() if x.is_visible())
       page.screenshot(path=str(out/f'{width}-{role}-inspection.png'),full_page=True)
       assert table.locator('.mobile-detail-cell, .mobile-detail-header, .desktop-detail-button').count()==0
       assert detail.get_attribute('type')=='button' and detail.locator('xpath=ancestor::form').count()==0
       assert 'underline' not in detail.evaluate('(e)=>getComputedStyle(e).textDecorationLine')
       detail.focus();detail.press('Enter');assert page.locator('#detailModal').is_visible()
       page.locator('#detailModal .js-close-detail-modal').click()
       detail.focus();detail.press('Space');assert page.locator('#detailModal').is_visible()
       page.locator('#detailModal .js-close-detail-modal').click()
       detail.click();assert page.locator('#detailModal').is_visible();assert page.locator('#detailTitle').inner_text().strip()
       modal=page.locator('#detailModal')
       save=modal.get_by_role('button',name='保存',exact=True);close=modal.get_by_role('button',name='閉じる',exact=True)
       sb=save.bounding_box();cb=close.bounding_box()
       assert abs(sb['width']-cb['width'])<1 and abs(sb['height']-cb['height'])<1 and sb['height']>=44,(sb,cb)
       for control in modal.locator('.file-upload-button').all():
        box=control.bounding_box();assert box['height']>=44
        assert control.evaluate('(e)=>getComputedStyle(e).borderRadius')==save.evaluate('(e)=>getComputedStyle(e).borderRadius')
       upload_boxes=[x.bounding_box() for x in modal.locator('.file-upload-button').all()]
       assert len(upload_boxes)==2 and abs(upload_boxes[0]['y']-upload_boxes[1]['y'])<1 and abs(upload_boxes[0]['width']-upload_boxes[1]['width'])<1,upload_boxes
       assert save.is_enabled()
       assert modal.locator('input[type=file][capture=environment]').count()==1
       assert modal.locator('input[type=file][multiple]').count()==1
       assert modal.locator('form').get_attribute('action').endswith('/save-detail')
       page.screenshot(path=str(out/f'{width}-{role}-detail.png'),full_page=True)
       page.locator('#detailModal .js-close-detail-modal').click();assert not page.locator('#detailModal').is_visible()
       expected_conditions={
        'daily_02': (),
        'daily_17': ('走行距離・運行時の状態などに応じた適切な時期に点検。',),
        'daily_01': ('走行距離・運行時の状態などに応じた適切な時期に点検。',),
        'daily_04': ('エアブレーキ装着車が対象。',),
        'daily_18': ('車両総重量8t以上、または乗車定員30人以上の車両が対象。',),
        'daily_20': ('走行距離・運行時の状態などに応じた適切な時期に点検。','エアブレーキ装着車が対象。')}
       record['row_criteria']=[]
       for code,conditions in expected_conditions.items():
        item=next(i for i in all_items if i.get('item_code')==code)
        buttons=table.locator('.js-open-detail').all()
        button=next(b for b in buttons if b.is_visible() and b.get_attribute('data-content')==item['content'])
        expected='\n'.join(('✓ 正常 / × 異常',)+conditions)
        assert button.get_attribute('data-criteria')==item['criteria'],'raw criteria attribute changed'
        assert button.get_attribute('data-criteria-display')==expected,(code,button.get_attribute('data-criteria-display'))
        button.click();modal=page.locator('#detailModal');assert modal.is_visible()
        assert page.locator('#detailTitle').text_content().strip()==item['content'].strip()
        assert page.locator('#detailCriteriaText').inner_text()==expected
        assert page.locator('#detailCriteria').input_value()==item['criteria'],'raw criteria submitted field changed'
        editor=page.locator('#detailCommentEditor');assert editor.is_visible() and editor.get_attribute('contenteditable')=='true'
        assert modal.locator('input[type=file][name=files]').count()==2
        assert modal.get_by_role('button',name='保存',exact=True).is_visible()
        box=modal.locator('.modal-box').bounding_box();assert box and box['x']>=0 and box['x']+box['width']<=width+1
        page.screenshot(path=str(out/f'{width}-{role}-{code}.png'),full_page=True)
        page.locator('#detailModal .js-close-detail-modal').click();assert not modal.is_visible()
        record['row_criteria'].append({'code':code,'display':expected,'raw_preserved':True})
       assert snapshot()==before,'inspection data changed'
       page.goto(origin+'/demo',wait_until='networkidle');assert page.locator('.public-demo-notice').is_visible()
       assert not errors,errors;assert not report['blocked'],report['blocked']
       record.update(status='passed',requests=requests,inspection_unchanged=True)
      except BaseException as error:
       record.update(status='failed',error_type=type(error).__name__,error=str(error),requests=requests,page_errors=errors)
       try:page.screenshot(path=str(out/f'{width}-{role}-FAILED.png'),full_page=True)
       except BaseException as capture:record['capture_error']=type(capture).__name__
       raise
      finally:ctx.close();server.shutdown();server.server_close();server_thread.join(timeout=5);cleanup()
   finally:browser.close()
finally:
 case.tearDownClass();(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print('PASS',len(report['cases']),'synthetic cases; real device and visual acceptance remain')
