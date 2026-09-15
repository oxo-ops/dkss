document.addEventListener("DOMContentLoaded", function () {
    const targetType =
        document.getElementById("target_type");

    const targetUserArea =
        document.getElementById("target_user_area");

    const targetVehicleArea =
        document.getElementById("target_vehicle_area");

    const targetOfficeArea =
        document.getElementById("target_office_area");

    const vehicleSearchInput =
        document.getElementById("vehicle_search");

    const vehicleSearchResults =
        document.getElementById("vehicle_search_results");

    const targetVehicle =
        document.getElementById("target_vehicle");

    const selectedVehicleDisplay =
        document.getElementById("selected_vehicle_display");

    let vehicleSearchTimer = null;


    function showSelectedFiles(input) {
        const area = input
            .closest(".file-upload-cell")
            ?.querySelector(".selected-file-names");

        if (!area) {
            return;
        }

        area.innerHTML = "";

        if (!input.files || input.files.length === 0) {
            return;
        }

        Array.from(input.files).forEach(function (file) {
            const item = document.createElement("div");
            item.textContent = file.name;
            area.appendChild(item);
        });
    }


    function selectVehicle(vehicle) {
        if (
            !targetVehicle ||
            !selectedVehicleDisplay ||
            !vehicleSearchResults ||
            !vehicleSearchInput
        ) {
            return;
        }

        targetVehicle.value = vehicle.vehicle_id;

        selectedVehicleDisplay.textContent = [
            vehicle.vehicle_id,
            vehicle.number || "",
            vehicle.manufacturer || "",
            vehicle.model_code || ""
        ].join(" / ");

        vehicleSearchResults.innerHTML = "";
        vehicleSearchInput.value = "";
    }


    function searchVehicles() {
        if (!vehicleSearchInput || !vehicleSearchResults) {
            return;
        }

        const keyword = vehicleSearchInput.value.trim();

        if (!keyword) {
            vehicleSearchResults.innerHTML = "";
            return;
        }

        fetch(
            "/api/vehicles?q=" +
            encodeURIComponent(keyword)
        )
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                vehicleSearchResults.innerHTML = "";

                if (!data.results || data.results.length === 0) {
                    const empty = document.createElement("div");
                    empty.textContent =
                        "該当する車両はありません。";

                    vehicleSearchResults.appendChild(empty);
                    return;
                }

                data.results.forEach(function (vehicle) {
                    const row =
                        document.createElement("div");

                    row.className =
                        "vehicle-search-result-row";

                    row.textContent = [
                        vehicle.vehicle_id,
                        vehicle.number || "",
                        vehicle.manufacturer || "",
                        vehicle.model_code || ""
                    ].join(" / ");

                    row.addEventListener(
                        "click",
                        function () {
                            selectVehicle(vehicle);
                        }
                    );

                    vehicleSearchResults.appendChild(row);
                });
            });
    }


    function switchChecklistTarget() {
        if (!targetType) {
            return;
        }

        const type = targetType.value;

        if (targetUserArea) {
            targetUserArea.classList.toggle(
                "is-hidden",
                type !== "user"
            );
        }

        if (targetVehicleArea) {
            targetVehicleArea.classList.toggle(
                "is-hidden",
                type !== "vehicle"
            );
        }

        if (targetOfficeArea) {
            targetOfficeArea.classList.toggle(
                "is-hidden",
                type !== "office"
            );
        }
    }


    targetType?.addEventListener(
        "change",
        switchChecklistTarget
    );


    document.addEventListener(
        "change",
        function (event) {
            if (
                event.target.matches(
                    ".js-file-upload-input"
                )
            ) {
                showSelectedFiles(event.target);
            }
        }
    );


    if (vehicleSearchInput) {
        vehicleSearchInput.addEventListener(
            "input",
            function () {
                clearTimeout(vehicleSearchTimer);

                vehicleSearchTimer =
                    setTimeout(
                        searchVehicles,
                        300
                    );
            }
        );
    }


    switchChecklistTarget();
});