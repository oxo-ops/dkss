(() => {
    const root = document.querySelector('[data-periodic-suggestions]');
    if (!root) return;
    const status = root.querySelector('[data-proposal-status]');
    const list = root.querySelector('[data-proposal-list]');
    const retry = root.querySelector('[data-proposal-retry]');
    const order = root.querySelector('[data-proposal-order]');
    const canGenerate = root.dataset.canGenerate === 'true';
    const pollInterval = 2_000, pollLimit = 15 * 60_000;
    let active, hasSavedResult = false;
    const node = (tag, text, cls) => {
        const el = document.createElement(tag); el.textContent = text || '';
        if (cls) el.className = cls;
        return el;
    };
    function render(data) {
        hasSavedResult = true;
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
        if (priority?.includesPrevious(items)) status.append(document.createTextNode(' ／ 前回評価を含む'));
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
    const remaining = attempt => attempt.deadline - Date.now();
    function stop(attempt) {
        if (active !== attempt) return;
        active = undefined;
        clearTimeout(attempt.pollTimer);
        clearTimeout(attempt.deadlineTimer);
        attempt.controller.abort();
    }
    function showPollTimeout() {
        status.textContent = 'AI提案の確認を続けられませんでした。時間をおいて再確認してください。'
            + (hasSavedResult ? ' 前回の提案を保存版として表示しています。' : '');
        if (retry && canGenerate) retry.hidden = false;
    }
    function timeout(attempt) {
        if (active !== attempt) return;
        stop(attempt);
        showPollTimeout();
    }
    function isLive(attempt) {
        if (active !== attempt) return false;
        if (remaining(attempt) > 0) return true;
        timeout(attempt);
        return false;
    }
    function schedulePoll(attempt) {
        if (!isLive(attempt)) return;
        attempt.pollTimer = setTimeout(() => {
            attempt.pollTimer = undefined;
            check(attempt);
        }, Math.min(pollInterval, remaining(attempt)));
    }
    async function readProposal(attempt, options = {}) {
        if (!isLive(attempt)) return null;
        const response = await fetch(root.dataset.periodicSuggestions, {
            credentials: 'same-origin', signal: attempt.controller.signal, ...options,
        });
        if (!isLive(attempt)) return null;
        if (!response.ok) throw new Error('request_failed');
        const data = await response.json();
        return isLive(attempt) ? data : null;
    }
    async function check(attempt, explicitRetry = false) {
        if (!isLive(attempt)) return;
        try {
            let data = await readProposal(attempt, {headers:{'Accept':'application/json'}});
            if (!data || !isLive(attempt)) return;
            if (data.status === 'completed' && data.is_current !== false) { render(data); return; }
            if (data.result && Array.isArray(data.result.recommendations)) render(data);

            // A request aborted in this browser may already have started generation.
            // Read the server first and keep following any fresh run instead of restarting it.
            const expiredRun = data.status === 'running' && Date.now() - Date.parse(data.updated_at) >= pollLimit;
            if (canGenerate && (data.status === 'missing' || (explicitRetry && (data.status === 'error' || expiredRun)))) {
                data = await readProposal(attempt, {method:'POST',
                    headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]')?.content || ''},
                    body:JSON.stringify({retry:explicitRetry})});
                if (!data || !isLive(attempt)) return;
                if (data.status === 'completed' && data.is_current !== false) { render(data); return; }
                if (data.result && Array.isArray(data.result.recommendations)) render(data);
            }
            const savedNote = hasSavedResult ? ' 前回の提案を保存版として表示しています。' : '';
            if (data.status === 'running') {
                status.textContent = 'AIが日常点検・定期点検と整備履歴を照合しています…' + savedNote;
                schedulePoll(attempt);return;
            }
            if (data.status === 'missing' && !canGenerate) {status.textContent = savedNote ? '分析の更新待ちです。' + savedNote : 'AI提案はまだありません。管理者がこの画面を開くと作成します。';return;}
            if (data.status === 'missing') {schedulePoll(attempt);return;}
            status.textContent = (data.error === 'confirmation_limit' ? '確認済み根拠が一度に照合できる件数を超えています。候補を一部だけに絞らず、分析更新を保留しています。' : data.error === 'not_configured' ? 'AIの接続設定を確認してください。今回の更新は完了していません。' : 'AI提案を更新できませんでした。時間をおいて再確認してください。') + savedNote;
            if (retry && canGenerate) retry.hidden = false;
        } catch (_) {
            if (isLive(attempt)) showPollTimeout();
        } finally {
            if (attempt.pollTimer === undefined) stop(attempt);
        }
    }
    function begin(explicitRetry = false) {
        if (active) stop(active);
        const attempt = {deadline: Date.now() + pollLimit, controller: new AbortController()};
        active = attempt;
        if (retry) retry.hidden = true;
        attempt.deadlineTimer = setTimeout(() => timeout(attempt), pollLimit);
        check(attempt, explicitRetry);
    }
    if (retry && canGenerate) retry.addEventListener('click', () => begin(true));
    window.addEventListener('pagehide', () => { if (active) stop(active); });
    window.addEventListener('pageshow', event => { if (event.persisted) begin(); });
    begin();
})();
