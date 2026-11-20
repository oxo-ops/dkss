const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path');
const root=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);
(async()=>{const browser=await chromium.launch({headless:true});const results=[];
try{for(const view of ['calendar','month'])for(const cpuRate of [1,4])for(let iteration=0;iteration<3;iteration++){
 const width=390,kind='planner',condition='original'; const context=await browser.newContext({viewport:{width,height:844},serviceWorkers:'block'});const page=await context.newPage();const cdp=await context.newCDPSession(page);await cdp.send('Emulation.setCPUThrottlingRate',{rate:cpuRate});const errors=[],blocked=[];page.on('pageerror',e=>errors.push(e.message));
 await context.routeWebSocket('**/*',ws=>ws.close());
 await context.route('**/*',async route=>{const req=route.request(),u=new URL(req.url());if(u.origin!=='http://isolated.test'||req.method()!=='GET'){blocked.push({url:u.origin+u.pathname,method:req.method()});return route.abort();}let data,type='text/html';
 if(u.pathname.startsWith('/static/')){const f=path.resolve(root,'.'+u.pathname);if(!f.startsWith(root+'/static/')||!fs.existsSync(f))return route.fulfill({status:404,body:''});data=fs.readFileSync(u.pathname==='/static/css/style.css'&&condition==='compact'?path.join(out,'style.compact.css'):f);type=f.endsWith('.js')?'application/javascript':f.endsWith('.css')?'text/css':f.endsWith('.svg')?'image/svg+xml':f.endsWith('.png')?'image/png':'application/octet-stream';
 if(u.pathname==='/static/css/style.css'&&condition==='css300')await new Promise(r=>setTimeout(r,300));
 if(u.pathname==='/static/js/base.js')data=data.toString()+`\ndocument.addEventListener('DOMContentLoaded',()=>window.measure.bellHandlerReady=performance.now());`;
 if(u.pathname==='/static/js/vehicle_inspection_plans.js'){
  data=data.toString();if(!data.includes('    function draw() {')||!data.includes('        renderSearchResults();\n        requestAnimationFrame(fitLayout);'))throw Error('instrumentation source drift');
  const insert=(from,to)=>{if(!data.includes(from))throw Error('Trace instrumentation drift '+from);data=data.replace(from,to);};
  insert('    function fitLayout(){fitTable();fitCalendar();}',"    function fitLayout(){performance.mark('probe-fit-start');try{fitTable();fitCalendar();}finally{performance.mark('probe-fit-end');}}");
  insert("        for(const cell of grid.querySelectorAll('[data-date]')) {","        for(const cell of grid.querySelectorAll('[data-date]')) { performance.mark('probe-day-start');");
  insert('            const room=Math.max','            performance.mark("probe-measure-start"); const room=Math.max');
  insert('            entries.slice(0,limit).forEach','            performance.mark("probe-measure-end"); entries.slice(0,limit).forEach');
  insert("items.append(more);}",'items.append(more);} performance.mark("probe-day-end");');
  data=data.replace('    function draw() {','    function draw() { window.measure.drawStart=performance.now();').replace('        renderSearchResults();\n        requestAnimationFrame(fitLayout);','        renderSearchResults();\n        window.measure.drawEnd=performance.now(); requestAnimationFrame(()=>{fitLayout();window.measure.fitEnd=performance.now();requestAnimationFrame(()=>window.measure.frameAfterDraw=performance.now());});');
 }
 }else if(u.pathname==='/vehicle/inspection-plans')data=fs.readFileSync(path.join(out,'response-0.bin')).toString().replace(/(?:&#34;|&quot;)view(?:&#34;|&quot;):\s*(?:&#34;|&quot;)[^&]*(?:&#34;|&quot;)/, '&quot;view&quot;: &quot;'+view+'&quot;');else if(u.pathname==='/notifications')data=fs.readFileSync(path.join(out,'response-2.bin'));else if(u.pathname==='/api/vehicle/inspection-plans'||u.pathname==='/api/notifications/recent'){if(condition==='api300')await new Promise(r=>setTimeout(r,300));data=fs.readFileSync(path.join(out,u.pathname.includes('inspection-plans')?'response-1.bin':'response-3.bin'));type='application/json';}else return route.fulfill({status:404,body:''});return route.fulfill({status:200,contentType:type,body:data});});
 await page.addInitScript(()=>{window.measure={};});
 const events=[];cdp.on('Tracing.dataCollected',e=>events.push(...e.value));const traceEnd=new Promise(r=>cdp.on('Tracing.tracingComplete',r));
 await cdp.send('Tracing.start',{categories:'devtools.timeline,blink.user_timing',transferMode:'ReportEvents'});
 await page.goto('http://isolated.test/'+(kind==='planner'?'vehicle/inspection-plans?scope=company&year=2026&month=2026-11&view='+view:'notifications'),{waitUntil:'load'});
 if(kind==='planner')await page.waitForFunction(()=>window.measure.frameAfterDraw);
 await page.waitForTimeout(300);
 await cdp.send('Tracing.end');await traceEnd;
 const actualView=await page.locator('[data-inspection-planner]').getAttribute('data-view');if(actualView!==view)throw Error('Wrong fixture view '+actualView+' expected '+view);
 const measure=await page.evaluate(()=>window.measure);
 const marks=events.filter(e=>e.name.startsWith('probe-')&&e.cat.includes('blink.user_timing')).sort((a,b)=>a.ts-b.ts);
 const tally=(from,to)=>{const windows=[];let start;for(const e of marks){if(e.name===from)start=e;if(e.name===to&&start){windows.push([start,e]);start=null;}}return windows.map(([a,b])=>{const selected=events.filter(e=>e.pid===a.pid&&e.tid===a.tid&&e.ts>=a.ts&&e.ts<b.ts&&e.ph==='X'&&['Layout','UpdateLayoutTree'].includes(e.name));return {ms:(b.ts-a.ts)/1000,layout:selected.filter(e=>e.name==='Layout').length,style:selected.filter(e=>e.name==='UpdateLayoutTree').length,layoutMs:selected.filter(e=>e.name==='Layout').reduce((x,e)=>x+(e.dur||0),0)/1000,styleMs:selected.filter(e=>e.name==='UpdateLayoutTree').reduce((x,e)=>x+(e.dur||0),0)/1000};});};
 const fit=tally('probe-fit-start','probe-fit-end'),days=tally('probe-day-start','probe-day-end'),reads=tally('probe-measure-start','probe-measure-end');
 if(!fit.length||(view==='calendar'&&(!days.length||days.length!==reads.length)))throw Error('Missing layout trace markers: '+JSON.stringify({marks:marks.length,fit:fit.length,days:days.length,reads:reads.length}));
 results.push({view,cpuRate,iteration,measure,fit,days,reads,errors,blocked});
 fs.writeFileSync(path.join(out,`trace-${view}-${cpuRate}-${iteration}.json`),JSON.stringify({traceEvents:events}));
 await context.close();
}
const sum=(a,k)=>a.reduce((n,x)=>n+x[k],0);
fs.writeFileSync(path.join(out,'planner-layout-summary.json'),JSON.stringify(results,null,2));
console.log('LAYOUT_TRACE_SUMMARY '+JSON.stringify(results.map(({view,cpuRate,iteration,fit,days,reads,errors,blocked})=>({view,cpuRate,iteration,fitCalls:fit.length,fitLayout:sum(fit,'layout'),fitStyle:sum(fit,'style'),fitMs:sum(fit,'ms'),fitLayoutMs:sum(fit,'layoutMs'),fitStyleMs:sum(fit,'styleMs'),dayCalls:days.length,dayLayout:sum(days,'layout'),dayStyle:sum(days,'style'),readsWithLayout:reads.filter(r=>r.layout>0).length,readsLayout:sum(reads,'layout'),readsLayoutMs:sum(reads,'layoutMs'),errors,blocked}))));
if(results.some(r=>r.errors.length||r.blocked.length))throw Error('Errors in isolated measurement');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
