(function () {
    "use strict";
    const MAX_BATCH_BYTES = 200 * 1024 * 1024;
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
        form.classList.add("ocr-queue-busy");
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
            form.classList.remove("ocr-queue-busy");
            delete form.dataset.loading;
            button.disabled = false;
            input.disabled = false;
            button.textContent = originalButtonText;
            if (clear) clear.disabled = false;
            showError(message);
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
            const destination = new URL(data.page_url, location.href);
            if (destination.origin !== location.origin) { fail("確認先が不正です。"); return; }
            destination.searchParams.set("open", "1");
            const move = () => {
                // Keep the durable queue, but show its progress in the upload card.
                // Older API fixtures without status_url retain their existing behavior.
                if (!data.status_url || typeof window.fetch !== "function") {
                    location.assign(destination.href);
                    return;
                }
                const statusUrl = new URL(data.status_url, location.href);
                if (statusUrl.origin !== location.origin) { fail("確認先が不正です。"); return; }
                button.textContent = "読み取り中…";
                status.textContent = "資料を受け付けました。読み取りを開始します。";
                let failures = 0;
                async function checkProgress() {
                    try {
                        const response = await window.fetch(statusUrl.href, {headers:{Accept:"application/json"},cache:"no-store"});
                        if (!response.ok) throw new Error("status");
                        const job = await response.json();
                        failures = 0;
                        const files = Array.isArray(job.files) ? job.files : [];
                        const current = files.find(file => file.status === "reading");
                        const summary = current ? " / " + current.filename + "：" +
                            (current.phase === "classifying" ? "資料の種類を確認中" :
                             current.phase === "ai_output" ? "読取結果を受信中" : "読み取り中") : "";
                        status.textContent = (job.completed || 0) + " / " + (job.total || files.length) +
                            " 資料処理済み" + summary;
                        if (job.finished) {
                            if (job.preview_ready && job.preview_url && !job.failed && !job.needs_review) {
                                const preview = new URL(job.preview_url, location.href);
                                if (preview.origin === location.origin) { location.assign(preview.href); return; }
                            }
                            // Errors and document-type reviews require the existing recovery UI.
                            if (job.failed || job.needs_review) {
                                status.textContent = "資料の確認が必要です。受付済みの資料から確認できます。";
                                const link = document.createElement("a");
                                link.href = destination.href;
                                link.textContent = "資料の確認へ進む";
                                link.className = "btn btn-outline";
                                status.append(" ", link);
                            } else {
                                status.textContent = "読み取りが完了しました。受付済みの資料から確認できます。";
                            }
                            form.classList.remove("ocr-queue-busy");
                            delete form.dataset.loading;
                            button.disabled = false;
                            input.disabled = false;
                            if (clear) clear.disabled = false;
                            button.textContent = originalButtonText;
                            return;
                        }
                    } catch (_) {
                        failures++;
                        status.textContent = "読取状況を再確認しています。資料は受付済みです。";
                    }
                    window.setTimeout(checkProgress, failures ? 10000 : 2000);
                }
                checkProgress();
            };
            if (window.DKSSImportSelections) window.DKSSImportSelections.accepted(form).then(move);
            else move();
        });
        xhr.addEventListener("abort", () => fail("送信を中断しました。受付済みの場合もあるため、元の画面で状況を確認してください。"));
        xhr.addEventListener("error", () => fail("通信が中断しました。再送信すると同じ受付番号で確認します。"));
        xhr.addEventListener("timeout", () => fail("送信が時間切れになりました。通信状態を確認してください。"));
        xhr.send(payload);
    }
    document.querySelectorAll('form[data-import-queue="1"]').forEach(form => {
        form.querySelector('input[type="file"]').addEventListener('change', () => { delete form.dataset.uploadKey; });
        // Lightweight test fixtures expose file events but not form events.
        // Real browser forms always provide addEventListener.
        if (typeof form.addEventListener !== 'function') return;
        form.addEventListener('submit', event => {
            if (event.defaultPrevented) return;
            const input = form.querySelector('input[type="file"]');
            // Type-transfer capture listener runs first and may cancel this submit.
            if (offerTypeTransfer(form, Array.from(input.files || []))) {
                event.preventDefault();
                return;
            }
            event.preventDefault();
            const error = form.querySelector('.import-error');
            const showError = message => {
                if (error) { error.textContent = message; error.hidden = false; }
            };
            if (error) { error.textContent = ''; error.hidden = true; }
            if (!input.files.length) { showError('資料を選択してください。'); return; }
            submit(form, showError);
        });
    });
    function offerDocumentTransfer(form, suggestion, showError) {
        const labels = {maintenance:"請求書・整備資料", inspection:"点検記録", driving_report:"安全運転日報"};
        const kind = suggestion.document_type;
        if (!Object.hasOwn(labels, kind)) return false;
        const source = form.querySelector('input[type="file"]');
        const selected = Array.from(source.files || []);
        const index = Number(suggestion.file_index);
        if (!Number.isInteger(index) || index < 0 || index >= selected.length || selected[index].name !== suggestion.filename) return false;
        const target = document.querySelector('#import-' + kind + ' form');
        if (!target || target === form) return false;
        const input = target.querySelector('input[type="file"]');
        if (target.dataset.loading === '1' || input.files.length) {
            showError('「' + labels[kind] + '」に別の資料があります。先に読み込むか選択を解除してください。今回のファイルは保持しています。');
            return true;
        }
        if (!window.confirm('「' + selected[index].name + '」は「' + labels[kind] + '」の資料と思われます。そちらへ移して読み込みますか？')) return true;
        const transfer = new DataTransfer(); transfer.items.add(selected[index]);
        const remaining = new DataTransfer(); selected.forEach((file, i) => { if (i !== index) remaining.items.add(file); });
        input.files = transfer.files;
        input.dispatchEvent(new Event('change', {bubbles:true}));
        source.files = remaining.files;
        delete form.dataset.uploadKey;
        source.dispatchEvent(new Event('change', {bubbles:true}));
        target.scrollIntoView({block:'center', behavior:'smooth'});
        target.requestSubmit();
        return true;
    }
    window.DKSSDocumentImportQueue = {submit, offer: offerTypeTransfer, offerDocument: offerDocumentTransfer};
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
