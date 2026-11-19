const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),html=path.resolve(process.env.HTML_OUT),out=path.resolve(process.env.ARTIFACTS);fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM?{executablePath:process.env.CHROMIUM}:{}),args:['--no-sandbox']});const rows=[];let external=0,posts=0;try{
for(const width of [320,390,650,768,1316])for(const mode of ['self','office','user']){
const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});let baseline=true;
await context.route('**/*',route=>{const r=route.request(),u=new URL(r.url());if(r.method()!=='GET'){posts++;return route.abort()}if(u.origin!=='https://fixture.invalid'){external++;return route.abort()}
if(u.pathname==='/safety/driving-reports')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(html,mode+'-all.html'),'utf8')});
if(baseline&&u.pathname.endsWith('/driving_report_compact.css'))return route.fulfill({contentType:'text/css',body:''});
const p=path.resolve(repo,'.'+u.pathname);if(u.pathname.startsWith('/static/')&&p.startsWith(repo+'/static/')&&fs.existsSync(p))return route.fulfill({path:p});return route.fulfill({status:404,body:'offline'});});
const page=await context.newPage();await page.addInitScript(()=>localStorage.setItem('dkss:first-guide:v1:normal:driving_reports','1'));
async function measure(){await page.goto('https://fixture.invalid/safety/driving-reports?scope='+mode+'&period=all&panel=reports');await page.evaluate(()=>document.fonts.ready);await page.keyboard.press('Escape');return page.locator('#report-list').evaluate(e=>({text:e.innerText,links:[...e.querySelectorAll('a')].map(x=>[x.textContent,x.getAttribute('href')]),height:e.querySelector('tbody tr').getBoundingClientRect().height,display:getComputedStyle(e.querySelector('table')).display,state:[...e.querySelectorAll('.driving-state')].map(x=>getComputedStyle(x).backgroundColor)}));}
const before=await measure();baseline=false;const after=await measure();assert.equal(after.text,before.text);assert.deepEqual(after.links,before.links);assert.deepEqual(after.state,before.state);assert.equal(after.display,before.display);
if(width<=650){assert(after.height<before.height*.8,`height ${width} ${mode}: ${before.height} => ${after.height}`);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'overflow');assert(await page.locator('#report-list td[data-label="日報"] a').evaluateAll(es=>es.every(e=>e.getBoundingClientRect().height>=44)),'touch size');}
else assert(Math.abs(after.height-before.height)<1,'desktop table geometry changed');
const active=page.locator('.driving-view-switch a[aria-current]');assert((await active.evaluate(e=>getComputedStyle(e).backgroundImage)).includes('35, 92, 157'),'blue selection');
await page.screenshot({path:path.join(out,`${mode}-${width}.png`),fullPage:true});rows.push({width,mode,before:before.height,after:after.height,passed:true});await context.close();
}assert.equal(external,0);assert.equal(posts,0);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({rows,external,posts},null,2));console.log(JSON.stringify(rows));}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
