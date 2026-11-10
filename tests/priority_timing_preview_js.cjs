const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const preview = require('../static/js/vehicle_priority_preview.js');

function element(tag = 'div') {
    return {tag, dataset: {}, children: [], attributes: {}, hidden: false, textContent: '',
        append(...children) { this.children.push(...children); },
        replaceChildren(...children) { this.children = children; },
        setAttribute(name, value) { this.attributes[name] = value; }};
}
const doc = {createElement: element};
const walk = el => [el, ...el.children.flatMap(walk)];
const texts = el => walk(el).map(e => e.textContent).join('\n');
const conditionsIn = el => walk(el).filter(e => e.className === 'priority-timing-preview');
const badgesIn = el => walk(el).filter(e => e.className === 'priority-preview-badge');
const check = data => preview.validateTiming(data, preview.validate(data).items);
function proposal(id) {
    return {proposal_id: id, proposal_revision: 'rev-1', target: 'synthetic part', priority: '高',
        current_state: '元の状態', action: '元の対応', feedback: {revision: 'rev-1', status: 'open'},
        priority_preview: {candidate_id: id, method: preview.METHOD, policy_status: 'trial', policy_version: 'trial-20261110',
            production_enabled: false, operation_decision: 'human_only', disclaimer: '運行可否は人が判断。',
            base_score: 20, effective_score: 20, label: '低', evidence_status: '根拠不足', missing_conditions: ['入力の最新性を確認要'],
            factors: ['impact', 'timing', 'state'].map((axis, i) => ({axis, points: [10, null, 10][i], source_ids: [], reference_ids: []})), applied_floors: []}};
}
function entry(id = 'a/#b', relation = 'all') {
    return {proposal_id: id, proposal_revision: 'rev-1', version: 'timing-condition-view-v1', mode: 'shadow', production_enabled: false,
        rule_key: 'synthetic-rule', relation, scope: {company_code: 'SYNTHETIC', vehicle_id: 1, target: 'synthetic part'},
        event_id: 'synthetic-event', as_of: '2026-03-01', snapshot_hash: 'a'.repeat(64), source_ids: ['knowledge:1', 'part:1', 'vehicle:1'],
        missing_conditions: relation === 'all' ? ['AND条件全体の接近・採点方法は未定義です。期限点を加算しません。', '月間隔の90％判定は未対応です。'] : ['月間隔の90％判定は未対応です。'],
        scoring_input_emitted: relation !== 'all', status: 'verified_condition_facts',
        condition_group: {relation, as_of: '2026-03-01', threshold_reached: relation !== 'all',
            calendar_threshold_on: relation === 'all' ? '2026-03-17' : '2026-02-28',
            calendar_threshold_basis: relation === 'all' ? 'all_calendar_conditions_latest' : relation === 'any' ? 'any_calendar_condition_earliest' : 'single_calendar_condition',
            source_quote: 'Synthetic source: 45日 AND 1暦月\n<script>alert("quoted text")</script>', scoring_input_emitted: relation !== 'all',
            note: '登録基準日の到達状態。実際の到達日や整備要否の推定ではありません。',
            conditions: [
                {metric: 'period_days', threshold: '45', unit: 'days', baseline_on: '2026-01-31', reference_on: '2026-03-01',
                    threshold_reached: false, due_on: '2026-03-17', elapsed_quantity: '29', remaining_quantity: '16', excess_quantity: '0', calendar_interval_days: 45, quantity_unit: 'days'},
                {metric: 'period_months', threshold: '1', unit: 'calendar_months', baseline_on: '2026-01-31', reference_on: '2026-03-01',
                    threshold_reached: true, due_on: '2026-02-28', elapsed_quantity: '29', remaining_quantity: '0', excess_quantity: '1', calendar_interval_days: 28, quantity_unit: 'days'}
            ]}};
}
function payload(entries = [entry()], items = [proposal('a/#b')]) {
    return {ok: true, has_result: true, is_current: true, status: 'completed',
        priority_preview: {status: 'available', mode: 'shadow', production_enabled: false, synthetic_only: true, as_of: '2026-03-01', message: '合成データ試算。保存版の最新性は未確認。'},
        analysis: {priority_preview_contract: preview.METHOD, priority_preview_production_enabled: false,
            recommendations: items, priority_preview_order: items.map(i => i.proposal_id).reverse()},
        priority_timing_conditions: {version: 'priority-timing-preview-v1', status: 'available', mode: 'shadow', production_enabled: false,
            synthetic_only: true, message: '登録された合成条件の事実表示です。', company_code: 'SYNTHETIC', vehicle_id: 1, as_of: '2026-03-01', entries}};
}
function singleMonth() {
    const result = entry('a/#b', 'single');
    result.condition_group.conditions.shift();
    return result;
}
function mixed(relation = 'all') {
    const result = entry('a/#b', relation), group = result.condition_group;
    group.conditions[0] = {metric: 'distance_km', threshold: '1000', unit: 'km', baseline_on: '2026-01-31', reference_on: '2026-02-28',
        threshold_reached: false, due_on: null, elapsed_quantity: '900', remaining_quantity: '100', excess_quantity: '0', calendar_interval_days: null, quantity_unit: 'km'};
    group.calendar_threshold_on = null;
    group.calendar_threshold_basis = null;
    return result;
}

test('separate factual AND block preserves original proposal scores, server order, revision and feedback', () => {
    const data = payload([entry()], [proposal('a/#b'), proposal('without-conditions')]), original = JSON.stringify(data);
    assert.equal(check(data).status, 'available');
    const tree = preview.render(doc, data), rendered = texts(tree);
    assert.equal(JSON.stringify(data), original);
    assert.deepEqual(walk(tree).filter(e => e.tag === 'article').map(e => e.dataset.proposalId), ['without-conditions', 'a/#b']);
    assert.equal(conditionsIn(tree).length, 1);
    assert.equal(walk(tree).find(e => e.tag === 'article').id, 'proposal=without-conditions');
    assert.ok(badgesIn(tree).every(b => b.textContent === '低 · 20点' && b.dataset.priority === '低'));
    for (const phrase of ['すべての条件（AND）', '原文条件', '条件値：45 日', '条件値：1 暦月', '起算日：2026-01-31',
        '記録基準日：2026-03-01', '経過量：29 日 / 残量：16 日', '条件の算出日：2026-03-17',
        '条件全体の暦上の成立日：2026-03-17', '最も遅い算出日', 'AND条件全体の接近・採点方法は未定義',
        '月間隔の90％判定は未対応', '点数・区分・並び順に連動していません', '点数への採用を意味しません']) assert.ok(rendered.includes(phrase), phrase);
    assert.doesNotMatch(rendered, /未評価|運行可能|安全確認済みです/);
    assert.equal(data.analysis.recommendations[0].priority_preview.factors[1].points, null);
});

test('OR, single, and mixed metrics stay explicit without inventing mixed group dates', () => {
    const orTree = preview.render(doc, payload([entry('a/#b', 'any')]));
    assert.match(texts(orTree), /いずれかの条件（OR）/);
    assert.match(texts(orTree), /条件全体の暦上の成立日：2026-02-28/);
    assert.match(texts(orTree), /最も早い算出日/);
    const singleTree = preview.render(doc, payload([singleMonth()]));
    assert.equal(conditionsIn(singleTree).length, 1);
    assert.match(texts(singleTree), /条件の関係：単独条件/);
    for (const relation of ['all', 'any']) {
        const data = payload([mixed(relation)]), tree = preview.render(doc, data);
        assert.equal(check(data).status, 'available');
        assert.match(texts(tree), /条件値：1000 km/);
        assert.match(texts(tree), /記録基準日：2026-02-28/);
        assert.match(texts(tree), /経過量：900 km \/ 残量：100 km/);
        assert.match(texts(tree), /条件全体の暦上の成立日は算出していません/);
        assert.doesNotMatch(texts(tree), /条件全体の暦上の成立日：/);
    }
});

test('original multiline long quote is textContent only, with wrapping and no interactive HTML', () => {
    const data = payload(), quote = '  <img src=x onerror=alert(1)>\n<script>document.write("unsafe")</script>\n' + '長い原文'.repeat(1000);
    data.priority_timing_conditions.entries[0].condition_group.source_quote = quote;
    const tree = preview.render(doc, data), quoted = walk(tree).find(e => e.className === 'priority-timing-source-quote');
    assert.equal(quoted.textContent, quote);
    assert.equal(quoted.children.length, 0);
    assert.equal(walk(tree).some(e => ['script', 'img', 'button', 'input', 'form', 'progress', 'meter'].includes(e.tag)), false);
    assert.equal(walk(tree).some(e => Object.hasOwn(e, 'innerHTML')), false);
    const css = fs.readFileSync(require.resolve('../static/css/vehicle_priority_preview.css'), 'utf8');
    assert.match(css, /\.priority-timing-source-quote\s*\{[^}]*white-space:\s*pre-wrap;[^}]*overflow-wrap:\s*anywhere/);
    assert.match(css, /\.priority-timing-preview\s*\{[^}]*min-width:\s*0/);
    assert.match(css, /\.priority-preview\s*\{[^}]*overflow-wrap:\s*anywhere/);
});

test('legacy, absent, and empty timing responses add no condition block or fourth priority', () => {
    const legacy = payload(); delete legacy.priority_timing_conditions;
    const absent = payload(); Object.assign(absent.priority_timing_conditions, {status: 'absent', entries: []});
    for (const data of [legacy, absent, payload([]), payload([], [])]) {
        const tree = preview.render(doc, data);
        assert.equal(conditionsIn(tree).length, 0);
        assert.equal(walk(tree).some(e => e.dataset.conditionStatus), false);
        assert.equal(badgesIn(tree).length, data.analysis.recommendations.length);
        assert.doesNotMatch(texts(tree), /未評価/);
    }
});

test('calculation unavailable shows specific missing conditions separately from valid scores', () => {
    const data = payload(), e = data.priority_timing_conditions.entries[0];
    Object.assign(e, {status: 'calculation_unavailable', condition_group: null, scoring_input_emitted: false,
        missing_conditions: ['全条件の期限計算・起算・適用条件を確認要']});
    assert.equal(check(data).status, 'available');
    const tree = preview.render(doc, data);
    assert.equal(conditionsIn(tree)[0].dataset.conditionStatus, 'calculation_unavailable');
    assert.match(texts(tree), /条件データの状態：計算内容を確認できません/);
    assert.match(texts(tree), /全条件の期限計算・起算・適用条件を確認要/);
    assert.equal(badgesIn(tree)[0].textContent, '低 · 20点');
    assert.doesNotMatch(texts(tree), /条件値：|原文条件|未評価/);
});

test('malformed envelope, binding, revisions, dates, units, arithmetic and flags withhold conditions, not valid scores', () => {
    const changes = [
        d => delete d.priority_timing_conditions.version,
        d => d.priority_timing_conditions.version = 'future',
        d => d.priority_timing_conditions = null,
        d => d.priority_timing_conditions.status = 'unknown',
        d => d.priority_timing_conditions.status = 'absent',
        d => d.priority_timing_conditions.status = 'blocked',
        d => d.priority_timing_conditions.mode = 'production',
        d => d.priority_timing_conditions.production_enabled = true,
        d => delete d.priority_timing_conditions.synthetic_only,
        d => d.priority_timing_conditions.synthetic_only = 'true',
        d => d.priority_timing_conditions.entries = {},
        d => d.priority_timing_conditions.entries.push(d.priority_timing_conditions.entries[0]),
        d => d.priority_timing_conditions.entries = [null],
        d => d.priority_timing_conditions.entries.push(entry('unknown')),
        d => d.priority_timing_conditions.company_code = 'OTHER',
        d => d.priority_timing_conditions.vehicle_id = 2,
        d => d.priority_timing_conditions.vehicle_id = '1',
        d => d.priority_timing_conditions.as_of = '2026-03-02',
        d => delete d.priority_preview.as_of,
        d => d.analysis.recommendations[0].proposal_revision = 'new-revision',
        d => d.analysis.recommendations[0].target = 'different target',
    ];
    const entryChanges = [
        e => e.version = 'future', e => e.proposal_revision = '', e => e.mode = 'production',
        e => e.production_enabled = true, e => delete e.production_enabled, e => e.scope = null,
        e => e.scope.company_code = 'OTHER', e => e.scope.vehicle_id = 2, e => e.scope.target = 'different target',
        e => e.as_of = '2026-02-29', e => e.event_id = '', e => e.rule_key = ' ', e => e.snapshot_hash = 'bad-hash',
        e => e.source_ids = [], e => e.source_ids = ['duplicate', 'duplicate'], e => e.missing_conditions = [],
        e => e.missing_conditions = [null], e => e.status = 'unknown', e => e.condition_group = null,
        e => e.relation = 'AND', e => e.scoring_input_emitted = true,
        e => e.condition_group.scoring_input_emitted = true, e => e.condition_group.relation = 'any',
        e => e.condition_group.as_of = '2026-03-02', e => e.condition_group.source_quote = '',
        e => delete e.condition_group.note, e => e.condition_group.threshold_reached = true,
        e => e.condition_group.calendar_threshold_on = '2026-02-28',
        e => e.condition_group.calendar_threshold_basis = 'any_calendar_condition_earliest',
        e => e.condition_group.conditions.pop(), e => e.condition_group.conditions = [],
        e => e.condition_group.conditions[1] = e.condition_group.conditions[0],
    ];
    const conditionChanges = [
        c => c.metric = 'engine_hours', c => c.unit = 'calendar_months', c => c.quantity_unit = 'km',
        c => c.threshold = 45, c => c.threshold = 'NaN', c => c.threshold = 'Infinity', c => c.threshold = '-1',
        c => c.threshold = '0', c => c.threshold = '1000000000001', c => c.threshold = '0.0000001',
        c => c.threshold = '45.1', c => c.threshold = '45 trailing', c => c.threshold = '1e999',
        c => c.baseline_on = '2026-1-31', c => c.baseline_on = '2026-02-30', c => c.baseline_on = '0000-01-01',
        c => c.baseline_on = '2026-03-02', c => c.reference_on = '2026-03-02', c => c.reference_on = '2026-02-28',
        c => c.due_on = '2026-03-16', c => c.due_on = null, c => c.threshold_reached = 'false', c => c.threshold_reached = true,
        c => c.elapsed_quantity = '30', c => c.remaining_quantity = '15', c => c.excess_quantity = '1',
        c => c.calendar_interval_days = '45', c => c.calendar_interval_days = 44, c => delete c.remaining_quantity,
    ];
    changes.push(...entryChanges.map(fn => d => fn(d.priority_timing_conditions.entries[0])),
        ...conditionChanges.map(fn => d => fn(d.priority_timing_conditions.entries[0].condition_group.conditions[0])));
    for (const [index, mutate] of changes.entries()) {
        const data = payload(); mutate(data);
        assert.equal(preview.validate(data).available, true, `score contract ${index}`);
        assert.equal(check(data).status, 'blocked', `timing contract ${index}`);
        const tree = preview.render(doc, data);
        assert.equal(conditionsIn(tree).length, 0, `condition block ${index}`);
        assert.equal(badgesIn(tree)[0].textContent, '低 · 20点', `score badge ${index}`);
        assert.match(texts(tree), /条件データの状態：表示不可/);
        assert.doesNotMatch(texts(tree), /未評価|Synthetic source/);
    }
});

test('malformed unavailable status, mixed inferred dates, and month arithmetic cannot look verified', () => {
    const invalids = [];
    for (const patch of [{condition_group: null}, {status: 'calculation_unavailable'},
        {status: 'calculation_unavailable', condition_group: null, missing_conditions: []},
        {status: 'calculation_unavailable', condition_group: null, scoring_input_emitted: true}]) {
        const value = entry(); Object.assign(value, patch); invalids.push(value);
    }
    const invented = mixed(); invented.condition_group.calendar_threshold_on = '2026-02-28'; invalids.push(invented);
    for (const key of ['due_on', 'calendar_interval_days', 'threshold_reached', 'remaining_quantity', 'excess_quantity']) {
        const value = mixed(), c = value.condition_group.conditions[0];
        c[key] = {due_on: '2026-02-28', calendar_interval_days: 28, threshold_reached: true, remaining_quantity: '101', excess_quantity: '1'}[key];
        invalids.push(value);
    }
    const month = singleMonth(); month.condition_group.conditions[0].threshold = '2'; invalids.push(month);
    const falseRatio = singleMonth(); falseRatio.condition_group.conditions[0].quantity_unit = 'calendar_months'; invalids.push(falseRatio);
    for (const value of invalids) assert.equal(check(payload([value])).status, 'blocked');
});

test('month-end, leap year and direct month addition validate calendar dates without month ratios', () => {
    for (const [baseline, due, threshold, interval] of [
        ['2026-01-31', '2026-03-31', '2', 59], ['2024-01-31', '2024-02-29', '1', 29],
        ['2025-01-31', '2025-02-28', '1', 28], ['2024-02-29', '2025-02-28', '12', 365],
        ['0001-01-31', '0001-02-28', '1', 28],
    ]) {
        const value = singleMonth(), group = value.condition_group, c = group.conditions[0], data = payload([value]);
        value.as_of = group.as_of = group.calendar_threshold_on = data.priority_timing_conditions.as_of = data.priority_preview.as_of = due;
        Object.assign(c, {baseline_on: baseline, reference_on: due, due_on: due, threshold, calendar_interval_days: interval,
            elapsed_quantity: String(interval), remaining_quantity: '0', excess_quantity: '0'});
        assert.equal(check(data).status, 'available', `${baseline} + ${threshold} months`);
        const tree = preview.render(doc, data);
        assert.match(texts(tree), new RegExp(`条件値：${threshold} 暦月`));
        assert.match(texts(tree), new RegExp(`経過量：${interval} 日`));
        assert.equal(walk(tree).some(e => ['progress', 'meter'].includes(e.tag)), false);
    }
});

test('decimal condition arithmetic stays exact and never supplies a scoring formula', () => {
    for (const [threshold, elapsed, remaining] of [['0.1', '0.09', '0.01'], ['1E+3', '9E+2', '1E+2'],
        ['0.000002', '0.000001', '0.000001'], ['1000000000000', '999999999999.999999', '0.000001']]) {
        const value = mixed(), c = value.condition_group.conditions[0];
        Object.assign(c, {threshold, elapsed_quantity: elapsed, remaining_quantity: remaining});
        const data = payload([value]);
        assert.equal(check(data).status, 'available', threshold);
        assert.equal(badgesIn(preview.render(doc, data))[0].textContent, '低 · 20点');
        c.remaining_quantity = '0';
        assert.equal(check(data).status, 'blocked', `${threshold} arithmetic mismatch`);
    }
});

test('all reached AND remains factual only and single distance has no inferred calendar crossing', () => {
    const all = mixed(), c = all.condition_group.conditions[0];
    Object.assign(c, {elapsed_quantity: '1000', remaining_quantity: '0', threshold_reached: true});
    all.condition_group.threshold_reached = true;
    const data = payload([all]), tree = preview.render(doc, data);
    assert.equal(check(data).status, 'available');
    assert.match(texts(tree), /条件全体の到達状態：到達済み/);
    assert.match(texts(tree), /期限点を加算しません/);
    assert.doesNotMatch(texts(tree), /条件全体の暦上の成立日：/);
    assert.equal(badgesIn(tree)[0].textContent, '低 · 20点');
    assert.equal(all.scoring_input_emitted, false);

    const single = mixed('any');
    single.relation = single.condition_group.relation = 'single';
    single.condition_group.conditions.pop();
    single.condition_group.threshold_reached = false;
    single.missing_conditions = [];
    assert.equal(check(payload([single])).status, 'available');
    const singleTree = preview.render(doc, payload([single]));
    assert.match(texts(singleTree), /条件の関係：単独条件/);
    assert.doesNotMatch(texts(singleTree), /条件全体の暦上の成立日：/);
});

test('repeated loader removes stale conditions for changed revision, blocked, absent, or failed response', async () => {
    const context = {URL, URLSearchParams, AbortSignal, setTimeout() {}, clearTimeout() {}, module: {exports: {}}};
    vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/vehicle_priority_preview.js'), 'utf8'), context);
    const status = element(), results = element(), requests = [], events = new Map();
    status.dataset.url = '/result';
    let data = payload(), failed = false;
    const localDoc = {...doc, addEventListener(name, fn) { events.set(name, fn); }, getElementById() { return null; }};
    const controller = context.module.exports.mountAnalysis({doc: localDoc, status, results,
        location: {origin: 'https://example.test', hash: ''},
        fetcher: async (url, init) => { requests.push({url, init}); if (failed) throw Error('synthetic failure'); return {ok: true, json: async () => data}; }});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(conditionsIn(results).length, 1);
    await controller.refresh();
    assert.equal(conditionsIn(results).length, 1);
    assert.equal(badgesIn(results).length, 1);
    data = payload(); data.analysis.recommendations[0].proposal_revision = 'new-revision';
    await controller.refresh();
    assert.equal(conditionsIn(results).length, 0);
    assert.equal(badgesIn(results).length, 1);
    data = payload(); await controller.refresh();
    data = payload(); Object.assign(data.priority_timing_conditions, {status: 'blocked', entries: [], message: '<img>条件の対応が古いため表示不可'});
    await controller.refresh();
    assert.equal(conditionsIn(results).length, 0);
    assert.match(texts(results), /<img>条件の対応が古い/);
    assert.equal(badgesIn(results).length, 1);
    data = payload(); await controller.refresh();
    delete data.priority_timing_conditions; await controller.refresh();
    assert.equal(conditionsIn(results).length, 0);
    assert.equal(badgesIn(results).length, 1);
    data = payload(); data.is_current = false; await controller.refresh();
    assert.match(texts(results), /前回入力/);
    assert.equal(conditionsIn(results).length, 1); // Saved-snapshot warning is distinct from an invalid condition binding.
    failed = true; await controller.refresh();
    assert.equal(conditionsIn(results).length, 0);
    assert.equal(badgesIn(results).length, 0);
    assert.ok(requests.every(r => r.init.method === 'GET' && !r.init.body));
    assert.equal(results.attributes['aria-busy'], 'false');
});

test('invalid score response still clears every old card, including otherwise valid conditions', () => {
    const data = payload(), host = element();
    host.replaceChildren(preview.render(doc, data));
    data.priority_preview.status = 'blocked';
    host.replaceChildren(preview.render(doc, data));
    assert.equal(conditionsIn(host).length, 0);
    assert.equal(badgesIn(host).length, 0);
});
