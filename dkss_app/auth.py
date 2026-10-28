"""Auth responsibilities; routes are registered by the application factory."""
from . import audit as _dkss_audit, common as _dkss_common, master_readers as _dkss_master_readers, models as _dkss_models, notifications_delivery as _dkss_notifications_delivery, runtime as _dkss_runtime, storage as _dkss_storage


def parse_password_history(value):
    try:
        parsed = _dkss_common.json.loads(value or "[]")
    except (TypeError, ValueError):
        return None

    if not isinstance(parsed, list):
        return None

    if not all(
        isinstance(item, str)
        for item in parsed
    ):
        return None

    return parsed



def send_mfa_code_email(user, code):
    if not user or not user.email_address:
        return False

    return _dkss_notifications_delivery.send_email_notification(
        user=user,
        title="ログイン認証コード",
        message=(
            "ログイン認証コードは以下です。\n\n"
            f"{code}\n\n"
            "このコードの有効期限は10分です。"
        ),
        require_opt_in=False,
    )



def is_valid_email_address(value):
    value = str(value or "").strip()

    if (
        not value
        or len(value) > 255
        or "\r" in value
        or "\n" in value
    ):
        return False

    _, parsed_address = _dkss_common.parseaddr(value)

    if parsed_address != value:
        return False

    if "@" not in parsed_address:
        return False

    local_part, domain = parsed_address.rsplit("@", 1)

    return bool(
        local_part
        and domain
        and "." in domain
    )



def send_email_change_code_email(
    email_address,
    code
):
    if not is_valid_email_address(
        email_address
    ):
        return False

    smtp_host = _dkss_common.os.environ.get("SMTP_HOST", "")
    try:
        smtp_port = int(
            _dkss_common.os.environ.get("SMTP_PORT", "587")
        )
    except (TypeError, ValueError):
        print(
            "メールアドレス変更確認メール未送信：SMTP_PORTが不正です。"
        )
        return False
    smtp_username = _dkss_common.os.environ.get(
        "SMTP_USERNAME",
        ""
    )
    smtp_password = _dkss_common.os.environ.get(
        "SMTP_PASSWORD",
        ""
    )
    smtp_from = _dkss_common.os.environ.get(
        "SMTP_FROM",
        smtp_username
    )

    if not smtp_host:
        return False

    if not is_valid_email_address(smtp_from):
        return False

    email = _dkss_common.EmailMessage()

    email["Subject"] = "メールアドレス変更確認コード"
    email["From"] = smtp_from
    email["To"] = email_address

    email.set_content(
        "メールアドレス変更確認コードは以下です。\n\n"
        f"{code}\n\n"
        "このコードの有効期限は10分です。"
    )

    try:
        with _dkss_common.smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=20
        ) as server:
            server.starttls()

            if smtp_username:
                server.login(
                    smtp_username,
                    smtp_password
                )

            server.send_message(email)

        return True

    except Exception:
        _dkss_runtime.app.logger.exception(
            "メールアドレス変更確認メール送信中に予期しないエラーが発生しました。"
        )
        return False



def create_email_change_code(
    user,
    new_email_address
):
    code = f"{_dkss_common.secrets.randbelow(1000000):06d}"

    user.pending_email_address = new_email_address

    user.email_change_code_hash = (
        _dkss_common.generate_password_hash(code)
    )

    user.email_change_code_expires_at = (
        _dkss_common.datetime.now() + _dkss_common.timedelta(minutes=10)
    ).strftime("%Y-%m-%d %H:%M:%S")

    return code



def create_mfa_code(user):
    now = _dkss_common.datetime.now()

    if user.mfa_code_sent_at:
        try:
            last_sent_at = _dkss_common.datetime.strptime(
                user.mfa_code_sent_at,
                "%Y-%m-%d %H:%M:%S"
            )

            if (
                now - last_sent_at
                < _dkss_common.timedelta(seconds=60)
            ):
                return None

        except ValueError:
            pass

    code = f"{_dkss_common.secrets.randbelow(1000000):06d}"

    user.mfa_code_hash = _dkss_common.generate_password_hash(
        code
    )

    user.mfa_code_expires_at = (
        now + _dkss_common.timedelta(minutes=10)
    ).strftime("%Y-%m-%d %H:%M:%S")

    user.mfa_code_sent_at = now.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    _dkss_common.db.session.commit()

    return code



def mfa_challenge_key(user):
    """Opaque identity for one issued code; never store the code in audit logs."""
    if not user.mfa_code_hash:
        return ""
    return _dkss_common.hashlib.sha256(
        user.mfa_code_hash.encode("utf-8")
    ).hexdigest()


def mfa_failed_attempt_count(user, challenge_key):
    """Persistent failures for one challenge, independent of client cookies.

    The caller holds the user row lock until the failure and invalidation commit.
    Only a fingerprint of the salted hash is stored with each audit event.
    """
    return _dkss_models.AuditLog.query.filter_by(
        company_code=user.company_code,
        username=user.username,
        action="mfa_failed",
        target_type="user",
        target_id=user.username,
    ).filter(
        _dkss_models.AuditLog.detail.startswith(
            f"MFA challenge {challenge_key}: "
        )
    ).count()


def login_csrf_token():
    from flask_wtf.csrf import generate_csrf

    response = _dkss_common.jsonify({
        "csrf_token": generate_csrf()
    })
    response.headers["Cache-Control"] = "no-store"
    return response



def login():
    error = None

    if _dkss_common.request.method == "GET" and _dkss_common.session.get("username"):
        if _dkss_common.session.get("role") == "itc":
            return _dkss_common.redirect("/itc")

        return _dkss_common.redirect("/")

    if _dkss_common.request.method == "POST":
        company_code = _dkss_common.request.form.get(
            "company_code",
            ""
        ).strip()
        username = _dkss_common.request.form.get(
            "username",
            ""
        ).strip()
        password = _dkss_common.request.form.get(
            "password",
            ""
        )

        if (
            len(company_code) > 50
            or len(username) > 50
            or len(password) > 255
        ):
            error = (
                "会社コード、ユーザーID、"
                "またはパスワードが違います。"
            )
            return _dkss_common.render_template(
                "login.html",
                error=error
            )

        matching_company_codes = (
            _dkss_common.db.session.query(_dkss_models.User.company_code)
            .filter(
                _dkss_common.db.func.lower(_dkss_models.User.company_code)
                == company_code.lower()
            )
            .distinct()
            .limit(2)
            .all()
        )

        if len(matching_company_codes) > 1:
            return _dkss_common.render_template(
                "login.html",
                error=(
                    "会社コードを特定できません。"
                    "管理者へお問い合わせください。"
                )
            )

        if matching_company_codes:
            company_code = matching_company_codes[0][0]

        user = _dkss_models.User.query.filter_by(
            company_code=company_code,
            username=username
        ).first()

        if user and user.login_locked:
            error = (
                "アカウントがロックされています。"
                "管理者へお問い合わせください。"
            )

        elif user and _dkss_common.check_password_hash(
            user.password,
            password
        ):

            now = _dkss_common.datetime.now()

            if user.last_login_at:
                try:
                    last_login_at = _dkss_common.datetime.strptime(
                        user.last_login_at,
                        "%Y-%m-%d %H:%M:%S"
                    )

                    if (
                        now - last_login_at
                        >= _dkss_common.timedelta(days=90)
                    ):
                        user.login_locked = True

                        _dkss_audit.add_audit_log(
                            action="account_locked",
                            target_type="user",
                            target_id=user.username,
                            detail="90日以上未使用によるアカウントロック",
                            company_code=user.company_code,
                            username=user.username,
                        )

                        _dkss_common.db.session.commit()

                        return _dkss_common.render_template(
                            "login.html",
                            error=(
                                "90日以上ログインがなかったため、"
                                "アカウントがロックされました。"
                                "管理者へお問い合わせください。"
                            )
                        )

                except ValueError:
                    pass

            user.failed_login_count = 0

            password_expired = False

            if user.password_changed_at:
                try:
                    password_changed_at = _dkss_common.datetime.strptime(
                        user.password_changed_at,
                        "%Y-%m-%d %H:%M:%S"
                    )

                    password_expired = (
                        _dkss_common.datetime.now() - password_changed_at
                        >= _dkss_common.timedelta(days=90)
                    )

                except ValueError:
                    password_expired = True
            else:
                # 既存ユーザーは導入時点から90日を数える
                user.password_changed_at = _dkss_common.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            _dkss_common.db.session.commit()

            company = _dkss_master_readers.get_company(user.company_code)
            if (
                user.role != "itc"
                and (
                    not company
                    or not company.active
                )
            ):
                return _dkss_common.render_template(
                    "login.html",
                    error=(
                        "この会社は現在利用停止中です。"
                        "ITCへお問い合わせください。"
                    )
                )

            if not _dkss_runtime.app.config['MFA_ENABLED']:
                user.last_login_at = _dkss_common.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                _dkss_audit.add_audit_log(
                    action="login_success",
                    target_type="user",
                    target_id=user.username,
                    detail="パスワード認証成功（MFA一時無効）",
                    company_code=user.company_code,
                    username=user.username,
                )

                _dkss_audit.update_company_usage_summary(
                    user.company_code,
                    increment_login=True
                )

                _dkss_common.db.session.commit()

                _dkss_common.session.clear()
                _dkss_common.session.permanent = True
                _dkss_common.session["company_code"] = user.company_code
                _dkss_common.session["username"] = user.username
                _dkss_common.session["account_identity"] = user.account_identity
                _dkss_common.session["role"] = user.role
                _dkss_common.session["name"] = (
                    f"{user.last_name or ''}"
                    f"{user.first_name or ''}"
                )
                _dkss_common.session["office"] = user.office

                _dkss_common.session["password_changed_at"] = (
                    user.password_changed_at
                )
                _dkss_common.session["password_expired"] = password_expired

                if password_expired:
                    return _dkss_common.redirect("/settings")

                if user.role == "itc":
                    return _dkss_common.redirect("/itc")

                return _dkss_common.redirect("/")

            code = create_mfa_code(user)
            if code is None:
                return _dkss_common.render_template(
                    "login.html",
                    error=(
                        "認証コードは60秒に1回まで送信できます。"
                        "少し待ってからもう一度お試しください。"
                    )
                )
            if not send_mfa_code_email(user, code):
                user.mfa_code_hash = None
                user.mfa_code_expires_at = None
                user.mfa_code_sent_at = None
                _dkss_common.db.session.commit()

                return _dkss_common.render_template(
                    "login.html",
                    error=(
                        "認証コードを送信できませんでした。"
                        "登録メールアドレスまたは"
                        "メール設定を確認してください。"
                    )
                )

            _dkss_common.session.clear()
            _dkss_common.session.permanent = True
            _dkss_common.session["mfa_pending_company_code"] = (
                user.company_code
            )
            _dkss_common.session["mfa_pending_username"] = (
                user.username
            )
            _dkss_common.session["mfa_password_expired"] = (
                password_expired
            )
            _dkss_common.session["mfa_password_changed_at"] = (
                user.password_changed_at
            )
            _dkss_common.session["mfa_pending_challenge"] = mfa_challenge_key(user)
            _dkss_common.session["mfa_account_identity"] = user.account_identity
            _dkss_common.session["mfa_attempts"] = 0

            return _dkss_common.redirect("/mfa")

        else:
            if user:
                user.failed_login_count = (
                    user.failed_login_count or 0
                ) + 1

                if user.failed_login_count >= 10:
                    user.login_locked = True

                    _dkss_audit.add_audit_log(
                        action="account_locked",
                        target_type="user",
                        target_id=user.username,
                        detail="パスワード認証10回失敗によるアカウントロック",
                        company_code=user.company_code,
                        username=user.username,
                    )

            _dkss_audit.add_audit_log(
                action="login_failed",
                target_type="user",
                target_id=username,
                detail="パスワード認証失敗",
                company_code=company_code,
                username=username,
            )

            _dkss_common.db.session.commit()

            error = (
                "会社コード、ユーザーID、"
                "またはパスワードが違います。"
            )

    return _dkss_common.render_template("login.html", error=error)



def mfa():
    company_code = _dkss_common.session.get(
        "mfa_pending_company_code"
    )
    username = _dkss_common.session.get(
        "mfa_pending_username"
    )

    if not company_code or not username:
        return _dkss_common.redirect("/login")

    user_query = _dkss_models.User.query.filter_by(
        company_code=company_code,
        username=username
    )
    if _dkss_common.request.method == "POST":
        # Serialize code consumption and failure accounting on PostgreSQL.
        user_query = user_query.with_for_update().populate_existing()
    user = user_query.first()

    if (not user or user.login_locked or not user.account_identity
            or _dkss_common.session.get("mfa_account_identity") != user.account_identity):
        _dkss_common.session.clear()
        return _dkss_common.redirect("/login")

    if user.role != "itc":
        company = _dkss_models.Company.query.filter_by(
            company_code=user.company_code
        ).first()

        if not company or not company.active:
            _dkss_common.session.clear()
            return _dkss_common.redirect("/login")

    if (
        _dkss_common.session.get("mfa_password_changed_at")
        != user.password_changed_at
    ):
        _dkss_common.session.clear()
        return _dkss_common.redirect("/login")

    challenge_key = mfa_challenge_key(user)
    if (
        not challenge_key
        or _dkss_common.session.get("mfa_pending_challenge") != challenge_key
    ):
        _dkss_common.session.clear()
        return _dkss_common.redirect("/login")

    error = None

    if _dkss_common.request.method == "POST":
        code = _dkss_common.request.form.get(
            "code",
            ""
        ).strip()

        if (
            not user.mfa_code_hash
            or not user.mfa_code_expires_at
        ):
            error = "認証コードが無効です。"

        else:
            try:
                expires_at = _dkss_common.datetime.strptime(
                    user.mfa_code_expires_at,
                    "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                expires_at = _dkss_common.datetime.min

            if _dkss_common.datetime.now() > expires_at:
                user.mfa_code_hash = None
                user.mfa_code_expires_at = None
                _dkss_common.db.session.commit()

                _dkss_common.session.clear()

                return _dkss_common.render_template(
                    "login.html",
                    error=(
                        "認証コードの有効期限が切れています。"
                        "もう一度ログインしてください。"
                    )
                )

            elif (
                len(code) != 6
                or not code.isdigit()
                or not _dkss_common.check_password_hash(
                    user.mfa_code_hash,
                    code
                )
            ):
                attempts = mfa_failed_attempt_count(user, challenge_key) + 1
                _dkss_common.session["mfa_attempts"] = attempts

                _dkss_audit.add_audit_log(
                    action="mfa_failed",
                    target_type="user",
                    target_id=user.username,
                    detail=f"MFA challenge {challenge_key}: MFA認証失敗 {attempts}回目",
                    company_code=user.company_code,
                    username=user.username,
                )

                if attempts >= 5:
                    user.mfa_code_hash = None
                    user.mfa_code_expires_at = None

                    _dkss_audit.add_audit_log(
                        action="mfa_code_invalidated",
                        target_type="user",
                        target_id=user.username,
                        detail="MFA認証5回失敗による認証コード無効化",
                        company_code=user.company_code,
                        username=user.username,
                    )

                    _dkss_common.db.session.commit()

                    _dkss_common.session.clear()

                    return _dkss_common.render_template(
                        "login.html",
                        error=(
                            "認証コードを5回間違えたため、"
                            "認証コードを無効化しました。"
                            "もう一度ログインしてください。"
                        )
                    )

                _dkss_common.db.session.commit()

                error = (
                    "認証コードが違います。"
                    f"あと{5 - attempts}回入力できます。"
                )

            else:
                password_expired = _dkss_common.session.get(
                    "mfa_password_expired",
                    False
                )

                user.mfa_code_hash = None
                user.mfa_code_expires_at = None
                user.last_login_at = _dkss_common.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                _dkss_audit.add_audit_log(
                    action="login_success",
                    target_type="user",
                    target_id=user.username,
                    detail="MFA認証成功",
                    company_code=user.company_code,
                    username=user.username,
                )

                _dkss_audit.update_company_usage_summary(
                    user.company_code,
                    increment_login=True
                )

                _dkss_common.db.session.commit()

                _dkss_common.session.clear()
                _dkss_common.session.permanent = True
                _dkss_common.session["company_code"] = user.company_code
                _dkss_common.session["username"] = user.username
                _dkss_common.session["account_identity"] = user.account_identity
                _dkss_common.session["role"] = user.role
                _dkss_common.session["name"] = (
                    f"{user.last_name or ''}"
                    f"{user.first_name or ''}"
                )
                _dkss_common.session["office"] = user.office
                _dkss_common.session["password_changed_at"] = (
                    user.password_changed_at
                )
                _dkss_common.session["password_expired"] = (
                    password_expired
                )

                if password_expired:
                    return _dkss_common.redirect("/settings")

                if user.role == "itc":
                    return _dkss_common.redirect("/itc")

                return _dkss_common.redirect("/")

    return _dkss_common.render_template(
        "mfa.html",
        error=error
    )



def register():
    error = None

    company_code_from_url = _dkss_common.request.args.get(
        "company_code",
        ""
    ).strip()

    if _dkss_common.request.method == "POST":
        company_code = company_code_from_url

        last_name = _dkss_common.request.form.get(
            "last_name",
            ""
        ).strip()

        first_name = _dkss_common.request.form.get(
            "first_name",
            ""
        ).strip()

        name = last_name + first_name

        employee_id = _dkss_common.request.form.get(
            "employee_id",
            ""
        ).strip()

        email_address = _dkss_common.request.form.get(
            "email_address",
            ""
        ).strip().lower()

        password = _dkss_common.request.form.get(
            "password",
            ""
        )

        office = _dkss_common.request.form.get(
            "office",
            ""
        ).strip()

        password_type_count = sum([
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ])

        company = _dkss_models.Company.query.filter_by(
            company_code=company_code
        ).first()

        if (
            not company_code
            or not last_name
            or not employee_id
            or not password
        ):
            error = "必須項目を入力してください。"

        elif not company:
            error = "会社コードが存在しません。"

        elif not company.active:
            error = "この会社は現在利用停止中です。"

        elif len(employee_id) > 50:
            error = "ログインIDは50文字以内で入力してください。"

        elif len(last_name) > 100:
            error = "姓は100文字以内で入力してください。"

        elif len(first_name) > 100:
            error = "名は100文字以内で入力してください。"

        elif email_address and not is_valid_email_address(
            email_address
        ):
            error = "メールアドレスの形式が不正です。"

        elif len(password) < 8:
            error = "パスワードは8文字以上にしてください。"

        elif len(password) > 128:
            error = "パスワードは128文字以内にしてください。"

        elif password_type_count < 3:
            error = (
                "パスワードは英大文字・英小文字・数字・記号の"
                "うち3種類以上を使用してください。"
            )

        elif _dkss_models.User.query.filter_by(
            company_code=company_code,
            username=employee_id
        ).first():
            error = "このログインIDはすでに使用されています。"

        elif office and not _dkss_models.Office.query.filter_by(
            company_code=company_code,
            name=office
        ).first():
            error = "営業所が不正です。"

        else:
            user = _dkss_models.User(
                company_code=company_code,
                username=employee_id,
                password=_dkss_common.generate_password_hash(password),
                password_changed_at=_dkss_common.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                role="user",
                last_name=last_name,
                first_name=first_name or None,
                office=office,
                email_address=email_address or None,
                email_notify_enabled=bool(email_address)
            )

            driver = _dkss_models.Driver.query.filter_by(
                company_code=company_code,
                employee_id=employee_id
            ).first()

            _dkss_common.db.session.add(user)

            if not driver:
                driver = _dkss_models.Driver(
                    company_code=company_code,
                    employee_id=employee_id,
                    name=(last_name or "") + (first_name or ""),
                    role="user",
                    office=office,
                    safe_start_date=_dkss_common.datetime.now().strftime(
                        "%Y-%m-%d"
                    ),
                    vehicles_json="[]",
                    licenses_json="[]"
                )
                _dkss_common.db.session.add(driver)

            _dkss_audit.add_audit_log(
                action="user_registered",
                target_type="user",
                target_id=employee_id,
                detail="招待URLからユーザー登録",
                company_code=company_code,
                username=employee_id,
            )

            try:
                _dkss_common.db.session.commit()
            except _dkss_common.IntegrityError:
                _dkss_common.db.session.rollback()
                error = (
                    "このログインIDはすでに使用されています。"
                    "画面を再読み込みして確認してください。"
                )
            else:
                return _dkss_common.redirect(
                    _dkss_common.url_for(
                        "login",
                        company_code=company_code
                    )
                )

    company = None

    if company_code_from_url:
        company = _dkss_models.Company.query.filter_by(
            company_code=company_code_from_url,
            active=True
        ).first()

    offices = []

    if company:
        offices = _dkss_master_readers.ordered_master_query(_dkss_models.Office, company.company_code).all()

    return _dkss_common.render_template(
        "register.html",
        error=error,
        company_code=company_code_from_url,
        offices=offices
    )



def logout():
    _dkss_audit.add_audit_log(
        action="logout",
        target_type="user",
        target_id=_dkss_common.session.get("username", ""),
        detail="ユーザーがログアウト",
    )

    _dkss_common.db.session.commit()

    _dkss_common.session.clear()
    return _dkss_common.redirect("/login")



def settings():
    current_user = _dkss_models.User.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        username=_dkss_common.session.get("username")
    ).first()

    if not current_user:
        _dkss_common.session.clear()
        return _dkss_common.redirect("/login")

    error = None
    notification_success = None
    password_success = None

    if _dkss_common.request.method == "POST":
        action = _dkss_common.request.form.get("action", "password")

        if action == "profile_image":
            profile_image = _dkss_common.request.files.get(
                "profile_image"
            )

            if profile_image and profile_image.filename:
                old_profile_image = _dkss_common.os.path.basename(
                    str(
                        current_user.profile_image
                        or ""
                    )
                )

                saved_filename = _dkss_storage.save_uploaded_file(
                    profile_image
                )

                if saved_filename:
                    current_user.profile_image = (
                        saved_filename
                    )

                    _dkss_common.db.session.commit()

                    _dkss_common.session["profile_image"] = (
                        saved_filename
                    )

                    if (
                        old_profile_image
                        and old_profile_image != saved_filename
                    ):
                        if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
                            try:
                                _dkss_runtime.app.extensions["dkss"]['s3_client'].delete_object(
                                    Bucket=_dkss_runtime.app.config['S3_BUCKET_NAME'],
                                    Key=(
                                        f"uploads/"
                                        f"{current_user.company_code}/"
                                        f"{old_profile_image}"
                                    )
                                )
                            except _dkss_common.ClientError:
                                _dkss_runtime.app.logger.warning(
                                    "旧プロフィール画像のS3削除に失敗しました。",
                                    exc_info=True
                                )
                        else:
                            safe_filename = _dkss_common.secure_filename(
                                old_profile_image
                            )

                            if safe_filename:
                                file_path = _dkss_common.os.path.join(
                                    _dkss_runtime.app.config["UPLOAD_FOLDER"],
                                    current_user.company_code,
                                    safe_filename
                                )

                                if _dkss_common.os.path.exists(file_path):
                                    _dkss_common.os.remove(file_path)

            return _dkss_common.redirect("/settings")

        if action == "notifications":
            new_email_address = (
                _dkss_common.request.form.get("email_address", "").strip()
            )

            if (
                new_email_address
                and not is_valid_email_address(
                    new_email_address
                )
            ):
                error = "メールアドレスの形式が不正です。"

            notification_current_password = (
                _dkss_common.request.form.get(
                    "notification_current_password",
                    ""
                )
            )

            old_email_address = (
                current_user.email_address or ""
            )

            if error:
                pass

            elif (
                new_email_address != old_email_address
                and not _dkss_common.check_password_hash(
                    current_user.password,
                    notification_current_password
                )
            ):
                error = (
                    "メールアドレスを変更するには、"
                    "現在のパスワードを入力してください。"
                )

            else:
                timezone_name = (
                    _dkss_common.request.form.get("timezone")
                    or current_user.timezone
                    or "Asia/Tokyo"
                ).strip()

                try:
                    _dkss_common.ZoneInfo(timezone_name)
                except Exception:
                    error = "タイムゾーンが不正です。"
                else:
                    email_notify_enabled = (
                        _dkss_common.request.form.get("email_notify_enabled") == "1"
                    )

                    current_user.timezone = timezone_name
                    current_user.email_notify_enabled = email_notify_enabled

                    if new_email_address != old_email_address:
                        code = create_email_change_code(
                            current_user,
                            new_email_address
                        )

                        if not send_email_change_code_email(
                            new_email_address,
                            code
                        ):
                            current_user.pending_email_address = None
                            current_user.email_change_code_hash = None
                            current_user.email_change_code_expires_at = None
                            _dkss_common.db.session.rollback()

                            error = (
                                "変更先メールアドレスへ"
                                "確認コードを送信できませんでした。"
                            )

                        else:
                            _dkss_common.db.session.commit()
                            _dkss_common.session["email_change_attempts"] = 0

                            return _dkss_common.redirect("/settings/email/verify")

                    else:
                        _dkss_common.db.session.commit()
                        notification_success = "通知設定を保存しました。"

        else:
            current_password = _dkss_common.request.form.get(
                "current_password",
                ""
            )
            new_password = _dkss_common.request.form.get(
                "new_password",
                ""
            )
            new_password_confirm = _dkss_common.request.form.get(
                "new_password_confirm",
                ""
            )

            password_type_count = sum([
                any(c.islower() for c in new_password or ""),
                any(c.isupper() for c in new_password or ""),
                any(c.isdigit() for c in new_password or ""),
                any(
                    not c.isalnum()
                    for c in new_password or ""
                ),
            ])

            password_history = parse_password_history(
                current_user.password_history_json
            )

            if password_history is None:
                error = (
                    "パスワード履歴データが不正です。"
                    "管理者へお問い合わせください。"
                )
                return _dkss_common.render_template(
                    "settings.html",
                    user=current_user,
                    error=error,
                    notification_success=notification_success,
                    password_success=password_success,
                )

            reused_password = (
                _dkss_common.check_password_hash(
                    current_user.password,
                    new_password or ""
                )
                or any(
                    _dkss_common.check_password_hash(
                        old_password_hash,
                        new_password or ""
                    )
                    for old_password_hash in password_history[-5:]
                )
            )

            if not _dkss_common.check_password_hash(
                current_user.password,
                current_password
            ):
                error = "現在のパスワードが違います。"

            elif not new_password:
                error = "新しいパスワードを入力してください。"

            elif len(new_password) < 8:
                error = "パスワードは8文字以上にしてください。"

            elif len(new_password) > 128:
                error = "パスワードは128文字以内にしてください。"

            elif password_type_count < 3:
                error = (
                    "パスワードは英大文字・英小文字・数字・記号の"
                    "うち3種類以上を使用してください。"
                )

            elif new_password != new_password_confirm:
                error = "新しいパスワードが一致しません。"

            elif reused_password:
                error = (
                    "現在または過去5回以内に使用した"
                    "パスワードは使用できません。"
                )

            else:
                password_history.append(
                    current_user.password
                )

                current_user.password_history_json = _dkss_common.json.dumps(
                    password_history[-5:]
                )

                current_user.password = _dkss_common.generate_password_hash(
                    new_password
                )

                current_user.password_changed_at = (
                    _dkss_common.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                _dkss_common.session["password_changed_at"] = (
                    current_user.password_changed_at
                )
                _dkss_common.session["password_expired"] = False
                _dkss_audit.add_audit_log(
                    action="password_changed",
                    target_type="user",
                    target_id=current_user.username,
                    detail="本人によるパスワード変更",
                    company_code=current_user.company_code,
                    username=current_user.username,
                )

                _dkss_common.db.session.commit()
                password_success = "パスワードを変更しました。"

    return _dkss_common.render_template(
        "settings.html",
        user=current_user,
        error=error,
        notification_success=notification_success,
        password_success=password_success,
    )



def verify_email_change():
    current_user = _dkss_models.User.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        username=_dkss_common.session.get("username")
    ).first()

    if not current_user:
        _dkss_common.session.clear()
        return _dkss_common.redirect("/login")

    if (
        not current_user.pending_email_address
        or not current_user.email_change_code_hash
        or not current_user.email_change_code_expires_at
    ):
        return _dkss_common.redirect("/settings")

    error = None

    if _dkss_common.request.method == "POST":
        code = _dkss_common.request.form.get(
            "code",
            ""
        ).strip()

        try:
            expires_at = _dkss_common.datetime.strptime(
                current_user.email_change_code_expires_at,
                "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            expires_at = _dkss_common.datetime.min

        if _dkss_common.datetime.now() > expires_at:
            current_user.pending_email_address = None
            current_user.email_change_code_hash = None
            current_user.email_change_code_expires_at = None

            _dkss_common.db.session.commit()

            _dkss_common.session.pop(
                "email_change_attempts",
                None
            )

            error = (
                "確認コードの有効期限が切れています。"
                "もう一度メールアドレス変更を行ってください。"
            )

        elif (
            len(code) != 6
            or not code.isdigit()
            or not _dkss_common.check_password_hash(
                current_user.email_change_code_hash,
                code
            )
        ):
            attempts = (
                _dkss_common.session.get("email_change_attempts", 0) + 1
            )

            _dkss_common.session["email_change_attempts"] = attempts

            if attempts >= 5:
                current_user.pending_email_address = None
                current_user.email_change_code_hash = None
                current_user.email_change_code_expires_at = None

                _dkss_audit.add_audit_log(
                    action="email_change_code_invalidated",
                    target_type="user",
                    target_id=current_user.username,
                    detail="メール変更確認コード5回失敗による無効化",
                    company_code=current_user.company_code,
                    username=current_user.username,
                )

                _dkss_common.db.session.commit()

                _dkss_common.session.pop(
                    "email_change_attempts",
                    None
                )

                return _dkss_common.redirect("/settings")

            error = (
                "確認コードが違います。"
                f"あと{5 - attempts}回入力できます。"
            )

        else:
            current_user.email_address = (
                current_user.pending_email_address
            )

            current_user.pending_email_address = None
            current_user.email_change_code_hash = None
            current_user.email_change_code_expires_at = None

            _dkss_common.session.pop(
                "email_change_attempts",
                None
            )

            _dkss_audit.add_audit_log(
                action="email_changed",
                target_type="user",
                target_id=current_user.username,
                detail="メール確認完了によるメールアドレス変更",
                company_code=current_user.company_code,
                username=current_user.username,
            )

            _dkss_common.db.session.commit()

            return _dkss_common.redirect("/settings")

    return _dkss_common.render_template(
        "email_change_verify.html",
        error=error
    )
