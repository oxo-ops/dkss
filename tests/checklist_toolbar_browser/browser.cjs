const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch();const results=[];fs.mkdirSync(process.argv[3],{recursive:true});
for(const width of [320,390,768,1440])for(const count of [0,8]){
 const context=await browser.newContext({viewport:{width,height:844},locale:'de-DE'});const page=await context.newPage();
 await page.route('**/*',r=>r.request().url().startsWith('file:')?r.continue():r.abort());
 await page.goto('file://'+path.resolve(process.argv[2],'page-'+count+'.html'));
 assert.equal(await page.locator('.vehicle-date-japanese').innerText(),'11/19');
 const dateDisplay=await page.locator('.vehicle-date-japanese').evaluate(el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return {width:r.width,height:r.height,clip:s.clipPath,opacity:s.opacity};});
 assert(dateDisplay.width>=(width<=600?80:44) && dateDisplay.height>=44,JSON.stringify({width,dateDisplay}));assert.equal(dateDisplay.clip,'none');assert.equal(dateDisplay.opacity,'1');
 assert.equal(await page.locator('#vehicle_workspace_date').inputValue(),'2026-11-19');
 assert.match(await page.locator('#vehicle_workspace_date').getAttribute('aria-label'),/2026年11月19日/);
 assert.equal(await page.locator('.vehicle-excel-action').getAttribute('href'),'/vehicle/checklist-results/7/excel');
 const excel=page.locator('.vehicle-excel-action');assert.equal(await excel.getAttribute('aria-label'),'Excel出力');assert(await excel.locator('svg').isVisible());
 const excelStyle=await excel.evaluate(el=>{const s=getComputedStyle(el),r=el.getBoundingClientRect();return {color:s.color,bg:s.backgroundColor,width:r.width,height:r.height};});assert.equal(excelStyle.color,'rgb(35, 117, 75)');assert.equal(excelStyle.width,44);assert.equal(excelStyle.height,44);assert.equal(await excel.locator('.vehicle-toolbar-text').isVisible(),false);
 await excel.focus();assert.equal(await excel.evaluate(el=>getComputedStyle(el).outlineStyle),'solid');await page.locator('#vehicle_workspace_date').focus();
 const old=page.locator('[data-vehicle-open-details="vehicle-target-settings"]');assert.equal(await old.count(),1);assert.equal(await old.isVisible(),false);assert.equal(await page.locator('.header-actions [data-vehicle-open-details="vehicle-target-settings"]').count(),1);
 const button=page.locator('.vehicle-search-action');assert(await button.isVisible());await button.click();assert.equal(await page.locator('#vehicle-target-settings').getAttribute('open'),'');
 await button.click();assert.equal(await page.locator('#vehicle-target-settings').getAttribute('open'),null);
 if(count){const d=page.locator('.vehicle-other-defects-menu');await d.locator('summary').click();assert(await d.locator('p').isVisible());assert.match(await d.locator('p').innerText(),/表示中の点検日時点の状態ではありません/);await d.locator('summary').press('Escape');assert.equal(await d.getAttribute('open'),null);}
 const geom=await page.evaluate(()=>{const a=document.querySelector('.vehicle-workspace-subtitle>strong').getBoundingClientRect(),b=document.querySelector('.vehicle-workspace-date').getBoundingClientRect();return {same:Math.abs((a.top+a.bottom)/2-(b.top+b.bottom)/2)<2,overflow:document.documentElement.scrollWidth>innerWidth+1};});
 assert(!geom.overflow,JSON.stringify({width,geom}));if(width<=600)assert(geom.same);
 await page.screenshot({path:path.join(process.argv[3],width+'-'+count+'.png'),fullPage:true});
 results.push({width,count,japaneseDate:true,excelUnchanged:true,searchToggle:true,defectMeaningPreserved:true,...geom});await context.close();
}fs.writeFileSync(path.join(process.argv[3],'results.json'),JSON.stringify(results,null,2));await browser.close();})().catch(e=>{console.error(e);process.exit(1)});



