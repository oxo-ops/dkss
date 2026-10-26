(() => {
    'use strict';
    const workspace = document.querySelector('.import-workspace[data-import-owner]');
    if (!workspace || !window.indexedDB) return;
    const owner = workspace.dataset.importOwner;
    const tabKey = 'dkss-import-tab-v1';
    let tab = sessionStorage.getItem(tabKey);
    if (!tab) { tab = crypto.randomUUID(); sessionStorage.setItem(tabKey, tab); }
    const key = JSON.stringify([owner, tab]);
    const ttl = 30 * 60 * 1000;
    let restoring = false, writes = Promise.resolve();
    const opened = new Promise((resolve, reject) => {
        const request = indexedDB.open('dkss-import-selections-v1', 1);
        const timeout = setTimeout(() => reject(new Error('selection-storage-timeout')), 2500);
        request.onupgradeneeded = () => request.result.createObjectStore('selections');
        request.onsuccess = () => { clearTimeout(timeout); resolve(request.result); };
        request.onerror = () => { clearTimeout(timeout); reject(request.error); };
        request.onblocked = () => { clearTimeout(timeout); reject(new Error('selection-storage-blocked')); };
    });
    opened.catch(() => {});
    const forms = () => Array.from(workspace.querySelectorAll('form.import-form'));
    const kind = form => form.querySelector('[name="document_type"]')?.value || 'operation';
    function save() {
        if (restoring) return writes;
        const selections = forms().filter(form => !form.dataset.importAccepted).map(form => ({
            kind: kind(form), files: Array.from(form.querySelector('input[type="file"]').files || []),
            uploadKey: form.dataset.uploadKey || ''
        })).filter(item => item.files.length);
        writes = writes.then(() => opened).then(db => new Promise((resolve, reject) => {
            const tx = db.transaction('selections', 'readwrite');
            const store = tx.objectStore('selections');
            if (selections.length) store.put({owner, expires: Date.now() + ttl, selections}, key);
            else store.delete(key);
            tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
        })).catch(() => {});
        return writes;
    }
    function position() {
        sessionStorage.setItem('dkss-import-return-v1', JSON.stringify({
            owner, path: location.pathname, x: scrollX, y: scrollY, expires: Date.now() + ttl
        }));
    }
    window.DKSSImportSelections = {accepted(form) {
        form.dataset.importAccepted = '1';
        return Promise.race([save(), new Promise(resolve => setTimeout(resolve, 2500))]);
    }};
    document.addEventListener('submit', event => {
        if (workspace.contains(event.target)) { position(); save(); }
    }, true);
    document.addEventListener('DOMContentLoaded', async () => {
        forms().forEach(form => {
            form.querySelector('input[type="file"]').addEventListener('change', () => {
                delete form.dataset.importAccepted; save();
            });
            form.querySelector('.import-clear')?.addEventListener('click', () => setTimeout(save, 0));
        });
        try {
            const db = await opened;
            const saved = await new Promise((resolve, reject) => {
                const request = db.transaction('selections').objectStore('selections').get(key);
                request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
            });
            if (saved?.owner === owner && saved.expires > Date.now() && typeof DataTransfer === 'function') {
                restoring = true;
                for (const item of saved.selections) {
                    const form = forms().find(form => kind(form) === item.kind);
                    const input = form?.querySelector('input[type="file"]');
                    if (!input || input.files.length) continue;
                    const transfer = new DataTransfer(); item.files.forEach(file => transfer.items.add(file));
                    input.files = transfer.files; input.dispatchEvent(new Event('change', {bubbles:true}));
                    if (item.uploadKey) form.dataset.uploadKey = item.uploadKey;
                }
                restoring = false;
            } else if (saved) {
                const tx = db.transaction('selections', 'readwrite'); tx.objectStore('selections').delete(key);
            }
        } catch (_) { restoring = false; }
        try {
            const saved = JSON.parse(sessionStorage.getItem('dkss-import-return-v1') || 'null');
            if (saved?.owner === owner && saved.path === location.pathname && saved.expires > Date.now()) {
                requestAnimationFrame(() => scrollTo(saved.x, saved.y));
                sessionStorage.removeItem('dkss-import-return-v1');
            }
        } catch (_) {}
    });
})();
