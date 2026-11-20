const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),html=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM?{executablePath:process.env.CHROMIUM}:{}),args:['--no-sandbox']});const rows=[];let external=0,posts=0,ws=0,page;try{
for(const width of [320,390,768,1316])for(const mode of ['self','office','user'])for(const period of ['month','custom'])for(const scale of [1,2]){
const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});await context.routeWebSocket('**/*',s=>{ws++;s.close()});page=await context.newPage();
await page.addInitScript(()=>{localStorage.setItem('dkss:first-guide:v1:normal:driving_reports','1')});
await context.route('**/*',route=>{const r=route.request(),u=new URL(r.url());if(r.method()!=='GET'){posts++;return route.abort()}if(u.origin!=='https://fixture.invalid'){external++;return route.abort()}
if(u.pathname==='/safety/driving-reports')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,u.searchParams.get('panel')==='comparison'?'office-comparison.html':mode+'-'+period+'.html'),'utf8')});
const p=path.resolve(repo,'.'+u.pathname);if(u.pathname.startsWith('/static/')&&p.startsWith(repo+'/static/')&&fs.existsSync(p))return route.fulfill({path:p});return route.fulfill({status:404,body:'offline'});});
await page.goto('https://fixture.invalid/safety/driving-reports?scope='+mode+'&period='+period);await page.evaluate(()=>document.fonts.ready);if(await page.locator('#firstGuidePanel').isVisible())await page.keyboard.press('Escape');
if(scale===2)await page.evaluate(()=>{const sizes=[...document.querySelectorAll('.driving-main-filters *, .driving-page-tabs *')].map(e=>[e,parseFloat(getComputedStyle(e).fontSize)]);for(const[e,n]of sizes)e.style.fontSize=n*2+'px'});
assert.equal(await page.locator('#driving-metric-sources').count(),0);assert.equal(await page.getByText('読取内容・比較条件を確認',{exact:false}).count(),0);
const tabs=page.locator('.driving-page-tabs a');assert.equal(await tabs.count(),mode!=='office'?3:4);assert.equal(await page.locator('.driving-view-switch a').count(),2);
if(width<=650){assert(await tabs.evaluateAll(es=>es.every(e=>Math.abs(e.getBoundingClientRect().top-es[0].getBoundingClientRect().top)<2)),'tabs same row');assert(await page.locator('.driving-view-switch a').evaluateAll(es=>es.every(e=>e.getBoundingClientRect().height>=44)),'scope touch size');assert(await tabs.evaluateAll(es=>es.every(e=>e.getBoundingClientRect().height>=44&&e.scrollWidth<=e.clientWidth+1)),'tab text/touch');assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page overflow');}
assert.equal(await page.locator('.driving-main-filters input[type=date][name=start]').isVisible(),period==='custom');
if(width<=650){assert(await page.locator('.driving-period-label select,.driving-filter-trigger,.driving-toolbar-actions> a,.driving-export-menu>summary').evaluateAll(es=>es.filter(e=>e.getBoundingClientRect().height).every(e=>{const r=e.getBoundingClientRect();return r.height>=44&&e.scrollWidth<=e.clientWidth+1&&r.left>=-1&&r.right<=innerWidth+1})),'toolbar controls fit and touch size: '+JSON.stringify(await page.locator('.driving-period-label select,.driving-filter-trigger,.driving-toolbar-actions> a,.driving-export-menu>summary').evaluateAll(es=>es.map(e=>({text:e.textContent,rect:e.getBoundingClientRect().toJSON(),scroll:e.scrollWidth,client:e.clientWidth,display:getComputedStyle(e).display})))));}

const filter=page.locator('#driving-extra-filters'),trigger=page.locator('.driving-filter-trigger');
if(await filter.getAttribute('open')!==null)await trigger.click();
await trigger.scrollIntoViewIfNeeded();const before=await trigger.boundingBox(),scrollBefore=await page.evaluate(()=>scrollY);
assert.equal(await trigger.getAttribute('aria-controls'),'driving-extra-filters');
const fields=await page.locator('#driving-filter-form').evaluate(f=>[...new FormData(f).entries()]);
await trigger.click();assert.notEqual(await filter.getAttribute('open'),null);
const after=await trigger.boundingBox();assert(Math.abs(before.x-after.x)<2&&Math.abs(before.y-after.y)<2,'filter button moved '+JSON.stringify({before,after}));
assert(Math.abs(await page.evaluate(()=>scrollY)-scrollBefore)<2,'scroll changed on disclosure');
assert(await page.locator('.driving-extra-filter-body input[name=start]').isVisible());
assert.deepEqual(await page.locator('#driving-filter-form').evaluate(f=>[...new FormData(f).entries()]),fields,'opening changed GET data');
await page.screenshot({path:path.join(out,`open-${mode}-${period}-${width}-${scale}x.png`),fullPage:true});
await trigger.focus();await page.keyboard.press('Space');assert.equal(await filter.getAttribute('open'),null);
await page.keyboard.press('Enter');assert.notEqual(await filter.getAttribute('open'),null);
if(period!=='custom')await trigger.click();
await page.locator('.driving-export-menu summary').click();assert.equal(await page.locator('.driving-export-menu a').count(),3);for(const a of await page.locator('.driving-export-menu a').all())assert((await a.getAttribute('href')).includes('period='+period));await page.locator('.driving-export-menu summary').click();
await page.screenshot({path:path.join(out,`${mode}-${period}-${width}-${scale}x.png`),fullPage:true});
if(mode==='office'&&period==='custom'&&scale===1){
 await page.goto('https://fixture.invalid/safety/driving-reports?scope=office&panel=comparison');
 const panel=page.locator('[data-workspace-panel="comparison"]');assert(await panel.isVisible());
 assert((await panel.locator('tbody tr').count())>0,'populated comparison rows');
 assert.equal(await panel.getByText('記録量・計算・出典',{exact:true}).count(),0);
 assert(await panel.getByRole('button',{name:'比較する',exact:true}).isVisible());
 assert((await panel.getByText('この比較をCSVで出力',{exact:true}).getAttribute('href')).includes('view=breakdown'));
 assert.equal(await panel.locator('thead th').count(),4);assert(await panel.getByText('前期間・差',{exact:true}).count());
 await panel.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,`comparison-${width}.png`),fullPage:true});
}
rows.push({width,mode,period,scale,text_enlargement_not_native_zoom:true,passed:true});await context.close();page=null;
}assert.equal(rows.length,48);assert.equal(external,0);assert.equal(posts,0);assert.equal(ws,0);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({rows,external,posts,ws}));}catch(e){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({rows,external,posts,ws,error:String(e)}));if(page)await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw e}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
