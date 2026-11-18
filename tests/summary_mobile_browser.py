"""Isolated synthetic UI check. No service, account, DB or network access."""
from pathlib import Path
from types import SimpleNamespace as NS
import argparse,json
from jinja2 import Environment
from playwright.sync_api import sync_playwright
p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--output',required=True);args=p.parse_args()
r=Path(args.root);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
s=(r/'templates/index.html').read_text();start=s.index('                <div class="dashboard-analysis-targets">');end=s.index('                </section>',start)+len('                </section>')
item=NS(id=1,target='車両管理',name='日常点検表',frequency_unit='day',display_type='month',history=NS(total=7,rows=[NS(date='2026-11-18',target='体験車両101',score=82,status='点検完了',url='/vehicle/checklists/1') for _ in range(7)]))
target=NS(target_label='体験車両101',count=12,average_score=82,review_items=['エンジンのかかり具合・低速、加速の状態','ウィンドウォッシャー液量・噴射状態'],vehicle_record_id=1,year=2026,month=11,day=18)
body=Environment(autoescape=True).from_string(s[start:end]).render(item=item,visible_targets=NS(items=[target]*3))
css='\n'.join((r/'static/css'/f).read_text() for f in ['style.css','responsive_layout.css','dashboard_mobile_refinement.css','dashboard_summary_mobile.css','notifications_dashboard.css'])
notification='<div class="page-header notification-page-header"><div class="notification-heading"><h2>通知</h2></div><div class="header-actions"><form><button id="notificationReadAllButton">すべて既読（12件）</button></form><a class="notification-page-close">閉じる</a></div></div><div id="notificationLayout"></div>'
html=f'<html lang="ja"><meta charset="utf-8"><style>{css}</style><body data-responsive-shell><main class="main-content" style="margin:0;padding:12px"><div class="dashboard-page dashboard-design-v2"><div class="dashboard-analysis-card">{body}</div></div>{notification}</main></body></html>'
results=[]
with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in [320,375,390,430,768,1280]:
  page=browser.new_page(viewport={'width':width,'height':900})
  page.route('**/*',lambda route: route.abort())
  page.set_content(html)
  if width<=640:
   for sel in ['.dashboard-analysis-targets-table','.dashboard-history-table']:
    assert page.locator(sel).evaluate('(e)=>e.scrollWidth<=e.clientWidth+1'),sel
   assert page.locator('.dashboard-history-table tbody tr:visible').count()==5
   card=page.locator('.dashboard-analysis-targets-table tbody tr').first
   assert card.locator('td').count()==5
   assert card.locator('td:nth-child(4)').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
  title=page.locator('.notification-heading').bounding_box();actions=page.locator('.header-actions').bounding_box()
  assert title['x']<actions['x']
  assert abs(title['y']+title['height']/2-actions['y']-actions['height']/2)<3
  page.screenshot(path=str(out/f'summary-{width}.png'),full_page=True)
  # Actual template filter strip: compact at phone sizes, same three controls on PC.
  source=(r/'templates/pointouts.html').read_text();chunk=source[source.index('<section class="safety-summary-grid'):];chunk=chunk[:chunk.index('</section>')+10]
  from urllib.parse import urlencode
  filter_html=Environment(autoescape=True).from_string(chunk).render(status_filter='waiting',patrol_stats=dict(waiting=1,not_started=2,rejected=3),view_type='user',office_filter='test',category_filter='安全',date_from='2026-11-01',date_to='2026-11-18',page_size=30,url_for=lambda endpoint,**kw:'/pointouts?'+urlencode(kw))
  filter_css=(r/'static/css/safety_filter_compact.css').read_text()
  page.set_content('<html><meta charset="utf-8"><style>'+css+filter_css+'</style><body><main style="padding:12px"><nav class="safety-list-breadcrumb" hidden></nav>'+filter_html+'</main></body></html>')
  assert page.locator('.safety-summary-card').count()==3
  assert page.locator('.safety-summary-grid').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
  assert 'status=&' in page.locator('.safety-summary-waiting').get_attribute('href')
  page.screenshot(path=str(out/f'filter-{width}.png'),full_page=True)
  results.append({'width':width,'pass':True});page.close()
 browser.close()
(out/'result.json').write_text(json.dumps(results,indent=2))
