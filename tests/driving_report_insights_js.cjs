const {test}=require('node:test');const assert=require('node:assert/strict');
const {series,validDay}=require('../static/js/driving_reports.js');
test('missing or invalid measurements stay gaps rather than zero',()=>{
 const rows=series([{date:'2026-10-01',value:'0'},{date:'2026-10-02',value:null},{date:'2026-10-03',value:''},{date:'2026-10-04',value:'Infinity'}]);
 assert.deepEqual(rows.map(r=>r.value),[0,null,null,null]);
});
test('invalid days are rejected and valid points sorted without inventing dates',()=>{
 assert.equal(validDay('2026-02-30'),false);assert.equal(validDay('2028-02-29'),true);
 assert.deepEqual(series([{date:'2026-10-02',value:'2'},{date:'2026-10-01',value:'1'},{date:'bad',value:'3'}]).map(r=>r.date),['2026-10-01','2026-10-02']);
});
