const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const args = process.argv.slice(2);
const fixture = JSON.parse(fs.readFileSync(args[0], 'utf8'));
const output = args[1];
const mode = args[2] || 'baseline';
const profiles = process.env.Q12_PROFILES?.split(',') || (args[3] === 'quick' ? ['pc-fast', 'mobile-fast'] : ['pc-fast','mobile-fast','pc-slow','mobile-slow']);
const base = `http://127.0.0.1:${fixture.port}`;
const routes = process.env.Q12_ROUTES?.split(',') || (args[3] === 'focus' ? ['/','/settings'] : ['/','/vehicle/karte','/vehicle/karte/1','/settings']);
let activeBrowser;
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.Q12_BROWSER_EXECUTABLE || undefined,args:['--disable-background-networking','--no-proxy-server','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1']});
  activeBrowser = browser;
  const results = [];
  for (const profile of profiles) {
    const mobile = profile.startsWith('mobile');
    const context = await browser.newContext({viewport: mobile ? {width:390,height:844} : {width:1440,height:1000},
      deviceScaleFactor:mobile?2:1,isMobile:mobile,hasTouch:mobile,serviceWorkers:'block'});
    await context.addCookies([{name:'dkss_session',value:fixture.cookie,url:base}]);
    const external = [];
    // Request interception disables Chromium's HTTP cache; do not use it in cache measurements.
    context.on('request', request => { const url = new URL(request.url()); if(url.hostname !== '127.0.0.1') external.push(url.origin); });
    for (const route of routes) {
      const page = await context.newPage();
      const cdp = await context.newCDPSession(page);
      await cdp.send('Network.enable');
      await cdp.send('Performance.enable');
      if(profile.endsWith('slow')) {
        await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:150,downloadThroughput:200000,uploadThroughput:100000,connectionType:'cellular4g'});
        await cdp.send('Emulation.setCPUThrottlingRate',{rate:4});
      }
      await page.addInitScript(() => {
        window.q12 = {cls:0,longTasks:0,longTaskMs:0,shifts:[]};
        new PerformanceObserver(list => list.getEntries().forEach(e => { if(!e.hadRecentInput){window.q12.cls += e.value;window.q12.shifts.push({ms:e.startTime,value:e.value,sources:(e.sources||[]).map(s=>({tag:s.node?.tagName,id:s.node?.id,classes:s.node?.className,before:s.previousRect.toJSON(),after:s.currentRect.toJSON()}))});} })).observe({type:'layout-shift',buffered:true});
        new PerformanceObserver(list => list.getEntries().forEach(e => {window.q12.longTasks++;window.q12.longTaskMs+=e.duration;})).observe({type:'longtask',buffered:true});
      });
      for (let visit=0;visit<2;visit++) {
        await cdp.send('Network.setCacheDisabled',{cacheDisabled:visit===0});
        const response = await page.goto(base+route,{waitUntil:'load',timeout:120000});
        await page.waitForTimeout(350);
        const metrics = await page.evaluate(() => {
          const nav=performance.getEntriesByType('navigation')[0];
          const resources=performance.getEntriesByType('resource').map(r=>({url:new URL(r.name).pathname,type:r.initiatorType,ms:r.duration,transfer:r.transferSize,encoded:r.encodedBodySize,decoded:r.decodedBodySize}));
          const imgs=[...document.images].map(im=>({url:new URL(im.currentSrc || im.src,location.href).pathname,width:im.width,height:im.height,naturalWidth:im.naturalWidth,naturalHeight:im.naturalHeight,complete:im.complete}));
          return {document:{transfer:nav.transferSize,encoded:nav.encodedBodySize,decoded:nav.decodedBodySize},ttfb:nav.responseStart-nav.requestStart,load:nav.loadEventEnd-nav.startTime,dom:nav.domContentLoadedEventEnd-nav.startTime,
            paints:performance.getEntriesByType('paint').map(p=>({name:p.name,ms:p.startTime})),server:nav.serverTiming.map(s=>({name:s.name,ms:s.duration,value:s.description})),
            resources,images:imgs,layout:window.q12,main:document.querySelector('.main-content')?.getBoundingClientRect().toJSON()};
        });
        const perf = await cdp.send('Performance.getMetrics');
        const row={mode,profile,route,visit,status:response.status(),...metrics,engine:Object.fromEntries(perf.metrics.filter(m=>['LayoutDuration','RecalcStyleDuration','ScriptDuration','TaskDuration'].includes(m.name)).map(m=>[m.name,m.value]))};
        results.push(row);fs.writeFileSync(output,JSON.stringify({fixture:{vehicles:fixture.vehicles,avatar:fixture.avatar},results},null,2));
        console.log(mode,profile,route,visit,response.status(),'load',Math.round(metrics.load),'wire',metrics.resources.reduce((s,r)=>s+r.transfer,0),'CLS',metrics.layout.cls.toFixed(4));
        if(visit===0 && (route==='/settings'||route==='/vehicle/karte')) await page.screenshot({path:path.join(path.dirname(output),`${mode}-${profile}-${route.replaceAll('/','_')}.png`)});
      }
      await page.close();
    }
    if(external.length) throw new Error('Unexpected external requests: '+external.join(','));
    await context.close();
  }
  await browser.close();
})().catch(async error=>{console.error(error);await activeBrowser?.close();process.exitCode=1;});
