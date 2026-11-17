"""Run only in permitted browser CI; routes all requests, never connects to a server."""
import argparse,json,os,subprocess
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parent;REPO=R.parents[1];ORIGIN='https://fixture.invalid'
def main():
 a=argparse.ArgumentParser();a.add_argument('--chromium',type=Path,required=True);args=a.parse_args();out=Path(os.environ['DKSS_BROWSER_ARTIFACT_DIR']);out.mkdir(parents=True,exist_ok=True)
 assert os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED')=='1'
 expected=os.environ['EXPECTED_HEAD'];actual=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip();assert actual==expected
 jobs=json.loads((R/'jobs.json').read_text());job=jobs[0]['job'];status=job['status_url'];receipt=job['page_url'];reports=[]
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=str(args.chromium),headless=True)
  try:
   for width in (320,390,1316):
    for mode in ('pending-headers','http-error','malformed','wrong-batch'):
     context=browser.new_context(viewport={'width':width,'height':568},service_workers='block');state={'mode':mode,'calls':0,'blocked':[],'held':[],'script_urls':[]}
     def bridge(route):
      req=route.request;u=urlsplit(req.url)
      if u.scheme+'://'+u.netloc!=ORIGIN or req.method!='GET':state['blocked'].append([req.method,u.path]);route.abort();return
      if u.path==status:
       state['calls']+=1;m=state['mode']
       if m=='pending-headers':state['held'].append(route);return
       if m=='http-error':route.fulfill(status=401,body='login');return
       if m=='malformed':route.fulfill(content_type='application/json',body='null');return
       data=json.loads(json.dumps(jobs[4]['job']))
       if m=='wrong-batch':data['batch_id']='00000000-0000-0000-0000-000000000000'
       route.fulfill(content_type='application/json',body=json.dumps(data));return
      if u.path==receipt:route.fulfill(content_type='text/html',body=(R/'page.html').read_text());return
      if u.path=='/static/js/document_import_queue.js':
       assert parse_qs(u.query)=={'v':['20261026-kind-recovery-1']},'script version URL mismatch'
       state['script_urls'].append(req.url)
       route.fulfill(content_type='text/javascript',body=(R/'candidate.js').read_text());return
      if u.path.startswith('/static/'):
       file=(REPO/u.path.lstrip('/')).resolve()
       if file.is_relative_to((REPO/'static').resolve()) and file.is_file():route.fulfill(path=str(file));return
      state['blocked'].append(['unexpected GET',u.path]);route.abort()
     context.route('**/*',bridge);context.route_web_socket('**/*',lambda ws:ws.close());page=context.new_page()
     page.add_init_script("document.addEventListener('submit',e=>{e.preventDefault();e.stopImmediatePropagation();window.__preventedPost=true},true)")
     try:
      page.goto(ORIGIN+receipt,wait_until='domcontentloaded');button=page.get_by_role('button',name='この受付の状況を再確認');button.wait_for(state='visible',timeout=18000)
      assert '確認できていません' in page.locator('#jobConnection').inner_text()
      assert page.locator('#jobRetry').is_hidden() and page.locator('#jobPreview').is_hidden()
      page.wait_for_timeout(2500) # Observe beyond the normal 2-second polling interval.
      assert state['calls']==1 # No auto retry after uncertain read.
      button.scroll_into_view_if_needed();geometry=button.evaluate('''e=>{const r=e.getBoundingClientRect();return {inside:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e}}''');assert geometry['inside'] and geometry['hit']
      # Reach via native Tab, not a synthetic button click only.
      page.locator('body').click(position={'x':2,'y':2});found=False
      for _ in range(30):
       page.keyboard.press('Tab')
       if button.evaluate('e=>e===document.activeElement'):found=True;break
      assert found
      state['mode']='good';page.keyboard.press('Enter');page.locator('#jobPreview').wait_for(state='visible');assert state['calls']==2
      assert page.url==ORIGIN+receipt # Recovery must not automatically navigate.
      assert not state['blocked'] and not page.evaluate('window.__preventedPost||false')
      page.screenshot(path=str(out/f'{width}-{mode}.png'))
      reports.append(dict(width=width,mode=mode,calls=state['calls'],geometry=geometry,keyboard=True,script_urls=state['script_urls'],cache_tested=False))
     except Exception as error:
      failure={'width':width,'mode':mode,'error':str(error),'calls':state['calls'],'blocked':state['blocked'],'script_urls':state['script_urls'],'url':page.url,'cache_tested':False}
      try:page.screenshot(path=str(out/f'failure-{width}-{mode}.png'));failure['screenshot']=f'failure-{width}-{mode}.png'
      except Exception as capture_error:failure['screenshot_error']=str(capture_error)
      (out/f'failure-{width}-{mode}.json').write_text(json.dumps(failure,indent=2))
      raise
     finally:context.close()
  finally:browser.close();(out/'browser-report.json').write_text(json.dumps(reports,indent=2))
if __name__=='__main__':main()
