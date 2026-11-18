// Isolated existing TEST fixture only. Never use a Live URL.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright'),fs=require('fs'),assert=require('node:assert/strict');
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),out=process.argv[3];assert(Number.isInteger(fixture.port));const base='http://127.0.0.1:'+fixture.port;
let browser,page;const results=[];
(async()=>{fs.mkdirSync(out,{recursive:true});browser=await chromium.launch({headless:true,executablePath:process.env.Q12_BROWSER_EXECUTABLE||undefined});
for(const width of [320,390,768,1440]){
 const context=await browser.newContext({viewport:{width,height:900},hasTouch:true,serviceWorkers:'block'}),blocked=[];await context.addCookies([{name:'dkss_session',value:fixture.cookie,url:base}]);await context.routeWebSocket('**/*',ws=>{blocked.push('WS');ws.close()});await context.route('**/*',r=>{if(new URL(r.request().url()).origin!==base||r.request().method()!=='GET'){blocked.push(r.request().method());return r.abort()}return r.continue()});page=await context.newPage();
 await page.goto(base+'/vehicle/inspection-plans?view=year&month=2026-07');await page.locator('.ip-year-days-scroll').waitFor();
 const scroll=page.locator('.ip-year-days-scroll');await page.locator('[data-year-month-picker]').fill('2026-07');await page.waitForFunction(()=>document.querySelector('input[name=month]').value==='2026-07');await scroll.scrollIntoViewIfNeeded();
 assert.equal(await page.locator('[data-period-title]').textContent(),'2026年度');assert.equal(await page.locator('[data-year-month-picker]').inputValue(),'2026-07');
 assert.equal(await page.locator('#notificationMenu').isVisible(),false);assert.equal(await page.locator('.top-bar-user').isVisible(),false);assert.equal(await page.locator('#sidebarToggle').isVisible(),true);
 if(width<=700){
  const plus=await page.locator('[data-plan-add]').boundingBox(),search=await page.locator('[data-plan-search-toggle]').boundingBox();assert(plus.width>=44&&plus.height>=44);assert(plus.y>search.y+100);assert.equal(await page.locator('.ip-year-month-head small').first().isVisible(),false);
  const client=await context.newCDPSession(page);
  async function swipe(dx,dy){const box=await scroll.boundingBox(),x=box.x+box.width*.65,y=Math.min(box.y+Math.min(box.height*.65,250),840);assert(y>box.y&&y<box.y+box.height);await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});for(let i=1;i<=10;i++){await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+dx*i/10,y:y+dy*i/10}]});await page.waitForTimeout(18)}await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await page.waitForTimeout(350)}
  const before=await scroll.evaluate(e=>({left:e.scrollLeft,top:e.scrollTop}));await swipe(-25,-100);const vertical=await scroll.evaluate(e=>({left:e.scrollLeft,top:e.scrollTop}));assert(Math.abs(before.left-vertical.left)<2);assert(vertical.top>before.top);assert.equal(await page.locator('[data-year-month-picker]').inputValue(),'2026-07');
  await swipe(-110,-8);const horizontal=await scroll.evaluate(e=>e.scrollLeft);assert(horizontal>vertical.left+20);await page.waitForTimeout(600);const aligned=await scroll.evaluate(e=>{const g=e.firstElementChild,day=g.querySelector('.ip-year-head').offsetWidth,max=e.scrollWidth-e.clientWidth;return [...g.querySelectorAll('.ip-year-month-head')].some(h=>Math.abs(e.scrollLeft-Math.min(Math.max(0,h.offsetLeft-g.offsetLeft-day),max))<2)});assert(aligned,'horizontal position must settle on a month boundary');await page.screenshot({path:out+`/axis-${width}.png`});
 }
 await page.screenshot({path:out+`/header-year-${width}.png`});assert.deepEqual(blocked,[]);results.push({width,passed:true,guideAvailable:true});await context.close();page=null;
}
fs.writeFileSync(out+'/axis-report.json',JSON.stringify({results,synthetic:true,nativeTouchCDP:true,realIPhone:false},null,2));await browser.close();})().catch(async e=>{console.error(e);if(page)await page.screenshot({path:out+'/axis-failure.png',fullPage:true}).catch(()=>{});await browser?.close();process.exitCode=1});
