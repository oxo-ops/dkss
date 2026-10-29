'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
assert.equal(new URL(fixture.url).hostname, '127.0.0.1');
const out = path.resolve(process.argv[3]); fs.mkdirSync(out, {recursive:true});
const results = {marker:'M07_SYNTHETIC_ONLY', cases:[], blockedOrigins:[]};
const edit = '/vehicle/karte/' + fixture.vehicle_id + '/maintenance/' + fixture.record_id + '/edit';
let formScreenshot = 0;
async function state(page) {
    const response = await page.request.get(fixture.url + '/__m07__/state');
    assert.equal(response.status(),200);
    const value = await response.json(); assert.equal(value.marker,'M07_SYNTHETIC_ONLY');
    for (const original of value.originals) assert.equal(original.stored,original.actual);
    return value;
}
async function login(page) {
    const response = await page.goto(fixture.url+'/login');
    assert.equal(response.headers()['x-m07-synthetic-only'],'M07_SYNTHETIC_ONLY');
    for (const name of ['company_code','username','password'])
        await page.locator('[name='+name+']').fill(fixture[name==='company_code'?'company':name]);
    await page.getByRole('button',{name:'ログイン',exact:true}).click();
    await page.waitForURL(url=>url.pathname!='/login');
}
async function save(page) {
    const width = await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));
    assert.ok(width.document<=width.viewport+2, 'The correction form must fit the viewport: '+JSON.stringify(width));
    await page.screenshot({path:path.join(out,'edit-form-'+String(++formScreenshot)+'.png'),fullPage:false});
    await Promise.all([page.waitForNavigation(),page.locator('#maintenance_form button[name=maintenance_action][value=save]').click()]);
}
async function replace(page) {
    await page.goto(fixture.url+'/master/vehicles/invoice-reviews');
    const form = page.locator('form[action$="/'+fixture.pending_id+'/correction"]');
    await form.locator('xpath=..').locator('summary').click();
    await form.locator('[name=replaces_document_id]').selectOption(fixture.extra_id);
    await form.locator('[name=confirm_correction]').check();
    await Promise.all([page.waitForNavigation(), form.getByRole('button',{name:'請求額を差し替える'}).click()]);
}
(async()=>{
    const browser = await chromium.launch({headless:true,executablePath:process.env.Q10_BROWSER_EXECUTABLE||undefined});
    results.version = browser.version();
    try {
        const devices = fixture.legacy ? [{name:'legacy-pc',width:1366,height:900}] :
            [{name:'primary-pc',width:1366,height:900},{name:'additional-mobile',width:390,height:844,isMobile:true}];
        for(const device of devices) {
            const context = await browser.newContext({viewport:{width:device.width,height:device.height},isMobile:!!device.isMobile,hasTouch:!!device.isMobile});
            await context.route('**/*',route=>{
                const url=new URL(route.request().url());
                if(url.origin===fixture.url)return route.continue();
                results.blockedOrigins.push(url.origin);return route.abort();
            });
            const page=await context.newPage();page.setDefaultTimeout(15000);
            const item={name:device.name,passed:false,errors:[]};
            page.on('pageerror',error=>item.errors.push(error.message));
            try {
                await login(page);
                await page.goto(fixture.url+edit);
                if(device.name==='additional-mobile') {
                    await page.locator('#invoice_source').selectOption('document:'+fixture.pending_id);
                    await page.locator('#total_cost').fill('-1');
                    await save(page);
                    assert.equal(await page.locator('#total_cost').inputValue(),'-1','Invalid input must survive the response');
                    assert.equal((await state(page)).total,'130.00');
                    await page.locator('#total_cost').fill('25');
                    await save(page);
                    assert.equal((await state(page)).total,'135.00');
                } else {
                    assert.equal(await page.locator('#total_cost').evaluate(e=>e.readOnly),true);
                    await page.locator('#invoice_source').selectOption(fixture.primary_key);
                    assert.equal(await page.locator('#total_cost').inputValue(),'100.00');
                    const original=await page.locator('#invoice-read-original').getAttribute('href');
                    const source=await page.request.get(fixture.url+original);
                    assert.equal(source.status(),200);
                    await page.locator('#total_cost').fill('110');
                    assert.match(await page.locator('#invoice-read-after').textContent(),/140\.00/);
                    if(fixture.legacy) {
                        assert.equal((await state(page)).total,'140.00');
                        assert.equal(await page.locator('#invoice-evidence').evaluate(e=>e.required),true);
                        await page.locator('#invoice-evidence').check();
                    }
                    await save(page);
                    const before=await state(page);
                    assert.equal(before.total,'140.00');
                    const revision=before.details.invoice_cost_reads.sources[fixture.primary_key].revisions[0];
                    assert.equal(revision.after.total_cost,'110');
                    assert.equal(revision.reconciled_legacy,fixture.legacy);
                    await replace(page);
                    const after=await state(page);assert.equal(after.total,'130.00');
                    assert.equal(after.documents.find(d=>d.id===fixture.extra_id).status,'superseded');
                    assert.equal(after.documents.find(d=>d.id===fixture.pending_id).status,'confirmed');
                }
                assert.deepEqual(item.errors,[]);
                await page.screenshot({path:path.join(out,device.name+'.png'),fullPage:false});
                item.passed=true;
            } catch(error) {
                item.failure=error.message;
                await page.screenshot({path:path.join(out,device.name+'-failure.png')}).catch(()=>{});
                fs.writeFileSync(path.join(out,device.name+'-failure.html'),await page.content().catch(()=>''));
            } finally {
                results.cases.push(item);
                fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(results,null,2));
                console.log(JSON.stringify(item));await context.close();
            }
        }
    } finally {await browser.close();}
    results.passed=results.cases.filter(c=>c.passed).length;
    results.failed=results.cases.length-results.passed;
    fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(results,null,2));
    if(results.failed)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
