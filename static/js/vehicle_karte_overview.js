(() => {
    "use strict";
    const panel = document.getElementById("ko-ai");
    const summary = document.querySelector("[data-ko-summary-count]");
    if (!panel?.dataset.resultUrl) {
        if (summary) summary.textContent = "確認不可";
        return;
    }
    const status = panel.querySelector("[data-ko-ai-status]");
    const list = panel.querySelector("[data-ko-ai-list]");
    const node = (tag, className, text) => {
        const el = document.createElement(tag);
        el.className = className;
        el.textContent = String(text ?? "");
        return el;
    };
    // Hide presentation annotations in saved AI output; preserve the actual advice.
    const text = value => typeof value === "string"
        ? value.replace(/[（(]\s*(?:提案上の時[機期]|リスク区分とは別)\s*[）)]/g, "").trim() : "";
    const visibleProposalLimit = 5;
    const previewMode = new URLSearchParams(window.location.search || "").get("priority_preview") === "1";
    const preview = window.VehiclePriorityPreview;
    async function load() {
        try {
            const response = await fetch(previewMode ? preview.url(panel.dataset.resultUrl, window.location) : panel.dataset.resultUrl, {
                credentials:"same-origin", cache:"no-store", signal:AbortSignal.timeout(15000)
            });
            if (response.redirected || !response.ok) throw new Error();
            const data = await response.json();
            if (!data.ok) throw new Error();
            const current = data.status === "completed" && data.is_current === true;
            list.replaceChildren();
            let previewResult;
            if (previewMode) {
                previewResult = preview.validate(data);
                if (!previewResult.available) {
                    summary.textContent = "試行表示不可";
                    panel.dataset.current = "false";
                    status.hidden = false;
                    status.textContent = previewResult.message;
                    return;
                }
            }
            if (!data.has_result || !Array.isArray(data.analysis?.recommendations)) {
                summary.textContent = "未取得";
                status.textContent = data.status === "error" ? "分析結果を取得できません。分析タブで確認してください。" :
                    ["running","pending"].includes(data.status) ? "初回の分析結果を待っています。" : "保存済みの分析結果はまだありません。";
                return;
            }
            const priorities = ["高", "中", "低"];
            // Only the three literal labels are priorities. Historical malformed
            // values keep their stable trailing order without being reclassified.
            const priorityRank = value => priorities.includes(value) ? priorities.indexOf(value) : priorities.length;
            const items = (previewMode ? previewResult.items : data.analysis.recommendations).filter(item => item && typeof item === "object" &&
                item.category !== "記録確認" && !(item.feedback?.revision === item.proposal_revision &&
                ["completed","dismissed"].includes(item.feedback?.status)))
                .sort((a,b) => previewMode ? 0 : priorityRank(a.priority) - priorityRank(b.priority));
            summary.textContent = `${items.length}件`;
            panel.dataset.current = String(current);
            for (const item of items.slice(0, visibleProposalLimit)) {
                const url = new URL(panel.dataset.analysisUrl, window.location.origin);
                if (url.origin !== window.location.origin) throw new Error();
                if (previewMode) url.searchParams.set("priority_preview", "1");
                if (item.proposal_id) url.hash = `proposal=${encodeURIComponent(item.proposal_id)}`;
                const row = node("li", "ko-proposal", "");
                if (previewMode) row.dataset.priorityPreview = "true";
                if (item.proposal_id) row.dataset.proposalId = String(item.proposal_id);
                const hasSavedPriority = priorities.includes(item.priority);
                const priority = previewMode ? preview.badge(document, item.priority_preview) :
                    hasSavedPriority ? node("span", "ko-priority", item.priority) : null;
                if (!previewMode && priority) {
                    priority.dataset.priority = item.priority;
                    priority.setAttribute("aria-label", `対応優先度：${item.priority}`);
                }
                const copy = node("div", "ko-proposal-copy", "");
                const heading = node("div", "ko-proposal-heading", "");
                const changed = item.feedback?.revision && item.feedback.revision !== item.proposal_revision;
                const feedback = changed ? "提案更新あり" : ({open:"未着手",accepted:"採用",in_progress:"対応中"}[item.feedback?.status] || "未着手");
                const target = text(item.target) || "確認項目";
                heading.append(node("strong", "", target));
                if (feedback !== "未着手") heading.append(node("span", "ko-badge", feedback));
                // Show saved advice verbatim. Full state, risk, timing and sources
                // remain available through the proposal-specific analysis link.
                copy.append(heading, node("p", "ko-proposal-action", text(item.action) || "提案内容を確認してください。"));
                if (!previewMode && !hasSavedPriority) {
                    row.dataset.priorityDataState = "invalid";
                    copy.append(node("p", "ko-proposal-data-state", "保存された優先度を確認できません。詳細から元の提案を確認してください。"));
                }
                if (previewMode) {
                    const p = item.priority_preview;
                    copy.append(node("p", "priority-preview-evidence", `根拠：${p.evidence_status}${p.missing_conditions.length ? ` / 確認事項 ${p.missing_conditions.length}件` : ""}`));
                }
                const action = node("a", "ko-proposal-detail", "詳細 ›");
                action.setAttribute("aria-label", `詳細：${target}の提案と対応を確認`);
                action.href = url.href;
                if (priority) row.append(priority);
                row.append(copy, action);
                list.append(row);
            }
            if (!items.length) list.append(node("li", "ko-empty", "対応済み・見送り等を除く予防整備の提案はありません。"));
            if (items.length > visibleProposalLimit) {
                const row=node("li", "", "");
                const more=node("a", "ko-action-button", `残り${items.length-visibleProposalLimit}件を分析で確認 →`);
                more.href=previewMode ? preview.url(panel.dataset.analysisUrl, window.location) : panel.dataset.analysisUrl; row.append(more); list.append(row);
            }
            status.textContent = current ? "" : `前回の提案 · ${data.status === "error" ? "更新エラー" : data.status === "running" ? "分析中" : data.status === "pending" || data.is_current === false ? "更新待ち" : "更新状態未確認"}`;
            status.hidden = current && !previewMode;
            if (previewMode) status.textContent = `${status.textContent ? status.textContent + " · " : ""}${previewResult.message} 試行値・本番未承認。低は安全確認済みではありません。根拠不足は詳細で確認し、運行可否は人が判断してください。`;
        } catch {
            if (previewMode) { list.replaceChildren(); panel.dataset.current = "false"; }
            if (summary) summary.textContent = "取得失敗";
            status.hidden = false;
            status.textContent = "分析結果を取得できませんでした。分析タブで確認してください。";
        }
    }
    load();
})();
(() => {
    "use strict";
    const form = document.querySelector("[data-note-form]");
    if (new URLSearchParams(window.location.search || "").get("priority_preview") === "1") {
        if (form) form.hidden = true;
        const editButton = document.querySelector("[data-note-edit]");
        if (editButton) editButton.hidden = true;
        return;
    }
    const edit = document.querySelector("[data-note-edit]");
    if (!form || !edit) return;
    const display = document.querySelector("[data-note-display]");
    const input = form.querySelector("textarea");
    const error = form.querySelector("[data-note-error]");
    let original = input.value;
    function close() {
        form.hidden = true;
        display.hidden = false;
        edit.hidden = false;
        edit.focus();
    }
    edit.addEventListener("click", () => {
        form.hidden = false;
        display.hidden = true;
        edit.hidden = true;
        error.hidden = true;
        const details = document.querySelector("[data-note-details]");
        if (details) details.open = true;
        input.focus();
    });
    form.querySelector("[data-note-cancel]").addEventListener("click", () => {
        input.value = original;
        close();
    });
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = form.querySelector("[type=submit]");
        button.disabled = true;
        error.hidden = true;
        try {
            const response = await fetch(form.action, {
                method:"POST", body:new FormData(form), credentials:"same-origin"
            });
            if (!response.ok) {
                const messages = {
                    400:"入力内容を確認してください。メモは10,000文字以内で入力してください。",
                    403:"編集権限がありません。", 404:"車両が見つかりません。",
                    409:"他の人がメモを更新しました。入力内容を控えてから画面を更新してください。"
                };
                throw new Error(messages[response.status] || "保存できませんでした。入力内容を残して再度お試しください。");
            }
            // A redirected sign-in page must never be treated as a successful save.
            if (!response.redirected || new URL(response.url).pathname !== new URL(form.action).pathname.replace(/\/note$/, "")) {
                throw new Error("ログイン状態を確認してください。入力内容を控えてから画面を更新してください。");
            }
            original = input.value;
            window.location.assign(response.url);
        } catch (failure) {
            error.textContent = failure.message || "通信に失敗しました。入力内容は保持されています。";
            error.hidden = false;
        } finally { button.disabled = false; }
    });
})();


(() => {
    "use strict";
    const chart=document.querySelector(".ko-monthly-chart");
    if (!chart) return;
    const buttons=[...chart.querySelectorAll("[data-cost-month]")];
    const records=[...document.querySelectorAll("[data-cost-record]")];
    const caption=document.querySelector("[data-cost-selection]");
    const empty=document.querySelector("[data-cost-empty]");
    function select(month) {
        for (const button of buttons) button.setAttribute("aria-pressed", String(button.dataset.costMonth===month));
        let count=0;
        for (const record of records) {
            record.hidden=Boolean(month && record.dataset.costRecord!==month);
            if (!record.hidden) count++;
        }
        caption.textContent=month ? `${month.replace("-","年")}月 · ${count}件` : `期間全体 · ${count}件`;
        empty.hidden=Boolean(count);
        empty.textContent=month ? "この月の整備記録はありません（支出0円を示すものではありません）" : "この期間の整備記録はありません";
    }
    buttons.forEach(button=>button.addEventListener("click",()=>select(button.dataset.costMonth)));
    document.querySelector("[data-cost-reset]")?.addEventListener("click",()=>select(null));
    select(buttons.find(button=>button.getAttribute("aria-pressed")==="true")?.dataset.costMonth || null);
})();
