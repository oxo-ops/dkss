(() => {
    const form = document.getElementById("dkss-login-form");
    if (!form) return;

    const companyInput = form.querySelector(
        'input[name="company_code"]'
    );
    const companyStorageKey = "dkss.login.company_code";

    if (companyInput) {
        try {
            if (!companyInput.value.trim()) {
                companyInput.value =
                    localStorage.getItem(companyStorageKey) || "";
            }
        } catch {
            // 保存できない環境でもログインは利用可能にする。
        }

        companyInput.setAttribute("autocapitalize", "none");
        companyInput.setAttribute("spellcheck", "false");

        form.addEventListener("submit", () => {
            try {
                const companyCode = companyInput.value.trim();

                if (companyCode) {
                    localStorage.setItem(
                        companyStorageKey,
                        companyCode
                    );
                } else {
                    localStorage.removeItem(companyStorageKey);
                }
            } catch {
                // 保存に失敗してもログインを続行する。
            }
        });
    }

    const button = form.querySelector('button[type="submit"]');
    const token = form.querySelector('input[name="csrf_token"]');
    const error = document.getElementById("login-submit-error");
    let submitting = false;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (submitting) return;

        submitting = true;
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        error.hidden = true;

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 10000);

        try {
            const response = await fetch(form.dataset.csrfUrl, {
                credentials: "same-origin",
                cache: "no-store",
                headers: { Accept: "application/json" },
                signal: controller.signal
            });

            if (!response.ok || response.redirected) {
                throw new Error("Token refresh failed");
            }

            const data = await response.json();
            if (typeof data.csrf_token !== "string" || !data.csrf_token) {
                throw new Error("Token missing");
            }

            token.value = data.csrf_token;
            HTMLFormElement.prototype.submit.call(form);
        } catch (failure) {
            error.textContent =
                "通信できませんでした。入力内容はそのままで、もう一度ログインを押してください。";
            error.hidden = false;
            submitting = false;
            button.disabled = false;
            button.removeAttribute("aria-busy");
        } finally {
            clearTimeout(timeout);
        }
    });
})();