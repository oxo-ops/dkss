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


                if (
                    file.type.startsWith("image/")
                ) {
                    const img =
                        document.createElement("img");

                    img.src =
                        URL.createObjectURL(file);

                    img.className =
                        "preview-image";

                    fileBox.appendChild(img);

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

                    fileBox.appendChild(video);

                } else {
                    const text =
                        document.createElement("p");

                    text.textContent =
                        "PDF：" + file.name;

                    fileBox.appendChild(text);
                }

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


    updateManualLink();
});