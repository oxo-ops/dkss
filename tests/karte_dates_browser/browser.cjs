const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const repo=process.env.PRODUCT_REPO,html=process.env.HTML_OUT,out=process.env.ARTIFACTS;fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||undefined,args:['--no-sandbox']});let report=[],blocked=[];
try{for(const width of [320,390,1440])for(const name of ['vehicle_karte_maintenance','vehicle_karte_inspections']){
const row=JSON.parse(fs.readFileSync(path.join(html,'routes.json'))).find(x=>x.endpoint===name);assert(row);
const context=await browser.newContext({viewport:{width,height:844},serviceWorkers:'block'}),page=await context.newPage();
await page.route('**/*',route=>{const req=route.request(),url=new URL(req.url());if(req.method()!=='GET'||url.origin!=='https://fixture.invalid'){blocked.push(req.method());return route.abort();}
if(url.pathname===new URL(row.path,'https://fixture.invalid').pathname)return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,name+'.html'),'utf8')});
if(url.pathname.startsWith('/static/')){const f=path.resolve(repo,'.'+url.pathname);if(f.startsWith(repo+'/static/')&&fs.existsSync(f))return route.fulfill({path:f});}
return route.fulfill({status:404,body:'offline'});});
await page.goto(new URL(row.path,'https://fixture.invalid').href);
const dates=page.locator('.karte-date-mobile');assert(await dates.count()>0);
for(const date of await dates.all()){const duplicate=await date.evaluate(e=>Boolean(e.closest('.karte-date-duplicate')));assert.equal(await date.isVisible(),width<=768&&!duplicate);}
if(name==='vehicle_karte_maintenance'){
 const cell=page.locator('.km-record-date').first();const text=await cell.innerText();
 if(width<=768){assert.equal(text.trim(),'11/18');assert.equal(await cell.locator('.karte-date-duplicate').isVisible(),false);}else{assert(text.includes('2026/11/18'));assert.equal(await cell.locator('.karte-date-duplicate').isVisible(),true);}
}
const href=row.path,box={};
await page.screenshot({path:path.join(out,name+'-'+width+'.png')});report.push({name,width,href,box,passed:true});await context.close();}
assert.equal(blocked.length,0);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({report,blocked},null,2));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
