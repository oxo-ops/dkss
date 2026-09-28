self.addEventListener("push", (event) => {
    let data = {};

    try {
        data = event.data
            ? event.data.json()
            : {};
    } catch (error) {
        data = {};
    }

    const title = data.title || "DKSS";

    const options = {
        body: data.message || "",
        icon: "/static/icons/notification.png",
        badge: "/static/icons/notification.png",
        data: {
            link: data.link || "/notifications"
        }
    };

    const unreadCount =
        Number(data.unread_count || 0);

    const badgePromise =
        "setAppBadge" in self.registration
            ? (
                unreadCount > 0
                    ? self.registration.setAppBadge(
                        unreadCount
                    )
                    : self.registration.clearAppBadge()
            )
            : Promise.resolve();

    event.waitUntil(
        Promise.all([
            self.registration.showNotification(
                title,
                options
            ),
            badgePromise
        ])
    );
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();

    const link =
        event.notification.data?.link
        || "/notifications";

    event.waitUntil(
        clients.matchAll({
            type: "window",
            includeUncontrolled: true
        }).then((clientList) => {
            for (const client of clientList) {
                if ("focus" in client) {
                    client.navigate(link);
                    return client.focus();
                }
            }

            if (clients.openWindow) {
                return clients.openWindow(link);
            }
        })
    );
});