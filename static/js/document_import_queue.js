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
        form.dataset.loading = "1";
        button.disabled = true;
        input.disabled = true;
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
            button.textContent = "読み込んで確認";
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
            location.assign(destination.href);
        });
        xhr.addEventListener("error", () => fail("通信が中断しました。再送信すると同じ受付番号で確認します。"));
        xhr.addEventListener("timeout", () => fail("送信が時間切れになりました。通信状態を確認してください。"));
        xhr.send(payload);
    }
    document.querySelectorAll('form[data-import-queue="1"]').forEach(form => {
        form.querySelector('input[type="file"]').addEventListener('change', () => { delete form.dataset.uploadKey; });
    });
    window.DKSSDocumentImportQueue = {submit};
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
            document.getElementById("jobSummary").textContent = job.completed + " / " + job.total + "ファイル処理済み（成功 " + job.succeeded + "・失敗 " + job.failed + "）";
            const progress = document.getElementById("jobProgress");
            progress.max = job.total;
            progress.value = job.completed;
            const items = job.files.map(file => {
                const item = document.createElement("li");
                let state = labels[file.status] || "処理中";
                if (file.status === "reading" && file.phase === "ai_output") state = "読取結果を受信中";
                if (file.status === "reading" && Number(file.received_lines) > 0) state += "・明細 " + file.received_lines + "件";
                item.textContent = file.filename + " — " + state + (file.message ? "：" + file.message : "");
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
                    if (root.dataset.autoOpen === "1" && job.failed === 0) { location.replace(destination.href); return; }
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
