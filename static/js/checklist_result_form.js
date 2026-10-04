document.addEventListener("DOMContentLoaded", function () {
    const targetType =
        document.getElementById("target_type");

    const targetUserArea =
        document.getElementById("target_user_area");

    const targetVehicleArea =
        document.getElementById("target_vehicle_area");

    const targetOfficeArea =
        document.getElementById("target_office_area");

    const targetUserSearch =
        document.getElementById("target_user_search");

    const targetUserInput =
        document.getElementById("target_user");

    const driverSearchResults =
        document.getElementById("driver_search_results");

    const driverSearchData =
        document.getElementById("driver_search_data");

    const vehicleSearchInput =
        document.getElementById("vehicle_search");

    const vehicleSearchResults =
        document.getElementById("vehicle_search_results");

    const targetVehicle =
        document.getElementById("target_vehicle");

    const selectedVehicleDisplay =
        document.getElementById("selected_vehicle_display");

    let vehicleSearchTimer = null;

    const approvalUsers =
        new Map();

    const config =
        document.getElementById(
            "safetyChecklistConfig"
        );

    let savedApprovalUsers = {};

    if (config) {
        try {
            savedApprovalUsers =
                JSON.parse(
                    config.dataset.savedApprovalUsers ||
                    "{}"
                );
        } catch (error) {
            console.error(
                "保存済み承認者の読込に失敗しました。",
                error
            );
        }
    }

    async function loadSavedNotifyUsers() {
        for (
            const [
                approvalIndex,
                savedUsers
            ]
            of Object.entries(
                savedApprovalUsers
            )
        ) {
            for (
                const savedValue
                of savedUsers
            ) {
            const value =
                String(
                    savedValue || ""
                ).trim();

            if (!value) {
                continue;
            }

            try {
                const response =
                    await fetch(
                        "/api/mention-users?q=" +
                        encodeURIComponent(
                            value
                        )
                    );

                if (!response.ok) {
                    console.warn(
                        "保存済み承認者を復元できません:",
                        value
                    );

                    showCommonError(
                        "保存済みの承認者を復元できませんでした。通信状態を確認してください。"
                    );
                    continue;
                }

                const data =
                    await response.json();

                const users =
                    data.users || [];

                const usernameMatch =
                    users.find(
                        function (user) {
                            return (
                                user.username ===
                                value
                            );
                        }
                    );

                if (usernameMatch) {
                    addNotifyUser(
                        approvalIndex,
                        usernameMatch.username,
                        usernameMatch.name
                    );
                    continue;
                }

                const nameMatches =
                    users.filter(
                        function (user) {
                            return (
                                user.name ===
                                value
                            );
                        }
                    );

                if (nameMatches.length === 1) {
                    addNotifyUser(
                        approvalIndex,
                        nameMatches[0].username,
                        nameMatches[0].name
                    );
                } else {
                    console.warn(
                        "保存済み承認者を一意に復元できません:",
                        value
                    );
                }

            } catch (error) {
                console.error(
                    "承認者の復元に失敗しました。",
                    error
                );

                showCommonError(
                    "保存済みの承認者を復元できませんでした。通信状態を確認してください。"
                );
            }
        }
        }
    }

    function updateSelectedApprovalCount(
        approvalIndex
    ) {
        const heading =
            document.querySelector(
                '.selected-approval-users-heading[data-approval-index="' +
                approvalIndex +
                '"]'
            );

        if (!heading) {
            return;
        }

        const count =
            approvalUsers.has(approvalIndex)
                ? approvalUsers.get(approvalIndex).size
                : 0;

        heading.textContent =
            `選択済み（${count}人）`;
    }

    function addNotifyUser(
        approvalIndex,
        username,
        name
    ) {
        if (
            !username ||
            (
                approvalUsers.has(approvalIndex) &&
                approvalUsers
                    .get(approvalIndex)
                    .has(username)
            )
        ) {
            return;
        }

        if (!approvalUsers.has(approvalIndex)) {
            approvalUsers.set(
                approvalIndex,
                new Map()
            );
        }

        approvalUsers
            .get(approvalIndex)
            .set(username, name);

        updateSelectedApprovalCount(
            approvalIndex
        );

        const approvalSearchInput =
            document.getElementById(
                "approval_user_search_" + approvalIndex
            );

        if (approvalSearchInput) {
            approvalSearchInput.classList.remove(
                "common-error-target"
            );
        }

        const tag =
            document.createElement("span");

        tag.className =
            "selected-vehicle-tag";

        tag.dataset.username = username;

        const text =
            document.createTextNode(name);

        const remove =
            document.createElement("button");

        remove.type = "button";
        remove.className = "tag-remove-btn";
        remove.textContent = "×";
        remove.setAttribute(
            "aria-label",
            name + " を削除"
        );

        remove.addEventListener(
            "click",
            function () {
                const users =
                    approvalUsers.get(
                        approvalIndex
                    );

                if (users) {
                    users.delete(username);
                }

                updateSelectedApprovalCount(
                    approvalIndex
                );

                tag.remove();

                const candidateArea =
                    document.querySelector(
                        '.approval-candidate-users[data-approval-index="' +
                        approvalIndex +
                        '"]'
                    );

                if (candidateArea) {
                    const candidateWrapper =
                        candidateArea.closest(
                            ".approval-candidate-area"
                        );

                    if (candidateWrapper) {
                        candidateWrapper.classList.remove(
                            "is-hidden"
                        );
                    }
                }

                loadApprovalCandidates(
                    approvalIndex
                );

                const searchInput =
                    document.querySelector(
                        '.approval-user-search[data-approval-index="' +
                        approvalIndex +
                        '"]'
                    );

                const searchResults =
                    document.querySelector(
                        '.approval-user-search-results[data-approval-index="' +
                        approvalIndex +
                        '"]'
                    );

                if (
                    searchInput &&
                    searchResults &&
                    searchInput.value.trim()
                ) {
                    searchNotifyUsers(
                        searchInput,
                        searchResults
                    );
                }
            }
        );

        const hidden =
            document.createElement("input");

        hidden.type = "hidden";
        hidden.name =
            "approval_notify_users_" +
            approvalIndex;
        hidden.value = username;
        hidden.dataset.approvalIndex =
            String(approvalIndex);

        tag.appendChild(text);
        tag.appendChild(remove);
        tag.appendChild(hidden);

        const selectedArea =
            document.querySelector(
                '.selected-approval-users[data-approval-index="' +
                approvalIndex +
                '"]'
            );

        if (selectedArea) {
            selectedArea.appendChild(tag);
        }
    }

    function loadApprovalCandidates(
        targetApprovalIndex = null
    ) {
        fetch("/api/approval-candidates")
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(
                        "HTTP " + response.status
                    );
                }

                return response.json();
            })
            .then(function (data) {
                const users = data.users || [];

                document.querySelectorAll(
                    ".approval-candidate-users"
                ).forEach(function (candidateArea) {
                    const approvalIndex =
                        candidateArea.dataset.approvalIndex;

                    if (
                        targetApprovalIndex !== null &&
                        String(targetApprovalIndex) !==
                        String(approvalIndex)
                    ) {
                        return;
                    }

                    candidateArea.replaceChildren();

                    users.forEach(function (user) {
                        if (
                            !user.username ||
                            (
                                approvalUsers.has(approvalIndex) &&
                                approvalUsers
                                    .get(approvalIndex)
                                    .has(user.username)
                            )
                        ) {
                            return;
                        }

                        const button =
                            document.createElement(
                                "button"
                            );

                        button.type = "button";
                        button.className =
                            "vehicle-select-item";
                        button.dataset.username =
                            user.username;

                        const name =
                            document.createElement(
                                "strong"
                            );

                        name.textContent =
                            user.name || user.username;

                        const addMark =
                            document.createElement(
                                "span"
                            );

                        addMark.className =
                            "approval-candidate-add";
                        addMark.textContent = "＋";

                        button.appendChild(name);
                        button.appendChild(addMark);

                        button.addEventListener(
                            "click",
                            function () {
                                addNotifyUser(
                                    approvalIndex,
                                    user.username,
                                    user.name ||
                                    user.username
                                );

                                const searchResults =
                                    document.querySelector(
                                        '.approval-user-search-results[data-approval-index="' +
                                        approvalIndex +
                                        '"]'
                                    );

                                if (searchResults) {
                                    searchResults
                                        .querySelectorAll(
                                            ".vehicle-select-item"
                                        )
                                        .forEach(function (searchButton) {
                                            if (
                                                searchButton.dataset.username ===
                                                user.username
                                            ) {
                                                searchButton.remove();
                                            }
                                        });

                                    searchResults.classList.toggle(
                                        "is-hidden",
                                        searchResults.children.length === 0
                                    );
                                }

                                candidateArea
                                    .querySelectorAll(
                                        ".vehicle-select-item"
                                    )
                                    .forEach(function (candidateButton) {
                                        if (
                                            candidateButton.dataset.username ===
                                            user.username
                                        ) {
                                            candidateButton.remove();
                                        }
                                    });

                                const candidateWrapper =
                                    candidateArea.closest(
                                        ".approval-candidate-area"
                                    );

                                if (candidateWrapper) {
                                    candidateWrapper.classList.toggle(
                                        "is-hidden",
                                        candidateArea.children.length === 0
                                    );
                                }
                            }
                        );

                        candidateArea.appendChild(
                            button
                        );
                    });

                    const candidateWrapper =
                        candidateArea.closest(
                            ".approval-candidate-area"
                        );

                    if (candidateWrapper) {
                        candidateWrapper.classList.toggle(
                            "is-hidden",
                            candidateArea.children.length === 0
                        );
                    }
                });
            })
            .catch(function () {
                // 候補の取得失敗時も、
                // 現在の表示状態はそのまま維持する
            });
    }

    loadSavedNotifyUsers().then(function () {
        loadApprovalCandidates();
    });

    function searchNotifyUsers(
        searchInput,
        searchResults
    ) {
        if (!searchInput || !searchResults) {
            return;
        }

        const approvalIndex =
            searchInput.dataset.approvalIndex;

        const keyword =
            searchInput.value.trim();

        searchResults.replaceChildren();

        if (!keyword) {
            searchResults.classList.add(
                "is-hidden"
            );
            return;
        }

        fetch(
            "/api/mention-users?q=" +
            encodeURIComponent(keyword)
        )
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(
                        "HTTP " + response.status
                    );
                }

                return response.json();
            })
            .then(function (data) {
                searchResults.replaceChildren();

                const users =
                    data.users || [];

                users.forEach(function (user) {
                    const allowGeneral =
                        searchInput.dataset.allowGeneral === "1";

                    if (
                        !user.username ||
                        (
                            !allowGeneral &&
                            user.role !== "admin"
                        ) ||
                        (
                            approvalUsers.has(approvalIndex) &&
                            approvalUsers
                                .get(approvalIndex)
                                .has(user.username)
                        )
                    ) {
                        return;
                    }

                    const button =
                        document.createElement(
                            "button"
                        );

                    button.type = "button";
                    button.className =
                        "vehicle-select-item";
                    button.dataset.username =
                        user.username;

                    const name =
                        document.createElement(
                            "strong"
                        );

                    name.textContent =
                        user.name || "";

                    button.appendChild(name);

                    button.addEventListener(
                        "click",
                        function () {
                            addNotifyUser(
                                approvalIndex,
                                user.username,
                                user.name ||
                                user.username
                            );

                            const candidateArea =
                                document.querySelector(
                                    '.approval-candidate-users[data-approval-index="' +
                                    approvalIndex +
                                    '"]'
                                );

                            if (candidateArea) {
                                candidateArea
                                    .querySelectorAll(
                                        ".vehicle-select-item"
                                    )
                                    .forEach(function (candidateButton) {
                                        if (
                                            candidateButton.dataset.username ===
                                            user.username
                                        ) {
                                            candidateButton.remove();
                                        }
                                    });

                                const candidateWrapper =
                                    candidateArea.closest(
                                        ".approval-candidate-area"
                                    );

                                if (candidateWrapper) {
                                    candidateWrapper.classList.toggle(
                                        "is-hidden",
                                        candidateArea.children.length === 0
                                    );
                                }
                            }

                            searchInput.value = "";
                            searchResults.replaceChildren();
                            searchResults.classList.add(
                                "is-hidden"
                            );
                        }
                    );

                    searchResults.appendChild(
                        button
                    );
                });

                searchResults.classList.toggle(
                    "is-hidden",
                    searchResults.children.length === 0
                );
            })
            .catch(function () {
                searchResults.replaceChildren();
                searchResults.classList.add(
                    "is-hidden"
                );

                showCommonError(
                    "承認者を取得できませんでした。"
                );
            });
    }

    document.querySelectorAll(
        ".approval-user-search"
    ).forEach(function (searchInput) {
        searchInput.addEventListener(
            "input",
            function () {
                if (!searchInput.value.trim()) {
                    const searchResults =
                        document.querySelector(
                            '.approval-user-search-results[data-approval-index="' +
                            searchInput.dataset.approvalIndex +
                            '"]'
                        );

                    if (searchResults) {
                        searchResults.replaceChildren();
                        searchResults.classList.add(
                            "is-hidden"
                        );
                    }

                    return;
                }

                clearTimeout(
                    searchInput._approvalSearchTimer
                );

                searchInput._approvalSearchTimer =
                    setTimeout(
                        function () {
                            const searchResults =
                                document.querySelector(
                                    '.approval-user-search-results[data-approval-index="' +
                                    searchInput.dataset.approvalIndex +
                                    '"]'
                                );

                            searchNotifyUsers(
                                searchInput,
                                searchResults
                            );
                        },
                        250
                    );
            }
        );
    });

    function prepareNextFileInput(input) {
        if (!input.files || input.files.length === 0) {
            return;
        }

        const label = input.closest(".file-upload-button");

        if (!label) {
            return;
        }

        const nextInput = input.cloneNode();

        nextInput.value = "";

        input.removeAttribute("id");

        label.parentNode.insertBefore(input, label);
        label.appendChild(nextInput);
    }

    function removeSelectedFile(fileInput, fileIndex) {
        if (!fileInput.files) {
            return;
        }

        const cell = fileInput.closest(".file-upload-cell");

        if (!cell) {
            return;
        }

        const removedFile = fileInput.files[fileIndex];

        if (removedFile) {
            const removedFileKey =
                removedFile.name +
                ":" +
                removedFile.size +
                ":" +
                removedFile.lastModified;

            if (cell.dataset.mainFileKey === removedFileKey) {
                delete cell.dataset.mainFileKey;
            }
        }

        const transfer = new DataTransfer();

        Array.from(fileInput.files).forEach(
            function (file, index) {
                if (index !== fileIndex) {
                    transfer.items.add(file);
                }
            }
        );

        fileInput.files = transfer.files;

        if (fileInput.files.length === 0) {
            const label = fileInput.closest(".file-upload-button");

            if (!label) {
                fileInput.remove();
            }
        }

        const remainingInput = cell.querySelector(
            ".js-file-upload-input"
        );

        if (remainingInput) {
            showSelectedFiles(remainingInput);
        }
    }

    function showSelectedFiles(input, showAll = false) {
        const cell = input.closest(".file-upload-cell");

        if (!cell) {
            return;
        }

        const area = cell.querySelector(".selected-file-names");

        if (!area) {
            return;
        }

        area.innerHTML = "";
        area.classList.toggle(
            "is-expanded",
            showAll
        );

        const inputs = cell.querySelectorAll(
            ".js-file-upload-input"
        );

        const selectedFiles = [];

        inputs.forEach(function (fileInput) {
            if (
                !fileInput.files ||
                fileInput.files.length === 0
            ) {
                return;
            }

            Array.from(fileInput.files).forEach(
                function (file, fileIndex) {
                    selectedFiles.push({
                        file: file,
                        fileInput: fileInput,
                        fileIndex: fileIndex,
                        fileKey:
                            file.name +
                            ":" +
                            file.size +
                            ":" +
                            file.lastModified
                    });
                }
            );
        });

        const mainFileKey = cell.dataset.mainFileKey;

        if (mainFileKey) {
            const mainIndex = selectedFiles.findIndex(
                function (entry) {
                    return entry.fileKey === mainFileKey;
                }
            );

            if (mainIndex > 0) {
                const mainFile =
                    selectedFiles.splice(mainIndex, 1)[0];

                selectedFiles.unshift(mainFile);
            }
        }

        const visibleFiles = showAll
            ? selectedFiles
            : selectedFiles.slice(0, 2);

        visibleFiles.forEach(function (entry) {
            const file = entry.file;
            const fileInput = entry.fileInput;
            const fileIndex = entry.fileIndex;
                    const item =
                        document.createElement("div");

                    item.className =
                        "selected-file-preview";

                    if (file.type.startsWith("image/")) {
                        const image =
                            document.createElement("img");

                        image.className =
                            "selected-file-preview-image";

                        image.alt = file.name;

                        const objectUrl =
                            URL.createObjectURL(file);

                        image.src = objectUrl;

                        image.addEventListener(
                            "load",
                            function () {
                                URL.revokeObjectURL(objectUrl);
                            }
                        );

                        image.addEventListener(
                            "click",
                            function () {
                                cell.dataset.mainFileKey =
                                    entry.fileKey;

                                showSelectedFiles(
                                    input,
                                    showAll
                                );
                            }
                        );

                        item.appendChild(image);
                    }

                    const removeButton =
                        document.createElement("button");

                    removeButton.type = "button";
                    removeButton.className =
                        "selected-file-preview-remove";

                    removeButton.textContent = "×";
                    removeButton.setAttribute(
                        "aria-label",
                        file.name + " を削除"
                    );

                    removeButton.addEventListener(
                        "click",
                        function () {
                            removeSelectedFile(
                                fileInput,
                                fileIndex
                            );
                        }
                    );

                    item.appendChild(removeButton);

                    if (!file.type.startsWith("image/")) {
                        const name =
                            document.createElement("div");

                        name.className =
                            "selected-file-preview-name";

                        name.textContent = file.name;

                        item.appendChild(name);
                    }

                    area.appendChild(item);
        });

        if (!showAll && selectedFiles.length > 2) {
            const more = document.createElement("button");

            more.type = "button";
            more.className = "selected-file-more";

            const hiddenFiles = selectedFiles.slice(2);
            const hiddenImagesOnly = hiddenFiles.every(
                function (entry) {
                    return entry.file.type.startsWith("image/");
                }
            );

            more.textContent =
                "＋" +
                hiddenFiles.length +
                (hiddenImagesOnly ? "枚" : "件");

            more.addEventListener(
                "click",
                function () {
                    showSelectedFiles(input, true);
                }
            );

            area.appendChild(more);
        }

        if (showAll && selectedFiles.length > 2) {
            const collapse = document.createElement("button");

            collapse.type = "button";
            collapse.className = "selected-file-collapse";
            collapse.textContent = "閉じる";

            collapse.addEventListener(
                "click",
                function () {
                    showSelectedFiles(input, false);
                }
            );

            area.appendChild(collapse);
        }
    }

    function selectVehicle(vehicle) {
        if (
            !targetVehicle ||
            !selectedVehicleDisplay ||
            !vehicleSearchResults ||
            !vehicleSearchInput
        ) {
            return;
        }

        targetVehicle.value = vehicle.vehicle_record_id;

        selectedVehicleDisplay.textContent =
            vehicle.number || "ナンバー未登録";

        vehicleSearchResults.innerHTML = "";
        vehicleSearchInput.value = "";
    }


    function searchVehicles() {
        if (!vehicleSearchInput || !vehicleSearchResults) {
            return;
        }

        const keyword = vehicleSearchInput.value.trim();

        if (!keyword) {
            vehicleSearchResults.innerHTML = "";
            return;
        }

        fetch(
            "/api/vehicles?q=" +
            encodeURIComponent(keyword)
        )
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(
                        "HTTP " + response.status
                    );
                }

                return response.json();
            })
            .then(function (data) {
                vehicleSearchResults.innerHTML = "";

                if (!data.results || data.results.length === 0) {
                    const empty = document.createElement("div");
                    empty.textContent =
                        "該当する車両はありません。";

                    vehicleSearchResults.appendChild(empty);
                    return;
                }

                data.results.forEach(function (vehicle) {
                    const row =
                        document.createElement("div");

                    row.className =
                        "vehicle-search-result-row";

                    row.textContent =
                        vehicle.number || "ナンバー未登録";

                    row.addEventListener(
                        "click",
                        function () {
                            selectVehicle(vehicle);
                        }
                    );

                    vehicleSearchResults.appendChild(row);
                });
            })
            .catch(function () {
                showCommonError(
                    "車両を取得できませんでした。通信状態を確認して、もう一度検索してください。"
                );

                vehicleSearchResults.innerHTML = "";

                const errorMessage =
                    document.createElement("div");

                errorMessage.className = "help-text";
                errorMessage.textContent =
                    "車両を取得できませんでした。通信状態を確認して、もう一度検索してください。";

                vehicleSearchResults.appendChild(
                    errorMessage
                );
            });
    }

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
            button.className =
                "target-user-option";

            button.textContent =
                driver.dataset.name || "";

            button.addEventListener(
                "click",
                function () {
                    targetUserSearch.value =
                        driver.dataset.name || "";

                    targetUserInput.value =
                        driver.dataset.employeeId || "";

                    if (targetType) {
                        targetType.value = "user";
                    }

                    driverSearchResults.replaceChildren();

                    driverSearchResults.classList.add(
                        "is-hidden"
                    );
                }
            );

            driverSearchResults.appendChild(
                button
            );
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
        "focus",
        updateDriverSearchResults
    );

    targetUserSearch?.addEventListener(
        "compositionend",
        updateDriverSearchResults
    );

    document.addEventListener(
        "click",
        function (event) {
            if (
                !event.target.closest(
                    "#target_user_search"
                ) &&
                !event.target.closest(
                    "#driver_search_results"
                )
            ) {
                driverSearchResults?.classList.add(
                    "is-hidden"
                );
            }
        }
    );    

    function switchChecklistTarget() {
        if (!targetType) {
            return;
        }

        const type = targetType.value;

        if (targetUserArea) {
            targetUserArea.classList.toggle(
                "is-hidden",
                type !== "user"
            );
        }

        if (targetVehicleArea) {
            targetVehicleArea.classList.toggle(
                "is-hidden",
                type !== "vehicle"
            );
        }

        if (targetOfficeArea) {
            targetOfficeArea.classList.toggle(
                "is-hidden",
                type !== "office"
            );
        }

        document.querySelectorAll(
            ".checklist-result-patrol-option"
        ).forEach(function (option) {
            const checkbox = option.querySelector(
                ".patrol-link-checkbox"
            );

            const supported = type === "user";

            option.classList.toggle(
                "is-hidden",
                !supported
            );

            if (checkbox) {
                checkbox.disabled = !supported;

                if (!supported) {
                    checkbox.checked = false;
                }
            }
        });
    }


    targetType?.addEventListener(
        "change",
        switchChecklistTarget
    );


    document.addEventListener(
        "change",
        function (event) {
            if (
                event.target.matches(
                    ".js-file-upload-input"
                )
            ) {
                showSelectedFiles(event.target);
                prepareNextFileInput(event.target);
            }
        }
    );

    const checklistResultForm =
        document.querySelector(
            'form[enctype="multipart/form-data"]'
        );

    if (checklistResultForm) {
        checklistResultForm.addEventListener(
            "submit",
            function (event) {
                clearCommonErrors();
                let totalSize = 0;
                let totalFiles = 0;

                checklistResultForm.querySelectorAll(
                    ".js-file-upload-input"
                ).forEach(function (input) {
                    Array.from(
                        input.files || []
                    ).forEach(function (file) {
                        totalSize += file.size;
                        totalFiles += 1;
                    });
                });

                if (totalFiles > 50) {
                    event.preventDefault();

                    showCommonError(
                        "一度にアップロードできるファイルは50件までです。"
                    );

                    return;
                }

                const maxSize =
                    1024 * 1024 * 1024;

                if (totalSize > maxSize) {
                    event.preventDefault();

                    showCommonError(
                        "写真・動画・ファイルの合計を1GB以下にしてください。"
                    );
                }
            }
        );
    }
    
    document.addEventListener(
        "click",
        function (event) {
            const button =
                event.target.closest(".saved-file-more");

            if (!button) {
                return;
            }

            const area =
                button.closest(".saved-file-names");

            if (!area) {
                return;
            }

            const isExpanded =
                area.classList.toggle("is-expanded");

            button.textContent = isExpanded
                ? "閉じる"
                : "＋" +
                  area.querySelectorAll(
                      '[data-saved-extra="true"]'
                  ).length +
                  "件";
        }
    );


    if (vehicleSearchInput) {
        vehicleSearchInput.addEventListener(
            "input",
            function () {
                clearTimeout(vehicleSearchTimer);

                vehicleSearchTimer =
                    setTimeout(
                        searchVehicles,
                        300
                    );
            }
        );
    }


    const resultForm = document.querySelector(
        'form[enctype="multipart/form-data"]'
    );

    const resultSubmitButton = document.querySelector(
        ".checklist-result-submit"
    );

    let invalidMessageShown = false;

    function clearValidationMessages() {
        document.querySelectorAll(
            ".checklist-validation-error"
        ).forEach(function (message) {
            message.remove();
        });

        document.querySelectorAll(
            ".checklist-validation-invalid"
        ).forEach(function (element) {
            element.classList.remove(
                "checklist-validation-invalid"
            );
        });
    }

    if (resultSubmitButton) {
        resultSubmitButton.addEventListener(
            "click",
            function () {
                invalidMessageShown = false;
                clearValidationMessages();
            }
        );
    }

    if (resultForm) {
        resultForm.addEventListener(
            "invalid",
            function (event) {
                event.preventDefault();

                const isFirstInvalid =
                    !invalidMessageShown;

                if (isFirstInvalid) {
                    invalidMessageShown = true;
                }

                const field = event.target;
                const row = field.closest("tr");
                const card =
                    row ||
                    field.closest(".card") ||
                    field.parentElement;

                if (!card) {
                    return;
                }

                card.classList.add(
                    "checklist-validation-invalid"
                );

                const message =
                    document.createElement("div");

                message.className =
                    "checklist-validation-error";

                if (field.type === "radio") {
                    message.textContent =
                        "評価を選択してください。";
                } else {
                    message.textContent =
                        "必須項目を入力してください。";
                }

                showCommonError(
                    message.textContent,
                    field.id || field.name
                );

                const choiceGroup = field.closest(
                    ".checklist-result-choice-group"
                );

                if (choiceGroup) {
                    choiceGroup.insertAdjacentElement(
                        "afterend",
                        message
                    );
                } else {
                    field.insertAdjacentElement(
                        "afterend",
                        message
                    );
                }

                if (isFirstInvalid) {
                    card.scrollIntoView({
                        behavior: "smooth",
                        block: "center"
                    });

                    window.setTimeout(function () {
                        field.focus({
                            preventScroll: true
                        });
                    }, 300);
                }
            },
            true
        );

        resultForm.addEventListener(
            "change",
            function (event) {
                const row = event.target.closest("tr");

                if (!row) {
                    return;
                }

                row.classList.remove(
                    "checklist-validation-invalid"
                );

                row.querySelectorAll(
                    ".checklist-validation-error"
                ).forEach(function (message) {
                    message.remove();
                });
            }
        );
    }

    switchChecklistTarget();
});