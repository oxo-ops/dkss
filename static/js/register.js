document.addEventListener("DOMContentLoaded", function () {
    const passwordInput = document.getElementById("password");
    const passwordToggle = document.querySelector(".js-password-toggle");

    if (!passwordInput || !passwordToggle) {
        return;
    }

    passwordToggle.addEventListener("change", function () {
        passwordInput.type = passwordToggle.checked ? "text" : "password";
    });
});