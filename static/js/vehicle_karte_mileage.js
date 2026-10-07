(() => {
    "use strict";

    const canvas = document.getElementById("vehicle_karte_mileage_chart");
    const dataElement = document.getElementById("vehicle_karte_mileage_data");

    if (!canvas || !dataElement) {
        return;
    }

    let points;

    try {
        points = JSON.parse(dataElement.textContent).map((point) => ({
            date: point.date,
            time: Date.parse(`${point.date}T00:00:00Z`),
            mileage: Number(point.mileage)
        })).filter((point) => (
            Number.isFinite(point.time)
            && Number.isFinite(point.mileage)
        )).sort((a, b) => a.time - b.time);
    } catch (error) {
        canvas.replaceWith(document.createTextNode(
            "走行距離のグラフを表示できませんでした。"
        ));
        return;
    }

    if (!points.length) {
        return;
    }

    const context = canvas.getContext("2d");

    if (!context) {
        return;
    }

    const latest = points[points.length - 1];
    const formatMileage = (value) => value.toLocaleString("ja-JP", {
        maximumFractionDigits: 2
    });

    canvas.style.display = "block";
    canvas.style.width = "100%";
    canvas.style.height = "220px";
    canvas.setAttribute(
        "aria-label",
        `累積走行距離の推移。${latest.date}時点で`
        + `${formatMileage(latest.mileage)}キロメートル。`
    );

    function draw() {
        const width = canvas.parentElement.clientWidth;
        const height = 220;

        if (width < 120) {
            return;
        }

        const ratio = window.devicePixelRatio || 1;
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
        context.clearRect(0, 0, width, height);

        const left = width < 400 ? 58 : 72;
        const right = width - 20;
        const top = 30;
        const bottom = height - 32;
        const maximum = Math.max(...points.map((point) => point.mileage), 1);
        const magnitude = 10 ** Math.floor(Math.log10(maximum));
        const step = Math.ceil(maximum / 5 / magnitude * 10) * magnitude / 10;
        const ceiling = step * 5;
        const firstTime = points[0].time;
        const lastTime = latest.time;
        const span = lastTime - firstTime;

        const x = (point) => span > 0
            ? left + (point.time - firstTime) / span * (right - left)
            : (left + right) / 2;
        const y = (point) => bottom
            - point.mileage / ceiling * (bottom - top);

        context.font = "11px sans-serif";
        context.lineWidth = 1;
        context.textAlign = "right";
        context.textBaseline = "middle";

        for (let index = 0; index <= 5; index += 1) {
            const value = step * index;
            const position = bottom - index / 5 * (bottom - top);

            context.strokeStyle = "#e4edf6";
            context.beginPath();
            context.moveTo(left, position);
            context.lineTo(right, position);
            context.stroke();

            context.fillStyle = "#64748b";
            context.fillText(formatMileage(value), left - 8, position);
        }

        context.textAlign = "left";
        context.fillText("km", left, 12);

        const labelCount = span > 0 ? (width < 400 ? 3 : 5) : 1;

        for (let index = 0; index < labelCount; index += 1) {
            const fraction = labelCount > 1 ? index / (labelCount - 1) : 0.5;
            const position = left + fraction * (right - left);
            const time = span > 0 ? firstTime + fraction * span : firstTime;
            const date = new Date(time).toISOString().slice(0, 10);

            context.textAlign = index === 0 ? "left"
                : index === labelCount - 1 ? "right" : "center";
            context.fillStyle = "#64748b";
            context.fillText(date.replaceAll("-", "/"), position, bottom + 18);
        }

        const gradient = context.createLinearGradient(0, top, 0, bottom);
        gradient.addColorStop(0, "rgba(37, 99, 235, 0.18)");
        gradient.addColorStop(1, "rgba(37, 99, 235, 0.02)");

        context.beginPath();
        context.moveTo(x(points[0]), bottom);
        points.forEach((point) => context.lineTo(x(point), y(point)));
        context.lineTo(x(latest), bottom);
        context.closePath();
        context.fillStyle = gradient;
        context.fill();

        context.beginPath();
        points.forEach((point, index) => {
            if (index === 0) {
                context.moveTo(x(point), y(point));
            } else {
                context.lineTo(x(point), y(point));
            }
        });
        context.strokeStyle = "#2563eb";
        context.lineWidth = 2;
        context.stroke();

        const markers = points.length <= 30 ? points : [latest];

        markers.forEach((point) => {
            context.beginPath();
            context.arc(x(point), y(point), 3, 0, Math.PI * 2);
            context.fillStyle = "#2563eb";
            context.fill();
        });

        context.textAlign = "right";
        context.textBaseline = "top";
        context.fillStyle = "#1d4ed8";
        context.font = "12px sans-serif";
        context.fillText(`${formatMileage(latest.mileage)} km`, right, 4);
    }

    draw();

    if ("ResizeObserver" in window) {
        new ResizeObserver(draw).observe(canvas.parentElement);
    } else {
        window.addEventListener("resize", draw);
    }
})();