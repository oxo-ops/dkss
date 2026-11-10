const test = require('node:test');
const assert = require('node:assert/strict');
const preview = require('../static/js/vehicle_priority_preview.js');
const fs = require('node:fs');
const vm = require('node:vm');
function element(tag = 'div') {
    return {tag, dataset: {}, children: [], attributes: {}, hidden: false, textContent: '',
        append(...children) { this.children.push(...children); },
        replaceChildren(...children) { this.children = children; },
        setAttribute(name, value) { this.attributes[name] = value; }};
}
function proposal(id, points = [10, 10, 10]) {
    const total = points.reduce((sum, n) => sum + (n ?? 0), 0);
    return {proposal_id: id, proposal_revision: 'rev1', priority: '高', target: `<script>${id}</script>`,
        current_state: '元の状態', action: '元の対応', feedback: {revision: 'rev1', status: 'accepted'},
        priority_preview: {candidate_id: id, method: preview.METHOD, policy_status: 'trial', policy_version: 'trial-20261110',
            production_enabled: false, operation_decision: 'human_only', disclaimer: '試行値。運行可否ではありません。',
            base_score: total, effective_score: total, label: total >= 60 ? '高' : total >= 25 ? '中' : '低',
            evidence_status: points.includes(null) ? '根拠不足' : '根拠あり',
            missing_conditions: points.includes(null) ? ['入力の最新性と根拠を確認要'] : [],
            factors: ['impact', 'timing', 'state'].map((axis, i) => ({axis, points: points[i], source_ids: [], reference_ids: []})), applied_floors: []}};
}
function payload(items = [proposal('a/#b')]) {
    return {ok: true, has_result: true, is_current: true, status: 'completed',
        priority_preview: {status: 'available', mode: 'shadow', production_enabled: false, synthetic_only: true, message: '非本番の合成データ試算です。保存版の最新性は未確認です。'},
        analysis: {priority_preview_contract: preview.METHOD, priority_preview_production_enabled: false,
            recommendations: items, priority_preview_order: items.map(i => i.proposal_id).reverse()}};
}
const walk = el => [el, ...el.children.flatMap(walk)];
const texts = el => walk(el).map(e => e.textContent).join('\n');
test('complete contract uses original objects and server order without mutation', () => {
    const data = payload([proposal('one'), proposal('two')]), original = JSON.stringify(data);
    const result = preview.validate(data);
    assert.equal(result.available, true);
    assert.equal(result.items[0], data.analysis.recommendations[1]);
    assert.equal(JSON.stringify(data), original);
    assert.equal(result.items[0].priority, '高');
    assert.equal(result.items[0].proposal_revision, 'rev1');
    assert.equal(result.items[0].feedback.status, 'accepted');
});
test('null factors are displayed separately, never a fourth priority or false zero evidence', () => {
    const data = payload([proposal('missing', [null, null, null])]);
    const tree = preview.render({createElement: element}, data);
    assert.equal(preview.validate(data).items[0].priority_preview.label, '低');
    assert.match(texts(tree), /根拠確認が必要（加点なし）/);
    assert.match(texts(tree), /根拠不足/);
    assert.match(texts(tree), /入力の最新性/);
    assert.doesNotMatch(texts(tree), /未評価/);
});
test('partial, duplicate, invalid or foreign contracts are blocked instead of inventing scores', () => {
    const mutations = [
        d => d.analysis.recommendations[0].priority_preview.factors.pop(),
        d => d.analysis.recommendations[0].priority_preview.factors[1].axis = 'impact',
        d => d.analysis.recommendations[0].priority_preview.factors[0].points = -1,
        d => d.analysis.recommendations[0].priority_preview.factors[0].points = '10',
        d => d.analysis.recommendations[0].priority_preview.effective_score = NaN,
        d => d.analysis.recommendations[0].priority_preview.effective_score = 101,
        d => d.analysis.recommendations[0].priority_preview.base_score = 0,
        d => d.analysis.recommendations[0].priority_preview.label = '未評価',
        d => d.analysis.recommendations[0].priority_preview.label = '低',
        d => d.analysis.recommendations[0].priority_preview.candidate_id = 'other',
        d => d.analysis.recommendations[0].priority_preview.policy_version = 'future',
        d => d.analysis.recommendations[0].priority_preview.applied_floors = [{code: 'unknown', minimum: 60, source_ids: ['x'], reference_ids: []}],
        d => d.analysis.priority_preview_order = ['unknown'],
        d => d.analysis.priority_preview_order = ['a/#b', 'a/#b'],
        d => d.analysis.recommendations[0].proposal_revision = '',
        d => d.priority_preview.production_enabled = true,
        d => d.priority_preview.status = 'unknown',
        d => d.analysis.priority_preview_contract = 'old',
        d => delete d.priority_preview,
    ];
    for (const mutate of mutations) {
        const data = payload(); mutate(data);
        assert.equal(preview.validate(data).available, false);
        const tree = preview.render({createElement: element}, data);
        assert.equal(walk(tree).filter(e => e.className === 'priority-preview-badge').length, 0);
        assert.doesNotMatch(texts(tree), /未評価/);
    }
});
test('renderer is read-only, text-safe, repeatable, anchored and explicit about stale input', () => {
    const data = payload(); data.is_current = false; data.status = 'unknown';
    const doc = {createElement: element};
    const tree = preview.render(doc, data), again = preview.render(doc, data);
    assert.equal(texts(tree), texts(again));
    assert.match(texts(tree), /前回入力/);
    assert.match(texts(tree), /元の状態/); assert.match(texts(tree), /元の対応/);
    assert.match(texts(tree), /<script>a\/#b<\/script>/);
    assert.equal(walk(tree).some(e => ['button', 'input', 'form', 'script'].includes(e.tag)), false);
    assert.equal(walk(tree).find(e => e.tag === 'article').id, 'proposal=a%2F%23b');
});
test('blocked payload clears prior score cards on repeated render', () => {
    const host = element(), doc = {createElement: element};
    host.replaceChildren(preview.render(doc, payload()));
    const blocked = payload(); blocked.priority_preview.status = 'blocked'; blocked.priority_preview.message = '紐付けが古いため表示不可';
    host.replaceChildren(preview.render(doc, blocked));
    assert.match(texts(host), /紐付けが古い/);
    assert.equal(walk(host).some(e => e.className === 'priority-preview-badge'), false);
});
test('URLs explicitly opt into preview and reject off-origin destinations', () => {
    const location = {origin: 'https://example.test', href: 'https://example.test/view', search: '?priority_preview=1'};
    assert.equal(preview.enabled(location), true);
    assert.equal(preview.enabled({search: '?priority_preview=0'}), false);
    assert.equal(preview.url('/result?a=2', location), 'https://example.test/result?a=2&priority_preview=1');
    assert.throws(() => preview.url('https://evil.test', location));
});
async function overview(data, options = {}) {
    const panel = element(), list = element(), status = element(), summary = element(), requests = [];
    panel.dataset = {resultUrl: '/analysis/result', analysisUrl: '/analysis'};
    panel.querySelector = selector => selector === '[data-ko-ai-status]' ? status : list;
    const context = {URL, URLSearchParams, AbortSignal,
        window: {VehiclePriorityPreview: preview, location: {origin: 'https://example.test', search: '?priority_preview=1'}},
        document: {getElementById: id => id === 'ko-ai' ? panel : null,
            querySelector: s => s === '[data-ko-summary-count]' ? summary : null, createElement: element},
        fetch: async (url, init) => { requests.push({url, init}); return {ok: true, redirected: false, json: async () => data}; }};
    vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/vehicle_karte_overview.js'), 'utf8'), context);
    await new Promise(resolve => setImmediate(resolve));
    return {panel, list, status, summary, requests};
}
test('overview uses shared server scores/order, max five, revision filtering and preview detail links', async () => {
    const items = Array.from({length: 9}, (_, i) => proposal(String(i)));
    items[0].category = '記録確認'; items[1].feedback.status = 'completed'; items[2].feedback.status = 'dismissed';
    items[3].feedback = {revision: 'old', status: 'completed'};
    const data = payload(items), original = JSON.stringify(data), ui = await overview(data);
    const rows = ui.list.children.filter(e => e.className === 'ko-proposal');
    assert.ok(rows.every(row => row.dataset.priorityPreview === 'true'));
    assert.equal(ui.summary.textContent, '6件'); assert.equal(rows.length, 5);
    assert.deepEqual(rows.map(e => e.dataset.proposalId), ['8', '7', '6', '5', '4']);
    assert.equal(rows[0].children[0].textContent, '中 · 30点');
    assert.match(rows[0].children[2].href, /priority_preview=1#proposal=8/);
    assert.match(ui.list.children.at(-1).children[0].href, /priority_preview=1/);
    assert.match(ui.requests[0].url, /priority_preview=1/);
    assert.match(ui.status.textContent, /本番未承認/); assert.equal(ui.status.hidden, false);
    assert.equal(JSON.stringify(data), original);
});
test('overview blocked/malformed/current-unknown payloads never silently look current', async () => {
    for (const status of ['blocked', 'unknown']) {
        const data = payload(); data.priority_preview.status = status;
        const ui = await overview(data);
        assert.equal(ui.summary.textContent, '試行表示不可');
        assert.equal(ui.list.children.length, 0); assert.equal(ui.panel.dataset.current, 'false');
    }
    const data = payload(); data.status = 'unknown'; data.is_current = false;
    const ui = await overview(data);
    assert.equal(ui.panel.dataset.current, 'false'); assert.match(ui.status.textContent, /前回の提案/);
});
test('analysis preview branch is GET-only and removes old scores after later failed response', async () => {
    const doc = {createElement: element, addEventListener() {}, getElementById() {return null;}}, status = element(), results = element();
    status.dataset.url = '/result';
    let data = payload(), reject = false;
    const calls = [];
    // Inject timers into the helper VM so this read-only loader cannot leave a polling timer alive in tests.
    const context = {URL, URLSearchParams, AbortSignal, setTimeout() {}, clearTimeout() {}, module: {exports: {}}};
    vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/vehicle_priority_preview.js'), 'utf8'), context);
    const controller = context.module.exports.mountAnalysis({doc, status, results,
        location: {origin: 'https://example.test', hash: ''},
        fetcher: async (url, init) => { calls.push({url, init}); if (reject) throw Error(); return {ok: true, json: async () => data}; }});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(walk(results).some(e => e.className === 'priority-preview-badge'), true);
    data = payload(); data.priority_preview.status = 'blocked'; await controller.refresh();
    assert.equal(walk(results).some(e => e.className === 'priority-preview-badge'), false);
    data = payload(); await controller.refresh(); reject = true; await controller.refresh();
    assert.equal(walk(results).some(e => e.className === 'priority-preview-badge'), false);
    assert.ok(calls.every(c => c.init.method === 'GET' && !c.init.body));
});


test('synthetic-only marker is mandatory and visible with saved-snapshot freshness', async () => {
    for (const value of [undefined, false, 'true', 1]) {
        const data = payload();
        if (value === undefined) delete data.priority_preview.synthetic_only;
        else data.priority_preview.synthetic_only = value;
        assert.equal(preview.validate(data).available, false);
        assert.equal(walk(preview.render({createElement: element}, data)).some(e => e.className === 'priority-preview-badge'), false);
        const ui = await overview(data);
        assert.equal(ui.summary.textContent, '試行表示不可');
        assert.equal(ui.list.children.length, 0);
    }
    const data = payload();
    assert.match(texts(preview.render({createElement: element}, data)), /非本番の合成データ試算です。保存版の最新性は未確認です。/);
    assert.match((await overview(data)).status.textContent, /合成データ/);
});

test('floor reasons are Japanese explanations, never raw internal codes', () => {
    const data = payload(), p = data.analysis.recommendations[0].priority_preview;
    const codes = ['operation_instruction_active', 'manufacturer_immediate_condition', 'safety_issue_open', 'required_safety_check_not_done', 'verified_legal_deadline_due'];
    p.applied_floors = codes.map(code => ({code, minimum: code === 'safety_issue_open' || code === 'required_safety_check_not_done' ? 25 : 60, source_ids: ['record-1'], reference_ids: []}));
    p.effective_score = 60; p.label = '高';
    assert.equal(preview.validate(data).available, true);
    const rendered = texts(preview.render({createElement: element}, data));
    for (const code of codes) assert.equal(rendered.includes(code), false);
    assert.match(rendered, /有効な運行停止・制限指示/);
    assert.match(rendered, /メーカーの即時対応条件/);
    assert.match(rendered, /未解消の安全上の指摘/);
    assert.match(rendered, /必要な安全点検が未実施/);
    assert.match(rendered, /確認済みの法定期限に到達/);
});

test('trial score column uses content width without changing normal priority columns', () => {
    const css = fs.readFileSync(require.resolve('../static/css/vehicle_priority_preview.css'), 'utf8');
    assert.match(css, /#vehicle-karte-overview #ko-ai \.ko-proposal\[data-priority-preview="true"\]\s*\{\s*grid-template-columns:\s*max-content minmax\(0, 1fr\) auto;/);
});
