from pathlib import Path
import os
import re,json
from playwright.sync_api import sync_playwright
root=Path(os.environ.get('PALETTE_QA_ROOT',Path(__file__).parent))
palette=(root/'palette.css').read_text()
assert not any(x in palette for x in ['padding:', 'margin:', 'font-size:', 'display:', 'position:', 'height:', 'width:'])
fixture='''<div class="dashboard-page dashboard-design-v2"><div class="dashboard-vehicles-section"><h3>使用車両・日常点検</h3><button class="dashboard-vehicle-add-button">車両を追加</button><div class="dashboard-vehicle-card"><strong>品川 100 か 101</strong><a href="#check" class="dashboard-vehicle-action dashboard-vehicle-action-primary">日常点検表</a></div></div><div class="dashboard-reference-action-links"><a href="#request"><strong>運行判断・不具合対応</strong><span>1件</span></a></div><div class="dashboard-trend-tabs"><button aria-selected="true">安全・点検</button><button>整備費</button></div><div class="dashboard-reference-safety"><div class="summary-card"><div class="summary-value good">5</div></div></div><span class="dashboard-safety-state" data-state="対策確認待ち">対策確認待ち</span><span class="dashboard-safety-state" data-state="差し戻し">差し戻し</span><span class="dashboard-reference-state" data-state="completed">完了</span><button class="dashboard-history-open">履歴を詳しく見る</button></div>'''
# CSS inclusion in live order, plus unchanged safety CSS for state preservation.
order=['static/css/style.css','static/css/dashboard_safety_attention.css','static/css/dashboard_mobile_refinement.css','static/css/video_proposal_lists.css','static/css/dashboard_summary_mobile.css']
report=[]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
 for width in (320,390,768,1440):
  vals=[]
  for variant in ('original','candidate'):
   page=browser.new_page(viewport={'width':width,'height':900})
   css='\n'.join((root/(variant if (root/variant/f).exists() else 'original')/f).read_text() for f in order)
   page.set_content('<style>'+css+(palette if variant=='candidate' else '')+'</style>'+fixture)
   vals.append(page.locator('.dashboard-design-v2 *').evaluate_all('(es)=>es.map(e=>{let r=e.getBoundingClientRect(),s=getComputedStyle(e);return {rect:[r.x,r.y,r.width,r.height],text:e.textContent,color:s.color,bg:s.backgroundColor}})'))
   page.screenshot(path=str(root/f'{variant}-{width}.png'),full_page=True)
   page.close()
  assert [(x['rect'],x['text']) for x in vals[0]]==[(x['rect'],x['text']) for x in vals[1]],width
  for a,b in zip(*vals):
   if a['text'] in ('対策確認待ち','差し戻し','完了','5'):assert(a['color'],a['bg'])==(b['color'],b['bg']),(width,a,b)
  report.append({'width':width,'layout_text_equal':True,'states_unchanged':True})
 browser.close()
(root/'report.json').write_text(json.dumps(report,indent=2))
print(report)
