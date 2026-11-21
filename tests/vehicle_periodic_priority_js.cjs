const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const view = require('../static/js/vehicle_priority_presentation.js');
const source = fs.readFileSync(require.resolve('../static/js/vehicle_periodic_suggestions.js'), 'utf8');
function el(tag='div') {
    return {tag, children:[], dataset:{}, attributes:{}, style:{}, hidden:false, textContent:'',
        append(...values){this.children.push(...values);}, replaceChildren(...values){this.children=values;},
        setAttribute(key,value){this.attributes[key]=value;}, addEventListener(){}};
}
const walk = e => [e, ...e.children.flatMap(walk)];
const texts = e => walk(e).map(v => v.textContent).join('\n');
function item(id, priority, score=null) {
    const value = {proposal_id:id, proposal_revision:'revision', priority, title:`${id} の提案`, target:'制動装置',
        action:'確認する', source_ids:['inspection:1'], confirmation_steps:['元記録を照合']};
    if (score !== null) value.priority_assessment = {version:view.VERSION, candidate_id:id, proposal_revision:'revision',
        method:'maintenance-response-priority-trial-v0.1',policy_version:'trial-20261110', policy_status:'trial',
        operation_decision:'human_only', safety_cleared:false, calculation_status:'computed', label:priority,
        base_score:score, effective_score:score, floor_adjustment:0,
        factors:['impact','timing','state'].map((axis,n)=>({axis,points:[40,null,10][n],source_ids:['inspection:1'],rule_ids:[],reference_ids:[]})),
        applied_floors:[],missing_conditions:['時期の根拠を確認'],applicable_reference_ids:[],evidence_status:'一部確認要',
        as_of:'2026-11-11',observed_at:'2026-11-11'};
    return value;
}
async function render(result, options={}) {
    const status=el(),list=el(),retry=el(),order=el(),root=el(),calls=[];
    const entries={'[data-proposal-status]':status,'[data-proposal-list]':list,'[data-proposal-retry]':retry,'[data-proposal-order]':order};
    root.dataset={periodicSuggestions:'/vehicle/karte/1/periodic/1/suggestions',canGenerate:'true'};
    root.querySelector=s=>entries[s];
    const doc={createElement:el,createTextNode:text=>({...el('#text'),textContent:text}),querySelector:s=>s==='[data-periodic-suggestions]'?root:null};
    const data={status:options.status||'completed',is_current:options.is_current,result,evidence:options.evidence||{'inspection:1':{url:'/vehicle/checklist-results/1',label:'元の点検'}},updated_at:'2026-11-11T12:00:00+09:00'};
    const window={VehiclePriorityPresentation:options.noHelper?undefined:view,location:{origin:'https://app.example.test'},addEventListener(){}};
    const timers = new Map();
    let nextTimer = 0;
    vm.runInNewContext(source,{document:doc,window,Date,URL,AbortController,
        setTimeout(fn,delay){const id=++nextTimer;timers.set(id,{fn,delay});return id;},
        clearTimeout(id){timers.delete(id);},
        fetch:async(url,init)=>{calls.push({url,init});return{ok:true,json:async()=>data};}});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(timers.size,0);
    return{status,list,retry,order,calls};
}
test('periodic view uses shared score, literal legacy and exact server order with counts',async()=>{
    const result={recommendations:[item('computed','中',50),item('saved','高'),item('broken','unknown')],
        priority_order_format:'source_indices_v1',priority_order_indices:[1,0,2],
        priority_summary:{labels:{高:1,中:1,低:0},invalid_count:1,proposal_count:3}};
    const before=JSON.stringify(result), ui=await render(result);
    assert.equal(ui.list.children.length,3);assert.match(texts(ui.list.children[0]),/1\. saved/);
    assert.match(texts(ui.list.children[1]),/中 · 50点/);assert.match(texts(ui.list.children[0]),/保存版/);
    assert.equal(walk(ui.list.children[2]).filter(e=>e.dataset.priority).length,0);
    assert.match(texts(ui.status),/高1件・中1件・低0件.*保存データ確認1件/);
    assert.match(texts(ui.status),/前回評価を含む/);
    assert.match(texts(ui.list),/根拠を確認要（0点の判定ではありません）/);
    assert.match(texts(ui.list),/故障確率や運行可否ではありません/);
    assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].init.method,undefined);
    assert.equal(JSON.stringify(result),before);
});
test('periodic details show original source safely and never parse proposal HTML',async()=>{
    const value=item('safe','中',50);value.title='<img src=x onerror=alert(1)>';
    const ui=await render({recommendations:[value]},{evidence:{'inspection:1':{url:'javascript:alert(1)',label:'悪いリンク'}}});
    assert.match(texts(ui.list),/<img src=x/);
    assert.equal(walk(ui.list).some(e=>['img','script'].includes(e.tag)),false);
    assert.equal(walk(ui.list).filter(e=>e.tag==='a').length,0);
    const good=await render({recommendations:[value]});
    assert.ok(walk(good.list).some(e=>e.href==='https://app.example.test/vehicle/checklist-results/1'));
});
test('missing shared helper never silently guesses low',async()=>{
    const ui=await render({recommendations:[item('saved','高')]},{noHelper:true});
    assert.equal(ui.list.children.length,1);assert.match(texts(ui.list),/元データを確認/);
    assert.equal(walk(ui.list).some(e=>e.dataset.priority),false);
    assert.doesNotMatch(texts(ui.list),/低/);
});
test('invalid summary is ignored rather than computing a client-side count',async()=>{
    const ui=await render({recommendations:[item('saved','高')],priority_summary:{labels:{高:0,中:0,低:1},invalid_count:1,proposal_count:1}});
    assert.doesNotMatch(texts(ui.status),/低1件/);
});


test('failed update keeps the previous cards and separates retry status from saved assessment',async()=>{
    const value=item('previous','高');
    const ui=await render({recommendations:[value]},{status:'error',is_current:false});
    assert.equal(ui.list.children.length,1);assert.match(texts(ui.list),/previous/);assert.match(texts(ui.list),/保存版/);
    assert.match(texts(ui.status),/更新できません/);assert.match(texts(ui.status),/前回の提案を保存版/);
    assert.doesNotMatch(texts(ui.status),/追加提案なし/);assert.equal(ui.retry.hidden,false);
    assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].init.method,undefined);
});

async function pollingFixture({canGenerate = true, respond, reply}) {
    const status=el(),list=el(),retry=el(),order=el(),root=el(),calls=[],timers=new Map();
    const entries={'[data-proposal-status]':status,'[data-proposal-list]':list,'[data-proposal-retry]':retry,'[data-proposal-order]':order};
    root.dataset={periodicSuggestions:'/vehicle/karte/1/periodic/1/suggestions',canGenerate:String(canGenerate)};
    root.querySelector=s=>entries[s];
    const doc={createElement:el,createTextNode:text=>({...el('#text'),textContent:text}),querySelector:s=>s==='[data-periodic-suggestions]'?root:null};
    const events = {};
    const window={VehiclePriorityPresentation:view,location:{origin:'https://app.example.test'},addEventListener(name,fn){events[name]=fn;}};
    let time=1_000, nextTimer=0, clickRetry;
    const requests=[];
    retry.addEventListener=(name,fn)=>{if(name==='click')clickRetry=fn;};
    const settled=()=>new Promise(resolve=>setImmediate(resolve));
    vm.runInNewContext(source,{document:doc,window,Date:{now:()=>time,parse:Date.parse},URL,AbortController,
        setTimeout(fn,delay){const id=++nextTimer;timers.set(id,{fn,delay,due:time+delay});return id;},
        clearTimeout(id){timers.delete(id);},
        fetch:async(url,init)=>{
            const method=init.method||'GET';calls.push(method);requests.push(init);
            return reply ? reply(method,requests.length) : {ok:true,json:async()=>respond(method)};
        }});
    await settled();
    return {status,list,retry,calls,requests,timers,events,settled,
        nextDelay(){return Math.min(...[...timers.values()].map(t=>t.delay));},
        async timer(elapsed){
            time=1_000+elapsed;
            const due=[...timers].filter(([,t])=>t.due<=time).sort((a,b)=>a[1].due-b[1].due);
            for (const [id,value] of due) if (timers.delete(id)) value.fn();
            await settled();
        },
        async retryNow(){clickRetry?.();await settled();}
    };
}

test('periodic missing status follows the same 15-minute deadline as running',async()=>{
    const previous={recommendations:[item('previous','高')]};
    let recovered=false;
    const ui=await pollingFixture({respond:()=>recovered
        ? {status:'completed',is_current:true,result:previous}
        : {status:'missing',is_current:false,result:previous}});
    assert.deepEqual(ui.calls,['GET','POST']);
    assert.equal(ui.nextDelay(),2_000);
    await ui.timer(899_000);
    assert.deepEqual(ui.calls,['GET','POST','GET','POST']);
    await ui.timer(900_000);
    assert.deepEqual(ui.calls,['GET','POST','GET','POST']);
    assert.equal(ui.timers.size,0);
    assert.equal(ui.list.children.length,1);
    assert.match(texts(ui.list),/previous/);
    assert.equal(ui.retry.hidden,false);
    assert.match(texts(ui.status),/前回の提案/);
    recovered=true;
    await ui.retryNow();
    assert.deepEqual(ui.calls,['GET','POST','GET','POST','GET']);
    assert.equal(ui.retry.hidden,true);
    assert.match(texts(ui.status),/AI提案 1件/);
});

test('periodic viewer polls running status without starting generation and stops at deadline',async()=>{
    const ui=await pollingFixture({canGenerate:false,respond:()=>({status:'running'})});
    assert.deepEqual(ui.calls,['GET']);
    assert.equal(ui.nextDelay(),2_000);
    await ui.timer(900_000);
    assert.deepEqual(ui.calls,['GET']);
    assert.equal(ui.timers.size,0);
    assert.match(texts(ui.status),/時間をおいて/);
});

const deferred = () => {
    let resolve, reject;
    const promise = new Promise((ok, err) => { resolve=ok; reject=err; });
    return {promise,resolve,reject};
};
const response = data => ({ok:true,json:async()=>data});
const proposal = id => ({status:'completed',is_current:true,result:{recommendations:[item(id,'高')]}});
const runningWithSaved = () => ({...proposal('previous'),status:'running',is_current:false});

test('periodic deadline aborts delayed GET headers and keeps saved cards and authorized retry',async()=>{
    const pending = deferred();
    const ui=await pollingFixture({reply:(_, n)=>n===1 ? response(runningWithSaved()) : pending.promise});
    await ui.timer(899_000);
    assert.deepEqual(ui.calls,['GET','GET']);
    assert.match(texts(ui.status),/照合しています/);
    assert.equal(ui.retry.hidden,true);
    await ui.timer(900_000);
    assert.equal(ui.requests[1].signal.aborted,true);
    assert.equal(ui.retry.hidden,false);
    assert.equal(ui.timers.size,0);
    assert.match(texts(ui.status),/時間をおいて.*前回の提案/);
    assert.match(texts(ui.list),/previous/);
    pending.resolve(response({status:'missing'}));
    await ui.settled();
    assert.deepEqual(ui.calls,['GET','GET']); // no delayed POST
    assert.match(texts(ui.status),/時間をおいて/);
});

test('periodic deadline covers a delayed GET body and old data cannot replace a new attempt',async()=>{
    const pending = deferred();
    const ui=await pollingFixture({reply:(_, n)=>n===1 ? response(runningWithSaved())
        : n===2 ? {ok:true,json:()=>pending.promise} : response(proposal('fresh'))});
    await ui.timer(899_000);
    await ui.timer(900_000);
    await ui.retryNow();
    assert.deepEqual(ui.calls,['GET','GET','GET']); // server already finished
    assert.match(texts(ui.list),/fresh/);
    pending.resolve(proposal('late'));
    await ui.settled();
    assert.match(texts(ui.list),/fresh/);
    assert.doesNotMatch(texts(ui.list),/late/);
    assert.equal(ui.retry.hidden,true);
    assert.equal(ui.timers.size,0);
});

test('periodic deadline covers delayed POST and retry adopts an active server run',async()=>{
    const pending = deferred();
    const ui=await pollingFixture({reply:(method,n)=>n===1 ? response({...runningWithSaved(),status:'missing'})
        : method==='POST' ? {ok:true,json:()=>pending.promise}
        : response({status:'running',updated_at:new Date(900_000).toISOString()})});
    assert.deepEqual(ui.calls,['GET','POST']);
    await ui.timer(900_000);
    assert.equal(ui.requests[1].signal.aborted,true);
    assert.match(texts(ui.status),/時間をおいて.*前回の提案/);
    await ui.retryNow();
    assert.deepEqual(ui.calls,['GET','POST','GET']); // aborting the client did not cancel server work
    assert.match(texts(ui.status),/照合しています.*前回の提案/);
    pending.reject(new Error('late network failure'));
    await ui.settled();
    assert.match(texts(ui.status),/照合しています/);
    assert.equal(ui.retry.hidden,true);
    assert.equal(ui.timers.size,2);
});

test('periodic manual retry can restart an expired server run after rechecking it',async()=>{
    let fetched=0;
    const ui=await pollingFixture({respond:()=>++fetched===3
        ? proposal('fresh') : {status:'running',updated_at:new Date(0).toISOString()}});
    assert.deepEqual(ui.calls,['GET']);
    await ui.timer(900_000);
    await ui.retryNow();
    assert.deepEqual(ui.calls,['GET','GET','POST']);
    assert.deepEqual(JSON.parse(ui.requests[2].body),{retry:true});
    assert.match(texts(ui.list),/fresh/);
});
