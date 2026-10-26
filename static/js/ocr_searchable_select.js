/* OCR uses the notification recipient pattern: type -> candidate -> selected tag. */
(() => {
    'use strict';
    const controllers = new WeakMap(), forms = new WeakSet();
    let activeControl = null, serial = 0;
    const {normalize, terms: searchTerms, matches: matchesTerms} = window.DkssVehicleChoiceSearch;
    const labelOf = option => option?.textContent.replace(/\s+/g, ' ').trim() || '';
    function enhance(select) {
        if (controllers.has(select)) return;
        const wrapper = select.closest('.ocr-choice-field');
        if (!wrapper) return;
        const input = wrapper.querySelector('[data-ocr-choice-input]');
        const panel = wrapper.querySelector('[data-ocr-choice-results]');
        const selected = wrapper.querySelector('[data-ocr-choice-selected]');
        const status = wrapper.querySelector('[data-ocr-choice-status]');
        document.body.append(panel);
        const title = select.dataset.searchLabel || '候補';
        const label = select.closest('label') || (select.id && document.querySelector(`label[for="${CSS.escape(select.id)}"]`));
        if (label) label.htmlFor = input.id;
        panel.id = 'ocr-candidates-' + (++serial);
        input.setAttribute('role','combobox'); input.setAttribute('aria-autocomplete','list');
        input.setAttribute('aria-controls',panel.id); input.setAttribute('aria-expanded','false');
        panel.setAttribute('role','listbox'); panel.setAttribute('aria-label',title + 'の候補');
        let matches = [], active = -1, composing = false;
        const available = option => !option.disabled && !option.parentElement?.disabled;
        const close = () => { panel.hidden = true; status.hidden = true; input.setAttribute('aria-expanded','false'); input.removeAttribute('aria-activedescendant'); active = -1; if (activeControl === controller) activeControl = null; };
        function commit(option) {
            if (select.disabled || !available(option)) return;
            select.value = option.value; sync();
            select.dispatchEvent(new Event('input',{bubbles:true}));
            select.dispatchEvent(new Event('change',{bubbles:true}));
            input.focus({preventScroll:true}); close();
        }
        function sync() {
            close(); input.value = ''; input.disabled = select.disabled;
            input.setCustomValidity(''); select.setCustomValidity(''); input.removeAttribute('aria-invalid');
            if (select.getAttribute('aria-describedby')) input.setAttribute('aria-describedby',select.getAttribute('aria-describedby'));
            selected.replaceChildren();
            if (select.value) {
                const tag = document.createElement('span'); tag.className = 'selected-vehicle-tag';
                const name = document.createElement('span'); name.textContent = labelOf(select.selectedOptions[0]); tag.append(name);
                const empty = [...select.options].find(option => !option.value && available(option));
                if (empty) {
                    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'tag-remove-btn';
                    remove.textContent = '×'; remove.setAttribute('aria-label',title + 'の選択を解除'); remove.disabled = select.disabled;
                    remove.addEventListener('click',event => { event.preventDefault(); commit(empty); }); tag.append(remove);
                }
                selected.append(tag);
            }
            selected.hidden = !select.value;
            queueMicrotask(() => input.classList.toggle('invoice-input-modified',select.classList.contains('invoice-input-modified')));
        }
        function show() {
            if (select.disabled || composing) return;
            const query = input.value.trim();
            if (!query && select.dataset.showAllOnFocus !== '1') { close(); return; }
            if (activeControl && activeControl !== controller) activeControl.close();
            activeControl = controller;
            const tokens = searchTerms(query);
            const all = [...select.options].filter(option => option.value && matchesTerms(normalize([labelOf(option),option.dataset.vehicleNumber,option.dataset.vehicleChassis].join(' ')), tokens));
            matches = all; active = -1; panel.replaceChildren(); input.removeAttribute('aria-activedescendant');
            matches.forEach((option,index) => {
                const button = document.createElement('button'); button.type = 'button'; button.className = 'vehicle-karte-search-result';
                button.id = panel.id + '-' + index; button.setAttribute('role','option'); button.setAttribute('aria-selected','false'); button.tabIndex = -1; button.disabled = !available(option);
                const name = document.createElement('strong'); name.textContent = labelOf(option); button.append(name);
                if (option.dataset.vehicleChassis) { const detail = document.createElement('span'); detail.textContent = '車台番号：' + option.dataset.vehicleChassis; button.append(detail); }
                button.addEventListener('pointerdown',event => event.preventDefault()); button.addEventListener('click',() => commit(option)); panel.append(button);
            });
            status.textContent = all.length ? `${all.length}${title === '対象車両' ? '台' : '件'}見つかりました。候補をクリックしてください。` : '該当する候補がありません。検索文字を変更してください。';
            status.hidden = false;
            panel.hidden = !all.length; panel.scrollTop = 0; input.setAttribute('aria-expanded',String(Boolean(all.length)));
            requestAnimationFrame(position);
        }
        function position() {
            if (panel.hidden) return;
            const rect = input.getBoundingClientRect();
            if (!input.getClientRects().length || rect.bottom < 0 || rect.top > innerHeight) { close(); return; }
            const anchorBottom = status.hidden ? rect.bottom : status.getBoundingClientRect().bottom;
            const below = innerHeight - anchorBottom - 12, above = rect.top - 12;
            const upwards = below < 180 && above > below;
            const height = Math.min(240,Math.max(60,upwards ? above : below));
            panel.style.position = 'fixed';
            panel.style.width = Math.min(rect.width,innerWidth-16) + 'px';
            panel.style.right = 'auto';
            panel.style.left = Math.max(8,Math.min(rect.left,innerWidth-panel.offsetWidth-8)) + 'px';
            panel.style.maxHeight = height + 'px';
            panel.style.top = (upwards ? Math.max(8,rect.top-Math.min(height,panel.scrollHeight)-4) : anchorBottom+4) + 'px';
        }
        function validate() {
            if (select.disabled) return true;
            const message = input.value.trim() ? '検索文字を入力しただけでは選択されません。候補から選択してください。'
                : select.required && !select.value ? title + 'を選択してください。' : '';
            input.setCustomValidity(message); select.setCustomValidity(message);
            if (!message) return true;
            input.setAttribute('aria-invalid','true'); input.dispatchEvent(new Event('invalid')); input.focus(); input.reportValidity(); return false;
        }
        const controller = {close,sync,validate,wrapper,panel,position}; controllers.set(select,controller);
        input.addEventListener('input',event => { const message = input.value.trim() ? '候補から選択して確定してください。' : ''; input.setCustomValidity(message); select.setCustomValidity(message); if (!composing && !event.isComposing) show(); });
        input.addEventListener('focus',show); input.addEventListener('compositionstart',() => { composing = true; });
        input.addEventListener('click',() => { if (select.dataset.showAllOnFocus === '1') show(); });
        input.addEventListener('compositionend',() => { composing = false; show(); });
        input.addEventListener('keydown',event => {
            if (event.isComposing || composing || event.keyCode === 229) return;
            if (event.key === 'Escape') { event.preventDefault(); sync(); return; }
            if (event.key === 'Tab') { close(); return; }
            if (event.key === 'Enter') {
                event.preventDefault();
                if (!panel.hidden) { if (active >= 0) commit(matches[active]); else if (matches.length === 1) commit(matches[0]); }
            } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault(); if (panel.hidden) show();
                const step = event.key === 'ArrowDown' ? 1 : -1;
                let next = active < 0 ? (step > 0 ? 0 : matches.length-1) : active + step;
                while (next >= 0 && next < matches.length && !available(matches[next])) next += step;
                if (next >= 0 && next < matches.length) {
                    active = next;
                    [...panel.querySelectorAll('[role=option]')].forEach((button,index) => button.setAttribute('aria-selected',String(index===active)));
                    const button = panel.querySelectorAll('[role=option]')[active]; input.setAttribute('aria-activedescendant',button.id); button.scrollIntoView({block:'nearest'});
                }
            }
        });
        select.addEventListener('change',sync); select.addEventListener('input',sync);
        select.addEventListener('invalid',event => { event.preventDefault(); validate(); });
        new MutationObserver(sync).observe(select,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['disabled','selected','value','required','aria-describedby']});
        sync();
        new ResizeObserver(() => { if (activeControl === controller) position(); }).observe(wrapper);
        if (select.form && !forms.has(select.form)) {
            forms.add(select.form);
            select.form.addEventListener('submit',event => {
                for (const field of event.currentTarget.querySelectorAll('select[data-searchable-select]')) {
                    const record = field.closest('.invoice-record');
                    if (record && record.querySelector('input[name=include]')?.checked === false) continue;
                    if (!controllers.get(field)?.validate()) { event.preventDefault(); event.stopImmediatePropagation(); break; }
                }
            },true);
            select.form.addEventListener('reset',() => queueMicrotask(() => select.form.querySelectorAll('select[data-searchable-select]').forEach(field => controllers.get(field)?.sync())));
        }
    }
    document.addEventListener('pointerdown',event => { if (activeControl && !activeControl.wrapper.contains(event.target) && !activeControl.panel.contains(event.target)) activeControl.close(); },true);
    let frame = 0;
    const reposition = () => { if (activeControl && !frame) frame = requestAnimationFrame(() => { frame = 0; activeControl?.position(); }); };
    window.addEventListener('resize',reposition); window.addEventListener('scroll',reposition,true);
    const initialize = () => document.querySelectorAll('select[data-searchable-select]').forEach(enhance);
    document.addEventListener('dkss:vehicle-workflow',() => { activeControl?.close(); initialize(); });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',initialize); else initialize();
})();
