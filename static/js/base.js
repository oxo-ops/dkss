function toggleSidebar() {
    if (window.innerWidth <= 900) {
        document.body.classList.toggle("sidebar-open");
        return;
    }

    document.body.classList.toggle("sidebar-collapsed");

    if (document.body.classList.contains("sidebar-collapsed")) {
        localStorage.setItem("sidebarCollapsed", "1");
    } else {
        localStorage.setItem("sidebarCollapsed", "0");
    }
}

function toggleMenu(button) {
    const group = button.closest(".sidebar-group");
    const key = group.dataset.menuKey;

    if (document.body.classList.contains("sidebar-collapsed")) {
        document.body.classList.remove("sidebar-collapsed");
        localStorage.setItem("sidebarCollapsed", "0");
    }

    group.classList.toggle("open");

    if (key) {
        localStorage.setItem(
            "menuOpen_" + key,
            group.classList.contains("open") ? "1" : "0"
        );
    }
}

window.addEventListener("DOMContentLoaded", function () {
    const currentPath = window.location.pathname;

    if (window.innerWidth <= 900) {
        document.body.classList.remove("sidebar-collapsed");
    }

    const isSafetyInputPage =
        /^\/safety\/checklists\/\d+\/new\/?$/.test(currentPath);

    const isSafetyResultListPage =
        /^\/safety\/checklists\/\d+\/?$/.test(currentPath);

    const isVehicleInputPage =
        /^\/vehicle\/checklists\/\d+\/?$/.test(currentPath);

    const isDocumentImportPreviewPage =
        /^\/vehicle\/data-import\/[^/]+\/preview\/?$/.test(currentPath);

    if (
        (isSafetyInputPage || isVehicleInputPage || isDocumentImportPreviewPage) &&
        window.innerWidth > 900
    ) {
        document.body.classList.add("sidebar-collapsed");

    } else if (
        isSafetyResultListPage &&
        window.innerWidth > 900
    ) {
        document.body.classList.remove("sidebar-collapsed");

    } else if (
        localStorage.getItem("sidebarCollapsed") === "1" && window.innerWidth > 900
    ) {
        document.body.classList.add("sidebar-collapsed");
    }

    document.querySelectorAll(".sidebar-group").forEach(function(group) {
        const key = group.dataset.menuKey;

        if (!key) {
            return;
        }

        const saved = localStorage.getItem("menuOpen_" + key);

        if (saved === "1") {
            group.classList.add("open");
        }

        if (saved === "0") {
            group.classList.remove("open");
        }
    });
});

const checklistChoiceState = new WeakMap();

document.addEventListener(
    "pointerdown",
    function (event) {
        const choice =
            event.target.closest(
                ".checklist-result-choice"
            );

        if (!choice) {
            return;
        }

        const radio =
            choice.querySelector(
                ".checklist-result-choice-radio"
            );

        if (!radio) {
            return;
        }

        checklistChoiceState.set(
            choice,
            radio.checked
        );
    },
    true
);

document.addEventListener(
    "click",
    function (event) {
        const choice =
            event.target.closest(
                ".checklist-result-choice"
            );

        if (!choice) {
            return;
        }

        const radio =
            choice.querySelector(
                ".checklist-result-choice-radio"
            );

        if (!radio) {
            return;
        }

        const wasChecked =
            checklistChoiceState.get(choice);

        checklistChoiceState.delete(choice);

        if (!wasChecked) {
            return;
        }

        event.preventDefault();
        radio.checked = false;

        radio.dispatchEvent(
            new Event(
                "change",
                {
                    bubbles: true
                }
            )
        );
    },
    true
);

document.addEventListener("input", function(e) {
    const target = e.target;

    if (
        !target.classList.contains("mention-input") &&
        !target.classList.contains("mention-rich-editor")
    ) {
        return;
    }

    if (target.classList.contains("mention-rich-editor")) {
        handleRichMentionInput(target);
        return;
    }

    const input = target;
    const text = input.value;
    const caret = input.selectionStart;
    const beforeCaret = text.slice(0, caret);

    const match = beforeCaret.match(/@([^@\s]*)$/);

    if (!match) {
        closeMentionBox();
        return;
    }

    const keyword = match[1];

    if (!keyword) {
        closeMentionBox();
        return;
    }

    fetch("/api/mention-users?q=" + encodeURIComponent(keyword))
        .then(function (response) {
            if (!response.ok) {
                throw new Error(
                    "HTTP " + response.status
                );
            }

            return response.json();
        })
        .then(function (data) {
            showMentionBox(
                input,
                data.users,
                match[0]
            );
        })
        .catch(function (error) {
            console.error(
                "メンション候補の取得に失敗しました。",
                error
            );

            showCommonError(
                "メンション候補の取得に失敗しました。"
            );

            closeMentionBox();
        });
});

let activeRichMentionRange = null;

function handleRichMentionInput(editor) {
    const selection = window.getSelection();

    if (!selection || selection.rangeCount === 0) {
        closeMentionBox();
        return;
    }

    const range = selection.getRangeAt(0);

    if (!editor.contains(range.startContainer)) {
        closeMentionBox();
        return;
    }

    const node = range.startContainer;

    if (node.nodeType !== Node.TEXT_NODE) {
        closeMentionBox();
        return;
    }

    const textBeforeCaret = node.textContent.slice(
        0,
        range.startOffset
    );

    const match = textBeforeCaret.match(/@([^@\s]*)$/);

    if (!match) {
        closeMentionBox();
        return;
    }

    const keyword = match[1];

    if (!keyword) {
        activeRichMentionRange = null;
        closeMentionBox();
        return;
    }

    activeRichMentionRange = {
        editor: editor,
        node: node,
        startOffset: range.startOffset - match[0].length,
        endOffset: range.startOffset
    };

    fetch("/api/mention-users?q=" + encodeURIComponent(keyword))
        .then(function (response) {
            if (!response.ok) {
                throw new Error(
                    "HTTP " + response.status
                );
            }

            return response.json();
        })
        .then(function (data) {
            showRichMentionBox(
                editor,
                data.users
            );
        })
        .catch(function (error) {
            console.error(
                "メンション候補の取得に失敗しました。",
                error
            );

            showCommonError(
                "メンション候補の取得に失敗しました。"
            );

            closeMentionBox();
        });
}

function positionMentionBox(target, box) {
    const rect = target.getBoundingClientRect();

    box.style.position = "fixed";
    box.style.left = rect.left + "px";
    box.style.top = (rect.bottom + 6) + "px";
    box.style.width = rect.width + "px";
}

function showRichMentionBox(editor, users) {
    const box = document.getElementById("mentionBox");

    if (!users || users.length === 0) {
        closeMentionBox();
        return;
    }

    box.innerHTML = "";

    users.forEach(function(user) {
        const item = document.createElement("button");

        item.type = "button";
        item.className = "mention-item";

        const name = document.createElement("strong");
        const office = document.createElement("span");

        name.textContent = user.name || "";
        office.textContent = [
            user.office || "",
            user.username
                ? "ID: " + user.username
                : ""
        ]
            .filter(Boolean)
            .join(" / ");

        item.appendChild(name);
        item.appendChild(office);

        item.addEventListener("mousedown", function (event) {
            event.preventDefault();
        });

        item.addEventListener("click", function () {
            insertRichMention(user);
        });

        box.appendChild(item);
    });

    positionMentionBox(editor, box);
    box.classList.add("is-visible");
}

function insertRichMention(user) {
    if (!activeRichMentionRange) {
        return;
    }

    const editor = activeRichMentionRange.editor;
    const node = activeRichMentionRange.node;

    const before = node.textContent.slice(
        0,
        activeRichMentionRange.startOffset
    );

    const after = node.textContent.slice(
        activeRichMentionRange.endOffset
    );

    const parent = node.parentNode;

    const beforeNode = document.createTextNode(before);
    const chip = createMentionChip(
        user.name,
        user.username + "|" + user.name
    );
    const spaceNode = document.createTextNode(" ");
    const afterNode = document.createTextNode(after);

    parent.insertBefore(beforeNode, node);
    parent.insertBefore(chip, node);
    parent.insertBefore(spaceNode, node);
    parent.insertBefore(afterNode, node);

    parent.removeChild(node);

    const range = document.createRange();
    const selection = window.getSelection();

    range.setStartAfter(spaceNode);
    range.collapse(true);

    selection.removeAllRanges();
    selection.addRange(range);

    const hiddenInput =
        getMentionHiddenInput(editor);

    if (hiddenInput) {
        hiddenInput.value =
            getMentionEditorValue(editor);
    }

    editor.focus();

    activeRichMentionRange = null;
    closeMentionBox();
}

function showMentionBox(input, users, mentionText) {
    const box = document.getElementById("mentionBox");

    if (!users || users.length === 0) {
        closeMentionBox();
        return;
    }

    box.innerHTML = "";

    users.forEach(function(user) {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "mention-item";

        const name = document.createElement("strong");
        const office = document.createElement("span");

        name.textContent = user.name || "";
        office.textContent = [
            user.office || "",
            user.username
                ? "ID: " + user.username
                : ""
        ]
            .filter(Boolean)
            .join(" / ");

        item.appendChild(name);
        item.appendChild(office);

        item.addEventListener("mousedown", function (event) {
            event.preventDefault();
        });

        item.addEventListener("click", function () {
            insertMention(
                input,
                mentionText,
                user.name,
                user.username
            );
        });
        box.appendChild(item);
    });

    positionMentionBox(input, box);
    box.classList.add("is-visible");
}

function insertMention(
    input,
    mentionText,
    name,
    username
) {
    const caret = input.selectionStart;
    const text = input.value;

    const before = text.slice(0, caret);
    const after = text.slice(caret);

    const newBefore = before.replace(
        /@([^@\s]*)$/,
        "[[" + username + "|" + name + "]] "
    );

    input.value = newBefore + after;
    input.focus();
    input.selectionStart =
        input.selectionEnd =
        newBefore.length;

    closeMentionBox();
}

function createMentionChip(name, mentionValue) {
    const chip = document.createElement("span");

    const currentUserName =
        document.body.dataset.currentUser || "";

    chip.className = "mention-chip";

    if (name === currentUserName) {
        chip.classList.add("mention-chip-self");
    } else {
        chip.classList.add("mention-chip-other");
    }

    chip.dataset.mention =
        mentionValue || name;

    chip.contentEditable = "false";
    chip.textContent = name;

    return chip;
}

function renderMentionValue(editor, value) {
    editor.innerHTML = "";

    const regex = /\[\[([^\]]+)\]\]/g;

    let lastIndex = 0;
    let match;

    while ((match = regex.exec(value)) !== null) {
        const beforeText =
            value.slice(lastIndex, match.index);

        if (beforeText) {
            editor.appendChild(
                document.createTextNode(beforeText)
            );
        }

        const mentionValue = match[1];
        const separatorIndex =
            mentionValue.indexOf("|");

        const displayName =
            separatorIndex >= 0
                ? mentionValue.slice(
                    separatorIndex + 1
                )
                : mentionValue;

        editor.appendChild(
            createMentionChip(
                displayName,
                mentionValue
            )
        );

        lastIndex = regex.lastIndex;
    }

    const afterText = value.slice(lastIndex);

    if (afterText) {
        editor.appendChild(
            document.createTextNode(afterText)
        );
    }
}

function getMentionHiddenInput(editor) {
    const tableCell = editor.closest("td");

    if (tableCell) {
        const commentInput =
            tableCell.querySelector(
                'input[type="hidden"][name^="comment_"]'
            );

        if (commentInput) {
            return commentInput;
        }
    }

    const parent = editor.parentElement;

    if (!parent) {
        return null;
    }

    return parent.querySelector(
        'input[type="hidden"][name]:not([name="csrf_token"])'
    );
}

function getMentionEditorValue(editor) {
    let value = "";

    editor.childNodes.forEach(function(node) {
        if (
            node.nodeType === Node.ELEMENT_NODE &&
            node.classList.contains("mention-chip")
        ) {
            value += "[[" + node.dataset.mention + "]]";
        } else {
            value += node.textContent;
        }
    });

    return value;
}

function closeMentionBox() {
    const box = document.getElementById("mentionBox");
    if (box) {
        box.classList.remove("is-visible");
    }
}

document.addEventListener("click", function(e) {
    if (
        !e.target.closest(".mention-box") &&
        !e.target.closest(".mention-input") &&
        !e.target.closest(".mention-rich-editor")
    ) {
        closeMentionBox();
    }
});

document.addEventListener("click", function(e) {
    const link = e.target.closest(".sidebar a");

    if (link && window.innerWidth <= 900) {
        document.body.classList.remove("sidebar-open");
    }
});

document.addEventListener("DOMContentLoaded", function () {
    const sidebarOverlay =
        document.getElementById("sidebarOverlay");

    sidebarOverlay?.addEventListener(
        "click",
        function () {
            if (window.innerWidth <= 768) {
                document.body.classList.remove(
                    "sidebar-open"
                );
            }
        }
    );
});

window.addEventListener("DOMContentLoaded", function() {

    document.querySelectorAll(".mention-rich-editor")
        .forEach(function(editor) {

    const hiddenInput =
        getMentionHiddenInput(editor);

            const initialValue =
                editor.dataset.value
                || (hiddenInput ? hiddenInput.value : "");

            renderMentionValue(
                editor,
                initialValue
            );

            editor.addEventListener("input", function() {
                if (hiddenInput) {
                    hiddenInput.value =
                        getMentionEditorValue(editor);
                }
            });

            const form = editor.closest("form");

            if (
                form &&
                form.dataset.mentionValidationReady !== "true"
            ) {
                form.dataset.mentionValidationReady = "true";

                form.addEventListener("submit", function (event) {
                    const editors = form.querySelectorAll(
                        ".mention-rich-editor"
                    );

                    let firstInvalidEditor = null;

                    editors.forEach(function (formEditor) {
                        const formHiddenInput =
                            getMentionHiddenInput(formEditor);

                        const value =
                            getMentionEditorValue(
                                formEditor
                            ).trim();

                        if (formHiddenInput) {
                            formHiddenInput.value = value;
                        }

                        formEditor.classList.remove(
                            "checklist-validation-invalid"
                        );

                        if (
                            !firstInvalidEditor &&
                            formEditor.dataset.required === "true" &&
                            !value
                        ) {
                            firstInvalidEditor = formEditor;
                        }
                    });

                    if (!firstInvalidEditor) {
                        return;
                    }

                    event.preventDefault();

                    firstInvalidEditor.classList.add(
                        "checklist-validation-invalid"
                    );

                    showCommonError(
                        "必須項目を入力してください。"
                    );

                    firstInvalidEditor.scrollIntoView({
                        behavior: "smooth",
                        block: "center"
                    });

                    window.setTimeout(function () {
                        firstInvalidEditor.focus();
                    }, 300);
                });
            }
        });

    document.querySelectorAll(".mention-display")
        .forEach(function(display) {

            const value =
                display.dataset.value
                || display.textContent
                || "";

            renderMentionValue(
                display,
                value
            );
        });
});

document.addEventListener("DOMContentLoaded", function () {
    const savedScrollPosition =
        sessionStorage.getItem(
            "formSubmitScrollPosition"
        );

    if (savedScrollPosition) {
        try {
            const position =
                JSON.parse(
                    savedScrollPosition
                );

            const currentPath =
                window.location.pathname
                + window.location.search;

            if (
                position.path === currentPath
            ) {
                window.scrollTo(
                    position.x || 0,
                    position.y || 0
                );
            }
        } catch (error) {
            console.error(
                "スクロール位置の復元に失敗しました。",
                error
            );
        }

        sessionStorage.removeItem(
            "formSubmitScrollPosition"
        );
    }

    const sidebarToggle =
        document.getElementById("sidebarToggle");

    if (sidebarToggle) {
        sidebarToggle.addEventListener(
            "click",
            toggleSidebar
        );
    }

    const settingsBack =
        document.getElementById(
            "topBarSettingsBack"
        );

    if (
        window.location.pathname === "/settings"
        && document.referrer
    ) {
        const referrerUrl =
            new URL(document.referrer);

        if (
            referrerUrl.origin === window.location.origin
            && referrerUrl.pathname !== "/settings"
        ) {
            sessionStorage.setItem(
                "settingsReturnUrl",
                referrerUrl.pathname
                + referrerUrl.search
                + referrerUrl.hash
            );
        }
    }

    settingsBack?.addEventListener(
        "click",
        function () {
            const returnUrl =
                sessionStorage.getItem(
                    "settingsReturnUrl"
                );

            sessionStorage.removeItem(
                "settingsReturnUrl"
            );

            window.location.href =
                returnUrl || "/";
        }
    );
});

document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".sidebar-parent").forEach(function (button) {
        button.addEventListener("click", function () {
            toggleMenu(button);
        });
    });
});

document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".confirm-delete-news").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            if (!window.confirm("このニュースを削除しますか？")) {
                event.preventDefault();
            }
        });
    });
});

document.addEventListener("submit", function (event) {
    const form = event.target;

    if (!(form instanceof HTMLFormElement)) {
        return;
    }

    if (!event.defaultPrevented) {
        sessionStorage.setItem(
            "formSubmitScrollPosition",
            JSON.stringify({
                path:
                    window.location.pathname
                    + window.location.search,
                x: window.scrollX,
                y: window.scrollY
            })
        );
    }

    window.setTimeout(function () {
        if (event.defaultPrevented) {
            return;
        }

        const submitButton =
            event.submitter ||
            form.querySelector(
                'button[type="submit"], input[type="submit"]'
            );

        if (!submitButton || submitButton.disabled) {
            return;
        }

        submitButton.disabled = true;
        submitButton.setAttribute(
            "aria-busy",
            "true"
        );

        if (submitButton.tagName === "BUTTON") {
            submitButton.dataset.originalText =
                submitButton.textContent;

            submitButton.textContent =
                form.enctype === "multipart/form-data"
                    ? "送信中..."
                    : "処理中...";
        }
    }, 0);
});

document.addEventListener("change", function (event) {
    const input = event.target;

    if (
        !(input instanceof HTMLInputElement) ||
        input.type !== "file"
    ) {
        return;
    }

    const form = input.closest("form");

    if (!form) {
        return;
    }

    const maxTotalSize =
        1024 * 1024 * 1024;

    let totalSize = 0;

    form.querySelectorAll(
        'input[type="file"]'
    ).forEach(function (fileInput) {
        Array.from(
            fileInput.files || []
        ).forEach(function (file) {
            totalSize += file.size;
        });
    });

    if (totalSize <= maxTotalSize) {
        return;
    }

    input.value = "";

    showCommonError(
        "1回に送信できるファイルの合計は1GB以下です。動画を短くするか、ファイルを分けて登録してください。"
    );
});

async function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat(
        (4 - base64String.length % 4) % 4
    );

    const base64 = (
        base64String
            .replace(/-/g, "+")
            .replace(/_/g, "/")
        + padding
    );

    const rawData = atob(base64);

    return Uint8Array.from(
        [...rawData].map(
            char => char.charCodeAt(0)
        )
    );
}

async function registerPushNotifications() {
    if (document.body.dataset.authenticated !== "true") {
        return;
    }

    if (
        !("serviceWorker" in navigator)
        || !("PushManager" in window)
    ) {
        return;
    }

    const registration =
        await navigator.serviceWorker.register(
            "/service-worker.js"
        );

    let subscription =
        await registration.pushManager.getSubscription();

    if (!subscription) {
        const permission =
            await Notification.requestPermission();

        if (permission !== "granted") {
            return;
        }

        const response = await fetch(
            "/api/push/vapid-public-key"
        );

        if (response.status === 503) {
            const configuration = await response.clone().json().catch(() => null);
            if (configuration?.error === "VAPID public key is not configured.") {
                return;
            }
        }

        if (!response.ok) {
            showCommonError(
                "端末通知の設定情報を取得できませんでした。",
                "",
                false
            );
            return;
        }

        const data = await response.json();

        if (!data.publicKey) {
            showCommonError(
                "端末通知の設定情報を取得できませんでした。",
                "",
                false
            );
            return;
        }

        subscription =
            await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey:
                    await urlBase64ToUint8Array(
                        data.publicKey
                    )
            });
    }

    const csrfToken = document
        .querySelector('meta[name="csrf-token"]')
        ?.getAttribute("content");

    const subscribeResponse = await fetch(
        "/api/push/subscribe",
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken || ""
            },
            body: JSON.stringify(
                subscription.toJSON()
            )
        }
    );

    if (!subscribeResponse.ok) {
        throw new Error(
            "Push subscription save failed: HTTP "
            + subscribeResponse.status
        );
    }
}

window.addEventListener(
    "load",
    () => {
        if (
            "Notification" in window
            && Notification.permission === "granted"
        ) {
            registerPushNotifications().catch(
                (error) => {
                    console.error(
                        "Push通知登録エラー:",
                        error
                    );

                    showCommonError(
                        "端末通知の登録に失敗しました。通信状態を確認してください。",
                        "",
                        false
                    );
                }
            );
        }
    }
);

document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".vehicle-data-import .import-form").forEach(function (form) {
        // Vehicle Excel import has its own controller and preview route.
        if (form.id === "registration-excel-form") return;
        const input = form.querySelector('input[type="file"]');
        const zone = form.querySelector(".import-dropzone");
        const status = form.querySelector(".import-file-status");
        const list = form.querySelector(".import-file-list");
        const error = form.querySelector(".import-error");
        const clear = form.querySelector(".import-clear");
        const extensions = input.accept.split(",");

        function showError(message) {
            error.textContent = message;
            error.hidden = !message;
            input.setAttribute("aria-invalid", message ? "true" : "false");
        }

        function validate(files) {
            if (!files.length) return "ファイルを選択してください。";
            if (files.length > (input.multiple ? 50 : 1)) {
                return input.multiple
                    ? "1回に取り込めるファイルは50件までです。"
                    : "CSVは1ファイルずつ選択してください。";
            }
            if (files.some(file =>
                !extensions.some(ext => file.name.toLowerCase().endsWith(ext))
            )) {
                return "対応形式のファイルを選択してください（" + input.accept + "）。";
            }
            if (
                ["maintenance", "inspection", "driving_report"].includes(form.querySelector('input[name="document_type"]')?.value)
            ) {
                const oversized = files.find(
                    file => file.size > 20 * 1024 * 1024
                );
                if (oversized) {
                    return oversized.name + "：資料は1ファイル20MB以下にしてください。";
                }
            }

            if (files.reduce((total, file) => total + file.size, 0) > 1024 * 1024 * 1024) {
                return "ファイルの合計は1GB以下にしてください。";
            }
            return "";
        }

        function refresh() {
            if (form.dataset.loading === "1") return;

            const files = Array.from(input.files || []);
            const ready = files.length > 0 && !validate(files);
            const title = zone.querySelector(".import-drop-copy strong");
            const detail = zone.querySelector(".import-drop-copy small");
            const pick = zone.querySelector(".import-pick-button");
            const submit = form.querySelector('button[type="submit"]');

            const size = value => value < 1024 * 1024
                ? Math.max(1, Math.ceil(value / 1024)) + " KB"
                : (value / 1024 / 1024).toFixed(1) + " MB";

            if (!zone.dataset.originalTitle) {
                zone.dataset.originalTitle = title.textContent;
                zone.dataset.originalDetail = detail.textContent;
            }

            zone.classList.toggle("has-files", ready);

            title.textContent = files.length === 1
                ? files[0].name
                : files.length > 1
                    ? files.length + "ファイルを選択しました"
                    : zone.dataset.originalTitle;

            title.title = files.map(file => file.name).join("\n");

            detail.textContent = files.length
                ? size(files.reduce((total, file) => total + file.size, 0))
                    + (ready
                        ? " ・ 読み取りの準備ができました"
                        : " ・ 選択内容を確認してください")
                : zone.dataset.originalDetail;

            pick.textContent = files.length ? "選び直す" : "ファイルを選ぶ";

            list.replaceChildren();
            files.forEach(function (file) {
                const item = document.createElement("li");
                item.textContent = file.name + "（" + size(file.size) + "）";
                list.appendChild(item);
            });

            status.textContent = ready
                ? "✓ " + files.length + "ファイルを選択済み"
                : files.length
                    ? "ファイルの確認が必要です"
                    : "ファイル未選択";

            list.hidden = files.length <= 1;
            clear.hidden = !files.length;
            submit.disabled = !ready;
        }

        input.addEventListener("change", function () {
            showError(input.files.length ? validate(Array.from(input.files)) : "");
            setTimeout(refresh, 0);
        });

        clear.addEventListener("click", function () {
            input.value = "";
            showError("");
            refresh();
            input.focus();
        });

        ["dragenter", "dragover"].forEach(function (name) {
            zone.addEventListener(name, function (event) {
                event.preventDefault();
                zone.classList.add("is-dragging");
            });
        });

        zone.addEventListener("dragleave", function (event) {
            if (!zone.contains(event.relatedTarget)) {
                zone.classList.remove("is-dragging");
            }
        });

        zone.addEventListener("drop", function (event) {
            event.preventDefault();
            zone.classList.remove("is-dragging");
            if (form.dataset.loading === "1") return;
            const files = Array.from(event.dataTransfer.files);
            const message = validate(files);
            showError(message);
            if (message) return;
            input.files = event.dataTransfer.files;
            input.dispatchEvent(new Event("change", { bubbles: true }));
        });

        form.addEventListener("submit", function (event) {
            event.preventDefault();
            if (form.dataset.loading === "1") return;

            const message = validate(Array.from(input.files || []));
            showError(message);

            if (message) {
                input.focus();
                return;
            }

            if (form.dataset.importQueue === "1") {
                if (!window.DKSSDocumentImportQueue) {
                    showError("送信画面を読み込めませんでした。再読み込みしてください。");
                    return;
                }
                window.DKSSDocumentImportQueue.submit(form, showError);
                return;
            }

            if (document.querySelector(
                '.vehicle-data-import .import-form[data-loading="1"]'
            )) {
                showError("別の資料を読み取り中です。完了後に実行してください。");
                return;
            }

            const payload = new FormData(form);
            const streaming = ["maintenance", "inspection", "driving_report"].includes(payload.get("document_type"));
            let lastServerUpdate = 0;
            const button = form.querySelector('button[type="submit"]');
            const title = zone.querySelector(".import-drop-copy strong");
            const detail = zone.querySelector(".import-drop-copy small");
            const pick = zone.querySelector(".import-pick-button");

            let progress = form.querySelector(".import-progress");
            if (!progress) {
                progress = document.createElement("progress");
                progress.className = "import-progress";
                progress.max = 100;
                progress.setAttribute(
                    "aria-label",
                    "ファイルの送信・読み取り状況"
                );
                zone.after(progress);
            }

            form.dataset.loading = "1";
            form.setAttribute("aria-busy", "true");
            zone.classList.add("is-loading");

            input.disabled = true;
            clear.disabled = true;
            button.disabled = true;
            button.textContent = "読み取り中…";
            pick.textContent = "処理中";

            progress.hidden = false;
            progress.value = 0;
            progress.setAttribute("aria-label", "ファイルの送信率");

            title.textContent = "ファイルを送信しています";
            detail.textContent = "この画面を開いたままお待ちください";

            const phase = document.createElement("span");
            phase.setAttribute("role", "status");
            phase.textContent = "送信中";

            const elapsed = document.createElement("span");
            elapsed.className = "import-elapsed";
            elapsed.setAttribute("aria-hidden", "true");
            elapsed.textContent = (streaming ? "数分かかる場合があります ｜ " : "")
                + "経過 0:00";

            status.setAttribute("aria-live", "off");
            status.replaceChildren(phase, elapsed);

            const started = Date.now();
            let waiting = false;

            const timer = window.setInterval(function () {
                const seconds = Math.floor((Date.now() - started) / 1000);
                elapsed.textContent = (streaming ? "数分かかる場合があります ｜ " : "")
                    + "経過 " + Math.floor(seconds / 60)
                    + ":" + String(seconds % 60).padStart(2, "0");

                if (waiting && seconds >= 60 && !streaming) {
                    title.textContent = "読み取りに時間がかかっています";
                }
            }, 1000);

            function restore(errorMessage) {
                window.clearInterval(timer);
                delete form.dataset.loading;
                form.setAttribute("aria-busy", "false");
                zone.classList.remove("is-loading");

                input.disabled = false;
                clear.disabled = false;
                button.textContent = "読み込んで確認";
                progress.hidden = true;

                status.setAttribute("aria-live", "polite");
                refresh();
                showError(errorMessage);
            }

            let received = 0;
            let pending = "";
            let streamError = "";
            let streamDestination = "";
            const xhr = new XMLHttpRequest();
            const endpoint = new URL(form.action, location.href);

            if (streaming) {
                endpoint.pathname = endpoint.pathname.replace(/\/$/, "") + "/progress";
            }

            xhr.open("POST", endpoint.href);

            function readProgress() {
                pending += xhr.responseText.slice(received);
                received = xhr.responseText.length;
                let newline;

                while ((newline = pending.indexOf("\n")) >= 0) {
                    const line = pending.slice(0, newline);
                    pending = pending.slice(newline + 1);
                    if (!line.trim()) continue;

                    let update;
                    try {
                        update = JSON.parse(line);
                    } catch (_) {
                        streamError = "進捗データを読み取れませんでした。";
                        continue;
                    }

                    lastServerUpdate = Date.now();
                    if (update.heartbeat === true) continue;

                    if (update.phase === "error") {
                        streamError = update.message || "読み取りに失敗しました。";
                        continue;
                    }

                    if (update.phase === "complete") {
                        streamDestination = update.redirect_url || "";
                        continue;
                    }

                    const total = Number(update.total);
                    const done = Number(update.completed);

                    if (
                        !(total > 0)
                        || !Number.isInteger(done)
                        || done < 0
                        || done > total
                    ) {
                        streamError = "進捗データが不正です。";
                        continue;
                    }

                    if (["ai_accepted", "ai_output"].includes(update.phase)) {
                        const count = Number(update.received_lines || 0);

                        if (!Number.isInteger(count) || count < 0) {
                            streamError = "AIの受信件数が不正です。";
                            continue;
                        }

                        progress.hidden = total === 1;

                        phase.textContent = "② AIからの読取結果"
                            + (update.phase === "ai_output"
                                ? "を受信中"
                                : "を待っています");

                        title.textContent = update.phase === "ai_accepted"
                            ? "AIの受付を確認しました"
                            : count > 0
                                ? "明細 " + count + "件を受信しました"
                                : "読取結果を受信し始めました";

                        detail.textContent = (done + 1)
                            + "件目：" + update.filename
                            + (update.phase === "ai_output"
                                ? " ／ 内容は確認前です"
                                : "");

                        continue;
                    }

                    progress.value = Math.round(done / total * 100);
                    progress.setAttribute("aria-label", "ファイルの処理完了率");
                    progress.hidden = total === 1;

                    phase.textContent = total > 1
                        ? done + " / " + total
                            + "ファイル処理済み（" + progress.value + "％）"
                        : {
                            accepted: "① 送信完了",
                            reading: "② AI読取中（送信完了）",
                            checking: "③ 車両照合中（読取完了）",
                            processed: "③ 車両照合完了",
                            saving: "④ 確認画面を準備中"
                        }[update.phase] || "処理中";

                    title.textContent = {
                        accepted: "送信完了・読み取りを開始します",
                        reading: "AIが資料を読み取っています",
                        checking: "読取結果と車両台帳を照合しています",
                        processed: "ファイルの処理結果を確認しました",
                        saving: "確認画面のデータを保存しています"
                    }[update.phase] || "処理中";

                    detail.textContent = update.filename
                        ? (done + (update.phase === "processed" ? 0 : 1))
                            + "件目：" + update.filename
                        : "成功 " + (update.succeeded || 0)
                            + "件・失敗 " + (update.failed || 0) + "件";

                    if (update.phase === "accepted") {
                        detail.textContent = total + "ファイルを受信しました";
                    }
                }
            }

            xhr.addEventListener("progress", function () {
                if (streaming && xhr.status === 200) readProgress();
            });
            xhr.setRequestHeader("X-DKSS-Final-Submit", "1");
            xhr.setRequestHeader("Accept", "application/json");

            xhr.upload.addEventListener("progress", function (upload) {
                if (upload.lengthComputable) {
                    progress.value = Math.round(
                        upload.loaded / upload.total * 100
                    );
                    phase.textContent = "ファイル送信 " + progress.value + "％";
                }
            });

            xhr.upload.addEventListener("load", function () {
                waiting = true;
                if (streaming) {
                    progress.value = 0;
                    phase.textContent = "送信完了・サーバーの受信確認待ち";
                    title.textContent = "送信が完了しました";
                    detail.textContent = "サーバーから進捗を受け取っています";
                    return;
                }
                progress.removeAttribute("value");
                phase.textContent = "送信完了 ・ 結果待ち";
                title.textContent = "資料の読み取り結果を待っています";
                detail.textContent =
                    "複数ページ・複数ファイルは時間がかかる場合があります";
            });

            xhr.addEventListener("load", function () {
                if (xhr.status < 200 || xhr.status >= 300) {
                    let message =
                        "読み取りに失敗しました（HTTP " + xhr.status + "）。";

                    try {
                        const result = JSON.parse(xhr.responseText);
                        if (
                            Array.isArray(result.errors)
                            && result.errors.length
                        ) {
                            message = result.errors
                                .map(item => item.message)
                                .join("\n");
                        }
                    } catch (_) {}

                    restore(message);
                    return;
                }

                if (streaming) {
                    readProgress();
                    if (streamError || !streamDestination) {
                        restore(
                            streamError
                            || "完了結果を受信できませんでした。サーバーログを確認してください。"
                        );
                        return;
                    }
                }

                const destination = new URL(
                    streamDestination || xhr.responseURL,
                    location.href
                );

                if (
                    destination.origin !== location.origin
                    || !/^\/vehicle\/(?:data-import|operation-import)\/[^/]+\/preview\/?$/.test(
                        destination.pathname
                    )
                ) {
                    restore(
                        "確認画面を開けませんでした。ログイン状態を確認してください。"
                    );
                    return;
                }

                window.clearInterval(timer);
                progress.value = 100;
                phase.textContent = "読み取り完了";
                title.textContent = "確認画面を開いています";
                button.textContent = "確認画面へ…";
                window.location.assign(destination.href);
            });

            xhr.addEventListener("error", function () {
                restore(
                    "通信が切れました。通信状態と読み取り結果を確認してください。"
                );
            });

            xhr.addEventListener("abort", function () {
                restore(
                    "通信が中断されました。読み取り結果を確認してください。"
                );
            });

            try {
                xhr.send(payload);
            } catch (_) {
                restore(
                    "ファイルを送信できませんでした。もう一度お試しください。"
                );
            }
        });

        refresh();
    });
});

function getFormErrorTarget(targetId) {
    if (!targetId) return null;

    const vehicleAnswerMatch =
        /^answer_(\d+)$/.exec(targetId);

    if (
        vehicleAnswerMatch
        && document.getElementById("vehicleChecklistConfig")
    ) {
        const checkForm = Array.from(
            document.querySelectorAll(".inline-check-form")
        ).find(function (form) {
            const itemNumber = form.querySelector(
                'input[name="item_no"]'
            );

            return itemNumber
                && itemNumber.value === vehicleAnswerMatch[1];
        });

        if (checkForm) {
            const answerInput =
                checkForm.querySelector(
                    '[name="value"]:checked'
                )
                || checkForm.querySelector(
                    '[name="value"]'
                );

            if (answerInput) {
                return answerInput;
            }
        }
    }

    let target = document.getElementById(targetId);

    if (!target) {
        target = document.querySelector(
            `[name="${CSS.escape(targetId)}"]`
        );
    }

    if (
        target
        && target.type === "hidden"
        && target.parentElement
    ) {
        const richEditor = target.parentElement.querySelector(
            ".mention-rich-editor"
        );

        if (richEditor) {
            return richEditor;
        }
    }

    return target;
}


function getFormFieldErrorAnchor(target) {
    // OCR include labels contain a checkbox and its caption in a flex row.
    // Keep validation text outside that row so the caption cannot be squeezed.
    const actions = target.closest(".invoice-include")?.closest(".invoice-record-actions");
    return actions || target;
}


function clearCommonErrors() {
    document
        .querySelectorAll(".field-error-message")
        .forEach(function (element) {
            const errorId = element.id;

            if (errorId) {
                document
                    .querySelectorAll(
                        `[aria-describedby~="${CSS.escape(errorId)}"]`
                    )
                    .forEach(function (target) {
                        const describedBy = (
                            target.getAttribute("aria-describedby") || ""
                        )
                            .split(/\s+/)
                            .filter(function (id) {
                                return id && id !== errorId;
                            });

                        if (describedBy.length > 0) {
                            target.setAttribute(
                                "aria-describedby",
                                describedBy.join(" ")
                            );
                        } else {
                            target.removeAttribute("aria-describedby");
                        }
                    });
            }

            element.remove();
        });

    document
        .querySelectorAll(".form-control-error")
        .forEach(function (element) {
            element.classList.remove("form-control-error");
            element.removeAttribute("aria-invalid");
        });

    document.getElementById("error-summary")?.remove();
}


function showCommonError(message, targetId = "", moveFocus = true) {
    let summary = document.getElementById("error-summary");

    if (!summary) {
        summary = document.createElement("div");
        summary.id = "error-summary";
        summary.className = "error-summary";
        summary.setAttribute("role", "alert");
        summary.setAttribute("tabindex", "-1");
        summary.setAttribute(
            "aria-labelledby",
            "error-summary-title"
        );
        summary.innerHTML = `
            <h2 id="error-summary-title">
                入力内容を確認してください
            </h2>
            <ul></ul>
        `;

        const main = document.querySelector("main");
        if (main) {
            main.prepend(summary);
        } else {
            document.body.prepend(summary);
        }
    }

    const openModalBox = document.querySelector(
        ".modal-bg.is-open:not(.is-hidden) .modal-box"
    );

    const summaryContainer =
        openModalBox
        || document.querySelector("main")
        || document.body;

    if (summary.parentElement !== summaryContainer) {
        summaryContainer.prepend(summary);
    }

    const list = summary.querySelector("ul");

    const duplicateError = Array.from(
        list.children
    ).some(function (item) {
        const link = item.querySelector(
            "[data-form-error-target]"
        );

        const itemTargetId = link
            ? link.dataset.formErrorTarget || ""
            : "";

        return (
            item.textContent.trim() === message.trim()
            && itemTargetId === targetId
        );
    });

    if (duplicateError) {
        return;
    }

    const item = document.createElement("li");

    if (targetId) {
        const link = document.createElement("a");
        link.href = `#${targetId}`;
        link.dataset.formErrorTarget = targetId;
        link.dataset.formErrorMessage = message;
        link.textContent = message;
        item.appendChild(link);

        const target = getFormErrorTarget(targetId);

        if (target) {
            target.classList.add("form-control-error");
            target.setAttribute("aria-invalid", "true");

            const errorText = document.createElement("div");
            errorText.id = `${targetId}_error_${list.children.length}`;
            errorText.className = "field-error-message";
            errorText.textContent = message;

            getFormFieldErrorAnchor(target).insertAdjacentElement(
                "afterend",
                errorText
            );

            const describedBy = [
                ...(target.getAttribute("aria-describedby") || "")
                    .split(/\s+/)
                    .filter(Boolean),
                errorText.id
            ];

            target.setAttribute(
                "aria-describedby",
                [...new Set(describedBy)].join(" ")
            );

            if (list.children.length === 0 && moveFocus) {
                target.scrollIntoView({
                    behavior: "smooth",
                    block: "center"
                });

                window.setTimeout(() => {
                    target.focus({ preventScroll: true });
                }, 300);
            }
        }
    } else {
        item.textContent = message;
        if (moveFocus) {
            summary.scrollIntoView({
                behavior: "smooth",
                block: "start"
            });
            summary.focus({ preventScroll: true });
        }
    }

    list.appendChild(item);
}


// フォームエラーを該当項目へ反映
document.querySelectorAll(".error-summary a[data-form-error-target]").forEach((link) => {
    const targetId = link.dataset.formErrorTarget;
    const message = link.dataset.formErrorMessage;
    const target = getFormErrorTarget(targetId);

    if (!target) return;

    const details = target.closest("details");

    if (details) {
        details.open = true;
    }

    target.classList.add("form-control-error");
    target.setAttribute("aria-invalid", "true");

    const errorIndex = Array.from(
        document.querySelectorAll(
            `.error-summary a[data-form-error-target="${CSS.escape(targetId)}"]`
        )
    ).indexOf(link);

    const errorText = document.createElement("div");
    errorText.id = `${targetId}_error_${errorIndex}`;
    errorText.className = "field-error-message";
    errorText.textContent = message;

    const errorAnchor =
        target.id === "delivery_place"
            ? document.getElementById("delivery_place_search_results")
            : getFormFieldErrorAnchor(target);

    errorAnchor.insertAdjacentElement("afterend", errorText);

    const describedBy = [
        ...(target.getAttribute("aria-describedby") || "")
            .split(/\s+/)
            .filter(Boolean),
        errorText.id
    ];

    target.setAttribute(
        "aria-describedby",
        [...new Set(describedBy)].join(" ")
    );
});

// エラーがある場合は最初の修正箇所へ自動移動
const firstErrorLink = document.querySelector(
    ".error-summary a[data-form-error-target]"
);

if (firstErrorLink) {
    const firstErrorTarget = getFormErrorTarget(
        firstErrorLink.dataset.formErrorTarget
    );

    if (firstErrorTarget && firstErrorTarget.type !== "hidden") {
        window.requestAnimationFrame(() => {
            firstErrorTarget.scrollIntoView({
                behavior: "smooth",
                block: "center"
            });

            window.setTimeout(() => {
                firstErrorTarget.focus({ preventScroll: true });
            }, 300);
        });
    }
}

// エラー概要から該当入力項目へ移動
document.addEventListener("click", function (event) {
    const link = event.target.closest(".error-summary a[data-form-error-target]");
    if (!link) return;

    event.preventDefault();

    const target = getFormErrorTarget(
        link.dataset.formErrorTarget
    );
    if (!target) return;

    target.scrollIntoView({
        behavior: "smooth",
        block: "center"
    });

    window.setTimeout(() => {
        target.focus({ preventScroll: true });
    }, 300);
});

// 全パスワード入力欄を共通の表示・非表示切替仕様にする
document.querySelectorAll('input[type="password"]').forEach(function (input) {
    if (input.closest(".password-field")) {
        return;
    }

    const wrapper = document.createElement("div");
    wrapper.className = "password-field";

    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);

    const toggle = document.createElement("button");

    toggle.type = "button";
    toggle.className = "password-eye";
    toggle.setAttribute("aria-label", "パスワードを表示");
    toggle.setAttribute("title", "パスワードを表示");

    toggle.innerHTML = `
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
                d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
            />
            <circle
                cx="12"
                cy="12"
                r="3"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
            />
        </svg>
    `;

    toggle.addEventListener("click", function () {
        const isHidden =
            input.type === "password";

        input.type =
            isHidden ? "text" : "password";

        toggle.classList.toggle(
            "is-visible",
            isHidden
        );

        toggle.setAttribute(
            "aria-label",
            isHidden
                ? "パスワードを隠す"
                : "パスワードを表示"
        );

        toggle.setAttribute(
            "title",
            isHidden
                ? "パスワードを隠す"
                : "パスワードを表示"
        );
    });

    wrapper.appendChild(toggle);
});

document.addEventListener("submit", async function (event) {
    const form = event.target.closest(
        ".js-vehicle-checklist-approval"
    );

    if (!form) {
        return;
    }

    event.preventDefault();

    const button = form.querySelector(
        'button[type="submit"]'
    );

    if (button) {
        button.disabled = true;
    }

    try {
        const response = await fetch(
            form.action,
            {
                method: "POST",
                body: new FormData(form)
            }
        );

        if (
            !response.ok
            || response.url.endsWith(
                "/vehicle/checklists"
            )
        ) {
            if (button) {
                button.disabled = false;
            }

            let message = "承認処理に失敗しました。";

            if (!response.ok) {
                const responseText = (
                    await response.text()
                ).trim();

                if (responseText) {
                    message = responseText;
                }
            }

            showCommonError(message);
            return;
        }

        const destination = new URL(
            response.url,
            window.location.href
        );

        if (
            destination.origin !== window.location.origin
            || destination.pathname !== window.location.pathname
        ) {
            if (button) {
                button.disabled = false;
            }
            showCommonError(
                "承認結果を確認できません。画面を再読み込みして確認してください。"
            );
            return;
        }

        window.history.replaceState(
            null, "", destination.href
        );
        window.location.reload();

    } catch (error) {
        if (button) {
            button.disabled = false;
        }

        showCommonError(
            "承認処理に失敗しました。通信状態を確認して、もう一度お試しください。"
        );
    }
});

document.addEventListener("DOMContentLoaded", function () {
    if (document.body.dataset.authenticated !== "true") {
        return;
    }

    let refreshing = false;
    let refreshAgain = false;

    function updateNotificationCount(count) {
        if (!Number.isInteger(count) || count < 0) {
            return;
        }

        document.body.dataset.unreadNotificationCount =
            String(count);

        [
            "notificationUnreadTabCount",
            "notificationReadAllCount",
            "notificationPopoverUnreadCount"
        ].forEach(function (id) {
            const element = document.getElementById(id);

            if (element) {
                element.textContent = String(count);
            }
        });

        const readAllButton = document.getElementById(
            "notificationReadAllButton"
        );

        if (readAllButton) {
            readAllButton.disabled = count === 0;
        }

        document.querySelectorAll(
            ".notification-bell"
        ).forEach(function (bell) {
            let badge = bell.querySelector(
                ".notification-count"
            );

            if (count === 0) {
                if (badge) {
                    badge.remove();
                }
                return;
            }

            if (!badge) {
                badge = document.createElement("span");
                badge.className = "notification-count";
                bell.appendChild(badge);
            }

            badge.textContent = String(count);
        });

        if (count > 0 && "setAppBadge" in navigator) {
            navigator.setAppBadge(count).catch(function () {});
        } else if (count === 0 && "clearAppBadge" in navigator) {
            navigator.clearAppBadge().catch(function () {});
        }
    }

    async function refreshNotificationCount() {
        if (document.visibilityState === "hidden") return;

        if (refreshing) {
            refreshAgain = true;
            return;
        }

        refreshing = true;

        try {
            const actionCountLabel = document.getElementById(
                "notificationActionTabCount"
            );
            const countUrl = actionCountLabel
                ? "/api/notifications/unread-count?include_action=1"
                : "/api/notifications/unread-count";

            const response = await fetch(
                countUrl,
                {
                    credentials: "same-origin",
                    cache: "no-store",
                    headers: {
                        "Accept": "application/json"
                    }
                }
            );

            if (!response.ok || response.redirected) {
                return;
            }

            const data = await response.json();

            if (refreshAgain) return;

            const count = data.unread_count;

            if (!Number.isInteger(count) || count < 0) {
                return;
            }

            updateNotificationCount(count);

            if (
                actionCountLabel
                && Number.isInteger(data.action_count)
                && data.action_count >= 0
            ) {
                actionCountLabel.textContent = data.action_count;
            }

            const workflowStates = data.workflow_states;

            if (
                workflowStates
                && typeof workflowStates === "object"
                && !Array.isArray(workflowStates)
            ) {
                document.querySelectorAll(
                    ".notification-wrapper[data-notification-id]"
                ).forEach(function (row) {
                    const state = workflowStates[row.dataset.notificationId];
                    const label = row.querySelector(
                        ".js-notification-workflow-label"
                    );

                    if (
                        !label
                        || !state
                        || typeof state.workflow_label !== "string"
                    ) {
                        return;
                    }

                    label.textContent = state.workflow_label;
                    label.hidden = !state.workflow_label;
                    label.dataset.workflowStatus =
                        state.workflow_status || "";
                    label.dataset.requiresAction =
                        state.requires_action ? "true" : "false";
                });

                document.dispatchEvent(new CustomEvent(
                    "dkss:notification-workflow-updated",
                    { detail: { workflowStates: workflowStates } }
                ));
            }
        } catch (error) {
            console.error("通知件数の更新に失敗しました:", error);
        } finally {
            refreshing = false;

            if (refreshAgain) {
                refreshAgain = false;
                refreshNotificationCount();
            }
        }
    }

    updateNotificationCount(Number(
        document.body.dataset.unreadNotificationCount || 0
    ));

    document.addEventListener(
        "dkss:notifications-changed",
        function (event) {
            updateNotificationCount(event.detail?.unread_count);
            refreshNotificationCount();
        }
    );

    const notificationSyncKey = "dkss-notifications-changed";

    window.addEventListener("storage", function (event) {
        if (event.key === notificationSyncKey) {
            refreshNotificationCount();
        }
    });

    window.setInterval(function () {
        refreshNotificationCount();
    }, 30000);

    refreshNotificationCount();

    window.addEventListener(
        "pageshow",
        refreshNotificationCount
    );

    window.addEventListener(
        "focus",
        refreshNotificationCount
    );

    document.addEventListener(
        "visibilitychange",
        refreshNotificationCount
    );
});

// ベル：最近の通知の開閉・取得
document.addEventListener("DOMContentLoaded", function () {
    const menu = document.getElementById("notificationMenu");
    const bell = document.getElementById("notificationBell");
    const panel = document.getElementById("notificationPopover");
    const closeButton = document.getElementById("notificationPopoverClose");
    const list = document.getElementById("notificationPopoverList");
    const status = document.getElementById("notificationPopoverStatus");

    if (!menu || !bell || !panel || !closeButton || !list || !status) {
        return;
    }

    let controller = null;

    function positionPanel() {
        if (panel.hidden) {
            return;
        }

        const rect = bell.getBoundingClientRect();
        const top = Math.max(
            16,
            Math.min(rect.bottom + 8, window.innerHeight - 120)
        );
        const width = panel.getBoundingClientRect().width;
        const right = Math.max(
            16,
            Math.min(
                window.innerWidth - rect.right,
                window.innerWidth - width - 16
            )
        );

        panel.style.top = top + "px";
        panel.style.right = right + "px";
        panel.style.maxHeight = Math.max(
            80,
            Math.min(560, window.innerHeight - top - 16)
        ) + "px";
    }

    function closePanel(returnFocus) {
        panel.hidden = true;
        bell.setAttribute("aria-expanded", "false");
        bell.setAttribute("aria-label", "最近の通知を開く");

        if (controller) {
            controller.abort();
            controller = null;
        }

        list.setAttribute("aria-busy", "false");

        if (returnFocus) {
            bell.focus();
        }
    }

    function appendText(parent, className, text) {
        const element = document.createElement("div");
        element.className = className;
        element.textContent = text;
        parent.appendChild(element);
    }

    let actionPending = false;

    async function runNotificationAction(id, action, button, payload) {
        if (actionPending) return;
        actionPending = true;
        button.disabled = true;

        try {
            const response = await fetch(
                "/api/notifications/" + id + "/" + action,
                {
                    method: "POST",
                    credentials: "same-origin",
                    cache: "no-store",
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "X-CSRFToken": document.querySelector(
                            'meta[name="csrf-token"]'
                        )?.content || ""
                    },
                    body: JSON.stringify(payload || {})
                }
            );
            const result = await response.json();

            if (!response.ok || response.redirected) {
                throw new Error(result.error || "通知を更新できませんでした。");
            }
            if (
                result.notification_id !== id ||
                !Number.isInteger(result.unread_count) ||
                result.unread_count < 0 ||
                (action === "read" && result.read !== true) ||
                (action === "delete" && typeof result.deleted_at !== "string") ||
                (action === "undo-delete" && result.deleted_at !== null)
            ) {
                throw new Error("通知の更新結果が正しくありません。");
            }

            document.dispatchEvent(new CustomEvent(
                "dkss:notifications-changed", { detail: result }
            ));
            document.dispatchEvent(new CustomEvent(
                "dkss:notification-item-updated",
                { detail: { ...result, action: action } }
            ));
            try {
                localStorage.setItem(
                    "dkss-notifications-changed",
                    Date.now() + ":" + Math.random()
                );
            } catch (error) {}

            if (!panel.hidden) {
                await loadRecentNotifications();
                if (!panel.hidden && action === "delete") {
                    status.replaceChildren(
                        document.createTextNode("通知を削除しました。 ")
                    );
                    const undo = document.createElement("button");
                    undo.type = "button";
                    undo.className = "notification-popover-undo";
                    undo.textContent = "元に戻す";
                    undo.addEventListener("click", function () {
                        runNotificationAction(id, "undo-delete", undo, {
                            deleted_at: result.deleted_at
                        });
                    });
                    status.appendChild(undo);
                    undo.focus({ preventScroll: true });
                } else if (!panel.hidden) {
                    closeButton.focus({ preventScroll: true });
                }
            }
        } catch (error) {
            showCommonError(
                error.message || "通知を更新できませんでした。"
            );
        } finally {
            actionPending = false;
            button.disabled = false;
        }
    }

    async function loadRecentNotifications() {
        const requestController = new AbortController();
        controller = requestController;
        list.replaceChildren();
        list.setAttribute("aria-busy", "true");
        status.textContent = "読み込み中…";

        try {
            const response = await fetch("/api/notifications/recent", {
                credentials: "same-origin",
                cache: "no-store",
                headers: { "Accept": "application/json" },
                signal: requestController.signal
            });

            if (!response.ok || response.redirected) {
                throw new Error("通知を取得できませんでした。");
            }

            const data = await response.json();

            if (!Array.isArray(data.notifications)) {
                throw new Error("通知の取得結果が正しくありません。");
            }

            if (panel.hidden || controller !== requestController) {
                return;
            }

            const fragment = document.createDocumentFragment();
            let previousDayKey = null;

            data.notifications.forEach(function (notification) {
                if (
                    !Number.isInteger(notification.id)
                    || notification.id <= 0
                ) {
                    return;
                }

                const dayKey = notification.day_key || "unknown";

                if (dayKey !== previousDayKey) {
                    appendText(
                        fragment,
                        "notification-popover-day",
                        notification.day_label || "日時不明"
                    );
                    previousDayKey = dayKey;
                }

                const item = document.createElement("a");
                item.className = "notification-popover-item"
                    + (notification.read ? "" : " unread");
                item.href = "/notifications?view=inbox&notification="
                    + notification.id;

                appendText(
                    item,
                    "notification-popover-meta",
                    [
                        notification.category_label,
                        notification.type_label
                    ].filter(Boolean).join("・")
                );

                const target = notification.target_info;
                const title = target?.checklist_name
                    ? [
                        target.checklist_name,
                        target.target_label || target.office
                    ].filter(Boolean).join("｜")
                    : notification.title || "";

                appendText(
                    item,
                    "notification-popover-title",
                    title
                );

                const states = document.createElement("div");
                states.className = "notification-popover-states";

                const readBadge = document.createElement("span");
                readBadge.className = "notification-popover-read";
                readBadge.textContent =
                    notification.read ? "既読" : "未読";
                states.appendChild(readBadge);

                if (notification.workflow_label) {
                    const workflowBadge = document.createElement("span");
                    workflowBadge.className =
                        "notification-popover-workflow";
                    workflowBadge.dataset.workflowStatus =
                        notification.workflow_status || "";
                    workflowBadge.dataset.requiresAction =
                        notification.requires_action ? "true" : "false";
                    workflowBadge.textContent =
                        notification.workflow_label;
                    states.appendChild(workflowBadge);
                }

                item.appendChild(states);
                const message = document.createElement("div");
                message.className = "notification-popover-message";

                renderMentionValue(
                    message,
                    notification.message || ""
                );

                item.appendChild(message);
                appendText(
                    item,
                    "notification-popover-meta",
                    notification.time_label || ""
                );

                const wrapper = document.createElement("div");
                wrapper.className = "notification-popover-row";
                wrapper.appendChild(item);

                const actions = document.createElement("details");
                actions.className = "notification-popover-actions";
                const trigger = document.createElement("summary");
                trigger.setAttribute("aria-label", "通知の操作");
                trigger.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>';
                actions.appendChild(trigger);

                const commands = document.createElement("div");
                commands.className = "notification-popover-commands";
                const confirm = document.createElement("a");
                confirm.href = item.href;
                confirm.textContent = "確認";
                commands.appendChild(confirm);

                function addAction(label, action) {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.textContent = label;
                    button.dataset.action = action;
                    button.addEventListener("click", function () {
                        actions.open = false;
                        runNotificationAction(
                            notification.id, action, button
                        );
                    });
                    commands.appendChild(button);
                }

                if (!notification.read) addAction("既読", "read");
                addAction("削除", "delete");
                actions.appendChild(commands);
                wrapper.appendChild(actions);

                actions.addEventListener("toggle", function () {
                    if (!actions.open) return;

                    list.querySelectorAll(
                        ".notification-popover-actions[open]"
                    ).forEach(function (other) {
                        if (other !== actions) other.open = false;
                    });

                    const rect = trigger.getBoundingClientRect();
                    commands.style.left = Math.max(
                        8,
                        Math.min(
                            rect.right - 140,
                            window.innerWidth - 148
                        )
                    ) + "px";
                    commands.style.top = Math.max(
                        8,
                        Math.min(
                            rect.bottom + 4,
                            window.innerHeight - commands.offsetHeight - 8
                        )
                    ) + "px";
                });

                fragment.appendChild(wrapper);
            });

            list.replaceChildren(fragment);

            if (
                Number.isInteger(data.unread_count) &&
                data.unread_count >= 0
            ) {
                document.dispatchEvent(new CustomEvent(
                    "dkss:notifications-changed",
                    { detail: { unread_count: data.unread_count } }
                ));
            }

            status.textContent = list.childElementCount
                ? ""
                : "受信箱に通知はありません。";
        } catch (error) {
            if (
                error.name === "AbortError"
                || panel.hidden
                || controller !== requestController
            ) {
                return;
            }

            status.textContent = "通知一覧から確認してください。";
            showCommonError("最近の通知を取得できませんでした。");
        } finally {
            if (controller === requestController) {
                controller = null;
                list.setAttribute("aria-busy", "false");
            }
        }
    }

    bell.addEventListener("click", function (event) {
        if (
            event.button !== 0
            || event.ctrlKey
            || event.metaKey
            || event.shiftKey
            || event.altKey
        ) {
            return;
        }

        event.preventDefault();

        if (!panel.hidden) {
            closePanel(true);
            return;
        }

        panel.hidden = false;
        bell.setAttribute("aria-expanded", "true");
        bell.setAttribute("aria-label", "最近の通知を閉じる");
        positionPanel();
        closeButton.focus();
        loadRecentNotifications();
    });

    closeButton.addEventListener("click", function () {
        closePanel(true);
    });

    document.addEventListener("click", function (event) {
        if (!panel.hidden && !menu.contains(event.target)) {
            closePanel(false);
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !panel.hidden) {
            event.preventDefault();
            closePanel(true);
        }
    });

    document.addEventListener("focusin", function (event) {
        if (!panel.hidden && !menu.contains(event.target)) {
            closePanel(false);
        }
    });

    window.addEventListener("resize", positionPanel);
    window.addEventListener("scroll", positionPanel, true);
});

// The driver list filter runs under the same strict CSP as every other page.
document.addEventListener("DOMContentLoaded", function () {
    const filter = document.getElementById("driver_vehicle_filter");
    const options = document.getElementById("driver_vehicle_options");
    if (!filter || !options) return;

    let searchTimer = null;
    let generation = 0;
    filter.addEventListener("input", function () {
        window.clearTimeout(searchTimer);
        const current = ++generation;
        const keyword = filter.value.trim();
        options.replaceChildren();
        if (!keyword) return;

        searchTimer = window.setTimeout(async function () {
            try {
                const response = await fetch(
                    "/api/vehicles?q=" + encodeURIComponent(keyword)
                );
                if (!response.ok) throw new Error("Vehicle lookup failed");
                const data = await response.json();
                if (!Array.isArray(data.results)) {
                    throw new Error("Invalid vehicle candidates");
                }
                if (current !== generation) return;
                data.results.forEach(function (vehicle) {
                    const option = document.createElement("option");
                    option.value = vehicle.vehicle_record_id;
                    option.label = vehicle.number || "ナンバー未登録";
                    options.appendChild(option);
                });
            } catch (error) {
                if (current !== generation) return;
                options.replaceChildren();
                showCommonError(
                    "使用車両の候補を取得できませんでした。再度検索してください。",
                    "driver_vehicle_filter"
                );
            }
        }, 300);
    });
});

// Confirmation handlers must be external; inline onsubmit is blocked by CSP.
document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
    const message = form.dataset.confirmMessage;
    if (message && !window.confirm(message)) event.preventDefault();
});

// GET filters use an external handler so they also work under strict CSP.
document.addEventListener("change", function (event) {
    const control = event.target;
    if (!(control instanceof HTMLSelectElement)
        || !control.hasAttribute("data-auto-submit")) return;
    const form = control.form;
    if (form && form.method.toLowerCase() === "get") form.requestSubmit();
});

// Dismiss overlays through each surface's existing close/cancel behavior.
// A drag beginning inside a panel must never count as a backdrop click.
(() => {
    let press = null;
    function outsideSurface(event) {
        const dialogs = Array.from(document.querySelectorAll('dialog[open]'))
            .filter(dialog => dialog.matches(':modal'));
        const dialog = dialogs.at(-1);
        if (dialog) {
            const surface = dialog.querySelector('.modal-box') || dialog;
            const box = surface.getBoundingClientRect();
            const outside = event.clientX < box.left || event.clientX > box.right
                || event.clientY < box.top || event.clientY > box.bottom;
            return outside ? { element: dialog, type: 'dialog' } : null;
        }
        const drawer = document.querySelector('.ka-reference-drawer:not([hidden])');
        if (drawer && !drawer.contains(event.target)) {
            return { element: drawer, type: 'drawer' };
        }
        return null;
    }
    document.addEventListener('pointerdown', event => {
        press = null;
        if (event.button !== 0 || !event.isPrimary) return;
        const surface = outsideSurface(event);
        if (surface) press = { ...surface, x: event.clientX, y: event.clientY };
    }, true);
    document.addEventListener('pointercancel', () => { press = null; }, true);
    document.addEventListener('click', event => {
        const start = press;
        press = null;
        if (!start || event.button !== 0) return;
        const end = outsideSurface(event);
        if (!end || end.element !== start.element
            || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 8) return;
        event.preventDefault();
        event.stopPropagation();
        const surface = start.element;
        if (surface.querySelector('[aria-busy="true"], [data-submitting="true"], button[type="submit"]:disabled, [data-review-save]:disabled, [data-plan-save]:disabled')) return;
        if (start.type === 'dialog') {
            // Existing cancel handlers retain unsaved-input and in-flight guards.
            if (surface.dispatchEvent(new Event('cancel', { cancelable: true }))) surface.close();
        } else {
            surface.querySelector('.ka-drawer-close')?.click();
        }
    }, true);
})();

// Company-wide master order, including filtered and responsive lists.
(() => {
    const busyUrls = new Set();
    function initializeMasterOrder() {
        document.querySelectorAll('[data-master-order-url]').forEach(initializeList);
    }
    function initializeList(table) {
        const body = table.tBodies ? table.tBodies[0] : table;
        const status = document.getElementById(table.dataset.masterStatusId)
            || table.previousElementSibling?.querySelector('.master-order-status');
        if (!body || !status) return;
        const url = table.dataset.masterOrderUrl;
        const peers = () => Array.from(document.querySelectorAll('[data-master-order-url]'))
            .filter(element => element.dataset.masterOrderUrl === url);
        const rows = () => Array.from(body.querySelectorAll('[data-master-id]'));
        const ids = () => rows().map(row => Number(row.dataset.masterId));
        let savedIds = ids();
        let savedAllIds = table.dataset.masterOrderAllIds
            ? JSON.parse(table.dataset.masterOrderAllIds) : savedIds.slice();
        document.addEventListener('master-order-saved', event => {
            if (event.detail.url !== url || saving) return;
            savedAllIds = event.detail.ids.slice();
            const ranks = new Map(savedAllIds.map((id, index) => [id, index]));
            savedIds = ids().sort((a, b) => ranks.get(a) - ranks.get(b));
            restore();
        });
        let saving = false;
        let drag = null;
        function restore() {
            const byId = new Map(rows().map(row => [Number(row.dataset.masterId), row]));
            savedIds.forEach(id => body.append(byId.get(id)));
        }
        async function save() {
            const next = ids();
            if (next.every((id, index) => id === savedIds[index])) return;
            if (busyUrls.has(url)) return;
            // Replace only visible slots; hidden checklist rows keep their positions.
            const visible = new Set(next);
            let index = 0;
            const merged = savedAllIds.map(id => visible.has(id) ? next[index++] : id);
            const focusedHandle = document.activeElement;
            saving = true;
            busyUrls.add(url);
            peers().forEach(peer => {
                peer.setAttribute('aria-busy', 'true');
                peer.querySelectorAll('.master-order-handle').forEach(handle => { handle.disabled = true; });
            });
            status.textContent = '保存中…';
            status.classList.remove('is-error');
            try {
                const response = await fetch(table.dataset.masterOrderUrl, {
                    method: 'POST', credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content
                    },
                    body: JSON.stringify({ids: merged, previous_ids: savedAllIds})
                });
                let result;
                try { result = await response.json(); } catch (_) { throw new Error('保存できませんでした。再読み込みして再度お試しください。'); }
                if (!response.ok || !result.ok) throw new Error(result.message || '保存できませんでした。');
                savedIds = next;
                savedAllIds = merged;
                document.dispatchEvent(new CustomEvent('master-order-saved', {detail: {url, ids: merged}}));
                status.textContent = '保存しました';
            } catch (error) {
                restore();
                status.textContent = error.message || '保存できませんでした。';
                status.classList.add('is-error');
            } finally {
                saving = false;
                busyUrls.delete(url);
                peers().forEach(peer => {
                    peer.removeAttribute('aria-busy');
                    peer.querySelectorAll('.master-order-handle').forEach(handle => { handle.disabled = false; });
                });
                if (focusedHandle?.classList.contains('master-order-handle')) focusedHandle.focus({preventScroll: true});
            }
        }
        function moveAtPointer() {
            if (!drag || !drag.moving) return;
            const hit = document.elementFromPoint(drag.x, drag.y)?.closest('[data-master-id]');
            if (!hit || hit === drag.row || hit.parentElement !== body) return;
            const rect = hit.getBoundingClientRect();
            if (drag.y < rect.top + rect.height / 2) body.insertBefore(drag.row, hit);
            else body.insertBefore(drag.row, hit.nextSibling);
        }
        function scrollFrame() {
            if (!drag) return;
            if (drag.moving) {
                const edge = 70;
                const dy = drag.y < edge ? -14 : drag.y > window.innerHeight - edge ? 14 : 0;
                if (dy) window.scrollBy(0, dy);
                moveAtPointer();
            }
            drag.frame = requestAnimationFrame(scrollFrame);
        }
        function finish(cancelled) {
            if (!drag) return;
            const current = drag;
            drag = null;
            cancelAnimationFrame(current.frame);
            current.row.classList.remove('is-dragging');
            document.body.classList.remove('master-order-dragging');
            if (body.hasPointerCapture(current.pointerId)) body.releasePointerCapture(current.pointerId);
            if (cancelled) restore();
            else if (current.moving) void save();
        }
        body.addEventListener('pointerdown', event => {
            const handle = event.target.closest('.master-order-handle');
            if (!handle || saving || busyUrls.has(url) || drag || event.button !== 0 || !event.isPrimary) return;
            event.preventDefault();
            handle.focus({preventScroll: true});
            drag = {row: handle.closest('[data-master-id]'), handle, pointerId: event.pointerId,
                    startX: event.clientX, startY: event.clientY,
                    x: event.clientX, y: event.clientY, moving: false, frame: 0};
            // Capture on the stable tbody: moving a row must not cancel the drag.
            body.setPointerCapture(event.pointerId);
            drag.frame = requestAnimationFrame(scrollFrame);
        });
        body.addEventListener('pointermove', event => {
            if (!drag || drag.pointerId !== event.pointerId) return;
            drag.x = event.clientX; drag.y = event.clientY;
            if (!drag.moving && Math.hypot(drag.x - drag.startX, drag.y - drag.startY) > 5) {
                drag.moving = true;
                drag.row.classList.add('is-dragging');
                document.body.classList.add('master-order-dragging');
            }
            moveAtPointer();
        });
        body.addEventListener('pointerup', event => { if (drag?.pointerId === event.pointerId) finish(false); });
        body.addEventListener('pointercancel', () => finish(true));
        body.addEventListener('lostpointercapture', () => { if (drag) finish(true); });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && drag) {
                event.preventDefault();
                finish(true);
            }
        });
        body.addEventListener('keydown', event => {
            const handle = event.target.closest('.master-order-handle');
            if (!handle || saving || busyUrls.has(url) || drag || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
            event.preventDefault();
            const row = handle.closest('[data-master-id]');
            const list = rows(); const index = list.indexOf(row);
            const target = list[index + (event.key === 'ArrowUp' ? -1 : 1)];
            if (!target) return;
            body.insertBefore(row, event.key === 'ArrowUp' ? target : target.nextSibling);
            handle.focus({preventScroll: true});
            void save();
        });
        window.addEventListener('beforeunload', event => {
            if (saving) { event.preventDefault(); event.returnValue = ''; }
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initializeMasterOrder);
    else initializeMasterOrder();
})();

// Keep the planning page's dynamically generated office choices in master order.
(() => {
    function orderPlannerOffices() {
        const meta = document.querySelector('meta[name="master-office-order"]');
        const select = document.querySelector('[data-inspection-planner] select[name="office"]');
        if (!meta || !select) return;
        const ranks = new Map(JSON.parse(meta.content).map((name, index) => [name, index]));
        const sort = () => {
            const before = Array.from(select.options);
            const ordered = before.slice().sort((a, b) => {
                const rank = o => !o.value ? -1 : ranks.get(o.value) ?? ranks.size;
                return rank(a) - rank(b);
            });
            if (ordered.some((option, index) => option !== before[index])) {
                const value = select.value;
                select.append(...ordered);
                select.value = value;
            }
        };
        new MutationObserver(sort).observe(select, {childList: true});
        sort();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', orderPlannerOffices);
    else orderPlannerOffices();
})();

// Standard checklist definitions are previewed locally without editable fields.
(() => {
    function initializeStandardChecklistPreview() {
        const dialog = document.getElementById('standard-checklist-dialog');
        if (!dialog) return;
        const body = dialog.querySelector('[data-standard-checklist-body]');
        const heading = document.getElementById('standard-checklist-dialog-title');
        const tooltip = document.getElementById('standard-checklist-explanation');
        let opener = null;
        function hideTooltip() { if (tooltip) tooltip.hidden = true; }
        function showTooltip(badge) {
            if (!tooltip) return;
            tooltip.hidden = false;
            const box = badge.getBoundingClientRect();
            tooltip.style.left = Math.max(8, Math.min(box.left, window.innerWidth - tooltip.offsetWidth - 8)) + 'px';
            tooltip.style.top = Math.max(8, Math.min(box.bottom + 6, window.innerHeight - tooltip.offsetHeight - 8)) + 'px';
        }
        document.addEventListener('click', event => {
            const button = event.target.closest('[data-standard-checklist-preview]');
            const badge = event.target.closest('[data-standard-checklist-info]');
            if (badge) { showTooltip(badge); return; }
            hideTooltip();
            if (!button) return;
            const template = document.getElementById(button.dataset.standardChecklistPreview);
            if (!template || template.tagName !== 'TEMPLATE') return;
            opener = button;
            heading.textContent = template.dataset.checklistTitle;
            body.replaceChildren(template.content.cloneNode(true));
            body.scrollTop = 0;
            if (!dialog.open) dialog.showModal();
        });
        document.addEventListener('focusin', event => {
            const badge = event.target.closest('[data-standard-checklist-info]');
            if (badge) showTooltip(badge); else hideTooltip();
        });
        document.addEventListener('pointerover', event => {
            const badge = event.target.closest('[data-standard-checklist-info]');
            if (badge) showTooltip(badge);
        });
        document.addEventListener('pointerout', event => {
            if (event.target.closest('[data-standard-checklist-info]') && !document.activeElement?.matches('[data-standard-checklist-info]')) hideTooltip();
        });
        document.addEventListener('keydown', event => { if (event.key === 'Escape') hideTooltip(); });
        window.addEventListener('scroll', hideTooltip, true);
        window.addEventListener('resize', hideTooltip);
        dialog.querySelector('[data-standard-checklist-close]').addEventListener('click', () => dialog.close());
        dialog.addEventListener('close', () => {
            body.replaceChildren();
            if (opener?.isConnected) opener.focus({preventScroll: true});
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initializeStandardChecklistPreview);
    else initializeStandardChecklistPreview();
})();

// Close checklist navigation on outside clicks and Escape.
(() => {
    function positionMenu(menu) {
        if (!menu.open) return;
        const panel = menu.querySelector('.checklist-result-options');
        const anchor = menu.querySelector('summary').getBoundingClientRect();
        panel.style.maxHeight = Math.max(100, Math.min(320, innerHeight - 24)) + 'px';
        panel.style.left = Math.max(12, Math.min(anchor.left, innerWidth - panel.offsetWidth - 12)) + 'px';
        panel.style.top = Math.max(12, Math.min(anchor.bottom + 8, innerHeight - panel.offsetHeight - 12)) + 'px';
    }
    document.addEventListener('toggle', event => {
        if (event.target.matches('.checklist-result-switcher')) positionMenu(event.target);
    }, true);
    window.addEventListener('resize', () => {
        document.querySelectorAll('.checklist-result-switcher[open]').forEach(positionMenu);
    });
    window.addEventListener('scroll', event => {
        if (event.target instanceof Element && event.target.closest('.checklist-result-options')) return;
        document.querySelectorAll('.checklist-result-switcher[open]').forEach(positionMenu);
    }, true);
    document.addEventListener('click', event => {
        document.querySelectorAll('.checklist-result-switcher[open]').forEach(menu => {
            if (!menu.contains(event.target)) menu.open = false;
        });
    });
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        document.querySelectorAll('.checklist-result-switcher[open]').forEach(menu => {
            menu.open = false;
            if (menu.contains(document.activeElement)) menu.querySelector('summary').focus();
        });
    });
})();
