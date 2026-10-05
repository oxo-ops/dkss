document.addEventListener("DOMContentLoaded", function () {
    const responsePanel = document.getElementById("vehicle-inspection-response");
    const flowPanel = document.querySelector(".vehicle-flow-panel");

    if (responsePanel?.querySelector(".js-vehicle-judgment-completed")) {
        responsePanel.querySelectorAll(".vehicle-judgment-heading")
            .forEach(function (heading) {
                const title = heading.querySelector("h4");
                if (title?.textContent.trim() === "運行判断へ進むには") {
                    heading.hidden = true;
                }
            });
    }

    if (responsePanel && flowPanel) {
        const checks = document.querySelector(".vehicle-check-table-scroll");
        if (checks) checks.id = "vehicle-flow-checks";

        const overview = responsePanel.querySelector("h3");
        if (overview) overview.id = "vehicle-flow-overview";

        const judgmentTarget =
            responsePanel.querySelector(".js-vehicle-judgment-completed")
            || responsePanel.querySelector(".js-vehicle-operation-judgment, .js-vehicle-operation-manager")
            || responsePanel.querySelector("h3 + p");

        if (judgmentTarget) {
            judgmentTarget.id = "vehicle-flow-judgment";
        }

        function showFlowTarget(hash) {
            if (!hash.startsWith("#vehicle-flow-")) return;

            const container = document.getElementById(hash.slice(1));
            if (!container) return;

            if (container.dataset.defectStatus === "解消") {
                const nextLink = Array.from(
                    flowPanel.querySelectorAll(".vehicle-flow-steps a")
                ).find(function (link) {
                    const url = new URL(link.href, window.location.href);
                    return /^#vehicle-flow-defect-\d+-\d+$/.test(url.hash)
                        && url.hash !== hash;
                });

                const destination = new URL(
                    nextLink ? nextLink.href : "#vehicle-flow-judgment",
                    window.location.href
                );

                const samePage =
                    destination.origin === window.location.origin
                    && destination.pathname === window.location.pathname
                    && destination.search === window.location.search;

                destination.searchParams.set("vehicle_notice", "resolved");
                sessionStorage.removeItem("vehicleChecklistReturnPosition");

                if (samePage) {
                    window.history.replaceState(null, "", destination.href);
                    showFlowTarget(destination.hash);
                } else {
                    window.location.assign(destination.href);
                }
                return;
            }

            const target =
                container.querySelector(".js-vehicle-inspection-repair")
                || container;

            let ancestor = target;
            while (ancestor) {
                if (ancestor.tagName === "DETAILS") {
                    ancestor.open = true;
                }
                ancestor = ancestor.parentElement;
            }

            document.querySelectorAll(".vehicle-flow-focus")
                .forEach(function (item) {
                    item.classList.remove("vehicle-flow-focus");
                });

            target.classList.add("vehicle-flow-focus");

            const savedUrl = new URL(window.location.href);

            if (savedUrl.searchParams.get("vehicle_notice") === "resolved") {
                document.querySelectorAll(".vehicle-response-notice")
                    .forEach(function (item) {
                        item.remove();
                    });

                const notice = document.createElement("p");
                notice.className = "vehicle-save-feedback vehicle-response-notice";
                notice.setAttribute("role", "status");
                notice.textContent = target.id === "vehicle-flow-judgment"
                    ? "通知の対象は対応済みです。運行判断の状況を表示しました。"
                    : "通知の対象は対応済みです。次の対応箇所を表示しました。";

                const noticeTarget =
                    target.closest(".vehicle-defect-workspace") || target;
                noticeTarget.before(notice);

                savedUrl.searchParams.delete("vehicle_notice");
                window.history.replaceState(null, "", savedUrl.href);
            }
            const savedKind = savedUrl.searchParams.get("vehicle_saved");
            const savedItem = savedUrl.searchParams.get("vehicle_saved_item") || "";
            const savedDate = savedUrl.searchParams.get("vehicle_saved_date") || "";

            if (
                ["repair", "recheck"].includes(savedKind)
                && /^\d+$/.test(savedItem)
            ) {
                document.querySelectorAll(".vehicle-save-feedback")
                    .forEach(function (item) {
                        item.remove();
                    });

                const feedback = document.createElement("p");
                feedback.className = "vehicle-save-feedback";
                feedback.setAttribute("role", "status");

                const dateText = /^\d{4}\/\d{1,2}\/\d{1,2}$/.test(savedDate)
                    ? savedDate + " " : "";
                const savedLabel = savedKind === "recheck"
                    ? "再確認結果" : "整備内容";

                feedback.textContent = dateText + "No." + savedItem
                    + "の" + savedLabel + "を保存しました。";

                const feedbackTarget =
                    target.closest(".vehicle-defect-workspace") || target;
                feedbackTarget.before(feedback);

                savedUrl.searchParams.delete("vehicle_saved");
                savedUrl.searchParams.delete("vehicle_saved_item");
                savedUrl.searchParams.delete("vehicle_saved_date");
                window.history.replaceState(null, "", savedUrl.href);
            }

            target.tabIndex = -1;
            target.focus({ preventScroll: true });
            target.scrollIntoView({
                block: "start",
                behavior: "instant"
            });

            const message = document.getElementById("vehicle-flow-message");
            if (message) {
                message.textContent = target.matches(".js-vehicle-judgment-completed")
                    ? "運行判断は登録済みです。保存した結果を表示しています。"
                    : target.matches(
                    ".js-vehicle-inspection-repair, .js-vehicle-operation-judgment"
                )
                    ? "入力欄を開きました。青枠の箇所で対応してください。"
                    : "青枠の箇所を表示しました。入力欄がない場合は閲覧のみです。";
            }
        }

        document.addEventListener("click", function (event) {
            const link = event.target.closest(".js-vehicle-flow-link");
            if (!link) return;

            const destination = new URL(link.href, window.location.href);

            if (
                destination.origin !== window.location.origin
                || destination.pathname !== window.location.pathname
                || destination.search !== window.location.search
            ) {
                return;
            }

            if (!document.getElementById(destination.hash.slice(1))) {
                return;
            }

            event.preventDefault();
            sessionStorage.removeItem("vehicleChecklistReturnPosition");
            window.history.replaceState(null, "", destination.href);
            showFlowTarget(destination.hash);
        });

        window.addEventListener("hashchange", function () {
            showFlowTarget(window.location.hash);
        });

        if (window.location.hash.startsWith("#vehicle-flow-")) {
            sessionStorage.removeItem("vehicleChecklistReturnPosition");

            const showAfterLoad = function () {
                requestAnimationFrame(function () {
                    requestAnimationFrame(function () {
                        showFlowTarget(window.location.hash);
                    });
                });
            };

            if (document.readyState === "complete") {
                showAfterLoad();
            } else {
                window.addEventListener("load", showAfterLoad, {
                    once: true
                });
            }
        }
    }
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

    document.querySelectorAll(".vehicle-approval-card .btn")
        .forEach(function (button) {
            button.classList.add("btn-outline");
        });

    if (window.location.hash === "#vehicle-inspection-response") {
        const target =
            document.getElementById("vehicle-inspection-response");

        if (target) {
            sessionStorage.removeItem("vehicleChecklistReturnPosition");

            const details = target.querySelector("details");
            if (details) {
                details.open = true;
            }

            const showTarget = function () {
                requestAnimationFrame(function () {
                    requestAnimationFrame(function () {
                        target.focus({ preventScroll: true });
                        target.scrollIntoView({
                            block: "start",
                            behavior: "instant"
                        });
                    });
                });
            };

            if (document.readyState === "complete") {
                showTarget();
            } else {
                window.addEventListener("load", showTarget, {
                    once: true
                });
            }
        }
    }

    document.querySelectorAll(
        ".js-vehicle-operation-judgment, .js-vehicle-inspection-repair"
    ).forEach(function (form) {
        form.addEventListener("submit", async function (event) {
            event.preventDefault();
            if (form.dataset.submitting === "1") {
                return;
            }

            form.dataset.submitting = "1";
            const button = form.querySelector('button[type="submit"]');
            if (button) {
                button.disabled = true;
            }
            clearCommonErrors();

            try {
                const response = await fetch(form.action, {
                    method: "POST",
                    headers: {"X-DKSS-Final-Submit": "1"},
                    body: new FormData(form)
                });

                if (!response.ok) {
                    if (response.headers.get("X-DKSS-Form-Errors") === "1") {
                        const data = await response.json();
                        (data.errors || []).forEach(function (error) {
                            showCommonError(error.message, error.field || "");
                        });
                        return;
                    }
                    throw new Error("HTTP " + response.status);
                }

                let redirectUrl;
                if ((response.headers.get("Content-Type") || "")
                    .includes("application/json")) {
                    const data = await response.json();
                    if (typeof data.redirect_url !== "string" || !data.redirect_url) {
                        throw new Error("保存結果を確認できません。");
                    }
                    redirectUrl = new URL(data.redirect_url, window.location.href);
                } else if (response.redirected) {
                    redirectUrl = new URL(response.url);
                } else {
                    throw new Error("保存結果を確認できません。");
                }
                if (redirectUrl.origin !== window.location.origin) {
                    throw new Error("保存結果の移動先を確認できません。");
                }

                sessionStorage.removeItem("vehicleChecklistReturnPosition");
                if (redirectUrl.pathname === window.location.pathname
                    && redirectUrl.search === window.location.search) {
                    window.history.replaceState(null, "", redirectUrl.href);
                    window.location.reload();
                } else {
                    window.location.assign(redirectUrl.href);
                }
            } catch (error) {
                showCommonError(
                    "保存できませんでした。通信状態を確認して、もう一度操作してください。"
                );
            } finally {
                delete form.dataset.submitting;
                if (button) {
                    button.disabled = false;
                }
            }
        });
    });

    document.querySelectorAll(".js-vehicle-inspection-repair")
        .forEach(function (form) {
            const status = form.querySelector('[name="repair_status"]');
            const button = form.querySelector('button[type="submit"]');
            const heading = form.querySelector(".vehicle-defect-form-heading");
            if (!status || !button || !heading) return;

            const help = document.createElement("p");
            help.setAttribute("aria-live", "polite");
            heading.appendChild(help);

            function updateRepairAction() {
                const completed = status.value === "再確認待ち";
                help.textContent = completed
                    ? "整備が完了したら保存してください。保存後は、異常が解消したか再確認します。"
                    : "作業途中の内容を保存できます。整備が終わったら「整備完了（再確認待ち）」を選んで保存してください。";
                button.textContent = completed
                    ? "整備完了を記録して再確認へ"
                    : "作業途中の内容を保存";
            }

            status.addEventListener("change", updateRepairAction);
            updateRepairAction();
        });

    document.querySelectorAll(".js-vehicle-inspection-repair")
        .forEach(function (form) {
            const result = form.querySelector('[name="recheck_result"]');
            const button = form.querySelector('button[type="submit"]');
            const heading = form.querySelector(".vehicle-defect-form-heading");
            if (!result || !button || !heading) return;

            const help = document.createElement("p");
            help.setAttribute("aria-live", "polite");
            heading.appendChild(help);

            function updateRecheckAction() {
                if (result.value === "異常なし") {
                    help.textContent = "この不具合を解消として記録します。ほかの不具合への対応が済んだら、整備管理者が運行可否を判断します。";
                    button.textContent = "不具合の解消を記録";
                } else if (result.value === "異常あり") {
                    help.textContent = "この不具合を対応待ちに戻します。再度、整備が必要です。";
                    button.textContent = "再整備が必要として記録";
                } else {
                    help.textContent = "整備後に対象箇所を確認し、結果・確認内容・実施日時を入力してください。";
                    button.textContent = "再確認結果を保存";
                }
            }

            result.addEventListener("change", updateRecheckAction);
            updateRecheckAction();
        });

    document.querySelectorAll(
        ".js-vehicle-inspection-repair, .js-vehicle-operation-judgment, .js-vehicle-operation-manager"
    ).forEach(function (form) {
        const heading = form.querySelector(
            ".vehicle-defect-form-heading, .vehicle-judgment-heading"
        ) || form;
        const help = heading.querySelector('p[aria-live="polite"]')
            || document.createElement("p");
        help.classList.add("vehicle-next-action");
        help.setAttribute("aria-live", "polite");
        heading.prepend(help);

        function updateNextAction() {
            form.querySelectorAll(".vehicle-next-input").forEach(function (item) {
                item.classList.remove("vehicle-next-input");
            });

            const status = form.querySelector('[name="repair_status"]');
            const result = form.querySelector('[name="recheck_result"]');
            const button = form.querySelector('button[type="submit"]');
            let next = form.querySelector(":invalid") || button;
            let message;

            if (status && status.value !== "再確認待ち") {
                next = status;
                message = "次にする操作：整備が終わったら、青枠の「整備状況」を「整備完了（再確認待ち）」に変更して保存してください。作業途中なら、途中保存できます。";
            } else if (status) {
                message = next === button
                    ? "次にする操作：青枠の「整備完了を記録して再確認へ」を押してください。再確認の依頼通知が送られます。"
                    : "次にする操作：青枠の未入力欄を入力し、「整備完了を記録して再確認へ」を押してください。";
            } else if (result) {
                if (!result.value) {
                    next = result;
                    message = "次にする操作：整備後の状態を確認し、青枠の「再確認結果」を選択してください。";
                } else if (next !== button) {
                    message = "次にする操作：青枠の確認内容・実施日時を入力して保存してください。異常なしは解消、異常ありは再整備として記録します。";
                } else {
                    message = result.value === "異常なし"
                        ? "次にする操作：青枠の「不具合の解消を記録」を押してください。残りの対応が0件になったら、整備管理者が運行判断を登録します。"
                        : "次にする操作：青枠の「再整備が必要として記録」を押してください。この不具合を再び整備する段階へ戻します。";
                }
            } else if (form.matches(".js-vehicle-operation-manager")) {
                message = next === button
                    ? "次にする操作：青枠の「整備管理者を設定」を押してください。選んだ人へ運行判断の依頼を通知します。"
                    : "次にする操作：青枠の選択欄で、運行判断を行う整備管理者を選んでください。";
            } else {
                const instructions = {
                    authority_role: "判断者の役割を選択してください。",
                    authority_confirmed: "運行判断を行う権限の確認にチェックしてください。",
                    decision: "運行可・運行不可・判断保留を選択してください。",
                    reason: "判断理由を入力してください。",
                    checks_confirmed: "点検記録の確認にチェックしてください。"
                };
                message = next === button
                    ? "次にする操作：青枠の保存ボタンを押して、点検確認・運行判断を記録してください。"
                    : "次にする操作：青枠で" + (
                        instructions[next.name]
                        || "必要な内容を入力・確認してください。"
                    );
            }

            help.textContent = message;

            if (next) {
                const target = next.closest('[role="group"]')
                    || next.closest(".vehicle-judgment-confirmation")
                    || next;
                target.classList.add("vehicle-next-input");
            }
        }

        form.addEventListener("input", updateNextAction);
        form.addEventListener("change", updateNextAction);
        updateNextAction();
    });

    document.querySelectorAll(".js-vehicle-operation-judgment")
        .forEach(function (form) {
            const reason = form.querySelector('[name="reason"]');
            const checks = form.querySelector('[name="checks_confirmed"]');
            const checksGroup = form.querySelector("#vehicle_judgment_checks");
            const help = form.querySelector("#vehicle_judgment_reason_help");

            function updateJudgmentFields() {
                const choice = form.querySelector('[name="decision"]:checked');
                const decision = choice ? choice.value : "";
                const allowed = decision === "運行可";

                if (reason) {
                    reason.required = ["運行不可", "判定保留"].includes(decision);
                }
                if (checksGroup) {
                    checksGroup.hidden = !allowed;
                }
                if (checks) {
                    checks.required = allowed;
                    checks.disabled = !allowed;
                    if (!allowed) checks.checked = false;
                }
                if (help) {
                    help.textContent = decision === "運行可"
                        ? "点検・整備・再確認の結果を確認して判断します。下の確認事項にチェックしてください。理由は任意です。"
                        : decision === "運行不可"
                            ? "運行できない理由を入力してください。この車両を運行不可として記録します。"
                            : decision === "判定保留"
                                ? "判断を保留する理由を入力してください。運行可の判断はまだ出ていない状態として記録します。"
                                : "整備管理者が点検結果と不具合の対応状況を確認し、運行可否を選んでください。";
                }
                const button = form.querySelector('button[type="submit"]');
                if (button) {
                    button.textContent = decision === "運行可"
                        ? "点検確認・運行可を記録"
                        : decision === "運行不可"
                            ? "点検確認・運行不可を記録"
                            : decision === "判定保留"
                                ? "点検確認・判断保留を記録"
                                : "確認・判断を保存";
                }
            }

            form.querySelectorAll('[name="decision"]')
                .forEach(function (input) {
                    input.addEventListener("change", updateJudgmentFields);
                });

            updateJudgmentFields();
        });

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

    const approvalUserSearchInputs =
        document.querySelectorAll(
            ".approval-user-search"
        );

    approvalUserSearchInputs.forEach(
        function (searchInput) {
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
                    searchInput.dispatchEvent(
                        new CustomEvent(
                            "approval-candidates-loaded",
                            {
                                detail: {
                                    users:
                                        data.users || []
                                }
                            }
                        )
                    );
                })
                .catch(function () {
                    showCommonError(
                        "承認者候補を取得できませんでした。"
                    );
                });
        }
    );


    function addApprovalUser(
        approvalIndex,
        user
    ) {
        const selectedArea =
            document.querySelector(
                '.selected-approval-users[data-approval-index="' +
                approvalIndex +
                '"]'
            );

        if (!selectedArea || !user.username) {
            return;
        }

        if (
            selectedArea.querySelector(
                '[data-username="' +
                CSS.escape(user.username) +
                '"]'
            )
        ) {
            return;
        }

        const tag =
            document.createElement("span");

        tag.className = "selected-vehicle-tag";
        tag.dataset.username = user.username;

        tag.appendChild(
            document.createTextNode(
                user.name || user.username
            )
        );

        if (!user.name) {
            fetch(
                "/api/mention-users?exact_username=1&q="
                + encodeURIComponent(user.username)
            )
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error("HTTP " + response.status);
                    }
                    return response.json();
                })
                .then(function (data) {
                    const matchedUser = (data.users || []).find(
                        function (entry) {
                            return entry.username === user.username;
                        }
                    );
                    if (matchedUser?.name && tag.isConnected) {
                        tag.firstChild.textContent = matchedUser.name;
                    }
                })
                .catch(function () {
                    showCommonError("選択済みのユーザー名を取得できませんでした。");
                });
        }

        const remove =
            document.createElement("button");

        remove.type = "button";
        remove.className = "tag-remove-btn";
        remove.textContent = "×";

        const hidden =
            document.createElement("input");

        hidden.type = "hidden";
        hidden.name =
            "approval_notify_users_" +
            approvalIndex;
        hidden.value = user.username;

        remove.addEventListener(
            "click",
            function () {
                tag.remove();

                const searchInput =
                    document.querySelector(
                        '.approval-user-search[data-approval-index="' +
                        approvalIndex +
                        '"]'
                    );

                if (searchInput) {
                    searchInput.dispatchEvent(
                        new Event(
                            "approval-reload-candidates"
                        )
                    );
                }
            }
        );

        tag.appendChild(remove);
        tag.appendChild(hidden);
        selectedArea.appendChild(tag);

        const selectedHeading =
            document.querySelector(
                '.selected-approval-users-heading[data-approval-index="' +
                approvalIndex +
                '"]'
            );

        if (selectedHeading) {
            selectedHeading.textContent =
                "選択済み（" +
                selectedArea.querySelectorAll(
                    'input[name^="approval_notify_users_"]'
                ).length +
                "人）";
        }

        remove.addEventListener(
            "click",
            function () {
                if (selectedHeading) {
                    selectedHeading.textContent =
                        "選択済み（" +
                        selectedArea.querySelectorAll(
                            'input[name^="approval_notify_users_"]'
                        ).length +
                        "人）";
                }
            }
        );
    }

    document.querySelectorAll(
        ".selected-approval-users[data-saved-usernames]"
    ).forEach(function (selectedArea) {
        let usernames;

        try {
            usernames = JSON.parse(
                selectedArea.dataset.savedUsernames || "[]"
            );
        } catch (error) {
            showCommonError(
                "保存済みの承認者候補を読み込めませんでした。"
            );
            return;
        }

        if (!Array.isArray(usernames)) {
            showCommonError(
                "保存済みの承認者候補が不正です。"
            );
            return;
        }

        usernames.forEach(function (username) {
            if (
                typeof username !== "string"
                || !username.trim()
            ) {
                return;
            }

            addApprovalUser(
                selectedArea.dataset.approvalIndex,
                { username: username }
            );
        });
    });

    approvalUserSearchInputs.forEach(
        function (searchInput) {
            searchInput.addEventListener(
                "approval-reload-candidates",
                function () {
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
                            searchInput.dispatchEvent(
                                new CustomEvent(
                                    "approval-candidates-loaded",
                                    {
                                        detail: {
                                            users:
                                                data.users || []
                                        }
                                    }
                                )
                            );
                        })
                        .catch(function () {
                            showCommonError(
                                "承認者候補を取得できませんでした。"
                            );
                        });
                }
            );

            searchInput.addEventListener(
                "approval-candidates-loaded",
                function (event) {
                    const approvalIndex =
                        searchInput.dataset.approvalIndex;

                    const candidateArea =
                        document.querySelector(
                            '.approval-candidate-users[data-approval-index="' +
                            approvalIndex +
                            '"]'
                        );

                    if (!candidateArea) {
                        return;
                    }

                    candidateArea.replaceChildren();

                    (event.detail.users || [])
                        .forEach(function (user) {
                            const selectedArea =
                                document.querySelector(
                                    '.selected-approval-users[data-approval-index="' +
                                    approvalIndex +
                                    '"]'
                                );

                            if (
                                selectedArea &&
                                selectedArea.querySelector(
                                    '[data-username="' +
                                    CSS.escape(user.username) +
                                    '"]'
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

                            button.textContent =
                                user.name ||
                                user.username;

                            button.addEventListener(
                                "click",
                                function () {
                                    addApprovalUser(
                                        approvalIndex,
                                        user
                                    );

                                    button.remove();
                                }
                            );

                            candidateArea.appendChild(
                                button
                            );
                        });
                }
            );
        }
    );


    approvalUserSearchInputs.forEach(
        function (searchInput) {
            const approvalIndex =
                searchInput.dataset.approvalIndex;

            const searchResults =
                document.querySelector(
                    '.approval-user-search-results[data-approval-index="' +
                    approvalIndex +
                    '"]'
                );

            if (!searchResults) {
                return;
            }

            let approvalSearchTimer = null;

            searchInput.addEventListener(
                "input",
                function () {
                    clearTimeout(
                        approvalSearchTimer
                    );

                    const keyword =
                        searchInput.value.trim();

                    searchResults.replaceChildren();

                    if (!keyword) {
                        searchResults.classList.add(
                            "is-hidden"
                        );
                        return;
                    }

                    approvalSearchTimer =
                        setTimeout(
                            async function () {
                                try {
                                    const response =
                                        await fetch(
                                            "/api/mention-users?approval_scope=" +
                                            (searchInput.dataset.allowGeneral === "1"
                                                ? "admin_user"
                                                : "admin") +
                                            "&q=" +
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

                                    const data =
                                        await response.json();

                                    const allowGeneral =
                                        searchInput.dataset.allowGeneral ===
                                        "1";

                                    const users =
                                        (data.users || []).filter(
                                            function (user) {
                                                return (
                                                    user.role === "admin"
                                                    || (
                                                        allowGeneral
                                                        && user.role === "user"
                                                    )
                                                );
                                            }
                                        );

                                    searchResults.replaceChildren();

                                    users.forEach(
                                        function (user) {
                                            const button =
                                                document.createElement(
                                                    "button"
                                                );

                                            button.type = "button";
                                            button.className =
                                                "vehicle-select-item";

                                            button.textContent =
                                                user.name ||
                                                user.username;

                                            button.addEventListener(
                                                "click",
                                                function () {
                                                    addApprovalUser(
                                                        approvalIndex,
                                                        user
                                                    );

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
                                        }
                                    );

                                    searchResults.classList.toggle(
                                        "is-hidden",
                                        users.length === 0
                                    );
                                } catch (error) {
                                    searchResults.replaceChildren();
                                    searchResults.classList.add(
                                        "is-hidden"
                                    );

                                    showCommonError(
                                        "承認者を検索できませんでした。"
                                    );
                                }
                            },
                            300
                        );
                }
            );
        }
    );


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
            async function (event) {
                event.preventDefault();

                const focusedInput = document.activeElement;

                if (
                    focusedInput
                    && focusedInput.matches(
                        ".js-inline-check-input"
                    )
                ) {
                    focusedInput.blur();
                }

                let pendingSave;

                do {
                    pendingSave = inlineSaveQueue;
                    await pendingSave;
                } while (pendingSave !== inlineSaveQueue);

                if (failedInlineForms.size > 0) {
                    showCommonError(
                        "保存に失敗した項目があります。該当項目を再保存してから、点検完了してください。"
                    );
                    return;
                }

                const checkForms = Array.from(
                    document.querySelectorAll(
                        ".inline-check-form"
                    )
                );

                const unansweredForms = checkForms.filter(
                    function (form) {
                        const value = new FormData(form).get(
                            "value"
                        );

                        return value === null
                            || !String(value).trim();
                    }
                );

                const missingRequiredForms = unansweredForms.filter(
                    function (form) {
                        return form.dataset.answerRequired === "1";
                    }
                );

                clearCommonErrors();

                if (missingRequiredForms.length > 0) {
                    missingRequiredForms.forEach(function (form, index) {
                        const itemNo = new FormData(form).get("item_no");
                        const content = new FormData(form).get("content") || "";
                        showCommonError(
                            "必須項目が未回答です。" + (content ? "：" + content : ""),
                            "answer_" + itemNo,
                            index === 0
                        );
                    });
                    return;
                }

                const unansweredCount = unansweredForms.length;
                const confirmationMessage =
                    checkForms.length > 0 && unansweredCount === checkForms.length
                        ? "すべての点検項目が未回答です。全件未回答のまま点検を完了しますか？"
                        : unansweredCount > 0
                            ? "任意項目に未回答が"
                                + unansweredCount
                                + "件あります。未回答のまま点検を完了しますか？"
                            : "この日の点検を完了しますか？";

                if (
                    !window.confirm(
                        confirmationMessage
                    )
                ) {
                    return;
                }

                if (completeForm.dataset.submitting === "1") {
                    return;
                }

                completeForm.dataset.submitting = "1";

                clearCommonErrors();

                try {
                    const response =
                        await fetch(
                            completeForm.action,
                            {
                                method: "POST",
                                headers: {
                                    "X-DKSS-Final-Submit":
                                        "1"
                                },
                                body:
                                    new FormData(
                                        completeForm
                                    )
                            }
                        );

                    if (!response.ok) {
                        if (
                            response.headers.get(
                                "X-DKSS-Form-Errors"
                            ) === "1"
                        ) {
                            const data =
                                await response.json();

                            (data.errors || []).forEach(
                                function (error) {
                                    showCommonError(
                                        error.message,
                                        error.field || ""
                                    );
                                }
                            );

                            return;
                        }

                        throw new Error(
                            "HTTP " +
                            response.status
                        );
                    }

                    const contentType = response.headers.get("Content-Type") || "";
                    if (contentType.includes("application/json")) {
                        const data = await response.json();
                        if (data.success && data.redirect_url) {
                            sessionStorage.removeItem("vehicleChecklistReturnPosition");
                            window.location.assign(data.redirect_url);
                            return;
                        }
                        throw new Error("点検完了後の移動先を取得できませんでした。");
                    }

                    if (response.redirected) {
                        window.location.assign(response.url);
                        return;
                    }

                    window.location.reload();

                } catch (error) {
                    console.error(
                        "点検完了エラー:",
                        error
                    );

                    showCommonError(
                        "点検を完了できませんでした。通信状態を確認して、もう一度操作してください。"
                    );
                } finally {
                    delete completeForm.dataset.submitting;
                }
            }
        );
    }


    /* =========================
       承認差し戻し
    ========================= */

    const vehicleRejectModal =
        document.getElementById(
            "vehicleRejectModal"
        );

    const vehicleRejectForm =
        document.getElementById(
            "vehicleRejectForm"
        );

    const vehicleRejectReason =
        document.getElementById(
            "vehicleRejectReason"
        );

    const vehicleRejectCancel =
        document.getElementById(
            "vehicleRejectCancel"
        );

    document.querySelectorAll(
        ".js-vehicle-checklist-reject"
    ).forEach(function (button) {
        button.addEventListener(
            "click",
            function () {
                if (
                    !vehicleRejectModal
                    || !vehicleRejectForm
                ) {
                    return;
                }

                const resultIndex =
                    button.dataset.resultIndex;

                vehicleRejectForm.action =
                    "/vehicle/checklist-results/"
                    + resultIndex
                    + "/reject";

                if (vehicleRejectReason) {
                    vehicleRejectReason.value = "";
                }

                vehicleRejectModal.classList.remove(
                    "is-hidden"
                );

                if (vehicleRejectReason) {
                    vehicleRejectReason.focus();
                }
            }
        );
    });

    if (vehicleRejectCancel) {
        vehicleRejectCancel.addEventListener(
            "click",
            function () {
                vehicleRejectModal.classList.add(
                    "is-hidden"
                );
            }
        );
    }

    if (vehicleRejectForm) {
        vehicleRejectForm.addEventListener(
            "submit",
            async function (event) {
                event.preventDefault();

                clearCommonErrors();

                try {
                    const response =
                        await fetch(
                            vehicleRejectForm.action,
                            {
                                method: "POST",
                                headers: {
                                    "X-DKSS-Validation-Only":
                                        "1"
                                },
                                body:
                                    new FormData(
                                        vehicleRejectForm
                                    )
                            }
                        );

                    if (!response.ok) {
                        if (
                            response.headers.get(
                                "X-DKSS-Form-Errors"
                            ) === "1"
                        ) {
                            const data =
                                await response.json();

                            (data.errors || []).forEach(
                                function (error) {
                                    showCommonError(
                                        error.message,
                                        error.field || ""
                                    );
                                }
                            );

                            return;
                        }

                        throw new Error(
                            "HTTP " +
                            response.status
                        );
                    }

                    if (response.redirected) {
                        window.location.assign(
                            response.url
                        );
                        return;
                    }

                    window.location.reload();

                } catch (error) {
                    console.error(
                        "差し戻しエラー:",
                        error
                    );

                    showCommonError(
                        "差し戻しできませんでした。通信状態を確認して、もう一度操作してください。",
                        "vehicleRejectReason"
                    );
                }
            }
        );
    }

    if (vehicleRejectModal) {
        vehicleRejectModal.addEventListener(
            "click",
            function (event) {
                if (event.target === vehicleRejectModal) {
                    vehicleRejectModal.classList.add(
                        "is-hidden"
                    );
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


    document.querySelectorAll(".js-vehicle-defect-files").forEach(function (area) {
        renderFiles(
            area.id,
            area.dataset.files || "",
            "初回報告の添付"
        );
    });

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

        const detailRow = button.closest("tr");

        const canEdit =
            Number(day) === Number(activeDay)
            && Boolean(
                detailRow
                && detailRow.querySelector(
                    ".inline-check-form"
                )
            );

        if (commentEditor) {
            commentEditor.contentEditable =
                canEdit ? "true" : "false";
        }

        document.querySelectorAll(
            "#detailModal .js-detail-file-input"
        ).forEach(function (input) {
            input.value = "";
            input.disabled = !canEdit;

            const uploadLabel = input.closest("label");

            if (uploadLabel) {
                uploadLabel.hidden = !canEdit;
            }
        });

        const detailSaveButton = document.querySelector(
            '#detailModal button[type="submit"]'
        );

        if (detailSaveButton) {
            detailSaveButton.disabled = !canEdit;
            detailSaveButton.hidden = !canEdit;
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

        clearCommonErrors();

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
            async function (event) {
                event.preventDefault();

                const saveButton = detailFileForm.querySelector(
                    'button[type="submit"]'
                );

                if (
                    !saveButton
                    || saveButton.disabled
                    || saveButton.hidden
                ) {
                    return;
                }

                clearCommonErrors();

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
                    showCommonError(
                        "写真・動画・ファイルの合計を1GB以下にしてください。"
                    );

                    return;
                }

                try {
                    const response =
                        await fetch(
                            detailFileForm.action,
                            {
                                method: "POST",
                                headers: {
                                    "X-DKSS-Validation-Only":
                                        "1"
                                },
                                body:
                                    new FormData(
                                        detailFileForm
                                    )
                            }
                        );

                    if (!response.ok) {
                        if (
                            response.headers.get(
                                "X-DKSS-Form-Errors"
                            ) === "1"
                        ) {
                            const data =
                                await response.json();

                            (data.errors || []).forEach(
                                function (error) {
                                    showCommonError(
                                        error.message,
                                        error.field || ""
                                    );
                                }
                            );

                            return;
                        }

                        throw new Error(
                            "HTTP " +
                            response.status
                        );
                    }

                    if (response.redirected) {
                        window.location.assign(
                            response.url
                        );
                        return;
                    }

                    window.location.reload();

                } catch (error) {
                    console.error(
                        "詳細保存エラー:",
                        error
                    );

                    showCommonError(
                        "保存できませんでした。通信状態を確認して、もう一度操作してください。"
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


    let inlineSaveQueue = Promise.resolve();
    const failedInlineForms = new Set();

    function saveInlineCheck(input) {
        const form = input.form;

        if (!form) {
            return;
        }

        const formData = new FormData(form);

        input.blur();
        restoreChecklistPosition();

        inlineSaveQueue = inlineSaveQueue.then(
            async function () {
                try {
                    const response = await fetch(
                        form.action,
                        {
                            method: "POST",
                            headers: {
                                "X-DKSS-Validation-Only": "1"
                            },
                            body: formData
                        }
                    );

                    if (!response.ok) {
                        failedInlineForms.add(form);

                        if (
                            response.headers.get(
                                "X-DKSS-Form-Errors"
                            ) === "1"
                        ) {
                            const data = await response.json();

                            clearCommonErrors();

                            (data.errors || []).forEach(
                                function (error) {
                                    showCommonError(
                                        error.message,
                                        error.field || ""
                                    );
                                }
                            );

                            return;
                        }

                        throw new Error(
                            "HTTP " + response.status
                        );
                    }

                    failedInlineForms.delete(form);
                } catch (error) {
                    failedInlineForms.add(form);

                    showCommonError(
                        "点検結果を保存できませんでした。通信状態を確認して、もう一度入力してください。"
                    );
                }
            }
        );

        return inlineSaveQueue;
    }

    const checklistChoiceWasChecked =
        new WeakMap();

    document.addEventListener(
        "pointerdown",
        function (event) {
            const choice =
                event.target.closest(
                    ".check-choice-button"
                );

            if (!choice) {
                return;
            }

            const input =
                choice.querySelector(
                    ".js-inline-check-input"
                );

            checklistChoiceWasChecked.set(
                choice,
                Boolean(
                    input &&
                    input.type === "radio" &&
                    input.checked
                )
            );

            if (
                input &&
                input.classList.contains(
                    "js-inline-check-input"
                )
            ) {
                rememberChecklistPosition();
            }
        },
        true
    );

    document.addEventListener(
        "click",
        function (event) {
            const choice =
                event.target.closest(
                    ".check-choice-button"
                );

            if (!choice) {
                return;
            }

            const input =
                choice.querySelector(
                    ".js-inline-check-input"
                );

            const wasChecked =
                checklistChoiceWasChecked.get(
                    choice
                );

            checklistChoiceWasChecked.delete(
                choice
            );

            if (
                !wasChecked ||
                !input ||
                input.type !== "radio"
            ) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();

            input.checked = false;

            input.dispatchEvent(
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

                        const selectedButton =
                            event.target.closest(
                                ".check-choice-button"
                            );

                        if (selectedButton) {
                            selectedButton.classList.toggle(
                                "is-selected",
                                event.target.checked
                            );
                        }
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
    if (!notifySearch || !notifyResults || !notifySelected) {
        return;
    }
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

                showCommonError(
                    "保存済みの通知先を復元できませんでした。通信状態を確認してください。"
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

            showCommonError(
                "保存済みの通知先を復元できませんでした。通信状態を確認してください。"
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

                                showCommonError(
                                    "通知先を取得できませんでした。通信状態を確認してください。"
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

                showCommonError(
                    "保存済みの点検未実施通知先を復元できませんでした。通信状態を確認してください。"
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

            showCommonError(
                "保存済みの点検未実施通知先を復元できませんでした。通信状態を確認してください。"
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
                "vehicle_record_id"
            );

        const formData =
            new FormData();

        formData.append(
            "csrf_token",
            csrfToken
        );

        formData.append(
            "vehicle_record_id",
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
                        headers: {
                            "X-DKSS-Validation-Only":
                                "1"
                        },
                        body: formData
                    }
                );

            if (!response.ok) {
                if (
                    response.headers.get(
                        "X-DKSS-Form-Errors"
                    ) === "1"
                ) {
                    const data =
                        await response.json();

                    clearCommonErrors();

                    (data.errors || []).forEach(
                        function (error) {
                            showCommonError(
                                error.message,
                                error.field || ""
                            );
                        }
                    );

                    return;
                }

                throw new Error(
                    "HTTP " + response.status
                );
            }
        } catch (error) {
            console.error(
                "点検忘れ通知先の保存に失敗しました。",
                error
            );

            showCommonError(
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

                                    showCommonError(
                                        "通知先を取得できませんでした。通信状態を確認してください。"
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
            "vehicle_record_id"
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
        ".usage-vehicle-shortcut"
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

                                showCommonError(
                                    "車両を取得できませんでした。通信状態を確認してください。"
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
                                            vehicle.number || "ナンバー未登録"
                                        ];

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
                                            vehicle.vehicle_record_id;

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

            const restorePosition = function () {
                requestAnimationFrame(function () {
                    requestAnimationFrame(function () {
                        document.querySelectorAll(
                            ".vehicle-check-table-scroll"
                        ).forEach(function (area, index) {
                            if (
                                position.tables &&
                                position.tables[index] !== undefined
                            ) {
                                area.scrollLeft = position.tables[index];
                            }
                        });

                        window.scrollTo({
                            left: position.pageX || 0,
                            top: position.pageY || 0,
                            behavior: "instant"
                        });
                    });
                });
            };

            if (document.readyState === "complete") {
                restorePosition();
            } else {
                window.addEventListener("load", restorePosition, {
                    once: true
                });
            }

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
                showCommonError(
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