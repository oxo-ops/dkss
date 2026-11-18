const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const root=path.resolve(process.env.PRODUCT_REPO),dir=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);
fs.mkdirSync(out,{recursive:true});
(async()=>{let b,c,p;const report={cases:[],unsafe:0};try{b=await chromium.launch({headless:true});
for(const width of [320,390,768,1316])for(const version of ['old','inline'])for(const unread of ['delay','error']){
 c=await b.newContext({viewport:{width,height:850},serviceWorkers:'block'});p=await c.newPage();let bellRequests=0;
 await c.routeWebSocket('**/*',s=>{report.unsafe++;s.close()});
 await c.route('**/*',async r=>{const u=new URL(r.request().url());if(r.request().method()!=='GET'||u.origin!=='https://fixture.invalid'){report.unsafe++;return r.abort()}
 if(u.pathname==='/'){let html=fs.readFileSync(path.join(dir,'detail.html'),'utf8');if(version==='old')html=html.replace(/<img\s+src="data:image\/png;base64,[\s\S]*?alt=""\s*>/,'<img src="/static/icons/notification-display-76.png" width="38" height="38" alt="">');return r.fulfill({contentType:'text/html',body:html});}
 if(u.pathname==='/api/notifications/unread-count'){if(unread==='delay')await new Promise(x=>setTimeout(x,1200));return r.fulfill({status:unread==='error'?503:200,contentType:'application/json',body:JSON.stringify({unread_count:3})});}
 if(u.pathname==='/api/notifications/recent')return r.fulfill({contentType:'application/json',body:JSON.stringify({notifications:[],unread_count:3})});
 if(u.pathname.startsWith('/files/uploads/'))return r.fulfill({path:path.join(dir,u.searchParams.has('preview')?'preview-'+u.searchParams.get('preview')+'.webp':'original.jpg')});
 const file=path.resolve(root,'.'+u.pathname);if(u.pathname.startsWith('/static/')&&file.startsWith(root+'/static/')&&fs.existsSync(file)){if(u.pathname.includes('notification-display-')){bellRequests++;await new Promise(x=>setTimeout(x,1800));}return r.fulfill({path:file});}
 return r.fulfill({status:404,body:'offline'});
 });
 await p.goto('https://fixture.invalid/',{waitUntil:'domcontentloaded'});
 const bell=p.locator('#notificationBell img');const readyAtDom=await bell.evaluate(i=>i.complete&&i.naturalWidth>0);assert.equal(readyAtDom,version==='inline');
 if(await p.locator('#firstGuidePanel').isVisible())await p.locator('[data-guide-close]').click();
 await p.waitForFunction(()=>document.querySelector('#notificationBell img').complete);assert.equal(bellRequests,version==='inline'?0:1);
 const pixels=await bell.screenshot();fs.writeFileSync(path.join(out,`${version}-${width}-${unread}-bell.png`),pixels);
 await p.locator('#notificationBell').click();await p.locator('#notificationPopover').waitFor({state:'visible'});await p.locator('#notificationPopoverClose').click();await p.locator('#notificationPopover').waitFor({state:'hidden'});
 await p.locator('#notificationBell').focus();await p.keyboard.press('Enter');await p.locator('#notificationPopover').waitFor({state:'visible'});await p.keyboard.press('Escape');await p.locator('#notificationPopover').waitFor({state:'hidden'});
 const attachment=p.locator('img.detail-image').first();await attachment.scrollIntoViewIfNeeded();await attachment.evaluate(i=>i.decode());const size=await attachment.evaluate(i=>({natural:i.naturalWidth,w:i.getBoundingClientRect().width,src:i.currentSrc}));assert([480,960].includes(size.natural));assert(size.src.includes('preview='));
 const popupPromise=c.waitForEvent('page');await attachment.click();const popup=await popupPromise;await popup.waitForLoadState();assert(!popup.url().includes('preview='));await popup.close();
 await p.screenshot({path:path.join(out,`${version}-${width}-${unread}.png`),fullPage:true});report.cases.push({width,version,unread,readyAtDom,bellRequests,size,passed:true});await c.close();c=null;
}
for(const width of [320,390,768,1316])for(const mode of ['delay','error'])assert(fs.readFileSync(path.join(out,`old-${width}-${mode}-bell.png`)).equals(fs.readFileSync(path.join(out,`inline-${width}-${mode}-bell.png`))),'bell pixels changed');
assert.equal(report.unsafe,0);assert.equal(report.cases.length,16);
}catch(e){report.error=String(e);if(p)await p.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw e}finally{if(c)await c.close();if(b)await b.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));}})().catch(e=>{console.error(e);process.exitCode=1});
