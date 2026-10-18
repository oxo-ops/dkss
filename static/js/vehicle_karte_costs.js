(() => {
    "use strict";

    const dataElement = document.getElementById("kc-chart-data");
    if (!dataElement) return;

    let data;
    try {
        data = JSON.parse(dataElement.textContent);
    } catch {
        document.querySelectorAll(".karte-costs canvas").forEach((canvas) => {
            canvas.replaceWith(document.createTextNode(
                "グラフ用データを読み込めませんでした。"
            ));
        });
        return;
    }

    const number = (value) => {
        if (value === null || value === undefined || value === "") return null;
        const result = Number(value);
        return Number.isFinite(result) ? result : null;
    };

    const format = (value) => value.toLocaleString("ja-JP", {
        maximumFractionDigits: 0
    });

    function prepare(canvas, width, height) {
        const context = canvas.getContext("2d");
        if (!context) return null;

        const ratio = window.devicePixelRatio || 1;
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
        context.clearRect(0, 0, width, height);
        return context;
    }

    function drawBars(id, items, labelKey, suffix) {
        const canvas = document.getElementById(id);
        if (!canvas || !Array.isArray(items)) return;

        const width = canvas.parentElement.clientWidth - 24;
        if (width < 140) return;

        const height = 140;
        const context = prepare(canvas, width, height);
        if (!context) return;

        canvas.hidden = false;
        canvas.style.display = "block";

        const values = items.map((item) => number(item.amount));
        const available = values.filter((value) => value !== null);

        canvas.setAttribute("aria-label", items.map((item, index) => (
            `${item[labelKey]}${suffix}：`
            + (values[index] === null ? "金額記録なし" : `${format(values[index])}円`)
        )).join("、"));

        context.font = "10px sans-serif";
        context.fillStyle = "#64748b";

        if (!available.length) {
            context.textAlign = "center";
            context.fillText("金額の記録はありません", width / 2, height / 2);
            return;
        }

        const left = 64;
        const right = width - 10;
        const top = 20;
        const bottom = height - 28;
        const maximum = Math.max(0, ...available);
        const minimum = Math.min(0, ...available);
        const span = maximum - minimum || 1;
        const rawStep = span / 4;
        const magnitude = 10 ** Math.floor(Math.log10(rawStep));
        const step = Math.ceil(rawStep / magnitude) * magnitude;
        const low = Math.floor(minimum / step) * step;
        const high = Math.max(low + step, Math.ceil(maximum / step) * step);
        const y = (value) => bottom - (value - low) / (high - low) * (bottom - top);
        const zero = y(0);

        context.textAlign = "right";
        context.textBaseline = "middle";
        for (let index = 0; index <= 4; index += 1) {
            const value = low + (high - low) * index / 4;
            const position = y(value);

            context.strokeStyle = "#e5edf8";
            context.lineWidth = 1;
            context.beginPath();
            context.moveTo(left, position);
            context.lineTo(right, position);
            context.stroke();

            context.fillStyle = "#64748b";
            context.fillText(format(value), left - 6, position);
        }

        context.textAlign = "left";
        context.textBaseline = "top";
        context.fillText("円", left, 2);

        const slot = (right - left) / Math.max(items.length, 1);
        const barWidth = Math.max(2, Math.min(42, slot * 0.58));

        items.forEach((item, index) => {
            const center = left + slot * (index + 0.5);
            const value = values[index];

            context.textAlign = "center";
            context.textBaseline = "top";
            context.fillStyle = "#64748b";
            context.fillText(`${item[labelKey]}${suffix}`, center, bottom + 9);

            if (value === null) {
                context.fillText("—", center, bottom - 14);
                return;
            }

            const position = y(value);
            context.fillStyle = "#669df0";
            context.fillRect(
                center - barWidth / 2,
                Math.min(position, zero),
                barWidth,
                Math.max(2, Math.abs(zero - position))
            );

            if (items.length <= 3) {
                context.fillStyle = "#36557c";
                context.textBaseline = value < 0 ? "top" : "bottom";
                context.fillText(
                    format(value),
                    center,
                    value < 0 ? position + 4 : position - 4
                );
            }
        });
    }

    function drawRing() {
        const canvas = document.getElementById("kc-category-chart");
        if (!canvas || !data.showRing || !Array.isArray(data.categories)) return;

        const items = data.categories.map((item) => ({
            ...item,
            value: number(item.amount)
        }));
        if (items.some((item) => item.value === null || item.value < 0)) return;

        const total = items.reduce((sum, item) => sum + item.value, 0);
        if (total <= 0) return;

        const context = prepare(canvas, 110, 110);
        if (!context) return;

        canvas.hidden = false;
        canvas.style.display = "block";

        let angle = -Math.PI / 2;
        items.forEach((item) => {
            const end = angle + item.value / total * Math.PI * 2;
            context.beginPath();
            context.arc(55, 55, 43, angle, end);
            context.strokeStyle = /^#[0-9a-f]{6}$/i.test(item.color)
                ? item.color : "#94a3b8";
            context.lineWidth = 16;
            context.stroke();
            angle = end;
        });

        context.textAlign = "center";
        context.fillStyle = "#64748b";
        context.font = "10px sans-serif";
        context.fillText("累計", 55, 45);
        context.fillStyle = "#203b60";
        context.font = "bold 12px sans-serif";
        context.fillText(format(total), 55, 61);
        context.font = "10px sans-serif";
        context.fillText("円", 55, 75);
        canvas.setAttribute("aria-label", `累計整備費 ${format(total)}円`);
    }

    function draw() {
        drawBars("kc-monthly-chart", data.monthly, "month", "月");
        drawBars("kc-yearly-chart", data.yearly, "year", "年");
        drawRing();
    }

    draw();

    const root = document.querySelector(".karte-costs");
    if ("ResizeObserver" in window && root) {
        const observer = new ResizeObserver(draw);
        observer.observe(root);
    } else {
        window.addEventListener("resize", draw);
    }
})();