// Public vehicle display asset selection, cache reuse and existing navigation.
const {chromium} = require('playwright');
const fs = require('fs');
const assert = require('node:assert/strict');
const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const output = process.argv[3];
(async () => {
    const browser = await chromium.launch({headless: true,
        executablePath: process.env.Q12_BROWSER_EXECUTABLE || undefined,
        args: ['--disable-background-networking', '--no-proxy-server',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1']});
    const results = [];
    try {
        for (const dpr of [1, 2, 4]) {
            const mobile = dpr !== 1;
            const base = 'http://127.0.0.1:' + fixture.port;
            const context = await browser.newContext({viewport: mobile
                ? {width:390, height:844} : {width:1440, height:1000},
                deviceScaleFactor:dpr, isMobile:mobile, serviceWorkers:'block'});
            await context.addCookies([{name:'dkss_session', value:fixture.cookie, url:base}]);
            const page = await context.newPage();
            const errors = [], requests = [], responses = [];
            page.on('response', r => responses.push({path:new URL(r.url()).pathname,status:r.status()}));
            page.on('pageerror', e => errors.push(e.message));
            page.on('request', r => {
                assert.equal(new URL(r.url()).hostname, '127.0.0.1');
                requests.push(new URL(r.url()).pathname);
            });
            const route = '/vehicle/karte/1/documents?document=closed';
            await page.goto(base + route, {waitUntil:'load'});
            assert.equal(await page.locator('.top-bar-user').count(), 1);
            const image = page.locator('.vehicle-karte-type-image');
            const initial = await image.evaluate(i => ({src:new URL(i.currentSrc).pathname,
                width:i.width, height:i.height, complete:i.complete, natural:i.naturalWidth}));
            const size = dpr === 1 ? 96 : dpr === 2 ? 192 : 384;
            assert(initial.complete && initial.natural > 0);
            assert(initial.src.endsWith('/truck-display-' + size + '.png'));
            assert.equal(initial.width, 50);
            assert.equal(initial.height, 50);
            assert.equal(requests.filter(p => p.includes('/truck-display-')).length, 1);
            assert(!requests.some(p => p.endsWith('/truck.png')));
            responses.length = 0;
            await page.reload({waitUntil:'load'});
            const cache = await page.evaluate(() => {
                const r = performance.getEntriesByType('resource').find(r => r.name.includes('/truck-display-'));
                return {transfer:r.transferSize, encoded:r.encodedBodySize};
            });
            assert(responses.some(r => r.path.includes('/truck-display-') && r.status === 304)
                || cache.transfer === 0, 'repeat revalidates/reuses the public body');
            await page.screenshot({path:output.replace('.json', '-dpr' + dpr + '.png')});
            await page.goto(base + '/vehicle/karte/6', {waitUntil:'load'});
            assert((await image.getAttribute('src')).endsWith('/car.png'));
            await page.goBack({waitUntil:'load'});
            assert.equal(new URL(page.url()).pathname, '/vehicle/karte/1/documents');
            assert.equal(await image.evaluate(i => i.complete && i.width === 50), true);
            assert.deepEqual(errors, []);
            results.push({dpr, initial, cache, nonTruckUnchanged:true, back:true, errors});
            await context.close();
        }
        fs.writeFileSync(output, JSON.stringify(results, null, 2));
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
