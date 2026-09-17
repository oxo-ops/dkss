function updateCategoryCandidates() {
    const datalist = document.getElementById("category_candidates");

    if (!datalist) {
        return;
    }

    const values = new Set();

    document.querySelectorAll('input[name="item_category"]').forEach(function(input) {
        const value = input.value.trim();

        if (value) {
            values.add(value);
        }
    });

    datalist.innerHTML = "";

    values.forEach(function(value) {
        const option = document.createElement("option");
        option.value = value;
        datalist.appendChild(option);
    });
}

function updateChoiceCandidates() {
    const datalist = document.getElementById("choices_candidates");

    if (!datalist) {
        return;
    }

    const values = new Set();

    document.querySelectorAll('input[name="choices"]').forEach(function(input) {
        const value = input.value.trim();

        if (value) {
            values.add(value);
        }
    });

    datalist.innerHTML = "";

    values.forEach(function(value) {
        const option = document.createElement("option");
        option.value = value;
        datalist.appendChild(option);
    });
}

function addChecklistItem() {
    const area = document.getElementById("checklist_items");
    const index = area.querySelectorAll(".checklist-item-row").length;

    const row = document.createElement("div");
    row.className = "checklist-item-row";

    row.innerHTML = `
        <div class="check-item-header">

            <div
                class="check-item-drag-handle"
                title="ドラッグして並べ替え"
            >
                ⋮⋮
            </div>

            <div class="check-main-row">

                <div class="check-main-field">
                    <label>項目種別</label>

                    <select
                        name="item_type"
                        class="js-item-type"
                    >
                        <option value="check">点検項目</option>
                        <option value="inspector">点検者</option>
                        <option value="approval">承認項目</option>
                    </select>
                </div>

                <div class="approval-user-setting is-hidden">
                    <label class="checkbox-row approval-user-checkbox">
                        <input
                            type="checkbox"
                            name="approval_allow_general"
                            value="${index}"
                        >
                        <span>一般ユーザーも承認可能</span>
                    </label>
                </div>

                <div class="check-main-field check-category-field">
                    <label>カテゴリ</label>

                    <input
                        type="text"
                        name="item_category"
                        list="category_candidates"
                        placeholder="例：荷扱い"
                        class="js-category-input"
                    >
                </div>

            </div>

        </div>

        <div class="check-fields">

            <label>チェック内容</label>
            <textarea
                name="item_content"
                rows="3"
                placeholder="例：荷台床板に異常はないか"
            ></textarea>

            <details class="check-detail-settings">
                <summary>詳細設定</summary>

                <div class="check-detail-body">

                    <label>評価方式</label>
                    <select
                        name="input_type"
                        class="js-input-type"
                    >
                        <option value="select">選択式</option>
                        <option value="text">自由記入</option>
                    </select>

                    <label>選択肢</label>
                    <input
                        type="text"
                        name="choices"
                        list="choices_candidates"
                        placeholder="例：〇,△,×"
                        class="js-choice-input"
                    >

                    <label>評価基準</label>
                    <textarea
                        name="criteria"
                        rows="3"
                        placeholder="例：〇＝異常なし、△＝要注意、×＝使用禁止"
                    ></textarea>

                    <label>評価基準ファイル</label>
                    <input
                        type="file"
                        name="criteria_files_${index}"
                        multiple
                        accept="image/*,video/*,.pdf"
                    >

                    <label class="checkbox-row">
                        <input
                            type="checkbox"
                            name="comment_required"
                            value="${index}"
                        >
                        <span>コメント入力あり</span>
                    </label>

                    <label class="checkbox-row">
                        <input
                            type="checkbox"
                            name="shaded"
                            value="${index}"
                        >
                        <span>毎日点検対象外</span>
                    </label>

                    <p class="help-text">
                        毎日の点検が不要な項目は、識別しやすいようグレー表示されます。
                    </p>

                </div>
            </details>

        </div>

        <div class="approval-fields is-hidden">
            <label>承認欄名</label>
            <input
                type="text"
                name="approval_label"
                placeholder="例：管理者印"
            >
        </div>

        <button
            type="button"
            class="btn-small btn-delete js-remove-checklist-item"
        >
            項目削除
        </button>
    `;

    area.appendChild(row);
}

function openTimePicker(input) {
    if (input.disabled) {
        return;
    }

    if (typeof input.showPicker === "function") {
        input.showPicker();
    }
}

let draggedChecklistItem = null;
let checklistDropIndicator = null;
let checklistDropTarget = null;

document.addEventListener("mousedown", function (event) {
    const handle = event.target.closest(".check-item-drag-handle");

    if (!handle) {
        return;
    }

    const row = handle.closest(".checklist-item-row");

    if (!row) {
        return;
    }

    row.draggable = true;
});

document.addEventListener("mouseup", function (event) {
    const row = event.target.closest(".checklist-item-row");

    if (row && !row.classList.contains("dragging")) {
        row.draggable = false;
    }
});

document.addEventListener("dragstart", function (event) {
    const row = event.target.closest(".checklist-item-row");

    if (!row || !row.draggable) {
        event.preventDefault();
        return;
    }

    draggedChecklistItem = row;
    row.classList.add("dragging");

    checklistDropIndicator = document.createElement("div");
    checklistDropIndicator.className = "checklist-drop-indicator";

    checklistDropTarget = null;
});

document.addEventListener("dragend", function () {
    if (!draggedChecklistItem) {
        return;
    }

    const container = document.getElementById("checklist_items");

    if (
        checklistDropIndicator &&
        checklistDropIndicator.isConnected
    ) {

        if (checklistDropTarget) {
            container.insertBefore(
                draggedChecklistItem,
                checklistDropTarget
            );
        } else {
            container.appendChild(draggedChecklistItem);
        }

        checklistDropIndicator.remove();
    }

    draggedChecklistItem.classList.remove("dragging");
    draggedChecklistItem.draggable = false;

    draggedChecklistItem = null;
    checklistDropIndicator = null;
    checklistDropTarget = null;

    resetCommentIndexes();
    resetFileIndexes();
});

document.getElementById("checklist_items").addEventListener(
    "dragover",
    function (event) {
        event.preventDefault();

        if (!draggedChecklistItem || !checklistDropIndicator) {
            return;
        }

        const container = this;

        const rows = [
            ...container.querySelectorAll(
                ".checklist-item-row:not(.dragging)"
            )
        ];

        let targetRow = null;

        for (const row of rows) {
            const box = row.getBoundingClientRect();
            const middle = box.top + box.height / 2;

            if (event.clientY < middle) {
                targetRow = row;
                break;
            }
        }

        if (targetRow) {
            container.insertBefore(
                checklistDropIndicator,
                targetRow
            );

            checklistDropTarget = targetRow;

        } else {
            container.appendChild(checklistDropIndicator);
            checklistDropTarget = null;
        }
    }
);

function removeChecklistItem(button) {
    button.parentElement.remove();
    resetCommentIndexes();
    resetFileIndexes();
}

function resetCommentIndexes() {
    const rows = document.querySelectorAll(".checklist-item-row");

    rows.forEach((row, index) => {
        const commentCheckbox = row.querySelector(
            'input[name="comment_required"]'
        );

        if (commentCheckbox) {
            commentCheckbox.value = index;
        }

        const shadedCheckbox = row.querySelector(
            'input[name="shaded"]'
        );

        if (shadedCheckbox) {
            shadedCheckbox.value = index;
        }
    });
}

function resetFileIndexes() {
    const rows = document.querySelectorAll(".checklist-item-row");

    rows.forEach((row, index) => {
        const fileInput = row.querySelector('input[type="file"][name^="criteria_files_"]');

        if (fileInput) {
            fileInput.name = `criteria_files_${index}`;
        }
    });
}

function toggleChoices(select) {
    const row = select.closest(".checklist-item-row");
    const choicesInput = row.querySelector('input[name="choices"]');
    const itemTypeSelect = row.querySelector('select[name="item_type"]');

    if (!choicesInput) {
        return;
    }

    const isCheckItem =
        !itemTypeSelect || itemTypeSelect.value === "check";

    if (select.value === "text") {
        choicesInput.classList.add("is-hidden");
        choicesInput.value = "";
        choicesInput.required = false;
    } else {
        choicesInput.classList.remove("is-hidden");
        choicesInput.required = isCheckItem;
    }
}

function toggleReminderTime() {
    const checkbox = document.getElementById("reminder_enabled");
    const timeInput = document.getElementById("reminder_time");

    if (!checkbox || !timeInput) {
        return;
    }

    timeInput.disabled = !checkbox.checked;
}

function toggleVehicleChecklistSetting() {
    const target = document.querySelector('select[name="target"]');
    const area = document.getElementById("vehicle_checklist_setting");

    if (!target || !area) {
        return;
    }

    area.classList.toggle(
        "is-hidden",
        target.value !== "車両管理"
    );
}

function toggleItemType(select) {
    const row = select.closest(".checklist-item-row");

    const checkFields = row.querySelector(".check-fields");
    const categoryField = row.querySelector(".check-category-field");
    const approvalFields = row.querySelector(".approval-fields");
    const approvalUserSetting = row.querySelector(".approval-user-setting");

    const isApproval = select.value === "approval";
    const isInspector = select.value === "inspector";

    checkFields.classList.toggle(
        "is-hidden",
        isApproval || isInspector
    );

    categoryField.classList.toggle(
        "is-hidden",
        isApproval || isInspector
    );

    approvalFields.classList.toggle(
        "is-hidden",
        !isApproval
    );

    if (approvalUserSetting) {
        approvalUserSetting.classList.toggle(
            "is-hidden",
            !isApproval
        );
    }
}

document.querySelector(".responsive-form").addEventListener(
    "invalid",
    function (event) {
        const details = event.target.closest(".check-detail-settings");

        if (details) {
            details.open = true;
        }
    },
    true
);

window.addEventListener("DOMContentLoaded", function () {
    toggleVehicleChecklistSetting();
    toggleReminderTime();

    document
        .querySelectorAll('select[name="item_type"]')
        .forEach(function(select) {
            toggleItemType(select);
        });

    document
        .querySelectorAll('select[name="input_type"]')
        .forEach(function(select) {
            toggleChoices(select);
        });
    document.querySelector(".js-checklist-target")
    ?.addEventListener("change", toggleVehicleChecklistSetting);

    document.querySelector(".js-reminder-enabled")
        ?.addEventListener("change", toggleReminderTime);

    document.querySelector(".js-reminder-time")
        ?.addEventListener("click", function () {
            openTimePicker(this);
        });

    document.addEventListener("change", function (event) {
        if (event.target.matches(".js-item-type")) {
            toggleItemType(event.target);
        }

        if (event.target.matches(".js-input-type")) {
            toggleChoices(event.target);
        }
    });

    document.addEventListener("focusin", function (event) {
        if (event.target.matches(".js-category-input")) {
            updateCategoryCandidates();
        }

        if (event.target.matches(".js-choice-input")) {
            updateChoiceCandidates();
        }
    });

    document.addEventListener("click", function (event) {
        const removeButton =
            event.target.closest(".js-remove-checklist-item");

        if (removeButton) {
            removeChecklistItem(removeButton);
            return;
        }

        const addButton =
            event.target.closest(".js-add-checklist-item");

        if (addButton) {
            addChecklistItem();
        }
    });
});
