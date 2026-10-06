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

    if (
        (isSafetyInputPage || isVehicleInputPage) &&
        window.innerWidth > 900
    ) {
        document.body.classList.add("sidebar-collapsed");

    } else if (
        isSafetyResultListPage &&
        window.innerWidth > 900
    ) {
        document.body.classList.remove("sidebar-collapsed");

    } else if (
        localStorage.getItem("sidebarCollapsed") === "1"
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

            target.insertAdjacentElement(
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
            : target;

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

        const approvedBy =
            document.body.dataset.currentUser || "";

        const badge =
            document.createElement("span");

        badge.className =
            "status-badge status-approved";

        badge.title = approvedBy;
        badge.textContent =
            approvedBy.slice(0, 1) || "済";

        form.replaceWith(badge);

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