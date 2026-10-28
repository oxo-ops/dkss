"""Assemble dashboard panels from scoped records; no HTTP or SQL calls."""

from datetime import datetime
from .serialization import safe_json_dict, safe_json_dict_list, safe_json_str_list
from .dashboard_scoring import DashboardScoring


class DashboardService:

    def __init__(self, scope, repository, *, checklist_to_dict, patrol_to_dict, history, url_for):
        self.scope = scope
        self.repository = repository
        self.checklist_to_dict = checklist_to_dict
        self.patrol_to_dict = patrol_to_dict
        self.history = history
        self.url_for = url_for
        self.scoring = DashboardScoring()

    def build(self):
        my_safe_days, my_vehicle_record_ids = self.personal_driver()
        ranking = self.ranking()
        good_count = self.repository.good_count()
        pending = self.pending_pointouts()
        alerts = self.inspection_alerts()
        setup_tasks = self.setup_tasks()
        self.repository.preload_vehicles(my_vehicle_record_ids)
        checklists = self.repository.checklists()
        summaries, personal, trend_groups = ([], [], [])
        for checklist_record in checklists:
            checklist = self.checklist_to_dict(checklist_record)
            has_score = checklist.get("score_enabled") or any(
                (
                    self.scoring.score_value(choice) is not None
                    for item in checklist.get("items", [])
                    if item.get("item_type") == "check" and item.get("input_type") == "select"
                    for choice in item.get("choices", [])
                )
            )
            is_vehicle = checklist_record.target == "車両管理"
            if not has_score and (not is_vehicle):
                continue
            check_items = [
                item for item in checklist.get("items", []) if item.get("item_type") == "check"
            ]
            rows = self.repository.checklist_results(checklist_record)
            my_rows = (
                [row for row in rows if row.vehicle_record_id in my_vehicle_record_ids]
                if is_vehicle
                else [
                    row
                    for row in rows
                    if row.target_type == "user" and row.target_username == self.scope.username
                ]
            )
            trend_groups.append((checklist_record, checklist, rows))
            scores, distribution, average, maximum = self.score_overview(
                rows, check_items, is_vehicle
            )
            if is_vehicle:
                personal.extend(
                    self.personal_vehicle_summaries(
                        my_vehicle_record_ids,
                        my_rows,
                        check_items,
                        average,
                        checklist_record,
                        checklist,
                        maximum,
                    )
                )
            else:
                personal.extend(
                    self.personal_safety_summaries(
                        my_rows, check_items, average, checklist_record, maximum
                    )
                )
            categories = self.category_analysis(rows, check_items, is_vehicle)
            item_stats, improvements = self.improvement_items(
                rows, check_items, is_vehicle, checklist, checklist_record
            )
            targets = self.target_analysis(rows, is_vehicle, check_items)
            if has_score:
                summaries.append(
                    {
                        "id": checklist_record.id,
                        "name": checklist_record.name,
                        "target": checklist_record.target,
                        "frequency_unit": checklist_record.frequency_unit,
                        "display_type": checklist_record.display_type,
                        "average_score": average,
                        "result_count": len(scores),
                        "scores": scores,
                        "max_score": maximum,
                        "score_distribution": distribution,
                        "category_analysis": categories,
                        "review_item_count": sum(
                            (
                                1
                                for stats in item_stats.values()
                                if stats["max_score"] > 0 and stats["score"] < stats["max_score"]
                            )
                        ),
                        "target_analysis": targets,
                        "history": self.history(
                            checklist_record, checklist, rows, self.scoring.score_value
                        ),
                        "improvement_items": improvements,
                    }
                )
        vehicles = self.repository.assigned_vehicles(my_vehicle_record_ids)
        context = dict(
            my_safe_days=my_safe_days,
            ranking=ranking,
            my_good_count=good_count,
            my_pending_pointouts=pending,
            inspection_alerts=alerts,
            setup_tasks=setup_tasks,
            checklist_score_summaries=summaries,
            my_checklist_summaries=personal,
            my_user_name=self.scope.user_name,
            my_vehicles=vehicles,
            my_vehicle_analysis=self.vehicle_analysis(vehicles, checklists),
            dashboard_settings=self.scope.settings,
            dashboard_scope_office=self.scope.office,
            dashboard_scope_missing=self.scope.office_missing,
            dashboard_period_start=self.scope.start_date,
            dashboard_period_end=self.scope.today.strftime("%Y-%m-%d"),
            is_dashboard_admin=self.scope.role in ["admin", "itc"],
        )
        return (context, trend_groups)

    def setup_tasks(self):
        if self.scope.role != "admin":
            return []
        missing = self.repository.missing_master_kinds()
        specifications = [
            ("offices", "営業所マスタ", "営業所を登録してください。"),
            ("vehicle-types", "車種マスタ", "車両登録で使用する車種を登録してください。"),
            (
                "license-types",
                "免許種別マスタ",
                "ドライバー登録で使用する免許種別を登録してください。",
            ),
            (
                "delivery-places",
                "納入先マスタ",
                "安全パトロールで使用する納入先を登録してください。",
            ),
            ("vehicles", "車両マスタ", "車両管理・点検で使用する車両を登録してください。"),
            (
                "checklists",
                "チェックリストマスタ",
                "安全管理・車両管理で使用するチェックリストを登録してください。",
            ),
        ]
        return [
            {"name": name, "description": description, "url": "/master/" + kind}
            for kind, name, description in specifications
            if kind in missing
        ]

    def personal_driver(self):
        my_driver = self.repository.driver()
        my_safe_days = None
        my_vehicle_record_ids = []
        if my_driver:
            my_vehicle_record_ids = [
                int(vehicle_record_id)
                for vehicle_record_id in safe_json_str_list(my_driver.vehicles_json)
                if vehicle_record_id.isdigit()
            ]
        if my_driver and my_driver.safe_start_date:
            try:
                start_date = datetime.strptime(my_driver.safe_start_date, "%Y-%m-%d").date()
                my_safe_days = max(0, (self.scope.today - start_date).days)
            except ValueError:
                my_safe_days = None
        return (my_safe_days, my_vehicle_record_ids)

    def ranking(self):
        ranking_records = self.repository.ranking_drivers()
        ranking = []
        for driver in ranking_records:
            try:
                start_date = datetime.strptime(driver.safe_start_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            ranking.append(
                {
                    "id": driver.id,
                    "index": driver.id,
                    "employee_id": driver.employee_id,
                    "name": driver.name,
                    "role": driver.role,
                    "office": driver.office,
                    "safe_start_date": driver.safe_start_date,
                    "safe_days": (self.scope.today - start_date).days,
                }
            )
        # Legacy strings can be unpadded or invalid; select ten only after parsing.
        ranking.sort(key=lambda row: row["safe_days"], reverse=True)
        return ranking[:10]

    def pending_pointouts(self):
        pending_records = self.repository.pending_pointouts()
        my_pending_pointouts = []
        for record in pending_records:
            my_pending_pointouts.append(self.patrol_to_dict(record))
        return my_pending_pointouts

    def inspection_alerts(self):
        inspection_vehicle_records = self.repository.inspection_vehicles()
        inspection_alerts = []
        for vehicle in inspection_vehicle_records:
            try:
                expiry_date = datetime.strptime(vehicle.inspection_expiry, "%Y-%m-%d").date()
            except ValueError:
                continue
            remaining_days = (expiry_date - self.scope.today).days
            item = {
                "vehicle_record_id": vehicle.id,
                "chassis_number": vehicle.chassis_number,
                "number": " ".join(
                    (
                        value
                        for value in [
                            vehicle.plate_area or "",
                            vehicle.plate_class or "",
                            vehicle.plate_kana or "",
                            vehicle.plate_number or "",
                        ]
                        if value
                    )
                ),
                "type": vehicle.type or "",
                "body_type": vehicle.body_type or "",
                "inspection_expiry": vehicle.inspection_expiry,
                "remaining_days": remaining_days,
            }
            inspection_alerts.append(item)
        return inspection_alerts

    def score_overview(self, result_records, check_items, is_vehicle_checklist):
        max_score = 100
        result_scores = []
        for result_record in result_records:
            answers = safe_json_dict_list(result_record.answers_json)
            result_check_items = check_items
            if is_vehicle_checklist and result_record.checklist_snapshot_json:
                result_snapshot = safe_json_dict(result_record.checklist_snapshot_json)
                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get("items", [])
                        if item.get("item_type") == "check"
                    ]
            total_score = 0
            total_max_score = 0
            for item, score_value, item_max_score in self.scoring.values(
                result_check_items, answers
            ):
                total_score += score_value
                total_max_score += item_max_score
            if total_max_score > 0:
                result_scores.append(round(total_score / total_max_score * 100, 1))
        score_distribution = {}
        for score in result_scores:
            score_value = float(score)
            score_label = int(score_value) if score_value.is_integer() else score_value
            score_distribution[score_label] = score_distribution.get(score_label, 0) + 1
        average_score = round(sum(result_scores) / len(result_scores), 1) if result_scores else None
        return (result_scores, score_distribution, average_score, max_score)

    def personal_vehicle_summaries(
        self,
        my_vehicle_record_ids,
        my_result_records,
        check_items,
        average_score,
        checklist_record,
        checklist,
        max_score,
    ):
        my_checklist_summaries = []
        for usage_vehicle_id in my_vehicle_record_ids:
            vehicle_result_records = [
                result_record
                for result_record in my_result_records
                if result_record.vehicle_record_id == usage_vehicle_id
            ]
            vehicle_result_scores = []
            vehicle_category_stats = {}
            for result_record in vehicle_result_records:
                answers = safe_json_dict_list(result_record.answers_json)
                result_check_items = check_items
                if result_record.checklist_snapshot_json:
                    result_snapshot = safe_json_dict(result_record.checklist_snapshot_json)
                    if result_snapshot:
                        result_check_items = [
                            item
                            for item in result_snapshot.get("items", [])
                            if item.get("item_type") == "check"
                        ]
                total_score = 0
                total_max_score = 0
                for item, score_value, item_max_score in self.scoring.values(
                    result_check_items, answers
                ):
                    total_score += score_value
                    total_max_score += item_max_score
                    category = (item.get("category") or "その他").strip()
                    if category not in vehicle_category_stats:
                        vehicle_category_stats[category] = {"score": 0, "max_score": 0}
                    vehicle_category_stats[category]["score"] += score_value
                    vehicle_category_stats[category]["max_score"] += item_max_score
                if total_max_score > 0:
                    vehicle_result_scores.append(round(total_score / total_max_score * 100, 1))
            vehicle_average_score = (
                round(sum(vehicle_result_scores) / len(vehicle_result_scores), 1)
                if vehicle_result_scores
                else None
            )
            vehicle_category_analysis = []
            for category, stats in vehicle_category_stats.items():
                if stats["max_score"] <= 0:
                    continue
                score_rate = round(stats["score"] / stats["max_score"] * 100, 1)
                vehicle_category_analysis.append(
                    {
                        "category": category,
                        "score_rate": score_rate,
                        "improvement_rate": round(100 - score_rate, 1),
                    }
                )
            vehicle_category_analysis.sort(key=lambda item: item["score_rate"])
            vehicle_category_analysis = vehicle_category_analysis[:2]
            average_difference = (
                round(vehicle_average_score - average_score, 1)
                if vehicle_average_score is not None and average_score is not None
                else None
            )
            usage_vehicle = self.repository.vehicle(usage_vehicle_id, active_only=True)
            if not usage_vehicle:
                continue
            my_checklist_summaries.append(
                {
                    "id": checklist_record.id,
                    "name": checklist_record.name,
                    "target": checklist_record.target,
                    "is_standard_daily": checklist.get("fixed_template_code")
                    == "daily_inspection_truck_trailer",
                    "is_daily": checklist.get("fixed_template_code")
                    == "daily_inspection_truck_trailer"
                    or (
                        checklist_record.frequency_unit == "day"
                        and str(checklist_record.frequency_value or "1") == "1"
                    ),
                    "vehicle_record_id": usage_vehicle_id,
                    "registration_number": " ".join(
                        (
                            value
                            for value in [
                                usage_vehicle.plate_area or "",
                                usage_vehicle.plate_class or "",
                                usage_vehicle.plate_kana or "",
                                usage_vehicle.plate_number or "",
                            ]
                            if value
                        )
                    ),
                    "chassis_number": usage_vehicle.chassis_number if usage_vehicle else "",
                    "target_user": self.scope.user_name,
                    "target_username": self.scope.username,
                    "average_score": vehicle_average_score,
                    "overall_average_score": average_score,
                    "average_difference": average_difference,
                    "result_count": len(vehicle_result_scores),
                    "max_score": max_score,
                    "category_analysis": vehicle_category_analysis,
                }
            )
        return my_checklist_summaries

    def personal_safety_summaries(
        self, my_result_records, check_items, average_score, checklist_record, max_score
    ):
        my_checklist_summaries = []
        my_result_scores = []
        for result_record in my_result_records:
            answers = safe_json_dict_list(result_record.answers_json)
            result_check_items = check_items
            total_score = 0
            total_max_score = 0
            for item, score_value, item_max_score in self.scoring.values(
                result_check_items, answers
            ):
                total_score += score_value
                total_max_score += item_max_score
            if total_max_score > 0:
                my_result_scores.append(round(total_score / total_max_score * 100, 1))
        my_average_score = (
            round(sum(my_result_scores) / len(my_result_scores), 1) if my_result_scores else None
        )
        my_category_stats = {}
        for result_record in my_result_records:
            answers = safe_json_dict_list(result_record.answers_json)
            for item, score, item_max_score in self.scoring.values(check_items, answers):
                category = (item.get("category") or "その他").strip()
                if category not in my_category_stats:
                    my_category_stats[category] = {"score": 0, "max_score": 0}
                my_category_stats[category]["score"] += score
                my_category_stats[category]["max_score"] += item_max_score
        my_category_analysis = []
        for category, stats in my_category_stats.items():
            if stats["max_score"] <= 0:
                continue
            score_rate = round(stats["score"] / stats["max_score"] * 100, 1)
            my_category_analysis.append(
                {
                    "category": category,
                    "score_rate": score_rate,
                    "improvement_rate": round(100 - score_rate, 1),
                }
            )
        my_category_analysis.sort(key=lambda item: item["score_rate"])
        my_category_analysis = my_category_analysis[:2]
        if my_average_score is not None:
            average_difference = (
                round(my_average_score - average_score, 1) if average_score is not None else None
            )
            my_checklist_summaries.append(
                {
                    "id": checklist_record.id,
                    "name": checklist_record.name,
                    "target": checklist_record.target,
                    "target_user": self.scope.user_name,
                    "target_username": self.scope.username,
                    "average_score": my_average_score,
                    "overall_average_score": average_score,
                    "average_difference": average_difference,
                    "result_count": len(my_result_scores),
                    "max_score": max_score,
                    "category_analysis": my_category_analysis,
                }
            )
        return my_checklist_summaries

    def category_analysis(self, result_records, check_items, is_vehicle_checklist):
        category_stats = {}
        for result_record in result_records:
            answers = safe_json_dict_list(result_record.answers_json)
            result_check_items = check_items
            if is_vehicle_checklist and result_record.checklist_snapshot_json:
                result_snapshot = safe_json_dict(result_record.checklist_snapshot_json)
                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get("items", [])
                        if item.get("item_type") == "check"
                    ]
            for item, score, item_max_score in self.scoring.values(result_check_items, answers):
                category = (item.get("category") or "その他").strip()
                if category not in category_stats:
                    category_stats[category] = {"score": 0, "max_score": 0, "count": 0}
                category_stats[category]["score"] += score
                category_stats[category]["max_score"] += item_max_score
                category_stats[category]["count"] += 1
        category_analysis = []
        for category, stats in category_stats.items():
            if stats["max_score"] <= 0:
                continue
            score_rate = round(stats["score"] / stats["max_score"] * 100, 1)
            category_analysis.append(
                {
                    "category": category,
                    "score_rate": score_rate,
                    "improvement_rate": round(100 - score_rate, 1),
                    "count": stats["count"],
                }
            )
        category_analysis.sort(key=lambda item: item["score_rate"])
        return category_analysis

    def improvement_items(
        self, result_records, check_items, is_vehicle_checklist, checklist, checklist_record
    ):
        item_stats = {}
        for result_record in result_records:
            answers = safe_json_dict_list(result_record.answers_json)
            result_check_items = check_items
            if is_vehicle_checklist and result_record.checklist_snapshot_json:
                result_snapshot = safe_json_dict(result_record.checklist_snapshot_json)
                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get("items", [])
                        if item.get("item_type") == "check"
                    ]
            for item, score, item_max_score in self.scoring.values(result_check_items, answers):
                content = (item.get("content") or "項目名なし").strip()
                category = (item.get("category") or "その他").strip()
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
            score_rate = round(stats["score"] / stats["max_score"] * 100, 1)
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
                    result_url = self.url_for(
                        "vehicle_checklist_results",
                        index=checklist_record.id,
                        vehicle_record_id=result_record.vehicle_record_id,
                        year=result_record.year,
                        month=result_record.month,
                        active_day=active_day,
                    )
                else:
                    result_url = self.url_for(
                        "checklist_result_detail", result_index=result_record.id
                    )
            improvement_items.append(
                {
                    "category": category,
                    "content": content,
                    "score_rate": score_rate,
                    "improvement_rate": round(100 - score_rate, 1),
                    "count": stats["count"],
                    "result_url": result_url,
                }
            )
        improvement_items.sort(key=lambda item: item["improvement_rate"], reverse=True)
        improvement_items = improvement_items[:5]
        return (item_stats, improvement_items)

    def target_analysis(self, result_records, is_vehicle_checklist, check_items):
        target_stats = {}
        for result_record in result_records:
            if is_vehicle_checklist:
                target_type = "vehicle"
                target_vehicle_record = self.repository.vehicle(result_record.vehicle_record_id)
                if not target_vehicle_record:
                    continue
                target_label = (
                    " ".join(
                        (
                            value
                            for value in [
                                target_vehicle_record.plate_area or "",
                                target_vehicle_record.plate_class or "",
                                target_vehicle_record.plate_kana or "",
                                target_vehicle_record.plate_number or "",
                            ]
                            if value
                        )
                    )
                    or "ナンバー未登録"
                )
            else:
                target_type = result_record.target_type
                if target_type == "user":
                    # Personal target breakdowns are restricted to administrators.
                    if self.scope.role not in ["admin", "itc"]:
                        continue
                    target_label = result_record.target_user
                elif target_type == "vehicle":
                    target_vehicle_record = self.repository.vehicle(
                        result_record.target_vehicle_record_id
                    )
                    if not target_vehicle_record:
                        continue
                    target_label = (
                        " ".join(
                            (
                                value
                                for value in [
                                    target_vehicle_record.plate_area or "",
                                    target_vehicle_record.plate_class or "",
                                    target_vehicle_record.plate_kana or "",
                                    target_vehicle_record.plate_number or "",
                                ]
                                if value
                            )
                        )
                        or "ナンバー未登録"
                    )
                elif target_type == "office":
                    target_label = result_record.target_office
                else:
                    continue
            if not target_label:
                continue
            answers = safe_json_dict_list(result_record.answers_json)
            result_check_items = check_items
            if is_vehicle_checklist and result_record.checklist_snapshot_json:
                result_snapshot = safe_json_dict(result_record.checklist_snapshot_json)
                if result_snapshot:
                    result_check_items = [
                        item
                        for item in result_snapshot.get("items", [])
                        if item.get("item_type") == "check"
                    ]
            target_score = 0
            target_max_score = 0
            target_review_items = {}
            for item, score, item_max_score in self.scoring.values(result_check_items, answers):
                target_score += score
                target_max_score += item_max_score
                if score < item_max_score:
                    content = str(item.get("content") or "項目名なし").strip() or "項目名なし"
                    target_review_items[content] = target_review_items.get(content, 0) + 1
            if target_max_score <= 0:
                continue
            target_identity = (
                target_vehicle_record.id
                if target_type == "vehicle"
                else (
                    result_record.target_username
                    if target_type == "user"
                    else result_record.target_office
                )
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
                        else (
                            result_record.target_vehicle_record_id
                            if target_type == "vehicle"
                            else None
                        )
                    ),
                    "target_value": (
                        result_record.target_username
                        if target_type == "user"
                        else (
                            result_record.target_office
                            if target_type == "office"
                            else (
                                result_record.vehicle_record_id
                                if is_vehicle_checklist
                                else (
                                    result_record.target_vehicle_record_id
                                    if target_type == "vehicle"
                                    else None
                                )
                            )
                        )
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
                target_stats[key]["year"] = getattr(result_record, "year", "") or ""
                target_stats[key]["month"] = getattr(result_record, "month", "") or ""
                target_stats[key]["day"] = getattr(result_record, "day", "") or ""
        target_analysis = []
        for (target_type, target_identity, target_label), stats in target_stats.items():
            if stats["max_score"] <= 0:
                continue
            score_rate = round(stats["score"] / stats["max_score"] * 100, 1)
            target_analysis.append(
                {
                    "target_type": target_type,
                    "target_label": target_label,
                    "vehicle_record_id": stats.get("vehicle_record_id"),
                    "target_value": stats.get("target_value"),
                    "year": stats.get("year", ""),
                    "month": stats.get("month", ""),
                    "day": stats.get("day", ""),
                    "score_rate": score_rate,
                    "average_score": round(stats["score_sum"] / stats["count"], 1),
                    "review_items": [
                        content
                        for content, count in sorted(
                            stats["review_items"].items(), key=lambda item: (-item[1], item[0])
                        )
                    ],
                    "improvement_rate": round(100 - score_rate, 1),
                    "count": stats["count"],
                }
            )
        target_analysis.sort(key=lambda item: item["improvement_rate"], reverse=True)
        for target in target_analysis:
            target["vehicle_type"] = ""
            target["body_type"] = ""
            if target["target_type"] == "vehicle":
                target_vehicle = self.repository.vehicle(target.get("vehicle_record_id"))
                if target_vehicle:
                    target["vehicle_record_id"] = target_vehicle.id
                    target["vehicle_type"] = target_vehicle.type or ""
                    target["body_type"] = target_vehicle.body_type or ""
        return target_analysis

    def vehicle_analysis(self, my_vehicles, score_checklists):
        my_vehicle_analysis = {}
        for vehicle in my_vehicles:
            vehicle_result_rates = []
            vehicle_result_count = 0
            vehicle_latest_date = ""
            vehicle_category_stats = {}
            for checklist_record in score_checklists:
                if checklist_record.target != "車両管理":
                    continue
                checklist = self.checklist_to_dict(checklist_record)
                vehicle_results = self.repository.personal_vehicle_results(
                    checklist_record.id, vehicle.id
                )
                for result_record in vehicle_results:
                    answers = safe_json_dict_list(result_record.answers_json)
                    result_checklist = checklist
                    if result_record.checklist_snapshot_json:
                        snapshot = safe_json_dict(result_record.checklist_snapshot_json)
                        if snapshot:
                            result_checklist = snapshot
                    check_items = [
                        item
                        for item in result_checklist.get("items", [])
                        if item.get("item_type") == "check"
                    ]
                    result_score = 0
                    result_max_score = 0
                    for item, score, item_max_score in self.scoring.values(check_items, answers):
                        result_score += score
                        result_max_score += item_max_score
                        category = item.get("category") or "その他"
                        if category not in vehicle_category_stats:
                            vehicle_category_stats[category] = {"score": 0, "max_score": 0}
                        vehicle_category_stats[category]["score"] += score
                        vehicle_category_stats[category]["max_score"] += item_max_score
                    if result_max_score > 0:
                        vehicle_result_rates.append(round(result_score / result_max_score * 100, 1))
                        vehicle_result_count += 1
                    if (
                        result_record.checked_date
                        and result_record.checked_date > vehicle_latest_date
                    ):
                        vehicle_latest_date = result_record.checked_date
            score_rate = None
            if vehicle_result_rates:
                score_rate = round(sum(vehicle_result_rates) / len(vehicle_result_rates), 1)
            vehicle_category_analysis = []
            for category, stats in vehicle_category_stats.items():
                if stats["max_score"] <= 0:
                    continue
                category_score_rate = round(stats["score"] / stats["max_score"] * 100, 1)
                vehicle_category_analysis.append(
                    {
                        "category": category,
                        "score_rate": category_score_rate,
                        "improvement_rate": round(100 - category_score_rate, 1),
                    }
                )
            vehicle_category_analysis.sort(key=lambda item: item["improvement_rate"], reverse=True)
            vehicle_category_analysis = vehicle_category_analysis[:2]
            my_vehicle_analysis[vehicle.id] = {
                "score_rate": score_rate,
                "result_count": vehicle_result_count,
                "latest_date": vehicle_latest_date,
                "category_analysis": vehicle_category_analysis,
            }
        return my_vehicle_analysis
