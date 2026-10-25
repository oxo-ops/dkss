document.addEventListener("DOMContentLoaded", function () {
    const licenseArea =
        document.getElementById("license_area");

    const licenseRowTemplate =
        document.getElementById("licenseRowTemplate");

    const vehicleSearch =
        document.getElementById("vehicle_search");

    const vehicleSearchResults =
        document.getElementById("vehicle_search_results");

    const selectedVehiclesArea =
        document.getElementById("selected_vehicles");

    let vehicleSearchTimer = null;
    let vehicleSearchGeneration = 0;

    function updateSelectedVehicleCount() {
        const count = document.getElementById("selected_vehicle_count");
        if (count && selectedVehiclesArea) {
            count.textContent = selectedVehiclesArea.querySelectorAll(".selected-vehicle").length + "台";
        }
    }


    function addLicenseRow() {
        if (!licenseArea || !licenseRowTemplate) {
            return;
        }

        const row =
            licenseRowTemplate.content.firstElementChild.cloneNode(true);

        licenseArea.appendChild(row);
    }


    function removeLicenseRow(button) {
        const row = button.closest(".license-row");

        if (row) {
            row.remove();
        }
    }


    function removeSelectedVehicle(vehicleId) {
        if (!selectedVehiclesArea || !vehicleSearch) {
            return;
        }

        const row = document.querySelector(
            '.selected-vehicle[data-vehicle-id="' +
            CSS.escape(vehicleId) +
            '"]'
        );

        if (row) {
            row.remove();
        }

        if (
            document.querySelectorAll(".selected-vehicle").length === 0
        ) {
            const empty = document.createElement("span");
            empty.id = "no_selected_vehicle";
            empty.textContent = "未選択";

            selectedVehiclesArea.appendChild(empty);
        }

        vehicleSearch.dispatchEvent(
            new Event("input")
        );
        updateSelectedVehicleCount();
    }


    function addSelectedVehicle(vehicle) {
        if (!selectedVehiclesArea || !vehicleSearch) {
            return;
        }

        const exists = document.querySelector(
            '.selected-vehicle[data-vehicle-id="' +
            CSS.escape(String(vehicle.vehicle_record_id)) +
            '"]'
        );

        if (exists) {
            return;
        }

        const noSelected =
            document.getElementById("no_selected_vehicle");

        if (noSelected) {
            noSelected.remove();
        }

        const row = document.createElement("div");
        row.className = "selected-vehicle";
        row.dataset.vehicleId = vehicle.vehicle_record_id;

        const hiddenInput = document.createElement("input");
        hiddenInput.type = "hidden";
        hiddenInput.name = "vehicles";
        hiddenInput.value = vehicle.vehicle_record_id;

        const labelParts = [
            vehicle.number || "ナンバー未登録"
        ];

        const label = document.createElement("span");
        label.className = "driver-vehicle-number";
        label.textContent = labelParts.join(" / ");

        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className =
            "btn-small driver-vehicle-remove js-remove-selected-vehicle";
        removeButton.dataset.vehicleId = vehicle.vehicle_record_id;
        removeButton.textContent = "解除";
        removeButton.setAttribute("aria-label", label.textContent + "の選択を解除");

        row.appendChild(hiddenInput);
        row.appendChild(label);
        row.appendChild(removeButton);

        selectedVehiclesArea.appendChild(row);

        vehicleSearch.dispatchEvent(
            new Event("input")
        );
        updateSelectedVehicleCount();
    }


    if (vehicleSearch && vehicleSearchResults) {
        vehicleSearch.addEventListener("input", function () {
            clearTimeout(vehicleSearchTimer);
            const generation = ++vehicleSearchGeneration;
            vehicleSearchResults.replaceChildren();

            const keyword = vehicleSearch.value.trim();

            if (!keyword) {
                vehicleSearchResults.hidden = true;
                return;
            }

            vehicleSearchResults.hidden = false;
            const loading = document.createElement("p");
            loading.className = "help-text";
            loading.setAttribute("role", "status");
            loading.textContent = "検索中…";
            vehicleSearchResults.appendChild(loading);

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
                        if (generation !== vehicleSearchGeneration) return;
                        vehicleSearchResults.innerHTML = "";

                        if (!data.results || data.results.length === 0) {
                            const message =
                                document.createElement("p");

                            message.className = "help-text";
                            message.textContent =
                                "該当する車両がありません。";

                            vehicleSearchResults.appendChild(message);
                            return;
                        }

                        data.results.forEach(function (vehicle) {
                            const alreadySelected =
                                document.querySelector(
                                    '.selected-vehicle[data-vehicle-id="' +
                                    CSS.escape(String(vehicle.vehicle_record_id)) +
                                    '"]'
                                );

                            const row =
                                document.createElement("div");

                            row.className = "vehicle-option";

                            const button =
                                document.createElement("button");

                            button.type = "button";
                            button.className = "btn-small";
                            button.disabled = Boolean(alreadySelected);
                            button.textContent =
                                alreadySelected
                                    ? "選択済み"
                                    : "追加";
                            button.classList.add("driver-vehicle-add");
                            button.setAttribute("aria-label", (vehicle.number || "ナンバー未登録") + (alreadySelected ? "は選択済み" : "を追加"));

                            const labelParts = [
                                vehicle.number || "ナンバー未登録"
                            ];

                            const label =
                                document.createElement("span");
                            label.className = "vehicle-option-label";

                            label.textContent =
                                labelParts.join(" / ");

                            if (!alreadySelected) {
                                button.addEventListener(
                                    "click",
                                    function () {
                                        addSelectedVehicle(vehicle);
                                    }
                                );
                            }

                            row.appendChild(label);
                            row.appendChild(button);

                            vehicleSearchResults.appendChild(row);
                        });
                    })
                    .catch(function () {
                        if (generation !== vehicleSearchGeneration) return;
                        showCommonError(
                            "車両を取得できませんでした。通信状態を確認して、もう一度検索してください。"
                        );

                        vehicleSearchResults.innerHTML = "";

                        const message =
                            document.createElement("p");

                        message.className = "help-text";
                        message.textContent =
                            "車両を取得できませんでした。通信状態を確認して、もう一度検索してください。";

                        vehicleSearchResults.appendChild(
                            message
                        );
                    });
            }, 300);
        });
    }

    updateSelectedVehicleCount();


    document.addEventListener("click", function (event) {
        const addLicenseButton =
            event.target.closest(".js-add-license-row");

        if (addLicenseButton) {
            addLicenseRow();
            return;
        }

        const removeLicenseButton =
            event.target.closest(".js-remove-license-row");

        if (removeLicenseButton) {
            removeLicenseRow(removeLicenseButton);
            return;
        }

        const removeVehicleButton =
            event.target.closest(".js-remove-selected-vehicle");

        if (removeVehicleButton) {
            removeSelectedVehicle(
                removeVehicleButton.dataset.vehicleId
            );
        }
    });
});
