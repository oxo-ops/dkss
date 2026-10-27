const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/vehicle_karte_selector.js'), 'utf8');

function mount(choices, onSelect) {
    function element(tag = 'div') {
        return {tag, dataset: {}, children: [], events: {}, hidden: false, value: '',
            textContent: '', setAttribute() {}, focus() { this.focused = true; },
            addEventListener(name, fn) { this.events[name] = fn; },
            replaceChildren() { this.children = []; },
            append(child) { this.children.push(...(child.tag === 'fragment' ? child.children : [child])); }};
    }
    const context = {window: {}, document: {getElementById: () => null,
        createElement: tag => element(tag), createDocumentFragment: () => element('fragment')}};
    vm.createContext(context);
    vm.runInContext(source, context);
    const input = element('input'), results = element(), status = element();
    context.window.DkssVehicleChoiceSearch.mount({input, results, status, choices, onSelect});
    return {input, results, status, search(value) {input.value = value; input.events.input({isComposing: false});}};
}

test('matching candidates display type as text and retain selection behavior', () => {
    let selected;
    const choice = {id: 7, number: '品川100あ1234', chassis_number: 'TYPE-7', type: '<img src=x onerror=alert(1)>'};
    const ui = mount([choice], row => { selected = row; });
    ui.search('１２３４');
    assert.equal(ui.results.children.length, 1);
    const link = ui.results.children[0];
    assert.equal(link.children[0].textContent, choice.number);
    assert.equal(link.children[1].tag, 'span');
    assert.equal(link.children[1].textContent, choice.type);
    assert.equal(link.children[1].children.length, 0);
    let prevented = false;
    link.events.click({preventDefault() { prevented = true; }});
    assert.ok(prevented);
    assert.equal(selected, choice);
    assert.equal(ui.input.value, choice.number);
    assert.equal(ui.results.hidden, true);
});

test('unknown type adds no empty label and chassis lookup still works', () => {
    const ui = mount([{id: 8, number: '車両8', chassis_number: 'ABC-123'}]);
    ui.search('abc 123');
    assert.equal(ui.results.children.length, 1);
    assert.equal(ui.results.children[0].children.length, 1);
});
