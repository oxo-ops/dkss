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
    vm.runInNewContext(source,{document:doc,window,Date,URL,setTimeout(){throw Error('No polling on complete');},clearTimeout(){},
        fetch:async(url,init)=>{calls.push({url,init});return{ok:true,json:async()=>data};}});
    await new Promise(resolve=>setImmediate(resolve));
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
