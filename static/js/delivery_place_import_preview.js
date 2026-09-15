document.addEventListener("DOMContentLoaded", function () {
    const form =
        document.querySelector(".js-delivery-import-form");

    if (!form) {
        return;
    }

    form.addEventListener("submit", function (event) {
        const newCount =
            Number(form.dataset.newCount || 0);

        const existingCount =
            Number(form.dataset.existingCount || 0);

        const duplicateCount =
            Number(form.dataset.duplicateCount || 0);

        const message =
            "納入先データを登録しますか？\n\n" +
            "新規登録：" + newCount + "件\n" +
            "登録済み：" + existingCount + "件\n" +
            "Excel内重複：" + duplicateCount + "件\n\n" +
            "登録済みとExcel内重複は登録されません。";

        if (!window.confirm(message)) {
            event.preventDefault();
        }
    });
});