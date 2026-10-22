(() => {
    'use strict';
    const panel = document.querySelector('#inspection-plan-panel');
    if (!panel || panel.dataset.initialized) return;
    panel.dataset.initialized = 'true';
    const review = document.querySelector('#inspection-plan-review');
    const planner = document.querySelector('[data-inspection-planner]');
    const form = panel.querySelector('#inspection-plan-form');
    const executionForm = panel.querySelector('#inspection-execution-form');
    let executionInitial = '', editorSequence = 0;
    const labels = { '3month': '3か月点検', '12month': '12か月点検', vehicle_inspection: '車検' };
    const sourceLabels = { manual: '手動で登録した予定', document: '点検簿の次回記載から反映', calculated: '周期から自動算出した候補' };
    let current = null, vehicle = null, initial = '', pending = null, data = null, selected = new Set();
    const args = planner ? JSON.parse(planner.dataset.planArgs || '{}') : {};
    const filters = planner?.querySelector('[data-plan-filters]');
    const node = (tag, text, cls) => {
        const el = document.createElement(tag);
        if (text !== undefined) el.textContent = text;
        if (cls) el.className = cls;
        return el;
    };
    function error(root, selector, message = '') {
        const el = root.querySelector(selector);
        el.textContent = message; el.hidden = !message;
    }
    async function api(path = '', body) {
        const response = await fetch('/api/vehicle/inspection-plans' + path, {
            method: body ? 'POST' : 'GET', credentials: 'same-origin',
            headers: body ? { 'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' } : {},
            body: body ? JSON.stringify(body) : undefined
        });
        const text = await response.text();
        let value; try { value = JSON.parse(text); } catch (_) { value = null; }
        if (!response.ok || !value) {
            const parsed = new DOMParser().parseFromString(text, 'text/html');
            throw new Error(value?.message || parsed.querySelector('p')?.textContent || '保存できませんでした。内容を保持しています。最新の予定を確認してください。');
        }
        return value;
    }
    function annualURL(scope = 'office') {
        const url = new URL('/vehicle/inspection-plans', location.origin);
        url.searchParams.set('scope', scope);
        if (vehicle?.id) url.searchParams.set('vehicle_id', vehicle.id);
        if (current?.kind) url.searchParams.set('kind', current.kind);
        return url;
    }
    function dirty() { return (initial && new URLSearchParams(new FormData(form)).toString() !== initial) || (!executionForm.hidden && executionInitial !== new URLSearchParams(new FormData(executionForm)).toString()); }
    function closePanel() {
        if (dirty() && !window.confirm('変更を保存せずに閉じますか？')) return;
        panel.close();
    }
    function openEditor(row, v, editable = true) {
        current = { ...row }; vehicle = v;
        panel.querySelector('[data-plan-kind-label]').textContent = labels[row.kind];
        panel.querySelector('[data-plan-vehicle-label]').textContent = v.number;
        panel.querySelector('[data-plan-office-label]').textContent = v.office || '営業所未設定';
        ['planned_month', 'reservation_date', 'factory', 'note'].forEach(key => {
            form.elements[key].value = row[key] || ''; form.elements[key].disabled = !editable;
        });
        panel.querySelector('[data-plan-source]').textContent = (sourceLabels[row.source] || '') + (row.document_date ? ' ／ 原本記載日 ' + row.document_date : '');
        panel.querySelector('[data-plan-save]').hidden = !editable;
        panel.querySelector('[data-plan-cancel-record]').hidden = !editable || !row.id || row.status === 'cancelled';
        const link = panel.querySelector('[data-plan-annual]');
        link.href = annualURL(v.office ? 'office' : 'company');
        panel.querySelector('[data-plan-scope="office"]').disabled = !v.office;
        initial = new URLSearchParams(new FormData(form)).toString();
        error(panel, '[data-plan-error]');
        executionForm.reset(); executionForm.hidden = true; form.hidden = false;
        const toggle = panel.querySelector('[data-execution-toggle]');
        toggle.hidden = !editable || !['3month', '12month'].includes(row.kind) || row.status === 'completed';
        const targets = executionForm.elements.target_plan;
        targets.replaceChildren(); const empty = node('option', '過去の実施（対象予定なし）'); empty.value = ''; targets.append(empty);
        if (row.id && row.status === 'planned') {
            const option = node('option', row.planned_month + ' の予定を実施済みにする'); option.value = row.id; targets.append(option);
            const currentMonth = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit' }).format(new Date());
            if (row.planned_month <= currentMonth) targets.value = String(row.id);
        }
        executionForm.elements.factory.value = row.factory || '';
        const sequence = ++editorSequence;
        panel.querySelector('[data-plan-current-status]').textContent = row.status === 'completed' ? '実施済み' + (row.performed_date ? '：' + row.performed_date : '') : row.reservation_date ? '表示中の予定：予約済み・実施未確認' : row.planned_month ? '表示中の予定：実施未確認' : '予定未設定';
        panel.querySelector('[data-plan-last]').textContent = '実施記録を確認中…';
        panel.querySelector('[data-plan-record-link]').hidden = true;
        api('?detail=1&vehicle_id=' + encodeURIComponent(v.id)).then(value => {
            if (sequence !== editorSequence) return;
            const actual = value.latest[row.kind];
            panel.querySelector('[data-plan-last]').textContent = actual ? '直近の実施：' + actual.performed_date + ' ／ 書類' + actual.document_status + (actual.factory ? ' ／ ' + actual.factory : '') : '実施記録なし（実施したかは未確認）';
            const link = panel.querySelector('[data-plan-record-link]'); link.hidden = !actual?.record_url;
            if (actual?.record_url) link.href = actual.record_url;
        }).catch(e => { if (sequence === editorSequence) panel.querySelector('[data-plan-last]').textContent = e.message; });
        panel.showModal();
    }
    document.querySelectorAll('[data-inspection-plan-open]').forEach(button => button.addEventListener('click', async () => {
        button.disabled = true;
        try {
            const value = await api('?detail=1&vehicle_id=' + encodeURIComponent(button.dataset.vehicleId));
            const kind = button.dataset.inspectionPlanOpen;
            openEditor(value.plans[kind] || { id: null, version: 0, vehicle_record_id: value.vehicle.id, kind, planned_month: '', source: 'manual' }, value.vehicle, value.can_edit);
        } catch (e) { window.alert(e.message); }
        finally { button.disabled = false; }
    }));
    panel.querySelectorAll('[data-plan-close]').forEach(b => b.addEventListener('click', closePanel));
    panel.addEventListener('cancel', e => { e.preventDefault(); closePanel(); });
    panel.querySelectorAll('[data-plan-scope]').forEach(b => b.addEventListener('click', () => {
        if (b.dataset.planScope === 'vehicle') return;
        if (dirty() && !window.confirm('未保存の変更があります。保存せずに年間計画へ移りますか？')) return;
        location.href = annualURL(b.dataset.planScope);
    }));
    async function showReview(changes) {
        const value = await api('/preview', { changes });
        pending = { changes, token: value.token };
        review.dataset.savePath = '/save';
        review.querySelector('#inspection-plan-review-title').textContent = '予定の変更を確認';
        review.querySelector('[data-plan-review-count]').textContent = value.changes.length + '件の変更。確定済みの予約変更もここで確認してください。';
        const tbody = review.querySelector('[data-plan-review-rows]'); tbody.replaceChildren();
        const description = p => p ? (p.status === 'cancelled' ? '取消' : p.planned_month) + '\n予約日 ' + (p.reservation_date || '未定') + '\n' + (p.factory || '実施先未定') + (p.note ? '\n' + p.note : '') : '未登録';
        value.changes.forEach(change => {
            const tr = node('tr');
            [change.number + '\n' + labels[change.after.kind], description(change.before), description(change.after)].forEach(text => tr.append(node('td', text)));
            tbody.append(tr);
        });
        error(review, '[data-review-error]'); review.showModal();
    }
    form.addEventListener('submit', async e => {
        e.preventDefault();
        if (!form.reportValidity()) return;
        const button = form.querySelector('[data-plan-save]'); button.disabled = true;
        try {
            const values = Object.fromEntries(new FormData(form));
            await showReview([{ ...current, ...values, status: 'planned', period_key: current.period_key || values.planned_month }]);
        } catch (e) { error(panel, '[data-plan-error]', e.message); }
        finally { button.disabled = false; }
    });
    panel.querySelector('[data-plan-cancel-record]').addEventListener('click', async () => {
        try { await showReview([{ ...current, status: 'cancelled' }]); }
        catch (e) { error(panel, '[data-plan-error]', e.message); }
    });
    review.querySelectorAll('[data-review-close]').forEach(b => b.addEventListener('click', () => review.close()));
    review.querySelector('[data-review-save]').addEventListener('click', async e => {
        const button = e.currentTarget; button.disabled = true;
        try {
            await api(review.dataset.savePath || '/save', pending);
            review.close(); panel.close(); initial = '';
            if (planner) { await load(); } else location.reload();
        } catch (e) { error(review, '[data-review-error]', e.message); }
        finally { button.disabled = false; }
    });
    panel.querySelector('[data-execution-toggle]').addEventListener('click', () => {
        executionForm.hidden = false; form.hidden = true;
        panel.querySelector('[data-execution-toggle]').hidden = true;
        executionInitial = new URLSearchParams(new FormData(executionForm)).toString();
        error(panel, '[data-execution-error]'); executionForm.elements.performed_date.focus();
    });
    panel.querySelector('[data-execution-back]').addEventListener('click', () => {
        if (executionInitial !== new URLSearchParams(new FormData(executionForm)).toString() && !window.confirm('実施登録の入力を保存せずに戻りますか？')) return;
        executionForm.hidden = true; form.hidden = false; panel.querySelector('[data-execution-toggle]').hidden = false;
    });
    executionForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!executionForm.reportValidity()) return;
        const button = executionForm.querySelector('[type=submit]'); button.disabled = true;
        try {
            const values = Object.fromEntries(new FormData(executionForm));
            const payload = { ...values, vehicle_record_id: vehicle.id, kind: current.kind,
                plan_id: values.target_plan || null, version: values.target_plan ? current.version : 0 };
            const response = await api('/execution/preview', payload), result = response.result, actual = result.execution;
            pending = { ...payload, token: response.token }; review.dataset.savePath = '/execution/save';
            review.querySelector('#inspection-plan-review-title').textContent = '点検の実施登録を確認';
            review.querySelector('[data-plan-review-count]').textContent = '実施済み・書類未受領として登録します。' + (result.warning || '');
            const tbody = review.querySelector('[data-plan-review-rows]'); tbody.replaceChildren();
            const tr = node('tr');
            [result.number + '\n' + labels[actual.kind], result.before ? result.before.planned_month + ' の予定（実施未確認）' : '実施記録なし',
                '実施済み ' + actual.performed_date + '\n' + (actual.factory || '実施先未登録') + '\n次回予定月 ' + actual.next_month + (actual.next_source === 'calculated' ? '（周期から算出）' : '') + (result.skip_next_for_newer_record ? '\n新しい実績があるため次回予定は更新しません。' : '') + (result.existing_next.length ? '\n既存の予定・予約は保持します。' : '')].forEach(text => tr.append(node('td', text)));
            tbody.append(tr); error(review, '[data-review-error]'); review.showModal();
        } catch (e) { error(panel, '[data-execution-error]', e.message); }
        finally { button.disabled = false; }
    });
    if (!planner) return;
    if (planner.querySelector('[data-alert-check-status]')) {
        api('/alerts/status').then(value => {
            planner.querySelector('[data-alert-check-status]').textContent = value.last_checked_at ? '／確認済み' : '／未確認';
            const missing = value.report.no_recipient || 0, invalid = value.report.invalid || 0;
            const warning = planner.querySelector('[data-alert-recipient-warning]');
            warning.textContent = (missing ? '通知先がない予定 ' + missing + '件。車両と管理者の所属営業所を確認してください。' : '') + (invalid ? ' 予定月・予約日の要確認 ' + invalid + '件。' : '');
            warning.hidden = !warning.textContent;
        }).catch(() => { planner.querySelector('[data-alert-check-status]').textContent = '／確認できませんでした'; });
    }
    const now = new Date();
    args.scope = args.scope || 'company';
    args.year = args.year || (now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1);
    ['scope', 'year', 'kind'].forEach(key => { filters.elements[key].value = args[key] || ''; });
    function visiblePlans() {
        const kind = filters.elements.kind.value;
        return data.plans.filter(p => !kind || kind === p.kind);
    }
    function selectionChanged() {
        planner.querySelector('[data-plan-selected]').textContent = selected.size + '台選択';
    }
    function draw() {
        const months = Array.from({ length: 12 }, (_, i) => {
            const year = Number(data.year) + (i >= 9 ? 1 : 0), mon = (i + 3) % 12 + 1;
            return `${year}-${String(mon).padStart(2, '0')}`;
        });
        const bulkMonth = planner.querySelector('[data-plan-bulk-month]');
        const old = bulkMonth.value; bulkMonth.replaceChildren();
        months.forEach(m => { const o = node('option', m); o.value = m; bulkMonth.append(o); });
        if (months.includes(old)) bulkMonth.value = old;
        const head = planner.querySelector('[data-plan-grid-head]'); head.replaceChildren();
        const hr = node('tr'), selectHead = node('th'), all = node('input'); all.type = 'checkbox'; all.setAttribute('aria-label', '表示中の車両を全選択'); all.checked = !!data.vehicles.length && data.vehicles.every(v => selected.has(v.id));
        all.addEventListener('change', () => { selected = all.checked ? new Set(data.vehicles.map(v => v.id)) : new Set(); draw(); });
        selectHead.append(all); hr.append(selectHead, node('th', '車両・営業所')); months.forEach(m => hr.append(node('th', Number(m.slice(5)) + '月'))); head.append(hr);
        const body = planner.querySelector('[data-plan-grid-body]'); body.replaceChildren();
        const rows = visiblePlans();
        for (const v of data.vehicles) {
            const tr = node('tr'), tdSelect = node('td'), cb = node('input'); cb.type = 'checkbox'; cb.checked = selected.has(v.id); cb.setAttribute('aria-label', v.number + 'を選択');
            cb.addEventListener('change', () => { cb.checked ? selected.add(v.id) : selected.delete(v.id); selectionChanged(); }); tdSelect.append(cb);
            const name = node('td'), link = node('a', v.number); link.href = '/vehicle/karte/' + v.id + '/inspections'; name.append(link, node('small', v.office)); tr.append(tdSelect, name);
            months.forEach(mon => {
                const td = node('td'); td.append(node('span', mon, 'ip-mobile-month'));
                rows.filter(p => p.vehicle_record_id === v.id && (p.display_month || p.planned_month) === mon).forEach(p => {
                    const prefix = p.status === 'completed' ? '✓' : p.status === 'cancelled' ? '取消' : p.status === 'candidate' ? '＋' : p.reservation_date ? '●' : '◯';
                    const b = node('button', prefix + ' ' + labels[p.kind] + (p.performed_date ? '\n' + p.performed_date.slice(5) + ' 実施' : p.reservation_date ? '\n' + p.reservation_date.slice(5) : ''), 'ip-chip'); b.type = 'button'; b.dataset.status = p.status; b.dataset.reserved = String(!!p.reservation_date);
                    b.title = sourceLabels[p.source] || '';
                    b.addEventListener('click', () => openEditor(p, v, data.can_edit && ['planned', 'candidate', 'cancelled'].includes(p.status)));
                    td.append(b);
                }); tr.append(td);
            }); body.append(tr);
        }
        planner.querySelector('[data-plan-bulk]').hidden = !data.can_edit;
        const missing = data.missing.filter(p => !filters.elements.kind.value || p.kind === filters.elements.kind.value);
        planner.querySelector('[data-plan-missing-count]').textContent = '基準未設定 ' + missing.length + '件';
        const list = planner.querySelector('[data-plan-missing]'); list.replaceChildren();
        missing.forEach(p => { const v = data.vehicles.find(v => v.id === p.vehicle_record_id); list.append(node('li', v.number + ' ／ ' + labels[p.kind] + '：' + p.reason)); });
        planner.querySelector('[data-plan-status]').textContent = data.vehicles.length + '台 ／ 登録済み ' + rows.filter(p => p.status !== 'candidate').length + '件 ／ 未登録の候補 ' + rows.filter(p => p.status === 'candidate').length + '件';
        selectionChanged();
    }
    let loadNumber = 0;
    async function load() {
        const loadId = ++loadNumber;
        error(planner, '[data-planner-error]');
        const params = new URLSearchParams({ ...args, ...Object.fromEntries(new FormData(filters)) });
        const value = await api('?' + params);
        if (loadId !== loadNumber) return;
        data = value;
        // Populate office choices from a company-wide read, never from arbitrary input.
        if (filters.elements.office.options.length === 1) {
            const company = args.scope === 'company' && !args.office ? value : await api('?scope=company&year=' + data.year);
            [...new Set(company.vehicles.map(v => v.office).filter(o => o !== '営業所未設定'))].sort().forEach(o => { const option = node('option', o); option.value = o; filters.elements.office.append(option); });
            filters.elements.office.value = args.office || (filters.elements.scope.value === 'office' ? value.vehicles[0]?.office || '' : '');
        }
        selected = new Set([...selected].filter(id => data.vehicles.some(v => v.id === id)));
        draw();
    }
    filters.addEventListener('submit', async e => {
        e.preventDefault();
        try { await load(); } catch (e) { error(planner, '[data-planner-error]', e.message); }
    });
    filters.elements.scope.addEventListener('change', () => {
        if (filters.elements.scope.value !== 'company' && !args.vehicle_id) {
            filters.elements.scope.value = 'company';
            error(planner, '[data-planner-error]', '車両カルテから開くと、この車両・同じ営業所を選べます。営業所で絞る場合は営業所欄を使用してください。');
        }
    });
    planner.querySelector('[data-plan-generate]').addEventListener('click', async () => {
        try {
            const rows = visiblePlans().filter(p => selected.has(p.vehicle_record_id) && p.status === 'candidate');
            if (!rows.length) throw new Error('予定を作成する車両を選択してください。未登録の候補だけを保存します。');
            await showReview(rows.map(p => ({ ...p, status: 'planned' })));
        } catch (e) { error(planner, '[data-planner-error]', e.message); }
    });
    planner.querySelector('[data-plan-bulk-apply]').addEventListener('click', async () => {
        try {
            const mon = planner.querySelector('[data-plan-bulk-month]').value;
            const reservation = planner.querySelector('[data-plan-bulk-date]').value;
            const factory = planner.querySelector('[data-plan-bulk-factory]').value.trim();
            if (!reservation && !factory) throw new Error('予約日か実施先を入力してください。空欄は現在の値を維持します。');
            const rows = visiblePlans().filter(p => selected.has(p.vehicle_record_id) && p.planned_month === mon && ['candidate', 'planned'].includes(p.status));
            if (!rows.length) throw new Error('対象の車両と月を選択してください。');
            await showReview(rows.map(p => ({ ...p, reservation_date: reservation || p.reservation_date, factory: factory || p.factory, status: 'planned' })));
        } catch (e) { error(planner, '[data-planner-error]', e.message); }
    });
    load().catch(e => error(planner, '[data-planner-error]', e.message));
})();
