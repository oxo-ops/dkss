(function () {
    "use strict";
    const root = document.getElementById("importFlow");
    if (!root) return;
    const panel = document.getElementById("importFlowError");
    const errorList = panel.querySelector("[data-import-flow-errors]");
    const cancelForm = document.getElementById("importFlowCancel");
    const toolbar = root.querySelector("[data-import-flow-toolbar]");
    const requests = new Set();
    let cancelling = false;
    let dismissed = false;
    let activeForm = null;
    let returnPosition = null;
    const onEntry = root.dataset.entry === "1";
    document.addEventListener("submit", event => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || form === cancelForm) return;
        if (!isImport(form.action) && form.id !== "certificate-upload-form") return;
        activeForm = form;
        returnPosition = {x: window.scrollX, y: window.scrollY};
        dismissed = false;
        panel.hidden = true;
    }, true);
    function selectedForm() {
        return activeForm || Array.from(document.querySelectorAll("form")).find(form =>
            Array.from(form.querySelectorAll('input[type="file"]')).some(input => input.files?.length));
    }
    function resetEntry() {
        const form = selectedForm();
        if (form?.id === "certificate-upload-form") {
            document.getElementById("certificate-back-button")?.click();
            document.getElementById("certificate-clear")?.click();
        }
        if (form) {
            delete form.dataset.loading;
            delete form.dataset.uploadKey;
            form.removeAttribute("aria-busy");
            form.querySelectorAll('input[type="file"]').forEach(input => {
                input.disabled = false;
                input.value = "";
                input.removeAttribute("aria-invalid");
                input.dispatchEvent(new Event("change", {bubbles: true}));
            });
            form.querySelectorAll('.import-error, #certificate-error').forEach(box => {
                box.textContent = "";
                box.hidden = true;
            });
        }
        window.clearCommonErrors?.();
        panel.hidden = true;
        toolbar.hidden = true;
        errorList.replaceChildren();
        const pos = returnPosition || {x: 0, y: 0};
        window.requestAnimationFrame(() => {
            window.scrollTo({left: pos.x, top: pos.y, behavior: "instant"});
            form?.querySelector('input[type="file"]')?.focus({preventScroll: true});
        });
    }
    function isImport(url) {
        try {
            const target = new URL(url, location.href);
            return target.origin === location.origin && /^\/(vehicle\/(data-import|operation-import)|master\/vehicles\/(import|certificate|new))(\/|$)/.test(target.pathname);
        } catch (_) { return false; }
    }
    function report(messages, code) {
        if (cancelling || dismissed) return;
        const values = [...new Set(messages.filter(Boolean).map(String))];
        if (!values.length) return;
        const duplicate = values.some(message => /登録済み|すでに登録|既に登録|重複|同じ原本/.test(message));
        panel.querySelector("[data-import-flow-title]").textContent = duplicate ? "登録済みの資料・記録があります" : "取り込み内容を確認してください";
        const duplicateGuide = document.querySelector('input[name="include"]')
            ? "重複する項目を外して未登録分だけ続けるか、キャンセルして取込画面へ戻れます。"
            : document.getElementById("certificate-review") && !document.getElementById("certificate-review").hidden
                ? "既存の車両を再登録する必要はありません。内容を確認・修正するか、キャンセルして取込画面へ戻れます。"
                : "同じ資料を再登録する必要はありません。別のファイルを選ぶか、キャンセルして取込画面へ戻れます。";
        panel.querySelector("[data-import-flow-guide]").textContent = duplicate
            ? "他の利用者が登録したものも含め、同じ会社の登録済みデータを確認しています。" + duplicateGuide
            : code === "network" ? "通信が中断しました。登録が完了している場合もあるため、元の画面で受付・登録結果を確認してから再試行してください。"
            : "入力内容やファイルを確認して続けるか、キャンセルして取込画面へ戻れます。";
        errorList.replaceChildren(...values.slice(0, 30).map(message => { const item = document.createElement("li"); item.textContent = message; return item; }));
        if (onEntry) panel.querySelector("[data-import-flow-guide]").textContent = duplicate
            ? "同じ会社で登録済みの資料です。他の利用者による登録も含みます。別のファイルを選ぶか、キャンセルで今回の選択を解除できます。"
            : "この取込画面でファイルを選び直せます。キャンセルで今回の選択とエラー表示を解除できます。";
        panel.hidden = false;
        toolbar.hidden = onEntry;
        panel.querySelector("[data-import-flow-login]").hidden = code !== "login";
    }
    function safeMessages(data) {
        return Array.isArray(data?.errors) ? data.errors.map(item => item.message) : data?.error ? [data.error] : [];
    }
    window.DKSSImportFlow = {report};
    if (typeof window.showCommonError === "function") {
        const original = window.showCommonError;
        window.showCommonError = function (message, ...args) {
            const result = original.call(this, message, ...args);
            report([message]);
            return result;
        };
    }
    document.querySelectorAll(".import-error, #certificate-error").forEach(box => {
        new MutationObserver(() => {
            if (dismissed && box.textContent.trim()) { box.textContent = ""; box.hidden = true; return; }
            if (!box.hidden && box.textContent.trim()) report([box.textContent.trim()]);
        })
            .observe(box, {childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ["hidden"]});
    });
    const originalFetch = window.fetch;
    window.fetch = async function (input, options) {
        const url = typeof input === "string" || input instanceof URL ? String(input) : input.url;
        const method = (options?.method || input?.method || "GET").toUpperCase();
        if (method !== "POST" || !isImport(url)) return originalFetch.call(this, input, options);
        const controller = new AbortController();
        const signal = options?.signal || (typeof input === "object" ? input.signal : null);
        const abort = () => controller.abort();
        if (signal?.aborted) controller.abort();
        else signal?.addEventListener("abort", abort, {once: true});
        const timeout = window.setTimeout(abort, 90000);
        requests.add(controller);
        toolbar.hidden = false;
        try {
            const response = await originalFetch.call(this, input, {...options, signal: controller.signal});
            if (response.redirected && new URL(response.url).pathname === "/login") report(["ログインの有効期限が切れています。"], "login");
            else if (!response.ok) {
                const data = await response.clone().json().catch(() => null);
                report(safeMessages(data).length ? safeMessages(data) : ["サーバーから処理結果を確認できませんでした。"], response.status === 401 || response.status === 403 ? "login" : "server");
            }
            return response;
        } catch (error) { report(["通信が中断、または時間切れになりました。"], "network"); throw error; }
        finally { clearTimeout(timeout); requests.delete(controller); signal?.removeEventListener("abort", abort); }
    };
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url, ...args) {
        this.dkssImportRequest = String(method).toUpperCase() === "POST" && isImport(String(url));
        return originalOpen.call(this, method, url, ...args);
    };
    XMLHttpRequest.prototype.send = function (...args) {
        if (this.dkssImportRequest) {
            requests.add(this);
            toolbar.hidden = false;
            this.addEventListener("load", () => {
                if (this.status >= 400) {
                    let data; try { data = JSON.parse(this.responseText); } catch (_) { data = null; }
                    report(safeMessages(data).length ? safeMessages(data) : ["サーバーから処理結果を確認できませんでした。"]);
                } else if (this.responseURL && new URL(this.responseURL).pathname === "/login") report(["ログインの有効期限が切れています。"], "login");
            });
            for (const event of ["timeout", "error"]) this.addEventListener(event, () => report(["通信が中断、または時間切れになりました。"], "network"));
            this.addEventListener("loadend", () => requests.delete(this));
        }
        return originalSend.apply(this, args);
    };
    let leftWhileSending = false;
    window.addEventListener("pagehide", () => {
        leftWhileSending = requests.size > 0;
        for (const pending of requests) pending.abort();
    });
    window.addEventListener("pageshow", event => {
        if (event.persisted && leftWhileSending) report(["前の送信を中断しました。受付・登録結果を確認してから続けてください。"], "network");
    });
    root.querySelectorAll("[data-import-flow-cancel]").forEach(button => button.addEventListener("click", () => {
        if (cancelling) return;
        cancelling = true;
        dismissed = true;
        for (const request of requests) request.abort();
        if (onEntry) {
            // Already on the intake screen: restore it without a self-redirect.
            window.setTimeout(() => { resetEntry(); cancelling = false; }, 0);
            return;
        }
        root.querySelectorAll("button").forEach(control => control.disabled = true);
        // Leave through a POST: pending drafts are cancelled without touching registered data.
        cancelForm.requestSubmit();
    }));
    root.querySelector("[data-import-flow-continue]").addEventListener("click", () => {
        panel.hidden = true;
        if (onEntry) {
            const input = selectedForm()?.querySelector('input[type="file"]:not([disabled])');
            input?.click();
            return;
        }
        const field = document.querySelector('[aria-invalid="true"]:not([disabled]), .form-control-error:not([disabled])');
        if (field) { field.focus(); field.scrollIntoView({block: "center"}); }
        else document.querySelector('input[type="file"]:not([disabled]), input:not([type="hidden"]):not([disabled])')?.focus();
    });
    if (document.getElementById("importFlowErrorPage")) root.querySelector("[data-import-flow-continue]").hidden = true;
    if (!panel.hidden) report(Array.from(errorList.children).map(item => item.textContent));
})();
