const test = require('node:test');
const assert = require('node:assert/strict');
const view = require('../static/js/vehicle_priority_presentation.js');
const fs = require('node:fs');
function proposal(id='one', points=[40,null,10], floor=false) {
    const base = points.reduce((n,p)=>n+(p??0),0), total=Math.max(base,floor?60:0), label=total>=60?'高':total>=25?'中':'低';
    return {proposal_id:id,proposal_revision:'rev1',priority:label,target:'制動の具体項目',feedback:{revision:'rev1',status:'accepted'},
        priority_assessment:{version:view.VERSION,candidate_id:id,proposal_revision:'rev1',method:'maintenance-response-priority-trial-v0.1',
            policy_version:'trial-20261110',policy_status:'trial',operation_decision:'human_only',safety_cleared:false,
            calculation_status:'computed',label,base_score:base,effective_score:total,floor_adjustment:total-base,
            factors:['impact','timing','state'].map((axis,i)=>({axis,points:points[i],source_ids:['inspection:1'],rule_ids:[],reference_ids:[]})),
            applied_floors:floor?[{code:'operation_instruction_active',minimum:60,source_ids:['instruction:1'],reference_ids:[]}]:[],
            missing_conditions:points.includes(null)?['対応期限を確認してください。']:[],applicable_reference_ids:[],evidence_status:'一部確認要',
            as_of:'2026-11-11',observed_at:'2026-11-10'}};
}
function el(tag='div') {return {tag,children:[],dataset:{},attributes:{},textContent:'',append(...v){this.children.push(...v);},setAttribute(k,v){this.attributes[k]=v;}};}
const doc={createElement:el}, walk=e=>[e,...e.children.flatMap(walk)], texts=e=>walk(e).map(e=>e.textContent).join('\n');
test('server score and null axis remain distinct from safety clearance',()=>{
    const item=proposal(), before=JSON.stringify(item), p=view.read(item);
    assert.equal(p.label,'中');assert.equal(p.score,50);assert.equal(p.note,'要確認');
    assert.equal(view.badge(doc,item).textContent,'中 · 50点');
    const detail=view.details(doc,item);assert.match(texts(detail),/0点の判定ではありません/);assert.doesNotMatch(texts(detail),/未評価/);
    assert.match(texts(detail),/運行可否・既存指示の解除は責任者/);assert.equal(JSON.stringify(item),before);
});
test('existing human instruction floor is shown without issuing an operation decision',()=>{
    const item=proposal('stop',[null,null,10],true), detail=view.details(doc,item);
    assert.equal(view.read(item).score,60);assert.match(texts(detail),/既存の運行前確認・停止等の指示：下限60点/);
    assert.doesNotMatch(texts(detail),/自動.*運行禁止/);
});
test('legacy label stays literal with no score or fourth class',()=>{
    for(const label of ['高','中','低']) {
        const item=proposal();item.priority=label;Object.assign(item.priority_assessment,{calculation_status:'legacy_preserved',label,base_score:null,effective_score:null,floor_adjustment:null,applied_floors:[]});
        item.priority_assessment.factors.forEach(f=>f.points=null);
        assert.equal(view.read(item).label,label);assert.equal(view.read(item).score,null);assert.match(view.read(item).note,/保存版/);
        assert.equal(view.badge(doc,item).textContent,label);assert.doesNotMatch(texts(view.details(doc,item)),/基本点|未評価/);
    }
    assert.equal(view.badge(doc,{priority:'unexpected'}),null);
});
test('malformed score, mismatched identity and unsafe contracts never become badges',()=>{
    const mutations=[i=>i.priority_assessment.candidate_id='other',i=>i.priority_assessment.proposal_revision='old',
        i=>i.priority_assessment.version='unknown',i=>i.priority_assessment.effective_score=0,
        i=>i.priority_assessment.factors[0].points='40',i=>i.priority_assessment.base_score=NaN,
        i=>i.priority_assessment.label='未評価',i=>i.priority_assessment.operation_decision='safe',
        i=>i.priority_assessment.factors[1].axis='impact',i=>i.priority_assessment.missing_conditions=[]];
    for(const mutate of mutations){const item=proposal();mutate(item);assert.equal(view.read(item).valid,false);assert.equal(view.badge(doc,item),null);}
});
test('server order is exact and does not alter source, feedback or ID',()=>{
    const items=[proposal('a'),proposal('b',[0,10,0])], before=JSON.stringify(items);
    assert.deepEqual(view.ordered(items,{priority_order:['b','a']}).map(i=>i.proposal_id),['b','a']);
    assert.deepEqual(view.ordered(items,{priority_order:['foreign','a']}).map(i=>i.proposal_id),['a','b']);
    assert.equal(JSON.stringify(items),before);
});
test('detail escapes evidence and only links same-origin verified source destinations',()=>{
    const item=proposal();item.priority_assessment.missing_conditions=['<img src=x onerror=alert(1)>'];
    const original=JSON.stringify(item), tree=view.details(doc,item,{'inspection:1':{label:'<script>source</script>',url:'/record/1'}},'https://dkss.test');
    assert.match(texts(tree),/<img/);assert.equal(walk(tree).some(e=>['img','script','form','input'].includes(e.tag)),false);
    assert.equal(walk(tree).find(e=>e.tag==='a').href,'https://dkss.test/record/1');
    const blocked=view.details(doc,item,{'inspection:1':{label:'x',url:'https://foreign.test/'}},'https://dkss.test');
    assert.equal(walk(blocked).some(e=>e.tag==='a'),false);assert.equal(JSON.stringify(item),original);
});
test('normal analysis no longer uses draft risk matrix for response label/order',()=>{
    const code=fs.readFileSync('static/js/vehicle_karte_analysis_ai.js','utf8');
    assert.doesNotMatch(code,/risk_assessment\?\.response_priority|riskResponseRank/);
    assert.match(code,/priorityPresentation\.ordered\(items, data\.analysis\)/);
    for(const file of ['templates/vehicle_karte.html','templates/vehicle_karte_analysis.html']){
        const template=fs.readFileSync(file,'utf8');assert.ok(template.indexOf('js/vehicle_priority_presentation.js') < template.indexOf(file.endsWith('_analysis.html')?'js/vehicle_karte_analysis_ai.js':'js/vehicle_karte_overview.js'));
    }
});
module.exports={proposal};

test('duplicate IDs and revisions retain every occurrence in server source-index order',()=>{
    const low=proposal('same',[0,10,0]), high=proposal('same',[40,35,10]);
    const items=[low,high,high], before=JSON.stringify(items);
    const result=view.ordered(items,{priority_order_format:'source_indices_v1',priority_order_indices:[1,2,0],priority_order:['same','same','same']});
    assert.equal(result[0],high);assert.equal(result[1],high);assert.equal(result[2],low);
    assert.equal(JSON.stringify(items),before);
    for(const order of [[1,1,0],[1,2],[1,2,3],[1,'2',0]]) {
        assert.deepEqual(view.ordered(items,{priority_order_format:'source_indices_v1',priority_order_indices:order}),items);
    }
});
