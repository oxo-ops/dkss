/* Actual template/JS/CSS, disposable synthetic HTML only. No image enlargement. */
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'/opt/codex/cua_node/lib/node_modules/playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),out=path.resolve(process.env.ARTIFACTS),dir=path.join(process.env.HTML_OUT,'inspection-states');
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM?{executablePath:process.env.CHROMIUM}:{}),args:['--no-sandbox']});let posts=0;const cases=[];try{
for(const width of [390,1316])for(const row of JSON.parse(fs.readFileSync(path.join(dir,'states.json')))){
 const context=await browser.newContext({viewport:{width,height:1000},deviceScaleFactor:3}),page=await context.newPage();const pageErrors=[];page.on('pageerror',e=>pageErrors.push(String(e)));console.log('inspection-case',width,row.role,row.code);

 const url=new URL(row.path,'https://fixture.invalid');
 await page.route('**/*',async route=>{const req=route.request(),u=new URL(req.url());if(req.method()!=='GET'){posts++;return route.abort()}if(u.origin!==url.origin)return route.abort();
 if(u.pathname===url.pathname)return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(dir,row.file),'utf8')});
 if(u.pathname.startsWith('/static/')){const file=path.resolve(repo,'.'+u.pathname);if(file.startsWith(repo+'/static/')&&fs.existsSync(file))return route.fulfill({path:file});}
 return route.fulfill({status:404,body:'offline fixture'});});
 await page.goto(url.href);const panel=page.locator('#firstGuidePanel'),titles=[];
 if(row.editable||row.code==='unselected'){try{await panel.waitFor({state:'visible'});}catch(error){const diagnostic=await page.evaluate(()=>({url:location.pathname,active:document.activeElement?.id,ready:document.readyState,seen:localStorage.getItem('dkss:first-guide:v1:demo:vehicle_checklist_results'),rootHidden:document.getElementById('firstUseGuide')?.hidden,search:[...document.querySelectorAll('#vehicle_search')].map(e=>({rects:e.getClientRects().length,visibility:getComputedStyle(e).visibility,hidden:!!e.closest('[hidden],[inert]')})),dialogs:document.querySelectorAll('dialog[open],.modal-bg.is-open,.ka-reference-drawer:not([hidden])').length}));console.log('initial-guide-diagnostic',JSON.stringify({width,role:row.role,code:row.code,pageErrors,...diagnostic}));await page.screenshot({path:path.join(out,`${width}-${row.role}-${row.code}-initial-failure.png`)});throw error;}assert(await panel.isVisible(),'editable first-use guide opens');}else{await page.locator('[data-guide-open]').click();}

 while(await panel.isVisible()){assert(titles.length<12);titles.push(await page.locator('[data-guide-title]').innerText());if(titles.at(-1)==='項目の詳細を見る')assert((await page.locator('[data-guide-text]').innerText()).includes('水色はコメントや写真・添付がある印'));await page.locator('[data-guide-next]').click();}
 if(row.code==='unselected'){assert.deepEqual(titles,['車両を選ぶ']);}else if(row.editable){for(const title of ['項目の詳細を見る','評価を入れる','依頼先を選ぶ','点検を完了する'])assert(titles.includes(title),row.role+'/'+row.code+': '+title);assert(titles.some(x=>x.includes('点検未実施通知先')))}else{assert.deepEqual(titles,['項目の詳細を見る'])}
 if(row.editable){
  await page.locator('[data-guide-open]').click();
  while((await page.locator('[data-guide-title]').innerText())!=='項目の詳細を見る')await page.locator('[data-guide-next]').click();
  const detailOpener=page.locator('.inspection-item-detail').first();
  await detailOpener.focus();await detailOpener.press('Enter');
  await page.waitForFunction(()=>document.activeElement===document.getElementById('detailTitle'));
  assert(!(await panel.isVisible()));assert.equal(await page.locator('[data-guide-open] span:last-child').innerText(),'案内を再開');
  await page.locator('#detailModal .js-close-detail-modal').click();
  assert(await detailOpener.evaluate(e=>document.activeElement===e),'close restores original item focus');
  await page.locator('[data-guide-open]').click();assert.equal(await page.locator('[data-guide-title]').innerText(),'評価を入れる');
  await page.screenshot({path:path.join(out,`${width}-${row.role}-${row.code}-guide-resumed.png`)});
  await page.locator('[data-guide-close]').click();assert.equal(await page.locator('[data-guide-open] span:last-child').innerText(),'使い方');
 }
 if(width===390&&row.role==='manager'&&row.code==='input'){
  await page.locator('.inspection-item-detail').first().click();const box=page.locator('#detailModal .modal-box');await box.waitFor({state:'visible'});
  assert(await box.locator('#detailCriteriaText').innerText());assert(await box.locator('#detailCommentEditor[contenteditable="true"]').isVisible());
  await box.screenshot({path:path.join(out,'inspection-detail-open-3x.png')});
  const b=await box.boundingBox();assert(b.width>300);cases.push({capture:true,cssWidth:b.width,dpr:3,no_resampling:true});
  await box.locator('.js-close-detail-modal').click();
 }
 cases.push({width,role:row.role,status:row.status,titles});await context.close();
}assert.equal(posts,0);fs.writeFileSync(path.join(out,'inspection-guide-states.json'),JSON.stringify({cases,posts,synthetic:true,live:false},null,2));}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
