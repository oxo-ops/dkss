import * as pdfjs from "../vendor/pdfjs/pdf.mjs";

pdfjs.GlobalWorkerOptions.workerSrc =
    new URL("../vendor/pdfjs/pdf.worker.mjs", import.meta.url).href;

const asset = name =>
    new URL("../vendor/pdfjs/" + name + "/", import.meta.url).href;

export class InvoicePdfViewer {
    constructor(root, options = {}) {
        this.options = options;
        this.destroyed = false;
        this.root = root;
        this.scroll = root.querySelector("[data-pdf-scroll]");
        this.stage = root.querySelector("[data-pdf-stage]");
        this.status = root.querySelector("[data-pdf-status]");
        this.pageInput = root.querySelector("[data-pdf-page]");
        this.zoomOutput = root.querySelector("[data-pdf-zoom]");
        this.pages = [];
        this.current = 1;
        this.scale = 1;
        this.fit = true;
        this.fitMode = root.dataset.defaultFit === "page" ? "page" : "width";
        this.generation = 0;
        this.running = 0;
        this.queue = [];
        this.busy = new Set();
        this.pending = Number(root.dataset.requestedPage || 1);
        this.activeKey = root.dataset.requestedRecordKey || "";
        this.viewStates = new Map();
        this.bind();
        this.ready = this.load();
    }

    bind() {
        let pan = null;

        const endPan = () => {
            if (!pan) return;
            const pointerId = pan.pointerId;
            pan = null;
            this.scroll.classList.remove("is-panning");

            if (this.scroll.hasPointerCapture(pointerId)) {
                this.scroll.releasePointerCapture(pointerId);
            }
        };

        this.scroll.addEventListener("pointerdown", event => {
            if (
                event.pointerType !== "mouse"
                || event.button !== 0
                || !event.isPrimary
            ) return;

            const rect = this.scroll.getBoundingClientRect();
            const insideX = event.clientX - rect.left - this.scroll.clientLeft;
            const insideY = event.clientY - rect.top - this.scroll.clientTop;

            if (
                insideX < 0
                || insideY < 0
                || insideX >= this.scroll.clientWidth
                || insideY >= this.scroll.clientHeight
            ) return;

            if (
                this.scroll.scrollWidth <= this.scroll.clientWidth
                && this.scroll.scrollHeight <= this.scroll.clientHeight
            ) return;

            pan = {
                pointerId: event.pointerId,
                x: event.clientX,
                y: event.clientY,
                left: this.scroll.scrollLeft,
                top: this.scroll.scrollTop
            };

            this.scroll.focus({ preventScroll: true });
            this.scroll.setPointerCapture(event.pointerId);
            this.scroll.classList.add("is-panning");
            event.preventDefault();
        });

        this.scroll.addEventListener("pointermove", event => {
            if (!pan || event.pointerId !== pan.pointerId) return;

            if ((event.buttons & 1) === 0) {
                endPan();
                return;
            }

            this.scroll.scrollLeft = pan.left - (event.clientX - pan.x);
            this.scroll.scrollTop = pan.top - (event.clientY - pan.y);
            event.preventDefault();
        });

        this.scroll.addEventListener("pointerup", endPan);
        this.scroll.addEventListener("pointercancel", endPan);
        this.scroll.addEventListener("lostpointercapture", endPan);
        this.endPan = endPan;
        window.addEventListener("blur", endPan);

        this.scroll.addEventListener("dragstart", event => {
            event.preventDefault();
        });
        this.root.querySelector("[data-pdf-prev]").addEventListener(
            "click", () => this.go(this.current - 1)
        );
        this.root.querySelector("[data-pdf-next]").addEventListener(
            "click", () => this.go(this.current + 1)
        );
        this.root.querySelector("[data-pdf-minus]").addEventListener(
            "click", () => this.zoom(this.scale / 1.2)
        );
        this.root.querySelector("[data-pdf-plus]").addEventListener(
            "click", () => this.zoom(this.scale * 1.2)
        );
        this.root.querySelector("[data-pdf-fit]").addEventListener(
            "click", () => this.fitWidth()
        );
        this.root.querySelector("[data-pdf-fit-page]")?.addEventListener(
            "click", () => this.fitPage()
        );

        this.pageInput.addEventListener(
            "change", () => this.go(Number(this.pageInput.value))
        );
        this.pageInput.addEventListener("keydown", event => {
            if (event.key === "Enter") {
                event.preventDefault();
                this.go(Number(this.pageInput.value));
            }
        });

        this.root.addEventListener(
            "dkss:source-page",
            event => this.handleSourceRequest(event.detail)
        );

        this.root.addEventListener("dkss:record-adopt", event => {
            this.activeKey = String(event.detail || "");
        });

        this.root.addEventListener("dkss:sync-request", () => {
            this.syncCurrent();
            this.reportVisiblePage();
        });

        this.scroll.addEventListener("scroll", () => {
            if (this.scrollFrame) return;
            this.scrollFrame = requestAnimationFrame(() => {
                this.scrollFrame = null;
                this.syncCurrent();
                this.visible();
                this.reportVisiblePage();
            });
        }, { passive: true });

        this.scroll.addEventListener("wheel", event => {
            if (!event.ctrlKey && !event.metaKey) return;
            event.preventDefault();
            const rect = this.scroll.getBoundingClientRect();
            this.zoom(
                this.scale * (event.deltaY < 0 ? 1.1 : 1 / 1.1),
                {
                    x: event.clientX - rect.left - this.scroll.clientLeft,
                    y: event.clientY - rect.top - this.scroll.clientTop
                }
            );
        }, { passive: false });

        this.scroll.addEventListener("keydown", event => {
            if (event.key === "+" || event.key === "=") {
                event.preventDefault();
                this.zoom(this.scale * 1.2);
            } else if (event.key === "-") {
                event.preventDefault();
                this.zoom(this.scale / 1.2);
            } else if (event.key === "0") {
                event.preventDefault();
                this.fitWidth();
            }
        });

        this.resizeObserver = new ResizeObserver(() => {
            clearTimeout(this.resizeTimer);
            this.resizeTimer = setTimeout(() => {
                if (this.fit && this.pages.length && this.scroll.clientWidth) {
                    this.fitView();
                }
            }, 120);
        });
        this.resizeObserver.observe(this.scroll);

        const disclosure = this.root.closest("details");
        if (disclosure) {
            disclosure.addEventListener("toggle", () => {
                if (disclosure.open && this.fit) {
                    requestAnimationFrame(() => this.fitView());
                }
            });
        }
    }

    showSourceFallback(message) {
        this.root.dataset.pdfError = "true";
        const link = document.createElement("a");
        link.href = this.root.dataset.sourceBase;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "原本を別タブで開く";
        this.status.replaceChildren(
            document.createTextNode(message + " "),
            link
        );
    }

    async load() {
        try {
            if (this.options.data) {
                this.loadingTask = pdfjs.getDocument({
                    data: this.options.data,
                    isEvalSupported: false,
                    useWasm: false,
                    cMapUrl: asset("cmaps"),
                    cMapPacked: true,
                    standardFontDataUrl: asset("standard_fonts"),
                    wasmUrl: asset("wasm"),
                    iccUrl: asset("iccs")
                });
                this.pdf = await this.loadingTask.promise;
            } else {
            const url = new URL(this.root.dataset.sourceBase, location.href);
            if (url.origin !== location.origin) {
                throw new Error("Source must be same-origin");
            }

            if (/\.(png|jpe?g)$/i.test(this.root.dataset.filename || "")) {
                url.searchParams.set("preview", "pdf");
            } else if (!/\.pdf$/i.test(this.root.dataset.filename || "")) {
                this.showSourceFallback("この原本の形式には対応していません。");
                return;
            }

            this.loadingTask = pdfjs.getDocument({
                url: url.href,
                withCredentials: true,
                isEvalSupported: false,
                useWasm: false,
                cMapUrl: asset("cmaps"),
                cMapPacked: true,
                standardFontDataUrl: asset("standard_fonts"),
                wasmUrl: asset("wasm"),
                iccUrl: asset("iccs")
            });
            this.pdf = await this.loadingTask.promise;

            }
            if (this.destroyed) return;

            this.root.querySelector("[data-pdf-count]").textContent =
                String(this.pdf.numPages);
            this.pageInput.max = String(this.pdf.numPages);

            for (let n = 1; n <= this.pdf.numPages; n++) {
                const page = await this.pdf.getPage(n);
                if (this.destroyed) return;
                const element = document.createElement("div");
                element.className = "invoice-pdf-page";
                element.setAttribute("role", "img");
                element.setAttribute("aria-label", "原本 " + n + "頁");
                element.dataset.page = String(n);

                const label = document.createElement("span");
                label.className = "invoice-pdf-page-label";
                label.textContent = n + "頁";
                element.append(label);
                this.stage.append(element);

                this.pages.push({
                    number: n,
                    page,
                    element,
                    viewport: page.getViewport({ scale: 1 }),
                    generation: -1,
                    task: null
                });
            }

            this.status.textContent =
                "スクロールでページ移動 · Ctrl＋ホイールで拡大縮小";
            this.fitView();
            this.go(this.pending);
        } catch (error) {
            if (this.destroyed) return;
            this.showSourceFallback("原本を表示できませんでした。");
            console.error("Invoice PDF preview failed", error);
        }
    }

    destroy() {
        this.destroyed = true;
        this.generation++;
        this.queue = [];
        this.endPan?.();
        window.removeEventListener("blur", this.endPan);
        this.resizeObserver?.disconnect();
        clearTimeout(this.resizeTimer);
        if (this.scrollFrame) cancelAnimationFrame(this.scrollFrame);
        for (const entry of this.pages) entry.task?.cancel();
        void this.loadingTask?.destroy().catch(() => {});
    }

    pageTop(entry) {
        return entry.element.getBoundingClientRect().top
            - this.scroll.getBoundingClientRect().top
            - this.scroll.clientTop
            + this.scroll.scrollTop;
    }

    pageLeft(entry) {
        return entry.element.getBoundingClientRect().left
            - this.scroll.getBoundingClientRect().left
            - this.scroll.clientLeft
            + this.scroll.scrollLeft;
    }

    saveView() {
        if (!this.activeKey || !this.pages.length) return;

        let anchor = this.pages[0];

        for (const entry of this.pages) {
            const top = this.pageTop(entry);
            if (top <= this.scroll.scrollTop) anchor = entry;
            else break;
        }

        const top = this.pageTop(anchor);
        const left = this.pageLeft(anchor);

        this.viewStates.set(this.activeKey, {
            scale: this.scale,
            fit: this.fit,
            fitMode: this.fitMode,
            page: anchor.number,
            x: (this.scroll.scrollLeft - left)
                / (anchor.element.offsetWidth || 1),
            y: (this.scroll.scrollTop - top)
                / (anchor.element.offsetHeight || 1)
        });
    }

    restoreView(state) {
        this.current = Math.max(
            1,
            Math.min(this.pages.length, state.page)
        );
        this.fit = state.fit;
        this.fitMode = state.fitMode || "width";

        if (state.fit) {
            this.fitView();
        } else {
            this.resize(state.scale);
        }

        const anchor = this.pages[this.current - 1];

        this.scroll.scrollTop = Math.max(
            0,
            this.pageTop(anchor)
                + state.y * anchor.element.offsetHeight
        );
        this.scroll.scrollLeft = Math.max(
            0,
            this.pageLeft(anchor)
                + state.x * anchor.element.offsetWidth
        );

        this.syncCurrent();
        this.visible();
    }

    handleSourceRequest(request) {
        if (!request || typeof request !== "object") {
            this.go(Number(request));
            return;
        }

        const page = Number(request.page) || 1;
        const key = String(request.key || "");

        if (!this.pages.length) {
            this.activeKey = key;
            this.pending = page;
            return;
        }

        if (key !== this.activeKey) {
            this.saveView();
            this.activeKey = key;

            const saved = this.viewStates.get(key);
            if (saved) {
                this.restoreView(saved);
            } else {
                this.fitView();
                this.go(page);
            }
            return;
        }

        if (request.switching) return;

        if (page !== this.current) {
            this.go(page);
        }
    }

    fitWidth() {
        this.fitMode = "width";
        this.fitView();
    }

    fitPage() {
        this.fitMode = "page";
        this.fitView();
        this.go(this.current);
    }

    fitView() {
        if (!this.pages.length || this.scroll.clientWidth < 40) return;
        this.fit = true;
        const widthScale = (this.scroll.clientWidth - 28)
            / Math.max(...this.pages.map(entry => entry.viewport.width));
        const page = this.pages[this.current - 1] || this.pages[0];
        const heightScale = Math.max(1, this.scroll.clientHeight - 24) / page.viewport.height;
        this.resize(this.fitMode === "page" ? Math.min(widthScale, heightScale) : widthScale);
    }

    zoom(scale, point = null) {
        this.fit = false;
        this.resize(scale, point);
    }

    resize(scale, point = null) {
        this.syncMuteUntil = performance.now() + 300;
        if (!this.pages.length) return;
        scale = Math.min(4, Math.max(0.2, scale));

        if (
            Math.abs(this.scale - scale) < 0.001
            && this.pages.every(entry => entry.element.style.width && entry.element.style.height)
        ) {
            this.visible();
            return;
        }

        const offsetX = Math.max(
            0,
            Math.min(this.scroll.clientWidth, point?.x ?? this.scroll.clientWidth / 2)
        );
        const offsetY = Math.max(
            0,
            Math.min(this.scroll.clientHeight, point?.y ?? this.scroll.clientHeight / 2)
        );

        const documentY = this.scroll.scrollTop + offsetY;
        let anchor = this.pages[0];

        for (const entry of this.pages) {
            const top = this.pageTop(entry);
            if (top <= documentY) anchor = entry;
            else break;
        }

        const oldTop = this.pageTop(anchor);
        const oldLeft = this.pageLeft(anchor);

        const fraction =
            (documentY - oldTop) / (anchor.element.offsetHeight || 1);
        const horizontal =
            (this.scroll.scrollLeft + offsetX - oldLeft)
            / (anchor.element.offsetWidth || 1);

        this.scale = scale;
        this.generation++;
        this.queue = [];

        for (const entry of this.pages) {
            if (entry.task) entry.task.cancel();
            entry.element.querySelector("canvas")?.remove();
            entry.generation = -1;

            const viewport = entry.page.getViewport({ scale });
            entry.element.style.width = Math.ceil(viewport.width) + "px";
            entry.element.style.height = Math.ceil(viewport.height) + "px";
        }

        this.zoomOutput.textContent = Math.round(scale * 100) + "%";
        this.scroll.scrollTop = Math.max(
            0,
            this.pageTop(anchor)
                + fraction * anchor.element.offsetHeight
                - offsetY
        );
        this.scroll.scrollLeft = Math.max(
            0,
            this.pageLeft(anchor)
                + horizontal * anchor.element.offsetWidth
                - offsetX
        );
        this.visible();
    }

    go(number) {
        this.syncMuteUntil = performance.now() + 300;
        if (!Number.isFinite(number)) number = this.current;
        number = Math.trunc(number);
        this.pending = number;
        if (!this.pages.length) return;

        number = Math.max(1, Math.min(this.pages.length, number));
        this.current = number;
        this.pageInput.value = String(number);

        if (this.fit && this.fitMode === "page") this.fitView();

        const target = this.pages[number - 1];
        this.scroll.scrollTop =
            this.pageTop(target) - 12;

        this.syncCurrent();
        this.enqueue(target);
        this.visible();
    }

    reportVisiblePage() {
        if (
            !this.pages.length
            || !this.scroll.clientHeight
            || performance.now() < (this.syncMuteUntil || 0)
        ) return;

        const detail = {
            page: this.current,
            accepted: false
        };

        this.root.dispatchEvent(
            new CustomEvent("dkss:visible-page", { detail })
        );

        if (detail.accepted) {
            this.saveView();
        }
    }

    syncCurrent() {
        if (!this.pages.length) return;

        const point = this.scroll.scrollTop
            + this.scroll.clientHeight / 2;
        let current = this.pages[0];

        for (const entry of this.pages) {
            if (this.pageTop(entry) <= point) {
                current = entry;
            } else {
                break;
            }
        }

        this.current = current.number;
        this.pageInput.value = String(this.current);
        this.root.querySelector("[data-pdf-prev]").disabled =
            this.current === 1;
        this.root.querySelector("[data-pdf-next]").disabled =
            this.current === this.pages.length;

        const label = this.root.closest(".invoice-source-panel")
            ?.querySelector("[data-source-page-label]");
        if (label) label.textContent = this.current + "頁";
    }

    visible() {
        if (this.destroyed || !this.pages.length || !this.scroll.clientHeight) return;

        const top = this.scroll.scrollTop - 300;
        const bottom =
            this.scroll.scrollTop + this.scroll.clientHeight + 300;

        for (const entry of this.pages) {
            const y = this.pageTop(entry);

            if (y < bottom && y + entry.element.offsetHeight > top) {
                this.enqueue(entry);
            } else if (
                Math.abs(entry.number - this.current) > 3
                && !this.busy.has(entry)
            ) {
                entry.element.querySelector("canvas")?.remove();
                entry.generation = -1;
            }
        }
    }

    enqueue(entry) {
        if (
            entry.generation === this.generation
            || this.busy.has(entry)
            || this.queue.includes(entry)
        ) return;

        this.queue.push(entry);
        this.pump();
    }

    pump() {
        while (!this.destroyed && this.running < 2 && this.queue.length) {
            const entry = this.queue.shift();

            if (
                entry.generation === this.generation
                || this.busy.has(entry)
            ) continue;

            this.running++;
            this.busy.add(entry);

            this.render(entry).finally(() => {
                this.running--;
                this.busy.delete(entry);
                entry.task = null;
                this.pump();
                this.visible();
            });
        }
    }

    async render(entry) {
        const generation = this.generation;
        const viewport = entry.page.getViewport({ scale: this.scale });
        const outputScale = Math.min(
            devicePixelRatio || 1,
            2,
            Math.sqrt(12000000 / (viewport.width * viewport.height))
        );

        const canvas = document.createElement("canvas");
        canvas.width = Math.max(
            1, Math.ceil(viewport.width * outputScale)
        );
        canvas.height = Math.max(
            1, Math.ceil(viewport.height * outputScale)
        );
        canvas.style.width = "100%";
        canvas.style.height = "100%";

        try {
            entry.task = entry.page.render({
                canvasContext: canvas.getContext("2d"),
                viewport,
                transform: outputScale === 1
                    ? null
                    : [outputScale, 0, 0, outputScale, 0, 0]
            });

            await entry.task.promise;
            if (generation !== this.generation) return;

            entry.element.querySelector("canvas")?.remove();
            entry.element.append(canvas);
            entry.generation = generation;
        } catch (error) {
            if (error?.name !== "RenderingCancelledException") {
                entry.generation = generation;
                entry.element.querySelector(".invoice-pdf-page-label")
                    .textContent = entry.number
                    + "頁：表示できません。原本を別タブで確認してください。";
            }
        }
    }
}

for (const root of document.querySelectorAll(".invoice-pdf-viewer")) {
    new InvoicePdfViewer(root);
}
