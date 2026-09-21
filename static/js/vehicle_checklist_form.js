document.addEventListener("DOMContentLoaded", function () {
    const vehicleSearch =
        document.getElementById("vehicle_search");

    const vehicleSearchResults =
        document.getElementById("vehicle_search_results");

    const vehicleId =
        document.getElementById("vehicle_id");

    const selectedVehicleDisplay =
        document.getElementById("selected_vehicle_display");

    if (
        !vehicleSearch ||
        !vehicleSearchResults ||
        !vehicleId ||
        !selectedVehicleDisplay
    ) {
        return;
    }

    let vehicleSearchTimer = null;

    function showMessage(message) {
        vehicleSearchResults.innerHTML = "";

        const paragraph =
            document.createElement("p");

        paragraph.className = "help-text";
        paragraph.textContent = message;

        vehicleSearchResults.appendChild(paragraph);
    }

    vehicleSearch.addEventListener(
        "keydown",
        function (event) {
            if (event.key === "Enter") {
                event.preventDefault();
            }
        }
    );

    vehicleSearch.addEventListener("input", function () {
        clearTimeout(vehicleSearchTimer);

        vehicleId.value = "";
        selectedVehicleDisplay.textContent =
            "未選択";

        vehicleSearchResults.classList.remove(
            "is-selected"
        );

        const keyword =
            vehicleSearch.value.trim();

        if (!keyword) {
            showMessage("車両を検索してください。");
            return;
        }

        vehicleSearchTimer = setTimeout(function () {
            fetch(
                "/api/vehicles?q=" +
                encodeURIComponent(keyword)
            )
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error(
                            "HTTP " + response.status
                        );
                    }

                    return response.json();
                })
                .then(function (data) {
                    vehicleSearchResults.innerHTML = "";

                    if (!data.results || data.results.length === 0) {
                        showMessage("該当する車両がありません。");
                        return;
                    }

                    data.results.forEach(function (vehicle) {
                        const row =
                            document.createElement("div");

                        const button =
                            document.createElement("button");

                        const label =
                            document.createElement("span");

                        const labelParts = [
                            vehicle.vehicle_id,
                            vehicle.number,
                            vehicle.manufacturer,
                            vehicle.model_code
                        ].filter(Boolean);

                        row.className =
                            "vehicle-option";

                        button.type =
                            "button";

                        button.className =
                            "btn-small";

                        button.textContent =
                            "選択";

                        label.textContent =
                            labelParts.join(" / ");

                        function selectVehicle() {
                            vehicleId.value =
                                vehicle.vehicle_id;

                            const selectedLabel =
                                labelParts.join(" / ");

                            selectedVehicleDisplay.textContent =
                                selectedLabel;

                            vehicleSearch.value =
                                selectedLabel;

                            vehicleSearchResults.innerHTML = "";

                            showMessage(
                                "対象車両を選択しました。"
                            );

                            vehicleSearchResults.classList.add(
                                "is-selected"
                            );

                            vehicleSearch.dispatchEvent(
                                new Event("change", {
                                    bubbles: true
                                })
                            );
                        }

                        button.addEventListener(
                            "click",
                            function (event) {
                                event.stopPropagation();
                                selectVehicle();
                            }
                        );

                        row.addEventListener(
                            "click",
                            selectVehicle
                        );

                        row.appendChild(button);
                        row.appendChild(label);

                        vehicleSearchResults.appendChild(row);
                    });
                })
                .catch(function () {
                    showMessage(
                        "車両を取得できませんでした。通信状態を確認して、もう一度検索してください。"
                    );
                });
        }, 300);
    });

    const form = vehicleSearch.closest("form");

    const submitButton = form
        ? form.querySelector('button[type="submit"]')
        : null;

    let validationMessageShown = false;

    if (submitButton) {
        submitButton.addEventListener("click", function () {
            validationMessageShown = false;
        });
    }

    if (form) {
        form.addEventListener(
            "invalid",
            function (event) {
                event.preventDefault();

                if (validationMessageShown) {
                    return;
                }

                validationMessageShown = true;

                const field = event.target;
                let message = "必須項目を入力してください。";

                if (
                    field.name &&
                    field.name.startsWith("answer_")
                ) {
                    message = "評価を選択してください。";
                }

                window.alert(message);

                const target =
                    field.closest("tr") ||
                    field.closest(".form-group") ||
                    field;

                target.scrollIntoView({
                    behavior: "smooth",
                    block: "center"
                });

                window.setTimeout(function () {
                    field.focus();
                }, 300);
            },
            true
        );

        form.addEventListener("submit", function (event) {
            if (vehicleId.value) {
                return;
            }

            event.preventDefault();

            window.alert(
                "候補から対象車両を選択してください。"
            );

            vehicleSearch.scrollIntoView({
                behavior: "smooth",
                block: "center"
            });

            window.setTimeout(function () {
                vehicleSearch.focus();
            }, 300);
        });
    }
});