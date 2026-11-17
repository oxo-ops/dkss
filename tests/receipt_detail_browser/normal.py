"""Unrun browser acceptance proposal; synthetic routes, product static JS."""
import argparse,hashlib,json,os
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parent;REPO=R.parents[1];ORIGIN='https://fixture.invalid'
def main():
 a=argparse.ArgumentParser();a.add_argument('--chromium',type=Path,required=True);args=a.parse_args()
 assert os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED')=='1'
 out=Path(os.environ['DKSS_BROWSER_ARTIFACT_DIR']);jobs=json.loads((R/'jobs.json').read_text());reports=[]
 code=(REPO/'static/js/document_import_queue.js').read_bytes()
 assert hashlib.sha256(code).hexdigest()==json.loads((R/'manifest.json').read_text())['candidate_sha256']
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=str(args.chromium),headless=True)
  try:
   for sequence in [[i] for i in range(6)]+[[0,1,4]]:
    for auto in (0,1):
     context=browser.new_context(viewport={'width':390,'height':568},service_workers='block');state={'calls':0,'blocked':[],'scripts':[],'preview':0}
     first=jobs[sequence[0]]['job'];last=jobs[sequence[-1]]['job'];receipt=first['page_url'];status=first['status_url'];preview=last['preview_url']
     should_nav=bool(auto and last['preview_ready'] and not last['failed'] and not last['needs_review'])
     def route(r):
      req=r.request;u=urlsplit(req.url)
      if u.scheme+'://'+u.netloc!=ORIGIN or req.method!='GET':state['blocked'].append(req.method+' '+u.path);r.abort();return
      if u.path==status:
       job=jobs[sequence[min(state['calls'],len(sequence)-1)]]['job'];state['calls']+=1;r.fulfill(content_type='application/json',body=json.dumps(job));return
      if u.path==receipt:r.fulfill(content_type='text/html',body=(R/'page.html').read_text().replace('data-auto-open="1"',f'data-auto-open="{auto}"'));return
      if preview and u.path==preview:state['preview']+=1;r.fulfill(content_type='text/html',body='<h1>Synthetic preview destination</h1>');return
      if u.path=='/static/js/document_import_queue.js':
       assert parse_qs(u.query)=={'v':['20261117-receipt-status-guard-1']};state['scripts'].append(req.url);r.fulfill(content_type='text/javascript',body=code);return
      if u.path.startswith('/static/'):
       f=(REPO/u.path.lstrip('/')).resolve()
       if f.is_relative_to((REPO/'static').resolve()) and f.is_file():r.fulfill(path=str(f));return
      state['blocked'].append(u.path);r.abort()
     context.route('**/*',route);context.route_web_socket('**/*',lambda ws:ws.close());page=context.new_page()
     try:
      page.goto(ORIGIN+receipt,wait_until='domcontentloaded')
      if should_nav:page.wait_for_url(ORIGIN+preview)
      else:
       expected=f"{last['completed']} / {last['total']}資料処理済み（成功 {last['succeeded']}・種類の確認 {last['needs_review']}・失敗 {last['failed']}）"
       page.wait_for_function('(a)=>document.getElementById("jobSummary").textContent===a.text && document.getElementById("jobFiles").firstElementChild.textContent.startsWith(a.filename)',arg={'text':expected,'filename':last['files'][0]['filename']})
       assert page.locator('#jobConnection').inner_text()==''
       assert page.get_by_role('button',name='この受付の状況を再確認').is_hidden()
       assert page.locator('#jobPreview').is_hidden()==(not last['preview_ready'])
       assert page.locator('#jobRetry').is_hidden()==(not bool(last['failed']))
       assert page.url==ORIGIN+receipt
      # Completed receipts must stay quiet beyond the normal 2-second interval.
      # Do not apply to active single-state fixtures, which should keep polling.
      if last['finished']:
       settled_calls=state['calls'];settled_preview=state['preview'];settled_url=page.url
       page.wait_for_timeout(2500)
       assert state['calls']==settled_calls, 'extra status GET after completion'
       assert state['preview']==settled_preview and page.url==settled_url, 'late navigation after completion'
      assert state['calls']==len(sequence) and state['preview']==int(should_nav)
      assert len(state['scripts'])==1 and not state['blocked']
      reports.append(dict(sequence=sequence,auto=auto,**state,cache_tested=False))
     except Exception:
      page.screenshot(path=str(out/f'normal-failure-{sequence}-{auto}.png'));raise
     finally:context.close()
  finally:browser.close();(out/'normal-report.json').write_text(json.dumps(reports,indent=2))
 assert len(reports)==14
if __name__=='__main__':main()
