/* Offline synthetic capture of the real product renderer. No AI, server or DB. */
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'/opt/codex/cua_node/lib/node_modules/playwright');
const base=path.resolve(process.env.PRODUCT_REPO||'demo-first-save-20261118/livebase-repo');
const out=path.resolve(process.env.ARTIFACTS||'demo-guide-expanded-20261118/ai-capture');fs.mkdirSync(out,{recursive:true});
const payload={ok:true,status:'completed',is_current:true,analysis_method:'ai',generated_at:'2026-11-18 12:00',sources:{},analysis:{overview:'点検記録の確認内容です。',maintenance_records:[],feedback_history:[],recommendations:[{proposal_id:'synthetic-proposal-1',category:'整備・点検',target:'タイヤの空気圧',priority:'中',current_state:'調整後の確認待ち',action:'運行前に空気圧とタイヤの状態を確認する',timing:'次の運行前',reason:'直近の点検記録に空気圧調整の記録があります。',source_ids:[]}]}};
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM?{executablePath:process.env.CHROMIUM}:{}),args:['--no-sandbox','--disable-dev-shm-usage']});let posts=0,network=0;const reports=[];try{for(const width of [390,1316]){
 const context=await browser.newContext({viewport:{width,height:844}});const page=await context.newPage();
 await page.route('**/*',async route=>{const req=route.request(),url=new URL(req.url());if(req.method()!=='GET'){posts++;await route.abort();return;}
 if(url.origin!=='https://fixture.invalid'){network++;await route.abort();return;}
 if(url.pathname==='/synthetic-analysis'){await route.fulfill({contentType:'application/json',body:JSON.stringify(payload)});return;}
 if(url.pathname.startsWith('/static/')){const file=path.resolve(base,'.'+url.pathname);if(file.startsWith(base+'/static/')&&fs.existsSync(file)){await route.fulfill({path:file});return;}}
 if(url.pathname==='/capture'){const css=['style','alseon_brand','vehicle_karte_analysis','vehicle_priority_presentation','vehicle_comparison_panels'].map(n=>`<link rel="stylesheet" href="/static/css/${n}.css">`).join('');await route.fulfill({contentType:'text/html',body:`<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${css}</head><body><main class="ka7-proposals"><div id="ka-ai-status" data-url="/synthetic-analysis"></div><div id="ka-ai-results" hidden></div></main><script src="/static/js/vehicle_karte_analysis_ai.js"></script></body></html>`});return;}
 await route.fulfill({status:404,body:'synthetic not found'});
 });
 await page.goto('https://fixture.invalid/capture');const opener=page.locator('.ka-reference-detail-button').first();await opener.click();const drawer=page.locator('.ka-reference-drawer');await drawer.waitFor({state:'visible'});assert((await drawer.innerText()).includes('運行前'));
 await drawer.screenshot({path:path.join(out,`${width}-ai-detail-open.png`)});
 await drawer.locator('.ka-action-evidence > summary').click();assert(await drawer.locator('.ka-action-evidence').evaluate(e=>e.open));await drawer.screenshot({path:path.join(out,`${width}-ai-evidence-open.png`)});
 reports.push({width,actual_product_renderer:true,synthetic_data:true,drawer_open:true,evidence_open:true});await context.close();
 }assert.equal(posts,0);assert.equal(network,0);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({cases:reports,posts,external:network,live:false},null,2));}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
