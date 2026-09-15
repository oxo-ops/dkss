document.addEventListener("DOMContentLoaded", function () {
    document.addEventListener("submit", function (event) {
        const form = event.target;

        if (
            form.matches(".js-checklist-result-delete-form") &&
            !window.confirm("この結果を削除しますか？")
        ) {
            event.preventDefault();
            return;
        }

        if (
            form.action.includes("/approve/") ||
            form.action.includes("/reject")
        ) {
            sessionStorage.setItem(
                "checklistResultScrollY",
                window.scrollY
            );
        }
    });

    const savedScrollY =
        sessionStorage.getItem("checklistResultScrollY");

    if (savedScrollY !== null) {
        window.scrollTo(0, Number(savedScrollY));
        sessionStorage.removeItem(
            "checklistResultScrollY"
        );
    }
});