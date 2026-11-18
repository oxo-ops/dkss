/* Synthetic-only browser fixture; extracts the product renderer, no app credentials. */
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=process.env.PRODUCT_REPO||process.cwd(),out=process.env.ARTIFACTS||'/tmp/attachment-safe';
fs.mkdirSync(out,{recursive:true});
const js=fs.readFileSync(path.join(repo,'static/js/vehicle_checklist_results.js'),'utf8');
const fn=js.slice(js.indexOf('    function renderFiles('),js.indexOf('    document.querySelectorAll(".js-vehicle-defect-files")'));
assert(fn.includes('img.loading = "lazy"'));assert(fn.includes('img.decoding = "async"'));
const template=fs.readFileSync(path.join(repo,'templates/pointout_detail.html'),'utf8');
const links=[...template.matchAll(/<a href="([^"]+)"\s+target="_blank" rel="noopener" aria-label="画像の原本を開く"><img\s+src="([^"]+)"\s+class="detail-image" loading="lazy" decoding="async" alt="添付画像"\s*><\/a>/g)];
assert.equal(links.length,3);
for(const link of links){assert.equal(link[1],link[2]);assert(link[1].includes("url_for('uploaded_file', folder='uploads', filename=file)"));}
assert(!template.includes('preview='));
const requests=[],external=[],cases=[];
const png=Buffer.from('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','base64');
const server=http.createServer((req,res)=>{
 if(req.url.startsWith('/files/')){requests.push(req.url);res.setHeader('Content-Type','image/png');res.setHeader('Cache-Control','no-store');return res.end(png);}
 res.setHeader('Content-Type','text/html; charset=utf-8');
 res.end('<meta name="viewport" content="width=device-width"><style>body{margin:16px;font:16px sans-serif}.preview-image,.detail-image{width:160px;height:120px;object-fit:contain}#below{margin-top:15000px}</style><h1>添付画像の隔離確認</h1><div id="visible"></div><div id="below"></div><script>'+fn+';window.renderFiles=renderFiles;renderFiles("visible","first.png,second.png,report.pdf","添付");renderFiles("below","offscreen.png","画面外");<\/script>');
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true});
 try{
 for(const width of [390,1316]){
  requests.length=0;
  const context=await browser.newContext({viewport:{width,height:844}});
  await context.route('**/*',r=>r.request().url().startsWith(origin)?r.continue():(external.push(r.request().url()),r.abort()));
  const page=await context.newPage();await page.goto(origin);
  await page.waitForFunction(()=>[...document.querySelectorAll('#visible img')].every(i=>i.complete&&i.naturalWidth));
  await page.waitForTimeout(300);
  assert(!requests.some(x=>x.includes('offscreen')),'offscreen fetched early');
  assert.deepEqual(await page.locator('#visible img').evaluateAll(xs=>xs.map(x=>x.getAttribute('src'))),['/files/uploads/first.png','/files/uploads/second.png']);
  assert.equal(await page.locator('#visible a').textContent(),'report.pdf');
  await page.screenshot({path:path.join(out,width+'-visible.png')});
  const popupPromise=page.waitForEvent('popup');await page.locator('#visible img').first().click();const popup=await popupPromise;await popup.waitForLoadState();assert(popup.url().endsWith('/files/uploads/first.png'));await popup.close();
  await page.locator('#below').scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelector('#below img').naturalWidth===320);assert(requests.includes('/files/uploads/offscreen.png'));
  // Repeated modal content refresh preserves one ordered set and original click target.
  for(let n=0;n<3;n++){await page.evaluate(()=>renderFiles('visible','second.png,first.png','添付'));assert.equal(await page.locator('#visible img').count(),2);}
  await page.evaluate(()=>renderFiles('visible','','添付'));assert.equal(await page.locator('#visible img').count(),0);
  await page.evaluate(()=>{document.getElementById('visible').innerHTML='<a href="/files/uploads/original.png" target="_blank" rel="noopener"><img src="/files/uploads/original.png" class="detail-image" loading="lazy" decoding="async" alt="添付画像"></a>';});
  await page.locator('#visible').scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelector('#visible img').naturalWidth===320);
  const pop2=page.waitForEvent('popup');await page.locator('#visible a').click();const original=await pop2;await original.waitForLoadState();assert(original.url().endsWith('/files/uploads/original.png'));await original.close();
  await page.screenshot({path:path.join(out,width+'-original-link.png')});
  cases.push({width,passed:true,offscreenDeferred:true,orderRetained:true,originalLink:true,repeatedRefresh:true,externalRequests:external.length});
  await context.close();
 }
 assert.equal(external.length,0);
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({fixtureOnly:true,notRealSafari:true,authorization:'unchanged server path; synthetic browser does not prove server auth',cases},null,2));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
