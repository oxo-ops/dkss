"""Vehicle Master responsibilities; routes are registered by the application factory."""
from .vehicle_capacity import reserved_vehicle_count, UNKNOWN_VEHICLE_STATE
from . import audit as _dkss_audit, common as _dkss_common, http as _dkss_http, knowledge as _dkss_knowledge, master_readers as _dkss_master_readers, models as _dkss_models, runtime as _dkss_runtime, serialization as _dkss_serialization, storage as _dkss_storage, vehicle_operations as _dkss_vehicle_operations, vehicle_readers as _dkss_vehicle_readers


def import_vehicles(source_file=None, source_draft_id=None):

    company_code = _dkss_common.session.get("company_code")

    if _dkss_common.request.method == "GET" and _dkss_common.request.args.get("complete") == "1":
        result = _dkss_common.session.get("vehicle_import_complete")
        if isinstance(result, dict):
            return _dkss_common.render_template("vehicle_import_complete.html", **result)

    if _dkss_common.request.method == "POST" or source_file is not None:

        excel_file = source_file if source_file is not None else _dkss_common.request.files.get("excel_file")

        if not excel_file or not excel_file.filename:
            return _dkss_http.return_form_errors([
                (
                    "Excelファイルを選択してください。",
                    "excel_file"
                )
            ])

        if not excel_file.filename.lower().endswith(".xlsx"):
            return _dkss_http.return_form_errors([
                (
                    "xlsx形式のExcelファイルを選択してください。",
                    "excel_file"
                )
            ])

        if not _dkss_storage.is_valid_uploaded_file(
            excel_file,
            ".xlsx"
        ):
            return _dkss_http.return_form_errors([
                (
                    "Excelファイルの内容が不正です。",
                    "excel_file"
                )
            ])

        try:
            workbook = _dkss_common.load_workbook(
                excel_file,
                data_only=True
            )
        except Exception:
            return _dkss_http.return_form_errors([
                (
                    "Excelファイルを読み込めませんでした。",
                    "excel_file"
                )
            ])

        sheet = workbook.active

        if sheet.max_row > 5000:
            return _dkss_http.return_form_errors([
                (
                    "一度に読み込めるExcelは5000行までです。",
                    "excel_file"
                )
            ])

        if sheet.max_column > 200:
            return _dkss_http.return_form_errors([
                (
                    "一度に読み込めるExcelは200列までです。",
                    "excel_file"
                )
            ])

        header_row = None

        for row in sheet.iter_rows():
            values = [cell.value for cell in row]

            if (
                "ID" in values
                and "車両番号" in values
                and "車体番号" in values
                and "車番" in values
            ):
                header_row = row[0].row
                break

        if header_row is None:
            return _dkss_http.return_form_errors([
                (
                    "車両台帳の見出し行が見つかりませんでした。",
                    "excel_file"
                )
            ])

        headers = [
            cell.value
            for cell in sheet[header_row]
        ]

        header_map = {
            name: index
            for index, name in enumerate(headers)
            if name is not None
        }
        required_headers = [
            "車種コード",
            "車番・地域名",
            "車番・分類",
            "車番・ひらがな",
            "車番",
            "車両総重量",
            "車体番号",
            "車体型式",
            "初年度車検",
            "車検期間終了日",
            "車両メーカー",
            "車両形状",
            "最大積載量",
        ]

        missing_headers = [
            header
            for header in required_headers
            if header not in header_map
        ]

        if missing_headers:
            return _dkss_http.return_form_errors([
                (
                    "Excelに必要な見出しがありません："
                    + "、".join(missing_headers),
                    "excel_file"
                )
            ])

        def normalize_excel_date(value):
            if value in (None, ""):
                return ""

            if hasattr(value, "strftime"):
                return value.strftime("%Y-%m-%d")

            return str(value).strip()
        vehicles_data = []

        for data_row in range(header_row + 1, sheet.max_row + 1):

            row_values = [
                cell.value
                for cell in sheet[data_row]
            ]

            # 空行は読み飛ばす
            if not any(value is not None for value in row_values):
                continue

            plate_number = row_values[header_map["車番"]]
            chassis_number = row_values[header_map["車体番号"]]



            vehicle_data = {
                "excel_row": data_row,

                "office": (
                    str(
                        row_values[header_map["営業所"]] or ""
                    ).strip()
                    if "営業所" in header_map
                    else ""
                ),

                "active_status": (
                    str(
                        row_values[header_map["有効／無効"]] or ""
                    ).strip()
                    if "有効／無効" in header_map
                    else ""
                ),

                "vehicle_type_code": str(
                    row_values[header_map["車種コード"]] or ""
                ).strip(),

                "plate_area": row_values[header_map["車番・地域名"]],
                "plate_class": row_values[header_map["車番・分類"]],
                "plate_kana": row_values[header_map["車番・ひらがな"]],
                "plate_number": plate_number,

                "gross_vehicle_weight": row_values[header_map["車両総重量"]],
                "chassis_number": chassis_number,
                "model_code": row_values[header_map["車体型式"]],

                "first_registration_date": normalize_excel_date(
                    row_values[header_map["初年度車検"]]
                ),
                "inspection_expiry": normalize_excel_date(
                    row_values[header_map["車検期間終了日"]]
                ),

                "vehicle_name_raw": row_values[header_map["車両メーカー"]],
                "body_type_raw": row_values[header_map["車両形状"]],

                "vehicle_name": row_values[header_map["車両メーカー"]],
                "body_type": row_values[header_map["車両形状"]],

                "max_payload": row_values[header_map["最大積載量"]],
            }

            vehicles_data.append(vehicle_data)

        valid_import_offices = {
            office.name
            for office in _dkss_models.Office.query.filter_by(
                company_code=_dkss_common.session.get("company_code")
            ).all()
        }

        for vehicle in vehicles_data:
            office = vehicle.get("office", "")
            active_status = vehicle.get("active_status", "")
            excel_row = vehicle.get("excel_row")

            if office and office not in valid_import_offices:
                return _dkss_http.return_form_errors([
                    (
                        f"{excel_row}行目の営業所「{office}」は"
                        "営業所マスタに登録されていません。",
                        "excel_file"
                    )
                ])

            if active_status not in {"", "有効", "無効"}:
                return _dkss_http.return_form_errors([
                    (
                        f"{excel_row}行目の有効／無効は"
                        "「有効」または「無効」で入力してください。",
                        "excel_file"
                    )
                ])

        def clean_preview_text(value):
            return str(
                "" if value is None else value
            ).strip()

        def preview_int(value):
            cleaned_value = clean_preview_text(
                value
            ).replace(",", "")

            if not cleaned_value:
                return None

            try:
                return int(float(cleaned_value))
            except (TypeError, ValueError):
                return None

        incoming_chassis_numbers = {
            clean_preview_text(
                vehicle.get("chassis_number")
            )
            for vehicle in vehicles_data
            if clean_preview_text(
                vehicle.get("chassis_number")
            )
        }


        existing_preview_records = []

        if incoming_chassis_numbers:
            existing_preview_records.extend(
                _dkss_models.Vehicle.query.filter(
                    _dkss_models.Vehicle.company_code
                    == _dkss_common.session.get("company_code"),
                    _dkss_common.db.func.trim(
                        _dkss_models.Vehicle.chassis_number
                    ).in_(incoming_chassis_numbers)
                ).all()
            )

        existing_preview_by_chassis = {}

        for existing_vehicle in existing_preview_records:

            existing_chassis = clean_preview_text(
                existing_vehicle.chassis_number
            )

            if existing_chassis:
                existing_preview_by_chassis[
                    existing_chassis
                ] = existing_vehicle

        # この会社で過去に保存した
        # Excel車種コード → 車種名 の対応を取得
        vehicle_type_mappings = _dkss_models.VehicleTypeImportMapping.query.filter_by(
            company_code=_dkss_common.session.get("company_code")
        ).all()

        valid_vehicle_type_names = {
            vehicle_type.name
            for vehicle_type in _dkss_models.VehicleType.query.filter_by(
                company_code=_dkss_common.session.get("company_code")
            ).all()
        }

        vehicle_type_mapping_dict = {
            mapping.excel_value: mapping.vehicle_type_name
            for mapping in vehicle_type_mappings
            if mapping.vehicle_type_name in valid_vehicle_type_names
        }

        for vehicle in vehicles_data:
            excel_vehicle_type = str(
                vehicle.get("vehicle_type_code", "") or ""
            ).strip()

            mapped_vehicle_type = vehicle_type_mapping_dict.get(
                excel_vehicle_type,
                ""
            )

            if (
                not mapped_vehicle_type
                and excel_vehicle_type in valid_vehicle_type_names
            ):
                mapped_vehicle_type = excel_vehicle_type

            vehicle["mapped_vehicle_type"] = mapped_vehicle_type

        processed_import_keys = set()

        for vehicle in vehicles_data:

            chassis_number = clean_preview_text(
                vehicle.get("chassis_number")
            )

            if not chassis_number:
                return _dkss_http.return_form_errors([
                    (
                        f"{vehicle.get('excel_row')}行目の車台番号を入力してください。",
                        "excel_file"
                    )
                ])

            import_key = (
                "chassis",
                chassis_number
            )

            existing_vehicle = (
                existing_preview_by_chassis.get(
                    chassis_number
                )
            )

            vehicle["recommended_update_id"] = None

            if not existing_vehicle:
                candidates = _dkss_vehicle_operations.get_vehicle_registration_plate_conflicts(
                    company_code,
                    vehicle.get("plate_area"),
                    vehicle.get("plate_class"),
                    vehicle.get("plate_kana"),
                    vehicle.get("plate_number"),
                    chassis_number,
                )
                complete_chassis = _dkss_common.normalize_vehicle_operation_plate(
                    chassis_number
                )
                correction_candidates = []

                for candidate in candidates:
                    shortened_chassis = _dkss_common.normalize_vehicle_operation_plate(
                        candidate["chassis_number"]
                    )

                    if (
                        shortened_chassis
                        and len(shortened_chassis) < len(complete_chassis)
                        and complete_chassis.startswith(shortened_chassis)
                        and clean_preview_text(candidate["chassis_number"])
                        not in incoming_chassis_numbers
                    ):
                        correction_candidates.append(candidate)

                if len(correction_candidates) == 1:
                    vehicle["recommended_update_id"] = (
                        correction_candidates[0]["id"]
                    )
                    existing_vehicle = _dkss_models.Vehicle.query.filter_by(
                        id=vehicle["recommended_update_id"],
                        company_code=company_code,
                    ).first()

            is_excel_duplicate = (
                import_key in processed_import_keys
            )

            if existing_vehicle:

                if not clean_preview_text(
                    vehicle.get("mapped_vehicle_type")
                ):
                    existing_vehicle_type = clean_preview_text(
                        existing_vehicle.type
                    )

                    if (
                        existing_vehicle_type
                        in valid_vehicle_type_names
                    ):
                        vehicle["mapped_vehicle_type"] = (
                            existing_vehicle_type
                        )

                if not vehicle.get("active_status"):
                    vehicle["active_status"] = (
                        "無効" if existing_vehicle.deleted else "有効"
                    )

                target_deleted = (
                    vehicle["active_status"] == "無効"
                )

                vehicle["reactivate"] = (
                    existing_vehicle.deleted and not target_deleted
                )

                vehicle["state_changed"] = (
                    bool(existing_vehicle.deleted) != target_deleted
                )

                if not vehicle.get("office"):
                    vehicle["office"] = (
                        existing_vehicle.office or ""
                    )

                update_values = {
                    "plate_area": clean_preview_text(
                        vehicle.get("plate_area")
                    ),
                    "plate_class": clean_preview_text(
                        vehicle.get("plate_class")
                    ),
                    "plate_kana": clean_preview_text(
                        vehicle.get("plate_kana")
                    ),
                    "plate_number": clean_preview_text(
                        vehicle.get("plate_number")
                    ),
                    "gross_vehicle_weight": preview_int(
                        vehicle.get(
                            "gross_vehicle_weight"
                        )
                    ),
                    "model_code": clean_preview_text(
                        vehicle.get("model_code")
                    ),
                    "first_registration_date":
                        clean_preview_text(
                            vehicle.get(
                                "first_registration_date"
                            )
                        ),
                    "inspection_expiry":
                        clean_preview_text(
                            vehicle.get(
                                "inspection_expiry"
                            )
                        ),
                    "manufacturer": clean_preview_text(
                        vehicle.get("vehicle_name")
                    ),
                    "body_type": clean_preview_text(
                        vehicle.get("body_type")
                    ),
                    "max_payload": preview_int(
                        vehicle.get("max_payload")
                    ),
                }

                vehicle_changed = (
                    bool(vehicle.get("recommended_update_id"))
                    or bool(vehicle.get("state_changed"))
                    or clean_preview_text(existing_vehicle.office)
                    != clean_preview_text(vehicle.get("office"))
                )

                for field_name, new_value in (
                    update_values.items()
                ):
                    # Excelが空欄なら既存値を維持
                    if new_value in ("", None):
                        continue

                    old_value = getattr(
                        existing_vehicle,
                        field_name
                    )

                    if isinstance(new_value, int):
                        try:
                            old_value = int(old_value)
                        except (TypeError, ValueError):
                            old_value = None
                    else:
                        old_value = clean_preview_text(
                            old_value
                        )

                    if old_value != new_value:
                        vehicle_changed = True
                        break

                mapped_vehicle_type = clean_preview_text(
                    vehicle.get("mapped_vehicle_type")
                )

                if (
                    mapped_vehicle_type
                    and clean_preview_text(existing_vehicle.type)
                    != mapped_vehicle_type
                ):
                    vehicle_changed = True

                if vehicle_changed:
                    vehicle["import_status"] = "更新"
                else:
                    vehicle["import_status"] = (
                        "変更なし"
                    )

            else:
                vehicle["import_status"] = "新規"

                if not vehicle.get("active_status"):
                    vehicle["active_status"] = "有効"

            vehicle["base_import_status"] = (
                vehicle["import_status"]
            )

            if is_excel_duplicate:
                vehicle["import_status"] = (
                    "Excel内重複"
                )
            processed_import_keys.add(import_key)



        company_vehicles = _dkss_models.Vehicle.query.filter_by(
            company_code=company_code
        ).order_by(_dkss_models.Vehicle.id.asc()).all()

        excel_plate_rows = {}

        for row_number, vehicle_data in enumerate(
            vehicles_data, start=1
        ):
            plate_key = tuple(
                _dkss_common.normalize_vehicle_operation_plate(
                    vehicle_data.get(field_name)
                )
                for field_name in (
                    "plate_area",
                    "plate_class",
                    "plate_kana",
                    "plate_number",
                )
            )

            if all(plate_key):
                excel_plate_rows.setdefault(
                    plate_key, []
                ).append((
                    row_number,
                    str(
                        vehicle_data.get("chassis_number") or ""
                    ).strip(),
                ))

        for row_number, vehicle_data in enumerate(
            vehicles_data, start=1
        ):
            chassis_number = str(
                vehicle_data.get("chassis_number") or ""
            ).strip()

            vehicle_data["plate_conflicts"] = (
                _dkss_vehicle_operations.get_vehicle_registration_plate_conflicts(
                    company_code,
                    vehicle_data.get("plate_area"),
                    vehicle_data.get("plate_class"),
                    vehicle_data.get("plate_kana"),
                    vehicle_data.get("plate_number"),
                    chassis_number,
                    existing_vehicles=company_vehicles,
                )
            )

            plate_key = tuple(
                _dkss_common.normalize_vehicle_operation_plate(
                    vehicle_data.get(field_name)
                )
                for field_name in (
                    "plate_area",
                    "plate_class",
                    "plate_kana",
                    "plate_number",
                )
            )

            vehicle_data["excel_plate_conflicts"] = [
                {
                    "row_number": other_row,
                    "chassis_number": other_chassis,
                }
                for other_row, other_chassis in (
                    excel_plate_rows.get(plate_key, [])
                )
                if other_row != row_number
                and other_chassis
                and chassis_number
                and other_chassis != chassis_number
            ]

        if source_draft_id is None and _dkss_common.request.headers.get('X-DKSS-Validation-Only') == '1':
            return _dkss_common.jsonify(ok=True)
        if source_draft_id is None:
            from .import_flow import store_excel_review
            draft = store_excel_review(excel_file, company_code, _dkss_common.session.get('username'))
            destination = _dkss_common.url_for('vehicle_excel_import_preview', draft_id=draft.id)
            if _dkss_common.request.headers.get('X-DKSS-Final-Submit') == '1':
                return _dkss_common.jsonify(preview_url=destination)
            return _dkss_common.redirect(destination, code=303)
        return _dkss_common.render_template(
            "vehicle_import_preview.html",
            vehicle_excel_import_draft=source_draft_id,
            import_flow_notice=('既存車両と照合しました。「変更なし」「Excel内重複」は新規登録しません。更新する項目だけ確認するか、キャンセルして登録方法の画面へ戻れます。' if any(item.get('import_status') in {'変更なし', 'Excel内重複'} for item in vehicles_data) else None),
            vehicles=vehicles_data,
            offices=_dkss_master_readers.offices_for_current_company(),
            vehicle_types=_dkss_vehicle_readers.vehicle_types_for_current_company(),
            vehicle_type_mapping_dict=vehicle_type_mapping_dict,
            vehicle_plate_candidates=[
                {
                    "id": vehicle.id,
                    "chassis_number": str(
                        vehicle.chassis_number or ""
                    ).strip(),
                    "plate_area": vehicle.plate_area or "",
                    "plate_class": vehicle.plate_class or "",
                    "plate_kana": vehicle.plate_kana or "",
                    "plate_number": vehicle.plate_number or "",
                    "office": vehicle.office or "",
                    "inactive": bool(vehicle.deleted),
                    "vehicle_type": vehicle.type or "",
                    "gross_vehicle_weight": vehicle.gross_vehicle_weight,
                    "model_code": vehicle.model_code or "",
                    "first_registration_date": vehicle.first_registration_date or "",
                    "inspection_expiry": vehicle.inspection_expiry or "",
                    "vehicle_name": vehicle.manufacturer or "",
                    "body_type": vehicle.body_type or "",
                    "max_payload": vehicle.max_payload,
                }
                for vehicle in company_vehicles
            ],
        )

    return _dkss_common.render_template(
        "vehicle_import.html"
    )



def confirm_vehicle_import():

    excel_review = None
    review_id = _dkss_common.request.form.get('vehicle_excel_import_draft')
    if review_id:
        excel_review = _dkss_models.VehicleDocumentImportDraft.query.filter_by(
            id=review_id, document_type='vehicle_excel', company_code=_dkss_common.session.get('company_code'),
            created_by_username=_dkss_common.session.get('username')).with_for_update().first_or_404()
        if excel_review.status != 'preview':
            return _dkss_http.return_form_errors([('このExcelはすでに登録済み、または取消済みです。元の画面で結果を確認してください。', '')], 409)

    company_code = _dkss_common.session.get("company_code")

    vehicle_type_codes = _dkss_common.request.form.getlist(
        "vehicle_type_code"
    )

    vehicle_types = _dkss_common.request.form.getlist(
        "vehicle_type"
    )

    valid_vehicle_type_names = {
        vehicle_type.name
        for vehicle_type in _dkss_models.VehicleType.query.filter_by(
            company_code=company_code
        ).all()
    }

    vehicle_types = [
        str(value or "").strip()
        for value in vehicle_types
    ]

    for i, vehicle_type in enumerate(vehicle_types):
        if vehicle_type and vehicle_type not in valid_vehicle_type_names:
            return _dkss_http.return_form_errors([
                (
                    f"{i + 1}件目の車種「{vehicle_type}」は"
                    "車種マスタに登録されていません。"
                    "既存の車種への割り当て、または新規登録を確認してください。",
                    "vehicle_type"
                )
            ])

    plate_areas = _dkss_common.request.form.getlist("plate_area")
    plate_classes = _dkss_common.request.form.getlist("plate_class")
    plate_kanas = _dkss_common.request.form.getlist("plate_kana")
    plate_numbers = _dkss_common.request.form.getlist("plate_number")

    gross_weights = _dkss_common.request.form.getlist("gross_vehicle_weight")
    chassis_numbers = _dkss_common.request.form.getlist("chassis_number")
    model_codes = _dkss_common.request.form.getlist("model_code")

    first_registration_dates = _dkss_common.request.form.getlist(
        "first_registration_date"
    )

    inspection_expiries = _dkss_common.request.form.getlist(
        "inspection_expiry"
    )

    vehicle_names = _dkss_common.request.form.getlist("vehicle_name")
    body_types = _dkss_common.request.form.getlist("body_type")
    max_payloads = _dkss_common.request.form.getlist("max_payload")

    offices = _dkss_common.request.form.getlist("office")
    active_statuses = _dkss_common.request.form.getlist("active_status")

    form_lists = [
        vehicle_type_codes,
        vehicle_types,
        plate_areas,
        plate_classes,
        plate_kanas,
        plate_numbers,
        gross_weights,
        chassis_numbers,
        model_codes,
        first_registration_dates,
        inspection_expiries,
        vehicle_names,
        body_types,
        max_payloads,
        offices,
        active_statuses,
    ]

    form_list_lengths = {
        len(values)
        for values in form_lists
    }

    if len(form_list_lengths) != 1:
        return _dkss_http.return_form_errors([
            (
                "取込データの件数が一致しません。"
                "Excel取込画面からやり直してください。",
                ""
            )
        ])

    import_count = len(chassis_numbers)

    if import_count > 5000:
        return _dkss_http.return_form_errors([
            (
                "一度に取り込める車両は5000件までです。",
                ""
            )
        ])

    if import_count == 0:
        return _dkss_http.return_form_errors([
            (
                "取込対象の車両がありません。",
                ""
            )
        ])

    valid_import_offices = {
        office.name
        for office in _dkss_models.Office.query.filter_by(
            company_code=company_code
        ).all()
    }

    offices = [
        str(value or "").strip()
        for value in offices
    ]

    target_deleted_values = []

    for i in range(import_count):
        office = offices[i]
        active_status = str(active_statuses[i] or "").strip()
        vehicle_type_code = str(vehicle_type_codes[i] or "").strip()

        if vehicle_type_code and not vehicle_types[i]:
            return _dkss_http.return_form_errors([
                (
                    f"{i + 1}件目の車種コード「{vehicle_type_code}」の"
                    "割り当てが未解決です。"
                    "既存の車種への割り当て、または新規登録を確認してください。",
                    "vehicle_type"
                )
            ])

        if len(office) > 100:
            return _dkss_http.return_form_errors([
                (
                    f"{i + 1}件目の営業所は100文字以内で入力してください。",
                    "office"
                )
            ])

        if office and office not in valid_import_offices:
            return _dkss_http.return_form_errors([
                (
                    f"{i + 1}件目の営業所「{office}」は"
                    "営業所マスタに登録されていません。",
                    "office"
                )
            ])

        if active_status not in {"有効", "無効"}:
            return _dkss_http.return_form_errors([
                (
                    f"{i + 1}件目の有効／無効を選択してください。",
                    "active_status"
                )
            ])

        target_deleted_values.append(active_status == "無効")

    company = _dkss_models.Company.query.filter_by(
        company_code=company_code
    ).first()

    current_count = reserved_vehicle_count(company_code)


    def normalize_import_text(value):
        return str(value or "").strip()

    import_chassis_numbers = {
        normalize_import_text(value)
        for value in chassis_numbers
        if normalize_import_text(value)
    }

    existing_vehicle_records = []

    if import_chassis_numbers:
        existing_vehicle_records.extend(
            _dkss_models.Vehicle.query.filter(
                _dkss_models.Vehicle.company_code == company_code,
                _dkss_common.db.func.trim(
                    _dkss_models.Vehicle.chassis_number
                ).in_(import_chassis_numbers)
            ).all()
        )

    existing_vehicles_by_chassis = {}

    for existing_vehicle in existing_vehicle_records:

        if existing_vehicle.deleted is None:
            return _dkss_http.return_form_errors([(UNKNOWN_VEHICLE_STATE, "")], 409)

        existing_chassis = normalize_import_text(
            existing_vehicle.chassis_number
        )

        if existing_chassis:
            existing_vehicles_by_chassis[
                existing_chassis
            ] = existing_vehicle

    company_vehicles = _dkss_models.Vehicle.query.filter_by(
        company_code=company_code
    ).order_by(_dkss_models.Vehicle.id.asc()).all()

    excel_plate_chassis = {}

    for i in range(import_count):
        plate_key = tuple(
            _dkss_common.normalize_vehicle_operation_plate(value)
            for value in (
                plate_areas[i],
                plate_classes[i],
                plate_kanas[i],
                plate_numbers[i],
            )
        )
        if all(plate_key):
            excel_plate_chassis.setdefault(
                plate_key, set()
            ).add(normalize_import_text(chassis_numbers[i]))

    vehicle_chassis_corrections = {}
    correction_target_ids = set()
    checked_chassis_numbers = set()
    resolution_errors = []

    for i in range(import_count):
        chassis_number = normalize_import_text(
            chassis_numbers[i]
        )

        if not chassis_number:
            continue

        if chassis_number in checked_chassis_numbers:
            continue

        checked_chassis_numbers.add(chassis_number)

        field_name = f"vehicle_plate_resolution_{i}"
        choice = _dkss_common.request.form.get(
            field_name, ""
        ).strip()

        existing_vehicle = existing_vehicles_by_chassis.get(
            chassis_number
        )

        conflicts = _dkss_vehicle_operations.get_vehicle_registration_plate_conflicts(
            company_code,
            plate_areas[i],
            plate_classes[i],
            plate_kanas[i],
            plate_numbers[i],
            chassis_number,
            existing_vehicles=company_vehicles,
        )

        plate_key = tuple(
            _dkss_common.normalize_vehicle_operation_plate(value)
            for value in (
                plate_areas[i],
                plate_classes[i],
                plate_kanas[i],
                plate_numbers[i],
            )
        )

        excel_conflict = any(
            other_chassis
            and other_chassis != chassis_number
            for other_chassis in (
                excel_plate_chassis.get(plate_key, set())
            )
        )

        if not conflicts and not excel_conflict:
            if choice.startswith("update:"):
                resolution_errors.append((
                    f"No.{i + 1}の車両情報が変更されています。"
                    "車台番号の訂正対象を確認してください。",
                    field_name,
                ))
            continue

        if excel_conflict:
            resolution_errors.append((
                f"No.{i + 1}はExcel内に同じナンバーで異なる"
                "車台番号の行があります。"
                "車台番号またはナンバープレートを確認・訂正してください。",
                field_name,
            ))
            continue

        if existing_vehicle:
            resolution_errors.append((
                f"No.{i + 1}は登録済み車両同士でナンバーが重複しています。"
                "既存車両の重複を解消してから取り込んでください。",
                field_name,
            ))
            continue

        allowed_choices = {}
        conflict_ids = {
            candidate["id"]
            for candidate in conflicts
        }

        for candidate in company_vehicles:
            if candidate.id in conflict_ids:
                allowed_choices[
                    f"update:{candidate.id}"
                ] = candidate

        if choice not in allowed_choices:
            resolution_errors.append((
                f"No.{i + 1}は同じナンバーで異なる"
                "車台番号の車両があります。"
                "登録・更新方法を選択してください。",
                field_name,
            ))
            continue

        if not choice.startswith("update:"):
            continue

        target_vehicle = allowed_choices[choice]
        old_chassis = normalize_import_text(
            target_vehicle.chassis_number
        )

        if (
            target_vehicle.id in correction_target_ids
            or old_chassis in import_chassis_numbers
        ):
            resolution_errors.append((
                f"No.{i + 1}の訂正対象車両は、"
                "今回のExcel内の別の行でも使用されています。"
                "取り込む車台番号を確認してください。",
                field_name,
            ))
            continue

        correction_target_ids.add(target_vehicle.id)
        vehicle_chassis_corrections[chassis_number] = (
            target_vehicle
        )

    if resolution_errors:
        return _dkss_http.return_form_errors(resolution_errors)

    for corrected_chassis, target_vehicle in (
        vehicle_chassis_corrections.items()
    ):
        existing_vehicles_by_chassis[
            corrected_chassis
        ] = target_vehicle

    counted_import_keys = set()
    new_vehicle_count = 0
    reactivate_vehicle_count = 0
    deactivate_vehicle_count = 0

    for i in range(import_count):

        chassis_number = normalize_import_text(
            chassis_numbers[i]
        )

        if not chassis_number:
            return _dkss_http.return_form_errors([
                (
                    f"{i + 1}行目の車台番号を入力してください。",
                    "chassis_number"
                )
            ])

        import_key = (
            "chassis",
            chassis_number
        )

        if import_key in counted_import_keys:
            continue

        counted_import_keys.add(import_key)

        existing_vehicle = existing_vehicles_by_chassis.get(
            chassis_number
        )
        target_deleted = target_deleted_values[i]

        if existing_vehicle:
            if existing_vehicle.deleted is None:
                return _dkss_http.return_form_errors([(UNKNOWN_VEHICLE_STATE, "")], 409)
            if existing_vehicle.deleted and not target_deleted:
                reactivate_vehicle_count += 1
            elif not existing_vehicle.deleted and target_deleted:
                deactivate_vehicle_count += 1
        elif not target_deleted:
            new_vehicle_count += 1

    # 取込後の有効車両台数で上限チェック
    if company:
        projected_active_count = (
            current_count
            + new_vehicle_count
            + reactivate_vehicle_count
            - deactivate_vehicle_count
        )

        if projected_active_count > company.vehicle_limit:
            return _dkss_http.return_form_errors([
                (
                    f"登録上限を超えます。"
                    f"現在の上限判定台数（状態未確認を含む） {current_count} 台、"
                    f"有効車両の新規登録予定 {new_vehicle_count} 台、"
                    f"再有効化予定 {reactivate_vehicle_count} 台、"
                    f"無効化予定 {deactivate_vehicle_count} 台、"
                    f"取込後の有効車両 {projected_active_count} 台、"
                    f"上限 {company.vehicle_limit} 台です。",
                    ""
                )
            ])
    # 今回のExcel内ですでに処理した車両
    processed_import_keys = set()
    processed_row_indexes = set()
    registered_count = 0
    updated_count = 0
    unchanged_count = 0
    duplicate_skip_count = 0

    def clean_text(value):
        return str(value or "").strip()

    def validate_text_length(
        value,
        field_name,
        max_length,
        row_number
    ):
        value = clean_text(value)

        error = get_vehicle_text_length_error(
            value,
            field_name,
            max_length
        )

        if error:
            return None, f"{row_number}行目の{error}"

        return value, None

    def to_nonnegative_int(value, field_name, row_number):
        value = str("" if value is None else value).strip().replace(",", "")

        if not value:
            return None, None

        try:
            parsed = _dkss_http.parse_nonnegative_int(
                value,
                field_name
            )
        except _dkss_common.UploadValidationError as error:
            return None, f"{row_number}行目の{error}"

        return parsed, None

    def validate_import_date(value, field_name, row_number):
        value = clean_text(value)

        error = get_vehicle_date_error(
            value,
            field_name
        )

        if error:
            return "", f"{row_number}行目の{error}"

        return value, None

    for i in range(import_count):

        chassis_number, error = validate_text_length(
            normalize_import_text(
                chassis_numbers[i]
            ),
            "車台番号",
            100,
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "chassis_number")
            ])

        plate_area, error = validate_text_length(
            normalize_import_text(
                plate_areas[i]
            ),
            "車番・地域名",
            50,
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "plate_area")
            ])

        plate_class, error = validate_text_length(
            normalize_import_text(
                plate_classes[i]
            ),
            "車番・分類",
            50,
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "plate_class")
            ])

        plate_kana, error = validate_text_length(
            normalize_import_text(
                plate_kanas[i]
            ),
            "車番・ひらがな",
            10,
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "plate_kana")
            ])

        plate_number, error = validate_text_length(
            normalize_import_text(
                plate_numbers[i]
            ),
            "車番",
            50,
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "plate_number")
            ])

        if not chassis_number:
            return _dkss_http.return_form_errors([
                (
                    f"{i + 1}行目の車台番号を入力してください。",
                    "chassis_number"
                )
            ])

        import_key = (
            "chassis",
            chassis_number
        )

        existing_vehicle = (
            existing_vehicles_by_chassis.get(
                chassis_number
            )
        )

        # Excel内で同じ車両が重複している場合
        if import_key in processed_import_keys:
            duplicate_skip_count += 1
            continue

        processed_import_keys.add(import_key)
        processed_row_indexes.add(i)
        gross_vehicle_weight, error = to_nonnegative_int(
            gross_weights[i],
            "車両総重量",
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "gross_vehicle_weight")
            ])

        max_payload, error = to_nonnegative_int(
            max_payloads[i],
            "最大積載量",
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "max_payload")
            ])

        first_registration_date, error = validate_import_date(
            first_registration_dates[i],
            "初年度登録日",
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "first_registration_date")
            ])

        inspection_expiry, error = validate_import_date(
            inspection_expiries[i],
            "車検満了日",
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "inspection_expiry")
            ])

        model_code, error = validate_text_length(
            model_codes[i],
            "車体型式",
            100,
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "model_code")
            ])

        manufacturer, error = validate_text_length(
            vehicle_names[i],
            "車両メーカー",
            100,
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "vehicle_name")
            ])

        body_type, error = validate_text_length(
            body_types[i],
            "車両形状",
            100,
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "body_type")
            ])

        selected_vehicle_type, error = validate_text_length(
            vehicle_types[i],
            "車種",
            100,
            i + 1
        )

        if error:
            return _dkss_http.return_form_errors([
                (error, "vehicle_type")
            ])

        # 車台番号が一致する車両、または確認済みの訂正対象を更新
        if existing_vehicle:
            update_values = {
                "chassis_number": chassis_number,
                "plate_area": clean_text(plate_areas[i]),
                "plate_class": clean_text(plate_classes[i]),
                "plate_kana": clean_text(plate_kanas[i]),
                "plate_number": clean_text(plate_numbers[i]),
                "gross_vehicle_weight": gross_vehicle_weight,
                "model_code": model_code,
                "first_registration_date": first_registration_date,
                "inspection_expiry": inspection_expiry,
                "manufacturer": manufacturer,
                "body_type": body_type,
                "max_payload": max_payload,
                "office": offices[i],
            }

            comparison_values = dict(update_values)
            comparison_values["type"] = selected_vehicle_type
            comparison_values["deleted"] = target_deleted_values[i]

            comparison_differences = {
                key: {
                    "before": getattr(existing_vehicle, key),
                    "submitted": value,
                    "blank_preserved": (
                        key in update_values and value in ("", None)
                    ),
                }
                for key, value in comparison_values.items()
                if getattr(existing_vehicle, key) != value
            }

            if comparison_differences or clean_text(plate_numbers[i]) in (
                "1594", "4624", "71", "553"
            ):
                _dkss_runtime.app.logger.warning(
                    "VEHICLE_IMPORT_COMPARE row=%s id=%s chassis=%s differences=%s",
                    i + 1,
                    existing_vehicle.id,
                    chassis_number,
                    _dkss_common.json.dumps(comparison_differences, ensure_ascii=False),
                )

            vehicle_changed = False
            target_deleted = target_deleted_values[i]

            if bool(existing_vehicle.deleted) != target_deleted:
                existing_vehicle.deleted = target_deleted
                vehicle_changed = True

            for field_name, new_value in update_values.items():
                # Excelが空欄なら既存値を残す
                if new_value in ("", None):
                    continue

                if getattr(existing_vehicle, field_name) != new_value:
                    setattr(
                        existing_vehicle,
                        field_name,
                        new_value
                    )
                    vehicle_changed = True


            if clean_text(existing_vehicle.type) != selected_vehicle_type:
                existing_vehicle.type = selected_vehicle_type
                vehicle_changed = True

            if vehicle_changed:
                updated_count += 1
            else:
                unchanged_count += 1

            continue

        vehicle = _dkss_models.Vehicle(
            company_code=company_code,

            plate_area=plate_area,
            plate_class=plate_class,
            plate_kana=plate_kana,
            plate_number=plate_number,

            gross_vehicle_weight=gross_vehicle_weight,

            chassis_number=chassis_number,
            model_code=model_code,

            first_registration_date=first_registration_date,
            inspection_expiry=inspection_expiry,

            # 画面上は「車名」だが、
            # 現在のDBでは manufacturer に保存
            manufacturer=manufacturer,

            body_type=body_type,

            max_payload=max_payload,

            type=selected_vehicle_type,
            office=offices[i],

            deleted=target_deleted_values[i],
        )

        _dkss_common.db.session.add(vehicle)

        registered_count += 1

    # Excel車種コードごとに今回選ばれた車種を整理
    mapping_candidates = {}

    for i, (
        excel_value,
        vehicle_type_name
    ) in enumerate(
        zip(
            vehicle_type_codes,
            vehicle_types
        )
    ):

        if i not in processed_row_indexes:
            continue

        excel_value = str(excel_value or "").strip()
        vehicle_type_name = str(
            vehicle_type_name or ""
        ).strip()

        if not excel_value:
            continue

        if len(excel_value) > 100:
            return _dkss_http.return_form_errors([
                (
                    "車種コードは100文字以内で入力してください。",
                    "vehicle_type_code"
                )
            ])

        if len(vehicle_type_name) > 100:
            return _dkss_http.return_form_errors([
                (
                    "車種は100文字以内で入力してください。",
                    "vehicle_type"
                )
            ])

        mapping_candidates.setdefault(
            excel_value,
            set()
        ).add(vehicle_type_name)

    # 同じコードの選択内容が一致している場合だけ学習
    for excel_value, selected_types in mapping_candidates.items():

        mapping = _dkss_models.VehicleTypeImportMapping.query.filter_by(
            company_code=company_code,
            excel_value=excel_value
        ).first()

        # 同じコードに複数の車種が指定されている
        # → 自動判定できないので学習しない
        if len(selected_types) > 1:
            if mapping:
                _dkss_common.db.session.delete(mapping)
            continue

        vehicle_type_name = next(iter(selected_types))

        if vehicle_type_name:
            if mapping:
                mapping.vehicle_type_name = vehicle_type_name
            else:
                _dkss_common.db.session.add(
                    _dkss_models.VehicleTypeImportMapping(
                        company_code=company_code,
                        excel_value=excel_value,
                        vehicle_type_name=vehicle_type_name
                    )
                )
        elif mapping:
            _dkss_common.db.session.delete(mapping)

    if excel_review is not None:
        excel_review.status = 'completed'
        excel_review.source_file = b''
    _dkss_common.db.session.commit()

    result = {
        "registered_count": registered_count,
        "updated_count": updated_count,
        "unchanged_count": unchanged_count,
        "duplicate_skip_count": duplicate_skip_count,
    }
    if _dkss_common.request.headers.get("X-DKSS-Final-Submit") == "1":
        _dkss_common.session["vehicle_import_complete"] = result
        return _dkss_common.jsonify(redirect_url=_dkss_common.url_for("import_vehicles", complete="1"))

    return _dkss_common.render_template("vehicle_import_complete.html", **result)



def apply_vehicle_form_values(
    vehicle,
    form_data,
    validated_values
):
    for field_key in [
        "plate_area",
        "plate_class",
        "plate_kana",
        "plate_number",
        "model_code",
        "manufacturer",
        "body_type",
    ]:
        setattr(
            vehicle,
            field_key,
            form_data.get(field_key)
        )

    for field_key in [
        "chassis_number",
        "first_registration_date",
        "inspection_expiry",
        "gross_vehicle_weight",
        "max_payload",
        "type",
        "office",
    ]:
        setattr(
            vehicle,
            field_key,
            validated_values[field_key]
        )

    for field_key, field_label, max_length in _dkss_common.VEHICLE_MAINTENANCE_ATTRIBUTE_FIELDS:
        if field_key in form_data:
            value = (form_data.get(field_key) or "").strip()
            setattr(vehicle, field_key, value or None)



def validate_vehicle_master_values(
    vehicle_type,
    office,
    company_code
):
    errors = []

    for value, model, field_name, field_key in [
        (vehicle_type, _dkss_models.VehicleType, "車種", "type"),
        (office, _dkss_models.Office, "営業所", "office"),
    ]:
        if value:
            # Keep the selected name valid until the related vehicle is saved.
            # PostgreSQL FOR SHARE makes master rename/delete wait for commit.
            valid_value = model.query.filter_by(
                company_code=company_code,
                name=value
            ).with_for_update(read=True).first()

            if not valid_value:
                errors.append((
                    f"{field_name}が不正です。",
                    field_key
                ))

    return errors



def parse_vehicle_weights(form_data):
    values = {
        "gross_vehicle_weight": 0,
        "max_payload": 0,
    }
    errors = []

    for field_key, field_name in [
        ("gross_vehicle_weight", "車両総重量"),
        ("max_payload", "最大積載量"),
    ]:
        try:
            values[field_key] = _dkss_http.parse_nonnegative_int(
                form_data.get(field_key),
                field_name
            )
        except _dkss_common.UploadValidationError:
            errors.append((
                f"{field_name}の入力内容を確認してください。",
                field_key
            ))

    return values, errors



def get_vehicle_text_length_error(
    value,
    field_name,
    max_length
):
    if len(value) > max_length:
        return (
            f"{field_name}は"
            f"{max_length}文字以内で入力してください。"
        )

    return None



def get_vehicle_date_error(value, field_name):
    if not value:
        return None

    # Certificate first registration has month precision; never invent a day.
    if field_name == "初年度登録日" and _dkss_common.re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        year, month = map(int, value.split("-"))
        if 1 <= year <= 9999 and 1 <= month <= 12:
            return None
        return f"{field_name}が不正です。"

    # strptime accepts unpadded month/day values, but expiry queries compare
    # stored ISO strings and inspection plans require exact YYYY-MM-DD.
    # Reject other precision/formats before they can be saved unchanged.
    if not _dkss_common.re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return f"{field_name}が不正です。"

    try:
        _dkss_common.datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return f"{field_name}が不正です。"

    return None



def validate_vehicle_dates(
    first_registration_date,
    inspection_expiry
):
    errors = []

    for value, field_name, field_key in [
        (
            first_registration_date,
            "初年度登録日",
            "first_registration_date"
        ),
        (
            inspection_expiry,
            "車検満了日",
            "inspection_expiry"
        ),
    ]:
        error = get_vehicle_date_error(
            value,
            field_name
        )

        if error:
            errors.append((
                error,
                field_key
            ))

    return errors



def validate_vehicle_text_fields(form_data):
    field_settings = [
        ("plate_area", "車番・地域名", 50),
        ("plate_class", "車番・分類", 50),
        ("plate_kana", "車番・ひらがな", 10),
        ("plate_number", "車番", 50),
        ("chassis_number", "車台番号", 100),
        ("model_code", "車体型式", 100),
        ("manufacturer", "車両メーカー", 100),
        ("body_type", "車両形状", 100),
    ]

    field_settings += list(_dkss_common.VEHICLE_MAINTENANCE_ATTRIBUTE_FIELDS)

    errors = []

    for field_key, field_name, max_length in field_settings:
        value = form_data.get(field_key, "").strip()

        error = get_vehicle_text_length_error(
            value,
            field_name,
            max_length
        )

        if error:
            errors.append((
                error,
                field_key
            ))

    return errors



def extract_vehicle_certificate_route():
    """車検証から登録候補を抽出する。DB更新なし。"""
    from flask import abort
    from vehicle_certificate_ai import extract_vehicle_certificate
    from vehicle_certificate_adapter import prepare_certificate_form

    if not _dkss_common.session.get("username") or not _dkss_common.session.get("company_code"):
        abort(403)

    max_bytes = 20 * 1024 * 1024

    if _dkss_common.request.content_length and _dkss_common.request.content_length > max_bytes + 65536:
        return {"error": "ファイルは20MB以下にしてください。"}, 413

    upload = _dkss_common.request.files.get("certificate")
    if upload is None or not upload.filename:
        return {"error": "車検証ファイルを選択してください。"}, 400

    filename = upload.filename.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if extension not in {"pdf", "jpg", "jpeg", "png"}:
        return {"error": "PDF・JPEG・PNGに対応しています。"}, 400

    raw = upload.read(max_bytes + 1)
    if not raw:
        return {"error": "ファイルが空です。"}, 400
    if len(raw) > max_bytes:
        return {"error": "ファイルは20MB以下にしてください。"}, 413

    valid_pdf = extension == "pdf" and raw.startswith(b"%PDF-")
    valid_jpeg = extension in {"jpg", "jpeg"} and raw.startswith(b"\xff\xd8\xff")
    valid_png = extension == "png" and raw.startswith(
        b"\x89PNG\r\n\x1a\n"
    )

    if not (valid_pdf or valid_jpeg or valid_png):
        return {"error": "ファイル形式が拡張子と一致しません。"}, 400

    try:
        extraction = extract_vehicle_certificate(raw, filename)

        vehicle_types = [
            item["name"]
            for item in _dkss_vehicle_readers.vehicle_types_for_current_company()
        ]

        prepared = prepare_certificate_form(extraction, vehicle_types)
        try:
            _dkss_knowledge.remember_vehicle_certificate_specification_source(raw, filename, extraction)
        except Exception:
            _dkss_common.db.session.rollback()
            _dkss_runtime.app.logger.exception("Certificate source preservation failed")
            prepared["warnings"].append(
                "原本との照合情報を保存できませんでした。車両情報の確認・登録は続けられます。"
            )

    except ValueError:
        return {
            "error": "車検証を読み取れませんでした。ファイルを確認してください。"
        }, 422
    except RuntimeError:
        return {
            "error": "AI読み取りに失敗しました。時間をおいて再試行してください。"
        }, 502

    response = _dkss_common.jsonify({
        "vehicle": prepared["form"],
        "warnings": prepared["warnings"],
        "needs_review": True,
        "source_filename": filename,
    })
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response, 200



def vehicle_certificate_register():
    """Keep old bookmarks on the current certificate import workflow."""
    from flask import abort

    if not _dkss_common.session.get("username") or not _dkss_common.session.get("company_code"):
        abort(403)

    return _dkss_common.redirect(_dkss_common.url_for(
        "vehicle_registration_method", _anchor="registration-certificate-title",
    ))



def vehicle_registration_method():
    return _dkss_common.render_template(
        "vehicle_registration_method.html",
        offices=_dkss_master_readers.offices_for_current_company(),
        vehicle_types=_dkss_vehicle_readers.vehicle_types_for_current_company(),
    )



def new_vehicle():
    if _dkss_common.request.method == "POST":
        if _dkss_common.request.form.get("vehicle_form_action") == "back":
            return _dkss_common.render_template(
                "vehicle_form.html",
                vehicle=_dkss_common.request.form.to_dict(flat=True),
                offices=_dkss_master_readers.offices_for_current_company(),
                vehicle_types=_dkss_vehicle_readers.vehicle_types_for_current_company(),
                mode="new"
            )

        form_errors = []

        company_code = _dkss_common.session.get("company_code")

        vehicle_count = reserved_vehicle_count(company_code)

        company = _dkss_models.Company.query.filter_by(
            company_code=company_code
        ).first()

        if company:
            if vehicle_count >= company.vehicle_limit:
                return _dkss_http.return_form_errors([
                    ("登録可能台数の上限に達しています。", "")
                ], 409)

        first_registration_date = (
            _dkss_common.request.form.get(
                "first_registration_date",
                ""
            ).strip()
        )

        inspection_expiry = (
            _dkss_common.request.form.get(
                "inspection_expiry",
                ""
            ).strip()
        )

        form_errors.extend(
            validate_vehicle_dates(
                first_registration_date,
                inspection_expiry
            )
        )

        vehicle_type = (
            _dkss_common.request.form.get("type", "").strip()
        )

        office = (
            _dkss_common.request.form.get("office", "").strip()
        )
        chassis_number = (
            _dkss_common.request.form.get("chassis_number", "").strip()
        )

        if not chassis_number:
            form_errors.append((
                "車台番号を入力してください。",
                "chassis_number"
            ))

        duplicate_vehicle = _dkss_models.Vehicle.query.filter_by(
            company_code=company_code,
            chassis_number=chassis_number
        ).first()

        if duplicate_vehicle:
            if not duplicate_vehicle.deleted:
                return _dkss_http.return_form_errors([
                    (
                        "同じ車台番号の車両が既に登録されています。",
                        "chassis_number"
                    )
                ], 409)

        form_errors.extend(
            validate_vehicle_text_fields(_dkss_common.request.form)
        )

        form_errors.extend(
            validate_vehicle_master_values(
                vehicle_type,
                office,
                company_code
            )
        )
        weight_values, weight_errors = parse_vehicle_weights(
            _dkss_common.request.form
        )
        form_errors.extend(weight_errors)

        gross_vehicle_weight = weight_values["gross_vehicle_weight"]
        max_payload = weight_values["max_payload"]

        if form_errors:
            return _dkss_http.return_form_errors(form_errors)

        if _dkss_common.request.headers.get('X-DKSS-Validation-Only') == '1':
            return _dkss_common.jsonify(ok=True)

        if _dkss_common.request.form.get("vehicle_form_action") != "save":
            confirmation_values = _dkss_common.request.form.to_dict(
                flat=True
            )
            confirmation_values.update({
                "chassis_number": chassis_number,
                "first_registration_date": first_registration_date,
                "inspection_expiry": inspection_expiry,
                "gross_vehicle_weight": gross_vehicle_weight,
                "max_payload": max_payload,
                "type": vehicle_type,
                "office": office,
            })

            return _dkss_common.render_template(
                "vehicle_registration_confirm.html",
                vehicle=confirmation_values
            )

        vehicle = duplicate_vehicle or _dkss_models.Vehicle(
            company_code=company_code,
            chassis_number=chassis_number
        )

        vehicle.deleted = False
        apply_vehicle_form_values(
            vehicle,
            _dkss_common.request.form,
            {
                "chassis_number": chassis_number,
                "first_registration_date": first_registration_date,
                "inspection_expiry": inspection_expiry,
                "gross_vehicle_weight": gross_vehicle_weight,
                "max_payload": max_payload,
                "type": vehicle_type,
                "office": office,
            }
        )

        if not duplicate_vehicle:
            _dkss_common.db.session.add(vehicle)
        _dkss_common.db.session.flush()
        _dkss_knowledge.link_vehicle_certificate_specification_source(vehicle)
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/vehicles")

    return _dkss_common.render_template(
        "vehicle_form.html",
        vehicle=_dkss_common.session.pop(
            "vehicle_form_data",
            None
        ),
        offices=_dkss_master_readers.offices_for_current_company(),
        vehicle_types=_dkss_vehicle_readers.vehicle_types_for_current_company(),
        mode="new"
    )



def _vehicle_edit_return_target(candidate, vehicle_id):
    """Keep navigation within vehicle pages; never redirect to a supplied host."""
    from urllib.parse import urlsplit

    default = ("/master/vehicles", "車両マスタへ戻る")
    if not isinstance(candidate, str) or any(
        ord(char) < 32 or ord(char) == 127 or char == "\\"
        for char in candidate
    ):
        return default
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return default
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return default
    if parsed.path == "/master/vehicles":
        label = "車両マスタへ戻る"
    elif parsed.path == "/vehicle/karte":
        label = "車両一覧へ戻る"
    elif parsed.path in {
        f"/vehicle/karte/{vehicle_id}" + suffix
        for suffix in ("", "/history", "/inspections", "/maintenance",
                       "/parts", "/costs", "/documents", "/analysis")
    }:
        label = "車両カルテへ戻る"
    else:
        return default
    return parsed.path + ("?" + parsed.query if parsed.query else ""), label


def edit_vehicle(index):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not vehicle:
        return _dkss_common.redirect("/master/vehicles")

    return_candidate = (
        _dkss_common.request.form.get("return_to")
        if _dkss_common.request.method == "POST"
        else _dkss_common.request.args.get("return_to")
    )
    vehicle_return_url, vehicle_return_label = _vehicle_edit_return_target(
        return_candidate, vehicle.id
    )

    if _dkss_common.request.method == "POST":
        if _dkss_common.request.form.get("vehicle_form_action") == "back":
            form_values = _dkss_common.request.form.to_dict(flat=True)
            form_values["vehicle_record_id"] = vehicle.id

            return _dkss_common.render_template(
                "vehicle_form.html",
                vehicle=form_values,
                index=vehicle.id,
                offices=_dkss_master_readers.offices_for_current_company(),
                vehicle_types=_dkss_vehicle_readers.vehicle_types_for_current_company(),
                mode="edit",
                vehicle_return_url=vehicle_return_url,
                vehicle_return_label=vehicle_return_label
            )

        form_errors = []

        chassis_number = (
            _dkss_common.request.form.get("chassis_number", "").strip()
        )

        if not chassis_number and vehicle.chassis_number:
            form_errors.append((
                "登録済みの車台番号は空欄にできません。訂正する場合は正しい番号を入力してください。",
                "chassis_number"
            ))
        chassis_number = chassis_number or None

        duplicate_vehicle = None
        if chassis_number:
            duplicate_vehicle = _dkss_models.Vehicle.query.filter(
                _dkss_models.Vehicle.company_code == vehicle.company_code,
                _dkss_models.Vehicle.chassis_number == chassis_number,
                _dkss_models.Vehicle.id != vehicle.id
            ).first()

        if duplicate_vehicle:
            return _dkss_http.return_form_errors([
                (
                    "同じ車台番号の車両が既に登録されています。",
                    "chassis_number"
                )
            ], 409)

        first_registration_date = (
            _dkss_common.request.form.get(
                "first_registration_date",
                ""
            ).strip()
        )

        inspection_expiry = (
            _dkss_common.request.form.get(
                "inspection_expiry",
                ""
            ).strip()
        )

        form_errors.extend(
            validate_vehicle_dates(
                first_registration_date,
                inspection_expiry
            )
        )

        vehicle_type = (
            _dkss_common.request.form.get("type", "").strip()
        )

        office = (
            _dkss_common.request.form.get("office", "").strip()
        )

        form_errors.extend(
            validate_vehicle_text_fields(_dkss_common.request.form)
        )


        form_errors.extend(
            validate_vehicle_master_values(
                vehicle_type,
                office,
                vehicle.company_code
            )
        )
        weight_values, weight_errors = parse_vehicle_weights(
            _dkss_common.request.form
        )
        form_errors.extend(weight_errors)
        for field in ("gross_vehicle_weight", "max_payload"):
            if not _dkss_common.request.form.get(field, "").strip() and getattr(vehicle, field) is None:
                weight_values[field] = None

        gross_vehicle_weight = weight_values["gross_vehicle_weight"]
        max_payload = weight_values["max_payload"]

        if form_errors:
            return _dkss_http.return_form_errors(form_errors)

        if _dkss_common.request.form.get("vehicle_form_action") != "save":
            confirmation_values = _dkss_common.request.form.to_dict(
                flat=True
            )
            confirmation_values.update({
                "chassis_number": chassis_number,
                "first_registration_date": first_registration_date,
                "inspection_expiry": inspection_expiry,
                "gross_vehicle_weight": gross_vehicle_weight,
                "max_payload": max_payload,
                "type": vehicle_type,
                "office": office,
            })

            previous_values = {
                field_key: getattr(vehicle, field_key)
                for field_key in [
                    "plate_area",
                    "plate_class",
                    "plate_kana",
                    "plate_number",
                    "chassis_number",
                    "model_code",
                    "first_registration_date",
                    "manufacturer",
                    "body_type",
                    "gross_vehicle_weight",
                    "max_payload",
                    "type",
                    "office",
                    "inspection_expiry",
                ]
            }

            previous_values.update({
                key: getattr(vehicle, key, None)
                for key, label, limit in _dkss_common.VEHICLE_MAINTENANCE_ATTRIBUTE_FIELDS
            })

            return _dkss_common.render_template(
                "vehicle_edit_confirm.html",
                vehicle=confirmation_values,
                previous_vehicle=previous_values,
                index=vehicle.id,
                vehicle_return_url=vehicle_return_url,
                vehicle_return_label=vehicle_return_label
            )

        apply_vehicle_form_values(
            vehicle,
            _dkss_common.request.form,
            {
                "chassis_number": chassis_number,
                "first_registration_date": first_registration_date,
                "inspection_expiry": inspection_expiry,
                "gross_vehicle_weight": gross_vehicle_weight,
                "max_payload": max_payload,
                "type": vehicle_type,
                "office": office,
            }
        )

        _dkss_common.db.session.flush()
        _dkss_knowledge.link_vehicle_certificate_specification_source(vehicle)
        _dkss_common.db.session.commit()

        return _dkss_common.redirect(vehicle_return_url)

    vehicle_dict = {
        "vehicle_record_id": vehicle.id,
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
        "number": _dkss_vehicle_readers.vehicle_number({
            "chassis_number": vehicle.chassis_number,
            "plate_area": vehicle.plate_area,
            "plate_class": vehicle.plate_class,
            "plate_kana": vehicle.plate_kana,
            "plate_number": vehicle.plate_number,
        }),
        "type": vehicle.type,
        "office": vehicle.office,
        "inspection_expiry": vehicle.inspection_expiry,
    }

    vehicle_dict.update({
        key: getattr(vehicle, key, None)
        for key, label, limit in _dkss_common.VEHICLE_MAINTENANCE_ATTRIBUTE_FIELDS
    })

    vehicle_dict = {
        key: "" if value is None else value
        for key, value in vehicle_dict.items()
    }
    vehicle_edit_form_data = _dkss_common.session.pop(
        "vehicle_edit_form_data",
        {}
    )

    if vehicle_edit_form_data:
        vehicle_dict.update(vehicle_edit_form_data)

    return _dkss_common.render_template(
        "vehicle_form.html",
        vehicle=vehicle_dict,
        index=vehicle.id,
        offices=_dkss_master_readers.offices_for_current_company(),
        vehicle_types=_dkss_vehicle_readers.vehicle_types_for_current_company(),
        mode="edit",
        vehicle_return_url=vehicle_return_url,
        vehicle_return_label=vehicle_return_label
    )



def toggle_vehicle_inactive(index):

    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not vehicle:
        return _dkss_common.redirect("/master/vehicles")

    if vehicle.deleted is None:
        return UNKNOWN_VEHICLE_STATE, 409

    new_inactive = (
        _dkss_common.request.form.get("inactive") == "1"
    )

    # 無効から有効へ戻す場合は登録上限を確認
    if vehicle.deleted and not new_inactive:
        company = _dkss_models.Company.query.filter_by(
            company_code=vehicle.company_code
        ).first()

        current_active_count = reserved_vehicle_count(vehicle.company_code)

        if (
            company
            and current_active_count >= company.vehicle_limit
        ):
            return (
                f"登録上限を超えるため有効化できません。"
                f"現在の上限判定台数（状態未確認を含む） {current_active_count} 台、"
                f"上限 {company.vehicle_limit} 台です。"
            )

    vehicle.deleted = new_inactive

    _dkss_common.db.session.commit()

    return _dkss_common.redirect("/master/vehicles")



def bulk_delete_vehicles():

    vehicle_indexes = _dkss_common.request.form.getlist("vehicle_ids")

    if len(vehicle_indexes) > 1000:
        return "一度に処理できる車両は1000件までです。", 400

    if not vehicle_indexes:
        return _dkss_common.redirect("/master/vehicles")

    company_code = _dkss_common.session.get("company_code")

    vehicles_to_delete = _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.id.in_(vehicle_indexes),
        _dkss_models.Vehicle.company_code == company_code
    ).all()

    if not vehicles_to_delete:
        return _dkss_common.redirect("/master/vehicles")

    vehicle_record_ids_to_delete = {
        vehicle.id
        for vehicle in vehicles_to_delete
    }

    related_records = (
        (_dkss_models.VehiclePatrol, "vehicle_record_id"),
        (_dkss_models.VehicleChecklistResult, "vehicle_record_id"),
        (_dkss_models.ChecklistResult, "target_vehicle_record_id"),
        (_dkss_models.VehicleDrivingReportRecord, "vehicle_record_id"),
        (_dkss_models.VehiclePeriodicInspectionRecord, "vehicle_record_id"),
        (_dkss_models.VehicleOperationRecord, "vehicle_record_id"),
        (_dkss_models.VehicleMaintenanceRecord, "vehicle_record_id"),
        (_dkss_models.VehicleMaintenanceDocument, "vehicle_record_id"),
        (_dkss_models.VehicleOperationVehicleMapping, "vehicle_record_id"),
        (_dkss_models.VehicleImportPending, "resolved_vehicle_id"),
        (_dkss_models.VehicleImportPendingRecord, "vehicle_record_id"),
    )

    for model, vehicle_field in related_records:
        related_record = model.query.filter(
            model.company_code == company_code,
            getattr(model, vehicle_field).in_(
                vehicle_record_ids_to_delete
            )
        ).first()

        if related_record:
            return _dkss_http.return_form_errors([
                (
                    "履歴または運行実績の対応付けがある車両を"
                    "含むため完全削除できません。"
                    "対象車両は無効化してください。",
                    ""
                )
            ], status_code=409)

    delete_vehicle_patterns = [
        f'"{vehicle_record_id}"'
        for vehicle_record_id in vehicle_record_ids_to_delete
    ]


    # ドライバーの車両割当から削除
    driver_query = _dkss_models.Driver.query.filter(
        _dkss_models.Driver.company_code == company_code
    )

    if delete_vehicle_patterns:
        driver_query = driver_query.filter(
            _dkss_common.db.or_(
                *[
                    _dkss_models.Driver.vehicles_json.contains(pattern)
                    for pattern in delete_vehicle_patterns
                ]
            )
        )

    for driver in driver_query.all():

        driver_vehicles = _dkss_serialization.safe_json_str_list(
            driver.vehicles_json
        )

        new_driver_vehicles = [
            vehicle_record_id
            for vehicle_record_id in driver_vehicles
            if vehicle_record_id not in {
                str(record_id)
                for record_id in vehicle_record_ids_to_delete
            }
        ]

        if new_driver_vehicles != driver_vehicles:

            driver.vehicles_json = _dkss_common.json.dumps(
                new_driver_vehicles,
                ensure_ascii=False
            )
    # 車両に紐づく通知設定を削除してから車両本体を完全削除
    for vehicle in vehicles_to_delete:

        _dkss_vehicle_readers.delete_vehicle_related_data(vehicle)

        _dkss_audit.add_audit_log(
            action="vehicle_deleted",
            target_type="vehicle",
            target_id=vehicle.id,
            detail="車両一括削除による完全削除",
            company_code=vehicle.company_code,
        )

        _dkss_common.db.session.delete(vehicle)


    _dkss_common.db.session.commit()

    return _dkss_common.redirect("/master/vehicles")



def bulk_inactive_vehicles():

    company_code = _dkss_common.session.get("company_code")

    vehicle_indexes = _dkss_common.request.form.getlist("vehicle_ids")

    if len(vehicle_indexes) > 1000:
        return "一度に処理できる車両は1000件までです。", 400

    if not vehicle_indexes:
        return _dkss_common.redirect("/master/vehicles")

    vehicles_to_inactivate = _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.id.in_(vehicle_indexes),
        _dkss_models.Vehicle.company_code == company_code,
        _dkss_models.Vehicle.deleted == False
    ).all()

    _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.id.in_(vehicle_indexes),
        _dkss_models.Vehicle.company_code == company_code
    ).update(
        {"deleted": True},
        synchronize_session=False
    )

    for vehicle in vehicles_to_inactivate:
        _dkss_audit.add_audit_log(
            action="vehicle_inactivated",
            target_type="vehicle",
            target_id=vehicle.id,
            detail="車両を一括無効化",
            company_code=vehicle.company_code,
        )

    _dkss_common.db.session.commit()

    return _dkss_common.redirect("/master/vehicles")



def bulk_active_vehicles():

    company_code = _dkss_common.session.get("company_code")
    vehicle_indexes = _dkss_common.request.form.getlist("vehicle_ids")

    if len(vehicle_indexes) > 1000:
        return "一度に処理できる車両は1000件までです。", 400

    if not vehicle_indexes:
        return _dkss_common.redirect("/master/vehicles")

    if _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.company_code == company_code,
        _dkss_models.Vehicle.id.in_(vehicle_indexes),
        _dkss_models.Vehicle.deleted.is_(None),
    ).first():
        return UNKNOWN_VEHICLE_STATE, 409

    vehicles_to_activate = _dkss_models.Vehicle.query.filter(
        _dkss_models.Vehicle.id.in_(vehicle_indexes),
        _dkss_models.Vehicle.company_code == company_code,
        _dkss_models.Vehicle.deleted == True
    ).all()

    if not vehicles_to_activate:
        return _dkss_common.redirect("/master/vehicles")

    company = _dkss_models.Company.query.filter_by(
        company_code=company_code
    ).first()

    current_active_count = reserved_vehicle_count(company_code)

    activate_count = len(vehicles_to_activate)

    if (
        company
        and current_active_count + activate_count
        > company.vehicle_limit
    ):
        return (
            f"登録上限を超えるため有効化できません。"
            f"現在の上限判定台数（状態未確認を含む） {current_active_count} 台、"
            f"有効化予定 {activate_count} 台、"
            f"上限 {company.vehicle_limit} 台です。"
        )

    for vehicle in vehicles_to_activate:
        vehicle.deleted = False

    for vehicle in vehicles_to_activate:
        _dkss_audit.add_audit_log(
            action="vehicle_activated",
            target_type="vehicle",
            target_id=vehicle.id,
            detail="車両を一括有効化",
            company_code=vehicle.company_code,
        )

    _dkss_common.db.session.commit()

    return _dkss_common.redirect("/master/vehicles")



def delete_vehicle(index):
    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not vehicle:
        return _dkss_common.redirect("/master/vehicles")

    vehicle_record_id = vehicle.id

    related_records = (
        (_dkss_models.VehiclePatrol, "vehicle_record_id"),
        (_dkss_models.VehicleChecklistResult, "vehicle_record_id"),
        (_dkss_models.ChecklistResult, "target_vehicle_record_id"),
        (_dkss_models.VehicleDrivingReportRecord, "vehicle_record_id"),
        (_dkss_models.VehiclePeriodicInspectionRecord, "vehicle_record_id"),
        (_dkss_models.VehicleOperationRecord, "vehicle_record_id"),
        (_dkss_models.VehicleMaintenanceRecord, "vehicle_record_id"),
        (_dkss_models.VehicleMaintenanceDocument, "vehicle_record_id"),
        (_dkss_models.VehicleOperationVehicleMapping, "vehicle_record_id"),
    )

    for model, vehicle_field in related_records:
        related_record = model.query.filter_by(
            company_code=vehicle.company_code,
            **{vehicle_field: vehicle_record_id}
        ).first()

        if related_record:
            return _dkss_http.return_form_errors([
                (
                    "履歴または運行実績の対応付けがある車両は"
                    "完全削除できません。無効化してください。",
                    ""
                )
            ], status_code=409)

    vehicle_record_id_str = str(vehicle_record_id)

    for driver in _dkss_models.Driver.query.filter(
        _dkss_models.Driver.company_code == vehicle.company_code,
        _dkss_models.Driver.vehicles_json.contains(f'"{vehicle_record_id_str}"')
    ).all():
        vehicles = _dkss_serialization.safe_json_str_list(
            driver.vehicles_json
        )

        if vehicle_record_id_str in vehicles:
            vehicles.remove(vehicle_record_id_str)
            driver.vehicles_json = _dkss_common.json.dumps(
                vehicles,
                ensure_ascii=False
            )
    # 車両に紐づく通知設定を削除
    _dkss_vehicle_readers.delete_vehicle_related_data(vehicle)

    _dkss_audit.add_audit_log(
        action="vehicle_deleted",
        target_type="vehicle",
        target_id=vehicle.id,
        detail="車両を完全削除",
        company_code=vehicle.company_code,
    )

    # 車両本体を完全削除
    _dkss_common.db.session.delete(vehicle)

    _dkss_common.db.session.commit()
    return _dkss_common.redirect("/master/vehicles")
