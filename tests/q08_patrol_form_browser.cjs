// Native Chromium selection and successful controls from the REAL Flask GET.
// Network is blocked; the Python test POSTs this exact FormData to the route.
const {chromium} = require('playwright');
const fs = require('node:fs');
(async () => {
    const html = fs.readFileSync(0, 'utf8');
    const browser = await chromium.launch({headless:true,
        executablePath:process.env.Q08_BROWSER_EXECUTABLE || chromium.executablePath(),
        args:['--disable-background-networking','--no-proxy-server',
            '--host-resolver-rules=MAP * ~NOTFOUND']});
    try {
        const context = await browser.newContext({serviceWorkers:'block'});
        const page = await context.newPage();
        await page.route('**/*', route => route.abort());
        await page.setContent(html, {waitUntil:'domcontentloaded'});
        const before = await page.locator('select[name=status]').evaluate(select => ({
            value:select.value, label:select.selectedOptions[0].textContent.trim(),
            disabled:select.selectedOptions[0].disabled,
        }));
        const formData = () => page.locator('form.responsive-form').evaluate(form =>
            Object.fromEntries(new FormData(form).entries()));
        // Model the rich editor's existing hidden-content contract. Only the
        // body is changed: do not set/remove/disable the status select in JS.
        await page.locator('input[name=content]').evaluate(input => {
            input.value='Q08 browser body-only edit';
        });
        const bodyOnly = await formData();
        const explicit = {};
        for (const status of ['未対応','対応中','修理完了']) {
            await page.locator('select[name=status]').selectOption(status);
            explicit[status] = await formData();
        }
        process.stdout.write(JSON.stringify({browserVersion:browser.version(),before, bodyOnly, explicit}));
    } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
