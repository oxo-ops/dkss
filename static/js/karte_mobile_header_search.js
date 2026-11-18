/* Reuse the existing authorised vehicle search and its result links. */
(() => {
    const input = document.getElementById('karte_vehicle_search');
    const search = input?.closest('.vehicle-karte-search');
    const bar = search?.closest('.top-bar');
    if (!search || !bar || typeof HTMLDialogElement === 'undefined') return;
    const mobile = matchMedia('(max-width: 767px)');
    const anchor = document.createComment('vehicle search original position');
    search.before(anchor);
    const trigger = document.createElement('button');
    trigger.type = 'button'; trigger.className = 'karte-mobile-search-trigger';
    trigger.setAttribute('aria-label', '車両検索を開く');
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-controls', 'karte-mobile-search-dialog');
    trigger.innerHTML = '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>';
    bar.querySelector('.top-bar-user')?.before(trigger);
    const dialog = document.createElement('dialog');
    dialog.id = 'karte-mobile-search-dialog'; dialog.className = 'karte-mobile-search-dialog';
    dialog.setAttribute('aria-label', '車両検索');
    const close = document.createElement('button');
    close.type = 'button'; close.className = 'karte-mobile-search-close';
    close.textContent = '×'; close.setAttribute('aria-label', '検索を閉じる');
    const clear = document.createElement('button');
    clear.type = 'button'; clear.className = 'karte-mobile-search-clear';
    clear.textContent = '×'; clear.setAttribute('aria-label', '検索文字を消去');
    const field = document.createElement('span');
    field.className = 'karte-mobile-search-field';
    input.before(field); field.append(input, clear);
    const syncClear = () => { clear.hidden = !input.value || input.disabled || input.readOnly; };
    input.addEventListener('input', syncClear); input.addEventListener('change', syncClear);
    syncClear();
    dialog.append(close); document.body.append(dialog);
    let previous = '';
    const dismiss = (restoreFocus = true) => {
        if (!dialog.open) return;
        input.value = previous; input.dispatchEvent(new Event('input', {bubbles:true}));
        dialog.close(); trigger.setAttribute('aria-expanded', 'false');
        if (restoreFocus && mobile.matches) trigger.focus();
    };
    trigger.addEventListener('click', () => {
        if (!mobile.matches || dialog.open) return;
        previous = input.value; dialog.showModal();
        trigger.setAttribute('aria-expanded', 'true'); input.focus();
    });
    close.addEventListener('click', () => dismiss());
    clear.addEventListener('click', () => {
        if (input.disabled || input.readOnly) return;
        input.value = ''; input.dispatchEvent(new Event('input', {bubbles:true})); input.focus();
    });
    dialog.addEventListener('cancel', event => { event.preventDefault(); dismiss(); });
    input.addEventListener('keydown', event => {
        if (dialog.open && event.key === 'Escape' && !event.isComposing) {
            event.preventDefault(); dismiss();
        }
    });
    const layout = () => {
        if (mobile.matches) dialog.prepend(search);
        else { dismiss(false); anchor.after(search); }
    };
    mobile.addEventListener('change', layout); layout();
})();
