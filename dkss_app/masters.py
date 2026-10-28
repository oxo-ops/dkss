"""Masters responsibilities; routes are registered by the application factory."""
from functools import wraps

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from . import audit as _dkss_audit, auth as _dkss_auth, common as _dkss_common, http as _dkss_http, master_readers as _dkss_master_readers, models as _dkss_models, runtime as _dkss_runtime, serialization as _dkss_serialization, storage as _dkss_storage, vehicle_readers as _dkss_vehicle_readers


def _master_write_conflicts(view):
    """Roll back expected write conflicts, including autoflush during a query."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except IntegrityError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            known_name_conflict = constraint in {
                "uq_office_company_name", "uq_vehicle_type_company_name"
            } or str(error.orig) in {
                "UNIQUE constraint failed: office.company_code, office.name",
                "UNIQUE constraint failed: vehicle_type.company_code, vehicle_type.name",
            }
            if not known_name_conflict or _dkss_common.request.method != "POST":
                raise
            _dkss_common.db.session.rollback()
            return "同じ名称が登録されています。一覧を再読み込みしてください。", 409
        except StaleDataError:
            if _dkss_common.request.method != "POST":
                raise
            _dkss_common.db.session.rollback()
            return "別の操作で更新されています。一覧を再読み込みしてください。", 409
    return wrapped


def _master_row(model, index):
    query = model.query.filter_by(
        id=index, company_code=_dkss_common.session.get("company_code")
    )
    if _dkss_common.request.method == "POST":
        # Hold the row until commit/teardown. A waiting writer must use the
        # committed name, not an instance previously loaded into this session.
        query = query.populate_existing().with_for_update()
    return query.first()


def vehicle_type_master():
    return _dkss_common.render_template(
        "vehicle_type_master.html",
        vehicle_types=_dkss_vehicle_readers.vehicle_types_for_current_company()
    )



def license_type_master():
    return _dkss_common.render_template(
        "license_type_master.html",
        license_types=_dkss_vehicle_readers.license_types_for_current_company()
    )



def new_license_type():
    if _dkss_common.request.method == "POST":

        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            return "免許種別名を入力してください。", 400

        if len(name) > 100:
            return "免許種別名は100文字以内で入力してください。", 400

        if _dkss_models.LicenseType.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            name=name
        ).first():
            return "この免許種別はすでに登録されています。", 409

        license_type = _dkss_models.LicenseType(
            company_code=_dkss_common.session.get("company_code"),
            name=name
        )

        _dkss_common.db.session.add(license_type)
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/license-types")

    return _dkss_common.render_template(
        "license_type_form.html",
        license_type=None,
        mode="new"
    )



def edit_license_type(index):
    license_type = _dkss_models.LicenseType.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not license_type:
        return _dkss_common.redirect("/master/license-types")

    if _dkss_common.request.method == "POST":

        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            return "免許種別名を入力してください。", 400

        if len(name) > 100:
            return "免許種別名は100文字以内で入力してください。", 400

        duplicate_license_type = _dkss_models.LicenseType.query.filter(
            _dkss_models.LicenseType.company_code == license_type.company_code,
            _dkss_models.LicenseType.name == name,
            _dkss_models.LicenseType.id != license_type.id
        ).first()

        if duplicate_license_type:
            return "この免許種別はすでに登録されています。", 409

        old_name = license_type.name

        drivers = _dkss_models.Driver.query.filter_by(
            company_code=license_type.company_code
        ).all()

        for driver in drivers:
            licenses = _dkss_serialization.safe_json_dict_list(
                driver.licenses_json
            )

            changed = False

            for license in licenses:
                if license.get("type") == old_name:
                    license["type"] = name
                    changed = True

            if changed:
                driver.licenses_json = _dkss_common.json.dumps(
                    licenses,
                    ensure_ascii=False
                )

        license_type.name = name

        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/license-types")

    return _dkss_common.render_template(
        "license_type_form.html",
        license_type={
            "id": license_type.id,
            "name": license_type.name
        },
        mode="edit"
    )



def delete_license_type(index):
    license_type = _dkss_models.LicenseType.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not license_type:
        return _dkss_common.redirect("/master/license-types")

    license_type_in_use = any(
        any(
            license.get("type") == license_type.name
            for license in _dkss_serialization.safe_json_dict_list(
                driver.licenses_json
            )
        )
        for driver in _dkss_models.Driver.query.filter_by(
            company_code=license_type.company_code
        ).all()
    )

    if license_type_in_use:
        return (
            "ドライバーに登録されている免許種別は削除できません。",
            409
        )

    _dkss_audit.add_audit_log(
        action="license_type_deleted",
        target_type="license_type",
        target_id=license_type.id,
        detail=f"免許種別削除: {license_type.name}",
        company_code=license_type.company_code,
    )

    _dkss_master_readers.remove_master_from_display_order("license-types", license_type)
    _dkss_common.db.session.delete(license_type)
    _dkss_common.db.session.commit()

    return _dkss_common.redirect("/master/license-types")



@_master_write_conflicts
def new_vehicle_type():
    if _dkss_common.request.method == "POST":
        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            return "車種名を入力してください。", 400

        if len(name) > 100:
            return "車種名は100文字以内で入力してください。", 400

        if _dkss_models.VehicleType.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            name=name
        ).first():
            return "この車種はすでに登録されています。", 409

        vehicle_type = _dkss_models.VehicleType(
            company_code=_dkss_common.session.get("company_code"),
            name=name
        )

        _dkss_common.db.session.add(vehicle_type)
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/vehicle-types")

    return _dkss_common.render_template(
        "vehicle_type_form.html",
        vehicle_type=None,
        mode="new"
    )



@_master_write_conflicts
def edit_vehicle_type(index):
    vehicle_type = _master_row(_dkss_models.VehicleType, index)

    if not vehicle_type:
        return _dkss_common.redirect("/master/vehicle-types")

    if _dkss_common.request.method == "POST":
        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            return "車種名を入力してください。", 400

        if len(name) > 100:
            return "車種名は100文字以内で入力してください。", 400

        duplicate_vehicle_type = _dkss_models.VehicleType.query.filter(
            _dkss_models.VehicleType.company_code == vehicle_type.company_code,
            _dkss_models.VehicleType.name == name,
            _dkss_models.VehicleType.id != vehicle_type.id
        ).first()

        if duplicate_vehicle_type:
            return "この車種はすでに登録されています。", 409

        old_name = vehicle_type.name

        _dkss_models.Vehicle.query.filter_by(
            company_code=vehicle_type.company_code,
            type=old_name
        ).update(
            {"type": name},
            synchronize_session=False
        )

        _dkss_models.VehicleTypeImportMapping.query.filter_by(
            company_code=vehicle_type.company_code,
            vehicle_type_name=old_name
        ).update(
            {"vehicle_type_name": name},
            synchronize_session=False
        )

        vehicle_type.name = name
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/vehicle-types")

    return _dkss_common.render_template(
        "vehicle_type_form.html",
        vehicle_type={
            "id": vehicle_type.id,
            "name": vehicle_type.name
        },
        mode="edit"
    )



@_master_write_conflicts
def delete_vehicle_type(index):
    vehicle_type = _master_row(_dkss_models.VehicleType, index)

    if not vehicle_type:
        return _dkss_common.redirect("/master/vehicle-types")

    _dkss_models.Vehicle.query.filter_by(
        company_code=vehicle_type.company_code,
        type=vehicle_type.name
    ).update(
        {"type": ""},
        synchronize_session=False
    )

    _dkss_models.VehicleTypeImportMapping.query.filter_by(
        company_code=vehicle_type.company_code,
        vehicle_type_name=vehicle_type.name
    ).delete(synchronize_session=False)

    _dkss_audit.add_audit_log(
        action="vehicle_type_deleted",
        target_type="vehicle_type",
        target_id=vehicle_type.id,
        detail=f"車種削除: {vehicle_type.name}",
        company_code=vehicle_type.company_code,
    )

    _dkss_master_readers.remove_master_from_display_order("vehicle-types", vehicle_type)
    _dkss_common.db.session.delete(vehicle_type)
    _dkss_common.db.session.commit()

    return _dkss_common.redirect("/master/vehicle-types")



def master():
    return _dkss_common.redirect(_dkss_common.url_for("vehicle_master"))



def office_master():
    return _dkss_common.render_template(
        "office_master.html",
        offices=_dkss_master_readers.offices_for_current_company()
    )



@_master_write_conflicts
def new_office():
    if _dkss_common.request.method == "POST":
        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            return "営業所名を入力してください。", 400

        if len(name) > 100:
            return "営業所名は100文字以内で入力してください。", 400

        if _dkss_models.Office.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            name=name
        ).first():
            return "この営業所はすでに登録されています。", 409

        office = _dkss_models.Office(
            company_code=_dkss_common.session.get("company_code"),
            name=name
        )

        _dkss_common.db.session.add(office)
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/offices")

    return _dkss_common.render_template(
        "office_form.html",
        office=None,
        index=None,
        mode="new"
    )



@_master_write_conflicts
def edit_office(index):
    office = _master_row(_dkss_models.Office, index)

    if not office:
        return _dkss_common.redirect("/master/offices")

    if _dkss_common.request.method == "POST":
        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            return "営業所名を入力してください。", 400

        if len(name) > 100:
            return "営業所名は100文字以内で入力してください。", 400

        if name != office.name:
            duplicate_office = _dkss_models.Office.query.filter(
                _dkss_models.Office.company_code == office.company_code,
                _dkss_models.Office.name == name,
                _dkss_models.Office.id != office.id
            ).first()

            if duplicate_office:
                return "この営業所はすでに登録されています。", 409

            patrol_in_use = _dkss_models.PatrolResult.query.filter_by(
                company_code=office.company_code,
                office=office.name
            ).first()

            checklist_in_use = _dkss_models.ChecklistResult.query.filter_by(
                company_code=office.company_code,
                target_office=office.name
            ).first()

            news_in_use = _dkss_models.News.query.filter_by(
                company_code=office.company_code,
                target_type="office",
                target_value=office.name
            ).first()

            if patrol_in_use or checklist_in_use or news_in_use:
                return (
                    "履歴またはお知らせで使用されている営業所は変更できません。",
                    409
                )

            old_name = office.name

            _dkss_models.Driver.query.filter_by(
                company_code=office.company_code,
                office=old_name
            ).update(
                {"office": name},
                synchronize_session=False
            )

            _dkss_models.User.query.filter_by(
                company_code=office.company_code,
                office=old_name
            ).update(
                {"office": name},
                synchronize_session=False
            )

            _dkss_models.Vehicle.query.filter_by(
                company_code=office.company_code,
                office=old_name
            ).update(
                {"office": name},
                synchronize_session=False
            )

        office.name = name
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/offices")

    office_dict = {
        "id": office.id,
        "index": office.id,
        "company_code": office.company_code,
        "name": office.name
    }

    return _dkss_common.render_template(
        "office_form.html",
        office=office_dict,
        index=office.id,
        mode="edit"
    )



@_master_write_conflicts
def delete_office(index):
    office = _master_row(_dkss_models.Office, index)

    if not office:
        return _dkss_common.redirect("/master/offices")

    patrol_in_use = _dkss_models.PatrolResult.query.filter_by(
        company_code=office.company_code,
        office=office.name
    ).first()

    checklist_in_use = _dkss_models.ChecklistResult.query.filter_by(
        company_code=office.company_code,
        target_office=office.name
    ).first()

    news_in_use = _dkss_models.News.query.filter_by(
        company_code=office.company_code,
        target_type="office",
        target_value=office.name
    ).first()

    if patrol_in_use or checklist_in_use or news_in_use:
        return (
            "履歴またはお知らせで使用されている営業所は削除できません。",
            409
        )

    _dkss_models.Driver.query.filter_by(
        company_code=office.company_code,
        office=office.name
    ).update(
        {"office": ""},
        synchronize_session=False
    )

    _dkss_models.User.query.filter_by(
        company_code=office.company_code,
        office=office.name
    ).update(
        {"office": ""},
        synchronize_session=False
    )

    _dkss_models.Vehicle.query.filter_by(
        company_code=office.company_code,
        office=office.name
    ).update(
        {"office": ""},
        synchronize_session=False
    )

    _dkss_audit.add_audit_log(
        action="office_deleted",
        target_type="office",
        target_id=office.id,
        detail=f"営業所削除: {office.name}",
        company_code=office.company_code,
    )

    _dkss_master_readers.remove_master_from_display_order("offices", office)
    _dkss_common.db.session.delete(office)
    _dkss_common.db.session.commit()

    return _dkss_common.redirect("/master/offices")



def import_delivery_places():

    if _dkss_common.request.method == "POST":

        excel_file = _dkss_common.request.files.get("excel_file")

        if not excel_file or not excel_file.filename:
            return "Excelファイルを選択してください。", 400

        if not excel_file.filename.lower().endswith(".xlsx"):
            return "xlsx形式のExcelファイルを選択してください。", 400

        if not _dkss_storage.is_valid_uploaded_file(
            excel_file,
            ".xlsx"
        ):
            return "Excelファイルの内容が不正です。", 400

        try:
            workbook = _dkss_common.load_workbook(
                excel_file,
                data_only=True
            )
        except Exception:
            return "Excelファイルを読み込めませんでした。", 400

        sheet = workbook.active

        if sheet.max_row > 5000:
            return (
                "一度に読み込めるExcelは5000行までです。",
                400
            )

        if sheet.max_column > 200:
            return (
                "一度に読み込めるExcelは200列までです。",
                400
            )

        header_names = {
            "納入先",
            "納入先名",
            "納入先名称",
            "配送先",
            "配送先名",
            "届け先",
            "届先",
            "得意先",
            "得意先名",
            "顧客名",
            "現場名",
        }

        def normalize_header(value):
            return (
                str(value or "")
                .strip()
                .replace(" ", "")
                .replace("　", "")
            )

        header_row = None
        delivery_column = None
        candidate_columns = []

        scan_end_row = min(sheet.max_row, 30)

        for row_number in range(1, scan_end_row + 1):

            row_candidates = []

            for column_number in range(
                1,
                sheet.max_column + 1
            ):
                cell_value = sheet.cell(
                    row=row_number,
                    column=column_number
                ).value

                normalized_value = normalize_header(
                    cell_value
                )

                if normalized_value in header_names:
                    row_candidates.append({
                        "column": column_number,
                        "header": str(cell_value).strip()
                    })

            if row_candidates:
                header_row = row_number
                candidate_columns = row_candidates

                if len(row_candidates) == 1:
                    delivery_column = row_candidates[0][
                        "column"
                    ]

                break

        if delivery_column:

            def normalize_delivery_name(value):
                return "".join(
                    str(value or "").split()
                ).casefold()

            existing_places = _dkss_models.DeliveryPlace.query.filter_by(
                company_code=_dkss_common.session.get("company_code")
            ).all()

            existing_names = {
                normalize_delivery_name(place.name)
                for place in existing_places
                if normalize_delivery_name(place.name)
            }

            delivery_places_data = []
            processed_names = set()

            for row_number in range(
                header_row + 1,
                sheet.max_row + 1
            ):
                cell_value = sheet.cell(
                    row=row_number,
                    column=delivery_column
                ).value

                place_name = str(
                    cell_value or ""
                ).strip()

                # 空欄は読み飛ばす
                if not place_name:
                    continue

                normalized_name = normalize_delivery_name(
                    place_name
                )

                if normalized_name in processed_names:
                    import_status = "Excel内重複"

                elif normalized_name in existing_names:
                    import_status = "登録済み"

                else:
                    import_status = "新規"

                processed_names.add(normalized_name)

                delivery_places_data.append({
                    "excel_row": row_number,
                    "name": place_name,
                    "import_status": import_status,
                })

            if not delivery_places_data:
                return (
                    "納入先として読み込めるデータが"
                    "見つかりませんでした。",
                    400
                )

            return _dkss_common.render_template(
                "delivery_place_import_preview.html",
                delivery_places=delivery_places_data,
            )

        # 自動判定できない場合は、ユーザーに列を選択してもらう
        selectable_columns = []

        for column_number in range(1, sheet.max_column + 1):

            sample_values = []

            for row_number in range(1, min(sheet.max_row, 5) + 1):

                value = sheet.cell(
                    row=row_number,
                    column=column_number
                ).value

                if value is not None and str(value).strip():
                    sample_values.append(str(value).strip())

            selectable_columns.append({
                "column": column_number,
                "samples": sample_values[:3],
            })

        sheet_rows = []

        for row in sheet.iter_rows(values_only=True):
            sheet_rows.append([
                "" if value is None else str(value)
                for value in row
            ])

        if candidate_columns:
            message = (
                "納入先と思われる列が複数見つかりました。"
                "使用する列を選択してください。"
            )
            start_row = (header_row or 0) + 1

        else:
            message = (
                "納入先の列を自動判定できませんでした。"
                "使用する列を選択してください。"
            )
            start_row = 1

        return _dkss_common.render_template(
            "delivery_place_import_column_select.html",
            columns=selectable_columns,
            rows_json=_dkss_common.json.dumps(
                sheet_rows,
                ensure_ascii=False
            ),
            start_row=start_row,
            message=message,
        )

    return _dkss_common.render_template(
        "delivery_place_import.html"
    )



def select_delivery_place_import_column():

    rows_json = _dkss_common.request.form.get("rows_json", "[]")
    delivery_column = _dkss_common.request.form.get(
        "delivery_column",
        type=int
    )
    start_row = _dkss_common.request.form.get(
        "start_row",
        1,
        type=int
    )

    if (
        not delivery_column
        or delivery_column < 1
        or delivery_column > 200
    ):
        return "納入先の列が不正です。", 400

    if (
        start_row < 1
        or start_row > 5000
    ):
        return "開始行が不正です。", 400

    try:
        sheet_rows = _dkss_common.json.loads(rows_json)
    except (TypeError, ValueError):
        return "Excelデータを読み込めませんでした。", 400

    if not isinstance(sheet_rows, list):
        return "Excelデータの形式が不正です。", 400

    if not all(
        isinstance(row, list)
        for row in sheet_rows
    ):
        return "Excelデータの形式が不正です。", 400

    if len(sheet_rows) > 5000:
        return (
            "一度に読み込めるExcelは5000行までです。",
            400
        )

    if any(
        len(row) > 200
        for row in sheet_rows
    ):
        return (
            "一度に読み込めるExcelは200列までです。",
            400
        )

    def normalize_delivery_name(value):
        return "".join(
            str(value or "").split()
        ).casefold()

    existing_places = _dkss_models.DeliveryPlace.query.filter_by(
        company_code=_dkss_common.session.get("company_code")
    ).all()

    existing_names = {
        normalize_delivery_name(place.name)
        for place in existing_places
        if normalize_delivery_name(place.name)
    }

    delivery_places_data = []
    processed_names = set()

    # HTML側は1列目、2列目…の1始まり
    column_index = delivery_column - 1

    # start_rowもExcel行番号の1始まり
    for row_number in range(
        start_row,
        len(sheet_rows) + 1
    ):

        row = sheet_rows[row_number - 1]

        if column_index >= len(row):
            continue

        place_name = str(
            row[column_index] or ""
        ).strip()

        # 空欄は読み飛ばす
        if not place_name:
            continue

        normalized_header = (
            place_name
            .replace(" ", "")
            .replace("　", "")
        )

        # 見出しそのものは納入先として取り込まない
        manual_header_names = {
            "納入先",
            "納入先名",
            "納入先名称",
            "配送先",
            "配送先名",
            "届け先",
            "届先",
            "得意先",
            "得意先名",
            "顧客名",
            "現場名",
        }

        if normalized_header in manual_header_names:
            continue

        # 「納入先一覧」のようなタイトル行も読み飛ばす
        if (
            "一覧" in normalized_header
            and any(
                word in normalized_header
                for word in [
                    "納入先",
                    "配送先",
                    "届け先",
                    "届先",
                    "得意先",
                    "顧客",
                    "現場",
                ]
            )
        ):
            continue
        normalized_name = normalize_delivery_name(
            place_name
        )

        if normalized_name in processed_names:
            import_status = "Excel内重複"

        elif normalized_name in existing_names:
            import_status = "登録済み"

        else:
            import_status = "新規"

        processed_names.add(normalized_name)

        delivery_places_data.append({
            "excel_row": row_number,
            "name": place_name,
            "import_status": import_status,
        })

    if not delivery_places_data:
        return (
            "選択した列に納入先として読み込める"
            "データがありませんでした。",
            400
        )

    return _dkss_common.render_template(
        "delivery_place_import_preview.html",
        delivery_places=delivery_places_data,
    )



def confirm_delivery_place_import():

    company_code = _dkss_common.session.get("company_code")

    submitted_names = _dkss_common.request.form.getlist(
        "delivery_place_name"
    )

    if len(submitted_names) > 5000:
        return (
            "一度に取り込める納入先は5000件までです。",
            400
        )

    def normalize_delivery_name(value):
        return "".join(
            str(value or "").split()
        ).casefold()

    existing_places = _dkss_models.DeliveryPlace.query.filter_by(
        company_code=company_code
    ).all()

    existing_names = {
        normalize_delivery_name(place.name)
        for place in existing_places
        if normalize_delivery_name(place.name)
    }

    processed_names = set()

    registered_count = 0
    existing_count = 0
    duplicate_count = 0

    for submitted_name in submitted_names:

        place_name = str(
            submitted_name or ""
        ).strip()

        if not place_name:
            continue

        if len(place_name) > 100:
            return (
                "納入先名は100文字以内で入力してください。",
                400
            )

        normalized_name = normalize_delivery_name(
            place_name
        )

        # 送信された一覧内で同じ納入先が重複している
        if normalized_name in processed_names:
            duplicate_count += 1
            continue

        processed_names.add(normalized_name)

        # データベースにすでに登録されている
        if normalized_name in existing_names:
            existing_count += 1
            continue

        place = _dkss_models.DeliveryPlace(
            company_code=company_code,
            name=place_name
        )

        _dkss_common.db.session.add(place)

        existing_names.add(normalized_name)
        registered_count += 1

    _dkss_common.db.session.commit()

    return _dkss_common.render_template(
        "delivery_place_import_complete.html",
        registered_count=registered_count,
        existing_count=existing_count,
        duplicate_count=duplicate_count,
    )



def delivery_place_master():
    return _dkss_common.render_template(
        "delivery_place_master.html",
        delivery_places=_dkss_master_readers.delivery_places_for_current_company()
    )



def new_delivery_place():
    if _dkss_common.request.method == "POST":

        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            return "納入先名を入力してください。", 400

        if len(name) > 100:
            return "納入先名は100文字以内で入力してください。", 400

        if _dkss_models.DeliveryPlace.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            name=name
        ).first():
            return "この納入先はすでに登録されています。", 409

        place = _dkss_models.DeliveryPlace(
            company_code=_dkss_common.session.get("company_code"),
            name=name
        )

        _dkss_common.db.session.add(place)
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/delivery-places")

    return _dkss_common.render_template(
        "delivery_place_form.html",
        place=None,
        index=None,
        mode="new"
    )



def edit_delivery_place(index):
    place = _dkss_models.DeliveryPlace.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not place:
        return _dkss_common.redirect("/master/delivery-places")

    if _dkss_common.request.method == "POST":
        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            return "納入先名を入力してください。", 400

        if len(name) > 100:
            return "納入先名は100文字以内で入力してください。", 400

        if name != place.name:
            duplicate_place = _dkss_models.DeliveryPlace.query.filter(
                _dkss_models.DeliveryPlace.company_code == place.company_code,
                _dkss_models.DeliveryPlace.name == name,
                _dkss_models.DeliveryPlace.id != place.id
            ).first()

            if duplicate_place:
                return "この納入先はすでに登録されています。", 409

            place_in_use = _dkss_models.PatrolResult.query.filter_by(
                company_code=place.company_code,
                delivery_place=place.name
            ).first()

            if place_in_use:
                return (
                    "安全パトロール履歴で使用されている納入先は変更できません。",
                    409
                )

        place.name = name
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/delivery-places")

    return _dkss_common.render_template(
        "delivery_place_form.html",
        place={
            "id": place.id,
            "index": place.id,
            "company_code": place.company_code,
            "name": place.name
        },
        index=place.id,
        mode="edit"
    )



def delete_delivery_place(index):
    place = _dkss_models.DeliveryPlace.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not place:
        return _dkss_common.redirect("/master/delivery-places")

    place_in_use = _dkss_models.PatrolResult.query.filter_by(
        company_code=place.company_code,
        delivery_place=place.name
    ).first()

    if place_in_use:
        return (
            "安全パトロール履歴で使用されている納入先は削除できません。",
            409
        )

    _dkss_audit.add_audit_log(
        action="delivery_place_deleted",
        target_type="delivery_place",
        target_id=place.id,
        detail=f"納入先削除: {place.name}",
        company_code=place.company_code,
    )

    _dkss_master_readers.remove_master_from_display_order("delivery-places", place)
    _dkss_common.db.session.delete(place)
    _dkss_common.db.session.commit()

    return _dkss_common.redirect("/master/delivery-places")



def patrol_content_type_master():
    return _dkss_common.render_template(
        "patrol_content_type_master.html",
        content_types=_dkss_master_readers.patrol_content_types_for_current_company()
    )



def new_patrol_content_type():
    if _dkss_common.request.method == "POST":

        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            return "内容区分名を入力してください。", 400

        if len(name) > 100:
            return "内容区分名は100文字以内で入力してください。", 400

        if _dkss_models.PatrolContentType.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            name=name
        ).first():
            return "この内容区分はすでに登録されています。", 409

        item = _dkss_models.PatrolContentType(
            company_code=_dkss_common.session.get("company_code"),
            name=name
        )

        _dkss_common.db.session.add(item)
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/patrol-content-types")

    return _dkss_common.render_template(
        "patrol_content_type_form.html",
        item=None,
        mode="new"
    )



def edit_patrol_content_type(index):
    item = _dkss_models.PatrolContentType.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not item:
        return _dkss_common.redirect("/master/patrol-content-types")

    if _dkss_common.request.method == "POST":
        name = _dkss_common.request.form.get("name", "").strip()

        if not name:
            return "内容区分名を入力してください。", 400

        if len(name) > 100:
            return "内容区分名は100文字以内で入力してください。", 400

        if name != item.name:
            duplicate_item = _dkss_models.PatrolContentType.query.filter(
                _dkss_models.PatrolContentType.company_code == item.company_code,
                _dkss_models.PatrolContentType.name == name,
                _dkss_models.PatrolContentType.id != item.id
            ).first()

            if duplicate_item:
                return "この内容区分はすでに登録されています。", 409

            item_in_use = _dkss_models.PatrolResult.query.filter_by(
                company_code=item.company_code,
                content_type=item.name
            ).first()

            if item_in_use:
                return (
                    "安全パトロール履歴で使用されている内容区分は変更できません。",
                    409
                )

        item.name = name
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/patrol-content-types")

    return _dkss_common.render_template(
        "patrol_content_type_form.html",
        item=item,
        mode="edit"
    )



def delete_patrol_content_type(index):
    item = _dkss_models.PatrolContentType.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not item:
        return _dkss_common.redirect("/master/patrol-content-types")

    item_in_use = _dkss_models.PatrolResult.query.filter_by(
        company_code=item.company_code,
        content_type=item.name
    ).first()

    if item_in_use:
        return (
            "安全パトロール履歴で使用されている内容区分は削除できません。",
            409
        )

    _dkss_audit.add_audit_log(
        action="patrol_content_type_deleted",
        target_type="patrol_content_type",
        target_id=item.id,
        detail=f"安全パトロール内容区分削除: {item.name}",
        company_code=item.company_code,
    )

    _dkss_master_readers.remove_master_from_display_order("patrol-content-types", item)
    _dkss_common.db.session.delete(item)
    _dkss_common.db.session.commit()
    return _dkss_common.redirect("/master/patrol-content-types")



def driver_master():
    keyword = _dkss_common.request.args.get("keyword", "").strip()
    office = _dkss_common.request.args.get("office", "").strip()
    vehicle = _dkss_common.request.args.get("vehicle", "").strip()

    if (
        len(keyword) > 100
        or len(office) > 100
        or len(vehicle) > 100
    ):
        return "検索条件が長すぎます。", 400

    if office:
        valid_office = _dkss_models.Office.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            name=office
        ).first()

        if not valid_office:
            return "営業所が不正です。", 400

    if vehicle:
        if not vehicle.isdigit():
            return "車両が不正です。", 400

        valid_vehicle = _dkss_models.Vehicle.query.filter_by(
            company_code=_dkss_common.session.get("company_code"),
            id=int(vehicle),
            deleted=False
        ).first()

        if not valid_vehicle:
            return "車両が不正です。", 400

    query = _dkss_models.Driver.query.filter(
        _dkss_models.Driver.company_code == _dkss_common.session.get("company_code")
    )

    if keyword:
        keyword_like = f"%{keyword}%"

        query = query.filter(
            _dkss_common.db.or_(
                _dkss_models.Driver.employee_id.ilike(keyword_like),
                _dkss_models.Driver.name.ilike(keyword_like)
            )
        )

    if office:
        query = query.filter(
            _dkss_models.Driver.office == office
        )

    if vehicle:
        query = query.filter(
            _dkss_models.Driver.vehicles_json.contains(f'"{vehicle}"')
        )

    driver_records = query.order_by(
        _dkss_models.Driver.id.asc()
    ).all()

    filtered_drivers = []

    for driver in driver_records:
        vehicle_record_ids = _dkss_serialization.safe_json_str_list(
            driver.vehicles_json
        )

        vehicle_records = _dkss_models.Vehicle.query.filter(
            _dkss_models.Vehicle.company_code == driver.company_code,
            _dkss_models.Vehicle.id.in_([
                int(vehicle_id)
                for vehicle_id in vehicle_record_ids
                if str(vehicle_id).isdigit()
            ])
        ).all()

        vehicle_map = {
            str(vehicle.id): vehicle
            for vehicle in vehicle_records
        }

        vehicle_labels = []

        for vehicle_id in vehicle_record_ids:
            vehicle_record = vehicle_map.get(
                str(vehicle_id)
            )

            if not vehicle_record:
                continue

            plate = " ".join(
                filter(
                    None,
                    [
                        vehicle_record.plate_area,
                        vehicle_record.plate_class,
                        vehicle_record.plate_kana,
                        vehicle_record.plate_number,
                    ]
                )
            )

            vehicle_labels.append(
                plate or "ナンバー未登録"
            )

        driver_item = {
            "index": driver.id,
            "id": driver.id,
            "company_code": driver.company_code,
            "employee_id": driver.employee_id,
            "username": driver.employee_id,
            "name": driver.name,
            "role": driver.role,
            "office": driver.office,
            "safe_start_date": driver.safe_start_date,
            "vehicles": vehicle_labels,
            "licenses": _dkss_serialization.safe_json_dict_list(
                driver.licenses_json
            ),
        }

        safe_start_date = driver.safe_start_date

        if safe_start_date:
            try:
                start_date = _dkss_common.datetime.strptime(
                    safe_start_date,
                    "%Y-%m-%d"
                )
                days = (
                    _dkss_common.datetime.today() - start_date
                ).days
            except ValueError:
                days = 0
        else:
            days = 0

        years = days // 365
        remaining_days = days % 365

        driver_item["safe_days_display"] = (
            f"{years}年{remaining_days}日継続中"
            if years > 0
            else f"{days}日継続中"
        )

        filtered_drivers.append(driver_item)

    return _dkss_common.render_template(
        "driver_master.html",
        drivers=filtered_drivers,
        offices=_dkss_master_readers.offices_for_current_company(),
        keyword=keyword,
        office=office,
        vehicle=vehicle,
    )



def new_driver():
    company_code = _dkss_common.session.get("company_code")

    if _dkss_common.request.method == "POST":
        form_errors = []

        employee_id = _dkss_common.request.form.get(
            "employee_id",
            ""
        ).strip()

        last_name = _dkss_common.request.form.get(
            "last_name",
            ""
        ).strip()

        first_name = _dkss_common.request.form.get(
            "first_name",
            ""
        ).strip()

        name = last_name + first_name

        email_address = _dkss_common.request.form.get(
            "email_address",
            ""
        ).strip().lower()

        password = _dkss_common.request.form.get(
            "password",
            ""
        )

        password_type_count = sum([
            any(c.islower() for c in password or ""),
            any(c.isupper() for c in password or ""),
            any(c.isdigit() for c in password or ""),
            any(
                not c.isalnum()
                for c in password or ""
            ),
        ])

        role = _dkss_common.request.form.get(
            "role",
            "user"
        ).strip()

        office = _dkss_common.request.form.get(
            "office",
            ""
        ).strip()

        safe_start_date = _dkss_common.request.form.get(
            "safe_start_date",
            ""
        ).strip()

        selected_vehicles = _dkss_common.request.form.getlist(
            "vehicles"
        )

        if len(selected_vehicles) > 1000:
            form_errors.append((
                "選択車両数が多すぎます。",
                "selected_vehicles"
            ))

        # 基本入力チェック

        if not employee_id:
            form_errors.append((
                "ログインIDを入力してください。",
                "employee_id"
            ))
        elif len(employee_id) > 50:
            form_errors.append((
                "ログインIDは50文字以内で入力してください。",
                "employee_id"
            ))

        if not last_name:
            form_errors.append((
                "姓を入力してください。",
                "last_name"
            ))
        elif len(last_name) > 100:
            form_errors.append((
                "姓は100文字以内で入力してください。",
                "last_name"
            ))

        if len(first_name) > 100:
            form_errors.append((
                "名は100文字以内で入力してください。",
                "first_name"
            ))

        if email_address and not _dkss_auth.is_valid_email_address(
            email_address
        ):
            form_errors.append((
                "メールアドレスの形式が不正です。",
                "email_address"
            ))

        if not password:
            form_errors.append((
                "パスワードを入力してください。",
                "password"
            ))
        elif len(password) < 8:
            form_errors.append((
                "パスワードは8文字以上にしてください。",
                "password"
            ))
        elif len(password) > 128:
            form_errors.append((
                "パスワードは128文字以内にしてください。",
                "password"
            ))
        elif password_type_count < 3:
            form_errors.append((
                "パスワードは英大文字・英小文字・数字・記号の"
                "うち3種類以上を使用してください。",
                "password"
            ))

        # ロール検証

        if role not in ["admin", "user"]:
            form_errors.append((
                "ユーザー種別が不正です。",
                "role"
            ))
        if safe_start_date:
            try:
                _dkss_common.datetime.strptime(
                    safe_start_date,
                    "%Y-%m-%d"
                )
            except ValueError:
                form_errors.append((
                    "無事故開始日が不正です。",
                    "safe_start_date"
                ))

        # ログインID重複確認

        if _dkss_models.User.query.filter_by(
            company_code=company_code,
            username=employee_id
        ).first():
            form_errors.append((
                "このログインIDはすでに使用されています。",
                "employee_id"
            ))

        # 営業所検証

        if office:
            valid_office = _dkss_models.Office.query.filter_by(
                company_code=company_code,
                name=office
            ).first()

            if not valid_office:
                form_errors.append((
                    "営業所が不正です。",
                    "office"
                ))

        # 車両検証

        valid_vehicle_record_ids = {
            str(vehicle.id)
            for vehicle in _dkss_models.Vehicle.query.filter_by(
                company_code=company_code,
                deleted=False
            ).all()
        }

        for vehicle_record_id in selected_vehicles:
            if vehicle_record_id not in valid_vehicle_record_ids:
                form_errors.append((
                    "選択された車両が不正です。",
                    "selected_vehicles"
                ))
                break

        # 免許種別検証

        valid_license_types = {
            item.name
            for item in _dkss_models.LicenseType.query.filter_by(
                company_code=company_code
            ).all()
        }

        licenses = []

        license_types = _dkss_common.request.form.getlist(
            "license_type"
        )

        license_expiries = _dkss_common.request.form.getlist(
            "license_expiry"
        )

        if (
            len(license_types) > 100
            or len(license_expiries) > 100
        ):
            form_errors.append((
                "免許情報の件数が多すぎます。",
                "license_area"
            ))

        for license_type, expiry in zip(
            license_types,
            license_expiries
        ):
            license_type = (
                license_type or ""
            ).strip()

            expiry = (
                expiry or ""
            ).strip()

            if not license_type:
                continue

            license_has_error = False

            if license_type not in valid_license_types:
                form_errors.append((
                    "免許種別が不正です。",
                    "license_area"
                ))
                license_has_error = True

            if expiry:
                try:
                    _dkss_common.datetime.strptime(
                        expiry,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    form_errors.append((
                        "免許有効期限が不正です。",
                        "license_area"
                    ))
                    license_has_error = True

            if not license_has_error:
                licenses.append({
                    "type": license_type,
                    "expiry": expiry
                })

        if form_errors:
            return _dkss_http.return_form_errors(form_errors)

        # Driver作成

        driver = _dkss_models.Driver(
            company_code=company_code,
            employee_id=employee_id,
            name=(last_name or "") + (first_name or ""),
            role=role,
            office=office,
            safe_start_date=safe_start_date,
            vehicles_json=_dkss_common.json.dumps(
                selected_vehicles,
                ensure_ascii=False
            ),
            licenses_json=_dkss_common.json.dumps(
                licenses,
                ensure_ascii=False
            )
        )

        # User作成

        user = _dkss_models.User(
            company_code=company_code,
            username=employee_id,
            password=_dkss_common.generate_password_hash(
                password
            ),
            password_changed_at=_dkss_common.datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            role=role,
            last_name=last_name,
            first_name=first_name or None,
            office=office,
            email_address=email_address or None,
            email_notify_enabled=bool(email_address)
        )

        _dkss_common.db.session.add(user)
        _dkss_common.db.session.add(driver)
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/drivers")

    driver_form_data = _dkss_common.session.pop(
        "driver_form_data",
        {}
    )

    form_driver = None

    if driver_form_data:
        form_driver = {
            "employee_id": driver_form_data.get(
                "employee_id",
                ""
            ),
            "last_name": driver_form_data.get(
                "last_name",
                ""
            ),
            "first_name": driver_form_data.get(
                "first_name",
                ""
            ),
            "name": (
                driver_form_data.get("last_name", "")
                + driver_form_data.get("first_name", "")
            ),
            "email_address": driver_form_data.get(
                "email_address",
                ""
            ),
            "role": driver_form_data.get(
                "role",
                "user"
            ),
            "office": driver_form_data.get(
                "office",
                ""
            ),
            "safe_start_date": driver_form_data.get(
                "safe_start_date",
                ""
            ),
            "licenses": [
                {
                    "type": license_type,
                    "expiry": expiry
                }
                for license_type, expiry in zip(
                    driver_form_data.get(
                        "license_type",
                        []
                    ),
                    driver_form_data.get(
                        "license_expiry",
                        []
                    )
                )
            ],
        }

    selected_vehicles = []

    selected_vehicle_record_ids = [
        int(vehicle_record_id)
        for vehicle_record_id in driver_form_data.get(
            "vehicles",
            []
        )
        if str(vehicle_record_id).isdigit()
    ]

    if selected_vehicle_record_ids:
        selected_vehicle_records = _dkss_models.Vehicle.query.filter(
            _dkss_models.Vehicle.company_code == company_code,
            _dkss_models.Vehicle.id.in_(selected_vehicle_record_ids),
            _dkss_models.Vehicle.deleted == False
        ).all()

        for vehicle in selected_vehicle_records:
            number = " ".join(
                value
                for value in [
                    vehicle.plate_area or "",
                    vehicle.plate_class or "",
                    vehicle.plate_kana or "",
                    vehicle.plate_number or "",
                ]
                if value
            )

            selected_vehicles.append({
                "vehicle_record_id": vehicle.id,
                "chassis_number": vehicle.chassis_number,
                "number": number,
                "type": vehicle.type or "",
            })

    return _dkss_common.render_template(
        "driver_form.html",
        driver=form_driver,
        offices=_dkss_master_readers.offices_for_current_company(),
        selected_vehicles=selected_vehicles,
        license_types=_dkss_vehicle_readers.license_types_for_current_company(),
        mode="new"
    )



def edit_driver(index):
    driver = _dkss_models.Driver.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not driver:
        return _dkss_common.redirect("/master/drivers")

    if _dkss_common.request.method == "POST":
        form_errors = []

        company_code = driver.company_code

        old_employee_id = driver.employee_id

        new_employee_id = _dkss_common.request.form.get(
            "employee_id",
            ""
        ).strip()

        last_name = _dkss_common.request.form.get(
            "last_name",
            ""
        ).strip()

        first_name = _dkss_common.request.form.get(
            "first_name",
            ""
        ).strip()

        name = last_name + first_name

        email_address = _dkss_common.request.form.get(
            "email_address",
            ""
        ).strip().lower()

        role = _dkss_common.request.form.get(
            "role",
            "user"
        ).strip()

        existing_user = _dkss_models.User.query.filter_by(
            company_code=company_code,
            username=old_employee_id
        ).first()

        if existing_user and existing_user.role == "itc":
            role = "itc"

        office = _dkss_common.request.form.get(
            "office",
            ""
        ).strip()

        safe_start_date = _dkss_common.request.form.get(
            "safe_start_date",
            ""
        ).strip()

        new_password = _dkss_common.request.form.get(
            "password",
            ""
        )

        password_type_count = sum([
            any(c.islower() for c in new_password or ""),
            any(c.isupper() for c in new_password or ""),
            any(c.isdigit() for c in new_password or ""),
            any(
                not c.isalnum()
                for c in new_password or ""
            ),
        ])

        selected_vehicles = _dkss_common.request.form.getlist(
            "vehicles"
        )

        if len(selected_vehicles) > 1000:
            form_errors.append((
                "選択車両数が多すぎます。",
                "selected_vehicles"
            ))

        # 基本入力チェック

        if not new_employee_id:
            form_errors.append((
                "ログインIDを入力してください。",
                "employee_id"
            ))
        elif len(new_employee_id) > 50:
            form_errors.append((
                "ログインIDは50文字以内で入力してください。",
                "employee_id"
            ))
        elif new_employee_id != old_employee_id:
            form_errors.append((
                "ログインIDは作成後に変更できません。",
                "employee_id"
            ))

        if not last_name:
            form_errors.append((
                "姓を入力してください。",
                "last_name"
            ))
        elif len(last_name) > 100:
            form_errors.append((
                "姓は100文字以内で入力してください。",
                "last_name"
            ))

        if len(first_name) > 100:
            form_errors.append((
                "名は100文字以内で入力してください。",
                "first_name"
            ))

        if email_address and not _dkss_auth.is_valid_email_address(
            email_address
        ):
            form_errors.append((
                "メールアドレスの形式が不正です。",
                "email_address"
            ))

        if new_password:
            if len(new_password) < 8:
                form_errors.append((
                    "パスワードは8文字以上にしてください。",
                    "password"
                ))
            elif len(new_password) > 128:
                form_errors.append((
                    "パスワードは128文字以内にしてください。",
                    "password"
                ))
            elif password_type_count < 3:
                form_errors.append((
                    "パスワードは英大文字・英小文字・数字・記号の"
                    "うち3種類以上を使用してください。",
                    "password"
                ))

        # ロール検証

        if role not in ["admin", "user", "itc"]:
            form_errors.append((
                "ユーザー種別が不正です。",
                "role"
            ))
        if safe_start_date:
            try:
                _dkss_common.datetime.strptime(
                    safe_start_date,
                    "%Y-%m-%d"
                )
            except ValueError:
                form_errors.append((
                    "無事故開始日が不正です。",
                    "safe_start_date"
                ))

        # ログインID重複確認

        if new_employee_id != old_employee_id:
            existing_user = _dkss_models.User.query.filter_by(
                company_code=company_code,
                username=new_employee_id
            ).first()

            if existing_user:
                form_errors.append((
                    "このログインIDはすでに使用されています。",
                    "employee_id"
                ))

        # 営業所検証

        if office:
            valid_office = _dkss_models.Office.query.filter_by(
                company_code=company_code,
                name=office
            ).first()

            if not valid_office:
                form_errors.append((
                    "営業所が不正です。",
                    "office"
                ))

        # 車両検証

        valid_vehicle_record_ids = {
            str(vehicle.id)
            for vehicle in _dkss_models.Vehicle.query.filter_by(
                company_code=company_code,
                deleted=False
            ).all()
        }

        for vehicle_record_id in selected_vehicles:
            if vehicle_record_id not in valid_vehicle_record_ids:
                form_errors.append((
                    "選択された車両が不正です。",
                    "selected_vehicles"
                ))
                break

        # 免許種別検証

        valid_license_types = {
            item.name
            for item in _dkss_models.LicenseType.query.filter_by(
                company_code=company_code
            ).all()
        }

        licenses = []

        license_types = _dkss_common.request.form.getlist(
            "license_type"
        )

        license_expiries = _dkss_common.request.form.getlist(
            "license_expiry"
        )

        if (
            len(license_types) > 100
            or len(license_expiries) > 100
        ):
            form_errors.append((
                "免許情報の件数が多すぎます。",
                "license_area"
            ))

        for license_type, expiry in zip(
            license_types,
            license_expiries
        ):
            license_type = (
                license_type or ""
            ).strip()

            expiry = (
                expiry or ""
            ).strip()

            if not license_type:
                continue

            license_has_error = False

            if license_type not in valid_license_types:
                form_errors.append((
                    "免許種別が不正です。",
                    "license_area"
                ))
                license_has_error = True

            if expiry:
                try:
                    _dkss_common.datetime.strptime(
                        expiry,
                        "%Y-%m-%d"
                    )
                except ValueError:
                    form_errors.append((
                        "免許有効期限が不正です。",
                        "license_area"
                    ))
                    license_has_error = True

            if not license_has_error:
                licenses.append({
                    "type": license_type,
                    "expiry": expiry
                })

        if form_errors:
            return _dkss_http.return_form_errors(form_errors)

        # User取得

        user = _dkss_models.User.query.filter_by(
            company_code=company_code,
            username=old_employee_id
        ).first()

        # Userが消えている異常状態なら
        # 固定パスワードを勝手に作らない
        if not user:
            if not new_password:
                return _dkss_http.return_form_errors([
                    "ユーザー情報が見つかりません。"
                    "再作成するためパスワードを入力してください。"
                ])

            user = _dkss_models.User(
                company_code=company_code,
                username=new_employee_id,
                password=_dkss_common.generate_password_hash(
                    new_password
                ),
                password_changed_at=_dkss_common.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                role=role,
                last_name=last_name,
                first_name=first_name or None,
                office=office,
                email_address=email_address or None,
                email_notify_enabled=bool(email_address),

            )

            _dkss_common.db.session.add(user)

        else:
            if new_password:
                password_history = _dkss_auth.parse_password_history(
                    user.password_history_json
                )

                if password_history is None:
                    return (
                        "パスワード履歴データが不正です。",
                        500
                    )

                reused_password = (
                    _dkss_common.check_password_hash(
                        user.password,
                        new_password
                    )
                    or any(
                        _dkss_common.check_password_hash(
                            old_password_hash,
                            new_password
                        )
                        for old_password_hash in password_history[-5:]
                    )
                )

                if reused_password:
                    return _dkss_http.return_form_errors([
                        (
                            "現在または過去5回以内に使用した"
                            "パスワードは使用できません。",
                            "password"
                        )
                    ])

                password_history.append(
                    user.password
                )

                user.password_history_json = _dkss_common.json.dumps(
                    password_history[-5:]
                )

                user.password = _dkss_common.generate_password_hash(
                    new_password
                )

                user.password_changed_at = (
                    _dkss_common.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )

                user.failed_login_count = 0
                user.login_locked = False

                _dkss_audit.add_audit_log(
                    action="admin_password_reset",
                    target_type="user",
                    target_id=user.username,
                    detail="管理者によるパスワード変更・アカウントロック解除",
                    company_code=user.company_code,
                )

            user.username = new_employee_id
            user.role = role
            user.last_name = last_name
            user.first_name = first_name or None
            user.office = office
            user.email_address = email_address or None
            user.email_notify_enabled = bool(email_address)

        # Driver更新

        driver.employee_id = new_employee_id
        driver.name = (last_name or "") + (first_name or "")
        driver.role = role
        driver.office = office
        driver.safe_start_date = safe_start_date
        driver.vehicles_json = _dkss_common.json.dumps(
            selected_vehicles,
            ensure_ascii=False
        )
        driver.licenses_json = _dkss_common.json.dumps(
            licenses,
            ensure_ascii=False
        )

        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/drivers")

    driver_dict = _dkss_vehicle_readers.driver_to_dict(driver)

    user = _dkss_models.User.query.filter_by(
        company_code=driver.company_code,
        username=driver.employee_id
    ).first()

    driver_dict["last_name"] = (
        user.last_name if user else ""
    )
    driver_dict["first_name"] = (
        user.first_name if user else ""
    )

    driver_edit_form_data = _dkss_common.session.pop(
        "driver_edit_form_data",
        {}
    )

    if driver_edit_form_data:
        driver_dict.update({
            "employee_id": driver_edit_form_data.get(
                "employee_id",
                driver_dict["employee_id"]
            ),
            "last_name": driver_edit_form_data.get(
                "last_name",
                driver_dict.get("last_name", "")
            ),
            "first_name": driver_edit_form_data.get(
                "first_name",
                driver_dict.get("first_name", "")
            ),
            "name": (
                driver_edit_form_data.get("last_name", "")
                + driver_edit_form_data.get("first_name", "")
            ) or driver_dict["name"],
            "email_address": driver_edit_form_data.get(
                "email_address",
                driver_dict["email_address"]
            ),
            "role": driver_edit_form_data.get(
                "role",
                driver_dict["role"]
            ),
            "office": driver_edit_form_data.get(
                "office",
                driver_dict["office"]
            ),
            "safe_start_date": driver_edit_form_data.get(
                "safe_start_date",
                driver_dict["safe_start_date"]
            ),
            "vehicles": driver_edit_form_data.get(
                "vehicles",
                driver_dict["vehicles"]
            ),
            "licenses": [
                {
                    "type": license_type,
                    "expiry": expiry
                }
                for license_type, expiry in zip(
                    driver_edit_form_data.get(
                        "license_type",
                        []
                    ),
                    driver_edit_form_data.get(
                        "license_expiry",
                        []
                    )
                )
            ],
        })


    selected_vehicle_records = []

    if driver_edit_form_data:
        driver_dict["vehicles"] = driver_edit_form_data.get(
            "vehicles",
            driver_dict["vehicles"]
        )

    if driver_dict["vehicles"]:

        selected_vehicle_record_ids = [
            int(vehicle_record_id)
            for vehicle_record_id in driver_dict["vehicles"]
            if str(vehicle_record_id).isdigit()
        ]

        selected_vehicle_records = _dkss_models.Vehicle.query.filter(
            _dkss_models.Vehicle.company_code == driver.company_code,
            _dkss_models.Vehicle.id.in_(selected_vehicle_record_ids),
            _dkss_models.Vehicle.deleted == False
        ).all()


    selected_vehicles = []

    for vehicle in selected_vehicle_records:

        number = " ".join(
            value
            for value in [
                vehicle.plate_area or "",
                vehicle.plate_class or "",
                vehicle.plate_kana or "",
                vehicle.plate_number or "",
            ]
            if value
        )

        selected_vehicles.append({
            "vehicle_record_id": vehicle.id,
            "chassis_number": vehicle.chassis_number,
            "number": number,
            "type": vehicle.type or "",
        })


    return _dkss_common.render_template(
        "driver_form.html",
        driver=driver_dict,
        index=driver.id,
        offices=_dkss_master_readers.offices_for_current_company(),
        selected_vehicles=selected_vehicles,
        license_types=_dkss_vehicle_readers.license_types_for_current_company(),
        mode="edit"
    )



def delete_driver(index):
    driver = _dkss_models.Driver.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not driver:
        return _dkss_common.redirect("/master/drivers")

    username = driver.employee_id

    approved_checklist_result = _dkss_models.ChecklistResult.query.filter(
        _dkss_models.ChecklistResult.company_code == driver.company_code,
        _dkss_models.ChecklistResult.status == "承認済み",
        _dkss_common.db.or_(
            _dkss_models.ChecklistResult.checked_by_username == username,
            _dkss_models.ChecklistResult.approved_by_username == username,
            _dkss_models.ChecklistResult.target_username == username
        )
    ).first()

    approved_vehicle_result = _dkss_models.VehicleChecklistResult.query.filter(
        _dkss_models.VehicleChecklistResult.company_code == driver.company_code,
        _dkss_models.VehicleChecklistResult.status == "承認済み",
        _dkss_common.db.or_(
            _dkss_models.VehicleChecklistResult.checked_by_username == username,
            _dkss_models.VehicleChecklistResult.approved_by_username == username
        )
    ).first()

    approved_patrol_result = _dkss_models.PatrolResult.query.filter(
        _dkss_models.PatrolResult.company_code == driver.company_code,
        _dkss_models.PatrolResult.approval_status == "承認済み",
        _dkss_common.db.or_(
            _dkss_models.PatrolResult.created_by_username == username,
            _dkss_models.PatrolResult.target_username == username,
            _dkss_models.PatrolResult.countermeasure_by_username == username
        )
    ).first()

    active_checklist_result = _dkss_models.ChecklistResult.query.filter(
        _dkss_models.ChecklistResult.company_code == driver.company_code,
        _dkss_models.ChecklistResult.status != "承認済み",
        _dkss_common.db.or_(
            _dkss_models.ChecklistResult.checked_by_username == username,
            _dkss_models.ChecklistResult.target_username == username
        )
    ).first()

    active_vehicle_result = _dkss_models.VehicleChecklistResult.query.filter(
        _dkss_models.VehicleChecklistResult.company_code == driver.company_code,
        _dkss_models.VehicleChecklistResult.status != "承認済み",
        _dkss_models.VehicleChecklistResult.checked_by_username == username
    ).first()

    active_patrol_result = _dkss_models.PatrolResult.query.filter(
        _dkss_models.PatrolResult.company_code == driver.company_code,
        _dkss_models.PatrolResult.approval_status != "承認済み",
        _dkss_common.db.or_(
            _dkss_models.PatrolResult.created_by_username == username,
            _dkss_models.PatrolResult.target_username == username,
            _dkss_models.PatrolResult.countermeasure_by_username == username
        )
    ).first()

    if (
        active_checklist_result
        or active_vehicle_result
        or active_patrol_result
    ):
        return (
            "進行中の点検・安全パトロールに関係する"
            "ドライバーは削除できません。",
            409
        )

    approved_step_result = False

    approved_checklist_results = _dkss_models.ChecklistResult.query.filter_by(
        company_code=driver.company_code,
        status="承認済み"
    ).all()

    for result in approved_checklist_results:
        approvals = _dkss_serialization.safe_json_dict_list(
            result.approvals_json
        )

        if any(
            approval.get("approved_by_username") == username
            for approval in approvals
        ):
            approved_step_result = True
            break

    if not approved_step_result:
        approved_vehicle_results = _dkss_models.VehicleChecklistResult.query.filter_by(
            company_code=driver.company_code,
            status="承認済み"
        ).all()

        for result in approved_vehicle_results:
            approvals = _dkss_serialization.safe_json_dict_list(
                result.approvals_json
            )

            if any(
                approval.get("approved_by_username") == username
                for approval in approvals
            ):
                approved_step_result = True
                break

    if (
        approved_checklist_result
        or approved_vehicle_result
        or approved_patrol_result
        or approved_step_result
    ):
        return (
            "承認済みの履歴に関係するドライバーは削除できません。",
            409
        )

    notify_settings = _dkss_models.VehicleChecklistNotifySetting.query.filter_by(
        company_code=driver.company_code
    ).all()

    for setting in notify_settings:
        notify_usernames = _dkss_serialization.safe_json_str_list(
            setting.notify_users_json
        )

        if username in notify_usernames:
            notify_usernames = [
                item
                for item in notify_usernames
                if item != username
            ]

            setting.notify_users_json = _dkss_common.json.dumps(
                notify_usernames,
                ensure_ascii=False
            )

    user = _dkss_models.User.query.filter_by(
        company_code=driver.company_code,
        username=username
    ).first()

    if user:
        _dkss_common.db.session.delete(user)

    _dkss_audit.add_audit_log(
        action="driver_deleted",
        target_type="driver",
        target_id=driver.employee_id,
        detail=f"ドライバー削除: {driver.name}",
        company_code=driver.company_code,
    )

    _dkss_common.db.session.delete(driver)
    _dkss_common.db.session.commit()
    return _dkss_common.redirect("/master/drivers")



def manual_master():
    return _dkss_common.render_template(
        "manual_master.html",
        manuals=_dkss_master_readers.manuals_for_current_company()
    )



def new_manual():
    if _dkss_common.request.method == "POST":
        title = _dkss_common.request.form.get("title", "").strip()
        category = _dkss_common.request.form.get("category", "").strip()

        if not title:
            return "タイトルを入力してください。", 400

        if len(title) > 200:
            return "タイトルは200文字以内で入力してください。", 400

        if len(category) > 100:
            return "カテゴリは100文字以内で入力してください。", 400

        file = _dkss_common.request.files.get("file")

        filename = _dkss_storage.save_uploaded_file(
            file,
            folder="static/manuals"
        )

        manual = _dkss_models.Manual(
            company_code=_dkss_common.session.get("company_code"),
            title=title,
            category=category,
            filename=filename
        )

        _dkss_common.db.session.add(manual)
        _dkss_common.db.session.commit()

        return _dkss_common.redirect("/master/manuals")

    return _dkss_common.render_template(
        "manual_form.html",
        manual=None,
        index=None,
        mode="new"
    )



def edit_manual(index):
    manual = _dkss_models.Manual.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not manual:
        return _dkss_common.redirect("/master/manuals")

    if _dkss_common.request.method == "POST":
        title = _dkss_common.request.form.get("title", "").strip()
        category = _dkss_common.request.form.get("category", "").strip()

        if not title:
            return "タイトルを入力してください。", 400

        if len(title) > 200:
            return "タイトルは200文字以内で入力してください。", 400

        if len(category) > 100:
            return "カテゴリは100文字以内で入力してください。", 400

        manual.title = title
        manual.category = category

        old_filename = _dkss_common.os.path.basename(
            str(manual.filename or "")
        )

        file = _dkss_common.request.files.get("file")
        filename = _dkss_storage.save_uploaded_file(
            file,
            folder="static/manuals"
        )

        if filename:
            manual.filename = filename

        _dkss_common.db.session.commit()

        if (
            filename
            and old_filename
            and old_filename != filename
        ):
            if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
                try:
                    _dkss_runtime.app.extensions["dkss"]['s3_client'].delete_object(
                        Bucket=_dkss_runtime.app.config['S3_BUCKET_NAME'],
                        Key=(
                            f"manuals/"
                            f"{manual.company_code}/"
                            f"{old_filename}"
                        )
                    )
                except _dkss_common.ClientError:
                    _dkss_runtime.app.logger.warning(
                        "旧マニュアルファイルのS3削除に失敗しました。",
                        exc_info=True
                    )
            else:
                safe_filename = _dkss_common.secure_filename(
                    old_filename
                )

                if safe_filename:
                    file_path = _dkss_common.os.path.join(
                        "static/manuals",
                        manual.company_code,
                        safe_filename
                    )

                    if _dkss_common.os.path.exists(file_path):
                        _dkss_common.os.remove(file_path)

        return _dkss_common.redirect("/master/manuals")

    manual_dict = {
        "id": manual.id,
        "index": manual.id,
        "company_code": manual.company_code,
        "title": manual.title,
        "category": manual.category,
        "filename": manual.filename,
    }

    return _dkss_common.render_template(
        "manual_form.html",
        manual=manual_dict,
        index=manual.id,
        mode="edit"
    )



def delete_manual(index):
    manual = _dkss_models.Manual.query.filter_by(
        id=index,
        company_code=_dkss_common.session.get("company_code")
    ).first()

    if not manual:
        return _dkss_common.redirect("/master/manuals")

    _dkss_audit.add_audit_log(
        action="manual_deleted",
        target_type="manual",
        target_id=manual.id,
        detail=f"マニュアル削除: {manual.title}",
        company_code=manual.company_code,
    )

    filename = _dkss_common.os.path.basename(
        str(manual.filename or "")
    )

    company_code = manual.company_code

    _dkss_master_readers.remove_master_from_display_order("manuals", manual)
    _dkss_common.db.session.delete(manual)
    _dkss_common.db.session.commit()

    if filename:
        if _dkss_runtime.app.extensions["dkss"]['s3_client'] and _dkss_runtime.app.config['S3_BUCKET_NAME']:
            try:
                _dkss_runtime.app.extensions["dkss"]['s3_client'].delete_object(
                    Bucket=_dkss_runtime.app.config['S3_BUCKET_NAME'],
                    Key=(
                        f"manuals/"
                        f"{company_code}/"
                        f"{filename}"
                    )
                )
            except _dkss_common.ClientError:
                _dkss_runtime.app.logger.warning(
                    "マニュアルファイルのS3削除に失敗しました。",
                    exc_info=True
                )
        else:
            safe_filename = _dkss_common.secure_filename(
                filename
            )

            if safe_filename:
                file_path = _dkss_common.os.path.join(
                    "static/manuals",
                    company_code,
                    safe_filename
                )

                if _dkss_common.os.path.exists(file_path):
                    _dkss_common.os.remove(file_path)

    return _dkss_common.redirect("/master/manuals")
