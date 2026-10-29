"""Patrols responsibilities; routes are registered by the application factory."""
from . import audit as _dkss_audit, checklist_common as _dkss_checklist_common, common as _dkss_common, http as _dkss_http, models as _dkss_models, serialization as _dkss_serialization


def new_vehicle_patrol():

    if _dkss_common.request.method == "POST":
        form_errors = []

        vehicle_record_id = _dkss_common.request.form.get(
            "vehicle_record_id",
            type=int
        )

        vehicle = _dkss_models.Vehicle.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            id=vehicle_record_id,
            deleted=False
        ).first()

        if not vehicle:
            form_errors.append((
                "車両が不正です。",
                "vehicle_record_id"
            ))

        category = _dkss_common.request.form.get("category", "").strip()
        priority = _dkss_common.request.form.get("priority", "").strip()
        status = _dkss_common.request.form.get("status", "未対応").strip()

        if category not in {
            "故障",
            "不具合",
            "事故",
            "点検指摘",
            "その他"
        }:
            form_errors.append((
                "分類が不正です。",
                "category"
            ))

        if priority not in {
            "高",
            "中",
            "低"
        }:
            form_errors.append((
                "重要度が不正です。",
                "priority"
            ))

        if status not in {
            "未対応",
            "対応中",
            "修理完了"
        }:
            form_errors.append((
                "状態が不正です。",
                "status"
            ))
        occurred_date = _dkss_common.request.form.get(
            "occurred_date",
            ""
        ).strip()

        repair_date = _dkss_common.request.form.get(
            "repair_date",
            ""
        ).strip()

        repair_time = _dkss_common.request.form.get(
            "repair_time",
            ""
        ).strip()

        repair_person = _dkss_common.request.form.get(
            "repair_person",
            ""
        ).strip()

        cost = _dkss_common.request.form.get(
            "cost",
            ""
        ).strip()

        if len(repair_person) > 100:
            form_errors.append((
                "修理担当者は100文字以内で入力してください。",
                "repair_person"
            ))

        for value, field_name in [
            (
                occurred_date,
                "発生日"
            ),
            (
                repair_date,
                "修理日"
            )
        ]:
            if value:
                try:
                    _dkss_common.datetime.strptime(
                        value,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    return f"{field_name}が不正です。", 400

        if repair_time:
            try:
                repair_time = _dkss_http.parse_time_hhmm(
                    repair_time,
                    "修理時間"
                )
            except _dkss_common.UploadValidationError:
                return "修理時間の入力内容を確認してください。", 400

        if cost:
            normalized_cost = cost.replace(",", "")

            if not normalized_cost.isdigit():
                return "修理費用が不正です。", 400

            if len(normalized_cost) > 50:
                return "修理費用は50文字以内で入力してください。", 400

            if int(normalized_cost) < 0:
                return "修理費用は0以上で入力してください。", 400

            cost = normalized_cost

        content = _dkss_common.request.form.get(
            "content",
            ""
        ).strip()
        cause = _dkss_common.request.form.get(
            "cause",
            ""
        ).strip()
        temporary_action = _dkss_common.request.form.get(
            "temporary_action",
            ""
        ).strip()
        repair_content = _dkss_common.request.form.get(
            "repair_content",
            ""
        ).strip()
        parts = _dkss_common.request.form.get(
            "parts",
            ""
        ).strip()

        for value, field_name in [
            (content, "内容"),
            (cause, "原因"),
            (temporary_action, "応急処置"),
            (repair_content, "修理内容"),
            (parts, "使用部品"),
        ]:
            if len(value) > 5000:
                return (
                    f"{field_name}は5000文字以内で入力してください。",
                    400
                )

        if form_errors:
            return _dkss_http.return_form_errors(form_errors)

        patrol = _dkss_models.VehiclePatrol(
            company_code=_dkss_common.session.get("company_code"),
            vehicle_record_id=vehicle.id,
            occurred_date=occurred_date,
            category=category,
            priority=priority,
            content=content,
            cause=cause,
            temporary_action=temporary_action,
            repair_content=repair_content,
            status=status,
            repair_date=repair_date,
            repair_person=repair_person,
            repair_time=repair_time,
            parts=parts,
            cost=cost
        )

        _dkss_common.db.session.add(patrol)
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/vehicle-patrols")

    return _dkss_common.render_template(
        "vehicle_patrol_form.html",
        patrol=None,
        selected_vehicle=None,
        mode="new"
    )



def add_usage_vehicle():
    vehicle_record_id = _dkss_common.request.form.get(
        "vehicle_record_id",
        type=int
    )

    if not vehicle_record_id:
        return _dkss_common.redirect("/vehicle-patrols")

    vehicle = _dkss_models.Vehicle.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        id=vehicle_record_id,
        deleted=False
    ).first()

    if not vehicle:
        return _dkss_common.redirect("/vehicle-patrols")

    current_driver = _dkss_models.Driver.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        employee_id=_dkss_common.session.get("username")
    ).first()

    if not current_driver:
        return _dkss_common.redirect(
            "/" if _dkss_common.request.form.get("next") == "/" else "/vehicle-patrols"
        )

    usage_vehicles = _dkss_serialization.safe_json_str_list(
        current_driver.vehicles_json
    )

    vehicle_record_id_str = str(vehicle.id)

    if vehicle_record_id_str not in usage_vehicles:
        usage_vehicles.append(vehicle_record_id_str)

    current_driver.vehicles_json = _dkss_common.json.dumps(
        usage_vehicles,
        ensure_ascii=False
    )

    _dkss_common.db.session.commit()

    return _dkss_common.redirect(
        "/" if _dkss_common.request.form.get("next") == "/" else "/vehicle-patrols"
    )



def remove_usage_vehicle(vehicle_record_id):
    current_driver = _dkss_models.Driver.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        employee_id=_dkss_common.session.get("username")
    ).first()

    if not current_driver:
        return _dkss_common.redirect(
            "/" if _dkss_common.request.form.get("next") == "/" else "/vehicle-patrols"
        )

    usage_vehicles = _dkss_serialization.safe_json_str_list(
        current_driver.vehicles_json
    )

    vehicle_record_id_str = str(vehicle_record_id)

    if vehicle_record_id_str in usage_vehicles:
        usage_vehicles.remove(vehicle_record_id_str)

    current_driver.vehicles_json = _dkss_common.json.dumps(
        usage_vehicles,
        ensure_ascii=False
    )

    _dkss_common.db.session.commit()

    return _dkss_common.redirect(
        "/" if _dkss_common.request.form.get("next") == "/" else "/vehicle-patrols"
    )



def vehicle_patrols():

    keyword = _dkss_common.request.args.get("keyword", "").strip()
    status_filter = _dkss_common.request.args.get("status", "active")

    if len(keyword) > 100:
        return "検索条件が長すぎます。", 400

    current_driver = _dkss_models.Driver.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        employee_id=_dkss_common.session.get("username")
    ).first()

    usage_vehicles = (
        _dkss_serialization.safe_json_str_list(current_driver.vehicles_json)
        if current_driver
        else []
    )

    usage_vehicle_records = _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.company_code == _dkss_common.session.get("company_code"),
        _dkss_models.Vehicle.deleted == False,
        _dkss_models.Vehicle.id.in_([
            int(vehicle_record_id)
            for vehicle_record_id in usage_vehicles
            if vehicle_record_id.isdigit()
        ])
    ).all() if usage_vehicles else []

    usage_patrols = []
    other_patrols = []

    query = _dkss_models.VehiclePatrol.query.join(
        _dkss_models.Vehicle,
        _dkss_models.Vehicle.id == _dkss_models.VehiclePatrol.vehicle_record_id
    ).filter(
        _dkss_models.VehiclePatrol.company_code == _dkss_common.session.get("company_code")
    )

    if status_filter == "active":
        query = query.filter(
            _dkss_models.VehiclePatrol.status != "修理完了"
        )
    elif status_filter:
        query = query.filter(
            _dkss_models.VehiclePatrol.status == status_filter
        )

    if keyword:
        keyword_like = f"%{keyword}%"

        query = query.filter(
            _dkss_common.db.or_(
                _dkss_models.Vehicle.chassis_number.ilike(keyword_like),
                _dkss_models.Vehicle.plate_number.ilike(keyword_like),
                _dkss_models.VehiclePatrol.content.ilike(keyword_like),
                _dkss_models.VehiclePatrol.repair_person.ilike(keyword_like)
            )
        )

    patrol_records = query.order_by(
        _dkss_models.VehiclePatrol.id.desc()
    ).all()

    for patrol_record in patrol_records:
        patrol = _dkss_checklist_common.vehicle_patrol_to_dict(patrol_record)

        if str(patrol.get("vehicle_record_id")) in usage_vehicles:
            usage_patrols.append(patrol)
        else:
            other_patrols.append(patrol)

    return _dkss_common.render_template(
        "vehicle_patrols.html",
        usage_patrols=usage_patrols,
        other_patrols=other_patrols,
        usage_vehicles=usage_vehicles,
        usage_vehicle_records=usage_vehicle_records,
        keyword=keyword,
        status_filter=status_filter
    )



def vehicle_patrol_detail(index):

    patrol = _dkss_models.VehiclePatrol.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not patrol:
        return _dkss_common.redirect("/vehicle-patrols")

    if patrol.company_code != _dkss_common.session.get("company_code"):
        return _dkss_common.redirect("/vehicle-patrols")

    return _dkss_common.render_template(
        "vehicle_patrol_detail.html",
        patrol=_dkss_checklist_common.vehicle_patrol_to_dict(patrol),
        index=patrol.id
    )



def edit_vehicle_patrol(index):

    if _dkss_common.session.get("role") not in ["admin", "itc"]:
        return _dkss_common.redirect("/vehicle-patrols")

    patrol = _dkss_models.VehiclePatrol.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not patrol:
        return _dkss_common.redirect("/vehicle-patrols")

    if _dkss_common.request.method == "POST":
        form_errors = []

        vehicle_record_id = _dkss_common.request.form.get(
            "vehicle_record_id",
            type=int
        )

        vehicle = _dkss_models.Vehicle.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            id=vehicle_record_id,
            deleted=False
        ).first()

        if not vehicle:
            return "車両が不正です。", 403

        category = _dkss_common.request.form.get("category", "").strip()
        priority = _dkss_common.request.form.get("priority", "").strip()
        status_submitted = "status" in _dkss_common.request.form
        status = _dkss_common.request.form.get("status", "").strip()

        if category not in {
            "故障",
            "不具合",
            "事故",
            "点検指摘",
            "その他"
        }:
            return "分類が不正です。", 400

        if priority not in {
            "高",
            "中",
            "低"
        }:
            return "重要度が不正です。", 400

        if status_submitted and status not in {
            "未対応",
            "対応中",
            "修理完了"
        }:
            form_errors.append((
                "状態が不正です。",
                "status"
            ))
        occurred_date = _dkss_common.request.form.get(
            "occurred_date",
            ""
        ).strip()

        repair_date = _dkss_common.request.form.get(
            "repair_date",
            ""
        ).strip()

        repair_time = _dkss_common.request.form.get(
            "repair_time",
            ""
        ).strip()

        repair_person = _dkss_common.request.form.get(
            "repair_person",
            ""
        ).strip()

        cost = _dkss_common.request.form.get(
            "cost",
            ""
        ).strip()

        if len(repair_person) > 100:
            form_errors.append((
                "修理担当者は100文字以内で入力してください。",
                "repair_person"
            ))

        for value, field_name in [
            (
                occurred_date,
                "発生日"
            ),
            (
                repair_date,
                "修理日"
            )
        ]:
            if value:
                try:
                    _dkss_common.datetime.strptime(
                        value,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    form_errors.append((
                        f"{field_name}が不正です。",
                        "occurred_date" if field_name == "発生日" else "repair_date"
                    ))

        if repair_time:
            try:
                repair_time = _dkss_http.parse_time_hhmm(
                    repair_time,
                    "修理時間"
                )
            except _dkss_common.UploadValidationError:
                return "修理時間の入力内容を確認してください。", 400

        if cost:
            normalized_cost = cost.replace(",", "")

            if not normalized_cost.isdigit():
                return "修理費用が不正です。", 400

            if len(normalized_cost) > 50:
                return "修理費用は50文字以内で入力してください。", 400

            if int(normalized_cost) < 0:
                return "修理費用は0以上で入力してください。", 400

            cost = normalized_cost

        content = _dkss_common.request.form.get(
            "content",
            ""
        ).strip()
        cause = _dkss_common.request.form.get(
            "cause",
            ""
        ).strip()
        temporary_action = _dkss_common.request.form.get(
            "temporary_action",
            ""
        ).strip()
        repair_content = _dkss_common.request.form.get(
            "repair_content",
            ""
        ).strip()
        parts = _dkss_common.request.form.get(
            "parts",
            ""
        ).strip()

        for value, field_name in [
            (content, "内容"),
            (cause, "原因"),
            (temporary_action, "応急処置"),
            (repair_content, "修理内容"),
            (parts, "使用部品"),
        ]:
            if len(value) > 5000:
                return (
                    f"{field_name}は5000文字以内で入力してください。",
                    400
                )

        if form_errors:
            return _dkss_http.return_form_errors(form_errors)

        patrol.vehicle_record_id = vehicle.id
        patrol.occurred_date = occurred_date
        patrol.category = category
        patrol.priority = priority
        patrol.content = content

        patrol.cause = cause
        patrol.temporary_action = temporary_action
        patrol.repair_content = repair_content

        patrol.repair_date = repair_date
        patrol.repair_person = repair_person
        patrol.repair_time = repair_time
        patrol.parts = parts
        patrol.cost = cost
        # An omitted field does not request a state transition.
        if status_submitted:
            patrol.status = status

        _dkss_common.db.session.commit()

        return _dkss_common.redirect(f"/vehicle-patrols/{patrol.id}")

    selected_vehicle = None

    vehicle = _dkss_models.Vehicle.query.filter_by(
        company_code=patrol.company_code,
        id=patrol.vehicle_record_id
    ).first()

    if vehicle:

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

        selected_vehicle = {
            "vehicle_record_id": vehicle.id,
            "chassis_number": vehicle.chassis_number,
            "number": number,
            "manufacturer": vehicle.manufacturer or "",
            "model_code": vehicle.model_code or "",
        }


    return _dkss_common.render_template(
        "vehicle_patrol_form.html",
        patrol=_dkss_checklist_common.vehicle_patrol_to_dict(patrol),
        index=patrol.id,
        selected_vehicle=selected_vehicle,
        mode="edit"
    )



def delete_vehicle_patrol(index):

    if _dkss_common.session.get("role") not in ["admin", "itc"]:
        return _dkss_common.redirect("/vehicle-patrols")

    patrol = _dkss_models.VehiclePatrol.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not patrol:
        return _dkss_common.redirect("/vehicle-patrols")

    _dkss_audit.add_audit_log(
        action="vehicle_patrol_deleted",
        target_type="vehicle_patrol",
        target_id=patrol.id,
        detail=(
            "車両パトロール・修理履歴削除: "
            f"vehicle_record_id={patrol.vehicle_record_id}"
        ),
        company_code=patrol.company_code,
    )

    _dkss_common.db.session.delete(patrol)
    _dkss_common.db.session.commit()

    return _dkss_common.redirect("/vehicle-patrols")
