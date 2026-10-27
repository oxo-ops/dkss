const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/document_import_queue.js'), 'utf8');
class Element {
    constructor() { this.dataset={};this.children=[];this.attributes={};this.isConnected=true;this.textContent='';this.classList={add(){},remove(){}}; }
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;}
    setAttribute(name,value){this.attributes[name]=value;}
    removeAttribute(name){delete this.attributes[name];}
    remove(){this.isConnected=false;}
}
function fixture() {
    const input = {files:[{name:'invoice.pdf',size:184053}], events:{}, addEventListener(name,callback){this.events[name]=callback;}};
    const button = {disabled:false,textContent:'読み込む'};
    const status = new Element(), clear = new Element(), zone = new Element(), form = new Element();
    form.action='https://test.example/vehicle/data-import/jobs';
    form.querySelector=selector=>selector==='input[type="file"]'?input:selector==='button[type="submit"]'?button:selector==='.import-clear'?clear:selector==='.import-dropzone'?zone:selector==='.import-inline-progress'?form.children.find(x=>x.isConnected && x.className===selector.slice(1)):status;
    let serial=0;
    const calls=[], destinations=[], errors=[], timers=[], requests=[], responses=[];
    class Payload {constructor(){this.values={};}set(name,value){this.values[name]=value;}}
    class XHR {
        constructor(){this.events={};this.headers={};this.upload={addEventListener(){}};calls.push(this);}
        open(method,url){this.method=method;this.url=url;}
        setRequestHeader(name,value){this.headers[name]=value;}
        addEventListener(name,callback){this.events[name]=callback;}
        send(payload){this.payload=payload;}
    }
    const context={URL,FormData:Payload,XMLHttpRequest:XHR,crypto:{randomUUID:()=>String(++serial)},
        document:{createElement:()=>new Element(),querySelectorAll:selector=>selector.startsWith("form[")?[form]:[],getElementById:()=>null},
        fetch:async(url,options)=>{requests.push({url,options});const job=responses.shift();if(job instanceof Error)throw job;return {ok:true,headers:{get:()=>"application/json"},json:async()=>job};},
        location:{href:'https://test.example/vehicle/data-import',origin:'https://test.example',assign:url=>destinations.push(url)},window:{setTimeout:(fn,ms)=>timers.push({fn,ms})}};
    vm.runInNewContext(source,context);
    return {form,input,button,status,calls,destinations,errors,timers,requests,responses,
        submit:()=>context.window.DKSSDocumentImportQueue.submit(form,message=>errors.push(message)),
        accept(job={}){calls.at(-1).status=202;calls.at(-1).responseText=JSON.stringify({page_url:'/vehicle/data-import/jobs/test',status_url:'/vehicle/data-import/jobs/test/status',total:1,completed:0,files:[{filename:'invoice.pdf',status:'reading'}],...job});calls.at(-1).events.load();}};
}
test('accepted upload stays on the drop screen and polls until the review is ready',async()=>{
    const f=fixture();f.submit();
    assert.equal(f.calls[0].method,'POST');assert.equal(f.calls[0].url,f.form.action);
    assert.equal(f.calls[0].headers['X-DKSS-Final-Submit'],'1');
    f.accept();assert.deepEqual(f.destinations,[]);assert.equal(f.button.textContent,'読み取り中…');
    assert.equal(f.input.disabled,true);assert.equal(f.form.attributes['aria-busy'],'true');
    f.responses.push({total:1,completed:0,files:[{filename:'invoice.pdf',status:'reading',phase:'ai_output',received_lines:3}]});
    await f.timers.shift().fn();assert.deepEqual(f.destinations,[]);
    const panel=f.form.querySelector('.import-inline-progress');assert.match(panel.children[1].children[0].textContent,/明細 3件/);
    f.responses.push({total:1,completed:1,preview_ready:true,preview_url:'/vehicle/data-import/test/preview',files:[]});
    await f.timers.shift().fn();assert.deepEqual(f.destinations,['https://test.example/vehicle/data-import/test/preview']);
    assert.equal(f.calls.length,1);assert.equal(f.requests.length,2);
});
test('network retries keep their receipt key; selecting a new file starts a new receipt',()=>{
    const f=fixture();f.submit();
    const first=f.calls[0].payload.values.upload_key;
    f.calls[0].events.error();assert.equal(f.button.disabled,false);
    f.submit();assert.equal(f.calls[1].payload.values.upload_key,first);
    f.calls[1].events.error();f.input.events.change();
    f.submit();assert.notEqual(f.calls[2].payload.values.upload_key,first);
});
test('oversized batches and duplicate submissions do not start extra requests',()=>{
    const f=fixture();f.input.files=[{size:201*1024*1024}];f.submit();
    assert.equal(f.calls.length,0);assert.match(f.errors[0],/200MB/);
    f.input.files=[{size:184053}];f.submit();f.submit();assert.equal(f.calls.length,1);
});
test('server validation errors are displayed without discarding selected files',()=>{
    const f=fixture();f.submit();f.calls[0].status=413;
    f.calls[0].responseText=JSON.stringify({errors:[{message:'容量を確認してください。'}]});
    f.calls[0].events.load();assert.equal(f.errors[0],'容量を確認してください。');
    assert.equal(f.input.files.length,1);assert.equal(f.button.disabled,false);
});

test('connection failure retries status without uploading the PDF again',async()=>{
 const f=fixture();f.submit();f.accept();f.responses.push(new Error('offline'));
 await f.timers.shift().fn();assert.match(f.status.textContent,/受付済み/);assert.equal(f.timers[0].ms,10000);
 assert.equal(f.calls.length,1);assert.deepEqual(f.destinations,[]);
});
test('failed or ambiguous documents stay in the intake card with recovery links',()=>{
 const f=fixture();f.submit();f.accept({finished:true,failed:1,needs_review:1,preview_ready:true,preview_url:'/vehicle/data-import/test/preview',files:[{filename:'invoice.pdf',status:'type_review',kind_url:'/vehicle/data-import/test/kind'}]});
 assert.deepEqual(f.destinations,[]);assert.equal(f.button.disabled,false);assert.equal(f.input.disabled,false);
 assert.equal(f.form.querySelector('.import-inline-progress').children[2].children.length,3);
 assert.equal(f.timers.length,0);
});
test('foreign status and preview URLs never navigate away or receive requests',()=>{
 const f=fixture();f.submit();f.accept({status_url:'https://other.example/status'});
 assert.match(f.errors[0],/不正/);assert.equal(f.timers.length,0);assert.deepEqual(f.destinations,[]);
 const g=fixture();g.submit();g.accept({finished:true,preview_ready:true,preview_url:'https://other.example/preview'});
 assert.deepEqual(g.destinations,[]);assert.equal(g.button.disabled,false);
});
test('cancelled intake does not open a delayed review response',async()=>{
 const f=fixture();f.submit();f.accept();delete f.form.dataset.loading;
 await f.timers.shift().fn();assert.equal(f.requests.length,0);assert.deepEqual(f.destinations,[]);
});
