const fs=require('fs'),path=require('path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const dir=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
let browser,context,report={cases:[],external:0,websocket:0,post:0};
try{browser=await chromium.launch({headless:true,executablePath:process.env.Q12_BROWSER_EXECUTABLE||undefined});
for(const width of [320,390,768,1316])for(const mode of ['same','mixed','long','empty'])for(const scale of [1,2]){
const id=`${mode}-${width}-${scale}`;context=await browser.newContext({viewport:{width,height:950},serviceWorkers:'block'});const page=await context.newPage();
await page.routeWebSocket('**/*',ws=>{report.websocket++;ws.close();});await page.route('**/*',route=>{const u=new URL(route.request().url());if(route.request().method()!=='GET'){report.post++;return route.abort();}if(u.origin!=='http://fixture.invalid'){report.external++;return route.abort();}if(u.pathname!=='/'+mode+'.html')return route.fulfill({status:404,body:''});return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(dir,mode+'.html'))});});
try{await page.goto('http://fixture.invalid/'+mode+'.html');if(scale===2)await page.locator('body').evaluate(e=>e.classList.add('enlarge'));
const panel=page.locator('[data-personal-requests]');
const handle=await panel.elementHandle(), link=panel.locator('a').first(), href=await link.getAttribute('href');
const before=await page.evaluate(()=>!!(document.querySelector('[data-personal-requests]').compareDocumentPosition(document.querySelector('.dashboard-attention-list'))&Node.DOCUMENT_POSITION_FOLLOWING));
if(before!==(width<=600))throw Error('reading order');
await link.focus();
for(const w of [width<=600?1316:390,width,width<=600?1316:390,width]){
 await page.setViewportSize({width:w,height:950});
 await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
 if(!await handle.evaluate(e=>e===document.querySelector('[data-personal-requests]'))||await page.locator('[data-personal-requests]').count()!==1||await link.getAttribute('href')!==href||!await link.evaluate(e=>e===document.activeElement))throw Error('resize identity/focus');
}
const checks=await page.evaluate(()=>{let bad=[];for(const e of document.querySelectorAll('.dashboard-personal-requests a,.dashboard-personal-requests strong,.dashboard-request-count,.dashboard-video-proposal,.dashboard-video-copy strong,.dashboard-video-action,.dashboard-video-timing,.dashboard-video-state,.dashboard-safety-opening,.dashboard-safety-next')){const r=e.getBoundingClientRect();if(r.width && (r.left<-.5||r.right>innerWidth+.5||e.scrollWidth>e.clientWidth+1))bad.push(e.className);}return{bad,overflow:document.documentElement.scrollWidth>innerWidth+1,links:[...document.querySelectorAll('a')].map(a=>a.getAttribute('href'))};});
if(checks.bad.length||checks.overflow)throw Error('content overflow '+JSON.stringify(checks));
if(width<=600)for(const row of await page.locator('.dashboard-video-proposal').all()){
 const b=await row.boundingBox();if(b.height<44)throw Error('tap height');
 const [t,s,d]=await Promise.all(['.dashboard-video-timing','.dashboard-video-state','.dashboard-video-detail'].map(x=>row.locator(x).boundingBox()));
 if(Math.abs(t.y-s.y)>2||Math.abs(t.y-d.y)>2||t.x+t.width>s.x+1||s.x+s.width>d.x+1)throw Error('meta overlap/order');
}
if(mode!=='empty'){const first=page.locator('.dashboard-video-proposal').first();await first.focus();if(!await first.evaluate(e=>e===document.activeElement))throw Error('focus missing');const expectShared=mode!=='mixed'&&width<=600;if(await page.locator('.dashboard-proposal-shared-vehicle').count() && await page.locator('.dashboard-proposal-shared-vehicle').isVisible()!==expectShared)throw Error('shared vehicle visibility');}
await page.screenshot({path:path.join(out,id+'.png'),fullPage:true});report.cases.push({id,passed:true,...checks});
}catch(e){await page.screenshot({path:path.join(out,id+'-failure.png'),fullPage:true}).catch(()=>{});report.cases.push({id,passed:false,error:String(e)});throw e;}finally{await context.close();context=null;fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));}
}if(report.external||report.websocket||report.post)throw Error('communication attempted');
}finally{if(context)await context.close();if(browser)await browser.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));}})().catch(e=>{console.error(e);process.exitCode=1});
