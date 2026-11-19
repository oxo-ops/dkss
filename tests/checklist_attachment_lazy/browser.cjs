const fs=require('fs'),path=require('path'),assert=require('assert');const{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),dir=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({headless:true});let cases=[];try{
for(const width of [320,390,768,1316])for(const mode of ['detail','edit']){
 const context=await browser.newContext({viewport:{width,height:844},serviceWorkers:'block'}),page=await context.newPage();let writes=0;
 await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin!=='https://fixture.invalid')return r.abort();if(r.request().method()!=='GET'){writes++;return r.abort();}
 let f=u.pathname==='/'?path.join(dir,mode+'.html'):u.pathname.startsWith('/files/')?path.join(dir,'original.jpg'):path.join(repo,u.pathname);
 if(!fs.existsSync(f))return r.fulfill({status:404,body:''});const ext=path.extname(f);return r.fulfill({status:200,contentType:({'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.jpg':'image/jpeg','.png':'image/png','.svg':'image/svg+xml'})[ext]||'application/octet-stream',body:fs.readFileSync(f)});});
 await page.goto('https://fixture.invalid/');
 if(mode==='detail'){
  const header=page.locator('.checklist-result-detail-header'),excel=header.locator('a[href$="/excel"]');
  const href=await excel.getAttribute('href');assert(href&&href.startsWith('/safety/checklist-results/'));
  assert.equal(await header.evaluate(e=>getComputedStyle(e).position),'static');
  await page.screenshot({path:path.join(out,'detail-top-'+width+'.png')});
  // Repeat real rendered content to exercise a genuinely scrollable result, not a short-page clamp.
  await page.locator('.result-info-card').evaluate(e=>{for(let i=0;i<3;i++)e.parentElement.append(e.cloneNode(true))});
  const before=await header.boundingBox();
  await page.evaluate(()=>window.scrollBy(0,500));
  const dy=await page.evaluate(()=>scrollY),after=await header.boundingBox();
  assert(dy>=499,'long fixture must scroll the requested distance');assert(after.y+after.height<0,'result title and Excel must leave viewport');assert(Math.abs(before.y-after.y-dy)<2,'heading must travel with document');
  await page.screenshot({path:path.join(out,'detail-scrolled-'+width+'.png')});
  await page.evaluate(()=>window.scrollTo(0,0));
  await excel.click();await page.waitForURL(u=>u.pathname.endsWith('/excel'));assert(page.url().endsWith(href));
  await page.goto('https://fixture.invalid/');
 }
 const img=page.locator(mode==='detail'?'.checklist-result-attachment-image':'.saved-file-preview-image').first();
 await img.scrollIntoViewIfNeeded();await img.evaluate(e=>e.decode());assert.equal(await img.getAttribute('loading'),'lazy');assert.equal(await img.getAttribute('decoding'),'async');assert.equal(await img.getAttribute('src'),'/files/uploads/avatar.jpg');
 const b=await img.boundingBox();assert(b.width>20&&b.x>=0&&b.x+b.width<=width+1);await page.screenshot({path:path.join(out,mode+'-'+width+'.png')});
 const promise=page.waitForEvent('popup');await img.click();const popup=await promise;await popup.waitForLoadState();assert(popup.url().endsWith('/files/uploads/avatar.jpg'));await popup.close();assert.equal(writes,0);cases.push({mode,width,passed:true,writes});await context.close();
}fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(cases,null,2));}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
