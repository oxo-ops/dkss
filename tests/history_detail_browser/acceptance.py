"""Read-only synthetic history -> maintenance detail browser acceptance."""
import os,sys,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from test_vehicle_history_categories import HistoryCategoryTests
assert os.environ['DKSS_BROWSER_ACCEPTANCE_ISOLATED']=='1'
output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
case=HistoryCategoryTests();case.setUpClass();report=[]
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch()
  try:
   for width in (390,1316):
    case.setUp()
    try:
     m=case.m;r=m.VehicleMaintenanceRecord(company_code='TEST',vehicle_record_id=case.vehicle.id,content='History detail fixture',category='整備',status='完了',total_cost=1234,invoice_details_json='{"source":{"draft_id":"history-fixture-source"}}')
     m.db.session.add(r);m.db.session.commit();before=m.VehicleMaintenanceRecord.query.count()
     context=browser.new_context(viewport={'width':width,'height':844},service_workers='block');requests=[]
     def route(req):
      u=urlsplit(req.request.url)
      assert u.netloc=='fixture.test' and req.request.method=='GET', 'unexpected external/write request'
      assert u.path.startswith(('/vehicle/karte/','/master/vehicles/','/static/','/api/notifications/','/api/push/')),u.path
      response=case.client.get(u.path+('?' + u.query if u.query else ''))
      requests.append([u.path,response.status_code])
      req.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding','set-cookie')},body=response.data)
     context.route('**/*',route);page=context.new_page()
     url=f'http://fixture.test/vehicle/karte/{case.vehicle.id}/history?category=maintenance'
     page.goto(url,wait_until='networkidle')
     guide=page.get_by_role('button',name='操作ガイドを閉じる',exact=True)
     if guide.is_visible():guide.click()
     page.get_by_role('link',name='History detail fixture',exact=True).filter(visible=True).click()
     page.wait_for_url(f'**/maintenance/{r.id}#maintenance_detail_panel')
     assert page.locator('#maintenance_detail_panel').is_visible()
     assert page.locator('#maintenance_detail_panel').inner_text().find('History detail fixture')>=0
     assert not any('/source' in path for path,status in requests)
     page.screenshot(path=str(output/f'history-detail-{width}.png'),full_page=True)
     page.go_back(wait_until='networkidle');assert 'category=maintenance' in page.url
     assert m.VehicleMaintenanceRecord.query.count()==before
     report.append({'width':width,'passed':True,'requests':requests,'business_writes':False});context.close()
    finally:case.tearDown()
  finally:browser.close()
finally:
 case.tearDownClass();(output/'report.json').write_text(json.dumps(report,indent=2))
