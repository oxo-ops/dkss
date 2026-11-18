"""Exact-head shared-demo header layout and real click targeting, disposable Flask bridge."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ORIGIN = 'http://127.0.0.1:8765'
WIDTHS = (320, 390, 768, 900, 901, 1024, 1165, 1200, 1280, 1316)
PAGES = ('/', '/vehicle/checklists', '/safety/driving-reports')

def require(value, message):
    if not value:
        raise AssertionError(message)

def click_target(page, control, label):
    control.scroll_into_view_if_needed()
    geometry = control.evaluate("""e=>{const r=e.getBoundingClientRect();
      const pad=Math.min(3,r.width/4,r.height/4);
      // Inline links may wrap into disjoint line boxes; whitespace in their union is not clickable.
      const fragments=Array.from(e.getClientRects()).filter(q=>q.width>0&&q.height>0);
      const style=getComputedStyle(e);
      const radius=Math.max(...['borderTopLeftRadius','borderTopRightRadius','borderBottomLeftRadius','borderBottomRightRadius'].map(k=>parseFloat(style[k])||0));
      const points=fragments.flatMap(q=>{const d=Math.min(Math.max(3,radius),q.width/4,q.height/4);
        return [[q.x+q.width/2,q.y+q.height/2],[q.left+d,q.top+d],
          [q.right-d,q.top+d],[q.left+d,q.bottom-d],[q.right-d,q.bottom-d]]});
      const describe=h=>h?{tag:h.tagName,id:h.id,cls:h.className,text:h.textContent.slice(0,120)}:null;
      const hit=([x,y])=>{const h=document.elementFromPoint(x,y);return {x,y,target:e===h||e.contains(h),hit:describe(h)}};
      const rect=q=>({x:q.x,y:q.y,width:q.width,height:q.height});
      return {inside:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,
        hits:points.map(p=>hit(p).target),fragmentCount:fragments.length,radius,hitDetails:points.map(hit),
        clientRects:Array.from(e.getClientRects()).map(rect),
        fragmentCenters:Array.from(e.getClientRects()).map(q=>hit([q.x+q.width/2,q.y+q.height/2])),
        rect:rect(r),display:getComputedStyle(e).display}}""")
    if not (geometry['inside'] and geometry['fragmentCount']>0 and all(geometry['hits'])):
        # Preserve viewport and all real-fragment hit gates; capture evidence before failing.
        out=Path(os.environ['DKSS_BROWSER_ARTIFACT_DIR'])
        page.screenshot(path=str(out/'failure.png'),full_page=False)
        (out/'failure.json').write_text(json.dumps(dict(label=label,url=page.url,
            viewport=page.viewport_size,geometry=geometry),ensure_ascii=False,indent=2))
        raise AssertionError(f'obscured/outside {label}: {geometry}')
    count=page.evaluate('window.__demoClickCount||0')
    control.click(timeout=3000)
    require(page.evaluate('window.__demoClick') == label, f'wrong click: {label}')
    require(page.evaluate('window.__demoClickCount') == count+1, f'missing/duplicate click: {label}')
    return geometry

def bell_roundtrip(page):
    # Finish the real first-use overlay before measuring underlying controls.
    # Do not hide it via CSS/DOM or weaken any notification hit-target assertion.
    guide = page.locator('#firstGuidePanel')
    if guide.is_visible():
        guide.get_by_role('button', name='操作ガイドを閉じる', exact=True).click()
        require(not guide.is_visible(), 'first-use guide did not close')
    click_target(page,page.locator('#notificationBell'),'notificationBell')
    require(page.locator('#notificationBell').get_attribute('aria-expanded')=='true','bell did not open')
    page.locator('#notificationPopoverList').get_by_text('長い架空通知',exact=False).first.wait_for()
    require(page.locator('#notificationPopover').evaluate('e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth}'),'long notification exceeds viewport')
    close=page.locator('#notificationPopoverClose')
    require(close.evaluate('''e=>{const r=e.getBoundingClientRect();const d=3;
      return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&
        [[r.x+r.width/2,r.y+r.height/2],[r.left+d,r.top+d],[r.right-d,r.top+d],
         [r.left+d,r.bottom-d],[r.right-d,r.bottom-d]].every(([x,y])=>{
           const h=document.elementFromPoint(x,y);return h===e||e.contains(h)})}'''),
      'notification close clipped or obscured')
    close.click()
    require(page.locator('#notificationBell').get_attribute('aria-expanded')=='false','bell did not close')

def notice_text_visibility(page):
    """Read every rendered line of the exact direct banner text, not its controls."""
    expected = '入力・変更は他の利用者にも見えます。個人情報や実際の業務資料は入力しないでください。メール・端末通知は外部送信されません。'
    notice = page.locator('.public-demo-notice')
    locate = """(e, expected) => {
      const matches=Array.from(e.childNodes).filter(n=>n.nodeType===Node.TEXT_NODE && n.textContent.trim()===expected);
      if(matches.length!==1)throw new Error('exact full notice text missing/duplicated');
      const n=matches[0],start=n.textContent.indexOf(expected),r=document.createRange();
      r.setStart(n,start);r.setEnd(n,start+expected.length);return r;
    }"""
    # Report each line individually: a tall banner need not fit in one viewport,
    # but all of its text must be reachable without horizontal scrolling.
    count = notice.evaluate('(e,x)=>{const r=('+locate+')(e,x);return r.getClientRects().length}',expected)
    require(count > 0, 'notice has no rendered text lines')
    lines=[]
    for index in range(count):
        notice.evaluate('''(e,a)=>{
          const r=('''+locate+''')(e,a.expected).getClientRects()[a.index];
          window.scrollBy({top:r.top+r.height/2-innerHeight/2,behavior:'instant'});
        }''',dict(expected=expected,index=index))
        state=notice.evaluate('''(e,a)=>{
          const range=('''+locate+''')(e,a.expected),r=range.getClientRects()[a.index];
          const clipping=[];let visible=true;
          for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p),b=p.getBoundingClientRect();
            if(s.display==='none'||s.visibility!=='visible'||Number(s.opacity)===0)visible=false;
            if(p!==document.body&&p!==document.documentElement){
              const x=['hidden','clip','auto','scroll'].includes(s.overflowX),y=['hidden','clip','auto','scroll'].includes(s.overflowY);
              if((x&&(r.left<b.left-1||r.right>b.right+1))||(y&&(r.top<b.top-1||r.bottom>b.bottom+1)))clipping.push(p.tagName);
            }}
          const points=[r.left+Math.min(2,r.width/4),r.left+r.width/2,r.right-Math.min(2,r.width/4)];
          return {index:a.index,rect:{left:r.left,right:r.right,top:r.top,bottom:r.bottom},visible,clipping,
            inside:r.width>0&&r.height>0&&r.left>=-1&&r.right<=innerWidth+1&&r.top>=-1&&r.bottom<=innerHeight+1,
            unobscured:points.every(x=>document.elementFromPoint(x,r.top+r.height/2)===e),
            noHorizontalScroll:e.scrollWidth<=e.clientWidth+1};
        }''',dict(expected=expected,index=index))
        require(state['visible'] and state['inside'] and state['unobscured'] and state['noHorizontalScroll'] and not state['clipping'],f'notice text clipped/obscured: {state}')
        lines.append(state)
    page.evaluate('window.scrollTo(0,0)')
    return dict(full_text_matched=True,line_count=count,lines=lines)

def brand_roundtrip(page, width, out, role, scene=0):
    """Verify real sidebar controls and alpha PNG loads on the rendered Flask page."""
    guide = page.locator('#firstGuidePanel')
    if guide.is_visible():
        guide.get_by_role('button', name='操作ガイドを閉じる', exact=True).click()
    body = page.locator('body')
    toggle = page.locator('#sidebarToggle')
    mobile = width <= 900
    if mobile or body.evaluate("e=>e.classList.contains('sidebar-collapsed')"):
        toggle.click()
    states = ['expanded'] if mobile else ['expanded', 'collapsed']
    checks = []
    for state in states:
        if state == 'collapsed':
            toggle.click()
        # The existing drawer toggle animates for 0.25s. Wait for its real
        # actionable, stable position before measuring or taking a screenshot.
        toggle.click(trial=True)
        # Stable click targeting can sample between transition frames. Await the
        # actual CSS animations too, without changing their duration or styles.
        page.locator('.sidebar').evaluate("e=>Promise.all(e.getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{})))")
        word = page.locator('.alseon-wordmark')
        symbol = page.locator('.alseon-symbol')
        require(word.is_visible() == (state == 'expanded'), 'wrong wordmark visibility')
        require(symbol.is_visible() == (state == 'collapsed'), 'wrong symbol visibility')
        logo = page.locator('.alseon-logo')
        require(logo.get_attribute('aria-label') == 'ALSEON ホーム', 'brand accessible name')
        require(logo.locator('img').evaluate_all('es=>es.every(e=>e.complete&&e.naturalWidth>0)'), 'logo asset failed to load')
        require(logo.evaluate("e=>getComputedStyle(e).backgroundColor") == 'rgba(0, 0, 0, 0)', 'opaque logo tile')
        require(page.locator('#alseon-dark-logo feColorMatrix').count() == 1, 'missing dark display matrix')
        require(logo.locator('img').evaluate_all("es=>es.every(e=>getComputedStyle(e).filter.includes('alseon-dark-logo'))"), 'dark display filter not applied')
        toggle.hover()
        require(toggle.evaluate("e=>getComputedStyle(e).backgroundColor") == 'rgba(15, 23, 42, 0.18)', 'sidebar hover palette regressed')
        require(toggle.evaluate("e=>getComputedStyle(e).color") == 'rgb(255, 255, 255)', 'sidebar toggle contrast regressed')
        geometry = logo.evaluate('''e=>{const r=e.getBoundingClientRect(),t=document.querySelector('#sidebarToggle').getBoundingClientRect(),s=e.closest('.sidebar').getBoundingClientRect();
          const contained=q=>q.left>=s.left-1&&q.right<=s.right+1&&q.top>=s.top-1&&q.bottom<=s.bottom+1;
          return {width:r.width,height:r.height,sidebarWidth:s.width,sidebarRight:s.right,toggleRight:t.right,sidebarContainsLogo:contained(r),sidebarContainsToggle:contained(t),inside:r.left>=0&&r.right<=innerWidth,
            overlap:r.left<t.right&&r.right>t.left&&r.top<t.bottom&&r.bottom>t.top}}''')
        require(geometry['inside'] and geometry['sidebarContainsLogo'] and geometry['sidebarContainsToggle'] and not geometry['overlap'], f'brand clips/overlaps toggle: {geometry}')
        page.screenshot(path=str(out / f'brand-{role}-{width}-{scene}-{state}.png'), full_page=False)
        checks.append(dict(state=state, **geometry))
    toggle.click()  # restore closed mobile drawer / expanded desktop
    return checks

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--chromium', type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--preflight-only', action='store_true')
    modes.add_argument('--run-browser', action='store_true')
    args = parser.parse_args()
    require(os.environ.get('DKSS_BROWSER_ACCEPTANCE_ISOLATED') == '1', 'isolated wrapper required')
    require(os.environ.get('DATABASE_URL') == 'sqlite:///:memory:', 'disposable SQLite only')
    repo, out = args.repo.resolve(), args.artifacts.resolve()
    sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    require(sha == args.expected_sha, 'wrong exact head')
    require(not subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True).strip(), 'dirty source')
    out.mkdir(parents=True, exist_ok=True)
    os.environ["DKSS_BROWSER_ARTIFACT_DIR"]=str(out)
    os.chdir(repo)
    sys.path[:0] = [str(repo), str(repo / 'tests')]
    from test_public_demo_workflow import DemoWorkflowTests
    report = dict(sha=sha, fixture_only=True, production_accessed=False,
                  browser_started=False, passed=False, cases=[], blocked_requests=[], preflight=[])
    case = DemoWorkflowTests()
    started = setup = False
    try:
        case.setUpClass(); started = True
        case.setUp(); setup = True
        require(case.db.engine.url.drivername == 'sqlite', 'non-SQLite DB forbidden')
        case.app.config['PUBLIC_DEMO_SHARED_COMPANY'] = True
        from identity_fixture import identity_for
        for role in ('checker','admin'):
            case.db.session.add(case.models.Notification(company_code='A',target_user='Test '+role,
                target_username=role,owner_identity=identity_for('A',role,app=case.app),
                title='長い架空通知：'+('点検の確認と判断理由を表示します。'*9),
                message='架空の長文通知です。'*30,link='/',read=False,created_at='2026-11-17 09:00:00'))
        case.db.session.commit()
        for role in ('checker', 'admin'):
            case.login(role)
            recent=case.request('GET','/api/notifications/recent')
            require(recent.status_code==200 and '長い架空通知' in json.dumps(recent.get_json(),ensure_ascii=False),'long notification fixture missing')
            for path in PAGES:
                response = case.request('GET', path, follow_redirects=True)
                require(response.status_code == 200, f'preflight {role} {path}: {response.status_code}')
                require('public-demo-notice' in response.get_data(as_text=True), 'missing demo banner')
                report['preflight'].append([role, path])
        if args.preflight_only:
            report['passed'] = True
            return
        from playwright.sync_api import sync_playwright
        require(args.chromium and args.chromium.is_file(), 'installed Chromium required')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(args.chromium), headless=True)
            report['browser_started'] = True
            baseline_css=False
            try:
                for role in ('checker', 'admin'):
                    case.login(role)
                    for width in WIDTHS:
                        context = browser.new_context(viewport={'width': width, 'height': 760}, service_workers='block')
                        def bridge(route):
                            request = route.request
                            url = urlsplit(request.url)
                            if (url.scheme + '://' + url.netloc != ORIGIN or request.method != 'GET'):
                                report['blocked_requests'].append([request.method, request.url])
                                route.abort(); return
                            response = case.request('GET', url.path + ('?' + url.query if url.query else ''), follow_redirects=True)
                            # Flask's fixture client owns the synthetic session. No browser cookies or real server.
                            headers = {k: v for k, v in response.headers.items() if k.lower() not in ('set-cookie', 'content-length', 'content-encoding')}
                            body=response.data
                            if baseline_css and url.path=='/static/css/responsive_layout.css':
                                marker=b'/* Shared demo controls follow the header on desktop too.'
                                require(body.count(marker)==1,'baseline CSS boundary missing')
                                body=body.split(marker)[0]
                            route.fulfill(status=response.status_code, headers=headers, body=body)
                        context.route('**/*', bridge)
                        page = context.new_page()
                        # Capture actual mouse-targeted controls without submitting forms or leaving fixture page.
                        page.add_init_script("""document.addEventListener('click', e => {
                          const target=e.target.closest('.public-demo-notice a,.public-demo-notice button,#notificationBell');
                          if(target){window.__demoClick=target.id==='notificationBell'?'notificationBell':target.textContent.trim();
                            window.__demoClickCount=(window.__demoClickCount||0)+1;
                            if(target.id!=='notificationBell')e.preventDefault();}
                        },true);""")
                        try:
                            for n, path in enumerate(PAGES):
                                page.goto(ORIGIN + path, wait_until='networkidle')
                                page.locator('.public-demo-notice').wait_for()
                                require(page.locator('.public-demo-notice form[action="/logout"]').count()==0,'removed demo exit returned')
                                notice_geometry = notice_text_visibility(page)
                                if width <= 900:
                                    require(not page.locator('body').evaluate("e=>e.classList.contains('sidebar-open')"), 'drawer should start closed')
                                for label in ('日常点検を開く', '運転者', '管理者'):
                                    control = page.get_by_text(label, exact=True)
                                    click_target(page,control,label)
                                    require(not page.locator('#notificationBell').get_attribute('aria-expanded') == 'true', 'demo click opened notification bell')
                                bell_roundtrip(page)
                                # Return-to-top check only; this does not prove hit targets during scrolling.
                                page.evaluate('window.scrollTo(0,400)')
                                page.evaluate('window.scrollTo(0,0)')
                                header = page.locator('main > .top-bar')
                                position = header.evaluate('e=>getComputedStyle(e).position')
                                require(position == ('sticky' if width <= 900 else 'relative'), f'wrong header positioning {width}: {position}')
                                click_target(page,page.get_by_text('日常点検を開く',exact=True),'日常点検を開く')
                                page.screenshot(path=str(out / f'{role}-{width}-{n}.png'), full_page=False)
                                report['cases'].append(dict(role=role,width=width,path=path,position=position,notice=notice_geometry))
                            # Real synthetic Flask POST, not a DOM-only hide. Keep browser bridge GET-only.
                            token=page.locator('.public-demo-notice form[action="/demo/role"] input[name="csrf_token"]').input_value()
                            selected=case.request('POST','/demo/role',data={'role':'manager' if role=='admin' else 'driver','csrf_token':token})
                            require(selected.status_code==302 and selected.headers['Location']=='/','role must return home')
                            for n,path in enumerate(PAGES):
                                page.goto(ORIGIN+path,wait_until='networkidle')
                                require(page.locator('.public-demo-notice').count()==0,'selected role retained demo notice')
                                header=page.locator('main > .top-bar')
                                position=header.evaluate('e=>getComputedStyle(e).position')
                                require(position==('sticky' if width<=900 else 'relative'),'selected header flow regressed')
                                require(not page.evaluate('document.documentElement.scrollWidth>innerWidth+1'),'selected horizontal overflow')
                                bell_roundtrip(page)
                                page.screenshot(path=str(out/f'{role}-{width}-{n}-selected.png'),full_page=False)
                                report['cases'].append(dict(role=role,width=width,path=path,brand=brand_roundtrip(page,width,out,role,n)))
                            page.goto(ORIGIN+'/demo',wait_until='networkidle')
                            require(page.locator('.public-demo-notice form[action="/demo/role"]').count()==1,'reentry must restore role selection')
                            require(page.get_by_text('日常点検を開く',exact=True).is_visible(),'initial independent inspection action missing')
                            require(page.locator('.public-demo-notice form[action="/logout"]').count()==0,'exit must remain absent')
                            report['cases'].append(dict(role=role,width=width,role_selected_hidden=True,reentry_restored=True))
                        finally:
                            context.close()
                # Ordinary sessions do not receive the scoped override.
                case.demo_active = False
                case.login('admin')
                for width in WIDTHS:
                    context = browser.new_context(viewport={'width':width,'height':760}, service_workers='block')
                    context.route('**/*', bridge)
                    try:
                        page=context.new_page()
                        page.add_init_script("""document.addEventListener('click',e=>{
                          if(e.target.closest('#notificationBell')){window.__demoClick='notificationBell';
                          window.__demoClickCount=(window.__demoClickCount||0)+1;}},true)""")
                        for path in PAGES:
                            page.goto(ORIGIN+path,wait_until='networkidle')
                            require(page.locator('.public-demo-notice').count()==0,'ordinary session has demo banner')
                            position=page.locator('main > .top-bar').evaluate('e=>getComputedStyle(e).position')
                            # Page-specific desktop headers are not all absolute. Compare against
                            # the same stylesheet before this candidate's appended scoped rule.
                            baseline_css=True
                            page.reload(wait_until='networkidle')
                            baseline_position=page.locator('main > .top-bar').evaluate('e=>getComputedStyle(e).position')
                            require(position==baseline_position,f'ordinary header changed {width} {path}: {position} vs {baseline_position}')
                            baseline_css=False
                            page.reload(wait_until='networkidle')
                            bell_roundtrip(page)
                            report['cases'].append(dict(role='ordinary-admin',width=width,path=path,position=position))
                    finally:context.close()
                require(not report['blocked_requests'], 'unexpected external request or mutation')
                report['passed'] = True
            finally:browser.close()
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        case.doCleanups()
        if setup:case.tearDown()
        if started:case.tearDownClass()

if __name__ == '__main__':
    main()
