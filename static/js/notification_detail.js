document.addEventListener("DOMContentLoaded", function () {
    const deleteForm =
        document.querySelector(
            ".js-notification-delete-form"
        );

    if (!deleteForm) {
        return;
    }

    deleteForm.addEventListener("submit", function (event) {
        if (!window.confirm("この通知を削除しますか？")) {
            event.preventDefault();
        }
    });
});