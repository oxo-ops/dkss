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
    function fact(label, value) {
        const row = node("div", "ko-proposal-fact", "");
        row.append(node("span", "", label), node("span", "", value));
        return row;
    }
    async function load() {
        try {
            const response = await fetch(panel.dataset.resultUrl, {
                credentials:"same-origin", cache:"no-store", signal:AbortSignal.timeout(15000)
            });
            if (response.redirected || !response.ok) throw new Error();
            const data = await response.json();
            if (!data.ok) throw new Error();
            const current = data.status === "completed" && data.is_current === true;
            list.replaceChildren();
            if (!data.has_result || !Array.isArray(data.analysis?.recommendations)) {
                summary.textContent = "未取得";
                status.textContent = data.status === "error" ? "分析結果を取得できません。分析タブで確認してください。" :
                    ["running","pending"].includes(data.status) ? "初回の分析結果を待っています。" : "保存済みの分析結果はまだありません。";
                return;
            }
            const priorities = {"高":0,"中":1,"低":2};
            const items = data.analysis.recommendations.filter(item => item && typeof item === "object" &&
                item.category !== "記録確認" && !(item.feedback?.revision === item.proposal_revision &&
                ["completed","dismissed"].includes(item.feedback?.status)))
                .sort((a,b) => (priorities[a.priority] ?? 3) - (priorities[b.priority] ?? 3));
            summary.textContent = `${items.length}件`;
            panel.dataset.current = String(current);
            for (const item of items.slice(0,3)) {
                const url = new URL(panel.dataset.analysisUrl, window.location.origin);
                if (url.origin !== window.location.origin) throw new Error();
                if (item.proposal_id) url.hash = `proposal=${encodeURIComponent(item.proposal_id)}`;
                const row = node("li", "ko-proposal", "");
                if (item.proposal_id) row.dataset.proposalId = String(item.proposal_id);
                const heading = node("div", "ko-proposal-heading", "");
                const badges = node("div", "ko-proposal-badges", "");
                const changed = item.feedback?.revision && item.feedback.revision !== item.proposal_revision;
                const feedback = changed ? "提案更新あり" : ({open:"未着手",accepted:"採用",in_progress:"対応中"}[item.feedback?.status] || "未着手");
                badges.append(node("span", "ko-badge ko-attention", text(item.timing) || "時期未評価"), node("span", "ko-badge", feedback));
                heading.append(node("strong", "", text(item.target) || "確認項目"), badges);
                row.append(heading, node("div", "ko-proposal-action", text(item.action) || "提案内容を確認"));
                row.append(fact("状態", text(item.current_state) || "状態を判断できる記録が不足しています。"));
                row.append(fact("懸念", text(item.risk) || "影響は未評価です。"));
                const footer = node("div", "ko-proposal-footer", "");
                const priority = node("span", "ko-badge ko-priority", `対応優先度：${["高","中","低"].includes(item.priority) ? item.priority : "未評価"}`);
                priority.dataset.priority = item.priority || "";
                const action = node("a", "ko-primary-action", "対応を確認 →");
                action.href = url.href;
                footer.append(priority, action);
                row.append(footer);
                list.append(row);
            }
            if (!items.length) list.append(node("li", "ko-empty", "対応済み・見送り等を除く予防整備の提案はありません。"));
            if (items.length > 3) {
                const row=node("li", "", "");
                const more=node("a", "ko-action-button", `残り${items.length-3}件を分析で確認 →`);
                more.href=panel.dataset.analysisUrl; row.append(more); list.append(row);
            }
            status.textContent = current ? "" : `前回の提案 · ${data.status === "error" ? "更新エラー" : data.status === "running" ? "分析中" : data.status === "pending" || data.is_current === false ? "更新待ち" : "更新状態未確認"}`;
            status.hidden = current;
        } catch {
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
