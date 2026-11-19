const assert=require('node:assert/strict');
const {candidates}=require('../static/js/first_use_guide.js');
const steps=candidates('dashboard',s=>({dataset:{},selector:s}),'demo');
const ai=steps.find(s=>s.title==='AIの整備提案を見る');
assert(ai); assert.equal(ai.text,'提案の行を押すと、理由と対応を確認できます。');
assert.equal(steps.length,7);
console.log('dashboard row-link guidance and 7 steps pass');
