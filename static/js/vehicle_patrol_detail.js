document.addEventListener("DOMContentLoaded", function () {
    const deleteForm =
        document.querySelector(
            ".js-vehicle-patrol-detail-delete-form"
        );

    if (!deleteForm) {
        return;
    }

    deleteForm.addEventListener("submit", function (event) {
        if (!window.confirm("削除しますか？")) {
            event.preventDefault();
        }
    });
});