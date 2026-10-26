// certificate-invoice-controls-v1
(() => {
    "use strict";

    const uploadForm = document.getElementById("certificate-upload-form");
    const review = document.getElementById("certificate-review");
    const reviewShell = document.getElementById("certificate-review-shell");
    const choiceGrid = document.getElementById("registration-choice-grid");
    const choiceGuide = document.getElementById("registration-choice-guide");
    const backButton = document.getElementById("certificate-back-button");
    if (!uploadForm || !review || !reviewShell || !choiceGrid || !choiceGuide || !backButton) return;

    const fileInput = document.getElementById("certificate-file");
    const fileLabel = document.getElementById("certificate-file-label");
    const status = document.getElementById("certificate-status");
    const errorBox = document.getElementById("certificate-error");
    const readButton = document.getElementById("certificate-read-button");
    const resetButton = document.getElementById("certificate-reset-fields");
    const clearButton = document.getElementById("certificate-clear");
    const progress = document.getElementById("certificate-progress");
    const zone = uploadForm.querySelector(".import-dropzone");
    const zoneTitle = zone.querySelector(".import-drop-copy strong");
    const zoneDetail = zone.querySelector(".import-drop-copy small");
    const zonePick = zone.querySelector(".import-pick-button");
    const defaultTitle = zoneTitle.textContent;
    const defaultDetail = zoneDetail.textContent;
    const changeLabel = document.getElementById("certificate-change-label");
    const warningBox = document.getElementById("certificate-warnings");
    const continueButton = document.getElementById(
        "certificate-continue-button"
    );

    const fields = Array.from(
        review.querySelectorAll("[data-certificate-field]")
    );
    const originals = new Map();

    window.DkssInvoiceReviewControls(review);

    let reading = false;
    let extractionReady = false;

    function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = !message;
    }

    function updateChanges() {
        if (!extractionReady) {
            changeLabel.hidden = true;
            resetButton.disabled = true;
            return;
        }

        const changed = fields.some(
            field => field.value !== (originals.get(field.name) ?? "")
        );

        changeLabel.hidden = !changed;
        resetButton.disabled = !changed;
    }

    function showWarnings(warnings) {
        warningBox.replaceChildren();

        if (!Array.isArray(warnings) || !warnings.length) {
            warningBox.hidden = true;
            return;
        }

        const list = document.createElement("ul");

        for (const warning of warnings) {
            if (typeof warning !== "string") continue;
            const item = document.createElement("li");
            item.textContent = warning;
            list.append(item);
        }

        warningBox.append(list);
        warningBox.hidden = !list.children.length;
    }


    const sourceContainer = document.getElementById(
        "certificate-source-container"
    );
    const pdfTemplate = document.getElementById(
        "certificate-pdf-template"
    );

    // certificate-preview-height-v2
    let previewFitFrame = null;
    function fitCertificatePreview() {
        previewFitFrame = null;
        if (reviewShell.hidden || review.hidden) return;
        const layout = review.querySelector(".invoice-review-layout");
        const viewer = sourceContainer.querySelector(":scope > .invoice-pdf-viewer");
        if (!layout || !viewer) return;
        const narrow = window.matchMedia("(max-width: 1000px)").matches;
        const actions = review.querySelector(".invoice-submit-actions");
        if (narrow) {
            layout.style.removeProperty("height");
        } else {
            const available = Math.max(260, Math.floor(
                window.innerHeight - layout.getBoundingClientRect().top
                - (actions?.getBoundingClientRect().height || 0) - 24
            ));
            const value = available + "px";
            if (layout.style.height !== value) layout.style.height = value;
        }
        const paneHeight = narrow
            ? Math.max(300, Math.min(window.innerHeight * 0.65, 600))
            : layout.clientHeight;
        const summary = sourceContainer.querySelector(":scope > summary");
        const height = Math.max(180, Math.floor(
            paneHeight - (summary?.getBoundingClientRect().height || 30)
        ));
        // Match the invoice screen: a definite pixel height bounds the scroll area.
        viewer.style.height = height + "px";
        viewer.style.maxHeight = height + "px";
        viewer.style.minHeight = "0";
        const scroll = viewer.querySelector(".invoice-pdf-scroll");
        if (scroll) {
            scroll.style.minHeight = "0";
            scroll.style.flex = "1 1 0px";
            scroll.style.overflowY = "scroll";
            scroll.style.overflowX = "auto";
            scroll.style.scrollbarGutter = "stable";
        }
    }
    function scheduleCertificatePreviewFit() {
        if (previewFitFrame === null) {
            previewFitFrame = requestAnimationFrame(fitCertificatePreview);
        }
    }
    window.addEventListener("resize", scheduleCertificatePreviewFit);
    window.visualViewport?.addEventListener("resize", scheduleCertificatePreviewFit);
    sourceContainer.addEventListener("toggle", scheduleCertificatePreviewFit);
    new MutationObserver(scheduleCertificatePreviewFit).observe(sourceContainer, { childList: true });
    new MutationObserver(scheduleCertificatePreviewFit).observe(reviewShell, { attributes: true, attributeFilter: ["hidden"] });
    const previewLayout = review.querySelector(".invoice-review-layout");
    if (previewLayout) new ResizeObserver(scheduleCertificatePreviewFit).observe(previewLayout);
    const mainContent = review.closest(".main-content");
    if (mainContent) new ResizeObserver(scheduleCertificatePreviewFit).observe(mainContent);
    document.fonts?.ready.then(scheduleCertificatePreviewFit);

    let sourceUrl = null;
    let pdfViewer = null;
    let imageFitObserver = null;
    let previewGeneration = 0;

    function clearPreview() {
        previewGeneration++;
        pdfViewer?.destroy();
        pdfViewer = null;
        imageFitObserver?.disconnect();
        imageFitObserver = null;
        if (sourceContainer) {
            for (const node of sourceContainer.querySelectorAll(":scope > .invoice-pdf-viewer")) {
                node.remove();
            }
        }
        if (sourceUrl) {
            URL.revokeObjectURL(sourceUrl);
            sourceUrl = null;
        }
    }

    async function showOriginal(file) {
        if (!sourceContainer || !pdfTemplate) {
            throw new Error("Original viewer is not available");
        }

        clearPreview();
        const currentPreview = previewGeneration;
        sourceUrl = URL.createObjectURL(file);

        if (/\.pdf$/i.test(file.name)) {
            const { InvoicePdfViewer } = await import(
                "./maintenance_invoice_pdf_viewer.mjs?v=20261026-portrait-review-1"
            );
            const bytes = new Uint8Array(await file.arrayBuffer());
            if (currentPreview !== previewGeneration) return;
            const root = pdfTemplate.content.firstElementChild.cloneNode(true);
            root.dataset.defaultFit = "page";
            root.dataset.filename = file.name;
            root.dataset.sourceBase = sourceUrl;
            sourceContainer.append(root);
            pdfViewer = new InvoicePdfViewer(root, { data: bytes });
            await pdfViewer.ready;
            return;
        }

        if (!/\.(png|jpe?g)$/i.test(file.name)) {
            throw new Error("Unsupported original file type");
        }

        const wrapper = document.createElement("section");
        wrapper.className = "invoice-pdf-viewer";

        const toolbar = document.createElement("div");
        toolbar.className = "invoice-pdf-toolbar";

        const zoomControls = document.createElement("div");
        zoomControls.className = "invoice-pdf-zoom";

        const minus = document.createElement("button");
        minus.type = "button";
        minus.textContent = "\u2212";
        minus.setAttribute("aria-label", "Shrink image");

        const output = document.createElement("output");

        const plus = document.createElement("button");
        plus.type = "button";
        plus.textContent = "+";
        plus.setAttribute("aria-label", "Enlarge image");

        const fit = document.createElement("button");
        fit.type = "button";
        fit.textContent = "\u5e45\u306b\u5408\u308f\u305b\u308b";

        const fitPage = document.createElement("button");
        fitPage.type = "button";
        fitPage.textContent = "全体";

        zoomControls.append(minus, output, plus, fitPage, fit);
        toolbar.append(zoomControls);

        const scroll = document.createElement("div");
        scroll.className = "invoice-pdf-scroll";
        scroll.tabIndex = 0;

        const image = document.createElement("img");
        image.src = sourceUrl;
        image.alt = "\u8eca\u691c\u8a3c\u306e\u539f\u672c";
        image.draggable = false;
        image.style.display = "block";
        image.style.height = "auto";
        image.style.marginInline = "auto";

        let scale = 1;
        let fitWholePage = true;

        function updateZoom(next, manual = true) {
            if (manual) fitWholePage = false;
            scale = Math.max(0.1, Math.min(4, next));
            image.style.width = `${scale * 100}%`;
            output.textContent = `${Math.round(scale * 100)}%`;
        }

        minus.addEventListener("click", () => updateZoom(scale / 1.2));
        plus.addEventListener("click", () => updateZoom(scale * 1.2));
        fit.addEventListener("click", () => updateZoom(1));
        function fitImagePage() {
            if (!fitWholePage || !image.naturalWidth || scroll.clientHeight < 40) return;
            const fullHeight = scroll.clientWidth * image.naturalHeight / image.naturalWidth;
            updateZoom(Math.min(1, (scroll.clientHeight - 16) / fullHeight), false);
            scroll.scrollTop = 0;
        }
        fitPage.addEventListener("click", () => { fitWholePage = true; fitImagePage(); });
        image.addEventListener("load", fitImagePage);
        imageFitObserver = new ResizeObserver(fitImagePage);
        imageFitObserver.observe(scroll);

        scroll.addEventListener("wheel", event => {
            if (!event.ctrlKey && !event.metaKey) return;
            event.preventDefault();
            updateZoom(scale * (event.deltaY < 0 ? 1.1 : 1 / 1.1));
        }, { passive: false });

        let drag = null;

        scroll.addEventListener("pointerdown", event => {
            if (event.button !== 0) return;
            drag = {
                x: event.clientX,
                y: event.clientY,
                left: scroll.scrollLeft,
                top: scroll.scrollTop
            };
            scroll.setPointerCapture(event.pointerId);
        });

        scroll.addEventListener("pointermove", event => {
            if (!drag) return;
            scroll.scrollLeft = drag.left - (event.clientX - drag.x);
            scroll.scrollTop = drag.top - (event.clientY - drag.y);
        });

        for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
            scroll.addEventListener(type, () => { drag = null; });
        }

        scroll.append(image);
        wrapper.append(toolbar, scroll);
        sourceContainer.append(wrapper);
        updateZoom(1, false);
    }

    function applyResult(result) {
        if (!result || !result.vehicle ||
            typeof result.vehicle !== "object" ||
            Array.isArray(result.vehicle)) {
            throw new Error("AIの読取結果が不正です。");
        }

        originals.clear();

        for (const field of fields) {
            const value = (field.name === "type" || field.name === "office")
                ? null : result.vehicle[field.name];
            const candidate = typeof value === "string" ? value : "";

            if (field.tagName === "SELECT") {
                const allowed = Array.from(field.options).some(
                    option => option.value === candidate
                );
                field.value = allowed ? candidate : "";
            } else {
                field.value = candidate;
            }

            originals.set(field.name, field.value);
            if (field.tagName === "SELECT") field.dispatchEvent(new Event("change", {bubbles:true}));
        }

        extractionReady = true;
        updateChanges();
        showWarnings(result.warnings);
        document.getElementById("certificate-review-filename").textContent =
            fileInput.files?.[0]?.name || "車検証の読取結果";

        choiceGrid.hidden = true;
        choiceGuide.hidden = true;
        reviewShell.hidden = false;
        review.hidden = false;
        sourceContainer.open = true;
        sourceContainer.dispatchEvent(new Event("toggle"));
        scheduleCertificatePreviewFit();

        // AI読取後は、原本との照合を経て登録確認へ進める。
        extractionReady = true;
        continueButton.disabled = false;

        status.textContent =
            "読み取りが完了しました。各項目を原本と照合してください。";

        reviewShell.scrollIntoView({ behavior: "instant", block: "start" });
    }

    continueButton.addEventListener("click", () => {
        if (reading || !extractionReady || review.hidden) {
            return;
        }

        // 未入力の必須項目を確認する。
        for (const field of fields) {
            if (!field.reportValidity()) {
                field.focus();
                return;
            }
        }

        const csrfToken = uploadForm.querySelector(
            'input[name="csrf_token"]'
        );

        if (!csrfToken || !csrfToken.value) {
            showError("認証情報を取得できません。画面を再読み込みしてください。");
            return;
        }

        // 既存の車両登録確認画面へ送る一時フォーム。
        // この段階ではDB保存を行わない。
        const form = document.createElement("form");
        form.method = "POST";
        form.action = "/master/vehicles/new";
        form.style.display = "none";

        const appendHidden = (name, value) => {
            const input = document.createElement("input");
            input.type = "hidden";
            input.name = name;
            input.value = value;
            form.appendChild(input);
        };

        appendHidden("csrf_token", csrfToken.value);

        for (const field of fields) {
            appendHidden(field.name, field.value.trim());
        }

        // vehicle_form_action=save は送らない。
        // 既存のnew_vehicle()が入力検証後に確認画面を表示する。
        document.body.appendChild(form);
        form.submit();
    });

    fields.forEach(field => {
        field.addEventListener("input", updateChanges);
        field.addEventListener("change", updateChanges);
    });

    resetButton.addEventListener("click", () => {
        if (!extractionReady) return;

        for (const field of fields) {
            field.value = originals.get(field.name) ?? "";
            if (field.tagName === "SELECT") field.dispatchEvent(new Event("change", {bubbles:true}));
        }

        updateChanges();
    });

    function validateFile(file) {
        if (!file) return "車検証ファイルを選択してください。";
        if (!/\.(pdf|png|jpe?g)$/i.test(file.name)) {
            return "PDF・PNG・JPEGを選択してください。";
        }
        if (!file.size || file.size > 20 * 1024 * 1024) {
            return "20MB以下のファイルを選択してください。";
        }
        return "";
    }

    function refreshFile() {
        if (reading) return;

        const file = fileInput.files?.[0];
        const issue = file ? validateFile(file) : "";
        const ready = Boolean(file && !issue);

        fileLabel.textContent = file
            ? file.name
            : "車検証を選択してください";

        zoneTitle.textContent = file ? file.name : defaultTitle;
        zoneTitle.title = file?.name || "";

        zoneDetail.textContent = file
            ? `${(file.size / 1024 / 1024).toFixed(1)} MB ・ ${
                ready ? "読み取りの準備ができました" : "選択内容を確認してください"
            }`
            : defaultDetail;

        zonePick.textContent = file ? "選び直す" : "ファイルを選ぶ";
        zone.classList.toggle("has-files", ready);

        clearButton.hidden = !file;
        readButton.disabled = !ready;

        status.textContent = ready
            ? "✓ 1ファイルを選択済み"
            : file ? "ファイルの確認が必要です" : "ファイル未選択";

        showError(issue);
    }

    function resetReview() {
        extractionReady = false;
        originals.clear();
        clearPreview();
        review.hidden = true;
        reviewShell.hidden = true;
        choiceGrid.hidden = false;
        choiceGuide.hidden = false;
        continueButton.disabled = true;
        updateChanges();
    }

    backButton.addEventListener("click", () => {
        if (reading) return;
        resetReview();
        refreshFile();
        choiceGrid.scrollIntoView({ behavior: "instant", block: "start" });
    });

    fileInput.addEventListener("change", () => {
        if (reading) return;
        resetReview();
        refreshFile();
    });

    clearButton.addEventListener("click", () => {
        if (reading) return;
        fileInput.value = "";
        resetReview();
        refreshFile();
        fileInput.focus();
    });

    for (const name of ["dragenter", "dragover"]) {
        zone.addEventListener(name, event => {
            event.preventDefault();
            if (!reading) zone.classList.add("is-dragging");
        });
    }

    zone.addEventListener("dragleave", event => {
        if (!zone.contains(event.relatedTarget)) {
            zone.classList.remove("is-dragging");
        }
    });

    zone.addEventListener("drop", event => {
        event.preventDefault();
        zone.classList.remove("is-dragging");

        if (reading) return;

        const files = event.dataTransfer.files;
        const file = files?.[0];

        if (!files || files.length !== 1 || validateFile(file)) {
            showError("PDF・PNG・JPEGを1ファイル（20MB以下）選択してください。");
            return;
        }

        fileInput.files = files;
        fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    function extractWithUploadProgress(payload, onUpload, onWaiting) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();

            xhr.open("POST", "/master/vehicles/certificate/extract");
            xhr.setRequestHeader("Accept", "application/json");

            xhr.upload.addEventListener("progress", event => {
                if (event.lengthComputable) {
                    onUpload(Math.round(
                        100 * event.loaded / event.total
                    ));
                }
            });

            xhr.upload.addEventListener("load", onWaiting);

            xhr.onerror = () => reject(
                new Error("通信エラーが発生しました。")
            );

            xhr.onload = () => {
                if (!(xhr.getResponseHeader("content-type") || "")
                    .includes("application/json")) {
                    reject(new Error(
                        "ログイン状態かサーバーの応答を確認してください。"
                    ));
                    return;
                }

                try {
                    const result = JSON.parse(xhr.responseText);

                    if (xhr.status < 200 || xhr.status >= 300) {
                        reject(new Error(
                            result.error || "車検証の読み取りに失敗しました。"
                        ));
                    } else {
                        resolve(result);
                    }
                } catch (error) {
                    reject(error);
                }
            };

            xhr.send(payload);
        });
    }

    uploadForm.addEventListener("submit", async event => {
        event.preventDefault();
        if (reading) return;

        const file = fileInput.files?.[0];
        const issue = validateFile(file);

        if (issue) {
            showError(issue);
            return;
        }

        reading = true;
        resetReview();

        uploadForm.dataset.loading = "1";
        uploadForm.setAttribute("aria-busy", "true");
        zone.classList.add("is-loading");

        const payload = new FormData(uploadForm);
        fileInput.disabled = true;
        clearButton.disabled = true;
        readButton.disabled = true;
        readButton.textContent = "読み取り中…";

        zonePick.textContent = "処理中";
        zoneTitle.textContent = "ファイルを送信しています";
        zoneDetail.textContent = "この画面を開いたままお待ちください";

        showError("");

        progress.hidden = false;
        progress.value = 0;
        progress.setAttribute("aria-label", "ファイルの送信率");

        const phase = document.createElement("span");
        phase.setAttribute("role", "status");
        phase.textContent = "送信中";

        const elapsed = document.createElement("span");
        elapsed.className = "import-elapsed";
        elapsed.setAttribute("aria-hidden", "true");

        status.replaceChildren(phase, elapsed);

        const started = Date.now();

        const timer = window.setInterval(() => {
            const seconds = Math.floor(
                (Date.now() - started) / 1000
            );

            elapsed.textContent =
                "経過 " + Math.floor(seconds / 60) +
                ":" + String(seconds % 60).padStart(2, "0");

            if (
                seconds >= 60 &&
                phase.textContent === "② AI読取中（送信完了）"
            ) {
                zoneTitle.textContent =
                    "読み取りに時間がかかっています";
            }
        }, 1000);

        let failureMessage = "";

        try {
            const result = await extractWithUploadProgress(
                payload,
                percent => {
                    progress.value = percent;
                    phase.textContent =
                        "ファイル送信 " + percent + "％";
                },
                () => {
                    progress.removeAttribute("value");
                    phase.textContent = "② AI読取中（送信完了）";

                    zoneTitle.textContent =
                        "資料の読み取り結果を待っています";

                    zoneDetail.textContent =
                        "AIで内容を確認しています。画面を閉じずにお待ちください";
                }
            );

            progress.value = 100;
            phase.textContent = "読み取り完了";

            applyResult(result);

            try {
                await showOriginal(file);
            } catch (previewError) {
                showError(
                    "AI読取は完了しましたが、原本の表示に失敗しました。"
                );
            }
        } catch (error) {
            failureMessage =
                error.message || "通信エラーが発生しました。";

            status.textContent = "読み取りに失敗しました。";
            showError(failureMessage);
        } finally {
            window.clearInterval(timer);

            reading = false;
            delete uploadForm.dataset.loading;
            uploadForm.setAttribute("aria-busy", "false");
            zone.classList.remove("is-loading");

            fileInput.disabled = false;
            clearButton.disabled = false;
            readButton.textContent = "読み込んで確認";
            progress.hidden = true;

            if (!extractionReady) {
                refreshFile();

                if (failureMessage) {
                    status.textContent = "読み取りに失敗しました。";
                    showError(failureMessage);
                }
            } else {
                readButton.disabled = false;
                zonePick.textContent = "選び直す";
                zoneTitle.textContent = file.name;
                zoneDetail.textContent = "読み取りが完了しました";
                status.textContent =
                    "読み取りが完了しました。原本と照合してください。";
            }
        }
    });
})();


// certificate-external-assets-v1
(() => {
    "use strict";

    const form = document.getElementById("registration-excel-form");
    if (!form) return;

    const input = document.getElementById("registration-excel-file");
    const dropzone = document.getElementById("registration-excel-dropzone");
    const title = document.getElementById("registration-excel-title");
    const detail = document.getElementById("registration-excel-detail");
    const status = document.getElementById("registration-excel-status");
    const clear = document.getElementById("registration-excel-clear");
    const submit = document.getElementById("registration-excel-submit");

    function update() {
        const file = input.files[0];
        const valid = !!file && /\.xlsx$/i.test(file.name);

        title.textContent = file ? file.name : "Excelをここにドロップ";
        detail.textContent = file
            ? (file.size / 1024 / 1024).toFixed(2) + " MB"
            : "Excel（.xlsx）／1ファイル";

        status.textContent = !file
            ? "ファイル未選択"
            : valid ? "1ファイルを選択済み" : "xlsx形式を選択してください";

        dropzone.classList.toggle("has-files", valid);
        clear.hidden = !file;
        submit.disabled = !valid;
    }

    input.addEventListener("change", update);

    clear.addEventListener("click", () => {
        input.value = "";
        update();
    });

    for (const type of ["dragenter", "dragover"]) {
        dropzone.addEventListener(type, event => {
            event.preventDefault();
            dropzone.classList.add("is-dragging");
        });
    }

    dropzone.addEventListener("dragleave", event => {
        if (!dropzone.contains(event.relatedTarget)) {
            dropzone.classList.remove("is-dragging");
        }
    });

    dropzone.addEventListener("drop", event => {
        event.preventDefault();
        dropzone.classList.remove("is-dragging");

        if (event.dataTransfer.files.length !== 1) {
            status.textContent = "Excelファイルを1件選択してください";
            return;
        }

        input.files = event.dataTransfer.files;
        update();
    });

    form.addEventListener("submit", event => {
        if (!input.files.length ||
            !/\.xlsx$/i.test(input.files[0].name)) {
            event.preventDefault();
            update();
            return;
        }

        submit.disabled = true;
        submit.textContent = "読み込み中…";
    });

    update();
})();
