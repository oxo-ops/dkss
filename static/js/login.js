(() => {
    const form = document.getElementById("dkss-login-form");
    if (!form) return;

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