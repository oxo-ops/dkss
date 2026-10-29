/* Invoice amounts are source scoped; the maintenance total is derived, not entered twice. */
(() => {
    const root = document.getElementById('invoice-cost-read');
    if (!root) return;
    const context = JSON.parse(root.dataset.context);
    const select = document.getElementById('invoice_source');
    const fields = ['labor_cost', 'parts_cost', 'other_cost', 'tax_amount', 'total_cost'];
    const inputs = Object.fromEntries(fields.map(f => [f, document.getElementById(f)]));
    const before = document.getElementById('invoice-read-before');
    const after = document.getElementById('invoice-read-after');
    const original = document.getElementById('invoice-read-original');
    const evidence = document.getElementById('invoice-evidence');
    const cents = (value, signed = false) => {
        if (value === null || value === '') return null;
        const raw = String(value).replace(/,/g, '');
        if (!(signed ? /^-?\d+(?:\.\d{1,2})?$/ : /^\d+(?:\.\d{1,2})?$/).test(raw)) throw new Error('invalid amount');
        const negative = raw.startsWith('-');
        const [n, d = ''] = (negative ? raw.slice(1) : raw).split('.');
        return (negative ? -1n : 1n) * (BigInt(n) * 100n + BigInt(d.padEnd(2, '0')));
    };
    const money = value => {
        if (value === null) return '不明';
        const absolute = value < 0n ? -value : value;
        return (value < 0n ? '-' : '') + String(absolute / 100n) + '.' + String(absolute % 100n).padStart(2, '0');
    };
    const selected = () => context.sources.find(s => s.key === select.value);
    function showTotal() {
        const source = selected();
        if (!source) { after.textContent = ''; return; }
        try {
            const values = context.sources.map(s => cents(s === source ? inputs.total_cost.value : s.values.total_cost, s.key === 'manual'));
            const total = values.some(v => v === null) ? null : values.reduce((a, b) => a + b, 0n);
            after.textContent = '訂正前：' + (source.values.total_cost ?? '不明') + ' 円 → 訂正後：' +
                (inputs.total_cost.value || '不明') + ' 円 ／ 保存後の整備合計：' + money(total) + ' 円';
        } catch (_) { after.textContent = '金額の入力内容を確認してください。'; }
    }
    let initial = true;
    function changeSource() {
        const source = selected();
        for (const f of fields) {
            inputs[f].value = (initial && context.submitted ? context.submitted[f] :
                (source ? source.values[f] : context.actual[f])) ?? '';
            inputs[f].readOnly = !source;
        }
        original.hidden = !source?.reference;
        if (source?.reference) {
            const vehicle = document.querySelector('#maintenance_form').action.match(/karte\/(\d+)\//)?.[1];
            original.href = '/vehicle/karte/' + vehicle + '/documents/' +
                encodeURIComponent(source.reference.draft_id) + '/source';
        }
        before.textContent = source ? '対象：' + (source.reference?.filename ?? source.label) +
            ' ／ 保存済み読取値：' + (source.read_values.total_cost ?? '不明') +
            ' 円 ／ 現在の確認額：' + (source.values.total_cost ?? '不明') + ' 円' :
            '整備合計を直接上書きせず、訂正する請求書を選択してください。';
        if (evidence) { evidence.required = !!source; evidence.checked = initial && !!context.evidence_confirmed; }
        showTotal();
        initial = false;
    }
    if (context.selection) select.value = context.selection;
    else if (context.sources.length === 1 && !context.unresolved) select.value = context.sources[0].key;
    select.addEventListener('change', changeSource);
    for (const input of Object.values(inputs)) input.addEventListener('input', showTotal);
    changeSource();
})();
