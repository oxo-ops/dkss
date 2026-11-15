const {test}=require('node:test');
const assert=require('node:assert/strict');
require('../static/js/shared_push_recovery_candidate.js');
const {run}=globalThis.DKSSSharedPushRecovery;
function fixture({status=[409,200],sameEndpoint=false}={}) {
 const calls=[], counters={post:0,subscribe:0,unsubscribe:0,context:0};
 let current;
 function sub(endpoint) { return {endpoint,toJSON(){return {endpoint,keys:{auth:'fake',p256dh:'fake'}}},async unsubscribe(){counters.unsubscribe++; current=null;return true}}; }
 current=sub('https://push.example.invalid/old');
 const f={calls,counters,actor:'A',context:'session-A',permission:'granted'};
 let tail=Promise.resolve();
 const manager={async getSubscription(){return current},async subscribe(){counters.subscribe++;current=sub(sameEndpoint?'https://push.example.invalid/old':'https://push.example.invalid/new');return current}};
 const env={permission:'granted',expectedActor:'A',csrf:'csrf-test',keyBytes:async x=>x,navigator:{
   locks:{request(name,cb){calls.push(name);const p=tail.then(cb);tail=p.catch(()=>{});return p}},
   serviceWorker:{async register(){return {pushManager:manager}}}},
   async fetch(url,options){calls.push(url);if(url.endsWith('vapid-public-key')){counters.context++;if(f.beforeContext)f.beforeContext();return {ok:true,json:async()=>({publicKey:'fake',sharedContext:f.context,sharedActor:f.actor})}};
     counters.post++;const code=status.shift()??200;f.lastBody=JSON.parse(options.body);if(f.afterPost)f.afterPost();return {ok:code===200,status:code};}};
 return Object.assign(f,{env,manager,setCurrent:v=>current=v});
}
test('one recovery rotates browser endpoint and keeps expected session',async()=>{
 const f=fixture();assert.equal((await run(f.env)).state,'recovered');assert.equal(f.counters.post,2);assert.equal(f.counters.unsubscribe,1);assert.equal(f.lastBody.sharedContext,'session-A');assert(!f.calls.includes('/api/push/unsubscribe'));
});
test('normal subscription retained without churn',async()=>{
 const f=fixture({status:[200]});assert.equal((await run(f.env)).state,'registered');assert.equal(f.counters.unsubscribe,0);assert.equal(f.counters.subscribe,0);
});
test('fresh subscription registers once',async()=>{
 const f=fixture({status:[200]});f.setCurrent(null);await run(f.env);assert.equal(f.counters.subscribe,1);assert.equal(f.counters.post,1);
});
test('no permission request for ungranted permission',async()=>{
 const f=fixture();f.env.permission='default';assert.equal((await run(f.env)).state,'permission-required');assert.equal(f.calls.length,0);
});
test('unsupported cross-tab lock fails before browser mutation',async()=>{
 const f=fixture();delete f.env.navigator.locks;await assert.rejects(run(f.env));assert.equal(f.counters.unsubscribe,0);assert.equal(f.counters.post,0);
});
test('stale person page cannot register as next user',async()=>{
 const f=fixture();f.actor='B';await assert.rejects(run(f.env));assert.equal(f.counters.post,0);assert.equal(f.counters.unsubscribe,0);
});
test('session switch after conflict stops before unsubscribe',async()=>{
 const f=fixture();f.afterPost=()=>f.context='session-B';await assert.rejects(run(f.env));assert.equal(f.counters.unsubscribe,0);assert.equal(f.counters.subscribe,0);
});
test('session switch after local unsubscribe stops resubscribe',async()=>{
 const f=fixture();f.beforeContext=()=>{if(f.counters.unsubscribe)f.context='session-B'};await assert.rejects(run(f.env));assert.equal(f.counters.unsubscribe,1);assert.equal(f.counters.subscribe,0);
});
test('409 retry is bounded',async()=>{
 const f=fixture({status:[409,409]});await assert.rejects(run(f.env));assert.equal(f.counters.post,2);assert.equal(f.counters.unsubscribe,1);
});
test('500 or 401 does not delete subscription',async()=>{
 for(const code of [401,403,500]){const f=fixture({status:[code]});await assert.rejects(run(f.env));assert.equal(f.counters.unsubscribe,0)}
});
test('failed unsubscribe stops',async()=>{
 const f=fixture();(await f.manager.getSubscription()).unsubscribe=async()=>false;await assert.rejects(run(f.env));assert.equal(f.counters.subscribe,0);
});
test('same endpoint is never reassigned',async()=>{
 const f=fixture({sameEndpoint:true});await assert.rejects(run(f.env));assert.equal(f.counters.post,1);
});
test('two simultaneous pages serialize recovery instead of double unsubscribe',async()=>{
 const f=fixture();await Promise.all([run(f.env),run(f.env)]);assert.equal(f.counters.unsubscribe,1);assert.equal(f.counters.subscribe,1);assert.equal(f.counters.post,3);
});
