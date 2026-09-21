document.addEventListener("DOMContentLoaded", function () {
    const timezone =
        Intl.DateTimeFormat().resolvedOptions().timeZone;

    const hiddenInput =
        document.getElementById("timezone");

    const displayInput =
        document.getElementById("timezone_display");

    if (timezone) {
        if (hiddenInput) {
            hiddenInput.value = timezone;
        }

        if (displayInput) {
            displayInput.value = timezone;
        }
    }

    const pushButton =
        document.getElementById(
            "enablePushNotifications"
        );

    const pushStatus =
        document.getElementById(
            "pushNotificationStatus"
        );

    if (!pushButton) {
        return;
    }

    if (
        !("Notification" in window)
        || !("serviceWorker" in navigator)
        || !("PushManager" in window)
    ) {
        pushButton.disabled = true;

        if (pushStatus) {
            pushStatus.textContent =
                "このブラウザは端末通知に対応していません。";
        }

        return;
    }

    if (Notification.permission === "granted") {
        if (pushStatus) {
            pushStatus.textContent =
                "端末通知は有効です。";
        }
    }

    if (Notification.permission === "denied") {
        pushButton.disabled = true;

        if (pushStatus) {
            pushStatus.textContent =
                "ブラウザ側で通知が拒否されています。";
        }
    }

    pushButton.addEventListener(
        "click",
        async function () {
            pushButton.disabled = true;

            if (pushStatus) {
                pushStatus.textContent =
                    "端末通知を設定しています...";
            }

            try {
                const permission =
                    await Notification.requestPermission();

                if (permission !== "granted") {
                    pushButton.disabled = false;

                    if (pushStatus) {
                        pushStatus.textContent =
                            "通知の許可が必要です。";
                    }

                    return;
                }

                await registerPushNotifications();

                if (
                    Notification.permission
                    === "granted"
                ) {
                    if (pushStatus) {
                        pushStatus.textContent =
                            "端末通知を有効にしました。";
                    }
                } else {
                    pushButton.disabled = false;

                    if (pushStatus) {
                        pushStatus.textContent =
                            "通知の許可が必要です。";
                    }
                }
            } catch (error) {
                console.error(
                    "端末通知設定エラー:",
                    error
                );

                pushButton.disabled = false;

                if (pushStatus) {
                    pushStatus.textContent =
                        "端末通知の設定に失敗しました。";
                }
            }
        }
    );
});