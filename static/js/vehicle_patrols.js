document.addEventListener("DOMContentLoaded", function () {
    const searchInput =
        document.getElementById("usage_vehicle_search");

    const vehicleIdInput =
        document.getElementById("usage_vehicle_id");

    const resultBox =
        document.getElementById("usage_vehicle_results");

    const form =
        searchInput ? searchInput.closest("form") : null;

    function hideResults() {
        if (!resultBox) {
            return;
        }

        resultBox.classList.add("is-hidden");
    }

    function showResults() {
        if (!resultBox) {
            return;
        }

        resultBox.classList.remove("is-hidden");
    }

    function clearResults() {
        if (!resultBox) {
            return;
        }

        resultBox.innerHTML = "";
    }

    function showMessage(message) {
        if (!resultBox) {
            return;
        }

        clearResults();

        const paragraph =
            document.createElement("p");

        paragraph.className =
            "help-text";

        paragraph.textContent =
            message;

        resultBox.appendChild(paragraph);

        showResults();
    }

    if (
        searchInput &&
        vehicleIdInput &&
        resultBox &&
        form
    ) {
        let searchTimer = null;

        searchInput.addEventListener("input", function () {
            clearTimeout(searchTimer);

            vehicleIdInput.value = "";

            const keyword =
                searchInput.value.trim();

            if (!keyword) {
                clearResults();
                hideResults();
                return;
            }

            searchTimer = setTimeout(function () {
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
                        clearResults();

                        if (
                            !data.results ||
                            data.results.length === 0
                        ) {
                            showMessage(
                                "該当する車両がありません。"
                            );
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
                                    vehicleIdInput.value =
                                        vehicle.vehicle_record_id;

                                    searchInput.value =
                                        labelParts.join(" / ");

                                    clearResults();
                                    hideResults();
                                }
                            );

                            row.appendChild(button);
                            row.appendChild(label);

                            resultBox.appendChild(row);
                        });

                        showResults();
                    })
                    .catch(function () {
                        showMessage(
                            "車両を取得できませんでした。通信状態を確認して、もう一度検索してください。"
                        );

                        showResults();
                    });
            }, 250);
        });

        form.addEventListener("submit", function (event) {
            if (!vehicleIdInput.value) {
                event.preventDefault();

                window.alert(
                    "候補から車両を選択してください。"
                );

                searchInput.focus();
            }
        });
    }

    document
        .querySelectorAll(".js-vehicle-patrol-delete-form")
        .forEach(function (deleteForm) {
            deleteForm.addEventListener(
                "submit",
                function (event) {
                    if (!window.confirm("削除しますか？")) {
                        event.preventDefault();
                    }
                }
            );
        });
});