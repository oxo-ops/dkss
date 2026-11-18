const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(process.env.PRODUCT_REPO),html=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS),routes=JSON.parse(fs.readFileSync(path.join(html,'routes.json')));
(async()=>{fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true});let page,report=[];try{
for(const width of [320,390,1440])for(const info of routes){
 const c=await browser.newContext({viewport:{width,height:844},serviceWorkers:'block'}),blocked=[];
 await c.routeWebSocket('**/*',w=>{blocked.push('WS');w.close()});
 await c.route('**/*',r=>{const q=r.request(),u=new URL(q.url());if(q.method()!=='GET'||u.origin!=='https://fixture.invalid'){blocked.push(q.method());return r.abort()}
 if(u.pathname===new URL(info.path,u.origin).pathname)return r.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,info.endpoint+'.html'),'utf8')});
 if(u.pathname==='/api/mention-users')return r.fulfill({json:{users:[{username:'admin',name:'通知担当太郎',role:'admin',office:'確認用'}]}});
 const f=path.resolve(root,'.'+u.pathname);if(u.pathname.startsWith('/static/')&&f.startsWith(root+'/static/')&&fs.existsSync(f))return r.fulfill({path:f});return r.fulfill({status:404,body:'offline fixture'});});
 page=await c.newPage();await page.goto('https://fixture.invalid'+info.path);
 const box=page.locator(info.role==='driver'?'[data-reminder-readonly]':'#selected_reminder_notify_users');
 await box.locator('.selected-vehicle-tag').filter({hasText:'通知担当太郎'}).waitFor({state:'visible'});
 assert(!/\badmin\b/.test(await box.innerText()));
 if(info.role==='driver')assert.equal(await box.locator('button').count(),0);
 else assert.equal(await box.locator('[data-user-name="admin"]').first().getAttribute('data-user-name'),'admin');
 await box.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,info.endpoint+'-'+width+'.png')});
 assert.deepEqual(blocked,[]);report.push({page:info.endpoint,width,nameVisible:true,role:info.role,externalOrPosts:0});await c.close();
}
assert.equal(report.length,12);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
}catch(e){fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(e),report}));if(page&&!page.isClosed())await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});throw e}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
