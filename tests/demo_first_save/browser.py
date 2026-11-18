"""Actual product page, synthetic Flask client and files only; no external transport."""
import os,sys,json,subprocess,io,base64
from pathlib import Path
from urllib.parse import urlsplit
REPO=Path(os.environ['DEMO_CANDIDATE_REPO']).resolve()
assert subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip()==os.environ['EXPECTED_HEAD']
assert not subprocess.check_output(['git','-C',str(REPO),'status','--porcelain'],text=True).strip()
import sitecustomize
assert sitecustomize.ROOT==Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
from test_http import HTTP
from playwright.sync_api import sync_playwright
OUT=Path(os.environ['ARTIFACTS']);OUT.mkdir(parents=True,exist_ok=True)
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=')
report={'head':os.environ['EXPECTED_HEAD'],'cases':[],'live':False}
HTTP.setUpClass()
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True)
  try:
   for width in (390,1316):
    case=HTTP();case.setUp();ctx=browser.new_context(viewport={'width':width,'height':850},service_workers='block');posts=[];blocked=[];page=ctx.new_page()
    try:
     token,csrf=case.setup_page();url=case.url+'?vehicle_record_id='+str(case.vehicle_id)+'&year=2026&month=10&active_day=23'
     def route(r):
      q=r.request;u=urlsplit(q.url)
      if u.scheme!='https' or u.netloc!='fixture.invalid' or q.method not in {'GET','POST'}:blocked.append(q.url);r.abort();return
      path=u.path+('?' +u.query if u.query else '')
      if q.method=='POST':
       assert u.path==case.url+'/save-detail' and len(posts)==0
       data=q.post_data_buffer or b'';assert PNG in data and b'synthetic.png' in data
       posts.append(u.path)
       response=case.client.open(path,method='POST',data=data,content_type=q.headers.get('content-type'),headers={k:v for k,v in q.headers.items() if k.lower().startswith('x-dkss-')})
       assert response.status_code==200 and response.json['saved'] is False and response.json['preserved'] is True
      else:response=case.client.get(path)
      assert response.status_code!=302,'native redirect must be explicitly handled'
      r.fulfill(status=response.status_code,headers=dict(response.headers),body=response.get_data())
     ctx.route('**/*',route)
     ctx.route_web_socket('**/*',lambda ws:(blocked.append(ws.url),ws.close()))
     page.goto('https://fixture.invalid'+url,wait_until='networkidle')
     # Optional real guide can be closed through its existing control, never force-clicked.
     guide=page.locator('#firstGuidePanel')
     if guide.count() and guide.is_visible():
      close=guide.locator('[data-guide-close]')
      if close.count():close.click()
     details=page.locator('#vehicle-inspection-record')
     if details.count() and details.get_attribute('open') is None:details.locator('summary').click()
     page.locator('.inspection-item-detail').first.click()
     modal=page.locator('#detailModal');assert modal.is_visible()
     modal.locator('#detailCommentEditor').fill('synthetic unsaved draft')
     file_input=modal.locator('input[type=file][multiple]').element_handle()
     file_input.set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':PNG})
     first=case.client.post(case.url+'/save-one',data={**case.params,'item_no':'0','value':'×','csrf_token':csrf},headers={'X-DKSS-Validation-Only':'1','X-DKSS-Demo-Snapshot':token});assert first.json['saved'] is True
     before=case.models.VehicleChecklistResult.query.one().answers_json
     before_url=page.url
     assert urlsplit(before_url).netloc=='fixture.invalid'
     document_id=page.evaluate('()=>{window.__syntheticDocumentId=crypto.randomUUID();return window.__syntheticDocumentId}')
     modal.get_by_role('button',name='保存',exact=True).click()
     notice=page.locator('#demoInspectionPreserved');notice.wait_for(state='visible')
     assert page.url==before_url, (before_url,page.url)
     assert page.evaluate('window.__syntheticDocumentId')==document_id
     assert modal.locator('#detailCommentEditor').inner_text()=='synthetic unsaved draft'
     assert file_input.evaluate('(el)=>el.isConnected && el.files.length===1 && el.files[0].name==="synthetic.png"')
     assert file_input.evaluate('async(el)=>Array.from(new Uint8Array(await el.files[0].arrayBuffer()))')==list(PNG)
     link=notice.get_by_role('link');assert link.get_attribute('target')=='_blank' and link.get_attribute('rel')=='noopener'
     modal.get_by_role('button',name='保存',exact=True).click();page.wait_for_timeout(100);assert len(posts)==1
     assert case.models.VehicleChecklistResult.query.one().answers_json==before and not blocked
     page.screenshot(path=str(OUT/f'{width}-preserved.png'),full_page=True)
     report['cases'].append({'width':width,'passed':True,'posts':len(posts),'file_count':1,'before_url':before_url,'after_url':page.url,'same_document':True})
    except BaseException as error:
     report['cases'].append({'width':width,'passed':False,'error_type':type(error).__name__,'error':str(error),'posts':posts,'blocked':blocked,'url':page.url,'before_url':locals().get('before_url')})
     try:page.screenshot(path=str(OUT/f'{width}-FAILED.png'),full_page=True)
     except BaseException:pass
     raise
    finally:ctx.close();case.tearDown();case.doCleanups()
  finally:browser.close()
finally:HTTP.tearDownClass();(OUT/'report.json').write_text(json.dumps(report,indent=2))
