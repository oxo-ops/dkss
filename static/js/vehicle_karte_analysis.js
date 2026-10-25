(() => {
    "use strict";

    const root = document.querySelector(".karte-analysis");
    const source = document.getElementById("ka-chart-data");
    if (!root || !source) return;

    let rows;
    try {
        rows = JSON.parse(source.textContent);
        if (!Array.isArray(rows)) return;
    } catch {
        return;
    }

    // Zoom to registered months; retain interior missing months as null, never zero.
    const populated = rows.map((row,index)=>row.distance !== null && row.distance !== undefined || row.cost !== null && row.cost !== undefined ? index : -1).filter(index=>index>=0);
    if(populated.length) rows=rows.slice(populated[0],populated[populated.length-1]+1);

    const number = (value) => {
        if (value === null || value === undefined || value === "") return null;
        const result = Number(value);
        return Number.isFinite(result) ? result : null;
    };

    const format = (value) => value.toLocaleString("ja-JP", {
        maximumFractionDigits: 1,
        notation: "compact"
    });

    function draw(id, field, unit, line) {
        const canvas = document.getElementById(id);
        if (!canvas || !rows.length) return;

        const panel = canvas.parentElement;
        const style = getComputedStyle(panel);
        const width = Math.floor(
            panel.clientWidth
            - parseFloat(style.paddingLeft || 0)
            - parseFloat(style.paddingRight || 0)
        );
        if (width < 160) return;

        const context = canvas.getContext("2d");
        if (!context) return;

        const height = 140;
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
        context.clearRect(0, 0, width, height);
        canvas.hidden = false;

        const note = panel.querySelector(".ka-chart-note");
        if (note) note.hidden = true;

        const values = rows.map((row) => number(row[field]));
        const known = values.filter((value) => value !== null);

        canvas.setAttribute("aria-label", rows.map((row, index) => (
            `${row.month}：${values[index] === null
                ? "記録なし"
                : values[index].toLocaleString("ja-JP") + unit}`
        )).join("、"));

        context.font = '12px "Segoe UI", "Meiryo", sans-serif';
        context.fillStyle = "#526277";

        if (!known.length) {
            context.textAlign = "center";
            context.fillText(
                "対象期間の記録はありません",
                width / 2,
                height / 2
            );
            return;
        }

        const left = 44;
        const top = 16;
        const bottom = 116;
        const plotWidth = width - left - 10;
        const low = Math.min(0, ...known);
        const maximum = Math.max(0, ...known);
        const high = unit === "件"
            ? Math.max(2, Math.ceil(maximum / 2) * 2)
            : maximum;
        const span = high - low || 1;
        const y = (value) => (
            bottom - (value - low) / span * (bottom - top)
        );
        const step = plotWidth / rows.length;
        const x = (index) => left + step * (index + 0.5);

        for (let index = 0; index <= 2; index += 1) {
            const value = low + span * index / 2;
            context.strokeStyle = "#e5ecf4";
            context.beginPath();
            context.moveTo(left, y(value));
            context.lineTo(width - 10, y(value));
            context.stroke();

            context.fillStyle = "#526277";
            context.textAlign = "right";
            context.fillText(
                format(value),
                left - 6,
                y(value) + 3
            );
        }

        context.textAlign = "left";
        context.fillText(unit, left, 10);

        if (line) {
            context.strokeStyle = "#397dea";
            context.lineWidth = 1.7;
            context.beginPath();
            let connected = false;

            values.forEach((value, index) => {
                if (value === null) {
                    connected = false;
                    return;
                }
                if (connected) {
                    context.lineTo(x(index), y(value));
                } else {
                    context.moveTo(x(index), y(value));
                }
                connected = true;
            });

            context.stroke();
            context.fillStyle = "#397dea";

            values.forEach((value, index) => {
                if (value === null) return;
                context.beginPath();
                context.arc(
                    x(index), y(value),
                    2.2, 0, Math.PI * 2
                );
                context.fill();
            });
        } else {
            const barWidth = Math.max(
                1, Math.min(18, step * 0.6)
            );
            context.fillStyle = "#8271d7";

            values.forEach((value, index) => {
                if (value === null) return;
                context.fillRect(
                    x(index) - barWidth / 2,
                    Math.min(y(0), y(value)),
                    barWidth,
                    Math.abs(y(0) - y(value))
                );
            });
        }

        const interval = Math.max(
            1, Math.ceil(rows.length / 4)
        );
        context.fillStyle = "#526277";
        context.textAlign = "center";

        rows.forEach((row, index) => {
            if (index % interval === 0) {
                context.fillText(
                    String(row.month).replace("-", "/"),
                    x(index),
                    134
                );
            }
        });
    }

    let frame = 0;
    const redraw = () => {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
            draw("ka-distance-chart", "distance", "km", true);
            draw("ka-cost-chart", "cost", "円", false);
            draw("ka-failure-chart", "failures", "件", false);
        });
    };

    if ("ResizeObserver" in window) {
        let previousWidth = -1;
        new ResizeObserver(() => {
            if (root.clientWidth === previousWidth) return;
            previousWidth = root.clientWidth;
            redraw();
        }).observe(root);
    }

    window.addEventListener("resize", redraw);
    if (document.fonts) document.fonts.ready.then(redraw);
    redraw();
})();