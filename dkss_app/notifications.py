"""Notifications responsibilities; routes are registered by the application factory."""
from . import audit as _dkss_audit, checklist_common as _dkss_checklist_common, common as _dkss_common, models as _dkss_models, runtime as _dkss_runtime, serialization as _dkss_serialization, vehicle_readers as _dkss_vehicle_readers


def get_operation_judgment_notification_state(notification, context):
    def state(status, label, requires_action=False):
        return {
            "workflow_status": status,
            "workflow_label": label,
            "requires_action": requires_action,
        }

    result_id = context.get("result_id")
    event_id = context.get("event_id")

    if (
        context.get("result_type") != "vehicle"
        or type(result_id) is not int
        or result_id <= 0
        or type(event_id) is not int
        or event_id < 0
    ):
        return state("unknown", "対応状態を確認できません")

    result_record = _dkss_models.VehicleChecklistResult.query.filter_by(
        company_code=notification.company_code,
        id=result_id
    ).first()

    if not result_record:
        return state("closed", "対象記録がないため終了")

    events = _dkss_models.ChecklistEvent.query.filter(
        _dkss_models.ChecklistEvent.company_code == notification.company_code,
        _dkss_models.ChecklistEvent.result_type == "vehicle",
        _dkss_models.ChecklistEvent.result_id == result_id,
        _dkss_models.ChecklistEvent.id > event_id,
        _dkss_models.ChecklistEvent.event_type.in_(["運行判断", "差し戻し"])
    ).order_by(_dkss_models.ChecklistEvent.id.asc()).all()

    for event in events:
        if event.event_type == "差し戻し":
            return state("rejected", "差し戻しにより終了")

        detail = _dkss_serialization.safe_json_dict(event.detail_json)
        judgment = detail.get("judgment")

        if (
            isinstance(judgment, dict)
            and judgment.get("status") in ("運行可", "運行不可")
        ):
            return state("completed", "対応済み")

    if result_record.status == "差し戻し":
        return state("rejected", "差し戻しにより終了")

    judgment = _dkss_serialization.safe_json_dict(result_record.operation_judgment_json)

    if judgment.get("status") in ("運行可", "運行不可"):
        return state("completed", "対応済み")

    if notification.target_username not in (
        judgment.get("requested_usernames") or []
    ):
        return state("closed", "担当変更により終了")

    if judgment.get("status") == "判定保留":
        return state("pending", "再判断待ち", True)

    return state("pending", "対応待ち", True)



def get_correction_notification_state(notification, context):
    def state(status, label, requires_action=False):
        return {
            "workflow_status": status,
            "workflow_label": label,
            "requires_action": requires_action,
        }

    result_models = {
        "safety": _dkss_models.ChecklistResult,
        "vehicle": _dkss_models.VehicleChecklistResult,
    }
    result_type = context.get("result_type")
    result_model = result_models.get(result_type)
    result_id = context.get("result_id")
    event_id = context.get("event_id")

    if (
        result_model is None
        or type(result_id) is not int
        or result_id <= 0
        or type(event_id) is not int
        or event_id < 0
    ):
        return state("unknown", "対応状態を確認できません")

    result_record = result_model.query.filter_by(
        company_code=notification.company_code,
        id=result_id
    ).first()

    if not result_record:
        return state("closed", "対象記録がないため終了")

    resubmission = _dkss_models.ChecklistEvent.query.filter(
        _dkss_models.ChecklistEvent.company_code == notification.company_code,
        _dkss_models.ChecklistEvent.result_type == result_type,
        _dkss_models.ChecklistEvent.result_id == result_id,
        _dkss_models.ChecklistEvent.id > event_id,
        _dkss_models.ChecklistEvent.event_type == "再申請"
    ).order_by(_dkss_models.ChecklistEvent.id.asc()).first()

    if resubmission:
        return state("completed", "再申請済み")

    return state("pending", "修正待ち", True)



def get_notification_actor_name(notification):
    context = _dkss_serialization.safe_json_dict(notification.workflow_context_json)

    if not context:
        event = get_notification_legacy_judgment_event(notification)
        if event:
            return str(event.actor_name or "").strip()

        message = str(notification.message or "")
        title = str(notification.title or "").strip()
        if (
            title.endswith((
                "：再確認待ち",
                "：再確認済み・異常なし",
                "：再確認で異常あり",
            ))
            and get_notification_summary(notification) != message
        ):
            return message.splitlines()[5].partition("：")[2].strip()
        return ""

    event_id = context.get("event_id")
    result_id = context.get("result_id")
    result_type = context.get("result_type")

    if (
        type(event_id) is not int
        or event_id <= 0
        or type(result_id) is not int
        or result_id <= 0
        or result_type not in ("safety", "vehicle")
    ):
        return ""

    event = _dkss_models.ChecklistEvent.query.filter_by(
        id=event_id,
        company_code=notification.company_code,
        result_type=result_type,
        result_id=result_id
    ).first()

    if not event:
        return ""

    return str(event.actor_name or "").strip()



def get_recheck_notification_state(notification):
    def state(status="", label="", requires_action=False):
        return {
            "workflow_status": status,
            "workflow_label": label,
            "requires_action": requires_action,
        }

    if (
        notification.company_code != _dkss_common.session.get("company_code")
        or notification.target_username != _dkss_common.session.get("username")
        or get_notification_summary(notification)
        == str(notification.message or "")
    ):
        return state()

    result_type, result_id = get_notification_result_reference(notification)
    parsed_link = _dkss_common.urlparse(str(notification.link or ""))
    match = _dkss_common.re.fullmatch(
        r"vehicle-flow-defect-([1-9]\d{0,9})-([1-9]\d{0,9})",
        parsed_link.fragment
    )
    if result_type != "vehicle" or not match:
        return state()

    result_record = _dkss_models.VehicleChecklistResult.query.filter_by(
        id=result_id,
        company_code=notification.company_code
    ).first()
    if not result_record:
        return state()

    judgment = _dkss_serialization.safe_json_dict(result_record.operation_judgment_json)
    defects = judgment.get("defects")
    if not isinstance(defects, list):
        return state()

    defect_no = int(match.group(2))
    defect = next((
        item for item in defects
        if isinstance(item, dict)
        and type(item.get("defect_no")) is int
        and item["defect_no"] == defect_no
    ), None)
    if not defect:
        return state()

    event = str(notification.title or "").strip().rpartition("：")[2]
    entry_key = "repair" if event == "再確認待ち" else "recheck"
    entry = defect.get(entry_key)
    if (
        not isinstance(entry, dict)
        or not notification.created_at
        or (
            entry.get("notification_created_at")
            or entry.get("recorded_at")
        ) != notification.created_at
    ):
        return state()

    current_status = defect.get("status")
    if event == "再確認待ち":
        if current_status == "再確認待ち":
            return state("pending", "再確認待ち", True)
        if current_status in ("対応待ち", "解消"):
            return state("completed", "再確認済み")

    elif event == "再確認で異常あり":
        if current_status == "対応待ち":
            return state("pending", "整備待ち", True)
        if current_status in ("整備中", "再確認待ち"):
            return state("completed", "整備登録済み")

    elif event == "再確認済み・異常なし":
        if current_status == "解消":
            return state("completed", "不具合解消")

    return state()



def get_notification_workflow_state(notification):
    def state(status, label, requires_action=False):
        return {
            "workflow_status": status,
            "workflow_label": label,
            "requires_action": requires_action,
        }

    context = _dkss_serialization.safe_json_dict(notification.workflow_context_json)

    if not context:
        return get_recheck_notification_state(notification)

    if context.get("action") == "periodic_issue":
        return _dkss_runtime.app.extensions["dkss"]['periodic_followups'].workflow(notification)

    if context.get("action") == "inspection_plan_alert":
        return _dkss_runtime.app.extensions["dkss"]['inspection_alerts'].workflow(notification)

    if context.get("action") == "operation_judgment":
        return get_operation_judgment_notification_state(
            notification,
            context
        )

    if context.get("action") == "correction":
        return get_correction_notification_state(
            notification,
            context
        )

    if context.get("action") != "approval":
        return state("", "")

    result_models = {
        "safety": _dkss_models.ChecklistResult,
        "vehicle": _dkss_models.VehicleChecklistResult,
    }
    result_type = context.get("result_type")
    result_model = result_models.get(result_type)
    result_id = context.get("result_id")
    approval_index = context.get("approval_index")
    event_id = context.get("event_id")

    if (
        result_model is None
        or type(result_id) is not int
        or result_id <= 0
        or type(approval_index) is not int
        or approval_index < 0
        or type(event_id) is not int
        or event_id < 0
    ):
        return state("unknown", "対応状態を確認できません")

    result_record = result_model.query.filter_by(
        company_code=notification.company_code,
        id=result_id
    ).first()

    if not result_record:
        return state("closed", "対象記録がないため終了")

    events = _dkss_models.ChecklistEvent.query.filter(
        _dkss_models.ChecklistEvent.company_code == notification.company_code,
        _dkss_models.ChecklistEvent.result_type == result_type,
        _dkss_models.ChecklistEvent.result_id == result_id,
        _dkss_models.ChecklistEvent.id > event_id,
        _dkss_models.ChecklistEvent.event_type.in_(
            ["承認", "差し戻し", "運行判断"]
        )
    ).order_by(
        _dkss_models.ChecklistEvent.id.asc()
    ).all()

    for event in events:
        if event.event_type == "差し戻し":
            return state("rejected", "差し戻しにより終了")

        detail = _dkss_serialization.safe_json_dict(event.detail_json)

        if (
            event.event_type == "承認"
            and detail.get("approval_index") == approval_index
        ):
            return state("completed", "対応済み")

        if (
            result_type == "vehicle"
            and event.event_type == "運行判断"
            and approval_index == 0
        ):
            judgment = detail.get("judgment")

            if (
                isinstance(judgment, dict)
                and judgment.get("status") in ("運行可", "運行不可")
            ):
                return state("completed", "対応済み")

    if result_record.status == "差し戻し":
        return state("rejected", "差し戻しにより終了")

    approvals = _dkss_serialization.safe_json_dict_list(result_record.approvals_json)

    if approval_index >= len(approvals):
        return state("unknown", "対象の承認工程を確認できません")

    if result_type == "vehicle" and approval_index == 0:
        judgment = _dkss_serialization.safe_json_dict(
            result_record.operation_judgment_json
        )

        if judgment.get("status") == "判定保留":
            return state("pending", "再判断待ち", True)

    approval = approvals[approval_index]

    if (
        approval.get("approved_by")
        or approval.get("approved_by_username")
    ):
        return state("completed", "対応済み")

    return state("pending", "対応待ち", True)



def get_notification_legacy_judgment_event(notification):
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")
    if (
        not company_code or not username
        or notification.company_code != company_code
        or notification.target_username != username
        or _dkss_serialization.safe_json_dict(notification.workflow_context_json)
    ):
        return None

    title = str(notification.title or "").strip()
    if title not in (
        "車両の運行判断：運行可",
        "車両の運行判断：運行不可",
        "車両の運行判断：判定保留",
    ):
        return None

    message = str(notification.message or "")
    if get_notification_summary(notification) == message:
        return None

    parsed_link = _dkss_common.urlparse(str(notification.link or ""))
    path_match = _dkss_common.re.fullmatch(
        r"/vehicle/checklists/([1-9]\d{0,9})/?", parsed_link.path
    )
    if not path_match or parsed_link.fragment != "vehicle-flow-judgment":
        return None

    try:
        pairs = _dkss_common.parse_qsl(parsed_link.query, max_num_fields=20)
        values = {}
        for key in ("vehicle_record_id", "year", "month", "active_day"):
            matches = [value for name, value in pairs if name == key]
            if len(matches) != 1 or not _dkss_common.re.fullmatch(r"\d{1,10}", matches[0]):
                return None
            values[key] = int(matches[0])

        checklist_id = int(path_match.group(1))
        vehicle_id = values["vehicle_record_id"]
        if not (
            0 < checklist_id <= 2147483647
            and 0 < vehicle_id <= 2147483647
        ):
            return None

        target_date = _dkss_common.datetime(
            values["year"], values["month"], values["active_day"]
        )
        lines = message.splitlines()
        body_date = _dkss_common.datetime.strptime(
            lines[0][len("点検日："):], "%Y-%m-%d"
        )
        if target_date != body_date or not notification.created_at:
            return None
    except (ValueError, OverflowError):
        return None

    cache = _dkss_common.request.environ.setdefault("dkss.legacy_judgment_events", {})
    cache_key = notification.id
    if cache_key in cache:
        return cache[cache_key]

    events = _dkss_models.ChecklistEvent.query.join(
        _dkss_models.VehicleChecklistResult,
        (_dkss_models.VehicleChecklistResult.id == _dkss_models.ChecklistEvent.result_id)
        & (_dkss_models.VehicleChecklistResult.company_code == _dkss_models.ChecklistEvent.company_code)
    ).filter(
        _dkss_models.ChecklistEvent.company_code == company_code,
        _dkss_models.ChecklistEvent.result_type == "vehicle",
        _dkss_models.ChecklistEvent.event_type == "運行判断",
        _dkss_models.ChecklistEvent.created_at == notification.created_at,
        _dkss_models.VehicleChecklistResult.checklist_id == checklist_id,
        _dkss_models.VehicleChecklistResult.vehicle_record_id == vehicle_id,
        _dkss_models.VehicleChecklistResult.year == str(target_date.year),
        _dkss_models.VehicleChecklistResult.month.in_(
            [str(target_date.month), f"{target_date.month:02d}"]
        ),
        _dkss_models.VehicleChecklistResult.day.in_(
            [str(target_date.day), f"{target_date.day:02d}"]
        ),
    ).all()

    decision = title.rpartition("：")[2]
    reason = "\n".join(lines[2:])[len("理由："):].strip()
    matches = []
    for event in events:
        judgment = _dkss_serialization.safe_json_dict(event.detail_json).get("judgment")
        if (
            isinstance(judgment, dict)
            and judgment.get("status") == decision
            and str(judgment.get("reason") or "").strip() == reason
        ):
            matches.append(event)

    matched_event = matches[0] if len(matches) == 1 else None
    cache[cache_key] = matched_event
    return matched_event



def get_notification_result_reference(notification):
    context = _dkss_serialization.safe_json_dict(notification.workflow_context_json)
    if context:
        return context.get("result_type"), context.get("result_id")

    parsed_link = _dkss_common.urlparse(str(notification.link or ""))
    match = _dkss_common.re.fullmatch(
        r"/(safety|vehicle)/checklist-results/(\d+)(?:/.*)?",
        parsed_link.path
    )
    if match:
        return match.group(1), int(match.group(2))

    if _dkss_common.re.fullmatch(r"/vehicle/checklists/\d+/?", parsed_link.path):
        match = _dkss_common.re.fullmatch(
            r"vehicle-flow-defect-([1-9]\d{0,9})-([1-9]\d{0,9})",
            parsed_link.fragment
        )
        if match:
            result_id = int(match.group(1))
            if result_id <= 2147483647:
                return "vehicle", result_id

    event = get_notification_legacy_judgment_event(notification)
    if event:
        return "vehicle", event.result_id

    return None, None



def get_notification_target_lookup(notifications):
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")
    lookup = {
        "results": {},
        "checklists": {},
        "vehicles": {},
    }

    if not company_code or not username:
        return lookup

    result_ids = {"safety": set(), "vehicle": set()}

    for notification in notifications:
        if (
            notification.company_code != company_code
            or notification.target_username != username
        ):
            continue

        result_type, result_id = get_notification_result_reference(
            notification
        )

        if (
            result_type in result_ids
            and type(result_id) is int
            and 0 < result_id <= 2147483647
        ):
            result_ids[result_type].add(result_id)

    models = {
        "safety": _dkss_models.ChecklistResult,
        "vehicle": _dkss_models.VehicleChecklistResult,
    }

    for result_type, ids in result_ids.items():
        if not ids:
            continue

        model = models[result_type]
        records = model.query.filter(
            model.company_code == company_code,
            model.id.in_(ids)
        ).all()

        for record in records:
            lookup["results"][(result_type, record.id)] = record

    records = list(lookup["results"].values())
    checklist_ids = {record.checklist_id for record in records}
    vehicle_ids = {
        vehicle_id
        for record in records
        for vehicle_id in [
            getattr(record, "vehicle_record_id", None),
            getattr(record, "target_vehicle_record_id", None),
        ]
        if vehicle_id
    }

    if checklist_ids:
        lookup["checklists"] = {
            record.id: record
            for record in _dkss_models.Checklist.query.filter(
                _dkss_models.Checklist.company_code == company_code,
                _dkss_models.Checklist.id.in_(checklist_ids)
            ).all()
        }

    if vehicle_ids:
        lookup["vehicles"] = {
            record.id: record
            for record in _dkss_models.Vehicle.query.filter(
                _dkss_models.Vehicle.company_code == company_code,
                _dkss_models.Vehicle.id.in_(vehicle_ids)
            ).all()
        }

    return lookup



def get_notification_target_info(notification, lookup=None):
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if (
        not company_code
        or not username
        or notification.company_code != company_code
        or notification.target_username != username
    ):
        return None

    result_type, result_id = get_notification_result_reference(
        notification
    )

    result_models = {
        "safety": _dkss_models.ChecklistResult,
        "vehicle": _dkss_models.VehicleChecklistResult,
    }
    result_model = result_models.get(result_type)

    if (
        result_model is None
        or type(result_id) is not int
        or result_id <= 0
        or result_id > 2147483647
    ):
        return None

    if lookup is not None:
        result_record = lookup["results"].get((result_type, result_id))
    else:
        result_record = result_model.query.filter_by(
            id=result_id,
            company_code=company_code
        ).first()

    if not result_record:
        return None

    # 記録時点の点検表名を優先する。
    snapshot = _dkss_serialization.safe_json_dict(
        result_record.checklist_snapshot_json
    )
    checklist_name = snapshot.get("name")

    if not isinstance(checklist_name, str):
        checklist_name = ""

    checklist_name = checklist_name.strip()

    if not checklist_name:
        if lookup is not None:
            checklist_record = lookup["checklists"].get(
                result_record.checklist_id
            )
        else:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=result_record.checklist_id,
                company_code=company_code
            ).first()

        if checklist_record:
            checklist_name = checklist_record.name

    target_label = ""
    office = ""
    period_label = result_record.checked_date or ""

    if result_type == "vehicle":
        vehicle_id = result_record.vehicle_record_id

        date_parts = [
            str(value).strip()
            for value in (
                result_record.year,
                result_record.month,
                result_record.day
            )
            if value not in (None, "", "0", 0)
        ]

        if date_parts:
            period_label = "/".join(date_parts)

    else:
        vehicle_id = result_record.target_vehicle_record_id
        target_label = result_record.target_user or ""
        office = result_record.target_office or ""

    if vehicle_id:
        if lookup is not None:
            vehicle_record = lookup["vehicles"].get(vehicle_id)
        else:
            vehicle_record = _dkss_models.Vehicle.query.filter_by(
                id=vehicle_id,
                company_code=company_code
            ).first()

        if vehicle_record:
            target_label = _dkss_vehicle_readers.vehicle_number({
                "plate_area": vehicle_record.plate_area or "",
                "plate_class": vehicle_record.plate_class or "",
                "plate_kana": vehicle_record.plate_kana or "",
                "plate_number": vehicle_record.plate_number or "",
            })
            office = office or vehicle_record.office or ""

    return {
        "checklist_name": checklist_name or "点検記録",
        "target_label": target_label,
        "period_label": period_label,
        "office": office,
    }



def get_notification_summary(notification):
    message = str(notification.message or "")
    title = str(notification.title or "").strip()
    path = _dkss_common.urlparse(str(notification.link or "")).path

    if not path.startswith("/vehicle/"):
        return message

    operation_results = {
        "車両の運行判断：運行可": (
            "運行可", "運行可と判断されました。",
        ),
        "車両の運行判断：運行不可": (
            "運行不可", "運行不可と判断されました。",
        ),
        "車両の運行判断：判定保留": (
            "判定保留", "運行判断が保留になりました。",
        ),
    }
    if title in operation_results:
        lines = message.splitlines()
        decision, description = operation_results[title]
        if (
            len(lines) < 3
            or not lines[0].startswith("点検日：")
            or lines[1] != "判断：" + decision
            or not lines[2].startswith("理由：")
        ):
            return message

        reason = "\n".join(lines[2:])[len("理由："):].strip()
        reason_preview = " ".join(reason.splitlines())
        if len(reason_preview) > 100:
            reason_preview = reason_preview[:100] + "…"

        return "\n".join(part for part in (
            description,
            lines[0],
            "理由：" + reason_preview if reason_preview else "",
        ) if part)

    events = {
        "再確認待ち": (
            "再確認待ち",
            "整備を登録しました。",
        ),
        "再確認済み・異常なし": (
            "解消",
            "再確認を完了しました。異常はありません。",
        ),
        "再確認で異常あり": (
            "対応待ち",
            "再確認を行いました。異常が残っています。",
        ),
    }
    vehicle, separator, event = title.rpartition("：")
    if not separator or event not in events:
        return message

    keys = (
        "対象車両", "点検日", "項目", "対応状況",
        "次にすること", "実施者", "実施日時",
    )
    lines = message.splitlines()
    if len(lines) < 8 or not lines[7].startswith("内容："):
        return message

    fields = {}
    for key, line in zip(keys, lines[:7]):
        prefix = key + "："
        if not line.startswith(prefix):
            return message
        fields[key] = line[len(prefix):].strip()

    expected_status, description = events[event]
    if (
        fields["対象車両"] != vehicle
        or fields["対応状況"] != expected_status
        or not fields["次にすること"]
        or not fields["項目"]
    ):
        return message

    actor = fields["実施者"]
    event_message = (actor + "さんが" if actor else "") + description
    next_action = fields["次にすること"]
    redundant_prefix = "この不具合の再確認は完了しました。"
    if (
        event == "再確認済み・異常なし"
        and next_action.startswith(redundant_prefix)
    ):
        next_action = next_action[len(redundant_prefix):]

    return "\n".join(part for part in (
        event_message,
        next_action,
        "対象項目：" + fields["項目"],
    ) if part)



def get_notification_display_info(notification):
    title = str(notification.title or "").strip()
    path = _dkss_common.urlparse(str(notification.link or "")).path

    if path.startswith(("/vehicle/", "/vehicle-patrols/")):
        category = "vehicle"
    elif path.startswith(("/safety/", "/pointouts/")):
        category = "safety"
    else:
        category = "general"

    notification_type = "notice"
    action_label = "該当ページを確認"

    if title == "メンションされました":
        notification_type = "mention"
        action_label = "メンションを確認"

    elif category in ("safety", "vehicle"):
        if "再申請" in title:
            notification_type = "resubmitted"
            action_label = "変更内容を確認"

        elif title in (
            "安全チェックリスト承認依頼",
            "車両チェックリスト承認依頼",
        ):
            notification_type = "approval_request"
            action_label = "承認内容を確認"

        elif title in (
            "安全パトロールが差し戻されました",
            "チェックリストが差し戻されました",
            "車両チェックリストが差し戻されました",
        ):
            notification_type = "rejected"
            action_label = "差し戻し内容を確認"

        elif (
            title == "運行判断の依頼"
            or title.startswith("運行可否の再判定依頼：")
        ):
            notification_type = "operation_request"
            action_label = "運行判断を確認"

        elif title in (
            "車両の運行判断：運行可",
            "車両の運行判断：運行不可",
            "車両の運行判断：判定保留",
        ):
            notification_type = "operation_result"
            action_label = "判断結果を確認"

        elif title == "安全パトロール確認依頼":
            notification_type = "confirmation_request"
            action_label = "確認内容を開く"

        elif title.startswith("日常点検の異常報告："):
            notification_type = "defect"
            action_label = "不具合を確認"

        elif title.endswith((
            "：再確認待ち",
            "：再確認済み・異常なし",
            "：再確認で異常あり",
        )):
            notification_type = "recheck"
            action_label = "整備・再確認内容を確認"

        elif title.startswith("点検簿の対応確認："):
            notification_type = "periodic_issue"
            action_label = "点検簿の対応を確認"

        elif title.startswith("点検予定の確認："):
            notification_type = "inspection_plan"
            action_label = "点検計画を確認"

        elif title == "車両点検が未実施です":
            notification_type = "reminder"
            action_label = "点検内容を確認"

        elif title in (
            "安全パトロールが承認されました",
            "チェックリストが承認されました",
            "車両チェックリストが承認されました",
        ):
            notification_type = "approved"
            action_label = "承認結果を確認"

        elif title in (
            "安全チェックリスト完了のお知らせ",
            "車両点検完了のお知らせ",
        ):
            notification_type = "completed"
            action_label = "点検結果を確認"

    action_label = {
        "approval_request": "承認内容を確認",
        "operation_request": "運行判断を確認",
        "operation_result": "判断結果を確認",
        "resubmitted": "変更内容を確認",
        "rejected": "差し戻しを確認",
        "mention": "メンション確認",
        "recheck": "再確認を見る",
        "defect": "不具合を確認",
        "reminder": "点検内容を確認",
        "inspection_plan": "点検計画を確認",
        "periodic_issue": "点検簿の対応を確認",
        "approved": "承認結果を確認",
        "completed": "点検結果を確認",
        "confirmation_request": "内容を確認",
    }.get(notification_type, "内容を確認")

    if notification_type == "recheck":
        event = title.rpartition("：")[2]
        action_label = {
            "再確認待ち": "再確認を見る",
            "再確認で異常あり": "整備を確認",
            "再確認済み・異常なし": "結果を確認",
        }.get(event, action_label)

    return {
        "category": category,
        "category_label": _dkss_common.NOTIFICATION_CATEGORY_LABELS[category],
        "notification_type": notification_type,
        "type_label": _dkss_common.NOTIFICATION_TYPE_LABELS[notification_type],
        "action_label": action_label,
        "summary_message": get_notification_summary(notification),
    }



def get_notification_list_state(current_view=None):
    view = (
        current_view
        if current_view is not None
        else _dkss_common.request.values.get("view", "inbox")
    )

    if view not in ("inbox", "unread", "action", "deleted"):
        view = "inbox"

    category = _dkss_common.request.values.get("category", "")
    notification_type = _dkss_common.request.values.get("type", "")
    search_query = _dkss_common.request.values.get("q", "").strip()[:200]

    if category not in _dkss_common.NOTIFICATION_CATEGORY_LABELS:
        category = ""

    if notification_type not in _dkss_common.NOTIFICATION_TYPE_LABELS:
        notification_type = ""

    return {
        "view": view,
        "category": category,
        "type": notification_type,
        "q": search_query,
    }



def get_notification_workflow_states():
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return {}

    records = _dkss_models.Notification.query.filter(
        _dkss_models.Notification.company_code == company_code,
        _dkss_models.Notification.target_username == username,
        _dkss_models.Notification.deleted_at.is_(None),
        _dkss_models.Notification.workflow_context_json.isnot(None),
        _dkss_models.Notification.workflow_context_json != "{}"
    ).all()

    return {
        str(notification.id): get_notification_workflow_state(notification)
        for notification in records
    }



def get_notification_action_count():
    return sum(
        1
        for state in get_notification_workflow_states().values()
        if state["requires_action"]
    )



def get_unread_notification_count():
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return 0

    return _dkss_models.Notification.query.filter(
        _dkss_models.Notification.company_code == company_code,
        _dkss_models.Notification.target_username == username,
        _dkss_models.Notification.deleted_at.is_(None),
        _dkss_common.db.or_(
            _dkss_models.Notification.read.is_(False),
            _dkss_models.Notification.read.is_(None)
        )
    ).count()



def inject_notification_count():
    return {
        "unread_notification_count":
            get_unread_notification_count()
    }



def notification_recent():
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return _dkss_common.jsonify({"error": "login_required"}), 401

    records = _dkss_models.Notification.query.filter(
        _dkss_models.Notification.company_code == company_code,
        _dkss_models.Notification.target_username == username,
        _dkss_models.Notification.deleted_at.is_(None)
    ).all()
    records = sort_notification_records(records)[:5]

    target_lookup = get_notification_target_lookup(records)
    items = []

    for notification in records:
        display_info = get_notification_display_info(notification)
        workflow_state = get_notification_workflow_state(notification)
        target_info = get_notification_target_info(
            notification, target_lookup
        )

        items.append({
            "id": notification.id,
            "title": str(notification.title or ""),
            "message": display_info["summary_message"],
            "read": bool(notification.read),
            "created_at": str(notification.created_at or ""),
            "time_label": format_notification_datetime(
                notification.created_at, "time"
            ),
            "day_key": format_notification_datetime(
                notification.created_at, "group"
            ),
            "day_label": format_notification_datetime(
                notification.created_at, "group"
            ),
            "category_label": display_info["category_label"],
            "type_label": display_info["type_label"],
            "workflow_label": workflow_state["workflow_label"],
            "workflow_status": workflow_state["workflow_status"],
            "requires_action": workflow_state["requires_action"],
            "target_info": target_info,
            "detail_url": _dkss_common.url_for(
                "notification_detail",
                index=notification.id,
                view="inbox"
            ),
        })

    response = _dkss_common.jsonify({
        "notifications": items,
        "unread_count": get_unread_notification_count(),
        "list_url": _dkss_common.url_for("notifications"),
    })
    response.headers["Cache-Control"] = "no-store"
    return response



def notification_unread_count():
    if not _dkss_common.session.get("company_code") or not _dkss_common.session.get("username"):
        return _dkss_common.jsonify({"error": "login_required"}), 401

    counts = {
        "unread_count": get_unread_notification_count()
    }

    if _dkss_common.request.args.get("include_action") == "1":
        workflow_states = get_notification_workflow_states()

        counts["action_count"] = sum(
            1
            for state in workflow_states.values()
            if state["requires_action"]
        )
        counts["workflow_states"] = workflow_states

    response = _dkss_common.jsonify(counts)
    response.headers["Cache-Control"] = "no-store"
    return response



def get_notification_target_link(notification):
    link = str(notification.link or "").strip()

    if (
        not link.startswith("/")
        or link.startswith("//")
        or "\\" in link
        or any(ord(character) < 32 for character in link)
    ):
        return ""

    if _dkss_serialization.safe_json_dict(notification.workflow_context_json).get('action') == 'inspection_plan_alert':
        link = _dkss_runtime.app.extensions["dkss"]['inspection_alerts'].target_link(notification)

    parsed_link = _dkss_common.urlparse(link)

    if parsed_link.scheme or parsed_link.netloc:
        return ""

    if notification.title == "車両チェックリスト承認依頼":
        match = _dkss_common.re.fullmatch(
            r"/vehicle/checklists/(\d+)/?",
            parsed_link.path
        )

        if match:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=int(match.group(1)),
                company_code=notification.company_code
            ).first()

            if (
                checklist_record
                and _dkss_checklist_common.checklist_to_dict(checklist_record).get(
                    "fixed_template_code"
                ) == "daily_inspection_truck_trailer"
            ):
                parsed_link = parsed_link._replace(
                    fragment="vehicle-flow-judgment"
                )

    return parsed_link.geturl()



def open_notification_target(index):
    list_state = get_notification_list_state()

    notification = _dkss_models.Notification.query.filter(
        _dkss_models.Notification.id == index,
        _dkss_models.Notification.company_code == _dkss_common.session.get("company_code"),
        _dkss_models.Notification.target_username == _dkss_common.session.get("username")
    ).first()

    if not notification:
        return _dkss_common.redirect(_dkss_common.url_for("notifications", **list_state))

    if notification.deleted_at is not None:
        return _dkss_common.redirect(
            _dkss_common.url_for(
                "notification_detail",
                index=index,
                **list_state
            )
        )

    target_link = get_notification_target_link(notification)

    if not target_link:
        _dkss_common.flash(
            "この通知には有効な移動先がありません。",
            "error:"
        )
        return _dkss_common.redirect(_dkss_common.url_for("notifications", **list_state))

    parsed_link = _dkss_common.urlparse(target_link)

    query_parameters = [
        (key, value)
        for key, value in _dkss_common.parse_qsl(
            parsed_link.query,
            keep_blank_values=True
        )
        if key != "_notification_id"
    ]

    query_parameters.append(("_notification_id", str(index)))

    target_link = parsed_link._replace(
        query=_dkss_common.urlencode(query_parameters)
    ).geturl()

    return _dkss_common.redirect(target_link)



def mark_notification_read_after_target_display(response):
    notification_id = _dkss_common.request.args.get(
        "_notification_id",
        type=int
    )

    if (
        _dkss_common.request.method != "GET"
        or response.status_code != 200
        or response.mimetype != "text/html"
        or not notification_id
        or notification_id <= 0
        or notification_id > 2147483647
        or not _dkss_common.session.get("company_code")
        or not _dkss_common.session.get("username")
    ):
        return response

    response.headers["Cache-Control"] = "no-store"

    try:
        notification = _dkss_models.Notification.query.filter(
            _dkss_models.Notification.id == notification_id,
            _dkss_models.Notification.company_code == _dkss_common.session.get("company_code"),
            _dkss_models.Notification.target_username == _dkss_common.session.get("username")
        ).first()

        if (
            not notification
            or notification.deleted_at is not None
            or notification.read
        ):
            return response

        target_link = get_notification_target_link(notification)

        if not target_link:
            return response

        parsed_link = _dkss_common.urlparse(target_link)

        if _dkss_common.request.path != parsed_link.path:
            return response

        expected_parameters = {}

        for key, value in _dkss_common.parse_qsl(
            parsed_link.query,
            keep_blank_values=True
        ):
            if key == "_notification_id":
                continue

            expected_parameters.setdefault(key, []).append(value)

        for key, values in expected_parameters.items():
            if _dkss_common.request.args.getlist(key) != values:
                return response

        notification.read = True
        _dkss_common.db.session.commit()

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception(
            "通知経由で開いたページの既読更新に失敗しました。"
        )

        _dkss_common.flash(
            "通知の既読状態を更新できませんでした。"
            "通知一覧からもう一度お試しください。",
            "error:"
        )

        return _dkss_common.redirect(_dkss_common.url_for("notifications"))

    return response



def sort_notification_records(records, newest=True):
    dated_records = []
    undated_records = []

    for record in records:
        sort_key = format_notification_datetime(
            record.created_at, "sort"
        )

        if sort_key:
            dated_records.append((sort_key, record.id, record))
        else:
            undated_records.append(record)

    dated_records.sort(
        key=lambda entry: entry[:2],
        reverse=newest
    )
    undated_records.sort(key=lambda record: record.id, reverse=newest)

    return [entry[2] for entry in dated_records] + undated_records



def format_notification_datetime(value, mode="detail"):
    text = str(value or "").strip()

    try:
        value_dt = _dkss_common.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        if mode == "key":
            return "unknown"
        if mode in ("day", "group"):
            return "日時不明"
        return ""

    local_now = _dkss_common.request.environ.get("dkss.notification_local_now")
    if local_now is None:
        local_now = _dkss_checklist_common.get_user_local_now(
            _dkss_common.session.get("company_code"),
            _dkss_common.session.get("username")
        )
        _dkss_common.request.environ["dkss.notification_local_now"] = local_now

    if value_dt.tzinfo is not None:
        value_dt = value_dt.astimezone(local_now.tzinfo)

    day = value_dt.date()
    today = local_now.date()
    time_text = value_dt.strftime("%H:%M")

    if mode == "key":
        return day.isoformat()

    if mode == "sort":
        sort_dt = value_dt
        if sort_dt.tzinfo is None:
            sort_dt = sort_dt.replace(tzinfo=local_now.tzinfo)
        return sort_dt.astimezone(_dkss_common.ZoneInfo("UTC")).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )

    if mode == "time":
        return time_text

    if mode == "date":
        return value_dt.strftime("%m/%d")

    if mode == "group":
        if day == today:
            return "今日"
        if day == today - _dkss_common.timedelta(days=1):
            return "昨日"
        if day > today:
            return f"{day.year}年{day.month}月{day.day}日"

        week_start = today - _dkss_common.timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        previous_month_start = (
            month_start - _dkss_common.timedelta(days=1)
        ).replace(day=1)

        if day >= week_start:
            return "今週"
        if day >= week_start - _dkss_common.timedelta(days=7):
            return "先週"
        if day >= month_start:
            return "今月"
        if day >= previous_month_start:
            return "先月"
        return "それ以前"

    if mode == "day":
        if day == today:
            return "今日"
        if day == today - _dkss_common.timedelta(days=1):
            return "昨日"
        if day.year == today.year:
            return f"{day.month}月{day.day}日"
        return f"{day.year}年{day.month}月{day.day}日"

    if mode == "recent":
        if day == today:
            return time_text
        if day == today - _dkss_common.timedelta(days=1):
            return f"昨日 {time_text}"
        if day.year == today.year:
            return f"{day.month}月{day.day}日 {time_text}"
        return f"{day.year}年{day.month}月{day.day}日 {time_text}"

    return f"{day.year}年{day.month}月{day.day}日 {time_text}"



def notifications():
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return _dkss_common.redirect("/")
    current_sort = _dkss_common.request.args.get(
        "sort",
        _dkss_common.session.get("notification_sort", "newest")
    )

    if current_sort not in ("newest", "oldest"):
        current_sort = "newest"

    _dkss_common.session["notification_sort"] = current_sort

    current_view = _dkss_common.request.args.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "inbox"

    selected_category = _dkss_common.request.args.get("category", "")
    selected_type = _dkss_common.request.args.get("type", "")
    search_query = _dkss_common.request.args.get("q", "").strip()[:200]

    if selected_category not in _dkss_common.NOTIFICATION_CATEGORY_LABELS:
        selected_category = ""

    if selected_type not in _dkss_common.NOTIFICATION_TYPE_LABELS:
        selected_type = ""

    query = _dkss_models.Notification.query.filter(
        _dkss_models.Notification.company_code == company_code,
        _dkss_models.Notification.target_username == username
    )

    if current_view == "deleted":
        query = query.filter(
            _dkss_models.Notification.deleted_at.isnot(None)
        )
    else:
        query = query.filter(
            _dkss_models.Notification.deleted_at.is_(None)
        )

        if current_view == "unread":
            query = query.filter(
                _dkss_common.db.or_(
                    _dkss_models.Notification.read.is_(False),
                    _dkss_models.Notification.read.is_(None)
                )
            )

    notification_records = query.order_by(
        _dkss_models.Notification.id.desc()
    ).all()
    notification_records = sort_notification_records(
        notification_records,
        newest=current_sort == "newest"
    )
    target_lookup = get_notification_target_lookup(
        notification_records
    )

    items = []
    search_text = search_query.casefold()

    for notification in notification_records:
        display_info = get_notification_display_info(notification)

        if (
            selected_category
            and display_info["category"] != selected_category
        ):
            continue

        selected_types = {
            "vehicle_approvals": {"approval_request", "resubmitted"},
            "vehicle_response": {
                "operation_request", "operation_result", "confirmation_request",
                "defect", "recheck",
            },
        }.get(selected_type, {selected_type})
        if selected_type and display_info["notification_type"] not in selected_types:
            continue

        target_info = (
            get_notification_target_info(notification, target_lookup)
            or {}
        )

        if search_text:
            searchable_text = "\n".join([
                str(notification.title or ""),
                str(notification.message or ""),
                str(notification.target_user or ""),
                str(get_notification_actor_name(notification) or ""),
                str(target_info.get("checklist_name") or ""),
                str(target_info.get("target_label") or ""),
                str(target_info.get("office") or ""),
                str(target_info.get("period_label") or ""),
            ]).casefold()

            if search_text not in searchable_text:
                continue

        workflow_state = get_notification_workflow_state(notification)

        if (
            current_view == "action"
            and not workflow_state["requires_action"]
        ):
            continue

        items.append({
            "id": notification.id,
            "index": notification.id,
            "target_user": notification.target_user,
            "title": notification.title,
            "message": notification.message,
            "link": notification.link,
            "files": _dkss_serialization.safe_json_str_list(
                notification.files_json
            ),
            "read": notification.read,
            "created_at": notification.created_at,
            "deleted_at": notification.deleted_at,
            "target_info": target_info,
            **display_info,
            **workflow_state,
        })

    return _dkss_common.render_template(
        "notifications.html",
        notifications=items,
        current_sort=current_sort,
        inbox_notification_count=_dkss_models.Notification.query.filter(
            _dkss_models.Notification.company_code == company_code,
            _dkss_models.Notification.target_username == username,
            _dkss_models.Notification.deleted_at.is_(None)
        ).count(),
        action_notification_count=get_notification_action_count(),
        current_view=current_view,
        selected_category=selected_category,
        selected_type=selected_type,
        search_query=search_query,
        category_labels=_dkss_common.NOTIFICATION_CATEGORY_LABELS,
        type_labels=_dkss_common.NOTIFICATION_TYPE_LABELS
    )



def notification_detail(index):
    panel_only = _dkss_common.request.args.get("panel") == "1"

    notification = _dkss_models.Notification.query.filter(
        _dkss_models.Notification.id == index,
        _dkss_models.Notification.company_code == _dkss_common.session.get("company_code"),
        _dkss_models.Notification.target_username == _dkss_common.session.get("username")
    ).first()

    current_view = _dkss_common.request.args.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "inbox"

    if not notification:
        if panel_only:
            return _dkss_common.jsonify({
                "error": "通知が見つかりません。"
            }), 404

        return _dkss_common.redirect(
            _dkss_common.url_for("notifications", **get_notification_list_state(current_view))
        )

    is_deleted = notification.deleted_at is not None

    if is_deleted:
        current_view = "deleted"
    elif current_view == "deleted":
        current_view = "inbox"

    should_mark_as_read = (
        not panel_only
        and not is_deleted
        and not notification.read
    )

    notification_dict = {
        "id": notification.id,
        "index": notification.id,
        "target_user": notification.target_user,
        "actor_name": get_notification_actor_name(notification),
        "title": notification.title,
        "message": notification.message,
        "link": notification.link,
        "files": _dkss_serialization.safe_json_str_list(
            notification.files_json
        ),
        "read": True if should_mark_as_read else notification.read,
        "created_at": notification.created_at,
        "deleted_at": notification.deleted_at,
        **get_notification_display_info(notification),
        **get_notification_workflow_state(notification),
    }

    if notification_dict["title"] == "車両チェックリスト承認依頼":
        link = notification_dict.get("link") or ""
        parsed_link = _dkss_common.urlparse(link)
        match = _dkss_common.re.fullmatch(
            r"/vehicle/checklists/(\d+)/?",
            parsed_link.path
        )

        if match:
            checklist_record = _dkss_models.Checklist.query.filter_by(
                id=int(match.group(1)),
                company_code=_dkss_common.session.get("company_code")
            ).first()

            if (
                checklist_record
                and _dkss_checklist_common.checklist_to_dict(checklist_record).get(
                    "fixed_template_code"
                ) == "daily_inspection_truck_trailer"
            ):
                notification_dict["link"] = parsed_link._replace(
                    fragment="vehicle-flow-judgment"
                ).geturl()

    if not panel_only:
        list_state = get_notification_list_state(current_view)

        if (
            current_view == "unread" and notification.read
        ) or (
            current_view == "action"
            and not notification_dict["requires_action"]
        ):
            list_state["view"] = "inbox"

        return _dkss_common.redirect(_dkss_common.url_for(
            "notifications",
            notification=notification.id,
            **list_state
        ))

    try:
        notification_dict["target_info"] = (
            get_notification_target_info(notification)
        )

        if should_mark_as_read:
            notification.read = True

        rendered_page = _dkss_common.render_template(
            "notification_detail.html",
            notification=notification_dict,
            index=notification.id,
            current_view=current_view,
            list_state=get_notification_list_state(current_view),
            panel_only=panel_only
        )

        if panel_only:
            response = _dkss_common.jsonify({
                "html": rendered_page,
                "notification_id": notification.id,
                "read": bool(notification.read),
                "deleted": is_deleted,
            })
            response.headers["Cache-Control"] = "no-store"
            return response

        if should_mark_as_read:
            _dkss_common.db.session.commit()

        return rendered_page

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        if panel_only:
            return _dkss_common.jsonify({
                "error": "通知を開けませんでした。もう一度お試しください。"
            }), 500
        _dkss_common.flash(
            "通知を開けませんでした。もう一度お試しください。",
            "error:"
        )

        return _dkss_common.redirect(
            _dkss_common.url_for("notifications", **get_notification_list_state(current_view))
        )



def mark_notification_read(index):
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return _dkss_common.jsonify({
            "error": "ログインし直してください。"
        }), 401

    try:
        notification = _dkss_models.Notification.query.filter(
            _dkss_models.Notification.id == index,
            _dkss_models.Notification.company_code == company_code,
            _dkss_models.Notification.target_username == username
        ).with_for_update().first()

        if not notification:
            return _dkss_common.jsonify({
                "error": "通知が見つかりません。"
            }), 404

        if notification.deleted_at is not None:
            return _dkss_common.jsonify({
                "error": "この通知は削除済みです。"
            }), 409

        notification.read = True
        _dkss_common.db.session.flush()

        unread_count = get_unread_notification_count()
        _dkss_common.db.session.commit()

        response = _dkss_common.jsonify({
            "notification_id": index,
            "read": True,
            "unread_count": unread_count,
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("通知の既読処理に失敗しました。")

        return _dkss_common.jsonify({
            "error": "既読にできませんでした。もう一度お試しください。"
        }), 500



def update_notification_popover_delete(index, undo):
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return _dkss_common.jsonify({"error": "ログインし直してください。"}), 401

    deletion_time = None

    if undo:
        payload = _dkss_common.request.get_json(silent=True)
        value = payload.get("deleted_at") if isinstance(payload, dict) else None

        try:
            if not isinstance(value, str) or not value or len(value) > 64:
                raise ValueError()
            deletion_time = _dkss_common.datetime.fromisoformat(value)
            if deletion_time.tzinfo is not None:
                raise ValueError()
        except (TypeError, ValueError):
            return _dkss_common.jsonify({"error": "削除の取り消し情報が正しくありません。"}), 400

    try:
        notification = _dkss_models.Notification.query.filter(
            _dkss_models.Notification.id == index,
            _dkss_models.Notification.company_code == company_code,
            _dkss_models.Notification.target_username == username
        ).with_for_update().first()

        if not notification:
            return _dkss_common.jsonify({"error": "通知が見つかりません。"}), 404

        if undo:
            if notification.deleted_at != deletion_time:
                return _dkss_common.jsonify({"error": "この削除は取り消せません。"}), 409
            notification.deleted_at = None
            audit_action = "notification_delete_undone"
            audit_detail = "通知の削除を取り消し"
        else:
            if notification.deleted_at is not None:
                return _dkss_common.jsonify({"error": "この通知は削除済みです。"}), 409
            notification.deleted_at = _dkss_common.datetime.now(
                _dkss_common.ZoneInfo("UTC")
            ).replace(tzinfo=None)
            audit_action = "notification_deleted"
            audit_detail = "通知を削除済みに移動"

        _dkss_audit.add_audit_log(
            action=audit_action,
            target_type="notification",
            target_id=notification.id,
            detail=f"{audit_detail}: {notification.title}",
            company_code=company_code,
        )
        _dkss_common.db.session.flush()
        unread_count = get_unread_notification_count()
        inbox_count = _dkss_models.Notification.query.filter(
            _dkss_models.Notification.company_code == company_code,
            _dkss_models.Notification.target_username == username,
            _dkss_models.Notification.deleted_at.is_(None)
        ).count()
        deleted_at = notification.deleted_at
        _dkss_common.db.session.commit()

        response = _dkss_common.jsonify({
            "notification_id": index,
            "deleted_at": deleted_at.isoformat() if deleted_at else None,
            "read": bool(notification.read),
            "unread_count": unread_count,
            "inbox_count": inbox_count,
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("最近の通知の削除・取り消しに失敗しました。")
        return _dkss_common.jsonify({
            "error": "通知を更新できませんでした。もう一度お試しください。"
        }), 500



def delete_notification(index):
    current_view = _dkss_common.request.args.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "inbox"

    back_url = _dkss_common.url_for("notifications", **get_notification_list_state(current_view))

    notification = _dkss_models.Notification.query.filter(
        _dkss_models.Notification.id == index,
        _dkss_models.Notification.company_code == _dkss_common.session.get("company_code"),
        _dkss_models.Notification.target_username == _dkss_common.session.get("username")
    ).first()

    if not notification or notification.deleted_at is not None:
        return _dkss_common.redirect(back_url)

    try:
        deleted_at = _dkss_common.datetime.now(
            _dkss_common.ZoneInfo("UTC")
        ).replace(tzinfo=None)

        notification.deleted_at = deleted_at

        _dkss_audit.add_audit_log(
            action="notification_deleted",
            target_type="notification",
            target_id=notification.id,
            detail=f"通知を削除済みに移動: {notification.title}",
            company_code=notification.company_code,
        )

        _dkss_common.db.session.commit()

        _dkss_common.flash(
            {
                "count": 1,
                "deleted_at": deleted_at.isoformat(),
                "view": current_view,
            },
            "notification_deleted"
        )

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("通知の削除処理に失敗しました。")
        _dkss_common.flash(
            "通知を削除できませんでした。もう一度お試しください。",
            "error:"
        )

    return _dkss_common.redirect(back_url)



def restore_notification(index):
    current_view = _dkss_common.request.args.get("view", "deleted")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "deleted"

    back_url = _dkss_common.url_for("notifications", **get_notification_list_state(current_view))

    notification = _dkss_models.Notification.query.filter(
        _dkss_models.Notification.id == index,
        _dkss_models.Notification.company_code == _dkss_common.session.get("company_code"),
        _dkss_models.Notification.target_username == _dkss_common.session.get("username")
    ).first()

    if not notification or notification.deleted_at is None:
        return _dkss_common.redirect(back_url)

    try:
        notification.deleted_at = None

        _dkss_audit.add_audit_log(
            action="notification_restored",
            target_type="notification",
            target_id=notification.id,
            detail=f"通知を受信箱へ復元: {notification.title}",
            company_code=notification.company_code,
        )

        _dkss_common.db.session.commit()

        _dkss_common.flash(
            "1件の通知を受信箱へ戻しました。",
            "notification_success"
        )

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("通知の復元処理に失敗しました。")
        _dkss_common.flash(
            "通知を復元できませんでした。もう一度お試しください。",
            "error:"
        )

    return _dkss_common.redirect(back_url)



def bulk_notifications():
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return _dkss_common.redirect("/")

    current_view = _dkss_common.request.form.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "inbox"

    back_url = _dkss_common.url_for("notifications", **get_notification_list_state(current_view))

    action = _dkss_common.request.form.get("action", "")
    action_labels = {
        "read": "既読にしました",
        "unread": "未読に戻しました",
        "delete": "削除済みに移動しました",
        "restore": "受信箱へ戻しました",
    }

    if action not in action_labels:
        _dkss_common.flash("通知の操作を選択してください。", "error:")
        return _dkss_common.redirect(back_url)

    try:
        notification_ids = list(dict.fromkeys(
            int(value)
            for value in _dkss_common.request.form.getlist("notification_ids")
        ))
    except (ValueError, TypeError):
        _dkss_common.flash("通知の選択内容が正しくありません。", "error:")
        return _dkss_common.redirect(back_url)

    if (
        not notification_ids
        or any(
            value <= 0 or value > 2147483647
            for value in notification_ids
        )
    ):
        _dkss_common.flash("操作する通知を選択してください。", "error:")
        return _dkss_common.redirect(back_url)

    if len(notification_ids) > 500:
        _dkss_common.flash("一度に操作できる通知は500件までです。", "error:")
        return _dkss_common.redirect(back_url)

    try:
        records = _dkss_models.Notification.query.filter(
            _dkss_models.Notification.company_code == company_code,
            _dkss_models.Notification.target_username == username,
            _dkss_models.Notification.id.in_(notification_ids)
        ).order_by(
            _dkss_models.Notification.id.asc()
        ).with_for_update().all()

        deleted_at = _dkss_common.datetime.now(
            _dkss_common.ZoneInfo("UTC")
        ).replace(tzinfo=None)

        changed_count = 0

        for notification in records:
            before = (
                notification.read,
                notification.deleted_at
            )

            if action == "read":
                if notification.deleted_at is not None:
                    continue
                notification.read = True

            elif action == "unread":
                notification.deleted_at = None
                notification.read = False

            elif action == "delete":
                if notification.deleted_at is not None:
                    continue
                notification.deleted_at = deleted_at

            elif action == "restore":
                notification.deleted_at = None

            after = (
                notification.read,
                notification.deleted_at
            )

            if before == after:
                continue

            changed_count += 1

            _dkss_audit.add_audit_log(
                action=f"notification_bulk_{action}",
                target_type="notification",
                target_id=notification.id,
                detail=f"通知の一括操作: {notification.title}",
                company_code=company_code,
            )

        _dkss_common.db.session.commit()

        if action == "delete" and changed_count:
            _dkss_common.flash(
                {
                    "count": changed_count,
                    "deleted_at": deleted_at.isoformat(),
                    "view": current_view,
                },
                "notification_deleted"
            )
        else:
            _dkss_common.flash(
                f"{changed_count}件の通知を"
                f"{action_labels[action]}。",
                "notification_success"
            )

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("通知の一括操作に失敗しました。")
        _dkss_common.flash(
            "通知を更新できませんでした。もう一度お試しください。",
            "error:"
        )

    return _dkss_common.redirect(back_url)



def mark_all_notifications_read():
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return _dkss_common.redirect("/")

    current_view = _dkss_common.request.form.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action"):
        current_view = "inbox"

    back_url = _dkss_common.url_for("notifications", **get_notification_list_state(current_view))

    try:
        records = _dkss_models.Notification.query.filter(
            _dkss_models.Notification.company_code == company_code,
            _dkss_models.Notification.target_username == username,
            _dkss_models.Notification.deleted_at.is_(None),
            _dkss_common.db.or_(
                _dkss_models.Notification.read.is_(False),
                _dkss_models.Notification.read.is_(None)
            )
        ).order_by(
            _dkss_models.Notification.id.asc()
        ).with_for_update().all()

        changed_count = len(records)

        for notification in records:
            notification.read = True

        if changed_count:
            _dkss_audit.add_audit_log(
                action="notification_read_all",
                target_type="notification",
                detail=f"受信箱の未読通知{changed_count}件を既読に変更",
                company_code=company_code,
            )

        _dkss_common.db.session.commit()

        _dkss_common.flash(
            f"{changed_count}件の通知を既読にしました。",
            "notification_success"
        )

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("通知の一括既読処理に失敗しました。")
        _dkss_common.flash(
            "通知を既読にできませんでした。もう一度お試しください。",
            "error:"
        )

    return _dkss_common.redirect(back_url)



def undo_notification_delete():
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return _dkss_common.redirect("/")

    current_view = _dkss_common.request.form.get("view", "inbox")

    if current_view not in ("inbox", "unread", "action", "deleted"):
        current_view = "inbox"

    back_url = _dkss_common.url_for("notifications", **get_notification_list_state(current_view))

    deletion_time = _dkss_common.request.form.get("deleted_at", "")

    try:
        if not deletion_time or len(deletion_time) > 64:
            raise ValueError()

        deleted_at = _dkss_common.datetime.fromisoformat(deletion_time)

        if deleted_at.tzinfo is not None:
            raise ValueError()

    except (ValueError, TypeError):
        _dkss_common.flash(
            "削除の取り消し情報が正しくありません。",
            "error:"
        )
        return _dkss_common.redirect(back_url)

    try:
        records = _dkss_models.Notification.query.filter(
            _dkss_models.Notification.company_code == company_code,
            _dkss_models.Notification.target_username == username,
            _dkss_models.Notification.deleted_at == deleted_at
        ).order_by(
            _dkss_models.Notification.id.asc()
        ).with_for_update().all()

        restored_count = len(records)

        for notification in records:
            notification.deleted_at = None

            _dkss_audit.add_audit_log(
                action="notification_delete_undone",
                target_type="notification",
                target_id=notification.id,
                detail=f"通知の削除を取り消し: {notification.title}",
                company_code=company_code,
            )

        _dkss_common.db.session.commit()

        _dkss_common.flash(
            f"{restored_count}件の通知を受信箱へ戻しました。",
            "notification_success"
        )

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("通知の削除取り消しに失敗しました。")
        _dkss_common.flash(
            "削除を取り消せませんでした。もう一度お試しください。",
            "error:"
        )

    return _dkss_common.redirect(back_url)
