(() => {
    const root = document.querySelector(".vehicle-karte-documents");
    const form = document.getElementById("document_filters");
    if (!root || !form) return;

    root.classList.add("kd-enhanced");

    const submit = () => form.requestSubmit();

    for (const select of form.querySelectorAll("select")) {
        select.addEventListener("change", submit);
    }

    document.querySelector('select[form="document_filters"]')
        ?.addEventListener("change", submit);

    const all = root.querySelector("[data-document-check-all]");
    const checks = [...root.querySelectorAll("[data-document-check]")];

    const sync = () => {
        const selected = checks.filter(check => check.checked).length;

        if (all) {
            all.checked = checks.length > 0 && selected === checks.length;
            all.indeterminate = selected > 0 && selected < checks.length;
        }

        for (const check of checks) {
            check.closest("tr")?.classList.toggle(
                "kd-checked",
                check.checked
            );
        }
    };

    all?.addEventListener("change", () => {
        for (const check of checks) {
            check.checked = all.checked;
        }
        sync();
    });

    for (const check of checks) {
        check.addEventListener("change", sync);
    }

    window.addEventListener("pageshow", sync);
    sync();
})();