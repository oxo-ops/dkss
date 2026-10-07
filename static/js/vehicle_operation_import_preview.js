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