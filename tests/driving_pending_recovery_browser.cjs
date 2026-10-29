const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {chromium}=require('playwright');
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const results=[];
(async()=>{
 const browser=await chromium.launch(process.env.RECOVERY_BROWSER_CHANNEL?{channel:process.env.RECOVERY_BROWSER_CHANNEL}:{});
 try{
  for(const width of [390,768,1390]){
   const context=await browser.newContext({viewport:{width,height:900},extraHTTPHeaders:{'X-Recovery-Fixture':fixture.key}});
   await context.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
   const page=await context.newPage();
   const control=async(action)=>{const r=await context.request.get(fixture.base+'/_recovery_fixture/'+action);assert.equal(r.status(),200);return r.json();};
   const state=()=>control('state');
   const login=async(role='admin')=>page.goto(fixture.base+'/_recovery_fixture/login?as='+role);
   const postByClick=async(button)=>{
    const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().startsWith(fixture.base+'/master/'));
    await button.click();return response;
   };
   const apply=async()=>{
    if(!await page.locator('select[name=vehicle_record_id]').count())await page.getByRole('link',{name:/登録済み車両を探す|別の車両です/}).click();
    const search=page.locator('input[data-ocr-choice-input][aria-label="登録済み車両"]');await search.fill('TEST-001');
    await page.locator('[data-ocr-choice-results] button').filter({hasText:'TEST-001'}).click();
    const select=page.locator('select[name=vehicle_record_id]');assert.equal(await select.inputValue(),data.vehicle);
    return postByClick(page.locator('form').filter({has:select}).locator('button[type=submit]'));
   };
   const choose=async(p)=>{await p.locator('#recovery-person').selectOption('confirmed-person');await p.locator('#recovery-basis').selectOption('company_record');await p.locator('[name=checked]').check();};
   let data=await control('reset');await login();await page.goto(fixture.base+data.queue);
   let response=await apply();await page.waitForLoadState('domcontentloaded');assert.equal(response.status(),409,JSON.stringify({location:response.headers().location,fields:[...new URLSearchParams(response.request().postData())].map(([k,v])=>[k,k==='csrf_token'?v.length:v]),body:(await page.locator('body').innerText()).slice(0,2000)}));
   await page.getByText('最新の状態で本人を確認し直す',{exact:true}).waitFor();
   assert.equal(await page.locator('[name=decision][value=confirmed]').count(),0);
   let s=await state();assert.equal(s.report_count,0);assert.equal(s.events.length,0);
   await page.screenshot({path:path.join(out,`${fixture.kind}-${width}-409.png`),fullPage:true});
   await page.getByText('最新の状態で本人を確認し直す',{exact:true}).click();
   assert.equal(await page.locator('#recovery-person').inputValue(),'');
   assert.equal(await page.locator('[name=evidence_reference]').inputValue(),'');
   assert.ok(await page.locator('fieldset[disabled]').count());
   const original=await context.request.get(fixture.base+data.source);assert.equal(original.status(),200);
   assert.equal(crypto.createHash('sha256').update(await original.body()).digest('hex'),data.sha256);
   await page.locator('.vehicle-document-import-preview [name=csrf_token]').evaluate(input=>input.value='');
   response=await postByClick(page.getByRole('button',{name:'根拠不足のため保留を続ける'}));assert.equal(response.status(),400);
   assert.equal((await state()).events.length,0);
   await page.goto(fixture.base+data.review);
   const stale=await context.newPage();await stale.goto(fixture.base+data.review);
   response=await postByClick(page.getByRole('button',{name:'根拠不足のため保留を続ける'}));assert.equal(response.status(),302);
   await choose(stale);
   const staleResponse=stale.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/identity'));
   await stale.getByRole('button',{name:'本人確認を記録',exact:true}).click();assert.equal((await staleResponse).status(),409);
   await stale.getByText('最新の状態で本人を確認し直す',{exact:true}).waitFor();
   s=await state();assert.equal(s.events.length,1);assert.equal(s.events[0].decision,'hold');assert.equal(s.report_count,0);
   await stale.close();await page.goto(fixture.base+data.review);await choose(page);
   await page.screenshot({path:path.join(out,`${fixture.kind}-${width}-confirmation.png`),fullPage:true});
   response=await postByClick(page.getByRole('button',{name:'本人確認を記録',exact:true}));assert.equal(response.status(),302);
   s=await state();assert.equal(s.events.length,2);assert.equal(s.report_count,0);assert.equal(s.pending_status,'pending');assert.equal(s.raw_unchanged,true);
   assert.equal(s.events[1].account_identity,data.person_uuid);assert.equal(s.events[1].evidence_reference,'');
   await login('applier');await page.goto(fixture.base+data.queue);response=await apply();assert.equal(response.status(),302);
   s=await state();assert.equal(s.report_count,1);assert.equal(s.events.length,2);assert.equal(s.grant_uuid,data.person_uuid);
   assert.equal(s.applied_by,data.applier_uuid);assert.equal(s.events[1].actor_identity,data.admin_uuid);assert.equal(s.raw_unchanged,true);
   await page.goto(fixture.base+data.review);assert.equal(await page.locator('[name=decision]').count(),0);
   await page.locator('[data-pdf-stage] canvas').first().waitFor({state:'visible'});
   await page.screenshot({path:path.join(out,`${fixture.kind}-${width}-history.png`),fullPage:true});
   await login('viewer');await page.goto(fixture.base+data.review);assert.equal(new URL(page.url()).pathname,'/');
   const forbidden=await context.request.get(fixture.base+'/safety/driving-reports/'+s.record_id,{headers:{Accept:'application/json'}});assert.equal(forbidden.status(),404);
   assert.equal((await state()).events.length,2);
   results.push({kind:fixture.kind,width,case:'recovery-hold-stale-csrf-confirm-apply-history-company-access',passed:true});
   data=await control('reset?normal=1');await login();await page.goto(fixture.base+data.queue);
   assert.equal(await page.getByText(/：原本と本人を確認/).count(),0);response=await apply();assert.equal(response.status(),302);
   s=await state();assert.equal(s.report_count,1);assert.equal(s.events.length,0);assert.equal(s.raw_unchanged,true);
   results.push({kind:fixture.kind,width,case:'normal-pending-without-extra-review',passed:true});
   data=await control('reset?count=12');await login();await page.goto(fixture.base+data.queue);
   const links=page.getByRole('link',{name:/：原本と本人を確認/});assert.equal(await links.count(),12);
   await links.last().click();await page.locator('#identity-confirmation').waitFor();
   assert.equal(await page.locator('fieldset[disabled]').count(),1);
   results.push({kind:fixture.kind,width,case:'all-twelve-saved-documents-reachable',passed:true});
   await context.close();
  }
 }finally{await browser.close();fs.writeFileSync(path.join(out,'results-'+fixture.kind+'.json'),JSON.stringify(results,null,2));}
 console.log(JSON.stringify(results));
})().catch(error=>{console.error(error);process.exitCode=1;});
