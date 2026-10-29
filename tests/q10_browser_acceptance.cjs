/* Real Chromium + loopback HTTP + PostgreSQL. External OCR/delivery are mocked. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const destination = new URL(fixture.url);
assert.equal(destination.protocol, 'http:');
assert.equal(destination.hostname, '127.0.0.1');
const output = path.resolve(process.argv[3]);
fs.mkdirSync(output, {recursive:true});
const run = Date.now().toString(36);
const results = {marker:'Q10_SYNTHETIC_ONLY', url:fixture.url, browser:'chromium', cases:[], blockedOrigins:[]};
const state = async(page)=>{
    const response = await page.request.get(fixture.url+'/__q10__/state');
    assert.equal(response.status(),200);
    const value = await response.json();
    assert.equal(value.marker,'Q10_SYNTHETIC_ONLY');
    assert.equal(value.dialect,'postgresql');
    return value;
};
const save = ()=>fs.writeFileSync(path.join(output,'browser-results.json'),JSON.stringify(results,null,2));

(async()=>{
    const browser = await chromium.launch({headless:true, executablePath:process.env.Q10_BROWSER_EXECUTABLE || undefined});
    results.version=browser.version();
    try{
        for(const device of [{name:'pc',width:1366,height:900},{name:'phone',width:390,height:844,isMobile:true,hasTouch:true}]){
            for(const scenario of [registration,ocrRecovery,returnPosition]){
                const name=device.name+'-'+scenario.name;
                const context=await browser.newContext({viewport:{width:device.width,height:device.height},isMobile:!!device.isMobile,hasTouch:!!device.hasTouch});
                await context.route('**/*',route=>{
                    const url=new URL(route.request().url());
                    if(url.origin===fixture.url)return route.continue();
                    results.blockedOrigins.push(url.origin); return route.abort();
                });
                const page=await context.newPage();
                page.setDefaultTimeout(12000);
                page.setDefaultNavigationTimeout(15000);
                const item={name,passed:false,observations:[],errors:[]};
                page.on('pageerror',error=>item.errors.push(error.message));
                try{
                    await login(page);
                    await scenario(page,item,device);
                    assert.deepEqual(item.errors,[], 'Unexpected browser JavaScript exception');
                    await page.screenshot({path:path.join(output,name+'.png'),fullPage:false});
                    item.passed=true;
                }catch(error){
                    item.failure=error.message;
                    await page.screenshot({path:path.join(output,name+'-failure.png'),fullPage:false}).catch(()=>{});
                    fs.writeFileSync(path.join(output,name+'-failure.html'),await page.content().catch(()=>''));
                }finally{
                    results.cases.push(item);save();console.log(JSON.stringify(item));await context.close();
                }
            }
        }
    }finally{await browser.close();}
    results.passed=results.cases.filter(x=>x.passed).length;
    results.failed=results.cases.length-results.passed;
    save();process.exitCode=results.failed?1:0;
})().catch(error=>{console.error(error.message);process.exitCode=1;});

async function login(page){
    const response=await page.goto(fixture.url+'/login');
    assert.equal(response.headers()['x-q10-synthetic-only'],'Q10_SYNTHETIC_ONLY');
    for(const [key,value] of Object.entries({company_code:fixture.company,username:fixture.username,password:fixture.password}))
        await page.locator(`[name=${key}]`).fill(value);
    await page.getByRole('button',{name:'ログイン',exact:true}).click();
    await page.waitForURL(url=>url.pathname!='/login');
}
async function noOverflow(page){
    const measured=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));
    assert.ok(measured.document<=measured.viewport+1,JSON.stringify(measured));
    return measured;
}
async function registration(page,item,device){
    const before=await state(page);
    await page.goto(fixture.url+'/master/vehicles/new');
    await page.locator('#chassis_number').waitFor();
    await page.locator('#type').selectOption({label:'Q10 Type'});
    await page.locator('#office').selectOption({label:'Q10 Office'});
    const [invalid]=await Promise.all([page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/master/vehicles/new'),
        page.getByRole('button',{name:'登録内容を確認',exact:true}).click()]);
    assert.equal(invalid.status(),400);
    await page.getByText('車台番号を入力してください。',{exact:true}).waitFor();
    assert.deepEqual((await state(page)).vehicles,before.vehicles);
    await page.goBack();
    await page.locator('#chassis_number').waitFor();
    assert.equal(await page.locator('#type').inputValue(),'Q10 Type');
    assert.equal(await page.locator('#office').inputValue(),'Q10 Office');
    const chassis='Q10-'+device.name+'-'+run;
    await page.locator('#chassis_number').fill(chassis);
    await page.getByRole('button',{name:'登録内容を確認',exact:true}).click();
    await page.getByRole('button',{name:'この内容で登録',exact:true}).waitFor();
    await page.getByRole('button',{name:'入力内容を修正',exact:true}).click();
    await page.locator('#chassis_number').waitFor();
    assert.equal(await page.locator('#chassis_number').inputValue(),chassis);
    assert.equal(await page.locator('#type').inputValue(),'Q10 Type');
    await page.getByRole('button',{name:'登録内容を確認',exact:true}).click();
    await page.getByRole('button',{name:'この内容で登録',exact:true}).waitFor();
    await page.getByRole('button',{name:'この内容で登録',exact:true}).click({clickCount:2});
    await page.waitForURL(url=>url.pathname==='/master/vehicles');
    const reflected=page.getByText(chassis,{exact:true}).filter({visible:true}).first();
    await reflected.waitFor();
    await reflected.scrollIntoViewIfNeeded();
    const after=await state(page);
    assert.equal(after.vehicles.filter(x=>x===chassis).length,1);
    assert.equal(after.vehicles.length,before.vehicles.length+1);
    item.observations.push({invalid:400,backPreserved:true,doubleClickCount:1,layout:await noOverflow(page)});
}
async function ocrRecovery(page,item,device){
    await page.goto(fixture.url+'/vehicle/data-import');
    const form=page.locator('form[data-import-queue]').filter({has:page.locator('[name=document_type][value=inspection]')});
    await form.waitFor();
    const before=await state(page);
    const buffer=Buffer.concat([fs.readFileSync(fixture.upload_path),Buffer.from('\n% Q10 '+device.name+' '+run)]);
    await form.locator('input[type=file]').setInputFiles({name:'q10-'+device.name+'.pdf',mimeType:'application/pdf',buffer});
    const abort=route=>route.abort('connectionfailed');
    await page.route('**/vehicle/data-import/jobs',abort);
    await form.locator('button[type=submit]').click();
    await form.locator('.import-error').waitFor();
    assert.match(await form.locator('.import-error').innerText(),/通信|送信|受付/);
    assert.equal(await form.locator('input[type=file]').evaluate(x=>x.files.length),1);
    assert.equal((await state(page)).drafts,before.drafts);
    await page.unroute('**/vehicle/data-import/jobs',abort);
    await form.locator('button[type=submit]').click({clickCount:2});
    await page.getByRole('link',{name:'資料の確認へ進む',exact:true}).waitFor({timeout:30000});
    await page.getByRole('link',{name:'資料の確認へ進む',exact:true}).click();
    await page.getByRole('button',{name:'失敗分だけ再実行',exact:true}).waitFor({timeout:30000});
    assert.equal((await state(page)).drafts,before.drafts+1);
    await page.getByRole('button',{name:'失敗分だけ再実行',exact:true}).click();
    await Promise.race([page.waitForURL(url=>url.pathname.endsWith('/preview'),{timeout:30000}),page.locator('#jobPreview').waitFor({timeout:30000})]);
    if(!new URL(page.url()).pathname.endsWith('/preview'))await page.locator('#jobPreview').click();
    await page.getByRole('button',{name:'選択した記録を登録',exact:true}).waitFor();
    await page.getByRole('button',{name:'選択した記録を登録',exact:true}).click({clickCount:2});
    await page.waitForURL(url=>/\/vehicle\/karte\/\d+\/inspections$/.test(url.pathname));
    await page.getByText('点検内容を確認',{exact:true}).first().click();
    await page.getByText(/ブレーキの効き/).filter({visible:true}).first().waitFor();
    const after=await state(page);
    assert.equal(after.inspections,before.inspections+1);
    const hash=require('node:crypto').createHash('sha256').update(buffer).digest('hex');
    assert.equal(after.attempts[hash],2);
    item.observations.push({networkAbortBeforeReceipt:true,receiptCount:1,ocrAttempts:2,registered:1,layout:await noOverflow(page)});
}
async function returnPosition(page,item){
    const route='/safety/driving-reports?period=all&scope=company&office=__company__&panel=reports';
    await page.goto(fixture.url+route);
    const row=page.locator('tr[id^=driving-report-]').nth(14);
    await row.waitFor();
    await row.evaluate(x=>x.scrollIntoView({block:'center'}));
    const identity=await row.getAttribute('id');
    const top=(await row.boundingBox()).y;
    await row.getByRole('link',{name:'日報の詳細',exact:true}).click();
    await page.getByRole('link',{name:'運転実績へ戻る',exact:true}).waitFor();
    await page.getByRole('link',{name:'運転実績へ戻る',exact:true}).click();
    await page.locator('#'+identity).waitFor();
    await page.waitForFunction(({id,top})=>Math.abs(document.getElementById(id).getBoundingClientRect().top-top)<=4,{id:identity,top},{timeout:8000});
    assert.equal(new URL(page.url()).searchParams.get('period'),'all');
    assert.equal(new URL(page.url()).searchParams.get('scope'),'company');
    item.observations.push({row:identity,topBefore:top,topAfter:(await page.locator('#'+identity).boundingBox()).y,layout:await noOverflow(page)});
}
