(() => {
    "use strict";

    const preview = document.querySelector(".vehicle-operation-import-preview");
    const template = document.getElementById("vehicle-operation-choice-options");
    if (!preview || !template) return;

    const options = Array.from(template.content.querySelectorAll("option"))
        .filter((option) => option.value);
    const labelOf = (option) => option.textContent.replace(/\s+/g, " ").trim();
    const rows = Array.from(
        preview.querySelectorAll(".vehicle-operation-resolution-row")
    );
    const details = document.getElementById("vehicle-operation-resolution-details");
    const status = document.getElementById("vehicle-operation-resolution-status");
    const list = document.createElement("datalist");

    list.id = "vehicle-operation-search-choices";
    options.forEach((option) => {
        list.append(new Option(labelOf(option), labelOf(option)));
    });
    preview.append(list);

    const header = details?.querySelector("thead th:last-child");
    if (header) header.hidden = true;

    const actions = preview.querySelector(".vehicle-operation-resolution-actions");
    if (actions) actions.hidden = true;

    const importForm = preview.querySelector("form");
    const importButton = importForm?.querySelector('button[type="submit"]');
    const importSummary = document.getElementById(
        "vehicle-operation-import-summary"
    );

    const updateImportCount = () => {
        let ready = 0;
        let pending = 0;
        const validIds = new Set(options.map((option) => option.value));

        preview.querySelectorAll(
            ".vehicle-operation-vehicle-select"
        ).forEach((select) => {
            const line = select.id.replace(/^vehicle_/, "");
            const checkbox = document.getElementById(`include_${line}`);

            if (
                select.disabled
                || !checkbox
                || checkbox.disabled
                || !checkbox.checked
            ) return;

            if (validIds.has(select.value)) {
                ready += 1;
            } else {
                pending += 1;
            }
        });

        if (importSummary) {
            importSummary.textContent = ready > 0
                ? `登録できる実績：${ready}件`
                    + (pending
                        ? ` ／ 登録先未設定の${pending}件は残します。`
                        : "")
                : pending > 0
                    ? `登録先が未設定です（実績${pending}件）。車両を選択するか追加してください。`
                    : "今回の登録対象はありません。";
        }

        if (importButton) {
            importButton.disabled = ready === 0;
            importButton.textContent = ready > 0
                ? `${ready}件の実績を登録`
                : "実績を登録";
        }
    };

    preview.addEventListener("change", updateImportCount);
    updateImportCount();

    const refresh = () => {
        updateImportCount();
        const complete = rows.length > 0
            && rows.every((row) => row.dataset.applied === "1");

        if (status) {
            status.hidden = !complete;
            status.textContent =
                "登録先を設定しました。内容を確認して実績を登録してください。";
        }

        if (complete && details) details.open = false;
    };

    const targetsOf = (row) => {
        try {
            const numbers = JSON.parse(row.dataset.lineNumbers || "[]");
            return Array.isArray(numbers)
                ? numbers.map((number) => ({
                    number,
                    select: document.getElementById(`vehicle_${number}`)
                })).filter((target) => target.select && !target.select.disabled)
                : [];
        } catch {
            return [];
        }
    };

    const setTargets = (row, option) => {
        const targets = targetsOf(row);

        targets.forEach(({ number, select }) => {
            const id = `mapping_confirmation_vehicle_${number}`;
            document.getElementById(id)?.remove();

            if (!option) {
                select.value = "";
                return;
            }

            if (!Array.from(select.options).some(
                (item) => item.value === option.value
            )) {
                select.append(option.cloneNode(true));
            }

            select.value = option.value;

            const confirmation = document.createElement("input");
            confirmation.type = "hidden";
            confirmation.id = id;
            confirmation.name = "confirmed_vehicle_mapping";
            confirmation.value = `${number}:${option.value}`;
            select.closest("form").append(confirmation);
        });

        if (option && targets.length) {
            row.dataset.applied = "1";
        } else {
            delete row.dataset.applied;
        }

        refresh();
    };

    rows.forEach((row) => {
        const input = row.querySelector(".vehicle-operation-resolution-search");
        const select = row.querySelector(".vehicle-operation-resolution-select");
        const message = row.querySelector(".vehicle-operation-resolution-message");
        const button = row.querySelector(".vehicle-operation-resolution-apply");

        if (!input || !select || !message) return;

        if (button) button.closest("td").hidden = true;

        select.hidden = true;
        input.type = "text";
        input.setAttribute("list", list.id);
        input.placeholder = "ナンバー・車台番号・営業所で検索して選択";

        const label = row.querySelector(`label[for="${input.id}"]`);
        if (label) label.textContent = "登録先の車両";

        input.addEventListener("input", () => {
            const matches = options.filter(
                (option) => labelOf(option) === input.value.trim()
            );

            select.hidden = matches.length <= 1;

            if (matches.length > 1) {
                select.replaceChildren(
                    new Option("登録先を選択", ""),
                    ...matches.map((option) => option.cloneNode(true))
                );
            }

            const option = matches.length === 1 ? matches[0] : null;

            if (option && !Array.from(select.options).some(
                (item) => item.value === option.value
            )) {
                select.append(option.cloneNode(true));
            }

            select.value = option ? option.value : "";
            setTargets(row, option);

            message.textContent = option
                ? ""
                : matches.length > 1
                    ? "同じ表示の車両が複数あります。登録先を確認してください。"
                    : input.value
                        ? "候補から登録先の車両を選択してください。"
                        : "";
        });

        select.addEventListener("change", () => {
            const option = options.find((item) => item.value === select.value);
            if (option) input.value = labelOf(option);

            setTargets(row, option);
            message.textContent = "";
        });
    });

    preview.addEventListener("change", (event) => {
        if (!event.target.classList.contains(
            "vehicle-operation-vehicle-select"
        )) return;

        document.getElementById(
            `mapping_confirmation_${event.target.id}`
        )?.remove();

        rows.forEach((row) => {
            if (!targetsOf(row).some(
                (target) => target.select === event.target
            )) return;

            delete row.dataset.applied;
            row.querySelector(
                ".vehicle-operation-resolution-message"
            ).textContent = "明細で登録先を変更しました。";
        });

        refresh();
    });

    const dialog = document.getElementById("operation-add-vehicle-dialog");
    const addForm = document.getElementById("operation-add-vehicle-form");

    if (dialog && addForm) {
        let activeRow = null;
        let opener = null;
        let busy = false;

        const cancel = document.getElementById("operation-add-vehicle-cancel");
        const submit = addForm.querySelector('button[type="submit"]');

        const showError = (message, field = "", focus = true) => {
            showCommonError(
                message,
                field ? `operation_new_${field}` : "",
                focus
            );
        };

        rows.forEach((row) => {
            const button = row.querySelector(".vehicle-operation-add-vehicle");
            if (!button) return;

            button.addEventListener("click", () => {
                activeRow = row;
                opener = button;
                addForm.reset();
                clearCommonErrors();

                const source = button.dataset.sourceNumber || "";
                document.getElementById(
                    "operation-add-vehicle-source"
                ).textContent = `CSVの車両：${source || "記載なし"}`;

                const parts = source.replace(/\s+/g, "").match(
                    /^(.+?)([0-9A-Z]{3})([ぁ-んァ-ヶA-Z])([0-9]{1,4})$/u
                );

                if (parts) {
                    [
                        "plate_area",
                        "plate_class",
                        "plate_kana",
                        "plate_number"
                    ].forEach((key, index) => {
                        addForm.elements.namedItem(key).value = parts[index + 1];
                    });
                }

                const office = addForm.elements.namedItem("office");
                if (Array.from(office.options).some(
                    (option) => option.value === button.dataset.sourceOffice
                )) {
                    office.value = button.dataset.sourceOffice;
                }

                dialog.showModal();
                document.getElementById(
                    "operation_new_chassis_number"
                ).focus();
            });
        });

        cancel.addEventListener("click", () => {
            if (!busy) dialog.close();
        });

        dialog.addEventListener("cancel", (event) => {
            if (busy) event.preventDefault();
        });

        dialog.addEventListener("close", () => {
            clearCommonErrors();

            if (details && !details.open) {
                preview.querySelector(
                    'form button[type="submit"]'
                )?.focus();
            } else {
                opener?.focus();
            }
        });

        addForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (busy || !activeRow) return;

            clearCommonErrors();
            busy = true;
            submit.disabled = true;
            cancel.disabled = true;
            submit.textContent = "追加中…";

            try {
                const response = await fetch(addForm.action, {
                    method: "POST",
                    body: new FormData(addForm),
                    headers: { "X-DKSS-Final-Submit": "1" }
                });

                if (response.redirected) {
                    showError(
                        "ログイン状態を確認できません。入力内容を残したまま、別タブでログインしてください。"
                    );
                    return;
                }

                const data = await response.json();

                if (!response.ok || !data.ok) {
                    const errors = Array.isArray(data.errors)
                        ? data.errors
                        : [];

                    if (!errors.length) {
                        showError(data.message || "車両を追加できませんでした。");
                    }

                    errors.forEach((error, index) => {
                        showError(
                            error.message,
                            error.field,
                            index === 0
                        );
                    });
                    return;
                }

                const vehicle = data.vehicle;
                const label =
                    `${vehicle.number} ／ 車台番号：${vehicle.chassis_number}`
                    + ` ／ ${vehicle.office || "営業所未設定"}`
                    + ` ／ 車検満了：${vehicle.inspection_expiry || "未設定"}`;

                const option = new Option(label, String(vehicle.id));

                options.push(option);
                template.content.append(option.cloneNode(true));
                list.append(new Option(label, label));

                preview.querySelectorAll(
                    '.vehicle-operation-vehicle-select[data-options-loaded="1"]'
                ).forEach((select) => {
                    select.append(option.cloneNode(true));
                });

                const input = activeRow.querySelector(
                    ".vehicle-operation-resolution-search"
                );
                input.value = label;
                input.dispatchEvent(new Event("input", { bubbles: true }));

                dialog.close();
            } catch {
                showError(
                    "車両の追加結果を確認できませんでした。入力内容は保持しています。通信状態を確認してください。"
                );
            } finally {
                busy = false;
                submit.disabled = false;
                cancel.disabled = false;
                submit.textContent = "追加して登録先に設定";
            }
        });
    }

    const populate = (event) => {
        const select = event.target;

        if (!select.classList.contains("vehicle-operation-vehicle-select")
            || select.dataset.optionsLoaded === "1") return;

        const value = select.value;
        select.replaceChildren(template.content.cloneNode(true));
        select.value = value;
        select.dataset.optionsLoaded = "1";
    };

    preview.addEventListener("pointerdown", populate, true);
    preview.addEventListener("focusin", populate);
})();