const test = require('node:test');
const assert = require('node:assert/strict');
const {candidates} = require('../static/js/first_use_guide.js');

const masterEndpoints = ['driver_master','office_master','vehicle_master','vehicle_type_master',
    'license_type_master','delivery_place_master','checklist_master','patrol_content_type_master','manual_master'];
const purposeSelector = '.master-unified-tabs .master-unified-tab.is-current[data-guide-text]';
const addSelector = '.master-top-toolbar .entry-add-icon, .page-header .entry-add-icon, .master-list-actions .entry-add-icon, .vehicle-workflow-tabs .entry-add-icon';
const orderSelector = '.master-order-handle:not([disabled])';
const editSelector='a.btn-edit';
const purpose = {dataset:{guideText:'現在の画面で扱う情報の説明。'}};

test('all nine masters keep a contextual purpose with no write or record actions', () => {
    for (const endpoint of masterEndpoints) {
        const outcome=candidates(endpoint,selector=>selector===purposeSelector ? purpose : null);
        assert.deepEqual(outcome.map(x=>x.title),['このマスタでできること'],endpoint);
        assert.equal(outcome[0].text,purpose.dataset.guideText,endpoint);
        assert.deepEqual(candidates(endpoint,()=>null),[],endpoint);
        assert.deepEqual(candidates(endpoint,selector=>selector===purposeSelector ? purpose : null,'demo'),[],endpoint);
    }
});
test('a populated page uses only controls actually available; no mutation or unapproved actions', () => {
    const matching = new Set([purposeSelector,addSelector,editSelector,orderSelector,'[data-guide-master-excel]']);
    const targetMap = new Map([...matching].map(key=>[key,key===purposeSelector ? purpose : {}]));
    for (const endpoint of masterEndpoints) {
        const titles = candidates(endpoint,selector=>targetMap.get(selector)).map(x=>x.title);
        assert(titles.includes('新しく登録する'));
        assert(titles.includes('登録内容を変更する'));
        assert.equal(titles.includes('Excelでまとめて登録する'), endpoint==='delivery_place_master');
        assert.equal(titles.includes('表示順を変える'), !['driver_master','vehicle_master'].includes(endpoint));
        assert(!titles.includes('削除前に対象を確認する'));
    }
});
test('master search copy matches the available field, and vehicle pending only retains valid steps', () => {
    const purposeOnly = selector=>selector===purposeSelector ? purpose : null;
    const usedFields = new Map([
        ['driver_master',['#driverFilterPanel input[name="keyword"]','ユーザーID・氏名']],
        ['vehicle_master',['#vehicle_search_plate_number','車番・車台番号']],
        ['checklist_master',['#checklistFilterPanel input[name="keyword"]','点検表名']],
    ]);
    for (const [endpoint,[selector,expected]] of usedFields) {
        const result=candidates(endpoint,s=>purposeOnly(s) || (s===selector ? {} : null));
        assert.equal(result[1].title,'一覧を検索する');
        assert(result[1].text.includes(expected));
    }
    const pending = candidates('vehicle_master',s=>purposeOnly(s) || (s===addSelector || s.endsWith('/invoice-reviews"]:not([aria-current])') ? {} : null));
    assert.deepEqual(pending.map(s=>s.title),['このマスタでできること','確認待ちの請求書を見る','新しく登録する']);
});
test('standard-only checklists show review without promising edits or deletions',()=>{
    const real = new Map([[purposeSelector,purpose],['[data-standard-checklist-preview]',{}],[orderSelector,{}]]);
    const outcome=candidates('checklist_master',selector=>real.get(selector));
    assert.deepEqual(outcome.map(x=>x.title),['このマスタでできること','標準点検表を確認する','表示順を変える']);
});
