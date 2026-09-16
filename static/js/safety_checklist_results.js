document.addEventListener("DOMContentLoaded", function () {
    const deleteForms = document.querySelectorAll(
        ".js-checklist-result-delete-form"
    );

    deleteForms.forEach(function (form) {
        form.addEventListener("submit", function (event) {
            if (!window.confirm("この結果を削除しますか？")) {
                event.preventDefault();
            }
        });
    });
});