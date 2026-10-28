// Functional geometry test: interception delays real fixture API data.
// Do not use these intercepted requests for cache or transfer measurements.
const {chromium}=require('playwright');
const fs=require('fs');
const assert=require('node:assert/strict');
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const output=process.argv[3],base='http://127.0.0.1:'+fixture.port;
let browser;
(async()=>{
 browser=await chromium.launch({headless:true,executablePath:process.env.Q12_BROWSER_EXECUTABLE||undefined,
  args:['--disable-background-networking','--no-proxy-server','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1']});
 const results=[];
 for(const width of [320,360,380,390,600,1440]){
  const context=await browser.newContext({viewport:{width,height:900},isMobile:width<=600,hasTouch:width<=600,serviceWorkers:'block'});
  await context.addCookies([{name:'dkss_session',value:fixture.cookie,url:base}]);
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  let release,seen;
  const hold=new Promise(r=>release=r),ready=new Promise(r=>seen=r);
  await page.route('**/api/vehicle/inspection-plans?*',async route=>{
   const response=await route.fetch();seen();await hold;await route.fulfill({response});
  });
  await page.goto(base+'/vehicle/inspection-plans',{waitUntil:'load'});
  await ready;await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(100);
  const geometry=()=>page.evaluate(()=>({
   period:document.querySelector('[data-plan-period]').getBoundingClientRect().toJSON(),
   missing:document.querySelector('.ip-missing').getBoundingClientRect().toJSON(),
   states:document.querySelector('[data-plan-states]').getBoundingClientRect().toJSON(),
   grid:document.querySelector('.ip-grid-scroll').getBoundingClientRect().toJSON(),
   empty:document.querySelector('.ip-empty')?.getBoundingClientRect().toJSON()
  }));
  const before=await geometry();release();
  await page.waitForFunction(()=>!document.querySelector('[data-plan-status]').textContent.includes('読み込み中'));
  await page.waitForTimeout(100);
  const after=await geometry();
  const result={width,before,after,controls:false,errors};
  results.push(result);fs.writeFileSync(output,JSON.stringify(results,null,2));
  if(width<=600){
   assert(Math.abs(after.period.y-before.period.y)<1,'period moved after data at '+width);
   assert(Math.abs(after.missing.y-before.missing.y)<1,'footer moved after data at '+width);
   assert(after.empty.width>after.grid.width*.9,'empty state collapsed to checkbox width at '+width);
  }
  assert.equal(await page.locator('[data-plan-states] button').count(),6);
  for(const view of ['calendar','year','month']){
   await page.locator('[data-view="'+view+'"]').click();
   assert.equal(await page.locator('[data-inspection-planner]').getAttribute('data-view'),view);
  }
  assert.deepEqual(errors,[]);
  result.controls=true;
  await page.screenshot({path:output.replace('.json','-'+width+'.png')});
  await context.close();
 }
 fs.writeFileSync(output,JSON.stringify(results,null,2));
 await browser.close();
})().catch(async e=>{console.error(e);await browser?.close();process.exitCode=1});
