const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path');
const root=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);
(async()=>{const browser=await chromium.launch({headless:true});const results=[];
try{for(const width of [320,390])for(let iteration=0;iteration<3;iteration++)for(const variant of (iteration%2?['dedupe','batch','original']:['original','batch','dedupe'])){
 const view='calendar',cpuRate=1,kind='planner',condition='original'; const context=await browser.newContext({viewport:{width,height:844},serviceWorkers:'block'});const page=await context.newPage();const cdp=await context.newCDPSession(page);await cdp.send('Emulation.setCPUThrottlingRate',{rate:cpuRate});const errors=[],blocked=[];page.on('pageerror',e=>errors.push(e.message));
 await context.routeWebSocket('**/*',ws=>ws.close());
 await context.route('**/*',async route=>{const req=route.request(),u=new URL(req.url());if(u.origin!=='http://isolated.test'||req.method()!=='GET'){blocked.push({url:u.origin+u.pathname,method:req.method()});return route.abort();}let data,type='text/html';
 if(u.pathname.startsWith('/static/')){const f=path.resolve(root,'.'+u.pathname);if(!f.startsWith(root+'/static/')||!fs.existsSync(f))return route.fulfill({status:404,body:''});data=fs.readFileSync(u.pathname==='/static/css/style.css'&&condition==='compact'?path.join(out,'style.compact.css'):f);type=f.endsWith('.js')?'application/javascript':f.endsWith('.css')?'text/css':f.endsWith('.svg')?'image/svg+xml':f.endsWith('.png')?'image/png':'application/octet-stream';
 if(u.pathname==='/static/css/style.css'&&condition==='css300')await new Promise(r=>setTimeout(r,300));
 if(u.pathname==='/static/js/base.js')data=data.toString()+`\ndocument.addEventListener('DOMContentLoaded',()=>window.measure.bellHandlerReady=performance.now());`;
 if(u.pathname==='/static/js/vehicle_inspection_plans.js'){
  data=data.toString();if(!data.includes('    function draw() {')||!data.includes('        renderSearchResults();\n        requestAnimationFrame(fitLayout);'))throw Error('instrumentation source drift');
  if(variant==='dedupe'){
   const scheduled='        requestAnimationFrame(fitCalendar);';
   if(data.split(scheduled).length!==2)throw Error('Duplicate schedule source drift');
   data=data.replace(scheduled,'');
  }
  if(variant==='batch'){
   const begin=data.indexOf("        for(const cell of grid.querySelectorAll('[data-date]')) {",data.indexOf('    function fitCalendar()'));
   const end=data.indexOf('    // Use the app',begin);
   if(begin<0||end<0)throw Error('Batch source drift');
   let fn=data.slice(begin,end);
   fn=fn.replace("        for(const cell of grid.querySelectorAll('[data-date]')) {", "        const cells=[...grid.querySelectorAll('[data-date]')];\n        for(const cell of cells)cell.querySelector('.ip-cal-items').replaceChildren();\n        performance.mark('probe-batch-start'); const sizes=cells.map(cell=>[cell.clientHeight,cell.querySelector('.ip-cal-day-head').offsetHeight]); performance.mark('probe-batch-end');\n        for(const cell of grid.querySelectorAll('[data-date]')) {\n            const [cellHeight,headHeight]=sizes.shift();");
   fn=fn.replace('items.replaceChildren();','').replace("            const head=cell.querySelector('.ip-cal-day-head');\n",'').replaceAll('cell.clientHeight-head.offsetHeight','cellHeight-headHeight');
   data=data.slice(0,begin)+fn+data.slice(end);
  }
  const insert=(from,to)=>{if(!data.includes(from))throw Error('Trace instrumentation drift '+from);data=data.replace(from,to);};
  insert('    function fitLayout(){fitTable();fitCalendar();}',"    function fitLayout(){performance.mark('probe-fit-start');try{fitTable();fitCalendar();}finally{performance.mark('probe-fit-end');}}");
  insert("        for(const cell of grid.querySelectorAll('[data-date]')) {","        for(const cell of grid.querySelectorAll('[data-date]')) { performance.mark('probe-day-start');");
  insert('            const room=Math.max','            performance.mark("probe-measure-start"); const room=Math.max');
  insert('            entries.slice(0,limit).forEach','            performance.mark("probe-measure-end"); entries.slice(0,limit).forEach');
  insert("items.append(more);}",'items.append(more);} performance.mark("probe-day-end");');
  data=data.replace('    function draw() {','    function draw() { window.measure.drawStart=performance.now();').replace('        renderSearchResults();\n        requestAnimationFrame(fitLayout);','        renderSearchResults();\n        window.measure.drawEnd=performance.now(); requestAnimationFrame(()=>{fitLayout();window.measure.fitEnd=performance.now();requestAnimationFrame(()=>window.measure.frameAfterDraw=performance.now());});');
 }
 }else if(u.pathname==='/vehicle/inspection-plans')data=fs.readFileSync(path.join(out,'response-0.bin')).toString().replace(/(?:&#34;|&quot;)view(?:&#34;|&quot;):\s*(?:&#34;|&quot;)[^&]*(?:&#34;|&quot;)/, '&quot;view&quot;: &quot;'+view+'&quot;');else if(u.pathname==='/notifications')data=fs.readFileSync(path.join(out,'response-2.bin'));else if(u.pathname==='/api/vehicle/inspection-plans'||u.pathname==='/api/notifications/recent'){if(condition==='api300')await new Promise(r=>setTimeout(r,300));data=fs.readFileSync(path.join(out,u.pathname.includes('inspection-plans')?'response-1.bin':'response-3.bin'));type='application/json';}else return route.fulfill({status:404,body:''});return route.fulfill({status:200,contentType:type,body:data});});
 await page.addInitScript(()=>{window.measure={};const parse=JSON.parse;JSON.parse=function(data,...args){const out=parse.call(this,data,...args);if(out&&Array.isArray(out.plans))window.probePlans=out.plans.length;return out;};});
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
 const fit=tally('probe-fit-start','probe-fit-end'),days=tally('probe-day-start','probe-day-end'),reads=tally('probe-measure-start','probe-measure-end'),batch=tally('probe-batch-start','probe-batch-end');
 if(!fit.length||(view==='calendar'&&(!days.length||days.length!==reads.length)))throw Error('Missing layout trace markers: '+JSON.stringify({marks:marks.length,fit:fit.length,days:days.length,reads:reads.length}));
 const states=[];
 const snapshot=label=>page.evaluate(label=>{const rect=e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height].map(x=>Math.round(x*100)/100);};const grid=document.querySelector('.ip-cal-grid');const cells=[...grid.querySelectorAll('[data-date]')];const more=document.querySelector('#inspection-plan-events');return {label,month:grid.getAttribute('aria-label'),grid:rect(grid),cells:cells.map(c=>({date:c.dataset.date,rect:rect(c),content:c.innerHTML})),details:more.open?more.querySelector('[data-events-list]').innerHTML:null,search:document.querySelector('[data-search-results]')?.innerHTML||null,filter:document.querySelector('[data-kind][aria-pressed="true"]')?.dataset.kind,apiPlans:window.probePlans};},label);
 const settle=()=>page.waitForTimeout(120);
 const action=css=>page.locator(css).first().evaluate(e=>e.click());
 const record=async name=>{await settle();states.push(await snapshot(name));};
 await record('initial');
 if(!await page.locator('.ip-cal-more').count())throw Error('Fixture lacks overflow');await action('.ip-cal-more');await record('overflow');if(!states.at(-1).details)throw Error('Overflow did not open');await action('[data-events-close]');
 await action('[data-plan-search-toggle]');await page.locator('input[name="search"]').evaluate(e=>{e.value='Synthetic workshop';e.dispatchEvent(new Event('input',{bubbles:true}));});await record('search');
 await action('.ip-search-close');await settle();
 await action('[data-kind="vehicle_inspection"]');await record('filter');if(states.at(-1).filter!=='vehicle_inspection')throw Error('Filter not applied');await action('[data-kind=""]');await settle();
 await action('[data-period="1"]');await page.waitForFunction(()=>document.querySelector('.ip-cal-grid')?.getAttribute('aria-label').startsWith('2026-12'));await record('next-month');
 await action('[data-period="-1"]');await page.waitForFunction(()=>document.querySelector('.ip-cal-grid')?.getAttribute('aria-label').startsWith('2026-11'));await record('back-month');
 results.push({view,width,variant,cpuRate,iteration,measure,fit,days,reads,batch,states,errors,blocked});
 await context.close();
}
const sum=(a,k)=>a.reduce((n,x)=>n+x[k],0);const summary=[];
for(const x of results){const o=results.find(y=>y.width===x.width&&y.iteration===x.iteration&&y.variant==='original');const diffs=x.states.map((v,i)=>({label:v.label,equal:JSON.stringify(v)===JSON.stringify(o.states[i]),cellDifferences:v.cells.filter((c,n)=>JSON.stringify(c)!==JSON.stringify(o.states[i].cells[n])).length}));summary.push({width:x.width,variant:x.variant,iteration:x.iteration,plans:x.states[0].apiPlans,initialDayCalls:x.days.length,withinHeightReads:sum(x.reads,'layout')+sum(x.batch,'layout'),styleWithinHeightReadsMs:sum(x.reads,'styleMs')+sum(x.batch,'styleMs'),nextFrame:x.measure.frameAfterDraw,diffs,errors:x.errors,blocked:x.blocked});}
fs.writeFileSync(path.join(out,'planner-layout-candidate-detail.json'),JSON.stringify(results,null,2));
fs.writeFileSync(path.join(out,'planner-layout-candidate-summary.json'),JSON.stringify(summary,null,2));
console.log('LAYOUT_CANDIDATE_SUMMARY '+JSON.stringify(summary));
if(summary.some(r=>r.errors.length||r.blocked.length||!r.plans))throw Error('Errors or missing fixture data');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
