const test = require('node:test');
const assert = require('node:assert/strict');
const {candidates} = require('../static/js/first_use_guide.js');

const vehicle = '.karte-mobile-search-trigger, .top-bar #karte_vehicle_search';
const patrol = [
    '.patrol-reading-surface > .tabs .tab:not(.active)',
    '.safety-summary-grid .safety-summary-card',
    '.patrol-filter-disclosure > summary, .patrol-filter-disclosure[open] #pointout_keyword',
    '[data-guide-patrol-record]',
    '.safety-results-new-button',
];

for (const mode of ['normal', 'demo']) {
    test(mode + ': vehicle guide targets only the real shared search', () => {
        const search = {marker:'vehicle-search'};
        assert.deepEqual(candidates('vehicle_karte_list', s => s===vehicle ? search : null, mode).map(x=>[x.title,x.target]), [['車両カルテを開く',search]]);
        assert.deepEqual(candidates('vehicle_karte_list',()=>null,mode),[]);
    });
    test(mode + ': safety patrol anchors real actions and skips missing records/creation', () => {
        const controls = Object.fromEntries(patrol.map((s,i) => [s,{marker:i}]));
        assert.deepEqual(candidates('pointouts',s=>controls[s],mode).map(x=>x.title),
            ['記録の対象を切り替える','状態で絞る','条件で絞る','記録を開く','記録を追加する']);
        const absent = new Set(patrol.slice(3));
        assert.deepEqual(candidates('pointouts',s=>absent.has(s)?null:controls[s],mode).map(x=>x.target.marker),[0,1,2]);
        assert.deepEqual(candidates('vehicle_patrols',s=>controls[s],mode),[]);
    });
}

// Simulate script execution order and a manual launcher without claiming browser geometry.
function bootstrap(page, hash, controlsAtReady) {
    const vm = require('node:vm');
    const fs = require('node:fs');
    const source = fs.readFileSync(require('node:path').join(__dirname,'../static/js/first_use_guide.js'),'utf8');
    const onDocument = new Map(), onControl = new Map(), frames = [], storage = new Map();
    const geometry = {left:30,right:70,top:50,bottom:94,width:40,height:44};
    const control = {
        isConnected:true, dataset:{}, getClientRects:()=>[geometry], getBoundingClientRect:()=>geometry,
        closest:()=>null, classList:{add(){},remove(){}},
        scrollIntoView:()=>assert.fail('visible controls must not scroll'),
        click:()=>assert.fail('guide must never click a real control'),
    };
    const position = {left:0,right:250,top:0,bottom:160,width:250,height:160};
    const panel = {hidden:true,dataset:{},offsetWidth:250,
        style:{setProperty(){}},getBoundingClientRect:()=>position};
    const title = {};
    const close = {focus(){},addEventListener(){}};
    const next = {addEventListener(){}};
    const launch = {querySelector:()=>null,addEventListener:(type,fn)=>onControl.set(type,fn),setAttribute(){}};
    const children = {'.first-guide-panel':panel,'[data-guide-open]':launch,
        '[data-guide-title]':title,'[data-guide-count]':{},'[data-guide-text]':{},
        '[data-guide-next]':next,'[data-guide-close]':close};
    const root = {dataset:{page,mode:'normal'},querySelector:s=>children[s]};
    const document = {
        readyState:'loading', body:{}, activeElement:{tagName:'BODY'},
        getElementById:id=>id==='firstUseGuide'?root:null,
        addEventListener:(type,fn)=>onDocument.set(type,fn), querySelector:()=>null,
        querySelectorAll:s=>controlsAtReady(s) ? [control] : [],
    };
    const window = {location:{hash},addEventListener(){},matchMedia:()=>({matches:false}),
        localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)}};
    vm.runInNewContext(source,{document,window,innerWidth:390,innerHeight:844,
        getComputedStyle:()=>({visibility:'visible'}), MutationObserver:class {observe(){}},
        requestAnimationFrame:fn=>frames.push(fn)});
    return {panel,title,storage,ready:()=>{onDocument.get('DOMContentLoaded')();frames.shift()();},
        launch:()=>onControl.get('click')()};
}

test('vehicle search guide waits until the deferred toolbar icon exists', () => {
    let mounted=false;
    const s=bootstrap('vehicle_karte_list','',selector=>mounted && selector===vehicle);
    assert.equal(s.panel.hidden,true);
    mounted=true;
    s.ready();
    assert.equal(s.panel.hidden,false);
    assert.equal(s.title.textContent,'車両カルテを開く');
    assert.equal(s.storage.get('dkss:first-guide:v1:normal:vehicle_karte_list'),'1');
});

test('patrol anchored navigation is not interrupted; manual help still works', () => {
    const s=bootstrap('pointouts','#pointouts-list',selector=>selector===patrol[0]);
    s.ready();
    assert.equal(s.panel.hidden,true);
    assert.equal(s.storage.size,0);
    s.launch();
    assert.equal(s.panel.hidden,false);
    assert.equal(s.title.textContent,'記録の対象を切り替える');
});
