const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const out=process.env.ARTIFACTS,html=process.env.HTML_OUT;fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,args:['--no-sandbox']});let report=[],blocked=[];
try{for(const width of [320,390,768,1440])for(const name of ['fixture','table']){
const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'}),page=await context.newPage();
await page.route('**/*',route=>{const req=route.request(),u=new URL(req.url());if(req.method()!=='GET'||u.origin!=='https://fixture.invalid'){blocked.push(req.method());return route.abort();}if(u.pathname==='/'+name)return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,name+'.html'),'utf8')});if(u.pathname.startsWith('/unchanged/'))return route.fulfill({contentType:'text/html',body:'<p>Original record destination</p>'});return route.fulfill({status:404,body:'offline'});});
const url='https://fixture.invalid/'+name;await page.goto(url);
const root=page.locator(name==='fixture'?'#vehicle-karte-overview':'.vehicle-karte-history-table');
for(const kind of ['日常点検','点検予定']){
 const label=root.locator(`[data-kind="${kind}"] .vehicle-history-kind-label`).first();assert(await label.isVisible());
 assert.deepEqual(await label.locator('.history-kind-unit').allTextContents(),[kind]);
 const bounds=await label.locator('.history-kind-unit').evaluateAll(es=>es.map(e=>({h:e.getBoundingClientRect().height,line:parseFloat(getComputedStyle(e).lineHeight),wrap:getComputedStyle(e).whiteSpace})));
 for(const b of bounds){assert.equal(b.wrap,'nowrap');assert(b.h<=b.line+2);}
 const box=await label.boundingBox(),cell=await label.locator('xpath=..').boundingBox();assert(box.x>=cell.x-1&&box.x+box.width<=cell.x+cell.width+1,'four character label stays inside category');
 assert.equal(await label.evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)');
}
const selector=name==='fixture'?'.ko-history-link':'.vehicle-history-mobile-content a';
if(name==='fixture'||width<=768){
 const link=root.locator(selector).first();assert.equal(await link.evaluate(e=>getComputedStyle(e).textDecorationLine),'none');assert.equal(await link.evaluate(e=>getComputedStyle(e).fontWeight),'400');const href=await link.getAttribute('href');
 for(const mode of ['click','Enter']){const l=page.locator(selector).first();await l.scrollIntoViewIfNeeded();if(mode==='click')await l.click();else{await l.focus();await page.keyboard.press('Enter');}await page.waitForURL('https://fixture.invalid'+href);await page.goBack();}
}
await root.scrollIntoViewIfNeeded();await root.screenshot({path:path.join(out,name+'-'+width+'.png')});
assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
report.push({name,width,passed:true});await context.close();}
assert.equal(blocked.length,0);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({report,blocked,fixture:'real template fragments, synthetic records, original link attributes retained'},null,2));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
