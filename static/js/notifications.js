document.addEventListener("DOMContentLoaded", function () {
    document
        .querySelectorAll(".js-notification-list-delete-form")
        .forEach(function (form) {
            form.addEventListener("submit", function (event) {
                if (!window.confirm("この通知を削除しますか？")) {
                    event.preventDefault();
                }
            });
        });
});