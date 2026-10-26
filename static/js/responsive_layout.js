/* Shared viewport contract. Browser zoom and split windows both change CSS pixels. */
(() => {
    'use strict';
    const root = document.documentElement;
    const drawer = window.matchMedia('(max-width: 900px)');
    let frame = 0, previousDrawer = null;
    const height = () => Math.max(1, Math.min(window.innerHeight,
        window.visualViewport?.height || window.innerHeight));
    const compactReview = layout => window.innerWidth <= 1000
        || (layout.clientWidth || window.innerWidth) < 900 || height() < 600;
    window.DkssViewport = { height, compactReview };

    function property(name, value) {
        if (root.style.getPropertyValue(name) !== value) root.style.setProperty(name, value);
    }
    function attribute(element, name, value) {
        if (element.getAttribute(name) !== value) element.setAttribute(name, value);
    }
    function update() {
        frame = 0;
        const body = document.body, main = document.querySelector('.main-content');
        if (!body || !main) return;
        property('--app-viewport-height', Math.floor(height()) + 'px');
        property('--app-viewport-width', window.innerWidth + 'px');
        const width = main.clientWidth - parseFloat(getComputedStyle(main).paddingLeft || 0)
            - parseFloat(getComputedStyle(main).paddingRight || 0);
        attribute(body, 'data-content-layout', width <= 640 ? 'compact' : width <= 1000 ? 'medium' : 'wide');
        attribute(body, 'data-short-viewport', String(height() < 600));
        if (previousDrawer !== drawer.matches) {
            body.classList.remove('sidebar-open');
            if (drawer.matches) body.classList.remove('sidebar-collapsed');
            else if (previousDrawer !== null) body.classList.toggle('sidebar-collapsed', localStorage.getItem('sidebarCollapsed') === '1');
            previousDrawer = drawer.matches;
        }
        const toggle = document.querySelector('#sidebarToggle');
        if (toggle) {
            toggle.setAttribute('aria-label', 'メニューを開閉');
            toggle.setAttribute('aria-expanded', String(drawer.matches
                ? body.classList.contains('sidebar-open') : !body.classList.contains('sidebar-collapsed')));
        }
        let compact = false;
        document.querySelectorAll('.invoice-review-layout').forEach(layout => {
            const small = compactReview(layout);
            attribute(layout, 'data-compact-review', String(small));
            compact ||= small;
        });
        attribute(body, 'data-review-layout', compact ? 'compact' : 'wide');
    }
    function schedule() {
        if (!frame) frame = requestAnimationFrame(update);
    }
    function initialize() {
        schedule();
        window.addEventListener('resize', schedule);
        window.addEventListener('orientationchange', schedule);
        window.addEventListener('pageshow', schedule);
        window.visualViewport?.addEventListener('resize', schedule);
        drawer.addEventListener('change', schedule);
        if ('ResizeObserver' in window) {
            const observer = new ResizeObserver(schedule);
            const main = document.querySelector('.main-content');
            if (main) observer.observe(main);
            document.querySelectorAll('.invoice-review-layout').forEach(layout => observer.observe(layout));
        }
        // Imports reveal existing panels and the sidebar changes the usable width.
        new MutationObserver(schedule).observe(document.body, { attributes: true, attributeFilter: ['class'] });
        const certificate = document.querySelector('#certificate-review-shell');
        if (certificate) new MutationObserver(schedule).observe(certificate, { attributes: true, attributeFilter: ['hidden'] });
        document.fonts?.ready.then(schedule);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, {once:true});
    else initialize();
})();
