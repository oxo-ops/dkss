const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/vehicle_checklist_results.js', 'utf8');
const block = source.slice(source.lastIndexOf('    if (vehicleFilterForm) {'), source.lastIndexOf('\n});'));
function navigate(year, month, day, targetName, mode='day_list') {
    const controls = Object.fromEntries(['year','month','active_day'].map(name =>
        [name, {addEventListener(type, cb) {this.cb = cb;}}]));
    let destination;
    const values = {year, month, active_day: day, vehicle_record_id:'42'};
    vm.runInNewContext(block, {
        vehicleFilterForm: {querySelector(selector) {return controls[selector.match(/name="([^"]+)"/)[1]];}},
        vehicleId: {value:'42'}, displayMode: mode,
        FormData: class {constructor() {return Object.entries(values);}}, URLSearchParams,
        window: {location:{pathname:'/vehicle/checklists/3', assign(url){destination=url;}}},
        showCommonError(){throw new Error('unexpected missing vehicle');}
    });
    controls[targetName].cb({target:controls[targetName]});
    return new URL(destination, 'https://example.invalid').searchParams;
}
test('month switch removes impossible prior day and retains company-scoped vehicle context', () => {
    const params=navigate('2026','02','31','month');
    assert.equal(params.has('active_day'),false);
    assert.equal(params.get('vehicle_record_id'),'42');
    assert.equal(params.get('month'),'02');
});
test('year switch removes leap day only when necessary', () => {
    assert.equal(navigate('2027','02','29','year').has('active_day'),false);
    assert.equal(navigate('2028','02','29','year').get('active_day'),'29');
});
test('valid month switch retains exact selected day', () => {
    assert.equal(navigate('2026','04','23','month').get('active_day'),'23');
});
test('direct invalid day is left for explicit server correction, never substituted', () => {
    assert.equal(navigate('2026','02','31','active_day').get('active_day'),'31');
});
test('monthly/yearly templates keep their existing semantics', () => {
    assert.equal(navigate('2026','02','2026','year','year_list').get('active_day'),'2026');
});
