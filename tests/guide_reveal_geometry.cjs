const assert=require('node:assert/strict');
const {revealOptions,candidates}=require('../static/js/first_use_guide.js');
for (const width of [320,390,768,1440]) {
 const v={left:0,top:0,width,height:700};
 const r=(top,bottom)=>({left:20,right:width-20,top,bottom});
 assert.equal(revealOptions(r(100,400),v,false),null);
 assert.equal(revealOptions(r(650,1200),v,false).behavior,'smooth');
 assert.equal(revealOptions(r(650,1600),v,false).block,'start');
 assert.equal(revealOptions(r(650,1600),v,true).behavior,'instant');
 assert.equal(revealOptions(r(12,1000),v,false),null);
}
const steps=candidates('dashboard',selector=>({selector,dataset:{}}),'demo');
assert.equal(steps.find(x=>x.title==='営業所の傾向を見る').revealSelector,'.dashboard-office-trends');
assert.equal(steps.find(x=>x.title==='期限や集計を確認する').revealSelector,'.dashboard-reference-safety');
console.log('20 viewport geometry checks and 2 section reveal checks passed');
