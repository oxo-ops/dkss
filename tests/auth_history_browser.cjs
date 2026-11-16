// Loopback synthetic personas only. Real browser history, no live app session.
const http=require('node:http'),fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const script=fs.readFileSync('static/js/auth-history.js','utf8'),css=fs.readFileSync('static/css/auth-history.css','utf8');
let user='A',requests=[];
const server=http.createServer((req,res)=>{
 requests.push({method:req.method,path:req.url});res.setHeader('Content-Type','text/html');
 if(req.url==='/other'){res.end('<body>Public second document</body>');return;}
 res.end(`<style>${css}</style><body data-authenticated="${user?'true':'false'}"><h1>${user?'Person '+user:'Login required'}</h1><textarea aria-label="entry"></textarea><select aria-label="scope"><option value="first">First</option><option value="second">Second</option></select><a href="/other">Leave</a><script>${script}</script></body>`);
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,ignoreDefaultArgs:['--disable-back-forward-cache']});
 try {
 const page=await browser.newPage();let restored=0;
 page.on('console',m=>{if(m.text()==='RESTORED')restored++;});
 await page.addInitScript(()=>window.addEventListener('pageshow',e=>{if(e.persisted)console.log('RESTORED');}));
 const base=`http://127.0.0.1:${server.address().port}`;
 for(const next of ['A','B','']){
 user='A';await page.goto(base+'/protected');await page.getByRole('link').click();user=next;
 await page.goBack();await page.getByRole('heading',{name:next?'Person '+next:'Login required',exact:true}).waitFor();
 assert(await page.getByRole('heading').isVisible());
 }
 assert(restored>0,'Actual BFCache restoration required; ordinary reload is insufficient');
 user='A';await page.goto(base+'/protected');await page.getByRole('textbox').fill('Synthetic unsaved text');
 await page.getByRole('link').click();user='B';await page.goBack();
 const discard=page.getByRole('button',{name:'未保存の入力を破棄して開く'});
 await discard.waitFor();assert.equal(await page.getByRole('heading',{name:'Person A'}).isVisible(),false);
 assert.equal(await page.locator('textarea').inputValue(),'Synthetic unsaved text');
 await discard.click();await page.getByRole('heading',{name:'Person B'}).waitFor();
 assert.equal(await page.locator('textarea').inputValue(),'');
 user='A';await page.goto(base+'/protected');await page.getByRole('combobox').selectOption('second');
 await page.getByRole('link').click();await page.goBack();
 await discard.waitFor();assert.equal(await page.getByRole('combobox').inputValue(),'second');
 await discard.click();await page.getByRole('heading',{name:'Person A'}).waitFor();
 assert.equal(await page.getByRole('combobox').inputValue(),'first');
 user='A';await page.goto(base+'/protected');await page.getByRole('link').click();
 await page.context().setOffline(true);await page.goBack().catch(()=>{});
 const retry=page.getByRole('button',{name:'もう一度確認して開く'});
 await retry.waitFor();await page.getByText(/接続を確認できませんでした/).waitFor();
 assert.equal(await page.getByRole('heading',{name:'Person A'}).isVisible(),false);
 await page.context().setOffline(false);await retry.click();await page.getByRole('heading',{name:'Person A'}).waitFor();
 assert(requests.every(r=>['GET','HEAD'].includes(r.method)),'Never resubmit POST');
 console.log(JSON.stringify({result:'PASS',actual_bfcache_restores:restored,cases:['same-user','logout','user-switch','explicit-unsaved-discard','offline-retry','implicit-select','changed-select-discard']}));
 } finally {await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
