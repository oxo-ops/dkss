document.addEventListener("DOMContentLoaded", function () {
    const bulkField =
        document.getElementById("bulk-field");

    const bulkOldValue =
        document.getElementById("bulk-old-value");

    const bulkNewValue =
        document.getElementById("bulk-new-value");

    const bulkOldVehicleType =
        document.getElementById("bulk-old-vehicle-type");

    const bulkNewVehicleType =
        document.getElementById("bulk-new-vehicle-type");

    const importModal =
        document.getElementById("import-confirm-modal");


    function toggleBulkVehicleTypeInputs() {
        if (
            !bulkField ||
            !bulkOldValue ||
            !bulkNewValue ||
            !bulkOldVehicleType ||
            !bulkNewVehicleType
        ) {
            return;
        }

        const isVehicleType =
            bulkField.value === "vehicle_type";

        bulkOldValue.classList.toggle(
            "is-hidden",
            isVehicleType
        );

        bulkNewValue.classList.toggle(
            "is-hidden",
            isVehicleType
        );

        bulkOldVehicleType.classList.toggle(
            "is-hidden",
            !isVehicleType
        );

        bulkNewVehicleType.classList.toggle(
            "is-hidden",
            !isVehicleType
        );
    }


    function getRowEditableValues(row) {
        return Array.from(
            row.querySelectorAll(
                'input:not([type="hidden"]), select'
            )
        ).map(function (input) {
            return String(
                input.value || ""
            ).trim();
        });
    }


    function getImportKey(row) {
        const chassisNumber = String(
            row.querySelector(
                '[name="chassis_number"]'
            )?.value || ""
        ).trim();

        if (chassisNumber) {
            return "chassis:" + chassisNumber;
        }

        const plateArea = String(
            row.querySelector(
                '[name="plate_area"]'
            )?.value || ""
        ).trim();

        const plateClass = String(
            row.querySelector(
                '[name="plate_class"]'
            )?.value || ""
        ).trim();

        const plateKana = String(
            row.querySelector(
                '[name="plate_kana"]'
            )?.value || ""
        ).trim();

        const plateNumber = String(
            row.querySelector(
                '[name="plate_number"]'
            )?.value || ""
        ).trim();

        return [
            "plate",
            plateArea,
            plateClass,
            plateKana,
            plateNumber
        ].join(":");
    }


    function setStatusCell(
        statusCell,
        status
    ) {
        if (!statusCell) {
            return;
        }

        statusCell.replaceChildren();

        const strong =
            document.createElement("strong");

        if (status === "新規") {
            strong.className =
                "vehicle-import-status-new";

        } else if (status === "更新") {
            strong.className =
                "vehicle-import-status-update";

        } else if (
            status === "変更なし"
        ) {
            strong.className =
                "vehicle-import-status-unchanged";

        } else {
            strong.className =
                "vehicle-import-status-duplicate";
        }

        strong.textContent = status;

        statusCell.appendChild(strong);
    }


    function updateImportStatuses() {
        let newCount = 0;
        let updateCount = 0;
        let unchangedCount = 0;
        let duplicateCount = 0;

        const seenImportKeys =
            new Set();

        document
            .querySelectorAll(".import-row")
            .forEach(function (row) {
                const baseStatus =
                    row.dataset.baseStatus;

                const statusCell =
                    row.querySelector(
                        ".import-status-cell"
                    );

                let currentStatus =
                    baseStatus;

                const importKey =
                    getImportKey(row);

                if (
                    seenImportKeys.has(
                        importKey
                    )
                ) {
                    currentStatus =
                        "Excel内重複";

                } else {
                    seenImportKeys.add(
                        importKey
                    );

                    if (
                        baseStatus ===
                        "変更なし"
                    ) {
                        const currentValues =
                            getRowEditableValues(
                                row
                            );

                        const initialValues =
                            JSON.parse(
                                row.dataset
                                    .initialValues ||
                                "[]"
                            );

                        const changed =
                            JSON.stringify(
                                currentValues
                            ) !==
                            JSON.stringify(
                                initialValues
                            );

                        currentStatus =
                            changed
                                ? "更新"
                                : "変更なし";
                    }
                }

                setStatusCell(
                    statusCell,
                    currentStatus
                );

                if (
                    currentStatus ===
                    "新規"
                ) {
                    newCount += 1;

                } else if (
                    currentStatus ===
                    "更新"
                ) {
                    updateCount += 1;

                } else if (
                    currentStatus ===
                    "変更なし"
                ) {
                    unchangedCount += 1;

                } else {
                    duplicateCount += 1;
                }
            });


        const countNew =
            document.getElementById(
                "count-new"
            );

        const countUpdate =
            document.getElementById(
                "count-update"
            );

        const countUnchanged =
            document.getElementById(
                "count-unchanged"
            );

        const countDuplicate =
            document.getElementById(
                "count-duplicate"
            );

        const modalCountNew =
            document.getElementById(
                "modal-count-new"
            );

        const modalCountUpdate =
            document.getElementById(
                "modal-count-update"
            );

        const modalCountUnchanged =
            document.getElementById(
                "modal-count-unchanged"
            );

        const modalCountDuplicate =
            document.getElementById(
                "modal-count-duplicate"
            );


        if (countNew) {
            countNew.textContent =
                newCount;
        }

        if (countUpdate) {
            countUpdate.textContent =
                updateCount;
        }

        if (countUnchanged) {
            countUnchanged.textContent =
                unchangedCount;
        }

        if (countDuplicate) {
            countDuplicate.textContent =
                duplicateCount;
        }

        if (modalCountNew) {
            modalCountNew.textContent =
                newCount;
        }

        if (modalCountUpdate) {
            modalCountUpdate.textContent =
                updateCount;
        }

        if (modalCountUnchanged) {
            modalCountUnchanged.textContent =
                unchangedCount;
        }

        if (modalCountDuplicate) {
            modalCountDuplicate.textContent =
                duplicateCount;
        }
    }


    function bulkReplace() {
        if (!bulkField) {
            return;
        }

        const field =
            bulkField.value;

        const oldValue =
            field === "vehicle_type"
                ? bulkOldVehicleType.value
                : bulkOldValue.value;

        const newValue =
            field === "vehicle_type"
                ? bulkNewVehicleType.value
                : bulkNewValue.value;


        if (
            field !== "vehicle_type" &&
            !oldValue
        ) {
            alert(
                "現在の値を入力してください。"
            );

            return;
        }


        if (
            field === "plate_full"
        ) {
            alert(
                "車番は地域名・分類番号・ひらがな・番号に分かれているため、" +
                "個別編集してください。"
            );

            return;
        }


        const inputs =
            document.querySelectorAll(
                ".bulk-" + field
            );

        let changedCount = 0;


        inputs.forEach(
            function (input) {
                if (
                    String(
                        input.value
                    ).trim() ===
                    String(
                        oldValue
                    ).trim()
                ) {
                    input.value =
                        newValue;

                    changedCount += 1;
                }
            }
        );


        updateImportStatuses();

        alert(
            changedCount +
            "件変更しました。"
        );
    }


    function openImportConfirm() {
        if (!importModal) {
            return;
        }

        updateImportStatuses();

        importModal.classList.remove(
            "is-hidden"
        );

        importModal.classList.add(
            "is-open"
        );
    }


    function closeImportConfirm() {
        if (!importModal) {
            return;
        }

        importModal.classList.remove(
            "is-open"
        );

        importModal.classList.add(
            "is-hidden"
        );
    }


    bulkField?.addEventListener(
        "change",
        toggleBulkVehicleTypeInputs
    );


    document.addEventListener(
        "click",
        function (event) {
            const bulkReplaceButton =
                event.target.closest(
                    ".js-bulk-replace"
                );

            if (bulkReplaceButton) {
                bulkReplace();
                return;
            }


            const openButton =
                event.target.closest(
                    ".js-open-import-confirm"
                );

            if (openButton) {
                openImportConfirm();
                return;
            }


            const closeButton =
                event.target.closest(
                    ".js-close-import-confirm"
                );

            if (closeButton) {
                closeImportConfirm();
            }
        }
    );


    document
        .querySelectorAll(".import-row")
        .forEach(function (row) {
            row.dataset.initialValues =
                JSON.stringify(
                    getRowEditableValues(
                        row
                    )
                );

            row.querySelectorAll(
                'input:not([type="hidden"]), select'
            ).forEach(
                function (input) {
                    input.addEventListener(
                        "input",
                        updateImportStatuses
                    );

                    input.addEventListener(
                        "change",
                        updateImportStatuses
                    );
                }
            );
        });


    toggleBulkVehicleTypeInputs();
    updateImportStatuses();
});