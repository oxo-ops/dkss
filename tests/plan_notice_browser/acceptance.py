"""Real synthetic Flask planner: purpose controls remain clickable before selection."""
import argparse,json,os,sys,subprocess
from pathlib import Path
from urllib.parse import urlsplit
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--expected-sha',required=True);p.add_argument('--chromium');p.add_argument('--preflight-only',action='store_true');p.add_argument('--run-browser',action='store_true');a=p.parse_args()
assert os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED')=='1'
assert os.environ.get('DATABASE_URL')=='sqlite:///:memory:'
assert subprocess.check_output(['git','-C',str(a.repo),'rev-parse','HEAD'],text=True).strip()==a.expected_sha
sys.path[:0]=[str(a.repo),str(a.repo/'tests')]
from test_public_demo_workflow import DemoWorkflowTests
c=DemoWorkflowTests();c.setUpClass();c.setUp();c.app.config['PUBLIC_DEMO_SHARED_COMPANY']=True
out=a.artifacts;out.mkdir(parents=True,exist_ok=True);report={'sha':a.expected_sha,'fixture_only':True,'production_accessed':False,'cases':[],'passed':False};origin='http://127.0.0.1:8765';path='/vehicle/inspection-plans'
try:
 c.login('checker');r=c.request('GET',path);assert r.status_code==200 and b'public-demo-purpose-actions' in r.data
 if a.preflight_only:report['passed']=True
 else:
  from playwright.sync_api import sync_playwright
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=a.chromium,headless=True)
   try:
    for width in [320,390,500,700,768,1316]:
     for role in ['driver','manager']:
      transitions=[]
      c.login('checker');context=browser.new_context(viewport={'width':width,'height':900},service_workers='block')
      def bridge(route):
       req=route.request;u=urlsplit(req.url);assert u.scheme+'://'+u.netloc==origin
       assert req.method=='GET' or (req.method=='POST' and u.path=='/demo/role')
       kw={'data':req.post_data,'content_type':req.headers.get('content-type')} if req.method=='POST' else {}
       response=c.request(req.method,u.path+('?' + u.query if u.query else ''),**kw)
       if req.method=='POST':
        assert response.status_code==302
        target=response.headers['Location'];transitions.append(target)
        response=c.request('GET',target,follow_redirects=True)
       route.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() not in ('set-cookie','content-length','content-encoding')},body=response.data)
      context.route('**/*',bridge);page=context.new_page();page.goto(origin+path,wait_until='networkidle')
      close=page.locator('[data-guide-close]:visible')
      if close.count():close.click()
      page.locator('.public-demo-notice').wait_for()
      for val in ['driver','manager']:
       b=page.locator('.public-demo-notice button[value="'+val+'"]');assert b.is_visible();assert b.evaluate('e=>{const r=e.getBoundingClientRect(),h=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.height>=44&&(h===e||e.contains(h))}')
      if width<=700:
       assert page.locator('.public-demo-notice').bounding_box()['y']>=page.locator('.mobile-shell-title').bounding_box()['y']+page.locator('.mobile-shell-title').bounding_box()['height']-1
      page.screenshot(path=str(out/f'unselected-{width}-{role}.png'))
      page.locator('.public-demo-notice button[value="'+role+'"]').click()
      page.wait_for_url('**/demo/role')
      assert len(transitions)==1
      if role=='driver':assert urlsplit(transitions[0]).path.startswith('/vehicle/checklists')
      else:assert transitions[0]=='/?__aonagi_entry=1'
      page.goto(origin+path,wait_until='networkidle')
      close=page.locator('[data-guide-close]:visible')
      if close.count():close.click()
      assert page.locator('.public-demo-notice').count()==0
      if width<=700:assert page.locator('.mobile-shell-title').evaluate('e=>getComputedStyle(e).marginBottom')=='-56px'
      page.screenshot(path=str(out/f'selected-{width}-{role}.png'))
      for selector in ['[data-plan-view-toggle]','[data-plan-filter-toggle]','[data-plan-search-toggle]']:
       b=page.locator(selector)
       if width>700:
        assert not b.is_visible();continue
       b.wait_for(state='visible');b.click(trial=True)
      if width>700:
       assert page.locator('[data-plan-filters]').is_visible()
       assert page.locator('[data-plan-filters] input[name="q"]').is_visible()
      page.screenshot(path=str(out/f'selected-{width}-{role}.png'));report['cases'].append({'width':width,'role':role,'purpose_native_click':True,'purpose_destination_preserved':True,'selected_plan_revisit':True});context.close()
    report['passed']=True
   finally:browser.close()
finally:
 (out/'report.json').write_text(json.dumps(report,indent=2));c.tearDown();c.tearDownClass()
