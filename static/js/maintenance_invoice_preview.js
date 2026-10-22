// certificate-invoice-controls-v1: shared by both import screens.
(() => {
    "use strict";
    const initialized = new WeakSet();
    window.DkssInvoiceReviewControls = root => {
        if (!root || initialized.has(root)) return;
        initialized.add(root);
        const blocks = root.matches("[data-invoice-document]")
            ? [root] : Array.from(root.querySelectorAll("[data-invoice-document]"));
        blocks.forEach(block => {
            const disclosure = block.querySelector(
                ".invoice-source-disclosure"
            );
            const layout = block.querySelector(".invoice-review-layout");
            const sourceToggle = block.querySelector("[data-view-switch]");

            if (disclosure && layout && sourceToggle) {
                function updateSourceVisibility() {
                    const visible = disclosure.open;

                    layout.classList.toggle("is-source-hidden", !visible);

                    const mode = visible ? "source" : "focus";

                    block.querySelectorAll(".invoice-overview-details").forEach(details => {
                        if (details.dataset.reviewMode !== mode) {
                            details.open = true;
                            details.dataset.reviewMode = mode;
                        }
                    });

                    block.querySelectorAll(".invoice-metadata").forEach(details => {
                        if (details.dataset.reviewMode !== mode) {
                            details.open = !visible;
                            details.dataset.reviewMode = mode;
                        }
                    });
                    sourceToggle.querySelectorAll("[data-document-view]").forEach(button => {
                        const selected = button.dataset.documentView === (
                            visible ? "source" : "focus"
                        );
                        button.setAttribute("aria-pressed", String(selected));
                    });

                    block.querySelectorAll("[data-review-view]").forEach(button => {
                        const selected = button.dataset.reviewView === (
                            visible ? "source" : "results"
                        );
                        button.setAttribute("aria-pressed", String(selected));
                    });
                }

                block.querySelectorAll("[data-review-view]").forEach(button => {
                    button.addEventListener("click", () => {
                        disclosure.open = button.dataset.reviewView === "source";
                        updateSourceVisibility();
                    });
                });

                disclosure.open = true;

                sourceToggle.addEventListener("click", event => {
                    const button = event.target.closest("[data-document-view]");
                    if (!button || !sourceToggle.contains(button)) return;

                    disclosure.open = button.dataset.documentView === "source";
                    updateSourceVisibility();
                });

                disclosure.addEventListener(
                    "toggle",
                    updateSourceVisibility
                );

                updateSourceVisibility();
            }
        });
        root.querySelectorAll(".invoice-review-layout").forEach(layout => {
            const splitter = layout.querySelector(".invoice-splitter");
            const source = layout.querySelector(".invoice-source-panel");
            if (!splitter || !source) return;

            let ratio = 0.55;
            let drag = null;
            const narrow = window.matchMedia("(max-width: 1000px)");

            function availableWidth() {
                const style = getComputedStyle(layout);
                const gap = parseFloat(style.columnGap) || 0;
                return Math.max(
                    1,
                    layout.clientWidth - splitter.offsetWidth - gap * 2
                );
            }

            function applyRatio(nextRatio) {
                if (narrow.matches || !layout.clientWidth) return;

                const available = availableWidth();
                const minimum = Math.min(280, available / 2);
                const maximum = available - Math.min(300, available / 2);
                const width = Math.max(
                    minimum,
                    Math.min(maximum, available * nextRatio)
                );

                ratio = width / available;
                layout.style.setProperty(
                    "--invoice-source-width",
                    (width / layout.clientWidth * 100) + "%"
                );

                splitter.setAttribute(
                    "aria-valuemin",
                    String(Math.round(minimum / available * 100))
                );
                splitter.setAttribute(
                    "aria-valuemax",
                    String(Math.round(maximum / available * 100))
                );
                splitter.setAttribute(
                    "aria-valuenow",
                    String(Math.round(ratio * 100))
                );
                splitter.setAttribute(
                    "aria-valuetext",
                    "原本 " + Math.round(ratio * 100)
                        + "％、確認内容 " + Math.round((1 - ratio) * 100) + "％"
                );
            }

            function endResize() {
                if (!drag) return;
                const pointerId = drag.pointerId;
                drag = null;
                layout.classList.remove("is-resizing");

                if (splitter.hasPointerCapture(pointerId)) {
                    splitter.releasePointerCapture(pointerId);
                }
            }

            splitter.addEventListener("pointerdown", event => {
                if (
                    narrow.matches
                    || event.button !== 0
                    || !event.isPrimary
                ) return;

                drag = {
                    pointerId: event.pointerId,
                    x: event.clientX,
                    width: source.getBoundingClientRect().width
                };

                splitter.setPointerCapture(event.pointerId);
                splitter.focus({ preventScroll: true });
                layout.classList.add("is-resizing");
                event.preventDefault();
            });

            splitter.addEventListener("pointermove", event => {
                if (!drag || event.pointerId !== drag.pointerId) return;

                if (
                    event.pointerType === "mouse"
                    && (event.buttons & 1) === 0
                ) {
                    endResize();
                    return;
                }

                applyRatio(
                    (drag.width + event.clientX - drag.x) / availableWidth()
                );
                event.preventDefault();
            });

            splitter.addEventListener("pointerup", endResize);
            splitter.addEventListener("pointercancel", endResize);
            splitter.addEventListener("lostpointercapture", endResize);
            window.addEventListener("blur", endResize);

            splitter.addEventListener("dblclick", () => applyRatio(0.55));

            splitter.addEventListener("keydown", event => {
                if (event.key === "ArrowLeft") {
                    event.preventDefault();
                    applyRatio(ratio - 0.03);
                } else if (event.key === "ArrowRight") {
                    event.preventDefault();
                    applyRatio(ratio + 0.03);
                } else if (event.key === "Home") {
                    event.preventDefault();
                    applyRatio(0.55);
                }
            });

            new ResizeObserver(() => applyRatio(ratio)).observe(layout);
            narrow.addEventListener("change", () => {
                endResize();
                applyRatio(ratio);
            });
            applyRatio(ratio);
        });
    };
})();

(() => {
    "use strict";

    const numberPattern = /^[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?$/;

    function formatted(raw) {
        const value = String(raw ?? "").trim();
        if (!numberPattern.test(value)) return value;

        const [whole, fraction = ""] = value.replaceAll(",", "").split(".");
        const decimal = fraction.replace(/0+$/, "");

        return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")
            + (decimal ? "." + decimal : "");
    }

    function canonical(raw) {
        const value = String(raw ?? "").trim();
        if (!numberPattern.test(value)) return null;

        const [whole, fraction = ""] = value.replaceAll(",", "").split(".");
        if (fraction.length > 2) return null;

        const sign = whole.startsWith("-") ? -1n : 1n;
        return sign * (
            BigInt(whole.replace(/^[+-]/, "")) * 100n
            + BigInt(fraction.padEnd(2, "0") || "0")
        );
    }

    function initializeInvoiceServiceMatches(form) {
        form.querySelectorAll('[data-invoice-service-match]').forEach(section => {
            const record = section.closest('.invoice-record');
            const key = record.dataset.recordKey;
            const field = name => form.elements.namedItem(name + '_' + key);
            const select = field('service_match');
            const message = section.querySelector('[data-service-match-message]');
            let generation = 0;
            let signature = '';
            const refresh = async () => {
                const context = [field('vehicle')?.value || '', field('date')?.value || '', field('completion_date')?.value || ''];
                const nextSignature = JSON.stringify(context);
                if (signature === nextSignature) return;
                const first = signature === '';
                signature = nextSignature;
                const current = ++generation;
                const saved = first ? select.dataset.savedChoice : '';
                select.replaceChildren(new Option('確認してください', ''));
                select.disabled = true;
                section.hidden = true;
                if (!context[0] || (!context[1] && !context[2])) return;
                const url = new URL(section.dataset.candidatesUrl, window.location.origin);
                url.searchParams.set('vehicle_id', context[0]);
                url.searchParams.set('record_date', context[1]);
                url.searchParams.set('completion_date', context[2]);
                try {
                    const response = await fetch(url, {credentials: 'same-origin', headers: {'Accept': 'application/json'}});
                    if (!response.ok) throw new Error('Candidate lookup failed');
                    const data = await response.json();
                    if (current !== generation) return;
                    if (!Array.isArray(data.candidates)) throw new Error('Invalid candidates');
                    if (!data.candidates.length) return;
                    data.candidates.forEach(candidate => {
                        const kind = candidate.kind === 'inspection' ? '定期点検' : '整備';
                        const date = candidate.completion_date || candidate.record_date || '';
                        select.add(new Option(`${kind} ${date} ${candidate.content || '内容未登録'}`, candidate.token));
                    });
                    select.add(new Option('別の整備として取り込む', 'new'));
                    if ([...select.options].some(option => option.value === saved)) select.value = saved;
                    message.textContent = '同じ作業日の記録があります。日付だけでは同じ整備か判断できないため、今回の請求に対応する記録を確認してください。';
                    select.disabled = false;
                    section.hidden = false;
                } catch (error) {
                    if (current !== generation) return;
                    signature = '';
                    section.hidden = false;
                    message.textContent = '整備候補を確認できませんでした。通信状態を確認して画面を再読み込みしてください。';
                }
            };
            ['vehicle', 'date', 'completion_date'].forEach(name => {
                field(name)?.addEventListener('change', refresh);
            });
            // Existing reset buttons restore these fields programmatically.
            form.addEventListener('click', event => {
                if (event.target.closest('[data-reset-info]')?.closest('.invoice-record') === record) {
                    queueMicrotask(refresh);
                }
            });
            refresh();
        });
    }

    function initialize() {
        const form = document.querySelector(".vehicle-document-import-preview");
        if (form) initializeInvoiceServiceMatches(form);
        if (!form) return;

        const submitActions = form.querySelector(".invoice-submit-actions");
        const pageHeading = document.querySelector(".invoice-page-heading");

        if (pageHeading && submitActions) {
            form.prepend(pageHeading);
            pageHeading.append(submitActions);
        }

        let fitFrame = 0;

        function fitReviewHeight() {
            fitFrame = 0;

            form.querySelectorAll(".invoice-review-layout").forEach(layout => {
                const viewer = layout.querySelector(".invoice-pdf-viewer");

                if (window.innerWidth <= 1000) {
                    layout.style.removeProperty("height");
                    viewer?.style.removeProperty("height");
                    return;
                }

                const block = layout.closest(".invoice-document");
                const top = layout.getBoundingClientRect().top
                    - block.getBoundingClientRect().top;
                const headingHeight = pageHeading?.getBoundingClientRect().height || 0;
                const gap = parseFloat(getComputedStyle(form).rowGap) || 0;
                const height = Math.max(240, Math.floor(
                    form.clientHeight - headingHeight - gap - top - 32
                ));
                const value = height + "px";

                if (layout.style.height !== value) {
                    layout.style.height = value;
                }

                if (viewer) {
                    const summary = layout.querySelector(
                        ".invoice-source-disclosure > summary"
                    );
                    const summaryHeight = summary?.getBoundingClientRect().height || 30;
                    const viewerHeight = Math.max(0, height - summaryHeight) + "px";

                    if (viewer.style.height !== viewerHeight) {
                        viewer.style.height = viewerHeight;
                    }
                }
            });
        }

        function scheduleReviewFit() {
            if (!fitFrame) fitFrame = requestAnimationFrame(fitReviewHeight);
        }

        window.addEventListener("resize", scheduleReviewFit);
        form.addEventListener("toggle", scheduleReviewFit, true);
        if (window.visualViewport) {
            window.visualViewport.addEventListener("resize", scheduleReviewFit);
        }
        const fitObserver = new ResizeObserver(scheduleReviewFit);
        [
            document.querySelector(".main-content"),
            submitActions,
            ...form.querySelectorAll(".invoice-document-heading, .invoice-switcher")
        ].filter(Boolean).forEach(element => fitObserver.observe(element));
        document.fonts?.ready.then(scheduleReviewFit);
        scheduleReviewFit();

        const byName = new Map(
            Array.from(form.elements)
                .filter(el => el.name)
                .map(el => [el.name, el])
        );

        const inputFor = (record, field) =>
            byName.get(field + "_" + record.dataset.recordKey);

        const lineInput = (line, field) =>
            byName.get(line.dataset.linePrefix + field);

        const lineValue = (line, field) =>
            lineInput(line, field)?.value.trim() ?? "";

        const showValue = value => value === "" ? "—" : formatted(value);

        function sourcePage(documentBlock, page, switching = false) {
            const viewer = documentBlock.querySelector("[data-invoice-source]");
            if (!viewer) return;

            const pageNumber = /^\d+$/.test(String(page)) && Number(page) > 0
                ? String(page)
                : "1";

            const activeRecord = documentBlock.querySelector(
                ".invoice-record:not([hidden])"
            );
            const key = activeRecord?.dataset.recordKey || "";

            viewer.dataset.requestedPage = pageNumber;
            viewer.dataset.requestedRecordKey = key;

            viewer.dispatchEvent(
                new CustomEvent("dkss:source-page", {
                    detail: {
                        page: Number(pageNumber),
                        key,
                        switching
                    }
                })
            );

            documentBlock.querySelector("[data-source-page-label]").textContent =
                pageNumber + "頁";
        }

        function updateSelectionCount() {
            const count = form.querySelectorAll(
                'input[name="include"]:checked'
            ).length;

            const label = form.querySelector(
                "[data-invoice-selection-count]"
            );

            if (label) {
                label.textContent = count + "件を登録対象に選択中";
            }
        }

        updateSelectionCount();

        form.addEventListener("change", event => {
            if (event.target.matches('input[name="include"]')) {
                updateSelectionCount();
            }
        });

        const reviewPositions = new Map();

        function activate(documentBlock, key, fromSource = false) {
            const pane = documentBlock.querySelector(".invoice-records");
            const previous = documentBlock.querySelector(
                ".invoice-record:not([hidden])"
            );
            const changed = previous?.dataset.recordKey !== key;

            if (changed && previous) {
                reviewPositions.set(
                    previous.dataset.recordKey,
                    pane.scrollTop
                );
            }

            let selectedRecord = null;

            documentBlock.querySelectorAll(".invoice-record").forEach(record => {
                const selected = record.dataset.recordKey === key;
                record.hidden = !selected;
                if (selected) selectedRecord = record;
            });

            documentBlock.querySelectorAll("[data-record-target]").forEach(button => {
                button.setAttribute(
                    "aria-pressed",
                    String(button.dataset.recordTarget === key)
                );
            });

            if (selectedRecord) {
                if (fromSource) {
                    const viewer = documentBlock.querySelector(
                        "[data-invoice-source]"
                    );
                    if (viewer) {
                        viewer.dataset.requestedRecordKey = key;
                        viewer.dispatchEvent(
                            new CustomEvent("dkss:record-adopt", {
                                detail: key
                            })
                        );
                    }
                } else {
                    sourcePage(
                        documentBlock,
                        selectedRecord.dataset.firstPage,
                        true
                    );
                }
            }

            if (changed) {
                pane.scrollTop = reviewPositions.get(key) ?? 0;
            }
        }

        function replacementNeedsReview(line) {
            const action = lineValue(line, "replacement_action") || "review";
            if (action === "not_replace") return false;
            if (action !== "replace") return true;

            const quantity = Number(
                lineValue(line, "quantity").replaceAll(",", "")
            );
            return !lineValue(line, "replacement_part_name").trim()
                || !Number.isFinite(quantity)
                || quantity <= 0
                || Math.abs(
                    quantity * 100 - Math.round(quantity * 100)
                ) > 0.000001;
        }

        function updateLine(line) {
            if (line.hasAttribute("data-inspection-item")) {
                line.querySelector("[data-edit-line]").textContent = lineValue(line, "item_name") || "記載なし";
                line.querySelector(".invoice-line-supplement").textContent = [lineValue(line, "category"), lineValue(line, "notes")].filter(Boolean).join(" · ");
                line.querySelector(".invoice-line-money").textContent = [lineValue(line, "raw_result"), lineValue(line, "result_text")].filter(Boolean).join(" ／ ") || "空欄";
                return;
            }
            const badge = line.querySelector("[data-replacement-summary]");
            if (badge) {
                const review = replacementNeedsReview(line);
                const action = lineValue(line, "replacement_action");
                badge.hidden = !review && action !== "replace";
                badge.textContent = review ? "要確認" : "交換部品";
                badge.title = review
                    ? "交換部品の判定・部品名・数量を確認してください。"
                    : lineValue(line, "replacement_part_name");
            }
            line.querySelector("[data-edit-line]").textContent =
                lineValue(line, "description") || "記載なし";

            const supplements = [];
            const quantity = lineValue(line, "quantity");
            const unitPrice = lineValue(line, "unit_price");
            const unit = lineValue(line, "unit");
            const partNumber = lineValue(line, "part_number");

            if (quantity !== "") {
                supplements.push(
                    "数量 " + formatted(quantity) + (unit ? " " + unit : "")
                );
            }
            if (unitPrice !== "") {
                supplements.push("単価 " + formatted(unitPrice) + "円");
            }
            if (partNumber) supplements.push("品番 " + partNumber);

            line.querySelector(".invoice-line-supplement").textContent =
                supplements.join(" · ");

            const cell = line.querySelector(".invoice-line-money");
            cell.replaceChildren();

            const components = [
                ["labor_amount", "工賃"],
                ["parts_amount", "部品代"]
            ]
                .map(([field, label]) => ({
                    label,
                    value: lineValue(line, field)
                }))
                .filter(item => item.value !== "");

            const total = lineValue(line, "amount");

            function appendAmount(label, value) {
                const block = document.createElement("div");

                if (label) {
                    const caption = document.createElement("span");
                    caption.textContent = label;
                    block.append(caption);
                }

                block.append(document.createTextNode(formatted(value)));
                cell.append(block);
            }

            components.forEach(item => appendAmount(item.label, item.value));

            if (total !== "") {
                const cents = components.map(item => canonical(item.value));
                const same = components.length > 0
                    && cents.every(value => value !== null)
                    && canonical(total) !== null
                    && cents.reduce((a, b) => a + b, 0n) === canonical(total);

                if (!same) {
                    appendAmount(components.length ? "行合計" : "", total);
                }
            }

            if (!cell.childElementCount) cell.textContent = "—";
        }

        function showVehicleCandidates(record) {
            const vehicle = inputFor(record, "vehicle");
            const holder = record.querySelector("[data-invoice-original]");
            if (!vehicle || !holder || vehicle.disabled) return;

            let original;
            try {
                original = JSON.parse(holder.dataset.invoiceOriginal);
            } catch {
                return;
            }

            const normalize = value => String(value || "")
                .normalize("NFKC").toUpperCase().replace(/[\s\-‐‑‒–—―−]/g, "");
            const plate = normalize(original.registration_number);
            if (!plate) return;

            const candidates = Array.from(vehicle.options).filter(option =>
                option.value && !option.disabled
                && option.dataset.vehicleDeleted !== "true"
                && normalize(option.dataset.vehicleNumber) === plate
            );
            if (!candidates.length) return;

            const box = document.createElement("div");
            box.className = "invoice-vehicle-candidates";
            box.dataset.vehicleCandidates = "";
            const title = document.createElement("strong");
            title.textContent = "車番が一致する候補";
            box.append(title);

            for (const option of candidates) {
                const card = document.createElement("div");
                const name = document.createElement("b");
                name.textContent = option.dataset.vehicleNumber;

                const comparison = document.createElement("p");
                comparison.textContent = "車台番号　AI読取："
                    + (original.chassis_number || "読取なし")
                    + " ／ 台帳："
                    + (option.dataset.vehicleChassis || "未登録");

                const note = document.createElement("p");
                note.textContent = normalize(original.chassis_number)
                    === normalize(option.dataset.vehicleChassis)
                    ? "車番・車台番号が一致しています。"
                    : "車台番号に違い、または空欄があります。原本と照合して選択してください。";

                const button = document.createElement("button");
                button.type = "button";
                button.className = "invoice-button";
                button.textContent = "この車両を選択";
                button.addEventListener("click", () => {
                    vehicle.value = option.value;
                    vehicle.dispatchEvent(new Event("change", { bubbles: true }));
                    const label = record.querySelector("[data-invoice-vehicle-label]");
                    label.tabIndex = -1;
                    label.focus({ preventScroll: true });
                });

                card.append(name, comparison, note, button);
                box.append(card);
            }

            record.querySelector(".invoice-record-actions").after(box);
        }

        function updateFacts(record) {
            const raw = field => inputFor(record, field)?.value.trim() ?? "";

            const facts = {
                record_date: raw("date"),
                mileage: raw("mileage"),
                content: raw("content"),
                total_cost: raw("total_cost"),
                labor_cost: raw("labor_cost"),
                parts_cost: raw("parts_cost"),
                other_cost: raw("other_cost"),
                tax_amount: raw("tax_amount"),
                issuer_name: raw("issuer_name"),
                maintenance_company: raw("maintenance_company"),
                completion_date: raw("completion_date"),
                invoice_date: raw("invoice_date"),
                sales_date: raw("sales_date"),
                notes: raw("notes"),
                inspection_type: ({"3month": "3か月点検", "12month": "12か月点検", "other": "その他の点検"})[raw("inspection_type")] || "未入力",
                inspection_company: raw("inspection_company"),
                inspector_name: raw("inspector_name"),
                next_inspection_date: raw("next_inspection_date"),
                next_inspection_month: raw("next_inspection_month"),
                symbol_legend: raw("symbol_legend")
            };

            const numbers = new Set([
                "mileage", "total_cost", "labor_cost",
                "parts_cost", "other_cost", "tax_amount"
            ]);

            record.querySelectorAll("[data-fact]").forEach(el => {
                const field = el.dataset.fact;
                if (!Object.hasOwn(facts, field)) return;

                el.textContent = numbers.has(field)
                    ? showValue(facts[field])
                    : facts[field] || (
                        field === "content" ? "記録内容の記載なし" : "未入力"
                    );
            });

            record.querySelectorAll("[data-cost-summary]").forEach(el => {
                el.hidden = facts[el.dataset.costSummary] === "";
            });

            record.querySelectorAll("[data-metadata-field]").forEach(el => {
                const field = el.dataset.metadataField;
                if (Object.hasOwn(facts, field)) {
                    el.hidden = facts[field] === "";
                }
            });

            const vehicle = inputFor(record, "vehicle");
            if (vehicle) {
                record.querySelector("[data-invoice-vehicle-label]").textContent =
                    vehicle.value
                        ? vehicle.selectedOptions[0]?.textContent.trim()
                            || "選択した車両"
                        : "登録先の車両が未確定です";

                const warning = record.querySelector("[data-vehicle-match-warning]");
                const candidates = record.querySelector("[data-vehicle-candidates]");
                if (warning) warning.hidden = Boolean(vehicle.value) || Boolean(candidates);
                if (candidates) candidates.hidden = Boolean(vehicle.value);
            }

            const inspection = record.closest("[data-invoice-document]").dataset.documentType === "inspection";
            const invoiceNumber = inspection ? facts.inspection_type : raw("invoice_number");
            record.querySelector(".invoice-eyebrow").textContent = inspection
                ? invoiceNumber : "伝票 " + (invoiceNumber || "番号記載なし");

            const tab = Array.from(
                record.closest("[data-invoice-document]")
                    .querySelectorAll("[data-record-target]")
            ).find(button =>
                button.dataset.recordTarget === record.dataset.recordKey
            );

            if (tab) {
                tab.querySelector("small").textContent =
                    invoiceNumber || "伝票番号なし";
            }
        }

        const editorHomes = new WeakMap();
        const dockMedia = window.matchMedia("(min-width: 1001px)");

        function editorRowFor(target) {
            const row = target.closest(".invoice-line-editor-row");
            if (row) return row;

            const panel = target.closest(".invoice-line-editor");
            return panel ? editorHomes.get(panel)?.row || null : null;
        }

        function releaseEditorDock(record) {
            const dock = record.querySelector(".invoice-editor-dock");
            const panel = dock?.querySelector(".invoice-line-editor");

            if (panel) {
                const home = editorHomes.get(panel);
                if (home) {
                    home.cell.append(panel);
                    home.row.classList.remove("is-docked");
                }
            }

            if (dock) dock.hidden = true;

            record.querySelector(".invoice-detail-content")
                ?.classList.remove("has-docked-editor");
        }

        function syncEditorDock(record) {
            releaseEditorDock(record);
        }

        form.addEventListener("click", event => {
            const button = event.target.closest("[data-dock-step]");
            if (!button || button.disabled) return;

            const record = button.closest(".invoice-record");
            const editor = record.querySelector(
                ".invoice-line-editor-row:not([hidden])"
            );
            if (!editor) return;

            const lines = Array.from(
                record.querySelectorAll(".invoice-line")
            ).filter(line => !line.hidden);

            const index = lines.indexOf(editor.previousElementSibling);
            const next = lines[index + Number(button.dataset.dockStep)];
            if (!next) return;

            openLine(next);

            const pane = record.closest(".invoice-records");
            const bounds = pane.getBoundingClientRect();
            const selected = next.getBoundingClientRect();

            if (selected.top < bounds.top + 8) {
                pane.scrollTop += selected.top - bounds.top - 8;
            } else if (selected.bottom > bounds.bottom - 8) {
                pane.scrollTop += selected.bottom - bounds.bottom + 8;
            }
        });

        const dockObserver = new MutationObserver(changes => {
            const records = new Set();

            for (const change of changes) {
                const target = change.target;

                if (target.matches(".invoice-review-layout")) {
                    target.querySelectorAll(".invoice-record")
                        .forEach(record => records.add(record));
                } else if (target.matches(
                    ".invoice-record, .invoice-line-editor-row"
                )) {
                    records.add(target.closest(".invoice-record"));
                }
            }

            records.forEach(record => {
                if (record) syncEditorDock(record);
            });
        });

        dockObserver.observe(form, {
            subtree: true,
            attributes: true,
            attributeFilter: ["hidden", "class"]
        });

        dockMedia.addEventListener("change", () => {
            form.querySelectorAll(".invoice-record")
                .forEach(syncEditorDock);
        });

        function closeLines(record) {
            releaseEditorDock(record);
            record.querySelectorAll(".invoice-line-editor-row").forEach(el => {
                el.hidden = true;
            });

            record.querySelectorAll(".invoice-line").forEach(el => {
                el.classList.remove("is-active");
            });

            record.querySelectorAll("[data-edit-line]").forEach(el => {
                el.setAttribute("aria-expanded", "false");
            });

            applyLineFilters(record);
        }

        function openLine(line) {
            const record = line.closest(".invoice-record");
            closeLines(record);

            const button = line.querySelector("[data-edit-line]");
            const panel = document.getElementById(
                button.getAttribute("aria-controls")
            );

            panel.hidden = false;
            button.setAttribute("aria-expanded", "true");
            line.classList.add("is-active");

            sourcePage(
                record.closest("[data-invoice-document]"),
                line.dataset.sourcePage
            );

            syncEditorDock(record);

            const editor = record.querySelector(
                ".invoice-editor-dock:not([hidden]) .invoice-line-editor"
            ) || panel;

            editor.querySelector("input, textarea, select")
                ?.focus({ preventScroll: true });
        }

        const resetStates = new WeakMap();

        function comparable(value, numeric) {
            const text = String(value ?? "").trim();
            if (!numeric || !numberPattern.test(text)) return text;

            const [whole, fraction = ""] = text.replaceAll(",", "").split(".");
            const digits = whole.replace(/^[+-]/, "").replace(/^0+(?=\d)/, "");
            const decimal = fraction.replace(/0+$/, "");
            const negative = whole.startsWith("-")
                && (digits !== "0" || decimal !== "");

            return (negative ? "-" : "")
                + digits
                + (decimal ? "." + decimal : "");
        }

        function fieldChanged(field) {
            return comparable(field.input.value, field.numeric)
                !== comparable(field.original, field.numeric);
        }

        function refreshChanges(record) {
            const state = resetStates.get(record);
            if (!state) return;

            for (const field of state.fields) {
                const changed = fieldChanged(field);
                field.input.classList.toggle("invoice-input-modified", changed);
                field.hint.hidden = !changed;
            }

            const infoChanged = state.info.some(fieldChanged);
            const infoBadge = record.querySelector("[data-info-change]");
            const infoReset = record.querySelector("[data-reset-info]");

            if (infoBadge) infoBadge.hidden = !infoChanged;
            if (infoReset) infoReset.disabled = !infoChanged;

            for (const item of state.lines) {
                const changed = item.fields.some(fieldChanged);
                item.line.classList.toggle("is-modified", changed);
                item.badge.hidden = !changed;
                if (item.reset) item.reset.disabled = !changed;
            }
        }

        function restoreFields(record, fields) {
            for (const field of fields) {
                const input = field.input;
                input.value = input.hasAttribute("data-invoice-money")
                    ? formatted(field.original)
                    : field.original;
                input.setCustomValidity("");
            }

            for (const field of fields) {
                field.input.dispatchEvent(
                    new Event("input", { bubbles: true })
                );
                field.input.dispatchEvent(
                    new Event("change", { bubbles: true })
                );
            }

            refreshChanges(record);
        }

        form.querySelectorAll(".invoice-record").forEach(record => {
            const holder = record.querySelector("[data-invoice-original]");
            if (!holder) return;

            let original;
            try {
                original = JSON.parse(holder.dataset.invoiceOriginal);
            } catch {
                console.error("Invoice original data could not be read");
                return;
            }

            if (!original || typeof original !== "object") return;

            const state = { info: [], lines: [], fields: [] };

            function remember(input, value, numeric) {
                if (!input) return null;

                const original = String(
                    value ?? (input.dataset.invoiceEmptyDefault || "")
                );
                const hint = document.createElement("span");
                hint.className = "invoice-original-hint";
                hint.id = input.id + "_original_hint";

                let display = numeric ? formatted(original) : original;

                if (input.tagName === "SELECT") {
                    display = Array.from(input.options).find(
                        option => option.value === original
                    )?.textContent.trim() || original;
                }

                hint.textContent = "読取値：" + (display || "空欄");
                hint.title = hint.textContent;
                hint.hidden = true;
                input.after(hint);

                input.setAttribute("aria-describedby", [
                    input.getAttribute("aria-describedby"),
                    hint.id
                ].filter(Boolean).join(" "));

                const field = {
                    input,
                    original,
                    numeric,
                    hint
                };
                state.fields.push(field);
                return field;
            }

            const infoFields = [
                ["vehicle", "vehicle_record_id", false],
                ["date", "record_date", false],
                ["mileage", "mileage", true],
                ["content", "content", false],
                ["invoice_number", "invoice_number", false],
                ["issuer_name", "issuer_name", false],
                ["maintenance_company", "maintenance_company", false],
                ["completion_date", "completion_date", false],
                ["invoice_date", "invoice_date", false],
                ["sales_date", "sales_date", false],
                ["labor_cost", "labor_cost", true],
                ["parts_cost", "parts_cost", true],
                ["other_cost", "other_cost", true],
                ["tax_amount", "tax_amount", true],
                ["total_cost", "total_cost", true],
                ["notes", "notes", false],
                ["inspection_type", "inspection_type", false],
                ["inspection_company", "inspection_company", false],
                ["inspector_name", "inspector_name", false],
                ["next_inspection_date", "next_inspection_date", false],
                ["next_inspection_month", "next_inspection_month", false],
                ["symbol_legend", "symbol_legend", false]
            ];

            for (const [inputName, sourceName, numeric] of infoFields) {
                const field = remember(
                    inputFor(record, inputName),
                    original[sourceName],
                    numeric
                );
                if (field) state.info.push(field);
            }

            const numericLineFields = new Set([
                "quantity", "unit_price",
                "labor_amount", "parts_amount", "amount"
            ]);
            const lineFields = [
                "description", "part_number", "unit", "notes", "category",
                "replacement_category",
                "replacement_action", "replacement_part_name",
                "quantity", "unit_price", "labor_amount", "parts_amount",
                "amount"
            ];

            record.querySelectorAll(".invoice-line").forEach((line, index) => {
                const inspection = line.hasAttribute("data-inspection-item");
                const source = (inspection ? original.inspection_items : original.line_items)?.[index];
                if (!source || typeof source !== "object") return;

                const fields = [];

                for (const name of (inspection ? ["category", "item_name", "raw_result", "result_text", "notes"] : lineFields)) {
                    const field = remember(
                        lineInput(line, name),
                        name === "replacement_action"
                            ? (source[name] || "review") : source[name],
                        numericLineFields.has(name)
                    );
                    if (field) fields.push(field);
                }

                const badge = document.createElement("span");
                badge.className = "invoice-change-label";
                badge.textContent = "修正済み";
                badge.hidden = true;
                line.querySelector("td").append(badge);

                const editor = line.nextElementSibling;
                const reset = editor?.querySelector("[data-reset-line]");

                state.lines.push({ line, fields, badge, reset });
            });

            resetStates.set(record, state);
            refreshChanges(record);
        });

        form.addEventListener("click", event => {
            const button = event.target.closest(
                "[data-reset-info], [data-reset-line]"
            );
            if (!button || button.disabled) return;

            const record = button.closest(".invoice-record");
            const state = resetStates.get(record);
            if (!state) return;

            if (button.hasAttribute("data-reset-info")) {
                restoreFields(record, state.info);
            } else {
                const editor = editorRowFor(button);
                const item = state.lines.find(
                    entry => entry.line.nextElementSibling === editor
                );
                if (item) restoreFields(record, item.fields);
            }
        });

        form.querySelectorAll("input[data-invoice-money]").forEach(el => {
            el.value = formatted(el.value);
        });

        form.querySelectorAll(".invoice-line").forEach(updateLine);
        form.querySelectorAll(".invoice-record").forEach(showVehicleCandidates);
        form.querySelectorAll(".invoice-record").forEach(updateFacts);

        form.querySelectorAll("[data-invoice-document]").forEach(block => {
            const active = block.querySelector(
                '[data-record-target][aria-pressed="true"]'
            );

            if (active) activate(block, active.dataset.recordTarget);


        });

        form.querySelectorAll("[data-invoice-document]").forEach(block => {
            const viewer = block.querySelector("[data-invoice-source]");
            const toggle = block.querySelector("[data-source-sync]");
            const status = block.querySelector("[data-sync-status]");
            if (!viewer || !toggle || !status) return;

            const records = Array.from(
                block.querySelectorAll(".invoice-record")
            );
            const pageOwners = new Map();

            for (const record of records) {
                let pages;
                try {
                    pages = JSON.parse(record.dataset.sourcePages || "[]");
                } catch {
                    pages = [];
                }
                if (!Array.isArray(pages)) continue;

                for (const value of new Set(pages.map(Number))) {
                    if (!Number.isInteger(value) || value < 1) continue;

                    if (!pageOwners.has(value)) {
                        pageOwners.set(value, []);
                    }
                    pageOwners.get(value).push(record);
                }
            }

            function activeRecord() {
                return block.querySelector(
                    ".invoice-record:not([hidden])"
                );
            }

            function editing() {
                const record = activeRecord();
                return Boolean(record?.querySelector(
                    ".invoice-info-editor:not([hidden]), "
                    + ".invoice-line-editor-row:not([hidden])"
                ));
            }

            function updateStatus() {
                if (!toggle.checked) {
                    status.textContent = "連動OFF：左右を自由に閲覧";
                    return false;
                }
                if (editing()) {
                    status.textContent = "連動を一時停止：修正中";
                    return false;
                }

                status.textContent =
                    "表示中の原本に合わせて記録を切替";
                return true;
            }

            function requestSync() {
                if (!updateStatus()) return;
                viewer.dispatchEvent(
                    new CustomEvent("dkss:sync-request")
                );
            }

            viewer.addEventListener("dkss:visible-page", event => {
                if (!updateStatus()) return;

                const page = Number(event.detail?.page);
                const owners = pageOwners.get(page) || [];

                if (owners.length !== 1) {
                    status.textContent = owners.length > 1
                        ? "このページに複数の記録があります。上で選択してください"
                        : "このページに対応する読取結果はありません";
                    return;
                }

                const target = owners[0];

                if (
                    activeRecord()?.dataset.recordKey
                    !== target.dataset.recordKey
                ) {
                    activate(block, target.dataset.recordKey, true);
                }

                event.detail.accepted = true;
                updateStatus();
            });

            toggle.addEventListener("change", requestSync);

            block.addEventListener("click", () => {
                requestAnimationFrame(() => {
                    requestSync();
                });
            });

            updateStatus();
        });

        window.DkssInvoiceReviewControls(form);

        form.addEventListener("click", event => {
            const button = event.target.closest("button");
            if (!button || button.type === "submit") return;

            const record = button.closest(".invoice-record");

            if (button.hasAttribute("data-record-target")) {
                activate(
                    button.closest("[data-invoice-document]"),
                    button.dataset.recordTarget
                );
            } else if (button.hasAttribute("data-toggle-info")) {
                const panel = document.getElementById(
                    button.getAttribute("aria-controls")
                );

                panel.hidden = !panel.hidden;
                button.setAttribute("aria-expanded", String(!panel.hidden));
                button.textContent = panel.hidden
                    ? "情報を修正"
                    : "修正を閉じる";
            } else if (button.hasAttribute("data-close-info")) {
                const panel = button.closest(".invoice-info-editor");
                panel.hidden = true;

                const toggle = record.querySelector("[data-toggle-info]");
                toggle.setAttribute("aria-expanded", "false");
                toggle.textContent = "情報を修正";
                toggle.focus({ preventScroll: true });
            } else if (button.hasAttribute("data-toggle-line-edit")) {
                const on = button.getAttribute("aria-pressed") !== "true";
                button.setAttribute("aria-pressed", String(on));
                button.textContent = on ? "修正を終了" : "明細を修正";

                record.querySelector(".invoice-edit-hint").hidden = !on;
                record.querySelectorAll("[data-edit-line]").forEach(el => {
                    el.disabled = !on;
                });

                if (!on) closeLines(record);
            } else if (
                button.hasAttribute("data-edit-line") && !button.disabled
            ) {
                openLine(button.closest(".invoice-line"));
            } else if (button.hasAttribute("data-close-line")) {
                closeLines(record);
            } else if (button.hasAttribute("data-show-source")) {
                const block = record.closest("[data-invoice-document]");
                block.querySelector(".invoice-source-disclosure").open = true;
                sourcePage(block, button.dataset.showSource);
            }
        });

        function applyLineFilters(record) {
            const search = record.querySelector("[data-line-search]");
            const filter = record.querySelector("[data-line-filter]");
            if (!search || !filter) return;

            if (record.querySelector(
                ".invoice-line-editor-row:not([hidden])"
            )) return;

            const normalize = value => String(value ?? "")
                .normalize("NFKC").toLocaleLowerCase().trim();

            const terms = normalize(search.value).split(/\s+/).filter(Boolean);
            const lines = Array.from(record.querySelectorAll(".invoice-line"));
            let count = 0;

            for (const line of lines) {
                const text = normalize(
                    ["description", "part_number", "category", "item_name", "raw_result", "result_text", "notes"]
                        .map(field => lineValue(line, field))
                        .join(" ")
                );

                const matchesSearch = terms.every(term => text.includes(term));
                const hasAmount = [
                    "labor_amount", "parts_amount", "amount"
                ].some(field => lineValue(line, field) !== "");

                const matchesFilter =
                    filter.value === "all"
                    || (filter.value === "modified"
                        && line.classList.contains("is-modified"))
                    || (filter.value === "amount" && hasAmount)
                    || (filter.value === "replacement_review"
                        && replacementNeedsReview(line));

                line.hidden = !(matchesSearch && matchesFilter);
                if (!line.hidden) count++;
            }

            record.querySelector("[data-line-filter-count]").textContent =
                count + " / " + lines.length + "件を表示";

            record.querySelector("[data-line-filter-empty]").hidden =
                count !== 0;

            record.querySelector("[data-clear-line-filter]").disabled =
                search.value === "" && filter.value === "all";
        }

        function changeLineFilter(event) {
            if (!event.target.matches(
                "[data-line-search], [data-line-filter]"
            )) return;

            const record = event.target.closest(".invoice-record");
            if (record) closeLines(record);
        }

        form.addEventListener("input", changeLineFilter);
        form.addEventListener("change", changeLineFilter);

        form.addEventListener("click", event => {
            const button = event.target.closest("[data-clear-line-filter]");
            if (!button || button.disabled) return;

            const record = button.closest(".invoice-record");
            record.querySelector("[data-line-search]").value = "";
            record.querySelector("[data-line-filter]").value = "all";
            closeLines(record);
            record.querySelector("[data-line-search]").focus({
                preventScroll: true
            });
        });

        form.querySelectorAll(".invoice-record").forEach(applyLineFilters);

        function updateFromInput(input) {
            const record = input.closest(".invoice-record");
            if (!record) return;

            const editorRow = editorRowFor(input);

            if (editorRow) {
                updateLine(editorRow.previousElementSibling);
            } else {
                updateFacts(record);
            }

            refreshChanges(record);
        }

        form.addEventListener("input", event => updateFromInput(event.target));
        form.addEventListener("change", event => updateFromInput(event.target));

        form.addEventListener("focusout", event => {
            const input = event.target;

            if (input.matches("input[data-invoice-money]")) {
                input.value = formatted(input.value);
                updateFromInput(input);
            }
        });

        function revealErrorTarget(target) {
            const record = target.closest(".invoice-record");
            if (!record) return;

            activate(
                record.closest("[data-invoice-document]"),
                record.dataset.recordKey
            );

            const search = record.querySelector("[data-line-search]");
            const filter = record.querySelector("[data-line-filter]");
            if (search) search.value = "";
            if (filter) filter.value = "all";
            closeLines(record);

            const info = target.closest(".invoice-info-editor");
            if (info) {
                info.hidden = false;
                const toggle = record.querySelector("[data-toggle-info]");
                toggle.setAttribute("aria-expanded", "true");
                toggle.textContent = "修正を閉じる";
            }

            const editor = editorRowFor(target);
            if (editor) {
                openLine(editor.previousElementSibling);
            }

            let details = target.closest("details");
            while (details && record.contains(details)) {
                details.open = true;
                details = details.parentElement?.closest("details");
            }
        }

        form.addEventListener(
            "invalid",
            event => revealErrorTarget(event.target),
            true
        );

        new MutationObserver(changes => {
            changes.forEach(change => {
                if (change.target.getAttribute("aria-invalid") === "true") {
                    revealErrorTarget(change.target);
                }
            });
        }).observe(form, {
            subtree: true,
            attributes: true,
            attributeFilter: ["aria-invalid"]
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }
})();