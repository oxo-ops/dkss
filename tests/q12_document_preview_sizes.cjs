// Fresh contexts: conservative sizes must never upscale a display derivative.
const {chromium}=require('playwright'),fs=require('fs'),assert=require('node:assert/strict');
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.Q12_BROWSER_EXECUTABLE||undefined,
args:['--disable-background-networking','--no-proxy-server','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1']});
const results=[];
try{for(const [width,dpr] of [[320,2],[390,3],[768,2],[1001,1],[1180,1.25],[1440,1],[1920,1],[2560,1]]){
 const base='http://127.0.0.1:'+fixture.port;
 const c=await b.newContext({viewport:{width,height:1000},deviceScaleFactor:dpr,isMobile:width<=768,serviceWorkers:'block'});
 await c.addCookies([{name:'dkss_session',value:fixture.cookie,url:base}]);
 const p=await c.newPage();p.on('request',r=>assert.equal(new URL(r.url()).hostname,'127.0.0.1'));
 await p.goto(base+'/vehicle/karte/1/documents?document=document:q12-jpg',{waitUntil:'load'});
 for(const sidebar of ['initial','toggled']){
  if(sidebar==='toggled')await p.locator('#sidebarToggle').click();
  const image=p.locator('.kd-image-preview img');await image.scrollIntoViewIfNeeded();await image.evaluate(i=>i.decode());
  const info=await image.evaluate(async i=>{
   const bitmap=await createImageBitmap(await(await fetch(i.currentSrc)).blob());
   const data={selected:new URL(i.currentSrc).pathname+new URL(i.currentSrc).search,
    cssWidth:i.getBoundingClientRect().width,pixels:bitmap.width,dpr:devicePixelRatio};bitmap.close();return data;
  });
  if(info.selected.includes('preview='))assert(info.pixels>=Math.ceil(info.cssWidth*info.dpr),JSON.stringify(info));
  else assert.equal(info.pixels,1600);
  results.push({viewport:width,sidebar,...info});
 }
 await c.close();
}fs.writeFileSync(process.argv[3],JSON.stringify(results,null,2));}finally{await b.close();}})().catch(e=>{console.error(e);process.exitCode=1});
