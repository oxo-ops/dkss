document.addEventListener("DOMContentLoaded", function () {
    const manualSelect =
        document.getElementById("manual_select");

    const manualLink =
        document.getElementById("manual_link");

    const filesInput =
        document.getElementById("files");

    const previewArea =
        document.getElementById("preview_area");

    const targetUserSearch =
        document.getElementById("target_user_search");

    const targetUserInput =
        document.getElementById("target_user");

    const driverSearchResults =
        document.getElementById("driver_search_results");

    const driverSearchData =
        document.getElementById("driver_search_data");

    function updateManualLink() {
        const url =
            manualSelect.value;

        if (!url) {
            manualLink.removeAttribute("href");
            manualLink.classList.add("is-hidden");
            return;
        }

        manualLink.href = url;
        manualLink.classList.remove("is-hidden");
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

                const mediaArea =
                    document.createElement("div");

                mediaArea.className =
                    "preview-media";

                if (
                    file.type.startsWith("image/")
                ) {
                    const img =
                        document.createElement("img");

                    img.src =
                        URL.createObjectURL(file);

                    img.className =
                        "preview-image";

                    img.alt =
                        "選択した画像";

                    mediaArea.appendChild(img);

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
                    video.preload = "metadata";

                    mediaArea.appendChild(video);

                } else {
                    const pdf =
                        document.createElement("div");

                    pdf.className =
                        "preview-file-icon";

                    pdf.textContent =
                        "PDF";

                    mediaArea.appendChild(pdf);
                }

                const info =
                    document.createElement("div");

                info.className =
                    "preview-info";

                const name =
                    document.createElement("p");

                name.className =
                    "preview-file-name";

                name.textContent =
                    file.name;

                const size =
                    document.createElement("p");

                size.className =
                    "preview-file-size";

                size.textContent =
                    formatFileSize(file.size);

                info.appendChild(name);
                info.appendChild(size);

                fileBox.appendChild(mediaArea);
                fileBox.appendChild(info);

                previewArea.appendChild(fileBox);
            });
    }

    manualSelect.addEventListener(
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

        targetUserInput.value = "";
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

    targetUserSearch?.addEventListener(
        "input",
        updateDriverSearchResults
    );

    targetUserSearch?.addEventListener(
        "compositionend",
        updateDriverSearchResults
    );

    filesInput?.addEventListener(
        "change",
        previewFiles
    );

    const contentEditor = document.getElementById("content_editor");
    const contentValue = document.getElementById("content_value");
    const editForm = contentEditor?.closest("form");

    if (contentEditor && contentValue && editForm) {
        editForm.addEventListener("submit", function () {
            contentValue.value = contentEditor.innerText.trim();
        });
    }

    updateManualLink();
    previewFiles();
});