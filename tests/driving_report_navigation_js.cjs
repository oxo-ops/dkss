const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');

function screen(path='/safety/driving-reports?scope=office&period=all',storage=new Map()){
 const location=new URL(path,'http://localhost'),listeners={};
 const root={scrollTop:360,scrollHeight:2000,clientHeight:900,parentElement:null};
 const anchor={id:'driving-analysis-top',parentElement:root,getBoundingClientRect:()=>({top:100})};
 const owner='["TEST","admin","admin"]';
 const link=(href,direct=false,back=false)=>({href:new URL(href,location).href,target:'',
  hasAttribute:name=>name==='data-analysis-destination'&&direct,
  classList:{contains:name=>name==='driving-back-link'&&back},
  closest:selector=>selector==='[id]'?anchor:null});
 const back=link('/safety/driving-reports?scope=office',false,true);
 const workspace={dataset:{positionOwner:owner},contains:()=>true,
  querySelectorAll:()=>[],querySelector:selector=>selector==='.driving-back-link'?back:null,
  addEventListener(){}};
 let ready;
 const document={querySelector:selector=>selector==='.driving-page'?workspace:null,
  querySelectorAll:()=>[],getElementById:()=>null,
  addEventListener(type,fn){if(type==='DOMContentLoaded')ready=fn;else listeners[type]=fn;}};
 vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/driving_reports.js'),'utf8'),{
  document,window:{addEventListener(){}},location,URL,Date,
  getComputedStyle:()=>({overflowY:'auto'}),
  sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
 });
 ready();
 return {storage,back,owner,click(destination,direct=false){
  const target=destination==='back'?back:link(destination,direct);
  listeners.click({target:{closest:()=>target},button:0,defaultPrevented:false,
   preventDefault(){throw new Error('Analysis navigation must remain a normal link');}});
 }};
}

test('AI person destination without an anchor remembers its source and scoped position',()=>{
 const s=screen();s.click('?scope=office&period=all&focus=person&panel=analysis',true);
 const saved=JSON.parse(s.storage.get('driving-workspace-returns'));
 assert.equal(saved.length,1);assert.equal(saved[0].focus,'person');
 assert.equal(saved[0].id,'driving-analysis-top');assert.equal(saved[0].y,360);
 assert.equal(saved[0].top,100);assert.equal(saved[0].owner,s.owner);
 assert.equal(new URL(saved[0].url,'http://localhost').searchParams.has('focus'),false);
});

test('new office destination starts normally without inheriting an old section position',()=>{
 const s=screen('/safety/driving-reports?scope=company&period=all');
 s.click('?scope=office&office=one&period=all&panel=analysis',true);
 assert.equal(s.storage.has('driving-workspace-position'),false);
});

test('person back action restores the original AI source even after a metric change',()=>{
 const s=screen();s.click('?scope=office&period=all&focus=person&panel=analysis',true);
 const destination=screen('/safety/driving-reports?scope=office&focus=person&metric=other',s.storage);
 assert.equal(new URL(destination.back.href,'http://localhost').searchParams.get('period'),'all');
 destination.click('back');
 const saved=JSON.parse(s.storage.get('driving-workspace-position'));
 assert.equal(saved.id,'driving-analysis-top');assert.equal(saved.top,100);assert.equal(saved.y,360);
 assert.deepEqual(JSON.parse(s.storage.get('driving-workspace-returns')),[]);
});
