"""Directory Api responsibilities; routes are registered by the application factory."""
from . import common as _dkss_common, master_readers as _dkss_master_readers, models as _dkss_models


def news_targets():
    target_type = _dkss_common.request.args.get("type", "")
    keyword = _dkss_common.request.args.get("q", "").strip()

    if len(keyword) > 100:
        return {"results": []}, 400

    company_code = _dkss_common.session.get("company_code")
    role = _dkss_common.session.get("role")

    results = []

    # ITC専用機能
    if role != "itc":
        return {"results": []}, 403

    if target_type == "company":
        query = _dkss_models.Company.query.filter_by(
            company_code=company_code
        )

        if keyword:
            keyword_like = f"%{keyword}%"
            query = query.filter(
                _dkss_common.db.or_(
                    _dkss_models.Company.company_name.ilike(keyword_like),
                    _dkss_models.Company.company_code.ilike(keyword_like)
                )
            )

        for company in query.order_by(
            _dkss_models.Company.company_name.asc()
        ).limit(10).all():
            results.append({
                "id": company.company_code,
                "name": company.company_name,
                "sub": "会社コード：" + company.company_code
            })

    elif target_type == "office":
        query = _dkss_models.Office.query.filter_by(
            company_code=company_code
        )

        if keyword:
            keyword_like = f"%{keyword}%"
            query = query.filter(
                _dkss_models.Office.name.ilike(keyword_like)
            )

        for office in _dkss_master_readers.ordered_master_query(
            _dkss_models.Office, company_code, query
        ).limit(10).all():
            results.append({
                "id": office.name or "",
                "name": office.name or "",
                "sub": "営業所"
            })

    elif target_type == "user":
        query = _dkss_models.User.query.filter(
            _dkss_models.User.company_code == company_code,
            _dkss_models.User.role != "itc"
        )

        if keyword:
            keyword_like = f"%{keyword}%"
            query = query.filter(
                _dkss_common.db.or_(
                    _dkss_models.User.last_name.ilike(keyword_like),
                    _dkss_models.User.first_name.ilike(keyword_like),
                    _dkss_models.User.username.ilike(keyword_like),
                    _dkss_models.User.office.ilike(keyword_like)
                )
            )

        for user in query.order_by(
            _dkss_models.User.last_name.asc(),
            _dkss_models.User.first_name.asc()
        ).limit(10).all():
            results.append({
                "id": user.username,
                "name": (
                    f"{user.last_name or ''}"
                    f"{user.first_name or ''}"
                ),
                "sub": user.office or ""
            })

    return {"results": results}



def approval_candidates():
    company_code = _dkss_common.session.get("company_code")
    office = _dkss_common.session.get("office") or ""

    if not company_code or not office:
        return {"users": []}

    users = _dkss_models.User.query.filter(
        _dkss_models.User.company_code == company_code,
        _dkss_models.User.office == office,
        _dkss_models.User.role == "admin"
    ).order_by(
        _dkss_models.User.last_name.asc(),
        _dkss_models.User.first_name.asc()
    ).all()

    return {
        "users": [
            {
                "name": (
                    f"{user.last_name or ''}"
                    f"{user.first_name or ''}"
                ),
                "username": user.username,
                "office": user.office or ""
            }
            for user in users
        ]
    }



def mention_users():
    keyword = _dkss_common.request.args.get("q", "").strip()

    if len(keyword) > 100:
        return {"users": []}, 400

    if not keyword:
        return {"users": []}

    user_query = _dkss_models.User.query.filter_by(
        company_code=_dkss_common.session.get("company_code")
    )

    if _dkss_common.request.args.get("exact_username") == "1":
        user_query = user_query.filter(
            _dkss_models.User.username == keyword
        )
    elif keyword:
        keyword_like = f"%{keyword}%"

        user_query = user_query.filter(
            _dkss_common.db.or_(
                _dkss_models.User.last_name.ilike(keyword_like),
                _dkss_models.User.first_name.ilike(keyword_like),
                _dkss_models.User.username.ilike(keyword_like),
                (
                    _dkss_common.db.func.coalesce(_dkss_models.User.last_name, "")
                    + _dkss_common.db.func.coalesce(_dkss_models.User.first_name, "")
                ).ilike(keyword_like)
            )
        )

    approval_scope = _dkss_common.request.args.get("approval_scope", "")
    if approval_scope == "admin":
        user_query = user_query.filter(_dkss_models.User.role == "admin")
    elif approval_scope == "admin_user":
        user_query = user_query.filter(_dkss_models.User.role.in_(["admin", "user"]))

    matched_users = (
        user_query
        .order_by(
            _dkss_models.User.last_name.asc(),
            _dkss_models.User.first_name.asc()
        )
        .limit(5)
        .all()
    )

    users = [
        {
            "name": (
                f"{user.last_name or ''}"
                f"{user.first_name or ''}"
            ),
            "username": user.username,
            "office": user.office or "",
            "role": user.role or "user"
        }
        for user in matched_users
    ]

    return {"users": users}



def search_vehicles():

    keyword = _dkss_common.request.args.get("q", "").strip()

    if len(keyword) > 100:
        return {"results": []}, 400

    company_code = _dkss_common.session.get("company_code")

    query = _dkss_models.Vehicle.query.filter_by(
        company_code=company_code,
        deleted=False
    )
    normalized = _dkss_common.normalize_vehicle_operation_plate(keyword)
    vehicles = []
    # Match the whole displayed registration as well as individual attributes.
    # Apply the result limit after matching so later vehicle IDs remain searchable.
    candidates = query.order_by(_dkss_models.Vehicle.id.asc()).yield_per(200)
    for vehicle in candidates:
        plate = ''.join(str(value or '') for value in (
            vehicle.plate_area, vehicle.plate_class,
            vehicle.plate_kana, vehicle.plate_number,
        ))
        values = (plate, vehicle.chassis_number, vehicle.model_code, vehicle.manufacturer)
        if normalized and not any(
            normalized in _dkss_common.normalize_vehicle_operation_plate(value) for value in values
        ):
            continue
        vehicles.append(vehicle)
        if len(vehicles) == 20:
            break

    results = []

    for vehicle in vehicles:

        number = " ".join(
            value
            for value in [
                vehicle.plate_area or "",
                vehicle.plate_class or "",
                vehicle.plate_kana or "",
                vehicle.plate_number or "",
            ]
            if value
        )

        results.append({
            "id": vehicle.id,
            "vehicle_record_id": vehicle.id,
            "number": number,
            "chassis_number": vehicle.chassis_number or "",
            "manufacturer": vehicle.manufacturer or "",
            "model_code": vehicle.model_code or "",
        })

    return {
        "results": results
    }
