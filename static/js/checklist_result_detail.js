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

    document.querySelectorAll(
        ".checklist-score-progress-bar"
    ).forEach(function (bar) {
        const percent = Number(
            bar.dataset.scorePercent || 0
        );

        bar.style.width =
            Math.max(0, Math.min(100, percent)) + "%";
    });

    document.querySelectorAll(
        ".checklist-score-filter"
    ).forEach(function (button) {
        button.addEventListener(
            "click",
            function () {
                const value =
                    button.dataset.scoreValue || "";

                const isActive =
                    button.classList.contains("is-active");

                document.querySelectorAll(
                    ".checklist-score-filter"
                ).forEach(function (item) {
                    item.classList.remove("is-active");
                });

                document.querySelectorAll(
                    ".checklist-table tbody tr[data-score-value]"
                ).forEach(function (row) {
                    const shouldHide =
                        !isActive &&
                        row.dataset.scoreValue !== value;

                    if (shouldHide) {
                        row.style.setProperty(
                            "display",
                            "none",
                            "important"
                        );
                    } else {
                        row.style.removeProperty("display");
                    }
                });

                const otherItems = document.querySelector(
                    ".checklist-other-items"
                );

                if (otherItems) {
                    otherItems.open = !isActive;
                }

                if (!isActive) {
                    button.classList.add("is-active");

                    if (otherItems) {
                        const hasVisibleOtherItem =
                            Array.from(
                                otherItems.querySelectorAll(
                                    "tbody tr[data-score-value]"
                                )
                            ).some(function (row) {
                                return row.style.display !== "none";
                            });

                        otherItems.open = hasVisibleOtherItem;
                    }
                }
            }
        );
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