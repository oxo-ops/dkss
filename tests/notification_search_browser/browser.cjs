/* Only synthetic actual GET response snapshots; native IME not claimed. */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict'),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(process.env.PRODUCT_REPO),html=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS),data=JSON.parse(fs.readFileSync(path.join(html,'routes.json')));
function canonical(u){const p=new URL(u,'https://fixture.invalid');p.searchParams.sort();return p.pathname+p.search}
(async()=>{fs.mkdirSync(out,{recursive:true});const b=await chromium.launch({headless:true}),report=[];let page;try{
for(const width of [320,390,768,1316]){const c=await b.newContext({viewport:{width,height:900},serviceWorkers:'block'}),blocked=[];
await c.routeWebSocket('**/*',w=>{blocked.push('WS');w.close()});
await c.route('**/*',r=>{const q=r.request(),u=new URL(q.url());if(q.method()!=='GET'||u.origin!=='https://fixture.invalid'){blocked.push(q.method());return r.abort()}
const route=data.routes.find(x=>canonical(x.path)===canonical(q.url()));if(route)return r.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,route.key+'.html'),'utf8')});
const file=path.resolve(root,'.'+u.pathname);if(u.pathname.startsWith('/static/')&&file.startsWith(root+'/static/')&&fs.existsSync(file))return r.fulfill({path:file});
return r.fulfill({status:404,body:'offline fixture'});});
page=await c.newPage();await page.goto('https://fixture.invalid'+data.routes[0].path);
const input=page.locator('#notificationSearch'),form=page.locator('#notificationFilterForm'),clear=page.locator('.query-clear-button');
assert.equal(await input.inputValue(),'表示確認');assert.equal(await page.locator('.notification-filter-reset').count(),0);
await clear.click();assert.equal(await input.inputValue(),'');assert(!await clear.isVisible());assert(await input.evaluate(e=>e===document.activeElement));
assert.equal(await form.locator('[name=category]').inputValue(),data.category);assert.equal(await form.locator('[name=type]').inputValue(),data.type);
await form.locator('button[type=submit]').click();await page.waitForURL(u=>u.searchParams.get('q')==='');
assert.equal(await form.locator('[name=category]').inputValue(),data.category);assert.equal(await form.locator('[name=type]').inputValue(),data.type);assert(await page.locator('.empty-text').isVisible());
await page.goBack();await page.waitForURL(u=>u.searchParams.get('q')==='表示確認');assert.equal(await input.inputValue(),'表示確認');
await input.fill('存在しない通知検索');await form.locator('button[type=submit]').click();await page.waitForURL(u=>u.searchParams.get('q')==='存在しない通知検索');
assert(await page.locator('.empty-text').isVisible());assert.equal(await form.locator('[name=category]').inputValue(),data.category);
const box=await clear.boundingBox();assert(box.width>=44&&box.height>=44);assert(box.x>=0&&box.x+box.width<=width+1);
await page.screenshot({path:out+'/notifications-'+width+'.png',fullPage:true});
await page.locator('.notification-filter-reset-all').click();await page.waitForURL(u=>!u.searchParams.has('category'));
assert.equal(await input.inputValue(),'');assert.equal(await form.locator('[name=category]').inputValue(),'');assert.equal(await form.locator('[name=type]').inputValue(),'');assert.equal(await form.locator('[name=view]').inputValue(),'unread');assert(!await clear.isVisible());
assert.deepEqual(blocked,[]);report.push({width,passed:true,postCount:0,getSnapshots:true,back:true,zeroResults:true,realIME:false});await c.close();page=null;}
fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));
}catch(e){if(page)await page.screenshot({path:out+'/failure.png',fullPage:true}).catch(()=>{});throw e}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
