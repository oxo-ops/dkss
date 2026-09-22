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