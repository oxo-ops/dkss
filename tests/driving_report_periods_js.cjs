const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

// Run the actual controller; requestSubmit snapshots successful controls immediately,
// as a browser does, so later change listeners cannot repair an invalid request.
function screen({period='custom',compare='custom'}={}) {
 const field=value=>({value,disabled:false,required:false,min:'',max:'',listeners:{},
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);},
  change(value){this.value=value;for(const fn of this.listeners.change||[])fn({target:this});}});
 const inputs={period:field(period),compare:field(compare),start:field('2026-10-01'),end:field('2026-10-26'),
  compare_start:field('2026-06-01'),compare_end:field('2026-06-07')};
 const labels=['compare_start','compare_end'].map(key=>({hidden:false,querySelector:()=>inputs[key]}));
 const details={open:false},submissions=[];
 const form={querySelector(selector){
   if(selector==='.driving-extra-filters')return details;
   const name=selector.match(/^\[name=([^\]]+)\]$/)?.[1];return inputs[name]||null;
  },querySelectorAll(selector){
   if(selector==='[data-comparison-date]')return labels;
   if(selector==='input[type=date]')return [inputs.start,inputs.end,inputs.compare_start,inputs.compare_end];
   if(selector==='input[name=start],input[name=end]')return [inputs.start,inputs.end];
   return [];
  },requestSubmit(){submissions.push(Object.fromEntries(Object.entries(inputs).filter(([,input])=>!input.disabled).map(([key,input])=>[key,input.value])));}};
 let ready;
 const location=new URL('http://localhost/safety/driving-reports');
 const document={getElementById:id=>id==='driving-filter-form'?form:null,
  querySelector:()=>null,querySelectorAll:()=>[],
  addEventListener(type,fn){if(type==='DOMContentLoaded')ready=fn;}};
 vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/driving_reports.js'),'utf8'),{
  document,window:{addEventListener(){}},location,URL,Date,
  sessionStorage:{getItem:()=>null,removeItem(){},setItem(){}},
 });
 ready();return {inputs,labels,details,submissions};
}

test('all-period selection clears custom comparison before the first submission',()=>{
 const s=screen();s.inputs.period.change('all');
 assert.equal(s.submissions.length,1);
 assert.equal(s.submissions[0].period,'all');
 assert.equal(s.submissions[0].compare,'previous');
 assert.equal(s.submissions[0].compare_start,undefined);
 assert.equal(s.submissions[0].compare_end,undefined);
});

test('inactive comparison dates cannot validate or enter a GET, but can be reselected',()=>{
 const s=screen();s.inputs.start.change('2026-05-01');
 assert.equal(s.inputs.compare_end.max,'2026-04-30');
 s.inputs.compare.change('previous');
 for(const input of [s.inputs.compare_start,s.inputs.compare_end]){
  assert.equal(input.disabled,true);assert.equal(input.required,false);
 }
 assert.ok(s.labels.every(label=>label.hidden));
 s.inputs.compare.change('custom');
 assert.ok(s.labels.every(label=>!label.hidden));
 assert.equal(s.inputs.compare_start.value,'2026-06-01');
 assert.equal(s.inputs.compare_end.required,true);
 assert.equal(s.inputs.compare_end.disabled,false);
 assert.equal(s.inputs.compare_end.max,'2026-04-30');
});

test('custom selection opens date controls without submitting an incomplete period',()=>{
 const s=screen({period:'all',compare:'previous'});
 s.inputs.period.change('custom');
 assert.equal(s.details.open,true);assert.equal(s.submissions.length,0);
});

test('choosing a custom comparison from all periods requests a finite target',()=>{
 const s=screen({period:'all',compare:'previous'});s.inputs.compare.change('custom');
 assert.equal(s.inputs.period.value,'custom');
 assert.equal(s.inputs.compare_start.required,true);
 assert.equal(s.submissions.length,0);
});
