const fs=require('fs'),path=require('path'),assert=require('assert');const{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),dir=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({headless:true});let cases=[];try{
for(const width of [390,1316])for(const mode of ['detail','edit']){
 const context=await browser.newContext({viewport:{width,height:844},serviceWorkers:'block'}),page=await context.newPage();let writes=0;
 await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin!=='https://fixture.invalid')return r.abort();if(r.request().method()!=='GET'){writes++;return r.abort();}
 let f=u.pathname==='/'?path.join(dir,mode+'.html'):u.pathname.startsWith('/files/')?path.join(dir,'original.jpg'):path.join(repo,u.pathname);
 if(!fs.existsSync(f))return r.fulfill({status:404,body:''});const ext=path.extname(f);return r.fulfill({status:200,contentType:({'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.jpg':'image/jpeg','.png':'image/png','.svg':'image/svg+xml'})[ext]||'application/octet-stream',body:fs.readFileSync(f)});});
 await page.goto('https://fixture.invalid/');const img=page.locator(mode==='detail'?'.checklist-result-attachment-image':'.saved-file-preview-image').first();
 await img.scrollIntoViewIfNeeded();await img.evaluate(e=>e.decode());assert.equal(await img.getAttribute('loading'),'lazy');assert.equal(await img.getAttribute('decoding'),'async');assert.equal(await img.getAttribute('src'),'/files/uploads/avatar.jpg');
 const b=await img.boundingBox();assert(b.width>20&&b.x>=0&&b.x+b.width<=width+1);await page.screenshot({path:path.join(out,mode+'-'+width+'.png')});
 const promise=page.waitForEvent('popup');await img.click();const popup=await promise;await popup.waitForLoadState();assert(popup.url().endsWith('/files/uploads/avatar.jpg'));await popup.close();assert.equal(writes,0);cases.push({mode,width,passed:true,writes});await context.close();
}fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(cases,null,2));}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});