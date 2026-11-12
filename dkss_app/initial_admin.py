"""First administrator provisioning through the authenticated ITC console only."""
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import abort, current_app, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash

from .access import require_itc
from .audit import add_audit_log, update_company_usage_summary
from .auth import is_valid_email_address
from .extensions import db
from .models import Company, Driver, User


def lock_company(company_code=None, company_id=None):
    """Serialize first-account provisioning and public registration on PostgreSQL.

    Both writers must hold this lock through their account transaction's commit.
    populate_existing prevents a previously loaded Company's stale active flag.
    """
    query = Company.query
    if company_id is not None:
        query = query.filter_by(id=company_id)
    else:
        query = query.filter_by(company_code=company_code)
    return query.populate_existing().with_for_update().first()


def eligible(company):
    return bool(company and company.active and company.company_code.upper() != "ITC"
                and not User.query.filter_by(company_code=company.company_code).first()
                and not Driver.query.filter_by(company_code=company.company_code).first())


def itc_initial_admin(index):
    # The application-wide login hook also validates identity, password age and role.
    if not require_itc():
        abort(403)
    company = lock_company(company_id=index)
    if company is None:
        abort(404)
    if not eligible(company):
        abort(409)
    error = None
    values = {}
    if request.method == "POST":
        values = {key: request.form.get(key, "").strip() for key in
                  ("employee_id", "last_name", "first_name", "email_address")}
        values["email_address"] = values["email_address"].lower()
        password = request.form.get("password", "")
        types = sum((any(c.islower() for c in password), any(c.isupper() for c in password),
                     any(c.isdigit() for c in password), any(not c.isalnum() for c in password)))
        if any(key in request.form for key in ("company_code", "company_id", "role")):
            error = "会社・権限はこの画面では変更できません。"
        elif not values["employee_id"] or not values["last_name"]:
            error = "ログインIDと姓を入力してください。"
        elif len(values["employee_id"]) > 50 or len(values["last_name"] + values["first_name"]) > 100:
            error = "ログインIDは50文字以内、氏名は合計100文字以内で入力してください。"
        elif (values["email_address"] and not is_valid_email_address(values["email_address"])) or (current_app.config.get("MFA_ENABLED") and not values["email_address"]):
            error = "有効なメールアドレスを入力してください。多要素認証が有効な場合は必須です。"
        elif not 8 <= len(password) <= 128 or types < 3:
            error = "パスワードは8〜128文字で英小文字・英大文字・数字・記号のうち3種類以上を含めてください。"
        else:
            try:
                code = company.company_code
                username = values["employee_id"]
                db.session.add(User(company_code=code, username=username,
                    password=generate_password_hash(password), password_history_json="[]",
                    password_changed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    last_name=values["last_name"], first_name=values["first_name"] or None,
                    role="admin", email_address=values["email_address"] or None,
                    email_notify_enabled=False))
                db.session.add(Driver(company_code=code, employee_id=username,
                    name=values["last_name"] + values["first_name"], role="admin",
                    safe_start_date=datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d"),
                    vehicles_json="[]", licenses_json="[]"))
                db.session.flush()
                add_audit_log(action="initial_company_admin_created", target_type="company",
                              target_id=company.id, company_code=code,
                              detail="ITC管理画面から初回管理者を作成")
                update_company_usage_summary(code)
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                # Never log raw database exceptions (which can contain bound secrets).
                error = "登録できませんでした。会社の登録状況を確認してください。"
            else:
                return redirect(url_for("itc_dashboard"))
    response = render_template("itc_initial_admin.html", company=company,
                               values=values, error=error,
                               mfa_enabled=current_app.config.get("MFA_ENABLED", False))
    # GET/invalid forms must not retain a company-row lock.
    db.session.rollback()
    return response, 400 if error else 200
