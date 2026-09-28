document.addEventListener("DOMContentLoaded", function () {
    const manualSelect = document.querySelector(".js-manual-select");
    const manualLink = document.getElementById("manual_link");
    const deleteForm = document.querySelector(".js-pointout-delete-form");

    if (manualSelect && manualLink) {
        manualSelect.addEventListener("change", function () {
            if (!manualSelect.value) {
                manualLink.removeAttribute("href");
                manualLink.classList.add("is-hidden");
                return;
            }

            manualLink.href = manualSelect.value;
            manualLink.classList.remove("is-hidden");
        });
    }

    if (deleteForm) {
        deleteForm.addEventListener("submit", function (event) {
            if (!window.confirm("削除しますか？")) {
                event.preventDefault();
            }
        });
    }

    const countermeasureForm =
        document.querySelector(".pointout-countermeasure-form");

    if (countermeasureForm) {
        countermeasureForm.addEventListener(
            "submit",
            function (event) {
                const errors = [];

                const fields = [
                    {
                        id: "countermeasure",
                        message: "対策内容を入力してください。"
                    },
                    {
                        id: "countermeasure_by_search",
                        hiddenId: "countermeasure_by",
                        message: "対応者を選択してください。"
                    }
                ];

                fields.forEach(function (field) {
                    const visibleInput =
                        document.getElementById(field.id);

                    const valueInput =
                        visibleInput?.classList.contains(
                            "mention-rich-editor"
                        )
                            ? getMentionHiddenInput(visibleInput)
                            : field.hiddenId
                                ? document.getElementById(field.hiddenId)
                                : visibleInput;

                    if (
                        !valueInput ||
                        !String(valueInput.value || "").trim()
                    ) {
                        errors.push({
                            fieldId: field.id,
                            message: field.message
                        });
                    }
                });

                if (errors.length === 0) {
                    return;
                }

                event.preventDefault();

                document
                    .querySelector("#error-summary")
                    ?.remove();

                document
                    .querySelectorAll(".form-control-error")
                    .forEach(function (input) {
                        input.classList.remove(
                            "form-control-error"
                        );
                        input.removeAttribute(
                            "aria-invalid"
                        );
                    });

                document
                    .querySelectorAll(".field-error-message")
                    .forEach(function (message) {
                        message.remove();
                    });

                const summary =
                    document.createElement("div");

                summary.id = "error-summary";
                summary.className = "error-summary";
                summary.setAttribute("role", "alert");
                summary.tabIndex = -1;

                const title =
                    document.createElement("h2");

                title.textContent =
                    "入力内容を確認してください";

                const list =
                    document.createElement("ul");

                errors.forEach(function (error) {
                    const input =
                        document.getElementById(
                            error.fieldId
                        );

                    if (!input) {
                        return;
                    }

                    input.classList.add(
                        "form-control-error"
                    );

                    input.setAttribute(
                        "aria-invalid",
                        "true"
                    );

                    const fieldMessage =
                        document.createElement("div");

                    fieldMessage.id =
                        `${error.fieldId}_error`;

                    fieldMessage.className =
                        "field-error-message";

                    fieldMessage.textContent =
                        error.message;

                    input.insertAdjacentElement(
                        "afterend",
                        fieldMessage
                    );

                    input.setAttribute(
                        "aria-describedby",
                        fieldMessage.id
                    );

                    const item =
                        document.createElement("li");

                    const link =
                        document.createElement("a");

                    link.href =
                        `#${error.fieldId}`;

                    link.textContent =
                        error.message;

                    link.addEventListener(
                        "click",
                        function (clickEvent) {
                            clickEvent.preventDefault();

                            input.scrollIntoView({
                                behavior: "smooth",
                                block: "center"
                            });

                            window.setTimeout(
                                function () {
                                    input.focus({
                                        preventScroll: true
                                    });
                                },
                                300
                            );
                        }
                    );

                    item.appendChild(link);
                    list.appendChild(item);
                });

                summary.appendChild(title);
                summary.appendChild(list);

                const main =
                    document.querySelector("main");

                if (main) {
                    main.prepend(summary);
                }

                const firstError =
                    document.getElementById(
                        errors[0].fieldId
                    );

                if (firstError) {
                    firstError.scrollIntoView({
                        behavior: "smooth",
                        block: "center"
                    });

                    window.setTimeout(
                        function () {
                            firstError.focus({
                                preventScroll: true
                            });
                        },
                        300
                    );
                }
            }
        );
    }
});