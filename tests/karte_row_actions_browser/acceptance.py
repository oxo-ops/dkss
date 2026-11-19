"""Real Flask GET + native Chromium, disposable records; business POST forbidden."""
import os,sys,json,unittest,socket
from pathlib import Path
R=Path(os.environ.get('PRODUCT_REPO','.')).resolve()
sys.path[:0]=[str(R/'tests'),str(R)]
from test_demo_inspection_compact import CompactDemoTests
from playwright.sync_api import sync_playwright
class Rows(CompactDemoTests):
 def test_rows(self):
  self.enter();self.login('admin')
  with self.client.session_transaction() as s:s['demo_role_selected']=True
  m=self.models
  item=m.VehicleMaintenanceRecord(company_code='A',vehicle_record_id=self.vehicle_id,category='整備',status='整備中',entry_date='2026-11-18',content='前照灯・方向指示器・車幅灯の点灯確認',maintenance_company='点検記録を確認して対応する',created_by_username='admin')
  self.db.session.add(item);self.db.session.commit()
  from flask import url_for
  with self.app.test_request_context():home=url_for('vehicle_karte',vehicle_record_id=self.vehicle_id)
  out=Path(os.environ['ARTIFACTS']);out.mkdir(parents=True,exist_ok=True)
  blocked=[];cases=[];requests=[]
  saved=(item.content,item.status,item.entry_date)
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
   try:
    for width in [320,390,768,1440]:
     context=browser.new_context(viewport={'width':width,'height':900},service_workers='block');page=context.new_page()
     def serve(route):
      from urllib.parse import urlsplit
      req=route.request;u=urlsplit(req.url)
      if req.method!='GET' or u.netloc!='fixture.invalid':blocked.append(req.method+' '+req.url);route.abort();return
      requests.append(u.path)
      if u.path.endswith('/analysis/result'):
       route.fulfill(json={'ok':True,'has_result':True,'status':'completed','is_current':True,'analysis':{'recommendations':[{'proposal_id':'row-test','proposal_revision':'1','target':'タイヤの状態','action':'次の運行前に確認してください','priority':'中'}]}});return
      response=self.client.get(u.path+('?' +u.query if u.query else ''))
      route.fulfill(status=response.status_code,body=response.data,headers={k:v for k,v in response.headers if k.lower() not in ['content-length','set-cookie','content-encoding']})
     page.route('**/*',serve)
     def load():
      page.goto('https://fixture.invalid'+home);page.wait_for_selector('.ko-proposal-detail')
      if page.locator('#firstGuidePanel').is_visible():page.locator('[data-guide-close]').click()
     load()
     self.assertEqual(page.locator('.ko-confirmed-row .ko-action-button').count(),0)
     link=page.locator('.ko-confirmed-link').first;expected=link.get_attribute('href')
     for mode in ['click','Enter']:
      link=page.locator('.ko-confirmed-link').first;link.scroll_into_view_if_needed()
      if mode=='click':link.click()
      else:link.focus();page.keyboard.press('Enter')
      page.wait_for_url('**'+expected);load()
     proposal=page.locator('.ko-proposal-detail').first
     self.assertEqual(proposal.inner_text(),'');proposal.focus();page.keyboard.press('Enter');page.wait_for_url('**/analysis#proposal=row-test');load()
     plan=page.locator('.ko-plan-row').first
     for mode in ['click','Enter','Space']:
      plan.scroll_into_view_if_needed()
      if mode=='click':plan.click()
      else:plan.focus();page.keyboard.press(mode)
      page.locator('#inspection-plan-panel').wait_for(state='visible')
      self.assertTrue(page.locator('#inspection-plan-panel [data-plan-kind-label]').inner_text())
      page.keyboard.press('Escape');self.assertFalse(page.locator('#inspection-plan-panel').is_visible())
     for selector,key in [('.ko-confirmed-row','confirmed'),('.ko-proposal','proposal'),('.ko-appointments','plans')]:
      el=page.locator(selector).first;el.scroll_into_view_if_needed();box=el.bounding_box();self.assertGreaterEqual(box['height'],44);self.assertGreaterEqual(box['x'],-1);self.assertLessEqual(box['x']+box['width'],width+1)
      el.screenshot(path=str(out/f'{key}-{width}.png'))
     self.db.session.refresh(item);self.assertEqual((item.content,item.status,item.entry_date),saved)
     cases.append({'width':width,'native_click_enter_space':True,'original_links':True,'plan_dialog':True,'passed':True});context.close()
   finally:browser.close()
  self.assertEqual(blocked,[])
  (out/'report.json').write_text(json.dumps({'cases':cases,'blocked':blocked,'business_writes':False,'synthetic_analysis_response':True,'requests':requests},ensure_ascii=False,indent=2))
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Rows('test_rows')]));sys.exit(not result.wasSuccessful())
