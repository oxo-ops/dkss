(() => {
    const root = document.querySelector('[data-periodic-suggestions]');
    if (!root) return;
    const status = root.querySelector('[data-proposal-status]');
    const list = root.querySelector('[data-proposal-list]');
    const retry = root.querySelector('[data-proposal-retry]');
    const order = root.querySelector('[data-proposal-order]');
    const canGenerate = root.dataset.canGenerate === 'true';
    let timer, stopped = false, started = 0, pending = false;
    const node = (tag, text, cls) => {
        const el = document.createElement(tag); el.textContent = text || '';
        if (cls) el.className = cls;
        return el;
    };
    function render(data) {
        list.replaceChildren();
        const priority = window.VehiclePriorityPresentation;
        const savedItems = data.result.recommendations || [];
        const items = priority ? priority.ordered(savedItems, data.result) : savedItems;
        status.textContent = `AI提案 ${items.length}件` + (items.length ? ' · 確認・対応の優先度順' : ' · 追加提案なし');
        const summary = data.result.priority_summary;
        if (summary && summary.labels && summary.proposal_count === items.length) {
            const labels = ['高', '中', '低'];
            if (labels.every(label => Number.isInteger(summary.labels[label]) && summary.labels[label] >= 0)
                && Number.isInteger(summary.invalid_count) && summary.invalid_count >= 0
                && labels.reduce((sum, label) => sum + summary.labels[label], summary.invalid_count) === items.length) {
                status.append(document.createTextNode(' ／ ' + labels.map(label => `${label}${summary.labels[label]}件`).join('・')
                    + (summary.invalid_count ? ` ／ 保存データ確認${summary.invalid_count}件` : '')));
            }
        }
        if (order) order.style.display = items.length ? '' : 'none';
        items.forEach((item, index) => {
            const card = node('article', '', 'pf-proposal');
            const heading = node('div', '', 'card-title-row');
            heading.append(node('strong', `${index + 1}. ${item.title}`));
            if (priority) { const badge = priority.badge(document, item); if (badge) heading.append(badge); }
            else heading.append(node('span', '優先度の元データを確認してください', 'help-text'));
            card.append(heading);
            [['対象',item.target],['現在の記録',item.current_state],['確認時期',item.timing],['提案',item.action],['理由',item.reason]].forEach(([label,value]) => {
                const row = node('p'); row.append(node('b',label+'：'),document.createTextNode(value || ''));card.append(row);
            });
            const detail = node('details');detail.append(node('summary','確認方法・根拠'));
            const steps = node('ol');(item.confirmation_steps || []).forEach(text => steps.append(node('li',text)));detail.append(steps);
            detail.append(node('p',item.confirmation_branch),node('p',item.uncertainty,'help-text'),node('p',item.basis_type,'help-text'));
            (item.source_ids || []).forEach(id => { const source = (data.evidence || {})[id];if (!source || typeof source.url !== 'string' || !/^(\/[^/]|https?:\/\/)/.test(source.url)) return;const a=node('a',source.label);a.href=source.url;a.target='_blank';a.rel='noopener';detail.append(a,document.createTextNode('　')); });
            card.append(detail);
            if (priority) card.append(priority.details(document, item, data.evidence || {}, window.location.origin));
            list.append(card);
        });
        if (data.updated_at && data.is_current !== false) status.append(document.createTextNode(' ／ ' + data.updated_at.slice(0,16).replace('T',' ') + '確認'));
    }
    async function check(start = false, explicitRetry = false) {
        if (pending || stopped) return;
        pending = true;if (retry) retry.hidden = true;
        try {
            let response = await fetch(root.dataset.periodicSuggestions, {credentials:'same-origin',headers:{'Accept':'application/json'}});
            if (!response.ok) throw new Error('request_failed');
            let data = await response.json();
            const previous = data.result && Array.isArray(data.result.recommendations) ? data : null;
            if (previous && (data.status !== 'completed' || data.is_current === false)) render(previous);
            if ((data.status === 'missing' || explicitRetry) && canGenerate && start) {
                response = await fetch(root.dataset.periodicSuggestions,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]')?.content || ''},body:JSON.stringify({retry:explicitRetry})});
                if (!response.ok) throw new Error('request_failed');
                data = await response.json();
            }
            if (data.status === 'completed' && data.is_current !== false) { render(data); return; }
            if (data.result && Array.isArray(data.result.recommendations)) render(data);
            const savedNote = previous || data.result ? ' 前回の提案を保存版として表示しています。' : '';
            if (data.status === 'running') {
                status.textContent = 'AIが日常点検・定期点検と整備履歴を照合しています…' + savedNote;
                if (Date.now()-started > 900000) throw new Error('long_running');
                timer=setTimeout(()=>check(true),2000);return;
            }
            if (data.status === 'missing' && !canGenerate) {status.textContent = savedNote ? '分析の更新待ちです。' + savedNote : 'AI提案はまだありません。管理者がこの画面を開くと作成します。';return;}
            if (data.status === 'missing') {timer=setTimeout(()=>check(true),2000);return;}
            status.textContent = (data.error === 'not_configured' ? 'AIの接続設定を確認してください。今回の更新は完了していません。' : 'AI提案を更新できませんでした。時間をおいて再確認してください。') + savedNote;
            if (retry) retry.hidden=false;
        } catch (_) {status.textContent='AI提案の確認を続けられませんでした。時間をおいて再確認してください。';if(retry)retry.hidden=false;}
        finally { pending=false; }
    }
    if (retry) retry.addEventListener('click',()=>{clearTimeout(timer);started=Date.now();check(true,true);});
    window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);});
    window.addEventListener('pageshow',event=>{if(event.persisted){stopped=false;started=Date.now();check(true);}});
    started=Date.now();check(true);
})();
