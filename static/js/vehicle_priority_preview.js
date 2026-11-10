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
    const TIMING_VERSION = "priority-timing-preview-v1";
    const CONDITION_VERSION = "timing-condition-view-v1";
    const RELATIONS = {single: "単独条件", all: "すべての条件（AND）", any: "いずれかの条件（OR）"};
    const UNITS = {distance_km: "km", period_days: "days", period_months: "calendar_months"};
    const UNIT_LABELS = {km: "km", days: "日", calendar_months: "暦月"};
    const DATE_BASES = {single: "single_calendar_condition", all: "all_calendar_conditions_latest", any: "any_calendar_condition_earliest"};
    const SCALE = 1000000n;
    function day(value) {
        if (typeof value !== "string" || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(value)) return null;
        const time = Date.parse(`${value}T00:00:00Z`);
        return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value ? time / 86400000 : null;
    }
    // Validate serialized decimal facts exactly, without introducing score ratios.
    function quantity(value) {
        if (typeof value !== "string" || value.length > 40) return null;
        const match = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/.exec(value);
        if (!match) return null;
        const digits = BigInt(match[2] + (match[3] || "")), exponent = Number(match[4] || 0) - (match[3]?.length || 0);
        if ((match[1] && digits !== 0n) || exponent < -6) return null;
        if (digits === 0n) return 0n;
        if (exponent > 12) return null;
        const result = digits * (10n ** BigInt(exponent + 6));
        return result <= 1000000000000n * SCALE ? result : null;
    }
    function validCondition(c, asOf) {
        if (!c || !Object.hasOwn(UNITS, c.metric) || c.unit !== UNITS[c.metric]
            || c.quantity_unit !== (c.metric === "distance_km" ? "km" : "days")
            || typeof c.threshold_reached !== "boolean") return false;
        const baseline = day(c.baseline_on), reference = day(c.reference_on), due = day(c.due_on);
        const threshold = quantity(c.threshold), elapsed = quantity(c.elapsed_quantity), remaining = quantity(c.remaining_quantity), excess = quantity(c.excess_quantity);
        if (baseline === null || reference === null || baseline > reference || reference > asOf
            || threshold === null || threshold <= 0n || elapsed === null || remaining === null || excess === null) return false;
        if (c.metric === "distance_km") {
            return c.due_on === null && c.calendar_interval_days === null
                && remaining === (threshold > elapsed ? threshold - elapsed : 0n)
                && excess === (elapsed > threshold ? elapsed - threshold : 0n)
                && c.threshold_reached === (elapsed >= threshold);
        }
        if (due === null || due <= baseline || reference !== asOf || threshold % SCALE !== 0n
            || !Number.isSafeInteger(c.calendar_interval_days) || c.calendar_interval_days !== due - baseline
            || elapsed !== BigInt(reference - baseline) * SCALE
            || remaining !== BigInt(Math.max(0, due - reference)) * SCALE
            || excess !== BigInt(Math.max(0, reference - due)) * SCALE
            || c.threshold_reached !== (reference >= due)) return false;
        if (c.metric === "period_days") return threshold === BigInt(due - baseline) * SCALE;
        // Check direct calendar-month addition and month-end clamping, never a 90% formula.
        const [by, bm, bd] = c.baseline_on.split("-").map(Number), [dy, dm, dd] = c.due_on.split("-").map(Number);
        const last = [31, dy % 4 === 0 && (dy % 100 !== 0 || dy % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][dm - 1];
        return threshold === BigInt((dy - by) * 12 + dm - bm) * SCALE && dd === Math.min(bd, last);
    }
    function validateTiming(data, items) {
        const block = message => ({status: "blocked", message: message || "条件データの版・対象・計算内容を確認できないため、条件の事実表示を取り下げています。点数・区分は別の検証結果です。", entries: new Map()});
        const meta = data?.priority_timing_conditions;
        if (meta === undefined) return {status: "absent", entries: new Map()};
        if (!meta || meta.version !== TIMING_VERSION || meta.mode !== "shadow" || meta.production_enabled !== false
            || meta.synthetic_only !== true || !string(meta.message) || !Array.isArray(meta.entries)) return block();
        if (meta.status === "absent" || meta.status === "blocked") {
            if (meta.entries.length) return block();
            return meta.status === "absent" ? {status: "absent", entries: new Map()} : block(meta.message);
        }
        const asOf = day(meta.as_of);
        if (meta.status !== "available" || !string(meta.company_code) || !Number.isSafeInteger(meta.vehicle_id)
            || meta.vehicle_id <= 0 || asOf === null || data.priority_preview?.as_of !== meta.as_of) return block();
        const proposals = new Map(items.map(item => [item.proposal_id, item])), entries = new Map();
        for (const entry of meta.entries) {
            const item = proposals.get(entry?.proposal_id);
            if (!item || entries.has(entry.proposal_id) || entry.proposal_revision !== item.proposal_revision
                || entry.version !== CONDITION_VERSION || entry.mode !== "shadow" || entry.production_enabled !== false
                || entry.scope?.company_code !== meta.company_code || entry.scope?.vehicle_id !== meta.vehicle_id
                || entry.scope?.target !== item.target || !string(entry.scope?.target)
                || entry.as_of !== meta.as_of || !string(entry.event_id) || !string(entry.rule_key)
                || typeof entry.snapshot_hash !== "string" || !/^[a-f0-9]{64}$/.test(entry.snapshot_hash)
                || !Object.hasOwn(RELATIONS, entry.relation) || !strings(entry.source_ids) || !entry.source_ids.length
                || new Set(entry.source_ids).size !== entry.source_ids.length || !strings(entry.missing_conditions)
                || typeof entry.scoring_input_emitted !== "boolean") return block();
            const group = entry.condition_group;
            if (entry.status === "calculation_unavailable") {
                if (group !== null || entry.scoring_input_emitted || !entry.missing_conditions.length) return block();
            } else {
                if (entry.status !== "verified_condition_facts" || !group || group.relation !== entry.relation || group.as_of !== entry.as_of
                    || !string(group.source_quote) || !string(group.note) || typeof group.threshold_reached !== "boolean"
                    || group.scoring_input_emitted !== entry.scoring_input_emitted || entry.scoring_input_emitted !== (entry.relation !== "all")
                    || !Array.isArray(group.conditions) || !group.conditions.length || group.conditions.length > 3
                    || (group.conditions.length === 1 ? entry.relation !== "single" : entry.relation === "single")
                    || group.conditions.some(c => !validCondition(c, asOf))
                    || new Set(group.conditions.map(c => c.metric)).size !== group.conditions.length
                    || new Set(group.conditions.map(c => c.baseline_on)).size !== 1) return block();
                const reached = entry.relation === "all" ? group.conditions.every(c => c.threshold_reached) : group.conditions.some(c => c.threshold_reached);
                if (group.threshold_reached !== reached) return block();
                if (group.conditions.some(c => c.metric === "distance_km")) {
                    if (group.calendar_threshold_on !== null || group.calendar_threshold_basis !== null) return block();
                } else {
                    const dates = group.conditions.map(c => c.due_on).sort();
                    if (group.calendar_threshold_on !== (entry.relation === "all" ? dates.at(-1) : dates[0])
                        || group.calendar_threshold_basis !== DATE_BASES[entry.relation]) return block();
                }
                if ((entry.relation === "all" || group.conditions.some(c => c.metric === "period_months")) && !entry.missing_conditions.length) return block();
            }
            entries.set(entry.proposal_id, entry);
        }
        return {status: "available", message: meta.message, entries};
    }
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
    function renderTiming(doc, entry) {
        const section = node(doc, "section", "priority-timing-preview");
        section.dataset.conditionStatus = entry.status;
        section.append(node(doc, "h5", "", "登録条件の事実表示（採点とは別）"),
            node(doc, "p", "priority-timing-disclaimer", "この条件表示は、この画面の点数・区分・並び順に連動していません。採点用入力の発行は点数への採用を意味しません。運行可否は人が判断してください。"),
            node(doc, "p", "", `条件の関係：${RELATIONS[entry.relation]} / 登録基準日：${entry.as_of}`));
        const group = entry.condition_group;
        if (!group) {
            section.append(node(doc, "p", "priority-timing-status", "条件データの状態：計算内容を確認できません。未検証の条件は表示していません。"));
        } else {
            section.append(node(doc, "p", "priority-timing-status", "条件データの状態：登録された計算結果との一致を確認（合成データ）"),
                node(doc, "p", "", `条件全体の到達状態：${group.threshold_reached ? "到達済み" : "未到達"}（登録された各記録基準日時点）`),
                node(doc, "h6", "", "原文条件"), node(doc, "p", "priority-timing-source-quote", group.source_quote));
            const conditions = node(doc, "ol", "priority-timing-conditions");
            for (const c of group.conditions) {
                const row = node(doc, "li", "priority-timing-condition"), unit = UNIT_LABELS[c.quantity_unit];
                row.append(node(doc, "p", "", `条件値：${c.threshold} ${UNIT_LABELS[c.unit]} / 到達状態：${c.threshold_reached ? "到達済み" : "未到達"}`),
                    node(doc, "p", "", `起算日：${c.baseline_on} / 記録基準日：${c.reference_on}`),
                    node(doc, "p", "", `経過量：${c.elapsed_quantity} ${unit} / 残量：${c.remaining_quantity} ${unit} / 超過量：${c.excess_quantity} ${unit}`));
                if (c.due_on !== null) row.append(node(doc, "p", "", `条件の算出日：${c.due_on} / 起算日から算出日まで：${c.calendar_interval_days} 日`));
                else row.append(node(doc, "p", "", "距離条件の実際の到達日は推定していません。"));
                conditions.append(row);
            }
            section.append(conditions);
            if (group.calendar_threshold_on !== null) {
                const basis = entry.relation === "all" ? "全条件の最も遅い算出日" : entry.relation === "any" ? "いずれかの条件の最も早い算出日" : "単独条件の算出日";
                section.append(node(doc, "p", "", `条件全体の暦上の成立日：${group.calendar_threshold_on}（${basis}。法定期限ではありません）`));
            } else section.append(node(doc, "p", "", "距離を含むため、条件全体の暦上の成立日は算出していません。"));
            section.append(node(doc, "p", "", group.note));
        }
        if (entry.missing_conditions.length) {
            section.append(node(doc, "h6", "", "条件・採点方法の確認事項"));
            const gaps = node(doc, "ul", "priority-timing-gaps");
            for (const missing of entry.missing_conditions) gaps.append(node(doc, "li", "", missing));
            section.append(gaps);
        }
        section.append(node(doc, "p", "priority-timing-provenance", `対象：${entry.scope.target} / 会社：${entry.scope.company_code} / 車両：${entry.scope.vehicle_id} / 事象：${entry.event_id} / 基準：${entry.rule_key}`),
            node(doc, "p", "priority-timing-provenance", `出典ID：${entry.source_ids.join("、")} / スナップショット：${entry.snapshot_hash}`));
        return section;
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
        const timing = validateTiming(data, result.items);
        if (timing.status === "blocked") {
            const blocked = node(doc, "p", "priority-timing-status priority-preview-warning", `条件データの状態：表示不可。${timing.message}`);
            blocked.dataset.conditionStatus = "blocked";
            section.append(blocked);
        }
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
            card.append(gaps);
            if (timing.entries.has(item.proposal_id)) card.append(renderTiming(doc, timing.entries.get(item.proposal_id)));
            card.append(node(doc, "p", "priority-preview-disclaimer", p.disclaimer));
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
    root.VehiclePriorityPreview = {METHOD, TIMING_VERSION, CONDITION_VERSION, enabled, url, validate, validateTiming, badge, render, mountAnalysis};
    if (typeof module !== "undefined") module.exports = root.VehiclePriorityPreview;
})(typeof window !== "undefined" ? window : globalThis);
