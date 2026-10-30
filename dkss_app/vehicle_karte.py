"""Vehicle Karte responsibilities; routes are registered by the application factory."""
from . import import_owner as _dkss_import_owner, operation_csv_owner as _csv_owner
from . import access as _dkss_access, analysis as _dkss_analysis, audit as _dkss_audit, checklist_common as _dkss_checklist_common, checklists as _dkss_checklists, common as _dkss_common, maintenance as _dkss_maintenance, models as _dkss_models, notifications_delivery as _dkss_notifications_delivery, runtime as _dkss_runtime, serialization as _dkss_serialization, vehicle_costs as _dkss_vehicle_costs, vehicle_imports as _dkss_vehicle_imports, vehicle_operations as _dkss_vehicle_operations, vehicle_readers as _dkss_vehicle_readers


def vehicle_karte(vehicle_record_id):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=_dkss_common.session.get("company_code")
    ).first_or_404()

    number = _dkss_vehicle_readers.vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or ""
    })

    open_defects = _dkss_checklists.get_vehicle_open_inspection_defects(
        vehicle.company_code,
        vehicle.id
    )

    current_user = _dkss_models.User.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        username=_dkss_common.session.get("username")
    ).first()

    if current_user is not None:
        user_settings = _dkss_serialization.safe_json_dict(
            current_user.dashboard_settings_json
        )

        if user_settings.get(
            "vehicle_karte_last_vehicle_id"
        ) != vehicle.id:
            user_settings[
                "vehicle_karte_last_vehicle_id"
            ] = vehicle.id

            current_user.dashboard_settings_json = _dkss_common.json.dumps(
                user_settings,
                ensure_ascii=False
            )
            _dkss_common.db.session.commit()

    overview = get_vehicle_karte_overview_context(vehicle)
    return _dkss_common.render_template(
        "vehicle_karte.html", vehicle=vehicle, vehicle_number=number,
        open_defects=open_defects, **overview,
    )



def vehicle_karte_note(vehicle_record_id):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id, company_code=_dkss_common.session.get("company_code")
    ).first_or_404()
    if not _dkss_access.require_master_admin():
        return "車両メモの編集権限がありません。", 403
    content = _dkss_common.request.form.get("content", "").strip()
    version = _dkss_common.request.form.get("version", type=int)
    if len(content) > 10000 or version is None or version < 0:
        return "メモは10,000文字以内で入力してください。", 400
    note = _dkss_models.VehicleKarteNote.query.filter_by(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id
    ).first()
    now = _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M")
    try:
        if note is None and version == 0:
            _dkss_common.db.session.add(_dkss_models.VehicleKarteNote(
                company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
                content=content, version=1, updated_at=now,
                updated_by_username=_dkss_common.session.get("username"),
            ))
        elif note is not None:
            changed = _dkss_models.VehicleKarteNote.query.filter_by(
                id=note.id, company_code=vehicle.company_code, version=version
            ).update({"content": content, "version": version + 1,
                      "updated_at": now, "updated_by_username": _dkss_common.session.get("username")})
            if not changed:
                _dkss_common.db.session.rollback()
                return "他の人がメモを更新しました。画面を更新して内容を確認してください。", 409
        else:
            return "メモの状態が変わりました。画面を更新してください。", 409
        _dkss_common.db.session.commit()
    except _dkss_common.IntegrityError:
        _dkss_common.db.session.rollback()
        return "他の人がメモを更新しました。画面を更新して内容を確認してください。", 409
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("車両メモを保存できませんでした。")
        return "メモを保存できませんでした。もう一度お試しください。", 500
    _dkss_common.flash("車両メモを保存しました。", "success")
    return _dkss_common.redirect(_dkss_common.url_for("vehicle_karte", vehicle_record_id=vehicle.id, _anchor="vehicle-note"))



def get_vehicle_karte_overview_context(vehicle):
    # OVERVIEW_SUMMARY_V19: reuse the existing domain records, without AI calls.
    from vehicle_karte_overview import build_overview
    return build_overview({
        'User': _dkss_models.User,
        'VehicleChecklistResult': _dkss_models.VehicleChecklistResult,
        'VehicleKarteAnalysis': _dkss_models.VehicleKarteAnalysis,
        'VehicleKarteNote': _dkss_models.VehicleKarteNote,
        'VehicleMaintenanceInspectionLink': _dkss_models.VehicleMaintenanceInspectionLink,
        'VehicleMaintenanceRecord': _dkss_models.VehicleMaintenanceRecord,
        'VehicleOperationRecord': _dkss_models.VehicleOperationRecord,
        'VehicleDrivingReportRecord': _dkss_models.VehicleDrivingReportRecord,
        'VehiclePatrol': _dkss_models.VehiclePatrol,
        'VehiclePeriodicInspectionRecord': _dkss_models.VehiclePeriodicInspectionRecord,
        'build_vehicle_karte_documents_context': build_vehicle_karte_documents_context,
        'build_vehicle_karte_mileage_reference': _dkss_analysis.build_vehicle_karte_mileage_reference,
        'filter_vehicle_maintenance_factual_history': _dkss_analysis.filter_vehicle_maintenance_factual_history,
        'get_vehicle_karte_documents': get_vehicle_karte_documents,
        'get_vehicle_karte_history_entries': get_vehicle_karte_history_entries,
        'get_vehicle_karte_parts_context': get_vehicle_karte_parts_context,
        'get_vehicle_maintenance_cost_details': _dkss_vehicle_costs.get_vehicle_maintenance_cost_details,
        'get_vehicle_maintenance_cost_summary': _dkss_vehicle_costs.get_vehicle_maintenance_cost_summary,
        'get_vehicle_open_inspection_defects': _dkss_checklists.get_vehicle_open_inspection_defects,
        'inspection_plans': _dkss_runtime.app.extensions["dkss"]['inspection_plans'],
        'periodic_followups': _dkss_runtime.app.extensions["dkss"]['periodic_followups'],
        'periodic_inspection_synthetic_evidence': _dkss_analysis.periodic_inspection_synthetic_evidence,
        'safe_json_dict': _dkss_serialization.safe_json_dict,
    }, vehicle)






def vehicle_karte_document_source(vehicle_record_id, draft_id):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=_dkss_common.session.get("company_code")
    ).first_or_404()

    draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
        id=draft_id,
        company_code=vehicle.company_code,
        status="completed"
    ).first_or_404()

    records = _dkss_serialization.safe_json_dict(
        draft.result_json
    ).get("records", [])

    if not isinstance(records, list):
        raise _dkss_common.NotFound()

    belongs_to_vehicle = any(
        isinstance(record, dict)
        and str(record.get("vehicle_record_id", ""))
        == str(vehicle.id)
        for record in records
    )

    if not belongs_to_vehicle:
        raise _dkss_common.NotFound()

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

    data = draft.source_file
    if _dkss_common.request.args.get("download") != "1" and "preview" in _dkss_common.request.args:
        from .document_images import WIDTHS, preview
        size = _dkss_common.request.args.get("preview", type=int)
        if size not in WIDTHS:
            raise _dkss_common.NotFound()
        display = preview(draft, vehicle.id) if extension in {".jpg", ".jpeg", ".png"} else None
        if display and size in display["variants"]:
            data, mimetype = display["variants"][size], "image/webp"

    response = _dkss_common.send_file(
        _dkss_common.BytesIO(data),
        mimetype=mimetype,
        download_name=draft.source_filename,
        as_attachment=_dkss_common.request.args.get("download") == "1",
        conditional=False,
        etag=False,
        max_age=0
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"

    return response



def get_vehicle_operation_imported_vehicle_ids(draft):
    result = _dkss_serialization.safe_json_dict(draft.result_json)
    vehicle_ids = result.get("imported_vehicle_ids")

    if isinstance(vehicle_ids, list):
        return {
            value for value in vehicle_ids
            if isinstance(value, int) and not isinstance(value, bool)
        }

    # 従来の完了済みCSVは既存の表示・ダウンロード権限を維持する。
    if draft.status != "completed":
        return set()

    selections = _dkss_serialization.safe_json_dict(draft.selection_json)
    return {
        selection["vehicle_record_id"]
        for selection in selections.values()
        if isinstance(selection, dict)
        and selection.get("include") is True
        and isinstance(selection.get("vehicle_record_id"), int)
        and not isinstance(selection.get("vehicle_record_id"), bool)
    }



def vehicle_karte_operation_source(vehicle_record_id, draft_id):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=_dkss_common.session.get("company_code")
    ).first_or_404()

    draft = _dkss_models.VehicleOperationImportDraft.query.filter(
        _dkss_models.VehicleOperationImportDraft.id == draft_id,
        _dkss_models.VehicleOperationImportDraft.company_code == vehicle.company_code,
        _dkss_models.VehicleOperationImportDraft.status.in_(["preview", "completed"])
    ).first_or_404()

    _csv_owner.hold_private_source(draft)
    if vehicle.id not in get_vehicle_operation_imported_vehicle_ids(draft):
        raise _dkss_common.NotFound()

    response = _dkss_common.send_file(
        _dkss_common.BytesIO(draft.source_file),
        mimetype="text/csv",
        download_name=draft.source_filename,
        as_attachment=True,
        conditional=False,
        etag=False,
        max_age=0
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"

    return response



def build_vehicle_karte_documents_context(vehicle, documents):
    from types import SimpleNamespace

    categories = [
        ("invoice", "請求書"),
        ("maintenance", "整備記録"),
        ("inspection_3", "3か月点検"),
        ("inspection_12", "12か月点検"),
        ("inspection_vehicle", "車検"),
        ("inspection_unconfirmed", "車検／12か月点検・区分未確認"),
        ("inspection", "点検記録"),
        ("driving_report", "安全運転日報"),
        ("inspection_ad_hoc", "突発修理"),
        ("photo", "写真"),
        ("operation_csv", "運行実績CSV"),
        ("other", "その他"),
    ]
    labels = dict(categories)

    related = {}
    rows = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
        company_code=vehicle.company_code,
        vehicle_record_id=vehicle.id,
    ).order_by(_dkss_models.VehicleMaintenanceRecord.id.asc()).all()

    for row in rows:
        source = _dkss_serialization.safe_json_dict(row.invoice_details_json).get("source")
        if (
            isinstance(source, dict)
            and isinstance(source.get("draft_id"), str)
        ):
            related.setdefault(source["draft_id"], []).append(row)

    # Use registered facts, including files imported before this change.
    periodic = {}
    for row in _dkss_models.VehiclePeriodicInspectionRecord.query.filter_by(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
    ).all():
        periodic.setdefault(row.source_draft_id, []).append(row)

    usernames = {
        document.get("created_by_username")
        for document in documents
    }
    usernames.discard(None)
    usernames.discard("")

    # Import drafts only stored a login ID. Do not relabel old uploaders with a
    # different person's current name after account deletion and ID reuse.
    user_names = {
        username: f"{username}（記録時のID・本人未確認）"
        for username in usernames
    }

    now = _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo"))

    for document in documents:
        filename = document.get("filename") or "file"
        extension = _dkss_common.os.path.splitext(filename)[1].lower().lstrip(".")
        is_operation = document["document_type"] == "operation_csv"
        records = (
            related.get(document["draft_id"], [])
            if not is_operation else []
        )
        normalized = (
            filename.lower()
            .replace("３", "3")
            .replace("１２", "12")
        )

        inspection_records = periodic.get(document["draft_id"], [])
        inspection_types = {_dkss_runtime.app.extensions["dkss"]["inspection_plans"].record_kind(row) for row in inspection_records}
        if is_operation:
            kind = "operation_csv"
        elif document["document_type"] == "driving_report":
            kind = "driving_report"
        elif document["document_type"] == "inspection":
            kind = ({"3month": "inspection_3", "12month": "inspection_12", "vehicle_inspection": "inspection_vehicle", "annual_unconfirmed": "inspection_unconfirmed", "ad_hoc": "inspection_ad_hoc"}
                    .get(next(iter(inspection_types)), "inspection")
                    if len(inspection_types) == 1 else "inspection")
        elif document["document_type"] == "maintenance":
            kind = "invoice"
        elif "車検" in filename:
            kind = "inspection_vehicle"
        elif any(term in normalized for term in (
            "12か月", "12ヶ月", "12ヵ月", "12カ月",
        )):
            kind = "inspection_12"
        elif any(term in normalized for term in (
            "3か月", "3ヶ月", "3ヵ月", "3カ月",
        )):
            kind = "inspection_3"
        elif (
            "請求書" in filename
            or any(row.invoice_number for row in records)
        ):
            kind = "invoice"
        elif extension in {"png", "jpg", "jpeg", "webp", "gif"}:
            kind = "photo"
        else:
            kind = "other"

        registered_at = document.get("completed_at")
        if registered_at is not None:
            if registered_at.tzinfo is None:
                registered_at = registered_at.replace(
                    tzinfo=_dkss_common.ZoneInfo("UTC")
                )
            registered_at = registered_at.astimezone(
                _dkss_common.ZoneInfo("Asia/Tokyo")
            )

        endpoint = (
            "vehicle_karte_operation_source"
            if is_operation else "vehicle_karte_document_source"
        )
        source_url = _dkss_common.url_for(
            endpoint,
            vehicle_record_id=vehicle.id,
            draft_id=document["draft_id"],
        )
        username = document.get("created_by_username") or ""

        document.update(
            key=(
                "operation:" if is_operation else "document:"
            ) + str(document["draft_id"]),
            kind=kind,
            kind_label=labels[kind],
            extension=extension,
            source_url=source_url,
            download_url=(
                source_url if is_operation else _dkss_common.url_for(
                    endpoint,
                    vehicle_record_id=vehicle.id,
                    draft_id=document["draft_id"],
                    download="1",
                )
            ),
            registered_at=registered_at,
            date_label=(
                registered_at.strftime("%Y/%m/%d")
                if registered_at else "—"
            ),
            registered_label=(
                registered_at.strftime("%Y/%m/%d %H:%M")
                if registered_at else "—"
            ),
            uploader=username,
            uploader_label=user_names.get(username, username) or "—",
            related_content=" / ".join(dict.fromkeys(
                row.content for row in [*records, *inspection_records] if row.content
            )),
            notes="\n".join(dict.fromkeys(
                row.notes for row in records if row.notes
            )),
        )

    tabs = [{
        "key": "",
        "label": "すべて",
        "count": len(documents),
    }] + [
        {
            "key": kind,
            "label": label,
            "count": sum(
                document["kind"] == kind for document in documents
            ),
        }
        for kind, label in categories
    ]

    filters = {
        "q": _dkss_common.request.args.get("q", "").strip()[:200],
        "kind": _dkss_common.request.args.get("kind", "").strip(),
        "period": _dkss_common.request.args.get("period", "").strip(),
        "uploader": _dkss_common.request.args.get("uploader", "").strip(),
    }
    if filters["kind"] not in labels:
        filters["kind"] = ""
    if filters["period"] not in {"", "30", "90", "365"}:
        filters["period"] = ""

    filtered = documents

    if filters["kind"]:
        filtered = [
            document for document in filtered
            if document["kind"] == filters["kind"]
        ]

    if filters["q"]:
        keyword = filters["q"].casefold()
        filtered = [
            document for document in filtered
            if keyword in " ".join(
                str(document.get(key) or "")
                for key in ("filename", "notes", "related_content")
            ).casefold()
        ]

    if filters["uploader"]:
        filtered = [
            document for document in filtered
            if document["uploader"] == filters["uploader"]
        ]

    if filters["period"]:
        cutoff = now - _dkss_common.timedelta(days=int(filters["period"]))
        filtered = [
            document for document in filtered
            if document["registered_at"]
            and document["registered_at"] >= cutoff
        ]

    filtered = sorted(
        filtered,
        key=lambda document: (
            document["registered_at"].isoformat()
            if document["registered_at"] else "",
            document["key"],
        ),
        reverse=True,
    )

    per_page = _dkss_common.request.args.get("per_page", 10, type=int)
    if per_page not in {10, 20, 50}:
        per_page = 10

    pages = max(1, (len(filtered) + per_page - 1) // per_page)
    page = min(
        pages,
        max(1, _dkss_common.request.args.get("page", 1, type=int)),
    )
    items = filtered[(page - 1) * per_page:page * per_page]

    selected_key = _dkss_common.request.args.get("document", "")
    selected = None
    if selected_key and selected_key != "closed":
        selected = next((
            document for document in filtered
            if document["key"] == selected_key
        ), None)
        if selected is None:
            raise _dkss_common.NotFound()
    elif selected_key != "closed" and items:
        selected = items[0]

    return {
        "document_page": SimpleNamespace(
            items=items,
            total=len(filtered),
            page=page,
            pages=pages,
            per_page=per_page,
            has_prev=page > 1,
            has_next=page < pages,
            prev_num=page - 1,
            next_num=page + 1,
        ),
        "document_categories": tabs,
        "document_filters": filters,
        "document_uploaders": [
            {
                "username": username,
                "label": user_names.get(username, username),
            }
            for username in sorted(usernames)
        ],
        "selected_document": selected,
    }



def get_vehicle_karte_documents(vehicle):
    drafts = (
        _dkss_models.VehicleDocumentImportDraft.query
        .with_entities(
            _dkss_models.VehicleDocumentImportDraft.id,
            _dkss_models.VehicleDocumentImportDraft.source_filename,
            _dkss_models.VehicleDocumentImportDraft.created_by_username,
            _dkss_models.VehicleDocumentImportDraft.document_type,
            _dkss_models.VehicleDocumentImportDraft.result_json,
            _dkss_models.VehicleDocumentImportDraft.completed_at
        )
        .filter(
            _dkss_models.VehicleDocumentImportDraft.company_code
            == vehicle.company_code,
            _dkss_models.VehicleDocumentImportDraft.status == "completed"
        )
        .order_by(
            _dkss_models.VehicleDocumentImportDraft.completed_at.desc(),
            _dkss_models.VehicleDocumentImportDraft.id.desc()
        )
        .all()
    )

    documents = []

    for draft in drafts:
        records = _dkss_serialization.safe_json_dict(
            draft.result_json
        ).get("records", [])

        if not isinstance(records, list):
            continue

        vehicle_records = [
            record
            for record in records
            if isinstance(record, dict)
            and str(record.get("vehicle_record_id", ""))
            == str(vehicle.id)
        ]

        if not vehicle_records:
            continue

        documents.append({
            "draft_id": draft.id,
            "filename": draft.source_filename,
            "created_by_username": draft.created_by_username,
            "document_type": draft.document_type,
            "completed_at": draft.completed_at,
            "records": vehicle_records,
        })

    operation_drafts = (
        _dkss_models.VehicleOperationImportDraft.query
        .with_entities(
            _dkss_models.VehicleOperationImportDraft.id,
            _dkss_models.VehicleOperationImportDraft.source_filename,
            _dkss_models.VehicleOperationImportDraft.created_by_username,
            _dkss_models.VehicleOperationImportDraft.selection_json,
            _dkss_models.VehicleOperationImportDraft.result_json,
            _dkss_models.VehicleOperationImportDraft.status,
            _dkss_models.VehicleOperationImportDraft.created_at,
            _dkss_models.VehicleOperationImportDraft.completed_at
        )
        .filter(
            _dkss_models.VehicleOperationImportDraft.company_code
            == vehicle.company_code,
            _dkss_models.VehicleOperationImportDraft.status.in_(["preview", "completed"]),
            _csv_owner.shared_or_owned_clause()
        )
        .order_by(
            _dkss_models.VehicleOperationImportDraft.completed_at.desc(),
            _dkss_models.VehicleOperationImportDraft.id.desc()
        )
        .all()
    )

    for draft in operation_drafts:
        if vehicle.id not in get_vehicle_operation_imported_vehicle_ids(draft):
            continue

        documents.append({
            "draft_id": draft.id,
            "filename": draft.source_filename,
            "created_by_username": draft.created_by_username,
            "document_type": "operation_csv",
            "completed_at": draft.completed_at or draft.created_at,
            "records": [],
        })

    documents.sort(
        key=lambda document: (
            document["completed_at"].isoformat()
            if document["completed_at"] is not None
            else ""
        ),
        reverse=True
    )

    return documents



def vehicle_karte_documents(vehicle_record_id):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=_dkss_common.session.get("company_code")
    ).first_or_404()

    number = _dkss_vehicle_readers.vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or ""
    })

    documents = get_vehicle_karte_documents(vehicle)
    open_defects = _dkss_checklists.get_vehicle_open_inspection_defects(vehicle.company_code, vehicle.id)

    context = build_vehicle_karte_documents_context(vehicle, documents)
    selected = context["selected_document"]
    if selected and selected["key"].startswith("document:") and selected["extension"] in {"jpg", "jpeg", "png"}:
        from .document_images import preview
        draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
            id=selected["draft_id"], company_code=vehicle.company_code, status="completed"
        ).first()
        if draft is not None and any(
            isinstance(row, dict) and str(row.get("vehicle_record_id", "")) == str(vehicle.id)
            for row in _dkss_serialization.safe_json_dict(draft.result_json).get("records", [])
        ):
            selected["display_image"] = preview(draft, vehicle.id)

    return _dkss_common.render_template(
        "vehicle_karte_documents.html",
        vehicle=vehicle,
        vehicle_number=number,
        open_defects=open_defects,
        documents=documents,
        **context
    )



def vehicle_karte_inspections(vehicle_record_id):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=_dkss_common.session.get("company_code")
    ).first_or_404()

    number = _dkss_vehicle_readers.vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or ""
    })

    from vehicle_inspection_plans import normalize_kind, kind_values, READ_KINDS
    identities = _dkss_runtime.app.extensions["dkss"]["inspection_plans"]
    inspection_view = _dkss_common.request.args.get("inspection_view", "all")
    if inspection_view == 'certificate':
        inspection_view = 'vehicle_inspection'
    if inspection_view not in {"all", "daily", "periodic", *READ_KINDS}:
        inspection_view = "all"

    def valid_date_arg(name):
        value = _dkss_common.request.args.get(name, "").strip()
        try:
            return _dkss_common.datetime.strptime(value, "%Y-%m-%d").date().isoformat() if value else ""
        except ValueError:
            return ""

    inspection_start = valid_date_arg("start_date")
    inspection_end = valid_date_arg("end_date")
    if inspection_start and inspection_end and inspection_start > inspection_end:
        inspection_start, inspection_end = inspection_end, inspection_start

    daily_query = _dkss_models.VehicleChecklistResult.query.filter_by(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id)
    periodic_query = _dkss_models.VehiclePeriodicInspectionRecord.query.filter_by(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id)
    if inspection_view in READ_KINDS:
        periodic_query = periodic_query.filter(_dkss_models.VehiclePeriodicInspectionRecord.inspection_type.in_(kind_values(inspection_view)))
    for boundary, value in (("start", inspection_start), ("end", inspection_end)):
        if value:
            daily_date = _dkss_common.db.func.substr(_dkss_models.VehicleChecklistResult.checked_date, 1, 10)
            periodic_date = _dkss_models.VehiclePeriodicInspectionRecord.inspection_date
            daily_query = daily_query.filter(daily_date >= value if boundary == "start" else daily_date <= value)
            periodic_query = periodic_query.filter(periodic_date >= value if boundary == "start" else periodic_date <= value)

    page = max(1, _dkss_common.request.args.get("page", 1, type=int))

    per_page = _dkss_common.request.args.get("per_page", 10, type=int)
    if per_page not in {10, 20, 50}:
        per_page = 10

    periodic_per_page = _dkss_common.request.args.get("periodic_per_page", 10, type=int)
    if periodic_per_page not in {10, 20, 50}:
        periodic_per_page = 10

    inspection_page = (
        daily_query
        .order_by(
            _dkss_models.VehicleChecklistResult.checked_date.desc(),
            _dkss_models.VehicleChecklistResult.id.desc()
        )
        .paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
    )

    inspection_snapshots = {
        record.id: _dkss_serialization.safe_json_dict(record.checklist_snapshot_json)
        for record in inspection_page.items
    }

    inspection_links = {
        record.id: _dkss_common.url_for(
            "vehicle_checklist_results",
            index=record.checklist_id,
            vehicle_record_id=vehicle.id,
            year=record.year,
            month=record.month,
            active_day=record.day
        )
        for record in inspection_page.items
    }

    periodic_page_number = max(
        1,
        _dkss_common.request.args.get("periodic_page", 1, type=int)
    )

    if inspection_view in READ_KINDS:
        matching_ids = [r.id for r in periodic_query.all() if identities.record_kind(r) == inspection_view]
        periodic_query = periodic_query.filter(_dkss_models.VehiclePeriodicInspectionRecord.id.in_(matching_ids))
    periodic_inspection_page = (
        periodic_query
        .order_by(
            _dkss_models.VehiclePeriodicInspectionRecord.inspection_date.desc(),
            _dkss_models.VehiclePeriodicInspectionRecord.id.desc()
        )
        .paginate(
            page=periodic_page_number,
            per_page=periodic_per_page,
            error_out=False
        )
    )

    periodic_invoices = {record.id: [] for record in periodic_inspection_page.items}
    if periodic_invoices:
        for invoice in _dkss_models.VehicleMaintenanceRecord.query.filter_by(
            company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
        ).all():
            inspection_id = _dkss_serialization.safe_json_dict(
                invoice.invoice_details_json
            ).get("periodic_inspection_id")
            if type(inspection_id) is int and inspection_id in periodic_invoices:
                periodic_invoices[inspection_id].append(invoice)

    return _dkss_common.render_template(
        "vehicle_karte_inspections.html",
        inspection_view=inspection_view,
        inspection_start=inspection_start, inspection_end=inspection_end,
        vehicle=vehicle,
        vehicle_number=number,
        inspection_page=inspection_page,
        inspection_snapshots=inspection_snapshots,
        inspection_results={
            record.id: _dkss_checklist_common.vehicle_checklist_result_to_dict(record)
            for record in inspection_page.items
        },
        inspection_links=inspection_links,
        periodic_inspection_page=periodic_inspection_page,
        periodic_invoices=periodic_invoices,
        inspection_kind_labels=READ_KINDS, inspection_identities=identities,
        periodic_followup_summary=_dkss_runtime.app.extensions["dkss"]['periodic_followups'].summary(vehicle.company_code, vehicle.id),
        manual_inspection_executions=[row for row in _dkss_runtime.app.extensions["dkss"]['inspection_plans'].manual_records(vehicle.company_code, vehicle.id)
            if (inspection_view not in READ_KINDS or identities.execution_kind(row) == inspection_view)
            and (not inspection_start or row.performed_date >= inspection_start)
            and (not inspection_end or row.performed_date <= inspection_end)],
        periodic_details={record.id: _dkss_serialization.safe_json_dict(record.details_json)
                          for record in periodic_inspection_page.items},
        open_defects=_dkss_checklists.get_vehicle_open_inspection_defects(
            vehicle.company_code,
            vehicle.id
        )
    )



def get_vehicle_karte_history_entries(company_code, vehicle_record_id, *, read_snapshot=None):
    entries = []
    if read_snapshot is not None:
        read_snapshot.require_scope(company_code, vehicle_record_id)

    def records_for(model):
        if read_snapshot is not None:
            return read_snapshot.rows(model)
        return model.query.filter_by(
            company_code=company_code, vehicle_record_id=vehicle_record_id,
        ).all()

    def normalize_date(value):
        text = str(value or "").strip()[:10]

        for date_format in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return _dkss_common.datetime.strptime(
                    text,
                    date_format
                ).strftime("%Y-%m-%d")
            except ValueError:
                continue

        return ""

    inspection_records = records_for(_dkss_models.VehicleChecklistResult)

    for record in inspection_records:
        snapshot = _dkss_serialization.safe_json_dict(record.checklist_snapshot_json)
        items = _dkss_serialization.safe_json_dict_list(
            _dkss_common.json.dumps(snapshot.get("items") or [])
        )
        is_daily_inspection = any(
            item.get("fixed_template_code")
            == "daily_inspection_truck_trailer"
            for item in items
        )

        inspection_date = normalize_date(
            f"{record.year}-"
            f"{str(record.month).zfill(2)}-"
            f"{str(record.day).zfill(2)}"
        )

        entries.append({
            "key": f"inspection:{record.id}",
            "date": inspection_date,
            "kind": "日常点検" if is_daily_inspection else "点検",
            "content": snapshot.get("name") or "車両チェックリスト",
            "files": list(dict.fromkeys(
                filename
                for answer in _dkss_serialization.safe_json_dict_list(record.answers_json)
                for filename in (
                    answer.get("files")
                    if isinstance(answer.get("files"), list)
                    else []
                )
                if isinstance(filename, str) and filename.strip()
            )),
            "mileage": None,
            "cost": None,
            "status": record.status or "",
            "actor": record.checked_by or record.checked_by_username or "",
            "link": _dkss_common.url_for(
                "vehicle_checklist_results",
                index=record.checklist_id,
                vehicle_record_id=vehicle_record_id,
                year=record.year,
                month=record.month,
                active_day=record.day
            ),
        })

        if is_daily_inspection:
            judgment = _dkss_serialization.safe_json_dict(record.operation_judgment_json)
            stored_defects = judgment.get("defects") or []
            defects = [
                dict(defect)
                for defect in stored_defects
                if isinstance(defect, dict)
            ] if isinstance(stored_defects, list) else []

            for answer in _dkss_serialization.safe_json_dict_list(record.answers_json):
                if str(answer.get("value") or "").strip() != "×":
                    continue

                item_no = str(answer.get("item_no", ""))
                accounted_for = False

                for defect in defects:
                    if str(defect.get("item_no", "")) != item_no:
                        continue

                    rechecked_answer = defect.get("rechecked_answer") or {}
                    if not isinstance(rechecked_answer, dict):
                        rechecked_answer = {}

                    if (
                        defect.get("status") != "解消"
                        or all(
                            rechecked_answer.get(field) == answer.get(field)
                            for field in ("value", "comment", "files")
                        )
                    ):
                        accounted_for = True
                        break

                if not accounted_for:
                    defects.append({
                        "item_no": item_no,
                        "status": "対応待ち",
                        "reported_answer": dict(answer),
                    })

            if isinstance(defects, list):
                for defect_index, defect in enumerate(defects):
                    if not isinstance(defect, dict):
                        continue

                    answer = defect.get("reported_answer") or {}
                    if not isinstance(answer, dict):
                        answer = {}

                    item_name = str(answer.get("content") or "").strip()
                    comment = str(answer.get("comment") or "").strip()
                    content = " / ".join(
                        value for value in (item_name, comment) if value
                    )

                    entries.append({
                        "key": (
                            f"defect:{record.id}:{defect_index}"
                        ),
                        "date": (
                            normalize_date(defect.get("reported_at"))
                            or inspection_date
                        ),
                        "kind": "異常・指摘",
                        "content": content or "日常点検の不具合",
                        "files": list(dict.fromkeys(
                            filename
                            for filename in (
                                answer.get("files")
                                if isinstance(answer.get("files"), list)
                                else []
                            )
                            if isinstance(filename, str) and filename.strip()
                        )),
                        "mileage": None,
                        "cost": None,
                        "status": defect.get("status") or "",
                        "actor": (
                            defect.get("reported_by")
                            or record.checked_by
                            or record.checked_by_username
                            or ""
                        ),
                        "link": _dkss_common.url_for(
                            "vehicle_checklist_results",
                            index=record.checklist_id,
                            vehicle_record_id=vehicle_record_id,
                            year=record.year,
                            month=record.month,
                            active_day=record.day
                        ),
                    })

    entries.extend(_dkss_runtime.app.extensions["dkss"]['periodic_followups'].history(company_code, vehicle_record_id))

    from vehicle_inspection_plans import READ_KINDS
    periodic_records = records_for(_dkss_models.VehiclePeriodicInspectionRecord)
    for record in periodic_records:
        entries.append({
            "key": f"periodic:{record.id}",
            "date": normalize_date(record.inspection_date),
            "kind": READ_KINDS.get(
                _dkss_runtime.app.extensions["dkss"]["inspection_plans"].record_kind(record), "定期点検"
            ),
            "content": record.content or "定期点検記録",
            "files": [],
            "mileage": record.mileage,
            "cost": None,
            "status": "登録済み",
            "actor": " / ".join(value for value in (
                record.inspection_company, record.inspector_name
            ) if value),
            "link": _dkss_common.url_for("vehicle_periodic_inspection_source", record_id=record.id),
        })

    plan_events = _dkss_common.db.session.query(_dkss_runtime.VehicleInspectionPlanEvent, _dkss_runtime.VehicleInspectionPlan).join(
        _dkss_runtime.VehicleInspectionPlan, _dkss_runtime.VehicleInspectionPlan.id == _dkss_runtime.VehicleInspectionPlanEvent.plan_id
    ).filter(
        _dkss_runtime.VehicleInspectionPlan.company_code == company_code,
        _dkss_runtime.VehicleInspectionPlan.vehicle_record_id == vehicle_record_id,
        _dkss_runtime.VehicleInspectionPlanEvent.company_code == company_code,
    ).all()
    for change, plan in plan_events:
        snapshot = _dkss_serialization.safe_json_dict(change.detail_json)
        after = snapshot.get("after") or {}
        kind_label = READ_KINDS.get(_dkss_runtime.app.extensions["dkss"]["inspection_plans"].plan_kind(plan), "点検")
        action_label = {"cancelled": "取消", "completed": "実施記録と連動", "completed_manual": "実施先行登録", "document_attached": "点検簿を関連付け", "created_from_document": "点検簿から作成"}.get(change.action, "登録・変更")
        entries.append({
            "key": f"inspection-plan:{change.id}",
            "date": normalize_date(change.created_at),
            "kind": "点検予定",
            "content": f"{kind_label} {action_label} / 予定月 {after.get('planned_month', '')} / 予約日 {after.get('reservation_date') or '未定'} / {after.get('factory') or '実施先未定'}",
            "files": [], "mileage": None, "cost": None,
            "status": {"planned": "予定", "completed": "実施済み", "cancelled": "取消"}.get(after.get("status"), ""),
            "actor": change.created_by,
            "link": _dkss_common.url_for("vehicle_inspection_plans", scope="vehicle", vehicle_id=vehicle_record_id, kind=plan.kind),
        })

    for execution in _dkss_runtime.app.extensions["dkss"]['inspection_plans'].manual_records(company_code, vehicle_record_id):
        entries.append({
            "key": f"inspection-execution:{execution.id}", "date": execution.performed_date,
            "kind": READ_KINDS.get(_dkss_runtime.app.extensions["dkss"]["inspection_plans"].execution_kind(execution), "点検"),
            "content": "点検実施（書類未受領） / " + (execution.factory or "実施先未登録") + (" / " + execution.note if execution.note else ""),
            "files": [], "mileage": None, "cost": None, "status": "実施済み・書類未受領",
            "actor": execution.created_by,
            "link": _dkss_common.url_for("vehicle_karte_inspections", vehicle_record_id=vehicle_record_id, inspection_view="periodic") + f"#manual-execution-{execution.id}",
        })

    driving_reports = records_for(_dkss_models.VehicleDrivingReportRecord)

    for record in driving_reports:
        entries.append({
            "key": f"driving-report:{record.id}",
            "date": normalize_date(record.operation_date),
            "kind": "安全運転日報",
            "content": record.content or "安全運転日報",
            "files": [],
            "mileage": record.mileage,
            "cost": None,
            "status": "",
            "actor": "",
            "link": _dkss_common.url_for(
                "vehicle_driving_report_source",
                record_id=record.id
            ),
        })

    maintenance_records = records_for(_dkss_models.VehicleMaintenanceRecord)

    for record in maintenance_records:
        invoice_details = _dkss_serialization.safe_json_dict(record.invoice_details_json)
        invoice_source = invoice_details.get("source")
        if not isinstance(invoice_source, dict):
            invoice_source = {}
        source_draft_id = invoice_source.get("draft_id")

        entries.append({
            "key": f"maintenance:{record.id}",
            "date": (
                normalize_date(record.completion_date)
                or normalize_date(record.entry_date)
            ),
            "kind": record.category or "整備",
            "content": (
                record.content
                or record.repair_content
                or record.symptom
                or ""
            ),
            "files": list(dict.fromkeys(
                _dkss_serialization.safe_json_str_list(record.files_json)
            )),
            "mileage": record.mileage,
            "cost": record.total_cost,
            "status": record.status or "",
            "actor": " / ".join(
                value
                for value in (
                    record.maintenance_company,
                    record.maintenance_person
                )
                if value
            ),
            "link": (
                _dkss_common.url_for(
                    "vehicle_karte_document_source",
                    vehicle_record_id=vehicle_record_id,
                    draft_id=source_draft_id,
                )
                if source_draft_id
                else None
            ),
        })

    repair_events = (
        _dkss_models.ChecklistEvent.query
        .join(
            _dkss_models.VehicleChecklistResult,
            _dkss_models.ChecklistEvent.result_id == _dkss_models.VehicleChecklistResult.id
        )
        .filter(
            _dkss_models.ChecklistEvent.company_code == company_code,
            _dkss_models.ChecklistEvent.result_type == "vehicle",
            _dkss_models.ChecklistEvent.event_type.in_(["整備中", "再確認待ち"]),
            _dkss_models.VehicleChecklistResult.company_code == company_code,
            _dkss_models.VehicleChecklistResult.vehicle_record_id == vehicle_record_id
        )
        .all()
    )

    for event in repair_events:
        detail = _dkss_serialization.safe_json_dict(event.detail_json)
        repair = detail.get("repair") or {}
        if not isinstance(repair, dict) or not repair:
            continue

        defect = detail.get("defect") or {}
        if not isinstance(defect, dict):
            defect = {}

        answer = defect.get("reported_answer") or {}
        if not isinstance(answer, dict):
            answer = {}

        item_name = str(answer.get("content") or "").strip()
        note = str(repair.get("note") or "").strip()
        content = " / ".join(
            value for value in (item_name, note) if value
        )

        result_record = _dkss_common.db.session.get(
            _dkss_models.VehicleChecklistResult,
            event.result_id
        )
        if not result_record:
            continue

        entries.append({
            "key": f"inspection-repair:{event.id}",
            "date": normalize_date(repair.get("performed_at")),
            "kind": "整備",
            "content": content or "日常点検の不具合対応",
            "mileage": None,
            "cost": None,
            "status": repair.get("status") or event.event_type or "",
            "actor": (
                repair.get("performed_by")
                or event.actor_name
                or ""
            ),
            "link": _dkss_common.url_for(
                "vehicle_checklist_results",
                index=result_record.checklist_id,
                vehicle_record_id=vehicle_record_id,
                year=result_record.year,
                month=result_record.month,
                active_day=result_record.day
            ),
        })

    entries.sort(
        key=lambda entry: (entry["date"], entry["key"]),
        reverse=True
    )

    return entries



def get_vehicle_maintenance_import_context(batch_id):
    company_code = _dkss_common.session.get("company_code")
    drafts = _dkss_models.VehicleDocumentImportDraft.query.filter_by(batch_id=batch_id, company_code=company_code, document_type="maintenance", status="completed").filter(_dkss_import_owner.owner_clause(_dkss_models.VehicleDocumentImportDraft)).order_by(_dkss_models.VehicleDocumentImportDraft.id.asc()).all()

    requested = []
    for draft in drafts:
        rows = _dkss_serialization.safe_json_dict(draft.result_json).get("records", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            record_id = row.get("record_id")
            vehicle_id = row.get("vehicle_record_id")
            if (
                row.get("document_type") == "maintenance"
                and type(record_id) is int and record_id > 0
                and type(vehicle_id) is int and vehicle_id > 0
            ):
                requested.append((record_id, vehicle_id))

    if not requested:
        raise _dkss_common.NotFound()

    records = _dkss_models.VehicleMaintenanceRecord.query.filter(
        _dkss_models.VehicleMaintenanceRecord.company_code == company_code,
        _dkss_models.VehicleMaintenanceRecord.id.in_([item[0] for item in requested]),
    ).all()
    record_map = {record.id: record for record in records}
    ordered_records = {}
    for record_id, vehicle_id in requested:
        record = record_map.get(record_id)
        if record is not None and record.vehicle_record_id == vehicle_id:
            ordered_records[record_id] = record

    vehicle_ids = list(dict.fromkeys(
        record.vehicle_record_id for record in ordered_records.values()
    ))
    vehicles = _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.company_code == company_code,
        _dkss_models.Vehicle.id.in_(vehicle_ids),
    ).all()
    vehicle_map = {vehicle.id: vehicle for vehicle in vehicles}
    targets = []
    for vehicle_id in vehicle_ids:
        vehicle = vehicle_map.get(vehicle_id)
        if vehicle is None:
            continue
        record_ids = [
            record.id for record in ordered_records.values()
            if record.vehicle_record_id == vehicle_id
        ]
        targets.append({
            "id": vehicle_id,
            "number": _dkss_vehicle_readers.vehicle_number({
                "plate_area": vehicle.plate_area or "",
                "plate_class": vehicle.plate_class or "",
                "plate_kana": vehicle.plate_kana or "",
                "plate_number": vehicle.plate_number or "",
            }),
            "count": len(record_ids),
            "record_ids": record_ids,
            "url": _dkss_common.url_for(
                "vehicle_karte_maintenance",
                vehicle_record_id=vehicle_id,
                import_batch=batch_id,
            ),
        })

    if not targets:
        raise _dkss_common.NotFound()
    return {
        "batch_id": batch_id,
        "vehicles": targets,
        "total": sum(target["count"] for target in targets),
    }



def get_vehicle_maintenance_record_events(record):
    labels = {
        "content": "整備内容",
        "category": "分類",
        "status": "状態",
        "entry_date": "入庫日",
        "completion_date": "完了日",
        "mileage": "走行距離（km）",
        "symptom": "症状",
        "cause": "原因",
        "temporary_action": "応急処置",
        "repair_content": "修理内容",
        "maintenance_company": "整備会社",
        "maintenance_person": "整備担当",
        "repair_hours": "作業時間",
        "invoice_number": "請求書番号",
        "invoice_date": "請求日",
        "cost_office": "整備時の営業所",
        "parts_cost": "部品代（円）",
        "labor_cost": "工賃（円）",
        "other_cost": "その他費用（円）",
        "tax_amount": "消費税（円）",
        "total_cost": "合計金額（円）",
        "notes": "備考",
    }
    numeric_fields = {
        "mileage", "repair_hours", "parts_cost", "labor_cost",
        "other_cost", "tax_amount", "total_cost",
    }
    action_labels = {
        "created": "整備記録を登録",
        "updated": "整備記録を編集",
        "status_changed": "状態を変更",
        "imported": "資料から取り込み",
    }

    events = _dkss_models.VehicleMaintenanceRecordEvent.query.filter_by(
        company_code=record.company_code,
        vehicle_record_id=record.vehicle_record_id,
        maintenance_record_id=record.id,
    ).order_by(
        _dkss_models.VehicleMaintenanceRecordEvent.created_at.desc(),
        _dkss_models.VehicleMaintenanceRecordEvent.id.desc(),
    ).limit(50).all()

    items = []
    for event in events:
        changes = []
        for change in _dkss_serialization.safe_json_dict_list(event.changes_json):
            field = change.get("field")
            if field == "invoice_read_correction":
                source = change.get("source") or {}
                changes.append({
                    "label": ("請求書の読取訂正：" + source["filename"]) if source else "手入力の整備費用の訂正",
                    "before": (change.get("before") or {}).get("total_cost") or "—",
                    "after": (change.get("after") or {}).get("total_cost") or "—",
                })
                continue
            if field not in labels:
                continue
            if change.get("before") == change.get("after"):
                continue
            if field == "status" and event.action == "status_changed":
                continue

            def display(value):
                if field in numeric_fields:
                    return format_vehicle_maintenance_number(value)
                return str(value) if value is not None and value != "" else "—"

            changes.append({
                "label": labels[field],
                "before": display(change.get("before")),
                "after": display(change.get("after")),
            })

        items.append({
            "label": action_labels.get(event.action, "記録を更新"),
            "date": (event.created_at or "")[:16].replace("T", " "),
            "username": event.created_by_username or "",
            "actor": (event.actor_name or event.created_by_username or "—")
                     if event.actor_identity else f"{event.created_by_username or '—'}（旧記録・本人未確認）",
            "status_before": event.status_before,
            "status_after": event.status_after,
            "status_changed": event.action == "status_changed",
            "changes": changes,
        })

    if record.created_at and not any(
        event.action in {"created", "imported"} for event in events
    ):
        items.append({
            "label": "登録（既存記録）",
            "date": record.created_at[:16].replace("T", " "),
            "username": record.created_by_username or "",
            "actor": f"{record.created_by_username or '—'}（旧記録・本人未確認）",
            "status_before": None,
            "status_after": None,
            "status_changed": False,
            "changes": [],
        })

    return items



def validate_vehicle_maintenance_form(form, *, entry_date_required=True):
    values = {}
    errors = []

    text_fields = {
        "content": ("整備内容", 5000),
        "category": ("分類", 50),
        "status": ("状態", 50),
        "symptom": ("症状", 5000),
        "cause": ("原因", 5000),
        "temporary_action": ("応急処置", 5000),
        "repair_content": ("修理内容", 5000),
        "maintenance_company": ("整備会社", 200),
        "maintenance_person": ("整備担当", 100),
        "invoice_number": ("請求書番号", 100),
        "cost_office": ("整備時の営業所", 100),
        "notes": ("備考", 10000),
    }

    for field, (label, limit) in text_fields.items():
        text = form.get(field, "").strip()
        values[field] = text or None
        if len(text) > limit:
            errors.append((
                f"{label}は{limit}文字以内で入力してください。",
                field,
            ))

    if not values["content"]:
        errors.append(("整備内容を入力してください。", "content"))

    for field, label in (
        ("entry_date", "入庫日"),
        ("completion_date", "完了日"),
        ("invoice_date", "請求日"),
    ):
        text = form.get(field, "").strip()
        values[field] = text or None

        if not text:
            if field == "entry_date" and entry_date_required:
                errors.append(("入庫日を入力してください。", field))
            continue

        try:
            parsed = _dkss_common.datetime.strptime(text, "%Y-%m-%d")
            if parsed.strftime("%Y-%m-%d") != text:
                raise ValueError()
        except ValueError:
            errors.append((f"{label}を正しく入力してください。", field))

    date_errors = {field for _, field in errors}
    if (
        values["entry_date"] and values["completion_date"]
        and not {"entry_date", "completion_date"} & date_errors
        and values["completion_date"] < values["entry_date"]
    ):
        errors.append((
            "完了日は入庫日以降にしてください。",
            "completion_date",
        ))

    for field, label, maximum, nonnegative in (
        ("mileage", "走行距離", "999999999999.99", True),
        ("repair_hours", "作業時間", "99999999.99", True),
        ("parts_cost", "部品代", "999999999999.99", False),
        ("labor_cost", "工賃", "999999999999.99", False),
        ("other_cost", "その他費用", "999999999999.99", False),
        ("tax_amount", "消費税", "999999999999.99", False),
        ("total_cost", "合計金額", "999999999999.99", False),
    ):
        text = form.get(field, "").strip()
        values[field] = None

        if not text:
            continue

        try:
            if len(text) > 100:
                raise ValueError()

            amount = _dkss_vehicle_imports.parse_maintenance_invoice_number(text)
            if (
                not amount.is_finite()
                or abs(amount) > _dkss_common.Decimal(maximum)
                or (nonnegative and amount < 0)
                or amount != amount.quantize(_dkss_common.Decimal("0.01"))
            ):
                raise ValueError()

            values[field] = amount
        except (_dkss_common.InvalidOperation, ValueError):
            errors.append((
                f"{label}は範囲内の数値を小数2桁までで入力してください。",
                field,
            ))

    return values, errors



def save_vehicle_maintenance_replacement_parts(
    record, *, allow_unconfirmed=False
):
    if (
        record.id is None
        or record.company_code != _dkss_common.session.get("company_code")
    ):
        raise ValueError("Invalid maintenance record")

    lines = _dkss_common.json.loads(record.line_items_json or "[]")
    if (
        not isinstance(lines, list)
        or len(lines) > 1000
        or not all(isinstance(line, dict) for line in lines)
    ):
        raise ValueError("Invalid maintenance lines")

    def number(raw, required=False, positive=False):
        if raw is None or str(raw).strip() == "":
            if required:
                raise ValueError("Missing replacement quantity")
            return None
        if isinstance(raw, bool) or len(str(raw)) > 100:
            raise ValueError("Invalid replacement number")
        value = _dkss_vehicle_imports.parse_maintenance_invoice_number(raw)
        if (
            not value.is_finite()
            or abs(value) > _dkss_common.Decimal("999999999999.99")
            or value != value.quantize(_dkss_common.Decimal("0.01"))
            or (positive and value <= 0)
        ):
            raise ValueError("Invalid replacement number")
        return value

    prepared = []
    for index, line in enumerate(lines):
        action = line.get("replacement_action")
        if action == "not_replace":
            continue
        if action == "review" and allow_unconfirmed:
            continue
        if action != "replace":
            raise ValueError("Unconfirmed replacement line")

        part_name = str(
            line.get("replacement_part_name") or ""
        ).strip()
        part_number = str(
            line.get("part_number") or ""
        ).strip()
        if not part_name or len(part_name) > 200:
            raise ValueError("Invalid replacement part name")
        if len(part_number) > 100:
            raise ValueError("Invalid replacement part number")

        prepared.append({
            "index": index,
            "version": _dkss_common.hashlib.sha256(_dkss_common.json.dumps(
                line,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ).encode("utf-8")).hexdigest(),
            "part_name": part_name,
            "part_number": part_number or None,
            "quantity": number(
                line.get("quantity"),
                required=True,
                positive=True,
            ),
            "cost": number(line.get("parts_amount")),
            "notes": line.get("notes") or None,
        })

    if not prepared:
        return 0

    replacement_date = (
        record.completion_date or record.entry_date or ""
    )
    parsed_date = _dkss_common.datetime.strptime(
        replacement_date, "%Y-%m-%d"
    ).date()
    if parsed_date.isoformat() != replacement_date:
        raise ValueError("Invalid replacement date")

    existing_sources = {
        item.source_line_index: item
        for item in _dkss_models.VehiclePartReplacementSource.query.filter_by(
            company_code=record.company_code,
            maintenance_record_id=record.id,
        ).all()
    }

    now = _dkss_common.datetime.now(
        _dkss_common.ZoneInfo("Asia/Tokyo")
    ).isoformat(timespec="seconds")
    created_count = 0

    for item in prepared:
        existing = existing_sources.get(item["index"])
        if existing is not None:
            if existing.source_line_version != item["version"]:
                raise ValueError("Registered source line has changed")
            existing_part = _dkss_common.db.session.get(
                _dkss_models.VehiclePartReplacement,
                existing.replacement_id,
            )
            if (
                existing_part is None
                or existing_part.company_code != record.company_code
                or existing_part.vehicle_record_id != record.vehicle_record_id
                or existing_part.maintenance_record_id != record.id
            ):
                raise ValueError("Invalid replacement source link")
            continue

        part = _dkss_models.VehiclePartReplacement(
            company_code=record.company_code,
            vehicle_record_id=record.vehicle_record_id,
            maintenance_record_id=record.id,
            part_name=item["part_name"],
            part_number=item["part_number"],
            quantity=item["quantity"],
            replacement_date=replacement_date,
            mileage=record.mileage,
            cost=item["cost"],
            notes=item["notes"],
            created_by_username=_dkss_common.session.get("username"),
            created_at=now,
            updated_by_username=_dkss_common.session.get("username"),
            updated_at=now,
        )
        _dkss_common.db.session.add(part)
        _dkss_common.db.session.flush()

        _dkss_common.db.session.add(_dkss_models.VehiclePartReplacementSource(
            company_code=record.company_code,
            maintenance_record_id=record.id,
            replacement_id=part.id,
            source_line_index=item["index"],
            source_line_version=item["version"],
        ))
        _dkss_common.db.session.flush()
        created_count += 1

    return created_count



def get_vehicle_karte_parts_context(vehicle, factual_only=False, *, read_snapshot=None):
    from types import SimpleNamespace
    if read_snapshot is not None:
        read_snapshot.require_scope(vehicle.company_code, vehicle.id)

    rows = (
        _dkss_common.db.session.query(
            _dkss_models.VehiclePartReplacement,
            _dkss_models.VehicleMaintenanceRecord,
        )
        .join(
            _dkss_models.VehicleMaintenanceRecord,
            _dkss_models.VehiclePartReplacement.maintenance_record_id
            == _dkss_models.VehicleMaintenanceRecord.id,
        )
        .filter(
            _dkss_models.VehiclePartReplacement.company_code == vehicle.company_code,
            _dkss_models.VehiclePartReplacement.vehicle_record_id == vehicle.id,
            _dkss_models.VehicleMaintenanceRecord.company_code == vehicle.company_code,
            _dkss_models.VehicleMaintenanceRecord.vehicle_record_id == vehicle.id,
        )
        .order_by(
            _dkss_models.VehiclePartReplacement.replacement_date.asc(),
            _dkss_models.VehiclePartReplacement.maintenance_record_id.asc(),
            _dkss_models.VehiclePartReplacement.id.asc(),
        )
        .all()
    )

    maintenance = {
        record.id: record
        for record in (
            read_snapshot.rows(_dkss_models.VehicleMaintenanceRecord) if read_snapshot is not None
            else _dkss_models.VehicleMaintenanceRecord.query.filter_by(
                company_code=vehicle.company_code,
                vehicle_record_id=vehicle.id,
            ).all()
        )
    }

    if factual_only:
        factual, _, _ = _dkss_analysis.filter_vehicle_maintenance_factual_history(list(maintenance.values()))
        maintenance = {record.id: record for record in factual}
        rows = [(part, record) for part, record in rows if record.id in maintenance]

    sources = (
        _dkss_models.VehiclePartReplacementSource.query.filter_by(
            company_code=vehicle.company_code,
        )
        .filter(
            _dkss_models.VehiclePartReplacementSource.maintenance_record_id.in_(
                list(maintenance)
            )
        )
        .all()
        if maintenance else []
    )
    source_map = {
        source.replacement_id: source for source in sources
    }
    line_map = {
        record.id: _dkss_serialization.safe_json_dict_list(record.line_items_json)
        for record in maintenance.values()
    }

    groups = {}
    history = []
    pending = []

    for record in maintenance.values():
        for index, line in enumerate(line_map[record.id]):
            if (line.get("replacement_action") or "review") == "review":
                pending.append({
                    "maintenance_record_id": record.id,
                    "invoice_number": record.invoice_number,
                    "line_index": index,
                    "description": line.get("description") or "名称未読取",
                })

    for part, record in rows:
        key = (part.part_name, part.part_number or "")
        source = source_map.get(part.id)
        line = {}

        if source and source.maintenance_record_id == record.id:
            original = line_map.get(record.id, [])
            if 0 <= source.source_line_index < len(original):
                line = original[source.source_line_index]

        category = str(
            line.get("replacement_category") or "未分類"
        ).strip()[:50] or "未分類"
        status = record.status or (
            "完了" if record.completion_date else "未設定"
        )

        group = groups.setdefault(key, {
            "part_name": part.part_name,
            "part_number": part.part_number,
            "latest": part,
            "events": {},
            "category": category,
        })

        if record.id not in group["events"]:
            previous = (
                group["latest"].mileage if group["events"] else None
            )
            distance = (
                part.mileage - previous
                if previous is not None
                and part.mileage is not None
                and part.mileage >= previous
                else None
            )
            group["events"][record.id] = (
                len(group["events"]) + 1,
                distance,
            )

        count, distance = group["events"][record.id]
        group.update(latest=part, category=category)

        history.append({
            "part": part,
            "category": category,
            "status": status,
            "replacement_count": count,
            "distance": distance,
        })

    priorities = (
        "エンジンオイル",
        "オイルエレメント",
        "タイヤ",
        "ブレーキパッド",
        "ファンベルト",
        "バッテリ",
        "フューエルフィルタ",
        "エアクリーナ",
    )

    def normalize(value):
        return (
            "".join(value.split())
            .replace("・", "")
            .replace("ー", "")
        )

    part_groups = []
    for group in groups.values():
        group["replacement_count"] = len(group.pop("events"))
        name = normalize(group["part_name"])
        if any(
            word in name
            for word in (
                "ガスケット", "パッキン", "シール",
                "キャップ", "ドレン", "オイルパン",
            )
        ):
            group["priority"] = 99
        elif "オイル" in name and any(
            word in name for word in ("エレメント", "フィルタ")
        ):
            group["priority"] = 1
        else:
            group["priority"] = next(
                (
                    index
                    for index, word in enumerate(priorities)
                    if normalize(word) in name
                ),
                99,
            )
        part_groups.append(group)

    ranking = sorted(
        part_groups,
        key=lambda group: (
            -group["replacement_count"],
            group["part_name"],
            group["part_number"] or "",
        ),
    )

    state_scope = _dkss_common.request.args.get("parts_scope", "major")
    if state_scope not in {"major", "all"}:
        state_scope = "major"

    major = sorted(
        (
            group for group in part_groups
            if group["priority"] < 99
        ),
        key=lambda group: (
            group["priority"],
            group["part_name"],
            group["part_number"] or "",
        ),
    )[:6]

    state_groups = (
        major if state_scope == "major"
        else sorted(
            part_groups,
            key=lambda group: (
                group["part_name"],
                group["part_number"] or "",
            ),
        )
    )

    search_query = (_dkss_common.request.args.get("q") or "").strip()[:200]
    selected_category = (
        _dkss_common.request.args.get("part_category") or ""
    ).strip()[:50]
    selected_status = (
        _dkss_common.request.args.get("part_status") or ""
    ).strip()[:50]

    categories = sorted({row["category"] for row in history})
    statuses = sorted({row["status"] for row in history})

    if selected_category not in categories:
        selected_category = ""
    if selected_status not in statuses:
        selected_status = ""

    filtered = [
        row for row in reversed(history)
        if (
            (
                not search_query
                or search_query.casefold() in (
                    row["part"].part_name
                    + " "
                    + (row["part"].part_number or "")
                ).casefold()
            )
            and (
                not selected_category
                or row["category"] == selected_category
            )
            and (
                not selected_status
                or row["status"] == selected_status
            )
        )
    ]

    per_page = _dkss_common.request.args.get("per_page", 10, type=int)
    if per_page not in {10, 20, 50}:
        per_page = 10

    total = len(filtered)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(
        max(1, _dkss_common.request.args.get("page", 1, type=int)),
        pages,
    )
    first = (page - 1) * per_page

    return {
        "part_rows": filtered[first:first + per_page],
        "part_groups": part_groups,
        "part_ranking": ranking[:5],
        "part_state_groups": state_groups,
        "part_categories": categories,
        "part_statuses": statuses,
        "part_search_query": search_query,
        "selected_part_category": selected_category,
        "selected_part_status": selected_status,
        "selected_parts_scope": state_scope,
        "pending_part_lines": pending,
        "part_page": SimpleNamespace(
            page=page,
            pages=pages,
            total=total,
            per_page=per_page,
            first=first + 1 if total else 0,
            last=min(first + per_page, total),
        ),
        "format_part_number": format_vehicle_maintenance_number,
    }



def vehicle_karte_parts(vehicle_record_id):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=_dkss_common.session.get("company_code"),
    ).first_or_404()

    number = _dkss_vehicle_readers.vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or "",
    })

    return _dkss_common.render_template(
        "vehicle_karte_parts.html",
        vehicle=vehicle,
        vehicle_number=number,
        **get_vehicle_karte_parts_context(vehicle),
    )



def get_maintenance_inspection_choices(vehicle, record):
    links = _dkss_models.VehicleMaintenanceInspectionLink.query.filter_by(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
        maintenance_record_id=record.id,
    ).all() if record is not None else []
    linked = {(row.inspection_result_id, row.defect_no) for row in links}
    choices = []
    results = _dkss_models.VehicleChecklistResult.query.filter_by(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
    ).order_by(_dkss_models.VehicleChecklistResult.id.asc()).all()
    for result in results:
        snapshot = _dkss_serialization.safe_json_dict(result.checklist_snapshot_json)
        if not any(item.get("fixed_template_code") == "daily_inspection_truck_trailer" for item in snapshot.get("items", []) if isinstance(item, dict)):
            continue
        judgment = _dkss_serialization.safe_json_dict(result.operation_judgment_json)
        for defect in judgment.get("defects", []):
            if not isinstance(defect, dict) or type(defect.get("defect_no")) is not int or defect["defect_no"] < 1:
                continue
            key = (result.id, defect["defect_no"])
            saved = key in linked
            if not saved:
                continue
            choices.append({
                "key": f"{key[0]}:{key[1]}",
                "token": f"{key[0]}:{key[1]}:{int(judgment.get('version') or 0)}",
                "linked": saved,
                "status": defect.get("status") or "",
                "label": f"{result.year}/{str(result.month).zfill(2)}/{str(result.day).zfill(2)} No.{int(defect.get('item_no', 0)) + 1} " + str((defect.get("reported_answer") or {}).get("content") or "点検指摘"),
                "link": _dkss_common.url_for("vehicle_checklist_results", index=result.checklist_id, vehicle_record_id=vehicle.id, year=result.year, month=result.month, active_day=result.day) + f"#vehicle-flow-defect-{result.id}-{defect['defect_no']}",
            })
    if linked != {(int(c["key"].split(":")[0]), int(c["key"].split(":")[1])) for c in choices if c["linked"]}:
        raise ValueError("紐付け済みの点検指摘を確認できません。元の点検記録を確認してください。")
    return choices



def validate_maintenance_inspection_selection(choices, tokens):
    if len(tokens) > 100 or len(tokens) != len(set(tokens)):
        raise ValueError("点検指摘の選択内容を確認してください。")
    available = {choice["token"]: choice for choice in choices}
    if any(token not in available for token in tokens):
        raise ValueError("点検指摘が更新されています。画面を開き直してください。")
    selected = [available[token] for token in tokens]
    if not {c["key"] for c in choices if c["linked"]} <= {c["key"] for c in selected}:
        raise ValueError("保存済みの点検指摘との紐付けは解除できません。")
    return selected



def sync_maintenance_inspection_links(record, choices, values, intent, current_user):
    targets = []
    changed = False
    updated_results = []
    local_now = _dkss_checklist_common.get_user_local_now(record.company_code, current_user.username)
    if intent == "complete":
        performed = _dkss_common.datetime.strptime(values.get("completion_date") or "", "%Y-%m-%d")
        if performed.date() > local_now.date():
            raise ValueError("整備完了日に未来の日付は指定できません。")
    grouped = {}
    for choice in choices:
        result_id, defect_no = map(int, choice["key"].split(":"))
        grouped.setdefault(result_id, []).append((defect_no, choice))
    for result_id, selected in grouped.items():
        result = _dkss_models.VehicleChecklistResult.query.filter_by(id=result_id, company_code=record.company_code, vehicle_record_id=record.vehicle_record_id).with_for_update().populate_existing().first()
        if result is None:
            raise ValueError("対象の点検記録を確認できません。")
        previous_json = result.operation_judgment_json
        previous = _dkss_serialization.safe_json_dict(previous_json)
        version = int(previous.get("version") or 0)
        if any(choice["token"] != f"{result_id}:{number}:{version}" for number, choice in selected):
            raise ValueError("点検指摘が更新されています。画面を開き直してください。")
        for number, choice in selected:
            link = _dkss_models.VehicleMaintenanceInspectionLink.query.filter_by(company_code=record.company_code, vehicle_record_id=record.vehicle_record_id, maintenance_record_id=record.id, inspection_result_id=result_id, defect_no=number).first()
            new_link = link is None
            if new_link:
                link = _dkss_models.VehicleMaintenanceInspectionLink(company_code=record.company_code, vehicle_record_id=record.vehicle_record_id, maintenance_record_id=record.id, inspection_result_id=result_id, defect_no=number)
                _dkss_common.db.session.add(link)
                changed = True
            defects = [dict(item) for item in previous.get("defects", [])]
            defect = next((d for d in defects if d.get("defect_no") == number), None)
            if defect is None:
                raise ValueError("対象の不具合を確認できません。")
            # Ordinary corrections do not reopen or complete an inspection defect.
            if intent != "complete":
                continue
            if defect.get("status") not in {"対応待ち", "整備中"}:
                raise ValueError("再確認中または解消済みの指摘です。元の点検画面で状態を確認してください。")
            next_status = "再確認待ち" if intent == "complete" else "整備中"
            date_text = values.get("completion_date") if intent == "complete" else values.get("entry_date")
            performed = _dkss_common.datetime.strptime(date_text or "", "%Y-%m-%d")
            inspection_date = _dkss_common.datetime(int(result.year), int(result.month), int(result.day)).date()
            if performed.date() < inspection_date or performed.date() > local_now.date():
                raise ValueError("整備実施日は点検日以降、今日以前にしてください。")
            repair = {
                "status": next_status,
                "note": values.get("repair_content") or values.get("content") or "",
                "performed_by": (current_user.last_name or "") + (current_user.first_name or ""),
                "performed_by_username": current_user.username,
                "performed_at": performed.strftime("%Y-%m-%d"),
                "recorded_at": local_now.strftime("%Y-%m-%d %H:%M:%S"),
                "notification_created_at": local_now.astimezone(_dkss_common.ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "timezone": str(local_now.tzinfo),
                "maintenance_record_id": record.id,
            }
            previous_defect = dict(defect)
            defect.update(status=next_status, repair=repair)
            judgment = {**previous, "defects": defects, "status": "未判定", "version": version + 1}
            for key in ("reason", "judged_by", "judged_by_username", "judged_at", "authority_role", "authority_confirmed", "checks_confirmed", "checks_evidence"):
                judgment.pop(key, None)
            targets.extend(persist_vehicle_inspection_repair(result, record.company_code, current_user, previous_json, judgment, next_status, repair, previous_defect, defect, previous, False))
            if result not in updated_results:
                updated_results.append(result)
            # The following selected defect belongs to the same transaction/version.
            previous = judgment
            previous_json = _dkss_common.json.dumps(judgment, ensure_ascii=False)
            version += 1
            changed = True
    return targets, changed, updated_results



def dispatch_maintenance_inspection_notifications(targets):
    for user, notification in targets:
        try:
            _dkss_notifications_delivery.dispatch_external_notification(user, notification.title, notification.message, notification.link, notification_id=notification.id)
        except Exception:
            _dkss_runtime.app.logger.exception("不具合対応の外部通知に失敗しました。")



def carry_inspection_repair_to_maintenance(result_record, defect_no, previous_defect, repair, current_user):
    """Carry a known inspection repair into the karte in the caller's transaction."""
    company_code = result_record.company_code
    vehicle_id = result_record.vehicle_record_id
    vehicle = _dkss_models.Vehicle.query.filter_by(id=vehicle_id, company_code=company_code).first()
    if vehicle is None or current_user.company_code != company_code:
        raise ValueError("INSPECTION_MAINTENANCE_SCOPE_INVALID")
    links = _dkss_models.VehicleMaintenanceInspectionLink.query.filter_by(
        company_code=company_code, vehicle_record_id=vehicle_id,
        inspection_result_id=result_record.id, defect_no=defect_no,
    ).all()
    records = []
    for link in links:
        record = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
            id=link.maintenance_record_id, company_code=company_code,
            vehicle_record_id=vehicle_id,
        ).with_for_update().first()
        if record is None:
            raise ValueError("INSPECTION_MAINTENANCE_LINK_INVALID")
        records.append(record)

    previous_repair = previous_defect.get("repair") or {}
    previous_id = previous_repair.get("maintenance_record_id")
    if previous_id is not None and (
        type(previous_id) is not int or previous_id not in {row.id for row in records}
    ):
        raise ValueError("INSPECTION_MAINTENANCE_REFERENCE_INVALID")
    record = None
    if previous_defect.get("status") == "整備中" and previous_id is not None:
        record = next(row for row in records if row.id == previous_id)
        if record.status == "完了":
            raise ValueError("INSPECTION_MAINTENANCE_STATE_CONFLICT")
    else:
        unfinished = [row for row in records if row.status != "完了"]
        if len(unfinished) > 1:
            raise ValueError("INSPECTION_MAINTENANCE_AMBIGUOUS")
        record = unfinished[0] if unfinished else None

    created = record is None
    stamp = repair["recorded_at"]
    if created:
        record = _dkss_models.VehicleMaintenanceRecord(
            company_code=company_code, vehicle_record_id=vehicle_id,
            category="修理", content=repair["note"],
            symptom=str((previous_defect.get("reported_answer") or {}).get("content") or ""),
            created_by_username=current_user.username, created_at=stamp,
        )
        _dkss_common.db.session.add(record)
    status_before = record.status
    changes = []
    updates = {
        "repair_content": repair["note"],
        "status": "完了" if repair["status"] == "再確認待ち" else "整備中",
        "maintenance_person": repair["performed_by"],
    }
    if repair["status"] == "再確認待ち":
        updates["completion_date"] = repair["performed_at"][:10]
    for field, after in updates.items():
        before = getattr(record, field)
        if before != after:
            setattr(record, field, after)
            changes.append({"field": field, "before": before, "after": after})
    # An inspection repair date does not establish an arrival date, mileage or cost.
    record.updated_by_username = current_user.username
    record.updated_at = stamp
    _dkss_common.db.session.flush()
    if created:
        _dkss_common.db.session.add(_dkss_models.VehicleMaintenanceInspectionLink(
            company_code=company_code, vehicle_record_id=vehicle_id,
            maintenance_record_id=record.id,
            inspection_result_id=result_record.id, defect_no=defect_no,
        ))
    repair["maintenance_record_id"] = record.id
    changes.append({
        "field": "inspection_repair", "before": previous_repair,
        "after": {"inspection_result_id": result_record.id, "defect_no": defect_no, **repair},
    })
    _dkss_maintenance.add_vehicle_maintenance_record_event(
        record, action="created" if created else "status_changed" if status_before != record.status else "updated",
        changes=changes, status_before=status_before,
    )
    return record



def persist_vehicle_inspection_repair(result_record, company_code, current_user, previous_json, judgment, next_status, repair, previous_defect, defect, previous, is_recheck):
    updated = _dkss_models.VehicleChecklistResult.query.filter_by(
        id=result_record.id,
        company_code=company_code,
        operation_judgment_json=previous_json
    ).update(
        {"operation_judgment_json": _dkss_common.json.dumps(judgment, ensure_ascii=False)},
        synchronize_session=False
    )
    if updated != 1:
        raise ValueError("INSPECTION_UPDATE_CONFLICT")

    _dkss_checklists.invalidate_other_vehicle_operation_judgments(result_record)

    _dkss_common.db.session.add(_dkss_models.ChecklistEvent(
        company_code=company_code,
        result_type="vehicle",
        result_id=result_record.id,
        event_type=next_status,
        actor_username=current_user.username,
        actor_name=repair["performed_by"],
        created_at=repair["recorded_at"],
        detail_json=_dkss_common.json.dumps({
            "previous_defect": previous_defect,
            "defect": defect,
            "repair": {} if is_recheck else repair,
            "recheck": repair if is_recheck else {},
            "previous_judgment": previous,
        }, ensure_ascii=False)
    ))

    notification_targets = []
    if next_status == "再確認待ち" or is_recheck:
        target_usernames = set(previous.get("requested_usernames") or [])

        if not target_usernames:
            inspector = _dkss_models.User.query.filter_by(
                company_code=company_code,
                username=result_record.checked_by_username
            ).first()

            if inspector and inspector.office:
                target_usernames.update(
                    user.username
                    for user in _dkss_models.User.query.filter_by(
                        company_code=company_code,
                        office=inspector.office,
                        role="admin"
                    ).all()
                )

        if result_record.checked_by_username:
            target_usernames.add(result_record.checked_by_username)

        vehicle = _dkss_models.Vehicle.query.filter_by(
            id=result_record.vehicle_record_id,
            company_code=company_code
        ).first()
        vehicle_name = (
            " ".join(value for value in [
                vehicle.plate_area or "",
                vehicle.plate_class or "",
                vehicle.plate_kana or "",
                vehicle.plate_number or ""
            ] if value)
            if vehicle else ""
        ) or f"車両ID：{result_record.vehicle_record_id}"

        item_name = (
            defect.get("reported_answer", {}).get("content") or ""
        )

        if not is_recheck:
            notification_action = "再確認待ち"
            next_action = (
                "整備した箇所を再確認し、再確認結果を登録してください。"
            )
        elif next_status == "解消":
            notification_action = "再確認済み・異常なし"
            next_action = (
                "この不具合の再確認は完了しました。"
                "整備管理者は、ほかの未解消の不具合と点検結果を確認し、"
                "運行可否を判断してください。"
            )
        else:
            notification_action = "再確認で異常あり"
            next_action = (
                "異常が残っています。整備内容を確認し、"
                "追加の整備を登録してください。"
            )

        notification_title = (
            f"{vehicle_name}：{notification_action}"
        )
        notification_message = (
            f"対象車両：{vehicle_name}\n"
            f"点検日：{result_record.year}/{result_record.month}/{result_record.day}\n"
            f"項目：No.{int(defect.get('item_no', 0)) + 1} {item_name}\n"
            f"対応状況：{next_status}\n"
            f"次にすること：{next_action}\n"
            f"実施者：{repair['performed_by']}\n"
            f"実施日時：{repair['performed_at']}\n"
            f"内容：{repair['note']}"
        )
        notification_link = _dkss_common.url_for(
            "vehicle_checklist_results",
            index=result_record.checklist_id,
            vehicle_record_id=result_record.vehicle_record_id,
            year=result_record.year,
            month=result_record.month,
            active_day=result_record.day
        ) + (
            f"#vehicle-flow-defect-{result_record.id}-"
            f"{defect.get('defect_no')}"
        )

        for target_username in sorted(target_usernames):
            target_user = _dkss_models.User.query.filter_by(
                company_code=company_code,
                username=target_username
            ).first()
            if not target_user:
                continue

            notification = _dkss_models.Notification(
                company_code=company_code,
                target_user=(target_user.last_name or "")
                + (target_user.first_name or ""),
                target_username=target_user.username,
                owner_identity=target_user.account_identity,
                title=notification_title,
                message=notification_message,
                link=notification_link,
                files_json="[]",
                read=False,
                created_at=repair["notification_created_at"]
            )
            _dkss_common.db.session.add(notification)
            notification_targets.append((target_user, notification))

    return notification_targets



def vehicle_maintenance_record_version(record):
    snapshot = {
        column.key: getattr(record, column.key)
        for column in _dkss_common.inspect(record).mapper.column_attrs
    }
    return _dkss_common.hashlib.sha256(_dkss_common.json.dumps(
        snapshot,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")).hexdigest()



def vehicle_karte_maintenance_form(vehicle_record_id, record_id):
    if not _dkss_access.require_master_admin():
        return "整備記録の登録・編集は管理者のみ利用できます。", 403

    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=_dkss_common.session.get("company_code"),
    ).first_or_404()

    if _dkss_common.request.method == "POST" and record_id is not None:
        # Financial review already locks company -> document -> record. Take
        # the same outer lock before the record/source-read locks below.
        company = _dkss_models.Company.query.filter_by(company_code=vehicle.company_code).populate_existing().with_for_update().first()
        if company is None or company.active is not True:
            raise _dkss_common.NotFound()

    if _dkss_common.request.method == "POST" and _dkss_runtime.app.extensions["dkss"]['periodic_followups'].for_maintenance(vehicle.company_code, record_id):
        _dkss_runtime.app.extensions["dkss"]['periodic_followups'].lock(vehicle.company_code)

    if _dkss_common.request.method == "POST" and (
        _dkss_common.request.form.getlist("inspection_defect")
        or (record_id is not None and _dkss_models.VehicleMaintenanceInspectionLink.query.filter_by(
            company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
            maintenance_record_id=record_id,
        ).first() is not None)
    ):
        lock_error = _dkss_checklists.lock_vehicle_inspection_updates(
            vehicle.company_code, vehicle_record_id=vehicle.id,
            checklist={"items": [{"fixed_template_code": "daily_inspection_truck_trailer"}]},
        )
        if lock_error is not None:
            return lock_error

    record = None
    if record_id is not None:
        query = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
            id=record_id,
            company_code=vehicle.company_code,
            vehicle_record_id=vehicle.id,
        )
        if _dkss_common.request.method == "POST":
            query = query.with_for_update()
        record = query.first_or_404()

    field_names = (
        "content", "category", "status",
        "entry_date", "completion_date", "mileage",
        "symptom", "cause", "temporary_action", "repair_content",
        "maintenance_company", "maintenance_person", "repair_hours",
        "invoice_number", "invoice_date", "cost_office",
        "parts_cost", "labor_cost", "other_cost",
        "tax_amount", "total_cost", "notes",
    )
    form_values = {
        field: getattr(record, field) if record is not None else ""
        for field in field_names
    }
    if record is None:
        form_values["cost_office"] = vehicle.office or ""
    record_version = (
        vehicle_maintenance_record_version(record) if record else ""
    )
    from . import invoice_cost_reads
    invoice_view = None
    invoice_context = None
    invoice_context_error = None
    if record is not None:
        try:
            invoice_view = invoice_cost_reads.projection(record)
            invoice_context = invoice_cost_reads.form_context(invoice_view)
        except ValueError as error:
            invoice_context_error = str(error)
    invoice_change = None
    try:
        inspection_choices = get_maintenance_inspection_choices(vehicle, record)
    except ValueError:
        _dkss_runtime.app.logger.warning("Unable to load maintenance inspection choices", exc_info=True)
        return "点検情報を確認できませんでした。画面を再読み込みしてください。", 409
    periodic_issues = _dkss_runtime.app.extensions["dkss"]['periodic_followups'].for_maintenance(vehicle.company_code, record_id)
    selected_inspection_tokens = [c["token"] for c in inspection_choices if c["linked"]]
    # Inspection repairs do not establish an arrival date. Keep that unknown
    # value editable without requiring the user to invent a date.
    entry_date_required = not (
        record is not None
        and not record.entry_date
        and (any(choice["linked"] for choice in inspection_choices) or periodic_issues)
    )
    selected_inspections = []
    intent = ""
    notification_targets = []
    inspection_results_updated = []
    errors = []
    response_status = 200

    if _dkss_common.request.method == "POST":
        form_values = {
            field: _dkss_common.request.form.get(field, "")
            for field in field_names
        }
        values, errors = validate_vehicle_maintenance_form(
            _dkss_common.request.form, entry_date_required=entry_date_required,
        )
        if record is not None and "cost_office" not in _dkss_common.request.form:
            values["cost_office"] = record.cost_office
        intent = _dkss_common.request.form.get("maintenance_action", "save")
        selected_inspection_tokens = _dkss_common.request.form.getlist("inspection_defect")
        try:
            selected_inspections = validate_maintenance_inspection_selection(
                inspection_choices, selected_inspection_tokens,
            )
            if intent not in {"save", "draft", "complete"}:
                raise ValueError("保存操作を確認してください。")
            if record is not None and record.is_invoice_actual:
                if intent != "save":
                    raise ValueError("請求書の実績は読取内容の訂正として保存してください。")
                values["status"] = record.status
                if set(selected_inspection_tokens) != {
                    c["token"] for c in inspection_choices if c["linked"]
                }:
                    raise ValueError("請求書の訂正では点検の関連を変更できません。")
            elif intent == "complete":
                if not values.get("completion_date"):
                    raise ValueError("整備完了日を入力してください。")
                values["status"] = "完了"
            elif intent in {"draft", "save"}:
                values["status"] = record.status if record and record.status == "完了" else "整備中"
        except ValueError as error:
            errors.append((str(error), "inspection_defects"))

        if record is not None:
            submitted_version = _dkss_common.request.form.get("record_version", "")
            if not _dkss_common.secrets.compare_digest(
                submitted_version.encode("utf-8"),
                record_version.encode("ascii"),
            ):
                errors.append((
                    "この記録は別の操作で更新されています。最新の記録を確認してください。",
                    "record_version",
                ))
                response_status = 409
            record_version = submitted_version

        if record is not None and not errors:
            cost_fields = invoice_cost_reads.FIELDS
            changed_cost = any(values[f] != getattr(record, f) for f in cost_fields)
            selected_source = _dkss_common.request.form.get('invoice_source', '')
            if invoice_context_error and changed_cost:
                errors.append((invoice_context_error, 'invoice_source'))
                response_status = 409
            elif invoice_view is not None and (changed_cost or selected_source):
                try:
                    invoice_view = invoice_cost_reads.projection(record, lock=True)
                    version = _dkss_common.request.form.get('invoice_read_version', '')
                    # Old single-source clients still identify one real original;
                    # a mixed aggregate must never be assigned to a guessed source.
                    if not selected_source and len(invoice_view['sources']) == 1 and not invoice_view['unresolved']:
                        selected_source = invoice_view['sources'][0]['key']
                        version = invoice_view['version']
                    recalculated, invoice_change = invoice_cost_reads.apply_read(
                        record, invoice_view, selected_source, version,
                        {f: values[f] for f in cost_fields},
                        confirm_evidence=_dkss_common.request.form.get('invoice_evidence_confirmed') == '1')
                    values.update(recalculated)
                except ValueError as error:
                    errors.append((str(error), 'invoice_source'))
                    response_status = 409
        if errors:
            _dkss_common.db.session.rollback()
            if response_status == 200:
                response_status = 400
        else:
            is_new = record is None
            changed_fields = [
                field for field in field_names
                if is_new or getattr(record, field) != values[field]
            ]
            status_before = record.status if record is not None else None
            changes = [
                {
                    "field": field,
                    "before": (
                        getattr(record, field) if not is_new else None
                    ),
                    "after": values[field],
                }
                for field in changed_fields
            ]

            if not changed_fields and invoice_change is None and intent != "complete" and all(c["linked"] for c in selected_inspections):
                _dkss_common.flash("変更はありませんでした。", "success")
                return _dkss_common.redirect(_dkss_common.url_for(
                    "vehicle_karte_maintenance",
                    vehicle_record_id=vehicle.id,
                    record_id=record.id,
                ))

            try:
                now = _dkss_common.datetime.now(
                    _dkss_common.ZoneInfo("Asia/Tokyo")
                ).isoformat(timespec="seconds")

                if is_new:
                    record = _dkss_models.VehicleMaintenanceRecord(
                        company_code=vehicle.company_code,
                        vehicle_record_id=vehicle.id,
                        created_by_username=_dkss_common.session.get("username"),
                        created_at=now,
                    )
                    _dkss_common.db.session.add(record)

                if not is_new and {
                    "mileage", "entry_date", "completion_date"
                }.intersection(changed_fields):
                    previous_date = (
                        record.completion_date or record.entry_date or ""
                    )
                    replacement_date = (
                        values["completion_date"] or values["entry_date"] or ""
                    )
                    previous_mileage = record.mileage
                    source_lines = _dkss_serialization.safe_json_dict_list(record.line_items_json)
                    part_sources = (
                        _dkss_models.VehiclePartReplacementSource.query.filter_by(
                            company_code=record.company_code,
                            maintenance_record_id=record.id,
                        ).all()
                    )

                    for source in part_sources:
                        index = source.source_line_index
                        if (
                            type(index) is not int
                            or not 0 <= index < len(source_lines)
                        ):
                            continue

                        line = source_lines[index]
                        line_version = _dkss_common.hashlib.sha256(_dkss_common.json.dumps(
                            line,
                            sort_keys=True,
                            ensure_ascii=False,
                            default=str,
                        ).encode("utf-8")).hexdigest()
                        if (
                            line.get("replacement_action") != "replace"
                            or source.source_line_version != line_version
                        ):
                            continue

                        part = (
                            _dkss_models.VehiclePartReplacement.query.filter_by(
                                id=source.replacement_id,
                                company_code=record.company_code,
                                vehicle_record_id=record.vehicle_record_id,
                                maintenance_record_id=record.id,
                            )
                            .with_for_update()
                            .populate_existing()
                            .first()
                        )
                        if part is None:
                            continue

                        part_changes = []
                        if (
                            previous_date != replacement_date
                            and part.replacement_date == previous_date
                        ):
                            part_changes.append((
                                "replacement_date",
                                part.replacement_date,
                                replacement_date,
                            ))
                        if (
                            previous_mileage != values["mileage"]
                            and part.mileage == previous_mileage
                        ):
                            part_changes.append((
                                "mileage", part.mileage, values["mileage"],
                            ))

                        for field, before, after in part_changes:
                            setattr(part, field, after)
                            changes.append({
                                "field": f"part_replacement:{part.id}:{field}",
                                "before": before,
                                "after": after,
                            })
                        if part_changes:
                            part.updated_by_username = _dkss_common.session.get("username")
                            part.updated_at = now

                for field in field_names:
                    setattr(record, field, values[field])

                record.updated_by_username = _dkss_common.session.get("username")
                record.updated_at = now
                _dkss_common.db.session.flush()
                saved_id = record.id
                if not record.is_invoice_actual and (selected_inspections or intent == "complete"):
                    current_user = _dkss_models.User.query.filter_by(
                        company_code=vehicle.company_code,
                        username=_dkss_common.session.get("username"),
                    ).first()
                    if not current_user:
                        raise ValueError("操作ユーザーを確認できません。")
                    notification_targets, links_changed, inspection_results_updated = sync_maintenance_inspection_links(
                        record, selected_inspections, values, intent, current_user,
                    )
                    if links_changed:
                        changes.append({
                            "field": "inspection_links",
                            "before": [c["key"] for c in inspection_choices if c["linked"]],
                            "after": [c["key"] for c in selected_inspections],
                        })

                if periodic_issues and not record.is_invoice_actual:
                    periodic_user = _dkss_models.User.query.filter_by(company_code=vehicle.company_code, username=_dkss_common.session.get("username")).first()
                    if periodic_user is None:
                        raise ValueError("操作ユーザーを確認できません。")
                    _dkss_runtime.app.extensions["dkss"]['periodic_followups'].sync_maintenance(record, intent, periodic_user)

                if invoice_change is not None:
                    changes.append(invoice_change)
                _dkss_maintenance.add_vehicle_maintenance_record_event(
                    record,
                    action=(
                        "created" if is_new
                        else "status_changed" if "status" in changed_fields
                        else "updated"
                    ),
                    changes=changes,
                    status_before=status_before,
                )

                _dkss_audit.add_audit_log(
                    action=(
                        "maintenance_created"
                        if is_new else "maintenance_updated"
                    ),
                    target_type="vehicle_maintenance_record",
                    target_id=saved_id,
                    detail=_dkss_common.json.dumps({
                        "vehicle_record_id": vehicle.id,
                        "changed_fields": changed_fields,
                    }, ensure_ascii=False),
                    company_code=vehicle.company_code,
                )
                _dkss_common.db.session.commit()

            except ValueError as error:
                _dkss_common.db.session.rollback()
                errors.append((str(error), "inspection_defects"))
                response_status = 409

            except _dkss_common.SQLAlchemyError:
                _dkss_common.db.session.rollback()
                _dkss_runtime.app.logger.exception("Maintenance record save failed")
                errors.append((
                    "保存できませんでした。時間をおいて再度お試しください。",
                    "",
                ))
                response_status = 500

            else:
                for result in inspection_results_updated:
                    try:
                        _dkss_checklists.dispatch_vehicle_defect_notifications(result)
                    except Exception:
                        _dkss_runtime.app.logger.exception("不具合対応の通知配信に失敗しました。")
                dispatch_maintenance_inspection_notifications(notification_targets)
                _dkss_common.flash(
                    "整備記録を登録しました。"
                    if is_new else "整備記録を更新しました。",
                    "success",
                )
                return _dkss_common.redirect(_dkss_common.url_for(
                    "vehicle_karte_maintenance",
                    vehicle_record_id=vehicle.id,
                    record_id=saved_id,
                ))

    number = _dkss_vehicle_readers.vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or "",
    })

    if invoice_context is not None:
        invoice_context['selection'] = _dkss_common.request.form.get('invoice_source', '') if _dkss_common.request.method == 'POST' else _dkss_common.request.args.get('invoice_source', '')
        if _dkss_common.request.method == 'POST':
            invoice_context['submitted'] = {f: form_values[f] for f in invoice_cost_reads.FIELDS}
            invoice_context['evidence_confirmed'] = _dkss_common.request.form.get('invoice_evidence_confirmed') == '1'
    rendered = _dkss_common.render_template(
        "vehicle_karte_maintenance_form.html",
        vehicle=vehicle,
        vehicle_number=number,
        maintenance_record=record if record_id is not None else None,
        invoice_actual=bool(record is not None and record.is_invoice_actual),
        invoice_cost_context=invoice_context,
        invoice_cost_context_error=invoice_context_error,
        form_values=form_values,
        form_errors=errors,
        record_version=record_version,
        inspection_choices=inspection_choices,
        periodic_issues=periodic_issues,
        selected_inspection_tokens=selected_inspection_tokens,
        entry_date_required=entry_date_required,
    )
    response = _dkss_runtime.app.make_response((rendered, response_status))
    if errors and (invoice_context is not None or invoice_context_error):
        # This response already contains the submitted values and recovery UI.
        # Reuse the established recovery marker instead of redirecting it away.
        response.headers['X-DKSS-Import-Recovery'] = '1'
        response.headers['Cache-Control'] = 'private, no-store'
    return response



def format_vehicle_maintenance_number(value):
    if value is None or value == "" or isinstance(value, bool):
        return "—"
    try:
        amount = _dkss_common.Decimal(str(value).replace(",", ""))
    except (_dkss_common.InvalidOperation, TypeError, ValueError):
        return "—"
    if not amount.is_finite() or abs(amount) > _dkss_common.Decimal("99999999999999.99"):
        return "—"
    text = format(amount, ",.2f")
    return text.rstrip("0").rstrip(".")



def vehicle_karte_maintenance(vehicle_record_id, record_id):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=_dkss_common.session.get("company_code"),
    ).first_or_404()

    number = _dkss_vehicle_readers.vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or "",
    })

    query = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
        company_code=vehicle.company_code,
        vehicle_record_id=vehicle.id,
    )
    import_batch = _dkss_common.request.args.get("import_batch", "").strip()
    import_context = (
        get_vehicle_maintenance_import_context(import_batch)
        if import_batch else None
    )
    imported_record_ids = []
    if import_context:
        target = next((
            item for item in import_context["vehicles"]
            if item["id"] == vehicle.id
        ), None)
        if target is None:
            raise _dkss_common.NotFound()
        imported_record_ids = target["record_ids"]

    selected_scope = _dkss_common.request.args.get(
        "scope", "import" if import_context else "all"
    )
    if not import_context or selected_scope != "import":
        selected_scope = "all"

    selected_category = _dkss_common.request.args.get("category", "").strip()
    selected_status = _dkss_common.request.args.get("status", "").strip()
    start_date = _dkss_common.request.args.get("start_date", "").strip()
    end_date = _dkss_common.request.args.get("end_date", "").strip()

    maintenance_categories = [
        row[0] for row in query.with_entities(
            _dkss_models.VehicleMaintenanceRecord.category
        ).filter(
            _dkss_models.VehicleMaintenanceRecord.category.isnot(None),
            _dkss_models.VehicleMaintenanceRecord.category != "",
        ).distinct().order_by(
            _dkss_models.VehicleMaintenanceRecord.category
        ).all()
    ]
    invoice_actual_ids = []
    maintenance_statuses = set()
    for actual_id, raw_status, invoice_json in query.with_entities(
        _dkss_models.VehicleMaintenanceRecord.id,
        _dkss_models.VehicleMaintenanceRecord.status,
        _dkss_models.VehicleMaintenanceRecord.invoice_details_json,
    ):
        fact = _dkss_models.VehicleMaintenanceRecord(invoice_details_json=invoice_json)
        if fact.is_invoice_actual:
            invoice_actual_ids.append(actual_id)
            maintenance_statuses.add("実施済み")
        elif raw_status:
            maintenance_statuses.add(raw_status)
    maintenance_statuses = sorted(maintenance_statuses)

    try:
        for date_value in (start_date, end_date):
            if date_value:
                parsed = _dkss_common.datetime.strptime(date_value, "%Y-%m-%d")
                if parsed.strftime("%Y-%m-%d") != date_value:
                    raise ValueError()
        if start_date and end_date and start_date > end_date:
            raise ValueError()
    except ValueError:
        _dkss_common.flash("期間を正しく指定してください。", "error")
        return _dkss_common.redirect(_dkss_common.url_for(
            "vehicle_karte_maintenance",
            vehicle_record_id=vehicle.id,
            import_batch=import_batch,
            scope=selected_scope,
        ))

    maintenance_date = _dkss_common.db.func.coalesce(
        _dkss_common.db.func.nullif(_dkss_models.VehicleMaintenanceRecord.entry_date, ""),
        _dkss_common.db.func.nullif(_dkss_models.VehicleMaintenanceRecord.completion_date, ""),
        "",
    )

    if selected_scope == "import":
        query = query.filter(
            _dkss_models.VehicleMaintenanceRecord.id.in_(imported_record_ids)
        )
    if selected_category:
        query = query.filter_by(category=selected_category)
    if selected_status == "実施済み":
        query = query.filter(_dkss_models.VehicleMaintenanceRecord.id.in_(invoice_actual_ids))
    elif selected_status:
        query = query.filter_by(status=selected_status).filter(
            ~_dkss_models.VehicleMaintenanceRecord.id.in_(invoice_actual_ids)
        )
    if start_date:
        query = query.filter(maintenance_date >= start_date)
    if end_date:
        query = query.filter(maintenance_date <= end_date)

    per_page = _dkss_common.request.args.get("per_page", 10, type=int)
    if per_page not in {10, 20, 50}:
        per_page = 10

    maintenance_page = query.order_by(
        maintenance_date.desc(),
        _dkss_models.VehicleMaintenanceRecord.id.desc(),
    ).paginate(
        page=max(1, _dkss_common.request.args.get("page", 1, type=int)),
        per_page=per_page,
        error_out=False,
    )

    maintenance_record = None
    invoice_details = {}
    invoice_inspection = None
    maintenance_lines = []
    source_url = None
    source_page = 1

    if record_id is not None:
        maintenance_record = query.filter_by(id=record_id).first_or_404()
    elif maintenance_page.items:
        maintenance_record = maintenance_page.items[0]

    if maintenance_record is not None:
        invoice_details = _dkss_serialization.safe_json_dict(
            maintenance_record.invoice_details_json
        )
        inspection_id = invoice_details.get("periodic_inspection_id")
        if type(inspection_id) is int:
            invoice_inspection = _dkss_models.VehiclePeriodicInspectionRecord.query.filter_by(
                id=inspection_id, company_code=vehicle.company_code,
                vehicle_record_id=vehicle.id,
            ).first()
        maintenance_lines = _dkss_serialization.safe_json_dict_list(
            maintenance_record.line_items_json
        )
        source = invoice_details.get("source")
        if isinstance(source, dict):
            draft_id = source.get("draft_id")
            if isinstance(draft_id, str) and draft_id.strip():
                source_url = _dkss_common.url_for(
                    "vehicle_karte_document_source",
                    vehicle_record_id=vehicle.id,
                    draft_id=draft_id,
                )
            pages = source.get("pages")
            if isinstance(pages, list):
                valid_pages = [
                    page for page in pages
                    if isinstance(page, int)
                    and not isinstance(page, bool)
                    and page > 0
                ]
                if valid_pages:
                    source_page = min(valid_pages)

    return _dkss_common.render_template(
        "vehicle_karte_maintenance.html",
        vehicle=vehicle,
        vehicle_number=number,
        maintenance_page=maintenance_page,
        import_context=import_context,
        imported_record_ids=imported_record_ids,
        selected_scope=selected_scope,
        maintenance_categories=maintenance_categories,
        maintenance_statuses=maintenance_statuses,
        selected_category=selected_category,
        selected_status=selected_status,
        start_date=start_date,
        end_date=end_date,
        maintenance_record=maintenance_record,
        periodic_issues=_dkss_runtime.app.extensions["dkss"]['periodic_followups'].for_maintenance(vehicle.company_code, maintenance_record.id if maintenance_record else None),
        maintenance_parts=(
            _dkss_models.VehiclePartReplacement.query.filter_by(
                company_code=vehicle.company_code,
                vehicle_record_id=vehicle.id,
                maintenance_record_id=maintenance_record.id,
            ).order_by(
                _dkss_models.VehiclePartReplacement.replacement_date.desc(),
                _dkss_models.VehiclePartReplacement.id.desc(),
            ).all()
            if maintenance_record is not None else []
        ),
        format_part_number=format_vehicle_maintenance_number,
        maintenance_events=(
            get_vehicle_maintenance_record_events(maintenance_record)
            if maintenance_record is not None else []
        ),
        invoice_details=invoice_details,
        invoice_inspection=invoice_inspection,
        maintenance_lines=maintenance_lines,
        maintenance_number=format_vehicle_maintenance_number,
        source_url=source_url,
        source_page=source_page,
        open_defects=_dkss_checklists.get_vehicle_open_inspection_defects(
            vehicle.company_code,
            vehicle.id,
        ),
    )



def vehicle_karte_history(vehicle_record_id):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=_dkss_common.session.get("company_code")
    ).first_or_404()

    number = _dkss_vehicle_readers.vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or ""
    })

    page = max(1, _dkss_common.request.args.get("page", 1, type=int))
    selected_event_type = _dkss_common.request.args.get("event_type", "").strip()
    selected_start_date = _dkss_common.request.args.get("start_date", "").strip()
    selected_end_date = _dkss_common.request.args.get("end_date", "").strip()

    history_date_errors = []

    for field_id, label, value in [
        ("history_start_date", "開始日", selected_start_date),
        ("history_end_date", "終了日", selected_end_date),
    ]:
        if not value:
            continue

        try:
            parsed_date = _dkss_common.datetime.strptime(value, "%Y-%m-%d")
            if parsed_date.strftime("%Y-%m-%d") != value:
                raise ValueError
        except ValueError:
            history_date_errors.append((
                field_id,
                label + "を正しい日付で入力してください。",
            ))

    if (
        not history_date_errors
        and selected_start_date
        and selected_end_date
        and selected_start_date > selected_end_date
    ):
        history_date_errors.append((
            "history_end_date",
            "終了日は開始日以降の日付を選択してください。",
        ))

    for field_id, message in history_date_errors:
        _dkss_common.flash(message, "error:" + field_id)

    from types import SimpleNamespace

    history_entries = get_vehicle_karte_history_entries(
        vehicle.company_code,
        vehicle.id
    )

    history_event_types = sorted({
        entry["kind"]
        for entry in history_entries
        if entry["kind"]
    })

    history_statuses = sorted({
        entry["status"]
        for entry in history_entries
        if entry["status"]
    })

    selected_status = _dkss_common.request.args.get("status", "").strip()

    if history_date_errors:
        history_entries = []
    else:
        history_entries = [
            entry
            for entry in history_entries
            if (
                (
                    not selected_event_type
                    or entry["kind"] == selected_event_type
                )
                and (
                    not selected_status
                    or entry["status"] == selected_status
                )
                and (
                    not selected_start_date
                    or entry["date"] >= selected_start_date
                )
                and (
                    not selected_end_date
                    or (
                        entry["date"]
                        and entry["date"] <= selected_end_date
                    )
                )
            )
        ]

    per_page = _dkss_common.request.args.get("per_page", 10, type=int)
    if per_page not in {10, 20, 50}:
        per_page = 10

    total = len(history_entries)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    offset = (page - 1) * per_page

    history_page = SimpleNamespace(
        items=history_entries[offset:offset + per_page],
        total=total,
        page=page,
        pages=pages,
        per_page=per_page,
        first=offset + 1 if total else 0,
        last=min(offset + per_page, total),
        has_prev=page > 1,
        has_next=page < pages,
        prev_num=page - 1 if page > 1 else None,
        next_num=page + 1 if page < pages else None
    )

    return _dkss_common.render_template(
        "vehicle_karte_history.html",
        vehicle=vehicle,
        vehicle_number=number,
        history_page=history_page,
        history_links={},
        history_details={},
        history_event_types=history_event_types,
        history_statuses=history_statuses,
        selected_event_type=selected_event_type,
        selected_status=selected_status,
        selected_start_date=selected_start_date,
        selected_end_date=selected_end_date,
        open_defects=_dkss_checklists.get_vehicle_open_inspection_defects(
            vehicle.company_code,
            vehicle.id
        )
    ), (400 if history_date_errors else 200)



def get_vehicle_karte_usage_vehicles():
    company_code = _dkss_common.session.get("company_code")
    username = _dkss_common.session.get("username")

    if not company_code or not username:
        return []

    current_driver = _dkss_models.Driver.query.filter_by(
        company_code=company_code,
        employee_id=username
    ).first()

    if current_driver is None:
        return []

    vehicle_ids = []
    for value in _dkss_serialization.safe_json_str_list(
        current_driver.vehicles_json
    ):
        if not value.isdigit() or len(value) > 18:
            continue

        vehicle_id = int(value)
        if vehicle_id > 0 and vehicle_id not in vehicle_ids:
            vehicle_ids.append(vehicle_id)

    if not vehicle_ids:
        return []

    records = _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.company_code == company_code,
        _dkss_models.Vehicle.deleted == False,
        _dkss_models.Vehicle.id.in_(vehicle_ids)
    ).all()

    record_map = {
        record.id: record
        for record in records
    }

    return [
        record_map[vehicle_id]
        for vehicle_id in vehicle_ids
        if vehicle_id in record_map
    ]



def inject_vehicle_karte_choices():
    from .vehicle_couplings import coupling_context
    if _dkss_common.request.endpoint not in {
        "vehicle_karte_list",
        "vehicle_karte",
        "vehicle_karte_history",
        "vehicle_karte_inspections",
        "vehicle_periodic_followup",
        "vehicle_karte_documents",
        "vehicle_karte_maintenance",
        "vehicle_karte_maintenance_form",
        "vehicle_karte_parts",
        "vehicle_karte_costs",
        "vehicle_karte_analysis",
    }:
        return {}

    company_code = _dkss_common.session.get("company_code")
    if not company_code:
        return {"karte_vehicle_choices": []}

    vehicles = _dkss_models.Vehicle.query.filter_by(
        company_code=company_code
    ).order_by(_dkss_models.Vehicle.id.asc()).all()

    driver_names_by_vehicle = {
        str(record.id): []
        for record in vehicles
    }

    drivers = _dkss_models.Driver.query.filter_by(
        company_code=company_code
    ).order_by(_dkss_models.Driver.id.asc()).all()

    for driver in drivers:
        driver_name = (driver.name or "").strip()
        if not driver_name:
            continue

        for vehicle_id in _dkss_serialization.safe_json_str_list(
            driver.vehicles_json
        ):
            names = driver_names_by_vehicle.get(
                vehicle_id
            )
            if names is not None and driver_name not in names:
                names.append(driver_name)

    choices = []
    for record in vehicles:
        number = _dkss_vehicle_readers.vehicle_number({
            "plate_area": record.plate_area or "",
            "plate_class": record.plate_class or "",
            "plate_kana": record.plate_kana or "",
            "plate_number": record.plate_number or "",
        })

        choices.append({
            "id": record.id,
            "number": number,
            "chassis_number": record.chassis_number or "",
            "type": record.type or record.body_type or "",
            "driver_names": "、".join(
                driver_names_by_vehicle.get(
                    str(record.id),
                    []
                )
            ),
        })

    operation_summary = {
        "current_mileage": None,
        "mileage_date": None,
    }

    vehicle_record_id = (
        _dkss_common.request.view_args or {}
    ).get("vehicle_record_id")

    if any(
        record.id == vehicle_record_id
        for record in vehicles
    ):
        operation_summary = _dkss_vehicle_operations.get_vehicle_operation_summary(
            company_code,
            vehicle_record_id
        )

    maintenance_summary = {
        "last_mileage": None,
        "last_date": None,
        "distance_since": None,
        "total_cost": None,
        "annual_costs": [],
    }

    if any(
        record.id == vehicle_record_id
        for record in vehicles
    ):
        maintenance_records = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
            company_code=company_code,
            vehicle_record_id=vehicle_record_id,
        ).all()

        maintenance_summary.update(
            _dkss_vehicle_costs.get_vehicle_overview_cost_summary(maintenance_records)
        )

        maintenance_records, _, _ = _dkss_analysis.filter_vehicle_maintenance_factual_history(maintenance_records)
        completed_records = [
            record
            for record in maintenance_records
            if (
                (record.completion_date or "").strip()
                or record.status == "完了"
            )
            and (
                (record.completion_date or "").strip()
                or (record.entry_date or "").strip()
            )
        ]
        if completed_records:
            latest_record = max(
                completed_records,
                key=lambda record: (
                    (record.completion_date or "").strip()
                    or (record.entry_date or "").strip(),
                    record.id,
                ),
            )
            maintenance_summary["last_mileage"] = latest_record.mileage
            maintenance_summary["last_date"] = (
                latest_record.completion_date
                or latest_record.entry_date
            )

            current_mileage = operation_summary.get("current_mileage")
            try:
                measured_on = _dkss_common.datetime.strptime(
                    str(operation_summary.get("mileage_date") or "")[:10].replace("/", "-"),
                    "%Y-%m-%d",
                ).date()
                maintained_on = _dkss_common.datetime.strptime(
                    str(maintenance_summary.get("last_date") or "")[:10].replace("/", "-"),
                    "%Y-%m-%d",
                ).date()
            except ValueError:
                measured_on = maintained_on = None

            if (
                operation_summary.get(
                    "mileage_reference", {}
                ).get("distance_usable") is True
                and current_mileage is not None
                and latest_record.mileage is not None
                and measured_on is not None
                and maintained_on is not None
                and measured_on >= maintained_on
            ):
                difference = (
                    _dkss_common.Decimal(str(current_mileage))
                    - _dkss_common.Decimal(str(latest_record.mileage))
                )
                if difference >= 0:
                    maintenance_summary["distance_since"] = difference

    return {
        "karte_vehicle_choices": choices,
        "karte_coupling": coupling_context(
            next((record for record in vehicles if record.id == vehicle_record_id), None), vehicles
        ),
        "karte_usage_vehicles": get_vehicle_karte_usage_vehicles(),
        "karte_operation_summary": operation_summary,
        "karte_maintenance_summary": maintenance_summary,
        "karte_execution_summary": (
            _dkss_runtime.app.extensions["dkss"]['inspection_plans'].latest(company_code, vehicle_record_id)
            if any(record.id == vehicle_record_id for record in vehicles) else {}
        ),
        "karte_issue_counts": {
            "daily": len(_dkss_checklists.get_vehicle_open_inspection_defects(company_code, vehicle_record_id)),
            "periodic": _dkss_runtime.app.extensions["dkss"]['periodic_followups'].summary(company_code, vehicle_record_id)["open_count"],
        } if any(record.id == vehicle_record_id for record in vehicles) else {},
        "karte_plan_summary": (
            _dkss_runtime.app.extensions["dkss"]['inspection_plans'].summary(company_code, vehicle_record_id)
            if any(record.id == vehicle_record_id for record in vehicles) else {}
        ),
        "karte_periodic_summary": (
            _dkss_vehicle_costs.get_vehicle_periodic_inspection_summary(company_code, vehicle_record_id)
            if any(record.id == vehicle_record_id for record in vehicles) else {}
        ),
        "karte_recent_maintenance": (
            sorted(
                maintenance_records,
                key=lambda record: (
                    (record.entry_date or "").strip()
                    or (record.completion_date or "").strip(),
                    record.id,
                ),
                reverse=True,
            )[:5]
            if _dkss_common.request.endpoint == "vehicle_karte"
            and any(
                record.id == vehicle_record_id
                for record in vehicles
            )
            else []
        ),
    }



def vehicle_karte_list():
    selected_value = _dkss_common.request.args.get(
        "vehicle_record_id",
        ""
    ).strip()

    if selected_value:
        selected_id = _dkss_common.request.args.get(
            "vehicle_record_id",
            type=int
        )

        if (
            selected_id is None
            or selected_id <= 0
            or selected_id > 9223372036854775807
        ):
            _dkss_common.flash(
                "表示する車両を選択し直してください。",
                "error:karte_vehicle_search"
            )
            return _dkss_common.render_template(
                "vehicle_karte.html",
                vehicle=None
            ), 400

        selected_vehicle = _dkss_models.Vehicle.query.filter_by(
            id=selected_id,
            company_code=_dkss_common.session.get("company_code")
        ).first()

        if selected_vehicle is None:
            _dkss_common.flash(
                "選択した車両を表示できません。車両を選択し直してください。",
                "error:karte_vehicle_search"
            )
            return _dkss_common.render_template(
                "vehicle_karte.html",
                vehicle=None
            ), 404

        return _dkss_common.redirect(_dkss_common.url_for(
            "vehicle_karte",
            vehicle_record_id=selected_vehicle.id
        ))

    usage_vehicles = get_vehicle_karte_usage_vehicles()

    if usage_vehicles:
        current_user = _dkss_models.User.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            username=_dkss_common.session.get("username")
        ).first()

        user_settings = _dkss_serialization.safe_json_dict(
            current_user.dashboard_settings_json
        ) if current_user is not None else {}

        last_vehicle_id = str(user_settings.get(
            "vehicle_karte_last_vehicle_id",
            ""
        ))

        default_vehicle = next(
            (
                record
                for record in usage_vehicles
                if str(record.id) == last_vehicle_id
            ),
            usage_vehicles[0]
        )

        return _dkss_common.redirect(_dkss_common.url_for(
            "vehicle_karte",
            vehicle_record_id=default_vehicle.id
        ))

    return _dkss_common.render_template(
        "vehicle_karte.html",
        vehicle=None
    )
