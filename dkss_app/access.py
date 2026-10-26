"""Access responsibilities; routes are registered by the application factory."""
from . import common as _dkss_common, models as _dkss_models, storage as _dkss_storage


def require_login():
    # 保護対象のstaticファイル
    if (
        _dkss_common.request.path.startswith("/static/uploads/")
        or _dkss_common.request.path.startswith("/static/manuals/")
    ):
        if not _dkss_common.session.get("username"):
            return _dkss_common.redirect("/login")

        current_user = _dkss_models.User.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            username=_dkss_common.session.get("username")
        ).first()

        if not current_user or current_user.login_locked:
            _dkss_common.session.clear()
            return _dkss_common.redirect("/login")

        if (
            _dkss_common.session.get("password_changed_at")
            != current_user.password_changed_at
        ):
            _dkss_common.session.clear()
            return _dkss_common.redirect("/login")

        _dkss_common.session["role"] = current_user.role
        _dkss_common.session["name"] = (
            f"{current_user.last_name or ''}"
            f"{current_user.first_name or ''}"
        )
        _dkss_common.session["office"] = current_user.office

        if current_user.role != "itc":
            current_company = _dkss_models.Company.query.filter_by(
                company_code=current_user.company_code
            ).first()

            if not current_company or not current_company.active:
                _dkss_common.session.clear()
                return _dkss_common.redirect("/login")

        parts = _dkss_common.request.path.strip("/").split("/")

        if len(parts) < 3:
            return "File not found", 404

        folder = parts[1]
        filename = _dkss_common.os.path.basename(parts[-1])

        if folder not in {"uploads", "manuals"}:
            return "File not found", 404

        if not _dkss_storage.file_belongs_to_current_company(
            filename,
            folder
        ):
            return "File not found", 404
    if (
        _dkss_common.request.endpoint in {
            "login",
            "login_csrf_token",
            "mfa",
            "register",
            "static",
            "service_worker"
        }
        or _dkss_common.request.endpoint is None
    ):
        return None

    if not _dkss_common.session.get("username"):
        if (
            _dkss_common.request.path.startswith("/api/")
            or _dkss_common.request.path == "/notifications/email-test"
        ):
            return {
                "ok": False,
                "message": "ログインが必要です。"
            }, 401

        return _dkss_common.redirect("/login")

    current_user = _dkss_models.User.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        username=_dkss_common.session.get("username")
    ).first()

    if not current_user or current_user.login_locked:
        _dkss_common.session.clear()

        if (
            _dkss_common.request.path.startswith("/api/")
            or _dkss_common.request.path == "/notifications/email-test"
        ):
            return {
                "ok": False,
                "message": "ログインが必要です。"
            }, 401

        return _dkss_common.redirect("/login")

    if (
        _dkss_common.session.get("password_changed_at")
        != current_user.password_changed_at
    ):
        _dkss_common.session.clear()

        if (
            _dkss_common.request.path.startswith("/api/")
            or _dkss_common.request.path == "/notifications/email-test"
        ):
            return {
                "ok": False,
                "message": "ログインが必要です。"
            }, 401

        return _dkss_common.redirect("/login")

    _dkss_common.session["role"] = current_user.role
    _dkss_common.session["name"] = (
        f"{current_user.last_name or ''}"
        f"{current_user.first_name or ''}"
    )
    _dkss_common.session["office"] = current_user.office
    _dkss_common.session["profile_image"] = current_user.profile_image

    if current_user.role != "itc":
        current_company = _dkss_models.Company.query.filter_by(
            company_code=current_user.company_code
        ).first()

        if not current_company or not current_company.active:
            _dkss_common.session.clear()

            if (
                _dkss_common.request.path.startswith("/api/")
                or _dkss_common.request.path == "/notifications/email-test"
            ):
                return {
                    "ok": False,
                    "message": "この会社では現在システムを利用できません。"
                }, 403

            return _dkss_common.redirect("/login")

    if (
        _dkss_common.session.get("password_expired")
        and _dkss_common.request.endpoint not in {
            "settings",
            "logout"
        }
    ):
        if (
            _dkss_common.request.path.startswith("/api/")
            or _dkss_common.request.path == "/notifications/email-test"
        ):
            return {
                "ok": False,
                "message": "パスワードの変更が必要です。"
            }, 403

        return _dkss_common.redirect("/settings")

    # マスタ管理は管理者のみ
    if _dkss_common.request.path == "/master" or _dkss_common.request.path.startswith("/master/"):
        if _dkss_common.session.get("role") not in ["admin", "itc"]:
            return _dkss_common.redirect("/")

    return None



def require_itc():
    return _dkss_common.session.get("role") == "itc"



def require_master_admin():
    return _dkss_common.session.get("role") in ["admin", "itc"]
