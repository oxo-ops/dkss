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

    vehicleSearch.addEventListener("input", function () {
        clearTimeout(vehicleSearchTimer);

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

                        button.addEventListener(
                            "click",
                            function () {
                                vehicleId.value =
                                    vehicle.vehicle_id;

                                selectedVehicleDisplay.textContent =
                                    labelParts.join(" / ");
                            }
                        );

                        row.appendChild(button);
                        row.appendChild(label);

                        vehicleSearchResults.appendChild(row);
                    });
                });
        }, 300);
    });
});