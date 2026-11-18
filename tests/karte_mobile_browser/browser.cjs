const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),html=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);
const css=fs.readFileSync(path.join(repo,'static/css/vehicle_karte_mobile.css'),'utf8');
const names=['vehicle_karte','vehicle_karte_history','vehicle_karte_inspections','vehicle_karte_maintenance','vehicle_karte_parts','vehicle_karte_costs','vehicle_karte_documents','vehicle_karte_analysis'];
(async()=>{fs.mkdirSync(out,{recursive:true});let browser,page,posts=0,external=0,ws=0,rows=[];
try{browser=await chromium.launch({headless:true,args:['--no-sandbox'],...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
for(const name of names)for(const width of [320,390,768,1316]){
 const context=await browser.newContext({serviceWorkers:"block",viewport:{width,height:900}});page=await context.newPage();
 await page.routeWebSocket('**/*',s=>{ws++;s.close()});
 await page.route('**/*',r=>{let u=new URL(r.request().url());if(r.request().method()!=='GET'){posts++;return r.abort()};if(u.origin!=='https://fixture.invalid'){external++;return r.abort()};
 if(u.pathname==='/page')return r.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,name+'.html'),'utf8')});
 if(u.pathname==='/static/css/vehicle_karte_mobile.css')return r.fulfill({contentType:'text/css',body:''});
 const f=path.resolve(repo,'.'+u.pathname);if(u.pathname.startsWith('/static/')&&f.startsWith(repo+'/static/')&&fs.existsSync(f))return r.fulfill({path:f});return r.fulfill({status:404,body:'offline fixture'});});
 await page.goto('https://fixture.invalid/page');await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
 if(await page.locator('#firstGuidePanel').isVisible())await page.locator('[data-guide-close]').click();
 await page.evaluate(()=>document.fonts.ready);await page.evaluate(()=>scrollTo({top:0,left:0,behavior:'instant'}));await page.waitForTimeout(100);
 const stableScreenshot=async filename=>{let previous;for(let i=0;i<8;i++){await page.waitForTimeout(120);const current=await page.screenshot({fullPage:true});if(previous&&current.equals(previous)){fs.writeFileSync(filename,current);return current;}previous=current;}throw new Error('Screenshot did not stabilize: '+filename);};
 const snapshot=()=>page.evaluate(()=>({text:document.querySelector('.main-content').innerText,links:[...document.querySelectorAll('.main-content a')].map(a=>[a.textContent.trim(),a.getAttribute('href')]),states:[...document.querySelectorAll('.ko-badge,.vi-badge,.km-status,.ka-priority-badge')].map(e=>[e.textContent,getComputedStyle(e).color,getComputedStyle(e).backgroundColor]),tabs:[...document.querySelectorAll('.vehicle-karte-tab')].map(e=>[e.textContent.trim(),e.getAttribute('aria-current')]),geometry:[...document.querySelectorAll('.main-content *')].map(e=>{let r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})}));
 const beforePNG=await stableScreenshot(path.join(out,`${name}-${width}-before.png`));const before=await snapshot();assert.equal(before.tabs.length,8);
 await page.addStyleTag({content:css});await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));const afterPNG=await stableScreenshot(path.join(out,`${name}-${width}-after.png`));const after=await snapshot();
 for(const key of ['text','links','states','tabs'])assert.deepEqual(after[key],before[key],`${name} ${width}: ${key}`);
 if(width>640 && JSON.stringify(after.geometry)!==JSON.stringify(before.geometry))fs.writeFileSync(path.join(out,'geometry-diff.json'),JSON.stringify({name,width,before:before.geometry,after:after.geometry}));
 if(width>640){assert.deepEqual(after.geometry,before.geometry,'desktop geometry');assert(await page.evaluate(async ([a,b])=>{const decode=async s=>{const bytes=Uint8Array.from(atob(s),c=>c.charCodeAt(0));const im=await createImageBitmap(new Blob([bytes],{type:'image/png'}));const c=new OffscreenCanvas(im.width,im.height),ctx=c.getContext('2d');ctx.drawImage(im,0,0);return {width:im.width,height:im.height,pixels:ctx.getImageData(0,0,im.width,im.height).data};};const x=await decode(a),y=await decode(b);return x.width===y.width&&x.height===y.height&&x.pixels.every((v,i)=>v===y.pixels[i]);},[beforePNG.toString('base64'),afterPNG.toString('base64')]),'desktop pixels unchanged');}
 else {const selected=page.locator('.vehicle-karte-tab[aria-current=page]');assert.equal(await selected.evaluate(e=>getComputedStyle(e).color),'rgb(255, 255, 255)');assert((await selected.evaluate(e=>getComputedStyle(e).backgroundImage)).includes('rgb(36, 92, 168)'));assert(await page.locator('.vehicle-karte-tab').evaluateAll(es=>es.every(e=>e.getBoundingClientRect().height>=44)));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'no document horizontal overflow');}
 rows.push({name,width,passed:true,content_links_states_unchanged:true,desktop_pixel_unchanged:width>640});await context.close();
}
assert.equal(rows.length,32);assert.equal(posts,0);assert.equal(external,0);assert.equal(ws,0);
} catch(e){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({rows,error:String(e)}));if(page&&!page.isClosed())await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw e;}
finally {fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({rows,posts,external,ws,synthetic:true,live:false},null,2));if(browser)await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
