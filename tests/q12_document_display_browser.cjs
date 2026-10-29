// Regression gate: request dependencies only when needed; render real local PDFs.
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),crypto=require('crypto'),assert=require('node:assert/strict');
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),output=process.argv[3],manifest=JSON.parse(fs.readFileSync(path.join(path.dirname(process.argv[2]),'documents.json'),'utf8'));
let activePage;
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.Q12_BROWSER_EXECUTABLE||undefined,args:['--disable-background-networking','--no-proxy-server','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1']});const results=[];
try{for(const mobile of [false,true]){const base='http://127.0.0.1:'+fixture.port,c=await b.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1000},isMobile:mobile,deviceScaleFactor:mobile?2:1,serviceWorkers:'block',acceptDownloads:true});await c.addCookies([{name:'dkss_session',value:fixture.cookie,url:base}]);// Delay the second page metadata to exercise asynchronous viewer readiness.
await c.addInitScript(() => {
    const original = Worker.prototype.postMessage;
    Worker.prototype.postMessage = function(message, ...args) {
        if (message?.action === 'GetPage' && message.data?.pageIndex === 1) {
            window.q12DelayedSecondPage = true;
            // A resize during the delayed metadata must not leave later pages unsized.
            const scroll = document.querySelector('[data-pdf-scroll]');
            const width = scroll.style.width;
            scroll.style.width = 'calc(100% - 1px)';
            setTimeout(() => { scroll.style.width = width; }, 250);
            setTimeout(() => original.call(this, message, ...args), 600);
            return;
        }
        return original.call(this, message, ...args);
    };
});
const p=await c.newPage(),errors=[],requests=[];p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>{assert.equal(new URL(r.url()).hostname,'127.0.0.1');requests.push(new URL(r.url()).pathname);});
activePage=p;
const route='/vehicle/karte/'+manifest.vehicle_id+'/documents';
for(const selection of ['closed','document:q12-jpg']){requests.length=0;await p.goto(base+route+'?document='+selection,{waitUntil:'load'});assert.equal(await p.locator('.top-bar-user').count(),1);assert.equal(await p.locator('script[src*="maintenance_invoice_pdf_viewer"]').count(),0);assert(!requests.some(x=>x.includes('/vendor/pdfjs/')||x.includes('maintenance_invoice_pdf_viewer')));
if(selection!=='closed'){const image=p.locator('.kd-image-preview img');assert(await image.evaluate(e=>e.complete&&e.naturalWidth===1600));assert(!(await image.getAttribute('src')).includes('thumb='));}await p.locator('[data-document-check-all]').check();assert.equal(await p.locator('[data-document-check]:checked').count(),2);}
const integrity=[];let pdfDimensions=[];
for(const doc of manifest.documents){if(doc.extension==='pdf'){requests.length=0;await p.goto(base+route+'?document=document:'+doc.id,{waitUntil:'load'});await p.waitForFunction(()=>document.querySelector('[data-pdf-count]')?.textContent==='2');await p.waitForFunction(()=>document.querySelector('.invoice-pdf-page canvas')?.width>0);// Total PDF page count is published before asynchronous getPage completes.
await p.waitForFunction(() => document.querySelectorAll('.invoice-pdf-page').length === 2
    && document.querySelector('[data-pdf-status]').textContent.includes('スクロールでページ移動')
    && document.querySelector('[data-pdf-page]').value === '1');
pdfDimensions=await p.locator('.invoice-pdf-page').evaluateAll(pages => pages.map(e => ({width:parseFloat(e.style.width),height:parseFloat(e.style.height)})));
assert(pdfDimensions.every(e => e.width>0 && e.height>0));
assert(await p.evaluate(() => window.q12DelayedSecondPage === true));assert(requests.some(x=>x.endsWith('/vendor/pdfjs/pdf.mjs')));assert(requests.some(x=>x.endsWith('/vendor/pdfjs/pdf.worker.mjs')));await p.locator('[data-pdf-next]').click();await p.waitForFunction(()=>document.querySelector('[data-pdf-page]').value==='2');await p.locator('[data-pdf-prev]').click();await p.waitForFunction(()=>document.querySelector('[data-pdf-page]').value==='1');const zoom=await p.locator('[data-pdf-zoom]').textContent();await p.locator('[data-pdf-plus]').click();assert.notEqual(await p.locator('[data-pdf-zoom]').textContent(),zoom);await p.locator('[data-pdf-fit-page]').click();await p.locator('[data-pdf-fit]').click();}
const event=p.waitForEvent('download');await p.locator('a.kd-download[href*="/'+doc.id+'/source"]').click();const download=await event;const bytes=fs.readFileSync(await download.path());assert.equal(bytes.length,doc.bytes);assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),doc.sha256);integrity.push({extension:doc.extension,bytes:bytes.length,sha256:doc.sha256});}
await p.screenshot({path:output.replace('.json',mobile?'-mobile.png':'-pc.png')});await p.locator('.kd-preview-close').click();await p.waitForLoadState('networkidle');assert.equal(await p.locator('.invoice-pdf-viewer').count(),0);await p.goBack({waitUntil:'load'});assert.equal(await p.locator('.invoice-pdf-viewer').count(),1);assert.deepEqual(errors,[]);results.push({profile:mobile?'mobile':'pc',imageAndClosedNoPdf:true,pdfPagesZoomFit:true,pdfDimensions,selectionAndBack:true,originalDownloads:integrity,errors});await c.close();}
fs.writeFileSync(output,JSON.stringify(results,null,2));}catch(error){
    const state = await activePage?.evaluate(() => ({
        path: location.pathname + location.search,
        pages: document.querySelectorAll('.invoice-pdf-page').length,
        pageSizes: [...document.querySelectorAll('.invoice-pdf-page')].map(e=>({width:e.style.width,height:e.style.height})),
        current: document.querySelector('[data-pdf-page]')?.value,
        total: document.querySelector('[data-pdf-count]')?.textContent,
        status: document.querySelector('[data-pdf-status]')?.textContent,
        scroll: (() => { const e=document.querySelector('[data-pdf-scroll]'); return e&&{top:e.scrollTop,height:e.clientHeight,total:e.scrollHeight}; })()
    })).catch(() => ({}));
    fs.writeFileSync(output.replace('.json','-failure.json'), JSON.stringify({error:String(error),state},null,2));
    await activePage?.screenshot({path:output.replace('.json','-failure.png')}).catch(() => {});
    throw error;
}finally{await b.close();}})().catch(e=>{console.error(e);process.exitCode=1});
