// Real Chromium rendering with native timezone override; only synthetic loopback data.
const {chromium} = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
assert.equal(fixture.marker, 'q05-synthetic-only');
assert.equal(fixture.host, '127.0.0.1');
const base = `http://127.0.0.1:${fixture.port}`, out = path.resolve(process.argv[3]);
fs.mkdirSync(out, {recursive:true});
const cases = [
  ['year-before','2026-12-31T14:59:59Z','admin'],
  ['year-at','2026-12-31T15:00:00Z','admin'],
  ['year-after','2027-01-01T15:00:00Z','admin'],
  ['month-before','2027-04-30T14:59:59Z','month'],
  ['month-at','2027-04-30T15:00:00Z','month'],
  ['leap-before','2028-02-28T14:59:59Z','leap'],
  ['leap-at','2028-02-28T15:00:00Z','leap'],
  ['leap-after','2028-02-29T15:00:00Z','leap'],
  ['leap-month-before','2028-02-29T14:59:59Z','march'],
  ['leap-month-at','2028-02-29T15:00:00Z','march'],
  ['regular-before','2026-12-31T14:59:59Z','regular'],
  ['regular-at','2026-12-31T15:00:00Z','regular'],
  ['regular-after','2027-01-01T15:00:00Z','regular'],
  ['legacy-before','2028-02-28T14:59:59Z','legacy'],
  ['past-year','2026-12-31T15:00:00Z','past'],
  ['blank','2026-12-31T15:00:00Z','blank'],
  ['monthonly','2026-12-31T15:00:00Z','monthonly'],
  ['invalid','2026-12-31T15:00:00Z','invalid'],
  ['unknown','2026-12-31T15:00:00Z','unknown'],
];
const smoke=process.argv[4]==='mobile-smoke';
const selectedCases=smoke?cases.slice(0,1):cases;
function dayNumber(value) {
  const match = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(value || '');
  if (!match) return null;
  const [y,m,d] = match.slice(1).map(Number), stamp = Date.UTC(y,m-1,d), result = new Date(stamp);
  return result.getUTCFullYear()===y && result.getUTCMonth()===m-1 && result.getUTCDate()===d ? stamp/86400000 : null;
}
function expected(driver, today) {
  const start = dayNumber(driver.start);
  if (start === null) return {personal:'—', listing:'0日継続中', days:null};
  const days = today-start;
  if (days < 0) {
    const label = `開始予定（${new Date(start*86400000).toISOString().slice(0,10).replaceAll('-','/')}）`;
    return {personal:label, listing:label, days:null};
  }
  return {personal:String(days), listing:days>=365 ? `${Math.floor(days/365)}年${days%365}日継続中` : `${days}日継続中`, days};
}
async function visibleBox(locator) {
  assert.equal(await locator.isVisible(), true);
  return locator.evaluate(el => {
    const rect=el.getBoundingClientRect(), parent=el.parentElement.getBoundingClientRect();
    return {width:rect.width,height:rect.height,left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,
      parentLeft:parent.left,parentRight:parent.right,parentBottom:parent.bottom,
      scrollWidth:el.scrollWidth,clientWidth:el.clientWidth,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight,
      font:getComputedStyle(el).fontSize,lineHeight:getComputedStyle(el).lineHeight};
  });
}
let browser;
const results=[], screenshots=[], errors=[];
(async()=>{
  browser=await chromium.launch({headless:true, executablePath:process.env.Q05_BROWSER_EXECUTABLE || undefined,
    args:['--disable-background-networking','--no-proxy-server','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1']});
  const version=browser.version();
  for (const mobile of (smoke?[true]:[false,true])) {
    const profile=mobile?'mobile':'pc';
    const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1000},
      deviceScaleFactor:mobile?2:1,isMobile:mobile,hasTouch:mobile,serviceWorkers:'block'});
    await context.route('**/*', route=>new URL(route.request().url()).origin===base ? route.continue() : route.abort());
    const page=await context.newPage(), cdp=await context.newCDPSession(page);
    page.on('pageerror',error=>errors.push(error.message));
    await page.clock.install({time:new Date(cases[0][1])});
    for (const zone of (smoke?['Asia/Tokyo']:['Asia/Tokyo','Pacific/Honolulu'])) {
      await cdp.send('Emulation.setTimezoneOverride',{timezoneId:''});
      await cdp.send('Emulation.setTimezoneOverride',{timezoneId:zone});
      for (const [name,instant,actor] of selectedCases) {
        fs.writeFileSync(fixture.control+'.tmp',JSON.stringify({instant}));
        fs.renameSync(fixture.control+'.tmp',fixture.control);
        await page.clock.setFixedTime(new Date(instant));
        const response=await page.goto(base+'/__q05_session/'+actor,{waitUntil:'networkidle'});
        assert.equal(response.status(),200,name+' dashboard');
        assert.equal(new URL(page.url()).pathname,'/');
        const clock=await page.evaluate(value=>({zone:Intl.DateTimeFormat().resolvedOptions().timeZone,
          offset:new Date(value).getTimezoneOffset(),local:new Date(value).toString(),now:new Date().toISOString()}),instant);
        assert.equal(clock.zone,zone);
        assert.equal(clock.offset,zone==='Asia/Tokyo'?-540:600);
        assert.equal(clock.now,new Date(instant).toISOString());
        const today=Math.floor((Date.parse(instant)+9*3600000)/86400000);
        const driver=fixture.drivers.find(d=>d.company==='TEST'&&d.actor===actor), want=expected(driver,today);
        const card=page.locator('.dashboard-reference-safety .summary-card.main');
        assert.equal(await card.evaluate(el=>el.tagName),driver.role==='admin'?'A':'DIV');
        const value=card.locator('.summary-value');
        assert.equal((await value.innerText()).trim(),want.personal,name+' personal');
        assert.equal(await card.locator('.summary-unit').count(),want.personal.startsWith('開始予定')?0:1);
        const geometry=await visibleBox(value);
        const titleGeometry=await visibleBox(card.locator('.summary-title'));
        // A future label must leave a readable title at the 390px viewport.
        assert(titleGeometry.height<=2*parseFloat(titleGeometry.lineHeight)+1,name+' cramped heading');
        assert(geometry.width>0&&geometry.height>0);
        assert(geometry.scrollWidth<=geometry.clientWidth+1&&geometry.scrollHeight<=geometry.clientHeight+1,name+' clipped value');
        assert(geometry.left>=geometry.parentLeft-1&&geometry.right<=geometry.parentRight+1&&geometry.bottom<=geometry.parentBottom+1,name+' outside card');
        const capture=name==='year-before'||name==='leap-at';
        const stem=`${profile}-${zone.replace('/','_')}-${name}`;
        if(capture) {const file=stem+'-personal.png';await card.screenshot({path:path.join(out,file),animations:'disabled'});screenshots.push(file);}
        // dashboard.js moves the server card into an initially hidden panel.
        await page.locator('[data-reference-target="#dashboard-reference-ranking"]').click();
        const ranking=page.locator('#dashboard-panel-ranking');
        await ranking.waitFor({state:'visible'});
        const ranked=await ranking.locator('tr:has(td)').evaluateAll(rows=>rows.map(row=>({
          name:row.cells[1].innerText.trim(),days:Number(row.cells[3].innerText.replace(/[^\d-]/g,''))})));
        const eligible=fixture.drivers.filter(d=>d.company==='TEST'&&dayNumber(d.start)!==null&&dayNumber(d.start)<=today);
        assert.deepEqual(ranked.map(r=>r.name).sort(),eligible.map(d=>d.name).sort(),name+' ranking membership');
        for (const row of ranked) assert.equal(row.days,today-dayNumber(eligible.find(d=>d.name===row.name).start));
        for (let i=1;i<ranked.length;i++) assert(ranked[i-1].days>=ranked[i].days);
        if(capture) {
          for(const [part,target] of [['ranking',ranking]]) {
            const file=stem+'-'+part+'.png'; await target.screenshot({path:path.join(out,file),animations:'disabled'}); screenshots.push(file);
          }
        }
        if(driver.role==='user') await page.goto(base+'/__q05_session/admin',{waitUntil:'networkidle'});
        const listingResponse=await page.goto(base+'/master/drivers',{waitUntil:'networkidle'});
        assert.equal(listingResponse.status(),200,name+' listing');
        const row=page.locator(mobile?'.mobile-list-card':'.checklist-table tbody tr').filter({has:page.getByText(actor,{exact:true})});
        assert.equal(await row.count(),1);
        assert.equal(await row.isVisible(),true);
        const shown=mobile?row.locator('.mobile-card-row').filter({has:page.getByText('無事故・無違反',{exact:true})}).locator('strong'):row.locator('td').nth(3);
        assert.equal((await shown.innerText()).trim().split('\n')[0],want.listing,name+' listing value');
        const listingBox=await visibleBox(shown);
        assert(listingBox.scrollWidth<=listingBox.clientWidth+1&&listingBox.scrollHeight<=listingBox.clientHeight+1,name+' clipped listing');
        if(capture) {const file=stem+'-listing.png';await row.screenshot({path:path.join(out,file),animations:'disabled'});screenshots.push(file);}
        const current=await (await context.request.get(base+'/__q05_snapshot')).json();
        assert.deepEqual(current.drivers,fixture.initial.drivers,name+' saved start dates');
        assert.deepEqual(current.user_timezones,fixture.initial.user_timezones,name+' saved user timezones');
        assert.equal(current.history_sha256,fixture.initial.history_sha256,name+' raw history');
        assert.deepEqual(current.usage,[{company:'TEST',users:fixture.expected_users,vehicles:1,login:0}]);
        results.push({profile,zone,name,instant,actor,clock,personal:want.personal,listing:want.listing,
          ranked:ranked.length,geometry,titleGeometry,listingBox,saved_dates_unchanged:true,history_unchanged:true,user_timezones_unchanged:true});
        fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({version,scope:smoke?'mobile-smoke':'full',results,screenshots,errors},null,2));
      }
    }
    await context.close();
  }
  assert.deepEqual(errors,[]);
  assert.equal(results.length,smoke?1:76);
  console.log('Q05 Chromium',version,':',results.length,'cases; PC/mobile; native Tokyo/Honolulu override; all passed');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{
  await browser?.close();
  await fetch(base+'/__q05_stop').catch(()=>{});
});
