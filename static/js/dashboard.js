document.addEventListener("DOMContentLoaded", function () {
document.querySelectorAll(".dashboard-auto-submit").forEach(function (select) {
    select.addEventListener("change", function () {
        select.form.submit();
    });
});
document.querySelectorAll(".dashboard-analysis-card").forEach(function (card) {
    card.addEventListener("click", function (event) {
        if (event.target.closest("a")) {
            return;
        }

        window.location.href = card.dataset.url;
    });
});
document.querySelectorAll(".dashboard-click-card, .dashboard-click-row").forEach(function (element) {
    element.addEventListener("click", function (event) {
        if (event.target.closest("a, button")) {
            return;
        }

        window.location.href = element.dataset.url;
    });
});
    const customizeButton =
        document.getElementById("dashboardCustomizeButton");

    const customizePanel =
        document.getElementById("dashboardCustomizePanel");

    const vehicleAddButton =
        document.getElementById("dashboardVehicleAddButton");

    const vehicleAddArea =
        document.getElementById("dashboardVehicleAddArea");

    if (vehicleAddButton && vehicleAddArea) {
        vehicleAddButton.addEventListener("click", function () {
            vehicleAddArea.classList.toggle("is-open");
        });
    }
    if (customizeButton && customizePanel) {

        function closeCustomizePanel() {
            customizePanel.classList.remove("is-open");
            customizeButton.setAttribute(
                "aria-expanded",
                "false"
            );
        }

        customizeButton.addEventListener(
            "click",
            function (event) {

                event.stopPropagation();

                const willOpen =
                    !customizePanel.classList.contains(
                        "is-open"
                    );

                customizePanel.classList.toggle(
                    "is-open",
                    willOpen
                );

                customizeButton.setAttribute(
                    "aria-expanded",
                    willOpen ? "true" : "false"
                );
            }
        );

        customizePanel.addEventListener(
            "click",
            function (event) {
                event.stopPropagation();
            }
        );

        document.addEventListener(
            "click",
            closeCustomizePanel
        );

        document.addEventListener(
            "keydown",
            function (event) {

                if (event.key === "Escape") {
                    closeCustomizePanel();
                }
            }
        );
    }

    const searchInput = document.getElementById("dashboardVehicleSearch");
    const vehicleIdInput = document.getElementById("dashboardVehicleId");
    const resultBox = document.getElementById("dashboardVehicleResults");
    const form = document.getElementById("dashboardVehicleForm");

    if (!searchInput || !vehicleIdInput || !resultBox || !form) {
        return;
    }

    let searchTimer = null;

    searchInput.addEventListener("input", function () {
        clearTimeout(searchTimer);

        vehicleIdInput.value = "";

        const keyword = searchInput.value.trim();

        if (!keyword) {
            resultBox.innerHTML = "";
            resultBox.classList.remove("is-open");
            return;
        }

        searchTimer = setTimeout(function () {
            fetch("/api/vehicles?q=" + encodeURIComponent(keyword))
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error(
                            "HTTP " + response.status
                        );
                    }

                    return response.json();
                })
                .then(data => {
                    resultBox.innerHTML = "";

                    if (!data.results || data.results.length === 0) {
                        resultBox.innerHTML =
                            '<p class="help-text dashboard-vehicle-empty-result">該当する車両がありません。</p>';

                        resultBox.classList.add("is-open");
                        return;
                    }

                    data.results.forEach(function (vehicle) {
                        const row = document.createElement("div");

                        row.className = "dashboard-vehicle-result-row";

                        const labelParts = [
                            vehicle.vehicle_id,
                            vehicle.number,
                            vehicle.manufacturer,
                            vehicle.model_code
                        ].filter(Boolean);

                        const label = document.createElement("span");
                        label.textContent = labelParts.join(" / ");

                        const button = document.createElement("button");
                        button.type = "button";
                        button.title = "使用車両に追加";
                        button.setAttribute("aria-label", "使用車両に追加");
                        button.className = "dashboard-vehicle-result-add-button";

                        button.textContent = "＋";

                        button.addEventListener("click", function () {
                            vehicleIdInput.value = vehicle.vehicle_id;
                            form.submit();
                        });

                        row.addEventListener("click", function (event) {
                            if (event.target === button) {
                                return;
                            }

                            vehicleIdInput.value = vehicle.vehicle_id;
                            form.submit();
                        });

                        row.appendChild(label);
                        row.appendChild(button);

                        resultBox.appendChild(row);
                    });

                    resultBox.classList.add("is-open");
                })
                .catch(function () {
                    resultBox.innerHTML =
                        '<p class="help-text dashboard-vehicle-empty-result">' +
                        '車両を取得できませんでした。通信状態を確認して、もう一度検索してください。' +
                        '</p>';

                    resultBox.classList.add("is-open");
                });

        }, 250);
    });

    document.addEventListener("click", function (event) {
        if (
            !searchInput.contains(event.target) &&
            !resultBox.contains(event.target)
        ) {
            resultBox.classList.remove("is-open");
        }
    });

    form.addEventListener("submit", function (event) {
        if (!vehicleIdInput.value) {
            event.preventDefault();

            alert("候補から車両を選択してください。");
            searchInput.focus();
        }
    });
});
