document.addEventListener("DOMContentLoaded", function () {
document.querySelectorAll(".dashboard-auto-submit").forEach(function (select) {
    select.addEventListener("change", function () {
        if (!select.form) return;
        if (select.id === "dashboardReportPeriod") {
            const period = select.form.querySelector('[name="period"]');
            if (period) period.value = select.value;
        }
        select.form.submit();
    });
});
document.querySelectorAll(".dashboard-analysis-card").forEach(function (card) {
    card.removeAttribute("data-url");
});

document.querySelectorAll(".dashboard-analysis-important[data-url]").forEach(function (element) {
    if (!element.dataset.url) return;

    const link = document.createElement("a");
    link.className = element.className;
    link.href = element.dataset.url;
    link.title = "実施記録を確認";

    while (element.firstChild) {
        link.append(element.firstChild);
    }

    element.replaceWith(link);
});
document.querySelectorAll(".dashboard-click-card, .dashboard-click-row").forEach(function (element) {
    element.addEventListener("click", function (event) {
        if (!element.dataset.url
            || event.target.closest("a, button, input, select, textarea, summary")) {
            return;
        }

        window.location.href = element.dataset.url;
    });
});
    const customizeButton =
        document.getElementById("dashboardCustomizeButton");

    const customizePanel =
        document.getElementById("dashboardCustomizePanel");

    const vehicleAddButton =
        document.getElementById("dashboardVehicleAddButton");

    const vehicleAddArea =
        document.getElementById("dashboardVehicleAddArea");

    if (vehicleAddButton && vehicleAddArea) {
        vehicleAddButton.addEventListener("click", function () {
            vehicleAddArea.classList.toggle("is-open");
        });
    }
    if (customizeButton && customizePanel) {

        function closeCustomizePanel() {
            customizePanel.classList.remove("is-open");
            customizeButton.setAttribute(
                "aria-expanded",
                "false"
            );
        }

        customizeButton.addEventListener(
            "click",
            function (event) {

                event.stopPropagation();

                const willOpen =
                    !customizePanel.classList.contains(
                        "is-open"
                    );

                customizePanel.classList.toggle(
                    "is-open",
                    willOpen
                );

                customizeButton.setAttribute(
                    "aria-expanded",
                    willOpen ? "true" : "false"
                );
            }
        );

        customizePanel.addEventListener(
            "click",
            function (event) {
                event.stopPropagation();
                if (event.target.closest('a[href^="#dashboard-view="]')) {
                    closeCustomizePanel();
                }
            }
        );

        document.addEventListener(
            "click",
            closeCustomizePanel
        );

        document.addEventListener(
            "keydown",
            function (event) {

                if (event.key === "Escape") {
                    closeCustomizePanel();
                }
            }
        );
    }

    const searchInput = document.getElementById("dashboardVehicleSearch");
    const vehicleIdInput = document.getElementById("dashboardVehicleId");
    const resultBox = document.getElementById("dashboardVehicleResults");
    const form = document.getElementById("dashboardVehicleForm");

    if (!searchInput || !vehicleIdInput || !resultBox || !form) {
        return;
    }

    let searchTimer = null;

    searchInput.addEventListener("input", function () {
        clearTimeout(searchTimer);

        vehicleIdInput.value = "";

        const keyword = searchInput.value.trim();

        if (!keyword) {
            resultBox.innerHTML = "";
            resultBox.classList.remove("is-open");
            return;
        }

        searchTimer = setTimeout(function () {
            fetch("/api/vehicles?q=" + encodeURIComponent(keyword))
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error(
                            "HTTP " + response.status
                        );
                    }

                    return response.json();
                })
                .then(data => {
                    resultBox.innerHTML = "";

                    if (!data.results || data.results.length === 0) {
                        resultBox.innerHTML =
                            '<p class="help-text dashboard-vehicle-empty-result">該当する車両がありません。</p>';

                        resultBox.classList.add("is-open");
                        return;
                    }

                    data.results.forEach(function (vehicle) {
                        const row = document.createElement("div");

                        row.className = "dashboard-vehicle-result-row";

                        const labelParts = [
                            vehicle.number || "ナンバー未登録"
                        ];

                        const label = document.createElement("span");
                        label.textContent = labelParts.join(" / ");

                        const button = document.createElement("button");
                        button.type = "button";
                        button.title = "使用車両に追加";
                        button.setAttribute("aria-label", "使用車両に追加");
                        button.className = "dashboard-vehicle-result-add-button";

                        button.textContent = "＋";

                        button.addEventListener("click", function () {
                            vehicleIdInput.value = vehicle.vehicle_record_id;
                            form.submit();
                        });

                        row.addEventListener("click", function (event) {
                            if (event.target === button) {
                                return;
                            }

                            vehicleIdInput.value = vehicle.vehicle_record_id;
                            form.submit();
                        });

                        row.appendChild(label);
                        row.appendChild(button);

                        resultBox.appendChild(row);
                    });

                    resultBox.classList.add("is-open");
                })
                .catch(function () {
                    showCommonError(
                        "車両を取得できませんでした。通信状態を確認して、もう一度検索してください。"
                    );

                    resultBox.innerHTML =
                        '<p class="help-text dashboard-vehicle-empty-result">' +
                        '車両を取得できませんでした。通信状態を確認して、もう一度検索してください。' +
                        '</p>';

                    resultBox.classList.add("is-open");
                });

        }, 250);
    });

    document.addEventListener("click", function (event) {
        if (
            !searchInput.contains(event.target) &&
            !resultBox.contains(event.target)
        ) {
            resultBox.classList.remove("is-open");
        }
    });

    form.addEventListener("submit", function (event) {
        if (!vehicleIdInput.value) {
            event.preventDefault();

            showCommonError(
                "候補から車両を選択してください。",
                searchInput.id || searchInput.name
            );
            searchInput.focus();
        }
    });
});


(() => {
    function initializeDashboardPanels() {
        const page = document.querySelector(".dashboard-page");
        if (!page || page.dataset.designReady) return;
        page.dataset.designReady = "true";

        const header = page.querySelector(".dashboard-header");
        const vehicles = page.querySelector(".dashboard-vehicles-section");
        const checklists = page.querySelector(".dashboard-other-checklists");

        if (vehicles && checklists) {
            const previous = checklists.closest(".dashboard-my-checklists-section");
            vehicles.append(checklists);
            if (previous && previous.children.length === 0) previous.remove();
        }

        const filters = page.querySelector("#dashboardFilterForm");
        if (filters && header) {
            filters.hidden = false;
            header.append(filters);
        }

        const overview = document.createElement("div");
        overview.className = "dashboard-home-layout";

        const other = page.querySelector("#dashboard-reference-other");

        for (const child of Array.from(page.children)) {
            if (child !== header && child !== other && child.tagName !== "SCRIPT") {
                overview.append(child);
            }
        }

        if (header) header.after(overview);
        else page.prepend(overview);

        const extraGrid = checklists?.querySelector(":scope > .dashboard-my-checklists-grid");
        const extraSummary = checklists?.querySelector(":scope > summary");
        if (extraGrid && extraSummary && vehicles?.contains(checklists)) {
            const extraPanel = document.createElement("section");
            extraPanel.id = "dashboardExtraChecklists";
            extraPanel.className = "dashboard-extra-checklists-panel";
            extraSummary.id = "dashboardExtraChecklistsTitle";
            extraSummary.setAttribute("aria-controls", extraPanel.id);
            extraPanel.setAttribute("aria-labelledby", extraSummary.id);
            extraPanel.append(extraGrid);

            const topRowEnd = overview.querySelector(".dashboard-attention-list") || vehicles;
            topRowEnd.after(extraPanel);

            const syncExtraChecklists = () => {
                extraPanel.hidden = !checklists.open;
                extraSummary.setAttribute("aria-expanded", String(checklists.open));
            };
            checklists.addEventListener("toggle", syncExtraChecklists);
            syncExtraChecklists();
        }

        const bottom = overview.querySelector(".dashboard-reference-bottom-grid");
        const requests = bottom
            ?.querySelector(".dashboard-reference-action-links")
            ?.closest("section");
        const safety = overview.querySelector(".dashboard-reference-safety");

        if (bottom && requests) {
            requests.classList.add("dashboard-request-band");
            bottom.before(requests);
        }

        if (bottom && safety) bottom.append(safety);

        const trendTabs = Array.from(
            page.querySelectorAll('.dashboard-trend-tabs [role="tab"]')
        );

        function selectTrendTab(selected, focus = false) {
            for (const tab of trendTabs) {
                const active = tab === selected;
                tab.setAttribute("aria-selected", String(active));
                tab.tabIndex = active ? 0 : -1;

                const panel = document.getElementById(
                    tab.getAttribute("aria-controls")
                );
                if (panel) panel.hidden = !active;
            }

            const period = page.querySelector("[data-trend-period]");
            if (period) period.hidden = selected.id === "dashboardTrendCostTab";
            if (focus) selected.focus();
        }

        for (const tab of trendTabs) {
            tab.addEventListener("click", () => selectTrendTab(tab));
            tab.addEventListener("keydown", event => {
                const index = trendTabs.indexOf(tab);
                let next;

                if (event.key === "ArrowRight") {
                    next = (index + 1) % trendTabs.length;
                } else if (event.key === "ArrowLeft") {
                    next = (index + trendTabs.length - 1) % trendTabs.length;
                } else if (event.key === "Home") {
                    next = 0;
                } else if (event.key === "End") {
                    next = trendTabs.length - 1;
                } else {
                    return;
                }

                event.preventDefault();
                selectTrendTab(trendTabs[next], true);
            });
        }

        const vehicleMenus = page.querySelectorAll(".dashboard-vehicle-checklists");
        for (const menu of vehicleMenus) {
            menu.addEventListener("toggle", () => {
                if (!menu.open) return;
                for (const other of vehicleMenus) {
                    if (other !== menu) other.open = false;
                }
            });
        }
        document.addEventListener("click", event => {
            for (const menu of vehicleMenus) {
                if (!menu.contains(event.target)) menu.open = false;
            }
        });
        document.addEventListener("keydown", event => {
            if (event.key !== "Escape") return;
            for (const menu of vehicleMenus) {
                if (!menu.open) continue;
                if (menu.contains(document.activeElement)) {
                    menu.querySelector("summary").focus();
                }
                menu.open = false;
            }
        });

        const views = new Map();
        const selectors = new Map();
        const inlineKeys = new Set(["analysis", "ranking", "inspection"]);
        const inlineButtons = new Map();
        const definitions = [
            ["analysis", ".dashboard-analysis-section", "チェックリスト集計"],
            ["ranking", "#dashboard-reference-ranking", "無事故無違反ランキング"],
            ["inspection", "#dashboard-reference-inspection", "車検期限が近い車両"],
            ["periodic", "#dashboard-reference-periodic", "3か月点検の予定"],
            ["setup", ".dashboard-setup-details", "初期設定"]
        ];

        for (const [key, selector, title] of definitions) {
            const target = other?.querySelector(selector);
            const panel = target?.matches("h3")
                ? target.closest(".dashboard-card")
                : target;

            if (!panel) continue;

            const view = document.createElement("section");
            view.className = "dashboard-report-view";
            view.hidden = true;

            const heading = document.createElement("div");
            heading.className = "dashboard-report-heading";

            const back = document.createElement("a");
            back.className = "dashboard-report-back";
            back.href = "#dashboard-home";
            back.textContent = "← ダッシュボード";

            const name = document.createElement("h3");
            name.textContent = title;
            name.tabIndex = -1;

            heading.append(back, name);

            view.id = `dashboard-panel-${key}`;
            name.id = `dashboard-panel-title-${key}`;
            if (inlineKeys.has(key)) {
                view.setAttribute("aria-label", title);
                back.remove();

                const panelTitle = panel.querySelector(
                    ":scope > .card-title-row > h3"
                );
                panelTitle?.remove();

                view.append(panel);
            } else {
                view.setAttribute("aria-labelledby", name.id);
                view.append(heading, panel);
            }

            if (key === "analysis") {
                const notes = panel.querySelectorAll(".dashboard-category-note, .dashboard-history-note");
                notes.forEach((note, index) => {
                    const table = note.closest(".dashboard-analysis-priority, .dashboard-analysis-history")
                        ?.querySelector("table");
                    if (!table) return;

                    note.id = `${view.id}-note-${index}`;
                    table.title = note.textContent.trim();
                    table.setAttribute("aria-describedby", note.id);
                    note.hidden = true;
                });
            }

            if (panel.tagName === "DETAILS") panel.open = true;

            panel.classList.remove("dashboard-click-card");
            delete panel.dataset.url;

            page.append(view);
            views.set(key, view);
            selectors.set(selector, key);
        }

        if (other) other.hidden = true;
        if (bottom && !bottom.children.length) bottom.hidden = true;

        for (const button of page.querySelectorAll("[data-reference-target]")) {
            const selector = button.dataset.referenceTarget;

            if (selectors.has(selector)) {
                const key = selectors.get(selector);
                if (inlineKeys.has(key)) {
                    button.setAttribute("aria-controls", views.get(key).id);
                    button.setAttribute("aria-expanded", "false");
                    if (!inlineButtons.has(key)) inlineButtons.set(key, []);
                    inlineButtons.get(key).push(button);

                    button.addEventListener("click", event => {
                        event.preventDefault();
                        const currentKey = new URLSearchParams(location.hash.slice(1))
                            .get("dashboard-view");
                        location.hash = currentKey === key
                            ? "dashboard-home"
                            : `dashboard-view=${key}`;
                    });
                    continue;
                }

                const link = document.createElement("a");
                link.href = `#dashboard-view=${key}`;
                link.className = button.className;
                while (button.firstChild) link.append(button.firstChild);
                button.replaceWith(link);
                continue;
            }

            const target = page.querySelector(selector);
            if (!target || target.tagName !== "DETAILS") continue;

            button.setAttribute("aria-controls", target.id);

            const sync = () => {
                button.setAttribute("aria-expanded", String(target.open));
            };

            sync();
            target.addEventListener("toggle", sync);

            button.addEventListener("click", event => {
                event.preventDefault();
                target.open = !target.open;
                sync();
            });
        }

        function showView(focus) {
            const viewParameters = new URLSearchParams(location.hash.slice(1));
            const key = viewParameters.get("dashboard-view") || "";
            const requestedChecklist = viewParameters.get("checklist");
            const reportSelect = page.querySelector("#dashboardReportChecklist");

            if (key === "analysis" && reportSelect && requestedChecklist
                && reportSelect.value !== requestedChecklist
                && Array.from(reportSelect.options).some(option => option.value === requestedChecklist)) {
                reportSelect.value = requestedChecklist;
                reportSelect.dispatchEvent(new Event("change"));
            }

            const previousInlineKey = Array.from(inlineButtons.keys())
                .find(value => !views.get(value).hidden);
            const active = views.get(key);
            const inlineActive = Boolean(active) && inlineKeys.has(key);
            const analysisActive = key === "analysis" && Boolean(active);
            const separateAnalysis = analysisActive && !inlineActive;

            overview.hidden = Boolean(active) && !inlineActive;
            page.classList.toggle("dashboard-view-analysis", separateAnalysis);
            if (header) header.hidden = separateAnalysis;

            if (filters) {
                const destination = separateAnalysis
                    ? active.querySelector(".dashboard-report-heading")
                    : header;
                if (destination && filters.parentElement !== destination) {
                    destination.append(filters);
                }
            }

            const returnView = page.querySelector("#dashboardReturnView");
            if (returnView) returnView.value = analysisActive ? "analysis" : "";

            for (const [viewKey, view] of views) {
                view.hidden = view !== active;
                for (const button of inlineButtons.get(viewKey) || []) {
                    const expanded = view === active;
                    button.setAttribute("aria-expanded", String(expanded));

                    if (button.closest(".dashboard-reference-footer")) {
                        const arrow = button.querySelector(":scope > span:last-child");
                        if (arrow) {
                            arrow.textContent = expanded ? "⌄" : "›";
                            arrow.setAttribute("aria-hidden", "true");
                        }
                    }
                }
            }

            if (focus) {
                const closedButton = !active && previousInlineKey
                    ? inlineButtons.get(previousInlineKey).at(-1)
                    : null;

                if (!inlineActive) {
                    const heading = active?.querySelector("h3");
                    if (heading) {
                        heading.focus({preventScroll: true});
                    } else if (closedButton) {
                        closedButton.focus({preventScroll: true});
                    } else {
                        header?.querySelector("h2")?.focus({preventScroll: true});
                    }
                }

                if (inlineActive || closedButton) {
                    const entrance = overview.querySelector(".dashboard-reference-footer");
                    (entrance || active || closedButton)?.scrollIntoView({block: "start"});
                } else {
                    window.scrollTo({top: 0, behavior: "instant"});
                }
            }
        }

        const title = header?.querySelector("h2");
        if (title) title.tabIndex = -1;

        for (const card of page.querySelectorAll(".dashboard-analysis-card")) {
            const buttons = Array.from(
                card.querySelectorAll("[data-checklist-view]")
            );

            function selectChecklistView(view) {
                card.dataset.reportTab = view === "history" ? "history" : "summary";
                for (const button of buttons) {
                    button.setAttribute(
                        "aria-pressed",
                        String(button.dataset.checklistView === card.dataset.reportTab)
                    );
                }
            }

            for (const button of buttons) {
                button.addEventListener("click", () => {
                    selectChecklistView(button.dataset.checklistView);
                });
            }

            card.querySelector(".dashboard-history-open")?.addEventListener("click", () => {
                selectChecklistView("history");
                card.querySelector(".dashboard-analysis-history h4")?.focus({
                    preventScroll: true
                });
            });

            selectChecklistView("summary");
        }

        const checklistSelect = page.querySelector("#dashboardReportChecklist");
        const checklistCards = Array.from(
            page.querySelectorAll(".dashboard-analysis-section .dashboard-analysis-card")
        );

        if (checklistSelect && checklistCards.length) {
            const savedChecklist = new URLSearchParams(location.hash.slice(1)).get("checklist");
            if (Array.from(checklistSelect.options).some(option => option.value === savedChecklist)) {
                checklistSelect.value = savedChecklist;
            }

            function showChecklist() {
                checklistCards.forEach(card => {
                    card.hidden = card.dataset.checklistId !== checklistSelect.value;
                });

                const returnChecklist = page.querySelector("#dashboardReturnChecklist");
                if (returnChecklist) returnChecklist.value = checklistSelect.value;

                if (new URLSearchParams(location.hash.slice(1)).get("dashboard-view") === "analysis") {
                    const url = new URL(location.href);
                    url.hash = `dashboard-view=analysis&checklist=${encodeURIComponent(checklistSelect.value)}`;
                    history.replaceState(history.state, "", url);
                }
            }

            checklistSelect.addEventListener("change", showChecklist);
            showChecklist();
        }

        window.addEventListener("hashchange", () => showView(true));
        showView(false);
    }

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            initializeDashboardPanels,
            {once: true}
        );
    } else {
        initializeDashboardPanels();
    }
})();
