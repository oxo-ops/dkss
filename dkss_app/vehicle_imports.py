"""Vehicle Imports responsibilities; routes are registered by the application factory."""
from . import access as _dkss_access, common as _dkss_common, http as _dkss_http, maintenance as _dkss_maintenance, master_readers as _dkss_master_readers, models as _dkss_models, runtime as _dkss_runtime, serialization as _dkss_serialization, storage as _dkss_storage, vehicle_karte as _dkss_vehicle_karte, vehicle_master as _dkss_vehicle_master, vehicle_operations as _dkss_vehicle_operations, vehicle_pending as _dkss_vehicle_pending, vehicle_readers as _dkss_vehicle_readers


def apply_maintenance_invoice_preview(draft, extraction):
    if (
        draft.document_type not in {"maintenance", "inspection"}
        or draft.company_code != _dkss_common.session.get("company_code")
        or draft.created_by_username != _dkss_common.session.get("username")
        or draft.status != "preview"
    ):
        raise ValueError("この資料の読み取り結果は変更できません。")

    if (
        extraction.get("schema_version") != 1
        or extraction.get("source_sha256") != draft.source_sha256
    ):
        raise ValueError("読み取り結果と原本PDFが一致しません。")

    vehicles = _dkss_models.Vehicle.query.filter_by(
        company_code=draft.company_code
    ).all()

    vehicle_choices = [
        {
            "id": vehicle.id,
            "number": " ".join(
                str(value)
                for value in (
                    vehicle.plate_area,
                    vehicle.plate_class,
                    vehicle.plate_kana,
                    vehicle.plate_number,
                )
                if value
            ),
            "chassis_number": vehicle.chassis_number or "",
            "deleted": bool(vehicle.deleted),
        }
        for vehicle in vehicles
    ]

    builder = (
        _dkss_common.build_inspection_preview if draft.document_type == "inspection"
        else _dkss_common.build_maintenance_invoice_preview
    )
    preview = builder(extraction, vehicle_choices)
    draft.preview_json = _dkss_common.json.dumps(
        preview,
        ensure_ascii=False,
    )
    return preview



def invoice_import_target_is_empty(record):
    details = _dkss_serialization.safe_json_dict(record.invoice_details_json)
    return not (
        record.invoice_number or record.invoice_date or details.get("source")
        or any(getattr(record, field) is not None for field in (
            "labor_cost", "parts_cost", "other_cost", "tax_amount", "total_cost"
        ))
        or _dkss_common.json.loads(record.line_items_json or "[]") or details.get("fees")
        or _dkss_models.VehiclePartReplacement.query.filter_by(
            company_code=record.company_code, vehicle_record_id=record.vehicle_record_id,
            maintenance_record_id=record.id,
        ).first() is not None
    )



def get_invoice_import_matches(company_code, vehicle_id, values):
    matches = _dkss_vehicle_pending.get_vehicle_pending_maintenance_candidates(company_code, vehicle_id, values)
    for candidate in matches:
        model = _dkss_models.VehicleMaintenanceRecord if candidate["kind"] == "maintenance" else _dkss_models.VehiclePeriodicInspectionRecord
        target = model.query.filter_by(
            id=candidate["record_id"], company_code=company_code, vehicle_record_id=vehicle_id,
        ).first()
        if target is None:
            raise _dkss_common.UploadValidationError("整備候補が変わりました。再確認してください。")
        candidate["token"] = candidate["kind"] + ":" + str(target.id) + ":" + _dkss_vehicle_karte.vehicle_maintenance_record_version(target)
    return matches



def resolve_invoice_import_choice(draft, values, choice):
    if not isinstance(choice, str) or len(choice) > 150:
        raise _dkss_common.UploadValidationError("請求書と整備の対応を確認してください。")
    vehicle_id = values.get("vehicle_record_id")
    if vehicle_id is None:
        return None
    candidates = get_invoice_import_matches(draft.company_code, vehicle_id, values)
    if choice == "new" or (not choice and not candidates):
        return None
    selected = next((row for row in candidates if row["token"] == choice), None)
    if selected is None:
        raise _dkss_common.UploadValidationError("同じ作業日の整備候補があります。請求書の対応先を確認してください。候補が更新された場合は選び直してください。")
    return selected



def apply_invoice_import_choice(draft, record_index, values):
    stored = _dkss_common.db.session.query(
        _dkss_models.VehicleDocumentImportDraft.status, _dkss_models.VehicleDocumentImportDraft.preview_json,
    ).filter_by(id=draft.id, company_code=draft.company_code,
                created_by_username=_dkss_common.session.get("username")).first()
    rows = _dkss_serialization.safe_json_dict(stored.preview_json).get("records") if stored else None
    if (draft.company_code != _dkss_common.session.get("company_code")
            or draft.created_by_username != _dkss_common.session.get("username")
            or draft.document_type != "maintenance" or stored is None or stored.status != "processing"
            or type(record_index) is not int or not isinstance(rows, list)
            or not 0 <= record_index < len(rows) or rows[record_index] != values
            or _dkss_common.hashlib.sha256(draft.source_file).hexdigest() != draft.source_sha256):
        raise _dkss_common.UploadValidationError("保存済みの請求書原本・確認内容を再確認してください。")
    selected = resolve_invoice_import_choice(draft, values, values.get("service_match", ""))
    invoice = build_vehicle_document_record(draft, record_index, values)
    if selected is None:
        _dkss_common.db.session.add(invoice)
        _dkss_common.db.session.flush()
        _dkss_maintenance.add_vehicle_maintenance_record_event(invoice, action="imported")
        _dkss_vehicle_karte.save_vehicle_maintenance_replacement_parts(invoice)
        return invoice.id, None
    model = _dkss_models.VehicleMaintenanceRecord if selected["kind"] == "maintenance" else _dkss_models.VehiclePeriodicInspectionRecord
    target = model.query.filter_by(
        id=selected["record_id"], company_code=draft.company_code,
        vehicle_record_id=values["vehicle_record_id"],
    ).with_for_update().populate_existing().first()
    if target is None or selected["token"].rsplit(":", 1)[1] != _dkss_vehicle_karte.vehicle_maintenance_record_version(target):
        raise _dkss_common.UploadValidationError("整備候補が更新されています。再確認してください。")
    if selected["kind"] == "maintenance" and invoice_import_target_is_empty(target):
        target = _dkss_vehicle_pending.merge_vehicle_pending_invoice_record(target.id, invoice)
        _dkss_maintenance.add_vehicle_maintenance_record_event(target, action="imported")
        _dkss_vehicle_karte.save_vehicle_maintenance_replacement_parts(target)
        return target.id, None
    # Existing financial and replacement data require the existing review workflow.
    if _dkss_common.hashlib.sha256(draft.source_file).hexdigest() != draft.source_sha256:
        raise _dkss_common.UploadValidationError("保存済みの原本を確認できません。")
    document = _dkss_models.VehicleMaintenanceDocument(
        company_code=draft.company_code, vehicle_record_id=values["vehicle_record_id"],
        source_draft_id=draft.id, source_record_index=record_index,
        maintenance_record_id=target.id if selected["kind"] == "maintenance" else None,
        inspection_record_id=target.id if selected["kind"] == "inspection" else None,
        payload_json=_dkss_common.json.dumps(values, ensure_ascii=False, sort_keys=True),
        decision_json=_dkss_common.json.dumps({"service_match": "same", "matched_by_username": _dkss_common.session.get("username"), "costs_applied": False, "parts_applied": False}, ensure_ascii=False),
        financial_status="pending", parts_status="pending", created_by_username=_dkss_common.session.get("username"),
    )
    _dkss_common.db.session.add(document)
    _dkss_common.db.session.flush()
    return target.id, document



def vehicle_invoice_import_candidates(batch_id, draft_id, record_index):
    if not _dkss_access.require_master_admin():
        return _dkss_common.jsonify(error="この操作は管理者のみ利用できます。"), 403
    draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
        id=draft_id, batch_id=batch_id, company_code=_dkss_common.session.get("company_code"),
        created_by_username=_dkss_common.session.get("username"), document_type="maintenance", status="preview",
    ).first_or_404()
    rows = _dkss_serialization.safe_json_dict(draft.preview_json).get("records")
    if not isinstance(rows, list) or not 0 <= record_index < len(rows):
        return _dkss_common.jsonify(error="対象の請求書明細を確認できません。"), 400
    try:
        vehicle_id = int(_dkss_common.request.args.get("vehicle_id", ""))
        if not 0 < vehicle_id <= 9223372036854775807:
            raise ValueError
        candidates = get_invoice_import_matches(draft.company_code, vehicle_id, {
            "record_date": _dkss_common.request.args.get("record_date") or None,
            "completion_date": _dkss_common.request.args.get("completion_date") or None,
        })
    except (ValueError, _dkss_common.UploadValidationError):
        return _dkss_common.jsonify(error="車両・作業日を確認してください。"), 400
    response = _dkss_common.jsonify(candidates=candidates)
    response.headers["Cache-Control"] = "private, no-store"
    return response



def build_vehicle_document_record(
    draft,
    record_index,
    values
):
    mileage = (
        _dkss_common.Decimal(values["mileage"])
        if values.get("mileage") is not None
        else None
    )

    if draft.document_type == "inspection":
        return _dkss_models.VehiclePeriodicInspectionRecord(
            company_code=draft.company_code,
            vehicle_record_id=values["vehicle_record_id"],
            inspection_type=values["inspection_type"],
            inspection_date=values["record_date"],
            completion_date=values.get("completion_date") or None,
            next_inspection_date=values.get("next_inspection_date") or None,
            inspection_company=values.get("inspection_company") or None,
            inspector_name=values.get("inspector_name") or None,
            mileage=mileage,
            content=values["content"],
            details_json=_dkss_common.json.dumps(
                values,
                ensure_ascii=False
            ),
            source_draft_id=draft.id,
            source_record_index=record_index,
            created_by_username=_dkss_common.session.get("username")
        )

    if draft.document_type == "driving_report":
        return _dkss_models.VehicleDrivingReportRecord(
            company_code=draft.company_code,
            vehicle_record_id=values["vehicle_record_id"],
            operation_date=values["record_date"],
            mileage=mileage,
            content=values["content"],
            details_json=_dkss_common.json.dumps(
                values,
                ensure_ascii=False
            ),
            source_draft_id=draft.id,
            source_record_index=record_index,
            created_by_username=_dkss_common.session.get("username")
        )

    if draft.document_type == "maintenance":
        costs = {}

        for field in (
            "labor_cost",
            "parts_cost",
            "other_cost",
            "tax_amount",
            "total_cost",
        ):
            raw = values.get(field)

            if raw is None or raw == "":
                costs[field] = None
                continue

            amount = _dkss_common.Decimal(str(raw))

            if (
                not amount.is_finite()
                or abs(amount) > _dkss_common.Decimal("999999999999.99")
                or amount != amount.quantize(_dkss_common.Decimal("0.01"))
            ):
                raise ValueError("整備費用の金額を確認してください。")

            costs[field] = amount

        for field in ("completion_date", "invoice_date"):
            value = values.get(field)

            if value:
                parsed = _dkss_common.datetime.strptime(value, "%Y-%m-%d")

                if parsed.strftime("%Y-%m-%d") != value:
                    raise ValueError("整備資料の日付を確認してください。")

        invoice_number = values.get("invoice_number") or ""
        maintenance_company = values.get("maintenance_company") or ""

        if len(invoice_number) > 100 or len(maintenance_company) > 200:
            raise ValueError("伝票番号・整備会社名の文字数を確認してください。")

        line_items = values.get("line_items") or []

        if (
            not isinstance(line_items, list)
            or len(line_items) > 1000
            or not all(isinstance(item, dict) for item in line_items)
        ):
            raise ValueError("整備明細を確認してください。")

        return _dkss_models.VehicleMaintenanceRecord(
            company_code=draft.company_code,
            vehicle_record_id=values["vehicle_record_id"],
            entry_date=values["record_date"],
            completion_date=values.get("completion_date") or None,
            mileage=mileage,
            content=values["content"],
            maintenance_company=maintenance_company or None,
            invoice_number=invoice_number or None,
            invoice_date=values.get("invoice_date") or None,
            invoice_details_json=_dkss_common.json.dumps(
                {
                    "schema_version": 1,
                    "issuer_name": values.get("issuer_name"),
                    "customer_name": values.get("customer_name"),
                    "sales_date": values.get("sales_date"),
                    "fees": values.get("fees") or [],
                    "registration_number": values.get("registration_number"),
                    "chassis_number": values.get("chassis_number"),
                    "vehicle_model": values.get("vehicle_model"),
                    "source": {
                        "draft_id": draft.id,
                        "record_index": record_index,
                        "filename": draft.source_filename,
                        "sha256": draft.source_sha256,
                        "pages": values.get("source_pages") or [],
                    },
                },
                ensure_ascii=False,
            ),
            line_items_json=_dkss_common.json.dumps(
                line_items,
                ensure_ascii=False,
            ),
            notes=values.get("notes") or None,
            **costs,
            created_by_username=_dkss_common.session.get("username"),
            created_at=_dkss_common.datetime.now(
                _dkss_common.ZoneInfo("Asia/Tokyo")
            ).isoformat(timespec="seconds")
        )

    raise ValueError("資料の種類が不正です。")



def parse_maintenance_invoice_number(raw):
    import re

    value = str(raw).strip()

    if not re.fullmatch(
        r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?",
        value,
    ):
        raise ValueError("Invalid number format")

    return _dkss_common.Decimal(value.replace(",", ""))



def maintenance_import_source_keys(source):
    if not isinstance(source, dict):
        return set()

    digest = source.get("sha256")
    if not isinstance(digest, str) or not digest:
        return set()

    pages = source.get("pages")
    if isinstance(pages, list):
        keys = {
            (digest, page)
            for page in pages
            if isinstance(page, int)
            and not isinstance(page, bool)
            and page > 0
        }
        if keys:
            return keys

    index = source.get("record_index")
    if (
        isinstance(index, int)
        and not isinstance(index, bool)
        and index >= 0
    ):
        return {(digest, "record:" + str(index))}

    return set()



def registered_maintenance_import_keys(
    company_code, exclude_pending_record_id=None
):
    keys = set()
    records = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
        company_code=company_code,
    ).all()

    for record in records:
        source = _dkss_serialization.safe_json_dict(
            record.invoice_details_json
        ).get("source")
        keys.update(maintenance_import_source_keys(source))

    document_query = _dkss_common.db.session.query(
        _dkss_models.VehicleMaintenanceDocument,
        _dkss_models.VehicleDocumentImportDraft.source_sha256
    ).join(
        _dkss_models.VehicleDocumentImportDraft,
        _dkss_models.VehicleMaintenanceDocument.source_draft_id == _dkss_models.VehicleDocumentImportDraft.id
    ).filter(
        _dkss_models.VehicleMaintenanceDocument.company_code == company_code,
        _dkss_models.VehicleDocumentImportDraft.company_code == company_code,
    )
    for document, digest in document_query.all():
        if (
            exclude_pending_record_id is not None
            and document.pending_record_id == exclude_pending_record_id
        ):
            continue
        payload = _dkss_serialization.safe_json_dict(document.payload_json)
        keys.update(maintenance_import_source_keys({
            "sha256": digest,
            "pages": payload.get("source_pages"),
            "record_index": document.source_record_index,
        }))

    pending_query = _dkss_common.db.session.query(
        _dkss_models.VehicleImportPendingRecord,
        _dkss_models.VehicleDocumentImportDraft.source_sha256
    ).join(
        _dkss_models.VehicleDocumentImportDraft,
        _dkss_models.VehicleImportPendingRecord.document_draft_id == _dkss_models.VehicleDocumentImportDraft.id
    ).filter(
        _dkss_models.VehicleImportPendingRecord.company_code == company_code,
        _dkss_models.VehicleDocumentImportDraft.company_code == company_code,
        _dkss_models.VehicleImportPendingRecord.source_kind == "maintenance",
        _dkss_models.VehicleImportPendingRecord.status == "pending"
    )
    if exclude_pending_record_id is not None:
        pending_query = pending_query.filter(
            _dkss_models.VehicleImportPendingRecord.id != exclude_pending_record_id
        )

    for pending_record, digest in pending_query.all():
        payload = _dkss_serialization.safe_json_dict(pending_record.payload_json)
        keys.update(maintenance_import_source_keys({
            "sha256": digest,
            "pages": payload.get("source_pages"),
            "record_index": pending_record.source_record_index,
        }))

    return keys



def registered_inspection_import_keys(company_code, exclude_pending_record_id=None):
    keys = set()
    for record_index, digest in _dkss_common.db.session.query(
        _dkss_models.VehiclePeriodicInspectionRecord.source_record_index, _dkss_models.VehicleDocumentImportDraft.source_sha256
    ).join(_dkss_models.VehicleDocumentImportDraft,
           _dkss_models.VehiclePeriodicInspectionRecord.source_draft_id == _dkss_models.VehicleDocumentImportDraft.id
    ).filter(_dkss_models.VehiclePeriodicInspectionRecord.company_code == company_code,
             _dkss_models.VehicleDocumentImportDraft.company_code == company_code).all():
        keys.add((digest, record_index))
    pending = _dkss_common.db.session.query(
        _dkss_models.VehicleImportPendingRecord.source_record_index, _dkss_models.VehicleDocumentImportDraft.source_sha256
    ).join(_dkss_models.VehicleDocumentImportDraft,
           _dkss_models.VehicleImportPendingRecord.document_draft_id == _dkss_models.VehicleDocumentImportDraft.id
    ).filter(_dkss_models.VehicleImportPendingRecord.company_code == company_code,
             _dkss_models.VehicleDocumentImportDraft.company_code == company_code,
             _dkss_models.VehicleImportPendingRecord.source_kind == "inspection",
             _dkss_models.VehicleImportPendingRecord.status == "pending")
    if exclude_pending_record_id is not None:
        pending = pending.filter(_dkss_models.VehicleImportPendingRecord.id != exclude_pending_record_id)
    keys.update((digest, record_index) for record_index, digest in pending.all())
    return keys



def save_vehicle_document_pending_record(draft, record_index, values):
    if values.get("vehicle_record_id") is not None:
        raise _dkss_common.UploadValidationError("登録待ちの対象を再確認してください。")

    digest = _dkss_common.hashlib.sha256(draft.source_file).hexdigest()
    if digest != draft.source_sha256:
        raise _dkss_common.UploadValidationError("取込原本の一致を確認できません。")

    source_number = str(values.get("registration_number") or "").strip()
    chassis_number = str(values.get("chassis_number") or "").strip()
    group_identity = {
        "source": "document",
        "plate": _dkss_common.normalize_vehicle_operation_plate(source_number),
        "chassis": _dkss_common.normalize_vehicle_operation_plate(chassis_number),
    }
    if not group_identity["plate"] and not group_identity["chassis"]:
        group_identity.update({
            "sha256": digest,
            "record_index": record_index
        })

    record, created = _dkss_vehicle_pending.save_vehicle_import_pending_record(
        company_code=draft.company_code,
        username=_dkss_common.session.get("username"),
        source_kind=draft.document_type,
        source_draft_id=draft.id,
        source_record_index=record_index,
        group_identity=group_identity,
        identity={
            "source_vehicle_number": source_number,
            "source_vehicle_code": "",
            "chassis_number": chassis_number,
            "document_type": draft.document_type,
        },
        record_identity={
            "sha256": digest,
            "record_index": record_index
        },
        payload=values,
        record_date=values.get("record_date"),
    )
    if record.status != "pending":
        raise _dkss_common.UploadValidationError(
            "この原本の明細はすでに車両へ反映されています。"
        )
    return record, created



def validate_vehicle_document_record(
    draft,
    record_index,
    original_record,
    form,
    allow_pending_vehicle=False
):
    row_key = f"{draft.id}_{record_index}"
    values = dict(original_record)
    errors = []

    vehicle_value = form.get(
        f"vehicle_{row_key}", ""
    ).strip()
    record_date = form.get(
        f"date_{row_key}", ""
    ).strip()
    mileage_text = form.get(
        f"mileage_{row_key}", ""
    ).strip()
    content = form.get(
        f"content_{row_key}", ""
    ).strip()

    values.update({
        "vehicle_record_id": vehicle_value,
        "record_date": record_date,
        "mileage": mileage_text or None,
        "content": content
    })

    try:
        if allow_pending_vehicle and not vehicle_value:
            values["vehicle_record_id"] = None
        else:
            vehicle_id = int(vehicle_value)

            if not 0 < vehicle_id <= 9223372036854775807:
                raise ValueError

            vehicle = _dkss_models.Vehicle.query.filter_by(
                id=vehicle_id,
                company_code=draft.company_code
            ).first()

            if vehicle is None:
                raise ValueError

            values["vehicle_record_id"] = vehicle.id
    except (ValueError, TypeError):
        errors.append((
            "同じ会社の対象車両を選択してください。",
            f"vehicle_{row_key}"
        ))

    try:
        parsed_date = _dkss_common.datetime.strptime(
            record_date, "%Y-%m-%d"
        )

        if parsed_date.strftime("%Y-%m-%d") != record_date:
            raise ValueError
    except ValueError:
        errors.append((
            "記録の日付を正しく入力してください。",
            f"date_{row_key}"
        ))

    if mileage_text:
        try:
            mileage = (
                parse_maintenance_invoice_number(mileage_text)
                if draft.document_type in {"maintenance", "inspection"}
                else _dkss_common.Decimal(mileage_text)
            )

            if (
                not mileage.is_finite()
                or mileage < 0
                or mileage > _dkss_common.Decimal("999999999999.99")
                or mileage != mileage.quantize(_dkss_common.Decimal("0.01"))
            ):
                raise ValueError

            values["mileage"] = format(mileage, ".2f")
        except (_dkss_common.InvalidOperation, ValueError):
            errors.append((
                "積算走行距離は0以上、小数点以下2桁までで入力してください。",
                f"mileage_{row_key}"
            ))

    if len(content) > 5000:
        errors.append((
            "記録内容は5000文字以内で入力してください。",
            f"content_{row_key}"
        ))

    if draft.document_type == "inspection":
        inspection_type = form.get(
            f"inspection_type_{row_key}", ""
        ).strip()
        values["inspection_type"] = inspection_type

        if inspection_type not in {
            "3month", "12month", "other"
        }:
            errors.append((
                "点検区分を選択してください。",
                f"inspection_type_{row_key}"
            ))

    if draft.document_type == "inspection":
        for field, (label, limit) in {
            "inspection_company": ("実施工場", 200),
            "inspector_name": ("点検者", 100),
            "notes": ("特記事項", 5000),
            "symbol_legend": ("記号凡例", 5000),
        }.items():
            key = f"{field}_{row_key}"
            values[field] = form.get(key, original_record.get(field) or "").strip() or None
            if len(values[field] or "") > limit:
                errors.append((f"{label}は{limit}文字以内で入力してください。", key))
        key = f"next_inspection_month_{row_key}"
        raw = form.get(key, original_record.get("next_inspection_month") or "").strip()
        values["next_inspection_month"] = raw or None
        if raw:
            from vehicle_inspection_plans import month as valid_plan_month
            if not valid_plan_month(raw):
                errors.append(("原本の次回予定月を正しく入力してください。", key))
        for field in ("completion_date", "next_inspection_date"):
            key = f"{field}_{row_key}"
            raw = form.get(key, original_record.get(field) or "").strip()
            values[field] = raw or None
            if raw:
                try:
                    if _dkss_common.datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d") != raw:
                        raise ValueError
                except ValueError:
                    errors.append(("原本に記載された日付を正しく入力してください。", key))
        if values.get("next_inspection_month") and values.get("next_inspection_date") and values["next_inspection_date"][:7] != values["next_inspection_month"]:
            errors.append(("次回予定月と次回点検日の年月を合わせてください。", f"next_inspection_month_{row_key}"))
        values["inspection_date"] = record_date
        values["inspection_items"] = []
        for index, original_item in enumerate(original_record.get("inspection_items") or []):
            item = dict(original_item)
            for field, limit in _dkss_common.ITEM_FIELDS.items():
                key = f"inspection_item_{row_key}_{index}_{field}"
                raw = form.get(key, original_item.get(field) or "").strip()
                item[field] = raw or None
                if len(raw) > limit or (field == "item_name" and not raw):
                    errors.append(("点検項目の名称・文字数を確認してください。", key))
            values["inspection_items"].append(item)

    if draft.document_type == "maintenance":
        text_fields = {
            "invoice_number": ("伝票番号", 100),
            "issuer_name": ("請求書発行元", 200),
            "maintenance_company": ("整備会社・工場", 200),
            "notes": ("備考", 5000),
        }

        for field, (label, limit) in text_fields.items():
            field_id = f"{field}_{row_key}"
            raw = form.get(field_id, values.get(field))
            value = str(raw or "").strip()
            values[field] = value or None

            if len(value) > limit:
                errors.append((
                    f"{label}は{limit}文字以内で入力してください。",
                    field_id,
                ))

        for field, label in (
            ("completion_date", "出庫日"),
            ("invoice_date", "請求日"),
            ("sales_date", "売上日"),
        ):
            field_id = f"{field}_{row_key}"
            raw = form.get(field_id, values.get(field))
            value = str(raw or "").strip()
            values[field] = value or None

            if not value:
                continue

            try:
                parsed = _dkss_common.datetime.strptime(value, "%Y-%m-%d")

                if parsed.strftime("%Y-%m-%d") != value:
                    raise ValueError
            except ValueError:
                errors.append((
                    f"{label}を正しく入力してください。",
                    field_id,
                ))

        for field, label in (
            ("labor_cost", "工賃"),
            ("parts_cost", "部品代"),
            ("other_cost", "その他費用"),
            ("tax_amount", "消費税"),
            ("total_cost", "請求総額"),
        ):
            field_id = f"{field}_{row_key}"
            raw = form.get(field_id, values.get(field))
            value = str(raw if raw is not None else "").strip()
            values[field] = value or None

            if not value:
                continue

            try:
                amount = parse_maintenance_invoice_number(value)

                if (
                    not amount.is_finite()
                    or abs(amount) > _dkss_common.Decimal("999999999999.99")
                    or amount != amount.quantize(_dkss_common.Decimal("0.01"))
                ):
                    raise ValueError

                values[field] = format(amount, ".2f")
            except (_dkss_common.InvalidOperation, ValueError):
                errors.append((
                    f"{label}は小数点以下2桁までの金額で入力してください。",
                    field_id,
                ))

        original_lines = original_record.get("line_items", [])
        values["line_items"] = []

        if (
            not isinstance(original_lines, list)
            or len(original_lines) > 1000
            or not all(isinstance(line, dict) for line in original_lines)
        ):
            errors.append(("整備明細を取得できませんでした。", ""))
        else:
            line_text_fields = {
                "description": ("内容", 1000),
                "replacement_part_name": ("交換部品名", 200),
                "part_number": ("品番", 200),
                "category": ("区分", 20),
                "unit": ("単位", 50),
                "notes": ("備考", 1000),
            }
            line_number_fields = {
                "quantity": ("数量", 6),
                "unit_price": ("単価", 2),
                "labor_amount": ("工賃", 2),
                "parts_amount": ("部品代", 2),
                "amount": ("行合計", 2),
            }

            for line_index, original_line in enumerate(original_lines):
                line = dict(original_line)
                prefix = f"invoice_line_{row_key}_{line_index}_"

                for field, (label, limit) in line_text_fields.items():
                    field_id = prefix + field
                    raw = form.get(field_id, original_line.get(field))
                    value = str(raw if raw is not None else "").strip()
                    line[field] = value or None

                    if len(value) > limit:
                        errors.append((
                            f"明細{line_index + 1}の{label}は{limit}文字以内で入力してください。",
                            field_id,
                        ))

                if line.get("category") not in {None, "部品", "工賃", "その他", "不明"}:
                    errors.append((
                        f"明細{line_index + 1}の区分を確認してください。",
                        prefix + "category",
                    ))

                for field, (label, places) in line_number_fields.items():
                    field_id = prefix + field
                    raw = form.get(field_id, original_line.get(field))
                    value = str(raw if raw is not None else "").strip()
                    line[field] = value or None

                    if not value:
                        continue

                    try:
                        if len(value) > 50:
                            raise ValueError
                        number = parse_maintenance_invoice_number(value)
                        quantum = _dkss_common.Decimal(1).scaleb(-places)
                        if (
                            not number.is_finite()
                            or abs(number) > _dkss_common.Decimal("999999999999.99")
                            or number != number.quantize(quantum)
                        ):
                            raise ValueError
                        line[field] = format(number, "f")
                    except (_dkss_common.InvalidOperation, ValueError):
                        errors.append((
                            f"明細{line_index + 1}の{label}は小数点以下{places}桁までの数値で入力してください。",
                            field_id,
                        ))

                action = str(form.get(
                    prefix + "replacement_action",
                    original_line.get("replacement_action") or "review",
                )).strip()
                line["replacement_action"] = action

                if action not in {"replace", "not_replace", "review"}:
                    errors.append((
                        f"明細{line_index + 1}の交換部品の判定を確認してください。",
                        prefix + "replacement_action",
                    ))
                elif action == "review":
                    errors.append((
                        f"明細{line_index + 1}が交換部品か確認してください。",
                        prefix + "replacement_action",
                    ))
                elif action == "replace":
                    if not line.get("replacement_part_name"):
                        errors.append((
                            f"明細{line_index + 1}の交換部品名を確認してください。",
                            prefix + "replacement_part_name",
                        ))

                    if len(line.get("part_number") or "") > 100:
                        errors.append((
                            f"明細{line_index + 1}の品番は100文字以内で入力してください。",
                            prefix + "part_number",
                        ))

                    try:
                        quantity = _dkss_common.Decimal(line.get("quantity") or "")
                        if (
                            not quantity.is_finite()
                            or quantity <= 0
                            or quantity > _dkss_common.Decimal("999999999999.99")
                            or quantity != quantity.quantize(_dkss_common.Decimal("0.01"))
                        ):
                            raise ValueError
                    except (_dkss_common.InvalidOperation, ValueError):
                        errors.append((
                            f"明細{line_index + 1}の交換数量を確認してください（0より大きい数・小数点以下2桁まで）。",
                            prefix + "quantity",
                        ))

                part_category = str(
                    form.get(
                        prefix + "replacement_category",
                        line.get("replacement_category") or "未分類",
                    ) or "未分類"
                ).strip()

                line["replacement_category"] = part_category

                if part_category not in {
                    "未分類", "消耗品", "電装系", "駆動系",
                    "冷却系", "足回り", "その他",
                }:
                    errors.append((
                        f"明細{line_index + 1}の部品分類を確認してください。",
                        prefix + "replacement_category",
                    ))

                values["line_items"].append(line)

        values["entry_date"] = values.get("record_date") or None

    return values, errors



def prepare_vehicle_document_import(files, document_type):
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return [], [
            ("ログイン情報を確認してください。", "")
        ]

    if document_type not in {
        "inspection",
        "driving_report",
        "maintenance"
    }:
        return [], [
            ("資料の種類を選択してください。", "document_type")
        ]

    uploaded_files = [
        file
        for file in files
        if file and file.filename
    ]

    if not uploaded_files:
        return [], [
            ("ファイルを選択してください。", "document_files")
        ]

    if len(uploaded_files) > 50:
        return [], [
            (
                "1回に取り込めるファイルは50件までです。",
                "document_files"
            )
        ]

    batch_id = str(_dkss_common.uuid4())
    drafts = []
    errors = []

    for file in uploaded_files:
        filename = _dkss_common.os.path.basename(
            file.filename.replace("\\", "/")
        )
        extension = _dkss_common.os.path.splitext(filename)[1].lower()

        if not filename or len(filename) > 255:
            errors.append((
                "ファイル名は1～255文字にしてください。",
                "document_files"
            ))
            continue

        if extension not in {".pdf", ".png", ".jpg", ".jpeg"}:
            errors.append((
                f"{filename}：PDF・PNG・JPEGを選択してください。",
                "document_files"
            ))
            continue

        if not _dkss_storage.is_valid_uploaded_file(file, extension):
            errors.append((
                f"{filename}：ファイルの内容が不正です。",
                "document_files"
            ))
            continue

        try:
            file.stream.seek(0)
            source_file = file.read()
        except (OSError, ValueError):
            errors.append((
                f"{filename}：ファイルを読み込めませんでした。",
                "document_files"
            ))
            continue

        if not source_file:
            errors.append((
                f"{filename}：ファイルが空です。",
                "document_files"
            ))
            continue

        if (
            document_type in {"maintenance", "inspection"}
            and len(source_file) > 20 * 1024 * 1024
        ):
            errors.append((
                f"{filename}：資料は1ファイル20MB以下にしてください。",
                "document_files"
            ))
            continue

        drafts.append(_dkss_models.VehicleDocumentImportDraft(
            id=str(_dkss_common.uuid4()),
            batch_id=batch_id,
            company_code=company_code,
            created_by_username=username,
            document_type=document_type,
            source_filename=filename,
            source_file=source_file,
            source_sha256=_dkss_common.hashlib.sha256(
                source_file
            ).hexdigest()
        ))

    if errors:
        return [], errors

    return drafts, []



def vehicle_data_import_progress():
    from flask import Response, stream_with_context
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue, Empty
    from time import monotonic

    if not _dkss_access.require_master_admin():
        return _dkss_http.return_form_errors(
            [("ログイン情報と権限を確認してください。", "")],
            status_code=403,
        )

    document_type = _dkss_common.request.form.get("document_type")
    if document_type not in {"maintenance", "inspection"}:
        return _dkss_http.return_form_errors(
            [("請求書・点検記録を選択してください。", "document_files")]
        )

    drafts, errors = prepare_vehicle_document_import(
        _dkss_common.request.files.getlist("document_files"), document_type
    )
    if errors:
        return _dkss_http.return_form_errors(errors)

    @stream_with_context
    def generate():
        total = len(drafts)
        ready = []
        failures = []

        def report(phase, completed, filename="", **extra):
            return _dkss_common.json.dumps({
                "phase": phase,
                "completed": completed,
                "total": total,
                "filename": filename,
                **extra,
            }, ensure_ascii=False) + "\n"

        try:
            yield report("accepted", 0)

            for index, draft in enumerate(drafts):
                yield report("reading", index, draft.source_filename)
                draft.status = "preview"

                try:
                    updates = Queue()
                    worker = ThreadPoolExecutor(max_workers=1)
                    try:
                        task = worker.submit(
                            _dkss_common.extract_inspection_documents if draft.document_type == "inspection" else _dkss_common.extract_maintenance_invoices,
                            draft.source_file,
                            filename=draft.source_filename,
                            progress_callback=updates.put,
                        )
                        last_sent = monotonic()

                        while True:
                            try:
                                update = updates.get(timeout=1)
                            except Empty:
                                if task.done():
                                    extraction = task.result()
                                    break

                                if monotonic() - last_sent >= 5:
                                    yield report(
                                        "reading",
                                        index,
                                        draft.source_filename,
                                        heartbeat=True,
                                    )
                                    last_sent = monotonic()
                            else:
                                yield report(
                                    update["phase"],
                                    index,
                                    draft.source_filename,
                                    received_lines=update.get("received_lines", 0),
                                )
                                last_sent = monotonic()
                    finally:
                        worker.shutdown(
                            wait=False,
                            cancel_futures=True,
                        )

                    yield report("checking", index, draft.source_filename)

                    preview = apply_maintenance_invoice_preview(
                        draft, extraction
                    )
                    if not preview.get("records"):
                        raise ValueError("OCR_NO_RECORDS")

                    ready.append(draft)

                except (ValueError, RuntimeError) as error:
                    _dkss_runtime.app.logger.exception(
                        "資料の読み取り失敗: %s",
                        draft.source_filename,
                    )
                    code = str(error).split(":", 1)[0]
                    reason = {
                        "API_KEY_NOT_SET": "AIの接続設定を確認してください。",
                        "OPENAI_NETWORK_OR_TIMEOUT": "AIとの通信が中断、または時間切れになりました。",
                        "NO_INVOICE_FOUND": "整備請求書が見つかりませんでした。",
                        "NO_INSPECTION_FOUND": "点検表が見つかりませんでした。",
                        "INVALID_INSPECTION_PDF": "PDFが破損・暗号化されているか、200ページを超えています。",
                        "INVALID_INSPECTION_EXTRACTION": "点検表の読取結果を確認できませんでした。原本を確認して再試行してください。",
                        "OCR_NO_RECORDS": "資料の内容を読み取れませんでした。",
                        "DOCUMENT_TOO_LARGE": "1ファイル20MB以下にしてください。",
                        "CONVERTED_PDF_TOO_LARGE": "変換後の容量が20MBを超えています。画像を小さくしてください。",
                        "IMAGE_TOO_LARGE": "画像の縦横サイズを小さくしてください。",
                        "IMAGE_READ_FAILED": "画像を開けません。ファイルを確認してください。",
                        "INVALID_SOURCE_PAGES": "読取結果のページ番号を確認できませんでした。",
                        "EXTRACTION_NOT_COMPLETED": "AIの読み取りが完了しませんでした。",
                    }.get(
                        code,
                        "読み取りに失敗しました。資料とサーバーログを確認してください。",
                    )
                    failures.append({
                        "filename": draft.source_filename,
                        "reason": reason,
                    })

                yield report(
                    "processed",
                    index + 1,
                    draft.source_filename,
                    succeeded=len(ready),
                    failed=len(failures),
                )

            if not ready:
                yield report(
                    "error",
                    total,
                    message="\n".join(
                        item["filename"] + "：" + item["reason"]
                        for item in failures
                    ),
                )
                return

            yield report(
                "saving",
                total,
                succeeded=len(ready),
                failed=len(failures),
            )

            if failures:
                preview = _dkss_serialization.safe_json_dict(ready[0].preview_json)
                preview["import_failures"] = failures
                ready[0].preview_json = _dkss_common.json.dumps(
                    preview, ensure_ascii=False
                )

            _dkss_common.db.session.add_all(ready)
            _dkss_common.db.session.commit()

            yield report(
                "complete",
                total,
                redirect_url=_dkss_common.url_for(
                    "vehicle_document_import_preview",
                    batch_id=ready[0].batch_id,
                ),
            )

        except GeneratorExit:
            _dkss_common.db.session.rollback()
            raise

        except Exception:
            _dkss_common.db.session.rollback()
            _dkss_runtime.app.logger.exception(
                "資料取り込みの進捗処理に失敗しました"
            )
            yield report(
                "error",
                0,
                message="処理を完了できませんでした。サーバーログを確認してください。",
            )

    return Response(
        generate(),
        mimetype="application/x-ndjson",
        headers={
            "Cache-Control": "no-store, no-transform",
            "X-Accel-Buffering": "no",
        },
    )



def vehicle_data_import():
    if not _dkss_access.require_master_admin():
        return _dkss_common.redirect(_dkss_common.url_for("vehicle_karte_list"))

    if _dkss_common.request.method == "GET":
        return _dkss_common.render_template(
            "vehicle_data_import.html"
        )

    drafts, errors = prepare_vehicle_document_import(
        _dkss_common.request.files.getlist("document_files"),
        _dkss_common.request.form.get("document_type", "")
    )

    if errors:
        return _dkss_http.return_form_errors(errors)

    if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
        return _dkss_common.jsonify({"ok": True})

    try:
        ready_drafts = []
        failed_imports = []

        for draft in drafts:
            if draft.document_type not in {"maintenance", "inspection"}:
                ready_drafts.append(draft)
                continue

            draft.status = "preview"

            try:
                extractor = _dkss_common.extract_inspection_documents if draft.document_type == "inspection" else _dkss_common.extract_maintenance_invoices
                extraction = extractor(
                    draft.source_file,
                    filename=draft.source_filename,
                )
                preview = apply_maintenance_invoice_preview(
                    draft,
                    extraction,
                )
                if not preview.get("records"):
                    raise ValueError("OCR_NO_RECORDS")
            except (ValueError, RuntimeError) as error:
                _dkss_runtime.app.logger.exception(
                    "資料の読み取りに失敗しました: %s",
                    draft.source_filename,
                )
                code = str(error).split(":", 1)[0]
                reason = {
                    "API_KEY_NOT_SET": "AIの接続設定を確認してください。",
                    "DOCUMENT_TOO_LARGE": "1ファイル20MB以下にしてください。",
                    "CONVERTED_PDF_TOO_LARGE": "変換後の容量が20MBを超えています。画像を小さくしてください。",
                    "IMAGE_TOO_LARGE": "画像の縦横サイズを小さくしてください。",
                    "IMAGE_READ_FAILED": "画像を開けません。ファイルを確認してください。",
                    "OCR_NO_RECORDS": "資料の内容を読み取れませんでした。",
                    "NO_INVOICE_FOUND": "整備請求書が見つかりませんでした。",
                    "NO_INSPECTION_FOUND": "点検表が見つかりませんでした。",
                    "INVALID_INSPECTION_PDF": "PDFが破損・暗号化されているか、200ページを超えています。",
                    "INVALID_INSPECTION_EXTRACTION": "点検表の読取結果を確認できませんでした。原本を確認して再試行してください。",
                    "OPENAI_NETWORK_OR_TIMEOUT": "AIとの通信が中断、または時間切れになりました。",
                    "EXTRACTION_NOT_COMPLETED": "AIの読み取りが完了しませんでした。",
                }.get(
                    code,
                    "読み取りに失敗しました。ファイルとサーバーログを確認してください。",
                )
                failed_imports.append({
                    "filename": draft.source_filename,
                    "reason": reason,
                })
                continue

            ready_drafts.append(draft)

        if not ready_drafts:
            return _dkss_http.return_form_errors(
                [
                    (
                        item["filename"] + "：" + item["reason"],
                        "document_files",
                    )
                    for item in failed_imports[:5]
                ] + (
                    [(
                        f"ほか{len(failed_imports) - 5}ファイルも読み取りに失敗しました。",
                        "",
                    )]
                    if len(failed_imports) > 5 else []
                ),
                status_code=503,
            )

        drafts = ready_drafts

        if failed_imports:
            first_preview = _dkss_serialization.safe_json_dict(drafts[0].preview_json)
            first_preview["import_failures"] = failed_imports
            drafts[0].preview_json = _dkss_common.json.dumps(
                first_preview,
                ensure_ascii=False,
            )

        _dkss_common.db.session.add_all(drafts)
        _dkss_common.db.session.commit()

    except (ValueError, RuntimeError) as error:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception(
            "資料の読み取りに失敗しました"
        )

        if str(error) == "API_KEY_NOT_SET":
            message = (
                "請求書を読み取るためのOPENAI_API_KEYが"
                "設定されていません。サーバーの設定を確認してください。"
            )
        elif str(error) == "OCR_NO_RECORDS":
            message = (
                "PDFから整備請求書を読み取れませんでした。"
                "資料の内容を確認してください。"
            )
        else:
            message = (
                "資料の読み取りに失敗しました。"
                "サーバーログで原因を確認してください。"
            )

        return _dkss_http.return_form_errors(
            [(message, "document_files")],
            status_code=503,
        )

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception(
            "資料取り込みの確認用データを保存できませんでした"
        )
        return _dkss_http.return_form_errors(
            [(
                "資料を保存できませんでした。もう一度お試しください。",
                "document_files"
            )],
            status_code=500
        )

    return _dkss_common.redirect(_dkss_common.url_for(
        "vehicle_document_import_preview",
        batch_id=drafts[0].batch_id
    ))



def vehicle_document_import_confirm(batch_id):
    if not _dkss_access.require_master_admin():
        return _dkss_http.return_form_errors(
            [("この操作を行う権限がありません。", "")],
            status_code=403
        )

    validation_only = (
        _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1"
    )

    query = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
        batch_id=batch_id,
        company_code=_dkss_common.session.get("company_code"),
        created_by_username=_dkss_common.session.get("username")
    )

    if not validation_only:
        query = query.with_for_update()

    drafts = query.order_by(
        _dkss_models.VehicleDocumentImportDraft.id
    ).all()

    if not drafts:
        raise _dkss_common.NotFound()

    if any(draft.status != "preview" for draft in drafts):
        return _dkss_http.return_form_errors(
            [(
                "この資料の取り込み確認は終了しています。",
                ""
            )],
            status_code=409
        )

    registered_source_keys = registered_maintenance_import_keys(
        _dkss_common.session.get("company_code")
    ) if any(
        draft.document_type == "maintenance" for draft in drafts
    ) else set()
    selected_source_keys = set()
    inspection_keys = registered_inspection_import_keys(_dkss_common.session.get("company_code")) if any(
        draft.document_type == "inspection" for draft in drafts
    ) else set()

    included = set(_dkss_common.request.form.getlist("include"))
    known_keys = set()
    submissions = []
    previews = {}
    errors = []

    for draft in drafts:
        preview = _dkss_serialization.safe_json_dict(draft.preview_json)
        original_records = preview.get("records")

        if original_records is None:
            original_records = [{}]

        if (
            not isinstance(original_records, list)
            or not original_records
            or not all(
                isinstance(record, dict)
                for record in original_records
            )
        ):
            errors.append((
                f"{draft.source_filename}：確認データを取得できませんでした。",
                ""
            ))
            continue

        updated_records = []

        for record_index, original_record in enumerate(
            original_records
        ):
            row_key = f"{draft.id}_{record_index}"
            known_keys.add(row_key)

            values, row_errors = validate_vehicle_document_record(
                draft,
                record_index,
                original_record,
                _dkss_common.request.form,
                allow_pending_vehicle=True
            )
            if draft.document_type == "maintenance":
                values["service_match"] = _dkss_common.request.form.get(f"service_match_{row_key}", "") if values.get("vehicle_record_id") is not None else ""
            values["include"] = row_key in included
            updated_records.append(values)

            if row_key not in included:
                continue

            if draft.document_type == "maintenance" and not row_errors:
                try:
                    resolve_invoice_import_choice(draft, values, values["service_match"])
                except _dkss_common.UploadValidationError as error:
                    row_errors.append((str(error), f"service_match_{row_key}"))

            if draft.document_type == "maintenance" and not row_errors:
                source_keys = maintenance_import_source_keys({
                    "sha256": draft.source_sha256,
                    "pages": values.get("source_pages"),
                    "record_index": record_index,
                })

                if source_keys & (
                    registered_source_keys | selected_source_keys
                ):
                    row_errors.append((
                        f"{draft.source_filename}の{record_index + 1}件目："
                        "同じ原本の請求書が登録済み、または今回の対象に重複しています。"
                        "この記録の取り込みチェックを外してください。",
                        f"include_{row_key}",
                    ))
                else:
                    selected_source_keys.update(source_keys)

            if draft.document_type == "inspection" and not row_errors:
                key = (draft.source_sha256, record_index)
                if key in inspection_keys:
                    row_errors.append(("同じ原本の点検記録が登録済み、または今回の対象に重複しています。取り込みチェックを外してください。", f"include_{row_key}"))
                inspection_keys.add(key)

            errors.extend(row_errors)

            if not row_errors:
                submissions.append((
                    draft,
                    record_index,
                    values
                ))

        if (
            draft.document_type == "maintenance"
            and "original_records" not in preview
        ):
            preview["original_records"] = _dkss_common.json.loads(
                _dkss_common.json.dumps(original_records, ensure_ascii=False)
            )

        preview["records"] = updated_records
        previews[draft.id] = preview

    if included - known_keys:
        errors.append((
            "取り込み対象が不正です。画面を再読み込みしてください。",
            ""
        ))

    if not included:
        errors.append((
            "取り込む記録を選択してください。",
            ""
        ))

    if errors:
        if not validation_only:
            try:
                for draft in drafts:
                    if draft.id in previews:
                        draft.preview_json = _dkss_common.json.dumps(
                            previews[draft.id],
                            ensure_ascii=False
                        )

                _dkss_common.db.session.commit()
            except _dkss_common.SQLAlchemyError:
                _dkss_common.db.session.rollback()
                _dkss_runtime.app.logger.exception(
                    "資料取り込みの編集内容を保持できませんでした"
                )
                return _dkss_http.return_form_errors(
                    [(
                        "編集内容を保存できませんでした。もう一度お試しください。",
                        ""
                    )],
                    status_code=500
                )

        return _dkss_http.return_form_errors(errors)

    if validation_only:
        return _dkss_common.jsonify({"ok": True})

    try:
        saved_preview_count = 0

        for draft_id, preview in previews.items():
            saved_preview_count += (
                _dkss_models.VehicleDocumentImportDraft.query
                .filter_by(
                    id=draft_id,
                    batch_id=batch_id,
                    company_code=_dkss_common.session.get("company_code"),
                    created_by_username=_dkss_common.session.get("username"),
                    status="preview"
                )
                .update(
                    {
                        "preview_json": _dkss_common.json.dumps(
                            preview,
                            ensure_ascii=False
                        )
                    },
                    synchronize_session=False
                )
            )

        if saved_preview_count != len(drafts):
            _dkss_common.db.session.rollback()
            return _dkss_http.return_form_errors(
                [(
                    "この資料はすでに処理されています。取り込み結果を確認してください。",
                    ""
                )],
                status_code=409
            )

        _dkss_common.db.session.commit()
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception(
            "資料取り込みの編集内容を保存できませんでした"
        )
        return _dkss_http.return_form_errors(
            [(
                "編集内容を保存できませんでした。もう一度お試しください。",
                ""
            )],
            status_code=500
        )

    try:
        claimed_count = (
            _dkss_models.VehicleDocumentImportDraft.query
            .filter(
                _dkss_models.VehicleDocumentImportDraft.id.in_(
                    [draft.id for draft in drafts]
                ),
                _dkss_models.VehicleDocumentImportDraft.company_code
                == _dkss_common.session.get("company_code"),
                _dkss_models.VehicleDocumentImportDraft.created_by_username
                == _dkss_common.session.get("username"),
                _dkss_models.VehicleDocumentImportDraft.status == "preview"
            )
            .update(
                {"status": "processing"},
                synchronize_session=False
            )
        )

        if claimed_count != len(drafts):
            _dkss_common.db.session.rollback()
            return _dkss_http.return_form_errors(
                [(
                    "この資料はすでに処理されています。取り込み結果を確認してください。",
                    ""
                )],
                status_code=409
            )

        if any(
            draft.document_type in {"maintenance", "inspection"} for draft in drafts
        ):
            _dkss_models.Company.query.filter_by(
                company_code=_dkss_common.session.get("company_code")
            ).with_for_update().one()

        if any(draft.document_type == "maintenance" for draft in drafts):
            latest_source_keys = registered_maintenance_import_keys(
                _dkss_common.session.get("company_code")
            )

            for draft, record_index, values in submissions:
                if draft.document_type != "maintenance":
                    continue

                source_keys = maintenance_import_source_keys({
                    "sha256": draft.source_sha256,
                    "pages": values.get("source_pages"),
                    "record_index": record_index,
                })

                if source_keys & latest_source_keys:
                    _dkss_common.db.session.rollback()
                    return _dkss_http.return_form_errors(
                        [(
                            "同じ原本の請求書がすでに登録されています。"
                            "取り込み対象を確認してください。",
                            "",
                        )],
                        status_code=409,
                    )

                latest_source_keys.update(source_keys)

        latest_inspection_keys = registered_inspection_import_keys(_dkss_common.session.get("company_code")) if any(
            draft.document_type == "inspection" for draft in drafts
        ) else set()
        for draft, record_index, values in submissions:
            if draft.document_type == "inspection":
                key = (draft.source_sha256, record_index)
                if key in latest_inspection_keys:
                    _dkss_common.db.session.rollback()
                    return _dkss_http.return_form_errors([("同じ原本の点検記録がすでに登録されています。", "")], status_code=409)
                if _dkss_common.hashlib.sha256(draft.source_file).hexdigest() != draft.source_sha256:
                    raise _dkss_common.UploadValidationError("保存済みの点検原本を確認できません。")
                latest_inspection_keys.add(key)

        reviews_created = []
        results = {draft.id: [] for draft in drafts}
        pending_results = {draft.id: [] for draft in drafts}

        for draft, record_index, values in submissions:
            if values["vehicle_record_id"] is None:
                pending_record, _ = save_vehicle_document_pending_record(
                    draft, record_index, values
                )
                pending_results[draft.id].append({
                    "pending_record_id": pending_record.id,
                    "record_index": record_index,
                })
                continue

            if draft.document_type == "maintenance":
                record_id, document = apply_invoice_import_choice(draft, record_index, values)
                result = {
                    "record_id": record_id, "record_index": record_index,
                    "vehicle_record_id": values["vehicle_record_id"],
                    "document_type": "maintenance" if document is None or document.maintenance_record_id is not None else "inspection",
                }
                if document is not None:
                    result["maintenance_document_id"] = document.id
                    reviews_created.append(document.id)
                results[draft.id].append(result)
                continue

            record = build_vehicle_document_record(
                draft,
                record_index,
                values
            )
            _dkss_common.db.session.add(record)
            _dkss_common.db.session.flush()

            if draft.document_type == "maintenance":
                _dkss_maintenance.add_vehicle_maintenance_record_event(
                    record,
                    action="imported",
                )

            if draft.document_type == "maintenance":
                _dkss_vehicle_karte.save_vehicle_maintenance_replacement_parts(record)

            results[draft.id].append({
                "record_id": record.id,
                "record_index": record_index,
                "vehicle_record_id": values["vehicle_record_id"],
                "document_type": draft.document_type
            })

        completed_at = _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC"))

        for draft in drafts:
            draft.preview_json = _dkss_common.json.dumps(
                previews[draft.id],
                ensure_ascii=False
            )
            draft.result_json = _dkss_common.json.dumps(
                {
                    "records": results[draft.id],
                    "pending_records": pending_results[draft.id],
                    "pending_count": len(pending_results[draft.id]),
                },
                ensure_ascii=False
            )
            draft.status = (
                "completed"
                if results[draft.id] or pending_results[draft.id]
                else "skipped"
            )
            draft.completed_at = completed_at

        _dkss_common.db.session.commit()
    except _dkss_common.UploadValidationError as error:
        _dkss_common.db.session.rollback()
        return _dkss_http.return_form_errors([(str(error), "")])
    except (_dkss_common.SQLAlchemyError, ValueError, _dkss_common.InvalidOperation):
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception(
            "資料取り込みの反映に失敗しました"
        )
        return _dkss_http.return_form_errors(
            [(
                "記録を反映できませんでした。入力内容を確認して、もう一度お試しください。",
                ""
            )],
            status_code=500
        )

    applied_submissions = [
        item for item in submissions
        if item[2]["vehicle_record_id"] is not None
    ]
    pending_count = sum(
        len(items) for items in pending_results.values()
    )
    if pending_count:
        _dkss_common.flash(
            f"車両未選択の資料明細{pending_count}件を登録待ちとして保存しました。再アップロードは不要です。",
            "success"
        )
    if not applied_submissions:
        return _dkss_common.redirect(_dkss_common.url_for("vehicle_master", view="pending"))

    if reviews_created:
        _dkss_common.flash("請求書を既存記録へ添付しました。登録済みの費用・部品は変更していません。請求の反映方法を確認してください。", "success")
        return _dkss_common.redirect(_dkss_common.url_for("vehicle_maintenance_document_reviews"))

    first_draft, _, first_values = applied_submissions[0]
    if first_draft.document_type == "maintenance":
        return _dkss_common.redirect(_dkss_common.url_for(
            "vehicle_karte_maintenance",
            vehicle_record_id=first_values["vehicle_record_id"],
            import_batch=batch_id,
        ))

    _dkss_common.flash(
        f"資料から{len(applied_submissions)}件の記録を反映しました。",
        "success"
    )
    destination = (
        "vehicle_karte_inspections"
        if first_draft.document_type == "inspection"
        else "vehicle_karte_history"
    )
    return _dkss_common.redirect(_dkss_common.url_for(
        destination,
        vehicle_record_id=first_values["vehicle_record_id"],
    ))



def vehicle_periodic_inspection_source(record_id):
    record = _dkss_models.VehiclePeriodicInspectionRecord.query.filter_by(
        id=record_id,
        company_code=_dkss_common.session.get("company_code")
    ).first_or_404()

    draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
        id=record.source_draft_id,
        company_code=record.company_code,
        status="completed"
    ).first_or_404()

    extension = _dkss_common.os.path.splitext(
        draft.source_filename
    )[1].lower()

    mimetype = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg"
    }.get(extension)

    if not mimetype:
        raise _dkss_common.NotFound()

    response = _dkss_common.send_file(
        _dkss_common.BytesIO(draft.source_file),
        mimetype=mimetype,
        download_name=draft.source_filename,
        as_attachment=False,
        conditional=False,
        etag=False,
        max_age=0
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"

    return response



def vehicle_document_import_source(draft_id):
    if not _dkss_access.require_master_admin():
        raise _dkss_common.NotFound()

    draft = (
        _dkss_models.VehicleDocumentImportDraft.query
        .filter_by(
            id=draft_id,
            company_code=_dkss_common.session.get("company_code"),
            created_by_username=_dkss_common.session.get("username")
        )
        .first_or_404()
    )

    if (
        _dkss_common.request.args.get("preview") == "pdf"
        and draft.document_type in {"maintenance", "inspection"}
        and _dkss_common.os.path.splitext(draft.source_filename)[1].lower()
        in {".png", ".jpg", ".jpeg"}
    ):
        try:
            preview_pdf = _dkss_common.prepare_maintenance_invoice_pdf(
                draft.source_file
            )
        except ValueError:
            return "画像のプレビューを作成できませんでした。", 422

        response = _dkss_common.send_file(
            _dkss_common.BytesIO(preview_pdf),
            mimetype="application/pdf",
            download_name=(
                _dkss_common.os.path.splitext(draft.source_filename)[0] + ".pdf"
            ),
            as_attachment=False,
            conditional=False,
            etag=False,
            max_age=0,
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "private, no-store"
        return response

    extension = _dkss_common.os.path.splitext(
        draft.source_filename
    )[1].lower()

    mimetype = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg"
    }.get(extension)

    if not mimetype:
        raise _dkss_common.NotFound()

    response = _dkss_common.send_file(
        _dkss_common.BytesIO(draft.source_file),
        mimetype=mimetype,
        download_name=draft.source_filename,
        as_attachment=False,
        conditional=False,
        etag=False,
        max_age=0
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"

    return response



def vehicle_document_import_preview(batch_id):
    if not _dkss_access.require_master_admin():
        return _dkss_common.redirect(_dkss_common.url_for("vehicle_karte_list"))

    drafts = (
        _dkss_models.VehicleDocumentImportDraft.query
        .filter_by(
            batch_id=batch_id,
            company_code=_dkss_common.session.get("company_code"),
            created_by_username=_dkss_common.session.get("username")
        )
        .order_by(
            _dkss_models.VehicleDocumentImportDraft.created_at,
            _dkss_models.VehicleDocumentImportDraft.id
        )
        .all()
    )

    if not drafts:
        raise _dkss_common.NotFound()

    pending_drafts = [
        draft
        for draft in drafts
        if draft.status == "preview"
    ]

    if not pending_drafts:
        _dkss_common.flash(
            "この資料の取り込み確認は終了しています。",
            "info"
        )
        return _dkss_common.redirect(_dkss_common.url_for("vehicle_data_import"))

    vehicles = (
        _dkss_models.Vehicle.query
        .filter_by(
            company_code=_dkss_common.session.get("company_code")
        )
        .order_by(
            _dkss_models.Vehicle.plate_area,
            _dkss_models.Vehicle.plate_class,
            _dkss_models.Vehicle.plate_kana,
            _dkss_models.Vehicle.plate_number,
            _dkss_models.Vehicle.id
        )
        .all()
    )

    vehicle_choices = [
        {
            "id": vehicle.id,
            "number": " ".join(
                str(value)
                for value in [
                    vehicle.plate_area,
                    vehicle.plate_class,
                    vehicle.plate_kana,
                    vehicle.plate_number
                ]
                if value
            ),
            "chassis_number": vehicle.chassis_number or "",
            "deleted": bool(vehicle.deleted)
        }
        for vehicle in vehicles
    ]

    documents = [
        {
            "id": draft.id,
            "filename": draft.source_filename,
            "document_type": draft.document_type,
            "preview": _dkss_serialization.safe_json_dict(draft.preview_json)
        }
        for draft in pending_drafts
    ]

    return _dkss_common.render_template(
        "vehicle_document_import_preview.html",
        batch_id=batch_id,
        documents=documents,
        vehicle_choices=vehicle_choices
    )



def vehicle_operation_import():
    if _dkss_common.request.method == "GET":
        return _dkss_common.render_template("vehicle_operation_import.html")

    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return _dkss_http.return_form_errors(
            [("ログイン情報を確認してください。", "")],
            status_code=403
        )

    csv_file = _dkss_common.request.files.get("csv_file")

    if not csv_file or not csv_file.filename:
        return _dkss_http.return_form_errors([
            ("CSVファイルを選択してください。", "csv_file")
        ])

    filename = _dkss_common.os.path.basename(
        csv_file.filename.replace("\\", "/")
    )

    if not filename.lower().endswith(".csv"):
        return _dkss_http.return_form_errors([
            ("CSV形式のファイルを選択してください。", "csv_file")
        ])

    if len(filename) > 255:
        return _dkss_http.return_form_errors([
            ("ファイル名は255文字以内にしてください。", "csv_file")
        ])

    try:
        csv_file.stream.seek(0)
        file_bytes = csv_file.read()
        _dkss_common.read_vehicle_operation_csv(file_bytes)
    except _dkss_common.UploadValidationError as error:
        return _dkss_http.return_form_errors([
            (str(error), "csv_file")
        ])

    if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
        return _dkss_common.jsonify({"ok": True})

    file_digest = _dkss_common.hashlib.sha256(file_bytes).digest()

    previous_drafts = (
        _dkss_models.VehicleOperationImportDraft.query
        .filter_by(
            company_code=company_code,
            created_by_username=username,
            status="preview"
        )
        .order_by(
            _dkss_models.VehicleOperationImportDraft.created_at.desc()
        )
        .all()
    )

    for previous in previous_drafts:
        if _dkss_common.hashlib.sha256(previous.source_file).digest() == file_digest:
            return _dkss_common.redirect(_dkss_common.url_for(
                "vehicle_operation_import_preview",
                draft_id=previous.id
            ))

    draft = _dkss_models.VehicleOperationImportDraft(
        id=str(_dkss_common.uuid4()),
        company_code=company_code,
        created_by_username=username,
        source_filename=filename,
        source_file=file_bytes,
    )

    try:
        _dkss_common.db.session.add(draft)
        _dkss_common.db.session.commit()
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception(
            "デジタコCSVの一時保存に失敗しました。"
        )
        return _dkss_http.return_form_errors(
            [(
                "CSVを保存できませんでした。もう一度お試しください。",
                "csv_file"
            )],
            status_code=500
        )

    return _dkss_common.redirect(_dkss_common.url_for(
        "vehicle_operation_import_preview",
        draft_id=draft.id
    ))



def vehicle_operation_import_add_vehicle(draft_id):
    if not _dkss_access.require_master_admin():
        return _dkss_http.return_form_errors([
            ("車両の追加には管理者権限が必要です。", "")
        ], 403)

    company_code = _dkss_common.session.get("company_code")
    draft = _dkss_models.VehicleOperationImportDraft.query.filter_by(
        id=draft_id,
        company_code=company_code,
        created_by_username=_dkss_common.session.get("username")
    ).first_or_404()

    if draft.status != "preview":
        return _dkss_http.return_form_errors([
            ("このCSVの取込確認は終了しています。", "")
        ], 409)

    values = {
        key: _dkss_common.request.form.get(key, "").strip()
        for key in (
            "plate_area", "plate_class", "plate_kana", "plate_number",
            "chassis_number", "model_code", "manufacturer", "body_type",
            "first_registration_date", "inspection_expiry", "type", "office"
        )
    }
    inactive = _dkss_common.request.form.get("inactive") == "1"

    errors = _dkss_vehicle_master.validate_vehicle_text_fields(values)
    errors.extend(_dkss_vehicle_master.validate_vehicle_dates(
        values["first_registration_date"],
        values["inspection_expiry"]
    ))
    errors.extend(_dkss_vehicle_master.validate_vehicle_master_values(
        values["type"],
        values["office"],
        company_code
    ))
    weights, weight_errors = _dkss_vehicle_master.parse_vehicle_weights(_dkss_common.request.form)
    errors.extend(weight_errors)

    if not values["chassis_number"]:
        errors.append((
            "車台番号を入力してください。",
            "chassis_number"
        ))

    duplicate = _dkss_models.Vehicle.query.filter_by(
        company_code=company_code,
        chassis_number=values["chassis_number"]
    ).first()

    if duplicate:
        errors.append((
            "同じ車台番号の車両が登録済みです。登録先から選択してください。",
            "chassis_number"
        ))

    plate_keys = (
        "plate_area",
        "plate_class",
        "plate_kana",
        "plate_number"
    )
    if all(values[key] for key in plate_keys):
        plate = _dkss_common.normalize_vehicle_operation_plate(
            _dkss_vehicle_readers.vehicle_number(values)
        )
        company_vehicles = _dkss_models.Vehicle.query.filter_by(
            company_code=company_code
        ).all()

        if any(
            all(getattr(vehicle, key) for key in plate_keys)
            and _dkss_common.normalize_vehicle_operation_plate(_dkss_vehicle_readers.vehicle_number({
                key: getattr(vehicle, key) for key in plate_keys
            })) == plate
            for vehicle in company_vehicles
        ):
            errors.append((
                "同じナンバープレートの車両が登録済みです。登録先を確認してください。",
                "plate_number"
            ))

    company = _dkss_models.Company.query.filter_by(
        company_code=company_code
    ).first()

    if company and not inactive:
        active_count = _dkss_models.Vehicle.query.filter_by(
            company_code=company_code,
            deleted=False
        ).count()

        if active_count >= company.vehicle_limit:
            errors.append((
                "登録可能台数の上限に達しています。",
                ""
            ))

    if errors:
        return _dkss_http.return_form_errors(errors)

    if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
        return _dkss_common.jsonify({"ok": True})

    vehicle = _dkss_models.Vehicle(
        company_code=company_code,
        chassis_number=values["chassis_number"],
        deleted=inactive
    )
    _dkss_vehicle_master.apply_vehicle_form_values(
        vehicle,
        values,
        {**values, **weights}
    )
    _dkss_common.db.session.add(vehicle)

    try:
        _dkss_common.db.session.commit()
    except _dkss_common.IntegrityError:
        _dkss_common.db.session.rollback()
        return _dkss_http.return_form_errors([
            (
                "同じ車台番号の車両が登録済みです。登録先を確認してください。",
                "chassis_number"
            )
        ], 409)
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception(
            "運行実績取込画面からの車両追加に失敗しました。"
        )
        return _dkss_http.return_form_errors([
            (
                "車両を追加できませんでした。入力内容を保持したまま再度お試しください。",
                ""
            )
        ], 500)

    return _dkss_common.jsonify({
        "ok": True,
        "vehicle": {
            "id": vehicle.id,
            "number": _dkss_vehicle_readers.vehicle_number(values)
                + ("（無効）" if inactive else ""),
            "chassis_number": vehicle.chassis_number,
            "office": vehicle.office or "",
            "inspection_expiry": vehicle.inspection_expiry or ""
        }
    }), 201



def vehicle_operation_import_preview(draft_id):
    draft = (
        _dkss_models.VehicleOperationImportDraft.query
        .filter_by(
            id=draft_id,
            company_code=_dkss_common.session.get("company_code"),
            created_by_username=_dkss_common.session.get("username")
        )
        .first_or_404()
    )

    if draft.status != "preview":
        _dkss_common.flash(
            "このCSVの取込確認は終了しています。",
            "info"
        )
        return _dkss_common.redirect(_dkss_common.url_for(
            "vehicle_operation_import"
        ))

    try:
        csv_rows = _dkss_common.read_vehicle_operation_csv(
            draft.source_file
        )
        vehicles, preview_rows = (
            _dkss_vehicle_operations.build_vehicle_operation_import_preview(
                csv_rows,
                draft.company_code
            )
        )
    except _dkss_common.UploadValidationError as error:
        _dkss_common.flash(str(error), "error:csv_file")
        return _dkss_common.redirect(_dkss_common.url_for(
            "vehicle_operation_import"
        ))

    vehicle_ids = {vehicle.id for vehicle in vehicles}
    saved_selections = _dkss_serialization.safe_json_dict(
        draft.selection_json
    )

    for row in preview_rows:
        row["include"] = bool(
            not row["errors"]
            and not row["duplicate_in_file"]
            and row["existing_record_id"] is None
        )

        selection = saved_selections.get(
            str(row["line_number"])
        )

        if not isinstance(selection, dict):
            continue

        selected_id = selection.get("vehicle_record_id")

        if selected_id is None:
            row["vehicle_record_id"] = None
        elif (
            isinstance(selected_id, int)
            and not isinstance(selected_id, bool)
            and selected_id in vehicle_ids
        ):
            row["vehicle_record_id"] = selected_id
        else:
            row["vehicle_record_id"] = None

        row["include"] = bool(
            selection.get("include") is True
            and not row["errors"]
            and row["existing_record_id"] is None
        )

    vehicle_choices = [
        {
            "id": vehicle.id,
            "number": _dkss_vehicle_readers.vehicle_number({
                "plate_area": vehicle.plate_area or "",
                "plate_class": vehicle.plate_class or "",
                "plate_kana": vehicle.plate_kana or "",
                "plate_number": vehicle.plate_number or "",
            }) + ("（無効）" if vehicle.deleted else ""),
            "chassis_number": (
                ""
                if str(vehicle.chassis_number or "").strip().casefold()
                in {"none", "null"}
                else str(vehicle.chassis_number or "").strip()
            ),
            "office": vehicle.office or "",
            "inspection_expiry": vehicle.inspection_expiry or "",
        }
        for vehicle in vehicles
    ]

    vehicle_choices_by_id = {
        choice["id"]: choice
        for choice in vehicle_choices
    }

    for row in preview_rows:
        row["selected_vehicle_choice"] = (
            vehicle_choices_by_id.get(
                row["vehicle_record_id"]
            )
        )

    grouped_vehicle_rows = {}

    for row in preview_rows:
        if (
            row["errors"]
            or row["existing_record_id"] is not None
            or not row["include"]
        ):
            continue

        source_row = row["source_row"]
        source_code = str(
            source_row.get("車両コード") or ""
        ).strip()
        source_number = str(
            source_row.get("車両") or ""
        ).strip()

        group_key = (
            source_code,
            _dkss_common.normalize_vehicle_operation_plate(
                source_number
            ),
        )

        group = grouped_vehicle_rows.setdefault(
            group_key,
            {
                "index": len(grouped_vehicle_rows),
                "source_code": source_code,
                "source_number": source_number,
                "source_office": str(
                    source_row.get("車両：事業所") or ""
                ).strip(),
                "line_numbers": [],
                "candidate_vehicle_ids": set(),
                "selected_vehicle_ids": set(),
                "has_unselected": False,
            },
        )

        group["line_numbers"].append(
            row["line_number"]
        )
        group["candidate_vehicle_ids"].update(
            row["candidate_vehicle_ids"]
        )

        selected_id = row["vehicle_record_id"]

        if selected_id is None:
            group["has_unselected"] = True
        else:
            group["selected_vehicle_ids"].add(
                selected_id
            )

    vehicle_resolution_groups = []

    for group in grouped_vehicle_rows.values():
        if (
            not group["has_unselected"]
            and len(group["selected_vehicle_ids"]) == 1
        ):
            continue

        group["candidate_choices"] = [
            vehicle_choices_by_id[vehicle_id]
            for vehicle_id in sorted(
                group["candidate_vehicle_ids"]
            )
            if vehicle_id in vehicle_choices_by_id
        ]
        group["row_count"] = len(
            group["line_numbers"]
        )

        vehicle_resolution_groups.append(group)

    saved_errors = _dkss_serialization.safe_json_dict(
        draft.result_json
    ).get("form_errors", [])

    errors_by_field = {}

    if isinstance(saved_errors, list):
        for error in saved_errors:
            if (
                not isinstance(error, (list, tuple))
                or len(error) != 2
            ):
                continue

            message, field = error

            if not isinstance(message, str):
                continue

            if not isinstance(field, str) or not field:
                continue

            errors_by_field.setdefault(field, []).append(
                message
            )

    for row in preview_rows:
        line_number = row["line_number"]
        row["submission_errors"] = list(dict.fromkeys(
            errors_by_field.get(
                f"vehicle_{line_number}",
                []
            )
            + errors_by_field.get(
                f"include_{line_number}",
                []
            )
        ))

    return _dkss_common.render_template(
        "vehicle_operation_import_preview.html",
        draft=draft,
        preview_rows=preview_rows,
        vehicle_choices=vehicle_choices,
        vehicle_resolution_groups=vehicle_resolution_groups,
        offices=_dkss_master_readers.offices_for_current_company(),
        vehicle_types=_dkss_vehicle_readers.vehicle_types_for_current_company(),
    )



def vehicle_operation_import_confirm(draft_id):
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    draft = (
        _dkss_models.VehicleOperationImportDraft.query
        .filter_by(
            id=draft_id,
            company_code=company_code,
            created_by_username=username
        )
        .first_or_404()
    )

    if draft.status != "preview":
        _dkss_common.flash(
            "このCSVの取込確認は終了しています。",
            "info"
        )
        return _dkss_common.redirect(_dkss_common.url_for(
            "vehicle_operation_import"
        ))

    validation_only = (
        _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1"
    )

    try:
        csv_rows = _dkss_common.read_vehicle_operation_csv(
            draft.source_file
        )
        selections, records, errors = (
            _dkss_vehicle_operations.get_vehicle_operation_import_submission(
                csv_rows,
                company_code,
                _dkss_common.request.form,
                allow_pending=False,
                keep_unassigned=True
            )
        )

        submitted_confirmations = set(
            _dkss_common.request.form.getlist(
                "confirmed_vehicle_mapping"
            )
        )
        previous_selections = _dkss_serialization.safe_json_dict(
            draft.selection_json
        )

        for line_number, selection in selections.items():
            selected_id = selection.get(
                "vehicle_record_id"
            )
            previous = previous_selections.get(
                str(line_number),
                {}
            )

            if not isinstance(previous, dict):
                previous = {}

            selection["mapping_confirmed"] = bool(
                selection.get("include") is True
                and selected_id is not None
                and (
                    f"{line_number}:{selected_id}"
                    in submitted_confirmations
                    or (
                        previous.get("mapping_confirmed") is True
                        and previous.get("vehicle_record_id")
                        == selected_id
                    )
                )
            )
    except _dkss_common.UploadValidationError as error:
        return _dkss_http.return_form_errors([
            (str(error), "")
        ])

    _, checked_rows = _dkss_vehicle_operations.build_vehicle_operation_import_preview(
        csv_rows,
        company_code
    )

    selected_lines = set(_dkss_common.request.form.getlist("include"))

    excluded_error_count = sum(
        1 for row in checked_rows
        if row["existing_record_id"] is None
        and (row["errors"] or row["duplicate_in_file"])
        and str(row["line_number"]) not in selected_lines
    )

    if (
        excluded_error_count
        and _dkss_common.request.form.get("acknowledge_excluded_errors") != "1"
    ):
        errors.append((
            "エラー・重複の実績を今回は取り込まないことを確認してください。",
            "acknowledge_excluded_errors"
        ))

    if errors:
        if not validation_only:
            try:
                draft.selection_json = _dkss_common.json.dumps(
                    selections,
                    ensure_ascii=False
                )
                draft.result_json = _dkss_common.json.dumps(
                    {**_dkss_serialization.safe_json_dict(draft.result_json), "form_errors": errors},
                    ensure_ascii=False
                )
                _dkss_common.db.session.commit()
            except _dkss_common.SQLAlchemyError:
                _dkss_common.db.session.rollback()
                _dkss_runtime.app.logger.exception(
                    "デジタコCSVの選択内容を保存できませんでした。"
                )
                return _dkss_http.return_form_errors(
                    [(
                        "選択内容を保存できませんでした。"
                        "もう一度お試しください。",
                        ""
                    )],
                    status_code=500
                )

        if (
            validation_only
            or _dkss_common.request.headers.get("X-DKSS-Final-Submit") == "1"
        ):
            return _dkss_http.return_form_errors(errors)

        return _dkss_http.return_form_errors([
            (
                f"確認が必要な項目が{len(errors)}件あります。"
                "表の確認事項を確認してください。"
                "選択内容は保存されています。",
                ""
            )
        ])

    if validation_only:
        return _dkss_common.jsonify({"ok": True})

    registered_count = sum(
        row["existing_record_id"] is not None
        and str(row["line_number"]) not in selected_lines
        for row in checked_rows
    )

    excluded_count = sum(
        row["existing_record_id"] is None
        and not selections[str(row["line_number"])]["include"]
        for row in checked_rows
    )

    try:
        claimed = (
            _dkss_models.VehicleOperationImportDraft.query
            .filter_by(
                id=draft_id,
                company_code=company_code,
                created_by_username=username,
                status="preview"
            )
            .update(
                {"status": "processing"},
                synchronize_session=False
            )
        )

        if claimed != 1:
            _dkss_common.db.session.rollback()
            _dkss_common.flash(
                "このCSVはすでに処理されています。",
                "info"
            )
            return _dkss_common.redirect(_dkss_common.url_for(
                "vehicle_operation_import"
            ))

        report_numbers = [
            record["values"]["report_number"]
            for record in records
        ]
        existing_reports = set()

        for start in range(0, len(report_numbers), 400):
            existing_records = (
                _dkss_models.VehicleOperationRecord.query
                .filter(
                    _dkss_models.VehicleOperationRecord.company_code == company_code,
                    _dkss_models.VehicleOperationRecord.report_number.in_(
                        report_numbers[start:start + 400]
                    )
                )
                .all()
            )

            existing_reports.update(
                record.report_number
                for record in existing_records
            )

        imported_at = _dkss_common.datetime.now(
            _dkss_common.ZoneInfo("Asia/Tokyo")
        ).strftime("%Y-%m-%d %H:%M:%S")

        added_count = 0
        skipped_count = 0
        pending_count = 0
        imported_vehicle_ids = _dkss_vehicle_karte.get_vehicle_operation_imported_vehicle_ids(draft)

        for record in records:
            values = record["values"]

            if values["report_number"] in existing_reports:
                skipped_count += 1
                continue

            record_identity = {"report_number": values["report_number"]}
            record_key = _dkss_common.hashlib.sha256(_dkss_common.json.dumps(
                record_identity, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), default=str
            ).encode("utf-8")).hexdigest()

            if record["vehicle_record_id"] is None:
                source_code = str(values.get("source_vehicle_code") or "").strip()
                source_number = str(values.get("source_vehicle_number") or "").strip()
                group_identity = {
                    "source": "dtg7",
                    "vehicle_code": source_code,
                    "plate": _dkss_common.normalize_vehicle_operation_plate(source_number),
                }
                if not source_code and not source_number:
                    group_identity["report_number"] = values["report_number"]

                _dkss_vehicle_pending.save_vehicle_import_pending_record(
                    company_code=company_code,
                    username=username,
                    source_kind="operation",
                    source_draft_id=draft.id,
                    source_record_index=record["line_number"],
                    group_identity=group_identity,
                    identity={
                        "source_vehicle_code": source_code,
                        "source_vehicle_number": source_number,
                        "operation_date": values["operation_date"],
                    },
                    record_identity=record_identity,
                    payload=values,
                    record_date=values["operation_date"],
                )
                pending_count += 1
                continue

            pending_record = _dkss_models.VehicleImportPendingRecord.query.filter_by(
                company_code=company_code,
                source_kind="operation",
                record_key=record_key
            ).first()
            if pending_record is not None:
                incoming_payload = _dkss_common.json.loads(_dkss_common.json.dumps(values, default=str))
                if _dkss_serialization.safe_json_dict(pending_record.payload_json) != incoming_payload:
                    raise _dkss_common.UploadValidationError(
                        "登録待ちの同じ日報と内容が異なります。確認してください。"
                    )

            operation_record = _dkss_models.VehicleOperationRecord(
                company_code=company_code,
                vehicle_record_id=record["vehicle_record_id"],
                source_filename=draft.source_filename,
                imported_by_username=username,
                imported_at=imported_at,
                **values
            )
            _dkss_common.db.session.add(operation_record)
            if pending_record is not None:
                _dkss_common.db.session.flush()
                pending_record.vehicle_record_id = record["vehicle_record_id"]
                pending_record.status = "applied"
                pending_record.applied_at = _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC"))
                pending_record.result_json = _dkss_common.json.dumps({
                    "operation_record_id": operation_record.id
                })
                original_draft = _dkss_models.VehicleOperationImportDraft.query.filter_by(
                    id=pending_record.operation_draft_id,
                    company_code=company_code
                ).first()
                if original_draft is not None:
                    original_ids = _dkss_vehicle_karte.get_vehicle_operation_imported_vehicle_ids(
                        original_draft
                    )
                    original_ids.add(record["vehicle_record_id"])
                    original_draft.result_json = _dkss_common.json.dumps({
                        **_dkss_serialization.safe_json_dict(original_draft.result_json),
                        "imported_vehicle_ids": sorted(original_ids),
                    })
                _dkss_common.db.session.flush()
                remaining = _dkss_models.VehicleImportPendingRecord.query.filter_by(
                    company_code=company_code,
                    pending_id=pending_record.pending_id,
                    status="pending"
                ).first()
                if remaining is None:
                    pending = _dkss_models.VehicleImportPending.query.filter_by(
                        id=pending_record.pending_id,
                        company_code=company_code
                    ).first()
                    if pending is not None:
                        vehicle_ids = {
                            item.vehicle_record_id
                            for item in _dkss_models.VehicleImportPendingRecord.query.filter_by(
                                company_code=company_code, pending_id=pending.id
                            ).all()
                            if item.vehicle_record_id is not None
                        }
                        pending.status = "resolved"
                        pending.resolved_vehicle_id = (
                            next(iter(vehicle_ids)) if len(vehicle_ids) == 1 else None
                        )
                        pending.resolved_at = _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC"))
                        pending.resolution_json = _dkss_common.json.dumps({
                            "vehicle_ids": sorted(vehicle_ids)
                        })

            added_count += 1
            imported_vehicle_ids.add(record["vehicle_record_id"])

        confirmed_pairs = {
            f"{line_number}:{selection['vehicle_record_id']}"
            for line_number, selection in selections.items()
            if (
                selection.get("mapping_confirmed") is True
                and selection.get("include") is True
                and selection.get("vehicle_record_id") is not None
            )
        }
        selected_ids_by_key = {}
        confirmed_mapping_keys = set()

        for record in records:
            values = record["values"]
            vehicle_id = record["vehicle_record_id"]
            if vehicle_id is None:
                continue

            mapping_key = (
                str(
                    values.get("source_vehicle_code") or ""
                ).strip(),
                _dkss_common.normalize_vehicle_operation_plate(
                    values.get("source_vehicle_number")
                ),
            )

            selected_ids_by_key.setdefault(
                mapping_key,
                set()
            ).add(vehicle_id)

            confirmation = (
                f"{record['line_number']}:{vehicle_id}"
            )

            if confirmation in confirmed_pairs:
                confirmed_mapping_keys.add(
                    mapping_key
                )

        existing_mappings = {
            (
                mapping.source_vehicle_code,
                mapping.source_vehicle_number,
            ): mapping
            for mapping in (
                _dkss_models.VehicleOperationVehicleMapping.query
                .filter_by(company_code=company_code)
                .all()
            )
        }

        for mapping_key in confirmed_mapping_keys:
            selected_ids = selected_ids_by_key[
                mapping_key
            ]

            if len(selected_ids) != 1:
                continue

            source_code, source_number = mapping_key

            if not source_number:
                continue

            vehicle_id = next(iter(selected_ids))
            mapping = existing_mappings.get(
                mapping_key
            )

            if mapping is None:
                mapping = _dkss_models.VehicleOperationVehicleMapping(
                    company_code=company_code,
                    source_vehicle_code=source_code,
                    source_vehicle_number=source_number,
                    vehicle_record_id=vehicle_id,
                    confirmed_by_username=username,
                )
                _dkss_common.db.session.add(mapping)
            else:
                mapping.vehicle_record_id = vehicle_id
                mapping.confirmed_by_username = username

            mapping.confirmed_at = _dkss_common.datetime.now(
                _dkss_common.ZoneInfo("UTC")
            )

        draft.selection_json = _dkss_common.json.dumps(
            selections,
            ensure_ascii=False
        )
        draft.result_json = _dkss_common.json.dumps({
            "added_count": added_count,
            "skipped_count": skipped_count,
            "pending_count": pending_count,
            "total_count": len(csv_rows),
            "registered_count": registered_count,
            "excluded_count": excluded_count,
            "imported_vehicle_ids": sorted(imported_vehicle_ids),
        })

        _dkss_common.db.session.refresh(draft, ["status"])
        draft.status = "completed"
        draft.completed_at = _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC"))

        _dkss_common.db.session.commit()

    except _dkss_common.UploadValidationError as error:
        _dkss_common.db.session.rollback()
        return _dkss_http.return_form_errors([(str(error), "")])

    except _dkss_common.IntegrityError:
        _dkss_common.db.session.rollback()
        return _dkss_http.return_form_errors(
            [(
                "他の取込で同じ日報が登録された可能性があります。"
                "確認画面を更新して、もう一度お試しください。",
                ""
            )],
            status_code=409
        )

    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception(
            "デジタコCSVの登録に失敗しました。"
        )
        return _dkss_http.return_form_errors(
            [(
                "運行実績を登録できませんでした。"
                "もう一度お試しください。",
                ""
            )],
            status_code=500
        )

    return _dkss_common.redirect(_dkss_common.url_for(
        "vehicle_operation_import_result",
        draft_id=draft.id
    ))



def vehicle_operation_import_result(draft_id):
    draft = _dkss_models.VehicleOperationImportDraft.query.filter_by(
        id=draft_id,
        company_code=_dkss_common.session.get("company_code"),
        created_by_username=_dkss_common.session.get("username"),
        status="completed"
    ).first_or_404()

    return _dkss_common.render_template(
        "vehicle_operation_import_result.html",
        draft=draft,
        result=_dkss_serialization.safe_json_dict(draft.result_json)
    )
