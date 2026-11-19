const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),html=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);
(async()=>{fs.mkdirSync(out,{recursive:true});let browser,page,rows=[],blocked=[],posts=0;try{browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
for(const width of [320,390,768,1316])for(const role of ['driver','manager'])for(const scale of [1,2]){
const c=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});await c.routeWebSocket('**/*',s=>{blocked.push('WS');s.close()});page=await c.newPage();
await page.addInitScript(()=>localStorage.setItem('dkss:first-guide:v1:demo:pointouts','1'));
await c.route('**/*',route=>{const r=route.request(),u=new URL(r.url());if(r.method()!=='GET'){posts++;return route.abort()}if(u.origin!=='https://fixture.invalid'){blocked.push(u.origin);return route.abort()}
if(u.pathname==='/pointouts')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,role+(u.searchParams.get('keyword')==='NO_MATCH_42'?'-empty':u.searchParams.get('category')==='Good'&&u.searchParams.get('keyword')?'-filtered':'')+'.html'),'utf8')});
const id=u.pathname.match(/^\/pointouts\/(\d+)$/);if(id)return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,role+'-detail-'+id[1]+'.html'),'utf8')});
if(u.pathname.includes('synthetic.png'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="90"><rect width="120" height="90" fill="#b6ccde"/><path d="M10 70L50 20L90 70Z" fill="#405d70"/></svg>'});
const f=path.resolve(repo,'.'+u.pathname);if(u.pathname.startsWith('/static/')&&f.startsWith(repo+'/static/')&&fs.existsSync(f))return route.fulfill({path:f});return route.fulfill({status:404,body:'fixture offline'});});
await page.goto('https://fixture.invalid/pointouts');await page.evaluate(()=>document.fonts.ready);if(await page.locator('#firstGuidePanel').isVisible())await page.keyboard.press('Escape');
if(scale===2)await page.evaluate(()=>{const v=[...document.querySelectorAll('.safety-results-mobile-list *')].map(e=>[e,parseFloat(getComputedStyle(e).fontSize)]);for(const[e,n]of v)e.style.fontSize=n*2+'px'});
const list=page.locator('.safety-results-mobile-list'),cards=list.locator('.safety-result-mobile-card');assert.equal(await cards.count(),5);assert.equal(await list.isVisible(),width<=768);
const filter=page.locator('.patrol-filter-disclosure');
const form=filter.locator('form');
if(width<=768){
assert(!(await form.isVisible()),'mobile filter must start collapsed');
await filter.locator('summary').click();
assert(await form.isVisible());
await form.locator('[name=keyword]').fill('通路');
await form.locator('[name=category]').selectOption('Good');
await filter.locator('summary').click();
assert(!(await form.isVisible()));
await filter.locator('summary').click();
assert.equal(await form.locator('[name=keyword]').inputValue(),'通路');
assert.equal(await form.locator('[name=category]').inputValue(),'Good');
await filter.locator('summary').click();
assert(await cards.evaluateAll(es=>es.every(e=>e.scrollWidth<=e.clientWidth+1)),'list internal overflow');
assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page overflow');
for(const card of await cards.all()){assert(!(await card.locator('.mobile-card-content').isVisible()));const summary=card.locator('summary');assert((await summary.boundingBox()).height>=44);assert((await card.locator('.safety-result-mobile-detail').boundingBox()).height>=44);}
await page.screenshot({path:path.join(out,role+'-'+width+'-'+scale+'x-list.png'),fullPage:true});
const card=cards.nth(1),summary=card.locator('summary');await summary.click();assert(await card.locator('.mobile-card-content').isVisible());assert((await card.locator('.mobile-card-content').innerText()).includes('負傷なし'));assert(await card.evaluate(e=>e.scrollWidth<=e.clientWidth+1));
await page.screenshot({path:path.join(out,role+'-'+width+'-'+scale+'x-open.png'),fullPage:true});await summary.press('Enter');assert(!(await card.locator('.mobile-card-content').isVisible()));
const first=cards.first();await first.locator('summary').click();const image=first.locator('img');await image.scrollIntoViewIfNeeded();await image.evaluate(e=>e.decode());assert(await image.evaluate(e=>e.naturalWidth>0));await first.locator('summary').click();
await first.locator('.safety-result-mobile-detail').click();await page.waitForURL(/\/pointouts\/\d+$/);assert((await page.locator('body').innerText()).includes('安全パトロール詳細'));await page.goBack();await list.waitFor({state:'visible'});
}else{assert(await form.isVisible(),'PC form stays available');await page.screenshot({path:path.join(out,role+'-'+width+'-'+scale+'x-pc.png'),fullPage:true});}
// Exercise original GET submission, retained conditions, zero results and full reset.
if(width<=768)await filter.locator('summary').click();
await form.locator('[name=keyword]').fill('通路');
await form.locator('[name=category]').selectOption('Good');
await form.getByRole('button',{name:'絞り込み',exact:true}).click();
await page.waitForURL(u=>u.searchParams.get('keyword')==='通路');
assert.equal(new URL(page.url()).searchParams.get('category'),'Good');
assert.equal(await page.locator('.safety-result-mobile-card').count(),1);
if(width<=768)await filter.locator('summary').click();
assert.equal(await form.locator('[name=keyword]').inputValue(),'通路');
await form.locator('[name=keyword]').fill('NO_MATCH_42');
await form.getByRole('button',{name:'絞り込み',exact:true}).click();
await page.waitForURL(u=>u.searchParams.get('keyword')==='NO_MATCH_42');
assert.equal(await page.locator('.safety-result-mobile-card').count(),0);
if(width<=768)await filter.locator('summary').click();
await form.getByRole('link',{name:'条件をクリア',exact:true}).click();
await page.waitForURL(u=>!u.searchParams.has('keyword'));
assert.equal(await page.locator('.safety-result-mobile-card').count(),5);
rows.push({width,role,scale,passed:true,text_scale_not_native_zoom:true,filter_submit_and_reset:true});await c.close();page=null;
}assert.equal(rows.length,16);assert.deepEqual(blocked,[]);assert.equal(posts,0);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({rows,blocked,posts,live:false}));
}catch(e){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({rows,blocked,posts,error:String(e)}));if(page)await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw e}finally{if(browser)await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
