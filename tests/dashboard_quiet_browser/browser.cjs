const fs=require('fs'),path=require('path'),assert=require('assert'),{chromium}=require(process.env.PLAYWRIGHT_MODULE);
(async()=>{const b=await chromium.launch({headless:true}),out=process.argv[3];fs.mkdirSync(out,{recursive:true});const results=[];
for(const width of[320,390,768,1440]){const p=await b.newPage({viewport:{width,height:900}});let blocked=0;await p.route('**/*',r=>{blocked++;r.abort()});await p.setContent(fs.readFileSync(path.join(process.argv[2],'page.html'),'utf8'));
const before=await p.locator('a').evaluateAll(es=>es.map(e=>e.getAttribute('href')));
for(const badge of await p.locator('.dashboard-safety-state:visible').all()){assert(await badge.evaluate(e=>getComputedStyle(e).whiteSpace==='nowrap'));assert(await badge.evaluate(e=>e.scrollWidth<=e.clientWidth+1));}
assert.equal(await p.locator('.dashboard-video-detail:visible').count(),0);
assert(await p.locator('.dashboard-safety-opening').first().evaluate(e=>getComputedStyle(e,'::after').content==='none'));
assert(!await p.locator('main').innerText().then(s=>s.includes('›')));
const more=p.locator('.dashboard-safety-more');assert(!await more.evaluate(e=>e.open));await more.locator('summary').click();assert(await more.evaluate(e=>e.open));assert.equal(await p.locator('.dashboard-safety-items>li:visible').count(),4);await more.locator('summary').click();assert(!await more.evaluate(e=>e.open));
await p.locator('.dashboard-video-proposal').first().focus();assert(await p.locator('.dashboard-video-proposal').first().evaluate(e=>e===document.activeElement));
assert.deepEqual(await p.locator('a').evaluateAll(es=>es.map(e=>e.getAttribute('href'))),before);
assert.equal(await p.locator('.dashboard-video-state').first().innerText(),'未着手');assert(await p.locator('main').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
await p.screenshot({path:path.join(out,'dashboard-'+width+'.png'),fullPage:true});assert.equal(blocked,0);results.push({width,passed:true,linksUnchanged:true,statusPreserved:true});await p.close();}
fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(results,null,2));await b.close();})().catch(e=>{console.error(e);process.exit(1)});
