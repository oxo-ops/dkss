document.addEventListener("DOMContentLoaded", function () {
    const manualSelect =
        document.getElementById("manual_select");

    const manualLink =
        document.getElementById("manual_link");

    if (!manualSelect || !manualLink) {
        return;
    }

    function updateManualLink() {
        const url =
            manualSelect.value;

        if (!url) {
            manualLink.removeAttribute("href");
            manualLink.classList.add("is-hidden");
            return;
        }

        manualLink.href = url;
        manualLink.classList.remove("is-hidden");
    }

    manualSelect.addEventListener(
        "change",
        updateManualLink
    );

    updateManualLink();
});