const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const repo=process.env.PRODUCT_REPO,html=process.env.HTML_OUT,out=process.env.ARTIFACTS;
fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch();const report=[];
try{for(const mode of ['normal-admin','normal-checker','demo-admin','demo-checker'])for(const width of [390,1440]){
const variants=[];
for(const variant of ['original','blue']){
 const ctx=await browser.newContext({viewport:{width,height:950},reducedMotion:'reduce',serviceWorkers:'block',locale:'ja-JP'});const page=await ctx.newPage();
 let writes=0; await ctx.route('**/*',r=>{const u=new URL(r.request().url());if(r.request().method()!=='GET'){writes++;return r.abort();}if(u.origin!=='https://fixture.invalid')return r.abort();
 if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,mode+'.html'),'utf8')});
 if(u.pathname.endsWith('/dashboard_blue_palette.css')&&variant==='original')return r.fulfill({contentType:'text/css',body:''});
 const f=path.resolve(repo,'.'+u.pathname);if(u.pathname.startsWith('/static/')&&f.startsWith(repo+'/static/')&&fs.existsSync(f))return r.fulfill({path:f});return r.fulfill({status:404,body:'offline'});});
 await page.goto('https://fixture.invalid/');await page.evaluate(()=>document.fonts.ready);await page.locator('.dashboard-page[data-design-ready="true"]').waitFor();
 const close=page.locator('[data-guide-close]');if(await close.isVisible())await close.click();
 const states=[];
 if(variant==='blue'){const bars=await page.locator('.office-trend-row progress').evaluateAll(es=>es.map(e=>getComputedStyle(e).accentColor));assert.equal(bars[0],'rgb(55, 108, 163)');assert.equal(new Set(bars.slice(0,3)).size,3,'three distinguishable trend series');}
 for(const expanded of [false,true]){
 if(expanded){for(const e of await page.locator('.dashboard-page details:not([open]) > summary').all())if(await e.isVisible())await e.click();for(const e of await page.locator('.dashboard-reference-footer button[aria-expanded="false"]').all())if(await e.isVisible())await e.click();}
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 states.push(await page.locator('.dashboard-page').evaluate(root=>[root,...root.querySelectorAll('*')].map(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return {tag:e.tagName,cls:e.className,text:e.childElementCount?'':e.textContent,rect:[r.x,r.y,r.width,r.height].map(n=>Math.round(n*10)/10),state:e.matches('[data-state],.summary-value.good,.status-badge,.dashboard-attention-status'),color:s.color,bg:s.backgroundColor};})));
 await page.screenshot({path:path.join(out,`${mode}-${width}-${variant}-${expanded?'expanded':'closed'}.png`),fullPage:true});
 }
 assert.equal(writes,0);variants.push(states);await ctx.close();
}
for(let i=0;i<2;i++){const a=variants[0][i],b=variants[1][i];assert.deepEqual(a.map(({tag,cls,text,rect})=>({tag,cls,text,rect})),b.map(({tag,cls,text,rect})=>({tag,cls,text,rect})),`${mode}/${width}/${i} geometry/text`);for(let j=0;j<a.length;j++)if(a[j].state){assert.equal(a[j].color,b[j].color);assert.equal(a[j].bg,b[j].bg);}}
report.push({mode,width,layout_text_equal:true,state_colors_equal:true,collapsed_and_expanded:true});
}}finally{await browser.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));}
})().catch(e=>{console.error(e);process.exitCode=1});
