const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const repo=process.env.PRODUCT_REPO,html=process.env.HTML_OUT,out=process.env.ARTIFACTS;fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,args:['--no-sandbox']});const results=[],blocked=[];let current;
try{for(const width of[320,390,768,1440]){
 const states=JSON.parse(fs.readFileSync(path.join(html,'closed_states.json')));const canonical=u=>{const v=new URL(u,'https://fixture.invalid');return v.pathname+'?'+[...v.searchParams].filter(([k,val])=>val!==''&&!(k==='page'&&val==='1')&&!(k==='per_page'&&val==='10')).sort().map(([k,val])=>k+'='+encodeURIComponent(val)).join('&')};const stateFiles=new Map(Object.entries(states.pages).map(([u,f])=>[canonical(u),f]));
 const info=JSON.parse(fs.readFileSync(path.join(html,'routes.json'))).find(r=>r.endpoint==='vehicle_karte_documents'),selected=JSON.parse(fs.readFileSync(path.join(html,'document_selected.json'))).url;
 const context=await browser.newContext({viewport:{width,height:844},serviceWorkers:'block'}),page=await context.newPage();current=page;
 await page.route('**/*',route=>{const req=route.request(),u=new URL(req.url());if(req.method()!=='GET'||u.origin!=='https://fixture.invalid'){blocked.push(req.method());return route.abort();}if(u.pathname===new URL(info.path,'https://fixture.invalid').pathname){const f=stateFiles.get(canonical(u.href)) || (u.search===new URL(selected,'https://fixture.invalid').search?'document_selected.html':'vehicle_karte_documents.html');return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,f),'utf8')});}if(u.pathname.startsWith('/static/')){const f=path.resolve(repo,'.'+u.pathname);if(f.startsWith(repo+'/static/')&&fs.existsSync(f))return route.fulfill({path:f});}return route.fulfill({status:404,body:'offline'});});
 await page.goto(new URL(info.path,'https://fixture.invalid').href);if(await page.locator('#firstGuidePanel').isVisible())await page.locator('[data-guide-close]').click();
 const table=page.locator('.kd-document-table');assert(await table.isVisible());await table.scrollIntoViewIfNeeded();
 const cols=await table.locator('thead th').evaluateAll(es=>es.filter(e=>getComputedStyle(e).display!=='none').length);assert.equal(cols,width<768?5:8);
 if(width<768){const rect=await table.boundingBox();assert(rect.x>=0&&rect.x+rect.width<=width+1,'table stays within viewport');assert(await table.locator('.kd-date-short').first().isVisible());}
 const href=await table.locator('.kd-filename').first().getAttribute('href'),download=await table.locator('.kd-download').first().getAttribute('href');assert(href.includes('#document_preview'));assert(download);
 await table.locator('[data-document-check]').first().check();assert(await table.locator('[data-document-check]').first().isChecked());await table.locator('[data-document-check]').first().uncheck();
 await page.screenshot({path:path.join(out,'documents-'+width+'.png')});
 await table.locator('.kd-filename').first().click();await page.waitForURL(u=>u.search===new URL(selected,'https://fixture.invalid').search);
 const detail=page.locator('#document_preview');assert(await detail.isVisible());assert((await detail.innerText()).includes('登録日時'));assert((await detail.innerText()).includes('登録者'));
 await detail.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'document-detail-'+width+'.png')});
 await page.goBack();await page.waitForURL(u=>u.search===new URL(info.path,'https://fixture.invalid').search);assert.equal(await page.locator('.kd-filename').first().getAttribute('href'),href);assert.equal(await page.locator('.kd-download').first().getAttribute('href'),download);

 await page.goto('https://fixture.invalid'+states.root+'?document=closed');if(await page.locator('#firstGuidePanel').isVisible())await page.locator('[data-guide-close]').click();
 assert.equal(await page.locator('#document_preview').count(),0);
 await page.getByRole('link',{name:'次のページ',exact:true}).click();await page.waitForURL(u=>u.searchParams.get('page')==='2');assert.equal(new URL(page.url()).searchParams.get('document'),'closed');assert.equal(await page.locator('#document_preview').count(),0);
 await page.screenshot({path:path.join(out,'closed-page2-'+width+'.png')});
 await page.goto('https://fixture.invalid'+states.root+'?document=closed');
 const chosen=page.locator('.kd-filename').first();await chosen.click();await page.waitForURL(u=>u.searchParams.get('document')!=='closed');assert(await page.locator('#document_preview').isVisible());
 await page.screenshot({path:path.join(out,'reopened-'+width+'.png')});
 results.push({width,cols,href,download,passed:true});await context.close();}
 assert.equal(results.length,4);assert.equal(blocked.length,0);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({results,blocked},null,2));
}catch(e){if(current&&!current.isClosed())await current.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw e;}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
