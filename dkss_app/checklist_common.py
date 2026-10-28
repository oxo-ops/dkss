"""Checklist Common responsibilities; routes are registered by the application factory."""
from . import common as _dkss_common, master_readers as _dkss_master_readers, models as _dkss_models, serialization as _dkss_serialization


def vehicle_patrol_to_dict(patrol):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        company_code=patrol.company_code,
        id=patrol.vehicle_record_id
    ).first()

    return {
        "chassis_number": (
            vehicle.chassis_number
            if vehicle
            else ""
        ),
        "number": (
            " ".join(
                value
                for value in [
                    vehicle.plate_area or "",
                    vehicle.plate_class or "",
                    vehicle.plate_kana or "",
                    vehicle.plate_number or "",
                ]
                if value
            )
            if vehicle
            else ""
        ),
        "id": patrol.id,
        "index": patrol.id,
        "company_code": patrol.company_code,
        "vehicle_record_id": patrol.vehicle_record_id,
        "occurred_date": patrol.occurred_date,
        "category": patrol.category,
        "priority": patrol.priority,
        "content": patrol.content,
        "cause": patrol.cause,
        "temporary_action": patrol.temporary_action,
        "repair_content": patrol.repair_content,
        "status": patrol.status,
        "repair_date": patrol.repair_date,
        "repair_person": patrol.repair_person,
        "repair_time": patrol.repair_time,
        "parts": patrol.parts,
        "cost": patrol.cost,
    }



def vehicle_patrols_for_current_company():
    query = _dkss_models.VehiclePatrol.query.filter_by(
        company_code=_dkss_common.session.get("company_code")
    )

    return [
        vehicle_patrol_to_dict(patrol)
        for patrol in query.order_by(_dkss_models.VehiclePatrol.id.desc()).all()
    ]



def ensure_daily_inspection_checklist():
    company_code = _dkss_common.session.get("company_code")
    template = _dkss_common.get_daily_inspection_default()

    company = _dkss_models.Company.query.filter_by(
        company_code=company_code
    ).with_for_update().first()

    if not company:
        raise ValueError("会社情報を確認できません。")

    existing_checklist = None

    for checklist in _dkss_models.Checklist.query.filter_by(
        company_code=company_code,
        target="車両管理"
    ).all():
        items = _dkss_serialization.safe_json_dict_list(checklist.items_json)

        if items and items[0].get("fixed_template_code") == template["template_code"]:
            existing_checklist = checklist
            break

    items = []

    for source in template["items"]:
        item = dict(source)
        item.update({
            "answer_required": False,
            "comment_required": False,
            "score_enabled": False,
            "criteria_files": []
        })
        items.append(item)

    for field in template["footer_fields"]:
        item = {
            "item_type": field["field_type"],
            "item_code": f"footer_{field['order']}",
            "category": "",
            "content": field["label"]
        }

        if field["field_type"] == "check":
            item.update({
                "input_type": "select",
                "choices": list(field["choices"]),
                "criteria": template["criteria"],
                "answer_required": False,
                "comment_required": False,
                "score_enabled": False,
                "criteria_files": [],
                "shaded": False
            })

        if field["field_type"] == "approval":
            item["approval_label"] = field["label"]
            item["approval_allow_general"] = False

        items.append(item)

    items[0]["fixed_template_code"] = template["template_code"]
    items[0]["fixed_template_version"] = template["template_version"]

    if existing_checklist:
        if _dkss_serialization.safe_json_dict_list(existing_checklist.items_json) != items:
            existing_checklist.items_json = _dkss_common.json.dumps(items, ensure_ascii=False)
            _dkss_common.db.session.flush()
        return existing_checklist

    checklist = _dkss_models.Checklist(
        company_code=company_code,
        name=template["name"],
        target="車両管理",
        frequency_value="1",
        frequency_unit="day",
        display_type="month",
        print_portrait=False,
        print_half_month=template["print_half_month"],
        reminder_enabled=False,
        reminder_time="08:00",
        active=True,
        items_json=_dkss_common.json.dumps(items, ensure_ascii=False),
        version_history_json="[]",
        notify_users_json="[]"
    )

    _dkss_common.db.session.add(checklist)
    _dkss_common.db.session.flush()

    return checklist



def checklist_to_dict(checklist):
    items = _dkss_serialization.safe_json_dict_list(
        checklist.items_json
    )

    return {
        "id": checklist.id,
        "index": checklist.id,
        "company_code": checklist.company_code,
        "name": checklist.name,
        "target": checklist.target,
        "frequency_value": checklist.frequency_value,
        "frequency_unit": checklist.frequency_unit,
        "display_type": checklist.display_type,
        "active": bool(checklist.active),
        "print_portrait": bool(checklist.print_portrait),
        "print_half_month": bool(checklist.print_half_month),
        "reminder_enabled": bool(checklist.reminder_enabled),
        "reminder_time": checklist.reminder_time or "08:00",
        "items": items,
        "fixed_template_code": (
            items[0].get("fixed_template_code", "")
            if items
            else ""
        ),
        "version_history": _dkss_serialization.safe_json_dict_list(
            checklist.version_history_json
        ),
        "score_enabled": any(
            item.get("score_enabled", False)
            for item in items
            if item.get("item_type") == "check"
        ),
    }



def checklist_revision_key(checklist):
    revision_data = {
        "name": checklist.get("name", ""),
        "target": checklist.get("target", ""),
        "frequency_value": checklist.get(
            "frequency_value",
            ""
        ),
        "frequency_unit": checklist.get(
            "frequency_unit",
            ""
        ),
        "display_type": checklist.get(
            "display_type",
            ""
        ),
        "print_portrait": bool(
            checklist.get("print_portrait")
        ),
        "print_half_month": bool(
            checklist.get("print_half_month")
        ),
        "items": checklist.get("items", []),
    }

    return _dkss_common.json.dumps(
        revision_data,
        ensure_ascii=False,
        sort_keys=True
    )



def checklist_for_date(
    checklist,
    year,
    month,
    day
):
    current_checklist = {
        key: value
        for key, value in checklist.items()
        if key != "version_history"
    }

    try:
        target_date = _dkss_common.datetime(
            int(year),
            int(month),
            int(day)
        ).date()
    except (TypeError, ValueError):
        return current_checklist

    version_history = []

    for version in checklist.get(
        "version_history",
        []
    ):
        try:
            change_datetime = _dkss_common.datetime.strptime(
                version.get("effective_until", ""),
                "%Y-%m-%d %H:%M:%S"
            )
        except (TypeError, ValueError):
            continue

        snapshot = version.get("snapshot") or {}

        if not isinstance(snapshot, dict):
            continue

        version_history.append({
            "change_date": change_datetime.date(),
            "snapshot": snapshot
        })

    version_history.sort(
        key=lambda version: version["change_date"]
    )

    for version in version_history:
        if target_date < version["change_date"]:
            return version["snapshot"]

    return current_checklist



def checklists_for_current_company():
    query = _dkss_master_readers.ordered_master_query(_dkss_models.Checklist, _dkss_common.session.get("company_code"))

    return [
        checklist_to_dict(checklist)
        for checklist in query.all()
    ]



def checklist_result_to_dict(result):
    return {
        "id": result.id,
        "index": result.id,
        "company_code": result.company_code,
        "checklist_id": result.checklist_id,
        "target_type": result.target_type,
        "target_user": result.target_user,
        "target_username": result.target_username,
        "target_user_id": result.target_user_id,
        "target_identity": result.target_identity,
        "target_vehicle_record_id": result.target_vehicle_record_id,
        "target_office": result.target_office,
        "checked_by": result.checked_by,
        "checked_by_username": result.checked_by_username,
        "checked_by_user_id": result.checked_by_user_id,
        "checked_by_identity": result.checked_by_identity,
        "checked_date": result.checked_date,
        "status": result.status,
        "approved_by": result.approved_by,
        "approved_by_username": result.approved_by_username,
        "approved_by_user_id": result.approved_by_user_id,
        "approved_by_identity": result.approved_by_identity,
        "approved_date": result.approved_date,
        "reject_reason": result.reject_reason,
        "approvals": _dkss_serialization.safe_json_dict_list(result.approvals_json),
        "notify_users": _dkss_serialization.safe_json_str_list(
            result.notify_users_json
        ),
        "answers": _dkss_serialization.safe_json_dict_list(result.answers_json),
        "checklist_snapshot": (
            _dkss_serialization.safe_json_dict(result.checklist_snapshot_json)
            if result.checklist_snapshot_json
            else {}
        ),
    }



def vehicle_checklist_result_to_dict(result):
    return {
        "id": result.id,
        "index": result.id,
        "company_code": result.company_code,
        "checklist_id": result.checklist_id,
        "vehicle_record_id": result.vehicle_record_id,
        "operation_judgment": _dkss_serialization.safe_json_dict(result.operation_judgment_json),
        "year": result.year,
        "month": result.month,
        "day": result.day,
        "checked_by": result.checked_by,
        "checked_by_username": result.checked_by_username,
        "checked_by_user_id": result.checked_by_user_id,
        "checked_by_identity": result.checked_by_identity,
        "checked_date": result.checked_date,
        "status": result.status,
        "approved_by": result.approved_by,
        "approved_by_username": result.approved_by_username,
        "approved_by_user_id": result.approved_by_user_id,
        "approved_by_identity": result.approved_by_identity,
        "approved_date": result.approved_date,
        "reject_reason": result.reject_reason,
        "approvals": _dkss_serialization.safe_json_dict_list(result.approvals_json),
        "notify_users": _dkss_serialization.safe_json_str_list(
            result.notify_users_json
        ),
        "answers": _dkss_serialization.safe_json_dict_list(result.answers_json),
        "checklist_snapshot": (
            _dkss_serialization.safe_json_dict(result.checklist_snapshot_json)
            if result.checklist_snapshot_json
            else {}
        ),
    }



def get_user_local_now(company_code, target_username):
    user = _dkss_models.User.query.filter_by(
        company_code=company_code,
        username=target_username
    ).first()

    timezone_name = (
        user.timezone
        if user and user.timezone
        else "Asia/Tokyo"
    )

    try:
        return _dkss_common.datetime.now(
            _dkss_common.ZoneInfo(timezone_name)
        )
    except Exception:
        return _dkss_common.datetime.now(
            _dkss_common.ZoneInfo("Asia/Tokyo")
        )



def is_vehicle_checklist_completed_on_date(
    company_code,
    checklist_id,
    vehicle_record_id,
    target_date
):
    result = _dkss_models.VehicleChecklistResult.query.filter_by(
        company_code=company_code,
        checklist_id=checklist_id,
        vehicle_record_id=vehicle_record_id,
        year=str(target_date.year),
        month=str(target_date.month).zfill(2),
        day=str(target_date.day).zfill(2)
    ).first()

    return result is not None



def patrol_result_to_dict(result):
    return {
        "id": result.id,
        "index": result.id,
        "company_code": result.company_code,
        "created_by_username": result.created_by_username,
        "created_by_user_id": result.created_by_user_id,
        "created_by_identity": result.created_by_identity,
        "created_by_name": result.created_by_name,
        "date": result.date,
        "office": result.office,
        "delivery_place": result.delivery_place,
        "category": result.category,
        "content_type": result.content_type,
        "target_type": result.target_type,
        "target_user": result.target_user,
        "target_username": result.target_username,
        "target_user_id": result.target_user_id,
        "target_identity": result.target_identity,
        "content": result.content,
        "files": _dkss_serialization.safe_json_str_list(
            result.files_json
        ),
        "countermeasure": result.countermeasure,
        "countermeasure_files": _dkss_serialization.safe_json_str_list(
            result.countermeasure_files_json
        ),
        "countermeasure_by": result.countermeasure_by,
        "countermeasure_by_user_id": result.countermeasure_by_user_id,
        "countermeasure_by_identity": result.countermeasure_by_identity,
        "countermeasure_by_username": (
            result.countermeasure_by_username
        ),
        "countermeasure_due_date": (
            result.countermeasure_due_date
        ),
        "approval_status": result.approval_status,
        "reject_reason": result.reject_reason,
    }
