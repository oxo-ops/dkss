"""Dashboard responsibilities; routes are registered by the application factory."""
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
    from decimal import Decimal, InvalidOperation
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo('Asia/Tokyo')).date()
    months = []
    for offset in range(6, -1, -1):
        serial = today.year * 12 + today.month - 1 - offset
        year, month = divmod(serial, 12)
        months.append({
            'key': f'{year:04d}-{month+1:02d}',
            'label': f'{month+1}月',
            'amount': Decimal('0'),
            'known': 0,
            'missing': 0,
        })

    result = {'months': months, 'available': False}
    if not company_code or not office:
        return result

    buckets = {item['key']: item for item in months}
    rows = _dkss_models.VehicleMaintenanceRecord.query.join(
        _dkss_models.Vehicle,
        _dkss_models.VehicleMaintenanceRecord.vehicle_record_id == _dkss_models.Vehicle.id,
    ).filter(
        _dkss_models.VehicleMaintenanceRecord.company_code == company_code,
        _dkss_models.Vehicle.company_code == company_code,
        _dkss_models.Vehicle.office == office,
        _dkss_models.Vehicle.deleted.is_(False),
    ).with_entities(
        _dkss_models.VehicleMaintenanceRecord.entry_date,
        _dkss_models.VehicleMaintenanceRecord.completion_date,
        _dkss_models.VehicleMaintenanceRecord.total_cost,
    ).all()

    for entry, completion, cost in rows:
        try:
            date = datetime.strptime(
                str(entry or completion or '')[:10].replace('/', '-'),
                '%Y-%m-%d',
            ).date()
        except ValueError:
            continue

        if date > today or date.strftime('%Y-%m') not in buckets:
            continue

        bucket = buckets[date.strftime('%Y-%m')]
        try:
            value = Decimal(str(cost))
            if not value.is_finite():
                raise InvalidOperation()
        except (ValueError, InvalidOperation):
            bucket['missing'] += 1
            continue

        bucket['amount'] += value
        bucket['known'] += 1

    known = [float(item['amount']) for item in months if item['known']]
    result['available'] = bool(known)
    low = min([0] + known)
    high = max([1] + known)

    for i, item in enumerate(months):
        item['x'] = round(45 + i * 82, 2)
        item['y'] = (
            round(84 - (float(item['amount']) - low) / (high - low) * 65, 2)
            if item['known'] else None
        )
        item['formatted'] = f"{item['amount']:,.0f}"

    result['maximum'] = f'{high / 10000:,.1f}'
    result['minimum'] = f'{low / 10000:,.1f}'
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
    user_name = _dkss_common.session.get("name")

    company_code = _dkss_common.session.get("company_code")

    _dkss_audit.update_company_usage_summary(company_code)
    _dkss_common.db.session.commit()

    current_user = _dkss_models.User.query.filter_by(
        company_code=company_code,
        username=_dkss_common.session.get("username")
    ).first()

    dashboard_settings = {
        "office": "",
        "period": "30d",
        "show_summary": True,
        "show_vehicles": True,
        "show_my_checklists": True,
        "show_analysis": True,
        "show_ranking": True,
        "show_inspection": True,
        "show_pending": True,
    }

    if current_user:
        saved_dashboard_settings = _dkss_serialization.safe_json_dict(
            current_user.dashboard_settings_json
        )
        dashboard_settings.update(saved_dashboard_settings)

    dashboard_scope_office = (
        str(current_user.office or "").strip()
        if current_user else ""
    )
    dashboard_scope_missing = not bool(dashboard_scope_office)
    dashboard_settings["office"] = dashboard_scope_office

    period_days = {
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "365d": 365,
    }.get(
        dashboard_settings.get("period"),
        30
    )

    dashboard_start_date = (
        today - _dkss_common.timedelta(days=period_days - 1)
    ).strftime("%Y-%m-%d")
    dashboard_end_exclusive = (
        today + _dkss_common.timedelta(days=1)
    ).strftime("%Y-%m-%d")

    # 自分の無事故無違反日数
    my_driver = _dkss_models.Driver.query.filter_by(
        company_code=company_code,
        employee_id=_dkss_common.session.get("username")
    ).first()

    my_safe_days = None

    my_vehicle_record_ids = []

    if my_driver:
        my_vehicle_record_ids = [
            int(vehicle_record_id)
            for vehicle_record_id in _dkss_serialization.safe_json_str_list(
                my_driver.vehicles_json
            )
            if vehicle_record_id.isdigit()
        ]

    if my_driver and my_driver.safe_start_date:
        try:
            start_date = _dkss_common.datetime.strptime(
                my_driver.safe_start_date,
                "%Y-%m-%d"
            ).date()

            my_safe_days = max(0, (today - start_date).days)
        except ValueError:
            my_safe_days = None

    # 社内ランキング
    ranking_query = _dkss_models.Driver.query.filter(
        _dkss_models.Driver.company_code == company_code,
        _dkss_models.Driver.safe_start_date.isnot(None),
        _dkss_models.Driver.safe_start_date != ""
    )

    if dashboard_scope_missing:
        ranking_query = ranking_query.filter(_dkss_common.db.false())
    elif dashboard_settings.get("office"):
        ranking_query = ranking_query.filter(
            _dkss_models.Driver.office == dashboard_settings["office"]
        )

    ranking_records = (
        ranking_query
        .order_by(_dkss_models.Driver.safe_start_date.asc())
        .limit(10)
        .all()
    )

    ranking = []

    for driver in ranking_records:
        try:
            start_date = _dkss_common.datetime.strptime(
                driver.safe_start_date,
                "%Y-%m-%d"
            ).date()
        except ValueError:
            continue

        ranking.append({
            "id": driver.id,
            "index": driver.id,
            "employee_id": driver.employee_id,
            "name": driver.name,
            "role": driver.role,
            "office": driver.office,
            "safe_start_date": driver.safe_start_date,
            "safe_days": (today - start_date).days,
        })

    # 自分のGood件数
    my_good_count = _dkss_models.PatrolResult.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        target_type="user",
        target_username=_dkss_common.session.get("username"),
        category="Good"
    ).count()

    # 自分に対する未対応指摘
    my_pending_pointouts = []

    pending_records = _dkss_models.PatrolResult.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        target_type="user",
        target_username=_dkss_common.session.get("username")
    ).filter(
        _dkss_models.PatrolResult.category != "Good",
        _dkss_models.PatrolResult.approval_status != "承認済み"
    ).order_by(
        _dkss_models.PatrolResult.id.desc()
    ).all()

    for record in pending_records:
        my_pending_pointouts.append(
            _dkss_checklist_common.patrol_result_to_dict(record)
        )

    # 車検が近い車両
    inspection_alerts = []

    inspection_limit_date = (
        today + _dkss_common.timedelta(days=90)
    ).strftime("%Y-%m-%d")


    inspection_vehicle_query = _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.company_code == company_code,
        _dkss_models.Vehicle.deleted == False,
        _dkss_models.Vehicle.inspection_expiry.isnot(None),
        _dkss_models.Vehicle.inspection_expiry != "",
        _dkss_models.Vehicle.inspection_expiry <= inspection_limit_date
    )

    if dashboard_scope_missing:
        inspection_vehicle_query = inspection_vehicle_query.filter(_dkss_common.db.false())
    elif dashboard_settings.get("office"):
        inspection_vehicle_query = inspection_vehicle_query.filter(
            _dkss_models.Vehicle.office == dashboard_settings["office"]
        )

    inspection_vehicle_records = (
        inspection_vehicle_query
        .order_by(_dkss_models.Vehicle.inspection_expiry.asc())
        .all()
    )


    for vehicle in inspection_vehicle_records:

        try:
            expiry_date = _dkss_common.datetime.strptime(
                vehicle.inspection_expiry,
                "%Y-%m-%d"
            ).date()
        except ValueError:
            continue


        remaining_days = (
            expiry_date - today
        ).days


        item = {
            "vehicle_record_id": vehicle.id,
            "chassis_number": vehicle.chassis_number,
            "number": " ".join(
                value
                for value in [
                    vehicle.plate_area or "",
                    vehicle.plate_class or "",
                    vehicle.plate_kana or "",
                    vehicle.plate_number or "",
                ]
                if value
            ),
            "type": vehicle.type or "",
            "body_type": vehicle.body_type or "",
            "inspection_expiry": vehicle.inspection_expiry,
            "remaining_days": remaining_days,
        }

        inspection_alerts.append(item)

    setup_tasks = []

    if _dkss_common.session.get("role") == "admin":
        company_code = _dkss_common.session.get("company_code")

        if _dkss_models.Office.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "営業所マスタ",
                "description": "営業所を登録してください。",
                "url": "/master/offices"
            })

        if _dkss_models.VehicleType.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "車種マスタ",
                "description": "車両登録で使用する車種を登録してください。",
                "url": "/master/vehicle-types"
            })

        if _dkss_models.LicenseType.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "免許種別マスタ",
                "description": "ドライバー登録で使用する免許種別を登録してください。",
                "url": "/master/license-types"
            })

        if _dkss_models.DeliveryPlace.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "納入先マスタ",
                "description": "安全パトロールで使用する納入先を登録してください。",
                "url": "/master/delivery-places"
            })

        if _dkss_models.Vehicle.query.filter_by(
            company_code=company_code,
            deleted=False
        ).count() == 0:
            setup_tasks.append({
                "name": "車両マスタ",
                "description": "車両管理・点検で使用する車両を登録してください。",
                "url": "/master/vehicles"
            })

        if _dkss_models.Checklist.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "チェックリストマスタ",
                "description": "安全管理・車両管理で使用するチェックリストを登録してください。",
                "url": "/master/checklists"
            })

    def dashboard_score_value(value):
        text = str(value if value is not None else "").strip()

        symbol_scores = {
            # 良好
            "○": 2.0,
            "〇": 2.0,
            "✓": 2.0,
            "✔": 2.0,
            "☑": 2.0,

            # 注意
            "△": 1.0,
            "▲": 1.0,

            # 不良
            "×": 0.0,
            "✕": 0.0,
            "✖": 0.0,
            "✗": 0.0,
            "✘": 0.0,
            "X": 0.0,
            "x": 0.0,
        }

        if text in symbol_scores:
            return symbol_scores[text]

        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    checklist_score_summaries = []
    my_checklist_summaries = []
    office_check_trend_groups = []

    score_checklists = _dkss_master_readers.ordered_master_query(_dkss_models.Checklist, company_code).filter(
        _dkss_models.Checklist.active.is_(True),
        _dkss_models.Checklist.target.in_(["安全管理", "車両管理"])
    ).all()

    for checklist_record in score_checklists:
        checklist = _dkss_checklist_common.checklist_to_dict(checklist_record)

        has_dashboard_score = checklist.get("score_enabled") or any(
            dashboard_score_value(choice) is not None
            for item in checklist.get("items", [])
            if item.get("item_type") == "check"
            and item.get("input_type") == "select"
            for choice in item.get("choices", [])
        )

        is_vehicle_checklist = (
            checklist_record.target == "車両管理"
        )

        if (
            not has_dashboard_score
            and not is_vehicle_checklist
        ):
            continue

        check_items = [
            item
            for item in checklist.get("items", [])
            if item.get("item_type") == "check"
        ]

        if is_vehicle_checklist:

            vehicle_result_query = _dkss_models.VehicleChecklistResult.query.filter_by(
                company_code=company_code,
                checklist_id=checklist_record.id
            ).filter(
                _dkss_models.VehicleChecklistResult.checked_date >= dashboard_start_date,
                _dkss_models.VehicleChecklistResult.checked_date < dashboard_end_exclusive
            )

            if dashboard_scope_missing:
                vehicle_result_query = vehicle_result_query.filter(
                    _dkss_common.db.false()
                )
            elif dashboard_settings.get("office"):
                office_vehicle_record_ids = [
                    vehicle.id
                    for vehicle in _dkss_models.Vehicle.query.filter_by(
                        company_code=company_code,
                        office=dashboard_settings["office"],
                        deleted=False
                    ).all()
                ]

                vehicle_result_query = vehicle_result_query.filter(
                    _dkss_models.VehicleChecklistResult.vehicle_record_id.in_(
                        office_vehicle_record_ids
                    )
                )

            result_records = vehicle_result_query.all()
            my_result_records = [
                result_record
                for result_record in result_records
                if result_record.vehicle_record_id in my_vehicle_record_ids
            ]

        else:

            safety_result_query = _dkss_models.ChecklistResult.query.filter_by(
                company_code=company_code,
                checklist_id=checklist_record.id
            ).filter(
                _dkss_models.ChecklistResult.checked_date >= dashboard_start_date,
                _dkss_models.ChecklistResult.checked_date < dashboard_end_exclusive
            )

            if dashboard_scope_missing:
                safety_result_query = safety_result_query.filter(_dkss_common.db.false())
            elif dashboard_settings.get("office"):
                safety_result_query = safety_result_query.filter(
                    _dkss_models.ChecklistResult.target_office == dashboard_settings["office"]
                )

            result_records = safety_result_query.all()

            # ログイン中ユーザー本人が対象の結果
            my_result_records = [
                result_record
                for result_record in result_records
                if (
                    result_record.target_type == "user"
                    and result_record.target_username
                    == _dkss_common.session.get("username")
                )
            ]

        office_check_trend_groups.append((checklist_record, checklist, result_records))

        max_score = 100

        result_scores = []

        for result_record in result_records:
            answers = _dkss_serialization.safe_json_dict_list(
                result_record.answers_json
            )

            result_check_items = check_items

            if (
                is_vehicle_checklist
                and result_record.checklist_snapshot_json
            ):
                result_snapshot = _dkss_serialization.safe_json_dict(
                    result_record.checklist_snapshot_json
                )

                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get(
                            "items",
                            []
                        )
                        if item.get("item_type") == "check"
                    ]

            total_score = 0
            total_max_score = 0

            for item, answer in zip(
                result_check_items,
                answers
            ):
                if item.get("input_type") != "select":
                    continue

                numeric_choices = [
                    dashboard_score_value(choice)
                    for choice in item.get("choices", [])
                ]

                numeric_choices = [
                    value
                    for value in numeric_choices
                    if value is not None
                ]

                if not numeric_choices:
                    continue

                score_value = dashboard_score_value(
                    answer.get("value")
                )

                if score_value is None:
                    continue

                total_score += score_value
                total_max_score += max(numeric_choices)

            if total_max_score > 0:
                result_scores.append(
                    round(
                        total_score / total_max_score * 100,
                        1
                    )
                )

        score_distribution = {}

        for score in result_scores:
            score_value = float(score)
            score_label = (
                int(score_value)
                if score_value.is_integer()
                else score_value
            )

            score_distribution[score_label] = (
                score_distribution.get(score_label, 0) + 1
            )

        average_score = (
            round(
                sum(result_scores) / len(result_scores),
                1
            )
            if result_scores
            else None
        )

        if is_vehicle_checklist:
            for usage_vehicle_id in my_vehicle_record_ids:
                vehicle_result_records = [
                    result_record
                    for result_record in my_result_records
                    if result_record.vehicle_record_id == usage_vehicle_id
                ]

                vehicle_result_scores = []
                vehicle_category_stats = {}

                for result_record in vehicle_result_records:
                    answers = _dkss_serialization.safe_json_dict_list(
                        result_record.answers_json
                    )

                    result_check_items = check_items

                    if result_record.checklist_snapshot_json:
                        result_snapshot = _dkss_serialization.safe_json_dict(
                            result_record.checklist_snapshot_json
                        )

                        if result_snapshot:
                            result_check_items = [
                                item
                                for item in result_snapshot.get(
                                    "items",
                                    []
                                )
                                if item.get("item_type") == "check"
                            ]

                    total_score = 0
                    total_max_score = 0

                    for item, answer in zip(
                        result_check_items,
                        answers
                    ):
                        if item.get("input_type") != "select":
                            continue

                        numeric_choices = [
                            dashboard_score_value(choice)
                            for choice in item.get(
                                "choices",
                                []
                            )
                        ]

                        numeric_choices = [
                            value
                            for value in numeric_choices
                            if value is not None
                        ]

                        if not numeric_choices:
                            continue

                        score_value = dashboard_score_value(
                            answer.get("value")
                        )

                        if score_value is None:
                            continue

                        item_max_score = max(
                            numeric_choices
                        )

                        total_score += score_value
                        total_max_score += item_max_score

                        category = (
                            item.get("category")
                            or "その他"
                        ).strip()

                        if category not in vehicle_category_stats:
                            vehicle_category_stats[category] = {
                                "score": 0,
                                "max_score": 0,
                            }

                        vehicle_category_stats[
                            category
                        ]["score"] += score_value

                        vehicle_category_stats[
                            category
                        ]["max_score"] += item_max_score

                    if total_max_score > 0:
                        vehicle_result_scores.append(
                            round(
                                total_score
                                / total_max_score
                                * 100,
                                1
                            )
                        )

                vehicle_average_score = (
                    round(
                        sum(vehicle_result_scores)
                        / len(vehicle_result_scores),
                        1
                    )
                    if vehicle_result_scores
                    else None
                )

                vehicle_category_analysis = []

                for (
                    category,
                    stats
                ) in vehicle_category_stats.items():
                    if stats["max_score"] <= 0:
                        continue

                    score_rate = round(
                        stats["score"]
                        / stats["max_score"]
                        * 100,
                        1
                    )

                    vehicle_category_analysis.append({
                        "category": category,
                        "score_rate": score_rate,
                        "improvement_rate": round(
                            100 - score_rate,
                            1
                        ),
                    })

                vehicle_category_analysis.sort(
                    key=lambda item: item["score_rate"]
                )

                vehicle_category_analysis = (
                    vehicle_category_analysis[:2]
                )

                average_difference = (
                    round(
                        vehicle_average_score
                        - average_score,
                        1
                    )
                    if (
                        vehicle_average_score is not None
                        and average_score is not None
                    )
                    else None
                )

                usage_vehicle = _dkss_models.Vehicle.query.filter_by(
                    company_code=company_code,
                    id=usage_vehicle_id,
                    deleted=False
                ).first()

                if not usage_vehicle:
                    continue

                my_checklist_summaries.append({
                    "id": checklist_record.id,
                    "name": checklist_record.name,
                    "target": checklist_record.target,
                    "is_standard_daily": (
                        checklist.get("fixed_template_code")
                        == "daily_inspection_truck_trailer"
                    ),
                    "is_daily": (
                        checklist.get("fixed_template_code")
                        == "daily_inspection_truck_trailer"
                        or (
                            checklist_record.frequency_unit == "day"
                            and str(checklist_record.frequency_value or "1") == "1"
                        )
                    ),
                    "vehicle_record_id": usage_vehicle_id,
                    "registration_number": " ".join(
                        value
                        for value in [
                            usage_vehicle.plate_area or "",
                            usage_vehicle.plate_class or "",
                            usage_vehicle.plate_kana or "",
                            usage_vehicle.plate_number or "",
                        ]
                        if value
                    ),
                    "chassis_number": (
                        usage_vehicle.chassis_number
                        if usage_vehicle
                        else ""
                    ),
                    "target_user": user_name,
                    "target_username": _dkss_common.session.get(
                        "username"
                    ),
                    "average_score": vehicle_average_score,
                    "overall_average_score": average_score,
                    "average_difference": average_difference,
                    "result_count": len(
                        vehicle_result_scores
                    ),
                    "max_score": max_score,
                    "category_analysis": (
                        vehicle_category_analysis
                    ),
                })

        else:
            my_result_scores = []

            for result_record in my_result_records:
                answers = _dkss_serialization.safe_json_dict_list(
                    result_record.answers_json
                )

                result_check_items = check_items

                total_score = 0
                total_max_score = 0

                for item, answer in zip(
                    result_check_items,
                    answers
                ):
                    if item.get("input_type") != "select":
                        continue

                    numeric_choices = [
                        dashboard_score_value(choice)
                        for choice in item.get(
                            "choices",
                            []
                        )
                    ]

                    numeric_choices = [
                        value
                        for value in numeric_choices
                        if value is not None
                    ]

                    if not numeric_choices:
                        continue

                    score_value = dashboard_score_value(
                        answer.get("value")
                    )

                    if score_value is None:
                        continue

                    total_score += score_value
                    total_max_score += max(
                        numeric_choices
                    )

                if total_max_score > 0:
                    my_result_scores.append(
                        round(
                            total_score
                            / total_max_score
                            * 100,
                            1
                        )
                    )

            my_average_score = (
                round(
                    sum(my_result_scores)
                    / len(my_result_scores),
                    1
                )
                if my_result_scores
                else None
            )

            my_category_stats = {}

            for result_record in my_result_records:
                answers = _dkss_serialization.safe_json_dict_list(
                    result_record.answers_json
                )

                for item, answer in zip(
                    check_items,
                    answers
                ):
                    if item.get("input_type") != "select":
                        continue

                    category = (
                        item.get("category")
                        or "その他"
                    ).strip()

                    numeric_choices = []

                    for choice in item.get(
                        "choices",
                        []
                    ):
                        score_value = (
                            dashboard_score_value(
                                choice
                            )
                        )

                        if score_value is not None:
                            numeric_choices.append(
                                score_value
                            )

                    if not numeric_choices:
                        continue

                    score = dashboard_score_value(
                        answer.get("value")
                    )

                    if score is None:
                        continue

                    item_max_score = max(
                        numeric_choices
                    )

                    if category not in my_category_stats:
                        my_category_stats[category] = {
                            "score": 0,
                            "max_score": 0,
                        }

                    my_category_stats[
                        category
                    ]["score"] += score

                    my_category_stats[
                        category
                    ]["max_score"] += item_max_score

            my_category_analysis = []

            for (
                category,
                stats
            ) in my_category_stats.items():
                if stats["max_score"] <= 0:
                    continue

                score_rate = round(
                    stats["score"]
                    / stats["max_score"]
                    * 100,
                    1
                )

                my_category_analysis.append({
                    "category": category,
                    "score_rate": score_rate,
                    "improvement_rate": round(
                        100 - score_rate,
                        1
                    ),
                })

            my_category_analysis.sort(
                key=lambda item: item["score_rate"]
            )

            my_category_analysis = (
                my_category_analysis[:2]
            )

            if my_average_score is not None:
                average_difference = (
                    round(
                        my_average_score
                        - average_score,
                        1
                    )
                    if average_score is not None
                    else None
                )

                my_checklist_summaries.append({
                    "id": checklist_record.id,
                    "name": checklist_record.name,
                    "target": checklist_record.target,
                    "target_user": user_name,
                    "target_username": _dkss_common.session.get(
                        "username"
                    ),
                    "average_score": my_average_score,
                    "overall_average_score": average_score,
                    "average_difference": average_difference,
                    "result_count": len(
                        my_result_scores
                    ),
                    "max_score": max_score,
                    "category_analysis": (
                        my_category_analysis
                    ),
                })

        # カテゴリ別の評価を集計
        category_stats = {}

        for result_record in result_records:
            answers = _dkss_serialization.safe_json_dict_list(
                result_record.answers_json
            )

            result_check_items = check_items

            if (
                is_vehicle_checklist
                and result_record.checklist_snapshot_json
            ):
                result_snapshot = _dkss_serialization.safe_json_dict(
                    result_record.checklist_snapshot_json
                )

                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get(
                            "items",
                            []
                        )
                        if item.get("item_type") == "check"
                    ]

            for item, answer in zip(
                result_check_items,
                answers
            ):
                if item.get("input_type") != "select":
                    continue

                category = (
                    item.get("category") or "その他"
                ).strip()

                numeric_choices = []

                for choice in item.get("choices", []):
                    score_value = dashboard_score_value(choice)

                    if score_value is not None:
                        numeric_choices.append(score_value)

                if not numeric_choices:
                    continue

                score = dashboard_score_value(
                    answer.get("value")
                )

                if score is None:
                    continue

                item_max_score = max(numeric_choices)

                if category not in category_stats:
                    category_stats[category] = {
                        "score": 0,
                        "max_score": 0,
                        "count": 0,
                    }

                category_stats[category]["score"] += score
                category_stats[category]["max_score"] += item_max_score
                category_stats[category]["count"] += 1

        category_analysis = []

        for category, stats in category_stats.items():
            if stats["max_score"] <= 0:
                continue

            score_rate = round(
                stats["score"] / stats["max_score"] * 100,
                1
            )

            category_analysis.append({
                "category": category,
                "score_rate": score_rate,
                "improvement_rate": round(
                    100 - score_rate,
                    1
                ),
                "count": stats["count"],
            })

        # 改善が必要な順
        category_analysis.sort(
            key=lambda item: item["score_rate"]
        )

        # 点検項目別の評価を集計
        item_stats = {}

        for result_record in result_records:
            answers = _dkss_serialization.safe_json_dict_list(
                result_record.answers_json
            )

            result_check_items = check_items

            if (
                is_vehicle_checklist
                and result_record.checklist_snapshot_json
            ):
                result_snapshot = _dkss_serialization.safe_json_dict(
                    result_record.checklist_snapshot_json
                )

                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get(
                            "items",
                            []
                        )
                        if item.get("item_type") == "check"
                    ]

            for item, answer in zip(
                result_check_items,
                answers
            ):
                if item.get("input_type") != "select":
                    continue

                content = (
                    item.get("content") or "項目名なし"
                ).strip()

                category = (
                    item.get("category") or "その他"
                ).strip()

                numeric_choices = []

                for choice in item.get("choices", []):
                    score_value = dashboard_score_value(choice)

                    if score_value is not None:
                        numeric_choices.append(score_value)

                if not numeric_choices:
                    continue

                score = dashboard_score_value(
                    answer.get("value")
                )

                if score is None:
                    continue

                item_max_score = max(numeric_choices)

                key = (category, content)

                if key not in item_stats:
                    item_stats[key] = {
                        "score": 0,
                        "max_score": 0,
                        "count": 0,
                        "result": result_record,
                        "lowest_score": score,
                    }

                item_stats[key]["score"] += score
                item_stats[key]["max_score"] += item_max_score
                item_stats[key]["count"] += 1

                if score < item_stats[key]["lowest_score"]:
                    item_stats[key]["lowest_score"] = score
                    item_stats[key]["result"] = result_record

        improvement_items = []

        for (category, content), stats in item_stats.items():
            if stats["max_score"] <= 0:
                continue

            score_rate = round(
                stats["score"] / stats["max_score"] * 100,
                1
            )

            result_record = stats.get("result")
            result_url = ""

            if result_record:
                if is_vehicle_checklist:
                    if checklist.get("frequency_unit") == "year":
                        active_day = result_record.year
                    elif checklist.get("display_type") == "month":
                        active_day = result_record.day
                    else:
                        active_day = result_record.month

                    result_url = _dkss_common.url_for(
                        "vehicle_checklist_results",
                        index=checklist_record.id,
                        vehicle_record_id=result_record.vehicle_record_id,
                        year=result_record.year,
                        month=result_record.month,
                        active_day=active_day,
                    )
                else:
                    result_url = _dkss_common.url_for(
                        "checklist_result_detail",
                        result_index=result_record.id,
                    )

            improvement_items.append({
                "category": category,
                "content": content,
                "score_rate": score_rate,
                "improvement_rate": round(
                    100 - score_rate,
                    1
                ),
                "count": stats["count"],
                "result_url": result_url,
            })

        improvement_items.sort(
            key=lambda item: item["improvement_rate"],
            reverse=True
        )

        improvement_items = improvement_items[:5]
        target_stats = {}

        for result_record in result_records:

            if is_vehicle_checklist:
                target_type = "vehicle"

                target_vehicle_record = _dkss_models.Vehicle.query.filter_by(
                    company_code=company_code,
                    id=result_record.vehicle_record_id
                ).first()

                if not target_vehicle_record:
                    continue

                target_label = " ".join(
                    value
                    for value in [
                        target_vehicle_record.plate_area or "",
                        target_vehicle_record.plate_class or "",
                        target_vehicle_record.plate_kana or "",
                        target_vehicle_record.plate_number or "",
                    ]
                    if value
                ) or "ナンバー未登録"

            else:
                target_type = result_record.target_type

                if target_type == "user":
                    # 個人名は管理者だけ集計対象にする
                    if _dkss_common.session.get("role") not in ["admin", "itc"]:
                        continue

                    target_label = result_record.target_user

                elif target_type == "vehicle":
                    target_vehicle_record = _dkss_models.Vehicle.query.filter_by(
                        company_code=company_code,
                        id=result_record.target_vehicle_record_id
                    ).first()

                    if not target_vehicle_record:
                        continue

                    target_label = " ".join(
                        value
                        for value in [
                            target_vehicle_record.plate_area or "",
                            target_vehicle_record.plate_class or "",
                            target_vehicle_record.plate_kana or "",
                            target_vehicle_record.plate_number or "",
                        ]
                        if value
                    ) or "ナンバー未登録"

                elif target_type == "office":
                    target_label = result_record.target_office

                else:
                    continue

            if not target_label:
                continue

            answers = _dkss_serialization.safe_json_dict_list(
                result_record.answers_json
            )

            result_check_items = check_items

            if (
                is_vehicle_checklist
                and result_record.checklist_snapshot_json
            ):
                result_snapshot = _dkss_serialization.safe_json_dict(
                    result_record.checklist_snapshot_json
                )

                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get(
                            "items",
                            []
                        )
                        if item.get("item_type") == "check"
                    ]

            target_score = 0
            target_max_score = 0
            target_review_items = {}

            for item, answer in zip(
                result_check_items,
                answers
            ):
                if item.get("input_type") != "select":
                    continue

                numeric_choices = []

                for choice in item.get("choices", []):
                    score_value = dashboard_score_value(choice)

                    if score_value is not None:
                        numeric_choices.append(score_value)

                if not numeric_choices:
                    continue

                score = dashboard_score_value(
                    answer.get("value")
                )

                if score is None:
                    continue

                target_score += score
                target_max_score += max(numeric_choices)
                if score < max(numeric_choices):
                    content = str(item.get("content") or "項目名なし").strip() or "項目名なし"
                    target_review_items[content] = target_review_items.get(content, 0) + 1

            if target_max_score <= 0:
                continue

            target_identity = (
                target_vehicle_record.id if target_type == "vehicle"
                else result_record.target_username if target_type == "user"
                else result_record.target_office
            )
            key = (target_type, target_identity, target_label)

            if key not in target_stats:
                target_stats[key] = {
                    "score": 0,
                    "max_score": 0,
                    "count": 0,
                    "vehicle_record_id": (
                        result_record.vehicle_record_id
                        if is_vehicle_checklist
                        else result_record.target_vehicle_record_id
                        if target_type == "vehicle"
                        else None
                    ),
                    "target_value": (
                        result_record.target_username
                        if target_type == "user"
                        else result_record.target_office
                        if target_type == "office"
                        else result_record.vehicle_record_id
                        if is_vehicle_checklist
                        else result_record.target_vehicle_record_id
                        if target_type == "vehicle"
                        else None
                    ),
                    "lowest_score_rate": None,
                    "score_sum": 0,
                    "review_items": {},
                    "year": "",
                    "month": "",
                    "day": "",
                }

            target_stats[key]["score"] += target_score
            target_stats[key]["max_score"] += target_max_score
            target_stats[key]["count"] += 1
            target_stats[key]["score_sum"] += target_score / target_max_score * 100

            for content, count in target_review_items.items():
                review = target_stats[key]["review_items"]
                review[content] = review.get(content, 0) + count

            current_score_rate = target_score / target_max_score

            if (
                target_stats[key]["lowest_score_rate"] is None
                or current_score_rate < target_stats[key]["lowest_score_rate"]
            ):
                target_stats[key]["lowest_score_rate"] = current_score_rate
                target_stats[key]["year"] = getattr(
                    result_record, "year", ""
                ) or ""
                target_stats[key]["month"] = getattr(
                    result_record, "month", ""
                ) or ""
                target_stats[key]["day"] = getattr(
                    result_record, "day", ""
                ) or ""


        target_analysis = []

        for (target_type, target_identity, target_label), stats in target_stats.items():
            if stats["max_score"] <= 0:
                continue

            score_rate = round(
                stats["score"] / stats["max_score"] * 100,
                1
            )

            target_analysis.append({
                "target_type": target_type,
                "target_label": target_label,
                "vehicle_record_id": stats.get("vehicle_record_id"),
                "target_value": stats.get("target_value"),
                "year": stats.get("year", ""),
                "month": stats.get("month", ""),
                "day": stats.get("day", ""),
                "score_rate": score_rate,
                "average_score": round(
                    stats["score_sum"] / stats["count"], 1
                ),
                "review_items": [
                    content for content, count in sorted(
                        stats["review_items"].items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ],
                "improvement_rate": round(
                    100 - score_rate,
                    1
                ),
                "count": stats["count"],
            })

        target_analysis.sort(
            key=lambda item: item["improvement_rate"],
            reverse=True
        )

        for target in target_analysis:

            target["vehicle_type"] = ""
            target["body_type"] = ""

            if target["target_type"] == "vehicle":

                target_vehicle = _dkss_models.Vehicle.query.filter_by(
                    company_code=company_code,
                    id=target.get("vehicle_record_id")
                ).first()

                if target_vehicle:
                    target["vehicle_record_id"] = target_vehicle.id
                    target["vehicle_type"] = target_vehicle.type or ""
                    target["body_type"] = target_vehicle.body_type or ""

        if not has_dashboard_score:
            continue

        checklist_score_summaries.append({
            "id": checklist_record.id,
            "name": checklist_record.name,
            "target": checklist_record.target,
            "frequency_unit": checklist_record.frequency_unit,
            "display_type": checklist_record.display_type,
            "average_score": average_score,
            "result_count": len(result_scores),
            "scores": result_scores,
            "max_score": max_score,
            "score_distribution": score_distribution,
            "category_analysis": category_analysis,
            "review_item_count": sum(
                1 for stats in item_stats.values()
                if stats["max_score"] > 0 and stats["score"] < stats["max_score"]
            ),
            "target_analysis": target_analysis,
            "history": get_dashboard_checklist_history(
                checklist_record,
                checklist,
                result_records,
                dashboard_score_value,
            ),
            "improvement_items": improvement_items,
        })

    my_vehicles = _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.company_code == company_code,
        _dkss_models.Vehicle.deleted == False,
        _dkss_models.Vehicle.id.in_(my_vehicle_record_ids)
    ).all() if my_vehicle_record_ids else []

    my_vehicle_analysis = {}

    for vehicle in my_vehicles:

        vehicle_result_rates = []
        vehicle_result_count = 0
        vehicle_latest_date = ""
        vehicle_category_stats = {}

        for checklist_record in score_checklists:

            if checklist_record.target != "車両管理":
                continue

            checklist = _dkss_checklist_common.checklist_to_dict(
                checklist_record
            )

            vehicle_results = (
                _dkss_models.VehicleChecklistResult.query.filter_by(
                    company_code=company_code,
                    checklist_id=checklist_record.id,
                    vehicle_record_id=vehicle.id
                )
                .filter(
                    _dkss_models.VehicleChecklistResult.checked_date >= dashboard_start_date,
                    _dkss_models.VehicleChecklistResult.checked_date < dashboard_end_exclusive
                )
                .all()
            )

            for result_record in vehicle_results:

                answers = _dkss_serialization.safe_json_dict_list(
                    result_record.answers_json
                )

                result_checklist = checklist

                if result_record.checklist_snapshot_json:
                    snapshot = _dkss_serialization.safe_json_dict(
                        result_record.checklist_snapshot_json
                    )

                    if snapshot:
                        result_checklist = snapshot

                check_items = [
                    item
                    for item in result_checklist.get("items", [])
                    if item.get("item_type") == "check"
                ]

                result_score = 0
                result_max_score = 0

                for item, answer in zip(
                    check_items,
                    answers
                ):

                    if item.get("input_type") != "select":
                        continue

                    numeric_choices = [
                        dashboard_score_value(choice)
                        for choice in item.get("choices", [])
                    ]

                    numeric_choices = [
                        value
                        for value in numeric_choices
                        if value is not None
                    ]

                    if not numeric_choices:
                        continue

                    score = dashboard_score_value(
                        answer.get("value")
                    )

                    if score is None:
                        continue

                    result_score += score
                    result_max_score += max(
                        numeric_choices
                    )
                    category = (
                        item.get("category")
                        or "その他"
                    )

                    if category not in vehicle_category_stats:
                        vehicle_category_stats[category] = {
                            "score": 0,
                            "max_score": 0,
                        }

                    vehicle_category_stats[category]["score"] += score
                    vehicle_category_stats[category]["max_score"] += max(
                        numeric_choices
                    )

                if result_max_score > 0:
                    vehicle_result_rates.append(
                        round(
                            result_score
                            / result_max_score
                            * 100,
                            1
                        )
                    )
                    vehicle_result_count += 1

                if (
                    result_record.checked_date
                    and result_record.checked_date
                    > vehicle_latest_date
                ):
                    vehicle_latest_date = (
                        result_record.checked_date
                    )

        score_rate = None

        if vehicle_result_rates:
            score_rate = round(
                sum(vehicle_result_rates)
                / len(vehicle_result_rates),
                1
            )

        vehicle_category_analysis = []

        for category, stats in vehicle_category_stats.items():

            if stats["max_score"] <= 0:
                continue

            category_score_rate = round(
                stats["score"]
                / stats["max_score"]
                * 100,
                1
            )

            vehicle_category_analysis.append({
                "category": category,
                "score_rate": category_score_rate,
                "improvement_rate": round(
                    100 - category_score_rate,
                    1
                ),
            })

        vehicle_category_analysis.sort(
            key=lambda item: item["improvement_rate"],
            reverse=True
        )

        vehicle_category_analysis = (
            vehicle_category_analysis[:2]
        )

        my_vehicle_analysis[
            vehicle.id
        ] = {
            "score_rate": score_rate,
            "result_count": vehicle_result_count,
            "latest_date": vehicle_latest_date,
            "category_analysis": vehicle_category_analysis,
        }

    return _dkss_common.render_template(
        "index.html",
        my_safe_days=my_safe_days,
        ranking=ranking,
        my_good_count=my_good_count,
        my_pending_pointouts=my_pending_pointouts,
        dashboard_request_counts=get_dashboard_request_counts(),
        dashboard_periodic_schedule=get_dashboard_periodic_schedule(
            company_code,
            dashboard_scope_office,
            today,
        ),
        dashboard_office_check_trend=get_dashboard_office_check_trend(
            office_check_trend_groups,
            dashboard_score_value,
            dashboard_start_date,
            today.strftime("%Y-%m-%d"),
        ),
        inspection_alerts=inspection_alerts,
        setup_tasks=setup_tasks,
        checklist_score_summaries=checklist_score_summaries,
        my_checklist_summaries=my_checklist_summaries,
        my_user_name=user_name,
        my_vehicles=my_vehicles,
        my_vehicle_analysis=my_vehicle_analysis,
        dashboard_office_trend=get_dashboard_office_maintenance_trend(
            company_code, dashboard_scope_office,
        ),
        dashboard_vehicle_attention=get_dashboard_vehicle_attention(
            company_code,
            dashboard_scope_office,
            [vehicle.id for vehicle in my_vehicles],
        ),
        dashboard_settings=dashboard_settings,
        dashboard_scope_office=dashboard_scope_office,
        dashboard_scope_missing=dashboard_scope_missing,
        dashboard_period_start=dashboard_start_date,
        dashboard_period_end=today.strftime("%Y-%m-%d"),
        dashboard_offices=_dkss_master_readers.offices_for_current_company(),
        is_dashboard_admin=_dkss_common.session.get("role") in ["admin", "itc"],
    )



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
