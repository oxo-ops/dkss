"""Actual shared sidebar markup/CSS/JS, synthetic role/path, no application or live access."""
import json,os,re,subprocess,mimetypes
from pathlib import Path
from jinja2 import Environment
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2];HEAD=os.environ['EXPECTED_HEAD'];OUT=Path(os.environ['ARTIFACTS'])
assert re.fullmatch('[0-9a-f]{40}',HEAD)
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==HEAD
assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
OUT.mkdir(parents=True,exist_ok=True)
base=(ROOT/'templates/base.html').read_text();aside=base[base.index('<aside class="sidebar">'):base.index('<main class="main-content">')]
def url_for(endpoint,**kw):
 if endpoint=='static': return '/static/'+kw['filename']
 return {'vehicle_karte_list':'/vehicle/karte','vehicle_inspection_plans':'/vehicle/inspection-plans','driving_reports':'/safety/driving-reports?scope=self','company_registration':'/company/registration'}.get(endpoint,'/'+endpoint)
def page_html(role,path):
 markup=Environment().from_string(aside).render(session={'username':'synthetic','role':role,'aonagi_readonly_demo':True},path=path,is_vehicle_karte_page=path.startswith('/vehicle/karte'),public_demo_shared=True,url_for=url_for,csrf_token=lambda:'synthetic')
 css=''.join('<style>'+ (ROOT/f'static/css/{f}').read_text()+'</style>' for f in ['style.css','safety_video_refinement.css','notifications_dashboard.css','alseon_brand.css','vehicle_karte_header.css','vehicle_couplings.css','vehicle_karte_overview.css','vehicle_inspection_plans.css','responsive_layout.css'])
 js=''.join('<script>'+ (ROOT/f'static/js/{f}').read_text()+'</script>' for f in ['shell_bootstrap.js','responsive_layout.js','base.js'])
 return '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+css+'<body data-responsive-shell class="vehicle-list-ppt"><div class="app-layout">'+markup+'<main class="main-content"><h1>確認用</h1></main></div>'+js+'</body>'
report={'head':HEAD,'synthetic':True,'live_access':False,'full_page':False,'rows':[],'blocked':[]};pw=sync_playwright().start();browser=None;page=None
try:
 browser=pw.chromium.launch()
 for width in [320,390,768,900,901,1316]:
  for role in ['user','admin']:
   for path in ['/vehicle/karte/647','/pointouts','/vehicle/checklists']:
    row={'width':width,'role':role,'path':path,'passed':False};report['rows'].append(row)
    context=browser.new_context(viewport={'width':width,'height':844},service_workers='block')
    def route(r):
     from urllib.parse import urlparse
     u=urlparse(r.request.url)
     if r.request.method=='GET' and u.netloc=='fixture.invalid' and u.path==path:return r.fulfill(content_type='text/html',body=page_html(role,path))
     if r.request.method=='GET' and u.netloc=='fixture.invalid' and u.path.startswith('/static/'):
      p=(ROOT/u.path.lstrip('/')).resolve()
      if p.is_relative_to(ROOT/'static') and p.is_file() and p.suffix in ('.png','.svg','.webp'):
       return r.fulfill(content_type=mimetypes.guess_type(p)[0] or 'application/octet-stream',body=p.read_bytes())
     report['blocked'].append({'method':r.request.method,'path':u.path});r.abort()
    context.route('**/*',route);page=context.new_page();page.route_web_socket('**/*',lambda ws:(report['blocked'].append({'ws':True}),ws.close()))
    errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
    page.goto('https://fixture.invalid'+path);page.wait_for_timeout(100)
    if width<=900:page.locator('#sidebarToggle').click();assert 'sidebar-open' in page.locator('body').get_attribute('class')
    elif 'sidebar-collapsed' in page.locator('body').get_attribute('class'):page.locator('#sidebarToggle').click()
    # Use actual group buttons, never modify classes to reveal rows.
    for group in page.locator('.sidebar-group').all():
     if 'open' not in group.get_attribute('class'):group.locator('.sidebar-parent').click()
    assert page.locator('.sidebar-nav a[href="/master/drivers"]').count()==(1 if role=='admin' else 0)
    assert page.locator('.sidebar-nav a[href="/company/registration"]').count()==0
    assert page.locator('.sidebar-nav').bounding_box()['height']>=200, 'Shared header must leave a usable menu area'
    logo=page.locator('.alseon-wordmark').bounding_box();head=page.locator('.sidebar-head').bounding_box()
    assert logo['height']<=head['height'] and logo['width']<=head['width']
    measured=[]
    for item in page.locator('.sidebar-submenu a').all():
     item.scroll_into_view_if_needed();r=item.bounding_box();t=item.locator('.menu-text').bounding_box();parent=item.locator('..').bounding_box()
     delta=abs((r['y']+r['height']/2)-(t['y']+t['height']/2))
     assert delta<=1, f'Text not centered: {delta}'
     assert r['height']>=44 and r['width']>=44
     assert t['x']>=r['x'] and t['x']+t['width']<=r['x']+r['width']+1
     assert r['x']>=parent['x'] and r['x']+r['width']<=parent['x']+parent['width']+1
     hit=item.evaluate('(e)=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}')
     assert hit, 'Link center obstructed'
     measured.append({'text':item.inner_text(),'height':r['height'],'center_delta':delta,'href':item.get_attribute('href')})
    page.locator('.sidebar-nav').evaluate('(e)=>e.scrollTop=0')
    page.screenshot(path=str(OUT/f'{width}-{role}-{path.split("/")[1]}-{path.split("/")[-1]}.png'))
    # Existing group toggle, keyboard focus and drawer open/close retain behavior.
    g=page.locator('.sidebar-group').first;g.locator('.sidebar-parent').click();assert 'open' not in g.get_attribute('class');g.locator('.sidebar-parent').click();assert 'open' in g.get_attribute('class')
    page.locator('.sidebar-submenu a').first.focus();assert page.locator('.sidebar-submenu a').first.evaluate('(e)=>document.activeElement===e')
    if width<=900:
     page.locator('#sidebarToggle').click();assert 'sidebar-open' not in page.locator('body').get_attribute('class')
     page.locator('#sidebarToggle').click();assert 'sidebar-open' in page.locator('body').get_attribute('class')
    page.evaluate('''() => {window.fixtureLinks=[];document.querySelectorAll('.sidebar-nav a').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();fixtureLinks.push(a.getAttribute('href'));}));}''')
    link=page.locator('.sidebar-submenu a').first;expected=link.get_attribute('href');link.click()
    assert page.evaluate('fixtureLinks')==[expected]
    if width<=900:assert 'sidebar-open' not in page.locator('body').get_attribute('class')
    assert not errors, errors
    row.update(passed=True,links=measured);context.close();page=None
 assert not report['blocked'],report['blocked']
except Exception as e:
 report['failure']={'type':type(e).__name__,'message':str(e)}
 if page:
  try:page.screenshot(path=str(OUT/'FAILED.png'))
  except Exception as shot:report['screenshot_error']=type(shot).__name__
 raise
finally:
 (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 if browser:browser.close()
 pw.stop()
