const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');

function screen({status='pending',autoRefresh=false,initialResponses=[]}={}){
 const timers=new Map(),events={},calls=[],responses=[...initialResponses];let next=0,reloads=0,ready,submit;
 const button={disabled:status==='pending',textContent:status==='pending'?'作成中':'作成する'};
 const message={hidden:status!=='pending',textContent:''};
 const form={action:'/safety/driving-reports/reflection',querySelector:()=>button,
  addEventListener(type,fn){if(type==='submit')submit=fn;},requestSubmit(){return submit({preventDefault(){}});}};
 const root={scrollTop:80,scrollHeight:1500,clientHeight:900,parentElement:null};
 const reflection={id:'driving-reflection',parentElement:root,getBoundingClientRect:()=>({top:100}),
  dataset:{endpoint:'/safety/driving-reports/reflection?period=all',key:'current',status,autoRefresh:String(autoRefresh)},
  querySelector:s=>s==='[data-reflection-form]'?form:s==='[data-reflection-status]'?message:null};
 const workspace={dataset:{positionOwner:'fixture'},querySelector:()=>null,querySelectorAll:()=>[],addEventListener(){}};
 const document={hidden:false,referrer:'',scrollingElement:root,getElementById:()=>null,querySelectorAll:()=>[],
  querySelector:s=>s==='[data-reflection]'?reflection:s==='.driving-page'?workspace:null,
  addEventListener(type,fn){if(type==='DOMContentLoaded')ready=fn;}};
 const location=new URL('http://localhost/safety/driving-reports?period=all');location.reload=()=>reloads++;
 vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/driving_reports.js'),'utf8'),{
  document,window:{addEventListener(type,fn){(events[type]??=[]).push(fn);}},location,URL,Date,
  FormData:class{},getComputedStyle:()=>({overflowY:'auto'}),
  sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},
  setTimeout(fn){timers.set(++next,fn);return next;},clearTimeout(id){timers.delete(id);},
  fetch:async(url,options={})=>{calls.push({url,method:options.method||'GET'});const value=responses.shift();if(value instanceof Error)throw value;assert.ok(value,'Unexpected extra request');return value;},
 });
 ready();
 return {button,message,timers,calls,document,get reloads(){return reloads;},
  respond(state,http=200,redirected=false){responses.push({ok:http>=200&&http<300,status:http,redirected,json:async()=>state});},
  error(){responses.push(new Error('offline'));},submit:()=>form.requestSubmit(),
  event(type,persisted=true){for(const fn of events[type]||[])fn({persisted});},
  async tick(){const [id,fn]=timers.entries().next().value||[];assert.ok(fn,'No scheduled poll');timers.delete(id);await fn();}};
}

test('a record update recovers by reloading instead of resending a stale input key',async()=>{
 const s=screen({status:'new'});s.respond({},409);await s.submit();
 assert.equal(s.button.disabled,false);assert.equal(s.button.textContent,'再表示');
 await s.submit();assert.equal(s.reloads,1);assert.equal(s.calls.length,1);
});

test('a changed polling key becomes visible and offers reload without another generation',async()=>{
 const s=screen();s.respond({key:'changed',status:'pending'});await s.tick();
 assert.equal(s.message.hidden,false);assert.equal(s.button.disabled,false);
 assert.equal(s.button.textContent,'再表示');assert.equal(s.timers.size,0);
 await s.submit();assert.equal(s.reloads,1);assert.equal(s.calls.length,1);
});

test('a restored pending page resumes one GET poll and never POSTs automatically',async()=>{
 const s=screen();s.event('pagehide');assert.equal(s.timers.size,0);
 s.event('pageshow');s.event('pageshow');assert.equal(s.timers.size,1);
 s.respond({key:'current',status:'pending'});await s.tick();
 assert.deepEqual(s.calls.map(c=>c.method),['GET']);assert.equal(s.timers.size,1);
});

test('a generation started on this page also resumes after returning',async()=>{
 const s=screen({status:'new'});s.respond({key:'current',status:'pending'},202);await s.submit();
 s.event('pagehide');s.event('pageshow');assert.equal(s.timers.size,1);
 s.respond({key:'current',status:'completed'});await s.tick();
 assert.equal(s.reloads,1);assert.deepEqual(s.calls.map(c=>c.method),['POST','GET']);
});

test('removed or unavailable records do not remain in an endless generation state',async()=>{
 for(const status of ['empty','unavailable','new']){
  const s=screen();s.respond({key:'current',status});await s.tick();
  assert.equal(s.timers.size,0);assert.equal(s.button.disabled,false);assert.equal(s.button.textContent,'再表示');
 }
});

test('a generation failure remains retryable and a restored failed page stays idle',async()=>{
 const s=screen();s.respond({key:'current',status:'failed'});await s.tick();
 assert.equal(s.button.textContent,'再試行');s.event('pagehide');s.event('pageshow');assert.equal(s.timers.size,0);
 s.respond({key:'current',status:'pending'},202);await s.submit();assert.equal(s.timers.size,1);
});

test('repeated submits while generation is starting do not create extra POSTs',async()=>{
 const s=screen({status:'new'});s.respond({key:'current',status:'pending'},202);
 const first=s.submit();await s.submit();await first;assert.equal(s.calls.length,1);
});

test('an ordinary new page and non-restoration pageshow do not start paid generation',()=>{
 const s=screen({status:'new'});s.event('pageshow',false);assert.equal(s.calls.length,0);assert.equal(s.timers.size,0);
});

test('network and temporary service errors offer a usable retry without leaking technical text',async()=>{
 const network=screen();network.error();await network.tick();
 assert.equal(network.button.disabled,false);assert.equal(network.button.textContent,'再試行');
 assert.match(network.message.textContent,/接続を確認/);assert.doesNotMatch(network.message.textContent,/offline/);
 for(const http of [429,503]){
  const s=screen({status:'new'});s.respond({},http);await s.submit();
  assert.equal(s.button.disabled,false);assert.equal(s.button.textContent,'再試行');
 }
});

test('the server-authorized existing auto-refresh still submits once and only polls on restoration',async()=>{
 const s=screen({status:'new',autoRefresh:true,initialResponses:[{
  ok:true,status:202,json:async()=>({key:'current',status:'pending'})}]});
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(s.calls.map(c=>c.method),['POST']);assert.equal(s.timers.size,1);
 s.event('pagehide');s.event('pageshow');s.respond({key:'current',status:'pending'});await s.tick();
 assert.deepEqual(s.calls.map(c=>c.method),['POST','GET']);
});

test('login redirects and permission failures offer reload rather than repeating a rejected request',async()=>{
 for(const [status,redirected] of [[200,true],[401,false],[403,false]]){
  const s=screen({status:'new'});s.respond({},status,redirected);await s.submit();
  assert.equal(s.button.textContent,'再表示');assert.equal(s.button.disabled,false);
  await s.submit();assert.equal(s.reloads,1);assert.equal(s.calls.length,1);
 }
 const pending=screen();pending.respond({},200,true);await pending.tick();
 assert.equal(pending.button.textContent,'再表示');assert.equal(pending.timers.size,0);
});
