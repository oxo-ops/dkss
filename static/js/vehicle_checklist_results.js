document.addEventListener("DOMContentLoaded", function () {
    const config =
        document.getElementById("vehicleChecklistConfig");

    if (!config) {
        return;
    }

    const displayMode =
        config.dataset.displayMode || "";

    const currentYear =
        config.dataset.year || "";

    const currentMonth =
        config.dataset.month || "";

    const companyCode =
        config.dataset.companyCode || "";

    const reminderUrl =
        config.dataset.reminderUrl || "";

    function parseJson(value) {
        try {
            return JSON.parse(value || "[]");
        } catch (error) {
            console.error("JSON解析エラー:", error);
            return [];
        }
    }

    const savedNotifyUsers =
        parseJson(config.dataset.savedNotifyUsers);

    const savedReminderNotifyUsers =
        parseJson(
            config.dataset.savedReminderNotifyUsers
        );

    const csrfInput =
        document.querySelector(
            'input[name="csrf_token"]'
        );

    const csrfToken =
        csrfInput ? csrfInput.value : "";


    /* =========================
       点検完了確認
    ========================= */

    const completeForm =
        document.querySelector(
            ".js-vehicle-check-complete-form"
        );

    if (completeForm) {
        completeForm.addEventListener(
            "submit",
            function (event) {
                if (
                    !window.confirm(
                        "この日の点検を完了しますか？"
                    )
                ) {
                    event.preventDefault();
                }
            }
        );
    }


    /* =========================
       詳細モーダル
    ========================= */

    const detailModal =
        document.getElementById("detailModal");

    const textModal =
        document.getElementById("textModal");


    function renderFiles(
        areaId,
        filesText,
        titleText
    ) {
        const area =
            document.getElementById(areaId);

        if (!area) {
            return;
        }

        area.replaceChildren();

        if (!filesText) {
            return;
        }

        const files = filesText
            .split(",")
            .map(function (filename) {
                return filename.trim();
            })
            .filter(Boolean);

        if (files.length === 0) {
            return;
        }

        const title =
            document.createElement("p");

        const strong =
            document.createElement("strong");

        strong.textContent = titleText;

        title.appendChild(strong);
        area.appendChild(title);

        files.forEach(function (filename) {
            const ext =
                filename.split(".").pop().toLowerCase();

            const path =
                "/static/uploads/" + filename;

            if (
                ["jpg", "jpeg", "png", "gif", "webp"]
                    .includes(ext)
            ) {
                const img =
                    document.createElement("img");

                img.src = path;
                img.className = "preview-image";

                img.addEventListener(
                    "click",
                    function () {
                        window.open(
                            path,
                            "_blank"
                        );
                    }
                );

                area.appendChild(img);

            } else if (
                ["mp4", "webm", "mov", "m4v"]
                    .includes(ext)
            ) {
                const video =
                    document.createElement("video");

                video.src = path;
                video.controls = true;
                video.preload = "metadata";
                video.className = "preview-video";

                area.appendChild(video);

            } else {
                const link =
                    document.createElement("a");

                link.href = path;
                link.target = "_blank";

                if (
                    [
                        "avi",
                        "mkv",
                        "mts",
                        "m2ts",
                        "mpg",
                        "mpeg"
                    ].includes(ext)
                ) {
                    link.textContent =
                        "▶ 動画を開く：" + filename;
                } else {
                    link.textContent = filename;
                }

                area.appendChild(link);
            }
        });
    }


    function openDetailModal(button) {
        const content =
            button.dataset.content || "";

        const category =
            button.dataset.category || "";

        const criteria =
            button.dataset.criteria || "";

        const day =
            button.dataset.day || "";

        const itemNo =
            button.dataset.itemNo || "";

        const comment =
            button.dataset.comment || "";

        const filesText =
            button.dataset.files || "";

        const criteriaFilesText =
            button.dataset.criteriaFiles || "";

        document.getElementById(
            "detailTitle"
        ).textContent = content;

        document.getElementById(
            "detailContent"
        ).value = content;

        document.getElementById(
            "detailCategory"
        ).value = category;

        document.getElementById(
            "detailCriteria"
        ).value = criteria;

        document.getElementById(
            "detailCriteriaText"
        ).textContent =
            criteria || "未設定";

        const detailYear =
            document.getElementById(
                "detailYear"
            );

        const detailMonth =
            document.getElementById(
                "detailMonth"
            );

        const detailDay =
            document.getElementById(
                "detailDay"
            );

        if (displayMode === "year_list") {
            detailYear.value =
                String(day);

            detailMonth.value = "01";
            detailDay.value = "01";

        } else if (
            displayMode === "month_list"
        ) {
            detailYear.value =
                currentYear;

            detailMonth.value =
                String(day).padStart(
                    2,
                    "0"
                );

            detailDay.value = "01";

        } else {
            detailYear.value =
                currentYear;

            detailMonth.value =
                currentMonth;

            detailDay.value =
                String(day).padStart(
                    2,
                    "0"
                );
        }

        document.getElementById(
            "detailItemNo"
        ).value = itemNo;

        const commentEditor =
            document.getElementById(
                "detailCommentEditor"
            );

        const commentInput =
            document.querySelector(
                '#detailModal input[type="hidden"][name="comment"]'
            );

        if (
            commentEditor &&
            typeof renderMentionValue ===
                "function"
        ) {
            renderMentionValue(
                commentEditor,
                comment
            );
        }

        if (commentInput) {
            commentInput.value = comment;
        }

        renderFiles(
            "criteriaFilesArea",
            criteriaFilesText,
            "評価基準ファイル："
        );

        renderFiles(
            "savedFilesArea",
            filesText,
            "登録済みファイル："
        );

        const preview =
            document.getElementById(
                "detailPreview"
            );

        if (preview) {
            preview.replaceChildren();
        }

        if (detailModal) {
            detailModal.classList.remove(
                "is-hidden"
            );

            detailModal.classList.add(
                "is-open"
            );
        }
    }


    function closeDetailModal() {
        if (!detailModal) {
            return;
        }

        detailModal.classList.remove(
            "is-open"
        );

        detailModal.classList.add(
            "is-hidden"
        );
    }


    function openTextModal(button) {
        const title =
            button.dataset.title || "";

        const text =
            button.dataset.text || "";

        document.getElementById(
            "textModalTitle"
        ).textContent = title;

        document.getElementById(
            "textModalBody"
        ).textContent = text;

        if (textModal) {
            textModal.classList.remove(
                "is-hidden"
            );

            textModal.classList.add(
                "is-open"
            );
        }
    }


    function closeTextModal() {
        if (!textModal) {
            return;
        }

        textModal.classList.remove(
            "is-open"
        );

        textModal.classList.add(
            "is-hidden"
        );
    }


    document.addEventListener(
        "click",
        function (event) {
            const detailButton =
                event.target.closest(
                    ".js-open-detail"
                );

            if (detailButton) {
                openDetailModal(
                    detailButton
                );

                return;
            }

            const textButton =
                event.target.closest(
                    ".js-open-text"
                );

            if (textButton) {
                openTextModal(
                    textButton
                );

                return;
            }

            if (
                event.target.closest(
                    ".js-close-detail-modal"
                )
            ) {
                closeDetailModal();
                return;
            }

            if (
                event.target.closest(
                    ".js-close-text-modal"
                )
            ) {
                closeTextModal();
            }
        }
    );


    /* =========================
       詳細ファイルプレビュー
    ========================= */

    function previewDetailFiles(input) {
        const preview =
            document.getElementById(
                "detailPreview"
            );

        if (!preview) {
            return;
        }

        preview.replaceChildren();

        Array.from(
            input.files || []
        ).forEach(function (file) {
            const ext =
                file.name
                    .split(".")
                    .pop()
                    .toLowerCase();

            if (
                file.type.startsWith(
                    "image/"
                )
            ) {
                const img =
                    document.createElement(
                        "img"
                    );

                img.src =
                    URL.createObjectURL(
                        file
                    );

                img.className =
                    "preview-image";

                img.addEventListener(
                    "click",
                    function () {
                        window.open(
                            img.src,
                            "_blank"
                        );
                    }
                );

                preview.appendChild(img);

            } else if (
                file.type.startsWith(
                    "video/"
                ) &&
                [
                    "mp4",
                    "webm",
                    "mov",
                    "m4v"
                ].includes(ext)
            ) {
                const video =
                    document.createElement(
                        "video"
                    );

                video.src =
                    URL.createObjectURL(
                        file
                    );

                video.controls = true;
                video.preload = "metadata";
                video.className =
                    "preview-video";

                preview.appendChild(video);

            } else {
                const p =
                    document.createElement(
                        "p"
                    );

                if (
                    [
                        "avi",
                        "mkv",
                        "mts",
                        "m2ts",
                        "mpg",
                        "mpeg"
                    ].includes(ext)
                ) {
                    p.textContent =
                        "▶ 動画ファイル：" +
                        file.name;
                } else {
                    p.textContent =
                        file.name;
                }

                preview.appendChild(p);
            }
        });
    }


    document.addEventListener(
        "change",
        function (event) {
            if (
                event.target.matches(
                    ".js-detail-file-input"
                )
            ) {
                previewDetailFiles(
                    event.target
                );
            }
        }
    );


    /* =========================
       インライン保存
    ========================= */

    let checklistPageY = null;
    let checklistPageX = null;
    let checklistTableX = null;


    function rememberChecklistPosition() {
        const scrollArea =
            document.querySelector(
                ".table-scroll"
            );

        checklistPageY =
            window.scrollY;

        checklistPageX =
            window.scrollX;

        checklistTableX =
            scrollArea
                ? scrollArea.scrollLeft
                : 0;
    }


    function restoreChecklistPosition() {
        const scrollArea =
            document.querySelector(
                ".table-scroll"
            );

        if (
            checklistPageY !== null
        ) {
            window.scrollTo(
                checklistPageX,
                checklistPageY
            );
        }

        if (
            scrollArea &&
            checklistTableX !== null
        ) {
            scrollArea.scrollLeft =
                checklistTableX;
        }
    }


    async function saveInlineCheck(
        input
    ) {
        const form = input.form;

        if (!form) {
            return;
        }

        input.blur();

        restoreChecklistPosition();

        try {
            const formData =
                new FormData(form);

            await fetch(
                form.action,
                {
                    method: "POST",
                    body: formData
                }
            );
        } catch (error) {
            console.error(
                "保存エラー:",
                error
            );
        }

        restoreChecklistPosition();

        requestAnimationFrame(
            restoreChecklistPosition
        );

        setTimeout(
            restoreChecklistPosition,
            50
        );

        setTimeout(
            restoreChecklistPosition,
            200
        );
    }


    document.addEventListener(
        "pointerdown",
        function (event) {
            if (
                event.target.matches(
                    ".js-inline-check-input"
                )
            ) {
                rememberChecklistPosition();
            }
        }
    );


    document.addEventListener(
        "change",
        function (event) {
            if (
                event.target.matches(
                    ".js-inline-check-input"
                )
            ) {
                saveInlineCheck(
                    event.target
                );
            }
        }
    );


    /* =========================
       点検完了通知先
    ========================= */

    const notifySearch =
        document.getElementById(
            "notify_user_search"
        );

    const notifyResults =
        document.getElementById(
            "notify_user_search_results"
        );

    const notifySelected =
        document.getElementById(
            "selected_notify_users"
        );

    const notifyUsers =
        new Map();


    savedNotifyUsers.forEach(
        function (name) {
            notifyUsers.set(
                name,
                name
            );
        }
    );


    function renderNotifyUsers() {
        if (!notifySelected) {
            return;
        }

        notifySelected.replaceChildren();

        notifyUsers.forEach(
            function (name, username) {
                const tag =
                    document.createElement(
                        "span"
                    );

                tag.className =
                    "selected-vehicle-tag";

                const text =
                    document.createTextNode(
                        name + " "
                    );

                const remove =
                    document.createElement(
                        "button"
                    );

                remove.type = "button";
                remove.className =
                    "tag-remove-btn";

                remove.dataset.username =
                    username;

                remove.textContent = "×";

                const hidden =
                    document.createElement(
                        "input"
                    );

                hidden.type = "hidden";
                hidden.name =
                    "notify_users";

                hidden.value = name;

                tag.appendChild(text);
                tag.appendChild(remove);
                tag.appendChild(hidden);

                notifySelected.appendChild(
                    tag
                );
            }
        );
    }


    renderNotifyUsers();


    if (notifySelected) {
        notifySelected.addEventListener(
            "click",
            function (event) {
                const button =
                    event.target.closest(
                        ".tag-remove-btn"
                    );

                if (!button) {
                    return;
                }

                notifyUsers.delete(
                    button.dataset.username
                );

                renderNotifyUsers();
            }
        );
    }


    function renderUserSearchResult(
        container,
        user,
        onSelect
    ) {
        const item =
            document.createElement(
                "button"
            );

        item.type = "button";
        item.className =
            "vehicle-select-item";

        const name =
            document.createElement(
                "strong"
            );

        name.textContent =
            user.name || "";

        const detail =
            document.createElement(
                "span"
            );

        const detailParts = [
            user.office,
            user.username
        ].filter(Boolean);

        detail.textContent =
            detailParts.join(" / ");

        item.appendChild(name);
        item.appendChild(detail);

        item.addEventListener(
            "click",
            function () {
                onSelect(user);
            }
        );

        container.appendChild(item);
    }


    function showNoUsers(container) {
        container.replaceChildren();

        const p =
            document.createElement("p");

        p.className = "help-text";

        p.textContent =
            "該当するユーザーがいません。";

        container.appendChild(p);

        container.classList.remove(
            "is-hidden"
        );
    }


    let notifyTimer = null;

    if (
        notifySearch &&
        notifyResults
    ) {
        notifySearch.addEventListener(
            "input",
            function () {
                clearTimeout(
                    notifyTimer
                );

                const keyword =
                    notifySearch.value
                        .trim();

                if (!keyword) {
                    notifyResults
                        .replaceChildren();

                    notifyResults
                        .classList.add(
                            "is-hidden"
                        );

                    return;
                }

                notifyTimer =
                    setTimeout(
                        async function () {
                            const response =
                                await fetch(
                                    "/api/mention-users?q=" +
                                    encodeURIComponent(
                                        keyword
                                    )
                                );

                            const data =
                                await response.json();

                            notifyResults
                                .replaceChildren();

                            if (
                                !data.users ||
                                data.users
                                    .length === 0
                            ) {
                                showNoUsers(
                                    notifyResults
                                );

                                return;
                            }

                            data.users.forEach(
                                function (
                                    user
                                ) {
                                    renderUserSearchResult(
                                        notifyResults,
                                        user,
                                        function (
                                            selectedUser
                                        ) {
                                            if (
                                                notifyUsers.has(
                                                    selectedUser.name
                                                )
                                            ) {
                                                return;
                                            }

                                            notifyUsers.set(
                                                selectedUser.name,
                                                selectedUser.name
                                            );

                                            renderNotifyUsers();

                                            notifySearch.value =
                                                "";

                                            notifyResults
                                                .replaceChildren();

                                            notifyResults
                                                .classList.add(
                                                    "is-hidden"
                                                );
                                        }
                                    );
                                }
                            );

                            notifyResults
                                .classList.remove(
                                    "is-hidden"
                                );
                        },
                        250
                    );
            }
        );
    }


    /* =========================
       点検未実施通知先
    ========================= */

    const reminderSearch =
        document.getElementById(
            "reminder_notify_user_search"
        );

    const reminderResults =
        document.getElementById(
            "reminder_notify_user_search_results"
        );

    const reminderSelected =
        document.getElementById(
            "selected_reminder_notify_users"
        );

    const reminderUsers =
        new Map();


    savedReminderNotifyUsers.forEach(
        function (name) {
            reminderUsers.set(
                name,
                name
            );
        }
    );


    async function saveReminderUsers() {
        if (!reminderUrl) {
            return;
        }

        const currentVehicleId =
            document.getElementById(
                "vehicle_id"
            );

        const formData =
            new FormData();

        formData.append(
            "csrf_token",
            csrfToken
        );

        formData.append(
            "vehicle_id",
            currentVehicleId
                ? currentVehicleId.value
                : ""
        );

        reminderUsers.forEach(
            function (name) {
                formData.append(
                    "reminder_notify_users",
                    name
                );
            }
        );

        const response =
            await fetch(
                reminderUrl,
                {
                    method: "POST",
                    body: formData
                }
            );

        if (!response.ok) {
            console.error(
                "点検忘れ通知先の保存に失敗しました。"
            );
        }
    }


    function renderReminderUsers() {
        if (!reminderSelected) {
            return;
        }

        reminderSelected
            .replaceChildren();

        reminderUsers.forEach(
            function (name, username) {
                const tag =
                    document.createElement(
                        "span"
                    );

                tag.className =
                    "selected-vehicle-tag";

                const text =
                    document.createTextNode(
                        name + " "
                    );

                const remove =
                    document.createElement(
                        "button"
                    );

                remove.type = "button";

                remove.className =
                    "tag-remove-btn reminder-tag-remove-btn";

                remove.dataset.username =
                    username;

                remove.textContent = "×";

                tag.appendChild(text);
                tag.appendChild(remove);

                reminderSelected
                    .appendChild(tag);
            }
        );
    }


    renderReminderUsers();


    if (reminderSelected) {
        reminderSelected
            .addEventListener(
                "click",
                function (event) {
                    const button =
                        event.target.closest(
                            ".reminder-tag-remove-btn"
                        );

                    if (!button) {
                        return;
                    }

                    reminderUsers.delete(
                        button.dataset.username
                    );

                    renderReminderUsers();
                    saveReminderUsers();
                }
            );
    }


    let reminderTimer = null;

    if (
        reminderSearch &&
        reminderResults
    ) {
        reminderSearch
            .addEventListener(
                "input",
                function () {
                    clearTimeout(
                        reminderTimer
                    );

                    const keyword =
                        reminderSearch.value
                            .trim();

                    if (!keyword) {
                        reminderResults
                            .replaceChildren();

                        reminderResults
                            .classList.add(
                                "is-hidden"
                            );

                        return;
                    }

                    reminderTimer =
                        setTimeout(
                            async function () {
                                const response =
                                    await fetch(
                                        "/api/mention-users?q=" +
                                        encodeURIComponent(
                                            keyword
                                        )
                                    );

                                const data =
                                    await response.json();

                                reminderResults
                                    .replaceChildren();

                                if (
                                    !data.users ||
                                    data.users
                                        .length ===
                                        0
                                ) {
                                    showNoUsers(
                                        reminderResults
                                    );

                                    return;
                                }

                                data.users.forEach(
                                    function (
                                        user
                                    ) {
                                        renderUserSearchResult(
                                            reminderResults,
                                            user,
                                            function (
                                                selectedUser
                                            ) {
                                                if (
                                                    reminderUsers.has(
                                                        selectedUser.name
                                                    )
                                                ) {
                                                    return;
                                                }

                                                reminderUsers.set(
                                                    selectedUser.name,
                                                    selectedUser.name
                                                );

                                                renderReminderUsers();
                                                saveReminderUsers();

                                                reminderSearch.value =
                                                    "";

                                                reminderResults
                                                    .replaceChildren();

                                                reminderResults
                                                    .classList.add(
                                                        "is-hidden"
                                                    );
                                            }
                                        );
                                    }
                                );

                                reminderResults
                                    .classList.remove(
                                        "is-hidden"
                                    );
                            },
                            250
                        );
                }
            );
    }


    /* =========================
       車両検索
    ========================= */

    const vehicleSearch =
        document.getElementById(
            "vehicle_search"
        );

    const vehicleSearchResults =
        document.getElementById(
            "vehicle_search_results"
        );

    const vehicleId =
        document.getElementById(
            "vehicle_id"
        );

    const selectedVehicleDisplay =
        document.getElementById(
            "selected_vehicle_display"
        );

    const vehicleFilterForm =
        document.getElementById(
            "vehicle_check_filter"
        );

    let vehicleSearchTimer = null;


    document.querySelectorAll(
        ".favorite-vehicle-shortcut"
    ).forEach(function (button) {
        button.addEventListener(
            "click",
            function () {
                if (
                    !vehicleId ||
                    !vehicleFilterForm
                ) {
                    return;
                }

                vehicleId.value =
                    button.dataset.vehicleId;

                vehicleFilterForm
                    .requestSubmit();
            }
        );
    });


    if (
        vehicleSearch &&
        vehicleSearchResults &&
        vehicleId &&
        vehicleFilterForm
    ) {
        vehicleSearch.addEventListener(
            "input",
            function () {
                clearTimeout(
                    vehicleSearchTimer
                );

                const keyword =
                    vehicleSearch.value
                        .trim();

                if (!keyword) {
                    vehicleSearchResults
                        .replaceChildren();

                    vehicleSearchResults
                        .classList.add(
                            "is-hidden"
                        );

                    return;
                }

                vehicleSearchTimer =
                    setTimeout(
                        async function () {
                            const params =
                                new URLSearchParams();

                            params.set(
                                "q",
                                keyword
                            );

                            if (companyCode) {
                                params.set(
                                    "company_code",
                                    companyCode
                                );
                            }

                            const response =
                                await fetch(
                                    "/api/vehicles?" +
                                    params.toString()
                                );

                            const data =
                                await response.json();

                            vehicleSearchResults
                                .replaceChildren();

                            vehicleSearchResults
                                .classList.remove(
                                    "is-hidden"
                                );

                            if (
                                !data.results ||
                                data.results
                                    .length === 0
                            ) {
                                const p =
                                    document.createElement(
                                        "p"
                                    );

                                p.className =
                                    "help-text";

                                p.textContent =
                                    "該当する車両がありません。";

                                vehicleSearchResults
                                    .appendChild(p);

                                return;
                            }

                            data.results.forEach(
                                function (
                                    vehicle
                                ) {
                                    const row =
                                        document.createElement(
                                            "div"
                                        );

                                    row.className =
                                        "vehicle-option";

                                    const labelParts =
                                        [
                                            vehicle.vehicle_id,
                                            vehicle.number,
                                            vehicle.manufacturer,
                                            vehicle.model_code
                                        ].filter(
                                            Boolean
                                        );

                                    const label =
                                        document.createElement(
                                            "span"
                                        );

                                    label.className =
                                        "vehicle-option-label";

                                    label.textContent =
                                        labelParts.join(
                                            " / "
                                        );

                                    const button =
                                        document.createElement(
                                            "button"
                                        );

                                    button.type =
                                        "button";

                                    button.className =
                                        "btn-small vehicle-option-select";

                                    button.textContent =
                                        "選択";

                                    button.addEventListener(
                                        "click",
                                        function () {
                                            vehicleId.value =
                                                vehicle.vehicle_id;

                                            if (
                                                selectedVehicleDisplay
                                            ) {
                                                selectedVehicleDisplay
                                                    .textContent =
                                                    labelParts.join(
                                                        " / "
                                                    );
                                            }

                                            vehicleSearch.value =
                                                "";

                                            vehicleSearchResults
                                                .replaceChildren();

                                            vehicleSearchResults
                                                .classList.add(
                                                    "is-hidden"
                                                );

                                            vehicleFilterForm
                                                .requestSubmit();
                                        }
                                    );

                                    row.appendChild(
                                        label
                                    );

                                    row.appendChild(
                                        button
                                    );

                                    vehicleSearchResults
                                        .appendChild(
                                            row
                                        );
                                }
                            );
                        },
                        300
                    );
            }
        );
    }


    /* =========================
       表示位置
    ========================= */

    function moveToActiveDay() {
        const scrollArea =
            document.querySelector(
                ".table-scroll"
            );

        const activeCell =
            document.querySelector(
                "td.active-day-cell"
            );

        const categoryCell =
            document.querySelector(
                "td.fixed-category"
            );

        const itemCell =
            document.querySelector(
                "td.fixed-item"
            );

        if (
            !scrollArea ||
            !activeCell ||
            !categoryCell ||
            !itemCell
        ) {
            return;
        }

        const fixedWidth =
            categoryCell.offsetWidth +
            itemCell.offsetWidth;

        scrollArea.scrollTo({
            left:
                activeCell.offsetLeft -
                fixedWidth,
            behavior: "instant"
        });
    }


    setTimeout(
        moveToActiveDay,
        300
    );

    setTimeout(
        moveToActiveDay,
        700
    );


    /* =========================
       フィルター
    ========================= */

    if (vehicleFilterForm) {
        const yearInput =
            vehicleFilterForm
                .querySelector(
                    'input[name="year"]'
                );

        const monthSelect =
            vehicleFilterForm
                .querySelector(
                    'select[name="month"]'
                );

        const activeDaySelect =
            vehicleFilterForm
                .querySelector(
                    'select[name="active_day"]'
                );

        function submitVehicleFilter() {
            if (
                !vehicleId ||
                !vehicleId.value
            ) {
                return;
            }

            vehicleFilterForm
                .requestSubmit();
        }

        yearInput?.addEventListener(
            "change",
            submitVehicleFilter
        );

        monthSelect?.addEventListener(
            "change",
            submitVehicleFilter
        );

        activeDaySelect?.addEventListener(
            "change",
            submitVehicleFilter
        );
    }
});