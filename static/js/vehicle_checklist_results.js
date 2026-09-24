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

    const activeDay =
        config.dataset.activeDay || "";

    const companyCode =
        config.dataset.companyCode || "";

    const reminderUrl =
        config.dataset.reminderUrl || "";

    function setupMobileChoiceButtons() {
        if (
            !window.matchMedia(
                "(max-width: 768px)"
            ).matches
        ) {
            return;
        }

        document.querySelectorAll(
            ".js-mobile-choice-select"
        ).forEach(function (select) {
            const wrapper =
                document.createElement("div");

            wrapper.className =
                "check-choice-buttons";

            Array.from(
                select.options
            ).forEach(function (option) {
                if (!option.value) {
                    return;
                }

                const button =
                    document.createElement("button");

                button.type = "button";
                button.className =
                    "check-choice-button";

                button.textContent =
                    option.textContent;

                if (
                    option.value ===
                    select.value
                ) {
                    button.classList.add(
                        "is-selected"
                    );
                }

                button.addEventListener(
                    "click",
                    function () {
                        select.value =
                            option.value;

                        wrapper
                            .querySelectorAll(
                                ".check-choice-button"
                            )
                            .forEach(
                                function (
                                    currentButton
                                ) {
                                    currentButton
                                        .classList
                                        .remove(
                                            "is-selected"
                                        );
                                }
                            );

                        button.classList.add(
                            "is-selected"
                        );

                        select.dispatchEvent(
                            new Event(
                                "change",
                                {
                                    bubbles: true
                                }
                            )
                        );
                    }
                );

                wrapper.appendChild(
                    button
                );
            });

            select.insertAdjacentElement(
                "afterend",
                wrapper
            );

            select.classList.add(
                "mobile-choice-source"
            );
        });
    }

    setupMobileChoiceButtons();

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
                "/files/uploads/" +
                encodeURIComponent(filename);

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

        document.querySelectorAll(
            "#detailModal .is-stored-detail-file-input"
        ).forEach(function (input) {
            input.remove();
        });

        document.querySelectorAll(
            "#detailModal .js-detail-file-input"
        ).forEach(function (input) {
            input.value = "";
        });

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

    function prepareNextDetailFileInput(input) {
        if (!input.files || input.files.length === 0) {
            return;
        }

        const label = input.closest(".file-upload-button");

        if (!label) {
            return;
        }

        const nextInput = input.cloneNode(true);
        nextInput.value = "";

        input.classList.add("is-stored-detail-file-input");
        label.parentNode.insertBefore(input, label);
        label.appendChild(nextInput);
    }
    /* =========================
       詳細ファイルプレビュー
    ========================= */

    function previewDetailFiles(
        input,
        showAll = false
    ) {
        const preview =
            document.getElementById(
                "detailPreview"
            );

        const uploadArea = input.closest(
            ".vehicle-detail-file-upload"
        );

        if (!preview || !uploadArea) {
            return;
        }

        const selectedFiles = [];

        uploadArea.querySelectorAll(
            ".js-detail-file-input"
        ).forEach(function (fileInput) {
            Array.from(
                fileInput.files || []
            ).forEach(function (file, fileIndex) {
                selectedFiles.push({
                    file: file,
                    fileInput: fileInput,
                    fileIndex: fileIndex
                });
            });
        });

        preview.replaceChildren();

        preview.classList.toggle(
            "is-expanded",
            showAll
        );

        const visibleFiles = showAll
            ? selectedFiles
            : selectedFiles.slice(0, 2);

        visibleFiles.forEach(function (entry) {
            const file = entry.file;
            const item =
                document.createElement("div");

            item.className =
                "selected-file-preview";

            if (file.type.startsWith("image/")) {
                const image =
                    document.createElement("img");

                image.src =
                    URL.createObjectURL(file);

                image.alt = file.name;
                image.className =
                    "selected-file-preview-image";

                image.addEventListener(
                    "click",
                    function () {
                        window.open(
                            image.src,
                            "_blank"
                        );
                    }
                );

                item.appendChild(image);

            } else if (
                file.type.startsWith("video/")
            ) {
                const video =
                    document.createElement("video");

                video.src =
                    URL.createObjectURL(file);

                video.controls = true;
                video.preload = "metadata";
                video.className =
                    "preview-video";

                item.appendChild(video);

            } else {
                const name =
                    document.createElement("div");

                name.className =
                    "selected-file-preview-name";

                name.textContent = file.name;
                item.appendChild(name);
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
                    const transfer =
                        new DataTransfer();

                    Array.from(
                        entry.fileInput.files || []
                    ).forEach(function (
                        currentFile,
                        currentIndex
                    ) {
                        if (
                            currentIndex !==
                            entry.fileIndex
                        ) {
                            transfer.items.add(
                                currentFile
                            );
                        }
                    });

                    entry.fileInput.files =
                        transfer.files;

                    if (
                        entry.fileInput.files.length === 0
                        && entry.fileInput.classList.contains(
                            "is-stored-detail-file-input"
                        )
                    ) {
                        entry.fileInput.remove();
                    }

                    const remainingInput =
                        uploadArea.querySelector(
                            ".js-detail-file-input"
                        );

                    if (remainingInput) {
                        previewDetailFiles(
                            remainingInput,
                            showAll
                        );
                    } else {
                        preview.replaceChildren();
                    }
                }
            );

            item.appendChild(removeButton);
            preview.appendChild(item);
        });

        if (!showAll && selectedFiles.length > 2) {
            const more =
                document.createElement("button");

            more.type = "button";
            more.className =
                "selected-file-more";

            more.textContent =
                "＋" +
                (selectedFiles.length - 2) +
                "件";

            more.addEventListener(
                "click",
                function () {
                    previewDetailFiles(
                        input,
                        true
                    );
                }
            );

            preview.appendChild(more);
        }

        if (showAll && selectedFiles.length > 2) {
            const collapse =
                document.createElement("button");

            collapse.type = "button";
            collapse.className =
                "selected-file-collapse";

            collapse.textContent = "閉じる";

            collapse.addEventListener(
                "click",
                function () {
                    previewDetailFiles(
                        input,
                        false
                    );
                }
            );

            preview.appendChild(collapse);
        }
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

                prepareNextDetailFileInput(
                    event.target
                );
            }
        }
    );

    const detailFileForm =
        document.querySelector(
            "#detailModal form"
        );

    if (detailFileForm) {
        detailFileForm.addEventListener(
            "submit",
            function (event) {
                const tableScrollPositions =
                    Array.from(
                        document.querySelectorAll(
                            ".vehicle-check-table-scroll"
                        )
                    ).map(function (area) {
                        return area.scrollLeft;
                    });

                sessionStorage.setItem(
                    "vehicleChecklistReturnPosition",
                    JSON.stringify({
                        pageX: window.scrollX,
                        pageY: window.scrollY,
                        tables: tableScrollPositions
                    })
                );

                let totalSize = 0;

                detailFileForm.querySelectorAll(
                    ".js-detail-file-input"
                ).forEach(function (input) {
                    Array.from(
                        input.files || []
                    ).forEach(function (file) {
                        totalSize += file.size;
                    });
                });

                const maxSize =
                    1024 * 1024 * 1024;

                if (totalSize > maxSize) {
                    event.preventDefault();

                    alert(
                        "写真・動画・ファイルの合計を" +
                        "1GB以下にしてください。"
                    );
                }
            }
        );
    }
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

            const response = await fetch(
                form.action,
                {
                    method: "POST",
                    body: formData
                }
            );

            if (!response.ok) {
                throw new Error(
                    "HTTP " + response.status
                );
            }
        } catch (error) {
            console.error(
                "保存エラー:",
                error
            );

            window.alert(
                "点検結果を保存できませんでした。通信状態を確認して、もう一度入力してください。"
            );

            input.focus();
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
                if (event.target.type === "radio") {
                    const choiceButtons =
                        event.target.closest(
                            ".check-choice-buttons"
                        );

                    if (choiceButtons) {
                        choiceButtons
                            .querySelectorAll(
                                ".check-choice-button"
                            )
                            .forEach(function (button) {
                                button.classList.remove(
                                    "is-selected"
                                );
                            });

                        event.target
                            .closest(
                                ".check-choice-button"
                            )
                            ?.classList.add(
                                "is-selected"
                            );
                    }
                }

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


async function loadSavedNotifyUsers() {
    for (
        const savedValue
        of savedNotifyUsers
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
                    "保存済み通知先を復元できません:",
                    value
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
                notifyUsers.set(
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
                notifyUsers.set(
                    nameMatches[0].username,
                    nameMatches[0].name
                );
            } else {
                console.warn(
                    "保存済み通知先を一意に復元できません:",
                    value
                );
            }

        } catch (error) {
            console.error(
                "通知先ユーザーの復元に失敗しました。",
                error
            );
        }
    }

    renderNotifyUsers();
}

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

                hidden.value = username;

                tag.appendChild(text);
                tag.appendChild(remove);
                tag.appendChild(hidden);

                notifySelected.appendChild(
                    tag
                );
            }
        );
    }


    loadSavedNotifyUsers();


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
                            let response;

                            try {
                                response =
                                    await fetch(
                                        "/api/mention-users?q=" +
                                        encodeURIComponent(
                                            keyword
                                        )
                                    );

                                if (!response.ok) {
                                    throw new Error(
                                        "HTTP " +
                                        response.status
                                    );
                                }
                            } catch (error) {
                                console.error(
                                    "通知先の取得に失敗しました。",
                                    error
                                );

                                notifyResults.replaceChildren();

                                const message =
                                    document.createElement("p");

                                message.className = "help-text";
                                message.textContent =
                                    "通知先を取得できませんでした。通信状態を確認してください。";

                                notifyResults.appendChild(
                                    message
                                );

                                notifyResults.classList.remove(
                                    "is-hidden"
                                );

                                return;
                            }

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
                                                    selectedUser.username
                                                )
                                            ) {
                                                return;
                                            }

                                            notifyUsers.set(
                                                selectedUser.username,
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


async function loadSavedReminderNotifyUsers() {
    for (
        const savedValue
        of savedReminderNotifyUsers
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
                    "保存済み点検未実施通知先を復元できません:",
                    value
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
                reminderUsers.set(
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
                reminderUsers.set(
                    nameMatches[0].username,
                    nameMatches[0].name
                );
            } else {
                console.warn(
                    "保存済み点検未実施通知先を一意に復元できません:",
                    value
                );
            }

        } catch (error) {
            console.error(
                "点検未実施通知先の復元に失敗しました。",
                error
            );
        }
    }

    renderReminderUsers();
}


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
            function (name, username) {
                formData.append(
                    "reminder_notify_users",
                    username
                );
            }
        );

        try {
            const response =
                await fetch(
                    reminderUrl,
                    {
                        method: "POST",
                        body: formData
                    }
                );

            if (!response.ok) {
                throw new Error(
                    "HTTP " + response.status
                );
            }
        } catch (error) {
            console.error(
                "点検忘れ通知先の保存に失敗しました。",
                error
            );

            window.alert(
                "点検忘れ通知先を保存できませんでした。通信状態を確認して、もう一度操作してください。"
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


    loadSavedReminderNotifyUsers();


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
                                let response;

                                try {
                                    response =
                                        await fetch(
                                            "/api/mention-users?q=" +
                                            encodeURIComponent(
                                                keyword
                                            )
                                        );

                                    if (!response.ok) {
                                        throw new Error(
                                            "HTTP " +
                                            response.status
                                        );
                                    }
                                } catch (error) {
                                    console.error(
                                        "点検忘れ通知先の取得に失敗しました。",
                                        error
                                    );

                                    reminderResults.replaceChildren();

                                    const message =
                                        document.createElement("p");

                                    message.className = "help-text";
                                    message.textContent =
                                        "通知先を取得できませんでした。通信状態を確認してください。";

                                    reminderResults.appendChild(
                                        message
                                    );

                                    reminderResults.classList.remove(
                                        "is-hidden"
                                    );

                                    return;
                                }

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
                                                        selectedUser.username
                                                    )
                                                ) {
                                                    return;
                                                }

                                                reminderUsers.set(
                                                    selectedUser.username,
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

                button.disabled = true;
                button.textContent =
                    "読み込み中…";

                vehicleId.value =
                    button.dataset.vehicleId;

                const params =
                    new URLSearchParams(
                        new FormData(
                            vehicleFilterForm
                        )
                    );

                const targetUrl =
                    new URL(
                        window.location.pathname,
                        window.location.origin
                    );

                targetUrl.search =
                    params.toString();

                window.location.assign(
                    targetUrl.toString()
                );
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

                            let response;

                            try {
                                response =
                                    await fetch(
                                        "/api/vehicles?" +
                                        params.toString()
                                    );

                                if (!response.ok) {
                                    throw new Error(
                                        "HTTP " +
                                        response.status
                                    );
                                }
                            } catch (error) {
                                console.error(
                                    "車両の取得に失敗しました。",
                                    error
                                );

                                vehicleSearchResults
                                    .replaceChildren();

                                const message =
                                    document.createElement("p");

                                message.className = "help-text";
                                message.textContent =
                                    "車両を取得できませんでした。通信状態を確認してください。";

                                vehicleSearchResults
                                    .appendChild(message);

                                vehicleSearchResults
                                    .classList.remove(
                                        "is-hidden"
                                    );

                                return;
                            }

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

                                    function selectVehicle() {
                                        if (
                                            row.classList.contains(
                                                "is-selecting"
                                            )
                                        ) {
                                            return;
                                        }

                                        row.classList.add(
                                            "is-selecting"
                                        );

                                        button.disabled = true;
                                        button.textContent =
                                            "読み込み中…";

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

                                        vehicleSearch.value = "";

                                        vehicleSearchResults
                                            .replaceChildren();

                                        vehicleSearchResults
                                            .classList.add(
                                                "is-hidden"
                                            );

                                        const params =
                                            new URLSearchParams(
                                                new FormData(
                                                    vehicleFilterForm
                                                )
                                            );

                                        window.location.assign(
                                            window.location.pathname +
                                                "?" +
                                                params.toString()
                                        );
                                    }

                                    button.addEventListener(
                                        "click",
                                        function (event) {
                                            event.stopPropagation();
                                            selectVehicle();
                                        }
                                    );

                                    row.addEventListener(
                                        "click",
                                        selectVehicle
                                    );

                                    row.appendChild(label);
                                    row.appendChild(button);

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
        if (
            window.matchMedia(
                "(max-width: 768px)"
            ).matches
        ) {
            return;
        }

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


    function markMobilePreviousDate() {
        const allDays =
            Array.from(
                document.querySelectorAll(
                    ".vehicle-check-table-scroll tr:first-child th.date-cell[data-day]"
                )
            )
                .map(function (header) {
                    return header.dataset.day;
                })
                .filter(function (
                    day,
                    index,
                    array
                ) {
                    return (
                        day &&
                        array.indexOf(day) === index
                    );
                })
                .sort(function (a, b) {
                    return Number(a) - Number(b);
                });

        const currentIndex =
            allDays.indexOf(activeDay);

        if (currentIndex <= 0) {
            return;
        }

        const previousDay =
            allDays[currentIndex - 1];

        document.querySelectorAll(
            ".vehicle-check-table-scroll th.date-cell[data-day], " +
            ".vehicle-check-table-scroll td.center-cell[data-day]"
        ).forEach(function (cell) {
            if (
                cell.dataset.day ===
                previousDay
            ) {
                cell.classList.add(
                    "mobile-previous-date"
                );
            }
        });
    }

    markMobilePreviousDate();

    document.querySelectorAll(
        ".vehicle-check-table-scroll"
    ).forEach(function (scrollArea) {
        const hasVisiblePeriod =
            scrollArea.querySelector(
                ".mobile-previous-date, .mobile-current-date"
            );

        scrollArea.classList.toggle(
            "mobile-no-visible-period",
            !hasVisiblePeriod
        );

        const periodHeading =
            scrollArea.previousElementSibling;

        if (
            periodHeading &&
            periodHeading.classList.contains(
                "checklist-version-period"
            )
        ) {
            periodHeading.classList.toggle(
                "mobile-no-visible-period",
                !hasVisiblePeriod
            );
        }
    });


    function restoreDetailReturnPosition() {
        const saved =
            sessionStorage.getItem(
                "vehicleChecklistReturnPosition"
            );

        if (!saved) {
            return false;
        }

        try {
            const position =
                JSON.parse(saved);

            sessionStorage.removeItem(
                "vehicleChecklistReturnPosition"
            );

            window.scrollTo(
                position.pageX || 0,
                position.pageY || 0
            );

            document.querySelectorAll(
                ".vehicle-check-table-scroll"
            ).forEach(function (area, index) {
                if (
                    position.tables &&
                    position.tables[index] !== undefined
                ) {
                    area.scrollLeft =
                        position.tables[index];
                }
            });

            requestAnimationFrame(function () {
                window.scrollTo(
                    position.pageX || 0,
                    position.pageY || 0
                );
            });

            return true;

        } catch (error) {
            console.error(
                "詳細保存後の位置復元に失敗しました。",
                error
            );

            sessionStorage.removeItem(
                "vehicleChecklistReturnPosition"
            );

            return false;
        }
    }

    const restoredDetailPosition =
        restoreDetailReturnPosition();

    if (!restoredDetailPosition) {
        setTimeout(
            moveToActiveDay,
            300
        );

        setTimeout(
            moveToActiveDay,
            700
        );
    }


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
                alert(
                    "先に対象車両を選択してください。"
                );

                vehicleSearch?.focus();
                return;
            }

            const params =
                new URLSearchParams(
                    new FormData(
                        vehicleFilterForm
                    )
                );

            window.location.assign(
                window.location.pathname +
                    "?" +
                    params.toString()
            );
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