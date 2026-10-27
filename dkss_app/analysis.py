"""Analysis responsibilities; routes are registered by the application factory."""
from .maintenance_timing import AdoptedMaintenanceTimingService
from . import access as _dkss_access
from . import vehicle_operations as _dkss_vehicle_operations
from . import analysis_feedback as _dkss_analysis_feedback, checklists as _dkss_checklists, common as _dkss_common, knowledge as _dkss_knowledge, models as _dkss_models, runtime as _dkss_runtime, serialization as _dkss_serialization, vehicle_karte as _dkss_vehicle_karte, vehicle_readers as _dkss_vehicle_readers


def vehicle_maintenance_synthetic_evidence(row):
    from .maintenance_facts import synthetic_evidence
    return synthetic_evidence(row)


def filter_vehicle_maintenance_factual_history(maintenance, parts=()):
    from .maintenance_facts import factual_history
    return factual_history(maintenance, parts)


def vehicle_analysis_summary_service():
    return _dkss_common.VehicleAnalysisSummaryService(
        filter_factual_history=filter_vehicle_maintenance_factual_history,
        periodic_synthetic_evidence=periodic_inspection_synthetic_evidence,
        today=lambda: _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).date(),
    )



def build_vehicle_karte_mileage_reference(
    maintenance_records, operation_records, as_of,
    periodic_records=(), include_points=False,
):
    return vehicle_analysis_summary_service().mileage_reference(
        maintenance_records, operation_records, as_of,
        periodic_records=periodic_records, include_points=include_points,
    )



def build_vehicle_karte_analysis_summary(
    maintenance_records, operation_records, part_records,
    defect_records, start_date, end_date, periodic_records=(),
):
    return vehicle_analysis_summary_service().summarize(
        maintenance_records, operation_records, part_records,
        defect_records, start_date, end_date, periodic_records=periodic_records,
    )



def vehicle_karte_analysis_matches_input(bundle, payload):
    previous = bundle.get("fingerprints")
    current = payload["_fingerprints"]
    return isinstance(previous, dict) and all(
        key in previous and key in current and previous[key] == current[key]
        for key in ("policy_version", "important_hash", "routine_hash")
    )



def vehicle_karte_analysis_result(vehicle_record_id):
    if not _dkss_common.session.get("username"):
        return _dkss_common.jsonify(
            ok=False,
            message="ログインし直してください。",
        ), 401

    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=_dkss_common.session.get("company_code"),
        deleted=False,
    ).first_or_404()

    state = _dkss_models.VehicleKarteAnalysis.query.filter_by(
        company_code=vehicle.company_code,
        vehicle_record_id=vehicle.id,
    ).first()

    bundle = _dkss_serialization.safe_json_dict(state.result_json) if state else {}
    analysis = bundle.get("analysis")
    has_result = isinstance(analysis, dict)
    status = state.status if state else "waiting"

    # PREVENTIVE_ANALYSIS_UI_FRESHNESS_V1: completed alone does not prove freshness.
    is_current = None
    input_summary = None
    scheduled_comparison = None
    try:
        projection, stable = get_vehicle_analysis_read_projection(vehicle)
        scheduled_comparison = projection.get('comparison')
        input_summary = projection['input_summary']
        if has_result and stable:
            is_current = vehicle_karte_analysis_matches_input(bundle, {'_fingerprints': projection['fingerprints']})
    except Exception:
        _dkss_runtime.app.logger.warning("車両分析の入力・更新状態を確認できませんでした。vehicle_id=%s", vehicle.id)

    if status == "completed" and is_current is True:
        message = "現在の登録内容に対応する分析結果です。"
    elif status == "completed" and is_current is False:
        message = "更新待ち"
    elif status == "completed":
        message = "状態未確認"
    elif status == "running":
        message = "新しい情報を分析しています。"
    elif status == "pending":
        message = (
            "登録内容の変更を確認しました。"
            "自動更新を予定しています。"
        )
    elif status == "error":
        message = (
            "自動更新に失敗しました。"
            "時間をおいて自動で再試行します。"
        )
    else:
        message = "自動分析の準備中です。"

    if has_result and status in {"running", "pending", "error"}:
        message += " 現在は前回の結果を表示しています。"

    from vehicle_risk_assessment import annotate_analysis  # VEHICLE_RISK_MATRIX_API_V1
    response = _dkss_common.jsonify(
        ok=True,
        status=status,
        has_result=has_result,
        is_current=is_current,
        input_summary=input_summary,
        scheduled_comparison=scheduled_comparison,
        message=message,
        analysis=annotate_analysis(_dkss_analysis_feedback.analysis_with_vehicle_feedback(analysis, vehicle), bundle.get("sources"), vehicle.company_code, vehicle.id, is_current) if has_result else None,
        sources=bundle.get("sources") if has_result else {},
        coverage=bundle.get("coverage") if has_result else {},
        comparison=(
            bundle["comparison"]
            if has_result and isinstance(bundle.get("comparison"), dict)
            else None
        ),
        generated_at=(
            bundle.get("generated_at") if has_result else None
        ),
        analysis_method=(
            bundle.get("analysis_method") if has_result else None
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return response



def get_vehicle_analysis_read_projection(vehicle):
    from flask import current_app
    from vehicle_analysis_service import (
        AnalysisReadProjectionService,
        analysis_input_projection,
    )
    from .analysis_read_cache import AnalysisReadCacheRepository, code_hash

    app = current_app._get_current_object()
    company, vehicle_id = vehicle.company_code, vehicle.id

    def clock():
        return _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC"))

    def key(now):
        settings = _dkss_common.AnalysisComparisonSettings.from_environ(
            _dkss_common.os.environ
        )
        scope = [
            code_hash(),
            now.astimezone(_dkss_common.ZoneInfo("Asia/Tokyo")).date().isoformat(),
            settings.registration_scope,
            settings.include_inactive,
        ]
        return _dkss_common.hashlib.sha256(
            _dkss_common.json.dumps(scope).encode()
        ).hexdigest()

    def legacy():
        payload, _sources = get_vehicle_karte_analysis_job_data(vehicle)
        return analysis_input_projection(payload)

    def load():
        with app.app_context():
            fresh = _dkss_models.Vehicle.query.filter_by(
                id=vehicle_id, company_code=company, deleted=False
            ).first_or_404()
            payload, _sources = get_vehicle_karte_analysis_job_data(fresh)
            return analysis_input_projection(payload)

    try:
        return AnalysisReadProjectionService(
            repository=AnalysisReadCacheRepository(),
            load_projection=load,
            load_legacy_projection=legacy,
            context_key=key,
            clock=clock,
        ).read(company, vehicle_id)
    except _dkss_common.SQLAlchemyError:
        app.logger.warning("Analysis read cache unavailable; rebuilding inputs")
        return legacy(), True


def get_vehicle_karte_analysis_job_data(vehicle):
    repository = _dkss_common.VehicleAnalysisInputRepository(
        maintenance=_dkss_models.VehicleMaintenanceRecord, operations=_dkss_models.VehicleOperationRecord,
        parts=_dkss_models.VehiclePartReplacement, defects=_dkss_models.VehiclePatrol,
        periodic=_dkss_models.VehiclePeriodicInspectionRecord,
        canonical_operations=_dkss_vehicle_operations.get_vehicle_canonical_operations,
    )
    return _dkss_common.VehicleAnalysisInputService(
        repository=repository, build_summary=build_vehicle_karte_analysis_summary,
        read_comparison=get_vehicle_karte_peer_comparison,
        build_payload=build_vehicle_karte_analysis_payload,
        today=lambda: _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).date(),
        read_settings=lambda: _dkss_common.AnalysisComparisonSettings.from_environ(_dkss_common.os.environ),
    ).build(vehicle)



def run_vehicle_karte_analysis_job(state_id):
    """専用のバックグラウンド処理から呼び出す。"""
    repository = _dkss_common.VehicleAnalysisJobRepository(
        db=_dkss_common.db, state_model=_dkss_models.VehicleKarteAnalysis, vehicle_model=_dkss_models.Vehicle,
    )
    return _dkss_common.VehicleAnalysisJobService(
        repository=repository, load_input=get_vehicle_karte_analysis_job_data,
        analyze=_dkss_common.analyze_vehicle_karte,
        utc_now=lambda: _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC")),
        new_token=lambda: str(_dkss_common.uuid4()),
        input_context=lambda: _dkss_runtime.app.test_request_context("/"),
        logger=_dkss_runtime.app.logger, read_api_key=lambda: _dkss_common.os.environ.get("OPENAI_API_KEY", ""),
    ).run(state_id)



def vehicle_karte_analysis_worker():
    """自動分析を専用プロセスで継続実行する。"""
    import time

    print(
        "車両分析の自動更新を開始します。停止する場合は Ctrl+C。",
        flush=True,
    )

    try:
        while True:
            try:
                from click import get_current_context

                get_current_context().invoke(
                    _dkss_runtime.app.cli.commands["vehicle-karte-analysis-tick"]
                )

            except Exception:
                _dkss_common.db.session.rollback()
                _dkss_runtime.app.logger.exception(
                    "車両分析の定期処理に失敗しました。"
                )

            finally:
                _dkss_common.db.session.remove()

            time.sleep(60)

    except KeyboardInterrupt:
        print(
            "車両分析の自動更新を停止しました。",
            flush=True,
        )



def vehicle_karte_analysis_tick():
    """公開資料と登録内容の変更を確認し、予約済み分析を実行する。"""
    try:
        public_result = _dkss_runtime.app.extensions["dkss"]['public_knowledge_tick']()
        if public_result:
            print(public_result, flush=True)
    except Exception:
        _dkss_common.db.session.rollback()
        _dkss_runtime.app.logger.exception("公開整備資料の更新確認に失敗しました。")
    finally:
        _dkss_common.db.session.remove()

    targets = (
        _dkss_common.db.session.query(_dkss_models.Vehicle.id, _dkss_models.Vehicle.company_code)
        .join(
            _dkss_models.Company,
            _dkss_models.Company.company_code == _dkss_models.Vehicle.company_code,
        )
        .filter(
            _dkss_models.Vehicle.deleted.is_(False),
            _dkss_models.Company.active.is_(True),
        )
        .order_by(_dkss_models.Vehicle.id)
        .all()
    )

    scanned = 0
    scan_errors = 0

    for vehicle_id, company_code in targets:
        try:
            vehicle = _dkss_models.Vehicle.query.filter_by(
                id=vehicle_id,
                company_code=company_code,
                deleted=False,
            ).first()

            if vehicle is None:
                continue

            with _dkss_runtime.app.test_request_context("/"):
                payload, _ = get_vehicle_karte_analysis_job_data(vehicle)

            queue_vehicle_karte_analysis(vehicle, payload)
            _dkss_common.db.session.commit()
            scanned += 1

        except Exception:
            _dkss_common.db.session.rollback()
            scan_errors += 1
            _dkss_runtime.app.logger.exception(
                "車両分析の変更確認に失敗しました: vehicle_id=%s",
                vehicle_id,
            )

        finally:
            _dkss_common.db.session.remove()

    now = _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC"))
    due_ids = (
        _dkss_common.db.session.query(_dkss_models.VehicleKarteAnalysis.id)
        .join(
            _dkss_models.Vehicle,
            _dkss_common.db.and_(
                _dkss_models.Vehicle.id == _dkss_models.VehicleKarteAnalysis.vehicle_record_id,
                _dkss_models.Vehicle.company_code == _dkss_models.VehicleKarteAnalysis.company_code,
            ),
        )
        .join(
            _dkss_models.Company,
            _dkss_models.Company.company_code == _dkss_models.Vehicle.company_code,
        )
        .filter(
            _dkss_models.Vehicle.deleted.is_(False),
            _dkss_models.Company.active.is_(True),
            _dkss_models.VehicleKarteAnalysis.status.in_(
                {"pending", "error", "running"}
            ),
            _dkss_models.VehicleKarteAnalysis.next_analysis_at <= now,
            _dkss_common.db.or_(
                _dkss_models.VehicleKarteAnalysis.lease_expires_at.is_(None),
                _dkss_models.VehicleKarteAnalysis.lease_expires_at <= now,
            ),
        )
        .order_by(
            _dkss_models.VehicleKarteAnalysis.next_analysis_at,
            _dkss_models.VehicleKarteAnalysis.id,
        )
        .limit(20)
        .all()
    )
    _dkss_common.db.session.remove()

    completed = 0
    failed = 0

    for (state_id,) in due_ids:
        try:
            if run_vehicle_karte_analysis_job(state_id):
                completed += 1
            else:
                failed += 1

        except Exception:
            _dkss_common.db.session.rollback()
            failed += 1
            _dkss_runtime.app.logger.exception(
                "車両分析ジョブの実行に失敗しました: state_id=%s",
                state_id,
            )

        finally:
            _dkss_common.db.session.remove()

    print(
        f"変更確認: {scanned}台 / 確認エラー: {scan_errors}台 / "
        f"分析完了: {completed}台 / 未完了: {failed}台"
    )



def queue_vehicle_karte_analysis(vehicle, payload):
    """バックグラウンド処理用。コミットは呼出元が行う。"""
    repository = _dkss_common.VehicleAnalysisJobRepository(
        db=_dkss_common.db, state_model=_dkss_models.VehicleKarteAnalysis, vehicle_model=_dkss_models.Vehicle,
    )
    return _dkss_common.VehicleAnalysisQueueService(
        repository=repository, utc_now=lambda: _dkss_common.datetime.now(_dkss_common.ZoneInfo("UTC")),
        parse_result=_dkss_serialization.safe_json_dict,
    ).queue(vehicle, payload)



def get_vehicle_karte_analysis_fingerprints(
    vehicle, summary, records,
):
    def digest(value):
        text = _dkss_common.json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return _dkss_common.hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()

    important = []
    inspection_patterns = {}
    normal_patterns = {}
    deadlines = {}

    for record in records:
        if record["source_id"].startswith("inspection:"):
            pattern = {
                key: value
                for key, value in record.items()
                if key not in {"source_id", "date"}
            }
            signature = digest(pattern)

            if record.get("has_attention"):
                inspection_patterns[signature] = pattern
            else:
                normal_patterns[signature] = pattern
            continue

        important.append(record)

        if record["source_id"].startswith("periodic:"):
            category = record.get("category") or "other"
            if category not in deadlines:
                deadlines[category] = record.get(
                    "next_inspection_date"
                )

    important.extend(inspection_patterns.values())
    important.sort(key=digest)

    vehicle_context = {
        "model_code": vehicle.model_code,
            "engine_code": getattr(vehicle, "engine_code", None),
        "manufacturer": vehicle.manufacturer,
        "first_registration_date": (
            vehicle.first_registration_date
        ),
    }

    deadlines["vehicle_inspection"] = (
        vehicle.inspection_expiry
    )
    today = _dkss_common.datetime.now(
        _dkss_common.ZoneInfo("Asia/Tokyo")
    ).date()
    deadline_states = {}

    for key, value in deadlines.items():
        text = (
            str(value or "").strip()[:10]
            .replace("/", "-")
        )
        try:
            day = _dkss_common.datetime.strptime(
                text, "%Y-%m-%d"
            ).date()
        except ValueError:
            continue

        deadline_states[key] = {
            "date": day.isoformat(),
            "status": (
                "期限経過" if day < today
                else "期限当日" if day == today
                else "期限前"
            ),
        }

    return {
        # PREVENTIVE_BASELINE_GUIDANCE_V1
        "policy_version": 12,
        "important_hash": digest({
            "factual_history_policy": "explicit-synthetic-document-v1",
            "source_exclusions": summary.get("source_exclusions", []),
            "vehicle": vehicle_context,
            "records": important,
        }),
        "routine_hash": digest({
            "evaluation_date": today.isoformat(),
            "distance": summary["distance"],
            "current_mileage": summary["current_mileage"],
            "current_mileage_date": summary.get(
                "current_mileage_date"
            ),
            "mileage_reference": summary.get(
                "mileage_reference"
            ),
            "total_cost": summary["total_cost"],
            "failure_count": summary["failure_count"],
            "part_replacement_count": (
                summary["part_replacement_count"]
            ),
            "deadlines": deadline_states,
            "normal_checks": sorted(normal_patterns),
            "inspection_attention_count": sum(
                record["source_id"].startswith("inspection:")
                and bool(record.get("has_attention"))
                for record in records
            ),
        }),
        "has_important_history": bool(important),
    }



def build_vehicle_karte_service_progress(maintenance, summary):
    def day(value):
        try:
            return _dkss_common.datetime.strptime(
                str(value or "")[:10], "%Y-%m-%d"
            ).date()
        except ValueError:
            return None

    def meter(value):
        try:
            number = _dkss_common.Decimal(str(value))
            return number if number.is_finite() and number >= 0 else None
        except (_dkss_common.InvalidOperation, ValueError, TypeError):
            return None

    as_of = day(summary.get("end_date"))
    if as_of:
        as_of = min(
            as_of,
            _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).date(),
        )

    measured = day(summary.get("current_mileage_date"))
    current = meter(summary.get("current_mileage"))
    result = {
        "as_of": as_of,
        "last_date": None,
        "last_mileage": None,
        "measured_date": measured,
        "current_mileage": current,
        "distance_since": None,
        "days_since": None,
        "note": "比較できる整備記録がありません。",
    }

    maintenance, _, _ = filter_vehicle_maintenance_factual_history(maintenance)
    candidates = []
    unknown_date = False
    for record in maintenance:
        completed = str(record.completion_date or "").strip()
        if record.status != "完了" and not completed:
            continue

        recorded = day(completed or record.entry_date)
        if recorded is None:
            unknown_date = True
        elif as_of and recorded <= as_of:
            candidates.append((recorded, record.id or 0, record))

    if not candidates:
        return result

    last_date, _, record = max(
        candidates, key=lambda item: item[:2]
    )
    last = meter(record.mileage)
    result.update(
        last_date=last_date,
        last_mileage=last,
        days_since=(as_of - last_date).days,
        note="",
    )

    same_day = {
        meter(item.mileage)
        for date, _, item in candidates
        if date == last_date and meter(item.mileage) is not None
    }

    if unknown_date:
        result["note"] = (
            "日付不明の完了記録があり、"
            "直近の整備か確認が必要です。"
        )
    elif len(same_day) > 1:
        result["note"] = "同日の整備記録で走行距離が異なります。"
    elif current is None or last is None:
        result["note"] = "走行距離の記録が不足しています。"
    elif measured is None or measured < last_date or measured > as_of:
        result["note"] = "整備後のメーター記録を確認できません。"
    elif current < last:
        result["note"] = (
            "メーター値が整備時より小さいため確認が必要です。"
        )
    else:
        result["distance_since"] = current - last

    if not str(record.completion_date or "").strip() and not result["note"]:
        result["note"] = (
            "整備日は、完了日未入力のため入庫日を使用しています。"
        )

    return result



def build_vehicle_part_document_evidence(part, parent, source):
    """Trace a registered part to its unchanged, reviewed invoice line."""
    import unicodedata

    def norm(value):
        return _dkss_common.re.sub(r"[\s・･]+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()

    result = {
        "status": "untraced",
        "part_source_id": f"part:{part.id}",
        "maintenance_source_id": f"maintenance:{parent.id}",
    }
    if (
        part.company_code != parent.company_code
        or part.vehicle_record_id != parent.vehicle_record_id
        or part.maintenance_record_id != parent.id
    ):
        return {**result, "reason": "parent_scope_mismatch"}
    if source is None:
        return {**result, "reason": "source_line_link_not_available"}
    if (
        source.company_code != parent.company_code
        or source.maintenance_record_id != parent.id
        or source.replacement_id != part.id
    ):
        return {**result, "reason": "source_line_scope_mismatch"}
    try:
        lines = _dkss_common.json.loads(parent.line_items_json or "[]")
    except (ValueError, TypeError):
        return {**result, "reason": "source_lines_invalid"}
    if not isinstance(lines, list) or not all(isinstance(line, dict) for line in lines):
        return {**result, "reason": "source_lines_invalid"}
    index = source.source_line_index
    if type(index) is not int or not 0 <= index < len(lines):
        return {**result, "reason": "source_line_index_invalid"}
    line = lines[index]
    version = _dkss_common.hashlib.sha256(_dkss_common.json.dumps(
        line, sort_keys=True, ensure_ascii=False, default=str,
    ).encode("utf-8")).hexdigest()
    if source.source_line_version != version:
        return {**result, "reason": "source_line_changed"}
    if (
        line.get("replacement_action") != "replace"
        or norm(line.get("replacement_part_name")) != norm(part.part_name)
        or str(line.get("part_number") or "").strip() != str(part.part_number or "").strip()
    ):
        return {**result, "reason": "replacement_line_not_matched"}
    try:
        quantity = _dkss_common.Decimal(str(line.get("quantity")))
        saved_quantity = _dkss_common.Decimal(str(part.quantity))
        if not quantity.is_finite() or quantity <= 0 or quantity != saved_quantity:
            raise ValueError()
    except (ValueError, TypeError, _dkss_common.InvalidOperation):
        return {**result, "reason": "replacement_quantity_not_matched"}
    invoice_source = _dkss_serialization.safe_json_dict(parent.invoice_details_json).get("source")
    if not isinstance(invoice_source, dict):
        return {**result, "reason": "invoice_source_not_available"}
    sha256 = invoice_source.get("sha256")
    pages = invoice_source.get("pages")
    page = line.get("source_page")
    if (
        not isinstance(sha256, str) or _dkss_common.re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is None
        or not isinstance(pages, list) or not pages
        or any(type(value) is not int or value < 1 for value in pages)
        or type(page) is not int or page not in pages
        or not isinstance(invoice_source.get("draft_id"), str) or not invoice_source["draft_id"]
        or type(invoice_source.get("record_index")) is not int or invoice_source["record_index"] < 0
    ):
        return {**result, "reason": "invoice_source_metadata_invalid"}
    return {
        **result,
        "status": "verified_saved_source_line",
        "verification_scope": "Saved reviewed line, linked part and stored original reference; original bytes are not reread here.",
        "source_line_index": index,
        "source_line_version": version,
        "source_page": page,
        "document_source": {key: invoice_source.get(key) for key in (
            "draft_id", "record_index", "sha256", "pages", "filename",
        )},
        "reviewed_line": line,
        "component_inclusion_confirmed": False,
    }



def get_related_air_dryer_assembly_history(part_name, preventive_facts):
    """A named whole-assembly record is related history, never a component baseline."""
    import unicodedata

    def norm(value):
        return _dkss_common.re.sub(r"[\s・･]+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold().replace("フィルター", "フィルタ")

    target = norm(part_name)
    allowed_targets = {
        norm(root + suffix)
        for root in ("エアドライヤ", "エアドライヤー")
        for suffix in ("", "の乾燥剤", "のフィルタ", "のゴム部品")
    }
    if target not in allowed_targets or not isinstance(preventive_facts, dict):
        return []
    result = []
    for fact in preventive_facts.get("part_replacements", []):
        if not isinstance(fact, dict) or norm(fact.get("part_name")) not in {
            norm("エアドライヤASSY"), norm("エアドライヤーASSY"),
        }:
            continue
        source_ids = fact.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids or any(
            not isinstance(value, str) or _dkss_common.re.fullmatch(r"part:[0-9]+", value) is None for value in source_ids
        ):
            continue
        result.append({
            "assembly_part_name": fact["part_name"],
            "replacement_date": fact.get("latest_dated_replacement"),
            "replacement_mileage": fact.get("replacement_mileage"),
            "replacement_date_usable": fact.get("replacement_date_usable") is True,
            "source_ids": source_ids,
            "document_evidence": fact.get("latest_replacement_document_evidence", []),
            "relationship": "registered_whole_assembly_related_to_named_component",
            "component_inclusion_confirmed": False,
            "usable_as_component_baseline": False,
            "usable_as_inspection_baseline": False,
            "interpretation": (
                "本体ASSYの交換登録あり。構成部品の交換範囲・新品か再生品かは未確定。"
                "構成部品の交換日・点検日を本体交換日へ置き換えない。"
                "関連履歴がないとは案内しない。交換未実施・期限超過とも断定しない。"
            ),
        })
    return result



def periodic_inspection_synthetic_evidence(row):
    from types import SimpleNamespace
    details = _dkss_serialization.safe_json_dict(row.details_json)
    evidence = vehicle_maintenance_synthetic_evidence(SimpleNamespace(
        id=row.id, company_code=row.company_code, vehicle_record_id=row.vehicle_record_id,
        notes=details.get("notes"), invoice_details_json="{}",
    ))
    if evidence:
        evidence["source_id"] = f"periodic:{row.id}"
        evidence["evidence_field"] = "details_json.notes"
    return evidence



def assess_saved_inspection_item(item, legend):
    """Use this document's legend; never use a universal circle/cross convention."""
    import unicodedata
    def text(value):
        return unicodedata.normalize("NFKC", str(value or "")).strip()
    raw = text(item.get("raw_result"))
    if not raw:
        return {"status": "blank", "inspection_performed_confirmed": False}
    pairs = {}
    for entry in _dkss_common.re.split(r"[、,;；\n\r]+", text(legend)):
        parts = _dkss_common.re.split(r"[:：]", entry)
        if len(parts) != 2:
            continue
        left, right = (part.strip() for part in parts)
        for symbol, meaning in ((left, right), (right, left)):
            if len(symbol) == 1 and meaning:
                pairs.setdefault(symbol, set()).add(meaning)
    meanings = pairs.get(raw, set())
    if len(meanings) != 1:
        return {"status": "symbol_unresolved", "inspection_performed_confirmed": False}
    meaning = next(iter(meanings))
    labels = {
        "点検良好": "inspection_recorded", "点検済": "inspection_recorded",
        "点検済み": "inspection_recorded", "点検": "inspection_recorded",
        "異常なし": "inspection_recorded", "良好": "inspection_recorded",
        "該当なし": "not_applicable", "省略": "omitted",
        "交換": "recorded_work", "修理": "recorded_work", "調整": "recorded_work",
        "締付": "recorded_work", "清掃": "recorded_work", "給油(水)": "recorded_work",
        "特定整備": "recorded_work", "不良": "recorded_attention", "異常あり": "recorded_attention",
    }
    status = labels.get(meaning, "meaning_unresolved")
    # Combined cells and placement notes do not establish each sub-item's result.
    if status == "inspection_recorded" and (
        "/" in text(item.get("item_name"))
        or any(word in text(item.get("notes")) for word in ("空欄", "左欄", "右欄", "判読", "不明", "不確実"))
    ):
        status = "item_scope_unresolved"
    if status == "inspection_recorded" and any(
        word in text(item.get("result_text")) + text(item.get("notes"))
        for word in ("未実施", "未点検", "不良", "異常あり", "要修理", "判読不能")
    ):
        status = "conflicting_result_text"
    return {"status": status, "legend_meaning": meaning,
            "inspection_performed_confirmed": status == "inspection_recorded"}



def build_periodic_inspection_ai_details(row, draft):
    """Read confirmed item values plus original reference without changing the import."""
    from io import BytesIO
    from pypdf import PdfReader
    details = _dkss_serialization.safe_json_dict(row.details_json)
    items = details.get("inspection_items")
    valid_items = isinstance(items, list) and len(items) <= 1000 and all(isinstance(item, dict) for item in items)
    legend = details.get("symbol_legend")
    legend = legend if isinstance(legend, str) else ""
    warnings = details.get("warnings")
    warnings = warnings if isinstance(warnings, list) else []
    evidence = {"status": "untraced", "source_id": f"periodic:{row.id}",
                "reason": "original_reference_not_available"}
    pages = details.get("source_pages")
    if (
        draft is not None and draft.id == row.source_draft_id
        and draft.company_code == row.company_code and draft.document_type == "inspection"
        and type(row.source_record_index) is int and row.source_record_index >= 0
    ):
        original = draft.source_file
        checksum = draft.source_sha256
        preview = _dkss_serialization.safe_json_dict(draft.preview_json)
        original_records = preview.get("records")
        if not isinstance(original_records, list):
            original_records = preview.get("original_records")
        if (
            isinstance(original, bytes) and isinstance(checksum, str)
            and _dkss_common.re.fullmatch(r"[0-9a-f]{64}", checksum)
            and _dkss_common.hashlib.sha256(original).hexdigest() == checksum
            and isinstance(original_records, list) and row.source_record_index < len(original_records)
            and isinstance(pages, list) and pages
            and all(type(page) is int and page > 0 for page in pages)
        ):
            try:
                pdf = PdfReader(BytesIO(original), strict=False)
                count = len(pdf.pages)
                if pdf.is_encrypted or not 1 <= count <= 200 or max(pages) > count:
                    raise ValueError("invalid pages")
                evidence = {
                    "status": "verified_saved_original",
                    "source_id": f"periodic:{row.id}", "draft_id": draft.id,
                    "record_index": row.source_record_index, "sha256": checksum,
                    "filename": draft.source_filename, "source_pages": pages,
                    "original_page_count": count,
                    "verification_scope": "Saved original bytes/checksum, company, source record and physical pages; confirmed item values retained.",
                }
            except Exception:
                evidence["reason"] = "original_pdf_not_verified"
        else:
            evidence["reason"] = "original_checksum_or_record_scope_not_verified"
    date_values = [details.get(key) for key in ("inspection_date", "record_date") if details.get(key)]
    date_consistent = bool(date_values) and all(value == row.inspection_date for value in date_values)
    try:
        meter = _dkss_common.Decimal(str(row.mileage))
        saved_meter = _dkss_common.Decimal(str(details.get("mileage")))
        meter_consistent = meter.is_finite() and meter >= 0 and meter == saved_meter
    except (TypeError, ValueError, _dkss_common.InvalidOperation):
        meter_consistent = False
    source_items = []
    for index, item in enumerate(items if valid_items else []):
        page = item.get("source_page")
        assessment = assess_saved_inspection_item(item, legend)
        if type(page) is not int or not isinstance(pages, list) or page not in pages:
            assessment = {"status": "source_page_unresolved", "inspection_performed_confirmed": False}
        source_items.append({**item, "item_index": index, "execution_evidence": assessment})
    return {
        "inspection_items": source_items,
        "symbol_legend": legend,
        "inspection_warnings": warnings,
        "inspection_document_evidence": evidence,
        "inspection_date_consistent": date_consistent,
        "inspection_mileage_consistent": meter_consistent,
        "next_inspection_month": details.get("next_inspection_month"),
        "inspection_execution_note": "記号は当該原本の凡例で解釈。空欄は未記入。交換・修理記号から別途の点検完了や指摘解消を作らない。",
    }



def build_recorded_inspection_facts(summary, records):
    def day(value):
        try:
            return _dkss_common.datetime.strptime(value, "%Y-%m-%d").date() if isinstance(value, str) and len(value) == 10 else None
        except ValueError:
            return None
    def number(value):
        try:
            result = _dkss_common.Decimal(str(value))
            return result if not isinstance(value, bool) and result.is_finite() and result >= 0 else None
        except (ValueError, TypeError, _dkss_common.InvalidOperation):
            return None
    as_of = day(summary.get("end_date"))
    measured = day(summary.get("current_mileage_date"))
    current = number(summary.get("current_mileage"))
    facts = []
    for record in records:
        if not str(record.get("source_id") or "").startswith("periodic:"):
            continue
        document = record.get("inspection_document_evidence") or {}
        if document.get("status") != "verified_saved_original":
            continue
        performed = day(record.get("date"))
        meter = number(record.get("mileage"))
        for item in record.get("inspection_items", []):
            assessment = item.get("execution_evidence") or {}
            if assessment.get("inspection_performed_confirmed") is not True:
                continue
            distance = None
            if (
                record.get("inspection_mileage_consistent") is True and meter is not None
                and current is not None and measured and performed and as_of
                and performed <= measured <= as_of and current >= meter
                and (summary.get("mileage_reference") or {}).get("distance_usable") is True
            ):
                distance = current - meter
            facts.append({
                "item_name": item.get("item_name"), "category": item.get("category"),
                "inspection_item_index": item.get("item_index"),
                "inspection_date": record.get("date"),
                "inspection_date_usable": bool(record.get("inspection_date_consistent") is True and performed and as_of and performed <= as_of),
                "inspection_mileage": meter,
                "inspection_mileage_usable": distance is not None,
                "distance_since_km": distance,
                "source_ids": [record["source_id"]], "source_page": item.get("source_page"),
                "raw_result": item.get("raw_result"), "legend_meaning": assessment.get("legend_meaning"),
                "document_evidence": document,
                "scope_note": "原本・当該項目から確認できる点検登録。交換・指摘解消・車両全体の安全性とは別。未登録実施の有無は不明。",
            })
    return facts



def inspection_procedure_matches(rule, part_name, fact):
    """Match the inspection procedure, not merely a shared device name."""
    import unicodedata
    def norm(value):
        value = unicodedata.normalize("NFKC", str(value or ""))
        return _dkss_common.re.sub(r"[\s・･☆★◎]+", "", value).casefold().replace("エアドライヤー", "エアドライヤ")
    target = norm(part_name)
    item = norm(fact.get("item_name"))
    quote = norm(rule.get("source_quote"))
    if not target or not item or not quote or "/" in item:
        return False
    if target == "エアドライヤ":
        return all(word in quote and word in item for word in ("エアドライヤ", "水", "量", "状態")) and any(
            word in item and word in quote for word in ("排出", "排水")
        )
    return target in item and len(item) >= len(target) + 4 and item in quote



def calculate_adopted_inspection_rule_timing(rule, part_name, preventive_facts, summary):
    service = AdoptedMaintenanceTimingService(
        procedure_matches=inspection_procedure_matches,
        related_assembly_history=get_related_air_dryer_assembly_history,
    )
    return service.inspection(rule, part_name, preventive_facts, summary)



def calculate_adopted_maintenance_rule_timing(rule, part_name, preventive_facts, summary):
    service = AdoptedMaintenanceTimingService(
        procedure_matches=inspection_procedure_matches,
        related_assembly_history=get_related_air_dryer_assembly_history,
    )
    return service.replacement(rule, part_name, preventive_facts, summary)



def build_vehicle_karte_preventive_facts(vehicle, summary, records):
    """交換後の期間・距離を計算する。交換期限や故障時期は推定しない。"""
    import unicodedata
    day = _dkss_common.parse_record_date

    def meter(value):
        try:
            number = _dkss_common.Decimal(str(value))
            return (
                number
                if number.is_finite() and number >= 0
                else None
            )
        except (_dkss_common.InvalidOperation, ValueError, TypeError):
            return None

    as_of = day(summary.get("end_date"))
    current = meter(summary.get("current_mileage"))
    measured_on = day(summary.get("current_mileage_date"))
    groups = {}

    for record in records:
        if not record["source_id"].startswith("part:"):
            continue

        completed_on = day(record.get("completion_date"))
        if record.get("status") != "完了" and completed_on is None:
            continue
        if completed_on and as_of and completed_on > as_of:
            continue

        name = str(record.get("content") or "").strip()
        number = str(record.get("part_number") or "").strip()
        if name:
            normalized_name = _dkss_common.re.sub(
                r"[\s・･]+", "",
                unicodedata.normalize("NFKC", name).casefold(),
            ).replace("フィルター", "フィルタ")
            groups.setdefault((normalized_name, number), []).append(record)

    facts = []

    for (name, number), rows in sorted(groups.items()):
        dated = [
            row for row in rows
            if day(row.get("date"))
        ]
        dated = [
            row for row in dated
            if not as_of or day(row["date"]) <= as_of
        ]
        if not dated:
            continue

        latest_day = max(day(row["date"]) for row in dated)
        latest = [
            row for row in dated
            if day(row["date"]) == latest_day
        ]
        distances = {
            meter(row.get("mileage"))
            for row in latest
        }
        replaced_meter = (
            next(iter(distances))
            if len(distances) == 1
            else None
        )
        notes = []

        if len(dated) != len(rows):
            notes.append(
                "日付不明などの交換記録があり、最新の交換かは要確認。"
            )
        if len(distances) > 1:
            notes.append(
                "同日の交換時走行距離が一致していません。"
            )

        distance = None
        if current is not None and replaced_meter is not None:
            if measured_on is None or measured_on < latest_day:
                notes.append(
                    "交換後の現在走行距離を確認できません。"
                )
            elif current < replaced_meter:
                notes.append(
                    "現在走行距離が交換時より小さいため距離を計算していません。"
                )
            else:
                distance = current - replaced_meter
        else:
            notes.append("走行距離の記録が不足しています。")

        previous_days = [
            day(row["date"]) for row in dated
            if day(row["date"]) < latest_day
        ]
        previous_day = max(previous_days) if previous_days else None
        previous = [
            row for row in dated
            if previous_day and day(row["date"]) == previous_day
        ]
        previous_meters = {
            meter(row.get("mileage")) for row in previous
        }
        previous_meter = (
            next(iter(previous_meters))
            if len(previous_meters) == 1 else None
        )
        interval_km = None
        if previous_meter is not None and replaced_meter is not None:
            if replaced_meter >= previous_meter:
                interval_km = replaced_meter - previous_meter
            else:
                notes.append(
                    "交換時走行距離が前回より小さいため交換間隔の距離を計算していません。"
                )

        facts.append({
            "part_name": str(latest[0].get("content") or name).strip(),
            "recorded_names": sorted({
                str(row.get("content") or "").strip() for row in rows
            }),
            "part_number": number,
            "latest_dated_replacement": latest_day.isoformat(),
            "replacement_date_usable": bool(
                as_of and len(dated) == len(rows)
            ),
            "replacement_mileage": replaced_meter,
            "replacement_mileage_usable": bool(
                as_of
                and len(dated) == len(rows)
                and replaced_meter is not None
                and (
                    previous_meter is None
                    or replaced_meter >= previous_meter
                )
            ),
            "days_since": (
                (as_of - latest_day).days if as_of else None
            ),
            "distance_since_km": distance,
            "previous_dated_replacement": (
                previous_day.isoformat() if previous_day else None
            ),
            "last_recorded_interval_days": (
                (latest_day - previous_day).days
                if previous_day else None
            ),
            "last_recorded_interval_km": interval_km,
            "interval_scope_note": (
                "登録された前回と直近の交換記録間の実績。"
                "途中の未登録作業の有無は不明。"
                "推奨交換間隔・交換期限・不具合の再発を意味しない。"
            ),
            "source_ids": list(dict.fromkeys(
                row["source_id"] for row in latest + previous
            )),
            "latest_replacement_document_evidence": [
                row["replacement_document_evidence"] for row in latest
                if isinstance(row.get("replacement_document_evidence"), dict)
            ],
            "notes": notes,
        })

    registered = str(
        vehicle.first_registration_date or ""
    ).strip()
    matched = _dkss_common.re.match(
        r"^(\d{4})[-/年](\d{1,2})(?:月|[-/]|$)",
        registered,
    )
    age_months = None

    if matched and as_of:
        year, month = map(int, matched.groups())
        if 1 <= year <= 9999 and 1 <= month <= 12:
            months = (
                (as_of.year - year) * 12
                + as_of.month - month
            )
            if months >= 0:
                age_months = months

    return {
        "as_of": summary.get("end_date"),
        "vehicle_age_months": age_months,
        "current_mileage_date": summary.get(
            "current_mileage_date"
        ),
        "inspection_items": build_recorded_inspection_facts(summary, records),
        "part_replacements": facts,
        "note": (
            "名称・品番が一致する登録記録を集計。"
            "交換記録がないことは未交換を意味しない。"
            "距離・期間は交換期限や故障予測ではない。"
        ),
    }



def build_vehicle_karte_analysis_payload(vehicle, summary, comparison, maintenance, parts, defects):
    maintenance, parts = (list(maintenance), list(parts))
    original_source_ids = {f'maintenance:{row.id}' for row in maintenance} | {f'part:{row.id}' for row in parts}
    maintenance, parts, synthetic_exclusions = filter_vehicle_maintenance_factual_history(maintenance, parts)
    source_exclusions = {(item['company_code'], item['vehicle_record_id'], item['source_id']): item for item in list(summary.get('source_exclusions', [])) + synthetic_exclusions}
    excluded_source_ids = original_source_ids - ({f'maintenance:{row.id}' for row in maintenance} | {f'part:{row.id}' for row in parts})
    excluded_source_ids.update((item['source_id'] for item in source_exclusions.values()))
    allowed_maintenance_ids = {row.id for row in maintenance}
    records = []
    sources = {}
    inspection_links = _dkss_models.VehicleMaintenanceInspectionLink.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).order_by(_dkss_models.VehicleMaintenanceInspectionLink.maintenance_record_id, _dkss_models.VehicleMaintenanceInspectionLink.inspection_result_id, _dkss_models.VehicleMaintenanceInspectionLink.defect_no).all()
    links_by_maintenance = {}
    links_by_defect = {}
    for link in inspection_links:
        if link.maintenance_record_id not in allowed_maintenance_ids:
            continue
        links_by_maintenance.setdefault(link.maintenance_record_id, []).append({'source_id': f'inspection:{link.inspection_result_id}', 'defect_no': link.defect_no})
        links_by_defect.setdefault((link.inspection_result_id, link.defect_no), []).append(f'maintenance:{link.maintenance_record_id}')

    def short(value, limit=400):
        return str(value or '').strip()[:limit]

    def add(kind, row, date_value, values, link):
        date_text = short(date_value, 10)
        if date_text:
            try:
                date_value = _dkss_common.datetime.strptime(date_text, '%Y-%m-%d').date()
            except ValueError:
                date_text = ''
            else:
                if date_value.isoformat() > summary['end_date']:
                    return
        source_id = f'{kind}:{row.id}'
        records.append({'source_id': source_id, 'date': date_text or None, **values})
        sources[source_id] = {'label': f"{date_text or '日付未登録'} {values['type']}：{short(values.get('content'), 80)}", 'url': link}
        if kind in {'part', 'periodic'}:
            sources[source_id]['snapshot'] = records[-1]
    from driving_report_data import payload as driving_payload, match_report as match_driving_report, identity as driving_identity
    driving_seen = set()
    driving_operations = _dkss_models.VehicleOperationRecord.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).all()
    for report in _dkss_models.VehicleDrivingReportRecord.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).all():
        data = driving_payload(report)
        if data.get('lifecycle') in {'cancelled', 'superseded'} or not report.operation_date or report.operation_date > summary['end_date']:
            continue
        key = driving_identity(report)
        if key in driving_seen:
            continue
        driving_seen.add(key)
        match = match_driving_report(report, driving_operations)
        add('driving_report', report, report.operation_date, {'type': '安全運転日報', 'content': report.content or '日報', 'record_scope': data.get('report_scope') or 'trip', 'source_system': data.get('source_system'), 'definition_version': data.get('definition_version'), 'confirmation': data.get('import_confirmation'), 'source_pages': data.get('source_pages', []), 'operation_reconciliation': match['status'], 'distance': data.get('distance'), 'mileage': data.get('mileage'), 'usage': {k: data.get(k) for k in ('driving_time', 'handling_time', 'idle_time', 'rest_time', 'work_time', 'fuel_consumption', 'fuel_unit', 'fuel_economy', 'fuel_economy_unit')}, 'report_items': data.get('report_items', []), 'events': data.get('events', []), 'duties': data.get('duties', []), 'extra_items': data.get('extra_items', []), 'comments': {k: data.get(k) for k in ('driver_comment', 'manager_comment', 'notes')}, 'review': data.get('review'), 'evidence_scope': '原本の記載と人の確認。事故確率・故障原因・過失・運行可否の確定ではない。定義・単位・版が不明な指標は比較不能。CSVとの未解決の値は距離計算に使わない。'}, _dkss_common.url_for('driving_report_detail', record_id=report.id))
    for row in maintenance:
        invoice_details = _dkss_serialization.safe_json_dict(row.invoice_details_json)
        invoice_attachment = {}
        invoice_text = {name: value.strip() if isinstance(value, str) else '' for name, value in (('content', invoice_details.get('attached_invoice_content')), ('notes', invoice_details.get('attached_invoice_notes')))}
        if isinstance(invoice_details.get('source'), dict) and any(invoice_text.values()):
            invoice_attachment['attached_invoice'] = {**invoice_text, 'source': {key: invoice_details['source'].get(key) for key in ('sha256', 'pages', 'record_index')}, 'evidence_scope': 'Confirmed invoice text attached to this maintenance record. It does not independently confirm repair completion or inspection defect resolution.'}
        add('maintenance', row, row.entry_date or row.completion_date, {**invoice_attachment, 'inspection_links': links_by_maintenance.get(row.id, []), 'type': '整備・修理', 'category': short(row.category), 'content': str(row.content or '').strip(), 'symptom': str(row.symptom or '').strip(), 'cause': str(row.cause or '').strip(), 'temporary_action': str(row.temporary_action or '').strip(), 'repair_content': str(row.repair_content or '').strip(), 'notes': str(row.notes or '').strip(), 'line_items': _dkss_serialization.safe_json_dict_list(row.line_items_json), 'status': short(row.status), 'completion_date': row.completion_date, 'mileage': row.mileage, 'total_cost': row.total_cost}, _dkss_common.url_for('vehicle_karte_maintenance', vehicle_record_id=vehicle.id, record_id=row.id))
    maintenance_map = {row.id: row for row in maintenance}
    part_source_rows = _dkss_models.VehiclePartReplacementSource.query.filter_by(company_code=vehicle.company_code).filter(_dkss_models.VehiclePartReplacementSource.maintenance_record_id.in_(list(maintenance_map))).all() if maintenance_map else []
    part_source_map = {row.replacement_id: row for row in part_source_rows}
    for row in parts:
        parent = maintenance_map.get(row.maintenance_record_id)
        if parent is None:
            continue
        add('part', row, row.replacement_date, {'replacement_document_evidence': build_vehicle_part_document_evidence(row, parent, part_source_map.get(row.id)), 'type': '部品交換', 'content': short(row.part_name), 'part_number': short(row.part_number), 'mileage': row.mileage, 'quantity': row.quantity, 'notes': short(row.notes), 'status': short(parent.status), 'completion_date': parent.completion_date}, _dkss_common.url_for('vehicle_karte_maintenance', vehicle_record_id=vehicle.id, record_id=parent.id))
    for row in defects:
        add('defect', row, row.occurred_date, {'type': '故障・不具合', 'category': short(row.category), 'content': short(row.content), 'priority': short(row.priority), 'cause': short(row.cause), 'repair_content': short(row.repair_content), 'status': short(row.status), 'repair_date': row.repair_date}, _dkss_common.url_for('vehicle_patrol_detail', index=row.id))
    inspections = _dkss_models.VehicleChecklistResult.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).filter(_dkss_models.VehicleChecklistResult.status.in_({'承認待ち', '承認済み', '点検完了'})).all()

    def inspection_date(row):
        text = f'{row.year}-{str(row.month).zfill(2)}-{str(row.day).zfill(2)}'
        try:
            return _dkss_common.datetime.strptime(text, '%Y-%m-%d').date().isoformat()
        except ValueError:
            return ''
    inspections.sort(key=lambda row: (inspection_date(row), row.id), reverse=True)
    latest_checklists = set()
    for row in inspections:
        date_text = inspection_date(row)
        if date_text and date_text > summary['end_date']:
            continue
        answers = _dkss_serialization.safe_json_dict_list(row.answers_json)
        snapshot = _dkss_serialization.safe_json_dict(row.checklist_snapshot_json)
        judgment = _dkss_serialization.safe_json_dict(row.operation_judgment_json)
        findings = [{'item_no': answer.get('item_no'), 'content': short(answer.get('content')), 'value': short(answer.get('value'), 50), 'comment': short(answer.get('comment'))} for answer in answers if str(answer.get('value') or '').strip() == '×' or str(answer.get('comment') or '').strip()]
        attention = bool(findings) or judgment.get('status') in {'運行不可', '判定保留'}
        if not attention and row.checklist_id in latest_checklists:
            continue
        latest_checklists.add(row.checklist_id)
        treatments = []
        stored_defects = judgment.get('defects') or []
        for defect in stored_defects if isinstance(stored_defects, list) else []:
            if not isinstance(defect, dict):
                continue
            repair = defect.get('repair') or {}
            if not isinstance(repair, dict):
                repair = {}
            treatments.append({'defect_no': defect.get('defect_no'), 'maintenance_source_ids': links_by_defect.get((row.id, defect.get('defect_no')), []), 'recheck_result': short((defect.get('recheck') or {}).get('result')), 'recheck_date': short((defect.get('recheck') or {}).get('performed_at'), 30), 'recheck_note': str((defect.get('recheck') or {}).get('note') or '').strip(), 'item_no': defect.get('item_no'), 'status': short(defect.get('status')), 'repair_note': short(repair.get('note')), 'repair_date': short(repair.get('performed_at'), 30)})
        add('inspection', row, date_text, {'type': '日常点検・車両チェックリスト', 'content': short(snapshot.get('name') or '点検結果'), 'status': short(row.status), 'has_attention': attention, 'answer_count': len(answers), 'failure_count': sum((str(answer.get('value') or '').strip() == '×' for answer in answers)), 'finding_count': len(findings), 'findings': findings, 'treatments': treatments, 'registered_operation_judgment': short(judgment.get('status')), 'judgment_reason': short(judgment.get('reason'))}, _dkss_common.url_for('vehicle_checklist_results', index=row.checklist_id, vehicle_record_id=vehicle.id, year=row.year, month=row.month, active_day=row.day))
    periodic = _dkss_models.VehiclePeriodicInspectionRecord.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).all()
    for row in periodic:
        excluded_inspection = periodic_inspection_synthetic_evidence(row)
        if excluded_inspection:
            source_exclusions[row.company_code, row.vehicle_record_id, excluded_inspection['source_id']] = excluded_inspection
            continue
        original_draft = _dkss_models.VehicleDocumentImportDraft.query.filter_by(id=row.source_draft_id, company_code=vehicle.company_code, document_type='inspection').first()
        inspection_details = build_periodic_inspection_ai_details(row, original_draft)
        add('periodic', row, row.inspection_date, {**inspection_details, 'type': '定期点検', 'category': short(row.inspection_type), 'content': short(row.content, 2000), 'notes': short(_dkss_serialization.safe_json_dict(row.details_json).get('notes'), 2000), 'mileage': row.mileage, 'completion_date': row.completion_date, 'next_inspection_date': row.next_inspection_date}, _dkss_common.url_for('vehicle_karte_inspections', vehicle_record_id=vehicle.id))
    records.sort(key=lambda item: (item['date'] or '', item['source_id']), reverse=True)
    fingerprints = get_vehicle_karte_analysis_fingerprints(vehicle, summary, records)
    fingerprints['routine_hash'] = _dkss_common.hashlib.sha256(_dkss_common.json.dumps({'vehicle': fingerprints['routine_hash'], 'comparison': comparison}, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()
    preventive_facts = build_vehicle_karte_preventive_facts(vehicle, summary, records)
    fact_source_ids = {source_id for fact in preventive_facts['part_replacements'] for source_id in fact['source_ids']}
    fact_source_ids.update((ident for fact in preventive_facts.get('inspection_items', []) for ident in fact['source_ids']))
    available_count = len(records)
    latest_parts = {}
    for item in records:
        if not item['source_id'].startswith('part:') or not item.get('date'):
            continue
        if item.get('status') != '完了' and (not item.get('completion_date')):
            continue
        key = (item.get('content'), item.get('part_number'))
        latest_parts.setdefault(key, item['date'])

    def important_for_analysis(item):
        source_id = item['source_id']
        if source_id.startswith('maintenance:'):
            return True
        if source_id.startswith('defect:'):
            return item.get('status') in {'未対応', '対応中'}
        if source_id.startswith('inspection:'):
            return bool(item.get('has_attention'))
        if source_id.startswith('periodic:'):
            return bool(item.get('content') or item.get('notes') or item.get('inspection_items'))
        if source_id.startswith('part:'):
            key = (item.get('content'), item.get('part_number'))
            return bool(item.get('date')) and item['date'] == latest_parts.get(key) and (item.get('status') == '完了' or bool(item.get('completion_date')))
        return False
    protected_records = []
    other_records = []
    for item in records:
        if important_for_analysis(item):
            protected_records.append(item)
        else:
            other_records.append(item)
    protected_count = len(protected_records)
    records = protected_records + other_records[:max(0, 80 - protected_count)]
    selected_ids = {item['source_id'] for item in records}
    evidence_ids = selected_ids | fact_source_ids
    sources = {key: value for key, value in sources.items() if key in evidence_ids}
    payload = {'vehicle': {'model_code': vehicle.model_code, 'engine_code': getattr(vehicle, 'engine_code', None), 'manufacturer': vehicle.manufacturer, 'first_registration_date': vehicle.first_registration_date, 'body_type': vehicle.body_type or None, 'registered_type': vehicle.type or None, 'gross_vehicle_weight_kg': vehicle.gross_vehicle_weight, 'max_payload_kg': vehicle.max_payload, 'attribute_scope_note': '登録済みの車両台帳情報。空欄は不明。初度登録日は製造年月ではない。車体形状・登録区分・重量だけで商品系列、エンジン、変速機、締結方式、装備、実際の使用条件を確定しない。'}, 'source_exclusions': list(source_exclusions.values()), 'summary': summary, 'comparison': comparison, 'preventive_facts': preventive_facts, 'records': records, '_fingerprints': fingerprints, 'coverage': {'available_count': available_count, 'sent_count': len(records), 'protected_count': protected_count, 'omitted_count': available_count - len(records), 'description': '対象は期間終了日以前の履歴。重要履歴は80件の枠で切り捨てず保持。通常履歴は合計80件までの残り枠へ追加。部品別の交換後距離・期間は履歴選択前に計算。計算に使った交換記録の参照先も保持。未対応不具合・点検指摘・定期点検内容・部品別の直近交換記録を優先。同じ優先区分では新しい順。日付不明は末尾。日常点検の指摘・対応は件数で切り捨てず保持。定期点検の内容・備考は各2000文字、整備・修理の内容・症状・原因・応急処置・修理内容・備考と登録明細は文字数で省略しない。整備・修理以外のその他の自由記述は最大400文字。'}, 'status_note': '状態・修理内容は現在の登録内容。指定期間終了時点の状態を復元したものではありません。'}
    knowledge, knowledge_sources, knowledge_count = _dkss_knowledge.get_vehicle_maintenance_knowledge(vehicle, records=records)
    import copy
    rule_timing_fingerprint = []
    for knowledge_item in knowledge:
        evidence = knowledge_item.get('maintenance_rule_evidence') or {}
        for rule in evidence.get('rules', []):
            adoption = rule.get('analysis_adoption') or {}
            if adoption.get('status') != 'adopted_for_analysis':
                continue
            timing = calculate_adopted_maintenance_rule_timing(rule, knowledge_item.get('part_name'), preventive_facts, summary)
            rule['timing_facts'] = timing
            adoption['calculation_permitted'] = timing['calculation_permitted']
            adoption['calculation_status'] = 'evaluated' if timing['calculation_permitted'] else 'held'
            rule_timing_fingerprint.append({'rule_key': adoption.get('rule_key'), 'timing_facts': timing})
        source_id = knowledge_item['source_id']
        if source_id in knowledge_sources:
            knowledge_sources[source_id]['snapshot'] = knowledge_item
    knowledge_for_fingerprint = copy.deepcopy(knowledge)
    for knowledge_item in knowledge_for_fingerprint:
        evidence = knowledge_item.get('maintenance_rule_evidence') or {}
        for rule in evidence.get('rules', []):
            rule.pop('timing_facts', None)
            adoption = rule.get('analysis_adoption')
            if isinstance(adoption, dict):
                adoption.pop('calculation_permitted', None)
                adoption.pop('calculation_status', None)
    fingerprints['routine_hash'] = _dkss_common.hashlib.sha256(_dkss_common.json.dumps({'history': fingerprints['routine_hash'], 'maintenance_rule_timing': rule_timing_fingerprint}, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()
    payload['maintenance_knowledge'] = knowledge
    payload['knowledge_coverage'] = {'matching_count': knowledge_count, 'sent_count': len(knowledge), 'description': '利用中・有効期間内でメーカー・型式が一致する知識。指摘・部品・整備記録との文字列関連性、メーカー・型式の限定、登録順で最大20件。資料の発行順ではない。適用条件の成立は別途確認。'}
    sources.update(knowledge_sources)
    if knowledge:
        source_id = f'vehicle:{vehicle.id}'
        payload['vehicle_source'] = {'source_id': source_id, **payload['vehicle'], 'current_mileage': summary['current_mileage'], 'current_mileage_date': summary.get('current_mileage_date'), 'mileage_reference': summary.get('mileage_reference')}
        sources[source_id] = {'label': '車両台帳・登録済み走行距離', 'url': _dkss_common.url_for('vehicle_karte', vehicle_record_id=vehicle.id)}

    def feedback_uses_excluded_history(row):
        snapshot = _dkss_serialization.safe_json_dict(row.snapshot_json)
        proposal = snapshot.get('proposal') or {}
        linked = snapshot.get('maintenance_record') or {}
        references = proposal.get('source_ids') or []
        return any((value in excluded_source_ids for value in references if isinstance(value, str))) or (isinstance(linked, dict) and f"maintenance:{linked.get('id')}" in excluded_source_ids)
    feedback_context = []
    for row in _dkss_analysis_feedback.latest_vehicle_analysis_feedback(vehicle.company_code, vehicle.id)[:20]:
        if feedback_uses_excluded_history(row):
            continue
        previous = _dkss_serialization.safe_json_dict(row.snapshot_json).get('proposal') or {}
        feedback_context.append({'proposal_id': row.proposal_key, 'target': previous.get('target') or previous.get('title'), 'action': previous.get('action'), 'source_ids': previous.get('source_ids', []), 'status': row.status, 'comment': row.comment[:1000], 'maintenance_record': _dkss_serialization.safe_json_dict(row.snapshot_json).get('maintenance_record'), 'by': row.created_by, 'at': row.created_at})
    evaluation_labels = {'appropriate': '適切', 'needs_revision': '要修正', 'uncertain': '判断保留'}
    for row in _dkss_analysis_feedback.latest_vehicle_analysis_evaluations(vehicle.company_code, vehicle.id)[:10]:
        if feedback_uses_excluded_history(row):
            continue
        previous = _dkss_serialization.safe_json_dict(row.snapshot_json).get('proposal') or {}
        feedback_context.append({'type': '人による提案内容の評価。実整備結果・確定診断とは別。', 'proposal_id': row.proposal_key, 'proposal_revision': row.proposal_revision, 'target': previous.get('target') or previous.get('title'), 'action': previous.get('action'), 'source_ids': previous.get('source_ids', []), 'evaluation': evaluation_labels.get(row.verdict, row.verdict), 'comment': row.comment[:1000], 'by': row.created_by, 'at': row.created_at})
    payload['feedback_context'] = feedback_context
    fingerprints['important_hash'] = _dkss_common.hashlib.sha256(_dkss_common.json.dumps({'history': fingerprints['important_hash'], 'knowledge': knowledge_for_fingerprint, 'feedback': feedback_context}, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()
    fingerprints['has_important_history'] = fingerprints['has_important_history'] or bool(knowledge) or bool(feedback_context)
    return (payload, sources)



def get_vehicle_karte_peer_comparison(vehicle, summary, registration_scope='auto', include_inactive=False):
    model = (vehicle.model_code or '').strip().upper()
    registration = str(vehicle.first_registration_date or '').strip()
    year_match = _dkss_common.re.match('^((?:19|20)\\d{2})(?:[-/年]|$)', registration)
    result = {'vehicle_count': None, 'metrics': [], 'part_statistics': [], 'note': ''}
    requested_scope = registration_scope
    if registration_scope == 'auto':
        registration_scope = 'same_year' if year_match else 'all_years'
    if registration_scope not in {'same_year', 'all_years'}:
        registration_scope = 'same_year'
    include_inactive = include_inactive is True
    result['registration_scope'] = registration_scope
    result['include_inactive'] = include_inactive
    result['comparison_scope'] = {'status': 'available', 'model_code': model or None, 'registration_scope': registration_scope, 'requested_registration_scope': requested_scope, 'year_scope_fallback': requested_scope == 'auto' and (not bool(year_match)), 'reference_registration_year': int(year_match.group(1)) if year_match else None, 'registration_year_basis': '初度登録年。製造年月ではありません。', 'include_inactive': include_inactive, 'start_date': summary.get('start_date'), 'end_date': summary.get('end_date'), 'same_company_only': True, 'target_vehicle_excluded': True, 'cohort_vehicle_ids': [], 'active_vehicle_count': None, 'inactive_vehicle_count': None, 'status_unknown_vehicle_count': None, 'data_scope_note': '登録済み記録に基づく比較。比較台数と各指標のsample_countは異なります。未登録を未交換・故障なしと扱いません。'}
    if not model:
        result['comparison_scope']['status'] = 'missing_model'
        result['note'] = '型式が未登録のため比較できません。'
        return result
    if registration_scope == 'same_year' and (not year_match):
        result['comparison_scope']['status'] = 'missing_registration_year'
        result['note'] = '同じ初度登録年で比較する条件ですが、対象車両の初度登録年が不明なため比較できません。比較対象0台という意味ではありません。画面では「初度登録年を限定しない」で別条件の比較ができます。画面の条件変更だけでは保存済み自動AIの条件は変わりません。'
        return result
    year = year_match.group(1) if year_match else None
    peers = [row for row in _dkss_models.Vehicle.query.filter_by(company_code=vehicle.company_code).all() if row.id != vehicle.id and (include_inactive or row.deleted is False) and ((row.model_code or '').strip().upper() == model) and (registration_scope == 'all_years' or _dkss_common.re.match('^' + year + '(?:[-/年]|$)', str(row.first_registration_date or '').strip()))]
    year_note = f'同じ初度登録年（{year}年）' if registration_scope == 'same_year' else '初度登録年を限定しない'
    active_note = '無効車両を含む' if include_inactive else '有効車両のみ'
    result['note'] = ('初度登録年が不明のため、年を限定せず同型式で比較。' if requested_scope == 'auto' and (not year_match) else '') + f'同じ会社・同型式・{year_note}・{active_note}。対象車両は平均から除外。'
    result['vehicle_count'] = len(peers)
    result['comparison_scope'].update({'status': 'available' if peers else 'no_peers', 'cohort_vehicle_ids': sorted((row.id for row in peers)), 'active_vehicle_count': sum((row.deleted is False for row in peers)), 'inactive_vehicle_count': sum((row.deleted is True for row in peers)), 'status_unknown_vehicle_count': sum((row.deleted is not False and row.deleted is not True for row in peers))})
    if not peers:
        result['note'] += ' 比較対象車両がありません。'
        return result
    grouped = {row.id: {'maintenance': [], 'operations': [], 'parts': [], 'defects': []} for row in peers}
    ids = list(grouped)
    for record_class, key in ((_dkss_models.VehicleMaintenanceRecord, 'maintenance'), (_dkss_models.VehicleOperationRecord, 'operations'), (_dkss_models.VehiclePartReplacement, 'parts'), (_dkss_models.VehiclePatrol, 'defects')):
        records = record_class.query.filter_by(company_code=vehicle.company_code).filter(record_class.vehicle_record_id.in_(ids)).all()
        for record in records:
            grouped[record.vehicle_record_id][key].append(record)
    peer_driving_reports = _dkss_models.VehicleDrivingReportRecord.query.filter_by(company_code=vehicle.company_code).filter(_dkss_models.VehicleDrivingReportRecord.vehicle_record_id.in_(ids)).all()
    from driving_report_data import canonical_operations
    for peer_id, values in grouped.items():
        values['operations'] = canonical_operations(values['operations'], [r for r in peer_driving_reports if r.vehicle_record_id == peer_id])
    for values in grouped.values():
        values['maintenance'], values['parts'], values['source_exclusions'] = filter_vehicle_maintenance_factual_history(values['maintenance'], values['parts'])
    result['source_exclusions'] = [item for values in grouped.values() for item in values['source_exclusions']]
    import unicodedata
    part_events = {}
    part_names = {}
    for peer_id, values in grouped.items():
        parents = {row.id: row for row in values['maintenance']}
        for part in values['parts']:
            parent = parents.get(part.maintenance_record_id)
            if parent is None or parent.vehicle_record_id != peer_id:
                continue
            try:
                replaced_on = _dkss_common.datetime.strptime(str(part.replacement_date or '')[:10], '%Y-%m-%d').date().isoformat()
            except ValueError:
                continue
            if not summary['start_date'] <= replaced_on <= summary['end_date']:
                continue
            name = str(part.part_name or '').strip()
            if not name:
                continue
            normalized_name = _dkss_common.re.sub('[\\s・･]+', '', unicodedata.normalize('NFKC', name).casefold()).replace('フィルター', 'フィルタ')
            number = str(part.part_number or '').strip()
            key = (normalized_name, number)
            part_names.setdefault(key, set()).add(name)
            part_events.setdefault(key, set()).add((peer_id, parent.id))
    result['part_statistics'] = [{'part_name': sorted(part_names[key])[0], 'recorded_names': sorted(part_names[key]), 'part_number': key[1], 'registered_event_count': len(events), 'vehicles_with_registered_events': len({peer_id for peer_id, _ in events})} for key, events in sorted(part_events.items(), key=lambda item: (-len(item[1]), item[0]))]
    result['part_statistics_note'] = '比較条件・指定期間内の部品交換登録を名称・品番別に集計。同一車両・同一整備記録・同一部品は1件。対象車両自身は含まない。未登録車両を未交換と扱わない。登録内容の真偽・作業完了・故障原因はこの集計では判定しない。件数の多さだけで故障多発や交換時期を判断しない。'
    from statistics import median
    interval_samples = {}
    for peer in peers:
        values = grouped[peer.id]
        parents = {row.id: row for row in values['maintenance']}
        peer_parts = []
        for part in values['parts']:
            parent = parents.get(part.maintenance_record_id)
            if parent is None or parent.vehicle_record_id != peer.id:
                continue
            peer_parts.append({'source_id': f'part:{part.id}', 'date': part.replacement_date, 'content': part.part_name, 'part_number': part.part_number, 'mileage': part.mileage, 'status': parent.status, 'completion_date': parent.completion_date})
        peer_facts = build_vehicle_karte_preventive_facts(peer, {'end_date': summary['end_date'], 'current_mileage': None, 'current_mileage_date': None}, peer_parts)
        for fact in peer_facts['part_replacements']:
            latest = fact['latest_dated_replacement']
            if not summary['start_date'] <= latest <= summary['end_date']:
                continue
            days = fact.get('last_recorded_interval_days')
            if days is None:
                continue
            name = _dkss_common.re.sub('[\\s・･]+', '', unicodedata.normalize('NFKC', fact['part_name']).casefold()).replace('フィルター', 'フィルタ')
            key = (name, fact['part_number'])
            interval_samples.setdefault(key, []).append({'vehicle_id': peer.id, 'days': days, 'km': fact.get('last_recorded_interval_km')})
    for item in result['part_statistics']:
        name = _dkss_common.re.sub('[\\s・･]+', '', unicodedata.normalize('NFKC', item['part_name']).casefold()).replace('フィルター', 'フィルタ')
        samples = interval_samples.get((name, item['part_number']), [])
        days = [sample['days'] for sample in samples]
        distances = [sample['km'] for sample in samples if sample['km'] is not None]
        item.update({'latest_interval_sample_count': len(days), 'latest_interval_distance_sample_count': len(distances), 'latest_interval_days_median': median(days) if days else None, 'latest_interval_km_median': median(distances) if distances else None})
    result['part_interval_note'] = '各比較対象車両の、期間内で直近の登録交換とその前回との間隔。同一部品・品番につき1台最大1組。前回は期間開始前も参照する。交換完了の登録がある記録を使用。全交換間隔の平均ではない。期間と距離の母数は別で、距離不明・逆転は距離集計から除外。途中の未登録作業やテスト記録等の真偽は未確認。メーカー基準・推奨交換間隔・故障発生間隔を意味しない。'
    summaries = [build_vehicle_karte_analysis_summary(values['maintenance'], values['operations'], values['parts'], values['defects'], summary['start_date'], summary['end_date']) for values in grouped.values()]
    for field, label, unit in (('total_cost', '期間内の整備費', '円'), ('failure_count', '登録故障件数', '件'), ('part_replacement_count', '部品交換登録件数', '件'), ('cost_per_km', '1kmあたり整備費', '円/km')):

        def comparable(item):
            if field == 'total_cost' and item['missing_cost_count']:
                return None
            return item[field]
        values = [comparable(item) for item in summaries]
        known = [_dkss_common.Decimal(str(value)) for value in values if value is not None]
        average = sum(known, _dkss_common.Decimal('0')) / len(known) if known else None
        current = comparable(summary)
        result['metrics'].append({'label': label, 'unit': unit, 'current': current, 'average': average, 'sample_count': len(known), 'vehicles_with_registered_events': sum((value > 0 for value in known)) if field in {'failure_count', 'part_replacement_count'} else None, 'sample_scope_note': '登録件数の平均には登録0件の比較対象車両も含む。登録0件は実際の故障・交換がなかった証明ではない。' if field in {'failure_count', 'part_replacement_count'} else '平均の母数はsample_count。比較対象の全台数とは限らず、記録のある費用・距離に基づく比較。', 'difference_percentage': (_dkss_common.Decimal(str(current)) - average) / average * _dkss_common.Decimal('100') if current is not None and average is not None and (average > 0) else None})
    return result



def build_vehicle_karte_dashboard_cost_breakdown(vehicle, maintenance, start_date, end_date):
    """Use registered monetary fields; never infer a repair category or tax rate."""
    from decimal import Decimal, InvalidOperation
    def money(value):
        if value is None or value == "": return None
        try:
            parsed = Decimal(str(value))
            return parsed if parsed.is_finite() else None
        except (ValueError, InvalidOperation, TypeError): return None
    parents = [row for row in maintenance if row.company_code == vehicle.company_code and row.vehicle_record_id == vehicle.id]
    parents, _, _ = filter_vehicle_maintenance_factual_history(parents, [])
    fields = (("labor_cost", "工賃"), ("parts_cost", "部品代"), ("other_cost", "その他費用"), ("tax_amount", "消費税"))
    totals = {label: Decimal("0") for _, label in fields}
    totals["内訳未確定"] = Decimal("0")
    total = Decimal("0"); records = 0; incomplete = 0
    for row in parents:
        day = str(row.entry_date or row.completion_date or "")[:10]
        try: _dkss_common.datetime.strptime(day, "%Y-%m-%d")
        except ValueError: continue
        if not start_date <= day <= end_date: continue
        amount = money(row.total_cost)
        if amount is None: continue
        records += 1; total += amount
        components = [(label, money(getattr(row, field, None))) for field, label in fields]
        known = sum((value for _, value in components if value is not None), Decimal("0"))
        remaining = amount - known
        # Inconsistent components do not become invented negative residual categories.
        inconsistent = (amount >= 0 and (remaining < 0 or any(value is not None and value < 0 for _,value in components))) or (amount < 0 and (remaining > 0 or any(value is not None and value > 0 for _,value in components)))
        if inconsistent:
            totals["内訳未確定"] += amount; incomplete += 1; continue
        for label, value in components:
            if value is not None: totals[label] += value
        if remaining != 0:
            totals["内訳未確定"] += remaining; incomplete += 1
    return {"rows": [{"label": label, "amount": value} for label, value in totals.items() if value != 0], "total": total if records else None, "record_count": records, "incomplete_count": incomplete, "note": "登録済みの工賃・部品代・その他費用・消費税を集計。合計との差額は内訳未確定。整備区分を推測して分類していません。"}



def build_vehicle_karte_dashboard_parts(vehicle, maintenance, parts, start_date, end_date):
    """Period-scoped saved registrations, independent of AI selection/freshness."""
    from decimal import Decimal, InvalidOperation

    def day(value):
        try:
            return _dkss_common.datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    start, end = day(start_date), day(end_date)
    if start is None or end is None or start > end:
        raise ValueError("分析期間が不正です。")
    # Fence both parent and child before applying the source-based exclusion.
    parents = [row for row in maintenance if row.company_code == vehicle.company_code
               and row.vehicle_record_id == vehicle.id]
    children = [row for row in parts if row.company_code == vehicle.company_code
                and row.vehicle_record_id == vehicle.id]
    _, children, _ = filter_vehicle_maintenance_factual_history(parents, children)
    candidates = []
    for part in children:
        replaced = day(part.replacement_date)
        if replaced is None or not start <= replaced <= end:
            continue
        name = str(part.part_name or "").strip()
        if not name:
            continue
        candidates.append((replaced, int(part.id or 0), part))
    result, seen = [], set()
    for replaced, _, part in sorted(candidates, key=lambda value: value[:2], reverse=True):
        key = (str(part.part_name).strip(), str(part.part_number or "").strip())
        if key in seen:
            continue
        seen.add(key)
        try:
            mileage = Decimal(str(part.mileage))
            if not mileage.is_finite() or mileage < 0:
                mileage = None
        except (InvalidOperation, ValueError, TypeError):
            mileage = None
        result.append({
            "source_id": f"part:{part.id}", "part_name": key[0],
            "part_number": key[1], "replacement_date": replaced.isoformat(),
            "mileage": mileage,
            "url": _dkss_common.url_for("vehicle_karte_maintenance", vehicle_record_id=vehicle.id,
                           record_id=part.maintenance_record_id),
        })
    return result



def vehicle_karte_analysis(vehicle_record_id):
    from flask import abort
    if not _dkss_common.session.get('username'):
        return _dkss_common.redirect(_dkss_common.url_for('login'))
    vehicle = _dkss_models.Vehicle.query.filter_by(id=vehicle_record_id, company_code=_dkss_common.session.get('company_code')).first_or_404()
    today = _dkss_common.datetime.now(_dkss_common.ZoneInfo('Asia/Tokyo')).date()
    default_start = today.replace(year=today.year - 2, day=min(today.day, _dkss_common.calendar.monthrange(today.year - 2, today.month)[1]))
    start_text = _dkss_common.request.args.get('start_date', default_start.isoformat())
    end_text = _dkss_common.request.args.get('end_date', today.isoformat())
    try:
        start = _dkss_common.datetime.strptime(start_text, '%Y-%m-%d').date()
        end = _dkss_common.datetime.strptime(end_text, '%Y-%m-%d').date()
        if start.isoformat() != start_text or end.isoformat() != end_text or start > end or ((end - start).days > 366 * 5):
            raise ValueError()
    except ValueError:
        abort(400, description='分析期間は開始日から終了日の順で、5年以内を指定してください。')
    maintenance = _dkss_models.VehicleMaintenanceRecord.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).all()
    operations = _dkss_models.VehicleOperationRecord.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).filter(_dkss_models.VehicleOperationRecord.operation_date <= end.isoformat()).all()
    operations = _dkss_vehicle_operations.get_vehicle_canonical_operations(vehicle.company_code, vehicle.id, operations, end=end.isoformat())
    parts = _dkss_models.VehiclePartReplacement.query.join(_dkss_models.VehicleMaintenanceRecord, _dkss_models.VehiclePartReplacement.maintenance_record_id == _dkss_models.VehicleMaintenanceRecord.id).filter(_dkss_models.VehiclePartReplacement.company_code == vehicle.company_code, _dkss_models.VehiclePartReplacement.vehicle_record_id == vehicle.id, _dkss_models.VehicleMaintenanceRecord.company_code == vehicle.company_code, _dkss_models.VehicleMaintenanceRecord.vehicle_record_id == vehicle.id).all()
    defects = _dkss_models.VehiclePatrol.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).all()
    summary = build_vehicle_karte_analysis_summary(maintenance, operations, parts, defects, start.isoformat(), end.isoformat(), periodic_records=_dkss_models.VehiclePeriodicInspectionRecord.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).all())
    number = _dkss_vehicle_readers.vehicle_number({'plate_area': vehicle.plate_area or '', 'plate_class': vehicle.plate_class or '', 'plate_kana': vehicle.plate_kana or '', 'plate_number': vehicle.plate_number or ''})
    if _dkss_common.request.method == 'POST':
        comparison = get_vehicle_karte_peer_comparison(vehicle, summary)
        payload, sources = build_vehicle_karte_analysis_payload(vehicle, summary, comparison, maintenance, parts, defects)
        if not payload['records']:
            result = {'overview': '分析の根拠となる整備・部品交換・故障の履歴がありません。', 'recommendations': []}
        else:
            try:
                result = _dkss_common.analyze_vehicle_karte(payload)
            except (ValueError, RuntimeError) as error:
                code = str(error)
                _dkss_runtime.app.logger.warning('車両AI分析に失敗しました: %s', code)
                if code == 'API_KEY_NOT_SET':
                    message = 'AI接続用のOPENAI_API_KEYが設定されていません。サーバー設定を確認してください。'
                    status = 503
                elif code == 'ANALYSIS_NETWORK_OR_TIMEOUT':
                    message = 'AIとの通信が完了せず、分析結果を取得できませんでした。'
                    status = 504
                elif code == 'ANALYSIS_HTTP_429':
                    message = 'AIサービスの利用上限に達したか、リクエストが集中しています。'
                    status = 429
                else:
                    message = 'AI分析の結果を取得・検証できませんでした。時間をおいて再実行してください。'
                    status = 502
                return (_dkss_common.jsonify(ok=False, message=message), status)
        return _dkss_common.jsonify(ok=True, analysis=result, sources=sources, coverage=payload['coverage'], generated_at=_dkss_common.datetime.now(_dkss_common.ZoneInfo('Asia/Tokyo')).strftime('%Y/%m/%d %H:%M'))
    return _dkss_common.render_template('vehicle_karte_analysis.html', karte_driving_summary=_dkss_vehicle_operations.get_vehicle_driving_report_summary(vehicle.company_code, vehicle.id, start.isoformat(), end.isoformat()) if _dkss_access.require_master_admin() else None, vehicle=vehicle, vehicle_number=number, open_defects=_dkss_checklists.get_vehicle_open_inspection_defects(vehicle.company_code, vehicle.id), inspection_defect_progress=_dkss_checklists.get_vehicle_open_inspection_defects(vehicle.company_code, vehicle.id, include_resolved=True), analysis_summary=summary, analysis_cost_breakdown=build_vehicle_karte_dashboard_cost_breakdown(vehicle, maintenance, start.isoformat(), end.isoformat()), analysis_part_history=build_vehicle_karte_dashboard_parts(vehicle, maintenance, parts, start.isoformat(), end.isoformat()), analysis_progress=build_vehicle_karte_service_progress(maintenance, summary), analysis_comparison=get_vehicle_karte_peer_comparison(vehicle, summary, registration_scope=_dkss_common.request.args.get('peer_registration', 'auto'), include_inactive=_dkss_common.request.args.get('peer_inactive') == '1'), analysis_today=today.isoformat(), format_analysis_number=_dkss_vehicle_karte.format_vehicle_maintenance_number)
