/* Q03 unverified browser acceptance only; reuses Q10 Playwright conventions. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
assert.equal(fixture.marker,'Q03_BROWSER_ONLY');assert.equal(new URL(fixture.url).hostname,'127.0.0.1');
const out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});
const results={marker:fixture.marker,csrf:true,source:process.env.Q03_SOURCE_SHA,cases:[],blockedOrigins:[]};
const save=()=>fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(results,null,2));
const state=async page=>{const r=await page.request.get(fixture.url+'/__q03__/state');assert.equal(r.status(),200);const s=await r.json();assert.equal(s.marker,fixture.marker);assert.equal(s.csrf_enabled,true);return s;};
async function login(page,user){await page.goto(fixture.url+'/login');for(const[k,v]of Object.entries({company_code:fixture.company,username:user,password:fixture.password}))await page.locator(`[name=${k}]`).fill(v);await page.getByRole('button',{name:'ログイン',exact:true}).click();await page.waitForURL(u=>u.pathname!='/login');}
async function screenshot(page,name){await page.screenshot({path:path.join(out,name+'.png'),fullPage:false});fs.writeFileSync(path.join(out,name+'.html'),await page.content());}
async function submit(page,form,button){const action=await form.getAttribute('action');const wait=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname===action);await button.click();return await wait;}
async function viewAnswer(page,info,prefix){if(info.kind==='vehicle'){await page.locator('.js-open-text').filter({visible:true}).filter({hasText:prefix.slice(0,2)}).first().click();await page.locator('#textModal').waitFor({state:'visible'});assert.ok((await page.locator('#textModal').innerText()).includes(prefix));await page.locator('#textModal button').click();}else assert.ok((await page.locator('body').innerText()).includes(prefix));}
async function finishConfirmation(page){const button=page.getByRole('button',{name:/この内容で/});if(await button.count()){await button.filter({visible:true}).first().click();}}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.Q10_BROWSER_EXECUTABLE||undefined});results.browser=browser.version();
 try{for(const device of [{name:'pc',width:1366,height:900},{name:'phone',width:390,height:844,isMobile:true,hasTouch:true}])for(const kind of ['safety','vehicle','reminder']){
  if(process.env.Q03_BROWSER_CASE&&!process.env.Q03_BROWSER_CASE.split(',').includes(device.name+'-'+kind))continue;
  const item={name:device.name+'-'+kind,emulation:!!device.isMobile,passed:false,posts:[],pageErrors:[],criteriaFailures:[]};const contexts=[];
  async function context(user){const c=await browser.newContext({viewport:{width:device.width,height:device.height},isMobile:!!device.isMobile,hasTouch:!!device.hasTouch});contexts.push(c);await c.tracing.start({screenshots:true,snapshots:true,sources:true});await c.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin===fixture.url)return route.continue();results.blockedOrigins.push(u.origin);return route.abort();});const p=await c.newPage();p.setDefaultTimeout(12000);p.on('dialog',async d=>{item.dialogs=item.dialogs||[];item.dialogs.push({type:d.type(),message:d.message()});await d.accept();});p.on('pageerror',e=>item.pageErrors.push(e.message));p.on('response',r=>{if(r.request().method()==='POST')item.posts.push({path:new URL(r.url()).pathname,status:r.status(),csrfPresent:/csrf_token/.test(r.request().postData()||'')});});await login(p,user);return p;}
  let main;
  try{
   const info=fixture.records[item.name];main=await context(kind==='reminder'?'admin':'approver');
   if(kind==='reminder')await reminders(main,info,item,device);else await approval(main,info,item,device,context);
   assert.deepEqual(item.pageErrors,[]);await screenshot(main,item.name+'-completed');item.passed=item.criteriaFailures.length===0;
  }catch(e){item.failure=e.stack;if(main)await screenshot(main,item.name+'-failure').catch(()=>{});}
  finally{for(let i=0;i<contexts.length;i++){await contexts[i].tracing.stop({path:path.join(out,item.name+'-'+i+'-trace.zip')});await contexts[i].close();}results.cases.push(item);save();console.log(JSON.stringify(item));}
 }}finally{await browser.close();}
 results.passed=results.cases.filter(c=>c.passed).length;results.failed=results.cases.length-results.passed;save();process.exitCode=results.failed?1:0;
})().catch(e=>{console.error(e);process.exitCode=1;});
async function approval(page,info,item,device,context){
 const checker=await context('checker'),admin=info.kind==='vehicle'?await context('admin'):null;
 await page.goto(fixture.url+info.page);const approvalPath=`/${info.kind==='safety'?'safety':'vehicle'}/checklist-results/${info.id}/approve/0`;
 const oldForm=page.locator(`form[action="${approvalPath}"]`);await oldForm.waitFor();assert.ok(await oldForm.locator('[name=csrf_token]').inputValue());
 await viewAnswer(page,info,'OLD_ANSWER_'+item.name);const oldVersion=await oldForm.locator('[name=approval_version]').inputValue();
 // A real authenticated browser request without CSRF must be rejected before save.
 const csrfProbe=await context('approver');const beforeCsrf=await state(page);const denied=await csrfProbe.evaluate(async p=>{const r=await fetch(p,{method:'POST',body:new URLSearchParams()});return r.status;},approvalPath);assert.equal(denied,400);assert.equal((await state(page)).snapshot_sha256,beforeCsrf.snapshot_sha256);item.csrfMissingRejected=denied;
 if(info.kind==='safety'){
  await checker.goto(fixture.url+info.page+'/edit');await checker.locator('.free-answer-input[contenteditable=true]').first().fill('NEW_ANSWER_'+item.name);
  await checker.getByRole('button',{name:'チェック結果を更新',exact:true}).click();await finishConfirmation(checker);
 }else{
  await admin.goto(fixture.url+info.page);await admin.locator('.js-vehicle-checklist-reject').filter({visible:true}).first().click();await admin.locator('#vehicleRejectReason').fill('Synthetic answer correction');await admin.getByRole('button',{name:'差し戻す',exact:true}).click();
  await admin.waitForFunction(()=>!document.querySelector('#vehicleRejectReason')||document.querySelector('#vehicleRejectModal')?.classList.contains('is-hidden')).catch(()=>{});
  await checker.goto(fixture.url+info.page);const input=checker.locator('form.inline-check-form input[name=value]').filter({visible:true}).first();await input.fill('NEW_ANSWER_'+item.name);await Promise.all([checker.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname.endsWith('/save-one')),input.press('Tab')]);
  await Promise.all([checker.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname.endsWith('/complete')),checker.getByRole('button',{name:'修正して再申請',exact:true}).click()]);
 }
 await page.waitForTimeout(300);const changed=await state(page);assert.equal(changed.cases[item.name].status,'承認待ち');assert.ok(JSON.stringify(changed.cases[item.name].answers).includes('NEW_ANSWER_'+item.name),'Other real UI operation must save new answers');
 assert.equal(await oldForm.locator('[name=approval_version]').inputValue(),oldVersion);
 const stale=await submit(page,oldForm,oldForm.getByRole('button',{name:/承認/}));if(stale.status()!==409)item.criteriaFailures.push('Stale HTML approval must return HTTP 409; actual '+stale.status());assert.equal((await state(page)).snapshot_sha256,changed.snapshot_sha256);item.staleStatus=stale.status();item.unseenAnswerNotApproved=true;
 await page.waitForTimeout(200);item.rejectionUrl=page.url();item.rejectionText=(await page.locator('body').innerText()).slice(0,3000);await screenshot(page,item.name+'-409');
 if(!/点検記録が更新|最新の回答|再読み込み|再読込/.test(item.rejectionText))item.criteriaFailures.push('Conflict guidance must explain reload/recheck; actual generic approval failure');
 // Browser reload/reopen uses a normal GET; no session or CSRF substitution.
 if(new URL(page.url()).pathname===new URL(fixture.url+info.page).pathname)await page.reload();else await page.goto(fixture.url+info.page);
 const fresh=page.locator(`form[action="${approvalPath}"]`);await fresh.waitFor();assert.notEqual(await fresh.locator('[name=approval_version]').inputValue(),oldVersion);await viewAnswer(page,info,'NEW_ANSWER_'+item.name);
 await screenshot(page,item.name+'-reconfirmed');const before=await state(page);const response=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname===approvalPath);await fresh.getByRole('button',{name:/承認/}).click({clickCount:2});const approved=await response;assert.ok([200,302].includes(approved.status()));await page.waitForTimeout(350);
 const after=await state(page);const current=after.cases[item.name];assert.equal(current.status,'承認済み');assert.equal(current.events.filter(e=>e.kind==='承認').length,1);assert.equal(current.notifications.length-before.cases[item.name].notifications.length,1);item.approvalEvents=1;item.approvalNotificationsAdded=1;item.recovered=true;
}
async function reminders(page,info,item,device){
 await page.goto(fixture.url+info.page);const second=await page.context().newPage();second.on('response',r=>{if(r.request().method()==='POST')item.posts.push({path:new URL(r.url()).pathname,status:r.status(),csrfPresent:/csrf_token/.test(r.request().postData()||'')});});await second.goto(fixture.url+info.page);
 fs.writeFileSync(path.join(out,item.name+'-initial.html'),await page.content());
 assert.equal((await state(page)).cases[item.name].settings.length,0);item.initialParentCount=0;
 const waiting=[];await page.context().route('**/reminder-notify-users',async route=>{waiting.push(route);if(waiting.length===2)await Promise.all(waiting.map(r=>r.continue()));});
 // Discover and operate the existing reminder selector, never a fixture write API.
 const selector=page.locator('#reminder_notify_user_search');await selector.waitFor();
 const secondSelector=second.locator('#reminder_notify_user_search');
 await Promise.all([selector.fill('Synthetic'),secondSelector.fill('Synthetic')]);
 await screenshot(page,item.name+'-choices');
 const first=page.locator('#reminder_notify_user_search_results .vehicle-select-item').first(),other=second.locator('#reminder_notify_user_search_results .vehicle-select-item').first();
 await Promise.all([first.click({clickCount:2}),other.click({clickCount:2})]);
 for(let i=0;i<50&&item.posts.filter(r=>r.path.endsWith('/reminder-notify-users')).length<2;i++)await page.waitForTimeout(100);assert.equal(item.posts.filter(r=>r.path.endsWith('/reminder-notify-users')&&r.status===200).length,2);item.realInitialSaves=2;
 const s=await state(page);assert.equal(s.cases[item.name].settings.length,1);item.settingParents=1;await second.close();
}
