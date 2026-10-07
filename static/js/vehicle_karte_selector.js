(() => {
    "use strict";

    const search = document.getElementById("karte_vehicle_search");
    const results = document.getElementById(
        "karte_vehicle_search_results"
    );
    const status = document.getElementById(
        "karte_vehicle_search_status"
    );
    const dataElement = document.getElementById(
        "karte_vehicle_search_data"
    );

    if (!search || !results || !status || !dataElement) {
        return;
    }

    const choices = JSON.parse(dataElement.textContent);
    let composing = false;

    const normalize = (value) => String(value || "")
        .normalize("NFKC")
        .toLocaleLowerCase("ja")
        .replace(/[\s\u3000\-‐‑‒–—―−]/g, "");

    const records = choices.map((choice) => ({
        choice,
        searchText: normalize([
            choice.number,
            choice.chassis_number
        ].join(" "))
    }));

    const updateResults = () => {
        results.replaceChildren();

        const terms = search.value.trim()
            .split(/[\s\u3000]+/)
            .map(normalize)
            .filter(Boolean);

        if (!terms.length) {
            results.hidden = true;
            status.hidden = true;
            status.textContent = "";
            return;
        }

        const matches = records.filter((record) =>
            terms.every((term) => record.searchText.includes(term))
        );

        status.textContent = matches.length
            ? `${matches.length}台見つかりました。車両をクリックしてください。`
            : "該当する車両がありません。";
        status.hidden = false;
        results.hidden = !matches.length;

        const fragment = document.createDocumentFragment();

        for (const { choice } of matches) {
            const link = document.createElement("a");
            const url = new URL(
                results.dataset.karteUrl,
                window.location.origin
            );
            url.searchParams.set("vehicle_record_id", choice.id);

            link.href = url.href;
            link.className = "vehicle-karte-search-result";

            const number = document.createElement("strong");
            number.textContent = choice.number || "車番未登録";
            link.append(number);
            fragment.append(link);
        }

        results.append(fragment);
    };

    search.addEventListener("compositionstart", () => {
        composing = true;
    });

    search.addEventListener("compositionend", () => {
        composing = false;
        updateResults();
    });

    search.addEventListener("input", (event) => {
        if (!composing && !event.isComposing) {
            updateResults();
        }
    });

    updateResults();
})();