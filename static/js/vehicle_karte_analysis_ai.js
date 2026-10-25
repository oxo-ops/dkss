(() => {
    "use strict";

    const status = document.getElementById("ka-ai-status");
    const results = document.getElementById("ka-ai-results");
    if (!status || !results || !status.dataset.url) return;

    let timer;
    let busy = false;
    let stopped = false;

    const fail = (message) =>
        Object.assign(new Error(message), { userMessage: true });

    const node = (tag, className, text) => {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = String(text);
        return element;
    };

    let referenceMaintenanceRecords = [];
    let referenceFeedbackHistory = [];

    function feedbackHistory(panel = node("details", "ka-feedback-history")) {
        panel.open = false;
        const summary = node("summary", "ka-info-summary");
        summary.append(
            node(
                "strong",
                "",
                `過去の提案と対応履歴（${referenceFeedbackHistory.length}件／直近30件）`
            ),
            node(
                "span",
                "ka-info-summary-description",
                "これまでに提案された内容と対応状況を確認できます"
            )
        );
        const historyList = node("div", "ka-history-list");
        historyList.setAttribute("role", "region");
        historyList.setAttribute("aria-label", "過去の提案と対応履歴");

        panel.replaceChildren(summary, historyList);

        const labels = {
            open: "未着手", accepted: "採用", in_progress: "対応中",
            completed: "完了", dismissed: "見送り"
        };
        if (!referenceFeedbackHistory.length) {
            historyList.append(
                node("p", "kc-muted ka-history-empty", "保存された対応はありません。")
            );
        }
        for (const entry of referenceFeedbackHistory) {
            const row = node("article", "ka-history-item");
            row.dataset.status = entry.status || "open";

            const header = node("div", "ka-history-item-header");

            const target = node(
                "strong",
                "ka-history-item-target",
                entry.target || "確認項目"
            );

            const state = node(
                "span",
                "ka-history-item-status",
                labels[entry.status] || entry.status || "未着手"
            );
            state.dataset.status = entry.status || "open";

            header.append(target, state);
            row.append(header);

            const meta = [entry.at, entry.by].filter(Boolean).join(" · ");
            if (meta) {
                row.append(node("p", "ka-history-item-meta", meta));
            }

            if (entry.action) {
                const action = node("div", "ka-history-item-action");
                action.append(
                    node("span", "ka-history-item-label", "提案内容"),
                    node("p", "", entry.action)
                );
                row.append(action);
            }

            if (entry.comment) {
                const comment = node("div", "ka-history-item-comment");
                comment.append(
                    node("span", "ka-history-item-label", "対応コメント"),
                    node("p", "", entry.comment)
                );
                row.append(comment);
            }
            const record = entry.maintenance_record;
            if (record?.url) {
                try {
                    const url = new URL(record.url, window.location.origin);
                    if (url.origin === window.location.origin) {
                        const link = node("a", "", `${record.label || "関連する整備記録"} ↗`);
                        link.href = url.href;
                        row.append(link);
                    }
                } catch {}
            }
            historyList.append(row);
        }
        return panel;
    }

    function feedbackControls(item) {
        const wrap = node("div", "ka-feedback");
        wrap.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:8px;";
        const choices = [
            ["open", "未着手"],
            ["in_progress", "対応中"], ["completed", "完了"],
            ["dismissed", "見送り"]
        ];
        const labels = {...Object.fromEntries(choices), accepted: "採用（以前の記録）"};
        let saved = {status: "open", ...(item.feedback || {})};
        let saving = false;
        const message = node("span", "kc-muted");
        message.setAttribute("role", "status");
        const editor = node("textarea");
        editor.rows = 2;
        editor.maxLength = 5000;
        editor.value = saved.comment || "";
        editor.placeholder = "補足があれば入力（任意）";
        editor.setAttribute("aria-label", "AI提案へのコメント（任意）");
        editor.style.cssText = "display:block;width:100%;min-width:220px;box-sizing:border-box;";
        const maintenanceSelect = node("select");
        maintenanceSelect.setAttribute("aria-label", "関連する整備記録（任意）");
        maintenanceSelect.style.cssText = "display:block;width:100%;margin:6px 0;";
        const blank = node("option", "", "整備記録を選択（任意）");
        blank.value = "";
        maintenanceSelect.append(blank);

        const recordChoices = [...referenceMaintenanceRecords];
        if (saved.maintenance_record && !recordChoices.some(record => record.id === saved.maintenance_record.id)) {
            recordChoices.push(saved.maintenance_record);
        }
        for (const record of recordChoices) {
            const option = node("option", "", record.label);
            option.value = String(record.id);
            maintenanceSelect.append(option);
        }
        maintenanceSelect.value = saved.maintenance_record ? String(saved.maintenance_record.id) : "";

        const recordLink = node("a", "", "関連する整備記録を開く ↗");
        function showRecordLink() {
            const selected = recordChoices.find(record => String(record.id) === maintenanceSelect.value);
            recordLink.hidden = true;
            if (!selected?.url) return;
            const url = new URL(selected.url, window.location.origin);
            if (url.origin !== window.location.origin) return;
            recordLink.href = url.href;
            recordLink.hidden = false;
        }
        function markDirty() {
            const recordId = saved.maintenance_record ? String(saved.maintenance_record.id) : "";
            wrap.dataset.feedbackDirty = editor.value !== (saved.comment || "")
                || maintenanceSelect.value !== recordId ? "1" : "0";
        }
        editor.addEventListener("input", markDirty);
        maintenanceSelect.addEventListener("change", () => {
            markDirty();
            showRecordLink();
        });
        showRecordLink();
        const buttons = [];
        function showSaved() {
            message.textContent = `${labels[saved.status] || "未対応"}${saved.at ? " · " + saved.at : ""}`;
            if (saved.revision && saved.revision !== item.proposal_revision) {
                message.textContent += " · 前回の判断後に提案内容が更新されています";
            }
            for (const [button, value] of buttons) {
                button.disabled = saving;
                button.setAttribute("aria-pressed", String(saved.status === value));
                button.style.background = saved.status === value ? "#eef5fc" : "";
            }
        }
        async function save(value, closeAfterSave = false) {
            if (saving) return;
            saving = true;
            wrap.dataset.feedbackDirty = "1";
            showSaved();
            commentSave.disabled = true;
            maintenanceSelect.disabled = true;
            editor.disabled = true;
            message.textContent = "保存中…";
            try {
                const url = new URL(status.dataset.url, window.location.origin);
                if (url.origin !== window.location.origin || !url.pathname.endsWith("/result")) {
                    throw new Error("保存先を確認できません。");
                }
                url.pathname = url.pathname.slice(0, -7) + "/feedback";
                const token = document.querySelector('meta[name="csrf-token"]')?.content;
                if (!token) throw new Error("画面を再読み込みしてください。");
                const response = await fetch(url.href, {
                    method: "POST", credentials: "same-origin", cache: "no-store",
                    headers: {
                        "Content-Type": "application/json", "Accept": "application/json",
                        "X-CSRFToken": token
                    },
                    body: JSON.stringify({
                        proposal_id: item.proposal_id,
                        proposal_revision: item.proposal_revision,
                        status: value, comment: editor.value,
                        maintenance_record_id: maintenanceSelect.value ? Number(maintenanceSelect.value) : null
                    }),
                    signal: AbortSignal.timeout(15000)
                });
                if (response.redirected) throw new Error("ログイン状態を確認してください。");
                const data = await response.json();
                if (!response.ok || !data.ok) {
                    throw new Error(data.message || "保存できませんでした。");
                }
                saved = data.feedback;
                item.feedback = saved;
                if (saved.id) {
                    referenceFeedbackHistory = [
                        saved,
                        ...referenceFeedbackHistory.filter(entry => entry.id !== saved.id)
                    ].slice(0, 30);
                    for (const panel of document.querySelectorAll(".ka-feedback-history")) {
                        feedbackHistory(panel);
                    }
                }
                wrap.dispatchEvent(new CustomEvent("ka-feedback-saved", {detail: saved}));
                editor.value = saved.comment || "";
                maintenanceSelect.value = saved.maintenance_record ? String(saved.maintenance_record.id) : "";
                showRecordLink();
                wrap.dataset.feedbackDirty = "0";
                showSaved();
                if (closeAfterSave && referenceDrawer
                    && wrap.closest(".ka-reference-drawer") === referenceDrawer) {
                    closeReferenceDrawer();
                }
            } catch (error) {
                message.textContent = error.message || "保存できませんでした。";
                markDirty();
            } finally {
                saving = false;
                for (const [button] of buttons) button.disabled = false;
                commentSave.disabled = false;
                maintenanceSelect.disabled = false;
                editor.disabled = false;
            }
        }
        for (const [value, label] of choices) {
            const button = node("button", "btn btn-outline", label);
            button.type = "button";
            button.style.cssText = "padding:5px 10px;font-size:12px;min-height:32px;";
            button.addEventListener("click", () => save(value));
            buttons.push([button, value]);
            wrap.append(button);
        }
        const comment = node("div", "ka-reference-comment");
        comment.append(node("p", "", "理由・確認結果（任意）"), editor);
        comment.append(
            node("p", "", "関連する整備記録（任意）"),
            maintenanceSelect,
            recordLink
        );
        const commentSave = node("button", "btn btn-outline", "保存");
        commentSave.type = "button";
        commentSave.style.cssText = "margin-top:6px;padding:5px 10px;font-size:12px;";
        commentSave.addEventListener("click", () => save(saved.status || "open", true));
        comment.append(commentSave);
        wrap.append(
            comment,
            message,
            evaluationControls(item)
        );
        showSaved();
        return wrap;
    }

    function evaluationControls(item) {
        const panel = node(
            "details",
            "ka-reference-comment ka-evaluation-panel"
        );

        const summary = node("summary", "ka-evaluation-summary");

        const heading = node("div", "ka-evaluation-heading");
        heading.append(
            node("strong", "", "提案の評価（任意）"),
            node(
                "span",
                "ka-evaluation-description",
                "AIの提案が適切だったかを評価し、改善につなげます"
            )
        );

        summary.append(heading);
        panel.append(summary);
        const choices = [
            ["appropriate", "適切"],
            ["needs_revision", "要修正"],
            ["uncertain", "判断保留"]
        ];
        let saved = item.evaluation || {};
        let saving = false;
        const editor = node("textarea");
        editor.rows = 2;
        editor.maxLength = 5000;
        editor.placeholder = "修正したい点など（任意）";
        editor.setAttribute("aria-label", "提案の評価コメント（任意）");
        editor.value = saved.comment || "";
        editor.addEventListener("input", () => {
            panel.dataset.feedbackDirty =
                editor.value !== (saved.comment || "") ? "1" : "0";
        });
        const message = node("p", "kc-muted");
        message.setAttribute("role", "status");
        const buttons = [];

        function show() {
            const label = choices.find(([value]) => value === saved.verdict)?.[1];
            message.textContent = label
                ? `${label}${saved.at ? " · " + saved.at : ""}`
                : "未評価";
            for (const [button, value] of buttons) {
                button.disabled = saving;
                button.setAttribute("aria-pressed", String(saved.verdict === value));
            }
        }

        async function save(verdict) {
            if (saving) return;
            saving = true;
            panel.dataset.feedbackDirty = "1";
            show();
            message.textContent = "保存中…";
            try {
                const url = new URL(status.dataset.url, window.location.origin);
                if (
                    url.origin !== window.location.origin
                    || !url.pathname.endsWith("/result")
                ) {
                    throw new Error("保存先を確認できません。");
                }
                url.pathname = url.pathname.slice(0, -7) + "/evaluation";
                const token = document.querySelector('meta[name="csrf-token"]')?.content;
                if (!token) throw new Error("画面を再読み込みしてください。");
                const response = await fetch(url.href, {
                    method: "POST",
                    credentials: "same-origin",
                    cache: "no-store",
                    headers: {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "X-CSRFToken": token
                    },
                    body: JSON.stringify({
                        proposal_id: item.proposal_id,
                        proposal_revision: item.proposal_revision,
                        verdict,
                        comment: editor.value
                    }),
                    signal: AbortSignal.timeout(15000)
                });
                if (response.redirected) {
                    throw new Error("ログイン状態を確認してください。");
                }
                const data = await response.json();
                if (!response.ok || !data.ok) {
                    throw new Error(data.message || "保存できませんでした。");
                }
                saved = data.evaluation;
                item.evaluation = saved;
                editor.value = saved.comment || "";
                panel.dataset.feedbackDirty = "0";
                show();
            } catch (error) {
                message.textContent = error.message || "保存できませんでした。";
            } finally {
                saving = false;
                for (const [button] of buttons) button.disabled = false;
            }
        }

        panel.append(editor);
        for (const [value, label] of choices) {
            const button = node("button", "btn btn-outline", label);
            button.type = "button";
            button.addEventListener("click", () => save(value));
            buttons.push([button, value]);
            panel.append(button);
        }
        panel.append(message);
        show();
        return panel;
    }

    let referenceDrawer = null;
    let referenceDrawerContent = null;
    let referenceDrawerOpener = null;
    let referenceLinkedProposalOpened = false;

    function closeReferenceDrawer() {
        if (!referenceDrawer) return;
        referenceDrawer.hidden = true;
        document.body.classList.remove("ka-reference-open");
        if (window.location.hash.startsWith("#proposal=")) {
            window.history.replaceState(
                window.history.state,
                "",
                window.location.pathname + window.location.search
            );
        }
        referenceDrawerOpener?.focus();
    }

    document.addEventListener("keydown", event => {
        if (event.key === "Escape") closeReferenceDrawer();
    });

    function openReferenceDrawer(item, content, opener) {
        if (referenceDrawerContent !== content
            && referenceDrawer?.querySelector('[data-feedback-dirty="1"]')) {
            referenceDrawer.hidden = false;
            document.body.classList.add("ka-reference-open");
            status.textContent = "入力中のコメントを保存してから、別の提案を開いてください。";
            status.hidden = false;
            return;
        }
        if (!referenceDrawer) {
            referenceDrawer = node("aside", "ka-reference-drawer");
            referenceDrawer.setAttribute("role", "dialog");
            referenceDrawer.setAttribute("aria-modal", "false");
            referenceDrawer.setAttribute("aria-labelledby", "ka-reference-drawer-title");
            document.body.append(referenceDrawer);
        }
        const header = node("header", "ka-reference-drawer-header");

        const heading = node("div", "ka-drawer-heading");
        heading.append(
            node("span", "ka-drawer-eyebrow", "AI提案の詳細")
        );

        const title = node(
            "h3",
            "",
            item.target || item.title || "確認項目"
        );
        title.id = "ka-reference-drawer-title";
        heading.append(title);

        const close = node("button", "ka-drawer-close", "×");
        close.type = "button";
        close.setAttribute("aria-label", "提案の詳細を閉じる");
        close.addEventListener("click", closeReferenceDrawer);

        header.append(heading, close);

        const summary = node("section", "ka-drawer-summary");

        const priorityRow = node("div", "ka-drawer-priority-row");
        priorityRow.append(
            node("span", "ka-drawer-summary-label", "優先度")
        );

        const priority = node(
            "span",
            "ka-ai-priority",
            item.priority || "未設定"
        );
        priority.dataset.priority = item.priority || "";
        priorityRow.append(priority);

        const state = node("div", "ka-drawer-summary-field");
        state.append(
            node("span", "ka-drawer-summary-label", "現在の状態"),
            node("p", "", item.current_state || "記録を確認")
        );

        const action = node(
            "div",
            "ka-drawer-summary-field ka-drawer-summary-action"
        );
        action.append(
            node("span", "ka-drawer-summary-label", "推奨する対応"),
            node("p", "", item.action || "確認が必要です")
        );

        summary.append(priorityRow, state, action);

        referenceDrawer.replaceChildren(header, summary, content);
        referenceDrawerContent = content;
        referenceDrawerOpener = opener;
        referenceDrawer.hidden = false;
        document.body.classList.add("ka-reference-open");
        close.focus();
    }

    function referenceOfficialKnowledge(item, sources) {
        const officialIds = Object.keys(sources || {}).filter(id =>
            id.startsWith("knowledge:")
            && sources[id]?.snapshot?.source_kind === "メーカー公式資料"
        );
        const usedIds = new Set(item.knowledge_ids || []);
        const used = officialIds.filter(id => usedIds.has(id));
        const text = used.length
            ? `メーカー公式資料：今回の提案で使用 ${used.length}件`
            : officialIds.length
                ? "メーカー公式資料：分析入力あり・今回の提案では未使用"
                : "メーカー公式資料：今回の分析入力にはなし";
        return node("p", "ka-reference-note", text);
    }

    function referenceConfirmation(item) {
        const section = node("section", "ka-reference-confirmation");
        section.append(node("h4", "", "最初の確認と分岐"));
        const steps = Array.isArray(item.confirmation_steps)
            ? item.confirmation_steps.filter(step => typeof step === "string" && step.trim())
            : [];
        const list = node("ol");
        list.style.cssText = "margin:8px 0;padding-left:24px;";
        for (const step of steps.length ? steps : [item.action]) {
            const row = node("li", "", step);
            row.style.cssText = "margin:8px 0;padding-left:4px;";
            list.append(row);
        }
        section.append(list);
        if (item.confirmation_branch) {
            section.append(node("p", "ka-reference-note", item.confirmation_branch));
        }
        return section;
    }

    function referenceComparison(snapshot, heading = "AI分析時の比較条件") {
        const section = node("section", "ka-reference-comparison");
        section.append(node("h4", "", heading));

        const scope = snapshot?.comparison_scope;
        const countLabel = value => (
            Number.isInteger(value) && value >= 0
                ? `${value}台` : "不明"
        );

        if (scope && typeof scope === "object" && !Array.isArray(scope)) {
            const year = Number.isInteger(scope.reference_registration_year)
                ? `${scope.reference_registration_year}年` : "不明";
            const registration = scope.registration_scope === "same_year"
                ? `同じ初度登録年（基準：${year}）`
                : scope.registration_scope === "all_years"
                    ? "初度登録年を限定しない" : "条件未記録";
            const active = scope.include_inactive === true
                ? "無効車両を含む"
                : scope.include_inactive === false
                    ? "有効車両のみ" : "条件未記録";

            const comparisonFacts = node("dl", "ka-comparison-facts");

            const comparisonRows = [
                ["型式", scope.model_code || "不明"],
                [
                    "比較集計期間",
                    `${scope.start_date || "不明"} ～ ${scope.end_date || "不明"}`
                ],
                ["初度登録年", registration],
                ["車両状態", active],
                [
                    "比較対象",
                    `${countLabel(snapshot.vehicle_count)}（この車両を除く）`
                ]
            ];

            for (const [label, value] of comparisonRows) {
                const row = node("div", "ka-comparison-fact");
                row.append(
                    node("dt", "", label),
                    node("dd", "", value)
                );
                comparisonFacts.append(row);
            }

            section.append(comparisonFacts);

            if (snapshot.note) {
                section.append(node("p", "kc-muted", snapshot.note));
            }

            const metrics = Array.isArray(snapshot.metrics)
                ? snapshot.metrics : [];
            if (metrics.length) {
                const metricSection = node(
                    "div", "ka-comparison-metrics-section"
                );
                metricSection.append(
                    node("h5", "", "比較指標の母数")
                );

                const samples = node("dl", "ka-comparison-facts");

                for (const metric of metrics) {
                    if (!metric || typeof metric !== "object") continue;

                    const row = node("div", "ka-comparison-fact");
                    const count = metric.sample_count;

                    const detail = count === 0
                        ? "0台（比較値なし）"
                        : count === 1
                            ? "1台（1台の実績）"
                            : countLabel(count);

                    row.append(
                        node("dt", "", metric.label || "指標名未記録"),
                        node("dd", "", detail)
                    );

                    samples.append(row);
                }

                metricSection.append(samples);
                section.append(metricSection);
            }
            section.append(node(
                "p", "kc-muted",
                "初度登録年は製造年月とは異なります。登録0件は未交換・故障なしの証明ではありません。"
            ));
        } else {
            section.append(node(
                "p", "ka-reference-note",
                "この保存結果には比較条件が記録されていません。次回の分析更新後に確認できます。"
            ));
        }

        section.append(node(
            "p", "kc-muted",
            "下のボタンでは、現在の画面の選択条件による比較表を開きます。"
        ));
        const button = node("button", "ka-reference-detail-button", "比較表を表示");
        button.type = "button";
        button.addEventListener("click", () => {
            closeReferenceDrawer();
            const aggregate = document.getElementById("ka-reference-aggregate");
            const comparison = document.querySelector(".ka-comparison-panel");
            if (aggregate) aggregate.open = true;
            comparison?.scrollIntoView({block: "start"});
        });
        section.append(button);
        return section;
    }

    function render(data) {
        referenceMaintenanceRecords = data.analysis?.maintenance_records || [];
        referenceFeedbackHistory = data.analysis?.feedback_history || [];
        const items = data.analysis?.recommendations;
        if (!Array.isArray(items)) return renderLegacy(data);

        if (items.some(item =>
            !["整備・点検", "記録確認"].includes(item.category)
        )) {
            const fragment = document.createDocumentFragment();
            fragment.append(
                node("p", "kc-muted",
                    "前の形式で保存された結果です。自動更新後に判断一覧へ切り替わります。"),
                renderLegacy(data)
            );
            return fragment;
        }

        const fragment = document.createDocumentFragment();
        const scope = node("details", "ka-ai-overview-detail");
        scope.append(node("summary", "", "AI分析の条件"));
        scope.append(node("p", "kc-muted", "重要な整備・不具合・点検指摘は、比較集計期間より前の履歴も分析対象です。"));
        scope.append(referenceComparison(data.has_result ? data.comparison : data.scheduled_comparison,
            data.has_result ? "AI分析時の比較条件" : "自動分析の設定条件"));
        fragment.append(scope);

        const table = (rows, label) => {
            const wrap = node("div", "ka-decision-scroll");
            wrap.tabIndex = 0;
            wrap.setAttribute("role", "region");
            wrap.setAttribute("aria-label", label);

            const grid = node("table", "ka-decision-table");
            const head = node("thead");
            const headings = node("tr");

            for (const title of [
                "優先度", "部品・箇所", "現在の状態",
                "推奨する対応", "対応の目安", "根拠・対応"
            ]) {
                const cell = node("th", "", title);
                cell.scope = "col";
                headings.append(cell);
            }

            head.append(headings);
            const body = node("tbody");
            if (!rows.length) {
                const emptyRow = node("tr");
                const emptyCell = node("td", "kc-muted", "現在の分析結果に対応候補はありません。");
                emptyCell.colSpan = 6;
                emptyRow.append(emptyCell);
                body.append(emptyRow);
            }

            for (const item of rows) {
                const row = node("tr");
                const priority = node(
                    "span", "ka-ai-priority", item.priority
                );
                priority.dataset.priority = item.priority;

                const first = node("td");
                first.append(priority);
                row.append(first);

                for (const value of [
                    item.target, item.current_state,
                    item.action, item.timing
                ]) {
                    const td = node("td");
                    const text = node("span", "ka-reference-brief", value || "情報なし");
                    text.title = value || "情報なし";
                    td.append(text);
                    row.append(td);
                }

                const cell = node("td");
                const detail = node("div", "ka-reference-detail");
                const recordLinks = node("div", "ka-reference-source-links");
                const knowledgeLinks = node("div", "ka-reference-source-links");
                const knowledgeIds = new Set(item.knowledge_ids || []);
                const reason = node("div", "ka-reference-reason");
                const reasonPriority = node("span", "ka-ai-priority", item.priority);
                reasonPriority.dataset.priority = item.priority;
                reason.append(reasonPriority, node("p", "", item.reason));
                detail.append(
                    node("h4", "", "勧める理由"),
                    reason,
                    node("h4", "", "根拠の記録"),
                    recordLinks
                );

                if (!Array.isArray(item.source_ids)
                    || !item.source_ids.length) {
                    throw fail(
                        "提案の根拠となる履歴を確認できませんでした。"
                    );
                }

                for (const id of item.source_ids) {
                    const source = data.sources?.[id];
                    if (!source || typeof source.url !== "string") {
                        throw fail(
                            "提案の根拠となる履歴を確認できませんでした。"
                        );
                    }

                    const url = new URL(
                        source.url, window.location.origin
                    );
                    if (url.origin !== window.location.origin) {
                        throw fail(
                            "履歴へのリンクを確認できませんでした。"
                        );
                    }

                    const link = node(
                        "a", "", source.label || "履歴を確認"
                    );
                    link.href = url.href;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    if (knowledgeIds.has(id) || String(id).startsWith("knowledge:")) {
                        const snapshot = source.snapshot || {};
                        const reference = String(snapshot.source_reference || "")
                            .replace(/\[knowledge-document:[a-f0-9-]{36}\]/g, "")
                            .trim();
                        const fields = [
                            ["対象メーカー", snapshot.manufacturer],
                            ["対象型式", snapshot.model_code],
                            ["適用条件", snapshot.conditions],
                            ["知識に記載された確認・対応", snapshot.guidance],
                            ["出典", reference]
                        ].filter(([, value]) => value);

                        const knowledge = node("details", "ka-reference-note");
                        knowledge.append(node(
                            "summary",
                            "",
                            snapshot.title || source.label || "根拠となる知識"
                        ));
                        for (const [label, value] of fields) {
                            knowledge.append(node(
                                "p",
                                "ka-reference-note",
                                `${label}：${value}`
                            ));
                        }
                        if (!fields.length) {
                            knowledge.append(node(
                                "p",
                                "ka-reference-note",
                                "この保存結果には知識の詳細が含まれていません。"
                            ));
                        }
                        knowledgeLinks.append(
                            node(
                                "span",
                                "ka-reference-knowledge",
                                snapshot.source_kind || "登録済み知識"
                            ),
                            knowledge
                        );
                    } else {
                        recordLinks.append(link);
                    }
                }

                detail.append(
                    node("h4", "", "判断に使う知識"),
                    node("span", "ka-reference-knowledge", item.basis_type || "記録上の指摘・対応"),
                    knowledgeLinks,
                    referenceOfficialKnowledge(item, data.sources),
                    node("p", "ka-reference-note", item.uncertainty),
                    referenceConfirmation(item),
                    node("p", "ka-reference-note", `現在の状態：${item.current_state || "記録を確認"}\n対応の目安：${item.timing || "時期の判断材料不足"}`),
                    referenceComparison(data.comparison),
                    node("h4", "", "対応を記録")
                );
                const labels = {
                    open: "未着手", accepted: "採用", in_progress: "対応中",
                    completed: "完了", dismissed: "見送り"
                };
                const state = item.feedback?.status || "open";
                const badge = node("span", "ka-reference-state", labels[state] || "未着手");
                badge.dataset.state = state;
                const button = node("button", "ka-reference-detail-button", "詳細・対応記録");
                button.type = "button";
                button.addEventListener("click", () => openReferenceDrawer(item, detail, button));
                if (!referenceLinkedProposalOpened && item.proposal_id
                    && window.location.hash === `#proposal=${item.proposal_id}`) {
                    referenceLinkedProposalOpened = true;
                    queueMicrotask(() => {
                        const group = button.closest("details");
                        if (group) group.open = true;
                        openReferenceDrawer(item, detail, button);
                    });
                }
                if (item.proposal_id && data.is_current === true && data.status === "completed") {
                    const controls = feedbackControls(item);
                    controls.addEventListener("ka-feedback-saved", event => {
                        badge.textContent = labels[event.detail.status] || "未着手";
                        badge.dataset.state = event.detail.status;
                    });
                    detail.append(controls);
                }
                cell.append(button, badge);
                row.append(cell);
                body.append(row);
            }

            grid.append(head, body);
            wrap.append(grid);
            return wrap;
        };

        const priorityOrder = {"高": 0, "中": 1, "低": 2};
        const ordered = [...items].sort((a, b) => (priorityOrder[a.priority] ?? 3) - (priorityOrder[b.priority] ?? 3));
        const current = data.is_current === true && data.status === "completed";
        const board = node("section", "ka3-board");
        const title = node("header", "ka3-board-title");
        title.append(node("h3", "", current ? `予防整備の提案 ${ordered.length}件` : data.has_result ? `前回の提案 ${ordered.length}件` : "予防整備の提案"));
        if (data.generated_at) title.append(node("span", "ka3-date", `分析 ${data.generated_at}`));
        board.append(title);
        if (data.has_result && !current) {
            board.append(node("p", "kc-muted", "前回の分析結果を表示しています。現在の登録内容と異なる可能性があるため、対応の記録は分析更新後に行ってください。"));
        }
        if (!ordered.length) {
            const empty = node("div", "ka3-empty");
            empty.append(node("span", "ka3-empty-symbol", current ? "≡" : "◷"), node("h4", "", current ? "現在の分析に提案はありません" : data.has_result ? "前回の分析に提案はありません" : "分析更新待ち"));
            board.append(empty);
        } else {
            // Keep existing evidence validation, source links and feedback handlers.
            const existing = table(ordered, "提案の根拠");
            const controls = [...existing.querySelectorAll("tbody tr")].map(tr => [...tr.lastElementChild.childNodes]);
            const workspace = node("div", "ka3-workspace");
            workspace.dataset.count = String(ordered.length);
            const list = node("div", "ka3-proposal-list");
            list.setAttribute("role", "list");
            list.setAttribute("aria-label", "優先度順の提案");
            const detail = node("section", "ka3-detail");
            detail.setAttribute("aria-label", "選択した提案の詳細");
            const buttons = [];
            function select(index) {
                buttons.forEach((button, i) => button.setAttribute("aria-pressed", String(i === index)));
                const item = ordered[index];
                const header = node("header", "ka3-detail-heading");
                const detailPriority = node("span", "ka3-priority", item.priority || "未確認");
                detailPriority.dataset.priority = item.priority;
                header.append(node("span", "ka3-eyebrow", item.category), detailPriority, node("h4", "", item.target || "確認項目"));
                const action = node("section", "ka3-next-action");
                action.append(node("span", "ka3-section-label", "次の行動"), node("p", "", item.action));
                const when = node("div", "ka3-when");
                when.append(node("span", "", "時期"), node("strong", "", item.timing || "未確認"));
                action.append(when);
                const reason = node("section", "ka3-detail-section");
                reason.append(node("h5", "", "この提案の理由"), node("p", "", item.reason));
                const evidence = node("section", "ka3-detail-section");
                evidence.append(node("h5", "", "根拠の記録"));
                const links = node("div", "ka3-evidence");
                for (const id of item.source_ids || []) {
                    const source = data.sources?.[id];
                    if (!source) continue;
                    const url = new URL(source.url, window.location.origin);
                    if (url.origin !== window.location.origin) continue;
                    const link = node("a", "ka3-source", source.label || "根拠の記録");
                    link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
                    links.append(link);
                }
                evidence.append(links);
                const steps = node("section", "ka3-detail-section");
                steps.append(node("h5", "", "確認の進め方"));
                const stepsList = node("ol", "ka3-steps");
                for (const text of item.confirmation_steps || []) stepsList.append(node("li", "", text));
                steps.append(stepsList);
                const footer = node("footer", "ka3-detail-footer");
                footer.append(...controls[index]);
                detail.replaceChildren(header, action, reason, evidence, steps);
                detail.append(footer);
            }
            ordered.forEach((item, index) => {
                const row = node("article", "ka3-list-item"); row.setAttribute("role", "listitem");
                const button = node("button", "ka3-select");button.type = "button";
                const top = node("span", "ka3-row-top");
                const priority = node("span", "ka3-priority", item.priority || "未確認");priority.dataset.priority = item.priority;
                top.append(priority, node("span", "ka3-row-category", item.category));
                button.append(top, node("strong", "ka3-row-target", item.target), node("span", "ka3-row-action", item.action), node("span", "ka3-row-timing", item.timing || "時期未確認"));
                button.addEventListener("click", () => select(index));
                buttons.push(button);row.append(button);list.append(row);
            });
            workspace.append(list, detail);board.append(workspace);select(0);
            // Preserve proposal deep links by selecting the containing row before opening its drawer.
            const linkedIndex = ordered.findIndex(item => item.proposal_id && window.location.hash === `#proposal=${item.proposal_id}`);
            if (linkedIndex >= 0) select(linkedIndex);
        }
        const input = data.input_summary;
        if (input) {
            const strip = node("footer", "ka3-input-strip");
            strip.append(node("span", "", "現在の分析対象データ"));
            for (const [label, value, kind] of [["日常点検", input.daily_inspections, "daily"], ["定期点検", input.periodic_inspections, "periodic"], ["整備", input.maintenance, "maintenance"], ["交換部品", input.parts, "parts"]]) {
                if (!Number.isInteger(value)) continue;
                const link = node("a", "", `${label} ${value}件`);
                const base = new URL(status.dataset.url, window.location.origin);
                base.pathname = base.pathname.replace(/\/analysis\/result\/?$/, kind === "maintenance" ? "/maintenance" : kind === "parts" ? "/parts" : "/inspections");
                if (["daily", "periodic"].includes(kind)) base.searchParams.set("inspection_view", kind);
                link.href = base.href;strip.append(link);
            }
            board.append(strip);
        }
        title.append(status);
        fragment.append(board);
        if (current && referenceFeedbackHistory.length) fragment.append(feedbackHistory());
        return fragment;
    }

    function renderLegacy(data) {
        const analysis = data.analysis;
        if (!analysis || typeof analysis.overview !== "string"
            || !Array.isArray(analysis.recommendations)) {
            throw fail("分析結果の形式を確認できませんでした。");
        }

        const fragment = document.createDocumentFragment();
        const overview = node("details", "ka-ai-overview-detail");
        overview.append(
            node("summary", "", "車両の状態・分析の概要"),
            node("p", "ka-ai-overview", analysis.overview)
        );
        fragment.append(overview);

        const coverage = data.coverage || {};
        const dateLabel = data.analysis_method === "record_check"
            ? "確認日時" : "分析日時";

        fragment.append(node("p", "kc-muted", [
            data.generated_at ? `${dateLabel}：${data.generated_at}` : "",
            `参照履歴：${coverage.sent_count ?? 0}件（対象履歴${coverage.available_count ?? 0}件中）`
        ].filter(Boolean).join("　")));

        const list = node("ul", "ka-ai-list");

        for (const item of analysis.recommendations) {
            const row = node("li", "ka-ai-item");
            const title = node("h4", "ka-ai-item-title");
            const priority = node("span", "ka-ai-priority", item.priority);
            priority.dataset.priority = item.priority;
            title.append(priority, node("span", "", item.title));
            const detail = node("details", "ka-ai-detail");
            const heading = node("summary", "ka-ai-toggle");
            heading.append(title);
            detail.append(
                heading,
                node("p", "ka-ai-action", item.action)
            );

            const facts = node("dl", "ka-ai-facts");

            for (const [label, text] of [
                ["理由", item.reason],
                ["対応候補", item.action],
                ["確認事項", item.uncertainty]
            ]) {
                if (label === "対応候補") continue;
                const fact = node("div");
                fact.append(
                    node("dt", "", label),
                    node("dd", "", text)
                );
                facts.append(fact);
            }

            if (!Array.isArray(item.source_ids)
                || !item.source_ids.length) {
                throw fail("提案の根拠となる履歴を確認できませんでした。");
            }

            const sourceRow = node("div");
            const links = node("dd", "ka-ai-sources");

            for (const id of item.source_ids) {
                const source = data.sources?.[id];
                if (!source || typeof source.url !== "string") {
                    throw fail("提案の根拠となる履歴を確認できませんでした。");
                }

                const url = new URL(source.url, window.location.origin);
                if (url.origin !== window.location.origin) {
                    throw fail("履歴へのリンクを確認できませんでした。");
                }

                const link = node("a", "", source.label || "履歴を確認");
                link.href = url.href;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                links.append(link);
            }

            sourceRow.append(node("dt", "", "元の履歴"), links);
            facts.append(sourceRow);
            detail.append(facts);
            row.append(detail);
            list.append(row);
        }

        fragment.append(list);

        if (analysis.recommendations.length) {
            fragment.append(node(
                "p",
                "kc-muted",
                "対応は、根拠の履歴や現物を確認して判断してください。"
            ));
        }

        return fragment;
    }

    async function refresh() {
        clearTimeout(timer);
        if (busy || stopped || document.hidden) return;

        busy = true;
        results.setAttribute("aria-busy", "true");

        try {
            const url = new URL(
                status.dataset.url,
                window.location.href
            );

            if (url.origin !== window.location.origin) {
                stopped = true;
                throw fail("取得先を確認できません。画面を再読み込みしてください。");
            }

            const response = await fetch(url.href, {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: { "Accept": "application/json" },
                signal: AbortSignal.timeout(15000)
            });

            if (response.redirected || response.status === 401) {
                stopped = true;
                throw fail("画面を再読み込みしてログイン状態を確認してください。");
            }

            if (response.status === 403 || response.status === 404) {
                stopped = true;
                throw fail("分析結果を取得できません。対象車両と閲覧権限を確認してください。");
            }

            const data = await response.json();
            if (!response.ok || !data.ok) {
                throw fail(
                    data.message || "分析結果を取得できませんでした。"
                );
            }

            if (data.ok) {
                data.analysis ||= {overview: "", recommendations: []};
                const signature = JSON.stringify([
                    data.analysis, data.sources, data.coverage,
                    data.comparison, data.scheduled_comparison, data.generated_at, data.analysis_method, data.is_current, data.status, data.input_summary
                ]);
                if (results.dataset.signature !== signature) {
                    if (document.querySelector('[data-feedback-dirty="1"]')
                        || (referenceDrawer && !referenceDrawer.hidden)) {
                        status.hidden = false;
                        status.textContent = "新しい結果あり";
                        return;
                    }
                    const fragment = render(data);
                    results.replaceChildren(fragment);
                    results.dataset.signature = signature;
                }
                results.hidden = false;
            }

            const statusLabels = {running: "分析中", pending: "更新待ち", error: "更新エラー", waiting: "準備中"};
            status.textContent = data.is_current === true && data.status === "completed"
                ? "分析済み" : statusLabels[data.status] || (data.is_current === false ? "更新待ち" : "状態未確認");
            status.hidden = false;

        } catch (error) {
            status.hidden = false;
            status.textContent = (
                error.userMessage
                    ? error.message
                    : "更新状況を取得できませんでした。接続後に自動で再確認します。"
            ) + (
                results.hidden
                    ? ""
                    : " 前回取得した結果を表示しています。"
            );

        } finally {
            busy = false;
            results.setAttribute("aria-busy", "false");

            if (!stopped && !document.hidden) {
                timer = setTimeout(refresh, 60000);
            }
        }
    }

    document.addEventListener("visibilitychange", () => {
        clearTimeout(timer);
        if (!document.hidden) refresh();
    });

    refresh();
})();

(() => {
    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-analysis-comparison]");
        if (!button) return;

        const aggregate = document.getElementById("ka-reference-aggregate");
        if (aggregate) aggregate.open = true;

        document.querySelector(".ka-comparison-panel")?.scrollIntoView({
            block: "start",
            behavior: "smooth"
        });
    });
})();
