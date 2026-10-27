"""Vehicle Documents responsibilities; routes are registered by the application factory."""
from . import access as _dkss_access, common as _dkss_common, http as _dkss_http, maintenance as _dkss_maintenance, models as _dkss_models, runtime as _dkss_runtime, serialization as _dkss_serialization, vehicle_imports as _dkss_vehicle_imports, vehicle_pending as _dkss_vehicle_pending, vehicle_readers as _dkss_vehicle_readers


def vehicle_maintenance_document_duplicate(document_id):
    if not _dkss_access.require_master_admin():
        return "この操作は管理者のみ利用できます。", 403

    if _dkss_common.request.form.get("already_recorded") != "1":
        return _dkss_http.return_form_errors([(
            "費用・交換内容がすべて登録済みであることを確認してください。",
            "already_recorded"
        )])

    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")
    if not company_code or not username:
        return "会社・利用者を確認できません。", 403

    try:
        company = _dkss_models.Company.query.filter_by(
            company_code=company_code
        ).with_for_update().first()
        if company is None:
            raise _dkss_common.UploadValidationError("会社情報を確認できません。")

        document = _dkss_models.VehicleMaintenanceDocument.query.filter_by(
            id=document_id, company_code=company_code
        ).with_for_update().populate_existing().first_or_404()

        vehicle = _dkss_models.Vehicle.query.filter_by(
            id=document.vehicle_record_id,
            company_code=company_code
        ).first_or_404()

        model = (
            _dkss_models.VehicleMaintenanceRecord
            if document.maintenance_record_id is not None
            else _dkss_models.VehiclePeriodicInspectionRecord
        )
        target_id = (
            document.maintenance_record_id
            or document.inspection_record_id
        )
        model.query.filter_by(
            id=target_id,
            company_code=company_code,
            vehicle_record_id=vehicle.id
        ).first_or_404()

        draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
            id=document.source_draft_id,
            company_code=company_code,
            document_type="maintenance",
            status="completed"
        ).first_or_404()

        if _dkss_common.hashlib.sha256(draft.source_file).hexdigest() != draft.source_sha256:
            raise _dkss_common.UploadValidationError("保存済みの原本を確認できません。")

        if document.financial_status not in {"pending", "duplicate"}:
            raise _dkss_common.UploadValidationError(
                "費用の確定状態が変わっています。一覧から再確認してください。"
            )

        if document.financial_status == "pending" or document.parts_status == "pending":
            decision = _dkss_common.json.loads(document.decision_json or "{}")
            if not isinstance(decision, dict) or not isinstance(
                decision.get("review_history", []), list
            ):
                raise _dkss_common.UploadValidationError("確認履歴を読み取れません。")

            now = _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC"))
            history = list(decision.get("review_history", []))
            history.append({
                "action": "already_recorded",
                "financial_status_before": document.financial_status,
                "parts_status_before": document.parts_status,
                "username": username,
                "reviewed_at": now.isoformat(),
            })

            document.financial_status = "duplicate"
            if document.parts_status == "pending":
                document.parts_status = "not_applicable"

            document.decision_json = _dkss_common.json.dumps({
                **decision,
                "review_history": history,
                "review_action": "already_recorded",
            }, ensure_ascii=False)
            document.reviewed_by_username = username
            document.reviewed_at = now

        if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
            _dkss_common.db.session.rollback()
            return _dkss_common.jsonify({"ok": True})

        _dkss_common.db.session.commit()

    except (_dkss_common.UploadValidationError, ValueError) as error:
        _dkss_common.db.session.rollback()
        return _dkss_http.return_form_errors([(str(error), "")])
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("請求書の確認結果を保存できませんでした。")
        return _dkss_http.return_form_errors([
            ("確認結果を保存できませんでした。再度お試しください。", "")
        ], status_code=500)

    _dkss_common.flash(
        "登録済みの内容として確認しました。原本を残し、費用・交換回数は追加していません。",
        "success"
    )
    return _dkss_common.redirect(_dkss_common.url_for("vehicle_maintenance_document_reviews"))



def vehicle_maintenance_document_initial_cost(document_id):
    return review_vehicle_maintenance_document_cost(document_id, "initial_cost")



def vehicle_maintenance_document_correction(document_id):
    return review_vehicle_maintenance_document_cost(document_id, "correction")



def calculate_vehicle_invoice_correction(target, replacement_id, incoming_amounts):
    fields = ("labor_cost", "parts_cost", "other_cost", "tax_amount", "total_cost")

    def parse_costs(values):
        if not isinstance(values, dict) or any(field not in values for field in fields):
            raise ValueError("請求額の確認履歴が不足しています。")
        costs = {}
        for field in fields:
            raw = values[field]
            value = None if raw is None else _dkss_common.Decimal(str(raw))
            if value is not None and (
                not value.is_finite() or abs(value) > _dkss_common.Decimal("999999999999.99")
                or value != value.quantize(_dkss_common.Decimal("0.01"))
            ):
                raise ValueError("請求額の確認履歴が不正です。")
            costs[field] = value
        return costs

    ledger = []
    for old in _dkss_models.VehicleMaintenanceDocument.query.filter(
        _dkss_models.VehicleMaintenanceDocument.company_code == target.company_code,
        _dkss_models.VehicleMaintenanceDocument.vehicle_record_id == target.vehicle_record_id,
        _dkss_models.VehicleMaintenanceDocument.maintenance_record_id == target.id,
        _dkss_models.VehicleMaintenanceDocument.financial_status.in_(("confirmed", "superseded"))
    ).with_for_update().populate_existing().all():
        decision = _dkss_common.json.loads(old.decision_json or "{}")
        if not isinstance(decision, dict) or decision.get("costs_applied") is not True:
            raise ValueError("費用の反映履歴を確認できません。")
        costs = parse_costs(decision.get("confirmed_costs"))
        history = decision.get("review_history")
        if not isinstance(history, list) or not all(isinstance(item, dict) for item in history):
            raise ValueError("費用の確認履歴が不正です。")
        actions = [item for item in history if item.get("action") in {
            "initial_cost", "additional_cost", "correction"
        }]
        if len(actions) != 1 or costs["total_cost"] is None:
            raise ValueError("費用の確認履歴が不足しています。")
        when = _dkss_common.datetime.fromisoformat(actions[0]["reviewed_at"])
        if when.tzinfo is None:
            raise ValueError("費用の確認日時が不正です。")
        ledger.append((when, old, decision, costs, actions[0]["action"]))
    if not ledger:
        raise ValueError("差し替え可能な確定済み請求書がありません。")
    ledger.sort(key=lambda item: (item[0], item[1].id))
    first = ledger[0]
    if first[4] == "initial_cost":
        baseline = {field: _dkss_common.Decimal("0") for field in fields}
    elif first[4] == "additional_cost":
        baseline = parse_costs(first[2].get("costs_before"))
        if baseline["total_cost"] is None:
            raise ValueError("請求書の反映前の費用を確認できません。")
    else:
        raise ValueError("最初の費用の反映履歴を確認できません。")
    active = [item for item in ledger if item[1].financial_status == "confirmed"]
    selected = next((item for item in active if item[1].id == replacement_id), None)
    if selected is None:
        raise ValueError("訂正前の請求書は確認状態が変わっています。選び直してください。")
    if any(item[4] == "initial_cost" for item in ledger[1:]):
        raise ValueError("初回費用の履歴が重複しています。")

    def aggregate(invoices):
        result = {}
        for field in fields:
            values = [baseline[field]] + [costs[field] for costs in invoices]
            result[field] = None if any(value is None for value in values) else sum(values, _dkss_common.Decimal("0"))
            if result[field] is not None and abs(result[field]) > _dkss_common.Decimal("999999999999.99"):
                raise ValueError("訂正後の費用が登録可能な金額を超えます。")
        return result

    current = aggregate([item[3] for item in active])
    if any(current[field] != getattr(target, field) for field in fields):
        raise ValueError("登録済み費用と請求書の履歴が一致しません。費用を再確認してください。")
    old = selected[1]
    draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
        id=old.source_draft_id, company_code=target.company_code,
        document_type="maintenance", status="completed"
    ).first()
    if draft is None or _dkss_common.hashlib.sha256(draft.source_file).hexdigest() != draft.source_sha256:
        raise ValueError("訂正前の原本を確認できません。")
    payload = _dkss_common.json.loads(old.payload_json)
    records = _dkss_serialization.safe_json_dict(draft.preview_json).get("records")
    index = old.source_record_index
    if (not isinstance(payload, dict) or not isinstance(records, list)
            or type(index) is not int or not 0 <= index < len(records)
            or records[index] != payload):
        raise ValueError("訂正前の明細を確認できません。")
    source_costs = parse_costs({
        field: None if payload.get(field) in (None, "") else payload[field]
        for field in fields
    })
    if source_costs != selected[3]:
        raise ValueError("訂正前の請求額と反映履歴が一致しません。")
    return aggregate([
        item[3] for item in active if item[1].id != replacement_id
    ] + [incoming_amounts]), old



def review_vehicle_maintenance_document_cost(document_id, cost_mode):
    if not _dkss_access.require_master_admin():
        return "この操作は管理者のみ利用できます。", 403
    if cost_mode not in {"initial_cost", "additional_cost", "correction"}:
        return "確認方法が不正です。", 400
    confirm_field = "confirm_" + cost_mode
    if _dkss_common.request.form.get(confirm_field) != "1":
        return _dkss_http.return_form_errors([("請求額の反映方法を確認してください。", confirm_field)])
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")
    if not company_code or not username:
        return "会社・利用者を確認できません。", 403
    try:
        if _dkss_models.Company.query.filter_by(company_code=company_code).with_for_update().first() is None:
            raise ValueError("会社情報を確認できません。")
        document = _dkss_models.VehicleMaintenanceDocument.query.filter_by(
            id=document_id, company_code=company_code
        ).with_for_update().populate_existing().first_or_404()
        _dkss_models.Vehicle.query.filter_by(
            id=document.vehicle_record_id, company_code=company_code
        ).first_or_404()
        if document.financial_status != "pending" or document.maintenance_record_id is None:
            raise ValueError("費用の確定状態・登録先を一覧から再確認してください。")
        target = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
            id=document.maintenance_record_id, company_code=company_code,
            vehicle_record_id=document.vehicle_record_id
        ).with_for_update().populate_existing().first_or_404()
        fields = ("labor_cost", "parts_cost", "other_cost", "tax_amount", "total_cost")
        if cost_mode == "initial_cost":
            if any(getattr(target, field) is not None for field in fields) or _dkss_models.VehicleMaintenanceDocument.query.filter_by(
                company_code=company_code, maintenance_record_id=target.id,
                financial_status="confirmed"
            ).first() is not None:
                raise ValueError("登録済みの費用があります。追加請求・訂正として確認してください。")
        else:
            if target.total_cost is None:
                raise ValueError("追加先の合計金額がありません。初回費用として確認してください。")
            expected_total = _dkss_common.Decimal(_dkss_common.request.form.get("expected_total", ""))
            if not expected_total.is_finite() or expected_total != target.total_cost:
                raise ValueError("登録済みの金額が変わりました。一覧を開き直してください。")
        draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
            id=document.source_draft_id, company_code=company_code,
            document_type="maintenance", status="completed"
        ).first_or_404()
        if _dkss_common.hashlib.sha256(draft.source_file).hexdigest() != draft.source_sha256:
            raise ValueError("保存済みの原本を確認できません。")
        payload = _dkss_common.json.loads(document.payload_json)
        records = _dkss_serialization.safe_json_dict(draft.preview_json).get("records")
        index = document.source_record_index
        if (not isinstance(payload, dict) or not isinstance(records, list)
                or type(index) is not int or not 0 <= index < len(records)
                or records[index] != payload
                or payload.get("vehicle_record_id") not in (None, document.vehicle_record_id)):
            raise ValueError("保存済み明細の一致を確認できません。")
        incoming = _dkss_vehicle_imports.build_vehicle_document_record(draft, index, {
            **payload, "vehicle_record_id": document.vehicle_record_id
        })
        amounts = {field: getattr(incoming, field) for field in fields}
        if amounts["total_cost"] is None or any(
            value is not None and value < 0 for value in amounts.values()
        ):
            raise ValueError("合計金額がない資料・マイナス金額は、初回費用として確定できません。")
        components = [amounts[field] for field in fields[:-1]]
        if all(value is not None for value in components) and sum(components) != amounts["total_cost"]:
            raise ValueError("内訳と合計金額が一致しません。原本を確認してください。")
        decision = _dkss_common.json.loads(document.decision_json or "{}")
        if not isinstance(decision, dict) or not isinstance(
            decision.get("review_history", []), list
        ):
            raise ValueError("確認履歴を読み取れません。")
        now = _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC"))
        before_costs = {field: getattr(target, field) for field in fields}
        confirmed_costs = {
            field: str(value) if value is not None else None
            for field, value in amounts.items()
        }
        replaced_document = None
        if cost_mode == "correction":
            amounts, replaced_document = calculate_vehicle_invoice_correction(
                target, _dkss_common.request.form.get("replaces_document_id", ""), amounts
            )
        elif cost_mode == "additional_cost":
            amounts = {
                field: before_costs[field] + amounts[field]
                if before_costs[field] is not None and amounts[field] is not None
                else None
                for field in fields
            }
            if any(value is not None and abs(value) > _dkss_common.Decimal("999999999999.99")
                   for value in amounts.values()):
                raise ValueError("加算後の費用が登録可能な金額を超えます。")
        changes = []
        for field, value in amounts.items():
            setattr(target, field, value)
            if before_costs[field] != value:
                changes.append({
                    "field": field,
                    "before": str(before_costs[field]) if before_costs[field] is not None else None,
                    "after": str(value) if value is not None else None,
                })
        if incoming.cost_office and not target.cost_office:
            changes.append({"field": "cost_office", "before": None, "after": incoming.cost_office})
            target.cost_office = incoming.cost_office
        target.updated_by_username = username
        target.updated_at = _dkss_common.datetime.now(
            _dkss_common.ZoneInfo("Asia/Tokyo")
        ).isoformat(timespec="seconds")
        _dkss_maintenance.add_vehicle_maintenance_record_event(
            target, action="updated", changes=changes
        )
        document.financial_status = "confirmed"
        if replaced_document is not None:
            document.related_document_id = replaced_document.id
            old_decision = _dkss_common.json.loads(replaced_document.decision_json)
            replaced_document.financial_status = "superseded"
            replaced_document.decision_json = _dkss_common.json.dumps({
                **old_decision,
                "replaced_by_document_id": document.id,
                "review_history": old_decision["review_history"] + [{
                    "action": "superseded", "replacement_document_id": document.id,
                    "username": username, "reviewed_at": now.isoformat(),
                }],
            }, ensure_ascii=False)
            replaced_document.reviewed_by_username = username
            replaced_document.reviewed_at = now
        document.decision_json = _dkss_common.json.dumps({
            **decision,
            "costs_applied": True,
            "review_action": cost_mode,
            "cost_record_id": target.id,
            "confirmed_costs": confirmed_costs,
            "costs_before": {
                field: str(value) if value is not None else None
                for field, value in before_costs.items()
            },
            "costs_after": {
                field: str(value) if value is not None else None
                for field, value in amounts.items()
            },
            "review_history": decision.get("review_history", []) + [{
                "action": cost_mode,
                "username": username,
                "reviewed_at": now.isoformat()
            }],
        }, ensure_ascii=False)
        document.reviewed_by_username = username
        document.reviewed_at = now
        if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
            _dkss_common.db.session.rollback()
            return _dkss_common.jsonify({"ok": True})
        _dkss_common.db.session.commit()
    except (ValueError, KeyError, TypeError, _dkss_common.InvalidOperation) as error:
        _dkss_common.db.session.rollback()
        return _dkss_http.return_form_errors([(
            "請求書の金額・明細・確認状態を確認してください。 " + str(error), ""
        )])
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("初回の請求費用を保存できませんでした。")
        return _dkss_http.return_form_errors([(
            "費用を保存できませんでした。再度お試しください。", ""
        )], status_code=500)
    _dkss_common.flash(
        "請求額を反映しました。交換部品の確認状態はそのまま保持しています。",
        "success"
    )
    return _dkss_common.redirect(_dkss_common.url_for("vehicle_maintenance_document_reviews"))



def vehicle_maintenance_document_additional_cost(document_id):
    return review_vehicle_maintenance_document_cost(document_id, "additional_cost")



def vehicle_invoice_parts_version(parts):
    return _dkss_common.hashlib.sha256(_dkss_common.json.dumps([
        [part.id, part.part_name, part.part_number, str(part.quantity),
         part.replacement_date, str(part.mileage), str(part.cost)]
        for part in sorted(parts, key=lambda item: item.id)
    ], ensure_ascii=False).encode("utf-8")).hexdigest()



def vehicle_maintenance_document_parts(document_id):
    if not _dkss_access.require_master_admin():
        return "この操作は管理者のみ利用できます。", 403
    if _dkss_common.request.form.get("confirm_parts") != "1":
        return _dkss_http.return_form_errors([("原本と交換履歴を確認してください。", "confirm_parts")])
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")
    if not company_code or not username:
        return "会社・利用者を確認できません。", 403
    try:
        if _dkss_models.Company.query.filter_by(company_code=company_code).with_for_update().first() is None:
            raise ValueError("会社情報を確認できません。")
        document = _dkss_models.VehicleMaintenanceDocument.query.filter_by(
            id=document_id, company_code=company_code
        ).with_for_update().populate_existing().first_or_404()
        if (document.parts_status != "pending" or document.maintenance_record_id is None
                or document.financial_status not in {"pending", "confirmed", "superseded"}):
            raise ValueError("部品の確認状態・登録先を一覧から再確認してください。")
        _dkss_models.Vehicle.query.filter_by(id=document.vehicle_record_id, company_code=company_code).first_or_404()
        target = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
            id=document.maintenance_record_id, company_code=company_code,
            vehicle_record_id=document.vehicle_record_id
        ).with_for_update().populate_existing().first_or_404()
        draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
            id=document.source_draft_id, company_code=company_code,
            document_type="maintenance", status="completed"
        ).first_or_404()
        if _dkss_common.hashlib.sha256(draft.source_file).hexdigest() != draft.source_sha256:
            raise ValueError("保存済みの原本を確認できません。")
        payload = _dkss_common.json.loads(document.payload_json)
        records = _dkss_serialization.safe_json_dict(draft.preview_json).get("records")
        index = document.source_record_index
        if (not isinstance(payload, dict) or not isinstance(records, list)
                or type(index) is not int or not 0 <= index < len(records)
                or records[index] != payload
                or payload.get("vehicle_record_id") not in (None, document.vehicle_record_id)):
            raise ValueError("保存済み明細の一致を確認できません。")
        lines = payload.get("line_items") or []
        if not isinstance(lines, list) or len(lines) > 1000 or not all(isinstance(line, dict) for line in lines):
            raise ValueError("請求書の明細を確認できません。")
        parts = _dkss_models.VehiclePartReplacement.query.filter_by(
            company_code=company_code, vehicle_record_id=target.vehicle_record_id,
            maintenance_record_id=target.id
        ).with_for_update().populate_existing().all()
        if _dkss_common.request.form.get("parts_version") != vehicle_invoice_parts_version(parts):
            raise ValueError("交換履歴が変わりました。一覧を開き直してください。")
        decision = _dkss_common.json.loads(document.decision_json or "{}")
        if not isinstance(decision, dict) or not isinstance(decision.get("review_history", []), list):
            raise ValueError("確認履歴を読み取れません。")

        def number(raw, required=False):
            if raw is None or str(raw).strip() == "":
                if required:
                    raise ValueError("新規の交換には数量が必要です。")
                return None
            if isinstance(raw, bool) or len(str(raw)) > 100:
                raise ValueError("部品の数値を確認してください。")
            value = _dkss_vehicle_imports.parse_maintenance_invoice_number(raw)
            if (not value.is_finite() or value < 0 or abs(value) > _dkss_common.Decimal("999999999999.99")
                    or value != value.quantize(_dkss_common.Decimal("0.01"))):
                raise ValueError("部品の数値を確認してください。")
            return value

        now = _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC"))
        confirmed = []
        created_count = 0
        import unicodedata
        normalize = lambda value: "".join(unicodedata.normalize("NFKC", value or "").split()).casefold()
        for line_index, line in enumerate(lines):
            action = _dkss_common.request.form.get("part_choice_" + str(line_index), "")
            if action == "none":
                confirmed.append({"source_line_index": line_index, "action": "not_replace"})
                continue
            if action.startswith("existing:"):
                existing_id = int(action.split(":", 1)[1])
                part = next((item for item in parts if item.id == existing_id), None)
                if part is None:
                    raise ValueError("同じ整備の交換履歴を選択してください。")
            elif action == "new":
                name = _dkss_common.request.form.get("part_name_" + str(line_index), "").strip()
                part_number = _dkss_common.request.form.get("part_number_" + str(line_index), "").strip()
                if not name or len(name) > 200 or len(part_number) > 100:
                    raise ValueError("新規の交換には部品名が必要です。名称・品番の文字数も確認してください。")
                quantity = number(_dkss_common.request.form.get("part_quantity_" + str(line_index)), required=True)
                if quantity <= 0:
                    raise ValueError("交換数量は0より大きい数値で入力してください。")
                replacement_date = _dkss_common.request.form.get("replacement_date", "")
                if _dkss_common.datetime.strptime(replacement_date, "%Y-%m-%d").date().isoformat() != replacement_date:
                    raise ValueError("交換日を確認してください。")
                if any(item.replacement_date == replacement_date and (
                    normalize(item.part_number) == normalize(part_number)
                    if item.part_number and part_number
                    else normalize(item.part_name) == normalize(name)
                ) for item in parts):
                    raise ValueError("同じ日・同じ部品の交換履歴があります。登録済みの交換を選んでください。別の交換の場合はカルテで内容を確認してください。")
                part = _dkss_models.VehiclePartReplacement(
                    company_code=company_code, vehicle_record_id=target.vehicle_record_id,
                    maintenance_record_id=target.id, part_name=name,
                    part_number=part_number or None, quantity=quantity,
                    replacement_date=replacement_date,
                    mileage=number(_dkss_common.request.form.get("replacement_mileage")),
                    cost=number(line.get("parts_amount")),
                    notes="請求書の確認から登録（明細" + str(line_index + 1) + "）",
                    created_by_username=username,
                    created_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds"),
                )
                _dkss_common.db.session.add(part)
                _dkss_common.db.session.flush()
                parts.append(part)
                created_count += 1
            else:
                raise ValueError("すべての明細で、登録済み・新規交換・交換対象外のいずれかを選んでください。")
            confirmed.append({
                "source_line_index": line_index, "action": action,
                "replacement_id": part.id, "part_name": part.part_name,
                "part_number": part.part_number, "quantity": str(part.quantity),
                "replacement_date": part.replacement_date,
            })
        document.parts_status = "confirmed" if any("replacement_id" in item for item in confirmed) else "not_applicable"
        document.decision_json = _dkss_common.json.dumps({
            **decision, "parts_applied": created_count > 0,
            "confirmed_parts": confirmed,
            "review_history": decision.get("review_history", []) + [{
                "action": "parts_review", "username": username,
                "reviewed_at": now.isoformat(), "created_count": created_count,
            }],
        }, ensure_ascii=False)
        document.reviewed_by_username = username
        document.reviewed_at = now
        if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
            _dkss_common.db.session.rollback()
            return _dkss_common.jsonify({"ok": True})
        _dkss_common.db.session.commit()
    except (ValueError, KeyError, TypeError, _dkss_common.InvalidOperation) as error:
        _dkss_common.db.session.rollback()
        return _dkss_http.return_form_errors([("交換部品を確認してください。 " + str(error), "")])
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("請求書の交換部品を保存できませんでした。")
        return _dkss_http.return_form_errors([("交換部品を保存できませんでした。再度お試しください。", "")], status_code=500)
    _dkss_common.flash("交換部品を確認しました。新規登録は" + str(created_count) + "件です。費用は変更していません。", "success")
    return _dkss_common.redirect(_dkss_common.url_for("vehicle_maintenance_document_reviews"))



def vehicle_maintenance_document_reviews():
    if not _dkss_access.require_master_admin():
        return "この操作は管理者のみ利用できます。", 403

    company_code = _dkss_common.session.get("company_code")
    query = _dkss_common.db.session.query(
        _dkss_models.VehicleMaintenanceDocument, _dkss_models.Vehicle, _dkss_models.VehicleDocumentImportDraft
    ).join(
        _dkss_models.Vehicle,
        _dkss_common.db.and_(
            _dkss_models.Vehicle.id == _dkss_models.VehicleMaintenanceDocument.vehicle_record_id,
            _dkss_models.Vehicle.company_code == company_code
        )
    ).join(
        _dkss_models.VehicleDocumentImportDraft,
        _dkss_common.db.and_(
            _dkss_models.VehicleDocumentImportDraft.id == _dkss_models.VehicleMaintenanceDocument.source_draft_id,
            _dkss_models.VehicleDocumentImportDraft.company_code == company_code
        )
    ).filter(
        _dkss_models.VehicleMaintenanceDocument.company_code == company_code,
        _dkss_common.or_(
            _dkss_models.VehicleMaintenanceDocument.financial_status == "pending",
            _dkss_common.db.and_(
                _dkss_models.VehicleMaintenanceDocument.financial_status.in_(("confirmed", "superseded")),
                _dkss_models.VehicleMaintenanceDocument.parts_status == "pending"
            )
        )
    )

    total = query.count()
    total_pages = max(1, (total + 9) // 10)
    page = max(1, min(
        _dkss_common.request.args.get("page", 1, type=int), total_pages
    ))
    rows = []

    for document, vehicle, draft in query.order_by(
        _dkss_models.VehicleMaintenanceDocument.created_at.desc(),
        _dkss_models.VehicleMaintenanceDocument.id.asc()
    ).offset((page - 1) * 10).limit(10).all():
        is_maintenance = document.maintenance_record_id is not None
        model = (
            _dkss_models.VehicleMaintenanceRecord if is_maintenance
            else _dkss_models.VehiclePeriodicInspectionRecord
        )
        target_id = (
            document.maintenance_record_id if is_maintenance
            else document.inspection_record_id
        )
        target = model.query.filter_by(
            id=target_id,
            company_code=company_code,
            vehicle_record_id=vehicle.id
        ).first()
        if target is None:
            continue

        replacement_parts = _dkss_models.VehiclePartReplacement.query.filter_by(
            company_code=company_code, vehicle_record_id=vehicle.id,
            maintenance_record_id=target.id
        ).order_by(_dkss_models.VehiclePartReplacement.id).all() if is_maintenance else []
        rows.append({
            "parts_review_available": is_maintenance and document.parts_status == "pending",
            "replacement_parts": replacement_parts,
            "parts_version": vehicle_invoice_parts_version(replacement_parts),
            "id": document.id,
            "vehicle_id": vehicle.id,
            "vehicle_number": _dkss_vehicle_readers.vehicle_number({
                "plate_area": vehicle.plate_area or "",
                "plate_class": vehicle.plate_class or "",
                "plate_kana": vehicle.plate_kana or "",
                "plate_number": vehicle.plate_number or "",
            }),
            "office": vehicle.office or "未設定",
            "draft_id": draft.id,
            "filename": draft.source_filename,
            "record_index": document.source_record_index,
            "payload": _dkss_serialization.safe_json_dict(document.payload_json),
            "target_kind": "整備記録" if is_maintenance else "点検記録",
            "target_date": (
                target.entry_date if is_maintenance
                else target.inspection_date
            ),
            "target_content": target.content or "",
            "existing_total": target.total_cost if is_maintenance else None,
            "financial_label": "訂正前（費用は集計対象外）" if document.financial_status == "superseded"
                else "確認待ち" if document.financial_status == "pending" else "確認済み",
            "correction_candidates": [{
                "id": previous.id,
                "invoice_number": _dkss_serialization.safe_json_dict(previous.payload_json).get("invoice_number") or "番号なし",
                "total_cost": _dkss_serialization.safe_json_dict(previous.payload_json).get("total_cost"),
                "draft_id": previous.source_draft_id,
            } for previous in _dkss_models.VehicleMaintenanceDocument.query.filter_by(
                company_code=company_code, vehicle_record_id=vehicle.id,
                maintenance_record_id=target.id, financial_status="confirmed"
            ).order_by(_dkss_models.VehicleMaintenanceDocument.created_at, _dkss_models.VehicleMaintenanceDocument.id).all()
              if _dkss_serialization.safe_json_dict(previous.decision_json).get("costs_applied") is True]
                if is_maintenance and document.financial_status == "pending" and target.total_cost is not None else [],
            "can_additional_cost": is_maintenance and document.financial_status == "pending"
                and target.total_cost is not None
                and _dkss_serialization.safe_json_dict(document.payload_json).get("total_cost") not in (None, ""),
            "can_initial_cost": is_maintenance and document.financial_status == "pending"
                and all(getattr(target, field) is None for field in (
                    "labor_cost", "parts_cost", "other_cost", "tax_amount", "total_cost"
                )) and _dkss_serialization.safe_json_dict(document.payload_json).get("total_cost") not in (None, ""),
            "financial_pending": document.financial_status == "pending",
            "parts_pending": document.parts_status == "pending",
        })

    return _dkss_common.render_template(
        "vehicle_master.html",
        invoice_review_rows=rows,
        invoice_review_count=total,
        invoice_review_page=page,
        invoice_review_total_pages=total_pages,
        pending_vehicle_count=_dkss_vehicle_pending.vehicle_import_pending_query(company_code).count(),
    )
