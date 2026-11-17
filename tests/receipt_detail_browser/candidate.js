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
        if (form.classList) form.classList.add("ocr-queue-busy");
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
            if (form.classList) form.classList.remove("ocr-queue-busy");
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
                let checks = 0;
                const stopProgress = () => {
                    if (form.classList) form.classList.remove("ocr-queue-busy");
                    delete form.dataset.loading;
                    button.disabled = false;
                    input.disabled = false;
                    if (clear) clear.disabled = false;
                    button.textContent = originalButtonText;
                    status.textContent = "自動確認を終了しました。資料は受付済みです。受付状況から確認できます。";
                    const link = document.createElement("a");
                    link.href = destination.href;
                    link.textContent = "受付状況を開く";
                    link.className = "btn btn-outline";
                    status.append(" ", link);
                };
                async function readStatus() {
                    const controller = typeof AbortController === "function" ? new AbortController() : null;
                    let timer;
                    try {
                        return await Promise.race([
                            (async () => {
                                const options = {headers:{Accept:"application/json"},cache:"no-store"};
                                if (controller) options.signal = controller.signal;
                                const response = await window.fetch(statusUrl.href, options);
                                if (!response.ok) throw new Error("status");
                                const job = await response.json();
                                if (!job || typeof job !== "object" || Array.isArray(job)
                                        || typeof job.finished !== "boolean") throw new Error("shape");
                                return job;
                            })(),
                            new Promise((_, reject) => {
                                timer = window.setTimeout(() => {
                                    reject(new Error("timeout"));
                                    if (controller) controller.abort();
                                }, 10000);
                            })
                        ]);
                    } finally {
                        window.clearTimeout(timer);
                    }
                }
                async function checkProgress() {
                    checks++;
                    try {
                        const job = await readStatus();
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
                            if (form.classList) form.classList.remove("ocr-queue-busy");
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
                    if (failures >= 3 || checks >= 60) {
                        stopProgress();
                        return;
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
    // Resume accepted documents in their original category card, not the legacy job page.
    document.querySelectorAll(".import-receipt-read[data-receipt-kind]").forEach(link => {
        link.addEventListener("click", async event => {
            const kind = link.dataset.receiptKind;
            const card = document.getElementById("import-" + kind);
            if (!card || !link.dataset.receiptStatusUrl || typeof window.fetch !== "function") return;
            event.preventDefault();
            if (link.dataset.loading === "1") return;
            const form = card.querySelector(".import-form");
            const status = card.querySelector(".import-file-status");
            const read = form && form.querySelector(".import-read");
            if (!status) return;
            const url = new URL(link.dataset.receiptStatusUrl, location.href);
            if (url.origin !== location.origin) return;
            link.dataset.loading = "1";
            link.setAttribute("aria-disabled", "true");
            card.scrollIntoView({block:"center", behavior:"smooth"});
            if (form) form.classList.add("ocr-queue-busy");
            if (read) read.disabled = true;
            let errors = 0;
            let checks = 0;
            const finish = () => {
                delete link.dataset.loading;
                link.removeAttribute("aria-disabled");
                if (form) form.classList.remove("ocr-queue-busy");
                if (read) read.disabled = false;
            };
            const stop = message => {
                finish();
                status.textContent = message;
                const fallback = document.createElement("a");
                fallback.href = link.href;
                fallback.textContent = "受付状況を開く";
                status.append(" ", fallback);
            };
            async function readStatus() {
                const controller = typeof AbortController === "function" ? new AbortController() : null;
                let timer;
                try {
                    return await Promise.race([
                        (async () => {
                            const options = {headers:{Accept:"application/json"},cache:"no-store"};
                            if (controller) options.signal = controller.signal;
                            const response = await window.fetch(url.href, options);
                            if (!response.ok) throw new Error("status");
                            const job = await response.json();
                            if (!job || typeof job !== "object" || Array.isArray(job)
                                    || typeof job.finished !== "boolean") throw new Error("shape");
                            return job;
                        })(),
                        new Promise((_, reject) => {
                            timer = window.setTimeout(() => {
                                reject(new Error("timeout"));
                                if (controller) controller.abort();
                            }, 10000);
                        })
                    ]);
                } finally {
                    window.clearTimeout(timer);
                }
            }
            async function check() {
                checks++;
                try {
                    const job = await readStatus();
                    errors = 0;
                    const files = Array.isArray(job.files) ? job.files : [];
                    status.textContent = (job.completed || 0) + " / " + (job.total || files.length) + " 資料処理済み";
                    if (!job.finished) {
                        status.textContent += "（読み取り中）";
                    } else {
                        finish();
                        status.textContent = job.failed || job.needs_review ? "資料の確認が必要です。" : "読み取りが完了しています。";
                        const destination = job.preview_ready && job.preview_url && !job.failed && !job.needs_review
                            ? job.preview_url : link.href;
                        const next = new URL(destination, location.href);
                        if (next.origin !== location.origin) return;
                        const action = document.createElement("a");
                        action.href = next.href;
                        action.className = "btn btn-outline";
                        action.textContent = "読み取り結果を確認する";
                        status.append(" ", action);
                        return;
                    }
                } catch (_) {
                    errors++;
                    status.textContent = "受付状況を再確認しています。";
                    if (errors >= 3) {
                        stop("受付状況を取得できませんでした。もう一度確認できます。");
                        return;
                    }
                }
                if (checks >= 60) {
                    stop("自動確認を終了しました。処理は続行中の場合があります。もう一度確認できます。");
                    return;
                }
                window.setTimeout(check, errors ? 10000 : 2000);
            }
            check();
        });
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
    let checking = false;
    let automaticOpenAllowed = true;
    const originalStatusUrl = root.dataset.statusUrl;
    const retryButtonStates = new Map();
    const reconnect = document.createElement('button');
    reconnect.type = 'button';
    reconnect.textContent = 'この受付の状況を再確認';
    reconnect.hidden = true;
    document.getElementById('jobConnection').after(reconnect);
    reconnect.addEventListener('click', () => { if (!checking) poll(); });
    async function readReceiptStatus() {
        const statusUrl = new URL(originalStatusUrl, location.href);
        const match = statusUrl.pathname.match(/^\/vehicle\/data-import\/jobs\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/status$/);
        if (statusUrl.origin !== location.origin || statusUrl.username || statusUrl.password
            || statusUrl.search || statusUrl.hash || !match
            || ![statusUrl.pathname, statusUrl.href].includes(originalStatusUrl)) throw new Error('status origin or canonical receipt');
        const controller = new AbortController();
        let timer;
        const operation = (async () => {
            const response = await fetch(statusUrl.href, {
                method: 'GET', headers:{Accept:'application/json'}, cache:'no-store', signal:controller.signal
            });
            if (response.redirected || !response.ok || !(response.headers.get('Content-Type') || '').includes('application/json')) throw new Error('status');
            const job = await response.json();
            if (!job || !Array.isArray(job.files)
                || !['completed','total','succeeded','failed'].every(key => Number.isInteger(job[key]) && job[key] >= 0)
                || ['completed','succeeded','failed'].some(key => job[key] > job.total)) throw new Error('status body');
            if (job.batch_id !== match[1] || job.files.length !== job.total
                || !job.files.every(file => file && ['queued','reading','type_review','preview','read_error','completed','skipped'].includes(file.status))) throw new Error('receipt mismatch');
            const count = states => job.files.filter(file => states.includes(file.status)).length;
            const active = count(['queued', 'reading']);
            if (job.succeeded !== count(['preview', 'completed', 'skipped'])
                || job.failed !== count(['read_error']) || job.needs_review !== count(['type_review'])
                || job.completed !== job.total - active || job.finished !== (active === 0)
                || job.preview_ready !== (active === 0 && count(['preview']) > 0)) throw new Error('inconsistent receipt counts');
            return job;
        })();
        try {
            return await Promise.race([operation, new Promise((_, reject) => {
                timer = window.setTimeout(() => { controller.abort(); reject(new Error('status timeout')); }, 15000);
            })]);
        } finally { window.clearTimeout(timer); }
    }
    async function poll() {
        if (checking) return;
        checking = true;
        reconnect.disabled = true;
        try {
            const job = await readReceiptStatus();
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
            reconnect.hidden = true;
            retryButtonStates.forEach((disabled, button) => { button.disabled = disabled; });
            retryButtonStates.clear();
            document.getElementById("jobRetry").hidden = !(job.failed > 0);
            const preview = document.getElementById("jobPreview");
            preview.hidden = true;
            if (job.preview_ready && job.preview_url) {
                const destination = new URL(job.preview_url, location.href);
                const expectedPreviewPath = '/vehicle/data-import/' + job.batch_id + '/preview';
                if (destination.origin === location.origin && !destination.username && !destination.password
                    && !destination.search && !destination.hash && destination.pathname === expectedPreviewPath
                    && [destination.pathname, destination.href].includes(job.preview_url)) {
                    preview.href = destination.href;
                    preview.hidden = false;
                    if (automaticOpenAllowed && root.dataset.autoOpen === "1" && job.failed === 0 && !job.needs_review) { location.replace(destination.href); return; }
                }
            }
            if (job.finished) return;
        } catch (_) {
            failures++;
            automaticOpenAllowed = false;
            document.getElementById("jobConnection").textContent = "受付の状況を確認できていません。処理が続いている可能性があります。資料を再送信せず「この受付の状況を再確認」を押してください。";
            document.getElementById("jobRetry").hidden = true;
            document.getElementById("jobRetry").querySelectorAll('button[type="submit"]').forEach(button => { if (!retryButtonStates.has(button)) retryButtonStates.set(button, button.disabled); button.disabled = true; });
            document.getElementById("jobPreview").hidden = true;
            reconnect.hidden = false;
            return; // Stop automatic polling; manual retry is GET for the original receipt only.
        } finally {
            checking = false;
            reconnect.disabled = false;
        }
        window.setTimeout(poll, 2000);
    }
    poll();
})();
