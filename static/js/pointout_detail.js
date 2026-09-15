document.addEventListener("DOMContentLoaded", function () {
    const manualSelect = document.querySelector(".js-manual-select");
    const manualLink = document.getElementById("manual_link");
    const deleteForm = document.querySelector(".js-pointout-delete-form");

    if (manualSelect && manualLink) {
        manualSelect.addEventListener("change", function () {
            if (!manualSelect.value) {
                manualLink.removeAttribute("href");
                manualLink.classList.add("is-hidden");
                return;
            }

            manualLink.href = manualSelect.value;
            manualLink.classList.remove("is-hidden");
        });
    }

    if (deleteForm) {
        deleteForm.addEventListener("submit", function (event) {
            if (!window.confirm("削除しますか？")) {
                event.preventDefault();
            }
        });
    }
});