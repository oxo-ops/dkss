// Native operation acceptance against disposable synthetic SQLite only.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright'),fs=require('fs'),assert=require('node:assert/strict');
const fixture=JSON.parse(fs.readFileSync(process.argv[2])),out=process.argv[3],base='http://127.0.0.1:'+fixture.port;
(async()=>{fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:process.env.Q12_BROWSER_EXECUTABLE||undefined}),report=[];let page;
try{for(const width of [320,390,768,1316]){
 const c=await browser.newContext({viewport:{width,height:900},acceptDownloads:true,serviceWorkers:'block'}),blocked=[];
 await c.addCookies([{name:'dkss_session',value:fixture.cookie,url:base}]);
 await c.route('**/*',r=>{if(new URL(r.request().url()).origin!==base||r.request().method()!=='GET'){blocked.push(r.request().method());return r.abort()}return r.continue()});
 page=await c.newPage();
 for(const view of ['month','calendar','year']){
  await page.goto(base+'/vehicle/inspection-plans?view='+view+'&month=2026-02');await page.waitForSelector('[data-plan-export].ip-excel-action');
  const excel=page.locator('[data-plan-export]');assert(await excel.isVisible());assert(!await page.locator('[data-plan-export-mobile]').isVisible());assert.equal(await excel.getAttribute('aria-label'),'Excel出力');assert.equal((await excel.innerText()).trim(),'');
  const info=await excel.evaluate(e=>{const r=e.getBoundingClientRect(),n=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {width:r.width,height:r.height,right:r.right,hit:n===e||e.contains(n),color:getComputedStyle(e).color,parent:e.parentElement.className}});
  assert(info.width>=44&&info.height>=44&&info.right<=width&&info.hit,JSON.stringify(info));assert.equal(info.color,'rgb(35, 117, 75)');assert(info.parent.includes('ip-top-actions'));
  // Native click keeps original endpoint/query and downloads an Excel workbook.
  const url=await excel.getAttribute('href');assert(url.includes('excel'));const downloadPromise=page.waitForEvent('download');await excel.click();const download=await downloadPromise;assert(/\.xlsx$/i.test(download.suggestedFilename()));assert.equal(await download.failure(),null);
  await page.screenshot({path:out+`/excel-${width}-${view}.png`});
  if(width<=700){for(const selector of ['[data-plan-view-toggle]','[data-plan-filter-toggle]','[data-plan-search-toggle]','[data-guide-open]']){const e=page.locator(selector).filter({visible:true});if(await e.count()){assert(await e.evaluate(el=>{const r=el.getBoundingClientRect(),n=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return n===el||el.contains(n)}),selector)}}}
  report.push({width,view,...info,url,download:true,passed:true});
 }
 assert.deepEqual(blocked,[]);await c.close();page=null;
}fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));}
catch(e){if(page)await page.screenshot({path:out+'/failure.png'}).catch(()=>{});throw e}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
