document.addEventListener("DOMContentLoaded", function () {
    const passwordInput = document.getElementById("password");
    const passwordToggle = document.querySelector(".js-password-toggle");

    if (!passwordInput || !passwordToggle) {
        return;
    }

    passwordToggle.addEventListener("click", function () {
        const isHidden = passwordInput.type === "password";

        passwordInput.type = isHidden ? "text" : "password";
        passwordToggle.classList.toggle("is-visible", isHidden);
        passwordToggle.setAttribute(
            "aria-label",
            isHidden ? "パスワードを隠す" : "パスワードを表示"
        );
        passwordToggle.setAttribute(
            "title",
            isHidden ? "パスワードを隠す" : "パスワードを表示"
        );
    });
});