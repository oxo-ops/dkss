document.addEventListener("DOMContentLoaded", function () {
    const targetTypeInput =
        document.getElementById("target_type");

    const userArea =
        document.getElementById("user_target_area");

    const deliveryArea =
        document.getElementById("delivery_place_area");

    const targetButtons =
        document.querySelectorAll(".js-target-type-button");

    const filesInput =
        document.getElementById("files");

    const previewArea =
        document.getElementById("preview_area");

    const dateInput =
        document.getElementById("event_date");

    const manualSelect =
        document.getElementById("manual_select");

    const manualLink =
        document.getElementById("manual_link");

    const targetUserSearch =
        document.getElementById("target_user_search");

    const targetUserInput =
        document.getElementById("target_user");

    const driverSearchResults =
        document.getElementById("driver_search_results");

    const driverSearchData =
        document.getElementById("driver_search_data");

    const deliveryPlaceInput =
        document.getElementById("delivery_place");

    const deliveryPlaceSearchResults =
        document.getElementById("delivery_place_search_results");

    const deliveryPlaceSearchData =
        document.getElementById("delivery_place_search_data");

    function selectTargetType(type, button) {
        if (
            !targetTypeInput ||
            !userArea ||
            !deliveryArea
        ) {
            return;
        }

        targetTypeInput.value = type;

        targetButtons.forEach(function (item) {
            item.classList.remove("active");
        });

        button.classList.add("active");

        const isUser =
            type === "user";

        userArea.classList.toggle(
            "is-hidden",
            !isUser
        );

        deliveryArea.classList.toggle(
            "is-hidden",
            isUser
        );
    }


    function formatFileSize(bytes) {
        if (bytes < 1024) {
            return `${bytes} B`;
        }

        if (bytes < 1024 * 1024) {
            return `${(bytes / 1024).toFixed(1)} KB`;
        }

        if (bytes < 1024 * 1024 * 1024) {
            return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
        }

        return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
    }


    function previewFiles() {
        if (!filesInput || !previewArea) {
            return;
        }

        previewArea.replaceChildren();

        Array.from(filesInput.files || [])
            .forEach(function (file) {
                const fileBox =
                    document.createElement("div");

                fileBox.className =
                    "preview-item";

                const mediaArea =
                    document.createElement("div");

                mediaArea.className =
                    "preview-media";

                if (
                    file.type.startsWith("image/")
                ) {
                    const img =
                        document.createElement("img");

                    img.src =
                        URL.createObjectURL(file);

                    img.className =
                        "preview-image";

                    img.alt =
                        "選択した画像";

                    mediaArea.appendChild(img);

                } else if (
                    file.type.startsWith("video/")
                ) {
                    const video =
                        document.createElement("video");

                    video.src =
                        URL.createObjectURL(file);

                    video.className =
                        "preview-video";

                    video.controls = true;
                    video.preload = "metadata";

                    mediaArea.appendChild(video);

                } else {
                    const pdf =
                        document.createElement("div");

                    pdf.className =
                        "preview-file-icon";

                    pdf.textContent =
                        "PDF";

                    mediaArea.appendChild(pdf);
                }

                const info =
                    document.createElement("div");

                info.className =
                    "preview-info";

                const name =
                    document.createElement("p");

                name.className =
                    "preview-file-name";

                name.textContent =
                    file.name;

                const size =
                    document.createElement("p");

                size.className =
                    "preview-file-size";

                size.textContent =
                    formatFileSize(file.size);

                info.appendChild(name);
                info.appendChild(size);

                fileBox.appendChild(mediaArea);
                fileBox.appendChild(info);

                previewArea.appendChild(
                    fileBox
                );
            });
    }


    function updateManualLink() {
        if (!manualSelect || !manualLink) {
            return;
        }

        const url =
            manualSelect.value;

        if (!url) {
            manualLink.removeAttribute("href");
            manualLink.classList.add(
                "is-hidden"
            );

            return;
        }

        manualLink.href = url;

        manualLink.classList.remove(
            "is-hidden"
        );
    }


    targetButtons.forEach(function (button) {
        button.addEventListener(
            "click",
            function () {
                selectTargetType(
                    button.dataset.targetType,
                    button
                );
            }
        );
    });


    filesInput?.addEventListener(
        "change",
        previewFiles
    );


    manualSelect?.addEventListener(
        "change",
        updateManualLink
    );

    function updateDriverSearchResults() {
        if (
            !targetUserSearch ||
            !targetUserInput ||
            !driverSearchResults ||
            !driverSearchData
        ) {
            return;
        }

        const keyword =
            targetUserSearch.value
                .trim()
                .toLowerCase();

        targetUserInput.value = "";
        driverSearchResults.replaceChildren();

        if (!keyword) {
            driverSearchResults.classList.add(
                "is-hidden"
            );
            return;
        }

        const drivers =
            Array.from(
                driverSearchData.querySelectorAll(
                    "[data-name][data-employee-id]"
                )
            );

        const matchedDrivers =
            drivers.filter(function (driver) {
                const name =
                    String(
                        driver.dataset.name || ""
                    ).toLowerCase();

                const employeeId =
                    String(
                        driver.dataset.employeeId || ""
                    ).toLowerCase();

                return (
                    name.includes(keyword) ||
                    employeeId.includes(keyword)
                );
            });

        matchedDrivers.forEach(function (driver) {
            const button =
                document.createElement("button");

            button.type = "button";
            button.className = "target-user-option";
            button.textContent =
                driver.dataset.name || "";



            button.addEventListener(
                "click",
                function () {
                    targetUserSearch.value =
                        driver.dataset.name || "";

                    targetUserInput.value =
                        driver.dataset.employeeId || "";

                    driverSearchResults.replaceChildren();

                    driverSearchResults.classList.add(
                        "is-hidden"
                    );
                }
            );

            driverSearchResults.appendChild(button);
        });

        driverSearchResults.classList.toggle(
            "is-hidden",
            matchedDrivers.length === 0
        );
    }

    function updateDeliveryPlaceSearchResults() {
        if (
            !deliveryPlaceInput ||
            !deliveryPlaceSearchResults ||
            !deliveryPlaceSearchData
        ) {
            return;
        }

        const keyword =
            deliveryPlaceInput.value
                .trim()
                .toLowerCase();

        deliveryPlaceSearchResults.replaceChildren();

        if (!keyword) {
            deliveryPlaceSearchResults.classList.add(
                "is-hidden"
            );
            return;
        }

        const places =
            Array.from(
                deliveryPlaceSearchData.querySelectorAll(
                    "[data-name]"
                )
            );

        const matchedPlaces =
            places.filter(function (place) {
                const name =
                    String(
                        place.dataset.name || ""
                    ).toLowerCase();

                return name.includes(keyword);
            });

        matchedPlaces.forEach(function (place) {
            const button =
                document.createElement("button");

            button.type = "button";
            button.className = "target-user-option";
            button.textContent =
                place.dataset.name || "";

            button.addEventListener(
                "click",
                function () {
                    deliveryPlaceInput.value =
                        place.dataset.name || "";

                    deliveryPlaceSearchResults.replaceChildren();
                    deliveryPlaceSearchResults.classList.add(
                        "is-hidden"
                    );
                }
            );

            deliveryPlaceSearchResults.appendChild(button);
        });

        deliveryPlaceSearchResults.classList.toggle(
            "is-hidden",
            matchedPlaces.length === 0
        );
    }

    deliveryPlaceInput?.addEventListener(
        "input",
        updateDeliveryPlaceSearchResults
    );

    deliveryPlaceInput?.addEventListener(
        "focus",
        updateDeliveryPlaceSearchResults
    );

    deliveryPlaceInput?.addEventListener(
        "compositionend",
        updateDeliveryPlaceSearchResults
    );

    targetUserSearch?.addEventListener(
        "input",
        updateDriverSearchResults
    );

    targetUserSearch?.addEventListener(
        "focus",
        updateDriverSearchResults
    );

    targetUserSearch?.addEventListener(
        "compositionend",
        updateDriverSearchResults
    );

    if (
        targetUserSearch &&
        targetUserInput &&
        driverSearchData &&
        targetUserInput.value
    ) {
        const selectedDriver =
            Array.from(
                driverSearchData.querySelectorAll(
                    "[data-name][data-employee-id]"
                )
            ).find(function (driver) {
                return (
                    driver.dataset.employeeId ===
                    targetUserInput.value
                );
            });

        if (selectedDriver) {
            targetUserSearch.value =
                selectedDriver.dataset.name || "";
        }
    }

    if (
        dateInput &&
        !dateInput.value
    ) {
        const today =
            new Date()
                .toISOString()
                .split("T")[0];

        dateInput.value = today;
    }


    document.addEventListener("click", function (event) {
        if (
            !event.target.closest("#target_user_search") &&
            !event.target.closest("#driver_search_results")
        ) {
            driverSearchResults?.classList.add("is-hidden");
        }

        if (
            !event.target.closest("#delivery_place") &&
            !event.target.closest("#delivery_place_search_results")
        ) {
            deliveryPlaceSearchResults?.classList.add("is-hidden");
        }
    });

    updateManualLink();
});