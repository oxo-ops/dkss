const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const repo=process.env.PRODUCT_REPO,html=process.env.HTML_OUT,out=process.env.ARTIFACTS;fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||undefined,args:['--no-sandbox']});let report=[],blocked=[];
try{for(const width of [320,390,1440])for(const name of ['normal_office_master','normal_vehicle_type_master','normal_license_type_master','normal_delivery_place_master','normal_manual_master','normal_patrol_content_type_master','pointouts','safety_checklist_results']){
const row=JSON.parse(fs.readFileSync(path.join(html,'routes.json'))).find(x=>x.endpoint===name);assert(row);
const context=await browser.newContext({viewport:{width,height:844},serviceWorkers:'block'}),page=await context.newPage();
await page.route('**/*',route=>{const req=route.request(),url=new URL(req.url());if(req.method()!=='GET'||url.origin!=='https://fixture.invalid'){blocked.push(req.method());return route.abort();}
if(url.pathname===new URL(row.path,'https://fixture.invalid').pathname)return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,name+'.html'),'utf8')});
if(url.pathname.startsWith('/static/')){const f=path.resolve(repo,'.'+url.pathname);if(f.startsWith(repo+'/static/')&&fs.existsSync(f))return route.fulfill({path:f});}
return route.fulfill({status:404,body:'offline'});});
await page.goto(new URL(row.path,'https://fixture.invalid').href);const button=page.locator('a.entry-add-icon').first();assert.equal((await button.innerText()).trim(),'＋');assert(await button.getAttribute('aria-label'));const box=await button.boundingBox();assert(box&&Math.abs(box.width-44)<1&&Math.abs(box.height-44)<1,JSON.stringify({name,width,box}));assert(box.x>=0&&box.x+box.width<=width+1);
const look=await button.evaluate(e=>({radius:getComputedStyle(e).borderRadius,font:getComputedStyle(e).fontSize}));assert.equal(look.radius,'50%');assert.equal(look.font,'24px');const href=await button.getAttribute('href');assert(href.includes('/new'));
if(name==='normal_office_master'){const hint=await page.locator('.master-order-help').boundingBox();assert(Math.abs(box.y+22-hint.y-hint.height/2)<2);assert.equal(await page.locator('.page-header').count(),0);}
await page.screenshot({path:path.join(out,name+'-'+width+'.png')});report.push({name,width,href,box,passed:true});await context.close();}
assert.equal(blocked.length,0);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({report,blocked},null,2));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
