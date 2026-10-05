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
            !event.defaultPrevented &&
            (
                form.action.includes("/approve/") ||
                form.action.includes("/reject")
            )
        ) {
            sessionStorage.setItem(
                "checklistResultScrollPosition",
                JSON.stringify({
                    path: location.pathname + location.search,
                    x: window.scrollX,
                    y: window.scrollY,
                    savedAt: Date.now(),
                    details: Array.from(document.querySelectorAll(
                        ".checklist-other-items, .checklist-criteria-details"
                    )).map(function (element) {
                        return element.open;
                    })
                })
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

    const savedPosition = sessionStorage.getItem(
        "checklistResultScrollPosition"
    );
    sessionStorage.removeItem("checklistResultScrollPosition");
    sessionStorage.removeItem("checklistResultScrollY");

    if (savedPosition && !document.getElementById("error-summary")) {
        try {
            const position = JSON.parse(savedPosition);

            if (
                position.path === location.pathname + location.search &&
                Date.now() - position.savedAt < 60000
            ) {
                document.querySelectorAll(
                    ".checklist-other-items, .checklist-criteria-details"
                ).forEach(function (element, index) {
                    if (typeof position.details?.[index] === "boolean") {
                        element.open = position.details[index];
                    }
                });

                const restorePosition = function () {
                    requestAnimationFrame(function () {
                        requestAnimationFrame(function () {
                            if (!document.getElementById("error-summary")) {
                                window.scrollTo({
                                    left: position.x || 0,
                                    top: position.y || 0,
                                    behavior: "instant"
                                });
                            }
                        });
                    });
                };

                if (document.readyState === "complete") {
                    restorePosition();
                } else {
                    window.addEventListener(
                        "load", restorePosition, { once: true }
                    );
                }
            }
        } catch (error) {
            // 読めない保存値は破棄し、通常の表示を続けます。
        }
    }
});