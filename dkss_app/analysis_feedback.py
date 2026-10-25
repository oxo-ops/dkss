"""Analysis Feedback responsibilities; routes are registered by the application factory."""
from . import analysis as _dkss_analysis, common as _dkss_common, models as _dkss_models, serialization as _dkss_serialization


def vehicle_analysis_proposal_ids(item):
    import unicodedata

    def digest(value):
        return _dkss_common.hashlib.sha256(_dkss_common.json.dumps(
            value, sort_keys=True, ensure_ascii=False, default=str,
        ).encode("utf-8")).hexdigest()

    target = unicodedata.normalize("NFKC", str(item.get("target") or item.get("title") or ""))
    key = digest({
        "target": " ".join(target.casefold().split()),
        "category": item.get("category", ""),
        "sources": sorted({
            value for value in item.get("source_ids", [])
            if isinstance(value, str) and not value.startswith("knowledge:")
        }),
    })
    return key, digest(item)



def latest_vehicle_analysis_feedback(company_code, vehicle_record_id):
    latest_ids = _dkss_common.db.session.query(_dkss_common.db.func.max(_dkss_models.VehicleAnalysisFeedback.id)).filter_by(
        company_code=company_code, vehicle_record_id=vehicle_record_id,
    ).group_by(_dkss_models.VehicleAnalysisFeedback.proposal_key).scalar_subquery()
    rows = _dkss_models.VehicleAnalysisFeedback.query.filter(
        _dkss_models.VehicleAnalysisFeedback.id.in_(latest_ids),
    ).order_by(_dkss_models.VehicleAnalysisFeedback.id.desc()).all()
    return [row for row in rows
            if not _dkss_serialization.safe_json_dict(row.snapshot_json).get("source_withdrawn")]



def vehicle_analysis_maintenance_value(row):
    date = row.entry_date or row.completion_date or "日付未登録"
    content = row.content or row.repair_content or row.category or "内容未登録"
    return {
        "id": row.id,
        "label": f"{date} · {content[:80]}",
        "url": _dkss_common.url_for(
            "vehicle_karte_maintenance",
            vehicle_record_id=row.vehicle_record_id,
            record_id=row.id,
        ),
        "entry_date": row.entry_date,
        "completion_date": row.completion_date,
        "status": row.status,
        "content": (row.content or "")[:2000],
        "repair_content": (row.repair_content or "")[:2000],
        "mileage": str(row.mileage) if row.mileage is not None else None,
    }



def vehicle_analysis_feedback_value(row):
    snapshot = _dkss_serialization.safe_json_dict(row.snapshot_json)
    proposal = snapshot.get("proposal") or {}
    return {
        "id": row.id,
        "proposal_id": row.proposal_key,
        "target": proposal.get("target") or proposal.get("title") or "過去の提案",
        "action": proposal.get("action") or "",
        "maintenance_record": snapshot.get("maintenance_record"),
        "status": row.status, "comment": row.comment,
        "by": row.created_by, "at": row.created_at,
        "revision": row.proposal_revision,
    }



def analysis_with_vehicle_feedback(analysis, vehicle):
    if not isinstance(analysis, dict):
        return analysis
    feedback = {
        row.proposal_key: row
        for row in latest_vehicle_analysis_feedback(vehicle.company_code, vehicle.id)
    }
    evaluations = {
        (row.proposal_key, row.proposal_revision): row
        for row in latest_vehicle_analysis_evaluations(vehicle.company_code, vehicle.id)
    }
    items = []
    for original in analysis.get("recommendations", []):
        if not isinstance(original, dict):
            continue
        key, revision = vehicle_analysis_proposal_ids(original)
        item = dict(original, proposal_id=key, proposal_revision=revision)
        item["evaluation"] = (
            vehicle_analysis_evaluation_value(evaluations[(key, revision)])
            if (key, revision) in evaluations else {}
        )
        item["feedback"] = (
            vehicle_analysis_feedback_value(feedback[key]) if key in feedback else {}
        )
        items.append(item)
    maintenance_records = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
        company_code=vehicle.company_code,
        vehicle_record_id=vehicle.id,
    ).order_by(
        _dkss_common.db.func.coalesce(
            _dkss_models.VehicleMaintenanceRecord.entry_date,
            _dkss_models.VehicleMaintenanceRecord.completion_date,
        ).desc(),
        _dkss_models.VehicleMaintenanceRecord.id.desc(),
    ).limit(100).all()
    return dict(
        analysis,
        recommendations=items,
        feedback_history=[
            vehicle_analysis_feedback_value(row)
            for row in _dkss_models.VehicleAnalysisFeedback.query.filter_by(
                company_code=vehicle.company_code,
                vehicle_record_id=vehicle.id,
            ).order_by(_dkss_models.VehicleAnalysisFeedback.id.desc()).limit(30).all()
        ],
        maintenance_records=[
            vehicle_analysis_maintenance_value(row)
            for row in maintenance_records
        ],
    )



def save_vehicle_analysis_feedback(vehicle_record_id):
    if not _dkss_common.session.get("username"):
        return _dkss_common.jsonify(ok=False, message="ログインし直してください。"), 401
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id, company_code=_dkss_common.session.get("company_code"), deleted=False,
    ).first_or_404()
    body = _dkss_common.request.get_json(silent=True)
    if not isinstance(body, dict):
        return _dkss_common.jsonify(ok=False, message="送信内容を確認できませんでした。"), 400
    chosen = body.get("status")
    comment = body.get("comment", "")
    if (
        not isinstance(chosen, str)
        or chosen not in {"open", "accepted", "in_progress", "completed", "dismissed"}
        or not isinstance(comment, str) or len(comment) > 5000
    ):
        return _dkss_common.jsonify(ok=False, message="コメントは5000文字以内で入力してください。"), 400
    state = _dkss_models.VehicleKarteAnalysis.query.filter_by(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
    ).first()
    bundle = _dkss_serialization.safe_json_dict(state.result_json) if state else {}
    analysis = bundle.get("analysis") or {}
    selected = None
    for item in analysis.get("recommendations", []):
        if not isinstance(item, dict):
            continue
        key, revision = vehicle_analysis_proposal_ids(item)
        if key == body.get("proposal_id") and revision == body.get("proposal_revision"):
            selected = item
            break
    if selected is None:
        return _dkss_common.jsonify(ok=False, message="提案が更新されています。最新の内容を確認してください。"), 409
    try:
        payload, _sources = _dkss_analysis.get_vehicle_karte_analysis_job_data(vehicle)
        current = state.status == "completed" and _dkss_analysis.vehicle_karte_analysis_matches_input(bundle, payload)
    except Exception:
        current = False
    if not current:
        return _dkss_common.jsonify(ok=False, message="分析の更新が必要です。更新完了後に最新の提案を確認して記録してください。"), 409
    comment = comment.strip()
    previous = _dkss_models.VehicleAnalysisFeedback.query.filter_by(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
        proposal_key=key,
    ).order_by(_dkss_models.VehicleAnalysisFeedback.id.desc()).first()
    previous_record = (
        _dkss_serialization.safe_json_dict(previous.snapshot_json).get("maintenance_record")
        if previous else None
    )
    record_id = body.get(
        "maintenance_record_id",
        (previous_record or {}).get("id"),
    )
    if record_id is not None and type(record_id) is not int:
        return _dkss_common.jsonify(
            ok=False,
            message="関連する整備記録を選び直してください。",
        ), 400

    linked_record = None
    if record_id is not None:
        record = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
            id=record_id,
            company_code=vehicle.company_code,
            vehicle_record_id=vehicle.id,
        ).first()
        if record is None:
            return _dkss_common.jsonify(
                ok=False,
                message="同じ車両の整備記録を選んでください。",
            ), 400
        linked_record = vehicle_analysis_maintenance_value(record)

    if previous and (
        previous.status == chosen and previous.comment == comment
        and previous.proposal_revision == revision
        and previous_record == linked_record
    ):
        return _dkss_common.jsonify(ok=True, feedback=vehicle_analysis_feedback_value(previous))
    row = _dkss_models.VehicleAnalysisFeedback(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
        proposal_key=key, proposal_revision=revision, status=chosen,
        comment=comment, created_by=_dkss_common.session["username"],
        created_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M"),
        snapshot_json=_dkss_common.json.dumps({
            "proposal": selected, "generated_at": bundle.get("generated_at"),
            "maintenance_record": linked_record,
            "sources": {
                source_id: source
                for source_id, source in (bundle.get("sources") or {}).items()
                if source_id in selected.get("source_ids", [])
            },
        }, ensure_ascii=False, default=str),
    )
    _dkss_common.db.session.add(row)
    _dkss_common.db.session.commit()
    return _dkss_common.jsonify(ok=True, feedback=vehicle_analysis_feedback_value(row))



def latest_vehicle_analysis_evaluations(company_code, vehicle_record_id):
    ids = _dkss_common.db.session.query(_dkss_common.db.func.max(_dkss_models.VehicleAnalysisEvaluation.id)).filter_by(
        company_code=company_code, vehicle_record_id=vehicle_record_id,
    ).group_by(
        _dkss_models.VehicleAnalysisEvaluation.proposal_key,
        _dkss_models.VehicleAnalysisEvaluation.proposal_revision,
    ).scalar_subquery()
    return _dkss_models.VehicleAnalysisEvaluation.query.filter(
        _dkss_models.VehicleAnalysisEvaluation.company_code == company_code,
        _dkss_models.VehicleAnalysisEvaluation.vehicle_record_id == vehicle_record_id,
        _dkss_models.VehicleAnalysisEvaluation.id.in_(ids),
    ).order_by(_dkss_models.VehicleAnalysisEvaluation.id.desc()).limit(100).all()



def vehicle_analysis_evaluation_value(row):
    return {
        "verdict": row.verdict, "comment": row.comment,
        "by": row.created_by, "at": row.created_at,
        "revision": row.proposal_revision,
    }



def save_vehicle_analysis_evaluation(vehicle_record_id):
    from flask import abort

    if not _dkss_common.session.get("username") or not _dkss_common.session.get("company_code"):
        abort(403)
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id, company_code=_dkss_common.session["company_code"], deleted=False,
    ).first_or_404()
    body = _dkss_common.request.get_json(silent=True)
    if not isinstance(body, dict):
        return _dkss_common.jsonify(ok=False, message="送信内容を確認できませんでした。"), 400

    verdict, comment = body.get("verdict"), body.get("comment", "")
    if (
        not isinstance(verdict, str)
        or verdict not in {"appropriate", "needs_revision", "uncertain"}
        or not isinstance(comment, str)
        or len(comment) > 5000
    ):
        return _dkss_common.jsonify(ok=False, message="評価とコメントを確認してください。"), 400

    state = _dkss_models.VehicleKarteAnalysis.query.filter_by(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
    ).first()
    bundle = _dkss_serialization.safe_json_dict(state.result_json) if state else {}
    analysis = bundle.get("analysis") or {}
    selected = None
    for item in analysis.get("recommendations", []):
        if not isinstance(item, dict):
            continue
        key, revision = vehicle_analysis_proposal_ids(item)
        if key == body.get("proposal_id") and revision == body.get("proposal_revision"):
            selected = item
            break
    if selected is None:
        return _dkss_common.jsonify(ok=False, message="提案が更新されています。最新の内容を確認してください。"), 409

    comment = comment.strip()
    previous = _dkss_models.VehicleAnalysisEvaluation.query.filter_by(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
        proposal_key=key, proposal_revision=revision,
    ).order_by(_dkss_models.VehicleAnalysisEvaluation.id.desc()).first()
    if previous and previous.verdict == verdict and previous.comment == comment:
        return _dkss_common.jsonify(ok=True, evaluation=vehicle_analysis_evaluation_value(previous))

    row = _dkss_models.VehicleAnalysisEvaluation(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
        proposal_key=key, proposal_revision=revision, verdict=verdict, comment=comment,
        created_by=_dkss_common.session["username"],
        created_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M"),
        snapshot_json=_dkss_common.json.dumps({
            "proposal": selected,
            "generated_at": bundle.get("generated_at"),
            "analysis_method": bundle.get("analysis_method"),
            "fingerprints": bundle.get("fingerprints"),
            "sources": {
                source_id: source
                for source_id, source in (bundle.get("sources") or {}).items()
                if source_id in selected.get("source_ids", [])
            },
        }, ensure_ascii=False, default=str),
    )
    _dkss_common.db.session.add(row)
    _dkss_common.db.session.commit()
    return _dkss_common.jsonify(ok=True, evaluation=vehicle_analysis_evaluation_value(row))
