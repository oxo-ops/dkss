// Viewport transitions without a browser: the same module used by every page.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = name => fs.readFileSync(path.join(__dirname, '../static/js', name), 'utf8');
const element = () => {
    const attributes = new Map(), styles = new Map(), classes = new Set();
    return {
        getAttribute: key => attributes.get(key) ?? null,
        setAttribute: (key, value) => attributes.set(key, value),
        style: {getPropertyValue:key=>styles.get(key)||'', setProperty:(key,value)=>styles.set(key,value)},
        classList: {contains:key=>classes.has(key), add:key=>classes.add(key),
            remove:(...keys)=>keys.forEach(key=>classes.delete(key)),
            toggle:(key,on)=>on?classes.add(key):classes.delete(key)},
    };
};
const root=element(), body=element(), toggle=element(), review=element();
body.classList.add('sidebar-collapsed');
const main={clientWidth:1208}, pending=new Map(), events={}, visualEvents={};
let width=1440, height=900, visualHeight=900, frame=0;
review.clientWidth=1100;
const media={get matches(){return width<=900;},addEventListener:(_type,fn)=>events.media=fn};
const window={get innerWidth(){return width;},get innerHeight(){return height;},
    visualViewport:{get height(){return visualHeight;},addEventListener:(type,fn)=>visualEvents[type]=fn},
    DkssShell:{readPreference:()=> '1'},matchMedia:()=>media,addEventListener:(type,fn)=>events[type]=fn};
const document={documentElement:root,body,readyState:'complete',
    querySelector:selector=>selector==='.main-content'?main:selector==='#sidebarToggle'?toggle:null,
    querySelectorAll:()=>[review]};
const context={window,document,localStorage:{getItem:()=> '1'},
    requestAnimationFrame:fn=>{pending.set(++frame,fn);return frame;},
    getComputedStyle:()=>({paddingLeft:'12px',paddingRight:'12px'}),
    ResizeObserver:class {observe(){}}, MutationObserver:class {observe(){}},console};
vm.createContext(context);vm.runInContext(source('responsive_layout.js'),context);
function flush(){const work=[...pending.values()];pending.clear();work.forEach(fn=>fn());}
function resize(w,h,m,r,v=h){width=w;height=h;visualHeight=v;main.clientWidth=m;review.clientWidth=r;events.resize();flush();}
flush();
assert.equal(body.getAttribute('data-content-layout'),'wide');
assert.equal(review.getAttribute('data-compact-review'),'false');
resize(960,720,760,720);
assert.equal(body.getAttribute('data-content-layout'),'medium');
assert.equal(review.getAttribute('data-compact-review'),'true');
resize(768,600,768,720,540);
assert.equal(body.classList.contains('sidebar-collapsed'),false);
assert.equal(body.getAttribute('data-short-viewport'),'true');
assert.equal(root.style.getPropertyValue('--app-viewport-height'),'540px');
resize(480,320,480,440,300);
assert.equal(body.getAttribute('data-content-layout'),'compact');
assert.equal(toggle.getAttribute('aria-expanded'),'false');
body.classList.add('sidebar-open');events.resize();flush();
assert.equal(toggle.getAttribute('aria-expanded'),'true');
resize(1440,900,1208,1100);
assert.equal(body.classList.contains('sidebar-collapsed'),true);
assert.equal(body.classList.contains('sidebar-open'),false);
assert.equal(review.getAttribute('data-compact-review'),'false');
visualHeight=200;visualEvents.resize();flush();
assert.equal(root.style.getPropertyValue('--app-viewport-height'),'200px');
assert.equal(review.getAttribute('data-compact-review'),'true');
resize(1440,900,950,800);
assert.equal(body.getAttribute('data-content-layout'),'medium');
assert.equal(review.getAttribute('data-compact-review'),'true');
events.resize();events.resize();visualEvents.resize();
assert.equal(pending.size,1,'Resize events are coalesced');flush();

// Viewport-relative bounds must not subtract scrolling for a second time.
const planSource=source('vehicle_inspection_plans.js');
const start=planSource.indexOf('    function remainingHeight(element)');
const end=planSource.indexOf('    function footerHeight()',start);
const geometry={window:{innerHeight:900,scrollY:450},
    planner:{closest:()=>({scrollTop:600,getBoundingClientRect:()=>({bottom:900})})},Math};
vm.createContext(geometry);vm.runInContext(planSource.slice(start,end),geometry);
assert.equal(vm.runInContext('remainingHeight({getBoundingClientRect:()=>({top:300})})',geometry),600);
assert.equal(vm.runInContext('remainingHeight({getBoundingClientRect:()=>({top:-100})})',geometry),900);
console.log('PASS: split widths, content widths, zoom/visual viewport, drawer restore, OCR transitions, frame coalescing, scrolled planner bounds');

// Sidebar preferences must be applied while the shell is still unparsed.
for (const [path, width, saved, initial, expected] of [
    ['/',1440,'1',false,true], ['/',1440,'0',false,false],
    ['/vehicle/karte/1',1440,'1',false,true],
    ['/vehicle/checklists/1',1440,'0',true,true],
    ['/safety/checklists/1/new',1440,'0',false,true],
    ['/safety/checklists/1',1440,'1',false,false],
    ['/vehicle/data-import/batch/preview',1440,'0',false,true],
    ['/vehicle/checklists/1',390,'1',true,false],
]) {
    const body=element(); if(initial)body.classList.add('sidebar-collapsed');
    const window={innerWidth:width,location:{pathname:path},localStorage:{getItem:()=>saved}};
    vm.runInNewContext(source('shell_bootstrap.js'),{window,document:{body}});
    assert.equal(body.classList.contains('sidebar-collapsed'),expected, path+' / '+width);
}
const noStorage={innerWidth:1440,location:{pathname:'/'},
    localStorage:{getItem:()=>{throw Error('denied')},setItem:()=>{throw Error('denied')}}};
vm.runInNewContext(source('shell_bootstrap.js'),{window:noStorage,document:{body:element()}});
assert.equal(noStorage.DkssShell.readPreference('sidebarCollapsed'),null);
assert.doesNotThrow(()=>noStorage.DkssShell.writePreference('sidebarCollapsed','1'));
console.log('PASS: first-paint sidebar preferences, page overrides, mobile and unavailable storage');
