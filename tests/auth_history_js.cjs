const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync('static/js/auth-history.js','utf8');
function setup(authenticated,dirty=false,offline=false,selects=[]){
 const events={},classes=new Set(),attributes=new Map(),nodes=[];let navigations=0,requests=0;
 const make=()=>({setAttribute(){},append(){},focus(){},addEventListener(k,v){this[k]=v;}});
 const body={dataset:{authenticated},classList:{add:x=>classes.add(x)},setAttribute:(k,v)=>attributes.set(k,v),
 querySelectorAll:(selector)=>selector==='select'?selects:[...selects,...(dirty?[{type:'text',value:'unsaved',defaultValue:''}]:[])]};
 const env={document:{body,createElement:()=>{const n=make();nodes.push(n);return n;},documentElement:{appendChild(){}}},
 AbortController,fetch:async(_,opts)=>{requests++;assert.equal(opts.method,'HEAD');if(offline)throw Error();return {status:200};},
 window:{setTimeout,clearTimeout,addEventListener:(k,v)=>events[k]=v,location:{href:'https://example.invalid/record',replace:()=>navigations++}}};
 vm.runInNewContext(code,env);return {events,classes,attributes,nodes,navigations:()=>navigations,requests:()=>requests,setOnline:()=>offline=false};
}
(async()=>{
 assert.deepEqual(Object.keys(setup('false').events),[]);
 const normal=setup('true');normal.events.pageshow({persisted:false});assert.equal(normal.requests(),0);
 normal.events.pagehide();assert(normal.classes.has('auth-history-concealed'));assert(normal.attributes.has('inert'));
 normal.events.pageshow({persisted:true});await new Promise(r=>setImmediate(r));assert.equal(normal.navigations(),1);
 const dirty=setup('true',true);dirty.events.pageshow({persisted:true});assert.equal(dirty.requests(),0);await dirty.nodes[2].click();assert.equal(dirty.navigations(),1);
 const offline=setup('true',false,true);offline.events.pageshow({persisted:true});await new Promise(r=>setImmediate(r));
 assert.equal(offline.navigations(),0);assert.equal(offline.nodes[2].disabled,false);assert.match(offline.nodes[1].textContent,/再試行/);
 offline.setOnline();await offline.nodes[2].click();assert.equal(offline.navigations(),1);
 const makeSelect=(selected,multiple=false)=>({tagName:'SELECT',multiple,
  options:selected.map(value=>({selected:value,defaultSelected:false}))});
 const implicit=makeSelect([true,false]);
 const untouched=setup('true',false,false,[implicit]);untouched.events.pageshow({persisted:true});
 await new Promise(r=>setImmediate(r));assert.equal(untouched.navigations(),1,'Implicit first selection is clean');
 const changedSelect=makeSelect([true,false]);const changed=setup('true',false,false,[changedSelect]);
 changedSelect.options[0].selected=false;changedSelect.options[1].selected=true;
 changed.events.pageshow({persisted:true});assert.equal(changed.requests(),0,'User selection must require discard');
 const multi=makeSelect([true,true,false],true);const sameMulti=setup('true',false,false,[multi]);
 sameMulti.events.pageshow({persisted:true});await new Promise(r=>setImmediate(r));assert.equal(sameMulti.navigations(),1);
 const multiChanged=makeSelect([true,false],true);const editedMulti=setup('true',false,false,[multiChanged]);
 multiChanged.options[1].selected=true;editedMulti.events.pageshow({persisted:true});assert.equal(editedMulti.requests(),0);
 const resetSelect=makeSelect([true,false]);const reset=setup('true',false,false,[resetSelect]);
 resetSelect.options[0].selected=false;resetSelect.options[0].selected=true;
 reset.events.pageshow({persisted:true});await new Promise(r=>setImmediate(r));assert.equal(reset.navigations(),1);
 const dynamic=[];const added=setup('true',false,false,dynamic);dynamic.push(makeSelect([true]));
 added.events.pageshow({persisted:true});assert.equal(added.requests(),0,'Unknown initial selection remains protected');
 console.log('PASS: 6 lifecycle cases + 6 initial-select regression cases');
})().catch(e=>{console.error(e);process.exitCode=1;});
