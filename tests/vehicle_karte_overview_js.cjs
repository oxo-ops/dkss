const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/vehicle_karte_overview.js'), 'utf8');

function element(tag = 'div') {
    return {tag, dataset: {}, children: [], attributes: {}, hidden: false, textContent: '',
        append(...children) { this.children.push(...children); },
        replaceChildren(...children) { this.children = children; },
        setAttribute(name, value) { this.attributes[name] = value; }};
}
const proposal = (id, priority = '中', extra = {}) => ({
    proposal_id: id, proposal_revision: 'current', priority, target: `部品${id}`,
    action: '保存された提案文です。点検と交換の計画を確認してください。', ...extra,
});

async function mount(recommendations = [], options = {}) {
    const panel = element(), list = element('ul'), status = element('p'), summary = element('b');
    panel.dataset = {resultUrl: options.inactive ? '' : '/vehicle/karte/7/analysis/result',
        analysisUrl: options.analysisUrl || '/vehicle/karte/7/analysis'};
    panel.querySelector = selector => selector === '[data-ko-ai-status]' ? status : list;
    const requests = [];
    const data = {ok: true, has_result: true, status: 'completed', is_current: true,
        analysis: {recommendations}, ...options.data};
    const context = {URL, URLSearchParams, AbortSignal, window: {location: {origin: 'https://example.test'}},
        document: {getElementById: id => id === 'ko-ai' ? panel : null,
            querySelector: selector => selector === '[data-ko-summary-count]' ? summary : null,
            createElement: element},
        fetch: async (url, init) => {
            requests.push({url, init});
            if (options.reject) throw new Error('offline');
            return {ok: options.ok !== false, redirected: Boolean(options.redirected),
                json: async () => data};
        }};
    vm.runInNewContext(source, context);
    await new Promise(resolve => setImmediate(resolve));
    return {panel, list, status, summary, requests,
        rows: list.children.filter(child => child.className === 'ko-proposal')};
}

test('shows up to five saved suggestions in stable high-to-low order without generating advice', async () => {
    const ui = await mount([proposal('low', '低'), proposal('medium1'), proposal('high1', '高'),
        proposal('medium2'), proposal('high2', '高'), proposal('medium3')]);
    assert.deepEqual(ui.rows.map(row => row.dataset.proposalId), ['high1', 'high2', 'medium1', 'medium2', 'medium3']);
    assert.equal(ui.summary.textContent, '6件');
    assert.equal(ui.list.children.at(-1).children[0].textContent, '残り1件を分析で確認 →');
    assert.equal(ui.rows[0].children[0].textContent, '高');
    assert.equal(ui.rows[0].children[0].attributes['aria-label'], '対応優先度：高');
    assert.equal(ui.rows[0].children[1].children[1].textContent, proposal('high1').action);
    assert.equal(ui.rows[0].children[2].href, 'https://example.test/vehicle/karte/7/analysis#proposal=high1');
    assert.equal(ui.rows[0].children[2].attributes['aria-label'], '詳細：部品high1の提案と対応を確認');
    assert.equal(ui.status.hidden, true);
    assert.equal(ui.requests.length, 1);
    assert.equal(ui.requests[0].init.method, undefined);
    assert.equal(ui.requests[0].init.credentials, 'same-origin');
});

test('does not manufacture five rows when only one suggestion is saved', async () => {
    const ui = await mount([proposal('only')]);
    assert.equal(ui.rows.length, 1);
    assert.equal(ui.summary.textContent, '1件');
    assert.equal(ui.list.children.length, 1);
});

test('hides completed or dismissed current revisions and record checks but retains changed proposals', async () => {
    const ui = await mount([proposal('complete', '高', {feedback: {revision: 'current', status: 'completed'}}),
        proposal('dismissed', '高', {feedback: {revision: 'current', status: 'dismissed'}}),
        proposal('record', '高', {category: '記録確認'}),
        proposal('changed', '高', {feedback: {revision: 'previous', status: 'completed'}}), null]);
    assert.deepEqual(ui.rows.map(row => row.dataset.proposalId), ['changed']);
    assert.equal(ui.rows[0].children[1].children[0].children[1].textContent, '提案更新あり');
});

test('preserves accepted and in-progress feedback without treating it as completed', async () => {
    const ui = await mount([proposal('a', '高', {feedback: {revision: 'current', status: 'accepted'}}),
        proposal('b', '中', {feedback: {revision: 'current', status: 'in_progress'}})]);
    assert.equal(ui.rows[0].children[1].children[0].children[1].textContent, '採用');
    assert.equal(ui.rows[1].children[1].children[0].children[1].textContent, '対応中');
});

test('invalid saved priority is separate data state without a fourth badge, HTML stays text, and hashes are encoded', async () => {
    const value = '<img src=x onerror=alert(1)>';
    const ui = await mount([proposal('a/#b', 'unexpected', {target: value, action: value}), proposal('low', '低')]);
    const row = ui.rows[1];
    assert.equal(row.dataset.priorityDataState, 'invalid');
    assert.equal(row.children.some(child => child.className === 'ko-priority'), false);
    const copy = row.children[0];
    assert.equal(copy.className, 'ko-proposal-copy');
    assert.equal(copy.children[0].children[0].textContent, value);
    assert.equal(copy.children[1].textContent, value);
    assert.equal(copy.children[1].children.length, 0);
    assert.equal(copy.children[2].className, 'ko-proposal-data-state');
    assert.equal(copy.children[2].textContent, '保存された優先度を確認できません。詳細から元の提案を確認してください。');
    assert.equal(new URL(row.children[1].href).hash, '#proposal=a%2F%23b');
});

test('stale results remain explicitly marked during pending, running, and failed refreshes', async () => {
    for (const [status, label] of [['pending', '更新待ち'], ['running', '分析中'], ['error', '更新エラー']]) {
        const ui = await mount([proposal('old')], {data: {status, is_current: false}});
        assert.equal(ui.rows.length, 1);
        assert.equal(ui.panel.dataset.current, 'false');
        assert.equal(ui.status.hidden, false);
        assert.equal(ui.status.textContent, `前回の提案 · ${label}`);
    }
});

test('empty results are distinct from missing and in-progress initial results', async () => {
    const empty = await mount([]);
    assert.equal(empty.summary.textContent, '0件');
    assert.match(empty.list.children[0].textContent, /提案はありません/);
    const pending = await mount([], {data: {has_result: false, status: 'pending'}});
    assert.equal(pending.summary.textContent, '未取得');
    assert.equal(pending.rows.length, 0);
    assert.equal(pending.status.textContent, '初回の分析結果を待っています。');
});

test('errors, redirected sign-in pages, and cross-origin detail URLs never look successful', async () => {
    for (const options of [{reject: true}, {ok: false}, {redirected: true},
        {data: {ok: false}}, {analysisUrl: 'https://other.test/analysis'}]) {
        const ui = await mount([proposal('x')], options);
        assert.equal(ui.summary.textContent, '取得失敗');
        assert.equal(ui.status.hidden, false);
        assert.equal(ui.rows.length, 0);
    }
});

test('inactive vehicles do not fetch analysis or trigger work', async () => {
    const ui = await mount([proposal('x')], {inactive: true});
    assert.equal(ui.requests.length, 0);
    assert.equal(ui.summary.textContent, '確認不可');
});

const walk = el => [el, ...el.children.flatMap(walk)];

test('missing and malformed priorities never manufacture labels or modify saved proposals', async () => {
    const values = [undefined, null, '', '未評価', 'unknown', ' 高 ', 0, false, ['高'], {label: '高'}, '__proto__', 'constructor'];
    for (const value of values) {
        const item = proposal('invalid');
        if (value === undefined) delete item.priority;
        else item.priority = value;
        const recommendations = [item, proposal('low', '低'), proposal('high', '高'), proposal('medium', '中')];
        const original = JSON.stringify(recommendations);
        const first = await mount(recommendations), second = await mount(recommendations);
        for (const ui of [first, second]) {
            assert.deepEqual(ui.rows.map(row => row.dataset.proposalId), ['high', 'medium', 'low', 'invalid']);
            assert.deepEqual(walk(ui.list).filter(el => el.className === 'ko-priority').map(el => el.textContent), ['高', '中', '低']);
            const invalid = ui.rows[3];
            assert.equal(invalid.dataset.priorityDataState, 'invalid');
            assert.equal(walk(invalid).some(el => el.attributes['aria-label']?.startsWith('対応優先度：')), false);
            assert.equal(walk(invalid).filter(el => el.className === 'ko-proposal-data-state').length, 1);
            assert.equal(invalid.children.at(-1).href, 'https://example.test/vehicle/karte/7/analysis#proposal=invalid');
            assert.doesNotMatch(walk(ui.list).map(el => el.textContent).join('\n'), /未評価/);
            assert.equal(ui.requests.length, 1);
            assert.equal(ui.requests[0].init.method, undefined);
        }
        assert.equal(JSON.stringify(recommendations), original);
    }
});

test('invalid data keeps proposal identity, feedback filtering, count and five-row limit', async () => {
    const recommendations = [proposal('first', null), proposal('second', ''), proposal('third', 'unknown'),
        proposal('fourth', null), proposal('fifth', null), proposal('sixth', null),
        proposal('done', null, {feedback: {revision: 'current', status: 'completed'}}),
        proposal('record', null, {category: '記録確認'})];
    const original = JSON.stringify(recommendations), ui = await mount(recommendations);
    assert.equal(ui.summary.textContent, '6件');
    assert.deepEqual(ui.rows.map(row => row.dataset.proposalId), ['first', 'second', 'third', 'fourth', 'fifth']);
    assert.equal(ui.list.children.at(-1).children[0].textContent, '残り1件を分析で確認 →');
    assert.equal(walk(ui.list).some(el => el.className === 'ko-priority'), false);
    assert.equal(JSON.stringify(recommendations), original);
});

test('data-state copy spans the missing badge column at every viewport and assets are versioned', () => {
    const css = fs.readFileSync(path.join(__dirname, '../static/css/vehicle_karte_overview.css'), 'utf8');
    assert.match(css, /\.ko-proposal\[data-priority-data-state="invalid"\] \.ko-proposal-copy\s*\{\s*grid-column:1 \/ 3;/);
    const template = fs.readFileSync(path.join(__dirname, '../templates/vehicle_karte.html'), 'utf8');
    assert.match(template, /css\/vehicle_karte_overview\.css', v='20261110-priority-data-state-1'/);
    assert.match(template, /js\/vehicle_karte_overview\.js', v='20261110-priority-data-state-1'/);
});
