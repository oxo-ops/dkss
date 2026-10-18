(() => {
    "use strict";
    document.querySelectorAll("[data-parts-submit]").forEach((control) => {
        control.addEventListener("change", () => {
            control.form?.requestSubmit();
        });
    });
})();
