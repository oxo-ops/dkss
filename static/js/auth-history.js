/* History defense in depth; server authorization remains authoritative. */
(function () {
    "use strict";
    const body = document.body;
    if (!body || body.dataset.authenticated !== "true") return;
    // Capture the browser's effective initial selection, not the HTML selected
    // attributes: a single select implicitly selects its first eligible option.
    const initialSelections = new WeakMap();
    Array.from(body.querySelectorAll("select")).forEach(function (field) {
        initialSelections.set(field, Array.from(field.options).map(option => ({
            option: option, selected: option.selected
        })));
    });
    function conceal() {
        body.classList.add("auth-history-concealed");
        body.setAttribute("inert", "");
    }
    window.addEventListener("pagehide", conceal);
    let restoring = false;
    window.addEventListener("pageshow", function (event) {
        if (!event.persisted || restoring) return;
        restoring = true;
        conceal();
        const dirty = Array.from(body.querySelectorAll("input, textarea, select")).some(function (field) {
            if (field.type === "hidden" || field.type === "submit" || field.type === "button") return false;
            if (field.type === "checkbox" || field.type === "radio") return field.checked !== field.defaultChecked;
            if (field.tagName === "SELECT") {
                const initial = initialSelections.get(field);
                const current = Array.from(field.options);
                // Dynamically introduced or replaced options have no trusted
                // initial baseline. Preserve them behind the discard choice.
                return !initial || current.length !== initial.length || current.some((option, index) =>
                    option !== initial[index].option || option.selected !== initial[index].selected);
            }
            return field.value !== field.defaultValue;
        });
        // The generic recovery notice is outside the concealed/inert body.
        // Never reveal or copy restored fields before fresh authorization.
        const notice = document.createElement("section");
        notice.className = "auth-history-notice";
        notice.setAttribute("role", "alertdialog");
        notice.setAttribute("aria-label", "画面の安全確認");
        const text = document.createElement("p");
        const initial = dirty
            ? "以前の入力が残っているため、画面を隠しています。未保存の入力を破棄して、現在の利用者の画面を開いてください。"
            : "以前の画面を隠しています。現在のログイン状態を確認して画面を開き直します。";
        text.textContent = initial;
        const button = document.createElement("button");
        button.textContent = dirty ? "未保存の入力を破棄して開く" : "もう一度確認して開く";
        async function navigate() {
            button.disabled = true;
            const controller = new AbortController();
            const timeout = window.setTimeout(() => controller.abort(), 8000);
            try {
                // HEAD is only a reachability check, never an auth decision.
                // The subsequent GET must independently authorize the current user.
                const response = await fetch(window.location.href, {
                    method: "HEAD", cache: "no-store", credentials: "same-origin",
                    signal: controller.signal
                });
                if (response.status >= 500) throw new Error("unavailable");
                // Unlike reload(), replace() cannot resubmit a prior POST body.
                window.location.replace(window.location.href);
            } catch (_) {
                text.textContent = "接続を確認できませんでした。以前の画面は表示せずに保護しています。通信が戻ったら、下のボタンで再試行してください。";
            } finally {
                window.clearTimeout(timeout);
                button.disabled = false;
            }
        }
        button.addEventListener("click", navigate);
        notice.append(text, button);
        document.documentElement.appendChild(notice);
        button.focus();
        if (!dirty) navigate();
    });
}());
