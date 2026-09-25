document.addEventListener("DOMContentLoaded", function () {
    const vehicleSearch =
        document.getElementById("vehicle_search");

    const vehicleSearchResults =
        document.getElementById("vehicle_search_results");

    const vehicleId =
        document.getElementById("vehicle_record_id");

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
                            vehicle.chassis_number,
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
                                    vehicle.vehicle_record_id;

                                selectedVehicleDisplay.textContent =
                                    labelParts.join(" / ");
                            }
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
});