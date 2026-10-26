"""Http responsibilities; routes are registered by the application factory."""
from . import common as _dkss_common, runtime as _dkss_runtime


def file_too_large(error):
    from .import_flow import context, form_error_response
    flow = context()
    if flow:
        if _dkss_common.request.endpoint == 'extract_vehicle_certificate_route':
            message = '車検証は1ファイル20MB以下にしてください。'
        elif flow['kind'] == 'document':
            message = '資料は1ファイル20MB以下・最大50ファイル・合計200MB以下に分けて選択してください。'
        else:
            message = 'ファイル容量が上限を超えています。ファイルを分けて選択し直してください。'
        return form_error_response([(message, '')], 413)
    if (
        _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1"
        or _dkss_common.request.headers.get("X-DKSS-Final-Submit") == "1"
    ):
        return return_form_errors(
            [
                (
                    "1回に送信できるファイルの合計は1GB以下です。",
                    ""
                )
            ],
            status_code=413
        )

    return return_form_errors(
        [
            (
                "1回に送信できるファイルの合計は1GB以下です。",
                ""
            )
        ],
        status_code=413
    )



def handle_csrf_error(error):
    if not _dkss_common.session.get("username"):
        return _dkss_common.redirect("/login")

    message = (
        "送信内容を確認できませんでした。"
        "画面を再読み込みして、もう一度お試しください。"
    )

    if (
        _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1"
        or _dkss_common.request.headers.get("X-DKSS-Final-Submit") == "1"
    ):
        return return_form_errors(
            [
                (
                    message,
                    ""
                )
            ],
            status_code=400
        )

    return return_form_errors(
        [
            (
                message,
                ""
            )
        ],
        status_code=400
    )



def return_form_errors(errors, status_code=400):
    from .import_flow import form_error_response
    recovery = form_error_response(errors, status_code)
    if recovery is not None:
        return recovery
    if (
        _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1"
        or _dkss_common.request.headers.get("X-DKSS-Final-Submit") == "1"
    ):
        normalized_errors = []

        for error in errors:
            if (
                isinstance(error, (tuple, list))
                and len(error) == 2
            ):
                message, error_field = error
            else:
                message = error
                error_field = get_form_error_field(message)

            normalized_errors.append({
                "message": str(message) if isinstance(message, str) else "入力内容を確認してください。",
                "field": error_field or ""
            })

        response = _dkss_common.jsonify({
            "errors": normalized_errors
        })
        response.status_code = status_code
        response.headers[
            "X-DKSS-Form-Errors"
        ] = "1"
        response.headers[
            "X-DKSS-Form-Error-Count"
        ] = str(len(normalized_errors))

        return response

    for error in errors:
        if (
            isinstance(error, (tuple, list))
            and len(error) == 2
        ):
            message, error_field = error
        else:
            message = error
            error_field = get_form_error_field(message)

        _dkss_common.flash(
            message if isinstance(message, str) else "入力内容を確認してください。",
            f"error:{error_field or ''}"
        )

    response = _dkss_runtime.app.make_response(
        ("", status_code)
    )
    response.headers[
        "X-DKSS-Form-Errors"
    ] = "1"

    return response



def checklist_form_data_to_dict(
    form_data,
    base_checklist=None
):
    if not form_data:
        return base_checklist

    checklist = dict(base_checklist or {})

    def first_value(key, default=""):
        values = form_data.get(key, [])

        if isinstance(values, list):
            return values[0] if values else default

        return values

    def list_values(key):
        values = form_data.get(key, [])

        if isinstance(values, list):
            return values

        return [values] if values else []

    item_types = list_values("item_type")
    item_categories = list_values("item_category")
    item_contents = list_values("item_content")
    input_types = list_values("input_type")
    choices_list = list_values("choices")
    criteria_list = list_values("criteria")
    approval_labels = list_values("approval_label")
    original_item_indexes = list_values(
        "original_item_index"
    )

    answer_required = {
        str(value)
        for value in list_values("answer_required")
    }
    shaded = {
        str(value)
        for value in list_values("shaded")
    }
    approval_allow_general = {
        str(value)
        for value in list_values(
            "approval_allow_general"
        )
    }

    old_items = (
        base_checklist.get("items", [])
        if base_checklist
        else []
    )

    items = []

    for i, item_type in enumerate(item_types):
        criteria_files = []

        if i < len(original_item_indexes):
            original_index = str(
                original_item_indexes[i] or ""
            ).strip()

            if original_index.isdigit():
                old_index = int(original_index)

                if 0 <= old_index < len(old_items):
                    criteria_files = list(
                        old_items[old_index].get(
                            "criteria_files",
                            []
                        )
                    )

        choices_text = (
            choices_list[i]
            if i < len(choices_list)
            else ""
        )

        items.append({
            "item_type": item_type,
            "category": (
                item_categories[i]
                if i < len(item_categories)
                else ""
            ),
            "content": (
                item_contents[i]
                if i < len(item_contents)
                else ""
            ),
            "input_type": (
                input_types[i]
                if i < len(input_types)
                else "select"
            ),
            "choices": [
                choice.strip()
                for choice in str(
                    choices_text or ""
                ).split(",")
                if choice.strip()
            ],
            "criteria": (
                criteria_list[i]
                if i < len(criteria_list)
                else ""
            ),
            "criteria_files": criteria_files,
            "answer_required": (
                str(i) in answer_required
            ),
            "shaded": str(i) in shaded,
            "approval_label": (
                approval_labels[i]
                if i < len(approval_labels)
                else ""
            ),
            "approval_allow_general": (
                str(i) in approval_allow_general
            ),
            "score_enabled": (
                first_value("score_enabled") == "1"
            ),
        })

    checklist.update({
        "name": first_value("name"),
        "target": first_value(
            "target",
            "安全管理"
        ),
        "frequency_value": first_value(
            "frequency_value"
        ),
        "frequency_unit": first_value(
            "frequency_unit"
        ),
        "display_type": first_value(
            "display_type"
        ),
        "print_portrait": (
            first_value("print_portrait") == "1"
        ),
        "print_half_month": (
            first_value("print_half_month") == "1"
        ),
        "reminder_enabled": (
            first_value("reminder_enabled") == "1"
        ),
        "reminder_time": first_value(
            "reminder_time",
            "08:00"
        ),
        "score_enabled": (
            first_value("score_enabled") == "1"
        ),
        "items": items,
    })

    return checklist



def get_form_error_field(message):
    field_map = {
        "発生日を入力してください。": "event_date",
        "発生日が不正です。": "event_date",
        "分類が不正です。": "category",
        "内容区分が不正です。": "content_type",
        "対象ユーザーを選択してください。": "target_user_search",
        "対象ユーザーが不正です。": "target_user_search",
        "対象ユーザー情報が不正です。": "target_user_search",
        "納入先を選択してください。": "delivery_place",
        "納入先が不正です。": "delivery_place",
        "内容は5000文字以内で入力してください。": "content_editor",
        "対策内容を入力してください。": "countermeasure",
        "対策内容は5000文字以内で入力してください。": "countermeasure",
        "対応者を選択してください。": "countermeasure_by_search",
        "対応者が不正です。": "countermeasure_by_search",
        "対応者情報が不正です。": "countermeasure_by_search",
        "対応期限が不正です。": "countermeasure_due_date",
        "差し戻し理由を入力してください。": "reject_reason",
        "差し戻し理由は5000文字以内で入力してください。": "reject_reason",
        "車台番号を入力してください。": "chassis_number",
        "同じ車台番号の車両が既に登録されています。": "chassis_number",
        "車両が不正です。": "vehicle_record_id",
        "ログインIDを入力してください。": "employee_id",
        "ログインIDは50文字以内で入力してください。": "employee_id",
        "このログインIDはすでに使用されています。": "employee_id",
        "ログインIDは作成後に変更できません。": "employee_id",
        "姓を入力してください。": "last_name",
        "姓は100文字以内で入力してください。": "last_name",
        "名は100文字以内で入力してください。": "first_name",
        "メールアドレスの形式が不正です。": "email_address",
        "パスワードを入力してください。": "password",
        "パスワードは8文字以上にしてください。": "password",
        "パスワードは128文字以内にしてください。": "password",
        "パスワードは英大文字・英小文字・数字・記号のうち3種類以上を使用してください。": "password",
        "ユーザー種別が不正です。": "role",
        "営業所が不正です。": "office",
        "無事故開始日が不正です。": "safe_start_date",
        "選択車両数が多すぎます。": "selected_vehicles",
        "免許種別が不正です。": "license_area",
        "免許有効期限が不正です。": "license_area",
        "初年度登録日が不正です。": "first_registration_date",
        "車検満了日が不正です。": "inspection_expiry",
        "車種が不正です。": "type",
        "車番・地域名は50文字以内で入力してください。": "plate_area",
        "車番・分類は50文字以内で入力してください。": "plate_class",
        "車番・ひらがなは10文字以内で入力してください。": "plate_kana",
        "車番は50文字以内で入力してください。": "plate_number",
        "車台番号は100文字以内で入力してください。": "chassis_number",
        "車体型式は100文字以内で入力してください。": "model_code",
        "車両メーカーは100文字以内で入力してください。": "manufacturer",
        "車両形状は100文字以内で入力してください。": "body_type",
        "車両総重量は整数で入力してください。": "gross_vehicle_weight",
        "車両総重量は0以上で入力してください。": "gross_vehicle_weight",
        "車両総重量の値が大きすぎます。": "gross_vehicle_weight",
        "最大積載量は整数で入力してください。": "max_payload",
        "最大積載量は0以上で入力してください。": "max_payload",
        "最大積載量の値が大きすぎます。": "max_payload",
        "会社コードを入力してください。": "company_code",
        "会社コードは50文字以内で入力してください。": "company_code",
        "会社コードは半角英数字・ハイフン・アンダースコアのみ使用できます。": "company_code",
        "この会社コードはすでに登録されています。": "company_code",
        "会社名を入力してください。": "company_name",
        "会社名は100文字以内で入力してください。": "company_name",
        "車両上限数は整数で入力してください。": "vehicle_limit",
        "車両上限数は0以上で入力してください。": "vehicle_limit",
        "車両上限数の値が大きすぎます。": "vehicle_limit",
        "通知対象が不正です。": "target_type",
        "タイトルを入力してください。": "title",
        "タイトルは200文字以内で入力してください。": "title",
        "本文は10000文字以内で入力してください。": "message_editor",
        "チェックリスト名を入力してください。": "name",
        "チェックリスト名は200文字以内で入力してください。": "name",
        "このチェックリストはすでに登録されています。": "name",
        "用途が不正です。": "target",
        "頻度は整数で入力してください。": "frequency_value",
        "頻度は1以上で入力してください。": "frequency_value",
        "頻度は9999以下で入力してください。": "frequency_value",
        "頻度単位が不正です。": "frequency_unit",
        "表示形式が不正です。": "display_type",
        "未実施通知時刻の形式が不正です。": "reminder_time",
        "重要度が不正です。": "priority",
        "状態が不正です。": "status",
        "修理担当者は100文字以内で入力してください。": "repair_person",
        "修理時間の形式が不正です。": "repair_time",
        "修理費用が不正です。": "cost",
        "修理費用は50文字以内で入力してください。": "cost",
        "修理費用は0以上で入力してください。": "cost",
    }

    if (
        _dkss_common.request.path.startswith("/itc/news")
        and message in {
            "対象会社が不正です。",
            "対象営業所が不正です。",
            "対象ユーザーが不正です。",
        }
    ):
        return "newsTargetSearch"

    return field_map.get(message)



def is_html_document_request():
    if _dkss_common.request.path.startswith("/api/"):
        return False

    if _dkss_common.request.is_json:
        return False

    fetch_dest = _dkss_common.request.headers.get(
        "Sec-Fetch-Dest",
        ""
    ).lower()

    if fetch_dest:
        return fetch_dest == "document"

    fetch_mode = _dkss_common.request.headers.get(
        "Sec-Fetch-Mode",
        ""
    ).lower()

    if fetch_mode:
        return fetch_mode == "navigate"

    accept_header = _dkss_common.request.headers.get(
        "Accept",
        ""
    ).lower()

    return "text/html" in accept_header



def build_safe_redirect_url(referrer, fallback="/"):
    """Build a local application URL; never redirect to a supplied URL verbatim."""
    adapter = _dkss_runtime.app.url_map.bind_to_environ(_dkss_common.request.environ)
    for candidate in (referrer, fallback):
        if not isinstance(candidate, str) or not candidate:
            continue
        if any(ord(char) < 32 or ord(char) == 127 for char in candidate):
            continue
        try:
            resolved = _dkss_common.urlparse(_dkss_common.urljoin(
                _dkss_common.request.host_url, candidate.replace("\\", "/")
            ))
            if resolved.scheme not in {"http", "https"}:
                continue
            if resolved.username is not None or resolved.password is not None:
                continue
            if resolved.netloc.lower() != _dkss_common.request.host.lower():
                continue
            matched = None
            for method in dict.fromkeys(("GET", _dkss_common.request.method)):
                try:
                    matched = adapter.match(resolved.path or "/", method=method)
                    break
                except _dkss_common.HTTPException:
                    continue
            if matched is None:
                continue
            endpoint, route_values = matched
            values = {}
            for key, value in _dkss_common.parse_qsl(resolved.query, keep_blank_values=True):
                # url_for reserves underscore-prefixed arguments for URL options.
                if key.startswith("_") or key in route_values:
                    continue
                values.setdefault(key, []).append(value)
            values.update(route_values)
            return _dkss_common.url_for(endpoint, _external=False, **values)
        except (ValueError, _dkss_common.BuildError):
            continue
    return "/"



def redirect_form_errors(response):
    if response.headers.get("X-DKSS-Import-Recovery") == "1":
        return response
    if _dkss_common.request.method != "POST":
        return response

    if _dkss_common.request.path.startswith("/api/"):
        return response

    if response.status_code not in {
        400,
        403,
        409,
        413,
        429,
        500,
        503,
    }:
        return response

    if not is_html_document_request():
        return response

    message = response.get_data(
        as_text=True
    ).strip()

    form_errors_already_flashed = (
        response.headers.get(
            "X-DKSS-Form-Errors"
        ) == "1"
    )

    if not message and not form_errors_already_flashed:
        if _dkss_common.request.path != "/pointouts/new":
            message = "入力内容を確認してください。"

    error_field = get_form_error_field(message)

    if _dkss_common.request.path == "/pointouts/new":
        target_type = _dkss_common.request.form.get(
            "target_type",
            "user"
        ).strip()

        if target_type in {"user", "delivery_place"}:
            _dkss_common.session["pointout_form_target_type"] = target_type

        _dkss_common.session["pointout_form_data"] = {
            "date": _dkss_common.request.form.get("date", ""),
            "category": _dkss_common.request.form.get("category", ""),
            "target_user": _dkss_common.request.form.get("target_user", ""),
            "target_user_search": _dkss_common.request.form.get("target_user_search", ""),
            "delivery_place": _dkss_common.request.form.get("delivery_place", ""),
            "content_type": _dkss_common.request.form.get("content_type", ""),
            "content": _dkss_common.request.form.get("content", ""),
        }

    elif _dkss_common.request.path.endswith("/countermeasure"):
        _dkss_common.session["countermeasure_form_data"] = {
            "countermeasure": _dkss_common.request.form.get(
                "countermeasure",
                ""
            ),
            "countermeasure_by": _dkss_common.request.form.get(
                "countermeasure_by",
                ""
            ),
            "countermeasure_by_search": _dkss_common.request.form.get(
                "countermeasure_by_search",
                ""
            ),
            "countermeasure_by_username": _dkss_common.request.form.get(
                "countermeasure_by_username",
                ""
            ),
            "countermeasure_due_date": _dkss_common.request.form.get(
                "countermeasure_due_date",
                ""
            ),
        }

    elif (
        _dkss_common.request.path.startswith("/pointouts/")
        and _dkss_common.request.path.endswith("/edit")
    ):
        _dkss_common.session["pointout_edit_form_data"] = {
            "date": _dkss_common.request.form.get("date", ""),
            "category": _dkss_common.request.form.get("category", ""),
            "target_user": _dkss_common.request.form.get("target_user", ""),
            "target_user_search": _dkss_common.request.form.get(
                "target_user_search",
                ""
            ),
            "delivery_place": _dkss_common.request.form.get(
                "delivery_place",
                ""
            ),
            "content_type": _dkss_common.request.form.get(
                "content_type",
                ""
            ),
            "content": _dkss_common.request.form.get("content", ""),
        }

    elif _dkss_common.request.path.endswith("/reject"):
        _dkss_common.session["pointout_reject_form_data"] = {
            "reject_reason": _dkss_common.request.form.get(
                "reject_reason",
                ""
            ),
        }

    elif _dkss_common.request.path == "/master/drivers/new":
        driver_form_data = _dkss_common.request.form.to_dict(
            flat=True
        )
        driver_form_data.pop("password", None)

        _dkss_common.session["driver_form_data"] = {
            **driver_form_data,
            "vehicles": _dkss_common.request.form.getlist("vehicles"),
            "license_type": _dkss_common.request.form.getlist(
                "license_type"
            ),
            "license_expiry": _dkss_common.request.form.getlist(
                "license_expiry"
            ),
        }

    elif (
        _dkss_common.request.path.startswith("/master/drivers/")
        and _dkss_common.request.path.endswith("/edit")
    ):
        driver_form_data = _dkss_common.request.form.to_dict(
            flat=True
        )
        driver_form_data.pop("password", None)

        _dkss_common.session["driver_edit_form_data"] = {
            **driver_form_data,
            "vehicles": _dkss_common.request.form.getlist("vehicles"),
            "license_type": _dkss_common.request.form.getlist(
                "license_type"
            ),
            "license_expiry": _dkss_common.request.form.getlist(
                "license_expiry"
            ),
        }

    elif _dkss_common.request.path == "/master/vehicles/new":
        _dkss_common.session["vehicle_form_data"] = _dkss_common.request.form.to_dict(
            flat=True
        )

    elif (
        _dkss_common.request.path.startswith("/master/vehicles/")
        and _dkss_common.request.path.endswith("/edit")
    ):
        _dkss_common.session["vehicle_edit_form_data"] = _dkss_common.request.form.to_dict(
            flat=True
        )

    elif _dkss_common.request.path == "/master/checklists/new":
        _dkss_common.session["checklist_form_data"] = _dkss_common.request.form.to_dict(
            flat=False
        )

    elif (
        _dkss_common.request.path.startswith("/master/checklists/")
        and _dkss_common.request.path.endswith("/edit")
    ):
        _dkss_common.session["checklist_edit_form_data"] = _dkss_common.request.form.to_dict(
            flat=False
        )

    if not form_errors_already_flashed:
        _dkss_common.flash(
            message,
            f"error:{error_field or ''}"
        )

    if _dkss_common.request.path == "/pointouts/new":
        return _dkss_common.redirect("/pointouts/new")

    return _dkss_common.redirect(
        build_safe_redirect_url(
            _dkss_common.request.referrer,
            _dkss_common.request.path
        )
    )



def handle_upload_validation_error(error):
    _dkss_runtime.app.logger.warning(
        "アップロード検証エラー: %s",
        error
    )

    if (
        _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1"
        or _dkss_common.request.headers.get("X-DKSS-Final-Submit") == "1"
    ):
        return return_form_errors(
            [
                (
                    str(error)
                    or "アップロード内容を確認してください。",
                    ""
                )
            ],
            status_code=400
        )

    return "アップロード内容を確認してください。", 400



def handle_http_error(error):
    from .import_flow import form_error_response
    import_messages = {403: 'この操作の権限またはログイン状態を確認してください。',
        404: '確認中の資料が見つかりません。登録済み・取消済みの可能性があります。元の画面で状況を確認してください。',
        429: '操作が集中しています。少し待ってから再試行するか、元の画面へ戻ってください。'}
    recovery = form_error_response([(import_messages.get(error.code, '資料の処理を続けられませんでした。内容・受付状況を確認するか、元の画面へ戻ってください。'), '')], error.code or 500)
    if recovery is not None:
        if error.code == 500:
            _dkss_common.db.session.rollback()
        retry_after = error.get_response().headers.get('Retry-After')
        if retry_after:
            recovery.headers['Retry-After'] = retry_after
        return recovery
    if error.code == 500:
        _dkss_common.db.session.rollback()

    if not is_html_document_request():
        return error

    error_messages = {
        400: "入力内容を確認してください。",
        401: "ログインが必要です。",
        403: "この操作を行う権限がありません。",
        404: "ページが見つかりません。",
        405: "この操作は利用できません。",
        409: "処理を完了できませんでした。最新の状態を確認してください。",
        413: "1回に送信できるファイルの合計は1GB以下です。",
        429: "操作回数が多すぎます。少し待ってからもう一度お試しください。",
    }

    _dkss_common.flash(
        error_messages.get(
            error.code,
            "処理中にエラーが発生しました。"
        ),
        "error:"
    )

    return _dkss_common.redirect(
        build_safe_redirect_url(
            _dkss_common.request.referrer,
            "/"
        )
    )



def handle_unexpected_error(error):
    _dkss_common.db.session.rollback()

    if isinstance(error, _dkss_common.HTTPException):
        return handle_http_error(error)

    _dkss_runtime.app.logger.exception(
        "予期しないエラーが発生しました。"
    )

    from .import_flow import form_error_response
    recovery = form_error_response([('処理を完了できませんでした。元の画面で受付・登録結果を確認してから再試行してください。', '')], 500)
    if recovery is not None:
        return recovery

    if not is_html_document_request():
        if (
            _dkss_common.request.path.startswith("/api/")
            or _dkss_common.request.path == "/notifications/email-test"
        ):
            return {
                "ok": False,
                "message": "処理中にエラーが発生しました。"
            }, 500

        return "処理中にエラーが発生しました。", 500

    _dkss_common.flash(
        "処理中にエラーが発生しました。もう一度お試しください。",
        "error:"
    )

    return _dkss_common.redirect(
        build_safe_redirect_url(
            _dkss_common.request.referrer,
            "/"
        )
    )



def parse_nonnegative_int(value, field_name):
    value = str(value or "").strip()

    if not value:
        return 0

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise _dkss_common.UploadValidationError(
            f"{field_name}は整数で入力してください。"
        )

    if parsed < 0:
        raise _dkss_common.UploadValidationError(
            f"{field_name}は0以上で入力してください。"
        )

    if parsed > 2147483647:
        raise _dkss_common.UploadValidationError(
            f"{field_name}の値が大きすぎます。"
        )

    return parsed



def parse_time_hhmm(value, field_name):
    value = str(value or "").strip()

    try:
        parsed = _dkss_common.datetime.strptime(
            value,
            "%H:%M"
        )
    except ValueError:
        raise _dkss_common.UploadValidationError(
            f"{field_name}の形式が不正です。"
        )

    return parsed.strftime("%H:%M")



def sanitize_excel_formulas(workbook):
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows():
            for cell in row:
                value = cell.value

                if not isinstance(value, str):
                    continue

                stripped_value = value.lstrip()

                if stripped_value.startswith(
                    ("=", "+", "-", "@")
                ):
                    cell.value = "'" + value
