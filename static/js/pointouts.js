document.addEventListener("DOMContentLoaded", function () {
    document
        .querySelectorAll(".js-pointout-delete-form")
        .forEach(function (form) {
            form.addEventListener("submit", function (event) {
                if (!window.confirm("削除しますか？")) {
                    event.preventDefault();
                }
            });
        });
});