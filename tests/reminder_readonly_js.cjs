const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const code=fs.readFileSync('static/js/vehicle_checklist_results.js','utf8');
const start=code.indexOf('async function loadSavedReminderNotifyUsers() {');
const end=code.indexOf('    async function saveReminderUsers()',start);
assert(start>=0 && end>start);
(async()=>{
 for(const [search,selected] of [[null,null],[{},null],[null,{}]]){
  let calls=0;
  const ctx={reminderSearch:search,reminderSelected:selected,savedReminderNotifyUsers:['synthetic'],
   fetch:()=>{calls++;throw Error('forbidden');},renderReminderUsers:()=>{throw Error('readonly redraw');}};
  vm.createContext(ctx);vm.runInContext(code.slice(start,end),ctx);
  await ctx.loadSavedReminderNotifyUsers();assert.equal(calls,0);
 }
 console.log('PASS: readonly recipient initialization performs no lookup/redraw (3 cases)');
})().catch(e=>{console.error(e);process.exit(1);});
