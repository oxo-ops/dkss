(function () {
    "use strict";
    const MAX_BATCH_BYTES = 200 * 1024 * 1024;
    function localUrl(value) {
        if (!value) return null;
        try {
            const url = new URL(value, location.href);
            return url.origin === location.origin && /^\/vehicle\/data-import(\/|$)/.test(url.pathname) ? url : null;
        } catch (_) { return null; }
    }
    function watchInline(form, initial, release) {
        const statusUrl = localUrl(initial.status_url);
        if (!statusUrl) { release("読取状況の確認先が不正です。受付済みの資料から確認してください。"); return; }
        form.querySelector(".import-inline-progress")?.remove();
        const panel = document.createElement("div");
        panel.className = "import-inline-progress";
        const progress = document.createElement("progress");
        progress.className = "import-progress";
        progress.setAttribute("aria-label", "資料の読み取り状況");
        const files = document.createElement("ul"); files.className = "import-inline-files";
        const actions = document.createElement("div"); actions.className = "import-inline-actions";
        panel.append(progress, files, actions); form.append(panel);
        const status = form.querySelector(".import-file-status");
        const button = form.querySelector('button[type="submit"]');
        const zone = form.querySelector(".import-dropzone");
        form.dataset.loading = "1";
        form.setAttribute("aria-busy", "true");
        zone?.classList.add("is-loading");
        button.textContent = "読み取り中…";
        const labels = {queued:"順番待ち", reading:"読み取り中", type_review:"種類を確認", preview:"確認できます", read_error:"読み取り失敗", completed:"登録済み", skipped:"確認済み"};
        let failures = 0;
        function active() { return panel.isConnected && form.dataset.loading === "1"; }
        function link(label, value) {
            const url = localUrl(value);
            if (!url) return;
            const a = document.createElement("a"); a.href = url.href;
            a.className = "btn btn-outline"; a.textContent = label; actions.append(a);
        }
        function render(job) {
            const completed = Number(job.completed) || 0;
            const total = Number(job.total) || 1;
            status.textContent = completed + " / " + total + "資料処理済み";
            progress.max = total;
            if (completed > 0 || job.finished) progress.value = completed;
            else progress.removeAttribute("value");
            const items = (job.files || []).map(file => {
                const item = document.createElement("li");
                let state = labels[file.status] || "処理中";
                if (file.status === "reading" && file.phase === "classifying") state = "資料の種類を確認中";
                if (file.status === "reading" && file.phase === "ai_output") state = "読取結果を受信中";
                if (file.status === "reading" && Number(file.received_lines) > 0) state += "・明細 " + file.received_lines + "件";
                item.textContent = file.filename + "：" + state + (file.message ? "（" + file.message + "）" : "");
                return item;
            });
            files.replaceChildren(...items); actions.replaceChildren();
            if (job.preview_ready && !job.failed && !job.needs_review) {
                const preview = localUrl(job.preview_url);
                if (preview) { location.assign(preview.href); return true; }
            }
            if (job.needs_review) (job.files || []).filter(file => file.status === "type_review").forEach(file => link("種類を確認して続ける", file.kind_url));
            if (job.preview_ready) link("読取結果を確認", job.preview_url);
            if (job.failed) link("失敗した資料を確認・再実行", job.page_url || initial.page_url);
            if (job.finished) {
                release();
                status.textContent = job.failed ? "読み取れなかった資料があります。" : job.needs_review ? "資料の種類を確認してください。" : "読み取りが完了しました。";
                return true;
            }
            return false;
        }
        async function poll() {
            if (!active()) return;
            try {
                const response = await fetch(statusUrl.href, {headers:{Accept:"application/json"}, cache:"no-store"});
                if (!response.ok || !(response.headers.get("Content-Type") || "").includes("application/json")) throw new Error("status");
                const job = await response.json();
                if (!active()) return;
                failures = 0;
                if (render(job)) return;
            } catch (_) {
                if (!active()) return;
                failures++;
                status.textContent = "通信を再確認しています。資料は受付済みです。再送信せずお待ちください。";
            }
            window.setTimeout(poll, failures ? 10000 : 2000);
        }
        if (!render(initial)) window.setTimeout(poll, 1000);
    }
    function submit(form, showError) {
        if (form.dataset.loading === "1") return;
        const input = form.querySelector('input[type="file"]');
        const files = Array.from(input.files || []);
        if (files.reduce((sum, file) => sum + file.size, 0) > MAX_BATCH_BYTES) {
            showError("1回の合計容量は200MB以下にしてください。");
            return;
        }
        const payload = new FormData(form);
        // Reuse the same receipt if an accepted upload loses its HTTP response.
        if (!form.dataset.uploadKey) form.dataset.uploadKey = crypto.randomUUID();
        payload.set("upload_key", form.dataset.uploadKey);
        const button = form.querySelector('button[type="submit"]');
        const status = form.querySelector('.import-file-status');
        const originalButtonText = button.textContent;
        const clear = form.querySelector(".import-clear");
        form.dataset.loading = "1";
        button.disabled = true;
        input.disabled = true;
        if (clear) clear.disabled = true;
        button.textContent = "送信中…";
        status.textContent = "原本を送信しています。送信完了後は画面を閉じられます。";
        const xhr = new XMLHttpRequest();
        xhr.open("POST", form.action);
        xhr.setRequestHeader("Accept", "application/json");
        xhr.setRequestHeader("X-DKSS-Final-Submit", "1");
        xhr.timeout = 900000;
        xhr.upload.addEventListener("progress", event => {
            if (event.lengthComputable) status.textContent = "ファイル送信 " + Math.round(event.loaded / event.total * 100) + "％";
        });
        function fail(message) {
            delete form.dataset.loading;
            button.disabled = false;
            input.disabled = false;
            button.textContent = originalButtonText;
            if (clear) clear.disabled = false;
            form.removeAttribute("aria-busy");
            form.querySelector(".import-dropzone")?.classList.remove("is-loading");
            if (message) showError(message);
        }
        xhr.addEventListener("load", () => {
            let data;
            try { data = JSON.parse(xhr.responseText); } catch (_) {
                fail("受付を確認できませんでした。再送信すると同じ受付番号で確認します。");
                return;
            }
            if (xhr.status !== 202) {
                fail((data.errors || []).map(item => item.message).join("\n") || "受付に失敗しました。");
                return;
            }
            const start = () => watchInline(form, data, fail);
            if (window.DKSSImportSelections) window.DKSSImportSelections.accepted(form).then(start, start);
            else start();
        });
        xhr.addEventListener("abort", () => fail("送信を中断しました。受付済みの場合もあるため、元の画面で状況を確認してください。"));
        xhr.addEventListener("error", () => fail("通信が中断しました。再送信すると同じ受付番号で確認します。"));
        xhr.addEventListener("timeout", () => fail("送信が時間切れになりました。通信状態を確認してください。"));
        xhr.send(payload);
    }
    document.querySelectorAll('form[data-import-queue="1"]').forEach(form => {
        form.querySelector('input[type="file"]').addEventListener('change', () => { delete form.dataset.uploadKey; });
    });
    window.DKSSDocumentImportQueue = {submit, offer: offerTypeTransfer};
    // Recover CSV/document drops in the browser before rejecting their extension.
    function offerTypeTransfer(form, files) {
        if (!files.length || form.dataset.loading === "1") return false;
        const source = form.querySelector('input[type="file"]');
        const csv = files.length === 1 && files.every(file => /\.csv$/i.test(file.name));
        const documents = files.length <= 50 && files.every(file => /\.(pdf|png|jpe?g)$/i.test(file.name));
        const operation = source.name === "csv_file";
        if (!(operation && documents) && !(!operation && csv)) return false;
        const target = document.querySelector(operation ? '#import-maintenance form' : '#import-operation form');
        if (!target) return false;
        const targetInput = target.querySelector('input[type="file"]');
        form.querySelector('[data-kind-transfer]')?.remove();
        const box = document.createElement('div'); box.dataset.kindTransfer = '1';
        box.className = 'help-text'; box.setAttribute('role', 'status');
        const message = document.createElement('p');
        message.textContent = operation ? 'PDF・画像の資料です。資料の読み取りへ移して続けられます。' : 'CSVファイルです。運行実績へ移して続けられます。';
        const go = document.createElement('button'); go.type = 'button'; go.className = 'btn btn-outline';
        go.textContent = operation ? '資料として読み込む' : '運行実績として読み込む';
        go.addEventListener('click', () => {
            if (target.dataset.loading === '1' || targetInput.files.length) {
                message.textContent = '移動先には別のファイルが選択されています。先にそのファイルを読み込むか、移動先の「削除」で選択を解除してください。今回のファイルは保持しています。';
                return;
            }
            const transfer = new DataTransfer(); files.forEach(file => transfer.items.add(file));
            targetInput.files = transfer.files;
            targetInput.dispatchEvent(new Event('change', {bubbles:true}));
            const selected = Array.from(source.files || []);
            if (selected.length === files.length && selected.every((file, i) => file === files[i])) {
                source.value = ''; delete form.dataset.uploadKey;
                source.dispatchEvent(new Event('change', {bubbles:true}));
            }
            box.remove(); target.requestSubmit();
        });
        const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'btn btn-outline';
        cancel.textContent = 'キャンセル'; cancel.addEventListener('click', () => box.remove());
        box.append(message, go, cancel); form.append(box);
        return true;
    }
    document.querySelectorAll('.vehicle-data-import .import-form').forEach(form => {
        const input = form.querySelector('input[type="file"]');
        form.addEventListener('submit', event => {
            if (offerTypeTransfer(form, Array.from(input.files || []))) {
                event.preventDefault(); event.stopImmediatePropagation();
            }
        }, true);
        form.querySelector('.import-dropzone')?.addEventListener('drop', event => {
            if (offerTypeTransfer(form, Array.from(event.dataTransfer.files || []))) {
                event.preventDefault(); event.stopImmediatePropagation();
            }
        }, true);
    });
    document.querySelectorAll(".import-receipt-delete-form").forEach(form => {
        form.addEventListener("submit", event => {
            if (form.dataset.deleting === "1") { event.preventDefault(); return; }
            if (!window.confirm("「" + form.dataset.filename + "」の受付を削除しますか？\n未登録の資料は読み取りを取り消して削除します。登録済みの車両記録と原本は残ります。")) {
                event.preventDefault();
                return;
            }
            form.dataset.deleting = "1";
            form.querySelector('button[type="submit"]').disabled = true;
        });
    });
    document.querySelectorAll(".import-workspace").forEach(workspace => {
        const list = workspace.querySelector(".import-receipt-list");
        if (!list) return;
        const main = workspace.closest(".main-content");
        let frame = null;
        function fitReceipts() {
            frame = null;
            if (window.innerWidth < 900) { list.style.maxHeight = ""; return; }
            const bottomPadding = main ? parseFloat(getComputedStyle(main).paddingBottom) || 0 : 0;
            const room = window.innerHeight - workspace.getBoundingClientRect().bottom - bottomPadding - (window.innerWidth < 1100 ? 32 : 8);
            const desired = Math.max(104, Math.min(600, Math.floor(list.getBoundingClientRect().height + room)));
            const value = desired + "px";
            if (list.style.maxHeight !== value) list.style.maxHeight = value;
        }
        function schedule() {
            if (frame !== null) return;
            frame = window.requestAnimationFrame(fitReceipts);
        }
        window.addEventListener("resize", schedule);
        workspace.querySelectorAll("details").forEach(item => item.addEventListener("toggle", schedule));
        if (window.ResizeObserver) new ResizeObserver(schedule).observe(workspace);
        if (document.fonts) document.fonts.ready.then(schedule);
        schedule();
    });
    const root = document.getElementById("documentImportJob");
    if (!root) return;
    const labels = {queued:"順番待ち", reading:"読み取り中", preview:"確認できます", read_error:"読み取り失敗", completed:"登録済み", skipped:"確認済み"};
    let failures = 0;
    async function poll() {
        try {
            const response = await fetch(root.dataset.statusUrl, {headers:{Accept:"application/json"}, cache:"no-store"});
            if (!response.ok || !(response.headers.get("Content-Type") || "").includes("application/json")) throw new Error("status");
            const job = await response.json();
            failures = 0;
            document.getElementById("jobSummary").textContent = job.completed + " / " + job.total + "資料処理済み（成功 " + job.succeeded + "・種類の確認 " + (job.needs_review || 0) + "・失敗 " + job.failed + "）";
            const progress = document.getElementById("jobProgress");
            progress.max = job.total;
            progress.value = job.completed;
            const items = job.files.map(file => {
                const item = document.createElement("li");
                let state = labels[file.status] || "処理中";
                if (file.status === "type_review") state = "種類を確認";
                if (file.status === "reading" && file.phase === "classifying") state = "資料の種類を確認中";
                if (file.status === "reading" && file.phase === "ai_output") state = "読取結果を受信中";
                if (file.status === "reading" && Number(file.received_lines) > 0) state += "・明細 " + file.received_lines + "件";
                item.textContent = file.filename + " — " + state + (file.message ? "：" + file.message : "");
                if (file.kind_url && !["completed", "skipped", "deleted"].includes(file.status)) {
                    const url = new URL(file.kind_url, location.href);
                    if (url.origin === location.origin) {
                        const change = document.createElement("a");
                        change.href = url.href; change.className = "btn btn-outline";
                        change.textContent = file.status === "type_review" ? "種類を確認して続ける" : "資料の種類を変更";
                        item.append(" ", change);
                    }
                }
                return item;
            });
            document.getElementById("jobFiles").replaceChildren(...items);
            document.getElementById("jobConnection").textContent = "";
            document.getElementById("jobRetry").hidden = !(job.failed > 0);
            const preview = document.getElementById("jobPreview");
            preview.hidden = !job.preview_ready;
            if (job.preview_url) {
                const destination = new URL(job.preview_url, location.href);
                if (destination.origin === location.origin) {
                    preview.href = destination.href;
                    if (root.dataset.autoOpen === "1" && job.failed === 0 && !job.needs_review) { location.replace(destination.href); return; }
                }
            }
            if (job.finished) return;
        } catch (_) {
            failures++;
            document.getElementById("jobConnection").textContent = "状況を再確認しています。受付済みの資料は再送信せず、この画面を再読み込みしてください。";
        }
        window.setTimeout(poll, failures ? 10000 : 2000);
    }
    poll();
})();
