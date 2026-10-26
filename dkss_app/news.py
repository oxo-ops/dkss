"""News responsibilities; routes are registered by the application factory."""
from . import access as _dkss_access, audit as _dkss_audit, common as _dkss_common, http as _dkss_http, master_readers as _dkss_master_readers, models as _dkss_models, notifications_delivery as _dkss_notifications_delivery, runtime as _dkss_runtime, serialization as _dkss_serialization, storage as _dkss_storage


def itc_new_news():
    if not _dkss_access.require_itc():
        return _dkss_common.redirect("/")

    company_code = _dkss_common.session.get("company_code")

    if _dkss_common.request.method == "POST":
        form_errors = []
        form_error_status = 400

        title = _dkss_common.request.form.get("title", "").strip()
        message = _dkss_common.request.form.get("message", "")

        if not title:
            form_errors.append((
                "タイトルを入力してください。",
                "title"
            ))
        elif len(title) > 200:
            form_errors.append((
                "タイトルは200文字以内で入力してください。",
                "title"
            ))

        if len(message) > 10000:
            form_errors.append((
                "本文は10000文字以内で入力してください。",
                "message_editor"
            ))

        target_type = _dkss_common.request.form.get("target_type")
        target_value = _dkss_common.request.form.get("target_value", "").strip()

        # 通知対象を現在の会社内だけに限定

        user_query = _dkss_models.User.query.filter_by(
            company_code=company_code
        )

        target_users = []

        if target_type == "all":
            target_users = user_query.all()

        elif target_type == "admins":
            target_users = user_query.filter_by(
                role="admin"
            ).all()

        elif target_type == "company":
            # 他社コードをPOSTされても無視する
            if target_value != company_code:
                form_errors.append((
                    "対象会社が不正です。",
                    "target_company"
                ))
                form_error_status = 403
            else:
                target_users = user_query.all()

        elif target_type == "office":
            valid_office = _dkss_models.Office.query.filter_by(
                company_code=company_code,
                name=target_value
            ).first()

            if not valid_office:
                form_errors.append((
                    "対象営業所が不正です。",
                    "target_office"
                ))
                form_error_status = 403
            else:
                target_users = user_query.filter_by(
                    office=target_value
                ).all()

        elif target_type == "user":
            target_user = _dkss_models.User.query.filter_by(
                company_code=company_code,
                username=target_value
            ).first()

            if not target_user:
                form_errors.append((
                    "対象ユーザーが不正です。",
                    "target_user_search"
                ))
                form_error_status = 403
            else:
                target_users = [target_user]

        else:
            form_errors.append((
                "通知対象が不正です。",
                "target_type"
            ))

        if form_errors:
            return _dkss_http.return_form_errors(
                form_errors,
                form_error_status
            )

        file_names = []

        uploaded_files = [
            file
            for file in _dkss_common.request.files.getlist("files")
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
                return "添付ファイルの検証に失敗しました。", 400

        for file in uploaded_files:
            filename = _dkss_storage.save_uploaded_file(file)

            if filename:
                file_names.append(filename)

        # News登録

        _dkss_notifications_delivery.add_news(
            title,
            message,
            files=file_names,
            target_type=target_type,
            target_value=target_value
        )

        # 通知登録

        for user in target_users:
            _dkss_notifications_delivery.add_notification(
                (
                    f"{user.last_name or ''}"
                    f"{user.first_name or ''}"
                ),
                title,
                message,
                "",
                files=file_names,
                company_code=company_code,
                target_username=user.username
            )

        _dkss_notifications_delivery.notify_mentions(
            message,
            "/notifications"
        )

        return _dkss_common.redirect("/itc")

    # GET

    company = _dkss_models.Company.query.filter_by(
        company_code=company_code
    ).first()

    companies = [company] if company else []

    users = _dkss_models.User.query.filter(
        _dkss_models.User.company_code == company_code,
        _dkss_models.User.role != "itc"
    ).all()

    return _dkss_common.render_template(
        "itc_news_form.html",
        companies=companies,
        offices=_dkss_master_readers.offices_for_current_company(),
        users=users,
        news=None,
        mode="new"
    )



def itc_edit_news(index):
    if not _dkss_access.require_itc():
        return _dkss_common.redirect("/")

    company_code = _dkss_common.session.get("company_code")

    news = _dkss_models.News.query.filter_by(
        id=index,
        company_code=company_code
    ).first()

    if not news:
        return _dkss_common.redirect("/itc")

    if _dkss_common.request.method == "POST":
        form_errors = []
        form_error_status = 400

        target_type = _dkss_common.request.form.get("target_type")
        target_value = _dkss_common.request.form.get(
            "target_value",
            ""
        ).strip()

        # 通知対象を現在の会社内だけに限定

        if target_type == "company":
            if target_value != company_code:
                form_errors.append((
                    "対象会社が不正です。",
                    "target_company"
                ))
                form_error_status = 403

        elif target_type == "office":
            valid_office = _dkss_models.Office.query.filter_by(
                company_code=company_code,
                name=target_value
            ).first()

            if not valid_office:
                form_errors.append((
                    "対象営業所が不正です。",
                    "target_office"
                ))
                form_error_status = 403

        elif target_type == "user":
            valid_user = _dkss_models.User.query.filter_by(
                company_code=company_code,
                username=target_value
            ).first()

            if not valid_user:
                form_errors.append((
                    "対象ユーザーが不正です。",
                    "target_user_search"
                ))
                form_error_status = 403

        elif target_type not in [
            "all",
            "admins"
        ]:
            form_errors.append((
                "通知対象が不正です。",
                "target_type"
            ))

        title = _dkss_common.request.form.get("title", "").strip()
        message = _dkss_common.request.form.get("message", "")

        if not title:
            form_errors.append((
                "タイトルを入力してください。",
                "title"
            ))
        elif len(title) > 200:
            form_errors.append((
                "タイトルは200文字以内で入力してください。",
                "title"
            ))

        if len(message) > 10000:
            form_errors.append((
                "本文は10000文字以内で入力してください。",
                "message_editor"
            ))

        if form_errors:
            return _dkss_http.return_form_errors(
                form_errors,
                form_error_status
            )

        files = _dkss_serialization.safe_json_str_list(
            news.files_json
        )

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
                return "添付ファイルの検証に失敗しました。", 400

        for file in uploaded_files:
            filename = _dkss_storage.save_uploaded_file(file)

            if filename:
                files.append(filename)

        news.title = title
        news.message = message
        news.target_type = target_type
        news.target_value = target_value

        news.files_json = _dkss_common.json.dumps(
            files,
            ensure_ascii=False
        )

        _dkss_audit.add_audit_log(
            action="news_updated",
            target_type="news",
            target_id=news.id,
            detail=f"お知らせ編集: {news.title}",
            company_code=news.company_code,
        )

        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/itc")

    # GET

    company = _dkss_models.Company.query.filter_by(
        company_code=company_code
    ).first()

    companies = [company] if company else []

    users = _dkss_models.User.query.filter(
        _dkss_models.User.company_code == company_code,
        _dkss_models.User.role != "itc"
    ).all()

    news_dict = {
        "id": news.id,
        "index": news.id,
        "title": news.title,
        "message": news.message,
        "files": _dkss_serialization.safe_json_str_list(
            news.files_json
        ),
        "target_type": news.target_type,
        "target_value": news.target_value,
        "created_at": news.created_at,
    }

    return _dkss_common.render_template(
        "itc_news_form.html",
        news=news_dict,
        index=news.id,
        mode="edit",
        companies=companies,
        offices=_dkss_master_readers.offices_for_current_company(),
        users=users
    )



def itc_delete_news(index):
    if not _dkss_access.require_itc():
        return _dkss_common.redirect("/")

    company_code = _dkss_common.session.get("company_code")

    news = _dkss_models.News.query.filter_by(
        id=index,
        company_code=company_code
    ).first()

    if not news:
        return _dkss_common.redirect("/itc")

    _dkss_audit.add_audit_log(
        action="news_deleted",
        target_type="news",
        target_id=news.id,
        detail=f"お知らせ削除: {news.title}",
        company_code=news.company_code,
    )

    files_to_delete = _dkss_serialization.safe_json_str_list(
        news.files_json
    )

    _dkss_common.db.session.delete(news)
    _dkss_common.db.session.commit()

    for filename in files_to_delete:
        filename = _dkss_common.os.path.basename(
            str(filename or "")
        )

        if not filename:
            continue

        still_referenced = False

        notification_records = _dkss_models.Notification.query.filter_by(
            company_code=company_code
        ).all()

        for notification in notification_records:
            notification_files = _dkss_serialization.safe_json_str_list(
                notification.files_json
            )

            if filename in notification_files:
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
                    "お知らせ添付ファイルのS3削除に失敗しました。",
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

    return _dkss_common.redirect("/itc")
