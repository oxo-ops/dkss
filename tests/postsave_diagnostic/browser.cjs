// Diagnostic only: real Flask-rendered synthetic template, all routes isolated.
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'/opt/codex/cua_node/lib/node_modules/playwright');
const root=process.env.PRODUCT_REPO||'/workspace/shared/attachment-detail-display';
const here=__dirname; const report=[];
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
try{for(const width of [390,1440])for(const mode of ['slow200','404']){
 const context=await browser.newContext({viewport:{width,height:900}});const page=await context.newPage();let good=mode==='slow200',release,requested=0;
 const gate=new Promise(r=>release=r);
 await context.route('**/*',async r=>{const u=new URL(r.request().url());if(u.origin!=='https://fixture.invalid')return r.abort();
 if(u.pathname==='/detail')return r.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(here,'html/detail.html'))});
 if(u.pathname.startsWith('/static/')){const p=path.resolve(root,'.'+u.pathname);if(!p.startsWith(root+'/static/')||!fs.existsSync(p))return r.fulfill({status:404});return r.fulfill({body:fs.readFileSync(p),contentType:p.endsWith('.css')?'text/css':p.endsWith('.js')?'application/javascript':'application/octet-stream'});}
 if(u.pathname==='/files/uploads/avatar.jpg'){requested++;if(mode==='slow200')await gate;if(!good)return r.fulfill({status:404,body:'File not found'});return r.fulfill({contentType:'image/webp',body:fs.readFileSync(path.join(here,'html/display-1280.webp'))});}
 return r.fulfill({status:404});});
 await page.goto('https://fixture.invalid/detail',{waitUntil:'domcontentloaded'});
 const img=page.locator('.detail-image').first();await img.scrollIntoViewIfNeeded();await page.waitForFunction(()=>{const e=document.querySelector('.detail-image');return e&&e.currentSrc;});
 if(mode==='slow200'){await page.waitForTimeout(300);const pending=await img.evaluate(e=>({complete:e.complete,w:e.naturalWidth}));assert.equal(pending.w,0);await page.screenshot({path:path.join(here,`pending-${width}.png`)});release();await img.evaluate(e=>e.decode());report.push({width,mode,pending,loaded:await img.evaluate(e=>e.naturalWidth)});}
 else{await page.waitForFunction(()=>document.querySelector('.detail-image').complete);assert.equal(await img.evaluate(e=>e.naturalWidth),0);good=true;await page.waitForTimeout(500);const requestsBeforeReload=requested;assert.equal(await img.evaluate(e=>e.naturalWidth),0);await page.screenshot({path:path.join(here,`failed-${width}.png`)});await page.reload({waitUntil:'domcontentloaded'});await img.scrollIntoViewIfNeeded();await img.evaluate(e=>e.decode());report.push({width,mode,requestsBeforeReload,recoveredOnReload:true});}
 await context.close();}
 fs.writeFileSync(path.join(here,'browser-report.json'),JSON.stringify(report,null,2));}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
