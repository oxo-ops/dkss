const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),dir=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);fs.mkdirSync(out,{recursive:true});
// Wait for the real drawer transition to settle before judging/taking evidence.
// Two animation frames are insufficient for the CSS .25s resize transition.
async function settledShell(page) {
 const geometry=await page.evaluate(async()=>{
  const sidebar=document.querySelector('.sidebar'),toggle=document.querySelector('#sidebarToggle');
  if(!sidebar||!toggle)throw Error('missing shell');
  let previous=null,stable=0;
  const started=performance.now();
  while(performance.now()-started<5000){
   await new Promise(resolve=>requestAnimationFrame(resolve));
   const s=sidebar.getBoundingClientRect(),t=toggle.getBoundingClientRect();
   const values=[s.x,s.y,s.width,s.height,t.x,t.y,t.width,t.height];
   const animating=[...sidebar.getAnimations(),...toggle.getAnimations()].some(a=>a.playState==='running');
   stable=!animating&&previous&&values.every((v,i)=>Math.abs(v-previous[i])<0.1)?stable+1:0;
   previous=values;
   if(stable>=6)return {width:innerWidth,open:document.body.classList.contains('sidebar-open'),sidebar:{x:s.x,right:s.right,width:s.width},toggle:{x:t.x,right:t.right,width:t.width}};
  }
  throw Error('sidebar geometry did not settle');
 });
 if(geometry.width<=900){
  assert.equal(geometry.open,false,'resize returns drawer closed');
  assert(geometry.sidebar.right<=1,'closed drawer must be entirely offscreen');
  assert(geometry.toggle.x>=-1&&geometry.toggle.right<=geometry.width+1,'toggle stays onscreen');
 }
 return geometry;
}
(async()=>{let browser,context,page;const report={cases:[],external:0,post:0,ws:0};try{
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM||undefined});
 for(const mode of ['normal-admin','normal-checker','demo-admin','demo-checker'])for(const width of [320,390,768,1316]){
  context=await browser.newContext({viewport:{width,height:950},serviceWorkers:'block'});page=await context.newPage();await context.routeWebSocket('**/*',s=>{report.ws++;s.close()});
  await context.route('**/*',r=>{const u=new URL(r.request().url());if(r.request().method()!=='GET'){report.post++;return r.abort()}if(u.origin!=='https://fixture.invalid'){report.external++;return r.abort()}
   if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(dir,mode+'.html'))});
   const f=path.resolve(repo,'.'+u.pathname);if(u.pathname.startsWith('/static/')&&f.startsWith(repo+'/static/')&&fs.existsSync(f))return r.fulfill({path:f});return r.fulfill({status:404,body:'offline'});
  });
  await page.goto('https://fixture.invalid/');await page.evaluate(()=>document.fonts.ready);
  assert(await page.locator('.dashboard-page').evaluate(e=>e.dataset.designReady==='true'));
  const guide=page.locator('#firstGuidePanel');await guide.waitFor({state:'visible'});const titles=[];
  for(let n=0;n<20;n++){titles.push(await page.locator('[data-guide-title]').innerText());await page.screenshot({path:path.join(out,mode+'-'+width+'-guide-'+n+'.png')});await page.locator('[data-guide-next]').click();if(!await guide.isVisible())break;if(n===19)throw Error('guide did not finish')}
  assert(titles.length>1,'full guide');assert(await page.locator('.dashboard-video-proposal').count()>0,'nonempty AI');assert(await page.locator('.office-trend-row').count()>0,'nonempty trend');assert(await page.locator('.dashboard-safety-next').count()>0,'nonempty safety');await page.locator('[data-guide-open]').click();await guide.waitFor({state:'visible'});await page.locator('[data-guide-close]').click();await guide.waitFor({state:'hidden'});
  const settled=[];const panel=page.locator('[data-personal-requests]'),handle=await panel.elementHandle(),link=panel.locator('a').first();assert.equal(await panel.count(),1);const href=await link.getAttribute('href');await link.focus();
  for(const w of [width<=600?1316:390,width]){await page.setViewportSize({width:w,height:950});settled.push(await settledShell(page));assert(await handle.evaluate(e=>e===document.querySelector('[data-personal-requests]')));assert(await link.evaluate(e=>e===document.activeElement));assert.equal(await link.getAttribute('href'),href);const before=await handle.evaluate(e=>!!(e.compareDocumentPosition(document.querySelector('.dashboard-attention-list'))&Node.DOCUMENT_POSITION_FOLLOWING));assert.equal(before,w<=600);}
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'full home overflow');await page.screenshot({path:path.join(out,mode+'-'+width+'.png'),fullPage:true});report.cases.push({mode,width,titles,settled,passed:true});await context.close();context=null;
 }
 assert.equal(report.cases.length,16);assert.equal(report.external,0);assert.equal(report.post,0);assert.equal(report.ws,0);
}catch(e){report.error=String(e);if(page)await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw e}finally{if(context)await context.close();if(browser)await browser.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));}})().catch(e=>{console.error(e);process.exitCode=1});
