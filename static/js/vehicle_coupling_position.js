// Restore the vehicle page exactly where the coupling dialog was opened.
(() => {
    "use strict";
    const dialog = document.getElementById("vehicle-coupling-dialog");
    if (!dialog) return;
    const key = "dkss:vehicle-coupling-return";
    const page = () => location.pathname + location.search;
    const selectors = [".main-content", ".app-layout", ".karte-vehicle-switcher-list"];
    const capture = () => ({
        url: page(), x: window.scrollX, y: window.scrollY, time: Date.now(),
        containers: selectors.map(selector => {
            const element = document.querySelector(selector);
            return element ? { selector, x: element.scrollLeft, y: element.scrollTop } : null;
        }).filter(Boolean)
    });
    const restore = state => {
        for (const item of state.containers || []) {
            const element = document.querySelector(item.selector);
            if (element) element.scrollTo({ left: item.x, top: item.y, behavior: "instant" });
        }
        window.scrollTo({ left: state.x, top: state.y, behavior: "instant" });
    };
    let openedAt;
    document.querySelectorAll("[data-coupling-open]").forEach(button => {
        button.addEventListener("click", () => { openedAt = capture(); }, { capture: true });
    });
    dialog.addEventListener("close", () => {
        if (openedAt) requestAnimationFrame(() => restore(openedAt));
    });
    dialog.addEventListener("submit", event => {
        if (event.defaultPrevented || !(event.target instanceof HTMLFormElement)) return;
        const state = openedAt || capture();
        let field = event.target.querySelector('input[name="return_to"]');
        if (!field) {
            field = document.createElement("input");
            field.type = "hidden";
            field.name = "return_to";
            event.target.append(field);
        }
        field.value = state.url;
        try { sessionStorage.setItem(key, JSON.stringify({ ...state, time: Date.now() })); } catch {}
    });
    let pending;
    try {
        pending = JSON.parse(sessionStorage.getItem(key) || "null");
        if (pending) sessionStorage.removeItem(key);
    } catch {}
    if (!pending || pending.url !== page() || !Number.isFinite(pending.x) || !Number.isFinite(pending.y)
        || !Number.isFinite(pending.time) || Date.now() - pending.time > 120000) return;
    // Prevent late font/layout changes from undoing the restored position.
    let active = true;
    for (const event of ["wheel", "touchstart", "pointerdown", "keydown"]) {
        window.addEventListener(event, () => { active = false; }, { once: true, passive: true });
    }
    const apply = () => requestAnimationFrame(() => { if (active) restore(pending); });
    apply();
    if (document.readyState !== "complete") window.addEventListener("load", apply, { once: true });
    if (document.fonts) document.fonts.ready.then(apply);
})();
