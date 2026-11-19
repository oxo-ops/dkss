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
  // Dismiss the genuine first-visit guide before testing toolbar operations.
  const guideClose=page.locator('[data-guide-close]').filter({visible:true});
  if(await guideClose.count())await guideClose.click();
  const excel=page.locator('[data-plan-export]');assert(await excel.isVisible());assert(!await page.locator('[data-plan-export-mobile]').isVisible());assert.equal(await excel.getAttribute('aria-label'),'Excel出力');assert.equal((await excel.innerText()).trim(),'');
  const info=await excel.evaluate(e=>{const r=e.getBoundingClientRect(),n=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {width:r.width,height:r.height,right:r.right,hit:n===e||e.contains(n),color:getComputedStyle(e).color,parent:e.parentElement.className,blocker:n?.outerHTML.slice(0,300)}});
  assert(info.width>=44&&info.height>=44&&info.right<=width&&info.hit,JSON.stringify(info));assert.equal(info.color,'rgb(35, 117, 75)');assert.equal(await excel.evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)');assert.equal(await excel.evaluate(e=>getComputedStyle(e).borderTopWidth),'0px');assert.equal(await excel.locator('svg rect[fill="#23754b"]').count(),1);assert.equal(await excel.locator('svg path[stroke="#fff"]').count(),2);assert(info.parent.includes('ip-top-actions'));
  // Native click keeps original endpoint/query and downloads an Excel workbook.
  const url=await excel.getAttribute('href');const exportURL=new URL(url,base),pageURL=new URL(page.url());assert.equal(exportURL.pathname,'/vehicle/inspection-plans/export.xlsx');for(const [k,v] of pageURL.searchParams)assert.equal(exportURL.searchParams.get(k),v,'export condition '+k);assert.equal(exportURL.searchParams.get('year'),'2025');const response=await c.request.get(base+url);assert.equal(response.status(),200);assert(response.headers()['content-type'].includes('spreadsheetml'));assert(response.headers()['content-disposition'].includes('.xlsx'));const expectedBytes=await response.body();const downloadPromise=page.waitForEvent('download');await excel.click();const download=await downloadPromise;const filename=download.suggestedFilename();console.log(JSON.stringify({width,view,filename,url}));assert.equal(await download.failure(),null);await download.saveAs(out+`/download-${width}-${view}.xlsx`);assert(fs.readFileSync(out+`/download-${width}-${view}.xlsx`).subarray(0,2).equals(Buffer.from('PK')));assert(expectedBytes.subarray(0,2).equals(Buffer.from('PK')));
  await page.screenshot({path:out+`/excel-${width}-${view}.png`});
  if(width<=700){for(const selector of ['[data-plan-view-toggle]','[data-plan-filter-toggle]','[data-plan-search-toggle]','[data-guide-open]']){const e=page.locator(selector).filter({visible:true});if(await e.count()){assert(await e.evaluate(el=>{const r=el.getBoundingClientRect(),n=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return n===el||el.contains(n)}),selector)}}}
  report.push({width,view,...info,url,download:true,passed:true});
 }
 for(const [i,path] of fixture.extra_paths.entries()){
  await page.goto(base+path);const close=page.locator('[data-guide-close]:visible');if(await close.count())await close.click();
  const e=page.locator('a.excel-icon-action');assert.equal(await e.count(),1);assert(await e.isVisible());
  assert.equal(await e.getAttribute('aria-label'),'Excel出力');assert.equal((await e.innerText()).trim(),'');
  assert.equal(await e.locator('svg rect[fill="#23754b"]').count(),1);
  assert.equal(await e.evaluate(el=>getComputedStyle(el).backgroundColor),'rgba(0, 0, 0, 0)');
  assert(await e.evaluate(el=>{const r=el.getBoundingClientRect();return r.width>=44&&r.height>=44}));
  const href=await e.getAttribute('href');assert(href.endsWith('/excel'));const res=await c.request.get(base+href);assert.equal(res.status(),200);assert((await res.body()).subarray(0,2).equals(Buffer.from('PK')));
  const dp=page.waitForEvent('download');await e.click();const dl=await dp;assert.equal(await dl.failure(),null);await dl.saveAs(out+`/extra-${width}-${i}.xlsx`);
  await page.screenshot({path:out+`/extra-${width}-${i}.png`});report.push({width,path,export:href,passed:true});
 }
 assert.deepEqual(blocked,[]);await c.close();page=null;
}fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));}
catch(e){if(page)await page.screenshot({path:out+'/failure.png'}).catch(()=>{});throw e}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
