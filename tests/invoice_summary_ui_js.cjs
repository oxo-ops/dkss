const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const test=require('node:test'),assert=require('node:assert/strict');
const js=fs.readFileSync(path.join(__dirname,'../static/js/vehicle_inspection_plans.js'),'utf8');
function element(tag,text,cls=''){
 const e={tag,own:text??'',className:cls,children:[],dataset:{},events:{},attrs:{},
 append(...children){this.children.push(...children)},replaceChildren(...children){this.children=children},
 setAttribute(k,v){this.attrs[k]=v},addEventListener(k,fn){this.events[k]=fn}};
 Object.defineProperty(e,'textContent',{get(){return this.own+this.children.map(c=>c.textContent).join('')},set(v){this.own=v;this.children=[]}});
 e.classList={add(...names){e.className+=' '+names.join(' ')}};
 return e;
}
function fixture(){
 const list=element('div'),title=element('h2'),dialog={open:false,showModal(){this.open=true},close(){this.open=false},
 querySelector(s){return s==='[data-events-list]'?list:title}};
 const ctx={node:element,data:{vehicles:[{id:3,number:'横浜 100 い 11-11'}]},
 document:{querySelector:()=>dialog},deadlineState:()=>'',eventLabels:{actual:'実施済み'},labels:{},states:{}};
 vm.createContext(ctx);
 for(const [from,to] of [['invoiceLink(fact)','vehicleCell(v)'],['calendarEvent(entry,compact=false)','drawCalendar(rows)']]){
  const start=js.indexOf('    function '+from),end=js.indexOf('    function '+to,start);
  vm.runInContext(js.slice(start,end),ctx);
 }
 const fact={summary:'2026/10/28 オイル量の確認・補充 実施',source_url:'/vehicle/karte/3/documents/invoice/source'};
 return {ctx,fact,list,title,dialog};
}
test('invoice summary uses the existing completed chip',()=>{
 const {ctx,fact}=fixture(),a=ctx.invoiceLink(fact);
 assert(a.className.includes('ip-chip'));assert.equal(a.dataset.status,'completed');
 assert.equal(a.textContent,'✓ 10/28オイル量の確認・補充');
});
test('source remains accessible with a descriptive label',()=>{
 const {ctx,fact}=fixture(),a=ctx.invoiceLink(fact);
 assert.equal(a.href,fact.source_url);assert.equal(a.rel,'noopener');
 assert(a.attrs['aria-label'].includes('請求書原本を開く'));
});
test('unknown date is explicit and never substituted',()=>{
 const {ctx,fact}=fixture();fact.summary='実施日不明 オイル確認 実施';
 const a=ctx.invoiceLink(fact);assert(a.textContent.includes('日付不明'));assert(a.textContent.includes('オイル確認'));
});
test('compact calendar uses the existing event labels and classes',()=>{
 const {ctx,fact}=fixture(),a=ctx.calendarEvent({invoice:fact,p:{vehicle_record_id:3}},true);
 assert(a.className.includes('ip-cal-event-compact'));assert.equal(a.dataset.event,'actual');
 assert.equal(a.children.length,2);assert.equal(a.children[0].textContent,'実施');
 assert(a.children[1].textContent.startsWith('横浜 100 い 11-11'));
});
test('mobile calendar stacks the status vehicle and content like other actuals',()=>{
 const {ctx,fact}=fixture(),a=ctx.calendarEvent({invoice:fact,p:{vehicle_record_id:3}},false);
 assert.equal(a.children.length,3);assert.equal(a.children[0].textContent,'実施済み');
 assert.equal(a.children[1].tag,'strong');assert.equal(a.children[2].textContent,'オイル量の確認・補充');
});
test('multiple originals retain the existing selection dialog',()=>{
 const {ctx,fact,list,dialog}=fixture();
 fact.sources=[{filename:'first.pdf',url:'/first'},{filename:'second.pdf',url:'/second'}];
 const a=ctx.invoiceLink(fact);let prevented=false;
 a.events.click({preventDefault(){prevented=true}});
 assert(prevented);assert(dialog.open);assert.equal(list.children.length,2);
 assert.equal(list.children[1].href,'/second');
});
