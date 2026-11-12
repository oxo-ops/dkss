/* Six focused Q04 acceptance flows. No production/external URL is accepted. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {isDeepStrictEqual} = require('node:util');
const {chromium} = require('playwright');
const ROOT = path.resolve(__dirname, '..');
const OUT = path.resolve(process.argv[2] || 'q04-selection-browser-results');
const PYTHON = process.env.Q04_PYTHON;
if (!PYTHON || !path.isAbsolute(PYTHON)) throw Error('Q04_PYTHON must be an absolute Python 3.12 path');
if (fs.existsSync(OUT)) throw Error('Refusing to reuse browser evidence/profile directory');
fs.mkdirSync(OUT, {recursive: true});
process.env.TMPDIR = OUT;
const summary = {
  source_sha: process.env.Q04_SOURCE_SHA || null,
  database: 'disposable SQLite only; PostgreSQL is a separate workflow',
  csrf_enabled: true,
  rate_limit: 'disabled only in disposable fixture',
  viewport: {width: 1440, height: 1050},
  cases: [],
};
let browser;
const write = (filename, value) => fs.writeFileSync(filename, JSON.stringify(value, null, 2));
function ok(value, message) { if (!value) throw Error(message); }
function equal(actual, expected, message) {
  if (!isDeepStrictEqual(actual, expected)) {
    throw Error(message + '\nactual: ' + JSON.stringify(actual) + '\nexpected: ' + JSON.stringify(expected));
  }
}

async function startServer(dir) {
  const log = fs.createWriteStream(path.join(dir, 'server.log'));
  const child = spawn(PYTHON, ['-B', path.join(__dirname, 'q04_vehicle_master_selection_browser_server.py'),
    '--work-dir', path.join(dir, 'fixture')], {
    cwd: ROOT,
    env: {PATH: '/usr/bin:/bin', LANG: 'C.UTF-8', HOME: dir,
      PYTHONDONTWRITEBYTECODE: '1', PYTHONNOUSERSITE: '1'},
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stderr.pipe(log, {end: false});
  child.stdout.pipe(log, {end: false});
  child.once('close', () => log.end());
  async function close() {
    if (child.exitCode !== null || child.signalCode !== null) return;
    const stopped = new Promise(resolve => child.once('close', resolve));
    child.kill('SIGTERM');
    const timer = setTimeout(() => child.kill('SIGKILL'), 3000);
    await stopped;
    clearTimeout(timer);
  }
  try {
    let raw = '';
    const meta = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('Fixture startup exceeded 30 seconds')), 30000);
      child.once('error', error => { clearTimeout(timer); reject(error); });
      child.once('exit', code => { clearTimeout(timer); reject(Error('Fixture exited: ' + code)); });
      child.stdout.on('data', chunk => {
        raw += chunk;
        const line = raw.match(/BROWSER_READY (.*)\n/);
        if (line) { clearTimeout(timer); resolve(JSON.parse(line[1])); }
      });
    });
    ok(new URL(meta.base).hostname === '127.0.0.1', 'Fixture must be loopback');
    return {...meta, close};
  } catch (error) {
    await close();
    throw error;
  }
}

async function privateContext(base, result, javaScriptEnabled = true) {
  const context = await browser.newContext({viewport: summary.viewport,
    javaScriptEnabled, serviceWorkers: 'block'});
  context.setDefaultTimeout(10000);
  context.setDefaultNavigationTimeout(15000);
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin === base || ['blob:', 'data:'].includes(url.protocol)) return route.continue();
    result.external_blocked.push(url.href);
    return route.abort('blockedbyclient');
  });
  context.on('page', page => {
    page.on('console', message => {
      if (message.type() === 'error') result.console_errors.push(message.text());
    });
    page.on('pageerror', error => result.page_errors.push(error.message));
    page.on('dialog', dialog => dialog.accept());
    page.on('response', response => {
      if (response.request().resourceType() === 'document' || response.request().method() === 'POST') {
        result.steps.push({method: response.request().method(), url: response.url(), status: response.status()});
      }
    });
  });
  return context;
}

async function runCase(name, test, javaScriptEnabled = true) {
  const dir = path.join(OUT, name);
  fs.mkdirSync(dir);
  const result = {name, javaScriptEnabled, status: 'running', steps: [],
    console_errors: [], page_errors: [], external_blocked: []};
  let server, context;
  try {
    server = await startServer(dir);
    context = await privateContext(server.base, result, javaScriptEnabled);
    const page = await context.newPage();
    await login(page, server.base);
    async function snapshot(label) {
      const response = await context.request.get(server.base + '/__fixture/snapshot', {maxRedirects: 0});
      equal(response.status(), 200, 'Snapshot status');
      const value = await response.json();
      write(path.join(dir, label + '.json'), value);
      return value;
    }
    const before = await snapshot('before');
    await test({page, context, server, dir, result, snapshot, before});
    const after = await snapshot('after');
    const foreign = state => Object.fromEntries(Object.entries(state).map(([table, rows]) =>
      [table, rows.filter(row => row.company_code === 'Q04-FOREIGN')]));
    equal(foreign(after), foreign(before), 'Foreign-company rows changed');
    const safetyResponse = await context.request.get(server.base + '/__fixture/safety', {maxRedirects: 0});
    equal(safetyResponse.status(), 200, 'Safety evidence status');
    const safety = await safetyResponse.json();
    write(path.join(dir, 'safety-sql-observed.json'), safety);
    equal(safety.events, [], 'Fixture attempted a forbidden side effect');
    equal(result.page_errors, [], 'Browser JavaScript exception');
    result.foreign_rows_unchanged = true;
    result.status = 'passed';
  } catch (error) {
    result.status = 'failed';
    result.error = error.stack;
    console.error(name, error.stack);
    if (context) {
      for (const [index, page] of context.pages().entries()) {
        try { await capture(page, dir, 'failure-' + index); } catch (_) { /* preserve primary failure */ }
      }
    }
  } finally {
    if (context) await context.close();
    if (server) await server.close();
    write(path.join(dir, 'result.json'), result);
    summary.cases.push(result);
    write(path.join(OUT, 'summary.json'), summary);
    console.log(name + ': ' + result.status);
  }
}

async function login(page, base) {
  await page.goto(base + '/login');
  await page.locator('[name=company_code]').fill('Q04-OWN');
  await page.locator('[name=username]').fill('synthetic-admin');
  await page.locator('[name=password]').fill('Synthetic-only-pass-918!');
  await Promise.all([page.waitForURL(base + '/'), page.locator('button[type=submit]').click()]);
}
async function fillNew(page, chassis) {
  const values = {plate_area: '架空', plate_class: '100', plate_kana: 'あ', plate_number: '00-02',
    chassis_number: chassis, manufacturer: 'Synthetic Browser Maker', gross_vehicle_weight: '1000', max_payload: '100'};
  for (const [field, value] of Object.entries(values)) await page.locator(`[name=${field}]`).fill(value);
  await page.locator('select[name=office]').selectOption('Synthetic Office A');
  await page.locator('select[name=type]').selectOption('Synthetic Type A');
}
async function submit(page, selector = 'form.responsive-form button[type=submit]') {
  await page.locator(selector).click();
  await page.waitForLoadState('networkidle');
}
async function fields(page) {
  return page.locator('form.responsive-form').evaluate(form => Object.fromEntries(new FormData(form)));
}
async function capture(page, dir, name) {
  await page.screenshot({path: path.join(dir, name + '.png'), fullPage: true});
  fs.writeFileSync(path.join(dir, name + '.html'), await page.content());
}
const own = (state, id) => state.vehicle.find(row => row.id === id);

(async () => {
  browser = await chromium.launch({headless: true,
    env: {HOME: OUT, PATH: '/usr/bin:/bin', LANG: 'C.UTF-8', TMPDIR: OUT},
    args: ['--disable-background-networking', '--disable-component-update', '--disable-sync',
      '--disable-domain-reliability', '--disable-features=MediaRouter,OptimizationHints',
      '--proxy-server=http://127.0.0.1:9', '--proxy-bypass-list=127.0.0.1',
      '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'],
  });
  summary.browser_version = browser.version();
  summary.playwright_version = require('playwright/package.json').version;
  equal(summary.playwright_version, '1.62.1', 'Pinned Playwright version');

  await runCase('01-edit-back-change', async ({page, server, dir, result, snapshot, before}) => {
    await page.goto(server.base + `/master/vehicles/${server.own_id}/edit`);
    const choices = await page.locator('select').evaluateAll(selects => Object.fromEntries(
      selects.map(select => [select.name, Array.from(select.options).map(option => option.value)])));
    equal(choices.office, ['', 'Synthetic Office A', 'Synthetic Office B'], 'Office name values/company boundary');
    equal(choices.type, ['', 'Synthetic Type A', 'Synthetic Type B'], 'Type name values/company boundary');
    await page.locator('[name=manufacturer]').fill('Synthetic Back Change');
    await submit(page);
    ok((await page.getByRole('heading', {name: '車両の変更内容確認', exact: true}).innerText()).includes('変更内容確認'), 'Edit confirmation missing');
    equal(await snapshot('after-first-confirm'), before, 'Confirmation mutated DB');
    await capture(page, dir, 'edit-confirm');
    await submit(page, 'button[value=back]');
    equal(await page.locator('[name=manufacturer]').inputValue(), 'Synthetic Back Change', 'Back lost input');
    await page.locator('select[name=office]').selectOption('Synthetic Office B');
    await page.locator('select[name=type]').selectOption('Synthetic Type B');
    await submit(page);
    const confirmed = await fields(page);
    equal(confirmed.office, 'Synthetic Office B', 'Changed office not confirmed');
    equal(confirmed.type, 'Synthetic Type B', 'Changed type not confirmed');
    await submit(page, 'button[value=save]');
    const saved = await snapshot('saved');
    equal([own(saved, server.own_id).office, own(saved, server.own_id).type,
      own(saved, server.own_id).manufacturer], ['Synthetic Office B', 'Synthetic Type B', 'Synthetic Back Change'],
      'Edit save values');
    result.name_select_values = true;
    result.back_changed_selection_saved = true;
  });

  await runCase('02-new-history-double-submit', async ({page, context, server, dir, result, snapshot, before}) => {
    await page.goto(server.base + '/master/vehicles/new');
    await fillNew(page, 'BROWSER-NEW-DOUBLE');
    await submit(page);
    ok((await page.getByRole('heading', {name: '車両の登録内容確認', exact: true}).innerText()).includes('登録内容確認'), 'New confirmation missing');
    const confirmed = await fields(page);
    equal(await snapshot('confirmed'), before, 'New confirmation mutated DB');
    await capture(page, dir, 'new-confirm');
    await page.goBack();
    await page.waitForLoadState('networkidle');
    equal(await page.locator('select[name=office]').inputValue(), 'Synthetic Office A', 'Browser Back lost choice');
    await page.goForward();
    await page.waitForLoadState('networkidle');
    ok((await page.getByRole('heading', {name: '車両の登録内容確認', exact: true}).innerText()).includes('登録内容確認'), 'Forward lost confirmation');
    equal((await fields(page)).vehicle_master_selection, confirmed.vehicle_master_selection, 'Forward changed proof');
    await page.locator('button[value=save]').evaluate(button => { button.click(); button.click(); });
    await page.waitForURL(server.base + '/master/vehicles');
    await page.waitForLoadState('networkidle');
    const saved = await snapshot('after-double-click');
    equal(saved.vehicle.filter(row => row.chassis_number === 'BROWSER-NEW-DOUBLE').length, 1, 'Double click duplicated vehicle');
    // Ensure a real duplicate POST is tested even if Chromium coalesces rapid clicks.
    const duplicate = await context.request.post(server.base + '/master/vehicles/new', {
      form: {...confirmed, vehicle_form_action: 'save'}, headers: {Accept: 'application/json'}, maxRedirects: 0});
    equal(duplicate.status(), 409, 'Duplicate confirmation save must reject');
    equal(await snapshot('after-repeat-post'), saved, 'Duplicate save changed DB');
    result.double_click_one_vehicle = true;
    result.duplicate_post_status = 409;
    result.back_forward_passed = true;
  });

  for (const [number, kind, column, table] of [
    ['03', 'offices', 'office', 'office'], ['04', 'vehicle-types', 'type', 'vehicle_type'],
  ]) {
    await runCase(number + '-stale-' + kind, async ({page, context, server, dir, result, snapshot, before}) => {
      const target = `/master/vehicles/${server.own_id}/edit`;
      await page.goto(server.base + target);
      await page.locator('[name=manufacturer]').fill('Synthetic Preserve Other Input');
      await submit(page);
      const held = {...await fields(page), vehicle_form_action: 'save'};
      const otherContext = await privateContext(server.base, result);
      try {
        const manager = await otherContext.newPage();
        await login(manager, server.base);
        const old = before[table].find(row => row.company_code === 'Q04-OWN' && row.name === held[column]);
        await manager.goto(server.base + '/master/' + kind);
        await submit(manager, `form[action="/master/${kind}/${old.id}/delete"] button`);
        equal(own(await snapshot('after-delete'), server.own_id)[column], '', 'Delete did not detach');
        await manager.goto(server.base + '/master/' + kind + '/new');
        await manager.locator('[name=name]').fill(held[column]);
        await submit(manager, 'form:has(input[name=name]) button[type=submit]');
        const replacement = await snapshot('after-reregister');
        const current = replacement[table].find(row => row.company_code === 'Q04-OWN' && row.name === held[column]);
        ok(current.id !== old.id && current.master_generation !== old.master_generation, 'Master identity not replaced');
        const conflict = await context.request.post(server.base + target, {
          form: held, headers: {Accept: 'application/json'}, maxRedirects: 0});
        equal(conflict.status(), 409, 'Stale JSON submission must return 409');
        equal(await snapshot('after-json-reject'), replacement, 'JSON rejection changed DB');
        const htmlPost = page.waitForResponse(response => response.url() === server.base + target
          && response.request().method() === 'POST');
        await submit(page, 'button[value=save]');
        equal((await htmlPost).status(), 302, 'HTML conflict must use existing redirect recovery');
        equal(await page.locator(`select[name=${column}]`).inputValue(), '', 'Stale choice reselected replacement');
        equal(await page.locator('[name=manufacturer]').inputValue(), 'Synthetic Preserve Other Input', 'Other input lost');
        const other = column === 'office' ? 'type' : 'office';
        equal(await page.locator(`select[name=${other}]`).inputValue(), held[other], 'Unaffected choice lost');
        ok((await page.locator('body').innerText()).includes('選択情報が古いか不正'), 'Recovery message missing');
        equal(await snapshot('after-html-reject'), replacement, 'HTML rejection changed DB');
        await capture(page, dir, 'stale-recovered-form');
        await submit(page);
        ok((await page.getByRole('heading', {name: '車両の変更内容確認', exact: true}).innerText()).includes('変更内容確認'), 'Stale recovery did not reach confirmation');
        equal((await fields(page))[column], '', 'Reconfirmation selected same-name replacement');
        equal(await snapshot('after-reconfirm'), replacement, 'Reconfirmation changed DB');
        await capture(page, dir, 'reconfirmed-empty-choice');
        result.json_conflict_status = 409;
        result.html_conflict_status = 'POST 302 then GET 200 recovery';
        result.invalid_choice_cleared = true;
        result.other_input_retained = true;
        result.reconfirm_does_not_reselect = true;
      } finally { await otherContext.close(); }
    });
  }

  await runCase('05-no-javascript-manual', async ({page, server, result, snapshot}) => {
    await page.goto(server.base + '/master/vehicles/new');
    await fillNew(page, 'BROWSER-NO-JAVASCRIPT');
    await submit(page);
    await submit(page, 'button[value=back]');
    await page.locator('select[name=office]').selectOption('Synthetic Office B');
    await submit(page);
    await submit(page, 'button[value=save]');
    const row = (await snapshot('saved')).vehicle.find(vehicle => vehicle.chassis_number === 'BROWSER-NO-JAVASCRIPT');
    ok(row && row.office === 'Synthetic Office B' && row.type === 'Synthetic Type A', 'No-JS new save failed');
    result.manual_flow_passed_without_javascript = true;
  }, false);

  await runCase('06-certificate-synthetic-result', async ({page, context, server, dir, result, snapshot, before}) => {
    const vehicle = {plate_area: '架空', plate_class: '100', plate_kana: 'あ', plate_number: '00-03',
      chassis_number: 'BROWSER-CERTIFICATE-SYNTHETIC', manufacturer: 'Synthetic Certificate Maker',
      gross_vehicle_weight: '1000', max_payload: '100', first_registration_date: '2020-01', inspection_expiry: '2027-01-31'};
    let mockCalls = 0;
    await context.route(server.base + '/master/vehicles/certificate/extract', async route => {
      mockCalls += 1;
      await route.fulfill({status: 200, contentType: 'application/json',
        body: JSON.stringify({vehicle, warnings: [], needs_review: true, source_filename: 'synthetic.png'})});
    });
    await page.goto(server.base + '/master/vehicles/register');
    ok(await page.locator('#certificate-upload-form input[name=vehicle_master_selection]').inputValue(), 'Upload proof missing');
    await page.locator('#certificate-file').setInputFiles({name: 'synthetic.png', mimeType: 'image/png',
      buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAADklEQVR4nGP4DwYMEAoAU7oL9ZisIGcAAAAASUVORK5CYII=', 'base64')});
    await page.locator('#certificate-read-button').click();
    await page.locator('#certificate-review').waitFor({state: 'visible'});
    // Use the visible shipped searchable-choice UI, not its hidden native select.
    await page.locator('#certificate_office_search').fill('Synthetic Office A');
    await page.getByRole('listbox', {name: '営業所の候補'})
      .getByRole('option', {name: 'Synthetic Office A', exact: true}).click();
    await page.locator('#certificate_type_search').fill('Synthetic Type B');
    await page.getByRole('listbox', {name: '車種の候補'})
      .getByRole('option', {name: 'Synthetic Type B', exact: true}).click();
    await capture(page, dir, 'synthetic-certificate-review');
    await page.locator('#certificate-continue-button').click();
    await page.locator('h2').filter({hasText: '登録内容確認'}).waitFor();
    await page.waitForLoadState('networkidle');
    const confirmed = await fields(page);
    ok(confirmed.vehicle_master_selection, 'Certificate confirmation proof lost');
    equal(confirmed.chassis_number, vehicle.chassis_number, 'Certificate field lost');
    equal(confirmed.type, 'Synthetic Type B', 'Certificate type choice lost');
    equal(confirmed.office, 'Synthetic Office A', 'Certificate office choice lost');
    equal(await snapshot('confirmed'), before, 'Certificate confirmation changed DB');
    await capture(page, dir, 'certificate-confirm');
    await submit(page, 'button[value=save]');
    const savedRows = (await snapshot('saved')).vehicle.filter(row => row.chassis_number === vehicle.chassis_number);
    equal(savedRows.length, 1, 'Certificate save failed');
    equal([savedRows[0].office, savedRows[0].type], ['Synthetic Office A', 'Synthetic Type B'],
      'Saved certificate office/type choices lost');
    equal(mockCalls, 1, 'Unexpected synthetic extractor intercept count');
    result.synthetic_response_intercepts = mockCalls;
    result.real_extractor_calls = 0;
    result.proof_transfer_passed = true;
  });
  equal(summary.cases.length, 6, 'Six representative cases must complete');
})().catch(error => {
  summary.fatal = error.stack;
  console.error(error);
  process.exitCode = 1;
}).finally(async () => {
  if (browser) await browser.close();
  summary.passed = summary.cases.length === 6 && summary.cases.every(item => item.status === 'passed') && !summary.fatal;
  write(path.join(OUT, 'summary.json'), summary);
  if (!summary.passed) process.exitCode = 1;
  console.log('Q04_BROWSER_EVIDENCE ' + OUT);
});
