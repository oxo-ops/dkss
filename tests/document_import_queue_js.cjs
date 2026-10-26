const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/document_import_queue.js'), 'utf8');
function fixture() {
    const input = {files:[{name:'invoice.pdf',size:184053}], events:{}, addEventListener(name,callback){this.events[name]=callback;}};
    const button = {disabled:false,textContent:'読み込んで確認'};
    const status = {textContent:''};
    const form = {dataset:{},action:'https://test.example/vehicle/data-import/jobs',querySelector(selector){return selector.includes('input')?input:selector.includes('button')?button:status;}};
    let serial=0;
    const calls=[], destinations=[], errors=[];
    class Payload {constructor(){this.values={};}set(name,value){this.values[name]=value;}}
    class XHR {
        constructor(){this.events={};this.headers={};this.upload={addEventListener(){}};calls.push(this);}
        open(method,url){this.method=method;this.url=url;}
        setRequestHeader(name,value){this.headers[name]=value;}
        addEventListener(name,callback){this.events[name]=callback;}
        send(payload){this.payload=payload;}
    }
    const context={URL,FormData:Payload,XMLHttpRequest:XHR,crypto:{randomUUID:()=>String(++serial)},
        document:{querySelectorAll:selector=>selector.startsWith("form[")?[form]:[],getElementById:()=>null},
        location:{href:'https://test.example/vehicle/data-import',origin:'https://test.example',assign:url=>destinations.push(url)},window:{}};
    vm.runInNewContext(source,context);
    return {form,input,button,status,calls,destinations,errors,submit:()=>context.window.DKSSDocumentImportQueue.submit(form,message=>errors.push(message))};
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
