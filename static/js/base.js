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

    fetch("/api/mention-users?q=" + encodeURIComponent(keyword))
        .then(res => res.json())
        .then(data => {
            showMentionBox(input, data.users, match[0]);
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

    activeRichMentionRange = {
        editor: editor,
        node: node,
        startOffset: range.startOffset - match[0].length,
        endOffset: range.startOffset
    };

    fetch("/api/mention-users?q=" + encodeURIComponent(keyword))
        .then(res => res.json())
        .then(data => {
            showRichMentionBox(
                editor,
                data.users
            );
        });
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

        item.innerHTML =
            "<strong>" + user.name + "</strong>" +
            "<span>" + (user.office || "") + "</span>";

        item.addEventListener("click", function () {
            insertRichMention(user.name);
        });

        box.appendChild(item);
    });

    box.classList.add("is-visible");
}

function insertRichMention(name) {
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
    const chip = createMentionChip(name);
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
        editor.parentElement.querySelector(
            'input[type="hidden"][name]'
        );

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

        item.innerHTML =
            "<strong>" + user.name + "</strong>" +
            "<span>" + (user.office || "") + "</span>";

        item.addEventListener("click", function () {
            insertMention(input, mentionText, user.name);
        });
        box.appendChild(item);
    });

    box.classList.add("is-visible");
}

function insertMention(input, mentionText, name) {
    const caret = input.selectionStart;
    const text = input.value;

    const before = text.slice(0, caret);
    const after = text.slice(caret);

    const newBefore = before.replace(
        /@([^@\s]*)$/,
        "[[" + name + "]] "
    );

    input.value = newBefore + after;
    input.focus();
    input.selectionStart = input.selectionEnd = newBefore.length;

    closeMentionBox();
}

function createMentionChip(name) {
    const chip = document.createElement("span");

    const currentUserName = document.body.dataset.currentUser || "";

    chip.className = "mention-chip";

    if (name === currentUserName) {
        chip.classList.add("mention-chip-self");
    } else {
        chip.classList.add("mention-chip-other");
    }

    chip.dataset.mention = name;
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
        const beforeText = value.slice(lastIndex, match.index);

        if (beforeText) {
            editor.appendChild(
                document.createTextNode(beforeText)
            );
        }

        editor.appendChild(
            createMentionChip(match[1])
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

window.addEventListener("DOMContentLoaded", function() {

    document.querySelectorAll(".mention-rich-editor")
        .forEach(function(editor) {

            const hiddenInput =
                editor.parentElement.querySelector(
                    'input[type="hidden"][name]'
                );

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

            if (form) {
                form.addEventListener("submit", function(event) {

                    const value =
                        getMentionEditorValue(editor).trim();

                    if (hiddenInput) {
                        hiddenInput.value = value;
                    }

                    if (
                        editor.dataset.required === "true" &&
                        !value
                    ) {
                        event.preventDefault();

                        alert("必須項目を入力してください。");

                        editor.focus();
                    }
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
    const sidebarToggle = document.getElementById("sidebarToggle");

    if (sidebarToggle) {
        sidebarToggle.addEventListener("click", toggleSidebar);
    }
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