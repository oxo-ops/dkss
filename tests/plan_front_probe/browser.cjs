// Isolated fixture only. Instrumentation/candidate replacements never enter product files.
const fs=require('fs'),assert=require('node:assert/strict'),{chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fixture=JSON.parse(fs.readFileSync(process.argv[2])),out=process.argv[3],base='http://127.0.0.1:'+fixture.port;
assert(Number.isInteger(fixture.port));
(async()=>{fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:process.env.Q12_BROWSER_EXECUTABLE});const results=[];
for(const candidate of [false,true])for(const width of [390,1440])for(const view of ['month','calendar','year']){
 const ctx=await browser.newContext({viewport:{width,height:850},serviceWorkers:'block'});await ctx.addCookies([{name:'dkss_session',value:fixture.cookie,url:base}]);
 await ctx.route('**/*',async route=>{let req=route.request();assert.equal(new URL(req.url()).origin,base);assert.equal(req.method(),'GET');
 if(new URL(req.url()).pathname==='/static/js/vehicle_inspection_plans.js'){
 let s=fs.readFileSync(process.env.PLAN_REPO+'/static/js/vehicle_inspection_plans.js','utf8');
 if(candidate)s=s.replaceAll('draw(); renderSearchResults();','draw();').replaceAll('draw();renderSearchResults();','draw();');
 s=s.replace('function draw() {','function __probeDraw() {').replace('function renderSearchResults() {','function __probeSearch() {');
 const end=s.lastIndexOf('})();');assert(end>0);
 s=s.slice(0,end)+`window.__planPerf={draw:[],search:[]}; function draw(){let start=performance.now();try{return __probeDraw()}finally{window.__planPerf.draw.push(performance.now()-start)}} function renderSearchResults(){let start=performance.now();try{return __probeSearch()}finally{window.__planPerf.search.push(performance.now()-start)}}\n`+s.slice(end);
 return route.fulfill({status:200,contentType:'text/javascript',body:s});
 }return route.continue();});
 const p=await ctx.newPage(),errors=[];p.on('pageerror',e=>errors.push(e.message));
 const start=Date.now();await p.goto(base+'/vehicle/inspection-plans?scope=company&month=2026-11&view='+view);await p.waitForFunction(()=>window.__planPerf?.draw.length>0);await p.evaluate(()=>document.fonts.ready);
 const initial=await p.evaluate(()=>({perf:structuredClone(window.__planPerf),nodes:document.querySelectorAll('*').length,tableRows:document.querySelectorAll('[data-plan-grid-body] tr').length,tableOpen:document.querySelector('[data-plan-vehicle-table]').open}));
 const readyMs=Date.now()-start;if(width<768){await p.locator('[data-plan-search-toggle]').click();await p.locator('.ip-search-dialog[open]').waitFor();}await p.evaluate(()=>{window.__planPerf.draw=[];window.__planPerf.search=[]});await p.locator('input[name=search]:visible').fill('試験');
 const search=await p.evaluate(()=>({perf:structuredClone(window.__planPerf),count:document.querySelectorAll('.ip-search-result').length,text:document.querySelector('[data-search-status]')?.textContent||'',table:document.querySelector('[data-plan-grid-body]').textContent}));
 assert.equal(errors.length,0,errors.join('\n'));if(width<768)assert(search.count>0);else assert(search.table.includes('試験'));results.push({candidate,width,view,readyMs,initial,search});await ctx.close();
}await browser.close();for(const before of results.filter(r=>!r.candidate)){const after=results.find(r=>r.candidate&&r.width===before.width&&r.view===before.view);assert.equal(before.search.count,after.search.count);assert.equal(before.search.text,after.search.text);assert.equal(before.search.table,after.search.table);assert.equal(before.search.perf.search.length,2);assert.equal(after.search.perf.search.length,1);}
fs.writeFileSync(out+'/front-profile.json',JSON.stringify(results,null,2));})().catch(e=>{console.error(e);process.exit(1)});
