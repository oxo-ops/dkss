const {chromium,webkit}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path');
const root=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);
const fixtures=JSON.parse(fs.readFileSync(path.join(out,'response-1.bin')));
const mainPlans=fixtures.plans.filter(p=>p.planned_month==='2026-11'&&p.kind==='ad_hoc'&&p.reservation_date);
if(mainPlans.length<160)throw Error('Expected at least 160 synthetic reserved plans, got '+mainPlans.length);
const densities={empty:[],sparse:mainPlans.slice(0,3),clustered:mainPlans.slice(0,18).map(p=>({...p,reservation_date:'2026-11-12'})),many:mainPlans};
const profiles=[{name:'narrow',width:320,height:700},{name:'phone',width:390,height:844},{name:'landscape-narrow',width:690,height:360},{name:'landscape-wide',width:844,height:390}];
(async()=>{const results=[];
for(const [engine,launcher] of Object.entries({chromium,webkit})){if(process.env.MATRIX_ENGINE&&process.env.MATRIX_ENGINE!==engine)continue;const browser=await launcher.launch({headless:true});
try{for(const {name:profile,width,height} of profiles)for(const density of Object.keys(densities))for(const variant of ['original','control','batch']){
 const view='calendar',kind='planner',condition='original';
 const context=await browser.newContext({viewport:{width,height},isMobile:true,hasTouch:true,deviceScaleFactor:2,serviceWorkers:'block'});const page=await context.newPage();const errors=[],blocked=[];page.setDefaultTimeout(6000);page.on('pageerror',e=>errors.push(e.message));
 try {
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
   fn=fn.replace("        for(const cell of grid.querySelectorAll('[data-date]')) {", "        const cells=[...grid.querySelectorAll('[data-date]')];\n        const narrow=window.matchMedia('(max-width:700px)').matches; window.probeBatchRuns=(window.probeBatchRuns||0)+Number(narrow); if(narrow)for(const cell of cells)cell.querySelector('.ip-cal-items').replaceChildren();\n        performance.mark('probe-batch-start'); const sizes=narrow?new Map(cells.map(cell=>[cell,[cell.clientHeight,cell.querySelector('.ip-cal-day-head').offsetHeight]])):null; performance.mark('probe-batch-end');\n        for(const cell of grid.querySelectorAll('[data-date]')) {\n");
   fn=fn.replace('items.replaceChildren();','if(!narrow)items.replaceChildren();').replaceAll('cell.clientHeight-head.offsetHeight','(narrow?sizes.get(cell)[0]-sizes.get(cell)[1]:cell.clientHeight-head.offsetHeight)');
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
 }else if(u.pathname==='/vehicle/inspection-plans')data=fs.readFileSync(path.join(out,'response-0.bin')).toString().replace(/(?:&#34;|&quot;)view(?:&#34;|&quot;):\s*(?:&#34;|&quot;)[^&]*(?:&#34;|&quot;)/, '&quot;view&quot;: &quot;'+view+'&quot;');else if(u.pathname==='/notifications')data=fs.readFileSync(path.join(out,'response-2.bin'));else if(u.pathname==='/api/vehicle/inspection-plans'){const month=u.searchParams.get('month');data=JSON.stringify({...fixtures,plans:month==='2026-11'?densities[density]:[],invoice_actuals:[]});type='application/json';}else return route.fulfill({status:404,body:''});return route.fulfill({status:200,contentType:type,body:data});});
 await page.addInitScript(()=>{window.measure={};const parse=JSON.parse;JSON.parse=function(data,...args){const out=parse.call(this,data,...args);if(out&&Array.isArray(out.plans))window.probePlans=out.plans.length;return out;};});
 await page.goto('http://isolated.test/vehicle/inspection-plans?scope=company&year=2026&month=2026-11&view=calendar',{waitUntil:'load'});
 await page.waitForFunction(()=>window.measure.frameAfterDraw);
 const actualView=await page.locator('[data-inspection-planner]').getAttribute('data-view');if(actualView!=='calendar')throw Error('Unexpected calendar view '+actualView);
 const states=[];
 const snapshot=label=>page.evaluate(label=>{const rect=e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height].map(x=>Math.round(x*100)/100);};const grid=document.querySelector('.ip-cal-grid');const cells=[...grid.querySelectorAll('[data-date]')];const more=document.querySelector('#inspection-plan-events');return {label,viewport:[innerWidth,innerHeight],month:grid.getAttribute('aria-label'),grid:rect(grid),cells:cells.map(c=>({date:c.dataset.date,rect:rect(c),content:c.innerHTML})),details:more.open?more.querySelector('[data-events-list]').innerHTML:null,search:document.querySelector('[data-search-results]')?.innerHTML||null,filter:document.querySelector('[data-kind][aria-pressed="true"]')?.dataset.kind,apiPlans:window.probePlans};},label);
 const settle=()=>page.waitForTimeout(120);
 const action=css=>page.locator(css).first().evaluate(e=>e.click());
 const record=async name=>{await settle();states.push(await snapshot(name));};
 await record('initial');
 if(await page.locator('.ip-cal-more').count()){await action('.ip-cal-more');await record('overflow');if(!states.at(-1).details)throw Error('Overflow did not open');await action('[data-events-close]');}
 else await record('no-overflow');
 await action('[data-plan-search-toggle]');await page.locator('input[name="search"]').evaluate(e=>{e.value='Synthetic workshop';e.dispatchEvent(new Event('input',{bubbles:true}));});await record('search');
 await action('.ip-search-close');await settle();
 if(width<=700){await action('[data-plan-filter-toggle]');await settle();} await action('[data-kind="vehicle_inspection"]');await record('filter');if(states.at(-1).filter!=='vehicle_inspection')throw Error('Filter not applied');await action('[data-kind=""]');if(width<=700)await page.locator('#inspection-plan-filter-dialog').evaluate(e=>{if(e.open)e.close();});await settle();
 await action('[data-period="1"]');await page.waitForFunction(()=>document.querySelector('.ip-cal-grid')?.getAttribute('aria-label').startsWith('2026-12'));await record('next-month');
 await action('[data-period="-1"]');await page.waitForFunction(()=>document.querySelector('.ip-cal-grid')?.getAttribute('aria-label').startsWith('2026-11'));await record('back-month');
 await page.setViewportSize({width:height,height:width});await page.evaluate(()=>window.dispatchEvent(new Event('orientationchange')));await record('rotation');
 await page.setViewportSize({width,height});await page.evaluate(()=>window.dispatchEvent(new Event('orientationchange')));await record('rotation-back');
 if(densities[density].length!==states[0].apiPlans||(density==='clustered'&&!states.some(x=>x.label==='overflow')))throw Error('Fixture density not exercised');
 results.push({engine,profile,width,height,density,variant,batchRuns:await page.evaluate(()=>window.probeBatchRuns||0),states,errors,blocked});
 }catch(e){results.push({engine,profile,width,height,density,variant,states:[],errors:[...errors,e.message],blocked});}finally{await context.close();}
}}finally{await browser.close();}}
const rows=[];
for(const x of results.filter(y=>y.variant!=='original')){const o=results.find(y=>y.engine===x.engine&&y.profile===x.profile&&y.density===x.density&&y.variant==='original');const diffs=[];for(let i=0;i<Math.max(x.states.length,o.states.length);i++){const a=o.states[i],b=x.states[i];if(JSON.stringify(a)!==JSON.stringify(b))diffs.push({before:a?.label,after:b?.label,beforeMore:a?.cells.filter(c=>c.content.includes('ip-cal-more')).length,afterMore:b?.cells.filter(c=>c.content.includes('ip-cal-more')).length,cellDifferences:b?.cells.filter((c,n)=>JSON.stringify(c)!==JSON.stringify(a?.cells[n])).length,gridBefore:a?.grid,gridAfter:b?.grid});}rows.push({engine:x.engine,variant:x.variant,batchRuns:x.batchRuns,profile:x.profile,density:x.density,plans:x.states[0]?.apiPlans,states:x.states.length,diffs,beforeErrors:o.errors,afterErrors:x.errors,blocked:[...o.blocked,...x.blocked]});}
fs.writeFileSync(path.join(out,'narrow-layout-matrix-detail.json'),JSON.stringify(results,null,2));fs.writeFileSync(path.join(out,'narrow-layout-matrix-summary.json'),JSON.stringify(rows,null,2));
console.log('NARROW_MATRIX_SUMMARY '+JSON.stringify(rows));if(rows.some(x=>x.beforeErrors.length||x.afterErrors.length||x.blocked.length))throw Error('Matrix harness errors');
})().catch(e=>{console.error(e);process.exit(1)});
