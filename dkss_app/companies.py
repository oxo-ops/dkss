"""Companies responsibilities; routes are registered by the application factory."""
from . import access as _dkss_access, audit as _dkss_audit, common as _dkss_common, http as _dkss_http, models as _dkss_models, serialization as _dkss_serialization


def itc_dashboard():
    if not _dkss_access.require_itc():
        return _dkss_common.redirect("/")

    companies = _dkss_models.Company.query.order_by(
        _dkss_models.Company.company_name.asc()
    ).all()

    company_summaries = []

    for company in companies:
        usage = _dkss_models.CompanyUsageSummary.query.filter_by(
            company_code=company.company_code
        ).first()

        vehicle_count = (
            usage.vehicle_count
            if usage
            else 0
        )

        company_summaries.append({
            "id": company.id,
            "company_code": company.company_code,
            "company_name": company.company_name,
            "vehicle_limit": company.vehicle_limit,
            "active": company.active,
            "vehicle_count": vehicle_count,
            "remaining_vehicles": (
                company.vehicle_limit - vehicle_count
            ),
            "user_count": usage.user_count if usage else 0,
            "login_count": usage.login_count if usage else 0,
            "checklist_result_count": (
                usage.checklist_result_count if usage else 0
            ),
            "last_used_at": usage.last_used_at if usage else None,
        })

    company_code = _dkss_common.session.get("company_code")

    news_items = []

    news_records = _dkss_models.News.query.filter_by(
        company_code=company_code
    ).order_by(
        _dkss_models.News.id.desc()
    ).all()

    for news in news_records:
        visible = False

        if news.target_type in ["all", "admins"]:
            visible = True

        elif (
            news.target_type == "company"
            and news.target_value == company_code
        ):
            visible = True

        elif news.target_type == "office":
            valid_office = _dkss_models.Office.query.filter_by(
                company_code=company_code,
                name=news.target_value
            ).first()

            visible = valid_office is not None

        elif news.target_type == "user":
            valid_user = _dkss_models.User.query.filter_by(
                company_code=company_code,
                username=news.target_value
            ).first()

            visible = valid_user is not None

        if not visible:
            continue

        news_items.append({
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
        })

    return _dkss_common.render_template(
        "itc_dashboard.html",
        companies=company_summaries,
        news=news_items
    )



def itc_new_company():
    if not _dkss_access.require_itc():
        return _dkss_common.redirect("/")

    if _dkss_common.request.method == "POST":
        form_errors = []

        company_code = _dkss_common.request.form.get(
            "company_code",
            ""
        ).strip()
        company_name = _dkss_common.request.form.get(
            "company_name",
            ""
        ).strip()

        if not company_code:
            form_errors.append((
                "会社コードを入力してください。",
                "company_code"
            ))
        elif len(company_code) > 50:
            form_errors.append((
                "会社コードは50文字以内で入力してください。",
                "company_code"
            ))
        elif not _dkss_common.re.fullmatch(
            r"[A-Za-z0-9_-]+",
            company_code
        ):
            form_errors.append((
                "会社コードは半角英数字・ハイフン・"
                "アンダースコアのみ使用できます。",
                "company_code"
            ))

        if not company_name:
            form_errors.append((
                "会社名を入力してください。",
                "company_name"
            ))
        elif len(company_name) > 100:
            form_errors.append((
                "会社名は100文字以内で入力してください。",
                "company_name"
            ))

        duplicate_company = _dkss_models.Company.query.filter(
            _dkss_common.db.func.lower(_dkss_models.Company.company_code)
            == company_code.lower()
        ).first()

        if duplicate_company:
            form_errors.append((
                "この会社コードはすでに登録されています。",
                "company_code"
            ))

        vehicle_limit = 0

        try:
            vehicle_limit = _dkss_http.parse_nonnegative_int(
                _dkss_common.request.form.get("vehicle_limit"),
                "車両上限数"
            )
        except _dkss_common.UploadValidationError:
            form_errors.append((
                "車両上限数の入力内容を確認してください。",
                "vehicle_limit"
            ))

        if form_errors:
            return _dkss_http.return_form_errors(
                form_errors,
                409 if duplicate_company else 400
            )

        company = _dkss_models.Company(
            company_code=company_code,
            company_name=company_name,
            vehicle_limit=vehicle_limit,
            active=True,
        )

        _dkss_common.db.session.add(company)

        default_content_types = [
            "落下",
            "車両",
            "環境",
            "荷扱い",
            "ルール違反",
            "Good",
            "その他",
        ]

        for name in default_content_types:
            _dkss_common.db.session.add(
                _dkss_models.PatrolContentType(
                    company_code=company.company_code,
                    name=name
                )
            )

        _dkss_audit.add_audit_log(
            action="company_created",
            target_type="company",
            target_id=company.company_code,
            detail=f"会社登録: {company.company_name}",
            company_code=_dkss_common.session.get("company_code"),
        )
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/itc")

    return _dkss_common.render_template(
        "itc_company_form.html",
        company=None,
        index=None,
        mode="new"
    )



def itc_edit_company(index):
    if not _dkss_access.require_itc():
        return _dkss_common.redirect("/")

    company = _dkss_models.Company.query.filter_by(
        id=index
    ).first()

    if not company:
        return _dkss_common.redirect("/itc")

    if _dkss_common.request.method == "POST":
        form_errors = []

        company_name = _dkss_common.request.form.get(
            "company_name",
            ""
        ).strip()

        if not company_name:
            form_errors.append((
                "会社名を入力してください。",
                "company_name"
            ))
        elif len(company_name) > 100:
            form_errors.append((
                "会社名は100文字以内で入力してください。",
                "company_name"
            ))

        vehicle_limit = 0

        try:
            vehicle_limit = _dkss_http.parse_nonnegative_int(
                _dkss_common.request.form.get("vehicle_limit"),
                "車両上限数"
            )
        except _dkss_common.UploadValidationError:
            form_errors.append((
                "車両上限数の入力内容を確認してください。",
                "vehicle_limit"
            ))

        if form_errors:
            return _dkss_http.return_form_errors(form_errors)

        company.company_name = company_name
        company.vehicle_limit = vehicle_limit
        company.active = _dkss_common.request.form.get("active") == "1"

        _dkss_audit.add_audit_log(
            action="company_updated",
            target_type="company",
            target_id=company.company_code,
            detail=f"会社情報変更: {company.company_name}",
            company_code=_dkss_common.session.get("company_code"),
        )

        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/itc")

    company_dict = {
        "company_code": company.company_code,
        "company_name": company.company_name,
        "vehicle_limit": company.vehicle_limit,
        "active": company.active,
    }

    return _dkss_common.render_template(
        "itc_company_form.html",
        company=company_dict,
        index=company.id,
        mode="edit"
    )
