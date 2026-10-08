(() => {
    "use strict";

    const preview = document.querySelector(
        ".vehicle-operation-import-preview"
    );
    const optionTemplate = document.getElementById(
        "vehicle-operation-choice-options"
    );

    if (!preview || !optionTemplate) {
        return;
    }

    const populateVehicleOptions = (event) => {
        const select = event.target;

        if (
            !(select instanceof HTMLSelectElement)
            || !select.classList.contains(
                "vehicle-operation-vehicle-select"
            )
            || select.dataset.optionsLoaded === "1"
        ) {
            return;
        }

        const selectedValue = select.value;

        select.replaceChildren(
            optionTemplate.content.cloneNode(true)
        );
        select.value = selectedValue;
        select.dataset.optionsLoaded = "1";
    };

    const resolutionRows = Array.from(
        preview.querySelectorAll(
            ".vehicle-operation-resolution-row"
        )
    );

    const normalizeSearchText = (value) => (
        String(value || "")
            .normalize("NFKC")
            .toLowerCase()
            .replace(/\s+/g, "")
    );

    const searchableOptions = Array.from(
        optionTemplate.content.querySelectorAll(
            "option[value]"
        )
    ).filter((option) => option.value !== "");

    resolutionRows.forEach((row) => {
        const search = row.querySelector(
            ".vehicle-operation-resolution-search"
        );
        const select = row.querySelector(
            ".vehicle-operation-resolution-select"
        );
        const message = row.querySelector(
            ".vehicle-operation-resolution-message"
        );

        if (!search || !select || !message) {
            return;
        }

        const initialOptions = Array.from(
            select.options
        ).map((option) => option.cloneNode(true));

        search.addEventListener("input", () => {
            const keyword = normalizeSearchText(
                search.value
            );
            const selectedValue = select.value;

            if (!keyword) {
                const restoredOptions = initialOptions.map(
                    (option) => option.cloneNode(true)
                );
                const selectedOption = searchableOptions.find(
                    (option) => option.value === selectedValue
                );

                if (
                    selectedOption
                    && !restoredOptions.some(
                        (option) => option.value === selectedValue
                    )
                ) {
                    restoredOptions.push(
                        selectedOption.cloneNode(true)
                    );
                }

                select.replaceChildren(...restoredOptions);
                select.value = selectedValue;
                message.textContent = "";
                return;
            }

            const matches = searchableOptions.filter(
                (option) => normalizeSearchText(
                    option.textContent
                ).includes(keyword)
            );

            const placeholder = document.createElement(
                "option"
            );
            placeholder.value = "";
            placeholder.textContent = "登録先を選択";

            const displayedOptions = matches.slice(0, 50).map(
                (option) => option.cloneNode(true)
            );
            const selectedOption = searchableOptions.find(
                (option) => option.value === selectedValue
            );

            if (
                selectedOption
                && !displayedOptions.some(
                    (option) => option.value === selectedValue
                )
            ) {
                displayedOptions.unshift(
                    selectedOption.cloneNode(true)
                );
            }

            select.replaceChildren(
                placeholder,
                ...displayedOptions
            );
            select.value = selectedValue;

            message.textContent = matches.length > 50
                ? `${matches.length}台あります。検索条件を追加してください。`
                : matches.length === 0
                    ? "一致する車両がありません。検索条件を変えてください。"
                    : `${matches.length}台見つかりました。登録先を選択してください。`;
        });
    });

    const resolutionDetails = document.getElementById(
        "vehicle-operation-resolution-details"
    );
    const resolutionStatus = document.getElementById(
        "vehicle-operation-resolution-status"
    );

    const refreshResolutionStatus = () => {
        const completed = (
            resolutionRows.length > 0
            && resolutionRows.every(
                (row) => row.dataset.applied === "1"
            )
        );

        if (resolutionStatus) {
            resolutionStatus.hidden = !completed;
        }

        if (completed && resolutionDetails) {
            resolutionDetails.open = false;
        }
    };

    resolutionRows.forEach((row) => {
        const select = row.querySelector(
            ".vehicle-operation-resolution-select"
        );
        const search = row.querySelector(
            ".vehicle-operation-resolution-search"
        );
        const button = row.querySelector(
            ".vehicle-operation-resolution-apply"
        );
        const message = row.querySelector(
            ".vehicle-operation-resolution-message"
        );

        if (!select || !button || !message) {
            return;
        }

        const markUnapplied = () => {
            delete row.dataset.applied;
            refreshResolutionStatus();
        };

        select.addEventListener("change", markUnapplied);

        if (search) {
            search.addEventListener("input", markUnapplied);
        }

        button.addEventListener("click", () => {
            const selectedOption = searchableOptions.find(
                (option) => option.value === select.value
            );

            if (!selectedOption) {
                message.textContent = "登録先の車両を選択してください。";
                select.focus();
                return;
            }

            let lineNumbers;

            try {
                lineNumbers = JSON.parse(
                    row.dataset.lineNumbers || "[]"
                );
            } catch {
                message.textContent = "対象行を確認できません。画面を再読み込みしてください。";
                return;
            }

            if (!Array.isArray(lineNumbers)) {
                return;
            }

            const targets = lineNumbers.map((lineNumber) => ({
                checkbox: document.getElementById(
                    `include_${lineNumber}`
                ),
                select: document.getElementById(
                    `vehicle_${lineNumber}`
                ),
            })).filter((target) => (
                target.checkbox
                && target.checkbox.checked
                && !target.checkbox.disabled
                && target.select
                && !target.select.disabled
            ));

            targets.forEach((target) => {
                if (!Array.from(target.select.options).some(
                    (option) => option.value === selectedOption.value
                )) {
                    target.select.append(
                        selectedOption.cloneNode(true)
                    );
                }

                target.select.value = selectedOption.value;
                target.select.dispatchEvent(
                    new Event("change", { bubbles: true })
                );

                const form = target.select.closest("form");
                const confirmationId = (
                    `mapping_confirmation_${target.select.id}`
                );
                let confirmation = document.getElementById(
                    confirmationId
                );

                if (form && !confirmation) {
                    confirmation = document.createElement("input");
                    confirmation.type = "hidden";
                    confirmation.id = confirmationId;
                    confirmation.name = "confirmed_vehicle_mapping";
                    form.append(confirmation);
                }

                if (confirmation) {
                    const lineNumber = target.select.id.replace(
                        /^vehicle_/,
                        ""
                    );
                    confirmation.value = (
                        `${lineNumber}:${selectedOption.value}`
                    );
                }
            });

            row.dataset.applied = "1";
            message.textContent = targets.length > 0
                ? `${targets.length}件に反映しました。実績の登録は画面下のボタンで行います。`
                : "対象行のチェックが外れているため、反映対象はありません。";

            refreshResolutionStatus();
        });
    });

    preview.addEventListener("change", (event) => {
        const target = event.target;

        if (
            !(target instanceof HTMLSelectElement)
            && !(target instanceof HTMLInputElement)
        ) {
            return;
        }

        const matched = target.id.match(
            /^(?:vehicle|include)_(\d+)$/
        );

        if (!matched) {
            return;
        }

        const lineNumber = Number(matched[1]);
        let changed = false;

        resolutionRows.forEach((row) => {
            if (row.dataset.applied !== "1") {
                return;
            }

            let lineNumbers;

            try {
                lineNumbers = JSON.parse(
                    row.dataset.lineNumbers || "[]"
                );
            } catch {
                return;
            }

            if (
                !Array.isArray(lineNumbers)
                || !lineNumbers.some(
                    (number) => Number(number) === lineNumber
                )
            ) {
                return;
            }

            delete row.dataset.applied;
            changed = true;

            const message = row.querySelector(
                ".vehicle-operation-resolution-message"
            );

            if (message) {
                message.textContent =
                    "明細の選択内容を変更しました。登録先を確認してください。";
            }
        });

        if (changed) {
            refreshResolutionStatus();

            if (resolutionDetails) {
                resolutionDetails.open = true;
            }
        }
    });

    preview.addEventListener(
        "pointerdown",
        populateVehicleOptions,
        true
    );
    preview.addEventListener(
        "focusin",
        populateVehicleOptions
    );
})();