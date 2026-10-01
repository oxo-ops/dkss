document.addEventListener("DOMContentLoaded", function () {
    const approvalUserSearchInputs =
        document.querySelectorAll(
            ".approval-user-search"
        );

    approvalUserSearchInputs.forEach(
        function (searchInput) {
            const approvalIndex =
                searchInput.dataset.approvalIndex;

            fetch("/api/approval-candidates")
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error(
                            "HTTP " + response.status
                        );
                    }

                    return response.json();
                })
                .then(function (data) {
                    searchInput.dispatchEvent(
                        new CustomEvent(
                            "approval-candidates-loaded",
                            {
                                detail: {
                                    approvalIndex:
                                        approvalIndex,
                                    users:
                                        data.users || []
                                }
                            }
                        )
                    );
                })
                .catch(function () {
                    showCommonError(
                        "承認者候補を取得できませんでした。"
                    );
                });
        }
    );

    function addApprovalUser(
        approvalIndex,
        user
    ) {
        const selectedArea =
            document.querySelector(
                '.selected-approval-users[data-approval-index="' +
                approvalIndex +
                '"]'
            );

        if (!selectedArea || !user.username) {
            return;
        }

        if (
            selectedArea.querySelector(
                '[data-username="' +
                CSS.escape(user.username) +
                '"]'
            )
        ) {
            return;
        }

        const tag =
            document.createElement("span");

        tag.className = "selected-vehicle-tag";
        tag.dataset.username = user.username;

        const text =
            document.createTextNode(
                user.name || user.username
            );

        const remove =
            document.createElement("button");

        remove.type = "button";
        remove.className = "tag-remove-btn";
        remove.textContent = "×";

        const hidden =
            document.createElement("input");

        hidden.type = "hidden";
        hidden.name =
            "approval_notify_users_" +
            approvalIndex;
        hidden.value = user.username;

        remove.addEventListener(
            "click",
            function () {
                tag.remove();

                const heading =
                    document.querySelector(
                        '.selected-approval-users-heading[data-approval-index="' +
                        approvalIndex +
                        '"]'
                    );

                if (heading) {
                    heading.textContent =
                        "選択済み（" +
                        selectedArea.children.length +
                        "人）";
                }
            }
        );

        tag.appendChild(text);
        tag.appendChild(remove);
        tag.appendChild(hidden);

        selectedArea.appendChild(tag);

        const heading =
            document.querySelector(
                '.selected-approval-users-heading[data-approval-index="' +
                approvalIndex +
                '"]'
            );

        if (heading) {
            heading.textContent =
                "選択済み（" +
                selectedArea.children.length +
                "人）";
        }
    }

    approvalUserSearchInputs.forEach(
        function (searchInput) {
            searchInput.addEventListener(
                "approval-candidates-loaded",
                function (event) {
                    const approvalIndex =
                        searchInput.dataset.approvalIndex;

                    const candidateArea =
                        document.querySelector(
                            '.approval-candidate-users[data-approval-index="' +
                            approvalIndex +
                            '"]'
                        );

                    if (!candidateArea) {
                        return;
                    }

                    candidateArea.replaceChildren();

                    const users =
                        event.detail.users || [];

                    users.forEach(function (user) {
                        const button =
                            document.createElement(
                                "button"
                            );

                        button.type = "button";
                        button.className =
                            "vehicle-select-item";
                        button.dataset.username =
                            user.username;

                        const name =
                            document.createElement(
                                "strong"
                            );

                        name.textContent =
                            user.name || user.username;

                        const addMark =
                            document.createElement(
                                "span"
                            );

                        addMark.className =
                            "approval-candidate-add";
                        addMark.textContent = "＋";

                        button.appendChild(name);
                        button.appendChild(addMark);

                        button.addEventListener(
                            "click",
                            function () {
                                addApprovalUser(
                                    approvalIndex,
                                    user
                                );

                                button.remove();
                            }
                        );

                        candidateArea.appendChild(
                            button
                        );
                    });
                }
            );
        }
    );

    const checklistForm =
        document.querySelector("form");

    if (checklistForm) {
        checklistForm.addEventListener(
            "submit",
            function (event) {
                const approvalCards =
                    checklistForm.querySelectorAll(
                        ".vehicle-approval-card"
                    );

                for (const approvalCard of approvalCards) {
                    const selectedApprovers =
                        approvalCard.querySelectorAll(
                            'input[name^="approval_notify_users_"]'
                        );

                    if (selectedApprovers.length === 0) {
                        event.preventDefault();

                        showCommonError(
                            "承認者を1人以上選択してください。",
                            "approval_user_search_"
                            + approvalCard.dataset.approvalIndex
                        );

                        return;
                    }
                }
            }
        );
    }

    const vehicleSearch =
        document.getElementById("vehicle_search");

    const vehicleSearchResults =
        document.getElementById("vehicle_search_results");

    const vehicleId =
        document.getElementById("vehicle_record_id");

    const selectedVehicleDisplay =
        document.getElementById("selected_vehicle_display");

    if (
        !vehicleSearch ||
        !vehicleSearchResults ||
        !vehicleId ||
        !selectedVehicleDisplay
    ) {
        return;
    }

    let vehicleSearchTimer = null;

    function showMessage(message) {
        vehicleSearchResults.innerHTML = "";

        const paragraph =
            document.createElement("p");

        paragraph.className = "help-text";
        paragraph.textContent = message;

        vehicleSearchResults.appendChild(paragraph);
    }

    vehicleSearch.addEventListener(
        "keydown",
        function (event) {
            if (event.key === "Enter") {
                event.preventDefault();
            }
        }
    );

    vehicleSearch.addEventListener("input", function () {
        clearTimeout(vehicleSearchTimer);

        vehicleId.value = "";
        selectedVehicleDisplay.textContent =
            "未選択";

        vehicleSearchResults.classList.remove(
            "is-selected"
        );

        const keyword =
            vehicleSearch.value.trim();

        if (!keyword) {
            showMessage("車両を検索してください。");
            return;
        }

        vehicleSearchTimer = setTimeout(function () {
            fetch(
                "/api/vehicles?q=" +
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
                    vehicleSearchResults.innerHTML = "";

                    if (!data.results || data.results.length === 0) {
                        showMessage("該当する車両がありません。");
                        return;
                    }

                    data.results.forEach(function (vehicle) {
                        const row =
                            document.createElement("div");

                        const button =
                            document.createElement("button");

                        const label =
                            document.createElement("span");

                        const labelParts = [
                            vehicle.number || "ナンバー未登録"
                        ];

                        row.className =
                            "vehicle-option";

                        button.type =
                            "button";

                        button.className =
                            "btn-small";

                        button.textContent =
                            "選択";

                        label.textContent =
                            labelParts.join(" / ");

                        function selectVehicle() {
                            vehicleId.value =
                                vehicle.vehicle_record_id;

                            const selectedLabel =
                                labelParts.join(" / ");

                            selectedVehicleDisplay.textContent =
                                selectedLabel;

                            vehicleSearch.value =
                                selectedLabel;

                            vehicleSearchResults.innerHTML = "";

                            showMessage(
                                "対象車両を選択しました。"
                            );

                            vehicleSearchResults.classList.add(
                                "is-selected"
                            );

                            vehicleSearch.dispatchEvent(
                                new Event("change", {
                                    bubbles: true
                                })
                            );
                        }

                        button.addEventListener(
                            "click",
                            function (event) {
                                event.stopPropagation();
                                selectVehicle();
                            }
                        );

                        row.addEventListener(
                            "click",
                            selectVehicle
                        );

                        row.appendChild(button);
                        row.appendChild(label);

                        vehicleSearchResults.appendChild(row);
                    });
                })
                .catch(function () {
                    showCommonError(
                        "車両を取得できませんでした。通信状態を確認して、もう一度検索してください。"
                    );

                    showMessage(
                        "車両を取得できませんでした。通信状態を確認して、もう一度検索してください。"
                    );
                });
        }, 300);
    });

    const form = vehicleSearch.closest("form");

    const submitButton = form
        ? form.querySelector('button[type="submit"]')
        : null;

    let validationMessageShown = false;

    if (submitButton) {
        submitButton.addEventListener("click", function () {
            validationMessageShown = false;
        });
    }

    if (form) {
        form.addEventListener(
            "invalid",
            function (event) {
                event.preventDefault();

                if (validationMessageShown) {
                    return;
                }

                validationMessageShown = true;

                const field = event.target;
                let message = "必須項目を入力してください。";

                if (
                    field.name &&
                    field.name.startsWith("answer_")
                ) {
                    message = "評価を選択してください。";
                }

                showCommonError(
                    message,
                    field.id || field.name
                );

                const target =
                    field.closest("tr") ||
                    field.closest(".form-group") ||
                    field;

                target.scrollIntoView({
                    behavior: "smooth",
                    block: "center"
                });

                window.setTimeout(function () {
                    field.focus();
                }, 300);
            },
            true
        );

        form.addEventListener("submit", function (event) {
            if (vehicleId.value) {
                return;
            }

            event.preventDefault();

            showCommonError(
                "候補から対象車両を選択してください。",
                vehicleSearch.id || vehicleSearch.name
            );

            vehicleSearch.scrollIntoView({
                behavior: "smooth",
                block: "center"
            });

            window.setTimeout(function () {
                vehicleSearch.focus();
            }, 300);
        });
    }
});