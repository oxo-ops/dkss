"""Vehicle Pending responsibilities; routes are registered by the application factory."""
from .vehicle_capacity import reserved_vehicle_count
from . import operation_csv_owner as _csv_owner
from . import driving_pending_identity as _driving_recovery
from . import access as _dkss_access, checklists as _dkss_checklists, common as _dkss_common, http as _dkss_http, maintenance as _dkss_maintenance, master_readers as _dkss_master_readers, models as _dkss_models, runtime as _dkss_runtime, serialization as _dkss_serialization, vehicle_imports as _dkss_vehicle_imports, vehicle_karte as _dkss_vehicle_karte, vehicle_operations as _dkss_vehicle_operations, vehicle_readers as _dkss_vehicle_readers


def find_vehicle_pending_cross_source_group(company_code, source_kind, identity):
    """Only reuse one unambiguous full-plate group across CSV/document sources."""
    plate = get_vehicle_import_pending_plate(identity)
    if plate is None:
        return None
    matches = [
        group for group in _dkss_models.VehicleImportPending.query.filter_by(
            company_code=company_code, status="pending"
        ).with_for_update().all()
        if get_vehicle_import_pending_plate(_dkss_serialization.safe_json_dict(group.identity_json)) == plate
    ]
    if len(matches) != 1:
        return None
    group = matches[0]
    existing = _dkss_serialization.safe_json_dict(group.identity_json)
    unknown = {"", "不明", "記載なし", "未設定", "なし", "unknown", "none", "n/a"}
    for field in ("chassis_number", "source_vehicle_code"):
        left = _dkss_common.normalize_vehicle_operation_plate(existing.get(field))
        right = _dkss_common.normalize_vehicle_operation_plate(identity.get(field))
        if left not in unknown and right not in unknown and left != right:
            return None
    kinds = {
        row.source_kind for row in _dkss_models.VehicleImportPendingRecord.query.filter_by(
            company_code=company_code, pending_id=group.id, status="pending"
        ).all()
    }
    has_other_source = (
        bool(kinds - {"operation"}) if source_kind == "operation"
        else "operation" in kinds
    )
    if not has_other_source:
        return None
    # Preserve the identifiers supplied by each source for subsequent conflicts.
    for field in ("chassis_number", "source_vehicle_code"):
        if (
            _dkss_common.normalize_vehicle_operation_plate(existing.get(field)) in unknown
            and _dkss_common.normalize_vehicle_operation_plate(identity.get(field)) not in unknown
        ):
            existing[field] = identity[field]
    group.identity_json = _dkss_common.json.dumps(existing, ensure_ascii=False)
    return group



def save_vehicle_import_pending_record(
    *, company_code, username, source_kind, source_draft_id,
    source_record_index, group_identity, identity,
    record_identity, payload, record_date=None
):
    document_kinds = {"driving_report", "inspection", "maintenance"}
    if source_kind not in document_kinds | {"operation"}:
        raise _dkss_common.UploadValidationError("取込データの種類が不正です。")
    if not company_code or not username:
        raise _dkss_common.UploadValidationError("会社・利用者を確認してください。")
    if (
        isinstance(source_record_index, bool)
        or not isinstance(source_record_index, int)
        or source_record_index < 0
        or not isinstance(identity, dict)
        or not isinstance(payload, dict)
        or not group_identity
        or not record_identity
    ):
        raise _dkss_common.UploadValidationError("登録待ちデータの形式が不正です。")

    draft_model = (
        _dkss_models.VehicleOperationImportDraft
        if source_kind == "operation"
        else _dkss_models.VehicleDocumentImportDraft
    )
    draft = draft_model.query.filter_by(
        id=source_draft_id, company_code=company_code
    ).first()
    if draft is None or (
        source_kind != "operation"
        and draft.document_type != source_kind
    ):
        raise _dkss_common.UploadValidationError("同じ会社の取込原本を確認できません。")

    def serialize(value):
        return _dkss_common.json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str
        )

    # Serialize creation as well as reuse, including when no group exists yet.
    if _dkss_models.Company.query.filter_by(company_code=company_code).with_for_update().first() is None:
        raise _dkss_common.UploadValidationError("会社情報を確認できません。")

    record_key = _dkss_common.hashlib.sha256(
        serialize(record_identity).encode("utf-8")
    ).hexdigest()
    payload_json = serialize(payload)
    existing = _dkss_models.VehicleImportPendingRecord.query.filter_by(
        company_code=company_code,
        source_kind=source_kind,
        record_key=record_key
    ).first()
    if existing is not None:
        if serialize(_dkss_serialization.safe_json_dict(existing.payload_json)) != payload_json:
            raise _dkss_common.UploadValidationError(
                "同じ識別子で内容が異なるデータがあります。確認してください。"
            )
        return existing, False

    match_key = _dkss_common.hashlib.sha256(
        serialize(group_identity).encode("utf-8")
    ).hexdigest()
    pending = _dkss_models.VehicleImportPending.query.filter_by(
        company_code=company_code, match_key=match_key, status="pending"
    ).first()
    if pending is None:
        previous = _dkss_models.VehicleImportPending.query.filter_by(
            company_code=company_code, match_key=match_key
        ).first()
        if previous is not None:
            raise _dkss_common.UploadValidationError(
                "対応済みの車両があります。登録先を再確認してください。"
            )
        pending = find_vehicle_pending_cross_source_group(
            company_code, source_kind, identity
        )
        if pending is None:
            pending = _dkss_models.VehicleImportPending(
                id=str(_dkss_common.uuid4()), company_code=company_code,
                match_key=match_key, identity_json=serialize(identity),
                created_by_username=username
            )
            _dkss_common.db.session.add(pending)
            _dkss_common.db.session.flush()

    record = _dkss_models.VehicleImportPendingRecord(
        id=str(_dkss_common.uuid4()), company_code=company_code,
        pending_id=pending.id, source_kind=source_kind,
        record_key=record_key,
        operation_draft_id=draft.id if source_kind == "operation" else None,
        document_draft_id=draft.id if source_kind != "operation" else None,
        source_record_index=source_record_index,
        record_date=record_date,
        payload_json=payload_json,
        created_by_username=username
    )
    _dkss_common.db.session.add(record)
    _dkss_common.db.session.flush()
    return record, True



def get_vehicle_pending_identity_match(identity, vehicles, plate_candidates):
    plate = _dkss_common.normalize_vehicle_operation_plate(
        identity.get("source_vehicle_number")
    )
    candidate_ids = plate_candidates.get(plate, []) if plate else []
    source_chassis = _dkss_common.normalize_vehicle_operation_plate(
        identity.get("chassis_number")
    )
    pending_identity_conflict = False
    pending_match_reason = "取込元のナンバーと一致する登録済み車両です。"

    if source_chassis and source_chassis not in {
        "不明", "記載なし", "未設定", "なし", "unknown", "none", "n/a"
    }:
        chassis_ids = {
            vehicle.id for vehicle in vehicles
            if _dkss_common.normalize_vehicle_operation_plate(
                vehicle.chassis_number
            ) == source_chassis
        }
        if chassis_ids:
            if candidate_ids and not chassis_ids.intersection(candidate_ids):
                candidate_ids = []
                pending_identity_conflict = True
            else:
                candidate_ids = sorted(
                    chassis_ids.intersection(candidate_ids)
                    if candidate_ids else chassis_ids
                )
                pending_match_reason = "取込元の車台番号と一致する登録済み車両です。"
        elif candidate_ids:
            compatible_ids = {
                vehicle.id for vehicle in vehicles
                if not _dkss_common.normalize_vehicle_operation_plate(
                    vehicle.chassis_number
                )
            }
            filtered_ids = [
                item for item in candidate_ids
                if item in compatible_ids
            ]
            pending_identity_conflict = (
                len(filtered_ids) != len(candidate_ids)
            )
            candidate_ids = [] if pending_identity_conflict else filtered_ids

    return candidate_ids, pending_identity_conflict, pending_match_reason



def get_vehicle_pending_workspace(company_code, selected_id=None):
    """Read-only queue, scoped to the current company; search spans every pending group."""
    keyword = _dkss_common.request.args.get("q", "").strip()[:100]
    normalized = _dkss_common.normalize_vehicle_operation_plate(keyword)
    groups = vehicle_import_pending_query(company_code).order_by(
        _dkss_models.VehicleImportPending.created_at.asc(), _dkss_models.VehicleImportPending.id.asc()
    ).all()
    summaries = {}
    for pending_id, kind, count in _dkss_common.db.session.query(
        _dkss_models.VehicleImportPendingRecord.pending_id,
        _dkss_models.VehicleImportPendingRecord.source_kind,
        _dkss_common.db.func.count(_dkss_models.VehicleImportPendingRecord.id)
    ).join(
        _dkss_models.VehicleImportPending,
        _dkss_models.VehicleImportPending.id == _dkss_models.VehicleImportPendingRecord.pending_id
    ).filter(
        _dkss_models.VehicleImportPending.company_code == company_code,
        _dkss_models.VehicleImportPending.status == "pending",
        _dkss_models.VehicleImportPendingRecord.company_code == company_code,
        _dkss_models.VehicleImportPendingRecord.status == "pending"
    ).group_by(
        _dkss_models.VehicleImportPendingRecord.pending_id, _dkss_models.VehicleImportPendingRecord.source_kind
    ).all():
        summaries.setdefault(pending_id, []).append((kind, count))
    labels = {
        "operation": "運行実績", "driving_report": "運行日報",
        "inspection": "点検記録", "maintenance": "請求書・整備資料"
    }
    rows = []
    for group in groups:
        identity = _dkss_serialization.safe_json_dict(group.identity_json)
        plate = str(identity.get("source_vehicle_number") or "").strip()
        code = str(identity.get("source_vehicle_code") or "").strip()
        chassis = str(identity.get("chassis_number") or "").strip()
        if normalized and not any(
            normalized in _dkss_common.normalize_vehicle_operation_plate(value)
            for value in (plate, code, chassis)
        ):
            continue
        kinds = summaries.get(group.id, [])
        rows.append({
            "id": group.id, "identity": identity,
            "title": plate or ("車両コード " + code if code else "車両情報未確認"),
            "record_count": sum(count for _, count in kinds),
            "summary": " ／ ".join(
                labels.get(kind, "その他") + " " + str(count) + "件"
                for kind, count in sorted(kinds)
            ),
        })
    selected_index = next((i for i, row in enumerate(rows) if row["id"] == selected_id), None)
    pages = max(1, (len(rows) + 19) // 20)
    page = max(1, min(_dkss_common.request.args.get("page", 1, type=int), pages))
    if selected_index is not None:
        page = selected_index // 20 + 1
    visible = rows[(page - 1) * 20:page * 20]
    vehicles, plate_candidates = _dkss_vehicle_operations.get_vehicle_operation_plate_candidates(company_code)
    for row in visible:
        ids, conflict, _ = get_vehicle_pending_identity_match(
            row["identity"], vehicles, plate_candidates
        )
        if len(ids) == 1 and not conflict:
            row.update(label="候補あり", tone="match")
        elif conflict or ids:
            row.update(label="要確認", tone="check")
        elif get_vehicle_import_pending_plate(row["identity"]):
            row.update(label="新規候補", tone="new")
        else:
            row.update(label="情報不足", tone="missing")
    return {
        "keyword": keyword, "rows": visible, "total": len(groups),
        "filtered_count": len(rows), "page": page, "pages": pages,
        "position": selected_index + 1 if selected_index is not None else 0,
        "previous_id": rows[selected_index - 1]["id"] if selected_index is not None and selected_index > 0 else None,
        "next_id": rows[selected_index + 1]["id"] if selected_index is not None and selected_index + 1 < len(rows) else None,
        "first_id": visible[0]["id"] if visible else None,
    }



def vehicle_master():
    if _dkss_common.request.args.get("view", "") != "pending":
        return render_vehicle_list("vehicle_master.html")

    if not _dkss_access.require_master_admin():
        return "この操作は管理者のみ利用できます。", 403

    workspace = get_vehicle_pending_workspace(_dkss_common.session.get("company_code"))

    if workspace["first_id"]:
        return _dkss_common.redirect(_dkss_common.url_for(
            "vehicle_import_pending_review",
            pending_id=workspace["first_id"],
            q=workspace["keyword"]
        ))

    return _dkss_common.render_template(
        "vehicle_master.html",
        pending_workspace=workspace,
        pending_vehicle_count=workspace["total"],
    )



def vehicle_import_pending_review(pending_id):
    if not _dkss_access.require_master_admin():
        return "この操作は管理者のみ利用できます。", 403

    company_code = _dkss_common.session.get("company_code")
    pending = _dkss_models.VehicleImportPending.query.filter_by(
        id=pending_id, company_code=company_code
    ).first_or_404()
    if pending.status != "pending":
        _dkss_common.flash("この登録待ちは対応済みか、処理中です。", "info")
        return _dkss_common.redirect(_dkss_common.url_for("vehicle_master", view="pending"))

    if _dkss_common.request.method == "POST":
        action = _dkss_common.request.form.get("pending_action", "link")
        if action not in {"link", "create"}:
            return _dkss_http.return_form_errors([("操作を選び直してください。", "")])

        vehicle_id = _dkss_common.request.form.get("vehicle_record_id", type=int)
        if action == "link" and (
            vehicle_id is None or not 0 < vehicle_id <= 9223372036854775807
        ):
            return _dkss_http.return_form_errors([
                ("登録先の車両を選択してください。", "vehicle_record_id")
            ])
        try:
            if action == "create":
                vehicle = create_vehicle_from_pending_operations(
                    pending, company_code
                )
                vehicle_id = vehicle.id
            questions = get_vehicle_pending_invoice_questions(
                pending.id, vehicle_id, company_code
            )
            invoice_choices = {
                question["pending_record_id"]: _dkss_common.request.form.get(
                    "invoice_choice_" + question["pending_record_id"], ""
                )
                for question in questions
            }
            if questions and not all(invoice_choices.values()):
                _dkss_common.db.session.rollback()
                if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
                    return _dkss_common.jsonify({"ok": True})
                return _dkss_common.render_template(
                    "vehicle_master.html",
                    pending_detail={"id": pending.id},
                    pending_invoice_questions=questions,
                    pending_invoice_vehicle_id=vehicle_id,
                    pending_workspace=get_vehicle_pending_workspace(company_code, pending.id),
                    pending_vehicle_count=vehicle_import_pending_query(
                        company_code
                    ).count(),
                )
            result = apply_vehicle_import_pending_records(
                pending.id, vehicle_id, company_code, _dkss_common.session.get("username"),
                invoice_choices=invoice_choices
            )
            if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
                _dkss_common.db.session.rollback()
                return _dkss_common.jsonify({"ok": True})
            _dkss_common.db.session.commit()
        except _driving_recovery.RecoveryConflict as error:
            _dkss_common.db.session.rollback()
            return _driving_recovery.render_review(pending_id, error.item_id, error.description, 409)
        except _dkss_common.HTTPException:
            _dkss_common.db.session.rollback()
            raise
        except (_dkss_common.UploadValidationError, ValueError, _dkss_common.InvalidOperation) as error:
            _dkss_common.db.session.rollback()
            return _dkss_http.return_form_errors([(str(error), "")])
        except _dkss_common.IntegrityError:
            _dkss_common.db.session.rollback()
            return _dkss_http.return_form_errors([
                ("別の操作で更新されました。一覧から再確認してください。", "")
            ])
        except _dkss_common.SQLAlchemyError:
            _dkss_common.db.session.rollback()
            _dkss_runtime.app.logger.exception("登録待ち実績の紐付けに失敗しました。")
            return _dkss_http.return_form_errors([
                ("保存できませんでした。時間をおいて再度お試しください。", "")
            ], status_code=500)

        _dkss_common.flash(
            ("車両を登録しました。" if action == "create" else "")
            + f"取込済みデータ{result['linked_count']}件を紐付けました。原本もカルテから確認できます。"
            + (
                f"うち請求書{result['review_pending_count']}件は、費用・部品を確認待ちで保存しました。"
                if result.get("review_pending_count") else ""
            ),
            "success"
        )
        if _dkss_common.request.form.get("queue_continue") == "1":
            workspace = get_vehicle_pending_workspace(company_code)
            next_id = _dkss_common.request.form.get("queue_next", "")
            if next_id and not vehicle_import_pending_query(company_code).filter(
                _dkss_models.VehicleImportPending.id == next_id
            ).first():
                next_id = None
            next_id = next_id or workspace["first_id"]
            if next_id:
                return _dkss_common.redirect(_dkss_common.url_for(
                    "vehicle_import_pending_review", pending_id=next_id,
                    q=workspace["keyword"]
                ))
            return _dkss_common.redirect(_dkss_common.url_for(
                "vehicle_master", view="pending", q=workspace["keyword"]
            ))
        return _dkss_common.redirect(_dkss_common.url_for(
            "vehicle_karte", vehicle_record_id=vehicle_id
        ))

    vehicles, plate_candidates = _dkss_vehicle_operations.get_vehicle_operation_plate_candidates(
        company_code
    )
    identity = _dkss_serialization.safe_json_dict(pending.identity_json)
    plate = _dkss_common.normalize_vehicle_operation_plate(
        identity.get("source_vehicle_number")
    )
    candidate_ids = plate_candidates.get(plate, []) if plate else []
    source_chassis = _dkss_common.normalize_vehicle_operation_plate(
        identity.get("chassis_number")
    )
    pending_identity_conflict = False
    pending_match_reason = "取込元のナンバーと一致する登録済み車両です。"

    if source_chassis and source_chassis not in {
        "不明", "記載なし", "未設定", "なし", "unknown", "none", "n/a"
    }:
        chassis_ids = {
            vehicle.id for vehicle in vehicles
            if _dkss_common.normalize_vehicle_operation_plate(
                vehicle.chassis_number
            ) == source_chassis
        }
        if chassis_ids:
            if candidate_ids and not chassis_ids.intersection(candidate_ids):
                candidate_ids = []
                pending_identity_conflict = True
            else:
                candidate_ids = sorted(
                    chassis_ids.intersection(candidate_ids)
                    if candidate_ids else chassis_ids
                )
                pending_match_reason = "取込元の車台番号と一致する登録済み車両です。"
        elif candidate_ids:
            compatible_ids = {
                vehicle.id for vehicle in vehicles
                if not _dkss_common.normalize_vehicle_operation_plate(
                    vehicle.chassis_number
                )
            }
            filtered_ids = [
                item for item in candidate_ids
                if item in compatible_ids
            ]
            pending_identity_conflict = (
                len(filtered_ids) != len(candidate_ids)
            )
            candidate_ids = [] if pending_identity_conflict else filtered_ids

    choices = [{
        "id": vehicle.id,
        "number": _dkss_vehicle_readers.vehicle_number({
            "plate_area": vehicle.plate_area or "",
            "plate_class": vehicle.plate_class or "",
            "plate_kana": vehicle.plate_kana or "",
            "plate_number": vehicle.plate_number or "",
        }),
        "chassis_number": vehicle.chassis_number,
        "office": vehicle.office,
        "deleted": vehicle.deleted,
    } for vehicle in vehicles]

    suggested = next((item for item in choices if (
        len(candidate_ids) == 1 and item["id"] == candidate_ids[0]
    )), None)

    summary = _dkss_common.db.session.query(
        _dkss_common.db.func.count(_dkss_models.VehicleImportPendingRecord.id),
        _dkss_common.db.func.min(_dkss_models.VehicleImportPendingRecord.record_date),
        _dkss_common.db.func.max(_dkss_models.VehicleImportPendingRecord.record_date)
    ).filter_by(
        pending_id=pending.id, company_code=company_code, status="pending"
    ).one()

    source_drafts = _dkss_common.db.session.query(
        _dkss_models.VehicleOperationImportDraft.id,
        _dkss_models.VehicleOperationImportDraft.source_filename,
        _dkss_models.VehicleOperationImportDraft.created_at
    ).join(
        _dkss_models.VehicleImportPendingRecord,
        _dkss_models.VehicleImportPendingRecord.operation_draft_id == _dkss_models.VehicleOperationImportDraft.id
    ).filter(
        _dkss_models.VehicleOperationImportDraft.company_code == company_code,
        _dkss_models.VehicleImportPendingRecord.company_code == company_code,
        _dkss_models.VehicleImportPendingRecord.pending_id == pending.id,
        _dkss_models.VehicleImportPendingRecord.source_kind == "operation",
        _dkss_models.VehicleImportPendingRecord.status == "pending"
    ).distinct().order_by(
        _dkss_models.VehicleOperationImportDraft.created_at.desc(),
        _dkss_models.VehicleOperationImportDraft.id.asc()
    ).all()

    pending_sources = []
    for source in source_drafts:
        created_at = source.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=_dkss_common.ZoneInfo("UTC"))
        pending_sources.append({
            "id": source.id,
            "kind": "operation",
            "filename": source.source_filename,
            "created_at": created_at.astimezone(
                _dkss_common.ZoneInfo("Asia/Tokyo")
            ).strftime("%Y/%m/%d %H:%M"),
        })

    document_sources = _dkss_common.db.session.query(
        _dkss_models.VehicleDocumentImportDraft.id,
        _dkss_models.VehicleDocumentImportDraft.source_filename,
        _dkss_models.VehicleDocumentImportDraft.created_at
    ).join(
        _dkss_models.VehicleImportPendingRecord,
        _dkss_models.VehicleImportPendingRecord.document_draft_id == _dkss_models.VehicleDocumentImportDraft.id
    ).filter(
        _dkss_models.VehicleDocumentImportDraft.company_code == company_code,
        _dkss_models.VehicleImportPendingRecord.company_code == company_code,
        _dkss_models.VehicleImportPendingRecord.pending_id == pending.id,
        _dkss_models.VehicleImportPendingRecord.source_kind == _dkss_models.VehicleDocumentImportDraft.document_type,
        _dkss_models.VehicleImportPendingRecord.status == "pending"
    ).distinct().all()

    for source in document_sources:
        created_at = source.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=_dkss_common.ZoneInfo("UTC"))
        pending_sources.append({
            "id": source.id,
            "kind": "document",
            "filename": source.source_filename,
            "created_at": created_at.astimezone(
                _dkss_common.ZoneInfo("Asia/Tokyo")
            ).strftime("%Y/%m/%d %H:%M"),
        })
    pending_sources.sort(
        key=lambda source: source["created_at"],
        reverse=True
    )

    labels = {
        "operation": "運行実績",
        "driving_report": "運行日報",
        "inspection": "点検記録",
        "maintenance": "請求書・整備資料",
    }
    pending_record_counts = [{
        "label": labels.get(kind, "その他"),
        "count": count,
    } for kind, count in _dkss_common.db.session.query(
        _dkss_models.VehicleImportPendingRecord.source_kind,
        _dkss_common.db.func.count(_dkss_models.VehicleImportPendingRecord.id)
    ).filter_by(
        pending_id=pending.id,
        company_code=company_code,
        status="pending"
    ).group_by(
        _dkss_models.VehicleImportPendingRecord.source_kind
    ).order_by(
        _dkss_models.VehicleImportPendingRecord.source_kind
    ).all()]

    return _dkss_common.render_template(
        "vehicle_master.html",
        pending_record_counts=pending_record_counts,
        pending_sources=pending_sources,
        pending_workspace=get_vehicle_pending_workspace(company_code, pending.id),
        pending_identity_reviews=_driving_recovery.navigation(pending.id),
        pending_documents=[{
            "draft_id": draft.id,
            "filename": draft.source_filename,
            "record_index": record.source_record_index,
            "kind": record.source_kind,
            "record_date": record.record_date,
            "payload": _dkss_serialization.safe_json_dict(record.payload_json),
        } for record, draft in _dkss_common.db.session.query(
            _dkss_models.VehicleImportPendingRecord, _dkss_models.VehicleDocumentImportDraft
        ).join(
            _dkss_models.VehicleDocumentImportDraft,
            _dkss_models.VehicleDocumentImportDraft.id == _dkss_models.VehicleImportPendingRecord.document_draft_id
        ).filter(
            _dkss_models.VehicleImportPendingRecord.company_code == company_code,
            _dkss_models.VehicleImportPendingRecord.pending_id == pending.id,
            _dkss_models.VehicleImportPendingRecord.status == "pending",
            _dkss_models.VehicleDocumentImportDraft.company_code == company_code,
        ).order_by(
            _dkss_models.VehicleImportPendingRecord.record_date.desc(),
            _dkss_models.VehicleImportPendingRecord.id.asc()
        ).limit(10).all()],
        pending_detail={
            "id": pending.id,
            "identity": identity,
            "record_count": summary[0],
            "date_from": summary[1],
            "date_to": summary[2],
        },
        pending_suggested=suggested,
        pending_identity_conflict=pending_identity_conflict,
        pending_match_reason=pending_match_reason,
        pending_new_plate=(
            get_vehicle_import_pending_plate(identity)
            if not candidate_ids and not pending_identity_conflict else None
        ),
        pending_choices=choices,
        pending_choose=_dkss_common.request.args.get("choose") == "1",
        pending_vehicle_count=vehicle_import_pending_query(
            company_code
        ).count(),
    )



def vehicle_import_pending_operation_source(pending_id, draft_id):
    if not _dkss_access.require_master_admin():
        return "この操作は管理者のみ利用できます。", 403

    company_code = _dkss_common.session.get("company_code")
    _dkss_models.VehicleImportPending.query.filter_by(
        id=pending_id, company_code=company_code
    ).first_or_404()

    belongs_to_pending = _dkss_common.db.session.query(
        _dkss_models.VehicleImportPendingRecord.id
    ).filter(
        _dkss_models.VehicleImportPendingRecord.pending_id == pending_id,
        _dkss_models.VehicleImportPendingRecord.company_code == company_code,
        _dkss_models.VehicleImportPendingRecord.source_kind == "operation",
        _dkss_models.VehicleImportPendingRecord.operation_draft_id == draft_id
    ).exists()

    draft = _dkss_models.VehicleOperationImportDraft.query.filter(
        _dkss_models.VehicleOperationImportDraft.id == draft_id,
        _dkss_models.VehicleOperationImportDraft.company_code == company_code,
        belongs_to_pending
    ).first_or_404()

    _csv_owner.hold_private_source(draft)
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



def get_vehicle_import_pending_plate(identity):
    plate = _dkss_common.normalize_vehicle_operation_plate(
        identity.get("source_vehicle_number")
    ).upper()
    match = _dkss_common.re.fullmatch(
        r"([一-龥々ヶぁ-んァ-ヶ]{1,20})([0-9][0-9A-Z]{1,2})([ぁ-ゖ])([0-9]{1,4})",
        plate
    )
    if match is None or int(match.group(4)) == 0:
        return None
    return dict(zip(
        ("plate_area", "plate_class", "plate_kana", "plate_number"),
        match.groups()
    ))



def create_vehicle_from_pending_operations(pending, company_code):
    if pending.company_code != company_code or pending.status != "pending":
        raise _dkss_common.UploadValidationError("登録待ちの車両を再確認してください。")

    parts = get_vehicle_import_pending_plate(
        _dkss_serialization.safe_json_dict(pending.identity_json)
    )
    if parts is None:
        raise _dkss_common.UploadValidationError(
            "新規登録に必要なナンバーを確認できません。資料を追加して確認してください。"
        )

    company = _dkss_models.Company.query.filter_by(
        company_code=company_code
    ).with_for_update().first()
    if company is None:
        raise _dkss_common.UploadValidationError("会社情報を確認できません。")

    active_count = reserved_vehicle_count(company_code)
    if active_count >= (company.vehicle_limit or 0):
        raise _dkss_common.UploadValidationError("登録可能台数の上限に達しています。")

    vehicles, plate_candidates = _dkss_vehicle_operations.get_vehicle_operation_plate_candidates(
        company_code
    )
    source_chassis = str(
        _dkss_serialization.safe_json_dict(pending.identity_json).get("chassis_number") or ""
    ).strip()
    normalized_chassis = _dkss_common.normalize_vehicle_operation_plate(source_chassis)

    if not normalized_chassis or normalized_chassis in {
        "不明", "記載なし", "未設定", "なし", "unknown", "none", "n/a"
    }:
        source_chassis = ""
        normalized_chassis = ""

    if len(source_chassis) > 100:
        raise _dkss_common.UploadValidationError("原本の車台番号を確認してください。")

    if normalized_chassis and any(
        _dkss_common.normalize_vehicle_operation_plate(
            vehicle.chassis_number
        ) == normalized_chassis
        for vehicle in vehicles
    ):
        raise _dkss_common.UploadValidationError(
            "同じ車台番号の車両が登録済みです。登録済み車両から選択してください。"
        )

    plate = _dkss_common.normalize_vehicle_operation_plate(_dkss_vehicle_readers.vehicle_number(parts))
    if plate_candidates.get(plate):
        raise _dkss_common.UploadValidationError(
            "同じナンバーの車両が登録済みです。登録済み車両から選択してください。"
        )

    vehicle = _dkss_models.Vehicle(
        company_code=company_code,
        chassis_number=source_chassis or None,
        deleted=False,
        **parts
    )
    _dkss_common.db.session.add(vehicle)
    _dkss_common.db.session.flush()
    return vehicle



def vehicle_import_pending_document_source(pending_id, draft_id):
    if not _dkss_access.require_master_admin():
        raise _dkss_common.NotFound()

    company_code = _dkss_common.session.get("company_code")
    _dkss_models.VehicleImportPending.query.filter_by(
        id=pending_id, company_code=company_code
    ).first_or_404()

    draft = _dkss_models.VehicleDocumentImportDraft.query.join(
        _dkss_models.VehicleImportPendingRecord,
        _dkss_models.VehicleImportPendingRecord.document_draft_id == _dkss_models.VehicleDocumentImportDraft.id
    ).filter(
        _dkss_models.VehicleDocumentImportDraft.id == draft_id,
        _dkss_models.VehicleDocumentImportDraft.company_code == company_code,
        _dkss_models.VehicleDocumentImportDraft.status == 'completed',
        _dkss_models.VehicleImportPendingRecord.company_code == company_code,
        _dkss_models.VehicleImportPendingRecord.pending_id == pending_id,
        _dkss_models.VehicleImportPendingRecord.source_kind == _dkss_models.VehicleDocumentImportDraft.document_type
    ).first_or_404()

    mimetype = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(_dkss_common.os.path.splitext(draft.source_filename)[1].lower())
    if mimetype is None:
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



def get_vehicle_pending_maintenance_candidates(company_code, vehicle_id, payload):
    """作業日が一致する候補を返す。確定・更新・費用の統合は行わない。"""
    if (
        not company_code or isinstance(vehicle_id, bool)
        or not isinstance(vehicle_id, int) or not isinstance(payload, dict)
    ):
        raise _dkss_common.UploadValidationError("会社・車両・請求書の情報を確認してください。")
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_id, company_code=company_code
    ).first()
    if vehicle is None:
        raise _dkss_common.UploadValidationError("登録先の車両を確認できません。")

    dates = set()
    for field in ("record_date", "completion_date"):
        value = payload.get(field)
        if not value:
            continue
        if not isinstance(value, str):
            raise _dkss_common.UploadValidationError("整備資料の作業日を確認してください。")
        try:
            parsed = _dkss_common.datetime.strptime(value, "%Y-%m-%d")
            if parsed.strftime("%Y-%m-%d") != value:
                raise ValueError
        except ValueError:
            raise _dkss_common.UploadValidationError("整備資料の作業日を確認してください。")
        dates.add(value)
    if not dates:
        return []

    candidates = []
    models = (
        ("maintenance", _dkss_models.VehicleMaintenanceRecord, "entry_date"),
        ("inspection", _dkss_models.VehiclePeriodicInspectionRecord, "inspection_date"),
    )
    for kind, model, date_field in models:
        rows = model.query.filter(
            model.company_code == company_code,
            model.vehicle_record_id == vehicle_id,
            _dkss_common.or_(getattr(model, date_field).in_(dates),
                model.completion_date.in_(dates)),
        ).order_by(model.id).all()
        for record in rows:
            matched_dates = sorted(dates.intersection({
                getattr(record, date_field), record.completion_date
            }))
            candidates.append({
                "kind": kind,
                "record_id": record.id,
                "record_date": getattr(record, date_field) or "",
                "completion_date": record.completion_date or "",
                "content": record.content or "",
                "maintenance_company": (
                    record.maintenance_company if kind == "maintenance"
                    else record.inspection_company
                ) or "",
                "matched_dates": matched_dates,
                "has_invoice": kind == "maintenance" and bool(
                    record.invoice_number or record.invoice_date
                    or _dkss_serialization.safe_json_dict(record.invoice_details_json).get("source")
                    or any(getattr(record, field) is not None for field in (
                        "labor_cost", "parts_cost", "other_cost",
                        "tax_amount", "total_cost"
                    ))
                ),
            })
    return candidates



def get_vehicle_pending_invoice_questions(pending_id, vehicle_id, company_code):
    """未反映の請求書ごとに、原本と整備候補を確認画面へ渡す。"""
    pending = _dkss_models.VehicleImportPending.query.filter_by(
        id=pending_id, company_code=company_code, status="pending"
    ).first()
    if pending is None:
        raise _dkss_common.UploadValidationError("登録待ちの情報を再確認してください。")

    questions = []
    items = _dkss_models.VehicleImportPendingRecord.query.filter_by(
        pending_id=pending.id, company_code=company_code,
        source_kind="maintenance", status="pending"
    ).order_by(_dkss_models.VehicleImportPendingRecord.id).all()

    for item in items:
        draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
            id=item.document_draft_id, company_code=company_code,
            document_type="maintenance", status="completed"
        ).first()
        if draft is None or _dkss_common.hashlib.sha256(
            draft.source_file
        ).hexdigest() != draft.source_sha256:
            raise _dkss_common.UploadValidationError("保存済みの原本を確認できません。")

        payload = _dkss_serialization.safe_json_dict(item.payload_json)
        records = _dkss_serialization.safe_json_dict(draft.preview_json).get("records")
        index = item.source_record_index
        if (
            not isinstance(records, list)
            or isinstance(index, bool) or not isinstance(index, int)
            or not 0 <= index < len(records)
            or records[index] != payload
            or payload.get("vehicle_record_id") is not None
        ):
            raise _dkss_common.UploadValidationError("保存済み明細の一致を確認できません。")

        candidates = get_vehicle_pending_maintenance_candidates(
            company_code, vehicle_id, payload
        )
        if candidates:
            questions.append({
                "pending_record_id": item.id,
                "draft_id": draft.id,
                "filename": draft.source_filename,
                "record_index": index,
                "record_date": payload.get("record_date") or "",
                "completion_date": payload.get("completion_date") or "",
                "invoice_date": payload.get("invoice_date") or "",
                "invoice_number": payload.get("invoice_number") or "",
                "content": payload.get("content") or "",
                "total_cost": payload.get("total_cost"),
                "candidates": candidates,
            })
    return questions



def save_vehicle_maintenance_document(
    pending_record_id, vehicle_id, target_kind, target_id, company_code, username
):
    """原本と確認待ち情報を保存する。既存費用・部品の更新や確定はしない。"""
    if (
        not company_code or not username
        or company_code != _dkss_common.session.get("company_code")
        or username != _dkss_common.session.get("username")
        or type(vehicle_id) is not int or type(target_id) is not int
        or target_kind not in {"maintenance", "inspection"}
    ):
        raise _dkss_common.UploadValidationError("資料の登録先を再確認してください。")

    company = _dkss_models.Company.query.filter_by(
        company_code=company_code
    ).with_for_update().first()
    if company is None:
        raise _dkss_common.UploadValidationError("会社情報を確認できません。")

    item = _dkss_models.VehicleImportPendingRecord.query.filter_by(
        id=pending_record_id, company_code=company_code,
        source_kind="maintenance"
    ).first()
    if item is None:
        raise _dkss_common.UploadValidationError("保存済みの請求書明細を確認できません。")

    draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
        id=item.document_draft_id, company_code=company_code,
        document_type="maintenance", status="completed"
    ).first()
    if draft is None or _dkss_common.hashlib.sha256(
        draft.source_file
    ).hexdigest() != draft.source_sha256:
        raise _dkss_common.UploadValidationError("保存済みの原本を確認できません。")

    payload = _dkss_serialization.safe_json_dict(item.payload_json)
    records = _dkss_serialization.safe_json_dict(draft.preview_json).get("records")
    index = item.source_record_index
    if (
        not isinstance(records, list) or type(index) is not int
        or not 0 <= index < len(records) or records[index] != payload
        or payload.get("vehicle_record_id") is not None
    ):
        raise _dkss_common.UploadValidationError("保存済み明細の一致を確認できません。")

    target_model = (
        _dkss_models.VehicleMaintenanceRecord if target_kind == "maintenance"
        else _dkss_models.VehiclePeriodicInspectionRecord
    )
    target = target_model.query.filter_by(
        id=target_id, company_code=company_code, vehicle_record_id=vehicle_id
    ).with_for_update().first()
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_id, company_code=company_code
    ).first()
    if target is None or vehicle is None:
        raise _dkss_common.UploadValidationError(
            "同じ会社・車両の整備または点検を選択してください。"
        )

    canonical_payload = _dkss_common.json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    existing = _dkss_models.VehicleMaintenanceDocument.query.filter_by(
        company_code=company_code, source_draft_id=draft.id,
        source_record_index=index
    ).first()
    target_fields = {
        "maintenance_record_id": target_id if target_kind == "maintenance" else None,
        "inspection_record_id": target_id if target_kind == "inspection" else None,
    }
    if existing is not None:
        if (
            existing.vehicle_record_id != vehicle_id
            or existing.pending_record_id != item.id
            or any(
                getattr(existing, key) != value
                for key, value in target_fields.items()
            )
            or _dkss_serialization.safe_json_dict(existing.payload_json) != payload
        ):
            raise _dkss_common.UploadValidationError(
                "この明細は別の登録先へ保存済みです。再確認してください。"
            )
        return existing

    if item.status != "pending":
        raise _dkss_common.UploadValidationError("この明細は対応済みです。再確認してください。")

    if not any(
        row["kind"] == target_kind and row["record_id"] == target_id
        for row in get_vehicle_pending_maintenance_candidates(
            company_code, vehicle_id, payload
        )
    ):
        raise _dkss_common.UploadValidationError("整備候補が変わりました。再確認してください。")

    document = _dkss_models.VehicleMaintenanceDocument(
        company_code=company_code, vehicle_record_id=vehicle_id,
        source_draft_id=draft.id, source_record_index=index,
        pending_record_id=item.id, payload_json=canonical_payload,
        decision_json=_dkss_common.json.dumps({
            "service_match": "same",
            "matched_by_username": username,
            "costs_applied": False,
            "parts_applied": False,
        }, ensure_ascii=False),
        financial_status="pending",
        parts_status="pending",
        created_by_username=username,
        **target_fields
    )
    _dkss_common.db.session.add(document)
    _dkss_common.db.session.flush()
    return document



def merge_vehicle_pending_invoice_record(target_id, invoice):
    """請求未登録の整備へ追加する。確定は呼出元のトランザクションで行う。"""
    if (
        not isinstance(invoice, _dkss_models.VehicleMaintenanceRecord)
        or not _dkss_common.inspect(invoice).transient
        or invoice.company_code != _dkss_common.session.get("company_code")
        or isinstance(target_id, bool) or not isinstance(target_id, int)
    ):
        raise _dkss_common.UploadValidationError("請求書の登録先を再確認してください。")

    candidates = get_vehicle_pending_maintenance_candidates(
        invoice.company_code, invoice.vehicle_record_id,
        {"record_date": invoice.entry_date,
         "completion_date": invoice.completion_date}
    )
    candidate = next((row for row in candidates if (
        row["kind"] == "maintenance" and row["record_id"] == target_id
    )), None)
    if candidate is None:
        raise _dkss_common.UploadValidationError("同じ車両・作業日の整備を選択してください。")

    record = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
        id=target_id, company_code=invoice.company_code,
        vehicle_record_id=invoice.vehicle_record_id
    ).with_for_update().populate_existing().first()
    if record is None:
        raise _dkss_common.UploadValidationError("登録先の整備記録を確認できません。")

    costs = ("labor_cost", "parts_cost", "other_cost", "tax_amount", "total_cost")
    details = _dkss_serialization.safe_json_dict(record.invoice_details_json)
    if (
        record.invoice_number or record.invoice_date or details.get("source")
        or any(getattr(record, field) is not None for field in costs)
        or _dkss_common.json.loads(record.line_items_json or "[]")
        or details.get("fees")
        or _dkss_models.VehiclePartReplacement.query.filter_by(
            company_code=record.company_code,
            maintenance_record_id=record.id
        ).first() is not None
    ):
        raise _dkss_common.UploadValidationError(
            "この整備には請求情報・費用・部品が登録済みです。上書きせず、内容を確認してください。"
        )

    invoice_details = _dkss_serialization.safe_json_dict(invoice.invoice_details_json)
    if not isinstance(invoice_details.get("source"), dict):
        raise _dkss_common.UploadValidationError("請求書の原本情報を確認できません。")

    if not invoice.cost_office and details.get("cost_attribution"):
        invoice_details["cost_attribution"] = details["cost_attribution"]
    record.invoice_details_json = _dkss_common.json.dumps({
        **details, **invoice_details,
        "before_invoice_attachment": details,
        "before_invoice_attachment_json": record.invoice_details_json,
        "attached_invoice_content": invoice.content,
        "attached_invoice_notes": invoice.notes,
    }, ensure_ascii=False)

    for field in (*costs, "invoice_number", "invoice_date", "line_items_json"):
        setattr(record, field, getattr(invoice, field))

    for field in ("entry_date", "completion_date", "mileage", "maintenance_company"):
        if getattr(record, field) is None or getattr(record, field) == "":
            setattr(record, field, getattr(invoice, field))

    record.updated_by_username = _dkss_common.session.get("username")
    record.updated_at = _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).isoformat(
        timespec="seconds"
    )
    return record



def apply_vehicle_import_pending_documents(
    pending_id, vehicle_id, company_code, username, *, invoice_choices=None
):
    return apply_vehicle_import_pending_records(
        pending_id, vehicle_id, company_code, username,
        invoice_choices=invoice_choices,
        allowed_kinds={"inspection", "maintenance", "driving_report"},
    )



def apply_vehicle_import_pending_operations(
    pending_id, vehicle_id, company_code, username
):
    return apply_vehicle_import_pending_records(
        pending_id, vehicle_id, company_code, username,
        allowed_kinds={"operation"},
    )



def apply_vehicle_import_pending_records(
    pending_id, vehicle_id, company_code, username, *, invoice_choices=None,
    allowed_kinds=None,
):
    """Claim once and apply every source in the caller's single transaction."""
    if (
        not company_code or not username
        or isinstance(vehicle_id, bool) or not isinstance(vehicle_id, int)
    ):
        raise _dkss_common.UploadValidationError("会社・利用者・登録先を確認してください。")

    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_id, company_code=company_code
    ).first()
    if vehicle is None:
        raise _dkss_common.UploadValidationError("登録先の車両を確認できません。")

    company = _dkss_models.Company.query.filter_by(
        company_code=company_code
    ).with_for_update().first()
    if company is None:
        raise _dkss_common.UploadValidationError("会社情報を確認できません。")

    claimed = _dkss_models.VehicleImportPending.query.filter_by(
        id=pending_id, company_code=company_code, status="pending"
    ).update({"status": "processing"}, synchronize_session=False)
    if claimed != 1:
        raise _dkss_common.UploadValidationError("この登録待ちは対応済みか、処理中です。")

    items = _dkss_models.VehicleImportPendingRecord.query.filter_by(
        pending_id=pending_id, company_code=company_code, status="pending"
    ).order_by(_dkss_models.VehicleImportPendingRecord.id).all()
    supported = {"operation", "inspection", "maintenance", "driving_report"}
    kinds = {item.source_kind for item in items}
    if not items or not kinds <= (
        supported if allowed_kinds is None else supported & allowed_kinds
    ):
        raise _dkss_common.UploadValidationError("登録待ちの資料構成を再確認してください。")

    result = {"added_count": 0, "linked_count": 0, "review_pending_count": 0}
    operations = [item for item in items if item.source_kind == "operation"]
    documents = [item for item in items if item.source_kind != "operation"]
    if operations:
        applied = _apply_vehicle_pending_operation_records(
            operations, vehicle_id, company_code, username
        )
        for key, value in applied.items():
            result[key] += value
    if documents:
        applied = _apply_vehicle_pending_document_records(
            documents, vehicle_id, company_code, username,
            invoice_choices=invoice_choices,
        )
        for key, value in applied.items():
            result[key] += value

    _dkss_common.db.session.flush()
    pending = _dkss_models.VehicleImportPending.query.filter_by(
        id=pending_id, company_code=company_code
    ).first()
    applied_ids = {
        row.vehicle_record_id
        for row in _dkss_models.VehicleImportPendingRecord.query.filter_by(
            pending_id=pending_id, company_code=company_code, status="applied"
        ).all()
        if row.vehicle_record_id is not None
    }
    pending.status = "resolved"
    pending.resolved_vehicle_id = (
        next(iter(applied_ids)) if len(applied_ids) == 1 else None
    )
    pending.resolved_at = _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC"))
    pending.resolution_json = _dkss_common.json.dumps({
        "vehicle_ids": sorted(applied_ids),
        "resolved_by_username": username,
    })
    _dkss_common.db.session.flush()
    return result



def _apply_vehicle_pending_document_records(items, vehicle_id, company_code, username, *, invoice_choices=None):
    maintenance_candidates = {item.id: get_vehicle_pending_maintenance_candidates(company_code, vehicle_id, _dkss_serialization.safe_json_dict(item.payload_json)) for item in items if item.source_kind == 'maintenance'}
    added_count = 0
    now = _dkss_common.datetime.now(_dkss_common.ZoneInfo('UTC'))
    for item in items:
        draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(id=item.document_draft_id, company_code=company_code, document_type=item.source_kind, status='completed').first()
        if draft is None or _dkss_common.hashlib.sha256(draft.source_file).hexdigest() != draft.source_sha256:
            raise _dkss_common.UploadValidationError('保存済みの原本を確認できません。')
        payload = _dkss_serialization.safe_json_dict(item.payload_json)
        preview_records = _dkss_serialization.safe_json_dict(draft.preview_json).get('records')
        index = item.source_record_index
        if not isinstance(preview_records, list) or not 0 <= index < len(preview_records) or preview_records[index] != payload or (payload.get('vehicle_record_id') is not None):
            raise _dkss_common.UploadValidationError('保存済み明細の一致を確認できません。')
        if item.source_kind == 'maintenance':
            source_keys = _dkss_vehicle_imports.maintenance_import_source_keys({'sha256': draft.source_sha256, 'pages': payload.get('source_pages'), 'record_index': index})
            if source_keys & _dkss_vehicle_imports.registered_maintenance_import_keys(company_code, exclude_pending_record_id=item.id):
                raise _dkss_common.UploadValidationError('同じ原本の請求書が登録済み、または他の登録待ちと重複しています。')
        if item.source_kind in {'inspection', 'driving_report'} and (draft.source_sha256, index) in _dkss_vehicle_imports.registered_inspection_import_keys(company_code, exclude_pending_record_id=item.id, source_kind=item.source_kind):
            raise _dkss_common.UploadValidationError('同じ原本の記録がすでに登録されています。')
        values = {**payload, 'vehicle_record_id': vehicle_id}
        recovered = _driving_recovery.effective_selection(item, draft) if item.source_kind == 'driving_report' else None
        if recovered:
            values['identity_recovery'] = recovered[2]
        record = _dkss_vehicle_imports.build_vehicle_document_record(draft, index, values)
        document = None
        if item.source_kind == 'maintenance':
            candidates = maintenance_candidates.get(item.id, [])
            choice = (invoice_choices or {}).get(item.id, '')
            if candidates and (not choice):
                raise _dkss_common.UploadValidationError('請求書と整備の対応を回答してください。')
            if choice and choice != 'new':
                selected = next((row for row in candidates if choice == f"{row['kind']}:{row['record_id']}"), None)
                if selected is None:
                    raise _dkss_common.UploadValidationError('整備候補が変わりました。再確認してください。')
                document = save_vehicle_maintenance_document(item.id, vehicle_id, selected['kind'], selected['record_id'], company_code, username)
        if document is None:
            added_count += int(_dkss_common.inspect(record).transient)
            _dkss_common.db.session.add(record)
            _dkss_common.db.session.flush()
            if item.source_kind == 'driving_report':
                from .driving_access import resolve_import
                try:
                    resolve_import(record, recovered[0] if recovered else values.get('_driving_account_choice') or None,
                                   expected_identity=recovered[1] if recovered else values.get('_driving_account_identity'))
                except _dkss_common.HTTPException as error:
                    if error.code == 409:raise _driving_recovery.RecoveryConflict(item.id) from None
                    raise
            if item.source_kind == 'maintenance':
                _dkss_maintenance.add_vehicle_maintenance_record_event(record, action='imported')
                _dkss_vehicle_karte.save_vehicle_maintenance_replacement_parts(record)
        applied_result = {'record_id': record.id if document is None else None, 'document_type': draft.document_type}
        if document is not None:
            applied_result.update({'maintenance_document_id': document.id, 'target_kind': selected['kind'], 'target_record_id': selected['record_id'], 'financial_status': document.financial_status, 'parts_status': document.parts_status})
        result = _dkss_serialization.safe_json_dict(draft.result_json)
        registered = result.get('records', [])
        if not isinstance(registered, list) or any((not isinstance(row, dict) or row.get('record_index') == index for row in registered)):
            raise _dkss_common.UploadValidationError('この明細の反映状況を再確認してください。')
        registered.append({**applied_result, 'record_index': index, 'vehicle_record_id': vehicle_id})
        waiting = result.get('pending_records', [])
        if not isinstance(waiting, list) or not all((isinstance(row, dict) for row in waiting)):
            raise _dkss_common.UploadValidationError('登録待ち明細を再確認してください。')
        waiting = [row for row in waiting if row.get('pending_record_id') != item.id]
        draft.result_json = _dkss_common.json.dumps({**result, 'records': registered, 'pending_records': waiting, 'pending_count': len(waiting)}, ensure_ascii=False)
        item.status = 'applied'
        item.vehicle_record_id = vehicle_id
        item.applied_at = now
        previous_result = _driving_recovery.object_value(item.result_json, item.id) if item.source_kind == 'driving_report' else {}
        item.result_json = _dkss_common.json.dumps({**previous_result, **applied_result}, ensure_ascii=False)
    _dkss_common.db.session.flush()
    review_pending_count = _dkss_models.VehicleMaintenanceDocument.query.filter(_dkss_models.VehicleMaintenanceDocument.company_code == company_code, _dkss_models.VehicleMaintenanceDocument.pending_record_id.in_([item.id for item in items]), _dkss_models.VehicleMaintenanceDocument.financial_status == 'pending').count()
    return {'added_count': added_count, 'linked_count': len(items), 'review_pending_count': review_pending_count}



def _apply_vehicle_pending_operation_records(
    records, vehicle_id, company_code, username
):
    source_rows_by_draft = {}
    added_count = 0
    linked_count = 0
    now = _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC"))
    imported_at = now.astimezone(_dkss_common.ZoneInfo("Asia/Tokyo")).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    for item in records:
        draft = _dkss_models.VehicleOperationImportDraft.query.filter_by(
            id=item.operation_draft_id, company_code=company_code
        ).first()
        if draft is None:
            raise _dkss_common.UploadValidationError("取込原本を確認できません。")
        _csv_owner.hold_private_source(draft)

        if draft.id not in source_rows_by_draft:
            source_rows_by_draft[draft.id] = {
                row["line_number"]: row["source_row"]
                for row in _dkss_common.read_vehicle_operation_csv(draft.source_file)
            }
        source_row = source_rows_by_draft[draft.id].get(
            item.source_record_index
        )
        if source_row is None:
            raise _dkss_common.UploadValidationError("原本の対象行を確認できません。")

        payload = _dkss_serialization.safe_json_dict(item.payload_json)
        values = _dkss_common.parse_vehicle_operation_csv_row(
            source_row, item.source_record_index
        )
        if _dkss_common.json.loads(_dkss_common.json.dumps(values, default=str)) != payload:
            raise _dkss_common.UploadValidationError("保存データと原本の内容が一致しません。")

        source_code = str(values.get("source_vehicle_code") or "").strip()
        source_number = _dkss_common.normalize_vehicle_operation_plate(
            values.get("source_vehicle_number")
        )
        if source_code and source_number:
            mapping = _dkss_models.VehicleOperationVehicleMapping.query.filter_by(
                company_code=company_code,
                source_vehicle_code=source_code,
                source_vehicle_number=source_number
            ).with_for_update().first()

            if mapping is not None and mapping.vehicle_record_id != vehicle_id:
                raise _dkss_common.UploadValidationError(
                    "この車両コード・ナンバーは別の車両に対応付けられています。登録先を再確認してください。"
                )

            if mapping is None:
                mapping = _dkss_models.VehicleOperationVehicleMapping(
                    company_code=company_code,
                    source_vehicle_code=source_code,
                    source_vehicle_number=source_number,
                    vehicle_record_id=vehicle_id,
                    confirmed_by_username=username,
                    confirmed_at=now
                )
                _dkss_common.db.session.add(mapping)
            else:
                mapping.confirmed_by_username = username
                mapping.confirmed_at = now

        operation = _dkss_models.VehicleOperationRecord.query.filter_by(
            company_code=company_code,
            report_number=values["report_number"]
        ).first()
        if operation is not None:
            if operation.vehicle_record_id != vehicle_id or any(
                getattr(operation, key) != value
                for key, value in values.items()
            ):
                raise _dkss_common.UploadValidationError(
                    "同じ日報番号の登録済み実績と内容・車両が異なります。"
                )
        else:
            operation = _dkss_models.VehicleOperationRecord(
                company_code=company_code,
                vehicle_record_id=vehicle_id,
                source_filename=draft.source_filename,
                imported_by_username=username,
                imported_at=imported_at,
                **values
            )
            _dkss_common.db.session.add(operation)
            _dkss_common.db.session.flush()
            added_count += 1

        item.status = "applied"
        item.vehicle_record_id = vehicle_id
        item.applied_at = now
        item.result_json = _dkss_common.json.dumps({
            "operation_record_id": operation.id
        })
        original_ids = _dkss_vehicle_karte.get_vehicle_operation_imported_vehicle_ids(draft)
        original_ids.add(vehicle_id)
        draft.result_json = _dkss_common.json.dumps({
            **_dkss_serialization.safe_json_dict(draft.result_json),
            "imported_vehicle_ids": sorted(original_ids),
        })
        linked_count += 1

    return {"added_count": added_count, "linked_count": linked_count}



def vehicle_import_pending_query(company_code):
    pending_record_exists = _dkss_common.db.session.query(
        _dkss_models.VehicleImportPendingRecord.id
    ).filter(
        _dkss_models.VehicleImportPendingRecord.pending_id == _dkss_models.VehicleImportPending.id,
        _dkss_models.VehicleImportPendingRecord.company_code == company_code,
        _dkss_models.VehicleImportPendingRecord.status == "pending"
    ).exists()

    return _dkss_models.VehicleImportPending.query.filter(
        _dkss_models.VehicleImportPending.company_code == company_code,
        _dkss_models.VehicleImportPending.status == "pending",
        pending_record_exists
    )



def render_vehicle_list(template_name):
    keyword = _dkss_common.request.args.get("keyword", "").strip()
    office = _dkss_common.request.args.get("office", "").strip()
    vehicle_type = _dkss_common.request.args.get("vehicle_type", "").strip()
    status = _dkss_common.request.args.get("status", "").strip()
    manufacturer = _dkss_common.request.args.get("manufacturer", "").strip()
    model_code = _dkss_common.request.args.get("model_code", "").strip()

    if (
        len(keyword) > 100
        or len(office) > 100
        or len(vehicle_type) > 100
        or len(status) > 50
        or len(manufacturer) > 100
        or len(model_code) > 100
    ):
        return "検索条件が長すぎます。", 400

    if status not in {"", "active", "inactive"}:
        return "状態が不正です。", 400

    company_code = _dkss_common.session.get("company_code")

    if office:
        valid_office = _dkss_models.Office.query.filter_by(
            company_code=company_code,
            name=office
        ).first()

        if not valid_office:
            return "営業所が不正です。", 400

    if vehicle_type:
        valid_vehicle_type = _dkss_models.VehicleType.query.filter_by(
            company_code=company_code,
            name=vehicle_type
        ).first()

        if not valid_vehicle_type:
            return "車種が不正です。", 400

    if manufacturer:
        valid_manufacturer = _dkss_models.Vehicle.query.filter_by(
            company_code=company_code,
            manufacturer=manufacturer
        ).first()

        if not valid_manufacturer:
            return "メーカーが不正です。", 400

    if model_code:
        valid_model_code = _dkss_models.Vehicle.query.filter_by(
            company_code=company_code,
            model_code=model_code
        ).first()

        if not valid_model_code:
            return "型式が不正です。", 400

    query = _dkss_models.Vehicle.query.filter_by(
        company_code=company_code
    )

    plate_number_search = _dkss_common.request.args.get(
        "plate_number_search", ""
    ).strip()
    chassis_number_search = _dkss_common.request.args.get(
        "chassis_number_search", ""
    ).strip()

    search_errors = []

    if len(plate_number_search) > 100:
        search_errors.append((
            "車番の検索条件は100文字以内で入力してください。",
            "vehicle_search_plate_number"
        ))

    if len(chassis_number_search) > 100:
        search_errors.append((
            "車台番号の検索条件は100文字以内で入力してください。",
            "vehicle_search_chassis_number"
        ))

    if search_errors:
        return _dkss_http.return_form_errors(search_errors)

    if plate_number_search:
        normalized_plate_number = "".join(
            plate_number_search.split()
        ).replace("-", "").replace("－", "")

        if normalized_plate_number:
            plate_number_expression = (
                _dkss_common.db.func.coalesce(_dkss_models.Vehicle.plate_area, "")
                + _dkss_common.db.func.coalesce(_dkss_models.Vehicle.plate_class, "")
                + _dkss_common.db.func.coalesce(_dkss_models.Vehicle.plate_kana, "")
                + _dkss_common.db.func.coalesce(_dkss_models.Vehicle.plate_number, "")
            )

            for separator in (" ", "　", "-", "－"):
                plate_number_expression = _dkss_common.db.func.replace(
                    plate_number_expression,
                    separator,
                    ""
                )

            query = query.filter(
                plate_number_expression.ilike(
                    f"%{normalized_plate_number}%"
                )
            )

    if chassis_number_search:
        query = query.filter(
            _dkss_models.Vehicle.chassis_number.ilike(
                f"%{chassis_number_search}%"
            )
        )

    # キーワード検索
    if keyword:

        keyword_like = f"%{keyword}%"

        query = query.filter(
            _dkss_common.db.or_(
                _dkss_models.Vehicle.plate_area.ilike(keyword_like),
                _dkss_models.Vehicle.plate_class.ilike(keyword_like),
                _dkss_models.Vehicle.plate_kana.ilike(keyword_like),
                _dkss_models.Vehicle.plate_number.ilike(keyword_like),
                _dkss_models.Vehicle.chassis_number.ilike(keyword_like),
                _dkss_models.Vehicle.model_code.ilike(keyword_like),
                _dkss_models.Vehicle.manufacturer.ilike(keyword_like),
                _dkss_models.Vehicle.body_type.ilike(keyword_like),
            )
        )


    # 有効・無効
    if status == "active":
        query = query.filter(
            _dkss_models.Vehicle.deleted == False
        )

    elif status == "inactive":
        query = query.filter(
            _dkss_models.Vehicle.deleted == True
        )


    # メーカー・車名
    if manufacturer:
        query = query.filter(
            _dkss_models.Vehicle.manufacturer == manufacturer
        )


    # 型式
    if model_code:
        query = query.filter(
            _dkss_models.Vehicle.model_code == model_code
        )


    # 営業所
    if office:
        query = query.filter(
            _dkss_models.Vehicle.office == office
        )


    # 車種
    if vehicle_type:
        query = query.filter(
            _dkss_models.Vehicle.type == vehicle_type
        )


    # メーカー候補
    manufacturers = [
        item[0]
        for item in _dkss_common.db.session.query(_dkss_models.Vehicle.manufacturer)
        .filter(
            _dkss_models.Vehicle.company_code == _dkss_common.session.get("company_code"),
            _dkss_models.Vehicle.manufacturer.isnot(None),
            _dkss_models.Vehicle.manufacturer != ""
        )
        .distinct()
        .order_by(_dkss_models.Vehicle.manufacturer)
        .all()
    ]


    # 型式候補
    model_codes = [
        item[0]
        for item in _dkss_common.db.session.query(_dkss_models.Vehicle.model_code)
        .filter(
            _dkss_models.Vehicle.company_code == _dkss_common.session.get("company_code"),
            _dkss_models.Vehicle.model_code.isnot(None),
            _dkss_models.Vehicle.model_code != ""
        )
        .distinct()
        .order_by(_dkss_models.Vehicle.model_code)
        .all()
    ]


    # ページ分割
    page = _dkss_common.request.args.get("page", 1, type=int)
    per_page = 10

    total_count = query.count()

    total_pages = max(
        1,
        (total_count + per_page - 1) // per_page
    )

    if page < 1:
        page = 1

    if page > total_pages:
        page = total_pages


    vehicle_records = (
        query
        .order_by(_dkss_models.Vehicle.id.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )


    filtered_vehicles = []

    for vehicle in vehicle_records:

        item = {
            "index": vehicle.id,
            "id": vehicle.id,
            "company_code": vehicle.company_code,
            "vehicle_record_id": vehicle.id,
            "deleted": vehicle.deleted,

            "plate_area": vehicle.plate_area,
            "plate_class": vehicle.plate_class,
            "plate_kana": vehicle.plate_kana,
            "plate_number": vehicle.plate_number,

            "chassis_number": vehicle.chassis_number,
            "model_code": vehicle.model_code,
            "first_registration_date": vehicle.first_registration_date,
            "manufacturer": vehicle.manufacturer,
            "body_type": vehicle.body_type,

            "gross_vehicle_weight": vehicle.gross_vehicle_weight,
            "max_payload": vehicle.max_payload,

            "type": vehicle.type,
            "office": vehicle.office,
            "inspection_expiry": vehicle.inspection_expiry,
        }

        item["number"] = _dkss_vehicle_readers.vehicle_number(item)

        if template_name == "vehicle_master.html":
            item["open_defect_count"] = len(
                _dkss_checklists.get_vehicle_open_inspection_defects(
                    company_code,
                    vehicle.id
                )
            )

        filtered_vehicles.append(item)

    company = _dkss_models.Company.query.filter_by(
        company_code=_dkss_common.session.get("company_code")
    ).first()

    vehicle_limit = 0

    vehicle_count = _dkss_models.Vehicle.query.filter_by(
        company_code=_dkss_common.session.get("company_code"),
        deleted=False
    ).count()

    remaining_vehicles = 0

    if company:
        vehicle_limit = company.vehicle_limit
        remaining_vehicles = vehicle_limit - vehicle_count

    return _dkss_common.render_template(
        template_name,
        vehicles=filtered_vehicles,
        offices=_dkss_master_readers.offices_for_current_company(),
        vehicle_types=_dkss_vehicle_readers.vehicle_types_for_current_company(),
        keyword=keyword,
        office=office,
        vehicle_type=vehicle_type,
        status=status,
        manufacturer=manufacturer,
        model_code=model_code,

        manufacturers=manufacturers,
        model_codes=model_codes,

        vehicle_limit=vehicle_limit,
        vehicle_count=vehicle_count,
        remaining_vehicles=remaining_vehicles,
        pending_vehicle_count=vehicle_import_pending_query(
            company_code
        ).count(),

        page=page,
        total_pages=total_pages,
        total_count=total_count,
    )



def register_vehicle_import_master():
    company_code = _dkss_common.session.get("company_code")

    if not company_code or not _dkss_access.require_master_admin():
        return _dkss_http.return_form_errors([
            ("管理者権限が必要です。", "")
        ], status_code=403)

    master_kind = _dkss_common.request.form.get("master_kind", "").strip()
    name = _dkss_common.request.form.get("name", "").strip()

    master_models = {
        "office": (_dkss_models.Office, "営業所"),
        "vehicle_type": (_dkss_models.VehicleType, "車種"),
    }

    if master_kind not in master_models:
        return _dkss_http.return_form_errors([
            ("登録するマスタの種類を確認してください。", "")
        ])

    model, label = master_models[master_kind]

    if not name:
        return _dkss_http.return_form_errors([
            (f"{label}名を入力してください。", "name")
        ])

    if len(name) > 100:
        return _dkss_http.return_form_errors([
            (f"{label}名は100文字以内で入力してください。", "name")
        ])

    existing = model.query.filter_by(
        company_code=company_code,
        name=name
    ).first()

    if existing:
        return _dkss_http.return_form_errors([
            (
                f"{label}「{name}」はすでに登録されています。"
                "既存マスタへの割り当てを選択してください。",
                "name"
            )
        ], status_code=409)

    if _dkss_common.request.headers.get("X-DKSS-Validation-Only") == "1":
        return _dkss_common.jsonify({"ok": True})

    if _dkss_common.request.form.get("confirmed") != "1":
        return _dkss_http.return_form_errors([
            ("新規登録する内容を確認してください。", "")
        ])

    master = model(
        company_code=company_code,
        name=name
    )

    try:
        _dkss_common.db.session.add(master)
        _dkss_common.db.session.commit()
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("車両Excel取込のマスタ登録に失敗しました。")
        return _dkss_http.return_form_errors([
            (
                f"{label}を登録できませんでした。"
                "入力内容を保持したまま、もう一度お試しください。",
                "name"
            )
        ], status_code=500)

    return _dkss_common.jsonify({
        "ok": True,
        "master_kind": master_kind,
        "master": {
            "id": master.id,
            "name": master.name,
        },
    })
