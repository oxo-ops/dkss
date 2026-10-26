/* Keep the shell in place while changing the vehicle workflow view. */
(() => {
    'use strict';
    const nav = document.querySelector('.vehicle-workflow-tabs');
    let panel = document.getElementById('vehicle-workflow-content');
    if (!nav || !panel) return;
    const links = Array.from(nav.querySelectorAll('a')).filter(link =>
        !link.classList.contains('vehicle-master-add-button'));
    const keyOf = value => { const url = new URL(value, location.href); return url.pathname + url.search; };
    const allowed = new Set(links.map(link => keyOf(link.href)));
    const views = new Map();
    let current = keyOf(location.href), controller = null, sequence = 0;
    // Pending record detail belongs to the pending tab, but retains its own URL.
    allowed.add(current);
    history.scrollRestoration = 'manual';

    function position() {
        return {x: window.scrollX, y: window.scrollY,
            containers: Array.from(document.querySelectorAll('main, .main-content'))
                .map(element => ({element, top: element.scrollTop, left: element.scrollLeft}))};
    }
    function restore(saved) {
        saved.containers.forEach(({element, top, left}) => {
            element.scrollTop = top; element.scrollLeft = left;
        });
        window.scrollTo({left: saved.x, top: saved.y, behavior: 'instant'});
    }
    function mark(source) {
        const incoming = source.querySelectorAll('a');
        links.forEach(link => {
            const match = Array.from(incoming).find(item => keyOf(item.href) === keyOf(link.href));
            link.removeAttribute('aria-current');
            if (match?.hasAttribute('aria-current')) link.setAttribute('aria-current', 'page');
            if (match) link.textContent = match.textContent;
        });
    }
    async function switchView(url, push) {
        const key = keyOf(url);
        if (key === current) { controller?.abort(); sequence++; nav.removeAttribute('aria-busy'); return; }
        controller?.abort();
        controller = new AbortController();
        const token = ++sequence;
        nav.setAttribute('aria-busy', 'true');
        try {
            let view = views.get(key);
            if (!view) {
                const response = await fetch(url, {signal: controller.signal, headers: {'Accept': 'text/html'}});
                if (!response.ok || new URL(response.url).origin !== location.origin) throw new Error('navigation');
                const page = new DOMParser().parseFromString(await response.text(), 'text/html');
                const content = page.getElementById('vehicle-workflow-content');
                if (!content || !page.querySelector('.vehicle-workflow-tabs')) throw new Error('navigation');
                // Scripts are loaded once by the shell, never executed from fetched HTML.
                content.querySelectorAll('script').forEach(script => script.remove());
                view = {panel: document.importNode(content, true), nav: page.querySelector('.vehicle-workflow-tabs')};
            }
            if (token !== sequence) return;
            const saved = position();
            const rect = panel.getBoundingClientRect();
            const height = Math.max(0, window.innerHeight - rect.top,
                ...saved.containers.map(({element}) =>
                    element.clientHeight - (rect.top - element.getBoundingClientRect().top)));
            views.set(current, {panel, nav: nav.cloneNode(true)});
            // Keep enough height for the current scroll offset even for a short view.
            view.panel.style.minHeight = Math.ceil(height) + 'px';
            panel.replaceWith(view.panel);
            panel = view.panel;
            mark(view.nav);
            current = key;
            if (push) history.pushState(null, '', url);
            document.dispatchEvent(new Event('dkss:vehicle-workflow'));
            restore(saved);
            requestAnimationFrame(() => { if (token === sequence) restore(saved); });
        } catch (error) {
            if (error.name !== 'AbortError' && token === sequence) location.assign(url);
        } finally {
            if (token === sequence) nav.removeAttribute('aria-busy');
        }
    }
    nav.addEventListener('click', event => {
        const link = event.target.closest('a');
        if (!links.includes(link) || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        switchView(link.href, true);
    });
    window.addEventListener('popstate', () => {
        if (allowed.has(keyOf(location.href))) switchView(location.href, false);
        else location.reload();
    });
})();
