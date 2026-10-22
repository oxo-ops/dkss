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
        const items = data.result.recommendations || [];
        status.textContent = `AI提案 ${items.length}件` + (items.length ? ' · 優先度の高い順' : ' · 追加提案なし');
        if (order) order.style.display = items.length ? '' : 'none';
        items.forEach((item, index) => {
            const card = node('article', '', 'pf-proposal');
            const heading = node('div', '', 'card-title-row');
            heading.append(node('strong', `${index + 1}. ${item.title}`), node('span', `優先度 ${item.priority}`, 'pf-priority pf-priority-' + ({'高':'high','中':'medium','低':'low'}[item.priority] || 'low')));
            card.append(heading);
            [['対象',item.target],['現在の記録',item.current_state],['確認時期',item.timing],['提案',item.action],['理由',item.reason]].forEach(([label,value]) => {
                const row = node('p'); row.append(node('b',label+'：'),document.createTextNode(value || ''));card.append(row);
            });
            const detail = node('details');detail.append(node('summary','確認方法・根拠'));
            const steps = node('ol');(item.confirmation_steps || []).forEach(text => steps.append(node('li',text)));detail.append(steps);
            detail.append(node('p',item.confirmation_branch),node('p',item.uncertainty,'help-text'),node('p',item.basis_type,'help-text'));
            (item.source_ids || []).forEach(id => { const source = (data.evidence || {})[id];if (!source) return;const a=node('a',source.label);a.href=source.url;a.target='_blank';a.rel='noopener';detail.append(a,document.createTextNode('　')); });
            card.append(detail);list.append(card);
        });
        if (data.updated_at) status.append(document.createTextNode(' ／ ' + data.updated_at.slice(0,16).replace('T',' ') + '確認'));
    }
    async function check(start = false, explicitRetry = false) {
        if (pending || stopped) return;
        pending = true;if (retry) retry.hidden = true;
        try {
            let response = await fetch(root.dataset.periodicSuggestions, {credentials:'same-origin',headers:{'Accept':'application/json'}});
            if (!response.ok) throw new Error('request_failed');
            let data = await response.json();
            if ((data.status === 'missing' || explicitRetry) && canGenerate && start) {
                response = await fetch(root.dataset.periodicSuggestions,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]')?.content || ''},body:JSON.stringify({retry:explicitRetry})});
                if (!response.ok) throw new Error('request_failed');
                data = await response.json();
            }
            if (data.status === 'completed') { render(data); return; }
            if (data.status === 'running') {
                status.textContent = 'AIが日常点検・定期点検と整備履歴を照合しています…';
                if (Date.now()-started > 900000) throw new Error('long_running');
                timer=setTimeout(()=>check(true),2000);return;
            }
            if (data.status === 'missing' && !canGenerate) {status.textContent='AI提案はまだありません。管理者がこの画面を開くと作成します。';return;}
            if (data.status === 'missing') {timer=setTimeout(()=>check(true),2000);return;}
            status.textContent = data.error === 'not_configured' ? 'AIの接続設定を確認してください。提案はまだ生成されていません。' : 'AI提案を取得できませんでした。時間をおいて再確認してください。';
            if (retry) retry.hidden=false;
        } catch (_) {status.textContent='AI提案の確認を続けられませんでした。時間をおいて再確認してください。';if(retry)retry.hidden=false;}
        finally { pending=false; }
    }
    if (retry) retry.addEventListener('click',()=>{clearTimeout(timer);started=Date.now();check(true,true);});
    window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);});
    window.addEventListener('pageshow',event=>{if(event.persisted){stopped=false;started=Date.now();check(true);}});
    started=Date.now();check(true);
})();
