"""Loopback-only brand fixture. No app factory, DB, credentials or business data.
Uses production picture markup, brand CSS, bytes and cache helper. This does NOT
replace full app authorization tests or actual-device acceptance.
"""
import hashlib, importlib.util, json, os, re, threading
from html.parser import HTMLParser
from urllib.parse import urlsplit
from pathlib import Path
from collections import Counter
from flask import Flask, request, session
from jinja2 import Environment
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.environ['BRAND_OUTPUT']);OUT.mkdir(parents=True,exist_ok=True)
spec=importlib.util.spec_from_file_location('cache_under_test',ROOT/'dkss_app/bundled_asset_cache.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
app=Flask(__name__,static_folder=str(ROOT/'static'),static_url_path='/static')
app.secret_key='synthetic-loopback-brand-only'
counts=Counter()
@app.before_request
def count():
 if request.endpoint=='static':counts[request.full_path]+=1
@app.after_request
def cache(response):
 response.headers['Cache-Control']='private, no-store'
 return module.apply_bundled_asset_cache(response)
base=(ROOT/'templates/base.html').read_text()
logo=re.search(r'<a href="/" class="logo alseon-logo".*?</a>',base,re.S).group()
filters=re.findall(r'<svg[^>]*alseon-brand-filter[\s\S]*?</svg>',base)
# No scripts or external references from the app are executed.
@app.get('/')
def index():
 markup=logo
 if request.args.get('png')=='1':markup=markup.replace('type="image/webp"','type="image/x-unsupported-brand-test"')
 if request.args.get('old')=='1':
  for h in module.PUBLIC_ASSET_VERSIONS.values():markup=markup.replace(h,'old')
 markup=Environment(autoescape=True).from_string(markup).render(url_for=lambda ep,filename,**kw:'/static/'+filename+('?v='+kw['v'] if 'v' in kw else ''))
 return ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
 '<link rel="stylesheet" href="/static/css/alseon_brand.css"><style>body{margin:0;background:#f3f6fc;font:16px sans-serif}.sidebar{width:240px;background:#25304b;padding:10px}.sidebar-head{display:flex;align-items:center}.sidebar-toggle{padding:12px}main{padding:20px}body.sidebar-collapsed .sidebar{width:72px}</style>'
 '<body>'+''.join(filters)+'<aside class="sidebar"><div class="sidebar-head">'+markup+'<button class="sidebar-toggle" id="toggle">☰</button></div></aside><main>Brand rendering fixture</main>'
 '<script>document.querySelector("#toggle").onclick=()=>document.body.classList.toggle("sidebar-collapsed")</script>')
class LocalReferences(HTMLParser):
 def handle_starttag(self, tag, attrs):
  for key,value in attrs:
   if key in {'src','href','srcset'} and value:
    for part in value.split(','):
     url=part.strip().split()[0]
     assert url.startswith('/') and not url.startswith('//'), (tag,key,url)
def validate_fixture():
 with app.test_request_context('/'):
  LocalReferences().feed(index())
 css=(ROOT/'static/css/alseon_brand.css').read_text()
 assert '@import' not in css.lower()
 for value in re.findall(r'url\((.*?)\)',css,re.I):
  assert value.strip(' \"\'').startswith('#'), 'external CSS resource'
def check_assets():
 for path,h in module.PUBLIC_ASSET_VERSIONS.items():assert hashlib.sha256((ROOT/'static'/path).read_bytes()).hexdigest()==h
check_assets();validate_fixture()
server=make_server('127.0.0.1',51249,app,threaded=True)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
results=[]
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--disable-background-networking','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'])
  for width,dpr in [(390,1),(390,3),(1316,1),(1316,2)]:
   context=browser.new_context(viewport={'width':width,'height':800},device_scale_factor=dpr,service_workers='block')
   page=context.new_page();origin='http://127.0.0.1:51249'
   violations=[]
   context.on('request',lambda r: violations.append({'url':r.url,'method':r.method}) if urlsplit(r.url).netloc!='127.0.0.1:51249' or r.method!='GET' else None)
   page.on('websocket',lambda ws:violations.append({'websocket':ws.url}))
   page.goto(origin);page.wait_for_function('Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)')
   assert all('.webp?v=' in x for x in page.locator('picture img').evaluate_all('(xs)=>xs.map(i=>i.currentSrc)'))
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   page.screenshot(path=str(OUT/f'brand-{width}-{dpr}-expanded.png'))
   before={k:v for k,v in counts.items() if '.webp?' in k}
   page.goto(origin+'/?second=1');page.wait_for_function('Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)')
   assert before=={k:v for k,v in counts.items() if '.webp?' in k}, 'versioned logos requested again instead of browser reuse'
   page.locator('#toggle').click();page.screenshot(path=str(OUT/f'brand-{width}-{dpr}-collapsed.png'))
   # A stale version must hit the server and remain no-store, then current version must select correct URL.
   response_headers=[]
   page.on('response',lambda r:response_headers.append((r.url,r.headers.get('cache-control',''))))
   page.goto(origin+'/?old=1');page.wait_for_function('Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)')
   assert any('v=old' in u and 'no-store' in h for u,h in response_headers)
   page.goto(origin+'/?current=1');page.wait_for_function('Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)')
   assert all('.webp?v=' in x and 'v=old' not in x for x in page.locator('picture img').evaluate_all('(xs)=>xs.map(i=>i.currentSrc)'))
   page.goto(origin+'/?png=1');page.wait_for_function('Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)')
   assert all(x.endswith('.png') for x in page.locator('picture img').evaluate_all('(xs)=>xs.map(i=>i.currentSrc)'))
   page.screenshot(path=str(OUT/f'brand-{width}-{dpr}-png-fallback.png'))
   assert not violations, violations
   results.append({'width':width,'dpr':dpr,'webp':True,'cache_reuse':True,'stale_no_store':True,'png_type_fallback':True})
   context.close()
  browser.close()
 (OUT/'report.json').write_text(json.dumps({'results':results,'limits':['isolated brand markup, not whole application','fallback tests unsupported source MIME, not failed network','no actual iPhone or Redis','manual class toggle tests brand CSS, not real sidebar JS','static URL allowlist and request assertions; resolver rule alone not OS network isolation','new version chosen by full hash; same content stale URL tested']},indent=2))
finally:server.shutdown()
