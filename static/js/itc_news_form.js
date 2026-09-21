document.addEventListener("DOMContentLoaded", function () {
    const targetTypeSelect = document.querySelector('select[name="target_type"]');
    const targetSearchArea = document.getElementById("targetSearchArea");
    const targetSearchInput = document.getElementById("newsTargetSearch");
    const targetValueInput = document.getElementById("newsTargetValue");
    const targetResults = document.getElementById("newsTargetResults");
    const deleteButton = document.querySelector(".js-news-delete");
    const newsForm = targetTypeSelect.closest("form");

    function hideTargetResults() {
        targetResults.classList.add("is-hidden");
    }

    function showTargetResults() {
        targetResults.classList.remove("is-hidden");
    }

    function updateTargetSearchArea() {
        const type = targetTypeSelect.value;
        const shouldHide = type === "all" || type === "admins";

        targetSearchArea.classList.toggle("is-hidden", shouldHide);

        if (shouldHide) {
            targetSearchInput.value = "";
            targetValueInput.value = "";
            targetResults.innerHTML = "";
            hideTargetResults();
        }
    }

    targetTypeSelect.addEventListener("change", function () {
        updateTargetSearchArea();
    });

    targetSearchInput.addEventListener("input", function () {
        const keyword = targetSearchInput.value.trim();
        const type = targetTypeSelect.value;

        targetValueInput.value = "";

        if (!keyword) {
            targetResults.innerHTML = "";
            targetValueInput.value = "";
            hideTargetResults();
            return;
        }

        fetch(
            "/api/news-targets?type=" +
            encodeURIComponent(type) +
            "&q=" +
            encodeURIComponent(keyword)
        )
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(
                        "HTTP " + response.status
                    );
                }

                return response.json();
            })
            .then(function (data) {
                targetResults.innerHTML = "";

                if (!data.results || data.results.length === 0) {
                    hideTargetResults();
                    return;
                }

                data.results.forEach(function (item) {
                    const button = document.createElement("button");
                    const name = document.createElement("strong");
                    const sub = document.createElement("span");

                    button.type = "button";
                    button.className = "news-target-item";

                    name.textContent = item.name;
                    sub.textContent = item.sub;

                    button.appendChild(name);
                    button.appendChild(sub);

                    button.addEventListener("click", function () {
                        targetSearchInput.value = item.name;
                        targetValueInput.value = item.id;
                        hideTargetResults();
                    });

                    targetResults.appendChild(button);
                });

                showTargetResults();
            })
            .catch(function () {
                targetResults.innerHTML = "";

                const message =
                    document.createElement("div");

                message.className = "help-text";
                message.textContent =
                    "配信対象を取得できませんでした。通信状態を確認して、もう一度検索してください。";

                targetResults.appendChild(message);
                showTargetResults();
            });
    });

    document.addEventListener("click", function (event) {
        if (!event.target.closest("#targetSearchArea")) {
            hideTargetResults();
        }
    });

    if (newsForm) {
        newsForm.addEventListener("submit", function (event) {
            if (
                event.submitter &&
                event.submitter.classList.contains(
                    "js-news-delete"
                )
            ) {
                return;
            }

            const type = targetTypeSelect.value;

            const needsTarget =
                type === "company" ||
                type === "office" ||
                type === "user";

            if (!needsTarget || targetValueInput.value) {
                return;
            }

            event.preventDefault();

            window.alert(
                "検索結果から配信対象を選択してください。"
            );

            targetSearchArea.classList.remove("is-hidden");

            targetSearchInput.scrollIntoView({
                behavior: "smooth",
                block: "center"
            });

            window.setTimeout(function () {
                targetSearchInput.focus();
            }, 300);
        });
    }

    if (deleteButton) {
        deleteButton.addEventListener("click", function (event) {
            if (!window.confirm("このニュースを削除しますか？")) {
                event.preventDefault();
            }
        });
    }

    updateTargetSearchArea();
});