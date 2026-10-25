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
                `対応履歴 ${referenceFeedbackHistory.length}件`
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

    // VEHICLE_RISK_CONTRACT_V2: reasoning/provenance never stand in for functional risk.
    function hasRiskContract(item) {
        return ["supported", "unassessed"].includes(item.risk_status)
            && typeof item.risk === "string" && item.risk.trim()
            && Array.isArray(item.risk_source_ids)
            && (item.risk_status === "supported"
                ? item.risk_source_ids.length > 0 && item.risk_source_ids.every(id => (item.source_ids || []).includes(id))
                : item.risk_source_ids.length === 0 && item.risk.trim() === "機能への影響は未判定です。");
    }

    function recommendationState(item) {
        return hasRiskContract(item) ? item.current_state || "車両の状態は未確認です。"
            : "車両状態の要点は分析更新後に表示します。";
    }

    // VEHICLE_RISK_MATRIX_UI_V1
    function riskResponsePriorityLabel(item) {
        return item.risk_assessment?.response_priority?.label || "要確認";
    }
    function riskResponseTone(item) {
        return item.risk_assessment?.response_priority?.tone || "";
    }
    function riskResponseRank(item) {
        const p = item.risk_assessment?.response_priority;
        if (p?.basis === "existing_operation_judgment") return 0;
        return {"優先対応": 1, "要確認": 2, "計画対応": 3, "通常管理": 4}[p?.label] ?? 2;
    }
    function recommendationConcern(item) {
        const value = recommendationConcernBeforeMatrix(item);
        const label = item.risk_assessment?.label || "未評価";
        return {...value, text: `リスク区分：${label}。${value.text}`};
    }

    function recommendationConcernBeforeMatrix(item) {
        if (hasRiskContract(item) && item.risk_status === "supported") {
            const general = item.risk_basis === "general_knowledge";
            return {text: item.risk.trim(),
                label: general ? "一般知識に基づく懸念（実車の異常は未確定）" : "リスク・懸念",
                explicit: !general};
        }
        return {text: "機能への影響は未判定です。", label: "未判定", explicit: false};
    }

    function preventiveRuleLabels(item, sources) {
        const labels = [];
        for (const id of item.source_ids || []) {
            const snapshot = sources?.[id]?.snapshot;
            if (snapshot?.source_kind !== "メーカー公式資料") continue;
            for (const rule of snapshot.maintenance_rule_evidence?.rules || []) {
                if (rule.analysis_adoption?.status !== "adopted_for_analysis"
                    || rule.source_verification?.status !== "quote_matched"
                    || rule.semantic_review?.status !== "supported") continue;
                const quote = String(rule.source_quote || "").replace(/\s+/g, " ").trim();
                if (quote) labels.push(`メーカー基準：${quote}`);
            }
        }
        return [...new Set(labels)];
    }

    function recommendedAction(item) {
        const first = Array.isArray(item.confirmation_steps)
            ? item.confirmation_steps.find(step => typeof step === "string" && step.trim()) : null;
        return item.category === "記録確認" && first ? first : item.action || item.title || "元の記録を確認してください。";
    }

    function feedbackControls(item) {
        const wrap = node("div", "ka-feedback");
        wrap.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:8px;";
        const choices = [
            ["in_progress", "対応を進める"], ["completed", "確認・対応を終えた"],
            ["dismissed", "今回は見送る"]
        ];
        const labels = {...Object.fromEntries(choices), accepted: "採用（以前の記録）"};
        let saved = {status: "open", ...(item.feedback || {})};
        let saving = false;
        let selectedStatus = null;
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
            wrap.dataset.feedbackDirty = (selectedStatus !== null && selectedStatus !== saved.status) || editor.value !== (saved.comment || "")
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
                button.setAttribute("aria-pressed", String((selectedStatus || saved.status) === value));
                button.style.background = (selectedStatus || saved.status) === value ? "#f2efff" : "";
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
                selectedStatus = null;
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
            button.addEventListener("click", () => { selectedStatus = value; markDirty(); showSaved(); });
            buttons.push([button, value]);
            wrap.append(button);
        }
        const comment = node("div", "ka-reference-comment");
        comment.append(node("p", "", "理由・確認結果（任意）"), editor);
        const recordDetails = node("details", "ka-action-record");
        recordDetails.append(node("summary", "", "整備記録と紐付ける（任意）"), maintenanceSelect, recordLink);
        comment.append(recordDetails);
        const commentSave = node("button", "btn btn-outline ka-action-save", "回答を保存");
        commentSave.type = "button";
        commentSave.style.cssText = "margin-top:6px;padding:5px 10px;font-size:12px;";
        commentSave.addEventListener("click", () => {
            if (!selectedStatus && !editor.value.trim() && !maintenanceSelect.value) { message.textContent = "対応を選ぶか、コメントを入力してください。"; return; }
            save(selectedStatus || saved.status || "open", false);
        });
        comment.append(commentSave);
        wrap.prepend(node("h4", "ka-action-answer-title", "確認・対応の状況を回答"));
        wrap.append(comment, message);
        const evaluation = node("details", "ka-action-evaluation");
        evaluation.append(node("summary", "", "提案自体への意見を送る（任意）"), evaluationControls(item));
        wrap.append(evaluation);
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
    let referenceDrawerBackdrop = null;
    const referenceDrawerInert = new Map();

    function showReferenceDrawer() {
        referenceDrawer.hidden = false;
        if (referenceDrawerBackdrop) referenceDrawerBackdrop.hidden = false;
        document.body.classList.add("ka-analysis-detail-open");
        for (const sibling of document.body.children) {
            if (sibling === referenceDrawer || sibling === referenceDrawerBackdrop || !('inert' in sibling)) continue;
            if (!referenceDrawerInert.has(sibling)) referenceDrawerInert.set(sibling, sibling.inert);
            sibling.inert = true;
        }
    }
    let referenceDrawerContent = null;
    let referenceDrawerOpener = null;
    let referenceLinkedProposalOpened = false;

    function closeReferenceDrawer() {
        if (!referenceDrawer || referenceDrawer.hidden) return;
        referenceDrawer.hidden = true;
        if (referenceDrawerBackdrop) referenceDrawerBackdrop.hidden = true;
        document.body.classList.remove("ka-analysis-detail-open");
        for (const [sibling, previous] of referenceDrawerInert) sibling.inert = previous;
        referenceDrawerInert.clear();
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
        if (!referenceDrawer || referenceDrawer.hidden) return;
        if (event.key === "Escape") { event.preventDefault(); closeReferenceDrawer(); return; }
        if (event.key !== "Tab") return;
        const focusable = [...referenceDrawer.querySelectorAll('button:not([disabled]),a[href],textarea:not([disabled]),input:not([disabled]),select:not([disabled]),summary,[tabindex="0"]')]
            .filter(element => element.getClientRects().length && !element.closest('[hidden],[inert]'));
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (!first) {event.preventDefault();referenceDrawer.focus();return;}
        if (event.shiftKey && document.activeElement === first) {event.preventDefault();last.focus();}
        else if (!event.shiftKey && document.activeElement === last) {event.preventDefault();first.focus();}
    });

    function openReferenceDrawer(item, content, opener, sources) {
        if (referenceDrawerContent !== content
            && referenceDrawer?.querySelector('[data-feedback-dirty="1"]')) {
            showReferenceDrawer();
            status.textContent = "入力中のコメントを保存してから、別の提案を開いてください。";
            status.hidden = false;
            return;
        }
        if (!referenceDrawer) {
            referenceDrawer = node("aside", "ka-reference-drawer");
            referenceDrawer.setAttribute("role", "dialog");
            referenceDrawer.setAttribute("aria-modal", "true");
            referenceDrawer.tabIndex = -1;
            referenceDrawer.setAttribute("aria-labelledby", "ka-reference-drawer-title");
            referenceDrawerBackdrop = node("div", "ka-analysis-detail-backdrop");
            referenceDrawerBackdrop.hidden = true;
            referenceDrawerBackdrop.setAttribute("aria-hidden", "true");
            referenceDrawerBackdrop.addEventListener("click", closeReferenceDrawer);
            document.body.append(referenceDrawerBackdrop, referenceDrawer);
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
        priority.dataset.priority = riskResponseTone(item);
        priorityRow.append(priority);

        const state = node("div", "ka-drawer-summary-field");
        state.append(node("span", "ka-drawer-summary-label", "現在の状態"),
            node("p", "", recommendationState(item)));
        const concern = recommendationConcern(item);
        const risk = node("div", "ka-drawer-summary-field ka-context-concern");
        risk.append(node("span", "ka-drawer-summary-label", concern.label), node("p", "", concern.text));

        const action = node(
            "div",
            "ka-drawer-summary-field ka-drawer-summary-action"
        );
        action.append(
            node("span", "ka-drawer-summary-label", "推奨する対応"),
            node("p", "", recommendedAction(item))
        );

        const when = node("p", "ka-action-when", `確認時期：${item.timing || "時期は未判定"}`);
        summary.append(priorityRow, state, risk, action);
        for (const text of preventiveRuleLabels(item, sources)) {
            summary.append(node("p", "ka-action-when", text));
        }
        summary.append(when);
        const original = content.querySelector(".ka-reference-source-links a");
        if (original) {
            const link = original.cloneNode(true);
            link.textContent = "元の点検・整備記録を開く ↗";
            link.className = "ka-action-original-link";
            summary.append(link);
        }

        referenceDrawer.replaceChildren(header, summary, content);
        referenceDrawerContent = content;
        referenceDrawerOpener = opener;
        showReferenceDrawer();
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

    function referenceComparison(snapshot) {
        const section = node("section", "ka-reference-comparison");
        section.append(node("h4", "", "AI分析時の比較条件"));

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
                    "対象期間",
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
            const comparison = document.getElementById("ka-reference-aggregate");
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
                priority.dataset.priority = riskResponseTone(item);

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
                const reasonPriority = node("span", "ka-ai-priority", riskResponsePriorityLabel(item));
                reasonPriority.dataset.priority = riskResponseTone(item);
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
                button.addEventListener("click", () => openReferenceDrawer(item, detail, button, data.sources));
                if (!referenceLinkedProposalOpened && item.proposal_id
                    && window.location.hash === `#proposal=${item.proposal_id}`) {
                    referenceLinkedProposalOpened = true;
                    queueMicrotask(() => {
                        const group = button.closest("details");
                        if (group) group.open = true;
                        openReferenceDrawer(item, detail, button, data.sources);
                    });
                }
                if (item.proposal_id) {
                    const controls = feedbackControls(item);
                    controls.addEventListener("ka-feedback-saved", event => {
                        badge.textContent = labels[event.detail.status] || "未着手";
                        badge.dataset.state = event.detail.status;
                    });
                    detail.append(controls);
                }
                const evidence = node("details", "ka-action-evidence");
                evidence.append(node("summary", "", "根拠・詳しい確認手順を見る"));
                const responseControls = detail.querySelector(".ka-feedback");
                const evidenceBody = node("div", "ka-action-evidence-body");
                for (const child of [...detail.childNodes]) if (child !== responseControls) evidenceBody.append(child);
                evidence.append(evidenceBody);
                detail.replaceChildren();
                if (responseControls) detail.append(responseControls);
                detail.append(evidence);
                cell.append(button, badge);
                row.append(cell);
                body.append(row);
            }

            grid.append(head, body);
            wrap.append(grid);
            return wrap;
        };

        const priorityOrder = {"高": 0, "中": 1, "低": 2};
        const ordered = [...items].sort((a, b) => riskResponseRank(a) - riskResponseRank(b));
        const current = data.is_current === true;
        const board = node("section", "ka7-board");
        const heading = node("header", "ka7-board-heading");
        heading.append(node("h3", "", "予防整備・対応候補"));
        if (current && ordered.length) heading.append(node("span", "ka7-count", `${ordered.length}件`));
        if (current && data.generated_at) heading.append(node("span", "ka7-date", `AI分析 ${data.generated_at}`));
        const labels=[['daily_inspections','日常点検'],['periodic_inspections','定期点検'],['maintenance','整備'],['parts','部品']];
        const counts=labels.filter(([key])=>Number.isInteger(data.input_summary?.[key]) && data.input_summary[key]>0).map(([key,label])=>`${label}${data.input_summary[key]}件`);
        // Input record counts are internal diagnostics.
        heading.append(status);board.append(heading);
        if(current && !ordered.length) {
            const insight=node("section", "ka10-insight");
            const line=node("div", "ka10-insight-top");
            line.append(node("span", "ka10-ai-mark", "AI"), node("strong", "", ordered.length ? `${ordered.length}件の確認候補` : "追加対応の提案なし"));
            const high=ordered.filter(item=>item.priority === "高").length;
            const medium=ordered.filter(item=>item.priority === "中").length;
            if(high) line.append(node("span", "ka10-severity high", `優先度 高 ${high}件`));
            if(medium) line.append(node("span", "ka10-severity medium", `優先度 中 ${medium}件`));
            insight.append(line);
            const overview=typeof data.analysis?.overview === "string" ? data.analysis.overview.trim() : "";
            if(overview) {
                const sentences=overview.match(/[^。！？]+[。！？]?/g) || [overview];
                const limits=sentences.filter(sentence=>/不明(?:なため|のため|で)|(?:計算|判定|判断|時期).{0,12}保留|判断(?:は)?できません[。！？]?$/.test(sentence));
                const findings=sentences.filter(sentence=>!limits.includes(sentence));
                if(findings.length) insight.append(node("p", "ka10-overview", findings.join("")));
                if(limits.length) {const limit=node("p", "ka10-limit");limit.append(node("strong", "", "判断に関する補足"),node("span", "", limits.join("")));insight.append(limit);}
            }
            board.append(insight);
        }
        if (!current) {
            const explanation = current && typeof data.analysis?.overview === "string"
                ? data.analysis.overview.trim() : "";
            const empty=node("div", "ka7-empty ka9-conclusion");
            empty.append(node("strong", "ka9-conclusion-title", current ? "追加対応の提案なし" : "分析更新待ち"));
            if(explanation) {
                const sentences=explanation.match(/[^。！？]+[。！？]?/g) || [explanation];
                const list=node("ul", "ka9-conclusion-facts");
                for(const sentence of sentences) if(sentence.trim()) list.append(node("li", "", sentence.trim()));
                empty.append(list);
            } else empty.append(node("p", "", current ? "現在の登録内容に基づく結果です。異常がないことを保証するものではありません。" : "更新が完了すると結果を表示します。"));
            board.append(empty);
        } else if(ordered.length) {
            const existing = table(ordered, "提案の根拠");
            const controls = [...existing.querySelectorAll("tbody tr")].map(tr => [...tr.lastElementChild.childNodes]);
            const wrap = node("div", "ka7-proposal-scroll");
            wrap.tabIndex = 0;wrap.setAttribute("role", "region");wrap.setAttribute("aria-label", "優先度順の予防整備・対応候補");
            const grid = node("table", "ka7-proposal-table");
            const head = node("thead");const header = node("tr");
            for (const text of ["対象・対応優先度", "現在の状態", "リスク・懸念", "推奨する対応", "時期・回答"]) {const th=node("th","",text);th.scope="col";header.append(th);}
            head.append(header);const body=node("tbody");
            ordered.forEach((item,index) => {
                const row=node("tr");row.dataset.priority=item.priority || "";
                const target=node("td","ka7-target");target.append(node("strong","",item.target || item.title || "確認項目"));
                const priority=node("span","ka7-priority", riskResponsePriorityLabel(item));priority.dataset.priority=riskResponseTone(item);
                const priorityLine=node("div", "ka-context-priority");priorityLine.append(priority);target.append(priorityLine);
                if(item.category) {const tag=node("small", "ka10-category", item.category);tag.dataset.kind=item.category === "記録確認" ? "record" : "maintenance";target.append(tag);}
                const state=node("td", "ka-context-state", recommendationState(item));
                const concern=recommendationConcern(item);
                const risk=node("td", "ka-context-risk");
                if(!concern.explicit) risk.append(node("small", "ka-context-risk-label", concern.label));
                risk.append(node("p", "", concern.text));
                const action=node("td","ka7-next");action.append(node("strong","",item.category === "記録確認" && item.target ? `${item.target}の対応記録を確認` : item.title || item.action || "詳細を確認"));
                const firstStep = Array.isArray(item.confirmation_steps) ? item.confirmation_steps.find(step => typeof step === "string" && step.trim()) : null;
                const nextStep = item.action || firstStep;
                if (nextStep && nextStep !== item.title) {const step=node("span","ka8-first-step",nextStep);step.title=nextStep;action.append(step);}
                const timing=node("td","ka7-timing");timing.append(node("span","",item.timing || "時期は未判定"));
                const rules=[];
                for (const id of item.source_ids || []) for (const rule of data.sources?.[id]?.snapshot?.maintenance_rule_evidence?.rules || []) {
                    if (rule.analysis_adoption?.status === "adopted_for_analysis" && rule.source_verification?.status === "quote_matched" && rule.semantic_review?.status === "supported") rules.push(rule);
                }
                if(rules.length===1 && rules[0].source_quote) {
                    timing.title = String(rules[0].source_quote).replace(/\s+/g," ").trim();
                    for (const text of preventiveRuleLabels(item, data.sources)) {
                        const basis = node("span", "ka8-first-step", text);
                        action.append(basis);
                    }
                    if(rules[0].timing_facts?.status === "held") timing.append(node("small","ka7-held","期限未判定"));
                }
                const actions=node("td","ka7-row-actions");actions.append(...timing.childNodes);
                const ids=item.source_ids || [];
                const id=ids.find(x=>/^(inspection|periodic):/.test(String(x))) || ids.find(x=>String(x).startsWith("maintenance:")) || ids[0];
                const source=data.sources?.[id];
                if(source) {
                    const url=new URL(source.url,window.location.origin);
                    if(url.origin===window.location.origin) {
                        const name=/^(inspection|periodic):/.test(String(id)) ? "元の点検 ↗" : String(id).startsWith("maintenance:") ? "整備記録 ↗" : String(id).startsWith("knowledge:") ? "根拠資料 ↗" : "元の記録 ↗";
                        const link=node("a","ka7-record-link",name);link.href=url.href;link.target="_blank";link.rel="noopener noreferrer";link.title=source.label || name;actions.append(link);
                    }
                }
                const button=controls[index].find(el=>el.nodeType===1&&el.matches("button"));
                const badge=controls[index].find(el=>el.nodeType===1&&el.matches(".ka-reference-state"));
                if(button){button.textContent="詳細・対応";actions.append(button);}if(badge)priorityLine.append(badge);
                row.append(target,state,risk,action,actions);body.append(row);
            });
            grid.append(head,body);wrap.append(grid);board.append(wrap);
        }
        if(current) {
            const related=new Set(ordered.flatMap(item=>item.source_ids || []));
            const body=document.querySelector('#ka7-part-history tbody');
            if(body) {
                const rows=[...body.children];
                for(const row of rows) row.dataset.analysisRelated=String(related.has(row.dataset.partSource));
                for(const row of rows.filter(row=>related.has(row.dataset.partSource)).reverse()) body.prepend(row);
            }
        }
        // Analysis input audit remains stored; not part of the user-facing result.
        fragment.append(board);
        if(current && referenceFeedbackHistory.length)fragment.append(feedbackHistory());
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

        if (data.generated_at) fragment.append(node("p", "kc-muted", `${dateLabel}：${data.generated_at}`));

        const list = node("ul", "ka-ai-list");

        for (const item of analysis.recommendations) {
            const row = node("li", "ka-ai-item");
            const title = node("h4", "ka-ai-item-title");
            const priority = node("span", "ka-ai-priority", riskResponsePriorityLabel(item));
            priority.dataset.priority = riskResponseTone(item);
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
                    data.comparison, data.generated_at, data.analysis_method, data.is_current, data.status, data.input_summary
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
            if(!status.isConnected) results.before(status);
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

        document.getElementById("ka-reference-aggregate")?.scrollIntoView({
            block: "start",
            behavior: "smooth"
        });
    });
})();
