(() => {
    function initializeKarteLayout() {
        const workspace = document.querySelector(
            ".km-workspace:has(> .km-list-panel), .kp-workspace, .vehicle-karte-history-panel, .vehicle-karte-inspections-primary, .vehicle-karte-documents .km-workspace"
        );
        if (!workspace) return;

        let frame = 0;

        function updateHeight() {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(() => {
                const bottomGap = 6;
                const main = workspace.closest(".main-content");

                if (main) {
                    main.style.setProperty(
                        "--karte-bottom-gap",
                        `${bottomGap}px`
                    );
                }

                const viewportHeight = Math.min(
                    document.documentElement.clientHeight,
                    window.visualViewport
                        ? window.visualViewport.height
                        : window.innerHeight
                );
                const top = workspace.getBoundingClientRect().top;
                const height = Math.max(
                    0,
                    Math.floor(viewportHeight - top - bottomGap)
                );
                workspace.style.setProperty(
                    "--karte-workspace-height",
                    `${height}px`
                );
            });
        }

        window.addEventListener("resize", updateHeight);
        window.addEventListener("load", updateHeight, { once: true });

        if ("ResizeObserver" in window) {
            const observer = new ResizeObserver(updateHeight);
            document.querySelectorAll(
                ".vehicle-karte-header, .vehicle-karte-tabs, .km-import-result"
            ).forEach(element => observer.observe(element));
        }

        if (document.fonts) {
            document.fonts.ready.then(updateHeight);
        }

        updateHeight();
    }

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded", initializeKarteLayout, { once: true }
        );
    } else {
        initializeKarteLayout();
    }
})();
