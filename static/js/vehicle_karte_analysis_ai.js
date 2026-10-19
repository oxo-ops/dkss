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
        panel.style.cssText = "width:100%;margin-top:12px;";
        panel.replaceChildren(node("summary", "", "過去の提案と対応履歴（直近30件）"));
        const labels = {
            open: "未着手", accepted: "採用", in_progress: "対応中",
            completed: "完了", dismissed: "見送り"
        };
        if (!referenceFeedbackHistory.length) {
            panel.append(node("p", "kc-muted", "保存された対応はありません。"));
        }
        for (const entry of referenceFeedbackHistory) {
            const row = node("div");
            row.style.cssText = "padding:10px 0;border-bottom:1px solid #e5edf5;";
            row.append(
                node("strong", "", `${entry.target} · ${labels[entry.status] || entry.status}`),
                node("p", "kc-muted", [entry.at, entry.by].filter(Boolean).join(" · ")),
                node("p", "", entry.action || "")
            );
            if (entry.comment) row.append(node("p", "", entry.comment));
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
            panel.append(row);
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
        wrap.append(comment, message, evaluationControls(item), feedbackHistory());
        showSaved();
        return wrap;
    }

    function evaluationControls(item) {
        const panel = node("details", "ka-reference-comment");
        panel.style.cssText = "width:100%;margin-top:12px;";
        panel.append(node("summary", "", "提案の評価（任意）"));
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
        const title = node("h3", "", `${item.target || item.title}｜提案の詳細`);
        title.id = "ka-reference-drawer-title";
        const close = node("button", "", "×");
        close.type = "button";
        close.setAttribute("aria-label", "提案の詳細を閉じる");
        close.addEventListener("click", closeReferenceDrawer);
        header.append(title, close);
        referenceDrawer.replaceChildren(header, content);
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

    function referenceComparison() {
        const section = node("section", "ka-reference-comparison");
        let context = {};
        try {
            context = JSON.parse(
                document.getElementById("ka-reference-context")?.textContent || "{}"
            );
        } catch {
            context = {};
        }
        const count = Number.isInteger(context.vehicle_count)
            ? `${context.vehicle_count}台` : "未確認";
        section.append(
            node("h4", "", "比較の条件"),
            node("p", "ka-reference-note", [
                "同じ会社・同型式（選択中の比較条件）",
                `型式：${context.model || "未登録"}`,
                `期間：${context.start_date || "未確認"} ～ ${context.end_date || "未確認"}`,
                `比較対象：${count}（この車両を除く）`
            ].join("\n"))
        );
        if (context.note) section.append(node("p", "kc-muted", context.note));
        const button = node("button", "ka-reference-detail-button", "比較条件・母数 →");
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
                        const fields = [
                            ["出典区分", snapshot.source_kind],
                            ["適用条件", snapshot.conditions],
                            ["提供者", snapshot.provider],
                            ["確認者", snapshot.confirmed_by],
                            ["確認日", snapshot.confirmed_at],
                            ["適用開始", snapshot.valid_from],
                            ["適用終了", snapshot.valid_until || "期限指定なし"],
                            ["出典", snapshot.source_reference]
                        ].filter(([, value]) => value);
                        const text = fields.map(([label, value]) => `${label}：${value}`).join("\n");
                        const confirmation = snapshot.status === "active"
                            && snapshot.confirmed_by && snapshot.confirmed_at
                            ? "確認済み（分析時点）"
                            : "確認状況は出典を確認";
                        knowledgeLinks.append(
                            node("span", "ka-reference-knowledge", `${snapshot.source_kind || "登録済み知識"} · ${confirmation}`),
                            link,
                            node("p", "ka-reference-note", text || "出典の詳細はリンク先を確認してください。")
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
                    referenceComparison(),
                    node("h4", "", "対応を記録")
                );
                const labels = {
                    open: "未着手", accepted: "採用", in_progress: "対応中",
                    completed: "完了", dismissed: "見送り"
                };
                const state = item.feedback?.status || "open";
                const badge = node("span", "ka-reference-state", labels[state] || "未着手");
                badge.dataset.state = state;
                const button = node("button", "ka-reference-detail-button", "詳細を見る ↗");
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
                if (item.proposal_id) {
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

        const maintenance = items.filter(
            item => item.category === "整備・点検"
        );
        const records = items.filter(
            item => item.category === "記録確認"
        );

        const decisionHeader = node("div", "ka-reference-list-heading");
        decisionHeader.append(
            node("h4", "ka-decision-heading", `次に確認・対応すること（${maintenance.length}件）`),
            node("small", "", data.generated_at ? `最終更新：${data.generated_at}` : "更新日時未確認")
        );
        fragment.append(decisionHeader);

        fragment.append(table(maintenance, "整備・点検の対応候補"));

        const recordDetail = node("details", "ka-decision-records");
        const recordSummary = node("summary");
        recordSummary.append(
            node("strong", "", "記録の確認事項"),
            node("span", "kc-muted", "　点検・整備・部品交換などの記録内容に関する確認事項")
        );
        recordDetail.append(recordSummary);
        if (records.length) {
            recordDetail.append(table(records, "記録の確認事項"));
        } else {
            recordDetail.append(node("p", "kc-muted", "現在の分析結果に記録の確認事項はありません。"));
        }
        fragment.append(recordDetail);

        const overview = node(
            "details", "ka-ai-overview-detail"
        );
        overview.append(
            node("summary", "", "分析の概要・参照範囲"),
            node("p", "", data.analysis.overview)
        );

        const coverage = data.coverage || {};
        overview.append(node("p", "kc-muted", [
            data.generated_at
                ? `更新：${data.generated_at}` : "",
            `参照履歴：${coverage.sent_count ?? 0}件／対象${coverage.available_count ?? 0}件`
        ].filter(Boolean).join("　")));

        fragment.append(overview, feedbackHistory());
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

            if (data.has_result) {
                const signature = JSON.stringify([
                    data.analysis, data.sources, data.coverage,
                    data.generated_at, data.analysis_method
                ]);
                if (results.dataset.signature !== signature) {
                    if (document.querySelector('[data-feedback-dirty="1"]')
                        || (referenceDrawer && !referenceDrawer.hidden)) {
                        status.hidden = false;
                        status.textContent = "新しい分析結果があります。詳細を閉じ、コメントを保存すると表示を更新できます。";
                        return;
                    }
                    const fragment = render(data);
                    results.replaceChildren(fragment);
                    results.dataset.signature = signature;
                }
                results.hidden = false;
            }

            status.textContent = data.message
                || "保存済みの結果を表示しています。";
            status.hidden = Boolean(data.has_result && data.status === "completed");

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
