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

    const targetSearch =
        document.getElementById(
            "pointout_target_search"
        );

    const targetResults =
        document.getElementById(
            "pointout_target_results"
        );

    const targetData =
        document.getElementById(
            "pointout_target_data"
        );

    function updateTargetResults() {
        if (
            !targetSearch ||
            !targetResults ||
            !targetData
        ) {
            return;
        }

        const keyword =
            targetSearch.value
                .trim()
                .toLowerCase();

        targetResults.replaceChildren();

        if (!keyword) {
            targetResults.classList.add(
                "is-hidden"
            );
            return;
        }

        const drivers =
            Array.from(
                targetData.querySelectorAll(
                    "[data-name]"
                )
            );

        const matchedDrivers =
            drivers.filter(function (driver) {
                const name =
                    String(
                        driver.dataset.name || ""
                    ).toLowerCase();

                return name.includes(keyword);
            });

        matchedDrivers.forEach(
            function (driver) {
                const button =
                    document.createElement(
                        "button"
                    );

                button.type = "button";
                button.className =
                    "pointout-target-option";

                button.textContent =
                    driver.dataset.name || "";

                button.addEventListener(
                    "click",
                    function () {
                        targetSearch.value =
                            driver.dataset.name || "";

                        targetResults
                            .replaceChildren();

                        targetResults
                            .classList.add(
                                "is-hidden"
                            );
                    }
                );

                targetResults.appendChild(
                    button
                );
            }
        );

        targetResults.classList.toggle(
            "is-hidden",
            matchedDrivers.length === 0
        );
    }

    targetSearch?.addEventListener(
        "input",
        updateTargetResults
    );

    targetSearch?.addEventListener(
        "compositionend",
        updateTargetResults
    );
});

// Choose a responsive default once; preserve a size selected by the user or link.
document.addEventListener("DOMContentLoaded", function () {
    const url = new URL(window.location.href);
    const requested = url.searchParams.get("page_size");
    if (["5", "8", "10", "20", "50"].includes(requested)) return;

    const desired = window.innerWidth <= 768 ? 5
        : window.innerWidth <= 1024 ? 8 : 10;
    if (desired === 10 && requested === null) return;
    url.searchParams.set("page_size", String(desired));
    url.searchParams.set("page", "1");
    window.location.replace(url.toString());
});
