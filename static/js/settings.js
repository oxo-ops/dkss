document.addEventListener("DOMContentLoaded", function () {
    const timezone =
        Intl.DateTimeFormat().resolvedOptions().timeZone;

    if (!timezone) {
        return;
    }

    const hiddenInput =
        document.getElementById("timezone");

    const displayInput =
        document.getElementById("timezone_display");

    if (hiddenInput) {
        hiddenInput.value = timezone;
    }

    if (displayInput) {
        displayInput.value = timezone;
    }
});