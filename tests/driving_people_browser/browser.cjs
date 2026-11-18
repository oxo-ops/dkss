const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
const repo=path.resolve(process.env.PRODUCT_REPO),html=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);
(async()=>{const b=await chromium.launch({headless:true,args:['--no-sandbox']});let rows=[],posts=0,external=0;
try{for(const width of [320,390,768,1316])for(const scale of [1,2])for(const mode of ['empty','content']){
const context=await b.newContext({viewport:{width,height:1000}}),page=await context.newPage();
await page.addInitScript(()=>{localStorage.setItem('dkss:first-guide:v1:normal:driving_reports','1')});
await page.route('**/*',route=>{const r=route.request(),u=new URL(r.url());if(r.method()!=='GET'){posts++;return route.abort()}if(u.origin!=='https://fixture.invalid'){external++;return route.abort()}
if(u.pathname==='/safety/driving-reports')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,mode+'.html'),'utf8')});
const p=path.resolve(repo,'.'+u.pathname);if(u.pathname.startsWith('/static/')&&p.startsWith(repo+'/static/')&&fs.existsSync(p))return route.fulfill({path:p});return route.fulfill({status:404,body:'offline'});});
await page.goto('https://fixture.invalid'+JSON.parse(fs.readFileSync(path.join(html,'route.json'))).url);
if(await page.locator('#firstGuidePanel').isVisible())await page.keyboard.press('Escape');
if(scale===2)await page.evaluate(()=>{const sizes=[...document.querySelectorAll('.driving-driver-directory *')].map(e=>[e,parseFloat(getComputedStyle(e).fontSize)]);for(const [e,n]of sizes)e.style.fontSize=(n*2)+'px'});
const box=page.locator('.driving-driver-directory'),cta=box.locator('.driving-open-analysis').first();await box.scrollIntoViewIfNeeded();
assert.equal(await cta.innerText(),'分析を見る');assert(await cta.getAttribute('href'));assert(await cta.evaluate(e=>e.getBoundingClientRect().height>=44));
await cta.focus();assert(await cta.evaluate(e=>document.activeElement===e));
assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'horizontal overflow');
assert.equal(await box.locator('.driving-person-review-entry').count()>0,mode==='content');
assert(await cta.evaluate(e=>getComputedStyle(e).color==='rgb(37, 99, 235)'),'existing action blue');
const dataRow=box.locator('tr').filter({has:page.locator('.driving-person-metric')});
assert.equal(await dataRow.count(),1);assert.equal(await dataRow.locator('.driving-person-metric').count(),2);
assert.equal(await dataRow.locator('.driving-change-direction[aria-label="減少"]').innerText(),'↓');
assert.equal(await dataRow.locator('.driving-change-direction[aria-label="増加"]').innerText(),'↑');
if(width<=650)assert(await dataRow.evaluate(row=>row.children[2].getBoundingClientRect().bottom<=row.children[1].getBoundingClientRect().top+1),'trip summary before metrics');
const geometry=await box.evaluate(root=>{
 const errors=[],eps=2;
 const textInside=(el,label)=>{const bound=el.getBoundingClientRect(),walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);let n;
  while(n=walker.nextNode()){if(!n.textContent.trim())continue;const parent=n.parentElement,cs=getComputedStyle(parent);if(cs.display==='none'||cs.visibility==='hidden')continue;
   const range=document.createRange();range.selectNodeContents(n);for(const r of range.getClientRects())if(r.width&&r.height&&(r.left<bound.left-eps||r.right>bound.right+eps||r.top<bound.top-eps||r.bottom>bound.bottom+eps))errors.push(label+':text outside');}
 };
 for(const [i,el]of [...root.querySelectorAll('.driving-person-metric')].entries()){if(el.scrollWidth>el.clientWidth+1||el.scrollHeight>el.clientHeight+1)errors.push('metric '+i+':overflow');textInside(el,'metric '+i);}
 for(const group of root.querySelectorAll('.driving-person-metrics')){const rects=[...group.querySelectorAll('.driving-person-metric')].map(e=>e.getBoundingClientRect());for(let i=0;i<rects.length;i++)for(let j=i+1;j<rects.length;j++){const a=rects[i],b=rects[j];if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>eps&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>eps)errors.push('metric tiles overlap');}}
 for(const [i,el]of [...root.querySelectorAll('.driving-person-review-entry')].entries()){const cs=getComputedStyle(el),r=el.getBoundingClientRect();if(cs.display==='none'||cs.visibility==='hidden'||!r.width||!r.height||el.scrollHeight>el.clientHeight+1||el.scrollWidth>el.clientWidth+1)errors.push('review '+i+':hidden or clipped');textInside(el,'review '+i);}
 return errors;
});assert.deepEqual(geometry,[],`inner geometry ${mode}/${width}/${scale}`);
await page.screenshot({path:path.join(out,`${mode}-${width}-${scale}.png`),fullPage:true});rows.push({width,textScale:scale,mode});await context.close();}
assert.equal(posts,0);assert.equal(external,0);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({cases:rows,posts,external,synthetic:true,live:false}));}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)});
