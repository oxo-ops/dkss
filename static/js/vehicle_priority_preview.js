/* Non-production, read-only display. Scores are supplied by the trusted server only. */
((root) => {
    "use strict";
    const METHOD = "maintenance-response-priority-trial-v0.1";
    const AXES = {impact: "影響", timing: "時期", state: "現在状態・進行"};
    const POINTS = {impact: [0, 10, 25, 40], timing: [0, 10, 25, 35], state: [0, 10, 25]};
    const FLOORS = {operation_instruction_active: 60, manufacturer_immediate_condition: 60,
        safety_issue_open: 25, required_safety_check_not_done: 25, verified_legal_deadline_due: 60};
    const FLOOR_LABELS = {
        operation_instruction_active: "有効な運行停止・制限指示",
        manufacturer_immediate_condition: "メーカーの即時対応条件",
        safety_issue_open: "未解消の安全上の指摘",
        required_safety_check_not_done: "必要な安全点検が未実施",
        verified_legal_deadline_due: "確認済みの法定期限に到達"
    };
    const string = v => typeof v === "string" && v.trim().length > 0;
    const strings = v => Array.isArray(v) && v.every(string);
    const score = v => Number.isInteger(v) && v >= 0 && v <= 100;
    const enabled = location => new URLSearchParams(location.search || "").get("priority_preview") === "1";
    function url(value, location) {
        const result = new URL(value, location.href || location.origin);
        if (result.origin !== location.origin) throw new Error("取得先を確認できません。");
        result.searchParams.set("priority_preview", "1");
        return result.href;
    }
    function validate(data) {
        const block = message => ({available: false, message: message || "試行表示を確認できません。入力・紐付け・閲覧条件を確認してください。", items: []});
        const meta = data?.priority_preview;
        if (!data?.ok || meta?.mode !== "shadow" || meta.production_enabled !== false || meta.synthetic_only !== true) return block();
        if (meta.status === "blocked") return block(string(meta.message) ? meta.message : undefined);
        const analysis = data.analysis;
        if (meta.status !== "available" || !string(meta.message) || !data.has_result
            || analysis?.priority_preview_contract !== METHOD || analysis.priority_preview_production_enabled !== false
            || !Array.isArray(analysis.recommendations) || !strings(analysis.priority_preview_order)) return block();
        const items = analysis.recommendations, ids = new Set();
        for (const item of items) {
            const p = item?.priority_preview;
            if (!string(item?.proposal_id) || !string(item.proposal_revision) || ids.has(item.proposal_id)
                || !p || p.candidate_id !== item.proposal_id || p.method !== METHOD || p.policy_status !== "trial" || p.policy_version !== "trial-20261110"
                || p.production_enabled !== false || p.operation_decision !== "human_only" || !string(p.disclaimer)
                || !score(p.base_score) || !score(p.effective_score)
                || p.label !== (p.effective_score >= 60 ? "高" : p.effective_score >= 25 ? "中" : "低")
                || !["記録不一致", "根拠不足", "一部確認要", "根拠あり"].includes(p.evidence_status)
                || !strings(p.missing_conditions) || !Array.isArray(p.factors) || p.factors.length !== 3
                || !Array.isArray(p.applied_floors)) return block();
            const axes = new Set();
            for (const f of p.factors) {
                if (!f || !Object.hasOwn(AXES, f.axis) || axes.has(f.axis)
                    || !(f.points === null || POINTS[f.axis].includes(f.points))
                    || !strings(f.source_ids) || !strings(f.reference_ids)) return block();
                axes.add(f.axis);
            }
            for (const f of p.applied_floors) {
                if (!f || !Object.hasOwn(FLOORS, f.code) || f.minimum !== FLOORS[f.code]
                    || !strings(f.source_ids) || !f.source_ids.length || !strings(f.reference_ids)) return block();
            }
            if (p.base_score !== p.factors.reduce((sum, f) => sum + (f.points ?? 0), 0)
                || p.effective_score !== Math.max(p.base_score, ...p.applied_floors.map(f => f.minimum))
                || (p.factors.some(f => f.points === null) && !p.missing_conditions.length)) return block();
            ids.add(item.proposal_id);
        }
        const order = analysis.priority_preview_order;
        if (order.length !== ids.size || new Set(order).size !== ids.size || order.some(id => !ids.has(id))) return block();
        const byId = new Map(items.map(item => [item.proposal_id, item]));
        return {available: true, items: order.map(id => byId.get(id)), message: meta.message};
    }
    function node(doc, tag, className, text) {
        const element = doc.createElement(tag);
        element.className = className;
        if (text !== undefined) element.textContent = String(text);
        return element;
    }
    function badge(doc, p, className = "priority-preview-badge") {
        const el = node(doc, "span", className, `${p.label} · ${p.effective_score}点`);
        el.dataset.priority = p.label;
        el.setAttribute("aria-label", `試行対応優先度：${p.label}、${p.effective_score}点`);
        return el;
    }
    function render(doc, data) {
        const section = node(doc, "section", "priority-preview");
        const result = validate(data);
        section.append(node(doc, "h3", "", "対応優先度の試行表示（読み取り専用）"),
            node(doc, "p", "", "本番利用は未承認です。点数・区分境界はシステムの試行値で、公的・メーカー規定や故障確率ではありません。低は安全確認済みを意味しません。運行可否は人が判断してください。"));
        if (!result.available) {
            section.append(node(doc, "p", "priority-preview-blocker", result.message));
            return section;
        }
        section.append(node(doc, "p", "priority-preview-context", result.message));
        if (data.is_current !== true || data.status !== "completed") section.append(node(doc, "p", "priority-preview-warning", "前回入力の試行表示です。入力の最新性を確認してください。"));
        for (const item of result.items) {
            const p = item.priority_preview, card = node(doc, "article", "priority-preview-card");
            card.id = `proposal=${encodeURIComponent(item.proposal_id)}`;
            card.dataset.proposalId = item.proposal_id;
            card.dataset.proposalRevision = item.proposal_revision;
            card.append(node(doc, "h4", "", item.target || "確認項目"), badge(doc, p),
                node(doc, "p", "", `現在の状態：${item.current_state || item.reason || "元の状態記載なし"}`),
                node(doc, "p", "", `対応：${item.action || "元の対応記載なし"}`),
                node(doc, "p", "", `記録上の対応状況：${item.feedback?.status || "open"}${item.feedback?.revision && item.feedback.revision !== item.proposal_revision ? "（旧版の対応記録）" : ""}`),
                node(doc, "p", "", `基礎点 ${p.base_score}点 / 適用後 ${p.effective_score}点`));
            const breakdown = node(doc, "ul", "priority-preview-factors");
            for (const f of p.factors) breakdown.append(node(doc, "li", "", `${AXES[f.axis]}：${f.points === null ? "根拠確認が必要（加点なし）" : `${f.points}点`} / 記録：${f.source_ids.join("、") || "なし"} / 参照：${f.reference_ids.join("、") || "なし"}`));
            for (const f of p.applied_floors) breakdown.append(node(doc, "li", "", `最低区分の適用：${FLOOR_LABELS[f.code]} / ${f.minimum}点 / 記録：${f.source_ids.join("、")} / 参照：${f.reference_ids.join("、") || "なし"}`));
            card.append(breakdown, node(doc, "h5", "", `根拠の確認状況：${p.evidence_status}`));
            const gaps = node(doc, "ul", "priority-preview-gaps");
            for (const condition of p.missing_conditions) gaps.append(node(doc, "li", "", condition));
            card.append(gaps, node(doc, "p", "priority-preview-disclaimer", p.disclaimer));
            section.append(card);
        }
        if (!result.items.length) section.append(node(doc, "p", "", "保存済みの提案はありません。"));
        return section;
    }
    // An isolated GET-only loader prevents existing feedback/event handlers from being installed.
    function mountAnalysis({doc, location, status, results, fetcher}) {
        let busy = false, timer, linkedProposalOpened = false;
        async function refresh() {
            clearTimeout(timer);
            if (busy || doc.hidden) return;
            busy = true;
            results.setAttribute("aria-busy", "true");
            try {
                const response = await fetcher(url(status.dataset.url, location), {method: "GET", credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(15000)});
                if (!response.ok || response.redirected) throw new Error();
                const data = await response.json();
                results.replaceChildren(render(doc, data));
                status.textContent = validate(data).available ? "試行表示・読み取り専用" : "試行表示を利用できません";
                if (!linkedProposalOpened && location.hash?.startsWith("#proposal=")) {
                    const target = doc.getElementById(location.hash.slice(1));
                    if (target) { target.scrollIntoView?.(); linkedProposalOpened = true; }
                }
            } catch {
                results.replaceChildren(render(doc, null));
                status.textContent = "試行表示を取得できません。前回の点数は表示していません。";
            } finally {
                status.hidden = false; results.hidden = false; busy = false;
                results.setAttribute("aria-busy", "false");
                if (!doc.hidden) timer = setTimeout(refresh, 60000);
            }
        }
        doc.addEventListener("visibilitychange", () => { clearTimeout(timer); if (!doc.hidden) refresh(); });
        refresh();
        return {refresh};
    }
    root.VehiclePriorityPreview = {METHOD, enabled, url, validate, badge, render, mountAnalysis};
    if (typeof module !== "undefined") module.exports = root.VehiclePriorityPreview;
})(typeof window !== "undefined" ? window : globalThis);
