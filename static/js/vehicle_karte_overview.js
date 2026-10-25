(() => {
    "use strict";
    const panel = document.getElementById("ko-ai");
    if (!panel?.dataset.resultUrl) return;
    const status = panel.querySelector("[data-ko-ai-status]");
    const list = panel.querySelector("[data-ko-ai-list]");
    const node = (tag, className, text) => {
        const el = document.createElement(tag);
        el.className = className;
        el.textContent = String(text ?? "");
        return el;
    };
    async function load() {
        try {
            const response = await fetch(panel.dataset.resultUrl, {
                credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(15000)
            });
            if (response.redirected || !response.ok) throw new Error();
            const data = await response.json();
            if (!data.ok) throw new Error();
            const current = data.status === "completed" && data.is_current === true;
            const state = data.status === "error" ? "更新に失敗" :
                data.status === "running" ? "分析更新中" :
                data.status === "pending" || data.is_current === false ? "更新待ち" :
                current ? "登録内容に対応する分析" : "更新状態を未確認";
            list.replaceChildren();
            if (!data.has_result || !Array.isArray(data.analysis?.recommendations)) {
                status.textContent = data.status === "error" ? "分析結果を取得できません。分析タブで確認してください。" :
                    data.status === "running" || data.status === "pending" ? "初回の分析結果を待っています。" : "保存済みの分析結果はまだありません。";
                return;
            }
            status.textContent = `${state}${data.generated_at ? " · 分析 " + data.generated_at : ""}${current ? "" : " · 前回結果"}`;
            const priorities = {"高": 0, "中": 1, "低": 2};
            const items = data.analysis.recommendations.filter(item => item && typeof item === "object" &&
                item.category !== "記録確認" && !(item.feedback?.revision === item.proposal_revision &&
                ["completed", "dismissed"].includes(item.feedback?.status)))
                .sort((a, b) => (priorities[a.priority] ?? 3) - (priorities[b.priority] ?? 3));
            for (const item of items.slice(0, 3)) {
                const row = node("li", "ko-action-row", "");
                if (item.proposal_id) row.dataset.proposalId = String(item.proposal_id);
                const heading = node("div", "ko-row-heading", "");
                const link = node("a", "", item.target || "確認項目");
                const url = new URL(panel.dataset.analysisUrl, window.location.origin);
                if (url.origin !== window.location.origin) throw new Error();
                if (item.proposal_id) url.hash = `proposal=${item.proposal_id}`;
                link.href = url.href;
                const changed = item.feedback?.revision && item.feedback.revision !== item.proposal_revision;
                const feedback = changed ? "提案更新あり" : ({open:"未着手",accepted:"採用",in_progress:"対応中",completed:"完了",dismissed:"見送り"}[item.feedback?.status] || "未着手");
                heading.append(link, node("span", "ko-badge", feedback));
                row.append(heading);
                row.append(node("p", "ko-meta", `状態：${item.current_state || "記録不足"}`));
                row.append(node("p", "", item.action || "分析タブで提案内容を確認してください。"));
                row.append(node("p", "ko-meta", `想定される影響：${typeof item.risk === "string" && item.risk.trim() ? item.risk : "未評価"}`));
                row.append(node("p", "ko-meta", `時期：${item.timing || "未評価"}${current ? "" : " · 最新の記録を確認してください"}`));
                list.append(row);
            }
            if (!items.length) {
                const message = data.analysis.recommendations.length ?
                    "対応済み・見送り等を除く予防整備候補はありません。" : "保存済みの分析結果に対応候補はありません。";
                list.append(node("li", "ko-empty", message));
            } else if (items.length > 3) {
                const more = node("a", "ko-state-footer", `残り${items.length - 3}件を分析で確認 ›`);
                more.href = panel.dataset.analysisUrl;
                const row = node("li", "", ""); row.append(more); list.append(row);
            }
        } catch {
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
