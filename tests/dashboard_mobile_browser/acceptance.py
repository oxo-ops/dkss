import os,sys,json,argparse,subprocess
from pathlib import Path
from urllib.parse import urlsplit
parser=argparse.ArgumentParser()
parser.add_argument('--repo',type=Path,required=True)
parser.add_argument('--artifacts',type=Path,required=True)
parser.add_argument('--chromium',type=Path)
parser.add_argument('--expected-sha',required=True)
parser.add_argument('--preflight-only',action='store_true')
parser.add_argument('--run-browser',action='store_true')
args=parser.parse_args()
assert os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED')=='1'
repo=args.repo.resolve();out=args.artifacts.resolve();out.mkdir(parents=True,exist_ok=True)
assert subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()==args.expected_sha
assert not subprocess.check_output(['git','-C',str(repo),'status','--porcelain'],text=True).strip()
os.environ['DKSS_BROWSER_ARTIFACT_DIR']=str(out)
sys.path[:0]=[str(repo),str(repo/'tests')]
from test_public_demo_workflow import DemoWorkflowTests
from playwright.sync_api import sync_playwright
case=DemoWorkflowTests();case.setUpClass();case.setUp()
report={'sha':args.expected_sha,'fixture_only':True,'cases':[],'blocked':[],'browser_started':False}
try:
 case.app.config['PUBLIC_DEMO_SHARED_COMPANY']=True
 from identity_fixture import identity_for
 for role in ['checker','admin']:
  u=case.models.User.query.filter_by(company_code='A',username=role).one();u.office='架空中央営業所'
  u.dashboard_settings_json=json.dumps({'show_pending':True,'show_analysis':True,'show_vehicles':True})
 case.db.session.commit()
 for role in ['checker','admin']:
  case.db.session.add(case.models.Notification(company_code='A',target_user='Test '+role,target_username=role,owner_identity=identity_for('A',role,app=case.app),title='長い架空通知：確認してください。',message='架空通知',link='/',read=False,created_at='2026-11-17 09:00:00'))
  case.db.session.commit()
 for i in range(4):
  case.db.session.add(case.models.PatrolResult(company_code='A',office='架空中央営業所',target_type='delivery_place',delivery_place='架空構内',content=f'【体験用・架空】{i+1} 雨天の構内で路面が滑りやすいことを確認し、減速して停止位置を手前に変更した。接触・負傷なし。確認事項：天候に応じた速度と歩行者動線の確認。',category='指摘',date='2026-10-28',countermeasure='写真と対策内容を確認',approval_status='差し戻し' if i==1 else '承認待ち',countermeasure_due_date='2026-11-19'))
 case.db.session.commit()
 # Saved, synthetic proposals only. No live AI or production data is involved.
 vehicle=case.models.Vehicle.query.filter_by(company_code='A').one()
 vehicle.office='架空中央営業所'
 for role in ['checker','admin']:
  case.db.session.add(case.models.Driver(company_code='A',employee_id=role,name='Test '+role,office='架空中央営業所',vehicles_json=json.dumps([str(vehicle.id)])))
 case.db.session.add(case.models.VehicleKarteAnalysis(company_code='A',vehicle_record_id=vehicle.id,status='completed',result_json=json.dumps({'analysis':{'recommendations':[dict(title=f'架空の保存済み候補{i}',target=f'架空部品{i}',category='整備・点検',priority=['高','中','低'][i%3],action='記録と現車を確認し整備担当者へ相談',reason='【試験用架空データ】保存済みの記録を根拠とする表示確認。安全判断を示すものではありません。',timing='次回点検時に確認') for i in range(6)]}},ensure_ascii=False)))
 case.db.session.commit()
 for role in ['checker','admin']:
  case.login(role)
  response=case.request('GET','/')
  assert response.status_code==200
  html=response.get_data(as_text=True)
  if html.count('class="dashboard-safety-content"')!=4:(out/f'fixture-{role}.html').write_text(html)
  assert html.count('class="dashboard-safety-content"')==4
  assert 'dashboard_mobile_refinement.css?v=20261117-mobile-cards-1' in html
  assert '架空部品5' in html
  assert '実在する人の個人情報や実際の業務資料は入れないでください' in html
 if args.preflight_only:
  report['preflight_passed']=True
  sys.exit(0)
 from demo_header_browser.acceptance import notice_text_visibility,click_target,bell_roundtrip
 assert args.chromium and args.chromium.is_file()
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=str(args.chromium),headless=True,args=['--no-sandbox'])
  report['browser_started']=True
  for role in ['checker','admin']:
   case.login(role)
   for width,scale in [(w,1) for w in [320,390,600,601,768,1316]]+[(320,2),(390,2)]:
    ctx=browser.new_context(viewport={'width':width,'height':568 if scale==2 else 740},service_workers='block')
    def bridge(route):
     req=route.request;u=urlsplit(req.url)
     if u.netloc!='127.0.0.1:8765' or req.method!='GET':
      report['blocked'].append(req.url);route.abort();return
     res=case.request('GET',u.path+('?' + u.query if u.query else ''),follow_redirects=True)
     route.fulfill(status=res.status_code,headers={k:v for k,v in res.headers.items() if k.lower() not in ['set-cookie','content-length','content-encoding']},body=res.data)
    ctx.route('**/*',bridge);page=ctx.new_page()
    page.add_init_script("""document.addEventListener('click',e=>{
      const t=e.target.closest('.public-demo-notice a,.public-demo-notice button,#notificationBell');
      if(t){window.__demoClick=t.id==='notificationBell'?'notificationBell':t.textContent.trim();
        window.__demoClickCount=(window.__demoClickCount||0)+1;
        if(t.id!=='notificationBell')e.preventDefault();}
    },true)""")
    page.goto('http://127.0.0.1:8765/',wait_until='networkidle')
    assert page.locator('.dashboard-safety-content').count()==4,'fixture safety records absent'
    if scale==2:
     page.evaluate("""()=>{const values=Array.from(document.querySelectorAll('.public-demo-notice,.public-demo-notice *,.dashboard-page,.dashboard-page *')).map(e=>[e,parseFloat(getComputedStyle(e).fontSize)*2]);for(const [e,size] of values)e.style.setProperty('font-size',size+'px','important')}""")
    notice_text_visibility(page)
    for label in ['日常点検を開く','運転者役で見る','管理者役で確認する','体験を終了']:
     control=page.get_by_text(label,exact=True)
     click_target(page,control,label)
     control.focus();page.keyboard.press('Tab')
    bell_roundtrip(page)
    page.evaluate('window.scrollTo(0,0)')
    page.screenshot(path=str(out/f'{role}-{width}-scale{scale}-top.png'))
    page.locator('.dashboard-safety-attention').scroll_into_view_if_needed();page.screenshot(path=str(out/f'{role}-{width}-scale{scale}-safety.png'))
    page.locator('.dashboard-attention-panel').first.scroll_into_view_if_needed();page.screenshot(path=str(out/f'{role}-{width}-scale{scale}-proposals.png'))
    assert page.locator('.dashboard-attention-preview tbody tr').count()==5
    assert page.locator('.dashboard-attention-empty').count()>=1
    measure=page.evaluate('''()=>({overflow:document.documentElement.scrollWidth>innerWidth+1, direction:getComputedStyle(document.querySelector('.dashboard-safety-items>li')).flexDirection, linkSize:getComputedStyle(document.querySelector('.dashboard-safety-content a')).fontSize})''')
    assert not measure['overflow'],measure
    if width<=600:assert measure['direction']=='column',measure
    for disclosure in page.locator('.dashboard-safety-items > li .dashboard-safety-story').all():
     if not disclosure.is_visible():continue
     summary=disclosure.locator('summary');summary.focus();page.keyboard.press('Enter')
     assert disclosure.get_attribute('open') is not None
     assert disclosure.locator('a').is_visible()
    for loc in ['.public-demo-notice a','.public-demo-notice button','.dashboard-safety-items:first-of-type .dashboard-safety-content a','.dashboard-attention-table td a']:
     for e in page.locator(loc).all():
      if not e.is_visible():continue
      e.scroll_into_view_if_needed();r=e.bounding_box();assert r['x']>=-1 and r['x']+r['width']<=width+1,(loc,r)
      if width<=600:assert r['height']>=43,(loc,r)
    summary=page.locator('.dashboard-safety-more>summary');summary.focus();page.keyboard.press('Enter');assert page.locator('.dashboard-safety-more').get_attribute('open') is not None
    assert page.locator('.dashboard-safety-content').last.is_visible()
    page.keyboard.press('Enter');assert page.locator('.dashboard-safety-more').get_attribute('open') is None
    report['cases'].append({'role':role,'width':width,'synthetic_text_scale':scale,**measure});ctx.close()
  case.login('checker')
  ctx=browser.new_context(viewport={'width':390,'height':740},java_script_enabled=False,service_workers='block')
  ctx.route('**/*',bridge);page=ctx.new_page();page.goto('http://127.0.0.1:8765/',wait_until='networkidle')
  disclosure=page.locator('.dashboard-safety-story').first
  disclosure.locator('summary').click()
  assert disclosure.locator('.dashboard-safety-story-full').is_visible()
  opening=page.locator('.dashboard-safety-opening').first
  href=opening.get_attribute('href');opening.click();page.wait_for_load_state('networkidle')
  assert urlsplit(page.url).path==href
  page.go_back(wait_until='networkidle')
  assert page.locator('.dashboard-safety-opening').count()==4
  page.screenshot(path=str(out/'checker-390-nojs-back.png'))
  report['cases'].append({'role':'checker','width':390,'javascript':False,'direct_detail_and_back':True})
  ctx.close()
  browser.close()
 assert not report['blocked'],report['blocked']
 report['passed']=True
finally:
 (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));case.doCleanups();case.tearDown();case.tearDownClass()
