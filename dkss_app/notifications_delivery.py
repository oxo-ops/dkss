"""Notifications Delivery responsibilities; routes are registered by the application factory."""
from .account_identity import current_identity
from . import audit as _dkss_audit, auth as _dkss_auth, common as _dkss_common, models as _dkss_models, runtime as _dkss_runtime


def service_worker():
    response = _dkss_runtime.app.send_static_file(
        "js/service-worker.js"
    )
    response.headers[
        "Service-Worker-Allowed"
    ] = "/"
    response.headers[
        "Cache-Control"
    ] = "no-cache"
    return response



def push_vapid_public_key():
    if not _dkss_runtime.app.config['VAPID_PUBLIC_KEY']:
        return {
            "publicKey": "",
            "error": "VAPID public key is not configured."
        }, 503

    return {
        "publicKey": _dkss_runtime.app.config['VAPID_PUBLIC_KEY']
    }



def push_subscribe():
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return {"error": "Unauthorized"}, 401

    data = _dkss_common.request.get_json(silent=True) or {}

    endpoint = str(
        data.get("endpoint") or ""
    ).strip()

    keys = data.get("keys") or {}

    p256dh = str(
        keys.get("p256dh") or ""
    ).strip()

    auth = str(
        keys.get("auth") or ""
    ).strip()

    if not endpoint or not p256dh or not auth:
        return {
            "error": "Invalid push subscription."
        }, 400

    if (
        len(endpoint) > 4000
        or len(p256dh) > 1000
        or len(auth) > 1000
    ):
        return {
            "error": "Push subscription is too large."
        }, 400

    subscription = _dkss_models.PushSubscription.query.filter_by(
        endpoint=endpoint
    ).first()

    if subscription and subscription.owner_identity not in (None, current_identity()):
        return {"error": "Subscription belongs to another account generation."}, 409

    if subscription:
        subscription.company_code = company_code
        subscription.username = username
        subscription.owner_identity = current_identity()
        subscription.p256dh = p256dh
        subscription.auth = auth

    else:
        subscription = _dkss_models.PushSubscription(
            company_code=company_code,
            username=username,
            owner_identity=current_identity(),
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            created_at=_dkss_common.datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        _dkss_common.db.session.add(subscription)

    _dkss_common.db.session.commit()

    return {
        "success": True
    }



def push_unsubscribe():
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return {"error": "Unauthorized"}, 401

    data = _dkss_common.request.get_json(silent=True) or {}
    endpoint = str(
        data.get("endpoint") or ""
    ).strip()

    if not endpoint:
        return {"error": "Invalid push subscription."}, 400

    subscription = _dkss_models.PushSubscription.query.filter_by(
        endpoint=endpoint,
        company_code=company_code,
        username=username,
        owner_identity=current_identity()
    ).first()

    if subscription:
        _dkss_common.db.session.delete(subscription)
        _dkss_common.db.session.commit()

    return {"success": True}



def send_web_push_notification(
    user,
    title,
    message,
    link=""
):
    if not user:
        return False

    if (
        not _dkss_runtime.app.config['VAPID_PRIVATE_KEY']
        or not _dkss_runtime.app.config['VAPID_PUBLIC_KEY']
        or not _dkss_runtime.app.config['VAPID_SUBJECT']
    ):
        print(
            "Web Push未送信：VAPID設定がありません。"
        )
        return False

    if not user.account_identity:
        return False

    subscriptions = _dkss_models.PushSubscription.query.filter_by(
        company_code=user.company_code,
        owner_identity=user.account_identity
    ).all()

    if not subscriptions:
        return False

    unread_count = _dkss_models.Notification.query.filter(
        _dkss_models.Notification.company_code == user.company_code,
        _dkss_models.Notification.owner_identity == user.account_identity,
        _dkss_models.Notification.deleted_at.is_(None),
        _dkss_common.db.or_(
            _dkss_models.Notification.read.is_(False),
            _dkss_models.Notification.read.is_(None)
        )
    ).count()

    payload = _dkss_common.json.dumps(
        {
            "title": str(title or "")[:200],
            "message": str(message or "")[:10000],
            "link": build_absolute_app_url(link),
            "unread_count": unread_count,
        },
        ensure_ascii=False
    )

    sent = False

    for subscription in subscriptions:
        try:
            _dkss_common.webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    },
                },
                data=payload,
                vapid_private_key=_dkss_runtime.app.config['VAPID_PRIVATE_KEY'],
                vapid_claims={
                    "sub": _dkss_runtime.app.config['VAPID_SUBJECT']
                },
                ttl=300,
                timeout=20,
            )

            sent = True

        except _dkss_common.WebPushException as e:
            _dkss_runtime.app.logger.warning(
                "Web Push送信エラー: %s",
                e
            )

            response = getattr(
                e,
                "response",
                None
            )

            if (
                response is not None
                and response.status_code in (404, 410)
            ):
                _dkss_common.db.session.delete(subscription)
                _dkss_common.db.session.commit()

        except Exception:
            _dkss_runtime.app.logger.exception(
                "Web Push送信中に予期しないエラーが発生しました。"
            )

    return sent



def push_test():
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return {"success": False, "error": "Unauthorized"}, 401

    user = _dkss_models.User.query.filter_by(
        company_code=company_code,
        username=username,
        account_identity=current_identity()
    ).first()

    if not user:
        return {"success": False, "error": "User not found"}, 404

    sent = send_web_push_notification(
        user,
        "DKSS テスト通知",
        "端末通知のテストです。",
        "/notifications"
    )

    if not sent:
        return {
            "success": False,
            "error": "Push notification was not sent."
        }, 400

    return {"success": True}



def send_email_notification(
    user,
    title,
    message,
    link="",
    require_opt_in=True
):
    if not user:
        return False

    if require_opt_in and not user.email_notify_enabled:
        return False

    title = str(title or "").strip()

    if (
        not title
        or len(title) > 200
        or "\r" in title
        or "\n" in title
    ):
        return False

    message = str(message or "")

    if len(message) > 10000:
        return False

    if not _dkss_auth.is_valid_email_address(
        user.email_address
    ):
        return False

    smtp_host = _dkss_common.os.environ.get("SMTP_HOST", "")
    try:
        smtp_port = int(
            _dkss_common.os.environ.get("SMTP_PORT", "587")
        )
    except (TypeError, ValueError):
        print(
            "メール通知未送信：SMTP_PORTが不正です。"
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
        print(
            "メール通知未送信：SMTP設定がありません。"
        )
        return False

    if not _dkss_auth.is_valid_email_address(smtp_from):
        print(
            "メール通知未送信：SMTP_FROM が不正です。"
        )
        return False

    full_link = build_absolute_app_url(link)

    email = _dkss_common.EmailMessage()

    email["Subject"] = title
    email["From"] = smtp_from
    email["To"] = user.email_address

    body = message or ""

    if full_link:
        body += (
            "\n\n"
            "該当画面を開く：\n"
            f"{full_link}"
        )

    email.set_content(body)

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
            "メール通知送信中に予期しないエラーが発生しました。"
        )
        return False



def dispatch_external_notification(
    user,
    title,
    message,
    link="",
    notification_id=None
):
    if not user:
        return

    # A committed notification may outlive its account before delivery starts.
    # Do not resolve a replacement by username or send to a retired principal.
    if not user.account_identity or not _dkss_models.User.query.filter_by(
        company_code=user.company_code, account_identity=user.account_identity
    ).with_for_update(read=True).first():
        return
    if notification_id is not None and not _dkss_models.Notification.query.filter_by(
        id=notification_id, company_code=user.company_code, owner_identity=user.account_identity
    ).first():
        return

    push_link = link

    if notification_id is not None:
        if str(link or "").strip():
            push_link = f"/notifications/{notification_id}/open"
        else:
            push_link = f"/notifications/{notification_id}"

    send_web_push_notification(
        user,
        title,
        message,
        push_link
    )

    if user.email_notify_enabled:
        send_email_notification(
            user,
            title,
            message,
            link
        )



def build_notification_workflow_context(
    result_record,
    result_type,
    action,
    approval_index=None
):
    latest_event = _dkss_models.ChecklistEvent.query.filter_by(
        company_code=result_record.company_code,
        result_type=result_type,
        result_id=result_record.id
    ).order_by(
        _dkss_models.ChecklistEvent.id.desc()
    ).first()

    context = {
        "result_type": result_type,
        "result_id": result_record.id,
        "action": action,
        "event_id": latest_event.id if latest_event else 0,
    }

    if approval_index is not None:
        context["approval_index"] = approval_index

    return context



def add_notification(
    target_user,
    title,
    message,
    link="",
    files=None,
    company_code=None,
    target_username=None,
    workflow_context=None,
    target_identity=None,
    *,
    pending=None
):
    target_user = str(target_user or "").strip()
    title = str(title or "").strip()
    message = str(message or "")

    if not target_user:
        return

    if len(target_user) > 100:
        return

    if not title or len(title) > 200:
        return

    if len(message) > 10000:
        return

    if target_username is not None:
        target_username = str(
            target_username
        ).strip()

        if len(target_username) > 50:
            return

    notification_company_code = (
        company_code
        or _dkss_common.session.get("company_code")
    )

    link = str(link or "").strip()

    if (
        len(link) > 200
        or (
            link
            and (
                not link.startswith("/")
                or link.startswith("//")
                or "\\" in link
                or "\r" in link
                or "\n" in link
            )
        )
    ):
        link = ""

    target_user_record = None

    if target_username:
        recipient_query = _dkss_models.User.query.filter_by(
            company_code=notification_company_code,
            username=target_username
        )
        if target_identity is not None:
            recipient_query = recipient_query.filter_by(account_identity=target_identity)
        target_user_record = recipient_query.with_for_update(read=True).first()

        if not target_user_record:
            return

        target_user = (
            f"{target_user_record.last_name or ''}"
            f"{target_user_record.first_name or ''}"
        )
        target_username = target_user_record.username

    notification = _dkss_models.Notification(
        company_code=notification_company_code,
        target_user=target_user,
        target_username=target_username,
        owner_identity=target_user_record.account_identity if target_user_record else None,
        title=title,
        message=message,
        link=link,
        files_json=_dkss_common.json.dumps(
            files or [],
            ensure_ascii=False
        ),
        workflow_context_json=_dkss_common.json.dumps(
            workflow_context
            if isinstance(workflow_context, dict)
            else {},
            ensure_ascii=False
        ),
        read=False,
        created_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC")).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    )

    recipient_identity = target_user_record.account_identity if target_user_record else None
    _dkss_common.db.session.add(notification)
    _dkss_common.db.session.flush()
    saved_notification_id = notification.id
    if pending is not None:
        pending.append((target_user_record.id if target_user_record else None,
                        saved_notification_id, title, message, link))
        return
    _dkss_common.db.session.commit()

    recipient = _dkss_models.User.query.filter_by(company_code=notification_company_code,
        account_identity=recipient_identity).with_for_update(read=True).first() if recipient_identity else None
    if recipient:
        dispatch_external_notification(
            recipient,
            title,
            message,
            link,
            notification_id=saved_notification_id
        )



def build_absolute_app_url(link=""):
    link = str(link or "").strip()

    if not link:
        return ""

    if (
        not link.startswith("/")
        or link.startswith("//")
        or "\\" in link
        or "\r" in link
        or "\n" in link
    ):
        return ""

    base_url = _dkss_common.os.environ.get(
        "APP_BASE_URL",
        "https://dkss.onrender.com"
    ).rstrip("/")

    return base_url + link



def add_news(
    title,
    message,
    files=None,
    target_type="",
    target_value="",
    company_code=None,
    target_identity=None,
    *,
    commit=True
):
    title = str(title or "").strip()
    message = str(message or "")
    target_type = str(target_type or "").strip()
    target_value = str(target_value or "").strip()

    if not title or len(title) > 200:
        return

    if len(message) > 10000:
        return

    if len(target_type) > 50:
        return

    if len(target_value) > 100:
        return

    news_company_code = (
        company_code
        or _dkss_common.session.get("company_code")
    )

    if not news_company_code:
        raise ValueError(
            "News company_code is required."
        )

    news = _dkss_models.News(
        owner_identity=target_identity if target_type == 'user' else None,
        company_code=news_company_code,
        title=title,
        message=message,
        files_json=_dkss_common.json.dumps(
            files or [],
            ensure_ascii=False
        ),
        target_type=target_type,
        target_value=target_value,
        created_at=_dkss_common.datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )
    )

    _dkss_common.db.session.add(news)
    _dkss_common.db.session.flush()

    _dkss_audit.add_audit_log(
        action="news_created",
        target_type="news",
        target_id=news.id,
        detail=f"お知らせ作成: {news.title}",
        company_code=news.company_code,
    )

    if commit:
        _dkss_common.db.session.commit()



def notify_mentions(text, link="", *, pending=None):
    if not text:
        return

    options = {"pending": pending} if pending is not None else {}

    users = _dkss_models.User.query.filter_by(
        company_code=_dkss_common.session.get("company_code")
    ).all()
    from types import SimpleNamespace
    users = [SimpleNamespace(username=u.username, account_identity=u.account_identity,
        last_name=u.last_name, first_name=u.first_name) for u in users]

    users_by_name = {}

    for user in users:
        full_name = (
            f"{user.last_name or ''}"
            f"{user.first_name or ''}"
        )

        if not full_name or not user.username:
            continue

        users_by_name.setdefault(
            full_name,
            []
        ).append(user)

    notified_usernames = set()

    for user in users:
        name = (
            f"{user.last_name or ''}"
            f"{user.first_name or ''}"
        )
        username = user.username

        if not name or not username:
            continue

        stable_tag = f"[[{username}|{name}]]"

        if stable_tag in text:
            add_notification(
                name,
                "メンションされました",
                text,
                link,
                target_identity=user.account_identity,
                target_username=username,
                **options
            )
            notified_usernames.add(username)
            continue

        name_matches = users_by_name.get(
            name,
            []
        )

        if len(name_matches) != 1:
            continue

        legacy_mention = "@" + name
        legacy_tag = f"[[{name}]]"

        if (
            legacy_mention in text
            or legacy_tag in text
        ):
            if username in notified_usernames:
                continue

            add_notification(
                name,
                "メンションされました",
                text,
                link,
                target_identity=user.account_identity,
                target_username=username,
                **options
            )
            notified_usernames.add(username)
