"""Checklists responsibilities; routes are registered by the application factory."""
from .report_layout import spreadsheet_text_width
from . import access as _dkss_access, audit as _dkss_audit, checklist_common as _dkss_checklist_common, checklist_notifications as _dkss_checklist_notifications, common as _dkss_common, http as _dkss_http, master_readers as _dkss_master_readers, models as _dkss_models, notifications_delivery as _dkss_notifications_delivery, runtime as _dkss_runtime, safety_permissions as _dkss_safety_permissions, serialization as _dkss_serialization, storage as _dkss_storage, vehicle_karte as _dkss_vehicle_karte, vehicle_readers as _dkss_vehicle_readers


def checklist_master():
    try:
        _dkss_checklist_common.ensure_daily_inspection_checklist()
        _dkss_common.db.session.commit()
    except Exception:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("日常点検の標準様式の登録に失敗しました。")
        _dkss_common.flash("日常点検の標準様式を登録できませんでした。", "error:")
        return _dkss_common.render_template(
            "checklist_master.html",
            checklists=[],
            keyword=_dkss_common.request.args.get("keyword", "").strip(),
            target=_dkss_common.request.args.get("target", "").strip(),
            status=_dkss_common.request.args.get("status", "").strip()
        ), 500

    checklists = _dkss_checklist_common.checklists_for_current_company()
    master_order_ids = [checklist["id"] for checklist in checklists]
    company_code = _dkss_common.session.get("company_code")

    keyword = _dkss_common.request.args.get("keyword", "").strip()
    target = _dkss_common.request.args.get("target", "").strip()
    status = _dkss_common.request.args.get("status", "").strip()

    for checklist in checklists:
        checklist_id = checklist["id"]

        has_safety_results = _dkss_models.ChecklistResult.query.filter_by(
            company_code=company_code,
            checklist_id=checklist_id
        ).first()

        has_vehicle_results = _dkss_models.VehicleChecklistResult.query.filter_by(
            company_code=company_code,
            checklist_id=checklist_id
        ).first()

        checklist["has_results"] = bool(
            has_safety_results or has_vehicle_results
        )

    if keyword:
        keyword_lower = keyword.lower()
        checklists = [
            checklist
            for checklist in checklists
            if keyword_lower in checklist["name"].lower()
        ]

    if target:
        checklists = [
            checklist
            for checklist in checklists
            if checklist["target"] == target
        ]

    if status == "active":
        checklists = [
            checklist
            for checklist in checklists
            if checklist["active"]
        ]
    elif status == "inactive":
        checklists = [
            checklist
            for checklist in checklists
            if not checklist["active"]
        ]

    return _dkss_common.render_template(
        "checklist_master.html",
        checklists=checklists,
        master_order_ids=master_order_ids,
        keyword=keyword,
        target=target,
        status=status
    )



def new_checklist():
    if _dkss_common.request.method == "POST":
        form_errors = []

        target = _dkss_common.request.form.get("target", "").strip()

        if target not in {
            "安全管理",
            "車両管理"
        }:
            form_errors.append((
                "用途が不正です。",
                "target"
            ))

        item_categories = _dkss_common.request.form.getlist("item_category")
        item_contents = _dkss_common.request.form.getlist("item_content")
        input_types = _dkss_common.request.form.getlist("input_type")
        item_types = _dkss_common.request.form.getlist("item_type")
        approval_labels = _dkss_common.request.form.getlist("approval_label")
        approval_allow_general_list = _dkss_common.request.form.getlist("approval_allow_general")
        choices_list = _dkss_common.request.form.getlist("choices")
        criteria_list = _dkss_common.request.form.getlist("criteria")
        answer_required_list = _dkss_common.request.form.getlist("answer_required")
        shaded_list = _dkss_common.request.form.getlist("shaded")

        if len(item_types) > 500:
            form_errors.append((
                "チェック項目は500件以内で設定してください。",
                "item_type_0"
            ))

        for i, item_type in enumerate(item_types):
            if item_type not in {
                "check",
                "inspector",
                "approval"
            }:
                form_errors.append((
                    "項目種別が不正です。",
                    f"item_type_{i}"
                ))

        for i, input_type in enumerate(input_types):
            if input_type not in {
                "select",
                "text"
            }:
                form_errors.append((
                    "評価方式が不正です。",
                    f"input_type_{i}"
                ))

        required_list_length = len(item_types)

        if any(
            len(values) < required_list_length
            for values in [
                item_categories,
                item_contents,
                input_types,
                choices_list,
                criteria_list
            ]
        ):
            form_errors.append((
                "チェック項目のデータが不正です。",
                "item_type_0"
            ))

        if form_errors:
            return _dkss_http.return_form_errors(form_errors)

        score_enabled = _dkss_common.request.form.get("score_enabled") == "1"
        print_portrait = (
            _dkss_common.request.form.get("target") == "車両管理"
            and _dkss_common.request.form.get("print_portrait") == "1"
        )
        print_half_month = (
            _dkss_common.request.form.get("target") == "車両管理"
            and _dkss_common.request.form.get("print_half_month") == "1"
        )

        reminder_enabled = (
            _dkss_common.request.form.get("reminder_enabled") == "1"
        )

        reminder_time = "08:00"

        try:
            reminder_time = _dkss_http.parse_time_hhmm(
                _dkss_common.request.form.get("reminder_time") or "08:00",
                "未実施通知時刻"
            )
        except _dkss_common.UploadValidationError:
            form_errors.append((
                "未実施通知時刻の入力内容を確認してください。",
                "reminder_time"
            ))

        items = []
        pending_criteria_files = []

        for i in range(len(item_types)):
            item_type = item_types[i]

            if item_type == "inspector":
                items.append({
                    "item_type": "inspector",
                })
                continue

            if item_type == "approval":
                label = ""

                if i < len(approval_labels):
                    label = approval_labels[i].strip()

                if len(label) > 100:
                    form_errors.append((
                        "承認ラベルは100文字以内で入力してください。",
                        f"approval_label_{i}"
                    ))

                items.append({
                    "item_type": "approval",
                    "approval_label": label,
                    "approval_allow_general": str(i) in approval_allow_general_list,
                    "criteria_files": [],
                })

                continue

            if i >= len(item_contents):
                continue

            if (
                not item_contents[i]
                and input_types[i] != "text"
            ):
                continue

            category = str(
                item_categories[i] or ""
            ).strip()
            content = str(
                item_contents[i] or ""
            ).strip()
            criteria = str(
                criteria_list[i] or ""
            ).strip()

            if len(category) > 100:
                form_errors.append((
                    "カテゴリは100文字以内で入力してください。",
                    f"item_category_{i}"
                ))

            if len(content) > 500:
                form_errors.append((
                    "チェック内容は500文字以内で入力してください。",
                    f"item_content_{i}"
                ))

            if len(criteria) > 500:
                form_errors.append((
                    "判定基準は500文字以内で入力してください。",
                    f"criteria_{i}"
                ))

            choices = []

            if input_types[i] == "select":
                choices = [
                    choice.strip()
                    for choice in choices_list[i].split(",")
                    if choice.strip()
                ]

                if not choices:
                    form_errors.append((
                        "選択式のチェック項目には評価の選択肢を1つ以上入力してください。",
                        f"choices_{i}"
                    ))
                elif len(choices) > 100:
                    form_errors.append((
                        "選択肢は100個以内で入力してください。",
                        f"choices_{i}"
                    ))
                elif any(
                    len(choice) > 100
                    for choice in choices
                ):
                    form_errors.append((
                        "各選択肢は100文字以内で入力してください。",
                        f"choices_{i}"
                    ))

            item_index = len(items)

            items.append({
                "item_type": "check",
                "category": category,
                "content": content,
                "input_type": input_types[i],
                "choices": choices,
                "criteria": criteria,
                "criteria_files": [],
                "answer_required": str(i) in answer_required_list,
                "shaded": str(i) in shaded_list,
                "score_enabled": score_enabled,
            })

            pending_criteria_files.append((item_index, i))

        frequency_value = ""
        frequency_unit = ""
        display_type = ""

        if target == "車両管理":
            frequency_value = _dkss_common.request.form.get(
                "frequency_value",
                ""
            ).strip()
            frequency_unit = _dkss_common.request.form.get(
                "frequency_unit",
                ""
            ).strip()
            display_type = _dkss_common.request.form.get(
                "display_type",
                ""
            ).strip()

            try:
                frequency_number = int(frequency_value)
            except (TypeError, ValueError):
                form_errors.append((
                    "頻度は整数で入力してください。",
                    "frequency_value"
                ))
                frequency_number = None

            if frequency_number is not None:
                if frequency_number < 1:
                    form_errors.append((
                        "頻度は1以上で入力してください。",
                        "frequency_value"
                    ))
                elif frequency_number > 9999:
                    form_errors.append((
                        "頻度は9999以下で入力してください。",
                        "frequency_value"
                    ))
                else:
                    frequency_value = str(frequency_number)

            if frequency_unit not in {
                "day",
                "month",
                "year"
            }:
                form_errors.append((
                    "頻度単位が不正です。",
                    "frequency_unit"
                ))

            if display_type not in {
                "month",
                "year"
            }:
                form_errors.append((
                    "表示形式が不正です。",
                    "display_type"
                ))

        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            form_errors.append((
                "チェックリスト名を入力してください。",
                "name"
            ))
        elif len(name) > 200:
            form_errors.append((
                "チェックリスト名は200文字以内で入力してください。",
                "name"
            ))

        duplicate_checklist = _dkss_models.Checklist.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            name=name
        ).first()

        if duplicate_checklist:
            form_errors.append((
                "このチェックリストはすでに登録されています。",
                "name"
            ))

        if form_errors:
            return _dkss_http.return_form_errors(
                form_errors,
                409 if duplicate_checklist else 400
            )

        pending_uploads = []

        if not _dkss_common.session.get("company_code"):
            return "company_code is required for file upload.", 400

        upload_file_count = sum(
            1
            for field_name in _dkss_common.request.files.keys()
            for file in _dkss_common.request.files.getlist(field_name)
            if file and file.filename
        )

        if upload_file_count > 50:
            return (
                "一度にアップロードできるファイルは50件までです。",
                400
            )

        for item_index, form_index in pending_criteria_files:
            for file in _dkss_common.request.files.getlist(
                f"criteria_files_{form_index}"
            ):
                if not file or not file.filename:
                    continue

                original_filename = _dkss_common.os.path.basename(
                    str(file.filename or "")
                )

                extension = _dkss_common.os.path.splitext(
                    original_filename
                )[1].lower()

                if (
                    extension not in _dkss_common.ALLOWED_UPLOAD_EXTENSIONS
                    or not _dkss_storage.is_valid_uploaded_file(
                        file,
                        extension
                    )
                ):
                    return "添付ファイルの検証に失敗しました。", 400

                pending_uploads.append(
                    (item_index, file)
                )

        for item_index, file in pending_uploads:
            filename = _dkss_storage.save_uploaded_file(file)

            if filename:
                items[item_index]["criteria_files"].append(filename)

        checklist = _dkss_models.Checklist(
            company_code=_dkss_common.session.get("company_code"),
            name=name,
            target=target,
            frequency_value=frequency_value,
            frequency_unit=frequency_unit,
            display_type=display_type,
            print_portrait=print_portrait,
            print_half_month=print_half_month,
            reminder_enabled=reminder_enabled,
            reminder_time=reminder_time,
            items_json=_dkss_common.json.dumps(items, ensure_ascii=False)
        )

        _dkss_common.db.session.add(checklist)
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/checklists")

    checklist_form_data = _dkss_common.session.pop(
        "checklist_form_data",
        {}
    )

    retained_checklist = _dkss_http.checklist_form_data_to_dict(
        checklist_form_data
    )

    return _dkss_common.render_template(
        "checklist_form.html",
        checklist=retained_checklist,
        index=None,
        mode="new"
    )



def checklist_navigation_owner():
    owner = [_dkss_common.session.get("company_code"), _dkss_common.session.get("username")]
    if _dkss_common.session.get("checklist_navigation_owner") != owner:
        _dkss_common.session["checklist_navigation_owner"] = owner
        _dkss_common.session.pop("checklist_last_safety", None)
        _dkss_common.session.pop("checklist_last_vehicle", None)



def checklist_entry_redirect(section, checklists):
    """Open an available checklist directly, never a stale remembered ID."""
    checklist_navigation_owner()
    if not checklists:
        return None
    remembered = _dkss_common.session.get("checklist_last_" + section)
    selected = next((row for row in checklists if row["id"] == remembered), checklists[0])
    allowed = ("target_type", "target_value") if section == "safety" else ("vehicle_record_id", "year", "month", "active_day")
    params = {key: _dkss_common.request.args[key] for key in allowed if _dkss_common.request.args.get(key)}
    return _dkss_common.redirect(_dkss_common.url_for(section + "_checklist_results", index=selected["id"], **params))



def checklist_result_navigation(checklist, section):
    checklist_navigation_owner()
    target = "安全管理" if section == "safety" else "車両管理"
    choices = [row for row in _dkss_checklist_common.checklists_for_current_company()
               if row["target"] == target and (row.get("active", True) or row["id"] == checklist.id)]
    if checklist.active:
        _dkss_common.session["checklist_last_" + section] = checklist.id
    allowed = ("target_type", "target_value") if section == "safety" else ("vehicle_record_id", "year", "month")
    params = {key: _dkss_common.request.args[key] for key in allowed if _dkss_common.request.args.get(key)}
    current = _dkss_checklist_common.checklist_to_dict(checklist)
    items = []
    for row in choices:
        row_params = dict(params)
        if section == "vehicle" and _dkss_common.request.args.get("active_day") and all(
            row.get(key) == current.get(key) for key in ("frequency_unit", "frequency_value", "display_type")
        ):
            row_params["active_day"] = _dkss_common.request.args["active_day"]
        items.append({"id": row["id"], "name": row["name"],
                      "active": row.get("active", True),
                      "url": _dkss_common.url_for(section + "_checklist_results", index=row["id"], **row_params)})
    return items



def safety_checklists():
    safety_lists = []

    for checklist in _dkss_checklist_common.checklists_for_current_company():
        if (
            checklist["target"] == "安全管理"
            and checklist.get("active", True)
        ):
            safety_lists.append(checklist)

    destination = checklist_entry_redirect("safety", safety_lists)
    if destination is not None:
        return destination
    return _dkss_common.render_template(
        "safety_checklists.html",
        checklists=safety_lists
    )



def safety_checklist_results(index):
    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code"),
        target="安全管理"
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/safety/checklists")

    checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)

    version_history = []

    for version in checklist.get("version_history", []):
        try:
            change_datetime = _dkss_common.datetime.strptime(
                version.get("effective_until", ""),
                "%Y-%m-%d %H:%M:%S"
            )
        except (TypeError, ValueError):
            continue

        version_history.append({
            "change_date": change_datetime.date(),
            "snapshot": version.get("snapshot") or {}
        })

    version_history.sort(
        key=lambda version: version["change_date"]
    )

    results = []

    query = _dkss_models.ChecklistResult.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        checklist_id=checklist_record.id
    )

    target_type = _dkss_common.request.args.get("target_type", "").strip()
    target_value = _dkss_common.request.args.get("target_value", "").strip()

    if target_type == "user" and target_value:
        query = query.filter(
            _dkss_models.ChecklistResult.target_type == "user",
            _dkss_models.ChecklistResult.target_username == target_value
        )

    elif target_type == "vehicle" and target_value:
        if not target_value.isdigit():
            return "対象車両が不正です。", 400

        query = query.filter(
            _dkss_models.ChecklistResult.target_type == "vehicle",
            _dkss_models.ChecklistResult.target_vehicle_record_id == int(target_value)
        )

    elif target_type == "office" and target_value:
        query = query.filter(
            _dkss_models.ChecklistResult.target_type == "office",
            _dkss_models.ChecklistResult.target_office == target_value
        )

    query = query.filter_by(
        company_code=_dkss_common.session.get("company_code")
    )

    for result in query.order_by(
        _dkss_models.ChecklistResult.checked_date.desc(),
        _dkss_models.ChecklistResult.id.desc()
    ).all():
        item = _dkss_checklist_common.checklist_result_to_dict(result)

        if not _dkss_safety_permissions.can_view_checklist_result(item):
            continue

        item["can_manage"] = _dkss_safety_permissions.can_manage_checklist_result(item)

        result_checklist = (
            item.get("checklist_snapshot")
            or _dkss_checklist_common.checklist_for_date(
                checklist,
                item.get("checked_date", "")[:4],
                item.get("checked_date", "")[5:7],
                item.get("checked_date", "")[8:10]
            )
        )

        item["checklist_revision_key"] = _dkss_checklist_common.checklist_revision_key(
            result_checklist
        )

        results.append(item)
    checklist_periods = []

    current_period = None

    # 期間判定は古い結果 → 新しい結果の順で行う
    for result in reversed(results):
        try:
            result_date = _dkss_common.datetime.strptime(
                result.get("checked_date", ""),
                "%Y-%m-%d %H:%M"
            ).date()
        except (TypeError, ValueError):
            continue

        checklist_key = result.get(
            "checklist_revision_key"
        )

        if (
            current_period is None
            or checklist_key
            != current_period["checklist_revision_key"]
        ):
            current_period = {
                "start_date": result_date,
                "end_date": result_date,
                "checklist_revision_key": checklist_key,
                "checklist": (
                    result.get("checklist_snapshot")
                    or checklist
                ),
                "results": []
            }
            checklist_periods.append(current_period)
        else:
            current_period["end_date"] = result_date

        current_period["results"].append(result)

    # 一覧では最新の様式・最新の結果を上に表示する
    for period in checklist_periods:
        period["results"].reverse()

    checklist_periods.reverse()

    return _dkss_common.render_template(
        "safety_checklist_results.html",
        checklist_navigation=checklist_result_navigation(checklist_record, "safety"),
        checklist=checklist,
        checklist_index=checklist_record.id,
        results=results,
        checklist_periods=checklist_periods
    )



def checklist_result_detail(result_index):
    result_record = _dkss_models.ChecklistResult.query.filter_by(
        id=result_index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not result_record:
        return _dkss_common.redirect("/safety/checklists")

    result = _dkss_checklist_common.checklist_result_to_dict(result_record)

    if not _dkss_safety_permissions.can_view_checklist_result(result):
        return _dkss_common.redirect("/safety/checklists")

    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=result_record.checklist_id,
        company_code=result_record.company_code
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/safety/checklists")

    checklist = (
        result.get("checklist_snapshot")
        or _dkss_checklist_common.checklist_to_dict(checklist_record)
    )
    if not result.get("approvals"):
        approvals = []

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get("approval_allow_general", False),
                "candidate_usernames": [],
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        result["approvals"] = approvals

    approval_items = [
        item
        for item in checklist.get("items", [])
        if item.get("item_type") == "approval"
    ]

    for approval_index, approval in enumerate(
        result.get("approvals", [])
    ):
        if (
            "allow_general" not in approval
            and approval_index < len(approval_items)
        ):
            approval["allow_general"] = approval_items[
                approval_index
            ].get(
                "approval_allow_general",
                False
            )

    criteria_list = []

    for answer in result["answers"]:
        criteria = answer.get("criteria", "")
        if criteria and criteria not in criteria_list:
            criteria_list.append(criteria)

    summary = {}
    total_score = 0
    max_score = 0

    check_items = [
        item
        for item in checklist["items"]
        if item.get("item_type") == "check"
    ]

    for item, answer in zip(check_items, result["answers"]):
        value = answer.get("value")

        # 自由記入は集計対象外
        if item.get("input_type") != "select":
            continue

        if value:
            if value not in summary:
                summary[value] = 0

            summary[value] += 1

        # 点数集計ONの場合だけ数値として計算
        if checklist.get("score_enabled"):
            try:
                total_score += float(value)
            except (TypeError, ValueError):
                pass

            numeric_choices = []

            for choice in item.get("choices", []):
                try:
                    numeric_choices.append(float(choice))
                except (TypeError, ValueError):
                    pass

            if numeric_choices:
                max_score += max(numeric_choices)

    result_items = []

    for item, answer in zip(
        check_items,
        result["answers"]
    ):
        result_item = dict(answer)
        result_item["input_type"] = item.get(
            "input_type",
            ""
        )

        result_item["has_detail"] = bool(
            str(
                answer.get("comment", "")
                or ""
            ).strip()
            or answer.get("files")
        )

        result_items.append(result_item)

    checklist_event_records = _dkss_models.ChecklistEvent.query.filter_by(
        company_code=result_record.company_code,
        result_type="safety",
        result_id=result_record.id
    ).order_by(
        _dkss_models.ChecklistEvent.id.asc()
    ).all()

    checklist_events = []

    for event in checklist_event_records:
        checklist_events.append({
            "event_type": event.event_type,
            "actor_username": event.actor_username,
            "actor_name": event.actor_name,
            "created_at": event.created_at,
            "detail": _dkss_serialization.safe_json_dict(
                event.detail_json
            ),
        })

    current_approval = next(
        (
            approval
            for approval in result.get("approvals", [])
            if not (
                approval.get("approved_by")
                or approval.get("approved_by_username")
            )
        ),
        None
    )

    return _dkss_common.render_template(
        "checklist_result_detail.html",
        result=result,
        result_index=result_record.id,
        summary=summary,
        total_score=total_score,
        max_score=max_score,
        criteria_list=criteria_list,
        result_items=result_items,
        checklist=checklist,
        can_manage=_dkss_safety_permissions.can_manage_checklist_result(result),
        can_reject=_dkss_safety_permissions.can_reject_checklist_result(
            result,
            current_approval
        ),
        checklist_events=checklist_events,
    )



def export_checklist_result_excel(result_index):

    result_record = _dkss_models.ChecklistResult.query.filter_by(
        id=result_index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not result_record:
        return _dkss_common.redirect("/safety/checklists")

    result = _dkss_checklist_common.checklist_result_to_dict(result_record)

    if not _dkss_safety_permissions.can_view_checklist_result(result):
        return _dkss_common.redirect("/safety/checklists")

    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=result_record.checklist_id,
        company_code=result_record.company_code
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/safety/checklists")

    checklist = (
        result.get("checklist_snapshot")
        or _dkss_checklist_common.checklist_to_dict(checklist_record)
    )
    # 評価基準
    criteria_list = []

    for answer in result["answers"]:
        criteria = answer.get("criteria", "")

        if criteria and criteria not in criteria_list:
            criteria_list.append(criteria)


    # チェック項目
    check_items = [
        item
        for item in checklist["items"]
        if item.get("item_type") == "check"
    ]


    # 評価集計・合計点
    summary = {}
    total_score = 0
    max_score = 0

    for item, answer in zip(
        check_items,
        result["answers"]
    ):
        value = answer.get("value")

        # 自由記入は集計対象外
        if item.get("input_type") != "select":
            continue

        if value:
            summary[value] = summary.get(value, 0) + 1

        # 点数集計ONの場合だけ計算
        if checklist.get("score_enabled"):

            try:
                total_score += float(value)
            except (TypeError, ValueError):
                pass

            numeric_choices = []

            for choice in item.get("choices", []):
                try:
                    numeric_choices.append(float(choice))
                except (TypeError, ValueError):
                    pass

            if numeric_choices:
                max_score += max(numeric_choices)


    workbook = _dkss_common.Workbook()
    sheet = workbook.active
    sheet.title = "チェックリスト結果"
    sheet.sheet_view.view = "pageBreakPreview"
    sheet.sheet_view.showGridLines = False

    # タイトル
    sheet.merge_cells("A1:L1")

    sheet["A1"] = f"{checklist['name']} 結果"
    sheet["A1"].font = _dkss_common.Font(size=16, bold=True)
    sheet["A1"].alignment = _dkss_common.Alignment(
        horizontal="center",
        vertical="center"
    )

    sheet.row_dimensions[1].height = 28

    # 対象表示
    if result["target_type"] == "user":
        target_type_label = "ユーザー"
        target_value = result["target_user"] or "-"
    elif result["target_type"] == "vehicle":
        target_type_label = "車両"

        target_vehicle_record = _dkss_models.Vehicle.query.filter_by(
            company_code=result["company_code"],
            id=result["target_vehicle_record_id"]
        ).first()

        target_value = (
            " ".join(
                value
                for value in [
                    target_vehicle_record.plate_area or "",
                    target_vehicle_record.plate_class or "",
                    target_vehicle_record.plate_kana or "",
                    target_vehicle_record.plate_number or "",
                ]
                if value
            ) or "ナンバー未登録"
            if target_vehicle_record
            else "-"
        )
    elif result["target_type"] == "office":
        target_type_label = "営業所"
        target_value = result["target_office"] or "-"
    else:
        target_type_label = "指定なし"
        target_value = ""

    info_rows = [
        ["実施日", result["checked_date"] or ""],
        ["実施者", result["checked_by"] or ""],
        ["対象", target_value or target_type_label],
        ["状態", result["status"] or ""],
    ]

    start_row = 3

    thin = _dkss_common.Side(style="thin")

    for row_offset, values in enumerate(info_rows):
        row_number = start_row + row_offset

        # 見出し A:B
        sheet.merge_cells(
            start_row=row_number,
            start_column=1,
            end_row=row_number,
            end_column=2
        )

        label_cell = sheet.cell(
            row=row_number,
            column=1,
            value=values[0]
        )

        label_cell.font = _dkss_common.Font(bold=True)
        label_cell.fill = _dkss_common.PatternFill(
            fill_type="solid",
            fgColor="D9EAF7"
        )

        label_cell.alignment = _dkss_common.Alignment(
            vertical="center",
            wrap_text=True
        )

        # 値 C:L
        sheet.merge_cells(
            start_row=row_number,
            start_column=3,
            end_row=row_number,
            end_column=12
        )

        value_cell = sheet.cell(
            row=row_number,
            column=3,
            value=values[1]
        )

        value_cell.alignment = _dkss_common.Alignment(
            vertical="center",
            wrap_text=True
        )

        # 罫線
        for col_number in range(1, 13):
            sheet.cell(
                row=row_number,
                column=col_number
            ).border = _dkss_common.Border(
                left=thin,
                right=thin,
                top=thin,
                bottom=thin
            )

    # 上部情報の下から次の表示を開始
    current_row = start_row + len(info_rows) + 2


    # 評価基準
    if criteria_list:

        criteria_title_cell = sheet.cell(
            row=current_row,
            column=1,
            value="評価基準"
        )

        criteria_title_cell.font = _dkss_common.Font(bold=True)

        criteria_title_cell.fill = _dkss_common.PatternFill(
            fill_type="solid",
            fgColor="D9EAF7"
        )

        # 見出しはA:Hを結合
        sheet.merge_cells(
            start_row=current_row,
            start_column=1,
            end_row=current_row,
            end_column=12
        )

        current_row += 1


        for criteria in criteria_list:

            sheet.merge_cells(
                start_row=current_row,
                start_column=1,
                end_row=current_row,
                end_column=12
            )

            criteria_cell = sheet.cell(
                row=current_row,
                column=1,
                value=criteria
            )

            criteria_cell.alignment = _dkss_common.Alignment(
                vertical="top",
                wrap_text=True
            )

            for col_number in range(1, 13):
                sheet.cell(
                    row=current_row,
                    column=col_number
                ).border = _dkss_common.Border(
                    left=thin,
                    right=thin,
                    top=thin,
                    bottom=thin
                )

            current_row += 1


    # 評価集計
    if checklist.get("score_enabled") and summary:

        # 見出し A:B
        sheet.merge_cells(
            start_row=current_row,
            start_column=1,
            end_row=current_row,
            end_column=2
        )

        summary_title_cell = sheet.cell(
            row=current_row,
            column=1,
            value="評価集計"
        )

        summary_title_cell.font = _dkss_common.Font(bold=True)

        summary_title_cell.fill = _dkss_common.PatternFill(
            fill_type="solid",
            fgColor="D9EAF7"
        )

        # 内容 C:H
        sheet.merge_cells(
            start_row=current_row,
            start_column=3,
            end_row=current_row,
            end_column=12
        )

        summary_text = " / ".join(
            f"{value}：{count}件"
            for value, count in summary.items()
        )

        sheet.cell(
            row=current_row,
            column=3,
            value=summary_text
        )

        for col_number in range(1, 13):
            sheet.cell(
                row=current_row,
                column=col_number
            ).border = _dkss_common.Border(
                left=thin,
                right=thin,
                top=thin,
                bottom=thin
            )

        current_row += 1

    # 合計点
    if checklist.get("score_enabled"):

        # 見出し A:B
        sheet.merge_cells(
            start_row=current_row,
            start_column=1,
            end_row=current_row,
            end_column=2
        )

        score_title_cell = sheet.cell(
            row=current_row,
            column=1,
            value="合計点"
        )

        score_title_cell.font = _dkss_common.Font(bold=True)

        score_title_cell.fill = _dkss_common.PatternFill(
            fill_type="solid",
            fgColor="D9EAF7"
        )

        # 点数 C:H
        sheet.merge_cells(
            start_row=current_row,
            start_column=3,
            end_row=current_row,
            end_column=12
        )

        sheet.cell(
            row=current_row,
            column=3,
            value=(
                f"{int(total_score)} / {int(max_score)}点"
                if max_score
                else f"{int(total_score)}点"
            )
        )

        for col_number in range(1, 13):
            sheet.cell(
                row=current_row,
                column=col_number
            ).border = _dkss_common.Border(
                left=thin,
                right=thin,
                top=thin,
                bottom=thin
            )

        current_row += 2

    else:
        current_row += 1

    # チェック結果
    result_header_row = current_row
    sheet.row_dimensions[result_header_row].height = 24

    # A:B = カテゴリ
    # C:G = チェック内容
    # H   = 評価
    # I:L = コメント
    header_ranges = [
        ("カテゴリ", 1, 2),
        ("チェック内容", 3, 7),
        ("評価", 8, 8),
        ("コメント", 9, 12),
    ]

    for header, start_col, end_col in header_ranges:

        sheet.merge_cells(
            start_row=current_row,
            start_column=start_col,
            end_row=current_row,
            end_column=end_col
        )

        cell = sheet.cell(
            row=current_row,
            column=start_col,
            value=header
        )

        cell.font = _dkss_common.Font(bold=True)

        cell.fill = _dkss_common.PatternFill(
            fill_type="solid",
            fgColor="D9EAF7"
        )

        cell.alignment = _dkss_common.Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True
        )

        for col_number in range(
            start_col,
            end_col + 1
        ):
            sheet.cell(
                row=current_row,
                column=col_number
            ).border = _dkss_common.Border(
                left=thin,
                right=thin,
                top=thin,
                bottom=thin
            )

    current_row += 1


    for item, answer in zip(
        check_items,
        result["answers"]
    ):

        # カテゴリ A:B
        sheet.merge_cells(
            start_row=current_row,
            start_column=1,
            end_row=current_row,
            end_column=2
        )

        sheet.cell(
            row=current_row,
            column=1,
            value=answer.get("category", "")
        )

        # チェック内容 C:G
        sheet.merge_cells(
            start_row=current_row,
            start_column=3,
            end_row=current_row,
            end_column=7
        )

        sheet.cell(
            row=current_row,
            column=3,
            value=answer.get("content", "")
        )

        # コメント I:L
        sheet.merge_cells(
            start_row=current_row,
            start_column=9,
            end_row=current_row,
            end_column=12
        )

        if item.get("input_type") == "select":

            sheet.cell(
                row=current_row,
                column=8,
                value=answer.get("value", "")
            )

            sheet.cell(
                row=current_row,
                column=9,
                value=answer.get("comment", "") or ""
            )

        else:

            sheet.cell(
                row=current_row,
                column=9,
                value=answer.get("value", "") or ""
            )

        # 罫線
        for col_number in range(1, 13):
            sheet.cell(
                row=current_row,
                column=col_number
            ).border = _dkss_common.Border(
                left=thin,
                right=thin,
                top=thin,
                bottom=thin
            )

        current_row += 1

    # 12列構成
    # A～Lはすべて同じ幅
    for column_letter in [
        "A", "B", "C", "D", "E", "F",
        "G", "H", "I", "J", "K", "L"
    ]:
        sheet.column_dimensions[column_letter].width = 9

    # 折り返し
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = _dkss_common.Alignment(
                horizontal=cell.alignment.horizontal,
                vertical=cell.alignment.vertical or "top",
                wrap_text=True
            )


    import math

    def wrapped_line_count(text, available_width):
        text = str(text or "")

        if not text:
            return 1

        line_count = 0

        for line in text.split("\n"):
            line_count += max(
                1,
                math.ceil(
                    spreadsheet_text_width(line) / available_width
                )
            )

        return line_count


    # チェック項目の文字量に応じて行高を調整
    for row_number in range(
        result_header_row + 1,
        current_row
    ):

        # チェック内容 C:G
        content = sheet.cell(
            row=row_number,
            column=3
        ).value or ""

        # コメント I:L
        comment = sheet.cell(
            row=row_number,
            column=9
        ).value or ""

        content_lines = wrapped_line_count(
            content,
            52
        )

        comment_lines = wrapped_line_count(
            comment,
            41
        )

        line_count = max(
            content_lines,
            comment_lines
        )

        sheet.row_dimensions[row_number].height = max(
            20,
            (line_count * 17) + 2
        )

    # 評価列 H を中央揃え
    for row_number in range(
        result_header_row + 1,
        current_row
    ):
        sheet.cell(
            row=row_number,
            column=8
        ).alignment = _dkss_common.Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True
        )

    # 押印欄（実施者・承認項目をマスタの並び順で出力）
    approval_items = [
        item
        for item in checklist["items"]
        if item.get("item_type") in {"inspector", "approval"}
    ]

    approval_results = result.get("approvals", [])

    stamp_entries = []

    approval_index = 0

    for item in approval_items:
        if item.get("item_type") == "inspector":
            stamp_entries.append({
                "label": "実施者",
                "approved_by": result.get("checked_by", ""),
                "approved_by_username": result.get(
                    "checked_by_username",
                    ""
                ),
                "approved_date": result.get("checked_date", ""),
            })
            continue

        label = (
            item.get("approval_label", "").strip()
            or "承認"
        )

        approval_result = (
            approval_results[approval_index]
            if approval_index < len(approval_results)
            else {}
        )

        stamp_entries.append({
            "label": label,
            "approved_by": approval_result.get("approved_by", ""),
            "approved_by_username": approval_result.get(
                "approved_by_username",
                ""
            ),
            "approved_date": approval_result.get("approved_date", ""),
        })

        approval_index += 1

    stamp_headers = [
        entry["label"]
        for entry in stamp_entries
    ]

    stamp_start_row = current_row + 2

    if stamp_headers:

        # 承認欄タイトル
        stamp_title_cell = sheet.cell(
            row=stamp_start_row,
            column=12,
            value="確認・押印"
        )

        stamp_title_cell.font = _dkss_common.Font(bold=True)

        stamp_title_cell.alignment = _dkss_common.Alignment(
            horizontal="right",
            vertical="center"
        )

        # 1行につき最大6つ
        entry_chunks = [
            stamp_entries[i:i + 6]
            for i in range(0, len(stamp_entries), 6)
        ]

        row_number = stamp_start_row + 1

        for entry_chunk in entry_chunks:

            item_count = len(entry_chunk)

            stamp_header_row = row_number
            stamp_box_row = row_number + 1

            # 押印欄はセル結合しない
            # A～Lは全列同じ幅
            # 1項目につき1セル、間に1セル空けて均等配置
            #
            # 1個 → L
            # 2個 → J / L
            # 3個 → H / J / L
            # 4個 → F / H / J / L
            # 5個 → D / F / H / J / L
            # 6個 → B / D / F / H / J / L

            all_stamp_columns = [7, 8, 9, 10, 11, 12]

            stamp_columns = all_stamp_columns[
                6 - item_count:
            ]

            for entry, column in zip(
                entry_chunk,
                stamp_columns
            ):

                # 見出し
                header_cell = sheet.cell(
                    row=stamp_header_row,
                    column=column,
                    value=entry["label"]
                )

                header_cell.font = _dkss_common.Font(bold=True)

                header_cell.alignment = _dkss_common.Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True
                )

                header_cell.border = _dkss_common.Border(
                    left=thin,
                    right=thin,
                    top=thin,
                    bottom=thin
                )

                # 押印内容
                approval_user = _dkss_models.User.query.filter_by(
                    company_code=result_record.company_code,
                    username=entry.get("approved_by_username")
                ).first()

                stamp_value = (
                    approval_user.last_name
                    if approval_user
                    else (
                        entry.get("approved_by")
                        or entry.get("approved_by_username")
                        or ""
                    )
                )

                if stamp_value and entry["approved_date"]:
                    stamp_value += (
                        f"\n{entry['approved_date']}"
                    )

                stamp_cell = sheet.cell(
                    row=stamp_box_row,
                    column=column,
                    value=stamp_value
                )

                stamp_cell.alignment = _dkss_common.Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True
                )

                stamp_cell.border = _dkss_common.Border(
                    left=thin,
                    right=thin,
                    top=thin,
                    bottom=thin
                )

            sheet.row_dimensions[
                stamp_header_row
            ].height = 22

            sheet.row_dimensions[
                stamp_box_row
            ].height = 55

            row_number = stamp_box_row + 1

        current_row = row_number

    # A4印刷設定
    sheet.sheet_properties.pageSetUpPr.fitToPage = True

    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.orientation = sheet.ORIENTATION_PORTRAIT
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0

    # 印刷時に水平方向の中央へ配置
    sheet.print_options.horizontalCentered = True

    # 印刷範囲
    sheet.print_area = f"A1:L{current_row - 1}"

    # 余白
    sheet.page_margins.left = 0.25
    sheet.page_margins.right = 0.25
    sheet.page_margins.top = 0.25
    sheet.page_margins.bottom = 0.25
    sheet.page_margins.header = 0.2
    sheet.page_margins.footer = 0.2

    # 2ページ目以降もチェック結果の見出しを表示
    sheet.print_title_rows = (
        f"{result_header_row}:{result_header_row}"
    )

    # 添付画像シート
    attachment_items = []

    for answer in result["answers"]:
        for filename in answer.get("files", []):
            extension = _dkss_common.os.path.splitext(filename)[1].lower()

            if extension in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
                attachment_type = "image"

            elif extension in [
                ".mp4",
                ".webm",
                ".mov",
                ".m4v",
                ".avi",
                ".mkv",
                ".mts",
                ".m2ts",
                ".mpg",
                ".mpeg",
            ]:
                attachment_type = "video"

            else:
                continue

            attachment_items.append({
                "category": answer.get("category", ""),
                "content": answer.get("content", ""),
                "filename": filename,
                "type": attachment_type,
            })

    if attachment_items:
        attachment_sheet = workbook.create_sheet("添付画像")
        attachment_sheet.sheet_view.showGridLines = False

        attachment_sheet["A1"] = "添付画像"
        attachment_sheet["A1"].font = _dkss_common.Font(
            size=16,
            bold=True
        )

        attachment_row = 3

        for attachment in attachment_items:
            attachment_sheet["A" + str(attachment_row)] = "カテゴリ"
            attachment_sheet["B" + str(attachment_row)] = attachment["category"]

            attachment_sheet["A" + str(attachment_row + 1)] = "チェック内容"
            attachment_sheet["B" + str(attachment_row + 1)] = attachment["content"]

            if attachment["type"] == "image":

                image_buffer = _dkss_storage.load_upload_bytes(
                    attachment["filename"]
                )

                if image_buffer:
                    excel_image = _dkss_common.ExcelImage(image_buffer)

                    excel_image.width = 420
                    excel_image.height = 280

                    attachment_sheet.add_image(
                        excel_image,
                        f"B{attachment_row + 2}"
                    )

                attachment_sheet.row_dimensions[
                    attachment_row + 2
                ].height = 215

                attachment_row += 18

            elif attachment["type"] == "video":

                video_cell = attachment_sheet[
                    "B" + str(attachment_row + 2)
                ]

                video_cell.value = "▶ 動画を開く"

                video_cell.hyperlink = _dkss_common.url_for(
                    "uploaded_file",
                    folder="uploads",
                    filename=attachment["filename"],
                    _external=True
                )

                video_cell.style = "Hyperlink"

                attachment_row += 5

        attachment_sheet.column_dimensions["A"].width = 14
        attachment_sheet.column_dimensions["B"].width = 65

    output = _dkss_common.BytesIO()

    _dkss_http.sanitize_excel_formulas(workbook)

    workbook.save(output)
    output.seek(0)

    safe_checklist_name = checklist["name"].replace("/", "_").replace("\\", "_")
    safe_checked_date = (
        (result["checked_date"] or "")
        .replace("/", "-")
        .replace(":", "-")
    )

    filename = (
        f"{safe_checklist_name}_"
        f"{safe_checked_date}_"
        f"結果.xlsx"
    )

    return _dkss_common.send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )



def checklist_result_edit_version(record):
    snapshot = {
        column.key: getattr(record, column.key)
        for column in _dkss_common.inspect(record).mapper.column_attrs
    }
    latest_event = _dkss_models.ChecklistEvent.query.filter_by(
        company_code=record.company_code, result_type="safety", result_id=record.id
    ).order_by(_dkss_models.ChecklistEvent.id.desc()).first()
    # Identical resubmissions within the same minute must still invalidate a form.
    snapshot["latest_event_id"] = latest_event.id if latest_event else None
    return _dkss_common.hashlib.sha256(_dkss_common.json.dumps(
        snapshot, sort_keys=True, ensure_ascii=False, default=str,
    ).encode("utf-8")).hexdigest()



def edit_checklist_result(result_index):
    result_record = _dkss_models.ChecklistResult.query.filter_by(
        id=result_index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not result_record:
        return _dkss_common.redirect("/safety/checklists")

    if result_record.status == "承認済み":
        return _dkss_common.redirect(
            _dkss_common.url_for("checklist_result_detail", result_index=result_index)
        )

    result = _dkss_checklist_common.checklist_result_to_dict(result_record)

    if not _dkss_safety_permissions.can_manage_checklist_result(result):
        return _dkss_common.redirect(_dkss_common.url_for("checklist_result_detail", result_index=result_index))

    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=result_record.checklist_id,
        company_code=result_record.company_code
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/safety/checklists")

    checklist = (
        result.get("checklist_snapshot")
        or _dkss_checklist_common.checklist_to_dict(checklist_record)
    )

    if _dkss_common.request.method == "POST":
        company_code = _dkss_common.session.get("company_code")
        operation_now = _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo"))

        result_record = _dkss_models.ChecklistResult.query.filter_by(
            id=result_index,
            company_code=company_code
        ).with_for_update().first()

        if not result_record:
            return _dkss_common.redirect("/safety/checklists")

        if result_record.status == "承認済み":
            return _dkss_common.redirect(
                _dkss_common.url_for("checklist_result_detail", result_index=result_index)
            )

        _dkss_common.db.session.refresh(result_record)
        result = _dkss_checklist_common.checklist_result_to_dict(result_record)

        if not _dkss_safety_permissions.can_manage_checklist_result(result):
            return _dkss_common.redirect(
                _dkss_common.url_for("checklist_result_detail", result_index=result_index)
            )

        if not _dkss_common.secrets.compare_digest(
            _dkss_common.request.form.get("record_version", "").encode("utf-8"),
            checklist_result_edit_version(result_record).encode("ascii"),
        ):
            return _dkss_http.return_form_errors([
                ("記録が更新されています。入力内容を確認し、画面を再読み込みしてください。", "")
            ], status_code=409)

        checklist = (
            result.get("checklist_snapshot")
            or _dkss_checklist_common.checklist_to_dict(checklist_record)
        )

        target_type = _dkss_common.request.form.get(
            "target_type",
            ""
        ).strip()

        target_user = _dkss_common.request.form.get(
            "target_user",
            ""
        ).strip()
        target_username = ""

        target_vehicle_record_id = _dkss_common.request.form.get(
            "target_vehicle_record_id",
            type=int
        )

        target_office = _dkss_common.request.form.get(
            "target_office",
            ""
        ).strip()

        # 対象種別検証

        if target_type not in {
            "",
            "user",
            "vehicle",
            "office"
        }:
            return _dkss_http.return_form_errors([
                (
                    "対象種別が不正です。",
                    "target_type"
                )
            ])

        # 個人

        if target_type == "user":
            if not target_user:
                return _dkss_http.return_form_errors([
                    (
                        "対象ユーザーを選択してください。",
                        "target_user"
                    )
                ])

            target_driver = _dkss_models.Driver.query.filter_by(
                company_code=company_code,
                employee_id=target_user
            ).first()

            if not target_driver:
                return _dkss_http.return_form_errors([
                    (
                        "対象ユーザーが不正です。",
                        "target_user"
                    )
                ])

            target_user_record = _dkss_models.User.query.filter_by(
                company_code=company_code,
                username=target_driver.employee_id
            ).first()

            if not target_user_record:
                return _dkss_http.return_form_errors([
                    (
                        "対象ユーザー情報が不正です。",
                        "target_user"
                    )
                ])

            target_username = target_user_record.username
            target_user = target_driver.name

            target_office = target_driver.office or ""
            target_vehicle_record_id = None

        # 車両

        elif target_type == "vehicle":
            if not target_vehicle_record_id:
                return _dkss_http.return_form_errors([
                    (
                        "対象車両を選択してください。",
                        "target_vehicle_record_id"
                    )
                ])

            vehicle = _dkss_models.Vehicle.query.filter_by(
                company_code=company_code,
                id=target_vehicle_record_id,
                deleted=False
            ).first()

            if not vehicle:
                return _dkss_http.return_form_errors([
                    (
                        "対象車両が不正です。",
                        "target_vehicle_record_id"
                    )
                ])

            target_office = vehicle.office or ""
            target_user = ""
            target_username = ""

        # 営業所

        elif target_type == "office":
            if not target_office:
                return _dkss_http.return_form_errors([
                    (
                        "対象営業所を選択してください。",
                        "target_office"
                    )
                ])

            valid_office = _dkss_models.Office.query.filter_by(
                company_code=company_code,
                name=target_office
            ).with_for_update(read=True).first()

            if not valid_office:
                return _dkss_http.return_form_errors([
                    (
                        "対象営業所が不正です。",
                        "target_office"
                    )
                ])

            target_user = ""
            target_username = ""
            target_vehicle_record_id = None

        if target_type in {"user", "vehicle"} and not _dkss_master_readers.office_reference_is_current(
            company_code, target_office
        ):
            return _dkss_http.return_form_errors([
                ("営業所が更新されています。画面を再読み込みしてください。", "target_office")
            ])

        previous_answers = [
            dict(answer)
            for answer in result.get("answers", [])
        ]

        previous_target = {
            "target_type": result_record.target_type or "",
            "target_user": result_record.target_user or "",
            "target_username": result_record.target_username or "",
            "target_vehicle_record_id": (
                result_record.target_vehicle_record_id
            ),
            "target_office": result_record.target_office or "",
        }

        answers = []
        answer_index = 0
        pending_answer_files = []

        for item in checklist["items"]:
            if item.get("item_type") != "check":
                continue

            value = _dkss_common.request.form.get(
                f"answer_{answer_index}",
                ""
            )

            choices = item.get("choices", [])

            if item.get("input_type") == "select":
                if value and value not in choices:
                    return _dkss_http.return_form_errors([
                        (
                            "評価値が不正です。",
                            f"answer_{answer_index}"
                        )
                    ])

            comment = _dkss_common.request.form.get(
                f"comment_{answer_index}",
                ""
            ).strip()

            if (
                item.get("answer_required")
                and not value
            ):
                return _dkss_http.return_form_errors([
                    (
                        "必須項目が未回答です。",
                        f"answer_{answer_index}"
                    )
                ])

            if len(comment) > 5000:
                return _dkss_http.return_form_errors([
                    (
                        "コメントは5000文字以内で入力してください。",
                        f"comment_{answer_index}"
                    )
                ])

            file_names = []

            if answer_index < len(result["answers"]):
                file_names = list(
                    result["answers"][answer_index].get("files", [])
                )

            item_index = len(answers)

            answers.append({
                "item_no": answer_index,
                "category": item.get("category", ""),
                "content": item.get("content", ""),
                "criteria": item.get("criteria", ""),
                "criteria_files": item.get("criteria_files", []),
                "value": value,
                "comment": comment,
                "files": file_names,
                "patrol_link": (
                    _dkss_common.request.form.get(
                        f"patrol_link_{answer_index}"
                    ) == "1"
                    if f"patrol_link_{answer_index}" in _dkss_common.request.form
                    else (
                        previous_answers[answer_index].get(
                            "patrol_link",
                            False
                        )
                        if answer_index < len(previous_answers)
                        else False
                    )
                ),
            })

            pending_answer_files.append(
                (item_index, answer_index)
            )

            answer_index += 1

        pending_uploads = []

        upload_file_count = sum(
            1
            for field_name in _dkss_common.request.files.keys()
            for file in _dkss_common.request.files.getlist(field_name)
            if file and file.filename
        )

        if upload_file_count > 50:
            return _dkss_http.return_form_errors([
                (
                    "一度にアップロードできるファイルは50件までです。",
                    ""
                )
            ])

        for item_index, form_index in pending_answer_files:
            for file in _dkss_common.request.files.getlist(
                f"files_{form_index}"
            ):
                if not file or not file.filename:
                    continue

                original_filename = _dkss_common.os.path.basename(
                    str(file.filename or "")
                )

                extension = _dkss_common.os.path.splitext(
                    original_filename
                )[1].lower()

                if (
                    extension not in _dkss_common.ALLOWED_UPLOAD_EXTENSIONS
                    or not _dkss_storage.is_valid_uploaded_file(
                        file,
                        extension
                    )
                ):
                    return _dkss_http.return_form_errors([
                        (
                            "添付ファイルの検証に失敗しました。",
                            f"files_{form_index}"
                        )
                    ])

                pending_uploads.append(
                    (item_index, file)
                )

        result_record.target_type = target_type
        result_record.target_user = target_user
        result_record.target_username = target_username
        result_record.target_vehicle_record_id = target_vehicle_record_id
        result_record.target_office = target_office
        result_record.answers_json = _dkss_common.json.dumps(answers, ensure_ascii=False)

        notify_usernames = [
            username.strip()
            for username in _dkss_common.request.form.getlist(
                "notify_users"
            )
            if username.strip()
        ]

        notify_usernames = list(
            dict.fromkeys(notify_usernames)
        )

        if len(notify_usernames) > 500:
            return _dkss_http.return_form_errors([
                (
                    "通知先ユーザー数が多すぎます。",
                    "notify_user_search"
                )
            ])

        valid_users = {
            user.username: user
            for user in _dkss_models.User.query.filter_by(
                company_code=company_code
            ).all()
            if user.username
        }

        invalid_notify_usernames = [
            username
            for username in notify_usernames
            if username not in valid_users
        ]

        if invalid_notify_usernames:
            return _dkss_http.return_form_errors([
                (
                    "通知先ユーザーが不正です。",
                    "notify_user_search"
                )
            ])

        result_record.notify_users_json = _dkss_common.json.dumps(
            notify_usernames,
            ensure_ascii=False
        )

        approvals = []

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approval_index = len(approvals)

            submitted_candidate_usernames = [
                username.strip()
                for username in _dkss_common.request.form.getlist(
                    f"approval_notify_users_{approval_index}"
                )
                if username.strip()
            ]

            if len(submitted_candidate_usernames) > 500:
                return _dkss_http.return_form_errors([
                    (
                        "承認候補者数が多すぎます。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            invalid_candidate_usernames = [
                username
                for username in submitted_candidate_usernames
                if (
                    username not in valid_users
                    or not (
                        valid_users[username].role == "admin"
                        or (
                            item.get(
                                "approval_allow_general",
                                False
                            )
                            and valid_users[username].role == "user"
                        )
                    )
                )
            ]

            if invalid_candidate_usernames:
                return _dkss_http.return_form_errors([
                    (
                        "承認者の選択内容が不正です。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get("approval_allow_general", False),
                "candidate_usernames": list(
                    dict.fromkeys(submitted_candidate_usernames)
                ),
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        saved_filenames = []

        try:
            for item_index, file in pending_uploads:
                filename = _dkss_storage.save_uploaded_file(file)

                if filename:
                    answers[item_index]["files"].append(filename)
                    saved_filenames.append(filename)

        except _dkss_common.UploadValidationError:
            for filename in saved_filenames:
                _dkss_storage.delete_uploaded_file(filename)

            return _dkss_http.return_form_errors([
                (
                    "添付ファイルの検証に失敗しました。",
                    ""
                )
            ])

        changes = []

        current_target = {
            "target_type": target_type,
            "target_user": target_user,
            "target_username": target_username,
            "target_vehicle_record_id": target_vehicle_record_id,
            "target_office": target_office,
        }

        if previous_target != current_target:
            changes.append({
                "type": "target",
                "before": previous_target,
                "after": current_target,
            })

        previous_answers_by_item_no = {
            answer.get("item_no"): answer
            for answer in previous_answers
            if answer.get("item_no") is not None
        }

        for answer_index, answer in enumerate(answers):
            item_no = answer.get("item_no")

            previous_answer = previous_answers_by_item_no.get(
                item_no
            )

            if previous_answer is None:
                previous_answer = (
                    previous_answers[answer_index]
                    if answer_index < len(previous_answers)
                    else {}
                )

            before = {
                "value": previous_answer.get("value", ""),
                "comment": previous_answer.get("comment", ""),
                "files": previous_answer.get("files", []),
                "patrol_link": previous_answer.get(
                    "patrol_link",
                    False
                ),
            }

            after = {
                "value": answer.get("value", ""),
                "comment": answer.get("comment", ""),
                "files": answer.get("files", []),
                "patrol_link": answer.get(
                    "patrol_link",
                    False
                ),
            }

            if before != after:
                changes.append({
                    "item_no": answer.get("item_no"),
                    "category": answer.get("category", ""),
                    "content": answer.get("content", ""),
                    "before": before,
                    "after": after,
                })

        if target_type in _dkss_common.PATROL_VIEW_TYPES:
            previous_answers_by_item_no = {
                answer.get("item_no"): answer
                for answer in previous_answers
                if answer.get("item_no") is not None
            }

            for answer in answers:
                item_no = answer.get("item_no")

                previous_answer = (
                    previous_answers_by_item_no.get(
                        item_no,
                        {}
                    )
                )

                if (
                    answer.get("patrol_link")
                    and not previous_answer.get(
                        "patrol_link",
                        False
                    )
                ):
                    _dkss_common.db.session.add(_dkss_models.PatrolResult(
                        company_code=company_code,
                        created_by_username=_dkss_common.session.get("username"),
                        created_by_name=_dkss_common.session.get("name"),
                        date=operation_now.strftime("%Y-%m-%d"),
                        delivery_place="",
                        category="点検指摘",
                        content_type="安全",
                        target_type=target_type,
                        target_user=target_user,
                        target_username=target_username,
                        office=target_office,
                        content=(
                            f"{answer.get('category', '')}："
                            f"{answer.get('content', '')}"
                            f" / 評価：{answer.get('value') or '-'}"
                            f" / コメント：{answer.get('comment') or '-'}"
                        ),
                        files_json=_dkss_common.json.dumps(
                            answer.get("files", []),
                            ensure_ascii=False
                        ),
                        countermeasure="",
                        approval_status="未対応",
                        reject_reason=""
                    ))

        was_rejected = (
            result_record.status == "差し戻し"
        )

        result_record.status = (
            "承認待ち"
            if approvals
            else "点検完了"
        )
        result_record.approvals_json = _dkss_common.json.dumps(
            approvals,
            ensure_ascii=False
        )
        result_record.notify_users_json = _dkss_common.json.dumps(
            notify_usernames,
            ensure_ascii=False
        )
        result_record.approved_by = ""
        result_record.approved_by_username = ""
        result_record.approved_date = ""
        result_record.reject_reason = ""

        checklist_event = _dkss_models.ChecklistEvent(
            company_code=result_record.company_code,
            result_type="safety",
            result_id=result_record.id,
            event_type=(
                "再申請"
                if was_rejected
                else "修正"
            ),
            actor_username=_dkss_common.session.get("username"),
            actor_name=_dkss_common.session.get("name"),
            detail_json=_dkss_common.json.dumps(
                {
                    "changes": changes,
                    "approvals": approvals,
                },
                ensure_ascii=False
            ),
            created_at=operation_now.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        _dkss_common.db.session.add(checklist_event)

        mention_text = "\n".join(
            "\n".join([
                answer.get("value", "") or "",
                answer.get("comment", "") or "",
            ])
            for answer in answers
        )

        try:
            _dkss_common.db.session.commit()

        except _dkss_common.IntegrityError:
            _dkss_common.db.session.rollback()

            for filename in saved_filenames:
                _dkss_storage.delete_uploaded_file(filename)

            return _dkss_http.return_form_errors(
                [
                    (
                        "安全チェックリストの更新に失敗しました。"
                        "もう一度お試しください。",
                        ""
                    )
                ],
                status_code=409
            )

        except _dkss_common.SQLAlchemyError:
            _dkss_common.db.session.rollback()

            for filename in saved_filenames:
                _dkss_storage.delete_uploaded_file(filename)

            return _dkss_http.return_form_errors(
                [
                    (
                        "安全チェックリストの更新に失敗しました。"
                        "もう一度お試しください。",
                        ""
                    )
                ],
                status_code=500
            )

        approval_usernames = set(
            approvals[0].get("candidate_usernames") or []
        ) if approvals else set()

        notification_usernames = set(approval_usernames)

        if was_rejected:
            latest_rejection = _dkss_models.ChecklistEvent.query.filter_by(
                company_code=company_code,
                result_type="safety",
                result_id=result_record.id,
                event_type="差し戻し"
            ).order_by(
                _dkss_models.ChecklistEvent.id.desc()
            ).first()

            if latest_rejection and latest_rejection.actor_username:
                notification_usernames.add(
                    latest_rejection.actor_username
                )

        for target_username in sorted(notification_usernames):
            target_user = _dkss_models.User.query.filter_by(
                company_code=company_code,
                username=target_username
            ).first()

            if not target_user:
                continue

            is_approval_recipient = (
                target_username in approval_usernames
            )

            if was_rejected:
                notification_title = (
                    "安全チェックリスト再申請の承認依頼"
                    if is_approval_recipient
                    else "安全チェックリスト修正・再申請のお知らせ"
                )
                notification_message = (
                    f"「{checklist_record.name}」が"
                    "修正・再申請されました。"
                    + (
                        "承認をお願いします。"
                        if is_approval_recipient
                        else "変更内容を確認してください。"
                    )
                )
            else:
                notification_title = "安全チェックリスト承認依頼"
                notification_message = (
                    f"「{checklist_record.name}」"
                    "の承認をお願いします。"
                )

            _dkss_notifications_delivery.add_notification(
                (target_user.last_name or "")
                + (target_user.first_name or ""),
                notification_title,
                notification_message,
                f"/safety/checklist-results/{result_record.id}",
                company_code=company_code,
                target_identity=target_user.account_identity,
                target_username=target_user.username,
                workflow_context=(
                    _dkss_notifications_delivery.build_notification_workflow_context(
                        result_record,
                        "safety",
                        "approval",
                        approval_index=0
                    )
                    if is_approval_recipient
                    else None
                )
            )

        if result_record.status == "点検完了":
            completion_notify_usernames = set(
                notify_usernames
            )

            if result_record.target_username:
                completion_notify_usernames.add(
                    result_record.target_username
                )

            if result_record.checked_by_username:
                completion_notify_usernames.add(
                    result_record.checked_by_username
                )

            for notify_username in completion_notify_usernames:
                notify_user = valid_users.get(
                    notify_username
                )

                if not notify_user:
                    continue

                _dkss_notifications_delivery.add_notification(
                    (notify_user.last_name or "")
                    + (notify_user.first_name or ""),
                    "安全チェックリスト完了のお知らせ",
                    (
                        f"「{checklist_record.name}」の"
                        "チェックが完了しました。"
                    ),
                    f"/safety/checklist-results/{result_record.id}",
                    company_code=company_code,
                    target_identity=notify_user.account_identity,
                    target_username=notify_user.username
                )

        _dkss_notifications_delivery.notify_mentions(
            mention_text,
            f"/safety/checklist-results/{result_record.id}"
        )

        return _dkss_common.redirect(f"/safety/checklist-results/{result_record.id}")

    selected_notify_users = result.get(
        "notify_users",
        []
    )

    criteria_list = []

    for item in checklist["items"]:
        if item.get("item_type") != "check":
            continue

        criteria = item.get("criteria", "")

        if criteria and criteria not in criteria_list:
            criteria_list.append(criteria)

    selected_vehicle = None

    if result.get("target_vehicle_record_id"):

        vehicle_record = _dkss_models.Vehicle.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            id=result.get("target_vehicle_record_id")
        ).first()

        if vehicle_record:

            number = " ".join(
                value
                for value in [
                    vehicle_record.plate_area or "",
                    vehicle_record.plate_class or "",
                    vehicle_record.plate_kana or "",
                    vehicle_record.plate_number or "",
                ]
                if value
            )

            selected_vehicle = {
                "vehicle_record_id": vehicle_record.id,
                "chassis_number": vehicle_record.chassis_number,
                "number": number,
                "manufacturer": vehicle_record.manufacturer or "",
                "model_code": vehicle_record.model_code or "",
            }
    return _dkss_common.render_template(
        "checklist_result_form.html",
        checklist=checklist,
        index=checklist_record.id,
        result=result,
        result_index=result_record.id,
        record_version=checklist_result_edit_version(result_record),
        mode="edit",
        criteria_list=criteria_list,
        drivers=_dkss_vehicle_readers.drivers_for_current_company(),
        selected_vehicle=selected_vehicle,
        selected_approval_users=[
            approval.get("candidate_usernames", [])
            for approval in result.get("approvals", [])
        ],
        offices=_dkss_master_readers.offices_for_current_company(),
        selected_notify_users=selected_notify_users
    )



def delete_checklist_result(result_index):
    result_record = _dkss_models.ChecklistResult.query.filter_by(
        id=result_index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not result_record:
        return _dkss_common.redirect("/safety/checklists")

    if result_record.status == "承認済み":
        return _dkss_common.redirect(
            _dkss_common.url_for("checklist_result_detail", result_index=result_index)
        )

    result = _dkss_checklist_common.checklist_result_to_dict(result_record)

    if not _dkss_safety_permissions.can_manage_checklist_result(result):
        return _dkss_common.redirect(_dkss_common.url_for("checklist_result_detail", result_index=result_index))

    checklist_id = result_record.checklist_id

    _dkss_audit.add_audit_log(
        action="checklist_result_deleted",
        target_type="checklist_result",
        target_id=result_record.id,
        detail=f"安全チェックリスト結果削除: checklist_id={checklist_id}",
        company_code=result_record.company_code,
    )

    files_to_delete = []

    for answer in _dkss_serialization.safe_json_dict_list(
        result_record.answers_json
    ):
        files_to_delete.extend(
            answer.get("files", [])
        )

    company_code = result_record.company_code

    _dkss_common.db.session.delete(result_record)
    _dkss_common.db.session.commit()

    for filename in files_to_delete:
        filename = _dkss_common.os.path.basename(
            str(filename or "")
        )

        if not filename:
            continue

        still_referenced = False

        patrol_records = _dkss_models.PatrolResult.query.filter_by(
            company_code=company_code
        ).all()

        for patrol in patrol_records:
            patrol_files = _dkss_serialization.safe_json_str_list(
                patrol.files_json
            )

            if filename in patrol_files:
                still_referenced = True
                break

        if still_referenced:
            continue

        if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
            try:
                _dkss_runtime.app.extensions["dkss"]['s3_client'].delete_object(
                    Bucket=_dkss_runtime.app.config['S3_BUCKET_NAME'],
                    Key=(
                        f"uploads/"
                        f"{company_code}/"
                        f"{filename}"
                    )
                )
            except _dkss_common.ClientError:
                _dkss_runtime.app.logger.warning(
                    "安全チェックリスト添付ファイルのS3削除に失敗しました。",
                    exc_info=True
                )
        else:
            safe_filename = _dkss_common.secure_filename(
                filename
            )

            if not safe_filename:
                continue

            file_path = _dkss_common.os.path.join(
                _dkss_runtime.app.config["UPLOAD_FOLDER"],
                company_code,
                safe_filename
            )

            if _dkss_common.os.path.exists(file_path):
                _dkss_common.os.remove(file_path)

    return _dkss_common.redirect(f"/safety/checklists/{checklist_id}")



def vehicle_daily_inspection_entry():
    return _dkss_common.redirect("/vehicle/checklists")



def vehicle_checklists():
    try:
        _dkss_checklist_common.ensure_daily_inspection_checklist()
        _dkss_common.db.session.commit()
    except Exception:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("日常点検の標準様式の登録に失敗しました。")
        _dkss_common.flash("日常点検の標準様式を登録できませんでした。", "error:")
        return _dkss_common.render_template(
            "vehicle_checklists.html",
            checklists=[]
        ), 500

    vehicle_lists = []

    for checklist in _dkss_checklist_common.checklists_for_current_company():
        if (
            checklist["target"] == "車両管理"
            and checklist.get("active", True)
        ):
            vehicle_lists.append(checklist)

    destination = checklist_entry_redirect("vehicle", vehicle_lists)
    if destination is not None:
        return destination
    return _dkss_common.render_template(
        "vehicle_checklists.html",
        checklists=vehicle_lists
    )



def vehicle_checklist_results(index):
    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/vehicle/checklists")

    checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)
    local_now = _dkss_checklist_common.get_user_local_now(
        checklist_record.company_code, _dkss_common.session.get("username")
    )

    if checklist["target"] != "車両管理":
        return _dkss_common.redirect("/vehicle/checklists")

    year = _dkss_common.request.args.get(
        "year",
        str(local_now.year)
    ).strip()

    month = _dkss_common.request.args.get(
        "month",
        str(local_now.month).zfill(2)
    ).strip()

    vehicle_record_id = _dkss_common.request.args.get(
        "vehicle_record_id",
        type=int
    )

    try:
        year_int = int(year)
        month_int = int(month)
    except (TypeError, ValueError):
        return _dkss_http.return_form_errors([
            (
                "表示年月が不正です。",
                None
            )
        ])

    if year_int < 2000 or year_int > 2100:
        return _dkss_http.return_form_errors([
            (
                "表示年が不正です。",
                None
            )
        ])

    if month_int < 1 or month_int > 12:
        return _dkss_http.return_form_errors([
            (
                "表示月が不正です。",
                None
            )
        ])

    year = str(year_int)
    month = str(month_int).zfill(2)

    if vehicle_record_id:
        valid_vehicle = _dkss_models.Vehicle.query.filter_by(
            company_code=checklist_record.company_code,
            id=vehicle_record_id,
            deleted=False
        ).first()

        if not valid_vehicle:
            return _dkss_http.return_form_errors([
                (
                    "対象車両が不正です。",
                    "vehicle_record_id"
                )
            ])

    if checklist.get("frequency_unit") == "year":
        default_active_day = str(local_now.year)
    elif checklist.get("display_type") == "month":
        default_active_day = str(local_now.day).zfill(2)
    else:
        default_active_day = str(local_now.month).zfill(2)

    active_day = _dkss_common.request.args.get("active_day", default_active_day)

    if not active_day:
        active_day = default_active_day

    display_days = []
    input_days = []
    display_weekdays = {}
    week_names = ["月", "火", "水", "木", "金", "土", "日"]

    frequency_unit = checklist.get("frequency_unit", "")
    display_mode = "month"

    if frequency_unit == "year":
        display_mode = "year_list"
        base_year = int(year)

        for y in range(base_year, base_year + 5):
            display_days.append(y)
            display_weekdays[y] = {
                "name": "",
                "is_weekend": False
            }

    elif checklist.get("display_type") == "month":
        display_mode = "day_list"

        import calendar
        last_day = calendar.monthrange(int(year), int(month))[1]

        for day in range(1, last_day + 1):
            display_days.append(day)

            weekday_index = _dkss_common.datetime(int(year), int(month), day).weekday()

            display_weekdays[day] = {
                "name": week_names[weekday_index],
                "is_weekend": weekday_index in [5, 6]
            }

        input_days = list(range(1, last_day + 1))


    else:
        display_mode = "month_list"

        for m in range(1, 13):
            display_days.append(m)
            display_weekdays[m] = {
                "name": "",
                "is_weekend": False
            }

    input_days = list(display_days)

    checklist_periods = []

    if display_mode == "day_list":
        version_history = []

        for version in checklist.get("version_history", []):
            try:
                change_datetime = _dkss_common.datetime.strptime(
                    version.get("effective_until", ""),
                    "%Y-%m-%d %H:%M:%S"
                )
            except (TypeError, ValueError):
                continue

            version_history.append({
                "change_date": change_datetime.date(),
                "snapshot": version.get("snapshot") or {}
            })

        version_history.sort(
            key=lambda version: version["change_date"]
        )

        current_checklist = {
            key: value
            for key, value in checklist.items()
            if key != "version_history"
        }

        current_period = None
        current_checklist_key = None

        for day in display_days:
            target_date = _dkss_common.datetime(
                int(year),
                int(month),
                int(day)
            ).date()

            day_checklist = current_checklist

            for version in version_history:
                if target_date < version["change_date"]:
                    day_checklist = version["snapshot"]
                    break

            checklist_key = _dkss_checklist_common.checklist_revision_key(
                day_checklist
            )

            if checklist_key != current_checklist_key:
                current_period = {
                    "start_day": day,
                    "end_day": day,
                    "checklist": day_checklist
                }

                checklist_periods.append(current_period)
                current_checklist_key = checklist_key

            else:
                current_period["end_day"] = day

    results = []

    query = _dkss_models.VehicleChecklistResult.query.filter_by(
        company_code=checklist_record.company_code,
        checklist_id=checklist_record.id
    )

    if vehicle_record_id:
        query = query.filter_by(
            vehicle_record_id=vehicle_record_id
        )

    for result_record in (query.all() if vehicle_record_id else []):
        result = _dkss_checklist_common.vehicle_checklist_result_to_dict(result_record)

        if display_mode == "year_list":
            if int(result.get("year", 0)) not in [int(d) for d in display_days]:
                continue

        elif display_mode == "month_list":
            if str(result.get("year")) != str(year):
                continue

        else:
            if str(result.get("year")) != str(year):
                continue

            if str(result.get("month")).zfill(2) != str(month).zfill(2):
                continue

        results.append(result)

    if display_mode == "day_list":
        for period in checklist_periods:
            start_day = period["start_day"]
            end_day = period["end_day"]

            period["days"] = [
                day
                for day in display_days
                if start_day <= day <= end_day
            ]

            period["results"] = [
                result
                for result in results
                if start_day
                <= int(result.get("day", 0))
                <= end_day
            ]

    if display_mode == "day_list" and checklist_periods:
        table_sections = []

        results_by_day = {}

        for result in results:
            try:
                result_day = int(result.get("day", 0))
            except (TypeError, ValueError):
                continue

            results_by_day[result_day] = result

        current_section = None
        current_checklist_key = None

        for day in display_days:
            day_result = results_by_day.get(day)
            day_checklist = None

            for period in checklist_periods:
                if (
                    period["start_day"]
                    <= day
                    <= period["end_day"]
                ):
                    day_checklist = period["checklist"]
                    break

            if day_result:
                result_snapshot = (
                    day_result.get("checklist_snapshot") or {}
                )
                if result_snapshot:
                    day_checklist = result_snapshot

            if not day_checklist:
                continue

            if checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
                current_template = next(
                    (
                        item
                        for item in checklist.get("items", [])
                        if item.get("fixed_template_code")
                        == "daily_inspection_truck_trailer"
                    ),
                    {}
                )
                saved_template = next(
                    (
                        item
                        for item in day_checklist.get("items", [])
                        if item.get("fixed_template_code")
                        == "daily_inspection_truck_trailer"
                    ),
                    {}
                )
                current_version = current_template.get(
                    "fixed_template_version",
                    1
                )
                saved_version = saved_template.get(
                    "fixed_template_version",
                    current_version
                )

                if str(saved_version) == str(current_version):
                    day_checklist = checklist

            checklist_key = _dkss_checklist_common.checklist_revision_key(
                day_checklist
            )

            if checklist_key != current_checklist_key:
                current_section = {
                    "start_day": day,
                    "end_day": day,
                    "days": [day],
                    "results": [],
                    "checklist": day_checklist
                }

                table_sections.append(current_section)
                current_checklist_key = checklist_key

            else:
                current_section["end_day"] = day
                current_section["days"].append(day)

            if day_result:
                current_section["results"].append(day_result)

    else:
        table_sections = [{
            "checklist": checklist,
            "days": display_days,
            "results": results
        }]

    selected_notify_users = []
    active_result = None

    for result in results:
        if display_mode == "year_list":
            is_active_result = (
                str(result.get("year")) == str(active_day)
            )

        elif display_mode == "month_list":
            is_active_result = (
                str(result.get("month")).zfill(2)
                == str(active_day).zfill(2)
            )

        else:
            is_active_result = (
                str(result.get("day")).zfill(2)
                == str(active_day).zfill(2)
            )

        if is_active_result:
            active_result = result
            selected_notify_users = result.get("notify_users", [])
            break

    if active_result:
        snapshot = active_result.get("checklist_snapshot") or {}

        if snapshot:
            checklist = snapshot

    selected_reminder_notify_users = (
        _dkss_checklist_notifications.get_vehicle_checklist_notify_users(
            checklist_record.company_code,
            checklist_record.id,
            vehicle_record_id
        )
        if vehicle_record_id
        else []
    )

    valid_vehicle_ids = {
        vehicle.id
        for vehicle in _dkss_models.Vehicle.query.filter_by(
            company_code=checklist_record.company_code,
            deleted=False
        ).all()
    }

    current_driver = _dkss_models.Driver.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        employee_id=_dkss_common.session.get("username")
    ).first()

    usage_vehicle_ids = [
        int(vehicle_record_id)
        for vehicle_record_id in (
            _dkss_serialization.safe_json_str_list(current_driver.vehicles_json)
            if current_driver
            else []
        )
        if vehicle_record_id.isdigit()
        and int(vehicle_record_id) in valid_vehicle_ids
    ]

    usage_vehicles = _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.company_code == checklist_record.company_code,
        _dkss_models.Vehicle.deleted == False,
        _dkss_models.Vehicle.id.in_(usage_vehicle_ids)
    ).all() if usage_vehicle_ids else []

    selected_vehicle = None

    if vehicle_record_id:

        vehicle_record = valid_vehicle

        if vehicle_record:

            number = " ".join(
                value
                for value in [
                    vehicle_record.plate_area or "",
                    vehicle_record.plate_class or "",
                    vehicle_record.plate_kana or "",
                    vehicle_record.plate_number or "",
                ]
                if value
            )

            selected_vehicle = {
                "vehicle_record_id": vehicle_record.id,
                "chassis_number": vehicle_record.chassis_number,
                "number": number,
                "manufacturer": vehicle_record.manufacturer or "",
                "model_code": vehicle_record.model_code or "",
            }

    checklist_events = []

    if active_result and vehicle_record_id:
        checklist_event_records = (
            _dkss_models.ChecklistEvent.query.filter_by(
                company_code=checklist_record.company_code,
                result_type="vehicle",
                result_id=active_result["id"]
            )
            .order_by(_dkss_models.ChecklistEvent.id.asc())
            .all()
        )

        for event in checklist_event_records:
            checklist_events.append({
                "event_type": event.event_type,
                "actor_username": event.actor_username,
                "actor_name": event.actor_name,
                "created_at": event.created_at,
                "detail": _dkss_serialization.safe_json_dict(event.detail_json),
            })

    vehicle_today = None
    if (
        vehicle_record_id
        and checklist.get("fixed_template_code")
        == "daily_inspection_truck_trailer"
    ):
        local_today = _dkss_checklist_common.get_user_local_now(
            checklist_record.company_code,
            _dkss_common.session.get("username")
        )
        vehicle_today = {
            "label": local_today.strftime("%Y/%m/%d"),
            "is_selected": (
                int(year) == local_today.year
                and int(month) == local_today.month
                and int(active_day) == local_today.day
            ),
            "url": _dkss_common.url_for(
                "vehicle_checklist_results",
                index=checklist_record.id,
                vehicle_record_id=vehicle_record_id,
                year=str(local_today.year),
                month=local_today.strftime("%m"),
                active_day=local_today.strftime("%d")
            ),
        }

    other_vehicle_inspection_defects = []

    if checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
        other_vehicle_inspection_defects = [
            entry
            for entry in get_vehicle_open_inspection_defects(
                checklist_record.company_code,
                vehicle_record_id
            )
            if not active_result
            or entry["result_id"] != active_result["id"]
        ]

    vehicle_response_notify_names = []
    if active_result and checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
        response_judgment = active_result.get("operation_judgment", {})
        target_usernames = set(response_judgment.get("requested_usernames") or [])
        inspector_username = active_result.get("checked_by_username")

        if not target_usernames and inspector_username:
            inspector = _dkss_models.User.query.filter_by(
                company_code=checklist_record.company_code,
                username=inspector_username
            ).first()
            if inspector and inspector.office:
                target_usernames.update(
                    user.username
                    for user in _dkss_models.User.query.filter_by(
                        company_code=checklist_record.company_code,
                        office=inspector.office,
                        role="admin"
                    ).all()
                )

        if inspector_username:
            target_usernames.add(inspector_username)

        if target_usernames:
            notify_users = _dkss_models.User.query.filter_by(
                company_code=checklist_record.company_code
            ).filter(_dkss_models.User.username.in_(target_usernames)).all()
            vehicle_response_notify_names = [
                (user.last_name or "") + (user.first_name or "") or user.username
                for user in sorted(notify_users, key=lambda user: user.username)
            ]

    vehicle_judgment_names = []
    if active_result and checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
        assigned_usernames = set(
            active_result.get("operation_judgment", {}).get("requested_usernames") or []
        )
        if assigned_usernames:
            vehicle_judgment_names = [
                (user.last_name or "") + (user.first_name or "") or user.username
                for user in sorted(notify_users, key=lambda user: user.username)
                if user.username in assigned_usernames and user.role == "admin"
            ]

    vehicle_operation_managers = []
    if active_result and checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
        vehicle_operation_managers = [
            {
                "username": user.username,
                "name": (user.last_name or "") + (user.first_name or "") or user.username,
                "office": user.office or "",
            }
            for user in _dkss_models.User.query.filter_by(
                company_code=checklist_record.company_code,
                role="admin"
            ).all()
        ]
        vehicle_operation_managers.sort(
            key=lambda user: (user["name"], user["username"])
        )

    return _dkss_common.render_template(
        "vehicle_checklist_results.html",
        checklist_navigation=checklist_result_navigation(checklist_record, "vehicle"),
        vehicle_operation_managers=vehicle_operation_managers,
        vehicle_judgment_names=vehicle_judgment_names,
        vehicle_response_notify_names=vehicle_response_notify_names,
        checklist=checklist,
        checklist_index=checklist_record.id,
        results=results,
        active_result=active_result,
        checklist_events=checklist_events,
        other_vehicle_inspection_defects=other_vehicle_inspection_defects,
        vehicle_today=vehicle_today,
        vehicle_operation_basis=(
            get_vehicle_operation_basis(
                checklist_record.company_code,
                vehicle_record_id
            )
            if checklist.get("fixed_template_code")
            == "daily_inspection_truck_trailer"
            else ""
        ),
        selected_notify_users=selected_notify_users,
        selected_reminder_notify_users=selected_reminder_notify_users,
        selected_vehicle=selected_vehicle,
        usage_vehicle_ids=usage_vehicle_ids,
        usage_vehicles=usage_vehicles,
        year=year,
        month=month,
        vehicle_record_id=vehicle_record_id,
        active_day=active_day,
        display_days=display_days,
        input_days=input_days,
        display_weekdays=display_weekdays,
        display_mode=display_mode,
        checklist_periods=checklist_periods,
        table_sections=table_sections
    )



def save_vehicle_checklist_reminder_notify_users(checklist_index):
    company_code = _dkss_common.session.get("company_code")
    if _dkss_common.session.get("role") not in ["admin", "itc"]:
        return _dkss_http.return_form_errors([
            (
                "通知先設定を変更する権限がありません。",
                ""
            )
        ], status_code=403)

    vehicle_record_id = _dkss_common.request.form.get(
        "vehicle_record_id",
        type=int
    )

    notify_usernames = [
        username.strip()
        for username in _dkss_common.request.form.getlist(
            "reminder_notify_users"
        )
        if username.strip()
    ]

    if len(notify_usernames) > 500:
        return _dkss_http.return_form_errors([
            (
                "通知先ユーザー数が多すぎます。",
                "reminder_notify_user_search"
            )
        ])

    # チェックリスト検証

    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=checklist_index,
        company_code=company_code,
        active=True
    ).first()

    if not checklist_record:
        return _dkss_http.return_form_errors([
            (
                "チェックリストが不正です。",
                ""
            )
        ], status_code=404)

    if checklist_record.target != "車両管理":
        return _dkss_http.return_form_errors([
            (
                "チェックリスト種別が不正です。",
                ""
            )
        ])

    # 車両検証

    if not vehicle_record_id:
        return _dkss_http.return_form_errors([
            (
                "車両を選択してください。",
                "vehicle_record_id"
            )
        ])

    vehicle = _dkss_models.Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return _dkss_http.return_form_errors([
            (
                "車両が不正です。",
                "vehicle_record_id"
            )
        ])

    # 通知先ユーザー検証

    valid_users = {
        user.username: user
        for user in _dkss_models.User.query.filter_by(
            company_code=company_code
        ).all()
        if user.username
    }

    for username in notify_usernames:
        if username not in valid_users:
            return _dkss_http.return_form_errors([
                (
                    "通知先ユーザーが不正です。",
                    "reminder_notify_user_search"
                )
            ])

    # 重複除去
    notify_usernames = list(
        dict.fromkeys(notify_usernames)
    )

    # 設定保存

    setting = _dkss_models.VehicleChecklistNotifySetting.query.filter_by(
        company_code=company_code,
        checklist_id=checklist_record.id,
        vehicle_record_id=vehicle_record_id
    ).first()

    if not setting:
        setting = _dkss_models.VehicleChecklistNotifySetting(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id
        )

        _dkss_common.db.session.add(setting)

    setting.notify_users_json = _dkss_common.json.dumps(
        notify_usernames,
        ensure_ascii=False
    )

    _dkss_common.db.session.commit()

    return {
        "ok": True
    }



def test_vehicle_checklist_reminders():

    if _dkss_common.session.get("role") not in ["admin", "itc"]:
        return {"ok": False}, 403

    _dkss_checklist_notifications.send_vehicle_checklist_reminders(
        _dkss_common.session.get("company_code")
    )

    return {"ok": True}



def test_email_notification():
    current_user = _dkss_models.User.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        username=_dkss_common.session.get("username")
    ).first()

    if not current_user:
        return {
            "ok": False,
            "message": "ユーザーが見つかりません。"
        }, 404

    if not current_user.email_notify_enabled:
        return {
            "ok": False,
            "message": "メール通知がOFFです。"
        }, 400

    if not current_user.email_address:
        return {
            "ok": False,
            "message": "メールアドレスが未設定です。"
        }, 400

    sent = _dkss_notifications_delivery.send_email_notification(
        current_user,
        "メール通知テスト",
        "通知メールの送信テストです。",
        "/settings"
    )

    if not sent:
        return {
            "ok": False,
            "message": "メール送信に失敗しました。"
        }, 500

    return {
        "ok": True,
        "message": "メールを送信しました。"
    }



def save_vehicle_inspection_repair(result_index, defect_no):
    lock_error = lock_vehicle_inspection_updates(
        _dkss_common.session.get("company_code"),
        result_index=result_index
    )
    if lock_error is not None:
        return lock_error
    company_code = _dkss_common.session.get("company_code")
    current_user = _dkss_models.User.query.filter_by(
        company_code=company_code,
        username=_dkss_common.session.get("username")
    ).first()
    if not current_user or current_user.role not in {"admin", "user"}:
        return _dkss_http.return_form_errors([("整備内容を登録する権限がありません。", "")], 403)

    result_record = _dkss_models.VehicleChecklistResult.query.filter_by(
        id=result_index,
        company_code=company_code
    ).with_for_update().first()
    if not result_record:
        return _dkss_http.return_form_errors([("対象の点検記録がありません。", "")], 404)

    snapshot = _dkss_serialization.safe_json_dict(result_record.checklist_snapshot_json)
    if not any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in snapshot.get("items", [])
    ):
        return _dkss_http.return_form_errors([("不具合対応の対象外の様式です。", "")], 400)

    previous_json = result_record.operation_judgment_json
    previous = _dkss_serialization.safe_json_dict(previous_json)
    defects = [dict(item) for item in previous.get("defects", [])]
    defect = next(
        (item for item in defects if item.get("defect_no") == defect_no),
        None
    )
    if not defect:
        return _dkss_http.return_form_errors([("対象の不具合がありません。", "")], 404)

    try:
        expected_version = int(_dkss_common.request.form.get("judgment_version", ""))
        current_version = int(previous.get("version") or 0)
    except (TypeError, ValueError):
        return _dkss_http.return_form_errors([("再読み込みして不具合の状態を確認してください。", "")], 409)

    if expected_version != current_version:
        return _dkss_http.return_form_errors([("点検または不具合対応が更新されています。再読み込みしてください。", "")], 409)

    is_recheck = _dkss_common.request.form.get("recheck_result") is not None

    if is_recheck:
        recheck_result = _dkss_common.request.form.get("recheck_result", "").strip()
        if defect.get("status") != "再確認待ち":
            return _dkss_http.return_form_errors([
                ("再確認待ちの不具合を選択してください。", "")
            ], 409)

        if recheck_result not in {"異常なし", "異常あり"}:
            return _dkss_http.return_form_errors([
                ("再確認結果を選択してください。", f"recheck_result_{defect_no}")
            ])

        next_status = (
            "解消"
            if recheck_result == "異常なし"
            else "対応待ち"
        )
    else:
        next_status = _dkss_common.request.form.get("repair_status", "").strip()
        if (
            defect.get("status") not in {"対応待ち", "整備中"}
            or next_status not in {"整備中", "再確認待ち"}
        ):
            return _dkss_http.return_form_errors([
                ("現在の状態ではこの整備操作を行えません。", "")
            ], 409)

    note = _dkss_common.request.form.get("repair_note", "").strip()
    if not note or len(note) > 5000:
        return _dkss_http.return_form_errors([
            ("整備内容を1〜5000文字で入力してください。", f"repair_note_{defect_no}")
        ])

    local_now = _dkss_checklist_common.get_user_local_now(company_code, current_user.username)
    date_only = "repair_performed_date" in _dkss_common.request.form
    try:
        if date_only:
            performed_at = _dkss_common.datetime.strptime(
                _dkss_common.request.form.get("repair_performed_date", ""),
                "%Y-%m-%d"
            )
        else:
            performed_at = _dkss_common.datetime.strptime(
                _dkss_common.request.form.get("repair_performed_at", ""),
                "%Y-%m-%dT%H:%M"
            )
    except ValueError:
        return _dkss_http.return_form_errors([
            ("実施日を入力してください。", f"repair_performed_at_{defect_no}")
        ])

    if performed_at > local_now.replace(tzinfo=None):
        return _dkss_http.return_form_errors([
            ("実施日に未来の日付は指定できません。", f"repair_performed_at_{defect_no}")
        ])

    repair = {
        "status": next_status,
        "note": note,
        "performed_by": (current_user.last_name or "") + (current_user.first_name or ""),
        "performed_by_username": current_user.username,
        "performed_at": performed_at.strftime(
            "%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M"
        ),
        "recorded_at": local_now.strftime("%Y-%m-%d %H:%M:%S"),
        "notification_created_at": local_now.astimezone(
            _dkss_common.ZoneInfo("UTC")
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": str(local_now.tzinfo),
    }
    previous_defect = dict(defect)
    defect["status"] = next_status

    if is_recheck:
        try:
            previous_repair = defect.get("repair") or {}
            repair_completed_at = _dkss_common.datetime.fromisoformat(
                previous_repair.get("performed_at", "")
            ).replace(
                tzinfo=_dkss_common.ZoneInfo(
                    previous_repair.get("timezone") or "Asia/Tokyo"
                )
            )
        except (TypeError, ValueError, KeyError):
            return _dkss_http.return_form_errors([
                ("整備実施日時を確認できません。整備記録を確認してください。", "")
            ], 409)

        if date_only:
            recheck_before_repair = (
                performed_at.date()
                < repair_completed_at.astimezone(local_now.tzinfo).date()
            )
        else:
            recheck_before_repair = (
                performed_at.replace(tzinfo=local_now.tzinfo)
                < repair_completed_at
            )

        if recheck_before_repair:
            return _dkss_http.return_form_errors([
                (
                    "再確認日は整備実施日以降を指定してください。",
                    f"repair_performed_at_{defect_no}"
                )
            ])

        repair["result"] = recheck_result
        defect["recheck"] = repair
        defect["rechecked_answer"] = next(
            (
                dict(answer)
                for answer in _dkss_serialization.safe_json_dict_list(result_record.answers_json)
                if str(answer.get("item_no", ""))
                == str(defect.get("item_no", ""))
            ),
            {}
        )
    else:
        defect["repair"] = repair

    judgment = {
        **previous,
        "defects": defects,
        "status": "未判定",
        "version": current_version + 1,
    }
    for key in (
        "reason", "judged_by", "judged_by_username",
        "judged_at", "authority_role", "authority_confirmed",
        "checks_confirmed", "checks_evidence"
    ):
        judgment.pop(key, None)

    if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
        return _dkss_common.jsonify({"success": True})

    try:
        if not is_recheck:
            _dkss_vehicle_karte.carry_inspection_repair_to_maintenance(
                result_record, defect_no, previous_defect, repair, current_user,
            )
        notification_targets = _dkss_vehicle_karte.persist_vehicle_inspection_repair(
            result_record, company_code, current_user, previous_json, judgment,
            next_status, repair, previous_defect, defect, previous, is_recheck,
        )
        _dkss_common.db.session.commit()
    except ValueError:
        _dkss_common.db.session.rollback()
        return _dkss_http.return_form_errors([("不具合対応が更新されています。再読み込みしてください。", "")], 409)
    except Exception:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("日常点検の整備内容の保存に失敗しました。")
        return _dkss_http.return_form_errors([
            ("整備内容を保存できませんでした。もう一度お試しください。", "")
        ], 500)

    dispatch_vehicle_defect_notifications(result_record)

    for target_user, notification in notification_targets:
        try:
            _dkss_notifications_delivery.dispatch_external_notification(
                target_user,
                notification.title,
                notification.message,
                notification.link,
                notification_id=notification.id
            )
        except Exception:
            _dkss_runtime.app.logger.exception("不具合対応の外部通知に失敗しました。")

    from urllib.parse import parse_qsl, urlencode, urlunparse

    return_year = result_record.year
    return_month = result_record.month
    return_day = result_record.day

    try:
        return_date = _dkss_common.datetime(
            int(_dkss_common.request.form.get("vehicle_return_year", "")),
            int(_dkss_common.request.form.get("vehicle_return_month", "")),
            int(_dkss_common.request.form.get("vehicle_return_day", ""))
        )
        if not 2000 <= return_date.year <= 2100:
            raise ValueError("戻り先の年が範囲外です")

        return_year = str(return_date.year)
        return_month = return_date.strftime("%m")
        return_day = return_date.strftime("%d")
    except (TypeError, ValueError):
        pass

    destination = _dkss_common.url_for(
        "vehicle_checklist_results",
        index=result_record.checklist_id,
        vehicle_record_id=result_record.vehicle_record_id,
        year=return_year,
        month=return_month,
        active_day=return_day
    )
    target = "vehicle-flow-judgment"
    saved_result_id = result_record.id
    saved_defect_no = defect.get("defect_no")
    saved_item_no = int(defect.get("item_no", 0)) + 1
    saved_date = (
        f"{result_record.year}/"
        f"{str(result_record.month).zfill(2)}/"
        f"{str(result_record.day).zfill(2)}"
    )

    try:
        pending_defects = get_vehicle_open_inspection_defects(
            company_code,
            result_record.vehicle_record_id
        )
        next_entry = next(
            (
                entry for entry in pending_defects
                if entry.get("result_id") == saved_result_id
                and str(entry.get("defect", {}).get("defect_no"))
                == str(saved_defect_no)
            ),
            pending_defects[0] if pending_defects else None
        )
        if next_entry:
            destination = next_entry["link"]
            next_defect_no = next_entry.get("defect", {}).get("defect_no")
            target = (
                f"vehicle-flow-defect-{next_entry['result_id']}-{next_defect_no}"
                if next_defect_no is not None else "vehicle-flow-overview"
            )
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("保存後の不具合対応の移動先を取得できませんでした。")
        target = f"vehicle-flow-defect-{saved_result_id}-{saved_defect_no}"

    parts = _dkss_common.urlparse(destination)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.update({
        "vehicle_saved": "recheck" if is_recheck else "repair",
        "vehicle_saved_item": str(saved_item_no),
        "vehicle_saved_date": saved_date,
        "vehicle_return_year": str(return_year),
        "vehicle_return_month": str(return_month).zfill(2),
        "vehicle_return_day": str(return_day).zfill(2),
    })
    redirect_url = urlunparse(parts._replace(
        query=urlencode(params),
        fragment=target
    ))
    if _dkss_common.request.headers.get("X-DKSS-Final-Submit") == "1":
        return _dkss_common.jsonify({"redirect_url": redirect_url})
    return _dkss_common.redirect(redirect_url)



def save_vehicle_operation_judgment(result_index):
    lock_error = lock_vehicle_inspection_updates(
        _dkss_common.session.get("company_code"),
        result_index=result_index
    )
    if lock_error is not None:
        return lock_error
    result_record = (
        _dkss_models.VehicleChecklistResult.query.filter_by(
            id=result_index,
            company_code=_dkss_common.session.get("company_code")
        ).with_for_update().first()
    )
    if not result_record:
        return _dkss_http.return_form_errors([("対象の点検記録がありません。", "")], 404)

    snapshot = _dkss_serialization.safe_json_dict(result_record.checklist_snapshot_json)
    if not any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in snapshot.get("items", [])
    ):
        return _dkss_http.return_form_errors([("運行判断の対象外の様式です。", "")], 400)

    if result_record.status not in {"承認待ち", "承認済み", "点検完了"}:
        return _dkss_http.return_form_errors([("点検完了後に運行判断を記録してください。", "")], 409)

    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=result_record.vehicle_record_id,
        company_code=result_record.company_code,
        deleted=False
    ).first()
    if not vehicle:
        return _dkss_http.return_form_errors([("対象車両を確認できません。", "")], 409)

    previous_json = result_record.operation_judgment_json
    previous = _dkss_serialization.safe_json_dict(previous_json)
    current_user = _dkss_models.User.query.filter_by(
        company_code=result_record.company_code,
        username=_dkss_common.session.get("username")
    ).first()
    if _dkss_common.request.form.get("action") == "assign_operation_manager":
        if not current_user or not (
            current_user.role == "admin"
            or (
                current_user.role == "user"
                and current_user.username == result_record.checked_by_username
            )
        ):
            return _dkss_http.return_form_errors([("整備管理者・補助者の設定は、点検者または管理者が行ってください。", "")], 403)

        if previous.get("requested_usernames") or previous.get("status") not in {None, "", "未判定"}:
            return _dkss_http.return_form_errors([("整備管理者・補助者または判断結果が既に登録されています。再読み込みしてください。", "")], 409)

        try:
            expected_version = int(_dkss_common.request.form.get("judgment_version", ""))
            current_version = int(previous.get("version") or 0)
        except (TypeError, ValueError):
            return _dkss_http.return_form_errors([("画面を再読み込みしてください。", "")], 409)

        if expected_version != current_version:
            return _dkss_http.return_form_errors([("記録が更新されています。再読み込みしてください。", "")], 409)

        manager = _dkss_models.User.query.filter_by(
            company_code=result_record.company_code,
            username=_dkss_common.request.form.get("manager_username", "").strip(),
            role="admin"
        ).first()
        if not manager:
            return _dkss_http.return_form_errors([("整備管理者・補助者を選択してください。", "manager_username")], 400)

        if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
            return _dkss_common.jsonify({"success": True})

        judgment = dict(previous)
        judgment["requested_usernames"] = [manager.username]
        judgment["version"] = current_version + 1
        created_at = _dkss_checklist_common.get_user_local_now(
            result_record.company_code, current_user.username
        ).strftime("%Y-%m-%d %H:%M:%S")
        manager_name = (
            (manager.last_name or "") + (manager.first_name or "")
            or manager.username
        )
        notification_link = _dkss_common.url_for(
            "vehicle_checklist_results",
            index=result_record.checklist_id,
            vehicle_record_id=result_record.vehicle_record_id,
            year=result_record.year,
            month=result_record.month,
            active_day=result_record.day
        ) + "#vehicle-flow-judgment"
        notification_title = "運行判断の依頼"
        notification_message = (
            f"点検日：{result_record.year}/{result_record.month}/{result_record.day}\n"
            "整備管理者として運行判断を依頼されました。点検結果と不具合の対応状況を確認し、運行可否を登録してください。"
        )

        try:
            updated = _dkss_models.VehicleChecklistResult.query.filter_by(
                id=result_record.id,
                company_code=result_record.company_code,
                operation_judgment_json=previous_json
            ).update({
                "operation_judgment_json": _dkss_common.json.dumps(judgment, ensure_ascii=False)
            }, synchronize_session=False)

            if updated != 1:
                _dkss_common.db.session.rollback()
                return _dkss_http.return_form_errors([("記録が更新されています。再読み込みしてください。", "")], 409)

            _dkss_common.db.session.add(_dkss_models.ChecklistEvent(
                company_code=result_record.company_code,
                result_type="vehicle",
                result_id=result_record.id,
                event_type="運行管理者設定",
                actor_username=current_user.username,
                actor_name=(
                    (current_user.last_name or "") + (current_user.first_name or "")
                    or current_user.username
                ),
                created_at=created_at,
                detail_json=_dkss_common.json.dumps({"運行管理者": manager_name}, ensure_ascii=False)
            ))
            notification = _dkss_models.Notification(
                company_code=result_record.company_code,
                target_user=manager_name,
                target_username=manager.username,
                owner_identity=manager.account_identity,
                title=notification_title,
                message=notification_message,
                link=notification_link,
                files_json="[]",
                workflow_context_json=_dkss_common.json.dumps(
                    _dkss_notifications_delivery.build_notification_workflow_context(
                        result_record,
                        "vehicle",
                        "operation_judgment"
                    ),
                    ensure_ascii=False
                ),
                read=False,
                created_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC")).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            )
            _dkss_common.db.session.add(notification)
            _dkss_common.db.session.commit()
        except Exception:
            _dkss_common.db.session.rollback()
            _dkss_runtime.app.logger.exception("運行管理者の設定に失敗しました。")
            return _dkss_http.return_form_errors([("整備管理者・補助者を設定できませんでした。", "")], 500)

        try:
            _dkss_notifications_delivery.dispatch_external_notification(
                manager,
                notification.title,
                notification.message,
                notification.link,
                notification_id=notification.id
            )
        except Exception:
            _dkss_runtime.app.logger.exception("運行管理者設定の外部通知に失敗しました。")

        return _dkss_common.redirect(notification_link)

    if (
        not current_user
        or current_user.role != "admin"
        or current_user.username not in previous.get("requested_usernames", [])
    ):
        return _dkss_http.return_form_errors([("選択された運行判断の担当者が操作してください。", "")], 403)

    decision = _dkss_common.request.form.get("decision", "").strip()
    reason = _dkss_common.request.form.get("reason", "").strip()
    authority_role = _dkss_common.request.form.get("authority_role", "").strip()

    if decision not in {"運行可", "運行不可", "判定保留"}:
        return _dkss_http.return_form_errors([
            ("運行可・運行不可・判定保留を選択してください。", "decision")
        ])
    if len(reason) > 5000:
        return _dkss_http.return_form_errors([("補足・判断理由は5000文字以内で入力してください。", "reason")])
    if decision in {"運行不可", "判定保留"} and not reason:
        return _dkss_http.return_form_errors([("運行不可・判断保留の場合は理由を入力してください。", "reason")])
    if (
        authority_role not in {"整備管理者", "補助者"}
        or _dkss_common.request.form.get("authority_confirmed") != "1"
    ):
        return _dkss_http.return_form_errors([("対象車両の運行判断を行う権限があることを確認してください。", "authority_confirmed")], 403)

    try:
        expected_version = int(_dkss_common.request.form.get("judgment_version", ""))
        current_version = int(previous.get("version", 0))
        expected_answers = _dkss_common.json.loads(_dkss_common.request.form.get("expected_answers", ""))
        expected_snapshot = _dkss_common.json.loads(_dkss_common.request.form.get("expected_snapshot", ""))
    except (TypeError, ValueError):
        return _dkss_http.return_form_errors([("画面を再読み込みして、点検内容を確認してください。", "")], 409)

    if (
        expected_version != current_version
        or expected_answers != _dkss_serialization.safe_json_dict_list(result_record.answers_json)
        or expected_snapshot != snapshot
    ):
        return _dkss_http.return_form_errors([("点検内容または運行判断が更新されています。再読み込みして確認してください。", "")], 409)

    approval_items = [
        item for item in snapshot.get("items", [])
        if item.get("item_type") == "approval"
        or (
            item.get("item_type") == "operation_judgment"
            and item.get("item_code") == "footer_30"
        )
    ]
    previous_approvals_json = result_record.approvals_json
    approvals = _dkss_serialization.safe_json_dict_list(previous_approvals_json)
    if len(approval_items) != 1 or len(approvals) > 1:
        return _dkss_http.return_form_errors([("標準点検表の確認欄を確認してください。", "")], 409)
    if not approvals:
        approvals = [{
            "label": approval_items[0].get("approval_label", "整備管理者（又は補助者）"),
            "allow_general": False,
            "candidate_usernames": list(previous.get("requested_usernames", [])),
            "approved_by": "",
            "approved_by_username": "",
            "approved_date": "",
        }]

    checks_evidence = ""

    if decision == "運行可":
        if _dkss_common.request.form.get("checks_confirmed") != "1":
            return _dkss_http.return_form_errors([
                ("必要な点検・確認の実施を確認してください。", "checks_confirmed")
            ])

        if _dkss_common.request.form.get("vehicle_operation_basis", "") != get_vehicle_operation_basis(
            result_record.company_code,
            result_record.vehicle_record_id
        ):
            return _dkss_http.return_form_errors([
                ("この車両の点検・不具合対応が更新されています。再読み込みして確認してください。", "")
            ], 409)

        answers_by_no = {
            str(answer.get("item_no", "")): answer
            for answer in _dkss_serialization.safe_json_dict_list(result_record.answers_json)
        }
        check_items = [
            item
            for item in snapshot.get("items", [])
            if item.get("item_type") == "check"
        ]

        for item_no, item in enumerate(check_items):
            if item.get("answer_required") and not str(
                answers_by_no.get(str(item_no), {}).get("value") or ""
            ).strip():
                return _dkss_http.return_form_errors([
                    ("必須の点検項目に未回答があります。確認してから判断してください。", "decision")
                ])

    operation_notify_usernames = []
    operation_notify_targets = []

    if decision == "運行不可":
        submitted_usernames = [
            username.strip()
            for username in _dkss_common.request.form.getlist(
                "approval_notify_users_operation"
            )
            if username.strip()
        ]

        if len(submitted_usernames) > 500:
            return _dkss_http.return_form_errors([
                (
                    "運行管理者の通知先は500人以内で選択してください。",
                    "operation_notify_users"
                )
            ], 400)

        operation_notify_usernames = list(
            dict.fromkeys(submitted_usernames)
        )

        if operation_notify_usernames:
            operation_notify_targets = _dkss_models.User.query.filter(
                _dkss_models.User.company_code == result_record.company_code,
                _dkss_models.User.role == "admin",
                _dkss_models.User.username.in_(operation_notify_usernames)
            ).all()

            valid_usernames = {
                user.username
                for user in operation_notify_targets
            }

            if any(
                username not in valid_usernames
                for username in operation_notify_usernames
            ):
                return _dkss_http.return_form_errors([
                    (
                        "通知先は同じ会社の管理者ユーザーから選択してください。",
                        "operation_notify_users"
                    )
                ], 400)

    if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
        return _dkss_common.jsonify({"success": True})

    judged_at = _dkss_checklist_common.get_user_local_now(
        result_record.company_code,
        current_user.username
    ).strftime("%Y-%m-%d %H:%M:%S")
    judgment = {
        **previous,
        "status": decision,
        "reason": reason,
        "judged_by": (current_user.last_name or "") + (current_user.first_name or ""),
        "judged_by_username": current_user.username,
        "judged_at": judged_at,
        "authority_role": authority_role,
        "authority_confirmed": True,
        "checks_confirmed": decision == "運行可",
        "checks_evidence": checks_evidence,
        "operation_notify_usernames": operation_notify_usernames,
        "version": current_version + 1
    }

    approval = approvals[0]
    approval_added = not (
        approval.get("approved_by") or approval.get("approved_by_username")
    )
    if approval_added:
        approval["approved_by"] = judgment["judged_by"]
        approval["approved_by_username"] = current_user.username
        approval["approved_date"] = judged_at[:16]

    try:
        updated = _dkss_models.VehicleChecklistResult.query.filter_by(
            id=result_record.id,
            company_code=result_record.company_code,
            operation_judgment_json=previous_json,
            approvals_json=previous_approvals_json,
            answers_json=result_record.answers_json,
            checklist_snapshot_json=result_record.checklist_snapshot_json,
            status=result_record.status
        ).update(
            {
                "operation_judgment_json": _dkss_common.json.dumps(judgment, ensure_ascii=False),
                "approvals_json": _dkss_common.json.dumps(approvals, ensure_ascii=False),
                "status": "承認済み",
                "approved_by": approval.get("approved_by", ""),
                "approved_by_username": approval.get("approved_by_username", ""),
                "approved_date": approval.get("approved_date", ""),
                "reject_reason": "",
            },
            synchronize_session=False
        )
        if updated != 1:
            _dkss_common.db.session.rollback()
            return _dkss_http.return_form_errors([("点検記録が更新されています。再読み込みして確認してください。", "")], 409)

        judgment_event = _dkss_models.ChecklistEvent(
            company_code=result_record.company_code,
            result_type="vehicle",
            result_id=result_record.id,
            event_type="運行判断",
            actor_username=current_user.username,
            actor_name=judgment["judged_by"],
            detail_json=_dkss_common.json.dumps(
                {"previous_judgment": previous, "judgment": judgment},
                ensure_ascii=False
            ),
            created_at=judged_at
        )
        _dkss_common.db.session.add(judgment_event)
        _dkss_common.db.session.flush()

        notification_target = None
        notification_title = "車両の運行判断：" + decision
        notification_message = (
            f"点検日：{result_record.year}-{result_record.month}-{result_record.day}\n"
            f"判断：{decision}\n理由：{reason}"
        )
        notification_link = _dkss_common.url_for(
            "vehicle_checklist_results",
            index=result_record.checklist_id,
            vehicle_record_id=result_record.vehicle_record_id,
            year=result_record.year,
            month=result_record.month,
            active_day=result_record.day
        ) + "#vehicle-flow-judgment"

        if result_record.checked_by_username:
            notification_target = _dkss_models.User.query.filter_by(
                company_code=result_record.company_code,
                username=result_record.checked_by_username
            ).first()

        if notification_target:
            notification = _dkss_models.Notification(
                company_code=result_record.company_code,
                target_user=(notification_target.last_name or "")
                + (notification_target.first_name or ""),
                target_username=notification_target.username,
                owner_identity=notification_target.account_identity,
                title=notification_title,
                message=notification_message,
                link=notification_link,
                files_json="[]",
                read=False,
                created_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC")).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                workflow_context_json=_dkss_common.json.dumps({
                    "result_type": "vehicle",
                    "result_id": result_record.id,
                    "event_id": judgment_event.id,
                    "action": "operation_result",
                }, ensure_ascii=False)
            )
            _dkss_common.db.session.add(notification)
        operation_notifications = []

        for target in operation_notify_targets:
            if (
                notification_target
                and target.username == notification_target.username
            ):
                continue

            operation_notification = _dkss_models.Notification(
                company_code=result_record.company_code,
                target_user=(
                    (target.last_name or "") + (target.first_name or "")
                    or target.username
                ),
                target_username=target.username,
                owner_identity=target.account_identity,
                title=notification_title,
                message=notification_message,
                link=notification_link,
                files_json="[]",
                read=False,
                created_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC")).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                workflow_context_json=_dkss_common.json.dumps({
                    "result_type": "vehicle",
                    "result_id": result_record.id,
                    "event_id": judgment_event.id,
                    "action": "operation_result",
                }, ensure_ascii=False)
            )
            _dkss_common.db.session.add(operation_notification)
            operation_notifications.append(
                (target, operation_notification)
            )

        _dkss_common.db.session.commit()
    except Exception:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("運行判断の保存に失敗しました。")
        return _dkss_http.return_form_errors([("運行判断を保存できませんでした。もう一度お試しください。", "")], 500)

    if notification_target:
        try:
            _dkss_notifications_delivery.dispatch_external_notification(
                notification_target,
                notification.title,
                notification.message,
                notification.link,
                notification_id=notification.id
            )
        except Exception:
            _dkss_runtime.app.logger.exception("運行判断の外部通知に失敗しました。")

    for target, operation_notification in operation_notifications:
        try:
            _dkss_notifications_delivery.dispatch_external_notification(
                target,
                operation_notification.title,
                operation_notification.message,
                operation_notification.link,
                notification_id=operation_notification.id
            )
        except Exception:
            _dkss_runtime.app.logger.exception(
                "運行不可の追加通知の外部配信に失敗しました。"
            )

    redirect_url = _dkss_common.url_for(
        "vehicle_checklist_results",
        index=result_record.checklist_id,
        vehicle_record_id=result_record.vehicle_record_id,
        year=result_record.year,
        month=result_record.month,
        active_day=result_record.day
    ) + "#vehicle-flow-judgment"
    if _dkss_common.request.headers.get("X-DKSS-Final-Submit") == "1":
        return _dkss_common.jsonify({"redirect_url": redirect_url})
    return _dkss_common.redirect(redirect_url)



def approve_vehicle_checklist_result(result_index, approval_index):
    lock_error = lock_vehicle_inspection_updates(
        _dkss_common.session.get("company_code"),
        result_index=result_index
    )
    if lock_error is not None:
        return lock_error
    result_record = (
        _dkss_models.VehicleChecklistResult.query
        .filter_by(
            id=result_index,
            company_code=_dkss_common.session.get("company_code")
        )
        .with_for_update()
        .first()
    )

    if not result_record:
        return _dkss_common.redirect("/vehicle/checklists")

    if result_record.status != "承認待ち":
        return _dkss_common.redirect("/vehicle/checklists")

    approvals = _dkss_serialization.safe_json_dict_list(
        result_record.approvals_json
    )
    if not approvals:
        approval_checklist = {}

        if result_record.checklist_snapshot_json:
            approval_checklist = _dkss_serialization.safe_json_dict(
                result_record.checklist_snapshot_json
            )

        if not approval_checklist:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                approval_checklist = _dkss_checklist_common.checklist_to_dict(
                    checklist_record
                )

        for item in approval_checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get(
                    "approval_allow_general",
                    False
                ),
                "candidate_usernames": [],
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

    if approval_index < 0 or approval_index >= len(approvals):
        return _dkss_common.redirect("/vehicle/checklists")

    current_approval_index = next(
        (
            index
            for index, item in enumerate(approvals)
            if not (
                item.get("approved_by")
                or item.get("approved_by_username")
            )
        ),
        None
    )

    if (
        current_approval_index is None
        or approval_index != current_approval_index
    ):
        return _dkss_common.redirect("/vehicle/checklists")

    approval = approvals[approval_index]

    # 旧データに allow_general が無い場合は
    # 記録時点のチェックリストから補完
    if "allow_general" not in approval:
        approval_checklist = {}

        if result_record.checklist_snapshot_json:
            approval_checklist = _dkss_serialization.safe_json_dict(
                result_record.checklist_snapshot_json
            )

        if not approval_checklist:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                approval_checklist = _dkss_checklist_common.checklist_to_dict(
                    checklist_record
                )

        approval_items = [
            item
            for item in approval_checklist.get("items", [])
            if item.get("item_type") == "approval"
        ]

        if approval_index < len(approval_items):
            approval["allow_general"] = approval_items[
                approval_index
            ].get(
                "approval_allow_general",
                False
            )

    if (
        approval.get("approved_by")
        or approval.get("approved_by_username")
    ):
        return _dkss_common.redirect("/vehicle/checklists")

    approval_snapshot = _dkss_serialization.safe_json_dict(result_record.checklist_snapshot_json)
    if any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in approval_snapshot.get("items", [])
    ):
        return _dkss_http.return_form_errors([
            ("標準の日常点検表は、運行判断の欄から確認・判断を保存してください。", "")
        ], 409)

    result = _dkss_checklist_common.vehicle_checklist_result_to_dict(result_record)

    approval_user = _dkss_models.User.query.filter_by(
        company_code=result_record.company_code,
        username=_dkss_common.session.get("username")
    ).first()

    if (
        not approval_user

        or not (
            approval_user.role == "admin"
            or (
                approval.get("allow_general", False)
                and approval_user.role == "user"
            )
        )
    ):
        return _dkss_common.redirect("/vehicle/checklists")

    approval["approved_by"] = _dkss_common.session.get("name")
    approval["approved_by_username"] = _dkss_common.session.get("username")
    approval["approved_date"] = _dkss_checklist_common.get_user_local_now(
        result_record.company_code,
        _dkss_common.session.get("username")
    ).strftime("%Y-%m-%d %H:%M")

    result_record.approvals_json = _dkss_common.json.dumps(
        approvals,
        ensure_ascii=False
    )

    result_record.reject_reason = ""

    all_approved = all(
        (
            item.get("approved_by")
            or item.get("approved_by_username")
        )
        for item in approvals
    )

    if approvals and all_approved:
        result_record.status = "承認済み"
        result_record.approved_by = _dkss_common.session.get("name")
        result_record.approved_by_username = _dkss_common.session.get("username")
        result_record.approved_date = _dkss_checklist_common.get_user_local_now(
            result_record.company_code,
            _dkss_common.session.get("username")
        ).strftime("%Y-%m-%d %H:%M")
    else:
        result_record.status = "承認待ち"
        result_record.approved_by = ""
        result_record.approved_by_username = ""
        result_record.approved_date = ""

    checklist_event = _dkss_models.ChecklistEvent(
        company_code=result_record.company_code,
        result_type="vehicle",
        result_id=result_record.id,
        event_type="承認",
        actor_username=_dkss_common.session.get("username"),
        actor_name=_dkss_common.session.get("name"),
        detail_json=_dkss_common.json.dumps(
            {
                "approval_index": approval_index,
                "approval": dict(approval),
                "all_approved": all_approved,
            },
            ensure_ascii=False
        ),
        created_at=_dkss_common.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    _dkss_common.db.session.add(checklist_event)
    _dkss_common.db.session.commit()

    vehicle_record = _dkss_models.Vehicle.query.filter_by(
        company_code=result_record.company_code,
        id=result_record.vehicle_record_id,
        deleted=False
    ).first()

    result_checklist = {}

    if result_record.checklist_snapshot_json:
        result_checklist = _dkss_serialization.safe_json_dict(
            result_record.checklist_snapshot_json
        )

    if not result_checklist:
        checklist_record = _dkss_models.Checklist.query.filter_by(
            id=result_record.checklist_id,
            company_code=result_record.company_code
        ).first()

        if checklist_record:
            result_checklist = _dkss_checklist_common.checklist_to_dict(
                checklist_record
            )

    if result_checklist.get("frequency_unit") == "year":
        active_value = result_record.year

    elif result_checklist.get("display_type") == "month":
        active_value = result_record.day

    else:
        active_value = result_record.month

    notification_link = (
        f"/vehicle/checklists/{result_record.checklist_id}"
        f"?vehicle_record_id={result_record.vehicle_record_id}"
        f"&year={result_record.year}"
        f"&month={result_record.month}"
        f"&active_day={active_value}"
    )

    if result_record.status != "承認済み":
        next_approval_index, next_approval = next(
            (
                (index, item)
                for index, item in enumerate(
                    approvals[approval_index + 1:],
                    start=approval_index + 1
                )
                if not (
                    item.get("approved_by")
                    or item.get("approved_by_username")
                )
            ),
            (None, None)
        )

        if next_approval:

            for target_username in next_approval.get(
                "candidate_usernames",
                []
            ):
                target_user = _dkss_models.User.query.filter_by(
                    company_code=result_record.company_code,
                    username=target_username
                ).first()

                if not target_user:
                    continue

                _dkss_notifications_delivery.add_notification(
                    (target_user.last_name or "")
                    + (target_user.first_name or ""),
                    "車両チェックリスト承認依頼",
                    "次の承認をお願いします。",
                    notification_link,
                    company_code=result_record.company_code,
                    target_identity=target_user.account_identity,
                    target_username=target_user.username,
                    workflow_context=_dkss_notifications_delivery.build_notification_workflow_context(
                        result_record,
                        "vehicle",
                        "approval",
                        approval_index=next_approval_index
                    )
                )

    if result_record.status == "承認済み":
        notify_usernames = set(
            _dkss_serialization.safe_json_str_list(
                result_record.notify_users_json
            )
        )

        if result_record.checked_by_username:
            notify_usernames.add(
                result_record.checked_by_username
            )

        for target_username in notify_usernames:
            target_user = _dkss_models.User.query.filter_by(
                company_code=result_record.company_code,
                username=target_username
            ).first()

            if not target_user:
                continue

            _dkss_notifications_delivery.add_notification(
                (target_user.last_name or "") + (target_user.first_name or ""),
                "車両チェックリストが承認されました",
                (
                    f"車両 {' '.join(value for value in [vehicle_record.plate_area or '', vehicle_record.plate_class or '', vehicle_record.plate_kana or '', vehicle_record.plate_number or ''] if value) if vehicle_record else '-'} の"
                    "チェックリストの承認が完了しました。"
                ),
                notification_link,
                company_code=result_record.company_code,
                target_identity=target_user.account_identity,
                target_username=target_user.username
            )

    return _dkss_common.redirect(
        f"/vehicle/checklists/{result_record.checklist_id}"
        f"?vehicle_record_id={result_record.vehicle_record_id}"
        f"&year={result_record.year}"
        f"&month={result_record.month}"
        f"&active_day={active_value}"
    )



def reject_vehicle_checklist_result(result_index):
    lock_error = lock_vehicle_inspection_updates(
        _dkss_common.session.get("company_code"),
        result_index=result_index
    )
    if lock_error is not None:
        return lock_error
    result_record = (
        _dkss_models.VehicleChecklistResult.query
        .filter_by(
            id=result_index,
            company_code=_dkss_common.session.get("company_code")
        )
        .with_for_update()
        .first()
    )

    if not result_record:
        return _dkss_common.redirect("/vehicle/checklists")

    if result_record.status not in {"承認待ち", "承認済み"}:
        return _dkss_http.return_form_errors([
            ("現在の状態では差し戻せません。画面を再読み込みしてください。", "")
        ], 409)

    if result_record.status == "承認済み":
        rejection_snapshot = _dkss_serialization.safe_json_dict(
            result_record.checklist_snapshot_json
        )
        if not rejection_snapshot:
            return _dkss_http.return_form_errors([
                ("点検様式を確認できないため差し戻せません。", "")
            ], 409)

        if any(
            item.get("fixed_template_code")
            == "daily_inspection_truck_trailer"
            for item in rejection_snapshot.get("items", [])
        ):
            return _dkss_http.return_form_errors([
                ("標準の日常点検表は運行判断の画面で操作してください。", "")
            ], 409)

    approvals = _dkss_serialization.safe_json_dict_list(
        result_record.approvals_json
    )

    if not approvals:
        approval_checklist = {}

        if result_record.checklist_snapshot_json:
            approval_checklist = _dkss_serialization.safe_json_dict(
                result_record.checklist_snapshot_json
            )

        if not approval_checklist:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                approval_checklist = _dkss_checklist_common.checklist_to_dict(
                    checklist_record
                )

        for item in approval_checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get(
                    "approval_allow_general",
                    False
                ),
                "candidate_usernames": [],
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

    if result_record.status == "承認済み":
        rejection_approval_index = _dkss_common.request.form.get(
            "approval_index",
            type=int
        )
        if (
            rejection_approval_index is None
            or rejection_approval_index < 0
            or rejection_approval_index >= len(approvals)
        ):
            return _dkss_http.return_form_errors([
                ("差し戻す承認欄を確認してください。", "")
            ], 400)

        current_approval = approvals[rejection_approval_index]

        if not (
            current_approval.get("approved_by")
            or current_approval.get("approved_by_username")
        ):
            return _dkss_http.return_form_errors([
                ("承認状況が更新されています。画面を再読み込みしてください。", "")
            ], 409)
    else:
        current_approval = next(
            (
                approval
                for approval in approvals
                if not (
                    approval.get("approved_by")
                    or approval.get("approved_by_username")
                )
            ),
            None
        )

    if not current_approval:
        return _dkss_http.return_form_errors([
            ("差し戻せる承認欄がありません。画面を再読み込みしてください。", "")
        ], 409)

    if "allow_general" not in current_approval:
        approval_checklist = {}

        if result_record.checklist_snapshot_json:
            approval_checklist = _dkss_serialization.safe_json_dict(
                result_record.checklist_snapshot_json
            )

        if not approval_checklist:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                approval_checklist = _dkss_checklist_common.checklist_to_dict(
                    checklist_record
                )

        approval_items = [
            item
            for item in approval_checklist.get("items", [])
            if item.get("item_type") == "approval"
        ]

        current_approval_index = approvals.index(
            current_approval
        )

        if current_approval_index < len(approval_items):
            current_approval["allow_general"] = (
                approval_items[
                    current_approval_index
                ].get(
                    "approval_allow_general",
                    False
                )
            )

    approval_user = _dkss_models.User.query.filter_by(
        company_code=result_record.company_code,
        username=_dkss_common.session.get("username")
    ).first()

    if (
        not approval_user
        or not (
            approval_user.role == "admin"
            or (
                current_approval.get(
                    "allow_general",
                    False
                )
                and approval_user.role == "user"
            )
        )
    ):
        return _dkss_common.redirect("/vehicle/checklists")

    reject_reason = _dkss_common.request.form.get(
        "reject_reason",
        ""
    ).strip()

    form_errors = []

    if not reject_reason:
        form_errors.append(
            (
                "差し戻し理由を入力してください。",
                "vehicleRejectReason"
            )
        )

    elif len(reject_reason) > 5000:
        form_errors.append(
            (
                "差し戻し理由は5000文字以内で入力してください。",
                "vehicleRejectReason"
            )
        )

    if form_errors:
        return _dkss_http.return_form_errors(form_errors)

    previous_approvals = [
        dict(approval)
        for approval in approvals
    ]

    for approval in approvals:
        approval["approved_by"] = ""
        approval["approved_by_username"] = ""
        approval["approved_date"] = ""

    result_record.approvals_json = _dkss_common.json.dumps(
        approvals,
        ensure_ascii=False
    )

    result_record.status = "差し戻し"
    result_record.approved_by = ""
    result_record.approved_by_username = ""
    result_record.approved_date = ""
    result_record.reject_reason = reject_reason

    checklist_event = _dkss_models.ChecklistEvent(
        company_code=result_record.company_code,
        result_type="vehicle",
        result_id=result_record.id,
        event_type="差し戻し",
        actor_username=_dkss_common.session.get("username"),
        actor_name=_dkss_common.session.get("name"),
        detail_json=_dkss_common.json.dumps(
            {
                "reject_reason": reject_reason,
                "approval_label": (
                    current_approval.get("label", "")
                    if current_approval
                    else ""
                ),
                "previous_approvals": previous_approvals,
            },
            ensure_ascii=False
        ),
        created_at=_dkss_common.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    _dkss_common.db.session.add(checklist_event)
    _dkss_common.db.session.commit()

    result_checklist = _dkss_serialization.safe_json_dict(
        result_record.checklist_snapshot_json
    )

    if not result_checklist:
        checklist_record = _dkss_models.Checklist.query.filter_by(
            id=result_record.checklist_id,
            company_code=result_record.company_code
        ).first()

        if checklist_record:
            result_checklist = _dkss_checklist_common.checklist_to_dict(
                checklist_record
            )

    if result_checklist.get("frequency_unit") == "year":
        active_value = result_record.year
    elif result_checklist.get("display_type") == "month":
        active_value = result_record.day
    else:
        active_value = result_record.month

    if result_record.checked_by_username:
        target_user = _dkss_models.User.query.filter_by(
            company_code=result_record.company_code,
            username=result_record.checked_by_username
        ).first()

        if target_user:
            _dkss_notifications_delivery.add_notification(
                (target_user.last_name or "")
                + (target_user.first_name or ""),
                "車両チェックリストが差し戻されました",
                (
                    "差し戻し理由："
                    f"{reject_reason}"
                ),
                (
                    f"/vehicle/checklists/"
                    f"{result_record.checklist_id}"
                    f"?vehicle_record_id="
                    f"{result_record.vehicle_record_id}"
                    f"&year={result_record.year}"
                    f"&month={result_record.month}"
                    f"&active_day={active_value}"
                ),
                company_code=result_record.company_code,
                target_identity=target_user.account_identity,
                target_username=target_user.username,
                workflow_context=_dkss_notifications_delivery.build_notification_workflow_context(
                    result_record,
                    "vehicle",
                    "correction"
                )
            )

    destination = _dkss_common.url_for(
        "vehicle_checklist_results",
        index=result_record.checklist_id,
        vehicle_record_id=result_record.vehicle_record_id,
        year=result_record.year,
        month=result_record.month,
        active_day=active_value
    )

    if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
        return _dkss_common.jsonify({
            "success": True,
            "status": "差し戻し",
            "redirect_url": destination
        })

    return _dkss_common.redirect(destination)



def export_vehicle_checklist_result_excel(result_index):
    result_record = _dkss_models.VehicleChecklistResult.query.filter_by(
        id=result_index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not result_record:
        return _dkss_common.redirect("/vehicle/checklists")
    result = _dkss_checklist_common.vehicle_checklist_result_to_dict(result_record)

    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=result_record.checklist_id,
        company_code=result_record.company_code
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/vehicle/checklists")

    checklist = (
        result.get("checklist_snapshot")
        or _dkss_checklist_common.checklist_to_dict(checklist_record)
    )

    # 点検頻度
    try:
        frequency_value = int(
            checklist.get("frequency_value") or 1
        )
    except (TypeError, ValueError):
        frequency_value = 1

    frequency_unit = checklist.get(
        "frequency_unit",
        ""
    )

    display_type = checklist.get(
        "display_type",
        ""
    )

    # Excelの表示単位を決定
    if frequency_unit == "year":
        excel_display_mode = "year"

    elif display_type == "month":
        excel_display_mode = "day"

    else:
        excel_display_mode = "month"

    vehicle_record = _dkss_models.Vehicle.query.filter_by(
        company_code=result_record.company_code,
        id=result_record.vehicle_record_id
    ).first()

    vehicle_info = {
        "vehicle_record_id": result_record.vehicle_record_id,
        "number": "",
        "manufacturer": "",
        "model_code": "",
    }

    if vehicle_record:
        vehicle_info["number"] = " ".join(
            value
            for value in [
                vehicle_record.plate_area or "",
                vehicle_record.plate_class or "",
                vehicle_record.plate_kana or "",
                vehicle_record.plate_number or "",
            ]
            if value
        )

        vehicle_info["manufacturer"] = (
            vehicle_record.manufacturer or ""
        )

        vehicle_info["model_code"] = (
            vehicle_record.model_code or ""
        )

    # 点検頻度に応じて出力対象を取得
    result_query = _dkss_models.VehicleChecklistResult.query.filter_by(
        company_code=result_record.company_code,
        checklist_id=result_record.checklist_id,
        vehicle_record_id=result_record.vehicle_record_id
    )

    if frequency_unit == "year":
        # 年次・複数年ごとの点検
        result_records = result_query.order_by(
            _dkss_models.VehicleChecklistResult.year.asc()
        ).all()

    elif display_type == "month":
        # 日次系
        result_records = result_query.filter_by(
            year=result_record.year,
            month=result_record.month
        ).order_by(
            _dkss_models.VehicleChecklistResult.day.asc()
        ).all()

    else:
        # 月例・3か月ごと・6か月ごと等
        result_records = result_query.filter_by(
            year=result_record.year
        ).order_by(
            _dkss_models.VehicleChecklistResult.month.asc()
        ).all()

    period_results = [
        _dkss_checklist_common.vehicle_checklist_result_to_dict(record)
        for record in result_records
    ]

    excel_sections = []

    if excel_display_mode == "day":
        master_checklist = _dkss_checklist_common.checklist_to_dict(
            checklist_record
        )

        version_history = []

        for version in master_checklist.get(
            "version_history",
            []
        ):
            try:
                change_datetime = _dkss_common.datetime.strptime(
                    version.get("effective_until", ""),
                    "%Y-%m-%d %H:%M:%S"
                )
            except (TypeError, ValueError):
                continue

            version_history.append({
                "change_date": change_datetime.date(),
                "snapshot": version.get("snapshot") or {}
            })

        version_history.sort(
            key=lambda version: version["change_date"]
        )

        current_checklist = {
            key: value
            for key, value in master_checklist.items()
            if key != "version_history"
        }

        results_by_day = {}

        for period_result in period_results:
            try:
                result_day = int(
                    period_result.get("day", 0)
                )
            except (TypeError, ValueError):
                continue

            results_by_day[result_day] = period_result

        days_in_month = _dkss_common.calendar.monthrange(
            int(result_record.year),
            int(result_record.month)
        )[1]

        current_section = None
        current_checklist_key = None

        for day in range(1, days_in_month + 1):
            target_date = _dkss_common.datetime(
                int(result_record.year),
                int(result_record.month),
                day
            ).date()

            day_checklist = current_checklist

            for version in version_history:
                if target_date < version["change_date"]:
                    day_checklist = version["snapshot"]
                    break

            day_result = results_by_day.get(day)

            if day_result:
                result_snapshot = (
                    day_result.get("checklist_snapshot") or {}
                )
                if result_snapshot:
                    day_checklist = result_snapshot

            if current_checklist.get("fixed_template_code") == "daily_inspection_truck_trailer":
                current_template = next(
                    (
                        item
                        for item in current_checklist.get("items", [])
                        if item.get("fixed_template_code")
                        == "daily_inspection_truck_trailer"
                    ),
                    {}
                )
                saved_template = next(
                    (
                        item
                        for item in day_checklist.get("items", [])
                        if item.get("fixed_template_code")
                        == "daily_inspection_truck_trailer"
                    ),
                    {}
                )
                current_version = current_template.get(
                    "fixed_template_version",
                    1
                )
                saved_version = saved_template.get(
                    "fixed_template_version",
                    current_version
                )

                if str(saved_version) == str(current_version):
                    day_checklist = current_checklist

            checklist_key = _dkss_checklist_common.checklist_revision_key(
                day_checklist
            )

            if checklist_key != current_checklist_key:
                current_section = {
                    "start_day": day,
                    "end_day": day,
                    "checklist": day_checklist,
                    "results": []
                }

                excel_sections.append(current_section)
                current_checklist_key = checklist_key

            else:
                current_section["end_day"] = day

            if day_result:
                current_section["results"].append(
                    day_result
                )

    if excel_display_mode == "day" and excel_sections:
        excel_render_sections = excel_sections
    else:
        excel_render_sections = [{
            "start_day": None,
            "end_day": None,
            "checklist": checklist,
            "results": period_results
        }]

    # 月間帳票を半月ごとに分ける設定
    half_month_mode = (
        excel_display_mode == "day"
        and checklist.get("print_half_month")
        and checklist.get("fixed_template_code") != "daily_inspection_truck_trailer"
        and len(excel_render_sections) == 1
    )

    workbook = _dkss_common.Workbook()

    excel_section = excel_render_sections[0]

    excel_checklist = excel_section["checklist"]
    excel_period_results = excel_section["results"]

    sheet = workbook.active

    if (
        excel_display_mode == "day"
        and excel_section["start_day"] is not None
        and excel_section["end_day"] is not None
    ):
        sheet.title = (
            f"{excel_section['start_day']}～"
            f"{excel_section['end_day']}日"
        )
    else:
        sheet.title = "車両点検結果"

    def render_excel_section(
        sheet,
        excel_checklist,
        excel_period_results
    ):

        # 印刷設定
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        if excel_checklist.get("print_portrait"):
            sheet.page_setup.orientation = sheet.ORIENTATION_PORTRAIT
        else:
            sheet.page_setup.orientation = sheet.ORIENTATION_LANDSCAPE
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.print_options.horizontalCentered = True

        # 点検頻度に応じた列幅
        sheet.column_dimensions["A"].width = 42

        if excel_display_mode == "day":
            days_in_month = _dkss_common.calendar.monthrange(
                int(result_record.year),
                int(result_record.month)
            )[1]

            end_column = days_in_month + 1

            if half_month_mode:
                period_width = 7.0
            else:
                period_width = 3.8

        elif excel_display_mode == "month":
            end_column = 13
            period_width = 6

        else:
            end_column = 6
            period_width = 12

        for column in range(2, end_column + 1):
            sheet.column_dimensions[
                sheet.cell(row=1, column=column).column_letter
            ].width = period_width

        # タイトル
        title_end_column = end_column

        sheet.merge_cells(
            start_row=1,
            start_column=1,
            end_row=2,
            end_column=title_end_column
        )

        title_cell = sheet["A1"]
        if excel_display_mode == "day":
            title_cell.value = (
                f"{result_record.year}年 "
                f"{int(result_record.month)}月 "
                f"{excel_checklist.get('name', '車両点検表')}"
            )

        elif excel_display_mode == "month":
            title_cell.value = (
                f"{result_record.year}年 "
                f"{excel_checklist.get('name', '車両点検表')}"
            )

        else:
            title_cell.value = (
                f"{excel_checklist.get('name', '車両点検表')}"
            )
        title_cell.font = _dkss_common.Font(
            bold=True,
            size=16
        )
        title_cell.alignment = _dkss_common.Alignment(
            horizontal="center",
            vertical="center"
        )

        # 評価基準
        criteria_list = []

        for item in excel_checklist.get("items", []):
            if item.get("item_type") != "check":
                continue

            criteria = (item.get("criteria") or "").strip()

            if criteria and criteria not in criteria_list:
                criteria_list.append(criteria)

        if criteria_list:
            criteria_text = "評価基準：\n" + "\n".join(criteria_list)

            # 評価基準の改行数と文字量から必要な行数を計算
            chars_per_line = 100
            line_count = 0

            for line in criteria_text.split("\n"):
                line_count += max(
                    1,
                    (len(line) + chars_per_line - 1) // chars_per_line
                )

            sheet.row_dimensions[3].height = max(
                24,
                line_count * 18
            )

            sheet.merge_cells(
                start_row=3,
                start_column=1,
                end_row=3,
                end_column=end_column
            )

            criteria_cell = sheet.cell(
                row=3,
                column=1,
                value=criteria_text
            )

            criteria_cell.font = _dkss_common.Font(
                size=9
            )

            criteria_cell.alignment = _dkss_common.Alignment(
                horizontal="left",
                vertical="center",
                wrap_text=True
            )

        # 月間帳票の車両情報
        vehicle_number = (
            vehicle_info["number"]
            or "ナンバー未登録"
        )

        sheet.merge_cells(
            start_row=4,
            start_column=1,
            end_row=4,
            end_column=end_column
        )

        sheet["A4"] = f"登録番号　{vehicle_number}"
        sheet["A4"].font = _dkss_common.Font(bold=True)
        sheet["A4"].alignment = _dkss_common.Alignment(
            horizontal="left",
            vertical="center"
        )

        # 点検表ヘッダー
        header_row = 5
        weekday_row = 6

        sheet["A5"] = "点検項目"

        sheet.merge_cells(
            start_row=5,
            start_column=1,
            end_row=6,
            end_column=1
        )

        year = int(result_record.year)
        month = int(result_record.month)

        if excel_display_mode == "day":
            # 日次：1～31日
            days_in_month = _dkss_common.calendar.monthrange(
                year,
                month
            )[1]

            weekday_names = [
                "月", "火", "水", "木", "金", "土", "日"
            ]

            for day in range(1, days_in_month + 1):
                column = day + 1

                if day <= days_in_month:
                    sheet.cell(
                        row=header_row,
                        column=column,
                        value=day
                    )

                    weekday_index = _dkss_common.datetime(
                        year,
                        month,
                        day
                    ).weekday()

                    sheet.cell(
                        row=weekday_row,
                        column=column,
                        value=weekday_names[weekday_index]
                    )

                    if weekday_index == 5:
                        sheet.cell(
                            row=weekday_row,
                            column=column
                        ).font = _dkss_common.Font(color="0000FF")

                    elif weekday_index == 6:
                        sheet.cell(
                            row=weekday_row,
                            column=column
                        ).font = _dkss_common.Font(color="FF0000")

        elif excel_display_mode == "month":
            # 月例・3か月・6か月ごと等：1～12月
            for month_no in range(1, 13):
                column = month_no + 1

                sheet.cell(
                    row=header_row,
                    column=column,
                    value=f"{month_no}月"
                )

                sheet.merge_cells(
                    start_row=header_row,
                    start_column=column,
                    end_row=weekday_row,
                    end_column=column
                )

        else:
            # 年次・複数年ごと
            base_year = int(result_record.year)

            for offset in range(5):
                column = offset + 2
                target_year = base_year + offset

                sheet.cell(
                    row=header_row,
                    column=column,
                    value=f"{target_year}年"
                )

                sheet.merge_cells(
                    start_row=header_row,
                    start_column=column,
                    end_row=weekday_row,
                    end_column=column
                )

        # 点検項目を縦に並べる
        current_row = 7
        previous_category = None
        category_rows = set()
        shaded_rows = set()

        item_no = -1
        approval_row_positions = []

        for item in excel_checklist.get("items", []):

            if item.get("item_type") in {
                "inspector", "approval", "operation_judgment"
            }:
                approval_row_positions.append(current_row)
                current_row += 1
                continue

            if item.get("item_type") != "check":
                continue

            item_no += 1

            category = item.get("category", "").strip()
            content = item.get("content", "").strip()

            # カテゴリが変わったら横一列のカテゴリ行を追加
            if category and category != previous_category:
                category_row = current_row
                category_rows.add(category_row)

                sheet.merge_cells(
                    start_row=category_row,
                    start_column=1,
                    end_row=category_row,
                    end_column=end_column
                )

                category_cell = sheet.cell(
                    row=category_row,
                    column=1,
                    value=f"（{category}）"
                )

                category_cell.font = _dkss_common.Font(bold=True)
                category_cell.alignment = _dkss_common.Alignment(
                    horizontal="left",
                    vertical="center"
                )

                sheet.row_dimensions[category_row].height = 20

                current_row += 1
                previous_category = category

            # 点検項目にはカテゴリ名を付けない
            item_text = content

            # 点検項目の文字量に応じて行高を調整
            import math



            item_line_count = 0

            for line in item_text.split("\n"):
                item_line_count += max(
                    1,
                    math.ceil(spreadsheet_text_width(line) / 42)
                )

            sheet.row_dimensions[current_row].height = max(
                21,
                item_line_count * 18 + 4
            )

            sheet.cell(
                row=current_row,
                column=1,
                value=item_text
            )

            sheet.cell(
                row=current_row,
                column=1
            ).alignment = _dkss_common.Alignment(
                vertical="center",
                wrap_text=True,
            )

            if item.get("shaded"):
                shaded_rows.add(current_row)

                shaded_fill = _dkss_common.PatternFill(
                    fill_type="solid",
                    fgColor="D9D9D9"
                )

                for column in range(1, end_column + 1):
                    sheet.cell(
                        row=current_row,
                        column=column
                    ).fill = shaded_fill

            # 点検結果を表示単位に応じて入れる
            for period_result in excel_period_results:

                if excel_display_mode == "day":
                    try:
                        period_value = int(
                            period_result.get("day", 0)
                        )
                    except (TypeError, ValueError):
                        continue

                    if period_value < 1 or period_value > 31:
                        continue

                    column = period_value + 1

                elif excel_display_mode == "month":
                    try:
                        period_value = int(
                            period_result.get("month", 0)
                        )
                    except (TypeError, ValueError):
                        continue

                    if period_value < 1 or period_value > 12:
                        continue

                    column = period_value + 1

                else:
                    try:
                        period_year = int(
                            period_result.get("year", 0)
                        )
                    except (TypeError, ValueError):
                        continue

                    year_offset = period_year - base_year

                    if year_offset < 0 or year_offset >= 5:
                        continue

                    column = year_offset + 2

                matched_answer = None

                for answer in period_result.get("answers", []):
                    answer_item_no = answer.get("item_no")

                    # item_no があるデータは番号だけで照合
                    if answer_item_no not in (None, ""):
                        if str(answer_item_no) == str(item_no):
                            matched_answer = answer
                            break
                        continue

                    # item_no が無い旧データだけカテゴリー＋内容で照合
                    if (
                        answer.get("category", "")
                        == item.get("category", "")
                        and answer.get("content", "")
                        == item.get("content", "")
                    ):
                        matched_answer = answer
                        break

                if not matched_answer:
                    continue

                result_cell = sheet.cell(
                    row=current_row,
                    column=column,
                    value=matched_answer.get("value", "") or ""
                )

                result_cell.alignment = _dkss_common.Alignment(
                    horizontal="center",
                    vertical="center"
                )

            current_row += 1

        if excel_checklist.get("score_enabled"):
            score_row = current_row

            sheet.cell(
                row=score_row,
                column=1,
                value="合計点"
            )

            sheet.cell(
                row=score_row,
                column=1
            ).font = _dkss_common.Font(bold=True)

            for period_result in excel_period_results:
                total_score = 0

                for answer in period_result.get("answers", []):
                    try:
                        total_score += float(answer.get("value") or 0)
                    except (TypeError, ValueError):
                        pass

                if excel_display_mode == "day":
                    try:
                        column = int(period_result.get("day", 0)) + 1
                    except (TypeError, ValueError):
                        continue

                elif excel_display_mode == "month":
                    try:
                        column = int(period_result.get("month", 0)) + 1
                    except (TypeError, ValueError):
                        continue

                else:
                    try:
                        period_year = int(period_result.get("year", 0))
                    except (TypeError, ValueError):
                        continue

                    year_offset = period_year - base_year

                    if year_offset < 0 or year_offset >= 5:
                        continue

                    column = year_offset + 2

                sheet.cell(
                    row=score_row,
                    column=column,
                    value=int(total_score)
                )

            current_row += 1

        # 押印欄（実施者・承認項目をマスタの並び順で出力）
        approval_items = [
            item
            for item in excel_checklist.get("items", [])
            if item.get("item_type") in {
                "inspector", "approval", "operation_judgment"
            }
        ]

        for approval_index, approval_item in enumerate(approval_items):
            approval_row = approval_row_positions[approval_index]

            sheet.row_dimensions[approval_row].height = 28

            sheet.cell(
                row=approval_row,
                column=1,
                value=(
                    (approval_item.get("content") or "実施者")
                    if approval_item.get("item_type") == "inspector"
                    else (
                        approval_item.get("content") or "整備管理者"
                        if approval_item.get("item_type") == "operation_judgment"
                        else approval_item.get("approval_label", "") or "承認"
                    )
                )
            )

            for period_result in excel_period_results:
                if approval_item.get("item_type") == "operation_judgment":
                    continue

                if approval_item.get("item_type") == "inspector":
                    approval = {
                        "approved_by": period_result.get("checked_by", ""),
                        "approved_by_username": period_result.get(
                            "checked_by_username",
                            ""
                        ),
                    }
                else:
                    approvals = period_result.get("approvals", [])

                    approval_position = sum(
                        1
                        for previous_item in approval_items[:approval_index]
                        if previous_item.get("item_type") == "approval"
                    )

                    if approval_position >= len(approvals):
                        continue

                    approval = approvals[approval_position]

                if not (
                    approval.get("approved_by")
                    or approval.get("approved_by_username")
                ):
                    continue

                if excel_display_mode == "day":
                    try:
                        column = int(period_result.get("day", 0)) + 1

                    except (TypeError, ValueError):
                        continue

                elif excel_display_mode == "month":
                    try:
                        column = int(period_result.get("month", 0)) + 1
                    except (TypeError, ValueError):
                        continue

                else:
                    try:
                        period_year = int(period_result.get("year", 0))
                    except (TypeError, ValueError):
                        continue

                    year_offset = period_year - base_year

                    if year_offset < 0 or year_offset >= 5:
                        continue

                    column = year_offset + 2

                approval_user = _dkss_models.User.query.filter_by(
                    company_code=result_record.company_code,
                    username=approval.get("approved_by_username")
                ).first()

                sheet.cell(
                    row=approval_row,
                    column=column,
                    value=(
                        approval_user.last_name
                        if approval_user
                        else (
                            approval.get("approved_by")
                            or approval.get("approved_by_username")
                            or ""
                        )
                    )
                ).alignment = _dkss_common.Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True
                )

        # 表全体の罫線・配置
        thin = _dkss_common.Side(
            style="thin",
            color="000000"
        )

        table_end_row = current_row - 1

        for row_number in range(5, table_end_row + 1):

            # カテゴリ行は横一列にして日付マスの縦線を付けない
            if row_number in category_rows:
                no_border = _dkss_common.Side(style=None)

                for category_column in range(
                    1,
                    title_end_column + 1
                ):
                    category_cell = sheet.cell(
                        row=row_number,
                        column=category_column
                    )

                    category_cell.border = _dkss_common.Border(
                        left=(
                            thin
                            if category_column == 1
                            else no_border
                        ),
                        right=(
                            thin
                            if category_column == title_end_column
                            else no_border
                        ),
                        top=thin,
                        bottom=thin
                    )

                continue

            for column_number in range(1, title_end_column + 1):

                cell = sheet.cell(
                    row=row_number,
                    column=column_number
                )

                cell.border = _dkss_common.Border(
                    left=thin,
                    right=thin,
                    top=thin,
                    bottom=thin
                )

                if column_number >= 2:
                    cell.alignment = _dkss_common.Alignment(
                        horizontal="center",
                        vertical="center",
                        wrap_text=True
                    )

        # ヘッダー装飾
        header_fill = _dkss_common.PatternFill(
            fill_type="solid",
            fgColor="D9E1F2"
        )

        for row_number in range(header_row, weekday_row + 1):
            for column_number in range(1, title_end_column + 1):
                header_cell = sheet.cell(
                    row=row_number,
                    column=column_number
                )

                header_cell.fill = header_fill
                header_cell.font = _dkss_common.Font(bold=True)
                header_cell.alignment = _dkss_common.Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True
                )

        # 日次表の土日列を薄く色付け
        if excel_display_mode == "day":
            saturday_fill = _dkss_common.PatternFill(
                fill_type="solid",
                fgColor="EAF2F8"
            )

            sunday_fill = _dkss_common.PatternFill(
                fill_type="solid",
                fgColor="FCE8E6"
            )

            for day in range(1, days_in_month + 1):
                if day > days_in_month:
                    continue

                column = day + 1

                weekday_index = _dkss_common.datetime(
                    year,
                    month,
                    day
                ).weekday()

                if weekday_index == 5:
                    fill = saturday_fill
                elif weekday_index == 6:
                    fill = sunday_fill
                else:
                    continue

                for row_number in range(
                    header_row,
                    table_end_row + 1
                ):
                    if row_number in shaded_rows:
                        continue

                    sheet.cell(
                        row=row_number,
                        column=column
                    ).fill = fill


        # 日次表の土日文字色を再設定
        if excel_display_mode == "day":
            for column_number in range(2, title_end_column + 1):

                weekday_cell = sheet.cell(
                    row=weekday_row,
                    column=column_number
                )

                if weekday_cell.value == "土":
                    weekday_cell.font = _dkss_common.Font(
                        bold=True,
                        color="0000FF"
                    )

                elif weekday_cell.value == "日":
                    weekday_cell.font = _dkss_common.Font(
                        bold=True,
                        color="FF0000"
                    )

        return {
            "table_end_row": table_end_row,
            "title_end_column": title_end_column,
            "days_in_month": (
                days_in_month
                if excel_display_mode == "day"
                else None
            )
        }

    render_info = render_excel_section(
        sheet,
        excel_checklist,
        excel_period_results
    )

    table_end_row = render_info["table_end_row"]
    title_end_column = render_info["title_end_column"]

    if excel_display_mode == "day":
        days_in_month = render_info["days_in_month"]

    rendered_sheets = [{
        "sheet": sheet,
        "checklist": excel_checklist,
        "render_info": render_info,
        "start_day": excel_section["start_day"],
        "end_day": excel_section["end_day"]
    }]

    if (
        excel_display_mode == "day"
        and not half_month_mode
        and len(excel_render_sections) > 1
    ):
        for extra_section in excel_render_sections[1:]:
            extra_sheet = workbook.create_sheet()

            extra_sheet.title = (
                f"{extra_section['start_day']}～"
                f"{extra_section['end_day']}日"
            )

            extra_checklist = extra_section["checklist"]
            extra_results = extra_section["results"]

            extra_render_info = render_excel_section(
                extra_sheet,
                extra_checklist,
                extra_results
            )

            rendered_sheets.append({
                "sheet": extra_sheet,
                "checklist": extra_checklist,
                "render_info": extra_render_info,
                "start_day": extra_section["start_day"],
                "end_day": extra_section["end_day"]
            })

    if excel_display_mode == "day" and not half_month_mode:
        for rendered_sheet in rendered_sheets:
            period_sheet = rendered_sheet["sheet"]
            start_day = rendered_sheet["start_day"]
            end_day = rendered_sheet["end_day"]

            if start_day is None or end_day is None:
                continue

            for day in range(1, days_in_month + 1):
                if start_day <= day <= end_day:
                    continue

                column = day + 1
                column_letter = period_sheet.cell(
                    row=5,
                    column=column
                ).column_letter

                period_sheet.column_dimensions[
                    column_letter
                ].hidden = True

    # 半月ごとに分ける場合は、表・裏の2シートにする
    if half_month_mode:
        sheet.title = "表 1～15日"

        back_sheet = workbook.copy_worksheet(sheet)
        back_sheet.title = "裏 16日～月末"

        # 表：16日～月末を非表示
        for day in range(16, days_in_month + 1):
            column = day + 1
            column_letter = sheet.cell(
                row=5,
                column=column
            ).column_letter
            sheet.column_dimensions[column_letter].hidden = True

        # 裏：1～15日を非表示
        for day in range(1, 16):
            column = day + 1
            column_letter = back_sheet.cell(
                row=5,
                column=column
            ).column_letter
            back_sheet.column_dimensions[column_letter].hidden = True

    # Excelファイルをメモリ上に保存
    output = _dkss_common.BytesIO()

    if half_month_mode:
        print_sheet_entries = [
            {
                "sheet": sheet,
                "checklist": excel_checklist,
                "render_info": render_info
            },
            {
                "sheet": back_sheet,
                "checklist": excel_checklist,
                "render_info": render_info
            }
        ]
    else:
        print_sheet_entries = rendered_sheets

    for print_entry in print_sheet_entries:
        print_sheet = print_entry["sheet"]
        print_checklist = print_entry["checklist"]
        print_render_info = print_entry["render_info"]

        print_sheet.print_area = (
            f"A1:{print_sheet.cell(
                row=print_render_info["table_end_row"],
                column=print_render_info["title_end_column"]
            ).coordinate}"
        )

        print_sheet.sheet_properties.pageSetUpPr.fitToPage = True
        print_sheet.page_setup.paperSize = print_sheet.PAPERSIZE_A4

        if print_checklist.get("print_portrait"):
            print_sheet.page_setup.orientation = (
                print_sheet.ORIENTATION_PORTRAIT
            )
        else:
            print_sheet.page_setup.orientation = (
                print_sheet.ORIENTATION_LANDSCAPE
            )

        print_sheet.page_setup.fitToWidth = 1
        print_sheet.page_setup.fitToHeight = 0
        print_sheet.print_options.horizontalCentered = True

        print_sheet.page_margins.left = 0.25
        print_sheet.page_margins.right = 0.25
        print_sheet.page_margins.top = 0.25
        print_sheet.page_margins.bottom = 0.25
        print_sheet.page_margins.header = 0.2
        print_sheet.page_margins.footer = 0.2

    _dkss_http.sanitize_excel_formulas(workbook)
    workbook.save(output)
    output.seek(0)

    filename = (
        f"{checklist.get('name', '車両点検表')}_"
        f"{result_record.year}"
    )

    if excel_display_mode == "day":
        filename += f"_{int(result_record.month):02d}"

    filename += ".xlsx"

    return _dkss_common.send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )



def lock_vehicle_inspection_updates(
    company_code,
    vehicle_record_id=None,
    checklist=None,
    result_index=None
):
    if result_index is not None:
        record = _dkss_models.VehicleChecklistResult.query.filter_by(
            id=result_index,
            company_code=company_code
        ).first()
        if not record:
            return None

        vehicle_record_id = record.vehicle_record_id
        checklist = _dkss_serialization.safe_json_dict(record.checklist_snapshot_json)

    if not any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in (checklist or {}).get("items", [])
    ):
        return None

    try:
        locked = _dkss_models.Vehicle.query.filter_by(
            company_code=company_code,
            id=vehicle_record_id,
            deleted=False
        ).update(
            {_dkss_models.Vehicle.id: _dkss_models.Vehicle.id},
            synchronize_session=False
        )

        if locked != 1:
            _dkss_common.db.session.rollback()
            return _dkss_http.return_form_errors([
                ("対象車両を確認できません。", "")
            ], 404)

        _dkss_common.db.session.expire_all()
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("日常点検の車両更新ロックに失敗しました。")
        return _dkss_http.return_form_errors([
            ("この車両の保存処理が競合しました。少し待ってからもう一度操作してください。", "")
        ], 409)

    return None



def get_vehicle_operation_basis(company_code, vehicle_record_id):
    if not company_code or not vehicle_record_id:
        return ""

    from hashlib import sha256

    basis = []
    records = _dkss_models.VehicleChecklistResult.query.filter_by(
        company_code=company_code,
        vehicle_record_id=vehicle_record_id
    ).order_by(_dkss_models.VehicleChecklistResult.id.asc()).all()

    for record in records:
        snapshot = _dkss_serialization.safe_json_dict(record.checklist_snapshot_json)
        if any(
            item.get("fixed_template_code") == "daily_inspection_truck_trailer"
            for item in snapshot.get("items", [])
        ):
            basis.append([
                record.id,
                record.answers_json,
                record.checklist_snapshot_json,
                record.operation_judgment_json,
                record.status,
            ])

    return sha256(
        _dkss_common.json.dumps(basis, ensure_ascii=False).encode("utf-8")
    ).hexdigest()



def get_vehicle_open_inspection_defects(company_code, vehicle_record_id, include_resolved=False, *, read_snapshot=None):
    if not company_code or not vehicle_record_id:
        return []

    if read_snapshot is not None:
        read_snapshot.require_scope(company_code, vehicle_record_id)
        records = sorted(read_snapshot.rows(_dkss_models.VehicleChecklistResult), key=lambda row: row.id)
    else:
        records = _dkss_models.VehicleChecklistResult.query.filter_by(
            company_code=company_code,
            vehicle_record_id=vehicle_record_id
        ).order_by(_dkss_models.VehicleChecklistResult.id.asc()).all()

    open_defects = []

    for record in records:
        snapshot = _dkss_serialization.safe_json_dict(record.checklist_snapshot_json)
        if not any(
            item.get("fixed_template_code") == "daily_inspection_truck_trailer"
            for item in snapshot.get("items", [])
        ):
            continue

        judgment = _dkss_serialization.safe_json_dict(record.operation_judgment_json)
        defects = list(judgment.get("defects") or [])

        for answer in _dkss_serialization.safe_json_dict_list(record.answers_json):
            if str(answer.get("value") or "").strip() != "×":
                continue

            item_no = str(answer.get("item_no", ""))
            accounted_for = any(
                str(defect.get("item_no", "")) == item_no
                and (
                    defect.get("status") != "解消"
                    or all(
                        defect.get("rechecked_answer", {}).get(field)
                        == answer.get(field)
                        for field in ("value", "comment", "files")
                    )
                )
                for defect in defects
            )
            if not accounted_for:
                defects.append({
                    "item_no": item_no,
                    "status": "対応待ち",
                    "reported_answer": dict(answer),
                })

        for defect in defects:
            if defect.get("status") == "解消" and not include_resolved:
                continue

            open_defects.append({
                "result_id": record.id,
                "judgment_version": judgment.get("version", 0),
                "inspection_date": (
                    f"{record.year}/"
                    f"{str(record.month).zfill(2)}/"
                    f"{str(record.day).zfill(2)}"
                ),
                "defect": dict(defect),
                "link": _dkss_common.url_for(
                    "vehicle_checklist_results",
                    index=record.checklist_id,
                    vehicle_record_id=record.vehicle_record_id,
                    year=record.year,
                    month=record.month,
                    active_day=record.day
                ),
            })

    return open_defects



def get_vehicle_recent_inspection_repairs(company_code, vehicle_record_id):
    events = (
        _dkss_models.ChecklistEvent.query
        .join(
            _dkss_models.VehicleChecklistResult,
            _dkss_models.ChecklistEvent.result_id == _dkss_models.VehicleChecklistResult.id
        )
        .filter(
            _dkss_models.ChecklistEvent.company_code == company_code,
            _dkss_models.ChecklistEvent.result_type == "vehicle",
            _dkss_models.ChecklistEvent.event_type.in_(["整備中", "再確認待ち"]),
            _dkss_models.VehicleChecklistResult.company_code == company_code,
            _dkss_models.VehicleChecklistResult.vehicle_record_id == vehicle_record_id
        )
        .order_by(
            _dkss_models.ChecklistEvent.created_at.desc(),
            _dkss_models.ChecklistEvent.id.desc()
        )
        .limit(5)
        .all()
    )

    repairs = []

    for event in events:
        detail = _dkss_serialization.safe_json_dict(event.detail_json)
        repair = detail.get("repair") or {}

        if not repair:
            continue

        defect = detail.get("defect") or {}
        answer = defect.get("reported_answer") or {}

        repairs.append({
            "item_name": answer.get("content") or "",
            "note": repair.get("note") or "",
            "performed_by": repair.get("performed_by") or "",
            "performed_at": repair.get("performed_at") or "",
            "recorded_at": event.created_at,
            "status": repair.get("status") or "",
        })

    return repairs



def invalidate_other_vehicle_operation_judgments(result_record):
    if not result_record.vehicle_record_id:
        return

    local_now = _dkss_checklist_common.get_user_local_now(
        result_record.company_code,
        _dkss_common.session.get("username")
    )
    today = (local_now.year, local_now.month, local_now.day)
    reason = "同じ車両の点検・不具合対応が更新されたため、再判定が必要です。"

    with _dkss_common.db.session.no_autoflush:
        records = _dkss_models.VehicleChecklistResult.query.filter_by(
            company_code=result_record.company_code,
            vehicle_record_id=result_record.vehicle_record_id
        ).all()

    for record in records:
        if record.id == result_record.id:
            continue
        try:
            inspection_date = (
                int(record.year), int(record.month), int(record.day)
            )
        except (TypeError, ValueError):
            continue
        if inspection_date < today:
            continue

        checklist = _dkss_serialization.safe_json_dict(record.checklist_snapshot_json)
        if not any(
            item.get("fixed_template_code") == "daily_inspection_truck_trailer"
            for item in checklist.get("items", [])
        ):
            continue

        previous = _dkss_serialization.safe_json_dict(record.operation_judgment_json)
        if previous.get("status") != "運行可":
            continue

        judgment = {
            **previous,
            "status": "未判定",
            "version": int(previous.get("version") or 0) + 1,
            "reason": reason,
        }
        for key in (
            "judged_by", "judged_by_username", "judged_at",
            "authority_role", "authority_confirmed",
            "checks_confirmed", "checks_evidence"
        ):
            judgment.pop(key, None)

        record.operation_judgment_json = _dkss_common.json.dumps(
            judgment, ensure_ascii=False
        )
        _dkss_common.db.session.add(_dkss_models.ChecklistEvent(
            company_code=record.company_code,
            result_type="vehicle",
            result_id=record.id,
            event_type="運行判断",
            actor_username=_dkss_common.session.get("username"),
            actor_name=_dkss_common.session.get("name"),
            created_at=local_now.strftime("%Y-%m-%d %H:%M:%S"),
            detail_json=_dkss_common.json.dumps({
                "previous_judgment": previous,
                "judgment": judgment,
                "changed_result_id": result_record.id,
            }, ensure_ascii=False)
        ))

        vehicle = _dkss_models.Vehicle.query.filter_by(
            company_code=record.company_code,
            id=record.vehicle_record_id
        ).first()
        vehicle_name = (
            " ".join(
                value for value in (
                    vehicle.plate_area or "",
                    vehicle.plate_class or "",
                    vehicle.plate_kana or "",
                    vehicle.plate_number or "",
                ) if value
            ) if vehicle else ""
        ) or f"車両ID：{record.vehicle_record_id}"
        notification_link = _dkss_common.url_for(
            "vehicle_checklist_results",
            index=record.checklist_id,
            vehicle_record_id=record.vehicle_record_id,
            year=record.year,
            month=record.month,
            active_day=record.day
        ) + "#vehicle-flow-judgment"

        for username in sorted(set(previous.get("requested_usernames") or [])):
            target_user = _dkss_models.User.query.filter_by(
                company_code=record.company_code,
                username=username,
                role="admin"
            ).first()
            if not target_user:
                continue

            notification = _dkss_models.Notification(
                company_code=record.company_code,
                target_user=(target_user.last_name or "") + (target_user.first_name or ""),
                target_username=target_user.username,
                owner_identity=target_user.account_identity,
                title="運行可否の再判定依頼：" + vehicle_name,
                message=(
                    f"対象車両：{vehicle_name}\n"
                    f"点検日：{record.year}/{record.month}/{record.day}\n"
                    f"{reason}\n"
                    "点検結果と未解消の不具合を確認し、運行可否を再登録してください。"
                ),
                link=notification_link,
                files_json="[]",
                workflow_context_json=_dkss_common.json.dumps(
                    _dkss_notifications_delivery.build_notification_workflow_context(
                        record,
                        "vehicle",
                        "operation_judgment"
                    ),
                    ensure_ascii=False
                ),
                read=False,
                created_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC")).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            )
            _dkss_common.db.session.add(notification)
            result_record._pending_defect_notifications = (
                getattr(result_record, "_pending_defect_notifications", [])
                + [(target_user, notification)]
            )



def dispatch_vehicle_defect_notifications(result_record):
    notifications = getattr(
        result_record,
        "_pending_defect_notifications",
        []
    )
    result_record._pending_defect_notifications = []

    for target_user, notification in notifications:
        try:
            _dkss_notifications_delivery.dispatch_external_notification(
                target_user,
                notification.title,
                notification.message,
                notification.link,
                notification_id=notification.id
            )
        except Exception:
            _dkss_runtime.app.logger.exception(
                "日常点検の異常報告の外部通知に失敗しました。"
            )



def reset_vehicle_operation_judgment(result_record, result_checklist):
    if not any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in result_checklist.get("items", [])
    ):
        return

    previous = _dkss_serialization.safe_json_dict(result_record.operation_judgment_json)
    judgment = dict(previous)
    defects = list(judgment.get("defects") or [])

    for answer in _dkss_serialization.safe_json_dict_list(result_record.answers_json):
        if str(answer.get("value") or "").strip() != "×":
            continue

        item_no = str(answer.get("item_no", ""))
        if not item_no or any(
            str(defect.get("item_no", "")) == item_no
            and (
                defect.get("status") != "解消"
                or all(
                    defect.get("rechecked_answer", {}).get(field)
                    == answer.get(field)
                    for field in ("value", "comment", "files")
                )
            )
            for defect in defects
        ):
            continue

        defects.append({
            "defect_no": len(defects) + 1,
            "item_no": item_no,
            "status": "対応待ち",
            "reported_by": _dkss_common.session.get("name") or "",
            "reported_by_username": _dkss_common.session.get("username") or "",
            "reported_at": _dkss_checklist_common.get_user_local_now(
                result_record.company_code,
                _dkss_common.session.get("username")
            ).strftime("%Y-%m-%d %H:%M:%S"),
            "reported_answer": dict(answer),
        })

    new_defects = defects[len(previous.get("defects") or []):]
    if new_defects:
        target_usernames = set(previous.get("requested_usernames") or [])

        if not target_usernames:
            inspector = _dkss_models.User.query.filter_by(
                company_code=result_record.company_code,
                username=result_record.checked_by_username
            ).first()

            if inspector and inspector.office:
                target_usernames.update(
                    user.username
                    for user in _dkss_models.User.query.filter_by(
                        company_code=result_record.company_code,
                        office=inspector.office,
                        role="admin"
                    ).all()
                )

        vehicle = _dkss_models.Vehicle.query.filter_by(
            company_code=result_record.company_code,
            id=result_record.vehicle_record_id
        ).first()

        vehicle_name = (
            " ".join(
                value
                for value in (
                    vehicle.plate_area or "",
                    vehicle.plate_class or "",
                    vehicle.plate_kana or "",
                    vehicle.plate_number or "",
                )
                if value
            )
            if vehicle else ""
        ) or f"車両ID：{result_record.vehicle_record_id}"

        notification_link = _dkss_common.url_for(
            "vehicle_checklist_results",
            index=result_record.checklist_id,
            vehicle_record_id=result_record.vehicle_record_id,
            year=result_record.year,
            month=result_record.month,
            active_day=result_record.day
        ) + (
            f"#vehicle-flow-defect-{result_record.id}-"
            f"{new_defects[0]['defect_no']}"
        )

        item_names = "\n".join(
            f"No.{int(defect['item_no']) + 1} "
            f"{defect.get('reported_answer', {}).get('content') or ''}"
            for defect in new_defects
        )

        for target_username in sorted(target_usernames):
            target_user = _dkss_models.User.query.filter_by(
                company_code=result_record.company_code,
                username=target_username,
                role="admin"
            ).first()

            if not target_user:
                continue

            notification = _dkss_models.Notification(
                company_code=result_record.company_code,
                target_user=(target_user.last_name or "")
                + (target_user.first_name or ""),
                target_username=target_user.username,
                owner_identity=target_user.account_identity,
                title="日常点検の異常報告：" + vehicle_name,
                message=(
                    f"対象車両：{vehicle_name}\n"
                    f"点検日：{result_record.year}/{result_record.month}/{result_record.day}\n"
                    f"異常項目：\n{item_names}\n"
                    "不具合対応と運行可否の判断を確認してください。"
                ),
                link=notification_link,
                files_json="[]",
                read=False,
                created_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC")).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            )
            _dkss_common.db.session.add(notification)

            result_record._pending_defect_notifications = (
                getattr(result_record, "_pending_defect_notifications", [])
                + [(target_user, notification)]
            )

    judgment["defects"] = defects
    judgment["status"] = "未判定"
    judgment["version"] = int(previous.get("version") or 0) + 1

    for key in (
        "reason",
        "judged_by",
        "judged_by_username",
        "judged_at",
        "authority_role",
        "authority_confirmed",
        "checks_confirmed",
        "checks_evidence",
    ):
        judgment.pop(key, None)

    result_record.operation_judgment_json = _dkss_common.json.dumps(
        judgment,
        ensure_ascii=False
    )

    invalidate_other_vehicle_operation_judgments(result_record)

    if previous.get("status") not in (
        "運行可",
        "運行不可",
        "判定保留",
    ):
        return

    vehicle = _dkss_models.Vehicle.query.filter_by(
        company_code=result_record.company_code,
        id=result_record.vehicle_record_id
    ).first()
    vehicle_name = (
        " ".join(
            value for value in (
                vehicle.plate_area or "",
                vehicle.plate_class or "",
                vehicle.plate_kana or "",
                vehicle.plate_number or "",
            ) if value
        ) if vehicle else ""
    ) or f"車両ID：{result_record.vehicle_record_id}"
    notification_link = _dkss_common.url_for(
        "vehicle_checklist_results",
        index=result_record.checklist_id,
        vehicle_record_id=result_record.vehicle_record_id,
        year=result_record.year,
        month=result_record.month,
        active_day=result_record.day
    ) + "#vehicle-flow-judgment"
    recorded_at = _dkss_checklist_common.get_user_local_now(
        result_record.company_code,
        _dkss_common.session.get("username")
    ).strftime("%Y-%m-%d %H:%M:%S")

    for username in sorted(set(previous.get("requested_usernames") or [])):
        target_user = _dkss_models.User.query.filter_by(
            company_code=result_record.company_code,
            username=username,
            role="admin"
        ).first()
        if not target_user:
            continue

        notification = _dkss_models.Notification(
            company_code=result_record.company_code,
            target_user=(target_user.last_name or "") + (target_user.first_name or ""),
            target_username=target_user.username,
            owner_identity=target_user.account_identity,
            title="運行可否の再判定依頼：" + vehicle_name,
            message=(
                f"対象車両：{vehicle_name}\n"
                f"点検日：{result_record.year}/{result_record.month}/{result_record.day}\n"
                "点検内容が変更され、変更前の運行判断は無効になりました。"
                "点検結果と未解消の不具合を確認し、運行可否を再登録してください。"
            ),
            link=notification_link,
            files_json="[]",
            workflow_context_json=_dkss_common.json.dumps(
                _dkss_notifications_delivery.build_notification_workflow_context(
                    result_record,
                    "vehicle",
                    "operation_judgment"
                ),
                ensure_ascii=False
            ),
            read=False,
            created_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC")).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        )
        _dkss_common.db.session.add(notification)
        result_record._pending_defect_notifications = (
            getattr(result_record, "_pending_defect_notifications", [])
            + [(target_user, notification)]
        )

    _dkss_common.db.session.add(_dkss_models.ChecklistEvent(
        company_code=result_record.company_code,
        result_type="vehicle",
        result_id=result_record.id,
        event_type="運行判断",
        actor_username=_dkss_common.session.get("username"),
        actor_name=_dkss_common.session.get("name"),
        detail_json=_dkss_common.json.dumps(
            {
                "previous_judgment": previous,
                "judgment": {
                    **judgment,
                    "reason": "点検内容が変更されたため、再判定が必要です。",
                },
            },
            ensure_ascii=False
        ),
        created_at=_dkss_checklist_common.get_user_local_now(
            result_record.company_code,
            _dkss_common.session.get("username")
        ).strftime("%Y-%m-%d %H:%M:%S")
    ))



def save_vehicle_checklist_one(index):
    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code"),
        active=True
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/vehicle/checklists")

    checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)
    local_now = _dkss_checklist_common.get_user_local_now(
        checklist_record.company_code, _dkss_common.session.get("username")
    )

    if checklist.get("target") != "車両管理":
        return _dkss_common.redirect("/vehicle/checklists")

    company_code = _dkss_common.session.get("company_code")

    vehicle_record_id = _dkss_common.request.form.get(
        "vehicle_record_id",
        type=int
    )

    year = _dkss_common.request.form.get(
        "year",
        ""
    ).strip()

    month = _dkss_common.request.form.get(
        "month",
        ""
    ).strip()

    day = _dkss_common.request.form.get(
        "day",
        ""
    ).strip()

    # 車両検証

    if not vehicle_record_id:
        return _dkss_http.return_form_errors([
            (
                "対象車両を選択してください。",
                "vehicle_record_id"
            )
        ])

    vehicle = _dkss_models.Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return _dkss_http.return_form_errors([
            (
                "対象車両が不正です。",
                "vehicle_record_id"
            )
        ])

    # 日付検証

    try:
        year_int = int(year)
        month_int = int(month)
        day_int = int(day)
    except (TypeError, ValueError):
        return _dkss_http.return_form_errors([
            (
                "点検日が不正です。",
                "year"
            )
        ])

    if year_int < 2000 or year_int > 2100:
        return _dkss_http.return_form_errors([
            (
                "点検年が不正です。",
                "year"
            )
        ])

    if checklist.get("frequency_unit") == "year":
        month_int = 1
        day_int = 1

    elif checklist.get("display_type") == "month":
        if month_int < 1 or month_int > 12:
            return _dkss_http.return_form_errors([
                (
                    "点検月が不正です。",
                    "month"
                )
            ])

        try:
            _dkss_common.datetime(
                year_int,
                month_int,
                day_int
            )
        except ValueError:
            return _dkss_http.return_form_errors([
                (
                    "点検日が不正です。",
                    "day"
                )
            ])

    else:
        if month_int < 1 or month_int > 12:
            return _dkss_http.return_form_errors([
                (
                    "点検月が不正です。",
                    "month"
                )
            ])

        day_int = 1

    year = str(year_int)
    month = str(month_int).zfill(2)
    day = str(day_int).zfill(2)

    if checklist.get("frequency_unit") == "year":
        active_day = year
    elif checklist.get("display_type") == "month":
        active_day = day
    else:
        active_day = month

    item_no_raw = _dkss_common.request.form.get(
        "item_no",
        ""
    ).strip()

    value = _dkss_common.request.form.get(
        "value",
        ""
    )

    lock_error = lock_vehicle_inspection_updates(
        company_code,
        vehicle_record_id=vehicle_record_id,
        checklist=checklist
    )
    if lock_error is not None:
        return lock_error

    result_record = (
        _dkss_models.VehicleChecklistResult.query
        .filter_by(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day
        )
        .with_for_update()
        .first()
    )

    if (
        result_record
        and result_record.status in {
            "承認待ち",
            "承認済み"
        }
    ):
        return _dkss_http.return_form_errors([
            (
                (
                    "承認待ちの点検結果は変更できません。"
                    if result_record.status == "承認待ち"
                    else "承認済みの点検結果は変更できません。"
                ),
                ""
            )
        ], status_code=403)

    result_checklist = _dkss_checklist_common.checklist_for_date(
        checklist,
        year,
        month,
        day
    )

    if (
        result_record
        and result_record.checklist_snapshot_json
    ):
        snapshot = _dkss_serialization.safe_json_dict(
            result_record.checklist_snapshot_json
        )

        if snapshot:
            result_checklist = snapshot

    # チェック項目検証

    try:
        item_no = int(item_no_raw)
    except (TypeError, ValueError):
        return _dkss_http.return_form_errors([
            (
                "チェック項目が不正です。",
                ""
            )
        ])

    check_items = [
        item
        for item in result_checklist.get("items", [])
        if item.get("item_type") == "check"
    ]

    if item_no < 0 or item_no >= len(check_items):
        return _dkss_http.return_form_errors([
            (
                "チェック項目が不正です。",
                ""
            )
        ])

    checklist_item = check_items[item_no]

    # 項目情報はPOST値を信用せず
    # チェックリストマスタから取得
    category = checklist_item.get(
        "category",
        ""
    )

    content = checklist_item.get(
        "content",
        ""
    )

    criteria = checklist_item.get(
        "criteria",
        ""
    )

    # 回答値検証

    input_type = checklist_item.get(
        "input_type",
        ""
    )

    if input_type == "select":
        valid_choices = [
            str(choice)
            for choice in checklist_item.get(
                "choices",
                []
            )
        ]

        if value and value not in valid_choices:
            return _dkss_http.return_form_errors([
                (
                    "回答値が不正です。",
                    f"answer_{item_no}"
                )
            ])

    if not result_record and not value:
        return _dkss_common.jsonify({
            "success": True
        })

    if not result_record:
        result_record = _dkss_models.VehicleChecklistResult(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day,
            checked_by=_dkss_common.session.get("name"),
            checked_by_username=_dkss_common.session.get("username"),
            checked_date=local_now.strftime("%Y-%m-%d %H:%M"),
            status="入力中",
            approved_by="",
            approved_by_username="",
            approved_date="",
            reject_reason="",
            answers_json="[]",
            checklist_snapshot_json=_dkss_common.json.dumps(
                result_checklist,
                ensure_ascii=False
            )
        )

        _dkss_common.db.session.add(result_record)

    answers = _dkss_serialization.safe_json_dict_list(
        result_record.answers_json
    )
    answer = None

    for a in answers:
        if str(a.get("item_no", "")) == str(item_no):
            answer = a
            break

    if not answer:
        answer = {
            "item_no": item_no,
            "category": category,
            "content": content,
            "criteria": criteria,
            "value": "",
            "comment": "",
            "files": []
        }
        answers.append(answer)

    previous_value = answer.get("value", "")

    answer["value"] = value
    answer["category"] = category
    answer["content"] = content
    answer["criteria"] = criteria

    if (
        not value.strip()
        and not str(answer.get("comment") or "").strip()
        and not answer.get("files")
    ):
        answers = [
            stored_answer
            for stored_answer in answers
            if stored_answer is not answer
        ]

    was_rejected = (
        result_record.status == "差し戻し"
    )

    result_record.checked_by = _dkss_common.session.get("name")
    result_record.checked_by_username = _dkss_common.session.get("username")
    result_record.checked_date = local_now.strftime("%Y-%m-%d %H:%M")
    result_record.status = (
        "差し戻し"
        if was_rejected
        else "入力中"
    )

    previous_approvals = _dkss_serialization.safe_json_dict_list(
        result_record.approvals_json
    )

    approvals = []

    for item in result_checklist.get("items", []):
        if item.get("item_type") != "approval":
            continue

        approval_index = len(approvals)

        previous_approval = (
            previous_approvals[approval_index]
            if approval_index < len(previous_approvals)
            else {}
        )

        approvals.append({
            "label": item.get("approval_label", ""),
            "allow_general": item.get("approval_allow_general", False),
            "candidate_usernames": previous_approval.get(
                "candidate_usernames",
                []
            ),
            "approved_by": "",
            "approved_by_username": "",
            "approved_date": "",
        })

    result_record.approved_by = ""
    result_record.approved_by_username = ""
    result_record.approved_date = ""
    result_record.approvals_json = _dkss_common.json.dumps(
        approvals,
        ensure_ascii=False
    )
    if not was_rejected:
        result_record.reject_reason = ""
    result_record.answers_json = _dkss_common.json.dumps(answers, ensure_ascii=False)

    if previous_value != value:
        reset_vehicle_operation_judgment(
            result_record,
            result_checklist
        )

    if was_rejected and previous_value != value:
        checklist_event = _dkss_models.ChecklistEvent(
            company_code=result_record.company_code,
            result_type="vehicle",
            result_id=result_record.id,
            event_type="修正",
            actor_username=_dkss_common.session.get("username"),
            actor_name=_dkss_common.session.get("name"),
            detail_json=_dkss_common.json.dumps(
                {
                    "changes": [
                        {
                            "item_no": item_no,
                            "before": previous_value,
                            "after": value,
                        }
                    ],
                },
                ensure_ascii=False
            ),
            created_at=local_now.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
        _dkss_common.db.session.add(checklist_event)

    try:
        _dkss_common.db.session.commit()
    except _dkss_common.IntegrityError:
        _dkss_common.db.session.rollback()

        return _dkss_http.return_form_errors([
            (
                "同じ点検結果が同時に更新されました。"
                "画面を再読み込みして確認してください。",
                ""
            )
        ], status_code=409)

    dispatch_vehicle_defect_notifications(result_record)

    _dkss_notifications_delivery.notify_mentions(
        value,
        f"/vehicle/checklists/{checklist_record.id}"
        f"?vehicle_record_id={vehicle_record_id}"
        f"&year={year}"
        f"&month={month}"
        f"&active_day={active_day}"
    )

    return _dkss_common.redirect(
        _dkss_common.url_for(
            "vehicle_checklist_results",
            index=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            active_day=active_day,
        )
    )



def save_vehicle_checklist_detail(index):
    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code"),
        active=True
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/vehicle/checklists")

    checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)
    local_now = _dkss_checklist_common.get_user_local_now(
        checklist_record.company_code, _dkss_common.session.get("username")
    )

    if checklist.get("target") != "車両管理":
        return _dkss_common.redirect("/vehicle/checklists")

    company_code = _dkss_common.session.get("company_code")

    vehicle_record_id = _dkss_common.request.form.get(
        "vehicle_record_id",
        type=int
    )

    year = _dkss_common.request.form.get(
        "year",
        ""
    ).strip()

    month = _dkss_common.request.form.get(
        "month",
        ""
    ).strip()

    day = _dkss_common.request.form.get(
        "day",
        ""
    ).strip()

    # 車両検証

    if not vehicle_record_id:
        return _dkss_http.return_form_errors([
            (
                "対象車両を選択してください。",
                "vehicle_record_id"
            )
        ])

    vehicle = _dkss_models.Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return _dkss_http.return_form_errors([
            (
                "対象車両が不正です。",
                "vehicle_record_id"
            )
        ])

    # 日付検証

    try:
        year_int = int(year)
        month_int = int(month)
        day_int = int(day)
    except (TypeError, ValueError):
        return _dkss_http.return_form_errors([
            (
                "点検日が不正です。",
                "detailYear"
            )
        ])

    if year_int < 2000 or year_int > 2100:
        return _dkss_http.return_form_errors([
            (
                "点検年が不正です。",
                "detailYear"
            )
        ])

    if checklist.get("frequency_unit") == "year":
        month_int = 1
        day_int = 1

    elif checklist.get("display_type") == "month":
        if month_int < 1 or month_int > 12:
            return _dkss_http.return_form_errors([
                (
                    "点検月が不正です。",
                    "detailMonth"
                )
            ])

        try:
            _dkss_common.datetime(
                year_int,
                month_int,
                day_int
            )
        except ValueError:
            return _dkss_http.return_form_errors([
                (
                    "点検日が不正です。",
                    "detailDay"
                )
            ])

    else:
        if month_int < 1 or month_int > 12:
            return _dkss_http.return_form_errors([
                (
                    "点検月が不正です。",
                    "detailMonth"
                )
            ])

        day_int = 1

    year = str(year_int)
    month = str(month_int).zfill(2)
    day = str(day_int).zfill(2)

    item_no_raw = _dkss_common.request.form.get(
        "item_no",
        ""
    ).strip()

    if checklist.get("frequency_unit") == "year":
        active_day = year
    elif checklist.get("display_type") == "month":
        active_day = day
    else:
        active_day = month

    comment = _dkss_common.request.form.get(
        "comment",
        ""
    ).strip()

    uploaded_files = [
        file
        for file in _dkss_common.request.files.getlist("files")
        if file and file.filename
    ]

    if len(comment) > 5000:
        return _dkss_http.return_form_errors([
            (
                "コメントは5000文字以内で入力してください。",
                "detailCommentEditor"
            )
        ])

    lock_error = lock_vehicle_inspection_updates(
        company_code,
        vehicle_record_id=vehicle_record_id,
        checklist=checklist
    )
    if lock_error is not None:
        return lock_error

    result_record = (
        _dkss_models.VehicleChecklistResult.query
        .filter_by(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day
        )
        .with_for_update()
        .first()
    )

    if (
        result_record
        and result_record.status in {
            "承認待ち",
            "承認済み"
        }
    ):
        return _dkss_http.return_form_errors([
            (
                (
                    "承認待ちの点検結果は変更できません。"
                    if result_record.status == "承認待ち"
                    else "承認済みの点検結果は変更できません。"
                ),
                ""
            )
        ], status_code=403)

    result_checklist = _dkss_checklist_common.checklist_for_date(
        checklist,
        year,
        month,
        day
    )

    if (
        result_record
        and result_record.checklist_snapshot_json
    ):
        snapshot = _dkss_serialization.safe_json_dict(
            result_record.checklist_snapshot_json
        )

        if snapshot:
            result_checklist = snapshot

    # チェック項目検証

    try:
        item_no = int(item_no_raw)
    except (TypeError, ValueError):
        return _dkss_http.return_form_errors([
            (
                "チェック項目が不正です。",
                "detailItemNo"
            )
        ])

    check_items = [
        item
        for item in result_checklist.get("items", [])
        if item.get("item_type") == "check"
    ]

    if item_no < 0 or item_no >= len(check_items):
        return _dkss_http.return_form_errors([
            (
                "チェック項目が不正です。",
                "detailItemNo"
            )
        ])

    checklist_item = check_items[item_no]

    category = checklist_item.get(
        "category",
        ""
    )

    content = checklist_item.get(
        "content",
        ""
    )

    criteria = checklist_item.get(
        "criteria",
        ""
    )



    if (
        not result_record
        and not comment
        and not uploaded_files
    ):
        return _dkss_common.jsonify({
            "success": True
        })

    if not result_record:
        result_record = _dkss_models.VehicleChecklistResult(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day,
            checked_by=_dkss_common.session.get("name"),
            checked_by_username=_dkss_common.session.get("username"),
            checked_date=local_now.strftime("%Y-%m-%d %H:%M"),
            status="入力中",
            approved_by="",
            approved_by_username="",
            approved_date="",
            reject_reason="",
            answers_json="[]",
            checklist_snapshot_json=_dkss_common.json.dumps(
                result_checklist,
                ensure_ascii=False
            )
        )
        _dkss_common.db.session.add(result_record)

    answers = _dkss_serialization.safe_json_dict_list(
        result_record.answers_json
    )

    answer = None

    for a in answers:
        if str(a.get("item_no", "")) == str(item_no):
            answer = a
            break

    if not answer:
        answer = {
            "category": category,
            "item_no": item_no,
            "content": content,
            "criteria": criteria,
            "value": "",
            "comment": "",
            "files": []
        }
        answers.append(answer)

    if len(uploaded_files) > 50:
        return _dkss_http.return_form_errors([
            (
                "一度にアップロードできるファイルは50件までです。",
                "detailPreview"
            )
        ])

    answer.setdefault("files", [])

    previous_files = list(
        answer.get("files", [])
    )

    for file in uploaded_files:
        original_filename = _dkss_common.os.path.basename(
            str(file.filename or "")
        )

        extension = _dkss_common.os.path.splitext(
            original_filename
        )[1].lower()

        if (
            extension not in _dkss_common.ALLOWED_UPLOAD_EXTENSIONS
            or not _dkss_storage.is_valid_uploaded_file(
                file,
                extension
            )
        ):
            return _dkss_http.return_form_errors([
                (
                    "添付ファイルの検証に失敗しました。",
                    "detailPreview"
                )
            ])

    saved_filenames = []

    for file in uploaded_files:
        try:
            filename = _dkss_storage.save_uploaded_file(file)
        except _dkss_common.UploadValidationError:
            for saved_filename in saved_filenames:
                _dkss_storage.delete_uploaded_file(saved_filename)

            return _dkss_http.return_form_errors([
                (
                    "添付ファイルの検証に失敗しました。",
                    "detailPreview"
                )
            ])

        if filename:
            saved_filenames.append(filename)
            answer["files"].append(filename)

    previous_comment = answer.get("comment", "")

    answer["comment"] = comment
    answer["category"] = category
    answer["content"] = content
    answer["criteria"] = criteria

    answer_value = answer.get("value", "")

    if (
        (answer_value is None or not str(answer_value).strip())
        and not comment
        and not answer.get("files")
    ):
        answers = [
            stored_answer
            for stored_answer in answers
            if stored_answer is not answer
        ]

    was_rejected = (
        result_record.status == "差し戻し"
    )

    previous_approvals = _dkss_serialization.safe_json_dict_list(
        result_record.approvals_json
    )

    approvals = []

    for item in result_checklist.get("items", []):
        if item.get("item_type") != "approval":
            continue

        approval_index = len(approvals)

        previous_approval = (
            previous_approvals[approval_index]
            if approval_index < len(previous_approvals)
            else {}
        )

        approvals.append({
            "label": item.get("approval_label", ""),
            "allow_general": item.get("approval_allow_general", False),
            "candidate_usernames": previous_approval.get(
                "candidate_usernames",
                []
            ),
            "approved_by": "",
            "approved_by_username": "",
            "approved_date": "",
        })

    result_record.checked_by = _dkss_common.session.get("name")
    result_record.checked_by_username = _dkss_common.session.get("username")
    result_record.checked_date = local_now.strftime("%Y-%m-%d %H:%M")
    result_record.status = (
        "差し戻し"
        if was_rejected
        else "入力中"
    )
    result_record.approved_by = ""
    result_record.approved_by_username = ""
    result_record.approved_date = ""
    result_record.approvals_json = _dkss_common.json.dumps(
        approvals,
        ensure_ascii=False
    )
    if not was_rejected:
        result_record.reject_reason = ""
    result_record.answers_json = _dkss_common.json.dumps(answers, ensure_ascii=False)

    if (
        previous_comment != comment
        or previous_files != answer.get("files", [])
    ):
        reset_vehicle_operation_judgment(
            result_record,
            result_checklist
        )

    if (
        was_rejected
        and (
            previous_comment != comment
            or previous_files != answer.get("files", [])
        )
    ):
        checklist_event = _dkss_models.ChecklistEvent(
            company_code=result_record.company_code,
            result_type="vehicle",
            result_id=result_record.id,
            event_type="修正",
            actor_username=_dkss_common.session.get("username"),
            actor_name=_dkss_common.session.get("name"),
            detail_json=_dkss_common.json.dumps(
                {
                    "changes": [
                        *(
                            [
                                {
                                    "item_no": item_no,
                                    "field": "comment",
                                    "before": previous_comment,
                                    "after": comment,
                                }
                            ]
                            if previous_comment != comment
                            else []
                        ),
                        *(
                            [
                                {
                                    "item_no": item_no,
                                    "field": "files",
                                    "before": previous_files,
                                    "after": answer.get("files", []),
                                }
                            ]
                            if previous_files != answer.get("files", [])
                            else []
                        ),
                    ],
                },
                ensure_ascii=False
            ),
            created_at=local_now.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
        _dkss_common.db.session.add(checklist_event)

    try:
        _dkss_common.db.session.commit()
    except _dkss_common.IntegrityError:
        _dkss_common.db.session.rollback()

        for filename in saved_filenames:
            _dkss_storage.delete_uploaded_file(filename)

        return _dkss_http.return_form_errors([
            (
                "同じ点検結果が同時に更新されました。"
                "画面を再読み込みして確認してください。",
                ""
            )
        ], status_code=409)

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()

        for filename in saved_filenames:
            _dkss_storage.delete_uploaded_file(filename)

        return _dkss_http.return_form_errors([
            (
                "車両チェックリストの更新に失敗しました。"
                "もう一度お試しください。",
                ""
            )
        ], status_code=500)

    dispatch_vehicle_defect_notifications(result_record)

    _dkss_notifications_delivery.notify_mentions(
        comment,
        f"/vehicle/checklists/{checklist_record.id}?vehicle_record_id={vehicle_record_id}&year={year}&month={month}&active_day={active_day}"
    )

    return _dkss_common.redirect(
        _dkss_common.url_for(
            "vehicle_checklist_results",
            index=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            active_day=active_day,
        )
    )



def complete_vehicle_checklist(index):
    company_code = _dkss_common.session.get("company_code")

    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=index,
        company_code=company_code,
        active=True
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/vehicle/checklists")

    checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)
    local_now = _dkss_checklist_common.get_user_local_now(
        checklist_record.company_code, _dkss_common.session.get("username")
    )

    if checklist.get("target") != "車両管理":
        return _dkss_common.redirect("/vehicle/checklists")

    vehicle_record_id = _dkss_common.request.form.get(
        "vehicle_record_id",
        type=int
    )

    year = _dkss_common.request.form.get(
        "year",
        ""
    ).strip()

    month = _dkss_common.request.form.get(
        "month",
        ""
    ).strip()

    day = _dkss_common.request.form.get(
        "day",
        ""
    ).strip()

    if checklist.get("frequency_unit") == "year":
        active_day = year
    elif checklist.get("display_type") == "month":
        active_day = day
    else:
        active_day = month

    # 車両検証

    if not vehicle_record_id:
        return _dkss_http.return_form_errors([
            (
                "対象車両を選択してください。",
                "vehicle_record_id"
            )
        ])

    vehicle = _dkss_models.Vehicle.query.filter_by(
        company_code=company_code,
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return _dkss_http.return_form_errors([
            (
                "対象車両が不正です。",
                "vehicle_record_id"
            )
        ])

    # 日付検証

    try:
        year_int = int(year)
        month_int = int(month)
        day_int = int(day)
    except (TypeError, ValueError):
        return _dkss_http.return_form_errors([
            (
                "点検日が不正です。",
                "year"
            )
        ])

    if year_int < 2000 or year_int > 2100:
        return _dkss_http.return_form_errors([
            (
                "点検年が不正です。",
                "year"
            )
        ])

    if checklist.get("frequency_unit") == "year":
        month_int = 1
        day_int = 1

    elif checklist.get("display_type") == "month":
        if month_int < 1 or month_int > 12:
            return _dkss_http.return_form_errors([
                (
                    "点検月が不正です。",
                    "month"
                )
            ])

        try:
            _dkss_common.datetime(
                year_int,
                month_int,
                day_int
            )
        except ValueError:
            return _dkss_http.return_form_errors([
                (
                    "点検日が不正です。",
                    "day"
                )
            ])

    else:
        if month_int < 1 or month_int > 12:
            return _dkss_http.return_form_errors([
                (
                    "点検月が不正です。",
                    "month"
                )
            ])

        day_int = 1

    year = str(year_int)
    month = str(month_int).zfill(2)
    day = str(day_int).zfill(2)

    lock_error = lock_vehicle_inspection_updates(
        company_code,
        vehicle_record_id=vehicle_record_id,
        checklist=checklist
    )
    if lock_error is not None:
        return lock_error

    # 結果取得

    result_record = (
        _dkss_models.VehicleChecklistResult.query
        .filter_by(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day
        )
        .with_for_update()
        .first()
    )

    if not result_record:
        result_record = _dkss_models.VehicleChecklistResult(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day,
            checked_by=_dkss_common.session.get("name"),
            checked_by_username=_dkss_common.session.get("username"),
            checked_date=local_now.strftime("%Y-%m-%d %H:%M"),
            status="入力中",
            approved_by="",
            approved_by_username="",
            approved_date="",
            reject_reason="",
            answers_json="[]",
            checklist_snapshot_json=_dkss_common.json.dumps(
                _dkss_checklist_common.checklist_for_date(
                    checklist,
                    year,
                    month,
                    day
                ),
                ensure_ascii=False
            )
        )

        _dkss_common.db.session.add(result_record)

    if result_record.status in {"承認待ち", "承認済み", "点検完了"}:
        return _dkss_http.return_form_errors([
            ({
                "承認待ち": "すでに承認待ちです。",
                "承認済み": "すでに承認済みです。",
                "点検完了": "すでに点検完了しています。",
            }[result_record.status], "")
        ], status_code=409)

    result_checklist = _dkss_checklist_common.checklist_for_date(
        checklist,
        year,
        month,
        day
    )

    if result_record.checklist_snapshot_json:
        snapshot = _dkss_serialization.safe_json_dict(
            result_record.checklist_snapshot_json
        )

        if snapshot:
            result_checklist = snapshot
    else:
        result_record.checklist_snapshot_json = _dkss_common.json.dumps(
            result_checklist,
            ensure_ascii=False
        )

    answers = _dkss_serialization.safe_json_dict_list(
        result_record.answers_json
    )

    check_items = [
        item
        for item in result_checklist.get("items", [])
        if item.get("item_type") == "check"
    ]

    answers_by_item_no = {}

    for answer in answers:
        try:
            answer_item_no = int(
                answer.get("item_no")
            )
        except (TypeError, ValueError):
            continue

        answers_by_item_no[answer_item_no] = answer

    for item_no, item in enumerate(check_items):
        answer = answers_by_item_no.get(item_no, {})

        value = str(
            answer.get("value", "")
            or ""
        ).strip()

        comment = str(
            answer.get("comment", "")
            or ""
        ).strip()

        if item.get("input_type") == "select":
            valid_choices = [
                str(choice)
                for choice in item.get(
                    "choices",
                    []
                )
            ]

            if value and value not in valid_choices:
                return _dkss_http.return_form_errors([
                    (
                        "回答値が不正です。",
                        f"answer_{item_no}"
                    )
                ])

        if (
            item.get("answer_required")
            and not value
        ):
            return _dkss_http.return_form_errors([
                (
                    "必須項目が未回答です。",
                    f"answer_{item_no}"
                )
            ])

        if len(comment) > 5000:
            return _dkss_http.return_form_errors([
                (
                    "コメントは5000文字以内で入力してください。",
                    f"comment_{item_no}"
                )
            ])

    # 通知先ユーザー検証

    notify_usernames = [
        username.strip()
        for username in _dkss_common.request.form.getlist(
            "notify_users"
        )
        if username.strip()
    ]

    if len(notify_usernames) > 500:
        return _dkss_http.return_form_errors([
            (
                "通知先ユーザー数が多すぎます。",
                "notify_user_search"
            )
        ])

    valid_users = {
        user.username: user
        for user in _dkss_models.User.query.filter_by(
            company_code=company_code
        ).all()
        if user.username
    }

    for username in notify_usernames:
        if username not in valid_users:
            return _dkss_http.return_form_errors([
                (
                    "通知先ユーザーが不正です。",
                    "notify_user_search"
                )
            ])

    notify_usernames = list(
        dict.fromkeys(notify_usernames)
    )

    if not notify_usernames:
        notify_usernames = (
            _dkss_checklist_notifications.get_vehicle_checklist_notify_users(
                company_code,
                checklist_record.id,
                vehicle_record_id
            )
        )

    notify_usernames = [
        username
        for username in notify_usernames
        if username in valid_users
    ]

    if (
        not notify_usernames
        and _dkss_common.session.get("username") in valid_users
    ):
        notify_usernames = [
            _dkss_common.session.get("username")
        ]

    if any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in result_checklist.get("items", [])
    ):
        notify_usernames = []

    # 完了処理

    result_record.checked_by = _dkss_common.session.get("name")
    result_record.checked_by_username = _dkss_common.session.get("username")
    result_record.checked_date = (
        local_now.strftime("%Y-%m-%d %H:%M")
    )

    approvals = []

    for item in result_checklist.get("items", []):
        if item.get("item_type") != "approval":
            continue

        approval_index = len(approvals)

        submitted_candidate_usernames = [
            username.strip()
            for username in _dkss_common.request.form.getlist(
                f"approval_notify_users_{approval_index}"
            )
            if username.strip()
        ]

        if len(submitted_candidate_usernames) > 500:
            return _dkss_http.return_form_errors([
                (
                    "承認候補者数が多すぎます。",
                    f"approval_user_search_{approval_index}"
                )
            ])

        invalid_candidate_usernames = [
            username
            for username in submitted_candidate_usernames
            if (
                username not in valid_users
                or not (
                    valid_users[username].role == "admin"
                    or (
                        item.get(
                            "approval_allow_general",
                            False
                        )
                        and valid_users[username].role == "user"
                    )
                )
            )
        ]

        if invalid_candidate_usernames:
            return _dkss_http.return_form_errors([
                (
                    "承認者の選択内容が不正です。",
                    f"approval_user_search_{approval_index}"
                )
            ])

        candidate_usernames = list(
            dict.fromkeys(
                submitted_candidate_usernames
            )
        )

        approvals.append({
            "label": item.get("approval_label", ""),
            "allow_general": item.get(
                "approval_allow_general",
                False
            ),
            "candidate_usernames": candidate_usernames,
            "approved_by": "",
            "approved_by_username": "",
            "approved_date": "",
        })

    if any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in result_checklist.get("items", [])
    ):
        existing_defects = _dkss_serialization.safe_json_dict(
            result_record.operation_judgment_json
        ).get("defects") or []

        has_unregistered_defect = any(
            str(answer.get("value") or "").strip() == "×"
            and str(answer.get("item_no", ""))
            and not any(
                str(defect.get("item_no", ""))
                == str(answer.get("item_no", ""))
                and (
                    defect.get("status") != "解消"
                    or all(
                        defect.get("rechecked_answer", {}).get(field)
                        == answer.get(field)
                        for field in ("value", "comment", "files")
                    )
                )
                for defect in existing_defects
            )
            for answer in answers
        )

        if has_unregistered_defect:
            reset_vehicle_operation_judgment(
                result_record,
                result_checklist
            )

        approval_items = [
            item
            for item in result_checklist.get("items", [])
            if item.get("item_type") == "approval"
        ]
        judgment = _dkss_serialization.safe_json_dict(result_record.operation_judgment_json)
        judgment.setdefault("status", "未判定")
        judgment["requested_usernames"] = []

        for approval_index, item in enumerate(approval_items):
            if item.get("item_code") == "footer_30":
                previous_requested_usernames = _dkss_serialization.safe_json_dict(
                    result_record.operation_judgment_json
                ).get("requested_usernames", [])

                next_requested_usernames = approvals[
                    approval_index
                ].get("candidate_usernames", [])

                if set(previous_requested_usernames) != set(
                    next_requested_usernames
                ):
                    judgment["version"] = int(
                        judgment.get("version") or 0
                    ) + 1

                judgment["requested_usernames"] = list(
                    approvals[approval_index].get("candidate_usernames", [])
                )
                break

        result_record.operation_judgment_json = _dkss_common.json.dumps(
            judgment,
            ensure_ascii=False
        )

    has_system_approval = bool(approvals)

    was_rejected = (
        result_record.status == "差し戻し"
    )

    result_record.status = (
        "承認待ち"
        if has_system_approval
        else "点検完了"
    )
    result_record.approved_by = ""
    result_record.approved_by_username = ""
    result_record.approved_date = ""
    result_record.approvals_json = _dkss_common.json.dumps(
        approvals,
        ensure_ascii=False
    )
    result_record.reject_reason = ""

    result_record.notify_users_json = _dkss_common.json.dumps(
        notify_usernames,
        ensure_ascii=False
    )

    if was_rejected:
        checklist_event = _dkss_models.ChecklistEvent(
            company_code=result_record.company_code,
            result_type="vehicle",
            result_id=result_record.id,
            event_type="再申請",
            actor_username=_dkss_common.session.get("username"),
            actor_name=_dkss_common.session.get("name"),
            detail_json=_dkss_common.json.dumps(
                {
                    "approvals": approvals,
                },
                ensure_ascii=False
            ),
            created_at=local_now.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
        _dkss_common.db.session.add(checklist_event)

    _dkss_common.db.session.commit()
    dispatch_vehicle_defect_notifications(result_record)

    # 通知

    notification_link = _dkss_common.url_for(
        "vehicle_checklist_results",
        index=checklist_record.id,
        vehicle_record_id=vehicle_record_id,
        year=year,
        month=month,
        active_day=active_day,
    )

    first_approval = (
        approvals[0]
        if has_system_approval and approvals
        else {}
    )
    approval_usernames = set(
        first_approval.get("candidate_usernames") or []
    )
    notification_usernames = set(approval_usernames)

    if was_rejected and not has_system_approval:
        latest_rejection = _dkss_models.ChecklistEvent.query.filter_by(
            company_code=company_code,
            result_type="vehicle",
            result_id=result_record.id,
            event_type="差し戻し"
        ).order_by(
            _dkss_models.ChecklistEvent.id.desc()
        ).first()

        if latest_rejection and latest_rejection.actor_username:
            notification_usernames.add(
                latest_rejection.actor_username
            )

    for target_username in sorted(notification_usernames):
        target_user = valid_users.get(target_username)

        if not target_user:
            continue

        is_approval_recipient = (
            target_username in approval_usernames
        )

        if was_rejected:
            notification_title = (
                "車両チェックリスト再申請の承認依頼"
                if is_approval_recipient
                else "車両チェックリスト修正・再申請のお知らせ"
            )
            notification_message = (
                f"「{checklist_record.name}」が"
                "修正・再申請されました。"
                + (
                    "承認をお願いします。"
                    if is_approval_recipient
                    else "変更内容を確認してください。"
                )
            )
        else:
            notification_title = "車両チェックリスト承認依頼"
            notification_message = (
                f"「{checklist_record.name}」"
                "の承認をお願いします。"
            )

        _dkss_notifications_delivery.add_notification(
            (target_user.last_name or "")
            + (target_user.first_name or ""),
            notification_title,
            notification_message,
            notification_link,
            company_code=company_code,
            target_identity=target_user.account_identity,
            target_username=target_user.username,
            workflow_context=(
                _dkss_notifications_delivery.build_notification_workflow_context(
                    result_record,
                    "vehicle",
                    "approval",
                    approval_index=0
                )
                if is_approval_recipient
                else None
            )
        )

    if not has_system_approval:
        for target_username in notify_usernames:
            target_user = valid_users[target_username]

            _dkss_notifications_delivery.add_notification(
                (target_user.last_name or "") + (target_user.first_name or ""),
                "車両点検完了のお知らせ",
                (
                    f"{' '.join(value for value in [vehicle.plate_area or '', vehicle.plate_class or '', vehicle.plate_kana or '', vehicle.plate_number or ''] if value) or 'ナンバー未登録'} の"
                    f"「{checklist_record.name}」が"
                    "点検完了しました。"
                ),
                notification_link,
                company_code=company_code,
                target_identity=target_user.account_identity,
                target_username=target_user.username
            )

    completion_link = notification_link
    if any(
        item.get("fixed_template_code") == "daily_inspection_truck_trailer"
        for item in result_checklist.get("items", [])
    ):
        completion_link = _dkss_common.url_for(
            "vehicle_checklist_results",
            index=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            active_day=active_day,
            vehicle_saved="complete"
        ) + "#vehicle-flow-completed"

    if _dkss_common.request.headers.get("X-DKSS-Final-Submit") == "1":
        return _dkss_common.jsonify({"success": True, "redirect_url": completion_link})

    return _dkss_common.redirect(completion_link)



def new_vehicle_checklist_result(index):
    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code"),
        active=True
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/vehicle/checklists")

    checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)
    local_now = _dkss_checklist_common.get_user_local_now(
        checklist_record.company_code, _dkss_common.session.get("username")
    )

    if checklist["target"] != "車両管理":
        return _dkss_common.redirect("/vehicle/checklists")

    if _dkss_common.request.method == "POST":
        lock_error = lock_vehicle_inspection_updates(
            _dkss_common.session.get("company_code"),
            vehicle_record_id=_dkss_common.request.form.get("vehicle_record_id", type=int),
            checklist=checklist
        )
        if lock_error is not None:
            return lock_error
        company_code = _dkss_common.session.get("company_code")

        vehicle_record_id = _dkss_common.request.form.get(
            "vehicle_record_id",
            type=int
        )

        year = _dkss_common.request.form.get(
            "year",
            ""
        ).strip()

        month = _dkss_common.request.form.get(
            "month",
            ""
        ).strip()

        day = _dkss_common.request.form.get(
            "day",
            ""
        ).strip()

        # 車両検証

        if not vehicle_record_id:
            return _dkss_http.return_form_errors([
                (
                    "対象車両を選択してください。",
                    "vehicle_record_id"
                )
            ])

        vehicle = _dkss_models.Vehicle.query.filter_by(
            company_code=company_code,
            id=vehicle_record_id,
            deleted=False
        ).first()

        if not vehicle:
            return _dkss_http.return_form_errors([
                (
                    "対象車両が不正です。",
                    "vehicle_record_id"
                )
            ])

        # 日付検証

        try:
            year_int = int(year)
            month_int = int(month)
            day_int = int(day)
        except (TypeError, ValueError):
            return _dkss_http.return_form_errors([
                (
                    "点検日が不正です。",
                    "year"
                )
            ])

        if year_int < 2000 or year_int > 2100:
            return _dkss_http.return_form_errors([
                (
                    "点検年が不正です。",
                    "year"
                )
            ])

        # 年次チェックリスト
        if checklist.get("frequency_unit") == "year":
            month_int = 1
            day_int = 1

        # 日単位表示
        elif checklist.get("display_type") == "month":
            if month_int < 1 or month_int > 12:
                return _dkss_http.return_form_errors([
                    (
                        "点検月が不正です。",
                        "month"
                    )
                ])

            try:
                _dkss_common.datetime(
                    year_int,
                    month_int,
                    day_int
                )
            except ValueError:
                return _dkss_http.return_form_errors([
                    (
                        "点検日が不正です。",
                        "day"
                    )
                ])

        # 月単位など
        else:
            if month_int < 1 or month_int > 12:
                return _dkss_http.return_form_errors([
                    (
                        "点検月が不正です。",
                        "month"
                    )
                ])

            day_int = 1

        year = str(year_int)
        month = str(month_int).zfill(2)
        day = str(day_int).zfill(2)

        checklist = _dkss_checklist_common.checklist_for_date(
            checklist,
            year,
            month,
            day
        )

        existing_result = _dkss_models.VehicleChecklistResult.query.filter_by(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day
        ).first()

        if existing_result:
            return _dkss_common.redirect(
                _dkss_common.url_for(
                    "vehicle_checklist_results",
                    index=checklist_record.id,
                    vehicle_record_id=vehicle_record_id,
                    year=year,
                    month=month,
                    active_day=day,
                )
            )

        answers = []
        answer_index = 0
        pending_answer_files = []

        for item in checklist["items"]:
            if item.get("item_type") != "check":
                continue

            value = _dkss_common.request.form.get(
                f"answer_{answer_index}",
                ""
            )

            input_type = item.get(
                "input_type",
                ""
            )

            # 回答値検証

            if input_type == "select":
                valid_choices = [
                    str(choice)
                    for choice in item.get(
                        "choices",
                        []
                    )
                ]

                if value and value not in valid_choices:
                    return _dkss_http.return_form_errors([
                        (
                            "回答値が不正です。",
                            f"answer_{answer_index}"
                        )
                    ])



            comment = _dkss_common.request.form.get(
                f"comment_{answer_index}",
                ""
            ).strip()

            if (
                item.get("answer_required")
                and not value
            ):
                return _dkss_http.return_form_errors([
                    (
                        "必須項目が未回答です。",
                        f"answer_{answer_index}"
                    )
                ])

            if len(comment) > 5000:
                return _dkss_http.return_form_errors([
                    (
                        "コメントは5000文字以内で入力してください。",
                        f"comment_{answer_index}"
                    )
                ])

            item_index = len(answers)

            answers.append({
                "item_no": answer_index,
                "category": item.get("category", ""),
                "content": item.get("content", ""),
                "criteria": item.get("criteria", ""),
                "value": value,
                "comment": comment,
                "files": []
            })

            pending_answer_files.append(
                (item_index, answer_index)
            )

            answer_index += 1

        pending_uploads = []

        upload_file_count = sum(
            1
            for field_name in _dkss_common.request.files.keys()
            for file in _dkss_common.request.files.getlist(field_name)
            if file and file.filename
        )

        if upload_file_count > 50:
            return _dkss_http.return_form_errors([
                (
                    "一度にアップロードできるファイルは50件までです。",
                    ""
                )
            ])

        for item_index, form_index in pending_answer_files:
            for file in _dkss_common.request.files.getlist(
                f"files_{form_index}"
            ):
                if not file or not file.filename:
                    continue

                original_filename = _dkss_common.os.path.basename(
                    str(file.filename or "")
                )

                extension = _dkss_common.os.path.splitext(
                    original_filename
                )[1].lower()

                if (
                    extension not in _dkss_common.ALLOWED_UPLOAD_EXTENSIONS
                    or not _dkss_storage.is_valid_uploaded_file(
                        file,
                        extension
                    )
                ):
                    return _dkss_http.return_form_errors([
                        (
                            "添付ファイルの検証に失敗しました。",
                            f"files_{form_index}"
                        )
                    ])

                pending_uploads.append(
                    (item_index, file)
                )

        valid_users = {
            user.username: user
            for user in _dkss_models.User.query.filter_by(
                company_code=company_code
            ).all()
            if user.username
        }

        approvals = []

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approval_index = len(approvals)

            submitted_candidate_usernames = [
                username.strip()
                for username in _dkss_common.request.form.getlist(
                    f"approval_notify_users_{approval_index}"
                )
                if username.strip()
            ]

            if len(submitted_candidate_usernames) > 500:
                return _dkss_http.return_form_errors([
                    (
                        "承認候補者数が多すぎます。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            invalid_candidate_usernames = [
                username
                for username in submitted_candidate_usernames
                if (
                    username not in valid_users
                    or not (
                        valid_users[username].role == "admin"
                        or (
                            item.get(
                                "approval_allow_general",
                                False
                            )
                            and valid_users[username].role == "user"
                        )
                    )
                )
            ]

            if invalid_candidate_usernames:
                return _dkss_http.return_form_errors([
                    (
                        "承認者の選択内容が不正です。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            candidate_usernames = list(
                dict.fromkeys(
                    submitted_candidate_usernames
                )
            )

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get(
                    "approval_allow_general",
                    False
                ),
                "candidate_usernames": (
                    candidate_usernames
                ),
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        has_system_approval = bool(approvals)

        notify_usernames = (
            _dkss_checklist_notifications.get_vehicle_checklist_notify_users(
                company_code,
                checklist_record.id,
                vehicle_record_id
            )
        )

        saved_filenames = []

        for item_index, file in pending_uploads:
            try:
                filename = _dkss_storage.save_uploaded_file(file)
            except _dkss_common.UploadValidationError:
                for saved_filename in saved_filenames:
                    _dkss_storage.delete_uploaded_file(saved_filename)

                return _dkss_http.return_form_errors([
                    (
                        "添付ファイルの検証に失敗しました。",
                        ""
                    )
                ])

            if filename:
                saved_filenames.append(filename)

                answers[item_index]["files"].append(
                    filename
                )

        answers = [
            answer
            for answer in answers
            if str(answer.get("value", "")).strip()
            or str(answer.get("comment", "")).strip()
            or answer.get("files")
        ]

        result = _dkss_models.VehicleChecklistResult(
            company_code=company_code,
            checklist_id=checklist_record.id,
            vehicle_record_id=vehicle_record_id,
            year=year,
            month=month,
            day=day,
            checked_by=_dkss_common.session.get("name"),
            checked_by_username=_dkss_common.session.get("username"),
            checked_date=local_now.strftime("%Y-%m-%d %H:%M"),
            status=(
                "承認待ち"
                if has_system_approval
                else "点検完了"
            ),
            approved_by="",
            approved_by_username="",
            approved_date="",
            reject_reason="",
            approvals_json=_dkss_common.json.dumps(
                approvals,
                ensure_ascii=False
            ),
            notify_users_json=_dkss_common.json.dumps(
                notify_usernames,
                ensure_ascii=False
            ),
            answers_json=_dkss_common.json.dumps(
                answers,
                ensure_ascii=False
            ),
            checklist_snapshot_json=_dkss_common.json.dumps(
                checklist,
                ensure_ascii=False
            )
        )

        _dkss_common.db.session.add(result)

        try:
            _dkss_common.db.session.commit()
        except _dkss_common.IntegrityError:
            _dkss_common.db.session.rollback()

            for filename in saved_filenames:
                _dkss_storage.delete_uploaded_file(filename)

            return _dkss_http.return_form_errors([
                (
                    "同じ車両・点検日の結果が同時に登録されました。"
                    "画面を再読み込みして確認してください。",
                    ""
                )
            ], status_code=409)

        except _dkss_common.SQLAlchemyError:
            _dkss_common.db.session.rollback()

            for filename in saved_filenames:
                _dkss_storage.delete_uploaded_file(filename)

            return _dkss_http.return_form_errors([
                (
                    "車両チェックリストの保存に失敗しました。"
                    "もう一度お試しください。",
                    ""
                )
            ], status_code=500)

        if has_system_approval and approvals:
            first_approval = approvals[0]

            for username in (
                first_approval.get(
                    "candidate_usernames",
                    []
                )
                if first_approval
                else []
            ):
                target_user = valid_users.get(username)

                if not target_user:
                    continue

                _dkss_notifications_delivery.add_notification(
                    target_user=(target_user.last_name or "")
                    + (target_user.first_name or ""),
                    company_code=company_code,
                    target_identity=target_user.account_identity,
                    target_username=username,
                    title="車両チェックリスト承認依頼",
                    workflow_context=_dkss_notifications_delivery.build_notification_workflow_context(
                        result,
                        "vehicle",
                        "approval",
                        approval_index=0
                    ),
                    message=(
                        f"「{checklist.get('name', '車両チェックリスト')}」"
                        "の承認をお願いします。"
                    ),
                    link=_dkss_common.url_for(
                        "vehicle_checklist_results",
                        index=checklist_record.id,
                        vehicle_record_id=vehicle_record_id,
                        year=year,
                        month=month,
                        active_day=day,
                    ),
                )

        if not has_system_approval:
            for target_username in notify_usernames:
                target_user = valid_users.get(
                    target_username
                )

                if not target_user:
                    continue

                _dkss_notifications_delivery.add_notification(
                    (
                        (target_user.last_name or "")
                        + (target_user.first_name or "")
                    ),
                    "車両点検完了のお知らせ",
                    (
                        f"「{checklist_record.name}」が"
                        "点検完了しました。"
                    ),
                    _dkss_common.url_for(
                        "vehicle_checklist_results",
                        index=checklist_record.id,
                        vehicle_record_id=vehicle_record_id,
                        year=year,
                        month=month,
                        active_day=day,
                    ),
                    company_code=company_code,
                    target_identity=target_user.account_identity,
                    target_username=target_user.username
                )

        mention_text = "\n".join(
            "\n".join([
                answer.get("value", "") or "",
                answer.get("comment", "") or "",
            ])
            for answer in answers
        )

        _dkss_notifications_delivery.notify_mentions(
            mention_text,
            f"/vehicle/checklists/{checklist_record.id}"
        )

        return _dkss_common.redirect(
            _dkss_common.url_for(
                "vehicle_checklist_results",
                index=checklist_record.id,
                vehicle_record_id=vehicle_record_id,
                year=year,
                month=month,
            )
        )

    return _dkss_common.render_template(
        "vehicle_checklist_form.html",
        checklist=checklist,
        checklist_index=checklist_record.id,
        mode="new",
        now_year=local_now.year,
        now_month=local_now.month,
        now_day=local_now.day
    )



def new_safety_checklist_result(index):
    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code"),
        active=True
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/safety/checklists")

    checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)

    if _dkss_common.request.method == "POST":
        company_code = _dkss_common.session.get("company_code")
        operation_now = _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo"))
        answers = []
        answer_index = 0

        target_type = _dkss_common.request.form.get(
            "target_type",
            ""
        ).strip()

        target_user = _dkss_common.request.form.get(
            "target_user",
            ""
        ).strip()

        target_username = ""

        target_vehicle_record_id = _dkss_common.request.form.get(
            "target_vehicle_record_id",
            type=int
        )

        target_office = _dkss_common.request.form.get(
            "target_office",
            ""
        ).strip()

        # 対象種別検証

        if target_type not in {
            "",
            "user",
            "vehicle",
            "office"
        }:
            return _dkss_http.return_form_errors([
                (
                    "対象種別が不正です。",
                    "target_type"
                )
            ])

        # 個人

        if target_type == "user":
            if not target_user:
                return _dkss_http.return_form_errors([
                    (
                        "対象ユーザーを選択してください。",
                        "target_user"
                    )
                ])

            target_driver = _dkss_models.Driver.query.filter_by(
                company_code=company_code,
                employee_id=target_user
            ).first()

            if not target_driver:
                return _dkss_http.return_form_errors([
                    (
                        "対象ユーザーが不正です。",
                        "target_user"
                    )
                ])

            target_user_record = _dkss_models.User.query.filter_by(
                company_code=company_code,
                username=target_driver.employee_id
            ).first()

            if not target_user_record:
                return _dkss_http.return_form_errors([
                    (
                        "対象ユーザー情報が不正です。",
                        "target_user"
                    )
                ])

            target_username = target_user_record.username
            target_user = target_driver.name
            target_office = target_driver.office or ""
            target_vehicle_record_id = None

        # 車両

        elif target_type == "vehicle":
            if not target_vehicle_record_id:
                return _dkss_http.return_form_errors([
                    (
                        "対象車両を選択してください。",
                        "target_vehicle_record_id"
                    )
                ])

            vehicle = _dkss_models.Vehicle.query.filter_by(
                company_code=company_code,
                id=target_vehicle_record_id,
                deleted=False
            ).first()

            if not vehicle:
                return _dkss_http.return_form_errors([
                    (
                        "対象車両が不正です。",
                        "target_vehicle_record_id"
                    )
                ])

            target_office = vehicle.office or ""
            target_user = ""

        # 営業所

        elif target_type == "office":
            if not target_office:
                return _dkss_http.return_form_errors([
                    (
                        "対象営業所を選択してください。",
                        "target_office"
                    )
                ])

            valid_office = _dkss_models.Office.query.filter_by(
                company_code=company_code,
                name=target_office
            ).with_for_update(read=True).first()

            if not valid_office:
                return _dkss_http.return_form_errors([
                    (
                        "対象営業所が不正です。",
                        "target_office"
                    )
                ])

            target_user = ""
            target_vehicle_record_id = None

        if target_type in {"user", "vehicle"} and not _dkss_master_readers.office_reference_is_current(
            company_code, target_office
        ):
            return _dkss_http.return_form_errors([
                ("営業所が更新されています。画面を再読み込みしてください。", "target_office")
            ])

        pending_answer_files = []

        for item in checklist["items"]:
            if item.get("item_type") != "check":
                continue

            value = _dkss_common.request.form.get(
                f"answer_{answer_index}",
                ""
            )

            choices = item.get("choices", [])

            if (
                item.get("input_type") == "select"
                and value
                and value not in choices
            ):
                return _dkss_http.return_form_errors([
                    (
                        "評価値が不正です。",
                        f"answer_{answer_index}"
                    )
                ])

            comment = _dkss_common.request.form.get(
                f"comment_{answer_index}",
                ""
            ).strip()

            if (
                item.get("answer_required")
                and not value
            ):
                return _dkss_http.return_form_errors([
                    (
                        "必須項目が未回答です。",
                        f"answer_{answer_index}"
                    )
                ])

            if len(comment) > 5000:
                return _dkss_http.return_form_errors([
                    (
                        "コメントは5000文字以内で入力してください。",
                        f"comment_{answer_index}"
                    )
                ])

            patrol_link = _dkss_common.request.form.get(
                f"patrol_link_{answer_index}"
            )

            item_index = len(answers)

            answers.append({
                "item_no": answer_index,
                "category": item.get("category", ""),
                "content": item.get("content", ""),
                "criteria": item.get("criteria", ""),
                "criteria_files": item.get("criteria_files", []),
                "value": value,
                "comment": comment,
                "files": [],
                "patrol_link": patrol_link == "1",
            })

            pending_answer_files.append(
                (item_index, answer_index)
            )

            answer_index += 1

        pending_uploads = []

        upload_file_count = sum(
            1
            for field_name in _dkss_common.request.files.keys()
            for file in _dkss_common.request.files.getlist(field_name)
            if file and file.filename
        )

        if upload_file_count > 50:
            return _dkss_http.return_form_errors([
                (
                    "一度にアップロードできるファイルは50件までです。",
                    ""
                )
            ])

        for item_index, form_index in pending_answer_files:
            for file in _dkss_common.request.files.getlist(
                f"files_{form_index}"
            ):
                if not file or not file.filename:
                    continue

                original_filename = _dkss_common.os.path.basename(
                    str(file.filename or "")
                )

                extension = _dkss_common.os.path.splitext(
                    original_filename
                )[1].lower()

                if (
                    extension not in _dkss_common.ALLOWED_UPLOAD_EXTENSIONS
                    or not _dkss_storage.is_valid_uploaded_file(
                        file,
                        extension
                    )
                ):
                    return _dkss_http.return_form_errors([
                        (
                            "添付ファイルの検証に失敗しました。",
                            f"files_{form_index}"
                        )
                    ])

                pending_uploads.append(
                    (item_index, file)
                )



        notify_usernames = [
            username.strip()
            for username in _dkss_common.request.form.getlist(
                "notify_users"
            )
            if username.strip()
        ]

        notify_usernames = list(
            dict.fromkeys(notify_usernames)
        )

        if len(notify_usernames) > 500:
            return _dkss_http.return_form_errors([
                (
                    "通知先ユーザー数が多すぎます。",
                    "notify_user_search"
                )
            ])

        valid_users = {
            user.username: user
            for user in _dkss_models.User.query.filter_by(
                company_code=company_code
            ).all()
            if user.username
        }

        invalid_notify_usernames = [
            username
            for username in notify_usernames
            if username not in valid_users
        ]

        if invalid_notify_usernames:
            return _dkss_http.return_form_errors([
                (
                    "通知先ユーザーが不正です。",
                    "notify_user_search"
                )
            ])

        approvals = []

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approval_index = len(approvals)

            submitted_candidate_usernames = [
                username.strip()
                for username in _dkss_common.request.form.getlist(
                    f"approval_notify_users_{approval_index}"
                )
                if username.strip()
            ]

            if len(submitted_candidate_usernames) > 500:
                return _dkss_http.return_form_errors([
                    (
                        "承認候補者数が多すぎます。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            invalid_candidate_usernames = [
                username
                for username in submitted_candidate_usernames
                if (
                    username not in valid_users
                    or not (
                        valid_users[username].role == "admin"
                        or (
                            item.get(
                                "approval_allow_general",
                                False
                            )
                            and valid_users[username].role == "user"
                        )
                    )
                )
            ]

            if invalid_candidate_usernames:
                return _dkss_http.return_form_errors([
                    (
                        "承認者の選択内容が不正です。",
                        f"approval_user_search_{approval_index}"
                    )
                ])

            candidate_usernames = list(
                dict.fromkeys(
                    submitted_candidate_usernames
                )
            )

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get(
                    "approval_allow_general",
                    False
                ),
                "candidate_usernames": list(
                    dict.fromkeys(candidate_usernames)
                ),
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

        saved_filenames = []

        try:
            for item_index, file in pending_uploads:
                filename = _dkss_storage.save_uploaded_file(file)

                if filename:
                    answers[item_index]["files"].append(filename)
                    saved_filenames.append(filename)

        except _dkss_common.UploadValidationError:
            for filename in saved_filenames:
                _dkss_storage.delete_uploaded_file(filename)

            return _dkss_http.return_form_errors([
                (
                    "添付ファイルの検証に失敗しました。",
                    ""
                )
            ])

        if target_type in _dkss_common.PATROL_VIEW_TYPES:
            for answer in answers:
                if not answer.get("patrol_link"):
                    continue

                _dkss_common.db.session.add(_dkss_models.PatrolResult(
                    company_code=_dkss_common.session.get("company_code"),
                    created_by_username=_dkss_common.session.get("username"),
                    created_by_name=_dkss_common.session.get("name"),
                    date=operation_now.strftime("%Y-%m-%d"),
                    delivery_place="",
                    category="点検指摘",
                    content_type="安全",
                    target_type=target_type,
                    target_user=target_user,
                    target_username=target_username,
                    office=target_office,
                    content=(
                        f"{answer.get('category', '')}：{answer.get('content', '')}"
                        f" / 評価：{answer.get('value') or '-'}"
                        f" / コメント：{answer.get('comment') or '-'}"
                    ),
                    files_json=_dkss_common.json.dumps(
                        answer.get("files", []),
                        ensure_ascii=False
                    ),
                    countermeasure="",
                    approval_status="未対応",
                    reject_reason=""
                ))

        result = _dkss_models.ChecklistResult(
            company_code=company_code,
            checklist_id=checklist_record.id,
            target_type=target_type,
            target_user=target_user,
            target_username=target_username,
            target_vehicle_record_id=target_vehicle_record_id,
            target_office=target_office,
            checked_by=_dkss_common.session.get("name"),
            checked_by_username=_dkss_common.session.get("username"),
            checked_date=operation_now.strftime("%Y-%m-%d %H:%M"),
            approved_by="",
            approved_by_username="",
            approved_date="",
            reject_reason="",
            status=(
                "承認待ち"
                if approvals
                else "点検完了"
            ),
            approvals_json=_dkss_common.json.dumps(
                approvals,
                ensure_ascii=False
            ),
            notify_users_json=_dkss_common.json.dumps(
                notify_usernames,
                ensure_ascii=False
            ),
            answers_json=_dkss_common.json.dumps(
                answers,
                ensure_ascii=False
            ),
            checklist_snapshot_json=_dkss_common.json.dumps(
                checklist,
                ensure_ascii=False
            )
        )

        _dkss_common.db.session.add(result)

        try:
            _dkss_common.db.session.commit()

        except _dkss_common.IntegrityError:
            _dkss_common.db.session.rollback()

            for filename in saved_filenames:
                _dkss_storage.delete_uploaded_file(filename)

            return _dkss_http.return_form_errors(
                [
                    (
                        "安全チェックリストの保存に失敗しました。"
                        "もう一度お試しください。",
                        ""
                    )
                ],
                status_code=409
            )

        except _dkss_common.SQLAlchemyError:
            _dkss_common.db.session.rollback()

            for filename in saved_filenames:
                _dkss_storage.delete_uploaded_file(filename)

            return _dkss_http.return_form_errors(
                [
                    (
                        "安全チェックリストの保存に失敗しました。"
                        "もう一度お試しください。",
                        ""
                    )
                ],
                status_code=500
            )

        first_approval_usernames = (
            approvals[0].get("candidate_usernames") or []
        ) if approvals else []

        for approval_username in first_approval_usernames:
            approval_user = _dkss_models.User.query.filter_by(
                company_code=company_code,
                username=approval_username
            ).first()

            if not approval_user:
                continue

            _dkss_notifications_delivery.add_notification(
                (approval_user.last_name or "")
                + (approval_user.first_name or ""),
                "安全チェックリスト承認依頼",
                (
                    f"「{checklist_record.name}」の"
                    "承認をお願いします。"
                ),
                f"/safety/checklist-results/{result.id}",
                company_code=company_code,
                target_identity=approval_user.account_identity,
                target_username=approval_user.username,
                workflow_context=_dkss_notifications_delivery.build_notification_workflow_context(
                    result,
                    "safety",
                    "approval",
                    approval_index=0
                )
            )

        if result.status == "点検完了":
            completion_notify_usernames = set()

            if target_type == "user" and target_username:
                completion_notify_usernames.add(
                    target_username
                )

            if _dkss_common.session.get("username"):
                completion_notify_usernames.add(
                    _dkss_common.session.get("username")
                )

            for notify_username in completion_notify_usernames:
                notify_user = _dkss_models.User.query.filter_by(
                    company_code=company_code,
                    username=notify_username
                ).first()

                if not notify_user:
                    continue

                _dkss_notifications_delivery.add_notification(
                    (notify_user.last_name or "") + (notify_user.first_name or ""),
                    "安全チェックリスト完了のお知らせ",
                    (
                        f"「{checklist_record.name}」の"
                        f"チェックが完了しました。"
                    ),
                    f"/safety/checklist-results/{result.id}",
                    company_code=company_code,
                    target_identity=notify_user.account_identity,
                    target_username=notify_user.username
                )

        mention_text = "\n".join(
            "\n".join([
                answer.get("value", "") or "",
                answer.get("comment", "") or "",
            ])
            for answer in answers
        )

        _dkss_notifications_delivery.notify_mentions(
            mention_text,
            f"/safety/checklist-results/{result.id}"
        )

        return _dkss_common.redirect(f"/safety/checklists/{checklist_record.id}")

    criteria_list = []

    for item in checklist["items"]:
        if item.get("item_type") != "check":
            continue

        criteria = item.get("criteria", "")
        if criteria and criteria not in criteria_list:
            criteria_list.append(criteria)

    return _dkss_common.render_template(
        "checklist_result_form.html",
        checklist=checklist,
        index=checklist_record.id,
        criteria_list=criteria_list,
        drivers=_dkss_vehicle_readers.drivers_for_current_company(),
        selected_vehicle=None,
        offices=_dkss_master_readers.offices_for_current_company()
    )



def edit_checklist(index):
    checklist_record = _dkss_models.Checklist.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not checklist_record:
        return _dkss_common.redirect("/master/checklists")

    checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)

    if checklist.get("fixed_template_code"):
        if _dkss_common.request.method == "POST":
            return _dkss_http.return_form_errors(
                [("標準の日常点検表は固定様式のため、変更できません。", "")],
                403
            )
        return _dkss_common.redirect("/master/checklists")

    if _dkss_common.request.method == "POST":
        form_errors = []

        has_safety_results = _dkss_models.ChecklistResult.query.filter_by(
            company_code=checklist_record.company_code,
            checklist_id=checklist_record.id
        ).first()

        has_vehicle_results = _dkss_models.VehicleChecklistResult.query.filter_by(
            company_code=checklist_record.company_code,
            checklist_id=checklist_record.id
        ).first()

        target = _dkss_common.request.form.get("target", "").strip()

        if target not in {
            "安全管理",
            "車両管理"
        }:
            form_errors.append((
                "用途が不正です。",
                "target"
            ))

        if (
            has_vehicle_results
            and checklist_record.target != target
        ):
            return _dkss_http.return_form_errors(
                [(
                    "車両点検履歴が存在するため、用途は変更できません。",
                    "target"
                )],
                409
            )
        item_categories = _dkss_common.request.form.getlist("item_category")
        item_contents = _dkss_common.request.form.getlist("item_content")
        input_types = _dkss_common.request.form.getlist("input_type")
        item_types = _dkss_common.request.form.getlist("item_type")
        original_item_indexes = _dkss_common.request.form.getlist(
            "original_item_index"
        )
        approval_labels = _dkss_common.request.form.getlist("approval_label")
        approval_allow_general_list = _dkss_common.request.form.getlist("approval_allow_general")
        choices_list = _dkss_common.request.form.getlist("choices")
        criteria_list = _dkss_common.request.form.getlist("criteria")
        answer_required_list = _dkss_common.request.form.getlist("answer_required")
        shaded_list = _dkss_common.request.form.getlist("shaded")

        if len(item_types) > 500:
            form_errors.append((
                "チェック項目は500件以内で設定してください。",
                "item_type_0"
            ))

        for i, item_type in enumerate(item_types):
            if item_type not in {
                "check",
                "inspector",
                "approval"
            }:
                form_errors.append((
                    "項目種別が不正です。",
                    f"item_type_{i}"
                ))

        for i, input_type in enumerate(input_types):
            if input_type not in {
                "select",
                "text"
            }:
                form_errors.append((
                    "評価方式が不正です。",
                    f"input_type_{i}"
                ))

        required_list_length = len(item_types)

        if any(
            len(values) < required_list_length
            for values in [
                item_categories,
                item_contents,
                input_types,
                choices_list,
                criteria_list
            ]
        ):
            form_errors.append((
                "チェック項目のデータが不正です。",
                "item_type_0"
            ))

        if form_errors:
            return _dkss_http.return_form_errors(form_errors)

        score_enabled = _dkss_common.request.form.get("score_enabled") == "1"
        print_portrait = (
            _dkss_common.request.form.get("target") == "車両管理"
            and _dkss_common.request.form.get("print_portrait") == "1"
        )
        print_half_month = (
            _dkss_common.request.form.get("target") == "車両管理"
            and _dkss_common.request.form.get("print_half_month") == "1"
        )
        reminder_enabled = (
            _dkss_common.request.form.get("reminder_enabled") == "1"
        )

        reminder_time = "08:00"

        try:
            reminder_time = _dkss_http.parse_time_hhmm(
                _dkss_common.request.form.get("reminder_time") or "08:00",
                "未実施通知時刻"
            )
        except _dkss_common.UploadValidationError:
            form_errors.append((
                "未実施通知時刻の入力内容を確認してください。",
                "reminder_time"
            ))

        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            form_errors.append((
                "チェックリスト名を入力してください。",
                "name"
            ))
        elif len(name) > 200:
            form_errors.append((
                "チェックリスト名は200文字以内で入力してください。",
                "name"
            ))

        duplicate_checklist = _dkss_models.Checklist.query.filter(
            _dkss_models.Checklist.company_code == checklist_record.company_code,
            _dkss_models.Checklist.name == name,
            _dkss_models.Checklist.id != checklist_record.id
        ).first()

        if duplicate_checklist:
            form_errors.append((
                "このチェックリストはすでに登録されています。",
                "name"
            ))

        frequency_number = None
        frequency_unit = ""
        display_type = ""

        if target == "車両管理":
            frequency_value = _dkss_common.request.form.get(
                "frequency_value",
                ""
            ).strip()
            frequency_unit = _dkss_common.request.form.get(
                "frequency_unit",
                ""
            ).strip()
            display_type = _dkss_common.request.form.get(
                "display_type",
                ""
            ).strip()

            try:
                frequency_number = int(frequency_value)
            except (TypeError, ValueError):
                form_errors.append((
                    "頻度は整数で入力してください。",
                    "frequency_value"
                ))
                frequency_number = None

            if frequency_number is not None:
                if frequency_number < 1:
                    form_errors.append((
                        "頻度は1以上で入力してください。",
                        "frequency_value"
                    ))
                elif frequency_number > 9999:
                    form_errors.append((
                        "頻度は9999以下で入力してください。",
                        "frequency_value"
                    ))

            if frequency_unit not in {
                "day",
                "month",
                "year"
            }:
                form_errors.append((
                    "頻度単位が不正です。",
                    "frequency_unit"
                ))

            if display_type not in {
                "month",
                "year"
            }:
                form_errors.append((
                    "表示形式が不正です。",
                    "display_type"
                ))

        old_items = checklist.get("items", [])

        old_criteria_files = {
            filename
            for item in old_items
            for filename in item.get(
                "criteria_files",
                []
            )
            if filename
        }

        items = []
        pending_criteria_files = []

        for i in range(len(item_types)):
            item_type = item_types[i]

            if item_type == "inspector":
                items.append({
                    "item_type": "inspector",
                    "content": (
                        str(item_contents[i] or "").strip()
                        if i < len(item_contents)
                        else ""
                    ),
                })
                continue

            if item_type == "approval":
                label = ""

                if i < len(approval_labels):
                    label = approval_labels[i].strip()

                if len(label) > 100:
                    form_errors.append((
                        "承認ラベルは100文字以内で入力してください。",
                        f"approval_label_{i}"
                    ))

                items.append({
                    "item_type": "approval",
                    "approval_label": label,
                    "approval_allow_general": str(i) in approval_allow_general_list,
                    "criteria_files": [],
                })

                continue

            if i >= len(item_contents):
                continue

            if (
                not item_contents[i]
                and input_types[i] != "text"
            ):
                continue

            category = str(
                item_categories[i] or ""
            ).strip()
            content = str(
                item_contents[i] or ""
            ).strip()
            criteria = str(
                criteria_list[i] or ""
            ).strip()

            if len(category) > 100:
                form_errors.append((
                    "カテゴリは100文字以内で入力してください。",
                    f"item_category_{i}"
                ))

            if len(content) > 500:
                form_errors.append((
                    "チェック内容は500文字以内で入力してください。",
                    f"item_content_{i}"
                ))

            if len(criteria) > 500:
                form_errors.append((
                    "判定基準は500文字以内で入力してください。",
                    f"criteria_{i}"
                ))

            choices = []

            if input_types[i] == "select":
                choices = [
                    choice.strip()
                    for choice in choices_list[i].split(",")
                    if choice.strip()
                ]

                if not choices:
                    form_errors.append((
                        "選択式のチェック項目には評価の選択肢を1つ以上入力してください。",
                        f"choices_{i}"
                    ))
                elif len(choices) > 100:
                    form_errors.append((
                        "選択肢は100個以内で入力してください。",
                        f"choices_{i}"
                    ))
                elif any(
                    len(choice) > 100
                    for choice in choices
                ):
                    form_errors.append((
                        "各選択肢は100文字以内で入力してください。",
                        f"choices_{i}"
                    ))

            criteria_files = []

            original_item_index = ""

            if i < len(original_item_indexes):
                original_item_index = str(
                    original_item_indexes[i] or ""
                ).strip()

            if original_item_index.isdigit():
                old_index = int(
                    original_item_index
                )

                if 0 <= old_index < len(old_items):
                    criteria_files = list(
                        old_items[old_index].get(
                            "criteria_files",
                            []
                        )
                    )

            item_index = len(items)

            items.append({
                "item_type": "check",
                "category": category,
                "content": content,
                "input_type": input_types[i],
                "choices": choices,
                "criteria": criteria,
                "criteria_files": criteria_files,
                "answer_required": str(i) in answer_required_list,
                "shaded": str(i) in shaded_list,
                "score_enabled": score_enabled,
            })

            pending_criteria_files.append((item_index, i))

        if form_errors:
            return _dkss_http.return_form_errors(
                form_errors,
                409 if duplicate_checklist else 400
            )

        pending_uploads = []

        upload_file_count = sum(
            1
            for field_name in _dkss_common.request.files.keys()
            for file in _dkss_common.request.files.getlist(field_name)
            if file and file.filename
        )

        if upload_file_count > 50:
            return _dkss_http.return_form_errors([
                "一度にアップロードできるファイルは50件までです。"
            ])

        if (
            upload_file_count > 0
            and not _dkss_common.session.get("company_code")
        ):
            return _dkss_http.return_form_errors([
                "company_code is required for file upload."
            ])

        for item_index, form_index in pending_criteria_files:
            for file in _dkss_common.request.files.getlist(
                f"criteria_files_{form_index}"
            ):
                if not file or not file.filename:
                    continue

                original_filename = _dkss_common.os.path.basename(
                    str(file.filename or "")
                )

                extension = _dkss_common.os.path.splitext(
                    original_filename
                )[1].lower()

                if (
                    extension not in _dkss_common.ALLOWED_UPLOAD_EXTENSIONS
                    or not _dkss_storage.is_valid_uploaded_file(
                        file,
                        extension
                    )
                ):
                    return _dkss_http.return_form_errors([
                        "添付ファイルの検証に失敗しました。"
                    ])

                pending_uploads.append(
                    (item_index, file)
                )

        create_new_version = _dkss_common.request.form.get(
            "create_new_version",
            ""
        )

        if create_new_version not in {"0", "1"}:
            response = _dkss_runtime.app.make_response(("", 409))
            response.headers[
                "X-DKSS-Choose-Checklist-Version"
            ] = "1"
            return response

        for item_index, file in pending_uploads:
            filename = _dkss_storage.save_uploaded_file(file)

            if filename:
                items[item_index]["criteria_files"].append(filename)

        version_history = _dkss_serialization.safe_json_dict_list(
            checklist_record.version_history_json
        )

        new_checklist_revision = {
            **checklist,
            "name": name,
            "target": target,
            "frequency_value": (
                str(frequency_number)
                if target == "車両管理"
                else ""
            ),
            "frequency_unit": (
                frequency_unit
                if target == "車両管理"
                else ""
            ),
            "display_type": (
                display_type
                if target == "車両管理"
                else ""
            ),
            "print_portrait": (
                print_portrait
                if target == "車両管理"
                else False
            ),
            "print_half_month": (
                print_half_month
                if target == "車両管理"
                else False
            ),
            "items": items,
        }

        if (
            create_new_version == "1"
            and _dkss_checklist_common.checklist_revision_key(checklist)
            != _dkss_checklist_common.checklist_revision_key(new_checklist_revision)
        ):
            version_history.append({
                "effective_until": _dkss_common.datetime.now(
                    _dkss_common.ZoneInfo("Asia/Tokyo")
                ).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "snapshot": {
                    key: value
                    for key, value in checklist.items()
                    if key != "version_history"
                }
            })

        if create_new_version == "0":
            updated_snapshot_json = _dkss_common.json.dumps(
                new_checklist_revision,
                ensure_ascii=False
            )

            _dkss_models.ChecklistResult.query.filter_by(
                company_code=checklist_record.company_code,
                checklist_id=checklist_record.id
            ).update(
                {
                    "checklist_snapshot_json": updated_snapshot_json
                },
                synchronize_session=False
            )

            _dkss_models.VehicleChecklistResult.query.filter_by(
                company_code=checklist_record.company_code,
                checklist_id=checklist_record.id
            ).update(
                {
                    "checklist_snapshot_json": updated_snapshot_json
                },
                synchronize_session=False
            )

        checklist_record.version_history_json = _dkss_common.json.dumps(
            version_history,
            ensure_ascii=False
        )

        checklist_record.name = name
        checklist_record.target = target
        checklist_record.reminder_enabled = reminder_enabled
        checklist_record.reminder_time = reminder_time

        if target == "車両管理":
            checklist_record.frequency_value = str(
                frequency_number
            )
            checklist_record.frequency_unit = frequency_unit
            checklist_record.display_type = display_type
            checklist_record.print_portrait = print_portrait
            checklist_record.print_half_month = print_half_month
        else:
            checklist_record.frequency_value = ""
            checklist_record.frequency_unit = ""
            checklist_record.display_type = ""
            checklist_record.print_portrait = False
            checklist_record.print_half_month = False

        checklist_record.items_json = _dkss_common.json.dumps(items, ensure_ascii=False)

        new_criteria_files = {
            filename
            for item in items
            for filename in item.get(
                "criteria_files",
                []
            )
            if filename
        }

        removed_criteria_files = (
            old_criteria_files
            - new_criteria_files
        )

        _dkss_common.db.session.commit()

        company_code = checklist_record.company_code

        for filename in removed_criteria_files:
            filename = _dkss_common.os.path.basename(
                str(filename or "")
            )

            if not filename:
                continue

            still_referenced = False

            for other_checklist in _dkss_models.Checklist.query.filter_by(
                company_code=company_code
            ).all():
                other_data = _dkss_checklist_common.checklist_to_dict(
                    other_checklist
                )

                if any(
                    filename in item.get(
                        "criteria_files",
                        []
                    )
                    for item in other_data.get(
                        "items",
                        []
                    )
                ):
                    still_referenced = True
                    break

                for version in other_data.get(
                    "version_history",
                    []
                ):
                    snapshot = version.get(
                        "snapshot",
                        {}
                    )

                    if any(
                        filename in item.get(
                            "criteria_files",
                            []
                        )
                        for item in snapshot.get(
                            "items",
                            []
                        )
                    ):
                        still_referenced = True
                        break

                if still_referenced:
                    break

            if not still_referenced:
                result_records = _dkss_models.ChecklistResult.query.filter_by(
                    company_code=company_code
                ).all()

                for result_record in result_records:
                    answers = _dkss_serialization.safe_json_dict_list(
                        result_record.answers_json
                    )

                    if any(
                        filename in answer.get(
                            "criteria_files",
                            []
                        )
                        for answer in answers
                    ):
                        still_referenced = True
                        break

                    snapshot = _dkss_serialization.safe_json_dict(
                        result_record.checklist_snapshot_json
                    )

                    if any(
                        filename in item.get(
                            "criteria_files",
                            []
                        )
                        for item in snapshot.get(
                            "items",
                            []
                        )
                    ):
                        still_referenced = True
                        break

            if not still_referenced:
                result_records = _dkss_models.VehicleChecklistResult.query.filter_by(
                    company_code=company_code
                ).all()

                for result_record in result_records:
                    answers = _dkss_serialization.safe_json_dict_list(
                        result_record.answers_json
                    )

                    if any(
                        filename in answer.get(
                            "criteria_files",
                            []
                        )
                        for answer in answers
                    ):
                        still_referenced = True
                        break

                    snapshot = _dkss_serialization.safe_json_dict(
                        result_record.checklist_snapshot_json
                    )

                    if any(
                        filename in item.get(
                            "criteria_files",
                            []
                        )
                        for item in snapshot.get(
                            "items",
                            []
                        )
                    ):
                        still_referenced = True
                        break

            if still_referenced:
                continue

            if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
                try:
                    _dkss_runtime.app.extensions["dkss"]['s3_client'].delete_object(
                        Bucket=_dkss_runtime.app.config['S3_BUCKET_NAME'],
                        Key=(
                            f"uploads/"
                            f"{company_code}/"
                            f"{filename}"
                        )
                    )
                except _dkss_common.ClientError:
                    _dkss_runtime.app.logger.warning(
                        "旧評価基準ファイルのS3削除に失敗しました。",
                        exc_info=True
                    )
            else:
                safe_filename = _dkss_common.secure_filename(
                    filename
                )

                if safe_filename:
                    file_path = _dkss_common.os.path.join(
                        _dkss_runtime.app.config["UPLOAD_FOLDER"],
                        company_code,
                        safe_filename
                    )

                    if _dkss_common.os.path.exists(file_path):
                        _dkss_common.os.remove(file_path)

        return _dkss_common.redirect("/master/checklists")

    checklist_edit_form_data = _dkss_common.session.pop(
        "checklist_edit_form_data",
        {}
    )

    retained_checklist = _dkss_http.checklist_form_data_to_dict(
        checklist_edit_form_data,
        checklist
    )

    return _dkss_common.render_template(
        "checklist_form.html",
        checklist=retained_checklist,
        index=checklist_record.id,
        mode="edit"
    )



def duplicate_checklist(index):
    company_code = _dkss_common.session.get("company_code")

    source = _dkss_models.Checklist.query.filter_by(
        id=index,
        company_code=company_code
    ).first()

    if not source:
        return _dkss_common.redirect("/master/checklists")

    if _dkss_checklist_common.checklist_to_dict(source).get("fixed_template_code"):
        return _dkss_http.return_form_errors(
            [("標準の日常点検表は固定様式のため、複製できません。", "")],
            403
        )

    base_name = f"{source.name}（コピー）"
    new_name = base_name
    copy_no = 2

    while _dkss_models.Checklist.query.filter_by(
        company_code=company_code,
        name=new_name
    ).first():
        new_name = f"{source.name}（コピー{copy_no}）"
        copy_no += 1

    duplicated = _dkss_models.Checklist(
        company_code=company_code,
        name=new_name,
        target=source.target,
        frequency_value=source.frequency_value,
        frequency_unit=source.frequency_unit,
        display_type=source.display_type,
        print_portrait=source.print_portrait,
        print_half_month=source.print_half_month,
        reminder_enabled=source.reminder_enabled,
        reminder_time=source.reminder_time,
        active=True,
        items_json=source.items_json,
        notify_users_json=source.notify_users_json,
        version_history_json="[]"
    )

    _dkss_common.db.session.add(duplicated)
    _dkss_common.db.session.flush()

    _dkss_audit.add_audit_log(
        action="duplicate_checklist",
        target_type="checklist",
        target_id=str(duplicated.id),
        detail=f"{source.name} から {new_name} を複製"
    )

    _dkss_common.db.session.commit()

    return _dkss_common.redirect(
        f"/master/checklists/{duplicated.id}/edit?duplicated=1"
    )



def toggle_checklist_active(index):
    checklist = _dkss_models.Checklist.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not checklist:
        return _dkss_common.redirect("/master/checklists")

    if _dkss_checklist_common.checklist_to_dict(checklist).get("fixed_template_code"):
        return _dkss_http.return_form_errors(
            [("標準の日常点検表は固定様式のため、無効化できません。", "")],
            403
        )

    checklist.active = not checklist.active

    _dkss_audit.add_audit_log(
        action="checklist_activated" if checklist.active else "checklist_deactivated",
        target_type="checklist",
        target_id=str(checklist.id),
        detail=f"{checklist.name} を"
        f"{'有効化' if checklist.active else '無効化'}"
    )

    _dkss_common.db.session.commit()

    return _dkss_common.redirect("/master/checklists")



def checklist_deletion_files(value):
    """Collect upload references from definitions, snapshots and answers."""
    files = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("files", "criteria_files") and isinstance(child, list):
                files.update(name for name in child if isinstance(name, str))
            else:
                files.update(checklist_deletion_files(child))
    elif isinstance(value, list):
        for child in value:
            files.update(checklist_deletion_files(child))
    return files



def checklist_upload_still_referenced(company_code, filename):
    # Be conservative: keep files referenced anywhere in this company's data.
    # Audit entries describe past actions and are not live file references.
    for table in _dkss_common.db.metadata.tables.values():
        if "company_code" not in table.c or table.name == _dkss_models.AuditLog.__tablename__:
            continue
        columns = [column for column in table.c
                   if isinstance(column.type, _dkss_common.db.String) and column.name != "company_code"]
        if columns and _dkss_common.db.session.execute(
            _dkss_common.db.select(table.c.company_code).where(
                table.c.company_code == company_code,
                _dkss_common.or_(*(column.contains(filename, autoescape=True) for column in columns))
            ).limit(1)
        ).first():
            return True
    return False



def delete_checklist(index):
    if not _dkss_access.require_master_admin():
        return _dkss_http.return_form_errors([("管理者のみ削除できます。", "")], 403)
    checklist = _dkss_models.Checklist.query.filter_by(
        id=index, company_code=_dkss_common.session.get("company_code")
    ).first()
    if not checklist:
        return _dkss_common.redirect("/master/checklists")
    if _dkss_checklist_common.checklist_to_dict(checklist).get("fixed_template_code"):
        return _dkss_http.return_form_errors(
            [("標準の日常点検表は固定様式のため、削除できません。", "")], 403
        )
    if _dkss_common.request.form.get("confirm_delete") != "1":
        return _dkss_http.return_form_errors(
            [("点検記録も削除されます。削除ボタンから確認して実行してください。", "")], 400
        )
    company_code = checklist.company_code
    files = checklist_deletion_files(_dkss_checklist_common.checklist_to_dict(checklist))
    safety = _dkss_models.ChecklistResult.query.filter_by(
        company_code=company_code, checklist_id=checklist.id
    ).all()
    vehicle = _dkss_models.VehicleChecklistResult.query.filter_by(
        company_code=company_code, checklist_id=checklist.id
    ).all()
    ids_by_type = {"safety": {row.id for row in safety},
                   "vehicle": {row.id for row in vehicle}}
    from urllib.parse import urlsplit
    try:
        for notification in _dkss_models.Notification.query.filter_by(company_code=company_code).all():
            context = _dkss_serialization.safe_json_dict(notification.workflow_context_json)
            result_id = context.get("result_id")
            try:
                path = urlsplit(notification.link or "").path.rstrip("/")
            except ValueError:
                path = ""
            result_type = context.get("result_type")
            linked = (type(result_id) is int and isinstance(result_type, str)
                      and result_id in ids_by_type.get(result_type, set()))
            linked = linked or path == f"/vehicle/checklists/{checklist.id}"
            linked = linked or any(path == f"/safety/checklist-results/{ident}"
                                   for ident in ids_by_type["safety"])
            if linked:
                files.update(_dkss_serialization.safe_json_str_list(notification.files_json))
                _dkss_common.db.session.delete(notification)
        for result_type, ids in ids_by_type.items():
            if not ids:
                continue
            for event in _dkss_models.ChecklistEvent.query.filter(
                _dkss_models.ChecklistEvent.company_code == company_code,
                _dkss_models.ChecklistEvent.result_type == result_type,
                _dkss_models.ChecklistEvent.result_id.in_(ids)
            ).all():
                files.update(checklist_deletion_files(_dkss_serialization.safe_json_dict(event.detail_json)))
                _dkss_common.db.session.delete(event)
        if ids_by_type["vehicle"]:
            _dkss_models.VehicleMaintenanceInspectionLink.query.filter(
                _dkss_models.VehicleMaintenanceInspectionLink.company_code == company_code,
                _dkss_models.VehicleMaintenanceInspectionLink.inspection_result_id.in_(ids_by_type["vehicle"])
            ).delete(synchronize_session=False)
        for result in safety + vehicle:
            files.update(checklist_deletion_files(_dkss_serialization.safe_json_dict(result.checklist_snapshot_json)))
            files.update(checklist_deletion_files(_dkss_serialization.safe_json_dict_list(result.answers_json)))
            _dkss_common.db.session.delete(result)
        _dkss_models.VehicleChecklistNotifySetting.query.filter_by(
            company_code=company_code, checklist_id=checklist.id
        ).delete(synchronize_session=False)
        _dkss_master_readers.remove_master_from_display_order("checklists", checklist)
        _dkss_audit.add_audit_log(
            action="checklist_deleted", target_type="checklist", target_id=checklist.id,
            detail=f"チェックリスト削除: {checklist.name} / 安全記録{len(safety)}件・車両記録{len(vehicle)}件",
            company_code=company_code,
        )
        _dkss_common.db.session.delete(checklist)
        _dkss_common.db.session.commit()
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("チェックリストと関連記録の削除に失敗しました。")
        return _dkss_http.return_form_errors([("削除できませんでした。再度お試しください。", "")], 500)
    for value in files:
        filename = _dkss_common.os.path.basename(str(value or ""))
        if not filename:
            continue
        try:
            if not checklist_upload_still_referenced(company_code, filename):
                _dkss_storage.delete_uploaded_file(filename)
        except Exception:
            _dkss_runtime.app.logger.warning("削除済みチェックリストの添付ファイル整理に失敗しました。", exc_info=True)
    return _dkss_common.redirect("/master/checklists")



def approve_checklist_result(result_index, approval_index):
    result_record = (
        _dkss_models.ChecklistResult.query
        .filter_by(
            id=result_index,
            company_code=_dkss_common.session.get("company_code")
        )
        .with_for_update()
        .first()
    )

    if not result_record:
        return _dkss_common.redirect("/safety/checklists")

    if result_record.status != "承認待ち":
        return _dkss_common.redirect(
            _dkss_common.url_for("checklist_result_detail", result_index=result_index)
        )

    result = _dkss_checklist_common.checklist_result_to_dict(result_record)

    approvals = result.get("approvals", [])
    if not approvals:
        approval_checklist = {}

        if result_record.checklist_snapshot_json:
            approval_checklist = _dkss_serialization.safe_json_dict(
                result_record.checklist_snapshot_json
            )

        if not approval_checklist:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                approval_checklist = _dkss_checklist_common.checklist_to_dict(
                    checklist_record
                )

        for item in approval_checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get(
                    "approval_allow_general",
                    False
                ),
                "candidate_usernames": [],
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

    if approval_index < 0 or approval_index >= len(approvals):
        return _dkss_common.redirect(_dkss_common.url_for("checklist_result_detail", result_index=result_index))

    if any(
        not (
            item.get("approved_by")
            or item.get("approved_by_username")
        )
        for item in approvals[:approval_index]
    ):
        return _dkss_common.redirect(
            _dkss_common.url_for("checklist_result_detail", result_index=result_index)
        )

    current_approval_index = next(
        (
            index
            for index, item in enumerate(approvals)
            if not (
                item.get("approved_by")
                or item.get("approved_by_username")
            )
        ),
        None
    )

    if approval_index != current_approval_index:
        return _dkss_common.redirect(
            _dkss_common.url_for("checklist_result_detail", result_index=result_index)
        )

    approval = approvals[approval_index]

    # 旧データに allow_general が無い場合は
    # 記録時点のチェックリストから補完
    if "allow_general" not in approval:
        approval_checklist = {}

        if result_record.checklist_snapshot_json:
            approval_checklist = _dkss_serialization.safe_json_dict(
                result_record.checklist_snapshot_json
            )

        if not approval_checklist:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                approval_checklist = _dkss_checklist_common.checklist_to_dict(
                    checklist_record
                )

        approval_items = [
            item
            for item in approval_checklist.get("items", [])
            if item.get("item_type") == "approval"
        ]

        if approval_index < len(approval_items):
            approval["allow_general"] = approval_items[
                approval_index
            ].get(
                "approval_allow_general",
                False
            )

    if (
        approval.get("approved_by")
        or approval.get("approved_by_username")
    ):
        return _dkss_common.redirect(
            _dkss_common.url_for("checklist_result_detail", result_index=result_index)
        )

    if not _dkss_safety_permissions.can_approve_checklist_result(result, approval):
        return _dkss_common.redirect(_dkss_common.url_for("checklist_result_detail", result_index=result_index))

    approval["approved_by"] = _dkss_common.session.get("name")
    approval["approved_by_username"] = _dkss_common.session.get("username")
    approval["approved_date"] = _dkss_checklist_common.get_user_local_now(
        result_record.company_code,
        _dkss_common.session.get("username")
    ).strftime("%Y-%m-%d %H:%M")

    result_record.approvals_json = _dkss_common.json.dumps(
        approvals,
        ensure_ascii=False
    )

    result_record.reject_reason = ""

    all_approved = all(
        (
            item.get("approved_by")
            or item.get("approved_by_username")
        )
        for item in approvals
    )

    if approvals and all_approved:
        result_record.status = "承認済み"
        result_record.approved_by = _dkss_common.session.get("name")
        result_record.approved_by_username = _dkss_common.session.get("username")
        result_record.approved_date = _dkss_checklist_common.get_user_local_now(
            result_record.company_code,
            _dkss_common.session.get("username")
        ).strftime("%Y-%m-%d %H:%M")
    else:
        result_record.status = "承認待ち"
        result_record.approved_by = ""
        result_record.approved_by_username = ""
        result_record.approved_date = ""

    checklist_event = _dkss_models.ChecklistEvent(
        company_code=result_record.company_code,
        result_type="safety",
        result_id=result_record.id,
        event_type="承認",
        actor_username=_dkss_common.session.get("username"),
        actor_name=_dkss_common.session.get("name"),
        detail_json=_dkss_common.json.dumps(
            {
                "approval_index": approval_index,
                "approval": dict(approval),
                "all_approved": all_approved,
            },
            ensure_ascii=False
        ),
        created_at=_dkss_common.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    _dkss_common.db.session.add(checklist_event)

    _dkss_common.db.session.commit()

    if result_record.status != "承認済み":
        next_approval_index, next_approval = next(
            (
                (index, item)
                for index, item in enumerate(
                    approvals[approval_index + 1:],
                    start=approval_index + 1
                )
                if not (
                    item.get("approved_by")
                    or item.get("approved_by_username")
                )
            ),
            (None, None)
        )

        for target_username in (
            next_approval.get(
                "candidate_usernames",
                []
            )
            if next_approval
            else []
        ):
            target_user = _dkss_models.User.query.filter_by(
                company_code=result_record.company_code,
                username=target_username
            ).first()

            if not target_user:
                continue

            _dkss_notifications_delivery.add_notification(
                (target_user.last_name or "")
                + (target_user.first_name or ""),
                "安全チェックリスト承認依頼",
                "次の承認をお願いします。",
                f"/safety/checklist-results/{result_record.id}",
                company_code=result_record.company_code,
                target_identity=target_user.account_identity,
                target_username=target_user.username,
                workflow_context=_dkss_notifications_delivery.build_notification_workflow_context(
                    result_record,
                    "safety",
                    "approval",
                    approval_index=next_approval_index
                )
            )

    if result_record.status == "承認済み":
        notify_usernames = {
            username
            for username in [
                result_record.checked_by_username,
                result_record.target_username
            ]
            if username
        }

        for target_username in notify_usernames:
            target_user = _dkss_models.User.query.filter_by(
                company_code=result_record.company_code,
                username=target_username
            ).first()

            if not target_user:
                continue

            _dkss_notifications_delivery.add_notification(
                (target_user.last_name or "") + (target_user.first_name or ""),
                "チェックリストが承認されました",
                "チェックリストの承認が完了しました。",
                f"/safety/checklist-results/{result_record.id}",
                company_code=result_record.company_code,
                target_identity=target_user.account_identity,
                target_username=target_user.username
            )

    return _dkss_common.redirect(f"/safety/checklist-results/{result_record.id}")



def reject_checklist_result(result_index):
    result_record = (
        _dkss_models.ChecklistResult.query
        .filter_by(
            id=result_index,
            company_code=_dkss_common.session.get("company_code")
        )
        .with_for_update()
        .first()
    )

    if not result_record:
        return _dkss_common.redirect("/safety/checklists")

    if result_record.status != "承認待ち":
        return _dkss_common.redirect(
            _dkss_common.url_for("checklist_result_detail", result_index=result_index)
        )

    result = _dkss_checklist_common.checklist_result_to_dict(result_record)

    approvals = _dkss_serialization.safe_json_dict_list(
        result_record.approvals_json
    )

    if not approvals:
        checklist = _dkss_serialization.safe_json_dict(
            result_record.checklist_snapshot_json
        )

        if not checklist:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                checklist = _dkss_checklist_common.checklist_to_dict(
                    checklist_record
                )

        for item in checklist.get("items", []):
            if item.get("item_type") != "approval":
                continue

            approvals.append({
                "label": item.get("approval_label", ""),
                "allow_general": item.get(
                    "approval_allow_general",
                    False
                ),
                "candidate_usernames": [],
                "approved_by": "",
                "approved_by_username": "",
                "approved_date": "",
            })

    current_approval_index = next(
        (
            index
            for index, approval in enumerate(approvals)
            if not (
                approval.get("approved_by")
                or approval.get("approved_by_username")
            )
        ),
        None
    )

    current_approval = (
        approvals[current_approval_index]
        if current_approval_index is not None
        else None
    )

    if (
        current_approval is not None
        and "allow_general" not in current_approval
    ):
        checklist = _dkss_serialization.safe_json_dict(
            result_record.checklist_snapshot_json
        )

        if not checklist:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=result_record.company_code
            ).first()

            if checklist_record:
                checklist = _dkss_checklist_common.checklist_to_dict(
                    checklist_record
                )

        approval_items = [
            item
            for item in checklist.get("items", [])
            if item.get("item_type") == "approval"
        ]

        if current_approval_index < len(approval_items):
            current_approval["allow_general"] = approval_items[
                current_approval_index
            ].get(
                "approval_allow_general",
                False
            )

    if not _dkss_safety_permissions.can_reject_checklist_result(
        result,
        current_approval
    ):
        return _dkss_common.redirect(
            _dkss_common.url_for("checklist_result_detail", result_index=result_index)
        )

    reject_reason = _dkss_common.request.form.get(
        "reject_reason",
        ""
    ).strip()

    form_errors = []

    if not reject_reason:
        form_errors.append(
            (
                "差し戻し理由を入力してください。",
                "reject_reason"
            )
        )

    elif len(reject_reason) > 5000:
        form_errors.append(
            (
                "差し戻し理由は5000文字以内で入力してください。",
                "reject_reason"
            )
        )

    if form_errors:
        return _dkss_http.return_form_errors(form_errors)

    previous_approvals = [
        dict(approval)
        for approval in approvals
    ]

    for approval in approvals:
        approval["approved_by"] = ""
        approval["approved_by_username"] = ""
        approval["approved_date"] = ""

    result_record.approvals_json = _dkss_common.json.dumps(
        approvals,
        ensure_ascii=False
    )

    result_record.status = "差し戻し"
    result_record.approved_by = ""
    result_record.approved_by_username = ""
    result_record.approved_date = ""
    result_record.reject_reason = reject_reason

    checklist_event = _dkss_models.ChecklistEvent(
        company_code=result_record.company_code,
        result_type="safety",
        result_id=result_record.id,
        event_type="差し戻し",
        actor_username=_dkss_common.session.get("username"),
        actor_name=_dkss_common.session.get("name"),
        detail_json=_dkss_common.json.dumps(
            {
                "reject_reason": reject_reason,
                "approval_label": (
                    current_approval.get("label", "")
                    if current_approval
                    else ""
                ),
                "previous_approvals": previous_approvals,
            },
            ensure_ascii=False
        ),
        created_at=_dkss_common.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    _dkss_common.db.session.add(checklist_event)

    notify_usernames = set()

    if result_record.checked_by_username:
        notify_usernames.add(
            result_record.checked_by_username
        )

    _dkss_common.db.session.commit()

    for target_username in notify_usernames:
        target_user = _dkss_models.User.query.filter_by(
            company_code=result_record.company_code,
            username=target_username
        ).first()

        if not target_user:
            continue

        _dkss_notifications_delivery.add_notification(
            (target_user.last_name or "") + (target_user.first_name or ""),
            "チェックリストが差し戻されました",
            reject_reason or "チェックリストが差し戻されました。",
            f"/safety/checklist-results/{result_record.id}",
            company_code=result_record.company_code,
            target_identity=target_user.account_identity,
            target_username=target_user.username,
            workflow_context=_dkss_notifications_delivery.build_notification_workflow_context(
                result_record,
                "safety",
                "correction"
            )
        )

    return _dkss_common.redirect(f"/safety/checklist-results/{result_record.id}")
