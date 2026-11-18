/* Component-state acceptance supplements, never substitutes for real pages. */
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const repo=path.resolve(process.env.PRODUCT_REPO),out=path.resolve(process.env.ARTIFACTS);
const theme=fs.readFileSync(process.env.THEME_PATH||path.join(repo,'static/css/shared_actions.css'),'utf8');
(async()=>{const b=await chromium.launch({headless:true,...(process.env.CHROMIUM?{executablePath:process.env.CHROMIUM}:{}),args:['--no-sandbox']});const rows=[];let current=null,currentWidth=null;
try{for(const width of [320,390,768,1316]){const p=await b.newPage({viewport:{width,height:900}});current=p;currentWidth=width;await p.route('**/*',r=>r.abort());await p.routeWebSocket('**/*',ws=>ws.close());
await p.setContent('<html lang="ja"><body><main><h1>操作ボタン</h1><div id="actions"></div><div id="dynamic"></div></main></body></html>');
await p.addStyleTag({content:fs.readFileSync(path.join(repo,'static/css/style.css'),'utf8')});
await p.addStyleTag({content:'body{padding:16px;margin:0}h1{font-size:20px}#actions,#dynamic{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}button{font:inherit}'});
await p.evaluate(()=>{for(const [cls,label,id]of [['btn-small','詳細','detail'],['btn-small btn-edit','編集','edit'],['btn-small btn-delete','削除','delete'],['btn-small driver-license-remove','削除','license-delete'],['btn','保存','disabled'],['choice-btn','✓','choice'],['status-badge','承認済み','status'],['btn','選択中','selected'],['btn btn-edit','選択中','selected-edit'],['btn btn-delete','選択中','selected-delete']]){const e=document.createElement('button');e.type='button';e.className=cls;e.textContent=label;e.id=id;if(id==='disabled')e.disabled=true;if(id.startsWith('selected'))e.setAttribute('aria-pressed','true');document.querySelector('#actions').append(e)}
window.clickCount=0;document.querySelector('#disabled').addEventListener('click',()=>window.clickCount++);});
const untouched=await p.locator('#choice,#status,#selected,#selected-edit,#selected-delete').evaluateAll(es=>es.map(e=>[getComputedStyle(e).color,getComputedStyle(e).background]));
await p.addStyleTag({content:theme});
assert.deepEqual(await p.locator('#choice,#status,#selected,#selected-edit,#selected-delete').evaluateAll(es=>es.map(e=>[getComputedStyle(e).color,getComputedStyle(e).background])),untouched);
for(const [id,color]of [['detail','rgb(36, 76, 145)'],['edit','rgb(25, 69, 143)'],['delete','rgb(155, 48, 56)'],['license-delete','rgb(155, 48, 56)']])assert.equal(await p.locator('#'+id).evaluate(e=>getComputedStyle(e).color),color);
assert.equal(await p.locator('#disabled').evaluate(e=>getComputedStyle(e).boxShadow),'none');await p.locator('#disabled').evaluate(e=>e.click());assert.equal(await p.evaluate(()=>window.clickCount),0);
await p.keyboard.press('Tab');await p.locator('#edit').focus();assert(await p.locator('#edit').evaluate(e=>document.activeElement===e&&getComputedStyle(e).outlineStyle!=='none'));
// Post-load controls use production class names, with no product handlers executed.
await p.evaluate(()=>{for(const cls of ['btn btn-outline','invoice-button','selected-file-more','selected-file-collapse','notification-popover-undo','btn-small driver-vehicle-remove']){const e=document.createElement('button');e.type='button';e.className=cls;e.textContent='確認';document.querySelector('#dynamic').append(e)}});
for(const e of await p.locator('#dynamic button').all())assert.equal(await e.evaluate(e=>getComputedStyle(e).color),'rgb(36, 76, 145)');
assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await p.screenshot({path:path.join(out,`component-states-${width}.png`),fullPage:true});rows.push({width,disabled:true,focus:true,dynamicSamples:6});await p.close();}
fs.writeFileSync(path.join(out,'component-report.json'),JSON.stringify({rows,syntheticComponents:true,actualDynamicHandlersTested:false},null,2));}catch(e){fs.writeFileSync(path.join(out,'component-failure-report.json'),JSON.stringify({width:currentWidth,completed:rows,error:String(e)},null,2));if(current&&!current.isClosed())await current.screenshot({path:path.join(out,'component-failure.png'),fullPage:true}).catch(()=>{});throw e}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)});
