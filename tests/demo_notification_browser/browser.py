"""Synthetic real-route snapshots only; every external/write request blocked."""
import os,json
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(os.environ['PRODUCT_REPO']);html=Path(os.environ['HTML_OUT']);out=Path(os.environ['ARTIFACTS']);out.mkdir(parents=True,exist_ok=True)
report=[]
with sync_playwright() as p:
 b=p.chromium.launch()
 try:
  for width in (390,1316):
   for mode in ('demo','normal'):
    c=b.new_context(viewport={'width':width,'height':900},service_workers='block');blocked=[]
    def route(r):
     from urllib.parse import urlparse
     u=urlparse(r.request.url)
     if u.netloc!='fixture.invalid' or r.request.method!='GET':
      blocked.append(r.request.method+' '+u.netloc);r.abort();return
     if u.path=='/notifications':r.fulfill(content_type='text/html',body=(html/f'{mode}-list.html').read_text());return
     if u.path.startswith('/notifications/'):
      nid=int(u.path.rsplit('/',1)[1]);r.fulfill(json={'html':(html/f'{mode}-{nid}.html').read_text(),'notification_id':nid,'read':True,'deleted':False});return
     f=root/u.path.lstrip('/')
     if u.path.startswith('/static/') and f.is_file():r.fulfill(path=str(f));return
     if u.path=='/api/notifications/unread-count':r.fulfill(json={'count':0});return
     r.fulfill(status=404,body='offline fixture')
    c.route('**/*',route);page=c.new_page();page.goto('https://fixture.invalid/notifications')
    for nid in (259,262,264,282):
     page.locator(f'[data-notification-id="{nid}"] .notification-item').click()
     pane=page.locator('.dkss-notification-detail');pane.wait_for()
     body=pane.inner_text()
     assert ('【体験用・架空】' in body or '【架空・通し検証' in body)==(mode=='normal'),(width,mode,nid,body)
     disclosure=pane.locator('details').filter(has=page.get_by_text('詳細を見る',exact=True))
     if disclosure.count():disclosure.locator('summary').click()
     assert not page.locator('.swal2-popup').count()
     page.screenshot(path=str(out/f'{mode}-{width}-{nid}.png'),full_page=True)
     pane.locator('.nd-close').click();pane.wait_for(state='hidden')
    assert not blocked,blocked
    report.append({'mode':mode,'width':width,'rows':4,'nativeOpenClose':True,'postCount':0,'passed':True});c.close()
 finally:b.close()
(out/'report.json').write_text(json.dumps(report,indent=2))
