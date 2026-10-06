document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(
        ".notification-list > .notification-date-heading"
    ).forEach(function (heading) {
        const toggle = heading.querySelector(".notification-date-toggle");
        if (!toggle) return;

        toggle.addEventListener("click", function () {
            const expanded = toggle.getAttribute("aria-expanded") === "true";
            toggle.setAttribute("aria-expanded", String(!expanded));

            let row = heading.nextElementSibling;
            while (row && !row.classList.contains("notification-date-heading")) {
                if (row.classList.contains("notification-wrapper")) {
                    row.hidden = expanded;
                }
                row = row.nextElementSibling;
            }
        });
    });

    const filterForm = document.querySelector(".notification-filter");

    document.querySelectorAll(
        ".notification-filter select, #notificationSort"
    ).forEach(function (select) {
        select.addEventListener("change", function () {
            filterForm.requestSubmit();
        });
    });

    const bulkForm = document.getElementById("notificationBulkForm");
    const selectAll = document.getElementById("notificationSelectAll");
    const countLabel = document.getElementById("notificationSelectedCount");

    let checkboxes = Array.from(
        document.querySelectorAll(".js-notification-select")
    );

    function selectedCount() {
        return checkboxes.filter(function (checkbox) {
            return checkbox.checked;
        }).length;
    }

    function updateSelection() {
        const count = selectedCount();

        if (countLabel) {
            countLabel.textContent = count + "件選択";
        }

        if (selectAll) {
            selectAll.checked =
                checkboxes.length > 0 && count === checkboxes.length;

            selectAll.indeterminate =
                count > 0 && count < checkboxes.length;
        }

        if (bulkForm) {
            bulkForm.hidden = false;

            const clearButton = document.getElementById(
                "notificationClearSelection"
            );

            if (clearButton) {
                clearButton.disabled = count === 0;
            }

            bulkForm.querySelectorAll(
                'button[type="submit"]'
            ).forEach(function (button) {
                button.disabled = count === 0;
            });
        }
    }

    if (selectAll) {
        selectAll.addEventListener("change", function () {
            checkboxes.forEach(function (checkbox) {
                checkbox.checked = selectAll.checked;
            });

            updateSelection();
        });
    }

    checkboxes.forEach(function (checkbox) {
        checkbox.addEventListener("change", updateSelection);
    });

    const clearSelection = document.getElementById(
        "notificationClearSelection"
    );

    clearSelection?.addEventListener("click", function () {
        checkboxes.forEach(function (checkbox) {
            checkbox.checked = false;
        });

        updateSelection();
    });

    const operationForms = Array.from(
        document.querySelectorAll(
            ".notification-actions form, #notificationReadAllForm, .js-notification-undo-form"
        )
    );

    if (bulkForm) {
        operationForms.push(bulkForm);
    }

    operationForms.forEach(function (form) {
        form.addEventListener("submit", function (event) {
            if (form.dataset.submitting === "true") {
                event.preventDefault();
                return;
            }

            if (form === bulkForm) {
                const count = selectedCount();

                if (count === 0 || count > 500) {
                    event.preventDefault();

                    showCommonError(
                        count === 0
                            ? "操作する通知を選択してください。"
                            : "一度に操作できる通知は500件までです。"
                    );

                    return;
                }
            }

            form.dataset.submitting = "true";
            form.setAttribute("aria-busy", "true");
        });
    });

    window.addEventListener("pageshow", function (event) {
        if (event.persisted) {
            history.replaceState(
                {
                    ...history.state,
                    notificationReturnScrollY: getListScrollPosition()
                },
                ""
            );

            window.location.reload();
            return;
        }

        operationForms.forEach(function (form) {
            delete form.dataset.submitting;
            form.removeAttribute("aria-busy");
        });

        updateSelection();

        const savedY = history.state?.notificationReturnScrollY;

        if (Number.isFinite(savedY) && savedY >= 0) {
            const nextState = { ...history.state };
            delete nextState.notificationReturnScrollY;
            history.replaceState(nextState, "");

            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    window.scrollTo({
                        top: savedY,
                        behavior: "instant"
                    });
                });
            });
        }
    });

    const scrollState = [
        document.body.dataset.currentUser || "",
        document.querySelector(
            '.notification-filter input[name="view"]'
        )?.value || "inbox",
        document.getElementById("notificationCategory")?.value || "",
        document.getElementById("notificationType")?.value || "",
        document.getElementById("notificationSearch")?.value || ""
    ];

    const scrollKey = "dkss-notification-scroll:"
        + JSON.stringify(scrollState);

    function getListScrollPosition() {
        const layout = document.getElementById("notificationLayout");
        const saved = Number(layout?.dataset.listScrollY);

        if (
            layout?.classList.contains("is-detail-open") &&
            matchMedia("(max-width: 1100px)").matches &&
            Number.isFinite(saved) && saved >= 0
        ) {
            return saved;
        }

        return window.scrollY;
    }

    function saveScrollPosition() {
        try {
            sessionStorage.setItem(
                scrollKey,
                String(getListScrollPosition())
            );
        } catch (error) {
            console.debug("通知一覧の位置を保存できません。");
        }
    }

    function restoreScrollPosition() {
        try {
            const saved = sessionStorage.getItem(scrollKey);

            if (saved === null) {
                return;
            }

            sessionStorage.removeItem(scrollKey);

            const position = Number(saved);

            if (!Number.isFinite(position) || position < 0) {
                return;
            }

            window.requestAnimationFrame(function () {
                window.requestAnimationFrame(function () {
                    window.scrollTo({
                        top: position,
                        behavior: "instant"
                    });
                });
            });
        } catch (error) {
            console.debug("通知一覧の位置を復元できません。");
        }
    }

    document.addEventListener("click", function (event) {
        const link = event.target.closest(
            ".notification-item, .js-notification-open"
        );

        if (
            !link
            || event.defaultPrevented
            || event.button !== 0
            || event.ctrlKey
            || event.metaKey
            || event.shiftKey
            || event.altKey
        ) {
            return;
        }

        saveScrollPosition();
    });

    document.addEventListener("submit", function (event) {
        const form = event.target;

        if (
            !event.defaultPrevented &&
            (operationForms.includes(form) ||
             form.closest("#notificationDetailPane"))
        ) {
            saveScrollPosition();
        }
    });

    window.addEventListener("pageshow", restoreScrollPosition);

    document.addEventListener(
        "dkss:notification-workflow-updated",
        function (event) {
            if (scrollState[1] !== "action") {
                return;
            }

            if (operationForms.some(function (form) {
                return form.dataset.submitting === "true";
            })) {
                return;
            }

            const states = event.detail?.workflowStates;

            if (
                !states
                || typeof states !== "object"
                || Array.isArray(states)
            ) {
                return;
            }

            document.querySelectorAll(
                ".notification-wrapper[data-notification-id]"
            ).forEach(function (row) {
                const state = states[row.dataset.notificationId];

                if (state?.requires_action !== false) {
                    return;
                }

                const checkbox = row.querySelector(
                    ".js-notification-select"
                );

                if (checkbox) {
                    checkbox.checked = false;
                    checkbox.disabled = true;
                }

                row.remove();
            });

            checkboxes = checkboxes.filter(function (checkbox) {
                return checkbox.isConnected;
            });
            updateSelection();

            const list = document.querySelector(".notification-list");

            if (list && !list.querySelector(".notification-wrapper")) {
                if (bulkForm) {
                    bulkForm.hidden = true;
                }

                if (!list.querySelector(".empty-text")) {
                    const message = document.createElement("p");
                    message.className = "empty-text";
                    message.textContent =
                        "この条件に一致する要対応の通知はありません。";
                    list.appendChild(message);
                }
            }
        }
    );

    document.addEventListener("dkss:notification-item-updated", function (event) {
        const result = event.detail;
        const id = result?.notification_id;

        if (
            Number.isInteger(id) && id > 0 &&
            (result.action === "delete" || result.action === "undo-delete") &&
            Number.isInteger(result.inbox_count) && result.inbox_count >= 0
        ) {
            const count = document.getElementById("notificationInboxTabCount");
            if (count) count.textContent = String(result.inbox_count);
        }
        if (!Number.isInteger(id) || id <= 0) return;

        const deleting = result?.action === "delete" &&
            typeof result.deleted_at === "string" && result.deleted_at.length > 0;
        const restoring = result?.action === "undo-delete" &&
            result.deleted_at === null;

        if (restoring) {
            if (document.querySelector(".notification-list")) {
                saveScrollPosition();
                window.location.reload();
            }
            return;
        }
        if (!deleting && (result?.action !== "read" || result.read !== true)) return;

        const row = document.querySelector(
            '.notification-wrapper[data-notification-id="' + id + '"]'
        );
        if (!row) return;

        if (!deleting) {
            row.querySelector(".notification-item")?.classList.remove("unread");
            const label = row.querySelector(".js-notification-read-label");
            if (label) label.textContent = "既読";

            const toggle = row.querySelector(".js-notification-read-toggle");
            if (toggle) {
                toggle.value = "unread";
                toggle.textContent = "未読に戻す";
            }

            const detail = document.querySelector(
                '.dkss-notification-detail[data-notification-id="' + id + '"]'
            );
            const badge = detail?.querySelector(".nd-read");
            if (badge) badge.textContent = "既読";
        }

        if (!deleting && scrollState[1] !== "unread") return;

        const checkbox = row.querySelector(".js-notification-select");
        if (checkbox) {
            checkbox.checked = false;
            checkbox.disabled = true;
        }
        row.remove();
        checkboxes = checkboxes.filter(checkbox => checkbox.isConnected);
        updateSelection();

        const list = document.querySelector(".notification-list");
        list?.querySelectorAll(".notification-date-heading").forEach(heading => {
            let next = heading.nextElementSibling;
            let hasRows = false;
            while (next && !next.classList.contains("notification-date-heading")) {
                if (next.classList.contains("notification-wrapper")) hasRows = true;
                next = next.nextElementSibling;
            }
            if (hasRows) return;
            if (heading.querySelector("#notificationSort")) {
                const button = heading.querySelector(".notification-date-toggle");
                if (button) button.style.display = "none";
            } else {
                heading.remove();
            }
        });

        if (list && !list.querySelector(".notification-wrapper")) {
            if (bulkForm) bulkForm.hidden = true;
            if (!list.querySelector(".empty-text")) {
                const message = document.createElement("p");
                message.className = "empty-text";
                message.textContent = scrollState[1] === "unread"
                    ? "未読の通知はありません。"
                    : scrollState[1] === "action"
                        ? "この条件に一致する要対応の通知はありません。"
                        : "この条件に一致する通知はありません。";
                list.appendChild(message);
            }
        }
    });

    updateSelection();
    restoreScrollPosition();
});

document.addEventListener("DOMContentLoaded", function () {
    const layout = document.getElementById("notificationLayout");
    const pane = document.getElementById("notificationDetailPane");

    if (!layout || !pane) return;

    const placeholder = pane.innerHTML;
    let controller = null;
    let generation = 0;
    let activeLink = null;
    let listScrollY = 0;

    document.addEventListener("dkss:notification-item-updated", function (event) {
        const result = event.detail;
        if (
            result?.action !== "delete" ||
            typeof result.deleted_at !== "string" ||
            !result.deleted_at ||
            !Number.isInteger(result.notification_id) || result.notification_id <= 0
        ) return;

        const activeId = Number(
            activeLink?.closest(".notification-wrapper")?.dataset.notificationId ||
            pane.querySelector(".dkss-notification-detail")?.dataset.notificationId
        );
        if (activeId !== result.notification_id) return;
        activeLink = null;
        closeDetail();
    });

    function closeDetail() {
        generation++;
        controller?.abort();
        controller = null;

        layout.classList.remove("is-detail-open");
        pane.innerHTML = placeholder;
        pane.setAttribute("aria-busy", "false");

        layout.querySelectorAll(".is-detail-selected").forEach(row => {
            row.classList.remove("is-detail-selected");
        });

        activeLink?.focus({ preventScroll: true });

        if (matchMedia("(max-width: 1100px)").matches) {
            window.scrollTo({
                top: listScrollY,
                behavior: "instant"
            });
        }
    }

    document.addEventListener("click", async function (event) {
        const link = event.target.closest(
            "#notificationListPane .notification-item"
        );

        if (
            !link || event.defaultPrevented || event.button !== 0 ||
            event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
        ) return;

        const row = link.closest(".notification-wrapper");
        const id = Number(row?.dataset.notificationId);

        if (!Number.isInteger(id) || id <= 0) return;

        event.preventDefault();

        if (!layout.classList.contains("is-detail-open")) {
            listScrollY = window.scrollY;
            layout.dataset.listScrollY = String(listScrollY);
        }

        activeLink = link;
        controller?.abort();
        controller = new AbortController();

        const requestController = controller;
        const version = ++generation;
        const url = new URL(link.href);
        url.searchParams.set("panel", "1");

        layout.classList.add("is-detail-open");
        pane.setAttribute("aria-busy", "true");
        pane.innerHTML = `
            <div class="notification-detail-placeholder">
                <button type="button" class="nd-close"
                        aria-label="通知一覧へ戻る">×</button>
                <p role="status">読み込み中…</p>
            </div>
        `;

        try {
            const response = await fetch(url, {
                credentials: "same-origin",
                cache: "no-store",
                headers: { Accept: "application/json" },
                signal: requestController.signal
            });

            if (!response.ok || response.redirected) {
                throw new Error("detail");
            }

            const data = await response.json();

            if (version !== generation) return;

            if (
                data.notification_id !== id ||
                typeof data.html !== "string"
            ) {
                throw new Error("detail");
            }

            const parsed = new DOMParser().parseFromString(
                data.html, "text/html"
            );
            const detail = parsed.querySelector(
                ".dkss-notification-detail"
            );

            if (!detail || !detail.querySelector(".nd-message")) {
                throw new Error("detail");
            }

            detail.querySelectorAll(".mention-display").forEach(display => {
                renderMentionValue(display, display.dataset.value || "");
            });

            detail.querySelector(".nd-primary")
                ?.classList.add("js-notification-open");

            detail.dataset.notificationId = String(id);
            pane.replaceChildren(document.importNode(detail, true));
            pane.setAttribute("aria-busy", "false");

            layout.querySelectorAll(".is-detail-selected").forEach(item => {
                item.classList.remove("is-detail-selected");
            });
            row.classList.add("is-detail-selected");

            if (matchMedia("(max-width: 1100px)").matches) {
                pane.scrollIntoView({
                    block: "start",
                    behavior: "instant"
                });
            }

            pane.querySelector(".nd-close")
                ?.focus({ preventScroll: true });

            await new Promise(resolve => requestAnimationFrame(resolve));

            if (
                version !== generation ||
                data.read || data.deleted ||
                document.visibilityState === "hidden"
            ) return;

            try {
                const readResponse = await fetch(
                    "/api/notifications/" + id + "/read",
                    {
                        method: "POST",
                        credentials: "same-origin",
                        cache: "no-store",
                        headers: {
                            Accept: "application/json",
                            "X-CSRFToken": document.querySelector(
                                'meta[name="csrf-token"]'
                            )?.content || ""
                        }
                    }
                );

                if (!readResponse.ok || readResponse.redirected) {
                    throw new Error("read");
                }

                const result = await readResponse.json();

                if (
                    result.notification_id !== id ||
                    result.read !== true ||
                    !Number.isInteger(result.unread_count) ||
                    result.unread_count < 0
                ) {
                    throw new Error("read");
                }

                document.dispatchEvent(new CustomEvent(
                    "dkss:notifications-changed",
                    { detail: result }
                ));
                document.dispatchEvent(new CustomEvent(
                    "dkss:notification-item-updated",
                    { detail: { ...result, action: "read" } }
                ));

                try {
                    localStorage.setItem(
                        "dkss-notifications-changed",
                        Date.now() + ":" + Math.random()
                    );
                } catch (error) {}
            } catch (error) {
                showCommonError(
                    "通知は表示できましたが、既読にできませんでした。もう一度通知を開いてください。",
                    "",
                    false
                );
            }
        } catch (error) {
            if (
                error.name === "AbortError" ||
                version !== generation
            ) return;

            closeDetail();
            showCommonError(
                "通知を開けませんでした。もう一度お試しください。"
            );
        } finally {
            if (version === generation) {
                pane.setAttribute("aria-busy", "false");
            }
        }
    });

    pane.addEventListener("click", function (event) {
        if (event.target.closest(".nd-close")) {
            event.preventDefault();
            closeDetail();
        }
    });

    document.addEventListener(
        "dkss:notification-workflow-updated",
        function (event) {
            const detail = pane.querySelector(".dkss-notification-detail");
            const id = detail?.dataset.notificationId;
            const state = event.detail?.workflowStates?.[id];
            const badge = detail?.querySelector(".nd-workflow");

            if (
                !badge || !state ||
                typeof state.workflow_label !== "string" ||
                typeof state.requires_action !== "boolean"
            ) return;

            badge.textContent = state.workflow_label;
            badge.hidden = !state.workflow_label;
            badge.classList.remove("nd-pending", "nd-completed", "nd-ended");
            badge.classList.add(
                state.requires_action ? "nd-pending" :
                state.workflow_status === "completed" ?
                    "nd-completed" : "nd-ended"
            );

            const hint = detail.querySelector(".nd-hint");
            if (hint) hint.hidden = !state.requires_action;
        }
    );

    pane.addEventListener("submit", function (event) {
        const form = event.target;

        if (form.dataset.submitting === "true") {
            event.preventDefault();
            return;
        }

        form.dataset.submitting = "true";
    });

    document.addEventListener("keydown", function (event) {
        if (
            event.key === "Escape" &&
            layout.classList.contains("is-detail-open")
        ) {
            closeDetail();
        }
    });

    const selectedUrl = new URL(window.location.href);
    const selectedId = Number(
        selectedUrl.searchParams.get("notification")
    );

    if (Number.isInteger(selectedId) && selectedId > 0) {
        const selectedLink = layout.querySelector(
            '.notification-wrapper[data-notification-id="' +
            selectedId + '"] .notification-item'
        );

        if (selectedLink) {
            selectedUrl.searchParams.delete("notification");
            history.replaceState(
                history.state, "", selectedUrl.href
            );
            selectedLink.click();
        } else {
            showCommonError(
                "選んだ通知が見つかりません。一覧を更新してください。"
            );
        }
    }
});

document.addEventListener("click", function (event) {
    const currentMenu = event.target.closest(".notification-row-menu");

    document.querySelectorAll(
        ".notification-row-menu[open]"
    ).forEach(function (menu) {
        if (menu !== currentMenu) {
            menu.open = false;
        }
    });
});