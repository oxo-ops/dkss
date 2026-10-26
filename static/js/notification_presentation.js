/* Notification presentation only: no requests, storage or workflow changes. */
(function () {
    "use strict";
    const plannerPrefix = /^点検予定の確認[：:]\s*/u;
    function compact(el, convert) {
        if (!el) return;
        const original = el.textContent.trim();
        const label = convert(original);
        if (!label || label === original) return;
        el.dataset.notificationOriginalLabel = original;
        el.title = original;
        el.textContent = label;
    }
    function messageParts(value) {
        // Use explicit source bullets only. Never infer a vehicle, due date or status.
        if (!value || /\[\[|https?:\/\//u.test(value)) return null;
        const lines = value.replace(/\r\n/g, "\n")
            .split(/\n|(?<=。)\s+(?=・)/u).map(x => x.trim()).filter(Boolean);
        if (!lines.some(x => /^・.+?\s+[/／]\s+/u.test(x))) return null;
        return lines.map(text => {
            if (!/^・.+?\s+[/／]\s+/u.test(text)) return { text };
            const fields = text.slice(1).split(/\s+[/／]\s+/u);
            return { text, fields };
        });
    }
    function formatMessage(el, summary) {
        if (!el || (el.dataset.notificationFormatted === "true" && el.querySelector(":scope > .np-record"))) return;
        // Preserve existing mention chips, links and attachments as rendered by base.js.
        if (el.querySelector('a,.mention-chip,[data-user-id]')) return;
        const original = el.dataset.value || el.textContent;
        const parts = messageParts(original);
        if (!parts) return;
        const fragment = document.createDocumentFragment();
        const ordered = summary
            ? parts.filter(x => x.fields).concat(parts.filter(x => !x.fields))
            : parts;
        ordered.forEach(part => {
            const line = document.createElement("span");
            line.className = part.fields ? "np-record" : "np-paragraph";
            if (part.fields) {
                const target = document.createElement("span");
                target.className = "np-target";
                target.textContent = part.fields[0];
                line.appendChild(target);
                part.fields.slice(1).forEach(text => {
                    const field = document.createElement("span");
                    field.className = "np-field";
                    field.textContent = text;
                    line.appendChild(field);
                });
            } else line.textContent = part.text;
            fragment.appendChild(line);
        });
        el.dataset.notificationOriginalMessage = original;
        el.dataset.notificationFormatted = "true";
        el.classList.add(summary ? "np-summary" : "np-full-message");
        el.replaceChildren(fragment);
    }
    function enhance(root) {
        root.querySelectorAll('.notification-row,.notification-popover-item').forEach(row => {
            const title = row.querySelector('.notification-title,.notification-popover-title');
            // Restrict abbreviated wording to this known generated notification family.
            const original = title?.dataset.notificationOriginalLabel || title?.textContent.trim() || "";
            if (!plannerPrefix.test(original)) return;
            compact(title, text => {
                const shortened = text.replace(plannerPrefix, "").trim();
                // Keep the purpose when the remaining text is only a count.
                return !shortened || /^\d+\s*件$/u.test(shortened) ? text : shortened;
            });
            compact(row.querySelector('.notification-kind-label,.notification-popover-meta'), text =>
                text.replace('点検予定・実施確認', '点検'));
            compact(row.querySelector('.notification-state-tag,.notification-popover-workflow'), text =>
                text.replace(/^点検予定の確認待ち/u, '確認待ち'));
            formatMessage(row.querySelector('.notification-message,.notification-popover-message'), true);
        });
        root.querySelectorAll('.dkss-notification-detail').forEach(detail => {
            const title = detail.querySelector('.nd-title');
            if (!plannerPrefix.test(title?.textContent.trim() || "")) return;
            // Full original heading and all message content remain in the detail.
            detail.querySelectorAll('.nd-message').forEach(el => formatMessage(el, false));
        });
    }
    function start() {
        document.querySelectorAll('#notificationListPane,#notificationDetailPane,#notificationPopover').forEach(root => {
            enhance(root);
            new MutationObserver(() => enhance(root)).observe(root, {childList: true, subtree: true});
        });
        // Direct detail route is also supported, without observing unrelated page content.
        document.querySelectorAll('.main-content > .dkss-notification-detail').forEach(detail => enhance(detail.parentElement));
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
