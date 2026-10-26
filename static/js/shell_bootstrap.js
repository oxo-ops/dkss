/* Parser-blocking by design: establish shell width before its first paint. */
(() => {
    'use strict';
    function readPreference(key) {
        try { return window.localStorage.getItem(key); }
        catch (_) { return null; }
    }
    function writePreference(key, value) {
        try { window.localStorage.setItem(key, value); }
        catch (_) { /* Menu controls still work when browser storage is disabled. */ }
    }
    window.DkssShell = { readPreference, writePreference };
    const path = window.location.pathname;
    const forcedCollapsed = /^\/safety\/checklists\/\d+\/new\/?$/.test(path)
        || /^\/vehicle\/checklists\/\d+\/?$/.test(path)
        || /^\/vehicle\/data-import\/[^/]+\/preview\/?$/.test(path);
    const forcedExpanded = /^\/safety\/checklists\/\d+\/?$/.test(path);
    const collapsed = forcedCollapsed || (!forcedExpanded
        && (document.body.classList.contains('sidebar-collapsed')
            || readPreference('sidebarCollapsed') === '1'));
    document.body.classList.toggle('sidebar-collapsed', window.innerWidth > 900 && collapsed);
})();
