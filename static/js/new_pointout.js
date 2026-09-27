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

    function prepareNextPointoutFileInput(input) {
        if (!input.files || input.files.length === 0) {
            return;
        }

        const label =
            input.closest(".file-upload-button");

        if (!label) {
            return;
        }

        const nextInput =
            input.cloneNode();

        nextInput.value = "";

        label.parentNode.insertBefore(
            input,
            label
        );

        label.appendChild(nextInput);
    }

    function removeSelectedPointoutFile(
        fileInput,
        fileIndex
    ) {
        if (!fileInput.files) {
            return;
        }

        const cell =
            fileInput.closest(".file-upload-cell");

        if (!cell) {
            return;
        }

        const transfer =
            new DataTransfer();

        Array.from(
            fileInput.files
        ).forEach(function (file, index) {
            if (index !== fileIndex) {
                transfer.items.add(file);
            }
        });

        fileInput.files =
            transfer.files;

        if (fileInput.files.length === 0) {
            fileInput.remove();
        }

        const remainingInput =
            cell.querySelector(
                ".js-file-upload-input"
            );

        if (remainingInput) {
            showSelectedPointoutFiles(
                remainingInput
            );
        } else {
            cell.querySelector(
                ".selected-file-names"
            )?.replaceChildren();
        }
    }


    function showSelectedPointoutFiles(
        input,
        showAll = false
    ) {
        const cell =
            input.closest(".file-upload-cell");

        if (!cell) {
            return;
        }

        const area =
            cell.querySelector(
                ".selected-file-names"
            );

        if (!area) {
            return;
        }

        area.replaceChildren();

        area.classList.toggle(
            "is-expanded",
            showAll
        );

        const visibleEntries =
            [];

        cell.querySelectorAll(
            ".js-file-upload-input"
        ).forEach(function (fileInput) {
            Array.from(
                fileInput.files || []
            ).forEach(function (
                file,
                fileIndex
            ) {
                visibleEntries.push({
                    file: file,
                    fileInput: fileInput,
                    fileIndex: fileIndex
                });
            });
        });

        const entriesToShow =
            showAll
                ? visibleEntries
                : visibleEntries.slice(0, 2);

        entriesToShow.forEach(function (entry) {
            const file =
                entry.file;

            const item =
                document.createElement("div");

            item.className =
                "selected-file-preview";

            if (
                file.type.startsWith("image/")
            ) {
                const image =
                    document.createElement("img");

                image.className =
                    "selected-file-preview-image";

                image.alt = file.name;

                const objectUrl =
                    URL.createObjectURL(file);

                image.src = objectUrl;

                image.addEventListener(
                    "load",
                    function () {
                        URL.revokeObjectURL(
                            objectUrl
                        );
                    }
                );

                item.appendChild(image);
            } else {
                const name =
                    document.createElement("div");

                name.className =
                    "selected-file-preview-name";

                name.textContent =
                    file.name;

                item.appendChild(name);
            }

            const removeButton =
                document.createElement("button");

            removeButton.type = "button";
            removeButton.className =
                "selected-file-preview-remove";

            removeButton.textContent = "×";

            removeButton.setAttribute(
                "aria-label",
                file.name + " を削除"
            );

            removeButton.addEventListener(
                "click",
                function () {
                    removeSelectedPointoutFile(
                        entry.fileInput,
                        entry.fileIndex
                    );
                }
            );

            item.appendChild(removeButton);

            area.appendChild(item);
        });

        if (
            !showAll &&
            visibleEntries.length > 2
        ) {
            const more =
                document.createElement("button");

            more.type = "button";

            more.className =
                "selected-file-more";

            more.textContent =
                "＋" +
                (visibleEntries.length - 2) +
                "件";

            more.addEventListener(
                "click",
                function () {
                    showSelectedPointoutFiles(
                        input,
                        true
                    );
                }
            );

            area.appendChild(more);
        }

        if (
            showAll &&
            visibleEntries.length > 2
        ) {
            const collapse =
                document.createElement("button");

            collapse.type = "button";

            collapse.className =
                "selected-file-collapse";

            collapse.textContent =
                "閉じる";

            collapse.addEventListener(
                "click",
                function () {
                    showSelectedPointoutFiles(
                        input,
                        false
                    );
                }
            );

            area.appendChild(collapse);
        }
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


    document.addEventListener(
        "change",
        function (event) {
            if (
                event.target.matches(
                    ".js-file-upload-input"
                )
            ) {
                showSelectedPointoutFiles(
                    event.target
                );

                prepareNextPointoutFileInput(
                    event.target
                );
            }
        }
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

        if (
            document.activeElement === targetUserSearch &&
            targetUserSearch.dataset.selectedEmployeeId &&
            targetUserSearch.value !==
                targetUserSearch.dataset.selectedName
        ) {
            targetUserInput.value = "";
            targetUserSearch.dataset.selectedEmployeeId = "";
            targetUserSearch.dataset.selectedName = "";
        }

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

                    targetUserSearch.dataset.selectedEmployeeId =
                        driver.dataset.employeeId || "";

                    targetUserSearch.dataset.selectedName =
                        driver.dataset.name || "";

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

            targetUserSearch.dataset.selectedEmployeeId =
                selectedDriver.dataset.employeeId || "";

            targetUserSearch.dataset.selectedName =
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