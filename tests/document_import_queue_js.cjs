const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/document_import_queue.js'), 'utf8');
function fixture({fetch} = {}) {
    const input = {files:[{name:'invoice.pdf',size:184053}], events:{}, addEventListener(name,callback){this.events[name]=callback;}};
    const button = {disabled:false,textContent:'読み込んで確認'};
    const status = {textContent:'', children:[], append(...items){this.children.push(...items);}};
    const classes=new Set();
    const form = {classList:{add:name=>classes.add(name),remove:name=>classes.delete(name)},dataset:{},action:'https://test.example/vehicle/data-import/jobs',querySelector(selector){return selector.includes('input')?input:selector.includes('button')?button:status;}};
    let serial=0;
    const calls=[], destinations=[], errors=[], timers=[];
    class Payload {constructor(){this.values={};}set(name,value){this.values[name]=value;}}
    class XHR {
        constructor(){this.events={};this.headers={};this.upload={addEventListener(){}};calls.push(this);}
        open(method,url){this.method=method;this.url=url;}
        setRequestHeader(name,value){this.headers[name]=value;}
        addEventListener(name,callback){this.events[name]=callback;}
        send(payload){this.payload=payload;}
    }
    const context={URL,AbortController,FormData:Payload,XMLHttpRequest:XHR,crypto:{randomUUID:()=>String(++serial)},
        document:{createElement:tag=>({tag}),querySelectorAll:selector=>selector.startsWith("form[")?[form]:[],getElementById:()=>null},
        location:{href:'https://test.example/vehicle/data-import',origin:'https://test.example',assign:url=>destinations.push(url)},window:{fetch,setTimeout:(callback,delay)=>{const timer={callback,delay};timers.push(timer);return timer;},
            clearTimeout:timer=>{const index=timers.indexOf(timer);if(index>=0)timers.splice(index,1);}}};
    vm.runInNewContext(source,context);
    return {form,input,button,status,calls,destinations,errors,timers,classes,submit:()=>context.window.DKSSDocumentImportQueue.submit(form,message=>errors.push(message))};
}
test('uploads to the durable endpoint, then opens the receipt without waiting for OCR',()=>{
    const f=fixture();f.submit();
    assert.equal(f.calls[0].method,'POST');
    assert.equal(f.calls[0].url,f.form.action);
    assert.equal(f.calls[0].headers['X-DKSS-Final-Submit'],'1');
    f.calls[0].status=202;f.calls[0].responseText=JSON.stringify({page_url:'/vehicle/data-import/jobs/test'});
    f.calls[0].events.load();
    assert.deepEqual(f.destinations,['https://test.example/vehicle/data-import/jobs/test?open=1']);
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

function kindTransferFixture({confirmed=true, busy=false, occupied=false}={}) {
    const files=[{name:'wrong.pdf',size:100},{name:'keep.pdf',size:100}];
    const fileInput={files,dispatchEvent(){}};
    const targetInput={files:occupied?[{name:'existing.pdf'}]:[],dispatchEvent(){}};
    const sourceForm={dataset:{},querySelector:()=>fileInput};
    let submitted=0, prompts=0;
    const target={dataset:busy?{loading:'1'}:{},querySelector:()=>targetInput,scrollIntoView(){},requestSubmit(){submitted++;}};
    class Transfer {constructor(){this.files=[];this.items={add:file=>this.files.push(file)};}}
    const context={DataTransfer:Transfer,Event:class {constructor(type){this.type=type;}},
        document:{querySelectorAll:()=>[],getElementById:()=>null,querySelector:selector=>selector==='#import-maintenance form'?target:null},
        window:{confirm(){prompts++;return confirmed;}}};
    vm.runInNewContext(source,context);
    const errors=[];
    return {source:fileInput,targetInput,errors,get submitted(){return submitted;},get prompts(){return prompts;},
        offer:suggestion=>context.window.DKSSDocumentImportQueue.offerDocument(sourceForm,
            {document_type:'maintenance',file_index:0,filename:'wrong.pdf',...suggestion},message=>errors.push(message))};
}
test('confirmed type suggestion moves only that file and submits the correct existing card',()=>{
    const f=kindTransferFixture();assert.equal(f.offer(),true);assert.equal(f.prompts,1);assert.equal(f.submitted,1);
    assert.deepEqual(f.targetInput.files.map(file=>file.name),['wrong.pdf']);
    assert.deepEqual(f.source.files.map(file=>file.name),['keep.pdf']);
});
test('declining the type suggestion keeps all original selections and submits nothing',()=>{
    const f=kindTransferFixture({confirmed:false});assert.equal(f.offer(),true);
    assert.equal(f.submitted,0);assert.equal(f.source.files.length,2);assert.equal(f.targetInput.files.length,0);
});
test('a busy or occupied destination never loses either set of selected files',()=>{
    for(const options of [{busy:true},{occupied:true}]) {
        const f=kindTransferFixture(options);assert.equal(f.offer(),true);
        assert.equal(f.submitted,0);assert.equal(f.prompts,0);assert.equal(f.source.files.length,2);assert.match(f.errors[0],/保持/);
        if(options.occupied)assert.equal(f.targetInput.files[0].name,'existing.pdf');
    }
});
test('invalid type or changed selections cannot redirect unrelated files',()=>{
    for(const suggestion of [{document_type:'other'},{file_index:-1},{filename:'different.pdf'}]) {
        const f=kindTransferFixture();assert.equal(f.offer(suggestion),false);assert.equal(f.submitted,0);assert.equal(f.prompts,0);
    }
});

async function acceptForPolling(f) {
    f.submit();
    f.calls[0].status = 202;
    f.calls[0].responseText = JSON.stringify({page_url:'/vehicle/data-import/jobs/receipt',
        status_url:'/vehicle/data-import/jobs/receipt/status'});
    f.calls[0].events.load();
    await new Promise(resolve => setImmediate(resolve));
}
test('accepted receipt stops polling on auth or missing receipt without resubmitting', async()=>{
    for (const code of [401,403,404]) {
        const f=fixture({fetch:async()=>({ok:false,status:code})});
        await acceptForPolling(f);
        assert.equal(f.timers.length,0);
        assert.match(f.status.textContent,code===404?/受付を表示できません/:/ログイン状態/);
        const link=f.status.children.find(item=>item.tag==='a');
        assert.equal(link.href,'https://test.example/vehicle/data-import/jobs/receipt?open=1');
        f.submit(); assert.equal(f.calls.length,1);
        assert.equal(f.form.dataset.loading,'1');
        assert.equal(f.classes.has('ocr-queue-busy'),false);
    }
});
test('transient status failures retry twice then offer durable receipt without upload', async()=>{
    const f=fixture({fetch:async()=>{throw new Error('network');}});
    await acceptForPolling(f);
    assert.equal(f.timers.length,1);
    for(let i=0;i<2;i++) {
        const timer=f.timers.shift();assert.equal(timer.delay,10000);
        await timer.callback();
    }
    assert.equal(f.timers.length,0);
    assert.match(f.status.textContent,/状況を確認できません/);
    assert.ok(f.status.children.some(item=>item.tag==='a'));
    f.submit();assert.equal(f.calls.length,1);
});
test('a recovered status request resets failures and completes through existing preview', async()=>{
    const responses=[null,{ok:true,json:async()=>({completed:0,total:1,files:[],finished:false})},
        null,{ok:true,json:async()=>({completed:1,total:1,files:[],finished:true,preview_ready:true,
            preview_url:'/vehicle/data-import/receipt/preview'})}];
    const f=fixture({fetch:async()=>{const r=responses.shift();if(!r)throw new Error('network');return r;}});
    await acceptForPolling(f);
    for(let i=0;i<3;i++)await f.timers.shift().callback();
    assert.equal(f.timers.length,0);
    assert.deepEqual(f.destinations,['https://test.example/vehicle/data-import/receipt/preview']);
    assert.equal(f.calls.length,1);
});

test('server errors and unexpected login HTML are bounded without exposing response content', async()=>{
    for(const response of [{ok:false,status:503},{ok:true,status:200,json:async()=>{throw new Error('private HTML');}}]) {
        const f=fixture({fetch:async()=>response});
        await acceptForPolling(f);
        for(let i=0;i<2;i++)await f.timers.shift().callback();
        assert.equal(f.timers.length,0);
        assert.equal(f.calls.length,1);
        assert.ok(!f.status.textContent.includes('private HTML'));
        assert.equal(f.classes.has('ocr-queue-busy'),false);
    }
});

test('malformed successful status payloads exhaust the failure budget', async()=>{
    for(const job of [null, [], {}, {completed:0,total:1,finished:false,files:[null]}]) {
        const f=fixture({fetch:async()=>({ok:true,json:async()=>job})});
        await acceptForPolling(f);
        for(let i=0;i<2;i++)await f.timers.shift().callback();
        assert.equal(f.timers.length,0);
        assert.ok(f.status.children.some(item=>item.tag==='a'));
        f.submit(); assert.equal(f.calls.length,1);
    }
});
test('stalled headers or body time out, abort GET only and preserve the accepted receipt', async()=>{
    for(const stalledBody of [false,true]) {
        const signals=[];
        const f=fixture({fetch:async(_,options)=>{
            signals.push(options.signal);
            return stalledBody?{ok:true,json:()=>new Promise(()=>{})}:new Promise(()=>{});
        }});
        await acceptForPolling(f);
        for(let i=0;i<3;i++) {
            const deadline=f.timers.shift(); assert.equal(deadline.delay,20000); deadline.callback();
            await new Promise(resolve=>setImmediate(resolve));
            assert.equal(signals[i].aborted,true);
            if(i<2) {
                const retry=f.timers.shift(); assert.equal(retry.delay,10000); retry.callback();
                await new Promise(resolve=>setImmediate(resolve));
            }
        }
        assert.equal(f.timers.length,0);
        assert.equal(f.classes.has('ocr-queue-busy'),false);
        assert.ok(f.status.children.some(item=>item.tag==='a'));
        f.submit(); assert.equal(f.calls.length,1);
    }
});

function resumeFixture(fetch) {
    const timers=[], signals=[];
    const classes=new Set();
    const status={textContent:'',children:[],append(...items){this.children.push(...items);}};
    const read={disabled:false};
    const form={classList:{add:n=>classes.add(n),remove:n=>classes.delete(n)},querySelector:()=>read};
    const card={scrollIntoView(){},querySelector:s=>s==='.import-form'?form:status};
    const link={dataset:{receiptKind:'maintenance',receiptStatusUrl:'/status'},href:'https://test.example/receipt',
        addEventListener(_,fn){this.click=fn;},setAttribute(){},removeAttribute(){}};
    const context={URL,AbortController,location:{href:'https://test.example/import',origin:'https://test.example'},
        document:{createElement:tag=>({tag}),querySelectorAll:s=>s==='.import-receipt-read[data-receipt-kind]'?[link]:[],
            getElementById:id=>id==='import-maintenance'?card:null},
        window:{fetch:async(url,options)=>{signals.push(options.signal);return fetch(url,options);},
            setTimeout:(callback,delay)=>{const t={callback,delay};timers.push(t);return t;},
            clearTimeout:t=>{const i=timers.indexOf(t);if(i>=0)timers.splice(i,1);}}};
    vm.runInNewContext(source,context);
    return {timers,signals,status,link,read,classes,start:async()=>{await link.click({preventDefault(){}});await new Promise(r=>setImmediate(r));}};
}
test('receipt-list resume rejects invalid successful bodies without endless polling',async()=>{
    const f=resumeFixture(async()=>({ok:true,json:async()=>null}));await f.start();
    for(let i=0;i<2;i++)await f.timers.shift().callback();
    assert.equal(f.timers.length,0);assert.equal(f.read.disabled,false);
    assert.equal(f.link.dataset.loading,undefined);assert.equal(f.classes.has('ocr-queue-busy'),false);
    assert.equal(f.status.children.find(x=>x.tag==='a').href,'https://test.example/receipt');
});
test('receipt-list resume bounds stalled body reads and retains normal completion',async()=>{
    for(const body of [false,true]) {
        const f=resumeFixture(async()=>body?{ok:true,json:()=>new Promise(()=>{})}:new Promise(()=>{}));await f.start();
        for(let i=0;i<3;i++) {
            const t=f.timers.shift();assert.equal(t.delay,20000);t.callback();await new Promise(r=>setImmediate(r));
            assert.equal(f.signals[i].aborted,true);
            if(i<2){f.timers.shift().callback();await new Promise(r=>setImmediate(r));}
        }
        assert.equal(f.timers.length,0);assert.equal(f.read.disabled,false);
        assert.equal(f.status.children.find(x=>x.tag==='a').href,'https://test.example/receipt');
    }
    const f=resumeFixture(async()=>({ok:true,json:async()=>({files:[],completed:1,total:1,finished:true,preview_ready:true,preview_url:'/preview'})}));
    await f.start();assert.equal(f.timers.length,0);assert.equal(f.read.disabled,false);
    assert.equal(f.status.children.find(x=>x.tag==='a').href,'https://test.example/preview');
});
