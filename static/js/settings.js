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
        pushButton.disabled = false;

        if (pushStatus) {
            pushStatus.textContent =
                "端末通知がブラウザ側でブロックされています。";
        }
    }

    pushButton.addEventListener(
        "click",
        async function () {
            if (Notification.permission === "denied") {
                window.alert(
                    "端末通知がブラウザでブロックされています。\n\n"
                    + "アドレスバー左の鍵アイコンを押してください。\n"
                    + "↓\n"
                    + "「通知」をONにしてください。\n"
                    + "↓\n"
                    + "その後、このページを再読み込みしてください。"
                );

                return;
            }

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