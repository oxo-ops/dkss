"""Storage responsibilities; routes are registered by the application factory."""
from .account_identity import notification_owner_clause
from . import audit as _dkss_audit, checklist_common as _dkss_checklist_common, common as _dkss_common, models as _dkss_models, runtime as _dkss_runtime, safety_permissions as _dkss_safety_permissions, serialization as _dkss_serialization


def is_valid_uploaded_file(file, extension):
    stream = file.stream
    original_position = stream.tell()

    try:
        stream.seek(0)
        header = stream.read(16)
        stream.seek(0)
        if extension == ".pdf":
            return header.startswith(b"%PDF-")

        if extension == ".png":
            return header.startswith(
                b"\x89PNG\r\n\x1a\n"
            )

        if extension in {".jpg", ".jpeg"}:
            return header.startswith(b"\xff\xd8\xff")

        if extension in {".mp4", ".mov"}:
            return (
                len(header) >= 8
                and header[4:8] == b"ftyp"
            )

        if extension == ".avi":
            return (
                len(header) >= 12
                and header[:4] == b"RIFF"
                and header[8:12] == b"AVI "
            )

        if extension in {".mkv", ".webm"}:
            return header.startswith(
                b"\x1a\x45\xdf\xa3"
            )

        if extension in {".mts", ".m2ts"}:
            return (
                header.startswith(b"\x47")
                or (
                    len(header) >= 5
                    and header[4:5] == b"\x47"
                )
            )

        if extension in {".mpg", ".mpeg"}:
            return header.startswith(
                (b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3")
            )

        if extension in {".docx", ".xlsx"}:
            try:
                with _dkss_common.zipfile.ZipFile(stream) as archive:
                    infos = archive.infolist()

                    if len(infos) > 5000:
                        return False
                    if any(
                        info.file_size > 50 * 1024 * 1024
                        for info in infos
                    ):
                        return False

                    total_uncompressed_size = sum(
                        info.file_size
                        for info in infos
                    )

                    if total_uncompressed_size > 100 * 1024 * 1024:
                        return False

                    if any(
                        (
                            info.file_size > 0
                            and info.compress_size == 0
                        )
                        or (
                            info.file_size > 1024 * 1024
                            and info.compress_size > 0
                            and info.file_size / info.compress_size > 100
                        )
                        for info in infos
                    ):
                        return False

                    names = [
                        info.filename
                        for info in infos
                    ]

                    if extension == ".docx":
                        return (
                            "[Content_Types].xml" in names
                            and "word/document.xml" in names
                        )
                    return (
                        "[Content_Types].xml" in names
                        and "xl/workbook.xml" in names
                    )

            except (
                _dkss_common.zipfile.BadZipFile,
                _dkss_common.zipfile.LargeZipFile,
                OSError,
                RuntimeError,
                ValueError
            ):
                return False

        return False

    finally:
        stream.seek(original_position)



def save_uploaded_file(file, folder=None):
    if not file or not file.filename:
        return ""

    upload_file_count = sum(
        1
        for field_name in _dkss_common.request.files.keys()
        for file in _dkss_common.request.files.getlist(field_name)
        if file and file.filename
    )

    if upload_file_count > 50:
        raise _dkss_common.UploadValidationError(
            "一度にアップロードできるファイルは50件までです。"
        )

    company_code = _dkss_common.session.get("company_code")

    if not company_code:
        raise _dkss_common.UploadValidationError(
            "company_code is required for file upload."
        )

    original_filename = _dkss_common.os.path.basename(
        str(file.filename or "")
    )

    extension = _dkss_common.os.path.splitext(
        original_filename
    )[1].lower()

    if extension not in _dkss_common.ALLOWED_UPLOAD_EXTENSIONS:
        raise _dkss_common.UploadValidationError(
            "許可されていないファイル形式です。"
        )

    if not is_valid_uploaded_file(
        file,
        extension
    ):
        raise _dkss_common.UploadValidationError(
            "ファイルの内容と形式が一致しません。"
        )

    extension_suffixes = {
        ".pdf": ".pdf",
        ".png": ".png",
        ".jpg": ".jpg",
        ".jpeg": ".jpeg",
        ".mp4": ".mp4",
        ".mov": ".mov",
        ".avi": ".avi",
        ".mkv": ".mkv",
        ".webm": ".webm",
        ".mts": ".mts",
        ".m2ts": ".m2ts",
        ".mpg": ".mpg",
        ".mpeg": ".mpeg",
        ".xlsx": ".xlsx",
        ".docx": ".docx",
    }

    filename = (
        f"{_dkss_common.uuid4().hex}"
        f"{extension_suffixes[extension]}"
    )

    if folder == "static/manuals":
        storage_folder = "manuals"
    else:
        storage_folder = "uploads"

    # S3
    # uploads/会社コード/ファイル名
    if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
        object_key = (
            f"{storage_folder}/"
            f"{company_code}/"
            f"{filename}"
        )

        _dkss_runtime.app.extensions["dkss"]['s3_client'].upload_fileobj(
            file,
            _dkss_runtime.app.config['S3_BUCKET_NAME'],
            object_key,
            ExtraArgs={
                "ContentType": _dkss_common.UPLOAD_CONTENT_TYPES[extension],
                "ServerSideEncryption": "AES256",
                "CacheControl": "no-store"
            }
        )

        _dkss_audit.add_audit_log(
            action="file_uploaded",
            target_type="file",
            target_id=filename,
            detail=f"ファイルアップロード: {extension}",
            company_code=company_code,
        )

        return filename

    # ローカル
    # static/uploads/会社コード/
    if storage_folder == "manuals":
        base_folder = "static/manuals"
    else:
        base_folder = _dkss_runtime.app.config["UPLOAD_FOLDER"]

    safe_company_code = _dkss_common.secure_filename(
        str(company_code)
    )

    if (
        not safe_company_code
        or safe_company_code != company_code
    ):
        raise _dkss_common.UploadValidationError(
            "Invalid company code."
        )

    save_folder = _dkss_common.safe_join(
        base_folder,
        safe_company_code
    )

    if not save_folder:
        raise _dkss_common.UploadValidationError(
            "Invalid company code."
        )

    _dkss_common.os.makedirs(
        save_folder,
        exist_ok=True
    )

    save_path = _dkss_common.os.path.join(
        save_folder,
        filename
    )

    file.save(save_path)

    _dkss_audit.add_audit_log(
        action="file_uploaded",
        target_type="file",
        target_id=filename,
        detail=f"ファイルアップロード: {extension}",
        company_code=company_code,
    )

    return filename



def delete_uploaded_file(filename, folder=None):
    company_code = _dkss_common.session.get("company_code")

    if not company_code or not filename:
        return

    filename = _dkss_common.os.path.basename(str(filename))

    if not filename:
        return

    from .profile_images import forget
    forget(company_code, filename)

    if folder == "static/manuals":
        storage_folder = "manuals"
        base_folder = "static/manuals"
    else:
        storage_folder = "uploads"
        base_folder = _dkss_runtime.app.config["UPLOAD_FOLDER"]

    if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
        try:
            _dkss_runtime.app.extensions["dkss"]['s3_client'].delete_object(
                Bucket=_dkss_runtime.app.config['S3_BUCKET_NAME'],
                Key=(
                    f"{storage_folder}/"
                    f"{company_code}/"
                    f"{filename}"
                )
            )
        except _dkss_common.ClientError:
            _dkss_runtime.app.logger.exception(
                "アップロード済みファイルの削除に失敗しました。"
            )
        return

    safe_company_code = _dkss_common.secure_filename(
        str(company_code)
    )
    safe_filename = _dkss_common.secure_filename(
        filename
    )

    if (
        not safe_company_code
        or safe_company_code != company_code
        or not safe_filename
        or safe_filename != filename
    ):
        return

    file_path = _dkss_common.safe_join(
        base_folder,
        safe_company_code,
        safe_filename
    )

    if file_path and _dkss_common.os.path.isfile(file_path):
        try:
            _dkss_common.os.remove(file_path)
        except OSError:
            _dkss_runtime.app.logger.exception(
                "アップロード済みファイルの削除に失敗しました。"
            )



def file_belongs_to_current_company(filename, folder="uploads"):
    company_code = _dkss_common.session.get("company_code")

    if not company_code or not filename:
        return False

    filename = _dkss_common.os.path.basename(filename)

    # プロフィール画像
    current_user = _dkss_models.User.query.filter_by(
        company_code=company_code,
        username=_dkss_common.session.get("username")
    ).first()

    if (
        current_user
        and current_user.profile_image == filename
    ):
        return True

    # マニュアル
    if folder == "manuals":
        return _dkss_models.Manual.query.filter_by(
            company_code=company_code,
            filename=filename
        ).first() is not None

    # お知らせ
    news_records = _dkss_models.News.query.filter_by(
        company_code=company_code
    ).all()

    for news in news_records:
        can_view_news = False

        if news.target_type in ["all", "company"]:
            can_view_news = True

        elif news.target_type == "admins":
            can_view_news = _dkss_common.session.get("role") in [
                "admin",
                "itc"
            ]

        elif news.target_type == "office":
            can_view_news = (
                news.target_value
                == (_dkss_common.session.get("office") or "")
            )

        elif news.target_type == "user":
            can_view_news = (
                news.owner_identity is not None
                and news.owner_identity == _dkss_common.session.get("account_identity")
            )

        if not can_view_news:
            continue

        files = _dkss_serialization.safe_json_str_list(
            news.files_json
        )

        if filename in files:
            return True

    # 通知
    notification_records = _dkss_models.Notification.query.filter(
        _dkss_models.Notification.company_code == company_code,
        notification_owner_clause()
    ).all()

    for notification in notification_records:
        files = _dkss_serialization.safe_json_str_list(
            notification.files_json
        )

        if filename in files:
            return True

    # チェックリスト評価基準添付
    checklist_records = _dkss_models.Checklist.query.filter_by(
        company_code=company_code
    ).all()

    for checklist_record in checklist_records:
        checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)

        if any(
            filename in item.get(
                "criteria_files",
                []
            )
            for item in checklist.get(
                "items",
                []
            )
        ):
            return True

        for version in checklist.get(
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
                return True

    # 安全パトロール
    patrol_records = _dkss_models.PatrolResult.query.filter_by(
        company_code=company_code
    ).all()

    for patrol in patrol_records:
        patrol_dict = _dkss_checklist_common.patrol_result_to_dict(patrol)

        if not _dkss_safety_permissions.can_view_patrol_result(patrol_dict):
            continue

        files = _dkss_serialization.safe_json_str_list(
            patrol.files_json
        )

        if filename in files:
            return True

        countermeasure_files = _dkss_serialization.safe_json_str_list(
            patrol.countermeasure_files_json
        )

        if filename in countermeasure_files:
            return True

    # 安全チェックリスト結果添付
    checklist_result_records = _dkss_models.ChecklistResult.query.filter_by(
        company_code=company_code
    ).all()

    for result in checklist_result_records:
        result_dict = _dkss_checklist_common.checklist_result_to_dict(result)

        if not _dkss_safety_permissions.can_view_checklist_result(result_dict):
            continue

        answers = _dkss_serialization.safe_json_dict_list(
            result.answers_json
        )

        for answer in answers:
            if filename in answer.get("files", []):
                return True

            if filename in answer.get(
                "criteria_files",
                []
            ):
                return True

    # 車両チェックリスト結果添付
    vehicle_result_records = _dkss_models.VehicleChecklistResult.query.filter_by(
        company_code=company_code
    ).all()

    for result in vehicle_result_records:
        answers = _dkss_serialization.safe_json_dict_list(
            result.answers_json
        )

        for answer in answers:
            if filename in answer.get("files", []):
                return True

            if filename in answer.get(
                "criteria_files",
                []
            ):
                return True

        judgment = _dkss_serialization.safe_json_dict(result.operation_judgment_json)
        defects = judgment.get("defects") or []
        if not isinstance(defects, list):
            continue

        for defect in defects:
            if not isinstance(defect, dict):
                continue

            reported_answer = defect.get("reported_answer") or {}
            if not isinstance(reported_answer, dict):
                continue

            reported_files = reported_answer.get("files") or []
            if (
                isinstance(reported_files, list)
                and filename in reported_files
            ):
                return True

    maintenance_records = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
        company_code=company_code
    ).all()

    for record in maintenance_records:
        if filename in _dkss_serialization.safe_json_str_list(record.files_json):
            return True

    return False



def load_upload_bytes(filename):
    company_code = _dkss_common.session.get("company_code")

    if not company_code or not filename:
        return None

    filename = _dkss_common.os.path.basename(
        str(filename)
    )

    if not filename:
        return None

    if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
        buffer = _dkss_common.BytesIO()

        try:
            _dkss_runtime.app.extensions["dkss"]['s3_client'].download_fileobj(
                _dkss_runtime.app.config['S3_BUCKET_NAME'],
                (
                    f"uploads/"
                    f"{company_code}/"
                    f"{filename}"
                ),
                buffer
            )

        except _dkss_common.ClientError:
            print(
                "S3添付ファイル取得エラー"
            )
            return None

        buffer.seek(0)
        return buffer

    file_path = _dkss_common.os.path.join(
        _dkss_runtime.app.config["UPLOAD_FOLDER"],
        company_code,
        filename
    )

    if not _dkss_common.os.path.exists(file_path):
        return None

    with open(file_path, "rb") as file:
        return _dkss_common.BytesIO(file.read())



def uploaded_file(folder, filename):
    if folder not in {"uploads", "manuals"}:
        return "Not found", 404

    company_code = _dkss_common.session.get("company_code")

    if not company_code:
        return "Not found", 404

    filename = _dkss_common.os.path.basename(filename)

    if not file_belongs_to_current_company(
        filename,
        folder
    ):
        return "File not found", 404

    if folder == "uploads" and ("avatar" in _dkss_common.request.args or "thumb" in _dkss_common.request.args):
        from .profile_images import display_avatar, display_thumbnail
        display = (display_avatar(filename) if "avatar" in _dkss_common.request.args
                   else display_thumbnail(filename))
        if display is not None:
            return display

    if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
        object_keys = [
            (
                f"{folder}/"
                f"{company_code}/"
                f"{filename}"
            ),
            (
                f"{folder}/"
                f"{filename}"
            ),
        ]

        for object_key in object_keys:
            try:
                s3_object = _dkss_runtime.app.extensions["dkss"]['s3_client'].get_object(
                    Bucket=_dkss_runtime.app.config['S3_BUCKET_NAME'],
                    Key=object_key
                )

                file_buffer = _dkss_common.BytesIO(
                    s3_object["Body"].read()
                )

                return _dkss_common.send_file(
                    file_buffer,
                    mimetype=s3_object.get(
                        "ContentType",
                        "application/octet-stream"
                    ),
                    download_name=filename,
                    max_age=0
                )

            except _dkss_common.ClientError:
                continue

        return "File not found", 404

    if folder == "manuals":
        local_path = (
            f"/static/manuals/"
            f"{company_code}/"
            f"{filename}"
        )
    else:
        local_path = (
            f"/static/uploads/"
            f"{company_code}/"
            f"{filename}"
        )

    return _dkss_common.redirect(local_path)



def s3_uploads_file(filename):
    company_code = _dkss_common.session.get("company_code")

    if not company_code:
        return "File not found", 404

    # URL側に会社コードを入れさせない
    filename = _dkss_common.os.path.basename(filename)

    if not file_belongs_to_current_company(
        filename,
        "uploads"
    ):
        return "File not found", 404

    if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
        object_keys = [
            (
                f"uploads/"
                f"{company_code}/"
                f"{filename}"
            ),
            (
                f"uploads/"
                f"{filename}"
            ),
        ]

        for object_key in object_keys:
            try:
                _dkss_runtime.app.extensions["dkss"]['s3_client'].head_object(
                    Bucket=_dkss_runtime.app.config['S3_BUCKET_NAME'],
                    Key=object_key
                )

                url = _dkss_runtime.app.extensions["dkss"]['s3_client'].generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": _dkss_runtime.app.config['S3_BUCKET_NAME'],
                        "Key": object_key,
                        "ResponseCacheControl": "no-store"
                    },
                    ExpiresIn=300
                )

                return _dkss_common.redirect(url)

            except _dkss_common.ClientError:
                continue

        return "File not found", 404

    try:
        return _dkss_runtime.app.send_static_file(
            f"uploads/{company_code}/{filename}"
        )
    except _dkss_common.NotFound:
        pass

    try:
        return _dkss_runtime.app.send_static_file(
            f"uploads/{filename}"
        )
    except _dkss_common.NotFound:
        return "File not found", 404



def s3_manual_file(filename):
    company_code = _dkss_common.session.get("company_code")
    if not company_code:
        return "File not found", 404

    filename = _dkss_common.os.path.basename(filename)
    if not file_belongs_to_current_company(filename, "manuals"):
        return "File not found", 404

    app = _dkss_runtime.app
    client = app.extensions["dkss"]["s3_client"]
    bucket = app.config["S3_BUCKET_NAME"]
    keys = [f"manuals/{company_code}/{filename}", f"manuals/{filename}"]
    if client and bucket:
        for key in keys:
            try:
                client.head_object(Bucket=bucket, Key=key)
                url = client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key,
                            "ResponseCacheControl": "no-store"},
                    ExpiresIn=300,
                )
                return _dkss_common.redirect(url)
            except _dkss_common.ClientError as error:
                code = str(error.response.get("Error", {}).get("Code", ""))
                if code not in {"404", "NoSuchKey", "NotFound"}:
                    app.logger.warning("Manual retrieval failed: %s", code)
                    return "File not found", 404
        return "File not found", 404

    for key in keys:
        try:
            return app.send_static_file(key)
        except _dkss_common.NotFound:
            continue
    return "File not found", 404



def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"

    response.headers["Referrer-Policy"] = (
        "strict-origin-when-cross-origin"
    )

    response.headers["X-Frame-Options"] = "DENY"

    response.headers["Cross-Origin-Embedder-Policy"] = (
        "unsafe-none"
    )

    response.headers["Cross-Origin-Opener-Policy"] = (
        "same-origin"
    )

    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )

    s3_csp_source = ""
    if _dkss_runtime.app.config['S3_BUCKET_NAME']:
        s3_csp_source = (
            f"https://{_dkss_runtime.app.config['S3_BUCKET_NAME']}.s3.{_dkss_runtime.app.config['AWS_REGION']}.amazonaws.com "
        )

    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        f"img-src 'self' data: blob: {s3_csp_source}; "
        "media-src 'self' blob:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "frame-src 'none'; "
        "worker-src 'self' blob:; "
        "manifest-src 'self'"
    )

    protected_static_file = (
        _dkss_common.request.path.startswith("/static/uploads/")
        or _dkss_common.request.path.startswith("/static/manuals/")
    )

    if _dkss_common.request.path == "/static/manifest.webmanifest":
        response.headers["Cache-Control"] = (
            "no-cache, must-revalidate"
        )

    if (
        protected_static_file
        or not _dkss_common.request.path.startswith("/static/")
    ):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"

    if _dkss_common.os.environ.get("RENDER") == "true":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    return response
