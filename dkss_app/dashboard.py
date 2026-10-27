"""Dashboard responsibilities; routes are registered by the application factory."""
from .dashboard_scope import DashboardScope
from .dashboard_repository import DashboardRepository
from .dashboard_service import DashboardService
from . import analysis_feedback as _dkss_analysis_feedback, audit as _dkss_audit, checklist_common as _dkss_checklist_common, common as _dkss_common, master_readers as _dkss_master_readers, models as _dkss_models, notifications as _dkss_notifications, runtime as _dkss_runtime, safety_permissions as _dkss_safety_permissions, serialization as _dkss_serialization, vehicle_readers as _dkss_vehicle_readers


def save_dashboard_settings():
    current_user = _dkss_models.User.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        username=_dkss_common.session.get("username")
    ).first()

    if not current_user:
        _dkss_common.session.clear()
        return _dkss_common.redirect("/login")

    office = _dkss_common.request.form.get("office", "").strip()
    period = _dkss_common.request.form.get("period", "30d").strip()

    if office:
        valid_office = _dkss_models.Office.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            name=office
        ).first()

        if not valid_office:
            office = ""

    if period not in ["7d", "30d", "90d", "365d"]:
        period = "30d"

    settings = _dkss_serialization.safe_json_dict(
        current_user.dashboard_settings_json
    )
    settings["office"] = office
    settings["period"] = period
    settings["show_summary"] = (
        _dkss_common.request.form.get("show_summary") == "1"
    )

    settings["show_vehicles"] = (
        _dkss_common.request.form.get("show_vehicles") == "1"
    )

    settings["show_my_checklists"] = (
        _dkss_common.request.form.get("show_my_checklists") == "1"
    )

    settings["show_analysis"] = (
        _dkss_common.request.form.get("show_analysis") == "1"
    )

    settings["show_ranking"] = (
        _dkss_common.request.form.get("show_ranking") == "1"
    )

    settings["show_inspection"] = (
        _dkss_common.request.form.get("show_inspection") == "1"
    )

    settings["show_pending"] = (
        _dkss_common.request.form.get("show_pending") == "1"
    )

    current_user.dashboard_settings_json = _dkss_common.json.dumps(
        settings,
        ensure_ascii=False
    )

    _dkss_common.db.session.commit()

    if _dkss_common.request.form.get("return_view") == "analysis":
        checklist_id = _dkss_common.request.form.get("return_checklist", "").strip()
        destination = "/#dashboard-view=analysis"
        if checklist_id.isascii() and checklist_id.isdigit() and len(checklist_id) <= 10:
            destination += "&checklist=" + checklist_id
        return _dkss_common.redirect(destination)

    return _dkss_common.redirect("/")



def get_dashboard_office_maintenance_trend(company_code, office):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from sqlalchemy.orm import load_only
    from .maintenance_facts import MaintenanceCostService

    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    rows = []
    if company_code and office:
        start = (
            MaintenanceCostService.office_months([], office, today)["months"][0]["key"]
            + "-01"
        )
        model = _dkss_models.VehicleMaintenanceRecord
        func = _dkss_common.db.func
        recorded_date = func.coalesce(
            func.nullif(func.trim(model.entry_date), ""),
            func.trim(model.completion_date),
        )
        recorded_date = func.substr(func.replace(recorded_date, "/", "-"), 1, 10)
        rows = (
            model.query.options(
                load_only(
                    model.id,
                    model.company_code,
                    model.vehicle_record_id,
                    model.entry_date,
                    model.completion_date,
                    model.total_cost,
                    model.notes,
                    model.invoice_details_json,
                )
            )
            .filter_by(company_code=company_code)
            .filter(recorded_date.between(start, today.isoformat()))
            .all()
        )
    result = MaintenanceCostService.office_months(rows, office, today)
    months = result["months"]

    known = [float(item["amount"]) for item in months if item["known"]]
    result["available"] = bool(known)
    low = min([0] + known)
    high = max([1] + known)

    for i, item in enumerate(months):
        item["x"] = round(45 + i * 82, 2)
        item["y"] = (
            round(84 - (float(item["amount"]) - low) / (high - low) * 65, 2)
            if item["known"]
            else None
        )
        item["formatted"] = f"{item['amount']:,.0f}"

    result["maximum"] = f"{high / 10000:,.1f}"
    result["minimum"] = f"{low / 10000:,.1f}"
    return result


def get_dashboard_vehicle_attention(company_code, office, my_vehicle_ids):
    groups = {
        key: {
            "items": [], "vehicles": 0, "missing": 0,
            "updating": 0, "errors": 0, "insufficient": 0,
        }
        for key in ("mine", "office")
    }
    own_ids = set(my_vehicle_ids)
    scope = _dkss_models.Vehicle.id.in_(own_ids)
    if office:
        scope = _dkss_common.db.or_(scope, _dkss_models.Vehicle.office == office)

    rows = (
        _dkss_common.db.session.query(_dkss_models.Vehicle, _dkss_models.VehicleKarteAnalysis)
        .outerjoin(_dkss_models.VehicleKarteAnalysis, _dkss_common.db.and_(
            _dkss_models.VehicleKarteAnalysis.vehicle_record_id == _dkss_models.Vehicle.id,
            _dkss_models.VehicleKarteAnalysis.company_code == company_code,
        ))
        .filter(
            _dkss_models.Vehicle.company_code == company_code,
            _dkss_models.Vehicle.deleted == False,
            scope,
        )
        .all()
    )

    for vehicle, state in rows:
        group = groups["mine" if vehicle.id in own_ids else "office"]
        group["vehicles"] += 1
        bundle = _dkss_serialization.safe_json_dict(state.result_json) if state else {}
        analysis = bundle.get("analysis")
        recommendations = (
            analysis.get("recommendations")
            if isinstance(analysis, dict) else None
        )

        if not isinstance(recommendations, list):
            group["missing"] += 1
            recommendations = []
        if state and state.status in ("pending", "running"):
            group["updating"] += 1
        if state and state.status == "error":
            group["errors"] += 1
        if bundle.get("analysis_method") == "record_check":
            group["insufficient"] += 1

        feedback_by_key = {
            row.proposal_key: row
            for row in _dkss_analysis_feedback.latest_vehicle_analysis_feedback(company_code, vehicle.id)
        }
        for item in recommendations:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            proposal_key, proposal_revision = _dkss_analysis_feedback.vehicle_analysis_proposal_ids(item)
            feedback = feedback_by_key.get(proposal_key)
            if (
                feedback and feedback.status in {"completed", "dismissed"}
                and feedback.proposal_revision == proposal_revision
            ):
                continue
            group["items"].append({
                "vehicle_id": vehicle.id,
                "vehicle_number": _dkss_vehicle_readers.vehicle_number({
                    field: getattr(vehicle, field) or ""
                    for field in (
                        "plate_area", "plate_class",
                        "plate_kana", "plate_number",
                    )
                }),
                "priority": item.get("priority", ""),
                "title": item["title"],
                "category": item.get("category", ""),
                "target": item.get("target", ""),
                "feedback_status": feedback.status if feedback else "open",
                "proposal_id": proposal_key,
                "current_state": item.get("current_state", ""),
                "timing": item.get("timing", ""),
                "action": item.get("action", ""),
                "reason": item.get("reason", ""),
                "generated_at": bundle.get("generated_at", ""),
                "url": _dkss_common.url_for(
                    "vehicle_karte_analysis",
                    vehicle_record_id=vehicle.id,
                ),
            })

    for group in groups.values():
        group["items"].sort(key=lambda item: (
            {"整備・点検": 0, "記録確認": 1}.get(item["category"], 2),
            {"高": 0, "中": 1, "低": 2}.get(item["priority"], 3),
            item["vehicle_id"],
            item["title"],
        ))
    return groups



def dashboard():
    today = _dkss_common.datetime.now().date()
    company_code = _dkss_common.session.get("company_code")
    _dkss_audit.update_company_usage_summary(company_code)
    _dkss_common.db.session.commit()
    user = DashboardRepository.current_user(company_code, _dkss_common.session.get("username"))
    scope = DashboardScope.for_user(user, company_code=company_code,
        username=_dkss_common.session.get("username"), role=_dkss_common.session.get("role"),
        user_name=_dkss_common.session.get("name"), today=today)
    service = DashboardService(scope, DashboardRepository(scope),
        checklist_to_dict=_dkss_checklist_common.checklist_to_dict,
        patrol_to_dict=_dkss_checklist_common.patrol_result_to_dict,
        history=get_dashboard_checklist_history, url_for=_dkss_common.url_for)
    context, trend_groups = service.build()
    context.update(
        dashboard_request_counts=get_dashboard_request_counts(),
        dashboard_periodic_schedule=get_dashboard_periodic_schedule(company_code, scope.office, scope.today),
        dashboard_office_check_trend=get_dashboard_office_check_trend(
            trend_groups, service.scoring.score_value, scope.start_date, scope.today.strftime("%Y-%m-%d")),
        dashboard_office_trend=get_dashboard_office_maintenance_trend(company_code, scope.office),
        dashboard_vehicle_attention=get_dashboard_vehicle_attention(
            company_code, scope.office, [vehicle.id for vehicle in context["my_vehicles"]]),
        dashboard_offices=_dkss_master_readers.offices_for_current_company(),
    )
    return _dkss_common.render_template("index.html", **context)



def get_dashboard_office_check_trend(groups, score_value, start_date, end_date):
    categories = {}
    issues = {}
    answer_count = 0
    record_count = 0

    for checklist_record, checklist, records in groups:
        for record in records:
            checked_date = str(record.checked_date or "")[:10]
            if not start_date <= checked_date <= end_date:
                continue

            snapshot = _dkss_serialization.safe_json_dict(record.checklist_snapshot_json) or checklist
            items = [
                item for item in snapshot.get("items", [])
                if isinstance(item, dict) and item.get("item_type") == "check"
            ]
            answers = _dkss_serialization.safe_json_dict_list(record.answers_json)
            counted_record = False

            for item, answer in zip(items, answers):
                if item.get("input_type") != "select":
                    continue

                choices = [
                    score_value(str(value) if value is not None else "")
                    for value in item.get("choices", [])
                ]
                choices = [value for value in choices if value is not None]
                score = score_value(
                    str(answer.get("value"))
                    if answer.get("value") is not None else ""
                )

                if not choices or score is None or max(choices) <= 0:
                    continue

                answer_count += 1
                counted_record = True

                if score >= max(choices):
                    continue

                category = str(item.get("category") or "その他").strip() or "その他"
                content = str(item.get("content") or "項目名なし").strip() or "項目名なし"
                categories[category] = categories.get(category, 0) + 1
                key = (category, content)

                if key not in issues:
                    if checklist_record.target == "車両管理":
                        if checklist.get("frequency_unit") == "year":
                            active_day = record.year
                        elif checklist.get("display_type") == "month":
                            active_day = record.day
                        else:
                            active_day = record.month

                        result_url = _dkss_common.url_for(
                            "vehicle_checklist_results",
                            index=checklist_record.id,
                            vehicle_record_id=record.vehicle_record_id,
                            year=record.year,
                            month=record.month,
                            active_day=active_day,
                        )
                    elif _dkss_safety_permissions.can_view_checklist_result(_dkss_checklist_common.checklist_result_to_dict(record)):
                        result_url = _dkss_common.url_for(
                            "checklist_result_detail",
                            result_index=record.id,
                        )
                    else:
                        result_url = ""

                    issues[key] = {
                        "category": category,
                        "content": content,
                        "count": 0,
                        "url": result_url,
                    }

                issues[key]["count"] += 1

            record_count += int(counted_record)

    ordered_categories = sorted(
        categories.items(),
        key=lambda item: (-item[1], item[0]),
    )
    ordered_issues = sorted(
        issues.values(),
        key=lambda item: (-item["count"], item["category"], item["content"]),
    )
    maximum = ordered_categories[0][1] if ordered_categories else 1

    return {
        "record_count": record_count,
        "answer_count": answer_count,
        "categories": [
            {"name": name, "count": count, "maximum": maximum}
            for name, count in ordered_categories[:3]
        ],
        "focus": ordered_issues[0] if ordered_issues else None,
    }



def get_dashboard_periodic_schedule(company_code, office, today):
    result = {
        "available": bool(company_code and office),
        "scheduled": [],
        "unregistered": [],
        "known_count": 0,
        "total_count": 0,
    }
    if not result["available"]:
        return result

    def parse_date(value):
        try:
            return _dkss_common.datetime.strptime(
                str(value or "")[:10].replace("/", "-"),
                "%Y-%m-%d",
            ).date()
        except ValueError:
            return None

    vehicles = _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.company_code == company_code,
        _dkss_models.Vehicle.office == office,
        _dkss_models.Vehicle.deleted.is_(False),
    ).all()
    result["total_count"] = len(vehicles)

    if not vehicles:
        return result

    for vehicle in vehicles:
        item = {
            "vehicle_record_id": vehicle.id,
            "number": "".join(str(value or "") for value in (
                vehicle.plate_area,
                vehicle.plate_class,
                vehicle.plate_kana,
                vehicle.plate_number,
            )) or "ナンバー未登録",
            "url": _dkss_common.url_for(
                "vehicle_karte_inspections",
                vehicle_record_id=vehicle.id,
            ),
        }
        plan = _dkss_runtime.app.extensions["dkss"]['inspection_plans'].summary(company_code, vehicle.id).get("3month")
        if not plan:
            result["unregistered"].append(item)
            continue
        result["known_count"] += 1
        reservation = parse_date(plan.get("reservation_date"))
        planned_month = plan["planned_month"]
        month_only = reservation is None
        due = reservation or parse_date(planned_month + "-01")
        if due <= today + _dkss_common.timedelta(days=90):
            item["date"] = reservation.isoformat() if reservation else planned_month + "（月予定）"
            item["remaining_days"] = None if month_only else (due - today).days
            item["month_only"] = month_only
            item["month_status"] = "予定月経過" if planned_month < today.isoformat()[:7] else "予約日未定"
            result["scheduled"].append(item)

    result["scheduled"].sort(
        key=lambda item: (item["date"], item["number"])
    )
    result["unregistered"].sort(
        key=lambda item: item["number"]
    )
    return result



def get_dashboard_checklist_history(checklist_record, checklist, records, score_value):
    company_code = _dkss_common.session.get("company_code")
    if not company_code or checklist_record.company_code != company_code:
        return {"total": 0, "rows": []}

    is_vehicle = checklist_record.target == "車両管理"
    allowed = []

    for record in records:
        if record.company_code != company_code or record.checklist_id != checklist_record.id:
            continue

        if not is_vehicle and not _dkss_safety_permissions.can_view_checklist_result(_dkss_checklist_common.checklist_result_to_dict(record)):
            continue

        allowed.append(record)

    allowed.sort(
        key=lambda record: (str(record.checked_date or ""), record.id),
        reverse=True,
    )
    selected = allowed[:50]

    vehicle_ids = {
        record.vehicle_record_id if is_vehicle else record.target_vehicle_record_id
        for record in selected
        if is_vehicle or record.target_type == "vehicle"
    }
    vehicles = {
        vehicle.id: vehicle
        for vehicle in _dkss_models.Vehicle.query.filter(
            _dkss_models.Vehicle.company_code == company_code,
            _dkss_models.Vehicle.id.in_(list(vehicle_ids)),
        ).all()
    } if vehicle_ids else {}

    rows = []

    for record in selected:
        snapshot = _dkss_serialization.safe_json_dict(record.checklist_snapshot_json) or checklist
        items = [
            item for item in snapshot.get("items", [])
            if isinstance(item, dict) and item.get("item_type") == "check"
        ]
        score = 0
        maximum = 0

        for item, answer in zip(items, _dkss_serialization.safe_json_dict_list(record.answers_json)):
            if item.get("input_type") != "select":
                continue

            choices = [
                score_value(value)
                for value in item.get("choices", [])
            ]
            choices = [value for value in choices if value is not None]
            value = score_value(answer.get("value"))

            if choices and value is not None and max(choices) > 0:
                score += value
                maximum += max(choices)

        if is_vehicle or record.target_type == "vehicle":
            vehicle_id = (
                record.vehicle_record_id
                if is_vehicle else record.target_vehicle_record_id
            )
            vehicle = vehicles.get(vehicle_id)
            label = "".join(str(value or "") for value in (
                vehicle.plate_area,
                vehicle.plate_class,
                vehicle.plate_kana,
                vehicle.plate_number,
            )) if vehicle else ""
            label = label or "ナンバー未登録"

        elif record.target_type == "user":
            label = record.target_user or "個人対象"
            if (
                _dkss_common.session.get("role") not in ["admin", "itc"]
                and record.target_username != _dkss_common.session.get("username")
            ):
                label = "個人対象"

        else:
            label = record.target_office or "営業所未設定"

        if is_vehicle:
            active_day = (
                record.year if checklist.get("frequency_unit") == "year"
                else record.day if checklist.get("display_type") == "month"
                else record.month
            )
            result_url = _dkss_common.url_for(
                "vehicle_checklist_results",
                index=checklist_record.id,
                vehicle_record_id=record.vehicle_record_id,
                year=record.year,
                month=record.month,
                active_day=active_day,
            )
        else:
            result_url = _dkss_common.url_for(
                "checklist_result_detail",
                result_index=record.id,
            )

        rows.append({
            "date": str(record.checked_date or "")[:10] or "—",
            "target": label,
            "score": round(score / maximum * 100, 1) if maximum > 0 else None,
            "status": record.status or "未登録",
            "url": result_url,
        })

    return {"total": len(allowed), "rows": rows}



def get_dashboard_request_counts():
    counts = {"vehicle_approvals": 0, "vehicle_response": 0}
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return counts

    type_groups = {
        "vehicle_approvals": {"approval_request", "resubmitted"},
        "vehicle_response": {
            "operation_request", "operation_result", "confirmation_request",
            "defect", "recheck",
        },
    }
    records = _dkss_models.Notification.query.filter(
        _dkss_models.Notification.company_code == company_code,
        _dkss_models.Notification.target_username == username,
        _dkss_models.Notification.deleted_at.is_(None),
    ).all()

    for notification in records:
        info = _dkss_notifications.get_notification_display_info(notification)
        if info["category"] != "vehicle":
            continue
        group = next((
            key for key, types in type_groups.items()
            if info["notification_type"] in types
        ), None)
        if group is None:
            continue
        if _dkss_notifications.get_notification_workflow_state(notification)["requires_action"]:
            counts[group] += 1

    return counts
