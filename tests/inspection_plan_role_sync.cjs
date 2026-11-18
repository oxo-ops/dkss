const fs=require('fs'),vm=require('vm'),assert=require('assert');
const s=fs.readFileSync(__dirname+'/../static/js/vehicle_inspection_plans.js','utf8');
const line=s.split('\n').find(l=>l.includes('input.value=url.pathname+url.search'));
assert(line);
for(const n of [0,1,2]) {
 const inputs=Array.from({length:n},()=>({value:'old'}));
 const url=new URL('https://fixture.invalid/vehicle/inspection-plans?month=2027-01&view=calendar&office=%E6%9C%AC%E7%A4%BE&q=101');
 vm.runInNewContext(line,{url,document:{querySelectorAll(selector){assert.equal(selector,'form[action="/demo/role"] input[name="checklist_return"]');return inputs;}}});
 for(const input of inputs)assert.equal(input.value,url.pathname+url.search);
}
console.log('3 role-target sync cases passed (extracted production statement; not browser)');
