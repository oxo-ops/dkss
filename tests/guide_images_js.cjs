const test=require('node:test'),assert=require('node:assert/strict');
const {candidates}=require('../static/js/first_use_guide.js');
const selectors=['.vehicle-search-action','.inspection-item-detail','.check-choice-buttons','.vehicle-check-complete-form .approval-user-search','#reminder_notify_user_search','.reminder-readonly','.vehicle-check-complete-primary'];
function steps(excluded=[]){const elements=Object.fromEntries(selectors.filter(x=>!excluded.includes(x)).map(x=>[x,x==='.vehicle-check-complete-form .approval-user-search'?{dataset:{guideTitle:'運行判断の依頼先を選ぶ'}}:{}]));return candidates('vehicle_checklist_results',x=>elements[x]);}
test('driver sees detail then evaluation, request, read-only notification and completion',()=>{
 const result=steps(['#reminder_notify_user_search']);
 assert.deepEqual(result.map(x=>x.title),['車両を選ぶ','項目の詳細を見る','評価を入れる','運行判断の依頼先を選ぶ','点検未実施通知先を確認する','点検を完了する']);

});
test('manager sees editable notification, not read-only step',()=>{
 const result=steps(['.reminder-readonly']);assert.equal(result[4].title,'点検未実施通知先を選ぶ');
});
test('saved or noneditable checklist does not advertise hidden write actions',()=>{
 const result=steps(['.check-choice-buttons','.vehicle-check-complete-form .approval-user-search','#reminder_notify_user_search','.reminder-readonly','.vehicle-check-complete-primary']);
 assert.equal(result.length,2);
});
test('absent controls do not create fake steps',()=>assert.deepEqual(candidates('vehicle_checklist_results',()=>null),[]));

test('ordinary checklist uses its rendered approval caption',()=>{
 const result=candidates('vehicle_checklist_results',selector=>selector==='.vehicle-check-complete-form .approval-user-search'?{dataset:{guideTitle:'承認依頼先を選ぶ',guideText:'承認する人を選択'}}:null);
 assert.equal(result[0].title,'承認依頼先を選ぶ');assert.equal(result[0].text,'承認する人を選択');
});
test('existing storage key is unchanged and private storage failure does not auto-open',()=>{
 const {key,state}=require('../static/js/first_use_guide.js');
 assert.equal(key('demo','vehicle_checklist_results'),'dkss:first-guide:v1:demo:vehicle_checklist_results');
 assert.deepEqual(state(null,'x'),{available:false,seen:true});
 const store=new Map([['x','1']]);const storage={setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k),getItem:k=>store.get(k)};
 assert.deepEqual(state(storage,'x'),{available:true,seen:true});assert.equal(store.get('x'),'1');assert.equal(store.size,1);
});

test('safety detail has contextual read-only steps without approval controls',()=>{
 const visible=new Set(['.result-info-card','.checklist-result-detail-card','.checklist-history-card']);
 const result=candidates('checklist_result_detail',s=>visible.has(s)?{}:null,'demo');
 assert.deepEqual(result.map(s=>s.title),['点検した対象と日付を確認する','点検の内容を見る','履歴を確認する']);
});
test('ordinary driving help retains existing page controls',()=>{
 const result=candidates('driving_reports',s=>s==='#driving-filter-form'?{}:null,'normal');
 assert.equal(result.length,1);assert.equal(result[0].title,'実績の範囲を選ぶ');
});
