(() => {
    "use strict";
    const dialog = document.getElementById("vehicle-coupling-dialog");
    if (!dialog) return;
    let opener;
    document.querySelectorAll("[data-coupling-open]").forEach((button) => {
        button.addEventListener("click", () => {
            opener = button;
            if (!dialog.open) dialog.showModal();
        });
    });
    dialog.querySelectorAll("[data-coupling-close]").forEach((button) => {
        button.addEventListener("click", () => dialog.close());
    });
    dialog.addEventListener("close", () => opener?.focus({ preventScroll: true }));
    dialog.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            dialog.close();
        }
    });
    const search = dialog.querySelector("#vc-search");
    const selected = dialog.querySelector("[data-coupling-selected]");
    const submit = dialog.querySelector("[data-coupling-submit]");
    const data = dialog.querySelector("[data-coupling-search-data]");
    if (search && selected && submit && data) {
        window.DkssVehicleChoiceSearch.mount({
            input: search,
            results: dialog.querySelector("#vc-search-results"),
            status: dialog.querySelector("#vc-search-status"),
            choices: JSON.parse(data.textContent),
            onInput: () => { selected.value = ""; submit.disabled = true; },
            onSelect: (choice) => {
                selected.value = String(choice.id);
                submit.disabled = false;
            }
        });
        search.form.addEventListener("submit", (event) => {
            if (!selected.value) { event.preventDefault(); search.focus(); }
        });
    }
    dialog.querySelectorAll("[data-coupling-remove]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm("この車両との紐づけを解除しますか？")) event.preventDefault();
        });
    });
})();
