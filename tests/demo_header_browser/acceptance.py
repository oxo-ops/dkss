"""Exact-head shared-demo header layout and real click targeting, disposable Flask bridge."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ORIGIN = 'http://127.0.0.1:8765'
WIDTHS = (320, 390, 768, 900, 901, 1024, 1316)
PAGES = ('/', '/vehicle/checklists', '/safety/driving-reports')

def require(value, message):
    if not value:
        raise AssertionError(message)

def click_target(page, control, label):
    control.scroll_into_view_if_needed()
    geometry = control.evaluate("""e=>{const r=e.getBoundingClientRect();
      const pad=Math.min(3,r.width/4,r.height/4);
      const points=[[r.x+r.width/2,r.y+r.height/2],[r.left+pad,r.top+pad],
        [r.right-pad,r.top+pad],[r.left+pad,r.bottom-pad],[r.right-pad,r.bottom-pad]];
      return {inside:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,
        hits:points.map(([x,y])=>{const h=document.elementFromPoint(x,y);return e===h||e.contains(h)}),
        rect:{x:r.x,y:r.y,width:r.width,height:r.height}}}""")
    require(geometry['inside'] and all(geometry['hits']), f'obscured/outside {label}: {geometry}')
    count=page.evaluate('window.__demoClickCount||0')
    control.click(timeout=3000)
    require(page.evaluate('window.__demoClick') == label, f'wrong click: {label}')
    require(page.evaluate('window.__demoClickCount') == count+1, f'missing/duplicate click: {label}')
    return geometry

def bell_roundtrip(page):
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
                            route.fulfill(status=response.status_code, headers=headers, body=response.data)
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
                                if width <= 900:
                                    require(not page.locator('body').evaluate("e=>e.classList.contains('sidebar-open')"), 'drawer should start closed')
                                for label in ('日常点検を開く', '運転者役で見る', '管理者役で確認する'):
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
                                report['cases'].append(dict(role=role,width=width,path=path,position=position))
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
                            require(position==('sticky' if width<=900 else 'absolute'),'ordinary header changed')
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
