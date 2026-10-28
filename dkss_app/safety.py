"""Safety responsibilities; routes are registered by the application factory."""
from . import audit as _dkss_audit, checklist_common as _dkss_checklist_common, common as _dkss_common, http as _dkss_http, master_readers as _dkss_master_readers, models as _dkss_models, notifications_delivery as _dkss_notifications_delivery, runtime as _dkss_runtime, safety_permissions as _dkss_safety_permissions, serialization as _dkss_serialization, storage as _dkss_storage, vehicle_readers as _dkss_vehicle_readers


def safety():
    return _dkss_common.redirect("/pointouts")



def pointouts():
    role = _dkss_common.session.get("role")

    view_type = _dkss_common.request.args.get("type", "user")
    if view_type not in _dkss_common.PATROL_VIEW_TYPES:
        view_type = "user"

    keyword = _dkss_common.request.args.get("keyword", "").strip()
    office_filter = _dkss_common.request.args.get("office", "").strip()
    status_filter = _dkss_common.request.args.get("status", "").strip()
    category = _dkss_common.request.args.get("category", "").strip()
    date_from = _dkss_common.request.args.get("date_from", "").strip()
    date_to = _dkss_common.request.args.get("date_to", "").strip()
    mine = _dkss_common.request.args.get("mine") == "1"
    pending = _dkss_common.request.args.get("pending") == "1"

    if len(keyword) > 100:
        return "検索条件が長すぎます。", 400

    for date_value in [date_from, date_to]:
        if not date_value:
            continue

        try:
            _dkss_common.datetime.strptime(
                date_value,
                "%Y-%m-%d"
            )
        except ValueError:
            return "発生日の検索条件が不正です。", 400

    if (
        date_from
        and date_to
        and date_from > date_to
    ):
        return "発生日の開始日と終了日が不正です。", 400

    query = _dkss_models.PatrolResult.query.filter(
        _dkss_models.PatrolResult.company_code == _dkss_common.session.get("company_code"),
        _dkss_models.PatrolResult.target_type == view_type
    )

    if office_filter:
        query = query.filter(
            _dkss_models.PatrolResult.office == office_filter
        )

    if status_filter == "not_started":
        query = query.filter(
            _dkss_models.PatrolResult.category != "Good",
            _dkss_models.PatrolResult.countermeasure == ""
        )
    elif status_filter == "waiting":
        query = query.filter(
            _dkss_models.PatrolResult.category != "Good",
            _dkss_models.PatrolResult.countermeasure != "",
            _dkss_models.PatrolResult.approval_status == "承認待ち"
        )
    elif status_filter == "rejected":
        query = query.filter(
            _dkss_models.PatrolResult.category != "Good",
            _dkss_models.PatrolResult.approval_status == "差し戻し"
        )
    elif status_filter == "approved":
        query = query.filter(
            _dkss_models.PatrolResult.category != "Good",
            _dkss_models.PatrolResult.approval_status == "承認済み"
        )
    elif status_filter == "none":
        query = query.filter(
            _dkss_models.PatrolResult.category == "Good"
        )

    if mine and view_type == "user":
        query = query.filter(
            _dkss_models.PatrolResult.target_username
            == _dkss_common.session.get("username")
        )

    if pending:
        query = query.filter(
            _dkss_models.PatrolResult.category != "Good",
            _dkss_models.PatrolResult.approval_status != "承認済み"
        )

    if category:
        query = query.filter(
            _dkss_models.PatrolResult.category == category
        )

    if date_from:
        query = query.filter(
            _dkss_models.PatrolResult.date >= date_from
        )

    if date_to:
        query = query.filter(
            _dkss_models.PatrolResult.date <= date_to
        )

    if keyword:
        keyword_like = f"%{keyword}%"

        keyword_filters = [
            _dkss_models.PatrolResult.office.ilike(keyword_like),
            _dkss_models.PatrolResult.content.ilike(keyword_like),
            _dkss_models.PatrolResult.content_type.ilike(keyword_like),
        ]

        if view_type == "user":
            keyword_filters.append(
                _dkss_models.PatrolResult.target_user.ilike(keyword_like)
            )
        elif view_type == "delivery_place":
            keyword_filters.append(
                _dkss_models.PatrolResult.delivery_place.ilike(keyword_like)
            )

        query = query.filter(
            _dkss_common.or_(*keyword_filters)
        )

    result_records = query.order_by(
        _dkss_models.PatrolResult.id.desc()
    ).all()

    visible_results = []

    for result_record in result_records:
        result = _dkss_checklist_common.patrol_result_to_dict(result_record)

        if not _dkss_safety_permissions.can_view_patrol_result(result):
            continue

        result["can_manage"] = _dkss_safety_permissions.can_edit_patrol_result(result)
        visible_results.append(result)

    # 現在のタブの全記録を、閲覧権限に従って集計する
    # ページ分割やステータス絞り込みの影響を受けない
    summary_records = _dkss_models.PatrolResult.query.filter(
        _dkss_models.PatrolResult.company_code == _dkss_common.session.get("company_code"),
        _dkss_models.PatrolResult.target_type == view_type
    ).all()

    patrol_stats = {
        "total": 0,
        "waiting": 0,
        "approved": 0,
        "not_started": 0,
        "rejected": 0,
        "none": 0
    }

    for summary_record in summary_records:
        summary_item = _dkss_checklist_common.patrol_result_to_dict(summary_record)

        if not _dkss_safety_permissions.can_view_patrol_result(summary_item):
            continue

        patrol_stats["total"] += 1

        if summary_item.get("category") == "Good":
            patrol_stats["none"] += 1
            continue

        if not summary_item.get("countermeasure"):
            patrol_stats["not_started"] += 1
        elif summary_item.get("approval_status") == "承認待ち":
            patrol_stats["waiting"] += 1
        elif summary_item.get("approval_status") == "承認済み":
            patrol_stats["approved"] += 1
        elif summary_item.get("approval_status") == "差し戻し":
            patrol_stats["rejected"] += 1
        else:
            patrol_stats["not_started"] += 1

    allowed_page_sizes = {5, 8, 10, 20, 50}

    try:
        page_size = int(
            _dkss_common.request.args.get(
                "page_size",
                "10"
            )
        )
    except ValueError:
        page_size = 10

    if page_size not in allowed_page_sizes:
        page_size = 10

    try:
        page = max(
            int(
                _dkss_common.request.args.get(
                    "page",
                    "1"
                )
            ),
            1
        )
    except ValueError:
        page = 1

    total_results = len(
        visible_results
    )

    total_pages = max(
        1,
        (
            total_results
            + page_size
            - 1
        ) // page_size
    )

    if page > total_pages:
        page = total_pages

    start_index = (
        page - 1
    ) * page_size

    paginated_results = (
        visible_results[
            start_index:
            start_index + page_size
        ]
    )

    driver_options = _dkss_models.Driver.query.filter(
        _dkss_models.Driver.company_code == _dkss_common.session.get("company_code")
    ).order_by(
        _dkss_models.Driver.name.asc()
    ).all()

    return _dkss_common.render_template(
        "pointouts.html",
        patrol_results=paginated_results,
        patrol_stats=patrol_stats,
        total_results=total_results,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        view_type=view_type,
        keyword=keyword,
        office_filter=office_filter,
        status_filter=status_filter,
        category_filter=category,
        date_from=date_from,
        date_to=date_to,
        role=role,
        show_target_user=view_type == "user",
        drivers=driver_options,
        offices=_dkss_master_readers.offices_for_current_company(),
        delivery_places=_dkss_master_readers.delivery_places_for_current_company(),
    )



def new_pointout():
    if _dkss_common.request.method == "POST":
        company_code = _dkss_common.session.get("company_code")
        form_errors = []

        target_type = _dkss_common.request.form.get(
            "target_type",
            ""
        ).strip()

        target_user = _dkss_common.request.form.get(
            "target_user",
            ""
        ).strip()
        target_username = ""

        delivery_place = _dkss_common.request.form.get(
            "delivery_place",
            ""
        ).strip()

        content_type = _dkss_common.request.form.get(
            "content_type",
            ""
        ).strip()

        category = _dkss_common.request.form.get(
            "category",
            ""
        ).strip()

        content = _dkss_common.request.form.get(
            "content",
            ""
        ).strip()

        date = _dkss_common.request.form.get(
            "date",
            ""
        ).strip()
        if category not in {
            "安全",
            "品質",
            "Good"
        }:
            form_errors.append((
                "分類が不正です。",
                "category"
            ))

        if not date:
            form_errors.append((
                "発生日を入力してください。",
                "event_date"
            ))
        else:
            try:
                _dkss_common.datetime.strptime(
                    date,
                    "%Y-%m-%d"
                )
            except ValueError:
                form_errors.append((
                    "発生日が不正です。",
                    "event_date"
                ))
        # 対象種別検証

        if target_type not in _dkss_common.PATROL_VIEW_TYPES:
            form_errors.append((
                "対象種別が不正です。",
                "target_type"
            ))

        target_office = _dkss_common.session.get("office") or ""

        # 対象ユーザー検証

        if target_type == "user":
            if not target_user:
                form_errors.append((
                    "対象ユーザーを選択してください。",
                    "target_user_search"
                ))
            else:
                target_driver = _dkss_models.Driver.query.filter_by(
                    company_code=company_code,
                    employee_id=target_user
                ).first()

                if not target_driver:
                    form_errors.append((
                        "対象ユーザーが不正です。",
                        "target_user_search"
                    ))
                else:
                    target_user_record = _dkss_models.User.query.filter_by(
                        company_code=company_code,
                        username=target_driver.employee_id
                    ).first()

                    if not target_user_record:
                        form_errors.append((
                            "対象ユーザー情報が不正です。",
                            "target_user_search"
                        ))
                    else:
                        target_username = target_user_record.username
                        target_identity = target_user_record.account_identity
                        target_user = target_driver.name
                        target_office = target_driver.office or ""

            delivery_place = ""

        # 納入先検証

        elif target_type == "delivery_place":
            if not delivery_place:
                form_errors.append((
                    "納入先を選択してください。",
                    "delivery_place"
                ))

            if delivery_place:
                # Keep validated master names present until the history commits.
                valid_delivery_place = _dkss_models.DeliveryPlace.query.filter_by(
                    company_code=company_code,
                    name=delivery_place
                ).with_for_update(read=True).first()

                if not valid_delivery_place:
                    form_errors.append((
                        "納入先が不正です。",
                        "delivery_place"
                    ))

            target_user = ""

        # 内容区分検証

        if content_type:
            valid_content_type = _dkss_models.PatrolContentType.query.filter_by(
                company_code=company_code,
                name=content_type
            ).with_for_update(read=True).first()

            if not valid_content_type:
                form_errors.append((
                    "内容区分が不正です。",
                    "content_type"
                ))

        if not _dkss_master_readers.office_reference_is_current(company_code, target_office):
            form_errors.append(("営業所が更新されています。画面を再読み込みしてください。", "target_user_search"))

        if len(content) > 5000:
            form_errors.append((
                "内容は5000文字以内で入力してください。",
                "content_editor"
            ))

        if form_errors:
            return _dkss_http.return_form_errors(form_errors)

        # 添付ファイル

        uploaded_files = [
            file
            for file in _dkss_common.request.files.getlist("files")
            if file and file.filename
        ]

        file_names = []

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
                return "添付ファイルの検証に失敗しました。", 400

        for file in uploaded_files:
            filename = _dkss_storage.save_uploaded_file(file)

            if filename:
                file_names.append(filename)

        # 登録

        result = _dkss_models.PatrolResult(
            company_code=company_code,
            created_by_username=_dkss_common.session.get("username"),
            created_by_name=_dkss_common.session.get("name"),
            date=date,
            office=target_office,
            category=category,
            content_type=content_type,
            target_type=target_type,
            target_user=target_user,
            target_username=(
                target_username
                if target_type == "user"
                else ""
            ),
            delivery_place=delivery_place,
            content=content,
            files_json=_dkss_common.json.dumps(
                file_names,
                ensure_ascii=False
            ),
            countermeasure="",
            approval_status="未対応",
            reject_reason=""
        )

        _dkss_common.db.session.add(result)
        _dkss_common.db.session.commit()

        # 個人対象のときだけ通知
        if target_type == "user":
            _dkss_notifications_delivery.add_notification(
                result.target_user,
                "安全パトロール確認依頼",
                "あなたに確認が必要な安全パトロールがあります。",
                f"/pointouts/{result.id}",
                company_code=company_code,
                target_identity=target_identity,
                target_username=result.target_username
            )

        _dkss_notifications_delivery.notify_mentions(
            result.content,
            f"/pointouts/{result.id}"
        )

        if target_type == "delivery_place":
            return _dkss_common.redirect(
                "/pointouts?type=delivery_place"
            )

        return _dkss_common.redirect(
            "/pointouts?type=user"
        )
    requested_target_type = _dkss_common.request.args.get(
        "target_type",
        ""
    ).strip()

    form_target_type = _dkss_common.session.pop(
        "pointout_form_target_type",
        (
            requested_target_type
            if requested_target_type in {
                "user",
                "delivery_place"
            }
            else "user"
        )
    )

    form_data = _dkss_common.session.pop(
        "pointout_form_data",
        {}
    )

    return _dkss_common.render_template(
        "new_pointout.html",
        form_target_type=form_target_type,
        form_data=form_data,
        drivers=_dkss_vehicle_readers.drivers_for_current_company(),
        delivery_places=_dkss_master_readers.delivery_places_for_current_company(),
        manuals=_dkss_master_readers.manuals_for_current_company(),
        content_types=_dkss_master_readers.patrol_content_types_for_current_company(),
    )



def pointout_detail(index):
    result_record = _dkss_models.PatrolResult.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not result_record:
        return _dkss_common.redirect("/pointouts")

    result = _dkss_checklist_common.patrol_result_to_dict(result_record)

    if not _dkss_safety_permissions.can_view_patrol_result(result):
        return _dkss_common.redirect("/pointouts")

    countermeasure_form_data = _dkss_common.session.pop(
        "countermeasure_form_data",
        {}
    )

    pointout_reject_form_data = _dkss_common.session.pop(
        "pointout_reject_form_data",
        {}
    )

    return _dkss_common.render_template(
        "pointout_detail.html",
        result=result,
        index=result_record.id,
        manuals=_dkss_master_readers.manuals_for_current_company(),
        drivers=_dkss_vehicle_readers.drivers_for_current_company(),
        countermeasure_form_data=countermeasure_form_data,
        pointout_reject_form_data=pointout_reject_form_data,
        can_manage=_dkss_safety_permissions.can_edit_patrol_result(result),
        can_countermeasure=_dkss_safety_permissions.can_countermeasure_patrol_result(
            result
        ),
        can_approve=_dkss_safety_permissions.can_approve_patrol_result(result),
    )



def edit_pointout(index):

    result_record = _dkss_models.PatrolResult.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not result_record:
        return _dkss_common.redirect("/pointouts")

    if result_record.approval_status == "承認済み":
        return _dkss_common.redirect(_dkss_common.url_for("pointout_detail", index=index))

    result = _dkss_checklist_common.patrol_result_to_dict(result_record)

    if not _dkss_safety_permissions.can_edit_patrol_result(result):
        return _dkss_common.redirect(_dkss_common.url_for("pointout_detail", index=index))

    pointout_edit_form_data = _dkss_common.session.pop(
        "pointout_edit_form_data",
        {}
    )

    if _dkss_common.request.method == "POST":
        company_code = _dkss_common.session.get("company_code")
        form_errors = []

        date = _dkss_common.request.form.get(
            "date",
            ""
        ).strip()

        category = _dkss_common.request.form.get(
            "category",
            ""
        ).strip()

        if category not in {
            "安全",
            "品質",
            "Good"
        }:
            form_errors.append((
                "分類が不正です。",
                "category"
            ))

        if not date:
            form_errors.append((
                "発生日を入力してください。",
                "event_date"
            ))
        else:
            try:
                _dkss_common.datetime.strptime(
                    date,
                    "%Y-%m-%d"
                )
            except ValueError:
                form_errors.append((
                    "発生日が不正です。",
                    "event_date"
                ))

        content_type = _dkss_common.request.form.get(
            "content_type",
            ""
        ).strip()

        content = _dkss_common.request.form.get(
            "content",
            ""
        ).strip()

        if len(content) > 5000:
            form_errors.append((
                "内容は5000文字以内で入力してください。",
                "content_editor"
            ))

        # 内容区分検証

        if content_type:
            valid_content_type = _dkss_models.PatrolContentType.query.filter_by(
                company_code=company_code,
                name=content_type
            ).with_for_update(read=True).first()

            if not valid_content_type:
                form_errors.append((
                    "内容区分が不正です。",
                    "content_type"
                ))

        validated_target_user = result_record.target_user
        validated_target_username = result_record.target_username
        validated_office = result_record.office
        validated_delivery_place = result_record.delivery_place

        validated_target_user = result_record.target_user
        validated_target_username = result_record.target_username
        validated_office = result_record.office
        validated_delivery_place = result_record.delivery_place

        # 対象ユーザー検証

        if result_record.target_type == "user":
            target_username = _dkss_common.request.form.get(
                "target_user",
                ""
            ).strip()

            if not target_username:
                form_errors.append((
                    "対象ユーザーを選択してください。",
                    "target_user_search"
                ))
            else:
                target_driver = _dkss_models.Driver.query.filter_by(
                    company_code=company_code,
                    employee_id=target_username
                ).first()

                if not target_driver:
                    form_errors.append((
                        "対象ユーザーが不正です。",
                        "target_user_search"
                    ))
                else:
                    target_user_record = _dkss_models.User.query.filter_by(
                        company_code=company_code,
                        username=target_driver.employee_id
                    ).first()

                    if not target_user_record:
                        form_errors.append((
                            "対象ユーザー情報が不正です。",
                            "target_user_search"
                        ))
                    else:
                        validated_target_user = (
                            target_driver.name
                        )
                        validated_target_username = (
                            target_user_record.username
                        )
                        validated_office = (
                            target_driver.office or ""
                        )
                        validated_delivery_place = ""

        # 納入先検証

        elif result_record.target_type == "delivery_place":
            delivery_place = _dkss_common.request.form.get(
                "delivery_place",
                ""
            ).strip()

            if not delivery_place:
                form_errors.append(
                    "納入先を選択してください。"
                )
            else:
                valid_delivery_place = _dkss_models.DeliveryPlace.query.filter_by(
                    company_code=company_code,
                    name=delivery_place
                ).with_for_update(read=True).first()

                if not valid_delivery_place:
                    form_errors.append((
                        "納入先が不正です。",
                        "delivery_place"
                    ))
                else:
                    validated_delivery_place = delivery_place
                    validated_target_user = ""
                    validated_target_username = ""

        else:
            return "対象種別が不正です。", 400

        if form_errors:
            return _dkss_http.return_form_errors(form_errors)

        if result_record.target_type == "user" and not _dkss_master_readers.office_reference_is_current(
            company_code, validated_office
        ):
            return _dkss_http.return_form_errors([
                ("営業所が更新されています。画面を再読み込みしてください。", "target_user_search")
            ])

        # 既存添付

        files = _dkss_serialization.safe_json_str_list(
            result_record.files_json
        )

        delete_files = _dkss_common.request.form.getlist(
            "delete_files"
        )

        if len(delete_files) > 50:
            return (
                "一度に削除できる添付ファイルは50件までです。",
                400
            )

        pending_delete_files = []

        for delete_file in delete_files:
            delete_file = _dkss_common.os.path.basename(
                delete_file
            )

            if delete_file not in files:
                continue

            files.remove(delete_file)
            pending_delete_files.append(delete_file)

        # 新規添付

        uploaded_files = [
            file
            for file in _dkss_common.request.files.getlist(
                "files"
            )
            if file and file.filename
        ]

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
                return "添付ファイルの検証に失敗しました。入力内容を確認してください。", 400

        for file in uploaded_files:
            filename = _dkss_storage.save_uploaded_file(file)

            if filename:
                files.append(filename)

        result_record.date = date
        result_record.category = category
        result_record.content_type = content_type
        result_record.content = content
        result_record.target_user = validated_target_user
        result_record.target_username = validated_target_username
        result_record.office = validated_office
        result_record.delivery_place = validated_delivery_place

        result_record.files_json = _dkss_common.json.dumps(
            files,
            ensure_ascii=False
        )

        _dkss_common.db.session.commit()

        for delete_file in pending_delete_files:
            deleted = False

            if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
                try:
                    _dkss_runtime.app.extensions["dkss"]['s3_client'].delete_object(
                        Bucket=_dkss_runtime.app.config['S3_BUCKET_NAME'],
                        Key=(
                            f"uploads/"
                            f"{company_code}/"
                            f"{delete_file}"
                        )
                    )
                    deleted = True
                except _dkss_common.ClientError:
                    print(
                        "S3添付ファイル削除エラー"
                    )
            else:
                safe_file_name = _dkss_common.secure_filename(delete_file)

                if not safe_file_name:
                    continue

                file_path = _dkss_common.os.path.join(
                    _dkss_runtime.app.config["UPLOAD_FOLDER"],
                    company_code,
                    safe_file_name
                )

                if _dkss_common.os.path.exists(file_path):
                    _dkss_common.os.remove(file_path)

                deleted = True

            if deleted:
                _dkss_audit.add_audit_log(
                    action="file_deleted",
                    target_type="file",
                    target_id=delete_file,
                    detail="安全パトロール添付ファイル削除",
                    company_code=company_code,
                )

        _dkss_common.db.session.commit()

        _dkss_notifications_delivery.notify_mentions(
            result_record.content,
            f"/pointouts/{result_record.id}"
        )

        return _dkss_common.redirect(
            f"/pointouts/{result_record.id}"
        )

    return _dkss_common.render_template(
        "edit_pointout.html",
        result=result,
        index=result_record.id,
        drivers=_dkss_vehicle_readers.drivers_for_current_company(),
        delivery_places=_dkss_master_readers.delivery_places_for_current_company(),
        manuals=_dkss_master_readers.manuals_for_current_company(),
        pointout_edit_form_data=pointout_edit_form_data,
    )



def register_countermeasure(index):
    result_record = _dkss_models.PatrolResult.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not result_record:
        return _dkss_common.redirect("/pointouts")

    if result_record.approval_status == "承認済み":
        return _dkss_common.redirect(_dkss_common.url_for("pointout_detail", index=index))

    result = _dkss_checklist_common.patrol_result_to_dict(result_record)

    if not _dkss_safety_permissions.can_countermeasure_patrol_result(result):
        return _dkss_common.redirect(_dkss_common.url_for("pointout_detail", index=index))

    form_errors = []

    countermeasure = _dkss_common.request.form.get(
        "countermeasure",
        ""
    ).strip()

    if not countermeasure:
        form_errors.append((
            "対策内容を入力してください。",
            "countermeasure"
        ))
    elif len(countermeasure) > 5000:
        form_errors.append((
            "対策内容は5000文字以内で入力してください。",
            "countermeasure"
        ))

    countermeasure_by_employee_id = _dkss_common.request.form.get(
        "countermeasure_by",
        ""
    ).strip()

    countermeasure_driver = None
    countermeasure_user = None

    if not countermeasure_by_employee_id:
        form_errors.append((
            "対応者を選択してください。",
            "countermeasure_by_search"
        ))
    else:
        countermeasure_driver = _dkss_models.Driver.query.filter_by(
            company_code=result_record.company_code,
            employee_id=countermeasure_by_employee_id
        ).first()

        if not countermeasure_driver:
            form_errors.append((
                "対応者が不正です。",
                "countermeasure_by_search"
            ))
        else:
            countermeasure_user = _dkss_models.User.query.filter_by(
                company_code=result_record.company_code,
                username=countermeasure_driver.employee_id
            ).first()

            if not countermeasure_user:
                form_errors.append((
                    "対応者情報が不正です。",
                    "countermeasure_by_search"
                ))

    countermeasure_due_date = _dkss_common.request.form.get(
        "countermeasure_due_date",
        ""
    ).strip()

    if countermeasure_due_date:
        try:
            _dkss_common.datetime.strptime(
                countermeasure_due_date,
                "%Y-%m-%d"
            )
        except ValueError:
            form_errors.append((
                "対応期限が不正です。",
                "countermeasure_due_date"
            ))

    if form_errors:
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

        for message in form_errors:
            _dkss_common.flash(
                message,
                f"error:{_dkss_http.get_form_error_field(message) or ''}"
            )

        if result_record.countermeasure:
            return _dkss_common.redirect(
                f"/pointouts/{result_record.id}?edit_countermeasure=1"
            )

        return _dkss_common.redirect(
            f"/pointouts/{result_record.id}"
        )

    countermeasure_files = _dkss_serialization.safe_json_str_list(
        result_record.countermeasure_files_json
    )

    delete_countermeasure_files = _dkss_common.request.form.getlist(
        "delete_countermeasure_files"
    )

    if len(delete_countermeasure_files) > 50:
        return (
            "一度に削除できる添付ファイルは50件までです。",
            400
        )

    pending_delete_countermeasure_files = []

    for delete_file in delete_countermeasure_files:
        delete_file = _dkss_common.os.path.basename(
            delete_file
        )

        if delete_file not in countermeasure_files:
            continue

        countermeasure_files.remove(delete_file)

        pending_delete_countermeasure_files.append(
            delete_file
        )

    uploaded_countermeasure_files = [
        file
        for file in _dkss_common.request.files.getlist(
            "countermeasure_files"
        )
        if file and file.filename
    ]

    for file in uploaded_countermeasure_files:
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

    for file in uploaded_countermeasure_files:
        try:
            saved_file = _dkss_storage.save_uploaded_file(file)
        except _dkss_common.UploadValidationError:
            return "添付ファイルの検証に失敗しました。", 400

        if saved_file:
            countermeasure_files.append(saved_file)

    result_record.countermeasure = countermeasure

    result_record.countermeasure_files_json = _dkss_common.json.dumps(
        countermeasure_files,
        ensure_ascii=False
    )

    result_record.countermeasure_by = (
        countermeasure_driver.name
    )

    result_record.countermeasure_by_username = (
        countermeasure_user.username
    )

    result_record.countermeasure_due_date = (
        countermeasure_due_date
    )

    result_record.approval_status = "承認待ち"
    result_record.reject_reason = ""

    _dkss_common.db.session.commit()

    for delete_file in pending_delete_countermeasure_files:
        deleted = False

        if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
            try:
                _dkss_runtime.app.extensions["dkss"]['s3_client'].delete_object(
                    Bucket=_dkss_runtime.app.config['S3_BUCKET_NAME'],
                    Key=(
                        f"uploads/"
                        f"{result_record.company_code}/"
                        f"{delete_file}"
                    )
                )
                deleted = True
            except _dkss_common.ClientError:
                print(
                    "S3対策添付ファイル削除エラー"
                )
        else:
            safe_file_name = _dkss_common.secure_filename(
                delete_file
            )

            if not safe_file_name:
                continue

            file_path = _dkss_common.os.path.join(
                _dkss_runtime.app.config["UPLOAD_FOLDER"],
                result_record.company_code,
                safe_file_name
            )

            if _dkss_common.os.path.exists(file_path):
                _dkss_common.os.remove(file_path)
                deleted = True

    _dkss_notifications_delivery.notify_mentions(
        result_record.countermeasure,
        f"/pointouts/{result_record.id}"
    )

    return _dkss_common.redirect(f"/pointouts/{result_record.id}")



def approve_countermeasure(index):
    result_record = _dkss_models.PatrolResult.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not result_record:
        return _dkss_common.redirect("/pointouts")

    if result_record.approval_status != "承認待ち":
        return _dkss_common.redirect(_dkss_common.url_for("pointout_detail", index=index))

    result = _dkss_checklist_common.patrol_result_to_dict(result_record)

    if not _dkss_safety_permissions.can_approve_patrol_result(result):
        return _dkss_common.redirect(_dkss_common.url_for("pointout_detail", index=index))

    result_record.approval_status = "承認済み"
    result_record.reject_reason = ""

    notify_usernames = {
        username
        for username in [
            result_record.created_by_username,
            result_record.target_username,
            result_record.countermeasure_by_username
        ]
        if username
    }

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
            "安全パトロールが承認されました",
            "安全パトロールの対応が承認されました。",
            f"/pointouts/{result_record.id}",
            company_code=result_record.company_code,
            target_identity=target_user.account_identity,
            target_username=target_user.username
        )

    return _dkss_common.redirect(f"/pointouts/{result_record.id}")



def reject_countermeasure(index):
    result_record = _dkss_models.PatrolResult.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not result_record:
        return _dkss_common.redirect("/pointouts")

    if result_record.approval_status != "承認待ち":
        return _dkss_common.redirect(_dkss_common.url_for("pointout_detail", index=index))

    result = _dkss_checklist_common.patrol_result_to_dict(result_record)

    if not _dkss_safety_permissions.can_approve_patrol_result(result):
        return _dkss_common.redirect(_dkss_common.url_for("pointout_detail", index=index))

    reject_reason = _dkss_common.request.form.get(
        "reject_reason",
        ""
    ).strip()

    if not reject_reason:
        return "差し戻し理由を入力してください。", 400

    if len(reject_reason) > 5000:
        return "差し戻し理由は5000文字以内で入力してください。", 400

    result_record.approval_status = "差し戻し"
    result_record.reject_reason = reject_reason

    notify_usernames = set()

    if result_record.created_by_username:
        notify_usernames.add(
            result_record.created_by_username
        )

    if result_record.target_username:
        notify_usernames.add(
            result_record.target_username
        )

    if result_record.countermeasure_by_username:
        notify_usernames.add(
            result_record.countermeasure_by_username
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
            "安全パトロールが差し戻されました",
            reject_reason
            or "安全パトロールが差し戻されました。",
            f"/pointouts/{result_record.id}",
            company_code=result_record.company_code,
            target_identity=target_user.account_identity,
            target_username=target_user.username
        )

    _dkss_notifications_delivery.notify_mentions(
        reject_reason,
        f"/pointouts/{result_record.id}"
    )

    return _dkss_common.redirect(f"/pointouts/{result_record.id}")



def delete_pointout(index):
    result_record = _dkss_models.PatrolResult.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not result_record:
        return _dkss_common.redirect("/pointouts")

    if result_record.approval_status == "承認済み":
        return _dkss_common.redirect(_dkss_common.url_for("pointout_detail", index=index))

    result = _dkss_checklist_common.patrol_result_to_dict(result_record)

    if not _dkss_safety_permissions.can_delete_patrol_result(result):
        return _dkss_common.redirect(_dkss_common.url_for("pointout_detail", index=index))

    view_type = result.get("target_type", "user")

    files_to_delete = (
        _dkss_serialization.safe_json_str_list(
            result_record.files_json
        )
        + _dkss_serialization.safe_json_str_list(
            result_record.countermeasure_files_json
        )
    )

    _dkss_audit.add_audit_log(
        action="patrol_result_deleted",
        target_type="patrol_result",
        target_id=result_record.id,
        detail=f"安全パトロール結果削除: target_type={view_type}",
        company_code=result_record.company_code,
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

        checklist_results = _dkss_models.ChecklistResult.query.filter_by(
            company_code=company_code
        ).all()

        for checklist_result in checklist_results:
            answers = _dkss_serialization.safe_json_dict_list(
                checklist_result.answers_json
            )

            if any(
                filename in answer.get("files", [])
                for answer in answers
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
                    "安全パトロール添付ファイルのS3削除に失敗しました。",
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

    return _dkss_common.redirect(f"/pointouts?type={view_type}")
