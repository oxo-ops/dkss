'use strict';
// No browser, socket or listener: run the actual shipped controllers in a VM.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const read=name=>fs.readFileSync(path.join(__dirname,'../static/js/',name),'utf8');
const message='保存済み結果を保持しています。この版では内容を正しく表示・更新できません。対応する新版で確認してください。';
const held={ok:true,status:'held',error:'saved_result_requires_newer_version',message,has_result:false,is_current:false,analysis:null,result:null,can_generate:false};
function el(){return {dataset:{},children:[],style:{},hidden:false,textContent:'',isConnected:true,setAttribute(){},replaceChildren(...items){this.children=items;},before(){},addEventListener(){}};}
async function settle(){for(let i=0;i<20;i++)await Promise.resolve();}

test('periodic held GET avoids automatic POST, retry display and fabricated empty proposals',async()=>{
 for(const canGenerate of [true,false]){
  const calls=[],status=el(),retry=el(),list=el(),order=el(),root=el();list.children=['old-high'];
  root.dataset={periodicSuggestions:'/synthetic',canGenerate:String(canGenerate)};
  root.querySelector=s=>({'[data-proposal-status]':status,'[data-proposal-retry]':retry,'[data-proposal-list]':list,'[data-proposal-order]':order}[s]);
  vm.runInNewContext(read('vehicle_periodic_suggestions.js'),{document:{querySelector:s=>s==='[data-periodic-suggestions]'?root:null},window:{addEventListener(){}},Date,setTimeout(){throw Error('held must not poll generation');},clearTimeout(){},fetch:async(url,opt)=>{calls.push(opt.method||'GET');return{ok:true,json:async()=>held};}});
  await settle();assert.deepEqual(calls,['GET']);assert.equal(status.textContent,message);assert.equal(retry.hidden,true);assert.equal(list.children.length,0);assert.equal(order.style.display,'none');
 }
});

test('overview shows retention instead of zero, missing, current-high or a carried recommendation',async()=>{
 const panel=el(),list=el(),status=el(),summary=el();list.children=['old-high'];panel.dataset={resultUrl:'/synthetic',analysisUrl:'/analysis'};
 panel.querySelector=s=>s==='[data-ko-ai-status]'?status:list;
 vm.runInNewContext(read('vehicle_karte_overview.js'),{URL,URLSearchParams,AbortSignal,window:{location:{origin:'https://example.test',search:''}},document:{getElementById:id=>id==='ko-ai'?panel:null,querySelector:s=>s==='[data-ko-summary-count]'?summary:null},fetch:async()=>({ok:true,json:async()=>held})});
 await settle();assert.equal(summary.textContent,'保存保持中');assert.equal(status.textContent,message);assert.equal(status.hidden,false);assert.equal(panel.dataset.current,'false');assert.equal(list.children.length,0);
});

test('normal analysis clears any prior result and shows the server retention reason before empty rendering',async()=>{
 const status=el(),results=el();status.dataset.url='/analysis/result';results.dataset.signature='old';results.children=['old-high'];let polls=0;
 const document={hidden:false,getElementById:id=>id==='ka-ai-status'?status:id==='ka-ai-results'?results:null,querySelector:()=>null,addEventListener(){}};
 vm.runInNewContext(read('vehicle_karte_analysis_ai.js'),{document,URL,URLSearchParams,AbortSignal,window:{location:{origin:'https://example.test',search:'',href:'https://example.test/analysis'}},setTimeout(){polls++;},clearTimeout(){},fetch:async()=>({ok:true,json:async()=>held})});
 await settle();assert.equal(status.textContent,message);assert.equal(status.hidden,false);assert.equal(results.hidden,true);assert.equal(results.children.length,0);assert.equal(results.dataset.signature,undefined);assert.equal(polls,1);
});


test('periodic explicit retry discovering held never posts and clears stale cards',async()=>{
 const calls=[],status=el(),retry=el(),list=el(),order=el(),root=el();let callback;
 retry.addEventListener=(name,fn)=>{callback=fn;};root.dataset={periodicSuggestions:'/synthetic',canGenerate:'true'};
 root.querySelector=s=>({'[data-proposal-status]':status,'[data-proposal-retry]':retry,'[data-proposal-list]':list,'[data-proposal-order]':order}[s]);
 const responses=[{status:'error',error:'generation_failed'},held];
 vm.runInNewContext(read('vehicle_periodic_suggestions.js'),{document:{querySelector:s=>s==='[data-periodic-suggestions]'?root:null},window:{addEventListener(){}},Date,setTimeout(){throw Error('unexpected generation poll');},clearTimeout(){},fetch:async(url,opt)=>{calls.push(opt.method||'GET');return{ok:true,json:async()=>responses.shift()};}});
 await settle();assert.equal(retry.hidden,false);list.children=['previous-high'];callback();await settle();
 assert.deepEqual(calls,['GET','GET']);assert.equal(status.textContent,message);assert.equal(retry.hidden,true);assert.equal(list.children.length,0);assert.equal(order.style.display,'none');
});

test('periodic POST race consumes held409 JSON and removes prior cards without generic failure',async()=>{
 const calls=[],status=el(),retry=el(),list=el(),order=el(),root=el();list.children=['previous-high'];
 root.dataset={periodicSuggestions:'/synthetic',canGenerate:'true'};
 root.querySelector=s=>({'[data-proposal-status]':status,'[data-proposal-retry]':retry,'[data-proposal-list]':list,'[data-proposal-order]':order}[s]);
 vm.runInNewContext(read('vehicle_periodic_suggestions.js'),{document:{querySelector:s=>s==='[data-periodic-suggestions]'?root:{content:'synthetic'}},window:{addEventListener(){}},Date,setTimeout(){throw Error('unexpected generation poll');},clearTimeout(){},fetch:async(url,opt)=>{calls.push(opt.method||'GET');return{ok:opt.method!=='POST',status:opt.method==='POST'?409:200,json:async()=>opt.method==='POST'?held:{status:'missing'}};}});
 await settle();assert.deepEqual(calls,['GET','POST']);assert.equal(status.textContent,message);assert.equal(retry.hidden,true);assert.equal(list.children.length,0);assert.equal(order.style.display,'none');
});
