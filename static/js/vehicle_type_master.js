document.addEventListener("DOMContentLoaded", function () {
    document
        .querySelectorAll(".js-vehicle-type-delete-form")
        .forEach(function (form) {
            form.addEventListener("submit", function (event) {
                if (!window.confirm("この車種を削除しますか？")) {
                    event.preventDefault();
                }
            });
        });
});