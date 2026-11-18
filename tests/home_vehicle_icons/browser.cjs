const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),dir=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({headless:true});const cases=[];try{
for(const width of [390,1316])for(const dpr of [1,2,3,4]){
 const context=await browser.newContext({viewport:{width,height:844},deviceScaleFactor:dpr,serviceWorkers:'block'});const page=await context.newPage();let external=0;
 await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin!=='https://fixture.invalid'){external++;return r.abort();}
 const f=u.pathname==='/'?path.join(dir,'icons.html'):path.join(repo,u.pathname);
 if(!fs.existsSync(f))return r.fulfill({status:404,body:''});
 return r.fulfill({status:200,contentType:f.endsWith('.png')?'image/png':'text/html; charset=utf-8',body:fs.readFileSync(f)});});
 await page.goto('https://fixture.invalid/');await page.locator('img').evaluateAll(xs=>Promise.all(xs.map(i=>i.decode())));
 const sources=await page.locator('.after').evaluateAll(xs=>xs.map(i=>({src:new URL(i.currentSrc).pathname,w:i.getBoundingClientRect().width,h:i.getBoundingClientRect().height})));
 const expected=dpr===1?96:dpr===2?192:384;
 assert.equal(sources[0].src,'/static/icons/truck-display-'+expected+'.png');
 ['trailer','tractor','crane','flatbed','car'].forEach((n,i)=>assert.equal(sources[i+1].src,'/static/icons/'+n+'.png'));
 assert(sources.every(s=>s.w===43&&s.h===43));assert.equal(external,0);
 await page.screenshot({path:path.join(out,width+'-dpr'+dpr+'.png')});
 cases.push({width,dpr,sources,passed:true});await context.close();
}
fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(cases,null,2));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
