(() => {
    function initializeKarteLayout() {
        // Reveal the selected tab inside its strip without moving the document.
        const tabs = document.querySelector(".vehicle-karte-tabs");
        function revealSelectedTab() {
            const current = tabs?.querySelector('[aria-current="page"]');
            if (!current || tabs.scrollWidth <= tabs.clientWidth) return;
            const strip = tabs.getBoundingClientRect(), item = current.getBoundingClientRect();
            if (item.left < strip.left) tabs.scrollLeft += item.left - strip.left;
            else if (item.right > strip.right) tabs.scrollLeft += item.right - strip.right;
        }
        requestAnimationFrame(revealSelectedTab);
        window.addEventListener("load", revealSelectedTab, {once:true});
        document.fonts?.ready.then(revealSelectedTab);
        window.addEventListener("resize", revealSelectedTab);
        const workspaces = document.querySelectorAll(
            ".km-workspace:has(> .km-list-panel), .kp-workspace, .vehicle-karte-history-panel, .vehicle-karte-inspections-primary, .vehicle-karte-documents .km-workspace"
        );
        if (!workspaces.length) return;

        let frame = 0;

        function updateHeight() {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(() => {
                workspaces.forEach(workspace => {
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
                        Math.floor(viewportHeight - Math.max(0, top) - bottomGap)
                    );
                    workspace.style.setProperty(
                        "--karte-workspace-height",
                        (height < 260 || main?.clientWidth < 760) ? "auto" : `${height}px`
                    );
                    workspace.dataset.flowLayout = String(height < 260 || main?.clientWidth < 760);
                });
            });
        }

        window.addEventListener("resize", updateHeight);
        window.visualViewport?.addEventListener("resize", updateHeight);
        window.addEventListener("load", updateHeight, { once: true });

        if ("ResizeObserver" in window) {
            const observer = new ResizeObserver(updateHeight);
            document.querySelectorAll(
                ".main-content, .vehicle-karte-header, .vehicle-karte-tabs, .km-import-result"
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
