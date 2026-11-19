const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),html=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);
async function motion(page,opening){
 const sampling=page.evaluate(()=>new Promise(resolve=>{const rows=[],start=performance.now();function frame(t){const b=document.querySelector('#sidebarToggle').getBoundingClientRect(),d=document.querySelector('.sidebar').getBoundingClientRect();rows.push({t:t-start,x:b.x,right:b.right,drawerRight:d.right,open:document.body.classList.contains('sidebar-open')});if(t-start<550)requestAnimationFrame(frame);else resolve(rows)}requestAnimationFrame(frame)}));
 await page.locator('#sidebarToggle').click();const rows=await sampling;
 await page.waitForFunction(open=>document.body.classList.contains('sidebar-open')===open&&document.querySelector('#sidebarToggle').getAttribute('aria-expanded')===String(open),opening);
 return rows;
}
(async()=>{fs.mkdirSync(out,{recursive:true});let report=[],blocked=[],current;const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{for(const width of [320,390,768,1024,1180,1440])for(const name of ['dashboard','checklist_result_detail','driving_reports','pointouts','vehicle_karte','vehicle_karte_history','normal_driver_master','normal_checklist_master','inspection_driver_input','demo_settings_manager','demo_settings_driver','normal_settings_manager','normal_settings_driver']){
 const file=path.join(html,name+'.html');assert(fs.existsSync(file),name);const info=JSON.parse(fs.readFileSync(path.join(html,'routes.json'))).find(r=>r.endpoint===name);assert(info);
 const context=await browser.newContext({viewport:{width,height:844},serviceWorkers:'block'});await context.routeWebSocket('**/*',ws=>{blocked.push('WS');ws.close()});const page=await context.newPage();current=page;
 await page.route('**/*',route=>{const req=route.request(),url=new URL(req.url());if(req.method()!=='GET'||url.origin!=='https://fixture.invalid'){blocked.push(req.method()+' '+url.origin);return route.abort()}
 if(url.pathname==='/api/approval-candidates'&&name.startsWith('inspection_'))return route.fulfill({contentType:'application/json',body:fs.readFileSync(path.join(html,'inspection-states',info.role+'-approval-candidates.json'),'utf8')});
 if(url.pathname===new URL(info.path,'https://fixture.invalid').pathname)return route.fulfill({contentType:'text/html',body:fs.readFileSync(file,'utf8')});
 if(url.pathname.startsWith('/static/')){const f=path.resolve(repo,'.'+url.pathname);if(f.startsWith(repo+'/static/')&&fs.existsSync(f))return route.fulfill({path:f});}
 return route.fulfill({status:404,body:'offline fixture'});});
 await page.goto(new URL(info.path,'https://fixture.invalid').href);await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
 const guide=page.locator('#firstGuidePanel');if(name==='dashboard'&&width<=900){assert(await guide.isVisible(),'initial dashboard guidance must be visible for menu acceptance');const old=await page.addStyleTag({content:'body[data-responsive-shell] .sidebar-toggle{left:12px!important}body[data-responsive-shell]:not(.sidebar-open) .sidebar-toggle{transform:translateX(var(--app-drawer-width))!important}body[data-responsive-shell].sidebar-open .sidebar-toggle{left:calc(var(--app-drawer-width) - 56px)!important;transform:translateX(0)!important}'});
 await page.evaluate(()=>Promise.all(document.querySelector('#sidebarToggle').getAnimations().map(a=>a.finished)));
 const oldOpen=await motion(page,true),oldClose=await motion(page,false);await old.evaluate(e=>e.remove());await page.evaluate(()=>Promise.all(document.querySelector('#sidebarToggle').getAnimations().map(a=>a.finished)));
 const newOpen=await motion(page,true);await page.screenshot({path:path.join(out,`menu-${width}-open.png`)});const newClose=await motion(page,false);
 for(const rows of [newOpen,newClose]){assert(rows.length>5);for(const p of rows)assert(p.x>=-1&&p.right<=width+1,'menu toggle outside viewport');let deltas=rows.slice(1).map((p,i)=>Math.abs(p.x-rows[i].x));assert(Math.max(...deltas)<80,'instant toggle jump');}
 fs.writeFileSync(path.join(out,`menu-motion-${width}.json`),JSON.stringify({oldOpen,oldClose,newOpen,newClose},null,2));}if(await guide.isVisible())await page.locator('[data-guide-close]').click();
 if(await page.locator('.first-guide-help-icon').count()){
  assert.equal(await page.locator('.first-guide-help-icon').innerText(),'?');
  if(name==='dashboard'){
   for(const stage of ['closed','opened','closed-again','reopened']){
    if(stage==='opened'||stage==='reopened')await page.locator('[data-guide-open]').click();
    if(stage==='closed-again')await page.locator('[data-guide-close]').click();
    assert.equal(await page.locator('.first-guide-help-icon').innerText(),'?');
    assert.equal(await guide.isVisible(),stage==='opened'||stage==='reopened');
    await page.screenshot({path:path.join(out,`help-${width}-${stage}.png`)});
   }
   await page.locator('[data-guide-close]').click();
  }
 }
 if(name.includes('settings_')){assert(await page.locator('.settings-user-card').isVisible());for(const selector of ['.settings-notification-card','.settings-password-card','form[action="/logout"]'])assert.equal(await page.locator(selector).count(),name.startsWith('demo_')?0:1);}
 if(name==='dashboard'&&width>900){
  const menu=page.locator('#sidebarToggle'),sidebar=page.locator('.sidebar');
  for(const collapsed of [true,false,true,false]){
   const now=await page.evaluate(()=>document.body.classList.contains('sidebar-collapsed'));
   if(now!==collapsed)await menu.click();
   await page.waitForTimeout(100);
   assert.equal(await menu.getAttribute('aria-expanded'),String(!collapsed));
   const rail=await sidebar.boundingBox();assert(collapsed?rail.width<=75:rail.width>=160,'desktop rail width matches state');
   assert.equal(await page.locator('.alseon-wordmark').isVisible(),!collapsed);
   assert.equal(await page.locator('.alseon-symbol').isVisible(),collapsed);
   const label=page.locator('.sidebar .menu-text').first();assert.equal(await label.isVisible(),!collapsed);
   if(collapsed)assert.equal(await page.locator('.sidebar-submenu').evaluateAll(es=>es.some(e=>e.getBoundingClientRect().height>0)),false,'collapsed submenus hidden');
   await page.screenshot({path:path.join(out,`desktop-sidebar-${width}-${collapsed?'collapsed':'expanded'}.png`)});
  }
 }
 const bar=page.locator('.main-content > .top-bar');assert(await bar.isVisible());const avatar=bar.locator('.top-bar-user');assert.equal(await avatar.isVisible(),!(name==='driving_reports'&&width<768));assert.equal(await bar.locator('.top-bar-user-name').isVisible(),width>900);
 if(width<768){const heading=page.locator('.main-content > [data-mobile-page-title]');assert(await heading.isVisible());const hb=await heading.boundingBox();assert(hb.x>=0,'title inside viewport');assert(hb.width>0);assert.equal(await bar.evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)');if(name==='driving_reports'){assert.equal(await bar.locator('.notification-menu').isVisible(),false);assert(await bar.locator('[data-guide-open]').isVisible());}}
 else assert.equal(await bar.locator('[data-mobile-page-title]').isVisible(),false);
 const help=bar.locator('#firstUseGuide'),bell=bar.locator('.notification-menu');if(await help.count()){assert(await help.evaluate((e)=>{let n=e.nextElementSibling;while(n&&['SCRIPT','LINK','STYLE'].includes(n.tagName))n=n.nextElementSibling;return n?.classList.contains('notification-menu');}),'help directly before notification');}
 if(name==='checklist_result_detail'){const launcher=page.locator('[data-guide-open]');assert(await launcher.isVisible());await launcher.click();const panel=page.locator('#firstGuidePanel');assert(await panel.isVisible());assert.equal(await panel.locator('[data-guide-title]').innerText(),'点検した対象と日付を確認する');await page.screenshot({path:path.join(out,`safety-detail-guide-${width}.png`)});await panel.locator('[data-guide-next]').click();assert.equal(await panel.locator('[data-guide-title]').innerText(),'点検の内容を見る');await panel.locator('[data-guide-close]').click();}
 const controls=bar.locator('.first-guide-launch,.notification-bell,.top-bar-user,.karte-mobile-search-trigger');
 const rects=await controls.evaluateAll(es=>es.filter(e=>e.getBoundingClientRect().width&&getComputedStyle(e).display!=='none').map(e=>{const r=e.getBoundingClientRect();return {label:e.getAttribute('aria-label'),x:r.x,y:r.y,w:r.width,h:r.height}}));
 if(width<768){for(const r of rects){assert(r.w>=44&&r.h>=44,JSON.stringify({name,width,r}));assert(r.x>=0&&r.x+r.w<=width+1,JSON.stringify({name,width,r}));}for(let i=0;i<rects.length;i++)for(let j=i+1;j<rects.length;j++){let a=rects[i],b=rects[j];assert(a.x+a.w<=b.x+1||b.x+b.w<=a.x+1||a.y+a.h<=b.y+1||b.y+b.h<=a.y+1,'header overlap');}}
 if(name==='inspection_driver_input'){if(width<768){assert(await page.locator('.vehicle-search-action').isVisible());assert.equal(await page.locator('.vehicle-workspace-top [data-vehicle-open-details="vehicle-target-settings"]').isVisible(),false);}assert.equal(await page.locator('#error-summary').count(),0,'real fixture approval response must not generate an error');await page.evaluate(()=>showCommonError('表示位置の確認用エラー','',false));const e=await page.locator('#error-summary').boundingBox(),h=await bar.boundingBox(),m=await page.locator('#sidebarToggle').boundingBox();assert(e.y>=h.y+h.height-1,'error must stay below account header');if(m)assert(e.x>=m.x+m.width-1||m.x>=e.x+e.width-1||e.y>=m.y+m.height-1||m.y>=e.y+e.height-1,'error must not collide with menu on either axis');await page.screenshot({path:path.join(out,`inspection-error-${width}.png`),fullPage:false});await page.evaluate(()=>clearCommonErrors());}
 if(name==='inspection_driver_input'){
  await page.locator('[data-guide-open]').click();
  await page.locator('[data-guide-next]').click();
  await page.waitForTimeout(650);
  assert.equal(await page.locator('#firstGuidePanel [data-guide-title]').innerText(),'項目の詳細を見る');
  const panel=await page.locator('#firstGuidePanel').boundingBox(),target=await page.locator('.inspection-item-detail.first-guide-target').boundingBox();
  assert(panel && target,'same inspection item highlighted');
  assert(panel.y+panel.height<=target.y+1 || panel.y>=target.y+target.height-1,'guide must not cover highlighted item');
  assert(await page.locator('[data-guide-picture]').isVisible(),'instruction image retained');
  await page.screenshot({path:path.join(out,`inspection-item-guide-${width}.png`)});
  await page.locator('[data-guide-close]').click(); await page.evaluate(()=>window.scrollTo(0,0));
 }
 const crumb=page.locator('.page-breadcrumb').first();if(await crumb.isVisible()&&width<=768){assert.equal(await crumb.evaluate(e=>getComputedStyle(e).paddingTop),'0px');const c=await crumb.boundingBox(),h=await bar.boundingBox();assert(c.y>=h.y+h.height-1,'breadcrumb under header');}
 await page.screenshot({path:path.join(out,`${name}-${width}.png`),fullPage:true});
 if(width<768 && ['dashboard','driving_reports','pointouts','vehicle_karte','inspection_driver_input'].includes(name)){
  const title=page.locator('.main-content > [data-mobile-page-title]'),before=await title.boundingBox();
  await page.evaluate(()=>window.scrollBy(0,500)); await page.waitForTimeout(100);
  const after=await title.boundingBox(),scroll=await page.evaluate(()=>window.scrollY);
  assert(scroll>0,'page scroll available'); assert(after.y<before.y-20,'title scrolls with content');
  const menu=await page.locator('#sidebarToggle').boundingBox();assert(menu.y>=0&&menu.y<60,'menu stays visible');
  assert.equal(await title.evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)');
  await page.screenshot({path:path.join(out,`scroll-title-${name}-${width}.png`)});
  await page.evaluate(()=>window.scrollTo(0,0));
 }
 if(name==='driving_reports'&&width<768){const filter=page.locator('.driving-extra-filters > summary');assert(await filter.locator('.driving-toolbar-icon').isVisible());assert.equal(await filter.locator('.driving-toolbar-label').isVisible(),false);await filter.click();assert(await page.locator('.driving-extra-filters input[name="start"]').isVisible());await filter.click();for(const control of [filter,page.locator('.driving-export-menu > summary')]){const r=await control.boundingBox();assert(r.width>=44&&r.height>=44);}}
 if(name.startsWith('vehicle_karte')){
 const trigger=page.locator('.karte-mobile-search-trigger'),input=page.locator('#karte_vehicle_search');
 if(width<768){assert(await trigger.isVisible());await trigger.click();const dialog=page.locator('#karte-mobile-search-dialog');await dialog.waitFor({state:'visible'});await assert.equal(await input.evaluate(e=>document.activeElement===e),true);let choices=await page.locator('#karte_vehicle_search_data').evaluate(e=>JSON.parse(e.textContent));assert(choices.length>0);const number=choices[0].number;await input.fill(number);await page.locator('#karte_vehicle_search_results a').first().waitFor({state:'visible'});let link=await page.locator('#karte_vehicle_search_results a').first().getAttribute('href');assert(new URL(link).searchParams.has('vehicle_record_id'));const searchRect=await dialog.boundingBox();assert(Math.abs(searchRect.x)<1&&Math.abs(searchRect.y)<1&&Math.abs(searchRect.width-width)<1&&Math.abs(searchRect.height-844)<1,JSON.stringify({name,width,searchRect}));await page.screenshot({path:path.join(out,`${name}-${width}-search-viewport.png`)});await page.screenshot({path:path.join(out,`${name}-${width}-search.png`),fullPage:true});assert.equal(await page.locator('.karte-mobile-search-clear').innerText(),'×');assert.equal(await page.locator('#karte-mobile-search-dialog').getByText('消去',{exact:true}).count(),0);const clearBox=await page.locator('.karte-mobile-search-clear').boundingBox();assert(clearBox.width>=44&&clearBox.height>=44);await page.locator('.karte-mobile-search-clear').click();assert.equal(await input.inputValue(),'');assert.equal(await page.locator('.karte-mobile-search-clear').isVisible(),false);assert(await input.evaluate(e=>document.activeElement===e));assert.equal(await dialog.isVisible(),true);await input.fill('no-matching-vehicle');await input.press('Escape');assert.equal(await dialog.isVisible(),false);assert.equal(await input.inputValue(),'');assert.equal(await trigger.evaluate(e=>document.activeElement===e),true);await trigger.click();await page.locator('.karte-mobile-search-close').click();assert.equal(await dialog.isVisible(),false);
 }else{assert.equal(await trigger.isVisible(),false);assert(await input.isVisible());assert.equal(await input.evaluate(e=>Boolean(e.closest('.top-bar'))),true);}
 }
 if(name==='normal_checklist_master'){
 const list=page.locator('.checklist-master-mobile-list'),table=page.locator('.checklist-master-table');
 if(width<=768){assert(await list.isVisible());assert.equal(await table.isVisible(),false);const row=list.locator('.checklist-compact-disclosure').first(),summary=row.locator('summary');assert.equal(await summary.locator(':scope > *').count(),2);assert.equal(await row.locator('.checklist-compact-detail').isVisible(),false);await summary.click();assert(await row.locator('.checklist-compact-detail').isVisible());assert(await row.locator('.master-order-handle').isVisible());await summary.press('Enter');assert.equal(await row.locator('.checklist-compact-detail').isVisible(),false);}else{assert(await table.isVisible());assert.equal(await list.isVisible(),false);}
 }
 report.push({name,width,passed:true,rects});await context.close();}
 assert.equal(report.length,78);assert.deepEqual(blocked,[]);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({report,blocked,synthetic:true,live:false},null,2));
}catch(e){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(e),report,blocked},null,2));if(current&&!current.isClosed())await current.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw e}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});



