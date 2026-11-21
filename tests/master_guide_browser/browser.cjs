'use strict';
// Actual candidate CSS/JS and Flask-rendered fixture HTML; no browser network.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const from = new URL('https://fixture.invalid');
const repo = path.resolve(process.env.PRODUCT_REPO), dir = path.resolve(process.env.HTML_OUT);
const out = path.resolve(process.env.ARTIFACTS);
const inventory = JSON.parse(fs.readFileSync(path.join(dir, 'routes.json'), 'utf8'));
const cases = {
  driver_master: ['new_driver', 'driver'], office_master: ['new_office'],
  vehicle_master: ['vehicle_registration_method', 'vehicle'], vehicle_type_master: ['new_vehicle_type'],
  license_type_master: ['new_license_type'], delivery_place_master: ['new_delivery_place'],
  checklist_master: ['new_checklist', 'checklist'], patrol_content_type_master: ['new_patrol_content_type'],
  manual_master: ['new_manual'],
};
const getFixture = name => {
  const row = inventory.find(x => x.endpoint === 'normal_'+name);
  assert(row && row.status === 200 && row.synthetic_company === 'B' && row.role === 'admin', name);
  return {...row, html: fs.readFileSync(path.join(dir, row.endpoint+'.html'), 'utf8')};
};
const overlaps = (a,b) => a && b && Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x)>1 &&
  Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y)>1;
const bounds = async (element,width,height=844) => {
  await element.waitFor({state:'visible'});
  const b=await element.boundingBox();
  assert(b && b.x >= -1 && b.width > 0 && b.x+b.width <= width+1 &&
    b.y >= -1 && b.height > 0 && b.y+b.height <= height+1, JSON.stringify({width,b}));
  return b;
};
const frame = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
async function run() {
  fs.mkdirSync(out,{recursive:true});
  const browser = await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||undefined,args:['--no-sandbox']});
  const output = [];
  try {
    for (const width of [320,390,1440]) for (const [name,[newName,searchKind]] of Object.entries(cases)) {
      const context = await browser.newContext({viewport:{width,height:844},reducedMotion:'reduce',serviceWorkers:'block'});
      const page = await context.newPage();
      const row = getFixture(name), nextRow = getFixture(newName), unexpectedWrites = [], ordering = [];
      try {
        await context.route('**/*', async route => {
          const r = route.request(), u = new URL(r.url()), m=r.method();
          if (u.origin!==from.origin) return route.abort();
          if (m!=='GET') {
            if (m==='POST' && name==='office_master' && u.pathname==='/master/offices/order') {
              ordering.push(r.postDataJSON()); return route.fulfill({json:{ok:true}});
            }
            unexpectedWrites.push({method:m,path:u.pathname}); return route.abort();
          }
          for (const f of [row,nextRow]) if (u.pathname===f.path) return route.fulfill({contentType:'text/html',body:f.html});
          if (u.pathname.startsWith('/static/')) {
            const f=path.resolve(repo,'.'+u.pathname); if(f.startsWith(repo+'/static/')&&fs.existsSync(f)) return route.fulfill({path:f});
          }
          return route.fulfill({status:404,body:'offline'});
        });
        const url = new URL(row.path,from), targetUrl = new URL(nextRow.path,from);
        await page.goto(url.href);
        const inline = page.locator('.master-unified-heading');
        const tabs = page.locator('.master-unified-tabs');
        assert.equal(await inline.locator('p').count(),0,'no paragraph beneath master title');
        assert.equal(await inline.getAttribute('data-master-guided'),'');
        const purpose = await tabs.locator('.is-current[data-guide-text]').getAttribute('data-guide-text');
        assert(purpose?.trim(), 'per-page purpose');
        const toolbar = page.locator('.master-top-toolbar'), add=toolbar.locator('.entry-add-icon');
        const help = page.locator('#firstUseGuide[data-master-guide="1"] [data-guide-open]'), panel=page.locator('#firstGuidePanel');
        const openBounds = await bounds(help,width), addBounds=await bounds(add,width), headingBounds=await bounds(inline,width);
        assert(addBounds.y>=headingBounds.y+headingBounds.height-2, 'registration belongs below title');
        assert(addBounds.y+addBounds.height<= (await tabs.boundingBox()).y+1,'registration belongs before master tabs');
        assert.equal((await add.innerText()).trim(),'＋');
        assert(await add.getAttribute('aria-label'));
        assert(!overlaps(openBounds,addBounds), 'help and registration overlap');
        assert.equal(await panel.isVisible(),false,'master guide must not autoplay');
        await page.screenshot({path:path.join(out,name+'-'+width+'-closed.png')});
        await help.click();
        await frame(page);
        assert.equal((await panel.locator('[data-guide-title]').innerText()).trim(),'このマスタでできること');
        assert.equal((await panel.locator('[data-guide-text]').innerText()).trim(),purpose.trim());
        const popup = await bounds(panel,width);
        assert(!overlaps(popup,addBounds),'guide purpose popup covers registration');
        const active = page.locator('.master-unified-tab.is-current.first-guide-target');
        const activeBox = await active.boundingBox();
        if (activeBox) assert(!overlaps(popup,activeBox),'guide purpose popup covers highlighted tab');
        await page.screenshot({path:path.join(out,name+'-'+width+'-guide.png')});
        await page.keyboard.press('Escape');
        assert.equal(await panel.isVisible(),false);
        assert(await help.evaluate(el=>el===document.activeElement), 'Escape restores focus');
        let searchBounds = null;
        if (searchKind) {
          const search=toolbar.locator('[data-master-filter="'+searchKind+'"]');
          searchBounds=await bounds(search,width);
          assert(!overlaps(searchBounds,addBounds) && !overlaps(searchBounds,openBounds),'toolbar controls overlap');
          assert.equal(await search.getAttribute('aria-expanded'),'false');
          await search.click();
          const searchPanel=page.locator('#'+await search.getAttribute('aria-controls'));
          assert(await searchPanel.isVisible());
          assert.equal(await search.getAttribute('aria-expanded'),'true');
          const inputFocused = await searchPanel.evaluate(el=>el.contains(document.activeElement)); assert(inputFocused);
          await page.keyboard.press('Escape');
          assert.equal(await search.getAttribute('aria-expanded'),'false');
          assert.equal(await searchPanel.isVisible(),false);
        }
        if (name==='office_master') {
          const table = page.locator('[data-master-order-url="/master/offices/order"]');
          const ids = () => table.locator('[data-master-id]').evaluateAll(rs=>rs.map(r=>Number(r.dataset.masterId)));
          const before = await ids(); assert(before.length>=2);
          const handle = table.locator('.master-order-handle').first();
          await handle.press('ArrowDown');
          await page.waitForFunction(()=>document.getElementById('officeMasterOrderStatus')?.textContent==='保存しました');
          const after=await ids(); const desired=[before[1],before[0],...before.slice(2)];
          assert.deepEqual(after,desired);
          assert.deepEqual(ordering,[{ids:desired,previous_ids:before}]);
        }
        await add.click();
        await page.waitForURL(targetUrl.href);
        assert.equal(new URL(page.url()).pathname,nextRow.path);
        await page.goBack({waitUntil:'domcontentloaded'}); await page.waitForURL(url.href);
        assert(await help.isVisible());
        assert.deepEqual(unexpectedWrites,[]);
        output.push({name,width,passed:true,openBounds,addBounds,searchBounds,popup,sandboxReorder:name==='office_master'});
      } catch (error) {
        output.push({name,width,passed:false,error:String(error),unexpectedWrites});
        await page.screenshot({path:path.join(out,name+'-'+width+'-error.png')}).catch(()=>{});
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({cases:output},null,2));
  assert.equal(output.length,27);
  assert(output.every(r=>r.passed),JSON.stringify(output.filter(r=>!r.passed)));
}
run().catch(e=>{console.error(e);process.exitCode=1;});
