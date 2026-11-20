const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const root=process.env.PRODUCT_REPO,out=process.env.DIAGNOSTIC_OUT;
(async()=>{const browser=await chromium.launch({headless:true});const report=[];
try{for(const width of [390,1180])for(const mode of ['local','delayed-shell'])for(let repeat=0;repeat<2;repeat++){
const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage(),requests=[],blocked=[],errors=[];
page.on('pageerror',e=>errors.push(String(e)));
await page.addInitScript(()=>{window.__diag={longtasks:[],paint:[]};for(const type of ['longtask','paint'])new PerformanceObserver(list=>{for(const e of list.getEntries())window.__diag[type==='paint'?'paint':'longtasks'].push({name:e.name,start:e.startTime,duration:e.duration})}).observe({type,buffered:true});});
await context.route('**/*',async route=>{const req=route.request(),u=new URL(req.url()),start=Date.now();requests.push({path:u.pathname,method:req.method()});
if(req.method()!=='GET'||u.origin!=='https://fixture.invalid'){blocked.push({url:u.href,method:req.method()});return route.abort();}
if(u.pathname==='/vehicle/checklists/1')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(out,'selected.html'))});
if(u.pathname.startsWith('/api/'))return route.fulfill({contentType:'application/json',body:JSON.stringify({users:[],vehicles:[],items:[],unread_count:0})});
if(u.pathname.startsWith('/static/')){const p=path.resolve(root,'.'+u.pathname);if(!p.startsWith(root+'/static/')||!fs.existsSync(p))return route.fulfill({status:404});
if(mode==='delayed-shell'&&u.pathname.endsWith('/shell_bootstrap.js'))await new Promise(r=>setTimeout(r,1200));
const type=p.endsWith('.css')?'text/css':p.endsWith('.js')?'application/javascript':p.endsWith('.svg')?'image/svg+xml':p.endsWith('.png')?'image/png':p.endsWith('.woff2')?'font/woff2':'application/octet-stream';return route.fulfill({contentType:type,body:fs.readFileSync(p)});}
return route.fulfill({status:404});});
await page.goto('https://fixture.invalid/vehicle/checklists/1?vehicle_record_id=1&year=2026&month=10&active_day=23',{waitUntil:'load'});await page.waitForTimeout(500);
const metrics=await page.evaluate(()=>{const n=performance.getEntriesByType('navigation')[0];return {dcl:n.domContentLoadedEventEnd,load:n.loadEventEnd,domInteractive:n.domInteractive,domCount:document.querySelectorAll('*').length,...window.__diag,resources:performance.getEntriesByType('resource').map(x=>({name:new URL(x.name).pathname,duration:x.duration,initiator:x.initiatorType}))}});
assert.equal(blocked.length,0,'no external requests or writes');assert(await page.locator('#vehicle_workspace_date').isVisible());
await page.screenshot({path:path.join(out,`${width}-${mode}-${repeat}.png`)});
report.push({width,mode,repeat,metrics,requests,blocked,errors});await context.close();}
fs.writeFileSync(path.join(out,'browser-timing.json'),JSON.stringify(report,null,2));}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
