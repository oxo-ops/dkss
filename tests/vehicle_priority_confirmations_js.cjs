const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../static/js/vehicle_priority_confirmations.js'), 'utf8');
function el(tag='div') {
    return {tag,children:[],dataset:{},events:{},attributes:{},hidden:false,disabled:false,textContent:'',
        append(...values){this.children.push(...values);},replaceChildren(...values){this.children=values;},
        addEventListener(name,callback){this.events[name]=callback;},setAttribute(k,v){this.attributes[k]=v;},scrollIntoView(){},focus(){}};
}
const walk=e=>[e,...e.children.flatMap(walk)];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function setup(history=[]) {
    const root=el(), entries={}, calls=[];
    for(const name of ['message','kind','selection','preview','controls','fields','originals','missing','replacing','history','subject','sources','statements'])
        entries[`[data-confirmation-${name}]`]=el(['selection','preview'].includes(name)?'form':name==='kind'?'select':'div');
    const kind=entries['[data-confirmation-kind]'],form=entries['[data-confirmation-selection]'],preview=entries['[data-confirmation-preview]'];
    kind.value='progression';form.values=[['current_observation','record-ref']];preview.values=[['statement','verified']];
    root.dataset={priorityConfirmations:'/vehicle/karte/1/priority-confirmations',previewUrl:'/vehicle/karte/1/priority-confirmations/preview',saveUrl:'/vehicle/karte/1/priority-confirmations'};
    root.children=Object.values(entries);root.querySelector=s=>entries[s]||el('summary');
    root.querySelectorAll=()=>walk(root).filter(e=>['button','select','input'].includes(e.tag));
    const data={ok:true,message:'原記録を確認',can_confirm:true,kinds:{manufacturer_immediate:'メーカー'},history,
        form:{fields:[{key:'current_observation',label:'元観測',options:[{value:'record-ref',label:'元記録'}]}],missing_conditions:[]}};
    let nextResponse;
    const window={confirm:()=>true},document={createElement:el,querySelector:s=>s==='[data-priority-confirmations]'?root:{content:'csrf-token'}};
    class FormData {constructor(form){this.values=form.values.filter(()=>!walk(form).some(e=>e.disabled));}entries(){return this.values;}getAll(key){return this.values.filter(([k])=>k===key).map(([,v])=>v);}}
    vm.runInNewContext(source,{window,document,location:{origin:'https://app.example.test',hash:''},URL,URLSearchParams,FormData,
        fetch:async(url,init)=>{calls.push({url,init});if(nextResponse){const pending=nextResponse;nextResponse=null;return pending;}return{ok:true,json:async()=>data};}});
    return{root,entries,kind,form,preview,calls,setPending(p){nextResponse=p;}};
}
test('manufacturer correction options GET contains identifiers, never long original quotes',async()=>{
    const quote='原文'.repeat(2000),ui=setup([{event_id:42,kind:'manufacturer_immediate',subject:'原観測',status:'active',
        actor:{name:'担当者'},confirmed_at:'2026-11-11T12:00:00+09:00',cancel_token:'signed',selection:{
            knowledge_source_id:'knowledge:1',rule_key:'rule',observation_input_ref:'observation',condition_quote:quote,action_quote:quote}}]);
    ui.root.open=true;ui.root.events.toggle();await flush();
    const correct=walk(ui.entries['[data-confirmation-history]']).find(e=>e.tag==='button'&&e.textContent.includes('訂正'));
    correct.events.click();await flush();
    const url=new URL(ui.calls.at(-1).url,'https://app.example.test'),selected=JSON.parse(url.searchParams.get('selection'));
    assert.deepEqual(Object.keys(selected).sort(),['manufacturer_rule','observation_input_ref']);
    assert.equal(selected.observation_input_ref,'observation');assert.ok(url.href.length<500);
    assert.ok(!url.href.includes(encodeURIComponent('原文')));
});
test('preview and save preserve form values before locking edits and reject a second click',async()=>{
    const ui=setup();ui.root.open=true;ui.root.events.toggle();await flush();
    let finish;ui.setPending(new Promise(resolve=>finish=resolve));
    const event={preventDefault(){}};
    const pending=ui.form.events.submit(event);
    assert.equal(ui.kind.disabled,true);assert.equal(ui.root.attributes['aria-busy'],'true');
    const payload=JSON.parse(ui.calls.at(-1).init.body);assert.equal(payload.selection.current_observation,'record-ref');
    const count=ui.calls.length;await ui.form.events.submit(event);assert.equal(ui.calls.length,count);
    finish({ok:true,json:async()=>({ok:true,token:'signed-token',message:'確認内容',preview:{subject:'元対象',display_sources:[],statements:[{key:'verified',label:'元記録を確認'}]}})});
    await pending;assert.equal(ui.kind.disabled,false);assert.equal(ui.preview.hidden,false);
    let saveFinish;ui.setPending(new Promise(resolve=>saveFinish=resolve));
    const saving=ui.preview.events.submit(event);
    assert.equal(ui.kind.disabled,true);assert.deepEqual(JSON.parse(ui.calls.at(-1).init.body).statements,['verified']);
    const savedCount=ui.calls.length;await ui.preview.events.submit(event);assert.equal(ui.calls.length,savedCount);
    saveFinish({ok:true,json:async()=>({ok:true,message:'登録済み'})});await saving;
    assert.equal(ui.kind.disabled,false);assert.equal(ui.root.attributes['aria-busy'],'false');
});
