// One vehicle-search component for navigation and vehicle selection.
(() => {
    const normalize = value => String(value || '').normalize('NFKC').toLocaleLowerCase('ja')
        .replace(/[ァ-ヶ]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0x60))
        .replace(/[\s\u3000\-‐‑‒–—―−]/g, '');
    const terms = value => String(value || '').trim().split(/[\s\u3000]+/).map(normalize).filter(Boolean);
    const matches = (text, queryTerms) => queryTerms.every(term => text.includes(term));

    function mount({ input, results, status, choices, onInput, onSelect, getHref }) {
        if (!input || !results || !status || !Array.isArray(choices) || input.dataset.vehicleSearchMounted) return;
        input.dataset.vehicleSearchMounted = '1';
        let composing = false;
        const records = choices.map(choice => ({ choice,
            searchText: normalize([choice.number, choice.chassis_number].join(' ')) }));
        const hideResults = () => {
            results.hidden = true;
            input.setAttribute('aria-expanded', 'false');
        };
        const updateResults = () => {
            onInput?.();
            results.replaceChildren();
            const query = terms(input.value);
            if (!query.length) {
                hideResults();
                status.hidden = true;
                status.textContent = '';
                return;
            }
            const found = records.filter(record => matches(record.searchText, query));
            status.textContent = found.length
                ? `${found.length}台見つかりました。車両をクリックしてください。`
                : '該当する車両がありません。';
            status.hidden = false;
            results.hidden = !found.length;
            input.setAttribute('aria-expanded', String(found.length > 0));
            const fragment = document.createDocumentFragment();
            for (const { choice } of found) {
                const link = document.createElement('a');
                link.href = getHref ? getHref(choice) : '#';
                link.className = 'vehicle-karte-search-result';
                const number = document.createElement('strong');
                number.textContent = choice.number || '車番未登録';
                link.append(number);
                if (onSelect) link.addEventListener('click', event => {
                    event.preventDefault();
                    input.value = choice.number || '車番未登録';
                    hideResults();
                    results.replaceChildren();
                    status.textContent = `${input.value} を選択しました。`;
                    onSelect(choice);
                    input.focus();
                });
                fragment.append(link);
            }
            results.append(fragment);
        };
        input.addEventListener('compositionstart', () => { composing = true; onInput?.(); });
        input.addEventListener('compositionend', () => { composing = false; updateResults(); });
        input.addEventListener('input', event => {
            if (!composing && !event.isComposing) updateResults();
        });
        input.addEventListener('keydown', event => {
            if (event.key === 'ArrowDown' && !results.hidden) {
                event.preventDefault();
                results.querySelector('a')?.focus();
            }
        });
        updateResults();
    }
    window.DkssVehicleChoiceSearch = { normalize, terms, matches, mount };
})();
(() => {
    const input = document.getElementById('karte_vehicle_search');
    const results = document.getElementById('karte_vehicle_search_results');
    const status = document.getElementById('karte_vehicle_search_status');
    const data = document.getElementById('karte_vehicle_search_data');
    if (!input || !results || !status || !data) return;
    window.DkssVehicleChoiceSearch.mount({
        input, results, status, choices: JSON.parse(data.textContent),
        getHref: choice => {
            const url = new URL(results.dataset.karteUrl, window.location.origin);
            url.searchParams.set('vehicle_record_id', choice.id);
            return url.href;
        }
    });
})();
