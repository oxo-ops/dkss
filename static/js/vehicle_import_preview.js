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


    const vehiclePlateCandidates = JSON.parse(
        document.getElementById("vehicle-plate-candidates")
            ?.textContent || "[]"
    );

    function normalizeImportPlate(value) {
        return String(value || "")
            .normalize("NFKC")
            .trim()
            .replace(/[\s\-‐‑‒–—―−・･.]+/gu, "")
            .toLowerCase();
    }

    function getImportPlateKey(parts) {
        const normalized = parts.map(normalizeImportPlate);
        return normalized.every(Boolean)
            ? JSON.stringify(normalized)
            : "";
    }

    function refreshVehiclePlateResolutions() {
        const area = document.getElementById(
            "vehicle-plate-resolution-area"
        );
        if (!area) {
            return;
        }

        const plateFields = [
            "plate_area",
            "plate_class",
            "plate_kana",
            "plate_number"
        ];
        const candidatesByPlate = new Map();
        const existingChassis = new Set();

        vehiclePlateCandidates.forEach(function (vehicle) {
            existingChassis.add(vehicle.chassis_number);
            const key = getImportPlateKey(
                plateFields.map(function (field) {
                    return vehicle[field];
                })
            );
            if (key) {
                if (!candidatesByPlate.has(key)) {
                    candidatesByPlate.set(key, []);
                }
                candidatesByPlate.get(key).push(vehicle);
            }
        });

        const rows = Array.from(
            document.querySelectorAll(".import-row")
        ).map(function (row, index) {
            function value(field) {
                return String(
                    row.querySelector(
                        `[name="${field}"]`
                    )?.value || ""
                ).trim();
            }
            const parts = plateFields.map(value);
            return {
                index: index,
                parts: parts,
                plateKey: getImportPlateKey(parts),
                chassis: value("chassis_number")
            };
        });

        const rowsByPlate = new Map();
        rows.forEach(function (row) {
            if (row.plateKey && row.chassis) {
                if (!rowsByPlate.has(row.plateKey)) {
                    rowsByPlate.set(row.plateKey, []);
                }
                rowsByPlate.get(row.plateKey).push(row);
            }
        });

        const previousChoices = new Map();
        area.querySelectorAll("select").forEach(function (field) {
            previousChoices.set(field.name, {
                fingerprint: field.dataset.fingerprint,
                value: field.value
            });
        });

        const seenChassis = new Set();
        const confirmations = [];

        rows.forEach(function (row) {
            if (!row.chassis || seenChassis.has(row.chassis)) {
                return;
            }
            seenChassis.add(row.chassis);

            const conflicts = (
                candidatesByPlate.get(row.plateKey) || []
            ).filter(function (vehicle) {
                return vehicle.chassis_number !== row.chassis;
            });
            const excelConflicts = (
                rowsByPlate.get(row.plateKey) || []
            ).filter(function (other) {
                return other.chassis !== row.chassis;
            });

            if (conflicts.length || excelConflicts.length) {
                confirmations.push({
                    row: row,
                    conflicts: conflicts,
                    excelConflicts: excelConflicts,
                    existing: existingChassis.has(row.chassis)
                });
            }
        });

        const signature = JSON.stringify(confirmations);
        if (area.dataset.signature === signature) {
            return;
        }
        area.dataset.signature = signature;

        const fragment = document.createDocumentFragment();

        function makeElement(tag, text, className) {
            const element = document.createElement(tag);
            if (text !== undefined) {
                element.textContent = text;
            }
            if (className) {
                element.className = className;
            }
            return element;
        }

        const groups = [
            {
                title: "車台番号が一致する登録済み車両",
                description: "各行の車台番号が一致する車両に反映します。変更した項目だけを更新します。",
                items: confirmations.filter(function (item) {
                    return item.existing;
                })
            },
            {
                title: "登録方法を確認する車両",
                description: "同じナンバーの登録済み車両があります。車台番号を訂正するか、別車両として新規登録するかを選択してください。",
                items: confirmations.filter(function (item) {
                    return !item.existing && item.conflicts.length;
                })
            },
            {
                title: "Excel内で同じナンバーを持つ車両",
                description: "Excel内に同じナンバーで異なる車台番号があります。別車両として新規登録する内容か、下の取込対象表で確認してください。",
                items: confirmations.filter(function (item) {
                    return !item.existing && !item.conflicts.length;
                })
            }
        ];

        groups.forEach(function (group) {
            if (!group.items.length) {
                return;
            }

            const section = makeElement(
                "section", undefined,
                "card vehicle-import-preview-card"
            );
            section.appendChild(makeElement("h4", group.title));
            section.appendChild(makeElement(
                "p", group.description, "help-text"
            ));

            const wrapper = makeElement("div");
            wrapper.style.overflowX = "auto";

            const table = makeElement("table");
            table.style.width = "100%";

            const head = makeElement("thead");
            const heading = makeElement("tr");

            [
                "ナンバープレート",
                "Excel行・車台番号",
                "同じナンバーの車両",
                "反映先・登録方法"
            ].forEach(function (text) {
                heading.appendChild(makeElement("th", text));
            });

            head.appendChild(heading);
            table.appendChild(head);

            const body = makeElement("tbody");
            const plateGroups = new Map();

            group.items.forEach(function (item) {
                const key = item.row.plateKey;
                if (!plateGroups.has(key)) {
                    plateGroups.set(key, []);
                }
                plateGroups.get(key).push(item);
            });

            plateGroups.forEach(function (items) {
                items.forEach(function (confirmation, position) {
                    const row = confirmation.row;
                    const tr = makeElement("tr");

                    if (position === 0) {
                        const plateCell = makeElement(
                            "td", row.parts.join(" ")
                        );
                        plateCell.rowSpan = items.length;
                        tr.appendChild(plateCell);
                    }

                    const sourceCell = makeElement("td");
                    sourceCell.appendChild(makeElement(
                        "div", `No.${row.index + 1}`
                    ));
                    sourceCell.appendChild(makeElement(
                        "div", row.chassis
                    ));
                    tr.appendChild(sourceCell);

                    const candidatesCell = makeElement("td");
                    const related = new Map();

                    confirmation.conflicts.forEach(function (vehicle) {
                        related.set(vehicle.chassis_number, {
                            vehicle: vehicle,
                            rows: []
                        });
                    });

                    confirmation.excelConflicts.forEach(function (other) {
                        if (!related.has(other.chassis)) {
                            related.set(other.chassis, {
                                vehicle: null,
                                rows: []
                            });
                        }
                        related.get(other.chassis).rows.push(
                            `No.${other.index + 1}`
                        );
                    });

                    related.forEach(function (entry, chassis) {
                        const details = [];

                        if (entry.vehicle) {
                            details.push(
                                entry.vehicle.inactive ? "無効" : "有効"
                            );
                            if (entry.vehicle.office) {
                                details.push(entry.vehicle.office);
                            }
                        }

                        if (entry.rows.length) {
                            details.push(
                                `Excel ${entry.rows.join("・")}`
                            );
                        }

                        candidatesCell.appendChild(makeElement(
                            "div",
                            `${chassis}（${details.join("／")}）`
                        ));
                    });

                    tr.appendChild(candidatesCell);
                    const actionCell = makeElement("td");
                    const fieldName =
                        `vehicle_plate_resolution_${row.index}`;

                    if (confirmation.existing) {
                        const field = makeElement("input");
                        field.type = "hidden";
                        field.id = fieldName;
                        field.name = fieldName;
                        field.value = "existing_chassis";
                        actionCell.appendChild(field);
                        actionCell.appendChild(makeElement(
                            "span", "今回の車台番号と一致する車両"
                        ));
                    } else {
                        const field = makeElement("select");
                        field.id = fieldName;
                        field.name = fieldName;
                        field.required = true;
                        field.setAttribute(
                            "aria-label",
                            `No.${row.index + 1}の登録・更新方法`
                        );
                        field.dataset.fingerprint =
                            JSON.stringify(confirmation);

                        if (confirmation.conflicts.length) {
                            field.add(new Option(
                                "選択してください", ""
                            ));
                        }

                        confirmation.conflicts.forEach(function (vehicle) {
                            field.add(new Option(
                                `車台番号を訂正：${vehicle.chassis_number} → ${row.chassis}`,
                                `update:${vehicle.id}`
                            ));
                        });

                        field.add(new Option(
                            "別車両として新規登録", "new"
                        ));

                        const previous =
                            previousChoices.get(fieldName);

                        if (
                            previous
                            && previous.fingerprint
                                === field.dataset.fingerprint
                            && Array.from(field.options).some(
                                function (option) {
                                    return option.value
                                        === previous.value;
                                }
                            )
                        ) {
                            field.value = previous.value;
                        }

                        actionCell.appendChild(field);
                    }

                    tr.appendChild(actionCell);
                    body.appendChild(tr);
                });
            });

            table.appendChild(body);
            wrapper.appendChild(table);
            section.appendChild(wrapper);
            fragment.appendChild(section);
        });

        if (confirmations.length) {
            fragment.appendChild(makeElement(
                "p",
                "車台番号の訂正は既存車両の履歴を引き継ぎます。別車両として新規登録する場合は引き継ぎません。登録済み車両同士の統合・削除は行いません。",
                "help-text"
            ));
        }

        area.replaceChildren(fragment);
    }

    function updateImportStatuses() {
        refreshVehiclePlateResolutions();
        let newCount = 0;
        let updateCount = 0;
        let unchangedCount = 0;
        let duplicateCount = 0;

        const seenImportKeys =
            new Set();

        document
            .querySelectorAll(".import-row")
            .forEach(function (row, rowIndex) {
                const statusCell = row.querySelector(
                    ".import-status-cell"
                );
                const read = (name) => String(
                    row.querySelector(
                        '[name="' + name + '"]'
                    )?.value ?? ""
                ).trim();

                const chassis = read("chassis_number");
                const importKey = getImportKey(row);
                let currentStatus;

                if (seenImportKeys.has(importKey)) {
                    currentStatus = "Excel内重複";
                } else {
                    seenImportKeys.add(importKey);

                    const resolution = document.getElementById(
                        `vehicle_plate_resolution_${rowIndex}`
                    )?.value || "";

                    const existing = vehiclePlateCandidates.find(
                        (vehicle) => vehicle.chassis_number === chassis
                    );

                    if (resolution.startsWith("update:")) {
                        currentStatus = "更新";
                    } else if (!existing) {
                        currentStatus = "新規";
                    } else {
                        const fields = [
                            "office",
                            "plate_area",
                            "plate_class",
                            "plate_kana",
                            "plate_number",
                            "model_code",
                            "first_registration_date",
                            "inspection_expiry",
                            "vehicle_name",
                            "body_type",
                            "gross_vehicle_weight",
                            "max_payload"
                        ];

                        const numericFields = new Set([
                            "gross_vehicle_weight",
                            "max_payload"
                        ]);

                        const changed = fields.some((name) => {
                            const value = read(name);

                            // 保存処理と同じく、空欄は既存値を保持する。
                            if (value === "") {
                                return false;
                            }

                            const oldValue = existing[name];

                            if (numericFields.has(name)) {
                                return oldValue == null
                                    || Number(value.replaceAll(",", ""))
                                        !== Number(oldValue);
                            }

                            return value !== String(oldValue ?? "");
                        });

                        const typeChanged = read("vehicle_type")
                            !== String(
                                existing.vehicle_type ?? ""
                            ).trim();

                        const inactive =
                            read("active_status") === "無効";

                        currentStatus =
                            changed
                            || typeChanged
                            || inactive !== Boolean(existing.inactive)
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
            showCommonError(
                "現在の値を入力してください。"
            );

            return;
        }


        if (
            field === "plate_full"
        ) {
            showCommonError(
                "車番は地域名・分類番号・ひらがな・番号に分かれているため、個別編集してください。"
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


    function validateVehiclePlateResolutions() {
        refreshVehiclePlateResolutions();

        const fields = document.querySelectorAll(
            '#vehicle-import-form select[name^="vehicle_plate_resolution_"]'
        );

        let valid = true;

        fields.forEach(function (field) {
            if (field.value) {
                return;
            }

            const rowNumber = Number(
                field.name.replace(
                    "vehicle_plate_resolution_", ""
                )
            ) + 1;

            showCommonError(
                `No.${rowNumber}の登録・更新方法を選択してください。`,
                field.id,
                valid
            );

            valid = false;
        });

        return valid;
    }

    function openImportConfirm() {
        if (!importModal) {
            return;
        }

        clearCommonErrors();

        if (!validateVehiclePlateResolutions()) {
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


    document.addEventListener("change", function (event) {
        if (
            event.target.matches(
                'select[name^="vehicle_plate_resolution_"]'
            )
        ) {
            updateImportStatuses();
        }
    });

    const importForm =
        document.getElementById("vehicle-import-form");

    let importSubmitting = false;

    importForm?.addEventListener("submit", async function (event) {
        event.preventDefault();

        if (importSubmitting) {
            return;
        }

        clearCommonErrors();

        if (!validateVehiclePlateResolutions()) {
            closeImportConfirm();
            return;
        }

        importSubmitting = true;

        const submitButton = event.submitter;
        const originalText = submitButton?.textContent;

        if (submitButton) {
            submitButton.disabled = true;
            submitButton.setAttribute("aria-busy", "true");
            submitButton.textContent = "処理中...";
        }

        try {
            const response = await fetch(importForm.action, {
                method: "POST",
                body: new URLSearchParams(new FormData(importForm)),
                headers: {
                    "Accept": "application/json",
                    "X-DKSS-Final-Submit": "1"
                }
            });

            if (response.redirected) {
                window.location.assign(response.url);
                return;
            }

            if (!response.ok) {
                closeImportConfirm();

                const data = await response.json().catch(() => null);

                if (Array.isArray(data?.errors) && data.errors.length) {
                    data.errors.forEach(function (error, index) {
                        const message = String(
                            error.message || "入力内容を確認してください。"
                        );

                        const rowMatch =
                            message.match(/^(\d+)(?:行目|件目)/);

                        const row = rowMatch
                            ? importForm.querySelectorAll(".import-row")[
                                Number(rowMatch[1]) - 1
                            ]
                            : null;

                        const rowTarget = row && error.field
                            ? Array.from(
                                row.querySelectorAll("input, select")
                            ).find(function (input) {
                                return (
                                    input.name === error.field
                                    && input.type !== "hidden"
                                );
                            })
                            : null;

                        const resolutionTarget =
                            /^vehicle_plate_resolution_\d+$/.test(
                                String(error.field || "")
                            )
                                ? document.getElementById(error.field)
                                : null;

                        const target =
                            rowTarget || resolutionTarget;

                        if (target && !target.id) {
                            target.id =
                                `vehicle-import-${rowMatch[1]}-${error.field}`;
                        }

                        showCommonError(
                            message,
                            target?.id || "",
                            index === 0
                        );
                    });
                } else {
                    showCommonError(
                        "取込を完了できませんでした。入力内容を確認してください。"
                    );
                }

                return;
            }

            const html = await response.text();

            document.open();
            document.write(html);
            document.close();
        } catch (error) {
            closeImportConfirm();

            showCommonError(
                "取込結果を確認できませんでした。車両一覧で反映状況を確認してから、再度操作してください。"
            );
        } finally {
            importSubmitting = false;

            if (submitButton) {
                submitButton.disabled = false;
                submitButton.removeAttribute("aria-busy");
                submitButton.textContent = originalText;
            }
        }
    });

    const masterSection = document.getElementById(
        "vehicle-import-master-resolution"
    );
    const masterItems = document.getElementById(
        "vehicle-import-master-items"
    );
    const masterStatus = document.getElementById(
        "vehicle-import-master-status"
    );
    const masterDataElement = document.getElementById(
        "vehicle-import-master-data"
    );

    const importMasters = masterDataElement
        ? JSON.parse(masterDataElement.textContent)
        : { offices: [], vehicle_types: [] };

    function collectUnresolvedImportMasters() {
        const groups = new Map();
        const officeNames = new Set(
            importMasters.offices.map((item) => item.name)
        );
        const typeNames = new Set(
            importMasters.vehicle_types.map((item) => item.name)
        );

        document.querySelectorAll(".import-row").forEach((row) => {
            const excelRow = row.querySelector(
                '[name="excel_row"]'
            )?.value || "";

            const officeInput = row.querySelector(
                '[name="office"]'
            );
            const typeInput = row.querySelector(
                '[name="vehicle_type"]'
            );
            const typeCode = String(row.querySelector(
                '[name="vehicle_type_code"]'
            )?.value || "").trim();

            const officeValue = String(
                officeInput?.value || ""
            ).trim();
            const typeValue = String(
                typeInput?.value || ""
            ).trim();

            const unresolved = [];

            if (officeValue && !officeNames.has(officeValue)) {
                unresolved.push({
                    kind: "office",
                    value: officeValue,
                    input: officeInput
                });
            }

            if (
                (typeValue && !typeNames.has(typeValue))
                || (!typeValue && typeCode)
            ) {
                unresolved.push({
                    kind: "vehicle_type",
                    value: typeCode || typeValue,
                    input: typeInput
                });
            }

            unresolved.forEach((item) => {
                const key = JSON.stringify([
                    item.kind,
                    item.value
                ]);

                if (!groups.has(key)) {
                    groups.set(key, {
                        key,
                        kind: item.kind,
                        value: item.value,
                        rows: [],
                        inputs: []
                    });
                }

                const group = groups.get(key);
                group.rows.push(excelRow);
                group.inputs.push(item.input);
            });
        });

        return Array.from(groups.values());
    }

    const masterResolutionGroups = new Map();

    function refreshImportMasterResolution() {
        if (!masterSection || !masterItems || !masterStatus) {
            return;
        }

        const pendingSelections = new Map();

        masterItems.querySelectorAll("[data-master-kind]").forEach(
            (item) => {
                const key = JSON.stringify([
                    item.dataset.masterKind,
                    item.dataset.masterValue
                ]);

                pendingSelections.set(key, {
                    mode: item.querySelector(
                        '[data-master-field="mode"]'
                    )?.value || "",
                    existing: item.querySelector(
                        '[data-master-field="existing"]'
                    )?.value || "",
                    name: item.querySelector(
                        '[data-master-field="name"]'
                    )?.value || ""
                });
            }
        );

        const unresolvedGroups = collectUnresolvedImportMasters();
        const unresolvedKeys = new Set(
            unresolvedGroups.map((group) => group.key)
        );

        unresolvedGroups.forEach((group) => {
            masterResolutionGroups.set(group.key, {
                ...group,
                resolvedName: "",
                resolvedMode: ""
            });
        });

        masterResolutionGroups.forEach((group, key) => {
            if (unresolvedKeys.has(key)) {
                return;
            }

            const choices = group.kind === "office"
                ? importMasters.offices
                : importMasters.vehicle_types;

            const names = group.inputs.map((input) =>
                String(input?.value || "").trim()
            );
            const name = names[0] || "";

            const resolved = name
                && names.every((value) => value === name)
                && choices.some((choice) => choice.name === name);

            if (!resolved) {
                masterResolutionGroups.delete(key);
                return;
            }

            group.resolvedName = name;
            group.resolvedMode = pendingSelections.get(key)?.mode
                || group.resolvedMode
                || "existing";
        });

        const groups = Array.from(masterResolutionGroups.values());
        masterItems.replaceChildren();
        masterSection.hidden = groups.length === 0;

        if (groups.some((group) => !group.resolvedName)) {
            window.clearTimeout(masterCompletionTimer);
            masterCompletionTimer = null;
            masterCompletionController?.abort();

            if (masterComplete) {
                masterComplete.hidden = true;
            }

            setMasterDetailsExpanded(true);

            Array.from(masterSection.children).forEach((element) => {
                if (element.matches("p.help-text")) {
                    element.hidden = false;
                }
            });

            if (masterApplyAll) {
                masterApplyAll.hidden = false;
            }
        }

        groups.forEach((group) => {
            const item = document.createElement("tr");
            item.className = "vehicle-import-master-row";
            item.dataset.masterKind = group.kind;
            item.dataset.masterValue = group.value;

            const label = group.kind === "office"
                ? "営業所"
                : "車種";

            const affectedRows = document.createElement("details");
            affectedRows.className = "help-text";

            const rowSummary = document.createElement("summary");
            rowSummary.textContent =
                `対象：${group.rows.length}行（行番号を確認）`;

            const rowNumbers = document.createElement("p");
            rowNumbers.textContent = group.rows.join("、");

            affectedRows.append(rowSummary, rowNumbers);

            const mode = document.createElement("select");
            mode.dataset.masterField = "mode";
            mode.add(new Option(
                `登録済みの${label}を使う`,
                "existing"
            ));
            mode.add(new Option(
                `${label}を新規登録する`,
                "new"
            ));

            const existingLabel = document.createElement("label");
            existingLabel.textContent = "割り当て先";
            existingLabel.hidden = true;

            const existingSelect = document.createElement("select");
            existingSelect.dataset.masterField = "existing";
            existingSelect.add(new Option("選択してください", ""));

            const choices = group.kind === "office"
                ? importMasters.offices
                : importMasters.vehicle_types;

            choices.forEach((choice) => {
                existingSelect.add(new Option(
                    choice.name,
                    choice.name
                ));
            });

            existingLabel.append(existingSelect);

            const nameLabel = document.createElement("label");
            nameLabel.textContent = group.kind === "office"
                ? "新しい営業所名"
                : "新しい車種名";
            nameLabel.hidden = true;

            const nameInput = document.createElement("input");
            nameInput.type = "text";
            nameInput.maxLength = 100;
            nameInput.autocomplete = "off";
            nameInput.dataset.masterField = "name";
            nameInput.value = group.value;
            nameLabel.append(nameInput);

            const applyButton = document.createElement("button");
            applyButton.type = "button";
            applyButton.className = "btn btn-outline";
            applyButton.dataset.masterAction = "apply";
            applyButton.textContent = "反映";
            applyButton.disabled = true;

            mode.addEventListener("change", () => {
                existingLabel.hidden = mode.value !== "existing";
                nameLabel.hidden = mode.value !== "new";
                existingSelect.disabled = mode.value !== "existing";
                nameInput.disabled = mode.value !== "new";
                applyButton.disabled = !mode.value;
                applyButton.textContent = mode.value === "new"
                    ? "新規登録して適用"
                    : "割り当てを適用";
            });

            existingSelect.disabled = true;
            nameInput.disabled = true;

            const pending = pendingSelections.get(group.key);

            if (pending) {
                mode.value = pending.mode || "new";
                existingSelect.value = pending.existing;
                nameInput.value = pending.name;
            } else {
                const existingMatch = choices.find(
                    (choice) => choice.name === group.value
                );

                if (existingMatch) {
                    mode.value = "existing";
                    existingSelect.value = existingMatch.name;
                } else {
                    mode.value = "new";
                }
            }

            mode.dispatchEvent(new Event("change"));

            const kindCell = document.createElement("td");
            kindCell.textContent = group.kind === "office"
                ? "営業所"
                : "車種";

            const sourceCell = document.createElement("td");
            sourceCell.className = "vehicle-import-master-source";
            sourceCell.textContent = group.value;

            const rowsCell = document.createElement("td");
            rowsCell.append(affectedRows);

            const modeCell = document.createElement("td");
            mode.setAttribute(
                "aria-label",
                `${group.value}の登録方法`
            );
            modeCell.append(mode);

            const valueCell = document.createElement("td");
            valueCell.className = "vehicle-import-master-value";

            existingSelect.setAttribute(
                "aria-label",
                `${group.value}に使用する登録済みの名称`
            );
            nameInput.setAttribute(
                "aria-label",
                `${group.value}の新規登録名`
            );

            existingLabel.replaceChildren(existingSelect);
            nameLabel.replaceChildren(nameInput);

            const placeholder = document.createElement("span");
            placeholder.className = "vehicle-import-master-placeholder";
            placeholder.textContent = "—";
            placeholder.hidden = Boolean(mode.value);

            valueCell.append(
                placeholder,
                existingLabel,
                nameLabel
            );

            const actionCell = document.createElement("td");
            actionCell.className = "vehicle-import-master-action";

            const updateActionLabel = () => {
                placeholder.hidden = Boolean(mode.value);
                applyButton.textContent = mode.value === "new"
                    ? "登録して反映"
                    : "反映";
            };

            mode.addEventListener("change", updateActionLabel);
            updateActionLabel();

            if (group.resolvedName) {
                mode.value = group.resolvedMode;
                existingSelect.value = group.resolvedName;
                nameInput.value = group.resolvedName;
                mode.dispatchEvent(new Event("change"));

                mode.disabled = true;
                existingSelect.disabled = true;
                nameInput.disabled = true;

                const confirmed = document.createElement("span");
                confirmed.className = "vehicle-import-master-confirmed";
                confirmed.textContent = "✓ 確認済み";
                actionCell.append(confirmed);
                item.classList.add("is-confirmed");
            } else {
                actionCell.append(applyButton);
            }

            item.append(
                kindCell,
                sourceCell,
                rowsCell,
                modeCell,
                valueCell,
                actionCell
            );
            masterItems.append(item);
        });

        masterStatus.textContent = "";

        if (masterApplyAll) {
            masterApplyAll.disabled = masterBatchPending
                || unresolvedGroups.length === 0;
        }
    }

    let masterRegistrationPending = false;
    let masterBatchPending = false;

    const masterApplyAll = document.getElementById(
        "vehicle-import-master-apply-all"
    );

    const masterComplete = document.getElementById(
        "vehicle-import-master-complete"
    );
    const masterDetails = document.getElementById(
        "vehicle-import-master-details"
    );
    const masterToggle = document.getElementById(
        "vehicle-import-master-toggle"
    );

    let masterCompletionTimer = null;
    let masterCompletionController = null;

    function setMasterDetailsExpanded(expanded) {
        if (!masterDetails || !masterToggle) {
            return;
        }

        masterDetails.hidden = !expanded;
        masterToggle.setAttribute(
            "aria-expanded",
            String(expanded)
        );
        masterToggle.textContent = expanded
            ? "反映内容を閉じる"
            : "反映内容を見る";
    }

    masterToggle?.addEventListener("click", () => {
        setMasterDetailsExpanded(masterDetails.hidden);
    });

    function showImportMasterCompletion() {
        if (
            !masterComplete
            || !masterDetails
            || !masterToggle
            || collectUnresolvedImportMasters().length
        ) {
            return;
        }

        window.clearTimeout(masterCompletionTimer);
        masterCompletionController?.abort();

        masterComplete.hidden = false;
        setMasterDetailsExpanded(true);

        let scrollCancelled = false;
        const controller = new AbortController();
        masterCompletionController = controller;

        const cancelScroll = () => {
            scrollCancelled = true;
        };

        ["wheel", "touchstart", "pointerdown", "keydown", "input"]
            .forEach((eventName) => {
                document.addEventListener(
                    eventName,
                    cancelScroll,
                    {
                        capture: true,
                        passive: true,
                        signal: controller.signal
                    }
                );
            });

        window.addEventListener("scroll", cancelScroll, {
            passive: true,
            signal: controller.signal
        });

        masterCompletionTimer = window.setTimeout(() => {
            masterCompletionTimer = null;
            controller.abort();

            if (collectUnresolvedImportMasters().length) {
                masterComplete.hidden = true;
                return;
            }

            setMasterDetailsExpanded(false);

            Array.from(masterSection.children).forEach((element) => {
                if (element.matches("p.help-text")) {
                    element.hidden = true;
                }
            });

            if (masterApplyAll) {
                masterApplyAll.hidden = true;
            }

            const heading = document.getElementById(
                "vehicle-import-target-heading"
            );

            if (!scrollCancelled && heading) {
                const reduceMotion = window.matchMedia(
                    "(prefers-reduced-motion: reduce)"
                ).matches;

                heading.focus({ preventScroll: true });
                heading.scrollIntoView({
                    behavior: reduceMotion ? "instant" : "smooth",
                    block: "start"
                });
            }
        }, 1000);
    }

    async function applyImportMaster(button) {
        if (!button || masterRegistrationPending) {
            return false;
        }

        const item = button.closest("[data-master-kind]");
        if (!item) {
            return;
        }

        const kind = item.dataset.masterKind;
        const sourceValue = item.dataset.masterValue;
        const mode = item.querySelector(
            '[data-master-field="mode"]'
        )?.value;

        const target = item.querySelector(
            mode === "new"
                ? '[data-master-field="name"]'
                : '[data-master-field="existing"]'
        );

        if (!target || !["existing", "new"].includes(mode)) {
            return;
        }

        if (!target.id) {
            target.id = `vehicle-import-master-field-${
                Array.from(masterItems.children).indexOf(item)
            }-${mode}`;
        }

        const name = String(target.value || "").trim();
        clearCommonErrors();

        if (!name) {
            showCommonError(
                mode === "new"
                    ? "新規登録する名称を入力してください。"
                    : "割り当て先を選択してください。",
                target.id
            );
            return;
        }

        if (name.length > 100) {
            showCommonError(
                "名称は100文字以内で入力してください。",
                target.id
            );
            return;
        }

        const choices = kind === "office"
            ? importMasters.offices
            : importMasters.vehicle_types;

        if (
            mode === "existing"
            && !choices.some((choice) => choice.name === name)
        ) {
            showCommonError(
                "割り当て先を一覧から選択してください。",
                target.id
            );
            return;
        }

        const originalText = button.textContent;
        masterRegistrationPending = true;
        button.disabled = true;
        button.setAttribute("aria-busy", "true");

        try {
            if (mode === "new") {
                button.textContent = "登録中...";

                const csrfToken = document.querySelector(
                    '#vehicle-import-form [name="csrf_token"]'
                )?.value;

                if (!csrfToken) {
                    showCommonError(
                        "登録に必要な情報を確認できませんでした。",
                        target.id
                    );
                    return;
                }

                const data = new FormData();
                data.append("csrf_token", csrfToken);
                data.append("master_kind", kind);
                data.append("name", name);
                data.append("confirmed", "1");

                let response;

                do {
                    response = await fetch(
                        masterSection.dataset.registerUrl,
                        {
                            method: "POST",
                            body: data,
                            headers: {
                                "Accept": "application/json",
                                "X-DKSS-Final-Submit": "1"
                            }
                        }
                    );

                    if (
                        response.status === 429
                        && masterBatchPending
                    ) {
                        const retryAfter = response.headers.get(
                            "Retry-After"
                        );
                        const retrySeconds = Number(retryAfter);
                        const retryDate = retryAfter
                            ? Date.parse(retryAfter)
                            : NaN;

                        let waitMs = 61000;

                        if (
                            Number.isFinite(retrySeconds)
                            && retrySeconds > 0
                        ) {
                            waitMs = (retrySeconds + 1) * 1000;
                        } else if (
                            Number.isFinite(retryDate)
                            && retryDate > Date.now()
                        ) {
                            waitMs = retryDate - Date.now() + 1000;
                        }

                        masterApplyAll.textContent =
                            `待機中（${Math.ceil(waitMs / 1000)}秒）`;
                        masterStatus.textContent =
                            "登録回数の制限に達しました。"
                            + "入力内容を保持したまま、自動で再開します。";

                        await new Promise((resolve) => {
                            window.setTimeout(resolve, waitMs);
                        });

                        masterApplyAll.textContent = "処理を再開しています";
                    }
                } while (
                    response.status === 429
                    && masterBatchPending
                );

                const result = await response.json().catch(() => null);

                if (!response.ok || !result?.ok) {
                    const errors = Array.isArray(result?.errors)
                        && result.errors.length
                        ? result.errors
                        : [{
                            message:
                                "登録できませんでした。入力内容は保持されています。"
                        }];

                    errors.forEach((error, index) => {
                        showCommonError(
                            String(error.message || "登録できませんでした。"),
                            target.id,
                            index === 0
                        );
                    });
                    return;
                }

                if (
                    result.master_kind !== kind
                    || result.master?.name !== name
                ) {
                    showCommonError(
                        "登録結果を確認できませんでした。",
                        target.id
                    );
                    return;
                }

                if (!choices.some((choice) => choice.name === name)) {
                    choices.push(result.master);
                }
            }

            if (kind === "vehicle_type") {
                document.querySelectorAll(
                    'select[name="vehicle_type"],'
                    + '#bulk-old-vehicle-type,'
                    + '#bulk-new-vehicle-type'
                ).forEach((select) => {
                    if (
                        !Array.from(select.options).some(
                            (option) => option.value === name
                        )
                    ) {
                        select.add(new Option(name, name));
                    }
                });
            }

            const currentGroup = collectUnresolvedImportMasters().find(
                (group) => (
                    group.kind === kind
                    && group.value === sourceValue
                )
            );

            currentGroup?.inputs.forEach((input) => {
                input.value = name;
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.dispatchEvent(new Event("change", { bubbles: true }));
            });

            updateImportStatuses();
            refreshImportMasterResolution();
            return true;
        } catch (error) {
            showCommonError(
                "登録結果を確認できませんでした。"
                + "入力内容は保持されています。"
                + "登録済みか確認してから再度操作してください。",
                target.id
            );
        } finally {
            masterRegistrationPending = false;
            button.disabled = false;
            button.removeAttribute("aria-busy");
            button.textContent = originalText;
        }
    }

    masterItems?.addEventListener("click", async (event) => {
        if (masterBatchPending) {
            return;
        }

        const button = event.target.closest(
            '[data-master-action="apply"]'
        );

        if (button) {
            const succeeded = await applyImportMaster(button);

            if (
                succeeded
                && collectUnresolvedImportMasters().length === 0
            ) {
                showImportMasterCompletion();
            }
        }
    });

    masterApplyAll?.addEventListener("click", async () => {
        if (masterBatchPending || masterRegistrationPending) {
            return;
        }

        const keys = collectUnresolvedImportMasters().map(
            (group) => group.key
        );

        if (!keys.length) {
            return;
        }

        const originalText = masterApplyAll.textContent;
        let completed = 0;

        masterBatchPending = true;
        masterApplyAll.disabled = true;
        masterApplyAll.setAttribute("aria-busy", "true");
        clearCommonErrors();

        try {
            for (const key of keys) {
                masterApplyAll.textContent =
                    `処理中（${completed}/${keys.length}）`;

                const item = Array.from(
                    masterItems.querySelectorAll("[data-master-kind]")
                ).find((row) => JSON.stringify([
                    row.dataset.masterKind,
                    row.dataset.masterValue
                ]) === key);

                const button = item?.querySelector(
                    '[data-master-action="apply"]'
                );

                if (!button) {
                    continue;
                }

                const succeeded = await applyImportMaster(button);

                if (!succeeded) {
                    break;
                }

                completed += 1;
            }
        } finally {
            masterBatchPending = false;
            masterApplyAll.removeAttribute("aria-busy");
            masterApplyAll.textContent = originalText;
            masterApplyAll.disabled =
                collectUnresolvedImportMasters().length === 0;
        }

        if (
            completed === keys.length
            && collectUnresolvedImportMasters().length === 0
        ) {
            showImportMasterCompletion();
        }
    });

    importForm?.addEventListener("submit", (event) => {
        const groups = collectUnresolvedImportMasters();

        if (
            !masterRegistrationPending
            && !masterBatchPending
            && !groups.length
        ) {
            return;
        }

        event.preventDefault();
        event.stopImmediatePropagation();
        closeImportConfirm();
        clearCommonErrors();

        if (masterRegistrationPending || masterBatchPending) {
            showCommonError("マスタ登録の完了を待ってください。");
            return;
        }

        refreshImportMasterResolution();

        groups.forEach((group, index) => {
            const label = group.kind === "office" ? "営業所" : "車種";
            showCommonError(
                `${label}「${group.value}」の確認が必要です。`
                + `対象のExcel行：${group.rows.join("、")}。`
                + "既存マスタへの割り当て、または新規登録を行ってください。",
                "",
                index === 0
            );
        });
    }, true);

    let masterResolutionRefreshTimer = null;

    function scheduleImportMasterRefresh() {
        window.clearTimeout(masterResolutionRefreshTimer);

        masterResolutionRefreshTimer = window.setTimeout(() => {
            if (!masterRegistrationPending) {
                refreshImportMasterResolution();
            }
        }, 200);
    }

    importForm?.addEventListener("input", (event) => {
        if (
            event.target.matches(
                '[name="office"], [name="vehicle_type"]'
            )
        ) {
            scheduleImportMasterRefresh();
        }
    });

    importForm?.addEventListener("change", (event) => {
        if (
            event.target.matches(
                '[name="office"], [name="vehicle_type"]'
            )
        ) {
            scheduleImportMasterRefresh();
        }
    });

    document.addEventListener("click", (event) => {
        if (event.target.closest(".js-bulk-replace")) {
            scheduleImportMasterRefresh();
        }
    });

    toggleBulkVehicleTypeInputs();
    updateImportStatuses();
    refreshImportMasterResolution();
});