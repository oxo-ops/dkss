const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/vehicle_inspection_plans.js','utf8');
function fn(name){const start=source.indexOf('    function '+name+'(');assert(start>=0);let b=source.indexOf('{',start),n=1,i=b+1;for(;n;i++){if(source[i]==='{')n++;if(source[i]==='}')n--;}return source.slice(start,i);}
const sandbox={filters:{elements:{search:{value:''},month:{value:'2026-11'}}},focus:null,kind:'',state:'',view:'calendar',labels:{ad_hoc:'突発修理','3month':'3か月点検'},data:{vehicles:[{id:1,number:'品川１００か１０１',chassis_number:'AONAGI-101'},{id:2,number:'102',chassis_number:'B'}],plans:[],invoice_actuals:[]}};
sandbox.data.plans=[{vehicle_record_id:1,kind:'ad_hoc',status:'planned',display_state:'reserved',planned_month:'2026-11',note:'ワイパー交換',factory:'青凪工場'},{vehicle_record_id:1,kind:'3month',status:'planned',display_state:'unreserved',planned_month:'2026-11',note:'オイル交換'},{vehicle_record_id:2,kind:'ad_hoc',status:'planned',display_state:'reserved',planned_month:'2026-12',note:'ワイパー交換'},{vehicle_record_id:999,kind:'ad_hoc',status:'planned',display_state:'reserved',planned_month:'2026-11',note:'ワイパー交換'}];
sandbox.data.invoice_actuals=[{vehicle_record_id:1,performed_date:'2026-11-02',summary:'タイヤ交換 実施'},{vehicle_record_id:2,performed_date:'2026-11-04',summary:'オイル交換 実施'}];
vm.createContext(sandbox);vm.runInContext("const norm = s => (s || '').normalize('NFKC').replace(/\\s/g, '').toLowerCase();\n"+['matchesSearch','periodRows','visiblePlans','invoiceFacts'].map(fn).join('\n'),sandbox);
const rows=()=>vm.runInContext('visiblePlans()',sandbox),facts=()=>vm.runInContext('invoiceFacts(data.vehicles[0],"2026-11")',sandbox);
for(const q of ['ワイパー','青凪工場','突発修理']){sandbox.filters.elements.search.value=q;assert.equal(rows().length,1);}
sandbox.filters.elements.search.value='ＡＯＮＡＧＩ －１０１';assert.equal(rows().length,2);
sandbox.filters.elements.search.value='ワイパー';sandbox.view='year';assert.equal(rows().length,2);sandbox.focus=1;assert.equal(rows().length,1);sandbox.focus=null;
sandbox.state='unreserved';assert.equal(rows().length,0);sandbox.state='';sandbox.kind='3month';assert.equal(rows().length,0);sandbox.kind='';
sandbox.filters.elements.search.value='タイヤ';assert.equal(facts().length,1);sandbox.kind='ad_hoc';assert.equal(facts().length,0);sandbox.kind='';sandbox.state='reserved';assert.equal(facts().length,0);sandbox.state='';
sandbox.filters.elements.search.value='不存在';assert.equal(rows().length,0);assert.equal(facts().length,0);
sandbox.filters.elements.search.value='';sandbox.view='month';assert.equal(rows().length,2);
assert(!source.includes("norm(v.number+' '+v.chassis_number).includes(search)"));
console.log('PASS search: content/factory/kind/vehicle normalization; month/year/list; state/kind/focus; scoped IDs; invoices');
