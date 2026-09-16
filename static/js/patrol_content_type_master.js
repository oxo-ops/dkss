document.addEventListener("DOMContentLoaded", function () {
    document
        .querySelectorAll(
            ".js-patrol-content-type-delete-form"
        )
        .forEach(function (form) {
            form.addEventListener("submit", function (event) {
                if (
                    !window.confirm(
                        "この内容区分を削除しますか？"
                    )
                ) {
                    event.preventDefault();
                }
            });
        });
});