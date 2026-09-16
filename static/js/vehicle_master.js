document.addEventListener("DOMContentLoaded", function () {
    const selectAll = document.getElementById("select-all-visible");
    const checkboxes = document.querySelectorAll(".vehicle-select");
    const countDisplay = document.getElementById("selected-count");
    const bulkDeleteButton = document.getElementById("bulk-delete-button");
    const bulkInactiveButton = document.getElementById("bulk-inactive-button");
    const bulkActiveButton = document.getElementById("bulk-active-button");
    const bulkDeleteForm = document.getElementById("bulk-delete-form");

    function updateSelectedCount() {
        const selectedCheckboxes =
            document.querySelectorAll(".vehicle-select:checked");

        const selectedCount = selectedCheckboxes.length;

        const selectedInactiveCount =
            Array.from(selectedCheckboxes).filter(function (checkbox) {
                return checkbox.dataset.inactive === "true";
            }).length;

        if (countDisplay) {
            countDisplay.textContent = selectedCount + "件選択中";
        }

        if (bulkDeleteButton) {
            bulkDeleteButton.disabled = selectedCount === 0;
        }

        if (bulkInactiveButton) {
            bulkInactiveButton.disabled = selectedCount === 0;
        }

        if (bulkActiveButton) {
            bulkActiveButton.disabled = selectedInactiveCount === 0;
            bulkActiveButton.classList.toggle(
                "is-hidden",
                selectedInactiveCount === 0
            );
        }

        if (!selectAll) {
            return;
        }

        if (selectedCount === 0) {
            selectAll.checked = false;
            selectAll.indeterminate = false;
        } else if (selectedCount === checkboxes.length) {
            selectAll.checked = true;
            selectAll.indeterminate = false;
        } else {
            selectAll.checked = false;
            selectAll.indeterminate = true;
        }
    }

    if (selectAll) {
        selectAll.addEventListener("change", function () {
            checkboxes.forEach(function (checkbox) {
                checkbox.checked = selectAll.checked;
            });

            updateSelectedCount();
        });
    }

    checkboxes.forEach(function (checkbox) {
        checkbox.addEventListener("change", function () {
            updateSelectedCount();
        });
    });

    document
        .querySelectorAll(".js-vehicle-inactive-toggle")
        .forEach(function (checkbox) {
            checkbox.addEventListener("change", function () {
                checkbox.form.submit();
            });
        });

    document
        .querySelectorAll(".js-vehicle-delete-form")
        .forEach(function (form) {
            form.addEventListener("submit", function (event) {
                const confirmed = window.confirm(
                    "この車両と関連データはすべて削除されます。\n本当に削除しますか？"
                );

                if (!confirmed) {
                    event.preventDefault();
                }
            });
        });

    if (bulkDeleteForm) {
        bulkDeleteForm.addEventListener("submit", function (event) {
            const selectedCheckboxes =
                document.querySelectorAll(".vehicle-select:checked");

            const selectedCount = selectedCheckboxes.length;

            if (selectedCount === 0) {
                event.preventDefault();
                return;
            }

            const submitButtonId =
                event.submitter ? event.submitter.id : "";

            let message;

            if (submitButtonId === "bulk-active-button") {
                const inactiveSelectedCount =
                    Array.from(selectedCheckboxes).filter(function (checkbox) {
                        return checkbox.dataset.inactive === "true";
                    }).length;

                message =
                    inactiveSelectedCount +
                    "台の車両を有効化します。\nよろしいですか？";
            } else if (submitButtonId === "bulk-inactive-button") {
                message =
                    selectedCount +
                    "台の車両を無効化します。\n" +
                    "点検履歴などの関連データは削除されません。\n" +
                    "よろしいですか？";
            } else {
                message =
                    selectedCount +
                    "台の車両と関連データはすべて削除されます。\n" +
                    "本当に削除しますか？";
            }

            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    }

    updateSelectedCount();
});