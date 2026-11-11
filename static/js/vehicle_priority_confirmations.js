(() => {
    const root = document.querySelector('[data-priority-confirmations]');
    if (!root) return;
    const find = selector => root.querySelector(selector);
    const message = find('[data-confirmation-message]');
    const kind = find('[data-confirmation-kind]');
    const form = find('[data-confirmation-selection]');
    const previewForm = find('[data-confirmation-preview]');
    let selection = {}, previewToken = null, replacing = null, loaded = false, busy = false, sequence = 0;
    const node = (tag, text) => { const element = document.createElement(tag); element.textContent = text || ''; return element; };
    function link(parent, url, text) {
        try {
            const target = new URL(url, location.origin);
            const internal = target.origin === location.origin && target.pathname.startsWith('/vehicle/');
            const publicLegal = target.origin === 'https://www.mlit.go.jp'
                && target.pathname === '/jidosha/content/001740686.pdf' && !target.search
                && (!target.hash || /^#page=\d+$/.test(target.hash));
            if ((!internal && !publicLegal) || target.username || target.password) return;
            const a = node('a', text); a.href = target.href; a.target = '_blank'; a.rel = 'noopener'; parent.append(a);
        } catch (_) {}
    }
    async function request(url, body) {
        const options = {credentials:'same-origin', headers:{Accept:'application/json'}};
        if (body) Object.assign(options, {method:'POST', headers:{...options.headers,
            'Content-Type':'application/json', 'X-CSRFToken':document.querySelector('meta[name=csrf-token]')?.content || ''}, body:JSON.stringify(body)});
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.message || '処理できませんでした。最新の画面を確認してください。');
        return data;
    }
    function setBusy(value) {
        busy = value;
        root.setAttribute('aria-busy', String(value));
        root.querySelectorAll('button, select, input').forEach(element => { element.disabled = value; });
    }
    function clearPreview() { previewToken = null; previewForm.hidden = true; }
    function sources(target, entries) {
        target.replaceChildren();
        for (const value of entries || []) {
            const article = node('article'); article.append(node('h5', value.label), node('p', value.text));
            if (value.url) link(article, value.url, '元記録・原本を開く');
            target.append(article);
        }
    }
    async function load() {
        const run = ++sequence;
        clearPreview();
        try {
            const querySelection = kind.value === 'manufacturer_immediate'
                ? {observation_input_ref:selection.observation_input_ref, manufacturer_rule:selection.manufacturer_rule}
                : selection;
            const query = new URLSearchParams({kind:kind.value, selection:JSON.stringify(querySelection)});
            const data = await request(root.dataset.priorityConfirmations + '?' + query);
            if (run !== sequence) return;
            loaded = true; message.textContent = data.message;
            find('[data-confirmation-controls]').hidden = !data.can_confirm;
            const fields = find('[data-confirmation-fields]'); fields.replaceChildren();
            for (const field of data.form.fields || []) {
                const label = node('label', field.label), select = node('select');
                select.name = field.key; select.required = true;
                const blank = node('option', '選択してください'); blank.value = ''; select.append(blank);
                for (const option of field.options || []) {
                    const opt = node('option', option.label); opt.value = option.value; select.append(opt);
                }
                select.value = selection[field.key] || '';
                select.addEventListener('change', () => {
                    selection[field.key] = select.value; clearPreview();
                    if (kind.value === 'manufacturer_immediate') {
                        if (field.key === 'observation_input_ref') { delete selection.manufacturer_rule; delete selection.condition_quote; delete selection.action_quote; }
                        if (field.key === 'manufacturer_rule') { delete selection.condition_quote; delete selection.action_quote; }
                        if (['observation_input_ref','manufacturer_rule'].includes(field.key)) load();
                    }
                });
                label.append(select); fields.append(label);
            }
            sources(find('[data-confirmation-originals]'), data.form.originals);
            find('[data-confirmation-missing]').textContent = (data.form.missing_conditions || []).join('。');
            find('[data-confirmation-replacing]').hidden = replacing === null;
            const history = find('[data-confirmation-history]'); history.replaceChildren();
            for (const entry of data.history) {
                const article = node('article');
                const state = {active:'確認済み', held:'元記録・適用条件を再確認', withdrawn:'取消済み', resolved:'元観測の解消を確認'}[entry.status] || '元記録を確認';
                article.append(node('strong', (data.kinds[entry.kind] || '') + '：' + entry.subject),
                    node('p', `${state} ／ ${entry.confirmed_at} ／ ${entry.actor.name}`));
                if (entry.cancel_token) {
                    const cancel = node('button', 'この根拠確認を取り消す'); cancel.type = 'button'; cancel.className = 'btn btn-outline';
                    cancel.addEventListener('click', async () => {
                        if (busy || !window.confirm('この根拠確認だけを取り消します。元の点検・整備・運行判断は変わりません。続けますか？')) return;
                        setBusy(true);
                        try { await request(root.dataset.saveUrl, {token:entry.cancel_token}); replacing = null; await load(); }
                        catch (error) { message.textContent = error.message; } finally { setBusy(false); }
                    });
                    const correct = node('button', '元記録を選び直して訂正'); correct.type = 'button'; correct.className = 'btn btn-outline';
                    correct.addEventListener('click', () => { replacing = entry.event_id; kind.value = entry.kind; selection = {...entry.selection};
                        if (entry.kind === 'manufacturer_immediate') {
                            selection.manufacturer_rule = JSON.stringify([selection.knowledge_source_id, selection.rule_key]);
                            delete selection.knowledge_source_id; delete selection.rule_key;
                        }
                        load(); form.scrollIntoView({block:'nearest'});
                    });
                    article.append(cancel, correct);
                }
                history.append(article);
            }
            if (!data.history.length) history.append(node('p', '根拠確認の登録はありません。未登録を低優先度や安全確認済みとは扱いません。'));
            setBusy(busy);
        } catch (error) { message.textContent = error.message; }
    }
    kind.addEventListener('change', () => { selection = {}; replacing = null; load(); });
    form.addEventListener('submit', async event => {
        event.preventDefault(); if (busy) return; clearPreview();
        selection = Object.fromEntries(new FormData(form).entries());
        setBusy(true);
        try {
            const data = await request(root.dataset.previewUrl, {kind:kind.value, selection, replace_event_id:replacing});
            previewToken = data.token;
            find('[data-confirmation-subject]').textContent = data.preview.subject;
            sources(find('[data-confirmation-sources]'), data.preview.display_sources);
            const statements = find('[data-confirmation-statements]'); statements.replaceChildren(node('legend', '元記録を見て確認した内容だけ選択してください'));
            for (const value of data.preview.statements) {
                const label = node('label'), input = node('input'); input.type = 'checkbox'; input.name = 'statement'; input.value = value.key; input.required = true;
                label.append(input, node('span', value.label)); statements.append(label);
            }
            previewForm.hidden = false; message.textContent = data.message;
        } catch (error) { message.textContent = error.message; } finally { setBusy(false); }
    });
    previewForm.addEventListener('submit', async event => {
        event.preventDefault(); if (busy || !previewToken) return;
        const statements = new FormData(previewForm).getAll('statement');
        setBusy(true);
        try {
            const data = await request(root.dataset.saveUrl, {token:previewToken, statements});
            replacing = null; selection = {}; await load(); message.textContent = data.message;
        } catch (error) { clearPreview(); message.textContent = error.message; } finally { setBusy(false); }
    });
    root.addEventListener('keydown', event => { if (event.key === 'Escape' && !event.defaultPrevented) { root.open = false; root.querySelector('summary').focus(); } });
    root.addEventListener('toggle', () => { if (root.open && !loaded) load(); });
    if (location.hash === '#priority-evidence') root.open = true;
})();
