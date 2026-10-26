"""Vehicle Operations responsibilities; routes are registered by the application factory."""
from . import analysis as _dkss_analysis, common as _dkss_common, models as _dkss_models, vehicle_readers as _dkss_vehicle_readers


def get_vehicle_operation_import_submission(
    csv_rows,
    company_code,
    form_data,
    allow_pending=False,
    keep_unassigned=False
):
    selected_lines = set(form_data.getlist("include"))
    known_lines = {
        str(row["line_number"])
        for row in csv_rows
    }

    errors = []
    selections = {}
    records = []
    selected_reports = {}

    if not selected_lines:
        errors.append((
            "取り込む行にチェックを付けてください。",
            ""
        ))

    if not selected_lines.issubset(known_lines):
        errors.append((
            "取込対象の行を確認してください。",
            ""
        ))

    valid_vehicle_ids = {
        vehicle.id
        for vehicle in _dkss_models.Vehicle.query.filter_by(
            company_code=company_code
        ).all()
    }

    for csv_row in csv_rows:
        line_number = csv_row["line_number"]
        line_key = str(line_number)
        field_name = f"vehicle_{line_number}"
        selected = line_key in selected_lines

        vehicle_id_text = str(
            form_data.get(field_name, "")
        ).strip()

        vehicle_id = None

        if _dkss_common.re.fullmatch(r"[1-9][0-9]{0,17}", vehicle_id_text):
            candidate_id = int(vehicle_id_text)

            if candidate_id in valid_vehicle_ids:
                vehicle_id = candidate_id

        selections[line_key] = {
            "include": selected,
            "vehicle_record_id": vehicle_id,
        }

        if not selected:
            continue

        if vehicle_id is None and not (
            keep_unassigned and not vehicle_id_text
        ):
            if allow_pending and not vehicle_id_text:
                continue

            errors.append((
                f"{line_number}行目の登録先車両を選択してください。",
                field_name
            ))
            continue

        try:
            values = _dkss_common.parse_vehicle_operation_csv_row(
                csv_row["source_row"],
                line_number
            )
        except _dkss_common.UploadValidationError as error:
            errors.append((
                str(error),
                f"include_{line_number}"
            ))
            continue

        report_number = values["report_number"]

        if report_number in selected_reports:
            errors.append((
                f"{line_number}行目の日報番号は"
                f"{selected_reports[report_number]}行目と重複しています。"
                "取り込む行を1つだけ選択してください。",
                f"include_{line_number}"
            ))
            continue

        selected_reports[report_number] = line_number

        records.append({
            "line_number": line_number,
            "vehicle_record_id": vehicle_id,
            "values": values,
        })

    if allow_pending and not records and not errors:
        errors.append((
            "登録先が決まった実績がありません。登録先を選択するか、車両を追加してください。",
            ""
        ))

    return selections, records, errors



def build_vehicle_operation_import_preview(csv_rows, company_code):
    if not company_code:
        raise _dkss_common.UploadValidationError(
            "会社情報を確認できませんでした。"
        )

    vehicles, plate_candidates = (
        get_vehicle_operation_plate_candidates(company_code)
    )

    saved_vehicle_mappings = {}
    valid_vehicle_ids = {vehicle.id for vehicle in vehicles}

    mappings = (
        _dkss_models.VehicleOperationVehicleMapping.query
        .filter_by(company_code=company_code)
        .all()
    )

    for mapping in mappings:
        source_number = _dkss_common.normalize_vehicle_operation_plate(
            mapping.source_vehicle_number
        )

        if mapping.vehicle_record_id not in valid_vehicle_ids:
            continue

        mapping_key = (
            (mapping.source_vehicle_code or "").strip(),
            source_number,
        )
        saved_vehicle_mappings[mapping_key] = (
            mapping.vehicle_record_id
        )

    report_counts = {}

    for csv_row in csv_rows:
        report_number = (
            csv_row["source_row"]
            .get("日報番号", "")
            .strip()
        )

        if report_number:
            report_counts[report_number] = (
                report_counts.get(report_number, 0) + 1
            )

    report_numbers = sorted(report_counts)
    existing_records = {}

    for start in range(0, len(report_numbers), 400):
        records = (
            _dkss_models.VehicleOperationRecord.query
            .filter(
                _dkss_models.VehicleOperationRecord.company_code == company_code,
                _dkss_models.VehicleOperationRecord.report_number.in_(
                    report_numbers[start:start + 400]
                )
            )
            .all()
        )

        for record in records:
            existing_records[record.report_number] = record.id

    preview_rows = []

    for csv_row in csv_rows:
        source_row = csv_row["source_row"]
        line_number = csv_row["line_number"]
        report_number = source_row.get("日報番号", "").strip()

        preview_row = {
            "line_number": line_number,
            "source_row": source_row,
            "values": {},
            "vehicle_record_id": None,
            "candidate_vehicle_ids": [],
            "duplicate_in_file": (
                report_counts.get(report_number, 0) > 1
            ),
            "existing_record_id": existing_records.get(
                report_number
            ),
            "errors": [],
        }

        try:
            values = _dkss_common.parse_vehicle_operation_csv_row(
                source_row,
                line_number
            )
        except _dkss_common.UploadValidationError as error:
            preview_row["errors"].append(str(error))
        else:
            values.pop("source_row_json", None)

            for field_name in (
                "departure_meter",
                "arrival_meter",
                "distance",
            ):
                if values[field_name] is not None:
                    values[field_name] = str(values[field_name])

            preview_row["values"] = values

            plate = _dkss_common.normalize_vehicle_operation_plate(
                values.get("source_vehicle_number")
            )
            candidate_ids = plate_candidates.get(plate, [])

            preview_row["candidate_vehicle_ids"] = list(
                candidate_ids
            )

            mapping_key = (
                str(
                    values.get("source_vehicle_code") or ""
                ).strip(),
                plate,
            )
            mapped_vehicle_id = saved_vehicle_mappings.get(
                mapping_key
            )

            if mapped_vehicle_id is not None:
                preview_row["vehicle_record_id"] = (
                    mapped_vehicle_id
                )
            elif len(candidate_ids) == 1:
                preview_row["vehicle_record_id"] = (
                    candidate_ids[0]
                )

        preview_rows.append(preview_row)

    return vehicles, preview_rows



def get_vehicle_operation_summary(company_code, vehicle_record_id):
    operations = _dkss_models.VehicleOperationRecord.query.filter_by(company_code=company_code, vehicle_record_id=vehicle_record_id).all()
    operations = get_vehicle_canonical_operations(company_code, vehicle_record_id, operations)
    maintenance = _dkss_models.VehicleMaintenanceRecord.query.filter_by(company_code=company_code, vehicle_record_id=vehicle_record_id).all()
    periodic = _dkss_models.VehiclePeriodicInspectionRecord.query.filter_by(company_code=company_code, vehicle_record_id=vehicle_record_id).all()
    reference = _dkss_analysis.build_vehicle_karte_mileage_reference(maintenance, operations, _dkss_common.datetime.now(_dkss_common.ZoneInfo('Asia/Tokyo')).date().isoformat(), periodic_records=periodic)
    return {'current_mileage': reference['value'], 'mileage_date': reference['date'], 'mileage_reference': reference}



def get_vehicle_registration_plate_conflicts(
    company_code,
    plate_area,
    plate_class,
    plate_kana,
    plate_number,
    chassis_number,
    exclude_vehicle_id=None,
    existing_vehicles=None
):
    plate_parts = (
        plate_area,
        plate_class,
        plate_kana,
        plate_number,
    )
    normalized_parts = tuple(
        _dkss_common.normalize_vehicle_operation_plate(value)
        for value in plate_parts
    )

    # 不完全なナンバーから同一車両と判断しない
    if not all(normalized_parts):
        return []

    if existing_vehicles is None:
        existing_vehicles = _dkss_models.Vehicle.query.filter_by(
            company_code=company_code
        ).order_by(_dkss_models.Vehicle.id.asc()).all()

    conflicts = []

    for vehicle in existing_vehicles:
        if vehicle.company_code != company_code:
            continue

        if vehicle.id == exclude_vehicle_id:
            continue
        existing_parts = tuple(
            _dkss_common.normalize_vehicle_operation_plate(value)
            for value in (
                vehicle.plate_area,
                vehicle.plate_class,
                vehicle.plate_kana,
                vehicle.plate_number,
            )
        )

        if existing_parts != normalized_parts:
            continue

        if (
            str(vehicle.chassis_number or "").strip()
            == str(chassis_number or "").strip()
        ):
            continue

        conflicts.append({
            "id": vehicle.id,
            "chassis_number": vehicle.chassis_number or "",
            "office": vehicle.office or "",
            "inactive": bool(vehicle.deleted),
        })

    return conflicts



def get_vehicle_operation_plate_candidates(company_code):
    vehicles = (
        _dkss_models.Vehicle.query
        .filter_by(
            company_code=company_code
        )
        .order_by(_dkss_models.Vehicle.id.asc())
        .all()
    )

    plate_candidates = {}

    for vehicle in vehicles:
        if not all((
            vehicle.plate_area,
            vehicle.plate_class,
            vehicle.plate_kana,
            vehicle.plate_number,
        )):
            continue

        plate = _dkss_common.normalize_vehicle_operation_plate(
            _dkss_vehicle_readers.vehicle_number({
                "plate_area": vehicle.plate_area,
                "plate_class": vehicle.plate_class,
                "plate_kana": vehicle.plate_kana,
                "plate_number": vehicle.plate_number,
            })
        )

        if plate:
            plate_candidates.setdefault(
                plate,
                []
            ).append(vehicle.id)

    return vehicles, plate_candidates


def get_vehicle_driving_report_summary(company_code, vehicle_record_id, start=None, end=None):
    from driving_report_data import metrics_summary
    rows = _dkss_models.VehicleDrivingReportRecord.query.filter_by(company_code=company_code, vehicle_record_id=vehicle_record_id).all()
    if start:
        rows = [r for r in rows if r.operation_date and r.operation_date >= start]
    if end:
        rows = [r for r in rows if r.operation_date and r.operation_date <= end]
    return metrics_summary(rows)


def get_vehicle_canonical_operations(company_code, vehicle_record_id, operations=None, end=None):
    from driving_report_data import canonical_operations
    if operations is None:
        operations = _dkss_models.VehicleOperationRecord.query.filter_by(company_code=company_code, vehicle_record_id=vehicle_record_id).all()
    reports = _dkss_models.VehicleDrivingReportRecord.query.filter_by(company_code=company_code, vehicle_record_id=vehicle_record_id).all()
    if end:
        reports = [r for r in reports if r.operation_date and r.operation_date <= end]
    return canonical_operations(operations, reports)
