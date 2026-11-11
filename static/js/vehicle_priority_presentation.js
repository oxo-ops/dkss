/* Read-only presentation of the server's versioned response-priority projection. */
((root) => {
    "use strict";
    const VERSION = "maintenance-response-priority-v1";
    const LABELS = ["高", "中", "低"];
    const AXES = {impact: "影響", timing: "対応時期", state: "状態・進行"};
    const POINTS = {impact: [0, 10, 25, 40], timing: [0, 10, 25, 35], state: [0, 10, 25]};
    const FLOORS = {operation_instruction_active: 60, manufacturer_immediate_condition: 60,
        safety_issue_open: 25, required_safety_check_not_done: 25, verified_legal_deadline_due: 60};
    const RULE_NAMES = {impact_safety: "標準点検の安全機能に関する具体的な不良回答", state_open: "元記録で未解消の指摘", safety_issue_open: "安全上の指摘の確認が必要", impact_minor: "具体的な軽度の劣化", impact_functional: "記録された機能不良", preventive_plan: "予防整備の計画", record_discrepancy: "記録の照合"};
    const FLOOR_NAMES = {operation_instruction_active: "既存の運行前確認・停止等の指示",
        manufacturer_immediate_condition: "適用できるメーカーの即時対応条件", safety_issue_open: "未解消の安全上の指摘",
        required_safety_check_not_done: "必要な安全確認の明示された未実施", verified_legal_deadline_due: "確認済みの法的期限"};
    const text = v => typeof v === "string" && v.trim().length > 0;
    const strings = v => Array.isArray(v) && v.every(text);
    const score = v => Number.isInteger(v) && v >= 0 && v <= 100;
    const unavailable = () => ({valid: false, label: null, score: null, note: "優先度のデータを確認できません。元の提案を確認してください。"});
    function read(item) {
        if (!item || typeof item !== "object") return unavailable();
        const p = item.priority_assessment;
        if (!p) return LABELS.includes(item.priority)
            ? {valid: true, label: item.priority, score: null, legacy: true, note: "保存版・算定根拠を確認"} : unavailable();
        if (p.version !== VERSION || p.method !== "maintenance-response-priority-trial-v0.1"
            || p.policy_version !== "trial-20261110" || p.policy_status !== "trial"
            || p.operation_decision !== "human_only" || p.safety_cleared !== false
            || p.candidate_id !== item.proposal_id || p.proposal_revision !== item.proposal_revision
            || !text(item.proposal_id) || !text(item.proposal_revision)
            || !strings(p.missing_conditions) || !strings(p.applicable_reference_ids)
            || !Array.isArray(p.factors) || p.factors.length !== 3 || !Array.isArray(p.applied_floors)) return unavailable();
        const axes = new Set();
        for (const f of p.factors) {
            if (!f || !Object.hasOwn(AXES, f.axis) || axes.has(f.axis)
                || !(f.points === null || POINTS[f.axis].includes(f.points))
                || !strings(f.source_ids) || !strings(f.rule_ids) || !strings(f.reference_ids)) return unavailable();
            axes.add(f.axis);
        }
        if (p.calculation_status === "legacy_preserved" || p.calculation_status === "invalid_legacy") {
            if (p.base_score !== null || p.effective_score !== null || p.floor_adjustment !== null
                || p.factors.some(f => f.points !== null) || p.applied_floors.length) return unavailable();
            if (p.calculation_status === "invalid_legacy") return unavailable();
            if (!LABELS.includes(p.label) || p.label !== item.priority) return unavailable();
            return {valid: true, label: p.label, score: null, legacy: true, assessment: p, note: "保存版・算定根拠を確認"};
        }
        if (p.calculation_status !== "computed" || !score(p.base_score) || !score(p.effective_score)
            || p.label !== item.priority || p.label !== (p.effective_score >= 60 ? "高" : p.effective_score >= 25 ? "中" : "低")
            || p.base_score !== p.factors.reduce((n, f) => n + (f.points ?? 0), 0)) return unavailable();
        for (const f of p.applied_floors) {
            if (!f || !Object.hasOwn(FLOORS, f.code) || f.minimum !== FLOORS[f.code]
                || !strings(f.source_ids) || !f.source_ids.length || !strings(f.reference_ids)) return unavailable();
        }
        if (p.effective_score !== Math.max(p.base_score, ...p.applied_floors.map(f => f.minimum))
            || p.floor_adjustment !== p.effective_score - p.base_score
            || (p.factors.some(f => f.points === null) && !p.missing_conditions.length)) return unavailable();
        return {valid: true, label: p.label, score: p.effective_score, legacy: false, assessment: p,
            note: p.missing_conditions.length ? "要確認" : "試行値"};
    }
    function ordered(items, analysis = {}) {
        const values = items.filter(item => item && typeof item === "object");
        if (Object.hasOwn(analysis, "priority_order_indices")) {
            const order = analysis.priority_order_indices;
            const indices = items.flatMap((item, index) => item && typeof item === "object" ? [index] : []);
            if (analysis.priority_order_format === "source_indices_v1" && Array.isArray(order)
                && order.length === indices.length && new Set(order).size === indices.length
                && order.every(index => Number.isInteger(index) && indices.includes(index))) {
                return order.map(index => items[index]);
            }
            return values;
        }
        if (Array.isArray(analysis.priority_order)) {
            const ids = values.map(item => item.proposal_id), order = analysis.priority_order;
            if (ids.every(text) && new Set(ids).size === ids.length && order.length === ids.length
                && new Set(order).size === ids.length && order.every(id => ids.includes(id))) {
                const byId = new Map(values.map(item => [item.proposal_id, item]));
                return order.map(id => byId.get(id));
            }
            // A partial/foreign order must not turn into a client-side score or guessed order.
            return values;
        }
        const rank = item => {const index = LABELS.indexOf(read(item).label); return index < 0 ? 3 : index;};
        return [...values].sort((a, b) => rank(a) - rank(b));
    }
    function node(doc, tag, cls, value) {
        const el = doc.createElement(tag); el.className = cls;
        if (value !== undefined) el.textContent = String(value);
        return el;
    }
    function badge(doc, item, cls = "priority-response-badge") {
        const p = read(item);
        if (!p.label) return null;
        const el = node(doc, "span", cls, p.score === null ? p.label : `${p.label} · ${p.score}点`);
        el.dataset.priority = p.label;
        el.setAttribute("aria-label", `対応優先度：${p.label}${p.score === null ? "" : `、${p.score}点`}`);
        return el;
    }
    function details(doc, item, sources = {}, origin) {
        const p = read(item), box = node(doc, "details", "priority-response-details");
        box.append(node(doc, "summary", "", "優先度の根拠・確認事項"));
        box.append(node(doc, "p", "priority-response-note", p.note));
        if (p.valid && p.assessment) {
            const a = p.assessment;
            if (!p.legacy) box.append(node(doc, "p", "", `基本点 ${a.base_score}点 / 下限適用後 ${a.effective_score}点`));
            const list = node(doc, "ul", "");
            for (const f of a.factors) {
                const basis = f.rule_ids.map(id => RULE_NAMES[id] || "適用ルールの根拠を確認").join("、");
                list.append(node(doc, "li", "", `${AXES[f.axis]}：${f.points === null ? "根拠を確認要（0点の判定ではありません）" : `${f.points}点`}${basis ? ` / ${basis}` : ""}`));
            }
            for (const f of a.applied_floors) list.append(node(doc, "li", "", `${FLOOR_NAMES[f.code]}：下限${f.minimum}点`));
            for (const message of a.missing_conditions) list.append(node(doc, "li", "", message));
            box.append(list);
            box.append(node(doc, "p", "", `根拠：${a.evidence_status || "確認要"} / 最終観測：${a.observed_at || "記録なし"} / 算定基準日：${a.as_of || "不明"}`));
            const ids = [...new Set([...a.factors.flatMap(f => f.source_ids), ...a.applied_floors.flatMap(f => f.source_ids)])];
            for (const id of ids) {
                const source = sources[id];
                if (!source || !text(source.url) || !origin) continue;
                try {
                    const url = new URL(source.url, origin);
                    if (url.origin !== origin) continue;
                    const link = node(doc, "a", "priority-response-source", source.label || id);
                    link.href = url.href; box.append(link);
                } catch (_) {}
            }
            if (a.applicable_reference_ids.length) box.append(node(doc, "p", "", `適用資料：${a.applicable_reference_ids.join("、")}`));
            box.append(node(doc, "p", "", `基準版：${a.policy_version}`));
        }
        box.append(node(doc, "p", "priority-response-disclaimer", "点数・区分境界はシステムの試行値です。故障確率や運行可否ではありません。低も安全確認済みを意味しません。運行可否・既存指示の解除は責任者が判断してください。"));
        return box;
    }
    const api = {VERSION, read, ordered, badge, details};
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    root.VehiclePriorityPresentation = api;
})(typeof window !== "undefined" ? window : globalThis);
