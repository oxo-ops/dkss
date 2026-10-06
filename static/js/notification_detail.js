document.addEventListener("DOMContentLoaded", function () {
    const forms = Array.from(
        document.querySelectorAll(".notification-actions form")
    );

    forms.forEach(function (form) {
        form.addEventListener("submit", function (event) {
            if (form.dataset.submitting === "true") {
                event.preventDefault();
                return;
            }

            form.dataset.submitting = "true";
            form.setAttribute("aria-busy", "true");
        });
    });

    window.addEventListener("pageshow", function () {
        forms.forEach(function (form) {
            delete form.dataset.submitting;
            form.removeAttribute("aria-busy");
        });
    });
});