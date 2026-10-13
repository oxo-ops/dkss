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

    const candidateList = document.createElement("div");
    candidateList.className = "operation-import-candidates";
    candidateList.id = "operation-import-candidates";
    candidateList.setAttribute("role", "listbox");
    candidateList.hidden = true;
    document.body.append(candidateList);

    let activeInput = null;
    let activeIndex = -1;

    const hideCandidates = () => {
        candidateList.hidden = true;

        if (activeInput) {
            activeInput.setAttribute("aria-expanded", "false");
            activeInput.removeAttribute("aria-activedescendant");
        }
    };

    const normalizeSearch = (value) => String(value || "")
        .normalize("NFKC")
        .toLocaleLowerCase()
        .replace(/[\s-]/g, "");

    rows.forEach((row) => {
        const input = row.querySelector(
            ".vehicle-operation-resolution-search"
        );
        const select = row.querySelector(
            ".vehicle-operation-resolution-select"
        );

        if (!input || !select) return;

        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-controls", candidateList.id);
        input.setAttribute("aria-expanded", "false");

        const showCandidates = () => {
            if (input.disabled) return;

            if (activeInput && activeInput !== input) {
                hideCandidates();
            }

            activeInput = input;
            activeIndex = -1;
            input.removeAttribute("aria-activedescendant");

            const query = normalizeSearch(input.value);
            const suggestedIds = new Set(
                Array.from(select.options)
                    .filter((option) => option.value)
                    .map((option) => option.value)
            );

            const matches = options.filter((option) => {
                return query
                    ? normalizeSearch(labelOf(option)).includes(query)
                    : suggestedIds.has(option.value);
            });

            candidateList.replaceChildren();

            matches.slice(0, 40).forEach((option, index) => {
                const button = document.createElement("button");
                button.type = "button";
                button.id = `operation-import-candidate-${index}`;
                button.setAttribute("role", "option");
                button.setAttribute("aria-selected", "false");

                const parts = labelOf(option).split("／");
                const title = document.createElement("strong");
                title.textContent = option.dataset.number
                    || parts[0].trim();

                const information = document.createElement("span");
                const chassis = option.dataset.chassisNumber
                    || (parts[1] || "")
                        .replace("車台番号：", "")
                        .trim()
                    || "記載なし";
                const office = option.dataset.office
                    || (parts[2] || "").trim()
                    || "営業所未設定";

                information.textContent =
                    `車台番号：${chassis} ／ ${office}`;

                button.append(title, information);

                button.addEventListener("mousedown", (event) => {
                    event.preventDefault();
                });

                button.addEventListener("click", () => {
                    input.value = labelOf(option);
                    input.dispatchEvent(
                        new Event("input", { bubbles: true })
                    );
                    hideCandidates();
                });

                candidateList.append(button);
            });

            if (!matches.length || matches.length > 40) {
                const message = document.createElement("p");

                message.textContent = !matches.length
                    ? query
                        ? "該当する車両はありません。検索を変えるか、車両を追加してください。"
                        : "ナンバー・車台番号・営業所を入力してください。"
                    : `${matches.length}台中40台を表示。検索語を追加して絞り込めます。`;

                candidateList.append(message);
            }

            candidateList.hidden = false;
            input.setAttribute("aria-expanded", "true");

            const rect = input.getBoundingClientRect();
            const width = Math.min(
                rect.width,
                window.innerWidth - 24
            );
            const below = window.innerHeight - rect.bottom - 12;
            const above = rect.top - 12;
            const placeAbove = below < 180 && above > below;
            const height = Math.min(
                280,
                Math.max(80, placeAbove ? above : below)
            );

            candidateList.style.width = `${width}px`;
            candidateList.style.left = `${Math.max(
                12,
                Math.min(rect.left, window.innerWidth - width - 12)
            )}px`;
            candidateList.style.maxHeight = `${height}px`;
            candidateList.style.top = `${placeAbove
                ? Math.max(
                    12,
                    rect.top - Math.min(height, candidateList.scrollHeight)
                )
                : rect.bottom + 4
            }px`;
        };

        input.addEventListener("focus", showCandidates);
        input.addEventListener("input", showCandidates);

        input.addEventListener("blur", () => {
            window.setTimeout(() => {
                if (activeInput === input) hideCandidates();
            }, 150);
        });

        input.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                hideCandidates();
                return;
            }

            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();

                if (candidateList.hidden) showCandidates();

                const buttons = Array.from(
                    candidateList.querySelectorAll("button")
                );

                if (!buttons.length) return;

                activeIndex = (
                    activeIndex
                    + (event.key === "ArrowDown" ? 1 : -1)
                    + buttons.length
                ) % buttons.length;

                buttons.forEach((button, index) => {
                    button.setAttribute(
                        "aria-selected",
                        String(index === activeIndex)
                    );
                });

                input.setAttribute(
                    "aria-activedescendant",
                    buttons[activeIndex].id
                );

                buttons[activeIndex].scrollIntoView({
                    block: "nearest"
                });
            } else if (event.key === "Enter" && !candidateList.hidden) {
                event.preventDefault();

                const buttons = Array.from(
                    candidateList.querySelectorAll("button")
                );

                if (activeIndex >= 0) {
                    buttons[activeIndex]?.click();
                } else if (buttons.length === 1) {
                    buttons[0].click();
                }
            }
        });
    });

    window.addEventListener("resize", hideCandidates);
    window.addEventListener("scroll", (event) => {
        if (!candidateList.contains(event.target)) {
            hideCandidates();
        }
    }, true);

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

        const excludedConfirmation = document.getElementById(
            "acknowledge_excluded_errors"
        );
        const needsExcludedConfirmation = Boolean(
            excludedConfirmation && !excludedConfirmation.checked
        );

        if (importSummary) {
            importSummary.textContent = pending > 0
                ? `車両未確認：${pending}件。登録先を選択するか、車両を追加してください。対象外の車両は「今回は取り込まない」を選んでください。`
                : ready === 0
                    ? "今回の取込対象はありません。登録済み・対象外の明細を確認するか、CSVの選択へ戻ってください。"
                    : needsExcludedConfirmation
                        ? "明細でエラー・重複の行を確認し、「今回は取り込まない」の確認欄にチェックしてください。"
                        : `確認できました。${ready}件の実績を取り込みます。下の取込ボタンを押してください。`;
        }

        if (importButton) {
            importButton.disabled = ready === 0
                || pending > 0
                || needsExcludedConfirmation;

            importButton.textContent = ready > 0
                ? `${ready}件の運行実績を取り込む`
                : "運行実績を取り込む";
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

        const skip = row.querySelector(".operation-import-skip-group");
        const addVehicleButton = row.querySelector(
            ".vehicle-operation-add-vehicle"
        );

        if (skip) {
            skip.addEventListener("change", () => {
                targetsOf(row).forEach(({ number }) => {
                    const checkbox = document.getElementById(
                        `include_${number}`
                    );

                    if (checkbox && !checkbox.disabled) {
                        checkbox.checked = !skip.checked;
                    }
                });

                input.disabled = skip.checked;

                if (addVehicleButton) {
                    addVehicleButton.disabled = skip.checked;
                }

                message.textContent = skip.checked
                    ? "この車両の実績は今回は取り込みません。"
                    : "登録先の車両を選択するか、追加してください。";

                refresh();
            });
        }

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

                dialog.querySelector(".modal-bg").classList.add("is-open");
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
            dialog.querySelector(".modal-bg").classList.remove("is-open");
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