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
    assert.match(view.read(item).note,/責任者・整備担当者の判断を優先/);
    assert.match(texts(detail),/下限による調整：\+50点/);
});

test('recorded vehicle-wide instruction stays distinct from a component cause and a new decision',()=>{
    const item=proposal('stop',[null,null,null],true);
    item.priority_assessment.instruction_details={scope:'whole_vehicle',recorded_status:'運行不可',
        actor_name:'<img src=x onerror=alert(1)>',authority_role:'整備管理者',recorded_at:'2026-11-11T08:15:00+09:00',
        reason:'元の指示文',source_id:'instruction:1'};
    item.priority_assessment.subject_label='既存の運行判断の確認';
    const before=JSON.stringify(item), tree=view.details(doc,item), content=texts(tree);
    assert.equal(view.read(item).valid,true);
    assert.match(content,/元記録にある権限者の判断（車両全体）/);
    assert.match(content,/算定の対象：既存の運行判断の確認/);
    assert.match(content,/個別部品が原因という判定ではありません/);
    assert.match(content,/2026-11-11T08:15:00\+09:00/);
    assert.match(content,/元の指示文/);
    assert.equal(walk(tree).some(e=>['img','script','form','input'].includes(e.tag)),false);
    assert.equal(JSON.stringify(item),before);
});

test('low priority keeps a verified deadline without implying delay is safe',()=>{
    const item=proposal('plan',[0,10,0]);item.priority_assessment.earliest_due_on='2026-12-31';
    const content=texts(view.details(doc,item));
    assert.equal(view.read(item).label,'低');assert.match(content,/根拠のある対応期限：2026-12-31/);
    assert.match(content,/低も安全確認済みを意味しません/);
    for(const invalid of ['2026-02-31','2026-12','<script>bad</script>']){
        item.priority_assessment.earliest_due_on=invalid;assert.equal(view.read(item).valid,false);
    }
});

test('adopted timing shows the original rule and origin without calculating a new interval',()=>{
    const item=proposal('timing',[0,35,0]);
    item.priority_assessment.timing_origin_on='2026-01-31';
    item.priority_assessment.timing_reference={url:'https://example.test/manual.pdf',issuer:'合成メーカー',
        title:'点検基準',source_page:3,version:'source-checksum',quote:'<b>合成の点検条件</b>',authority:'manufacturer',action:'inspect'};
    const before=JSON.stringify(item), tree=view.details(doc,item), content=texts(tree);
    assert.equal(view.read(item).valid,true);assert.match(content,/適用した点検基準/);
    assert.match(content,/合成メーカー：点検基準（3ページ）/);assert.match(content,/起算記録：2026-01-31/);
    assert.equal(walk(tree).find(e=>e.tag==='a').href,'https://example.test/manual.pdf');
    assert.equal(walk(tree).find(e=>e.tag==='a').rel,'noopener noreferrer');
    assert.equal(walk(tree).some(e=>e.tag==='b'),false);assert.equal(JSON.stringify(item),before);
    for(const url of ['javascript:alert(1)','file:///etc/passwd','https://name:secret@example.test/manual.pdf']){
        item.priority_assessment.timing_reference.url=url;assert.equal(view.read(item).valid,false);
    }
});

test('malformed instruction attribution is not presented as a valid server assessment',()=>{
    const base={scope:'whole_vehicle',recorded_status:'運行不可',actor_name:'管理者',authority_role:'整備管理者',
        recorded_at:'2026-11-11T08:15:00+09:00',reason:'確認指示',source_id:'instruction:1'};
    for(const invalid of [{...base,scope:'brake'},{...base,actor_name:''},{...base,recorded_at:'2026-11-11 08:15:00'},
        {...base,recorded_at:'2026-02-31T08:15:00+09:00'},{...base,recorded_status:'運行可'},{...base,source_id:'instruction:foreign'}]){
        const item=proposal('stop',[null,null,null],true);item.priority_assessment.instruction_details=invalid;
        assert.equal(view.read(item).valid,false);assert.equal(view.badge(doc,item),null);
    }
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


test('confirmed original facts remain server facts with text-only same-origin links',()=>{
    const item=proposal();
    item.priority_assessment.confirmation_details={kind:'progression',event_id:42,confirmed_at:'2026-11-11T12:00:00+09:00',
        actor_name:'<script>actor</script>',statements:['同じ症状と位置を確認'],display_sources:[
            {label:'現在の観測',text:'<img src=x onerror=alert(1)>',url:'/vehicle/checklists/1'},
            {label:'外部URL',text:'原文',url:'https://foreign.test/vehicle/source'},
            {label:'不正URL',text:'原文',url:'javascript:alert(1)'}]};
    const before=JSON.stringify(item), tree=view.details(doc,item,{},'https://dkss.test');
    assert.equal(view.read(item).score,50);
    assert.match(texts(tree),/同じ症状と位置を確認/);assert.match(texts(tree),/<script>actor/);
    assert.equal(walk(tree).some(e=>['script','img','form','input'].includes(e.tag)),false);
    assert.deepEqual(walk(tree).filter(e=>e.tag==='a').map(e=>e.href),['https://dkss.test/vehicle/checklists/1']);
    assert.equal(JSON.stringify(item),before);
});
test('malformed confirmation metadata cannot present a computed priority',()=>{
    const valid={kind:'legal_deadline',event_id:42,confirmed_at:'2026-11-11T12:00:00+09:00',
        actor_name:'管理者',statements:['適用を確認'],display_sources:[{label:'原本',text:'原文'}]};
    for(const change of [{event_id:true},{kind:'score_input'},{confirmed_at:'2026-11-11'},
        {statements:[]},{display_sources:[{label:'原本',text:{html:'x'}}]}]){
        const item=proposal();item.priority_assessment.confirmation_details={...valid,...change};
        assert.equal(view.read(item).valid,false);
    }
});


test('legal confirmation opens only the fixed public legal reference outside the app',()=>{
    const item=proposal();item.priority_assessment.confirmation_details={kind:'legal_deadline',event_id:42,
        confirmed_at:'2026-11-11T12:00:00+09:00',actor_name:'管理者',statements:['原本と適用条件を確認'],display_sources:[
            {label:'公的根拠',text:'有効期間に関する原文',url:'https://www.mlit.go.jp/jidosha/content/001740686.pdf#page=121'},
            {label:'別URL',text:'別原文',url:'https://www.mlit.go.jp/other.pdf'},
            {label:'不正認証',text:'別原文',url:'https://user@www.mlit.go.jp/jidosha/content/001740686.pdf'}]};
    const tree=view.details(doc,item,{},'https://dkss.test');
    assert.deepEqual(walk(tree).filter(e=>e.tag==='a').map(e=>e.href),['https://www.mlit.go.jp/jidosha/content/001740686.pdf#page=121']);
});

test('merged confirmations show each original actor and source without blending them',()=>{
    const first={kind:'progression',event_id:42,confirmed_at:'2026-11-11T12:00:00+09:00',actor_name:'担当A',
        statements:['同症状再発を確認'],display_sources:[{label:'原観測A',text:'再発の原文',url:'/vehicle/checklists/1'}]};
    const second={kind:'manufacturer_immediate',event_id:43,confirmed_at:'2026-11-11T13:00:00+09:00',actor_name:'担当B',
        statements:['メーカー条件を確認'],display_sources:[{label:'原本B',text:'<img src=x>即時対応の原文',url:'/vehicle/knowledge/2'}]};
    const item=proposal();item.priority_assessment.confirmation_details=first;
    item.priority_assessment.confirmation_details_list=[first,second];
    const before=JSON.stringify(item),tree=view.details(doc,item,{},'https://dkss.test');
    assert.equal(view.read(item).valid,true);
    const sections=walk(tree).filter(e=>e.className==='priority-response-confirmation');
    assert.equal(sections.length,2);assert.match(texts(sections[0]),/担当A/);assert.doesNotMatch(texts(sections[0]),/担当B/);
    assert.match(texts(sections[1]),/担当B/);assert.match(texts(sections[1]),/<img src=x>/);
    assert.equal(walk(tree).some(e=>e.tag==='img'),false);assert.equal(JSON.stringify(item),before);
    for(const list of [[],[null],[first,first],Array.from({length:101},(_,i)=>({...first,event_id:i+1})),[first,{...second,actor_name:''}]]) {
        item.priority_assessment.confirmation_details_list=list;assert.equal(view.read(item).valid,false);
    }
});

test('carried previous evaluation separates saved label and dates from current scoring',()=>{
    const item=proposal(),a=item.priority_assessment;
    Object.assign(a,{calculation_status:'legacy_preserved',base_score:null,effective_score:null,floor_adjustment:null,
        applied_floors:[],factors:a.factors.map(f=>({...f,points:null})),previous_result:{
            version:'previous-confirmed-priority-result-v1',original_revision:'a'.repeat(64),label:item.priority,
            previous_generated_at:'2026/11/10 12:00',confirmed_at:['2026-11-10T11:00:00+09:00'],reason:'原本が改訂され、現在の条件を再計算できません。'}});
    assert.equal(view.read(item).score,null);
    a.historical_confirmation_details=[{kind:'manufacturer_immediate',event_id:42,confirmed_at:'2026-11-10T11:00:00+09:00',
        actor_name:'当時の確認者',statements:['当時の原文適用を確認'],display_sources:[{label:'保存した原文',text:'旧版の条件本文',url:'/vehicle/knowledge/1'}]}];
    const tree=view.details(doc,item,{},'https://dkss.test'),content=texts(tree);
    assert.match(content,/前回保存時の根拠確認（現在の成立を示すものではありません）/);
    assert.match(content,/当時の確認者/);assert.match(content,/旧版の条件本文/);
    assert.match(content,/前回の評価：中（現在の再計算値ではありません）/);
    assert.match(content,/前回分析：2026\/11\/10/);assert.match(content,/元の事実確認：2026-11-10T11:00/);
    assert.match(content,/原本が改訂/);assert.doesNotMatch(content,/基本点 0|未評価/);
    for(const change of [{label:'未評価'},{confirmed_at:['2026-11-10']},{original_revision:'invalid'},{reason:''}]) {
        const copy=JSON.parse(JSON.stringify(item));Object.assign(copy.priority_assessment.previous_result,change);
        assert.equal(view.read(copy).valid,false);
    }
});
